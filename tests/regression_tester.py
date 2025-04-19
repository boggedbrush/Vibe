#!/usr/bin/env python3
import sys
import os
from pathlib import Path

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

    hello_src = hello_path.read_text()
    patch_src = patch_path.read_text()
    meta, code = vibe_cli.load_patch(patch_path)
    vibe_cli.validate_spec(meta)
    got = vibe_cli.apply_patch(meta, code, case_dir, dry=True)
    exp = expected_path.read_text() if expected_path.exists() else ""

    if got == exp:
        print(f"[PASS] {case_dir.name} – OK")
        out = True
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
        out = False
    return out
def main():
    results = []
    for case in sorted(TESTS_DIR.iterdir()):
        if case.is_dir():
            result = run_case(case)
            results.append([result, case.name])
    print("Done.")
    n_pass = 0
    for pass_fail, name in results:
        print(f"[{['FAIL', 'PASS'][pass_fail]}]:{name}")
        n_pass += pass_fail
    print(f"{n_pass}/{len(results)} tests passed.")
    sys.exit(0)

if __name__ == "__main__":
    main()
