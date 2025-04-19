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
    miss = req - set(meta.keys())
    if miss:
        raise ValueError(f"Missing meta keys: {sorted(miss)}")
    if meta.get("VibeSpec") != "1.0":
        raise ValueError(f"Unsupported VibeSpec version: {meta.get('VibeSpec')}")

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
    return trimmed + "\n\n" + block.rstrip() + "\n"

def _replace_function(src: str, name: str, block: str) -> str:
    pat = re.compile(rf"^\s*def\s+{re.escape(name)}\s*\(")
    m = pat.search(src)
    if not m:
        return _append_func_before_class(src, block)
    lines = src.splitlines(keepends=True)
    start = src[:m.start()].count("\n")
    indent = len(m.group(0)) - len(m.group(0).lstrip())
    end = start + 1
    print(len(lines))
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
#  Apply patch
# =============================================================================

def apply_patch(meta: Dict[str, Any], code: str, repo: Path, dry: bool=False):
    target = repo / meta["file"]
    if not target.exists():
        raise FileNotFoundError(target)
    _log("Backup → {}", _backup(target))
    src = target.read_text()
    pt = meta["patch_type"]
    if pt == "add_function":
        name = re.match(r"def\s+(\w+)", code.lstrip()).group(1)
        new_src = _replace_function(src, name, code)
    elif pt == "add_method":
        cls = meta.get("class") or ""
        name = re.match(r"def\s+(\w+)", code.lstrip()).group(1)
        new_src = _replace_method(src, cls, name, code)
    elif pt == "add_class":
        name = re.match(r"class\s+(\w+)", code.lstrip()).group(1)
        new_src = _replace_class(src, name, code)
    else:
        new_src = src.rstrip("\n") + "\n\n" + code.rstrip() + "\n"
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
    meta, _ = load_patch(args.patch)
    validate_spec(meta)
    _log("Lint OK ({})", meta["patch_type"])


def cmd_preview(args: argparse.Namespace) -> None:
    meta, code = load_patch(args.patch)
    validate_spec(meta)
    tgt = args.repo / meta["file"]
    tmp = Path(os.getenv("TMPDIR", "/tmp")) / f"vibe_prev_{tgt.name}"
    tmp.write_text(tgt.read_text() + "\n" + code + "\n")
    subprocess.call(["diff", "-u", str(tgt), str(tmp)])


def cmd_apply(args: argparse.Namespace) -> None:
    meta, code = load_patch(args.patch)
    validate_spec(meta)
    apply_patch(meta, code, args.repo, dry=args.dry)


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
