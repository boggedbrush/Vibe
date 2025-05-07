import argparse
import datetime as _dt
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional
import textwrap
import tempfile
import yaml
from textwrap import dedent
import ast

def get_function_extent_ast(src: str, function_name: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Uses AST to find the start and end line numbers (1-indexed, inclusive)
    of a top-level function, including its decorators.
    Returns (None, None) if not found or if the source cannot be parsed.
    """
    try:
        # ast.parse requires a complete, valid Python module string.
        tree = ast.parse(src)
    except SyntaxError:
        _log(f"AST: SyntaxError encountered while parsing source to find '{function_name}'.")
        return None, None

    for node in tree.body: # Iterate over top-level nodes in the module (e.g., functions, classes)
        # Check if the node is a function definition (sync or async)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == function_name:
                # Determine the start line (1-indexed)
                start_line = node.lineno # Line of the 'def' keyword
                if node.decorator_list:
                    # If there are decorators, the function block effectively starts at the earliest decorator
                    min_decorator_lineno = min(dec.lineno for dec in node.decorator_list)
                    start_line = min(start_line, min_decorator_lineno) # Should be min_decorator_lineno

                # end_lineno is the last line of the function block, inclusive (1-indexed)
                end_line = node.end_lineno
                return start_line, end_line

    # _log(f"AST: Function '{function_name}' not found in top-level AST nodes.")
    return None, None # Function not found at the top level


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
        # Sort for consistent error messages
        raise ValueError(f"Missing meta keys: {sorted(list(missing))}")

    vs = meta["VibeSpec"]
    # VibeSpec versions supported by this CLI version
    supported_versions = ("1.0", "1.2", "1.3", "1.4", "1.5", "1.6")
    if vs not in supported_versions:
        raise ValueError(f"Unsupported VibeSpec version: '{vs}'. Supported: {supported_versions}")

    pt = meta["patch_type"]
    allowed_patch_types = {
        "add_function", "add_method", "add_class", "add_block",
        "replace_function", "replace_method", "replace_class", "replace_block",
        "remove_function", "remove_method", "remove_class", "remove_block"
    }
    if pt not in allowed_patch_types:
        # Sort for consistent error messages
        raise ValueError(f"Unsupported patch_type: '{pt}'. Allowed: {sorted(list(allowed_patch_types))}")

    # --- Key requirements based on patch_type ---

    # `class` key requirement
    if pt in ("add_method", "replace_method", "remove_method"):
        if not meta.get("class"):
            raise ValueError(f"`class` key required for patch_type '{pt}'")

    # `name` key requirement
    # (add_* types infer name from code, or don't need it if purely appending)
    if pt in ("replace_function", "replace_method", "replace_class",
               "remove_function", "remove_method", "remove_class"):
        if not meta.get("name"):
            raise ValueError(f"`name` key required for patch_type '{pt}'")

    # `add_block` specific checks
    if pt == "add_block":
        # position: defaults to "end" if not provided.
        pos = meta.get("position", "end")
        if pos not in ("start", "end", "before", "after"):
            raise ValueError(f"Invalid add_block position: '{pos}'. Must be one of 'start', 'end', 'before', 'after'.")
        if pos in ("before", "after") and not meta.get("anchor"):
            raise ValueError(f"add_block with position '{pos}' requires an `anchor` regex.")

    # `remove_block` specific checks
    if pt == "remove_block":
        if not meta.get("anchor_start") or not meta.get("anchor_end"):
            raise ValueError("remove_block requires both `anchor_start` and `anchor_end` metadata keys.")

    # `replace_block` specific checks
    if pt == "replace_block":
        if not meta.get("anchor_start") or not meta.get("anchor_end"):
            raise ValueError("replace_block requires both `anchor_start` and `anchor_end` metadata keys.")

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
    # Changed from "\n\n" to "\n" to reduce excessive blank lines.
    # PEP 8 usually wants one blank line after a function/method,
    # and two before a top-level class or function.
    # The block itself should be formatted correctly internally.
    # This change makes the splicer less opinionated about spacing *after* the block.
    return lines[:start] + [block.rstrip('\n') + "\n"] + lines[end:]

# ---------- function replace ------------------------------------------------

def _append_func_before_class(src: str, block: str) -> str:
    """
    Appends a function block.
    Tries to insert before the first class definition, otherwise at EOF.
    Manages blank lines to aim for PEP 8 spacing.
    """
    normalized_src = src.replace('\r\n', '\n').replace('\r', '\n')
    normalized_block = block.rstrip() # The function code itself

    lines = normalized_src.splitlines(keepends=True)
    class_match = re.search(r"^\s*class\s+", normalized_src, re.MULTILINE)

    if class_match:
        class_start_char_offset = class_match.start()
        current_char_offset = 0
        class_line_idx = -1
        for i, line_content_iter in enumerate(lines):
            if class_start_char_offset >= current_char_offset and \
               class_start_char_offset < (current_char_offset + len(line_content_iter)):
                class_line_idx = i
                break
            current_char_offset += len(line_content_iter)

        if class_line_idx == -1: # Should not happen
            _log("Error: _append_func_before_class could not find class line index. Appending to EOF.")
            # Fallback to EOF logic
            trimmed_src_for_eof = normalized_src.rstrip()
            if trimmed_src_for_eof:
                return trimmed_src_for_eof + "\n\n" + normalized_block + "\n"
            else:
                return normalized_block + "\n"

        prefix_str = "".join(lines[:class_line_idx])
        suffix_str = "".join(lines[class_line_idx:])

        # How many blank lines are already before the class in the prefix?
        # (i.e., how many trailing newlines does the prefix have after rstrip())
        stripped_prefix = prefix_str.rstrip('\n')
        num_trailing_newlines_in_prefix = len(prefix_str) - len(stripped_prefix)

        # We want 2 blank lines before the class. The new function block will add one \n.
        # So, after the new function, we need one more \n if the class follows.
        # Before the new function, we need enough newlines so that `stripped_prefix + newlines + new_function`
        # results in the correct spacing.

        # Case 1: Prefix is empty or all whitespace
        if not stripped_prefix.strip():
            # If prefix was all blank lines, or empty, we just add the new function.
            # It will be followed by the class. We need two blank lines.
            # block\n + \n + class...
            # If prefix was just "\n\n", keep it.
            # If prefix was "\n", make it "\n\n" before block, unless block makes it so.
            # This is simpler: just put block, then ensure 2 newlines before suffix.
            return normalized_block + "\n\n" + suffix_str.lstrip('\n')


        # Case 2: Prefix has content.
        # We want: stripped_prefix + "\n\n" + normalized_block + "\n\n" + suffix_str (if suffix starts with content)
        # More simply: stripped_prefix + "\n\n" + normalized_block + "\n" + (optional "\n") + suffix_str

        # Start with the prefix that has content, end it with two newlines.
        # This ensures two blank lines after whatever was before our new function.
        prefix_formatted = stripped_prefix + "\n\n"

        # Then add the new function block, which should end with one newline.
        # Then, the suffix (class definition) should follow.
        # The two newlines from prefix_formatted should be enough.

        # The block itself should end with one newline.
        # The suffix (class) should start without leading newlines from original source.
        # We want prefix_formatted + new_block_with_one_trailing_newline + one_blank_line + suffix_lstripped
        return prefix_formatted + normalized_block + "\n\n" + suffix_str.lstrip('\n')

    else:
        # No class found: append at EOF
        trimmed_src = normalized_src.rstrip()
        if trimmed_src: 
            return trimmed_src + "\n\n" + normalized_block + "\n"
        else: 
            return normalized_block + "\n"

def _replace_function(src: str, name: str, block: str) -> str:
    """
    Replaces a top-level function named `name` with the content of `block`,
    using AST to determine the extent of the original function.
    If the original function is not found by AST, it appends the new function.
    """
    # Normalize line endings first for consistent splitting and line indexing by AST.
    normalized_src = src.replace('\r\n', '\n').replace('\r', '\n')

    start_line_1_indexed, end_line_1_indexed = get_function_extent_ast(normalized_src, name)

    if start_line_1_indexed is None or end_line_1_indexed is None:
        # Function to be replaced not found by AST or parse error.
        # Fallback: append the new function (similar to add_function behavior).
        # For a strict "replace-only", this could raise an error or return src unchanged.
        _log(f"AST: Function '{name}' not found for replacement. Appending new function.")
        return _append_func_before_class(normalized_src, block)

    lines = normalized_src.splitlines(keepends=True)

    # Convert 1-indexed AST line numbers to 0-indexed for list slicing.
    # start_idx_0_indexed is the first line to remove/replace (inclusive).
    start_idx_0_indexed = start_line_1_indexed - 1
    # end_idx_exclusive_0_indexed is the line *after* the last line to remove/replace.
    end_idx_exclusive_0_indexed = end_line_1_indexed # AST end_lineno is inclusive

    # Basic sanity checks for calculated indices
    if not (0 <= start_idx_0_indexed < len(lines) and \
            0 < end_idx_exclusive_0_indexed <= len(lines) and \
            start_idx_0_indexed < end_idx_exclusive_0_indexed):
        _log(f"AST: Calculated line indices for replacing '{name}' (start_0idx={start_idx_0_indexed}, end_0idx_excl={end_idx_exclusive_0_indexed}) are out of bounds for {len(lines)} lines. Appending new function as fallback.")
        return _append_func_before_class(normalized_src, block)

    # --- DEBUG Prints (can be uncommented if needed) ---
    # _log(f"AST _replace_function: name='{name}', start_line_1idx={start_line_1_indexed}, end_line_1idx={end_line_1_indexed}")
    # _log(f"AST _replace_function: Replacing lines from {start_idx_0_indexed} up to (not including) {end_idx_exclusive_0_indexed}")
    # ---

    # Use the existing _replace_block helper, which takes 0-indexed start/end_exclusive
    # and the new code block string.
    new_src_lines = _replace_block(lines, start_idx_0_indexed, end_idx_exclusive_0_indexed, block)

    result_src = "".join(new_src_lines)

    # Ensure a single trailing newline if there's content, or empty string if not.
    # _replace_block adds '\n\n', so this might need adjustment if too many newlines.
    # For now, let _replace_block handle its own newline management.
    # If _replace_block's `\n\n` is too much, this final strip/add might be:
    # stripped_result = result_src.rstrip()
    # if stripped_result:
    #     return stripped_result + '\n'
    # else:
    #     return ""
    return result_src # Rely on _replace_block for now

def get_method_extent_ast(src: str, class_name: str, method_name: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Uses AST to find the start and end line numbers (1-indexed, inclusive)
    of a method within a specific class, including its decorators.
    Returns (None, None) if not found or if the source cannot be parsed.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        _log(f"AST: SyntaxError encountered while parsing source to find method '{class_name}.{method_name}'.")
        return None, None

    for node in tree.body: # Iterate over top-level nodes
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            # Found the class, now look for the method within its body
            for class_node_item in node.body:
                if isinstance(class_node_item, (ast.FunctionDef, ast.AsyncFunctionDef)) and class_node_item.name == method_name:
                    # Found the method
                    start_line = class_node_item.lineno # Line of the 'def' keyword
                    if class_node_item.decorator_list:
                        min_decorator_lineno = min(dec.lineno for dec in class_node_item.decorator_list)
                        start_line = min(start_line, min_decorator_lineno)

                    end_line = class_node_item.end_lineno
                    return start_line, end_line
            # _log(f"AST: Method '{method_name}' not found in class '{class_name}'.")
            return None, None # Method not found in this class

    # _log(f"AST: Class '{class_name}' not found in top-level AST nodes.")
    return None, None # Class not found

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
    Remove a top‑level function named `name` using AST to determine its extent,
    including its def line and any @decorators above.
    Aims to maintain reasonable PEP 8 spacing.
    """
    normalized_src = src.replace('\r\n', '\n').replace('\r', '\n')
    start_line_1_indexed, end_line_1_indexed = get_function_extent_ast(normalized_src, name)

    if start_line_1_indexed is None or end_line_1_indexed is None:
        _log(f"AST: Function '{name}' not found or parse error during removal. Source unchanged.")
        return src

    lines = normalized_src.splitlines(keepends=True)
    start_idx_0_indexed = start_line_1_indexed - 1
    end_idx_exclusive_0_indexed = end_line_1_indexed

    if not (0 <= start_idx_0_indexed < len(lines) and \
            0 < end_idx_exclusive_0_indexed <= len(lines) and \
            start_idx_0_indexed < end_idx_exclusive_0_indexed):
         _log(f"AST: Calculated line indices for removing '{name}' (start_0idx={start_idx_0_indexed}, end_0idx_excl={end_idx_exclusive_0_indexed}) are out of bounds for {len(lines)} lines. Source unchanged.")
         return src

    prefix_lines = lines[:start_idx_0_indexed]
    suffix_lines = lines[end_idx_exclusive_0_indexed:]

    # Reconstruct the source, managing blank lines between prefix and suffix
    prefix_str = "".join(prefix_lines).rstrip('\n') # Prefix without any of its original trailing newlines
    suffix_str = "".join(suffix_lines).lstrip('\n') # Suffix without any of its original leading newlines

    if not prefix_str.strip() and not suffix_str.strip(): # Both were empty or all whitespace
        return ""

    if not prefix_str.strip(): # Prefix was empty or all whitespace, suffix has content
        # Suffix becomes the new start of the file. Ensure it's clean.
        return suffix_str.lstrip() # Remove any leading blank lines from suffix

    if not suffix_str.strip(): # Suffix was empty or all whitespace, prefix has content
        # Prefix is the new end of the file. Ensure it ends with one newline.
        return prefix_str + "\n"

    # Both prefix and suffix have content. Aim for PEP 8 spacing.
    # Typically 2 blank lines before a top-level function or class.

    # We need prefix_str + \n (from prefix) + \n (blank line 1) + \n (blank line 2) + suffix_str
    # This means 3 newlines total between content of prefix and content of suffix.
    return prefix_str + "\n\n\n" + suffix_str

def _remove_method(src: str, cls_name: str, meth_name: str) -> str:
    """
    Remove a method `meth_name` inside class `cls_name` using AST,
    including its def line and any @decorators above.
    Aims to maintain reasonable PEP 8 spacing (usually 1 blank line between methods).
    """
    normalized_src = src.replace('\r\n', '\n').replace('\r', '\n')
    start_line_1_indexed, end_line_1_indexed = get_method_extent_ast(normalized_src, cls_name, meth_name)

    if start_line_1_indexed is None or end_line_1_indexed is None:
        _log(f"AST: Method '{cls_name}.{meth_name}' not found or parse error during removal. Source unchanged.")
        return src

    lines = normalized_src.splitlines(keepends=True)
    start_idx_0_indexed = start_line_1_indexed - 1
    end_idx_exclusive_0_indexed = end_line_1_indexed

    if not (0 <= start_idx_0_indexed < len(lines) and \
            0 < end_idx_exclusive_0_indexed <= len(lines) and \
            start_idx_0_indexed < end_idx_exclusive_0_indexed):
         _log(f"AST: Calculated line indices for removing '{cls_name}.{meth_name}' (start_0idx={start_idx_0_indexed}, end_0idx_excl={end_idx_exclusive_0_indexed}) are out of bounds for {len(lines)} lines. Source unchanged.")
         return src

    prefix_lines = lines[:start_idx_0_indexed]
    suffix_lines = lines[end_idx_exclusive_0_indexed:]

    prefix_str = "".join(prefix_lines).rstrip('\n') 
    suffix_str = "".join(suffix_lines).lstrip('\n')

    if not prefix_str.strip() and not suffix_str.strip(): 
        # This implies the class itself might become empty or only contained this method.
        # Ideally, if a class body becomes empty, 'pass' should be inserted.
        # For now, if the entire result is whitespace, return empty or 'pass' on the class line.
        # This is complex; current result is just empty string if all was whitespace.
        return "" 

    if not prefix_str.strip(): 
        # This means the removed method was the first thing in the class body (after 'class ...:').
        # The suffix_str is the rest of the methods.
        # We need to ensure the class line (part of original prefix_lines, now gone from prefix_str)
        # is followed correctly by suffix_str. This case is tricky with simple rstrip/lstrip.
        # A simpler safe return:
        # Reconstruct class header + suffix. The prefix_str is likely just the class header.
        # For now, let's assume prefix_str (if non-blank) ends with the class definition line.
        if "".join(prefix_lines).strip().endswith(":"): # Likely class header
             return "".join(prefix_lines) + suffix_str # Preserve original newlines after class header
        return suffix_str.lstrip() # Fallback

    if not suffix_str.strip(): 
        # Removed method was the last thing in the class.
        # Prefix ends with the content before the removed method.
        # Ensure prefix ends with one newline.
        return prefix_str + "\n"

    # Both prefix and suffix (within the class) have content.
    # PEP 8: Usually one blank line between methods.
    # prefix_str (content before) + \n (end of prefix) + \n (blank line) + suffix_str (next method)
    return prefix_str + "\n\n" + suffix_str

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
    pt = meta["patch_type"]

    file_existed_originally = target.exists()
    src = "" 

    if not file_existed_originally:
        is_add_or_replace = pt.startswith("add_") or pt.startswith("replace_")
        if is_add_or_replace:
            _log("Target file {} does not exist. Creating for patch type '{}'.", target.name, pt)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("", encoding='utf-8')
            src = ""
        else: 
            raise FileNotFoundError(f"Target file '{target}' not found for patch type '{pt}'.")
    else:
        if not dry:
             _log("Backup → {}", _backup(target))
        src = target.read_text(encoding='utf-8')
        # DEBUG print moved to only when file exists, to avoid printing for newly created files.
        print(f"DEBUG apply_patch: Target path is '{target.resolve()}'") 
        print(f"DEBUG apply_patch: Read source for {target.name}:\n>>>\n{src}\n<<<END_OF_SRC\n") 

    block = dedent(code).rstrip("\n") if code else ""
    # Pass src to _remove_block, not lines, so it can normalize and split
    # lines_list_for_remove_block = src.splitlines(keepends=True) # Original lines for remove_block if needed

    new_src = None

    # --- Refined _remove_block Helper for anchor_start/anchor_end ---
    # This helper is now specific to how VibeSpec remove_block is defined.
    def _perform_anchor_block_removal(source_text: str, start_pattern: str, end_pattern: str) -> str:
        # Normalize line endings for consistent processing
        normalized_text = source_text.replace('\r\n', '\n').replace('\r', '\n')
        lines_list = normalized_text.splitlines(keepends=True)

        start_re = re.compile(start_pattern)
        end_re = re.compile(end_pattern)

        output_lines = []
        in_removal_block = False
        start_anchor_found = False

        for line_content in lines_list:
            if not start_anchor_found and start_re.search(line_content):
                # Found the start anchor. Start skipping lines (including this one).
                in_removal_block = True
                start_anchor_found = True 
                # Do not append this line
                continue 

            if in_removal_block:
                # We are inside the block to be removed.
                if end_re.search(line_content):
                    # Found the end anchor. Stop skipping from the *next* line.
                    # This end anchor line itself is also removed.
                    in_removal_block = False
                    # Do not append this line
                    continue
                # Still in removal block, and it's not the end anchor line.
                # Do not append this line.
                continue

            # If not in removal block, append the line.
            output_lines.append(line_content)

        return "".join(output_lines)

    # --- Patch Type Logic ---
    try:
        if pt == "add_function":
            m = re.search(r"^\s*(?:async\s+)?def\s+([\w_]+)", block, re.MULTILINE)
            if not m: raise ValueError(f"add_function: Cannot find function name in code block.")
            name_from_code = m.group(1)
            new_src = _replace_function(src, name_from_code, block)
        elif pt == "add_method":
            cls = meta.get("class")
            if not cls: raise ValueError("add_method requires 'class' metadata.")
            m = re.search(r"^\s*(?:async\s+)?def\s+([\w_]+)", block, re.MULTILINE)
            if not m: raise ValueError(f"add_method: Cannot find method name in code block.")
            name_from_code = m.group(1)
            new_src = _replace_method(src, cls, name_from_code, block)
        elif pt == "add_class":
            m = re.search(r"^\s*class\s+([\w_]+)", block, re.MULTILINE)
            if not m: raise ValueError("add_class: Cannot find class name in code block.")
            cls_name_from_code = m.group(1)
            new_src = _replace_class(src, cls_name_from_code, block)
        elif pt == "add_block":
            # This logic for add_block seems mostly okay.
            # It operates on 'lines' derived from 'src.splitlines(keepends=True)' at the start of apply_patch.
            # For consistency, it might be better if add_block also worked on normalized_src if it did complex parsing.
            # However, it's mostly line insertion, so current 'lines' might be fine.
            current_lines_for_add_block = src.splitlines(keepends=True) # Use fresh split for add_block
            pos = meta.get("position", "end")
            anchor = meta.get("anchor")
            if pos == "start":
                sep = "\n\n" if src.strip() else "\n"
                new_src = block.rstrip() + sep + src
            elif pos in ("before", "after"):
                if not anchor: raise ValueError("add_block before/after requires 'anchor' regex.")
                pat = re.compile(anchor)
                match_indices = [i for i, ln_idx in enumerate(current_lines_for_add_block) if pat.search(ln_idx)]
                if not match_indices:
                     _log(f"Warning: add_block anchor '{anchor}' not found in {target.name}. Appending to end.")
                     pos = "end" 
                else:
                     idx = match_indices[0]
                     if pos == "after":
                         anchor_indent = len(current_lines_for_add_block[idx]) - len(current_lines_for_add_block[idx].lstrip()) if current_lines_for_add_block[idx].strip() else float('inf')
                         j = idx + 1
                         while j < len(current_lines_for_add_block):
                             ln_loop = current_lines_for_add_block[j]; ws = len(ln_loop) - len(ln_loop.lstrip()) if ln_loop.strip() else float('inf')
                             if ln_loop.strip() and ws <= anchor_indent: break
                             j += 1
                         idx = j
                     new_lines_list = list(current_lines_for_add_block) # Important: operate on a copy
                     inserted = False
                     if idx > 0 and new_lines_list[idx-1].strip():
                         new_lines_list.insert(idx, "\n"); idx += 1; inserted = True
                     new_lines_list.insert(idx, block.rstrip() + "\n"); idx += 1; inserted = True
                     if idx < len(new_lines_list) and new_lines_list[idx].strip():
                         new_lines_list.insert(idx, "\n"); inserted = True
                     elif idx == len(new_lines_list):
                          new_lines_list.append("\n"); inserted = True
                     if inserted: new_src = "".join(new_lines_list)
                     else: new_src = src
            if pos == "end": # Handles explicit 'end' or fallback
                 if new_src is None: # Only if not already set by before/after fallback
                     sep = "\n\n" if src.strip() else "\n"
                     new_src = src.rstrip("\n") + sep + block.rstrip() + "\n"
        elif pt == "remove_function":
            name = meta.get("name")
            if not name: raise ValueError("remove_function requires 'name'.")
            new_src = _remove_function(src, name)
        elif pt == "remove_method":
            cls = meta.get("class")
            name = meta.get("name")
            if not cls or not name: raise ValueError("remove_method requires 'class' and 'name'.")
            new_src = _remove_method(src, cls, name)
        elif pt == "remove_class":
            cls_rm = meta.get("name")
            if not cls_rm: raise ValueError("remove_class requires 'name'.")
            new_src = _remove_class(src, cls_rm)
        elif pt == "remove_block":
            start_pat = meta.get("anchor_start")
            end_pat = meta.get("anchor_end")
            if not start_pat or not end_pat: raise ValueError("remove_block requires 'anchor_start' and 'anchor_end'.")
            new_src = _perform_anchor_block_removal(src, start_pat, end_pat) # Use the new helper
        elif pt == "replace_function":
            target_name = meta.get("name")
            if not target_name: raise ValueError("replace_function requires 'name' metadata.")
            if not block.strip(): raise ValueError("replace_function requires a non-empty code block.")
            new_src = _replace_function(src, target_name, block)
        elif pt == "replace_block":
             start_pat = meta.get("anchor_start"); end_pat = meta.get("anchor_end")
             if start_pat and end_pat:
                  # This logic should be similar to remove_block + add_block
                  # For now, let's ensure remove_block works. replace_block might need its own AST-aware approach or careful line manipulation.
                  # A simple approach: remove then add.
                  temp_src_after_removal = _perform_anchor_block_removal(src, start_pat, end_pat)
                  # Now, how to insert `block` where the old block was?
                  # This is tricky without knowing the exact line numbers of the removal.
                  # For now, this will effectively append if the block isn't found by a subsequent add_block-like logic.
                  # This part needs a more robust strategy if replace_block is to be fully reliable by anchor.
                  # A simple replace_block would be to find the start_anchor, remove until end_anchor, then insert.

                  # Simpler interim logic for replace_block:
                  # Find the start of the block to replace
                  normalized_temp_src = src.replace('\r\n', '\n').replace('\r', '\n')
                  temp_lines = normalized_temp_src.splitlines(keepends=True)

                  start_re = re.compile(start_pat); end_re = re.compile(end_pat)
                  start_idx_rb = -1; end_idx_rb = -1

                  for i, ln_enum in enumerate(temp_lines):
                       if start_idx_rb == -1 and start_re.search(ln_enum): start_idx_rb = i
                       if start_idx_rb != -1 and i >= start_idx_rb and end_re.search(ln_enum): 
                           end_idx_rb = i + 1 # end_idx is exclusive for slicing
                           break
                  if start_idx_rb != -1 and end_idx_rb != -1:
                       new_lines_list_rb = list(temp_lines)
                       # Ensure proper newline handling for the inserted block
                       replacement_content = [block.rstrip() + "\n"] 
                       # Add a blank line before if the preceding line is not blank
                       if start_idx_rb > 0 and new_lines_list_rb[start_idx_rb-1].strip():
                           replacement_content.insert(0, "\n")
                       # Add a blank line after if the succeeding line is not blank (and exists)
                       if end_idx_rb < len(new_lines_list_rb) and new_lines_list_rb[end_idx_rb].strip():
                           replacement_content.append("\n")
                       elif not replacement_content[-1].endswith("\n\n"): # Ensure at least one trailing newline for block
                            replacement_content[-1] = replacement_content[-1].rstrip('\n') + '\n'


                       new_lines_list_rb[start_idx_rb:end_idx_rb] = replacement_content
                       new_src = "".join(new_lines_list_rb)
                  else:
                       _log(f"Warning: replace_block anchors '{start_pat}'...'{end_pat}' not found in {target.name}. Appending.")
                       sep = "\n\n" if src.strip() else "\n"
                       new_src = src.rstrip("\n") + sep + block.rstrip() + "\n"
             else:
                  raise ValueError("replace_block requires 'anchor_start' and 'anchor_end' for reliable operation.")

        if new_src is None:
             raise ValueError(f"Patch type '{pt}' was not handled correctly or failed for file '{target.name}'. No changes applied by this patch.")

    except Exception as e:
         _log(f"Error applying patch ({pt}) to {target.name}: {e}") 
         raise

    if dry:
        print(new_src.rstrip())
        return new_src

    try:
        target.write_text(new_src, encoding='utf-8')
        _log("Patch applied to {}", target)
    except Exception as write_err:
         _log(f"FATAL: Failed to write patched content to {target}: {write_err}")
         raise

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
