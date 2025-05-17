#!/usr/bin/env python3
"""
make_expected.py  – create .expected files for each test patch in tests/*
Directory layout expected:

tests/
├─ add_function_create/
│   ├─ add_function_create.vibe
│   └─ hello.py
├─ add_function_replace/
│   ├─ add_function_replace.vibe
│   └─ hello.py
⋯

After running:
tests/
├─ add_function_create/
│   ├─ add_function_create.vibe
│   ├─ hello.py
│   └─ add_function_create.expected      <-- NEW
⋯


Usage:
    python make_expected.py

For each subdirectory in tests/, this script finds the single .vibe patch and the accompanying hello.py,
applies the patch in dry‐run mode, and writes the resulting file to <patchname>.expected in that directory.
"""
import autopep8
import sys
import importlib.util
from pathlib import Path
from typing import Tuple, Dict, Any

# Load the CLI module dynamically
REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO_ROOT / "vibe_cli.py"
spec = importlib.util.spec_from_file_location("vibe_cli", SPEC_PATH)
vibe_cli = importlib.util.module_from_spec(spec)  # type: ignore
spec.loader.exec_module(vibe_cli)          # type: ignore

TESTS_DIR = REPO_ROOT / "tests"


def process_case(case_dir: Path) -> None:
    # Expect exactly one .vibe and a hello.py in each test directory
    vibe_files = list(case_dir.glob("*.vibe"))
    source_file = case_dir / "hello.py"
    if len(vibe_files) != 1 or not source_file.exists():
        print(f"[SKIP] {case_dir.name} (needs 1 .vibe + hello.py)")
        return

    patch_path = vibe_files[0]
    # Load and validate
    meta, code = vibe_cli.load_patch(patch_path)
    try:
        vibe_cli.validate_spec(meta)
    except Exception as e:
        print(f"[ERROR] {patch_path.name}: Validation failed: {e}")
        return

    # Apply patch in dry-run mode
    try:
        new_src = vibe_cli.apply_patch(meta, code, case_dir, dry=True)
    except Exception as e:
        print(f"[ERROR] {patch_path.name}: Apply failed: {e}")
        return
    if new_src is None:
        print(f"[ERROR] {patch_path.name}: No output from dry-run")
        return

    # Write expected
    out_path = case_dir / f"{patch_path.stem}.expected"
    formatted_src = autopep8.fix_code(new_src)

    out_path.write_text(formatted_src)
    print(f"[OK]  {case_dir.name}/{out_path.name} created")


def main():
    for case in sorted(TESTS_DIR.iterdir()):
        if case.is_dir():
            process_case(case)

    print("\nDone generating expected files.")


if __name__ == "__main__":
    main()

