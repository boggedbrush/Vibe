# Vibe Patch Toolkit

Iterative code patching via human‑readable `.vibe` files, with both a CLI and a browser‑based UI.

## v1.x: CLI & Regression Tests

### Quick start

```bash
python vibe_cli.py lint   path/to/patch.vibe
python vibe_cli.py preview path/to/patch.vibe     # uses $DIFFTOOL or falls back to diff -u
python vibe_cli.py apply  path/to/patch.vibe      # backups to VibeBackups/

Regression suite

python make_expected.py
python tests/regression_tester.py

v1.4: Name‑Only Removals

You can now remove functions, methods, and classes by name only — no need to supply the full definition.
remove_function

# VibeSpec: 1.4
patch_type: remove_function
file: hello.py
name: farewell

Removes the def farewell(...) line and its entire indented body.
remove_method

# VibeSpec: 1.4
patch_type: remove_method
file: hello.py
class: Greeter
name: old_method

Within class Greeter:, removes def old_method(...) and its method body.
remove_class

# VibeSpec: 1.4
patch_type: remove_class
file: hello.py
name: OldClass

Deletes the class OldClass: header and its entire indented block.
remove_block

Unchanged from v1.3.

    Anchors:

anchor_start: "^# begin-delete"
anchor_end:   "^# end-delete"

Literal lines:

    --- code: |
        # begin-delete
        helper()
        # end-delete

v2.0‑beta: Split‑Screen UI & HTTP Wrapper

A browser‑based UI for visual patch review + one‑click apply.
Launch the HTTP server

pip install flask
python server.py --baseDir .

Browse to http://localhost:8000/ and use:

    Load File – select your .py file

    Load Patch – select a .vibe patch (diff shown automatically)

    Accept – applies the patch to disk under --baseDir and refreshes the UI

Continuous Integration

A GitHub Actions workflow (.github/workflows/v2-ci.yml) now checks out the repo, installs dependencies, regenerates expected files, and runs the regression suite on every push and PR.

Enjoy hacking with Vibe Patches! 🚀