import argparse
import datetime as _dt
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Tuple

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
    """Parse a .vibe patch file; return (meta, code)."""
    meta: Dict[str, Any] = {}
    code_lines: list[str] = []
    in_code = False
    for raw in path.read_text().splitlines():
        if raw.startswith("--- code"):
            in_code = True
            continue
        if in_code:
            code_lines.append(raw.rstrip("\n"))
        else:
            ln = _clean_meta(raw.rstrip("\n"))
            if ":" in ln:
                k, v = ln.split(":", 1)
                meta[k.strip()] = v.strip()
    return meta, "\n".join(code_lines)


def validate_spec(meta: Dict[str, Any]) -> None:
    req = {"VibeSpec", "patch_type", "file"}
    miss = req - meta.keys()
    if miss:
        raise ValueError(f"Missing meta keys: {sorted(miss)}")
    if meta["VibeSpec"] != "1.0":
        raise ValueError(f"Unsupported VibeSpec version: {meta['VibeSpec']}")

# =============================================================================
#  Backup helper
# =============================================================================

def _backup(target: Path) -> Path:
    d = target.parent / "VibeBackups"
    d.mkdir(exist_ok=True)
    dst = d / f"{target.stem}_{_timestamp()}{target.suffix}"
    shutil.copy2(target, dst)
    return dst

# =============================================================================
#  Code replacement helpers
# =============================================================================

def _replace_block(lines: list[str], start: int, end: int, block: str) -> list[str]:
    return lines[:start] + [block.rstrip() + "\n\n"] + lines[end:]

# ---------- functions ---------------------------------------------------------

def _append_func_before_first_class(src: str, block: str) -> str:
    class_match = re.search(r"^class\s+", src, re.MULTILINE)
    if class_match:
        idx = src[:class_match.start()].count("\n")
        lines = src.splitlines(keepends=True)
        return "".join(lines[:idx] + [block.rstrip() + "\n\n"] + lines[idx:])
    sep = "\n" if src.endswith("\n") else "\n\n"
    return src + sep + block.rstrip() + "\n"


def _replace_function(src: str, name: str, block: str) -> str:
    pat = re.compile(rf"^def\s+{re.escape(name)}\s*\(.*", re.MULTILINE)
    m = pat.search(src)
    if not m:
        return _append_func_before_first_class(src, block)
    lines = src.splitlines(keepends=True)
    start = src[:m.start()].count("\n")
    indent = len(m.group(0)) - len(m.group(0).lstrip())
    end = start + 1
    while end < len(lines):
        if lines[end].strip() and (len(lines[end]) - len(lines[end].lstrip())) <= indent:
            break
        end += 1
    return "".join(_replace_block(lines, start, end, block))

# ---------- classes -----------------------------------------------------------

def _replace_class(src: str, name: str, block: str) -> str:
    pat = re.compile(rf"^class\s+{re.escape(name)}\b.*:", re.MULTILINE)
    m = pat.search(src)
    if not m:
        sep = "\n" if src.endswith("\n") else "\n\n"
        return src + sep + block.rstrip() + "\n"
    lines = src.splitlines(keepends=True)
    start = src[:m.start()].count("\n")
    indent = 0  # top‑level class
    end = start + 1
    while end < len(lines):
        if lines[end].strip() and not lines[end].startswith(' '):
            break
        end += 1
    return "".join(_replace_block(lines, start, end, block))

# ---------- methods -----------------------------------------------------------

def _replace_method(src: str, cls: str, meth: str, block: str) -> str:
    cls_pat = re.compile(rf"^class\s+{re.escape(cls)}\b.*:", re.MULTILINE)
    cm = cls_pat.search(src)
    if not cm:
        raise ValueError(f"Class {cls} not found")
    lines = src.splitlines(keepends=True)
    c_start = src[:cm.start()].count("\n")
    c_indent = len(cm.group(0)) - len(cm.group(0).lstrip())
    c_end = c_start + 1
    while c_end < len(lines):
        if lines[c_end].strip() and (len(lines[c_end]) - len(lines[c_end].lstrip())) <= c_indent:
            break
        c_end += 1
    indent = ' ' * (c_indent + 4)
    meth_pat = re.compile(rf"^{re.escape(indent)}def\s+{re.escape(meth)}\s*\(")
    m_start = None
    for idx in range(c_start + 1, c_end):
        if meth_pat.match(lines[idx]):
            m_start = idx
            break
    # normalise indentation of incoming block
    if not block.startswith(indent):
        block = indent + block.rstrip().replace("\n", "\n" + indent)
    # ensure previous line ends with a blank line spacer when appending
    if m_start is None and lines[c_end-1].strip():
        block = "\n" + block  # prepend one blank line
    if m_start is None:
        return "".join(lines[:c_end] + [block + "\n\n"] + lines[c_end:])
    # find method end
    m_end = m_start + 1
    while m_end < c_end:
        if lines[m_end].strip() and (len(lines[m_end]) - len(lines[m_end].lstrip())) <= len(indent):
            break
        m_end += 1
    return "".join(_replace_block(lines, m_start, m_end, block))

# =============================================================================
#  Apply patch
# =============================================================================

def apply_patch(meta: Dict[str, Any], code: str, repo: Path, dry: bool=False):
    tgt = repo / meta["file"]
    if not tgt.exists():
        raise FileNotFoundError(tgt)
    _log("Backup → {}", _backup(tgt))
    src = tgt.read_text()
    pt = meta["patch_type"]
    if pt == "add_function":
        func = re.match(r"def\s+(\w+)", code.lstrip()).group(1)
        new_src = _replace_function(src, func, code)
    elif pt == "add_method":
        cls = meta.get("class") or ""
        if not cls:
            raise ValueError("'class' key required for add_method")
        meth = re.match(r"def\s+(\w+)", code.lstrip()).group(1)
        new_src = _replace_method(src, cls, meth, code)
    elif pt == "add_class":
        cls = re.match(r"class\s+(\w+)", code.lstrip()).group(1)
        new_src = _replace_class(src, cls, code)
    else:
        sep = "\n" if src.endswith("\n") else "\n\n"
        new_src = src + sep + code.rstrip() + "\n"
    if dry:
        _log("[DRY] new length {} bytes", len(new_src))
        return new_src  # return for test harness use
    tgt.write_text(new_src)
    _log("Patch applied to {}", tgt)

# =============================================================================
#  CLI
# =============================================================================

def build_cli() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vibe", description="Vibe Patch helper v1.0")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("lint").add_argument("patch", type=Path)
    pv = sub.add_parser("preview"); pv.add_argument("patch", type=Path); pv.add_argument("repo", type=Path, nargs="?", default=Path.cwd())
    ap = sub.add_parser("apply"); ap.add_argument("patch", type=Path); ap.add_argument("repo", type=Path, nargs="?", default=Path.cwd()); ap.add_argument("--dry", action="store_true")

    return p


def cmd_lint(a):
    m, _ = load_patch(a.patch); validate_spec(m); _log("Lint OK ({})", m["patch_type"])


def cmd_preview(a):
    m, code = load_patch(a.patch); validate_spec(m); tgt = a.repo / m["file"]
    tmp = Path("/tmp") / f"vibe_prev_{tgt.name}"; tmp.write_text(tgt.read_text() + "\n" + code + "\n")
    subprocess.call(["diff", "-u", str(tgt), str(tmp)])


def cmd_apply(a):
    m, code = load_patch(a.patch); validate_spec(m); apply_patch(m, code, a.repo, dry=a.dry)

# =============================================================================
#  Entrypoint
# =============================================================================

if __name__ == "__main__":
    cli = build_cli()
    args = cli.parse_args()
    if args.cmd == "lint":
        cmd_lint(args)
    elif args.cmd == "preview":
        cmd_preview(args)
    elif args.cmd == "apply":
        cmd_apply(args)
