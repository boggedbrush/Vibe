import argparse
import datetime as _dt
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Tuple
import textwrap

import tempfile
from typing import List, Tuple

def load_patches(path: Path) -> List[Tuple[Dict[str, Any], str]]:
    """
    Parse a .vibe file with one or more patches (v1.5).
    Returns a list of (meta, code) tuples, in document order.
    """
    lines = path.read_text().splitlines(keepends=True)
    patches: List[Tuple[Dict[str, Any], str]] = []

    # If not v1.5 batch, fall back
    if not lines or "VibeSpec: 1.5" not in lines[0]:
        return [load_patch(path)]

    i = 1  # skip header
    while i < len(lines):
        # find next patch_type
        if not lines[i].startswith("patch_type:"):
            i += 1
            continue

        # collect metadata until code marker
        meta_block = []
        while i < len(lines) and not lines[i].startswith("--- code"):
            meta_block.append(lines[i])
            i += 1

        if i >= len(lines):
            raise ValueError("Malformed multi-patch: missing '--- code'")
        i += 1  # skip '--- code' line

        # collect only indented code lines
        code_block = []
        while i < len(lines):
            ln = lines[i]
            # stop on next patch header or non-indented line
            if ln.startswith("patch_type:") or not ln.startswith((" ", "\t")):
                break
            code_block.append(ln)
            i += 1

        # rebuild a standalone snippet
        snippet = "".join([
            "# VibeSpec: 1.5\n",
            *meta_block,
            "--- code\n",
            *code_block
        ])
        # parse it
        tmpdir = tempfile.mkdtemp()
        tmpf   = Path(tmpdir) / "part.vibe"
        tmpf.write_text(snippet)
        meta, code = load_patch(tmpf)
        patches.append((meta, code))
        shutil.rmtree(tmpdir)

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

        # Allow v1.0, v1.2, v1.3, v1.4, and batch spec 1.5
        vs = meta["VibeSpec"]
        if vs not in ("1.0", "1.2", "1.3", "1.4", "1.5"):
            raise ValueError(f"Unsupported VibeSpec version: {vs}")

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
    if vs not in ("1.0", "1.2", "1.3", "1.4", "1.5"):
        raise ValueError(f"Unsupported VibeSpec version: {vs}")

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

def old_validate_spec(meta: Dict[str, Any]) -> None:
    """
    Ensure the patch metadata is well‑formed and supported.
    Raises ValueError on any problem.
    """
    # 1) Required keys
    required = {"VibeSpec", "patch_type", "file"}
    missing = required - set(meta.keys())
    if missing:
        raise ValueError(f"Missing meta keys: {sorted(missing)}")

    # 2) Spec version (allow 1.0, 1.2, 1.3, 1.4)
    vs = meta["VibeSpec"]
    if vs not in ("1.0", "1.2", "1.3", "1.4"):
        raise ValueError(f"Unsupported VibeSpec version: {vs}")

    # 3) Supported patch types
    pt = meta["patch_type"]
    allowed = {
        "add_function", "add_method", "add_class", "add_block", 
        "remove_function", "remove_method", "remove_class", "remove_block",
    }
    if pt not in allowed:
        raise ValueError(f"Unsupported patch_type: {pt}")

    # 4) 'class' key required for method patches
    if pt in ("add_method", "remove_method") and not meta.get("class"):
        raise ValueError("`class` key is required for method patches")

    # 5) 'name' key required for named removals
    if pt in ("remove_function", "remove_method", "remove_class") and not meta.get("name"):
        raise ValueError("`name` key is required for named removal patches")

    # 6) add_block additional checks
    if pt == "add_block":
        pos = meta.get("position", "end")
        if pos not in ("start", "end", "before", "after"):
            raise ValueError(f"Invalid position for add_block: {pos}")
        if pos in ("before", "after") and not meta.get("anchor"):
            raise ValueError("add_block with before/after requires an `anchor` regex")

    # 7) remove_block additional checks (anchors optional)
    if pt == "remove_block":
        # if one anchor given, require the other
        has_start = "anchor_start" in meta
        has_end   = "anchor_end" in meta
        if has_start ^ has_end:
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
    start = src[:m.start()].count("\n")
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
    lines = src.splitlines(keepends=True)
    cls_idx: Any = None
    cls_indent = 0
    for i, ln in enumerate(lines):
        if re.match(rf"^\s*class\s+{re.escape(cls)}\b.*:", ln):
            cls_idx = i
            cls_indent = len(ln) - len(ln.lstrip())
            break
    if cls_idx is None:
        raise ValueError(f"Class {cls} not found")
    end_idx = cls_idx + 1
    while end_idx < len(lines):
        ln = lines[end_idx]
        ws = len(ln) - len(ln.lstrip())
        if ln.strip() and ws <= cls_indent:
            break
        end_idx += 1
    indent = ' ' * (cls_indent + 4)
    pat = re.compile(rf"^{re.escape(indent)}def\s+{re.escape(meth)}\s*\(")
    meth_idx: Any = None
    for i in range(cls_idx+1, end_idx):
        if pat.match(lines[i]):
            meth_idx = i
            break
    if not block.startswith(indent):
        block = indent + block.rstrip().replace("\n", "\n" + indent)
    if meth_idx is None and lines[end_idx-1].strip():
        block = "\n" + block
    if meth_idx is not None:
        m_end = meth_idx + 1
        while m_end < end_idx:
            ln = lines[m_end]
            ws = len(ln) - len(ln.lstrip())
            if ln.strip() and ws <= len(indent):
                break
            m_end += 1
        return "".join(_replace_block(lines, meth_idx, m_end, block))
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
    Remove a top‑level function named `name` (its entire def … body).
    """
    import re
    lines = src.splitlines(keepends=True)
    pat   = re.compile(rf"^(\s*)def\s+{re.escape(name)}\s*\(", re.MULTILINE)
    m     = pat.search(src)
    if not m:
        return src

    indent = len(m.group(1))
    # start at the line *after* the def – skip the header itself
    start  = src[:m.start()].count("\n") + 1
    end    = start + 1

    # consume until we hit a line with indentation ≤ the function header
    while end < len(lines):
        ln = lines[end]
        ws = len(ln) - len(ln.lstrip())
        if ln.strip() and ws <= indent:
            break
        end += 1

    # splice out [start:end]
    return "".join(lines[:start] + lines[end:])

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


def _remove_method(src: str, cls: str, meth: str) -> str:
    """
    Remove a method named `meth` inside class `cls`.
    """
    import re
    lines = src.splitlines(keepends=True)

    # Locate the class header
    cls_pat = re.compile(rf"^(\s*)class\s+{re.escape(cls)}\b", re.MULTILINE)
    mcls    = cls_pat.search(src)
    if not mcls:
        return src
    cls_indent = len(mcls.group(1))

    # Determine the start/end lines of the class body
    start = src[:mcls.start()].count("\n") + 1
    end   = start + 1
    while end < len(lines):
        ln = lines[end]
        ws = len(ln) - len(ln.lstrip())
        if ln.strip() and ws <= cls_indent:
            break
        end += 1

    # Find the method within that slice
    meth_pat = re.compile(rf"^(\s*)def\s+{re.escape(meth)}\s*\(")
    for i in range(start, end):
        mn = meth_pat.match(lines[i])
        if not mn:
            continue
        indent = len(mn.group(1))
        mstart = i
        mend   = mstart + 1
        # Swallow the method body
        while mend < end:
            ln = lines[mend]
            ws = len(ln) - len(ln.lstrip())
            if ln.strip() and ws <= indent:
                break
            mend += 1

        # Splice out signature+body
        return "".join(lines[:mstart] + lines[mend:end] + lines[end:])

    return src


# =============================================================================
#  Apply patch
# =============================================================================

def apply_patch(meta: Dict[str, Any], code: str, repo: Path, dry: bool=False):
    target = repo / meta["file"]
    if not target.exists():
        raise FileNotFoundError(target)
    _log("Backup → {}", _backup(target))
    src = target.read_text()
    pt  = meta["patch_type"]

    # Dedent once—applies to all block types
    block = textwrap.dedent(code).rstrip("\n")
    lines = src.splitlines(keepends=True)

    if pt == "add_function":
        print("===")
        print(block)
        print("----")
        name = re.match(r"def\s+(\w+)", block, re.MULTILINE).group(1)
        new_src = _replace_function(src, name, block)

    elif pt == "add_method":
        cls  = meta.get("class") or ""
        name = re.match(r"def\s+(\w+)", block).group(1)
        new_src = _replace_method(src, cls, name, block)

    elif pt == "add_class":
        cls     = re.match(r"class\s+(\w+)", block).group(1)
        new_src = _replace_class(src, cls, block)

    elif pt == "add_block":
        pos    = meta.get("position", "end")
        anchor = meta.get("anchor")

        if pos == "start":
            # Prepend block + blank line
            new_src = block + "\n\n" + src

        elif pos in ("before", "after") and anchor:
            pat = re.compile(anchor)
            # locate the anchor line
            idx = next((i for i, ln in enumerate(lines) if pat.search(ln)), None)
            if idx is None:
                # fallback to end of file
                idx = len(lines)

            if pos == "after":
                # If anchor begins a block (e.g. def/class), move to end of that block
                indent = len(lines[idx]) - len(lines[idx].lstrip())
                j = idx + 1
                while j < len(lines):
                    ln = lines[j]
                    ws = len(ln) - len(ln.lstrip())
                    if ln.strip() and ws <= indent:
                        break
                    j += 1
                idx = j

            # ensure a single blank line before insertion
            if idx > 0 and lines[idx-1].strip():
                lines.insert(idx, "\n")
                idx += 1

            # insert the block plus a blank line after
            lines.insert(idx, block + "\n")
            lines.insert(idx + 1, "\n")
            new_src = "".join(lines)

        else:
            # default: append at EOF
            trimmed = src.rstrip("\n")
            new_src = trimmed + "\n\n" + block + "\n"

    elif pt == "remove_function":
        # remove a top‐level function by its name
        func_name = meta["name"]
        new_src = _remove_function(src, func_name)

    elif pt == "remove_method":
        # remove a method inside a class by its name
        cls_name  = meta["class"]
        meth_name = meta["name"]
        new_src = _remove_method(src, cls_name, meth_name)

    elif pt == "remove_class":
        # remove an entire class by its name
        cls_name = meta["name"]
        new_src   = _remove_class(src, cls_name)

    elif pt == "remove_block":
        # generic block removal by anchors or literal match
        if "anchor_start" in meta and "anchor_end" in meta:
            new_src = _remove_between(
                src,
                meta["anchor_start"],
                meta["anchor_end"]
            )
        else:
            # delete the exact code lines (if any) or do nothing
            literal = code.rstrip() + "\n"
            new_src  = src.replace(literal, "")
    else:
        # fallback behavior for unknown patch types
        trimmed = src.rstrip("\n")
        new_src  = trimmed + "\n\n" + block + "\n"

    if dry:
        print(new_src)
        return new_src

    target.write_text(new_src)
    _log("Patch applied to {}", target)

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
