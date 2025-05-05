import argparse
import datetime as _dt
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple, Dict, Any
import textwrap
import tempfile
import yaml
from textwrap import dedent

def load_patches(patch_path: Path) -> List[Tuple[Dict[str, Any], str]]:
    """
    Load one or more VibeSpec patches from a .vibe file.
    Returns a list of (metadata_dict, code_str) tuples.
    Splits metadata at the next 'patch_type:' or '--- code:' marker.
    """
    text = patch_path.read_text()
    lines = text.splitlines()
    patches: List[Tuple[Dict[str, Any], str]] = []
    i = 0
    current_version: Optional[str] = None

    while i < len(lines):
        # Skip blank lines
        if not lines[i].strip():
            i += 1
            continue

        # Capture spec header
        m = re.match(r'^#\s*VibeSpec:\s*(\d+\.\d+)', lines[i])
        if m:
            current_version = m.group(1)
            i += 1
            continue

        # Begin a new patch
        # 1) Gather metadata lines until we see either '--- code:' or another 'patch_type:'
        meta_lines: List[str] = []
        # Expect at least one 'patch_type:' line
        if lines[i].startswith("patch_type:"):
            meta_lines.append(lines[i])
            i += 1
        else:
            # skip until a patch_type
            while i < len(lines) and not lines[i].startswith("patch_type:"):
                i += 1
            if i < len(lines):
                meta_lines.append(lines[i])
                i += 1

        # Now keep absorbing metadata until a code block or the next patch_type
        while i < len(lines) and not lines[i].startswith("--- code:") and not lines[i].startswith("patch_type:") and lines[i].strip():
            meta_lines.append(lines[i])
            i += 1

        # Parse metadata
        meta: Dict[str, Any] = yaml.safe_load("\n".join(meta_lines)) or {}
        if current_version:
            meta["VibeSpec"] = current_version

        # 2) If there's a code block, read it
        code = ""
        if i < len(lines) and lines[i].startswith("--- code:"):
            i += 1
            code_lines: List[str] = []
            # literal lines are either indented or blank
            while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
                code_lines.append(lines[i])
                i += 1
            code = dedent("\n".join(code_lines)).rstrip("\n")

        patches.append((meta, code))

    return patches

def apply_patches(patches: List[Tuple[Dict[str, Any], str]], repo: Path, dry: bool=False):
    """
    Apply each (meta, code) in sequence.
    """
    for meta, code in patches:
        validate_spec(meta)
        apply_patch(meta, code, repo, dry=dry)

# =============================================================================
#  Utility helpers
# =============================================================================

def _log(msg: str, *args: Any) -> None:
    print(msg.format(*args), file=sys.stderr)


def _timestamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")

# =============================================================================
#  Patch parsing
# =============================================================================

def _clean_meta(line: str) -> str:
    line = line.lstrip()
    return line[1:].lstrip() if line.startswith("#") else line


def load_patch(path: Path) -> Tuple[Dict[str, Any], str]:
    """
    Parse a .vibe patch file; collect keys (VibeSpec, patch_type, file,
    class, position, anchor, etc.) into meta, and everything after
    `--- code` into a literal block.
    """
    meta: Dict[str, Any] = {}
    code_lines: list[str] = []
    in_code = False

    for raw in path.read_text().splitlines():
        if raw.startswith("--- code"):
            in_code = True
            continue

        if in_code:
            code_lines.append(raw)
        else:
            ln = raw.lstrip()
            if ln.startswith("#"):
                ln = ln[1:].lstrip()
            if ":" in ln:
                k, v = ln.split(":", 1)
                v = v.strip()
                # strip matching surrounding quotes
                if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
                    v = v[1:-1]
                meta[k.strip()] = v

    return meta, "\n".join(code_lines)

    def validate_spec(meta: Dict[str, Any]) -> None:
        """
        Ensure the patch metadata is well‑formed and supported.
        Raises ValueError on any problem.
        """
        required = {"VibeSpec", "patch_type", "file"}
        missing  = required - set(meta.keys())
        if missing:
            raise ValueError(f"Missing meta keys: {sorted(missing)}")

        # Allow v1.0, v1.2, v1.3, v1.4, v1.5 and now v1.6
        vs = meta["VibeSpec"]
        if vs not in ("1.0", "1.2", "1.3", "1.4", "1.5", "1.6"):
            raise ValueError(f"Unsupported VibeSpec version: '{vs}'")
        
        pt = meta["patch_type"]
        allowed = {
            "add_function", "add_method", "add_class", "add_block", "replace_block",
            "remove_function", "remove_method", "remove_class", "remove_block"
        }
        if pt not in allowed:
            raise ValueError(f"Unsupported patch_type: {pt}")

        # class key required for method patches
        if pt in ("add_method", "remove_method") and not meta.get("class"):
            raise ValueError("`class` key required for method patches")

        # name key required for named removals
        if pt in ("remove_function", "remove_method", "remove_class") and not meta.get("name"):
            raise ValueError("`name` key required for named removal patches")

        # add_block extra checks
        if pt == "add_block":
            pos = meta.get("position", "end")
            if pos not in ("start", "end", "before", "after"):
                raise ValueError(f"Invalid add_block position: {pos}")
            if pos in ("before", "after") and not meta.get("anchor"):
                raise ValueError("add_block before/after requires an `anchor` regex")

        # remove_block extra checks
        if pt == "remove_block":
            has_s = "anchor_start" in meta
            has_e = "anchor_end"   in meta
            if has_s ^ has_e:
                raise ValueError("remove_block requires both `anchor_start` and `anchor_end` when using anchors")

def validate_spec(meta: Dict[str, Any]) -> None:
    """
    Ensure the patch metadata is well‑formed and supported.
    Raises ValueError on any problem.
    """
    required = {"VibeSpec", "patch_type", "file"}
    missing  = required - set(meta.keys())
    if missing:
        raise ValueError(f"Missing meta keys: {sorted(missing)}")

    # Allow v1.0, v1.2, v1.3, v1.4, and batch spec 1.5
    vs = meta["VibeSpec"]
    if vs not in ("1.0", "1.2", "1.3", "1.4", "1.5", "1.6"):
        raise ValueError(f"Unsupported VibeSpec version: '{vs}'")

    pt = meta["patch_type"]
    allowed = {
        "add_function", "add_method", "add_class", "add_block", "replace_block",
        "remove_function", "remove_method", "remove_class", "remove_block"
    }
    if pt not in allowed:
        raise ValueError(f"Unsupported patch_type: {pt}")

    # class key required for method patches
    if pt in ("add_method", "remove_method") and not meta.get("class"):
        raise ValueError("`class` key required for method patches")

    # name key required for named removals
    if pt in ("remove_function", "remove_method", "remove_class") and not meta.get("name"):
        raise ValueError("`name` key required for named removal patches")

    # add_block extra checks
    if pt == "add_block":
        pos = meta.get("position", "end")
        if pos not in ("start", "end", "before", "after"):
            raise ValueError(f"Invalid add_block position: {pos}")
        if pos in ("before", "after") and not meta.get("anchor"):
            raise ValueError("add_block before/after requires an `anchor` regex")

    # remove_block extra checks
    if pt == "remove_block":
        has_s = "anchor_start" in meta
        has_e = "anchor_end"   in meta
        if has_s ^ has_e:
            raise ValueError("remove_block requires both `anchor_start` and `anchor_end` when using anchors")

# =============================================================================
#  Backup helper
# =============================================================================

def _backup(target: Path) -> Path:
    bdir = target.parent / "VibeBackups"
    bdir.mkdir(exist_ok=True)
    dest = bdir / f"{target.stem}_{_timestamp()}{target.suffix}"
    shutil.copy2(target, dest)
    return dest

# =============================================================================
#  Block replacement helpers
# =============================================================================

def _replace_block(lines: list[str], start: int, end: int, block: str) -> list[str]:
    return lines[:start] + [block.rstrip() + "\n\n"] + lines[end:]

# ---------- function replace ------------------------------------------------

def _append_func_before_class(src: str, block: str) -> str:
    lines = src.splitlines(keepends=True)
    # find first class definition
    m = re.search(r"^\s*class\s+", src, re.MULTILINE)
    if m:
        idx = src[:m.start()].count("\n")
        # if there's already a blank line before class, move insertion point up
        if idx > 0 and not lines[idx-1].strip():
            idx -= 1
        # insert the new function with exactly one blank line after
        insert = ["\n" + block.rstrip() + "\n"]
        return "".join(lines[:idx] + insert + lines[idx:])
    # no class found: append at EOF with one blank line before function
    trimmed = src.rstrip("\n")
    return trimmed + "\n" + block.rstrip() + "\n"

def _replace_function(src: str, name: str, block: str) -> str:
    # match existing function definitions across lines
    pat = re.compile(rf"^\s*def\s+{re.escape(name)}\s*\(", re.MULTILINE)
    m = pat.search(src)
    if not m:
        return _append_func_before_class(src, block)
    lines = src.splitlines(keepends=True)

    # start at the def, but include any decorator lines immediately above
    start = src[:m.start()].count("\n")
    # if the line(s) above are decorators, fold them into the replacement
    while start > 0 and lines[start-1].lstrip().startswith("@"):
        start -= 1
    indent = len(m.group(0)) - len(m.group(0).lstrip())
    end = start + 1
    while end < len(lines):
        ln = lines[end]
        if ln.strip() and (len(ln) - len(ln.lstrip())) <= indent:
            break
        end += 1
    return "".join(_replace_block(lines, start, end, block))

# ---------- class replace ----------------------------------------------------

def _replace_class(src: str, cls: str, block: str) -> str:
    lines = src.splitlines(keepends=True)
    start_idx: Any = None
    indent = 0
    for i, ln in enumerate(lines):
        if re.match(rf"^\s*class\s+{re.escape(cls)}\b.*:", ln):
            start_idx = i
            indent = len(ln) - len(ln.lstrip())
            break
    if start_idx is None:
        return src.rstrip("\n") + "\n\n" + block.rstrip() + "\n"
    end_idx = start_idx + 1
    while end_idx < len(lines):
        ln = lines[end_idx]
        ws = len(ln) - len(ln.lstrip())
        if ln.strip() and ws <= indent:
            break
        end_idx += 1
    return "".join(lines[:start_idx] + [block.rstrip() + "\n\n"] + lines[end_idx:])

# ---------- method replace --------------------------------------------------

def _replace_method(src: str, cls: str, meth: str, block: str) -> str:
    """
    Replace (or append) a method `meth` inside class `cls`, including any decorators.
    """
    lines = src.splitlines(keepends=True)

    # 1) Find the class definition
    cls_idx = None
    cls_indent = 0
    for i, ln in enumerate(lines):
        if re.match(rf"^\s*class\s+{re.escape(cls)}\b.*:", ln):
            cls_idx = i
            cls_indent = len(ln) - len(ln.lstrip())
            break
    if cls_idx is None:
        raise ValueError(f"Class {cls} not found")

    # 2) Determine class-body boundary
    end_idx = cls_idx + 1
    while end_idx < len(lines):
        ln = lines[end_idx]
        ws = len(ln) - len(ln.lstrip())
        if ln.strip() and ws <= cls_indent:
            break
        end_idx += 1

    # 3) Locate existing method (if any)
    indent_str = ' ' * (cls_indent + 4)
    meth_pat = re.compile(rf"^{re.escape(indent_str)}@?")  # match decorator or method
    meth_def = re.compile(rf"^{re.escape(indent_str)}def\s+{re.escape(meth)}\s*\(")
    meth_idx = None
    for i in range(cls_idx+1, end_idx):
        if meth_def.match(lines[i]):
            meth_idx = i
            break

    # 4) Prepare new block (ensure proper indentation)
    if not block.startswith(indent_str):
        block = indent_str + block.rstrip().replace("\n", "\n" + indent_str)
    # ensure leading newline if appending
    if meth_idx is None and lines[end_idx-1].strip():
        block = "\n" + block

    # 5) If replacing, adjust start to include decorators
    if meth_idx is not None:
        # back up to include any decorator lines
        start_idx = meth_idx
        while start_idx > cls_idx and lines[start_idx-1].lstrip().startswith("@"):
            start_idx -= 1

        # find end of method (first line with indent <= method indent)
        m_end = start_idx + 1
        while m_end < end_idx:
            ln = lines[m_end]
            ws = len(ln) - len(ln.lstrip())
            if ln.strip() and ws <= len(indent_str):
                break
            m_end += 1

        # replace the old block (decorators + def + body)
        new_lines = lines[:start_idx] + [block + "\n\n"] + lines[m_end:end_idx] + lines[end_idx:]
        return "".join(new_lines)

    # 6) Otherwise, append the new method at end of class body
    return "".join(lines[:end_idx] + [block + "\n\n"] + lines[end_idx:])

# =============================================================================
#  Removal helpers
# =============================================================================

def _remove_between(src: str, start_pat: str, end_pat: str) -> str:
    """
    Remove every line from the first match of start_pat through
    (and including) the first match of end_pat.
    """
    import re
    lines = src.splitlines(keepends=True)
    start_re = re.compile(start_pat)
    end_re   = re.compile(end_pat)
    out = []
    removing = False

    for ln in lines:
        if not removing and start_re.search(ln):
            removing = True
            continue
        if removing:
            if end_re.search(ln):
                removing = False
            continue
        out.append(ln)
    return "".join(out)

def _remove_function(src: str, name: str) -> str:
    """
    Remove a top‑level function named `name`, including its def line and any @decorators above.
    """
    import re
    lines = src.splitlines(keepends=True)

    # 1) Find the index of the `def name(` line
    start = None
    indent = 0
    for idx, ln in enumerate(lines):
        m = re.match(rf"^(\s*)def\s+{re.escape(name)}\s*\(", ln)
        if m:
            start = idx
            indent = len(ln) - len(ln.lstrip())
            break
    if start is None:
        # nothing to remove
        return src

    # 2) Fold in any decorator lines immediately above
    while start > 0 and lines[start-1].lstrip().startswith("@"):
        start -= 1

    # 3) Scan forward to end of that function body
    end = start + 1
    while end < len(lines):
        ln = lines[end]
        ws = len(ln) - len(ln.lstrip())
        # break at the first non‑blank line with indent <= the function indent
        if ln.strip() and ws <= indent:
            break
        end += 1

    # 4) Splice out lines[start:end]
    return "".join(lines[:start] + lines[end:])

def _remove_method(src: str, cls: str, meth: str) -> str:
    """
    Remove a method `meth` inside class `cls`, including its def line and any @decorators above.
    """
    import re
    lines = src.splitlines(keepends=True)

    # find the class header
    cls_pat = re.compile(rf"^(\s*)class\s+{re.escape(cls)}\b", re.MULTILINE)
    mcls = cls_pat.search(src)
    if not mcls:
        return src

    # compute the class body range
    cls_indent = len(mcls.group(1))
    start = src[:mcls.start()].count("\n") + 1
    end = start + 1
    while end < len(lines):
        ln = lines[end]
        ws = len(ln) - len(ln.lstrip())
        if ln.strip() and ws <= cls_indent:
            break
        end += 1

    # locate the method within the class slice
    meth_pat = re.compile(rf"^(\s*)def\s+{re.escape(meth)}\s*\(")
    for i in range(start, end):
        if meth_pat.match(lines[i]):
            # back up to include decorators
            mstart = i
            while mstart > start and lines[mstart-1].lstrip().startswith("@"):
                mstart -= 1
            # consume until indent <= method indent
            indent = len(lines[i]) - len(lines[i].lstrip())
            mend = mstart + 1
            while mend < end:
                ln = lines[mend]
                ws = len(ln) - len(ln.lstrip())
                if ln.strip() and ws <= indent:
                    break
                mend += 1
            # splice out [mstart:mend)
            return "".join(lines[:mstart] + lines[mend:])
    return src

def _remove_class(src: str, cls: str) -> str:
    """
    Remove an entire class definition (header + indented block).
    """
    import re
    lines = src.splitlines(keepends=True)
    # find class header
    for i, ln in enumerate(lines):
        if re.match(rf"^\s*class\s+{re.escape(cls)}\b", ln):
            indent = len(ln) - len(ln.lstrip())
            start  = i
            break
    else:
        return src
    end = start + 1
    # consume indented block
    while end < len(lines):
        ln = lines[end]
        ws = len(ln) - len(ln.lstrip())
        if ln.strip() and ws <= indent:
            break
        end += 1
    return "".join(lines[:start] + lines[end:])

# =============================================================================
#  Apply patch
# =============================================================================

def apply_patch(meta: Dict[str, Any], code: str, repo: Path, dry: bool=False):
    """
    Apply a single VibeSpec patch described by meta and code to the target file.
    Creates the target file if it doesn't exist for 'add_*'/'replace_*' patches.
    """
    target = repo / meta["file"]
    pt = meta["patch_type"] # Get patch type early

    # --- MODIFICATION START ---
    file_existed_originally = target.exists()
    src = "" # Initialize src

    if not file_existed_originally:
        # File doesn't exist. Check if patch type allows creation.
        is_add_or_replace = pt.startswith("add_") or pt.startswith("replace_") # Basic check
        if is_add_or_replace:
            _log("Target file {} does not exist. Creating for patch type '{}'.", target.name, pt)
            # Ensure parent directory exists
            target.parent.mkdir(parents=True, exist_ok=True)
            # Create empty file to operate on
            target.write_text("", encoding='utf-8')
            src = "" # Source is empty for a new file
        else:
            # If it's a remove_* patch or similar on a non-existent file, raise error
            raise FileNotFoundError(f"Target file '{target}' not found for patch type '{pt}'.")
    else:
        # File exists, proceed with backup and reading source
        if not dry: # Only backup if not dry run and file existed
             _log("Backup → {}", _backup(target))
        src = target.read_text(encoding='utf-8')
    # --- MODIFICATION END ---

    # --- Rest of the function remains largely the same ---
    block = dedent(code).rstrip("\n")
    lines = src.splitlines(keepends=True) # Use src which is now correctly loaded or empty

    # helper to remove blocks by regex anchors or indent-sensitive (keep as is)
    def _remove_block(lines, start_re, end_re=None, indent_sensitive=False):
        # ... (implementation remains the same) ...
        new_lines = []
        skipping = False
        base_indent = None

        for ln in lines:
            if not skipping and start_re.search(ln):
                skipping = True
                if indent_sensitive:
                    base_indent = len(ln) - len(ln.lstrip())
                continue
            if skipping:
                if end_re:
                    if end_re.search(ln):
                        skipping = False
                    continue # Always continue if using end_re until it matches
                if indent_sensitive:
                    curr_indent = len(ln) - len(ln.lstrip())
                    # Skip indented lines or blank lines within the block
                    if (curr_indent > base_indent and ln.strip()) or (not ln.strip()):
                         continue
                    else: # Non-blank line at or below base_indent: stop skipping
                         skipping = False
                         # Fall through to append this line
                else: # Not indent sensitive, stop skipping on first non-blank, non-indented line
                    if not ln.strip() or ln.startswith((" ", "\t")):
                        continue
                    else:
                        skipping = False
                         # Fall through to append this line

            new_lines.append(ln) # Append if not skipping
        return "".join(new_lines)


    # --- Patch Type Logic (mostly unchanged, operates on potentially empty src) ---
    new_src = "" # Initialize new_src
    if pt == "add_function":
        m = re.search(r"^\s*def\s+(\w+)", block, re.MULTILINE)
        if not m: raise ValueError(f"Invalid add_function block, no func sig: {block[:80]}...")
        name = m.group(1)
        new_src = _replace_function(src, name, block)

    elif pt == "add_method":
        cls = meta.get("class")
        if not cls: raise ValueError("`class` key required for add_method")
        m = re.search(r"^\s*def\s+(\w+)", block, re.MULTILINE)
        if not m: raise ValueError(f"Invalid add_method block, no method sig: {block[:80]}...")
        name = m.group(1)
        new_src = _replace_method(src, cls, name, block)

    elif pt == "add_class":
        mcls = re.search(r"^\s*class\s+(\w+)", block, re.MULTILINE)
        cls_name = mcls.group(1) if mcls else None
        # Always use _replace_class for add_class; it handles append if not found
        new_src = _replace_class(src, cls_name, block) if cls_name else (src.rstrip("\n") + "\n\n" + block + "\n")


    elif pt == "add_block":
        pos = meta.get("position", "end")
        anchor = meta.get("anchor")
        if pos == "start":
            new_src = block.rstrip() + ("\n\n" if src.strip() else "\n") + src # Add only one newline if src is empty

        elif pos in ("before", "after"):
            if not anchor: raise ValueError("add_block before/after requires `anchor` regex")
            pat = re.compile(anchor)
            # Use finditer to handle potential multiple matches if needed, though next usually suffices
            match_indices = [i for i, ln in enumerate(lines) if pat.search(ln)]
            idx = match_indices[0] if match_indices else len(lines) # Find first match or EOF

            if pos == "after" and idx < len(lines):
                # Advance index past the matched block for 'after'
                anchor_indent = len(lines[idx]) - len(lines[idx].lstrip()) if lines[idx].strip() else float('inf')
                j = idx + 1
                while j < len(lines):
                    ln = lines[j]
                    ws = len(ln) - len(ln.lstrip()) if ln.strip() else float('inf')
                    # Stop at the next line with equal or lesser indentation, or EOF
                    if ln.strip() and ws <= anchor_indent:
                        break
                    j += 1
                idx = j # Insertion point is after the block

            # Ensure single blank line before insertion point (unless at start)
            if idx > 0 and idx < len(lines) and lines[idx-1].strip() and lines[idx].strip(): # Check both surrounding lines
                 lines.insert(idx, "\n")
                 idx += 1
            elif idx > 0 and not lines[idx-1].strip(): # If line before is blank, use it
                 pass
            elif idx == 0 and lines: # Inserting at very beginning before existing content
                 lines.insert(idx, "\n") # Insert blank line after new block
                 idx +=1 # this seems wrong.. should insert before the block? test this
            elif idx > 0 and lines[idx-1].strip(): # only line before has content
                 lines.insert(idx, "\n")
                 idx += 1


            # Insert the block, ensuring appropriate newlines
            lines.insert(idx, block.rstrip() + "\n") # Add the block with one newline
            # Add another newline after if not at EOF and next line isn't already blank
            if (idx + 1) < len(lines) and lines[idx+1].strip():
                lines.insert(idx + 1, "\n")
            elif (idx + 1) == len(lines): # If inserting right at the end
                 lines.append("\n") # Ensure a trailing newline for the file


            new_src = "".join(lines)
        else: # Default 'end' position
             sep = "\n\n" if src.strip() else "\n" # Add only one newline if src is empty
             new_src = src.rstrip("\n") + sep + block.rstrip() + "\n" # Ensure trailing newline

    elif pt == "remove_block":
        start_pat = meta.get("anchor_start")
        end_pat = meta.get("anchor_end")
        if not start_pat or not end_pat: raise ValueError("remove_block requires anchor_start and anchor_end")
        start_re = re.compile(start_pat)
        end_re   = re.compile(end_pat)
        new_src = _remove_block(lines, start_re, end_re) # Pass lines list

    elif pt == "remove_function":
        name = meta.get("name")
        if not name: raise ValueError("remove_function requires `name`")
        new_src = _remove_function(src, name)

    elif pt == "remove_method":
        cls = meta.get("class")
        name = meta.get("name")
        if not cls or not name: raise ValueError("remove_method requires `class` and `name`")
        new_src = _remove_method(src, cls, name)

    elif pt == "remove_class":
        cls_rm = meta.get("name")
        if not cls_rm: raise ValueError("remove_class requires `name`")
        new_src = _remove_class(src, cls_rm)

    # --- Handle replace_block (if distinct logic is needed) ---
    elif pt == "replace_block":
         # Current implementation might implicitly handle some cases via add_*
         # If specific anchor-based replacement is intended:
         start_pat = meta.get("anchor_start")
         end_pat = meta.get("anchor_end")
         if start_pat and end_pat:
              start_re = re.compile(start_pat); end_re = re.compile(end_pat)
              # Find start/end indices
              start_idx = -1; end_idx = -1
              for i, ln in enumerate(lines):
                   if start_idx == -1 and start_re.search(ln): start_idx = i
                   if start_idx != -1 and end_re.search(ln): end_idx = i + 1; break # Include end line range
              if start_idx != -1 and end_idx != -1:
                   new_lines = lines[:start_idx] + [block.rstrip() + "\n"] + lines[end_idx:]
                   # Add surrounding newlines if needed, similar to add_block logic
                   if start_idx > 0 and lines[start_idx-1].strip(): new_lines.insert(start_idx, "\n")
                   if end_idx < len(lines) and lines[end_idx].strip(): new_lines.insert(start_idx + 2, "\n") # After the inserted block+newline
                   new_src = "".join(new_lines)
              else: # Anchors not found, maybe append or error? Append for now.
                  _log("Warning: replace_block anchors not found for '{}'. Appending.", target.name)
                  sep = "\n\n" if src.strip() else "\n"
                  new_src = src.rstrip("\n") + sep + block.rstrip() + "\n"
         else: # No anchors, treat like add_block 'end' or raise error?
             _log("Warning: replace_block used without anchors. Appending block for '{}'.", target.name)
             sep = "\n\n" if src.strip() else "\n"
             new_src = src.rstrip("\n") + sep + block.rstrip() + "\n"

    else: # Fallback for unrecognized patch types or unhandled cases
        _log(f"Warning: Unhandled patch_type '{pt}' or scenario for {target.name}. Appending code.")
        sep = "\n\n" if src.strip() else "\n"
        new_src = src.rstrip("\n") + sep + block.rstrip() + "\n"


    # --- Final write or print ---
    if dry:
        print(new_src.rstrip()) # Print for dry run, strip final newline for cleaner output
        return new_src # Return the modified source for the tester

    # Write the modified source back to the target file
    target.write_text(new_src, encoding='utf-8')
    _log("Patch applied to {}", target)
    # For non-dry run, maybe return True/None? Returning new_src is mostly for dry run.
    # Let's return None for non-dry run to avoid confusion.
    return None

# =============================================================================
#  CLI
# =============================================================================

def build_cli() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vibe", description="Vibe Patch helper v1.0")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("lint").add_argument("patch", type=Path)
    pv = sub.add_parser("preview")
    pv.add_argument("patch", type=Path)
    pv.add_argument("repo", type=Path, nargs="?", default=Path.cwd())
    ap = sub.add_parser("apply")
    ap.add_argument("patch", type=Path)
    ap.add_argument("repo", type=Path, nargs="?", default=Path.cwd())
    ap.add_argument("--dry", action="store_true")
    return p


def cmd_lint(args: argparse.Namespace) -> None:
    # batch‑aware lint
    patches = load_patches(args.patch)
    for meta, _ in patches:
        validate_spec(meta)
    _log(f"Lint OK ({len(patches)} patches)")

def cmd_preview(args: argparse.Namespace) -> None:
    # batch‑aware preview
    patches = load_patches(args.patch)
    tmpdir  = Path(tempfile.mkdtemp())
    # copy affected files
    for meta, _ in patches:
        src = args.repo / meta["file"]
        dst = tmpdir / meta["file"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text())
    apply_patches(patches, tmpdir, dry=False)
    # show diffs
    for meta, _ in patches:
        orig = args.repo / meta["file"]
        new  = tmpdir   / meta["file"]
        print(f"--- diff {meta['file']} ---")
        subprocess.call(["diff","-u", str(orig), str(new)])
    shutil.rmtree(tmpdir)

def cmd_apply(args: argparse.Namespace) -> None:
    # batch‑aware apply
    patches = load_patches(args.patch)
    apply_patches(patches, args.repo, dry=args.dry)

if __name__ == "__main__":
    cli = build_cli()
    args = cli.parse_args()
    if args.cmd == "lint":
        cmd_lint(args)
    elif args.cmd == "preview":
        cmd_preview(args)
    elif args.cmd == "apply":
        cmd_apply(args)
    else:
        cli.error(f"Unknown command: {args.cmd}")
