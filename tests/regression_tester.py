#!/usr/bin/env python3
import sys
import os
from pathlib import Path
import tempfile
import shutil

# Ensure the project root (one level up) is on sys.path so we can import vibe_cli
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import vibe_cli

TESTS_DIR = Path(__file__).parent

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

    if got == exp:
        print(f"[PASS] {case_dir.name} – OK")
        return True
    else:
        print(f"[FAIL] {case_dir.name} – Output does not match .expected")
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
        return False
def main():
    results = []
    for case in sorted(TESTS_DIR.iterdir()):
        if case.is_dir():
            result = run_case(case)
            results.append([result, case.name])
    print("Done.")
    n_pass = 0
    for pass_fail, name in results:
        print(f"{['❌', '✅'][pass_fail]} {name}")
        n_pass += pass_fail
    print(f"{n_pass}/{len(results)} tests passed.")
    if n_pass == len(results):
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
