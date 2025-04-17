import argparse
import datetime as _dt
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Tuple

# =============================================================================
#  Lightweight logger & helpers
# =============================================================================

def _log(msg: str, *args: Any) -> None:
    """Tiny stderr logger supporting str.format placeholders."""
    print(msg.format(*args), file=sys.stderr)


def _timestamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")


# =============================================================================
#  Patch Parsing & Validation (spec v1.0)
# =============================================================================

def _clean_meta_line(line: str) -> str:
    """Strip leading comment markers & whitespace so `# key: value` works."""
    line = line.lstrip()
    if line.startswith("#"):
        line = line[1:].lstrip()
    return line


def load_patch(path: Path) -> Tuple[Dict[str, Any], str]:
    """Return (meta‑dict, code‑block) for a .vibe patch file."""
    meta: Dict[str, Any] = {}
    code_lines: list[str] = []
    in_code = False
    for raw in path.read_text().splitlines():
        line = raw.rstrip("\n")
        if line.startswith("--- code"):
            in_code = True
            continue
        if in_code:
            code_lines.append(line)
        else:
            clean = _clean_meta_line(line)
            if ":" in clean:
                k, v = clean.split(":", 1)
                meta[k.strip()] = v.strip()
    return meta, "\n".join(code_lines)


def validate_meta(meta: Dict[str, Any]) -> None:
    required = {"VibeSpec", "patch_type", "file"}
    missing = required - meta.keys()
    if missing:
        raise ValueError(f"Missing required meta keys: {sorted(missing)}")
    if meta["VibeSpec"] != "1.0":
        raise ValueError(f"Unsupported VibeSpec version: {meta['VibeSpec']}")


# =============================================================================
#  File operations
# =============================================================================

def backup_file(file_path: Path) -> Path:
    backup_dir = file_path.parent / "VibeBackups"
    backup_dir.mkdir(exist_ok=True)
    dest = backup_dir / f"{file_path.stem}_{_timestamp()}{file_path.suffix}"
    shutil.copy2(file_path, dest)
    return dest


def apply_patch(meta: Dict[str, Any], code: str, repo_root: Path, dry_run: bool = False) -> None:
    target_file = repo_root / meta["file"]
    if not target_file.exists():
        raise FileNotFoundError(target_file)

    backup_path = backup_file(target_file)
    _log("Backup created → {}", backup_path)

    new_contents = target_file.read_text() + "\n" + code + "\n"
    if dry_run:
        _log("[DRY‑RUN] Would write {} bytes to {}", len(code), target_file)
        return

    target_file.write_text(new_contents)
    _log("Patch applied successfully to {}", target_file)


# =============================================================================
#  CLI plumbing
# =============================================================================

def build_cli() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vibe", description="Vibe Patch helper (spec v1.0)")
    sub = p.add_subparsers(dest="cmd", required=True)

    lint_p = sub.add_parser("lint", help="Validate patch file against spec v1.0")
    lint_p.add_argument("patch", type=Path)

    prev_p = sub.add_parser("preview", help="Open side‑by‑side diff via $DIFFTOOL or fallback to 'diff -u'")
    prev_p.add_argument("patch", type=Path)
    prev_p.add_argument("repo", type=Path, nargs="?", default=Path.cwd())

    ap = sub.add_parser("apply", help="Lint + backup + apply patch to repo")
    ap.add_argument("patch", type=Path)
    ap.add_argument("repo", type=Path, nargs="?", default=Path.cwd())
    ap.add_argument("--dry", action="store_true")

    return p


# ---------------- CLI command handlers ----------------

def cmd_lint(args):
    meta, _ = load_patch(args.patch)
    validate_meta(meta)
    _log("Lint OK ✓  (VibeSpec {})", meta["VibeSpec"])


def _launch_diff_tool(old: Path, new: Path) -> None:
    tool_env = os.getenv("DIFFTOOL", "")
    if tool_env:
        cmd = shlex.split(tool_env) + [str(old), str(new)]
    else:
        # Fallback to git diff if available, else plain diff -u
        cmd = ["git", "--no-pager", "diff", "--no-index", str(old), str(new)] if shutil.which("git") else ["diff", "-u", str(old), str(new)]
    try:
        subprocess.call(cmd)
    except FileNotFoundError as e:
        _log("Diff tool '{}' not found. Falling back to unified diff.", cmd[0])
        subprocess.call(["diff", "-u", str(old), str(new)])


def cmd_preview(args):
    meta, code = load_patch(args.patch)
    validate_meta(meta)

    target_file = args.repo / meta["file"]
    if not target_file.exists():
        raise FileNotFoundError(target_file)

    tmp_new = Path(os.getenv("TMPDIR", "/tmp")) / f"vibe_prev_{target_file.name}"
    tmp_new.write_text(target_file.read_text() + "\n" + code + "\n")

    _launch_diff_tool(target_file, tmp_new)


def cmd_apply(args):
    meta, code = load_patch(args.patch)
    validate_meta(meta)
    apply_patch(meta, code, args.repo, dry_run=args.dry)


# =============================================================================
#  Entry point + demo behaviour
# =============================================================================

def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    cli = build_cli()
    args = cli.parse_args(argv)

    match args.cmd:
        case "lint":
            cmd_lint(args)
        case "preview":
            cmd_preview(args)
        case "apply":
            cmd_apply(args)
        case _:
            cli.error(f"Unknown command: {args.cmd}")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        _log("No arguments provided – showing help followed by demo lint…")
        main(["--help"])
        example = Path(__file__).with_name("example_patch.vibe")
        if example.exists():
            _log("\nDemo: linting {}\n------------------------------", example)
            main(["lint", str(example)])
        else:
            _log("(Place an 'example_patch.vibe' next to vibe_cli.py for an automatic demo)")
    else:
        main()
