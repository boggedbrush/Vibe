# Vibe Patch Toolkit

Iterative, human‑readable code patching via `.vibe` files, with both a CLI and a browser‑based UI.

---

## Quick start

```bash
# Lint a patch
python vibe_cli.py lint path/to/patch.vibe

# Preview changes (uses $DIFFTOOL or diff -u fallback)
python vibe_cli.py preview path/to/patch.vibe [repo_dir]

# Apply changes (backs up modified files under VibeBackups/)
python vibe_cli.py apply path/to/patch.vibe [repo_dir]

v1.x: CLI & Regression Tests

Write your patches as simple YAML + a --- code: block.
Test fixtures live under tests/; regenerate or verify with:

# (Re)generate expected outputs (optional for v1.x)
python tests/make_expected.py

# Run the full regression suite
python tests/regression_tester.py

v1.4: Name‑Only Removals

You can now remove functions, methods, or classes by name only:

# VibeSpec: 1.4
patch_type: remove_function
file: hello.py
name: farewell

# VibeSpec: 1.4
patch_type: remove_method
file: hello.py
class: Greeter
name: old_method

# VibeSpec: 1.4
patch_type: remove_class
file: hello.py
name: OldClass

Blocks can still be removed via anchors or literal match:

# VibeSpec: 1.4
patch_type: remove_block
file: hello.py
anchor_start: "^# begin-delete"
anchor_end:   "^# end-delete"

v1.5: Multi‑Patch Bundles

Bundle several patches in one .vibe file and apply them in order:

# VibeSpec: 1.5

# --- Patch 1: replace greet()
patch_type: replace_function
file: hello.py
--- code: |
    def greet(name):
        print(f"Greetings, {name}!")

# --- Patch 2: add farewell()
patch_type: add_function
file: hello.py
--- code: |
    def farewell(name):
        print(f"Goodbye, {name}!")

CLI usage remains the same:

python vibe_cli.py lint   multi.vibe
python vibe_cli.py preview multi.vibe [repo_dir]
python vibe_cli.py apply  multi.vibe [repo_dir]

v2.0‑beta: Split‑Screen UI & HTTP Wrapper

A lightweight Flask server plus Monaco diff editor:

pip install flask
python server.py --baseDir .

    Load File – pick your .py

    Load Patch – pick your .vibe (diff shows automatically)

    Accept – writes patched file under --baseDir and refreshes UI

Continuous Integration

GitHub Actions workflow (.github/workflows/v2-ci.yml) runs on push/PR:

    Checks out code

    Sets up Python & Flask

    Runs regression tests against committed .expected files

No manual regeneration needed—just commit your new fixtures and patches.

Enjoy chaining and reviewing code patches with Vibe! 🚀