#!/usr/bin/env python3
"""Run all test cases under tests/* and compare patched output to .expected.

Usage:  python regression_tester.py [--tests tests]
returns non‑zero exit code if any case fails.
"""
import importlib.util
import sys
from pathlib import Path
from typing import Tuple
import argparse

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR  = REPO_ROOT / "tests"
CLI_PATH   = REPO_ROOT / "vibe_cli.py"

# Dynamically import vibe_cli so we can reuse helpers without installing as module
spec = importlib.util.spec_from_file_location("vibe_cli", CLI_PATH)
vibe_cli = importlib.util.module_from_spec(spec)  # type: ignore
spec.loader.exec_module(vibe_cli)  # type: ignore

def run_case(case_dir: Path) -> Tuple[str, bool, str]:
    """Return (case_name, pass?, message)."""
    vibe_files = list(case_dir.glob("*.vibe"))
    if len(vibe_files) != 1:
        return (case_dir.name, False, "Missing or multiple .vibe patches")
    patch_path = vibe_files[0]
    expected_files = list(case_dir.glob("*.expected"))
    if len(expected_files) != 1:
        return (case_dir.name, False, "Missing .expected output")
    expected_path = expected_files[0]
    meta, code = vibe_cli.load_patch(patch_path)
    vibe_cli.validate_spec(meta)

    # dry‑run returns None in CLI; use low‑level helpers instead to generate output
    repo_root = case_dir  # hello.py is inside the case directory
    try:
        result = vibe_cli.apply_patch(meta, code, repo_root, dry=True)
        if result is None:
            # CLI didn't return result; recompute using helpers
            original = (repo_root / meta["file"]).read_text()
            if meta["patch_type"] == "add_function":
                fn = code.lstrip().split()[1].split("(")[0]
                result = vibe_cli._replace_function(original, fn, code)
            elif meta["patch_type"] == "add_method":
                cls = meta["class"]
                meth = code.lstrip().split()[1].split("(")[0]
                result = vibe_cli._replace_method(original, cls, meth, code)
            elif meta["patch_type"] == "add_class":
                cls = code.lstrip().split()[1].split(":")[0]
                result = vibe_cli._replace_class(original, cls, code)
            else:
                sep = "\n" if original.endswith("\n") else "\n\n"
                result = original + sep + code.rstrip() + "\n"
    except Exception as e:
        return (case_dir.name, False, f"Patch application error: {e}")

    expected = expected_path.read_text()
    if result == expected:
        return (case_dir.name, True, "OK")
    else:
        return (case_dir.name, False, "Output does not match .expected")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tests", default=str(TESTS_DIR), help="Root tests directory")
    args = ap.parse_args()
    tests_root = Path(args.tests)
    total = 0
    failures = []
    for case_dir in sorted(tests_root.iterdir()):
        if not case_dir.is_dir():
            continue
        total += 1
        name, ok, msg = run_case(case_dir)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name} – {msg}")
        if not ok:
            failures.append(name)
    print("\nSummary: {} / {} passed".format(total - len(failures), total))
    if failures:
        print("Failed cases: " + ", ".join(failures))
        sys.exit(1)

if __name__ == "__main__":
    main()
