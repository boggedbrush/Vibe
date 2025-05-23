#!/usr/bin/env python3
import difflib
import sys
import os
from pathlib import Path
import tempfile
import shutil
import argparse
import autopep8
import re

# Ensure the project root (one level up) is on sys.path so we can import vibe_cli
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import vibe_cli

TESTS_DIR = Path(__file__).parent

def enforce_two_blank_lines(src: str) -> str:
    # Ensure there are exactly two blank lines before top-level defs/classes
    # This looks for lines that start a def/class at zero indentation
    # and ensures two blank lines before it.
    
    lines = src.splitlines()
    new_lines = []
    for i, line in enumerate(lines):
        if re.match(r'^(def|class) ', line):
            # Check previous two lines
            prev_lines = new_lines[-2:] if len(new_lines) >= 2 else new_lines
            # Count how many blank lines before current line
            blank_count = 0
            for prev_line in reversed(prev_lines):
                if prev_line.strip() == '':
                    blank_count += 1
                else:
                    break
            needed = 2 - blank_count
            if needed > 0:
                new_lines.extend([''] * needed)
        new_lines.append(line)
    return '\n'.join(new_lines)


def show_difference(str1, str2):
    """Prints the differences between two strings."""
    diff = difflib.unified_diff(str1.splitlines(keepends=True), str2.splitlines(keepends=True))
    return ''.join(diff)

def run_case(case_dir: Path):
    patch_paths = list(case_dir.glob("*.vibe"))
    hello_path  = case_dir / "hello.py"
    if len(patch_paths) != 1 or not hello_path.exists():
        print(f"[SKIP] {case_dir.name} (needs 1 .vibe + hello.py)")
        return

    patch_path    = patch_paths[0]
    expected_path = case_dir / f"{patch_path.stem}.expected"

    # Read original and patch sources
    hello_src = hello_path.read_text()
    patch_src = patch_path.read_text()

    # Batch‑aware loading of one or more patches
    patches = vibe_cli.load_patches(patch_path)

    # Apply each patch in memory, chaining the results
    curr_src = hello_src
    for meta, code in patches:
        vibe_cli.validate_spec(meta)
        # Write current source to a temp hello.py for apply_patch to read
        tmpdir  = Path(tempfile.mkdtemp())
        tmpfile = tmpdir / "hello.py"
        tmpfile.write_text(curr_src)
        # Run apply_patch in dry‑run mode to get the new source
        curr_src = vibe_cli.apply_patch(meta, code, tmpdir, dry=True)
        shutil.rmtree(tmpdir)

    got = curr_src
    exp = expected_path.read_text() if expected_path.exists() else ""
    exp = autopep8.fix_code(exp, options={'aggressive': 1}).rstrip()
    got = enforce_two_blank_lines(got)
    exp = enforce_two_blank_lines(exp)

    if got == exp:
        print(f"[PASS] {case_dir.name} – OK")
        return True
    else:
        print(f"[FAIL] {case_dir.name} – Output does not match .expected")
        print(show_difference(got, exp))
        print("\nOriginal code\n```python")
        print(hello_src.rstrip("\n"))
        print("```\n")
        print("Vibe Patch\n```yaml")
        print(patch_src.rstrip("\n"))
        print("```\n")
        print("Expected\n```python")
        print(exp.rstrip("\n"))
        print("```\n")
        print("Got\n```python")
        print(got.rstrip("\n"))
        print("```\n")
        # Compute and print a unified diff
        print("Unified diff (expected → got):")
        diff = difflib.unified_diff(
            exp.splitlines(keepends=True),
            got.splitlines(keepends=True),
            fromfile="expected",
            tofile="got",
            lineterm=""
        )
        for line in diff:
            # colorize removals/additions if you like, or just raw
            line = line.replace(' ', '_')
            print(line.strip())

        print()  # final newline        
        return False

def main():
    parser = argparse.ArgumentParser(description="Run regression tests")
    parser.add_argument('--unit_test_dir', default=None,
                        help="Directory containing unit test cases")
    args = parser.parse_args()
    results = []
    if args.unit_test_dir:
        cases = [Path(args.unit_test_dir)]
    else:
        cases = sorted(TESTS_DIR.iterdir())
    for case in cases:
        if case.is_dir():
            result = run_case(case)
            results.append([result, case.name])
    print("Done.")
    n_pass = 0
    for pass_fail, name in results:
        if pass_fail is None:
            pass_fail = False
        print(f"{['❌', '✅'][pass_fail]} {name}")
        n_pass += pass_fail
    if n_pass == len(results):
        print(f"{n_pass}/{len(results)} tests passed. 🎉")
    else:
        print(f"{n_pass}/{len(results)} tests passed. 😱")
        
    if n_pass == len(results):
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
