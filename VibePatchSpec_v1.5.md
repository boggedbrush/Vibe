# VibePatchSpec v1.5

Version 1.5 adds **multi‑patch bundles**: you may put more than one patch in a single `.vibe` file and apply them in sequence.

---

## File format

Every `.vibe` file must start with the spec header:

```yaml
# VibeSpec: 1.5

After that you list one or more patch sections, each with its own metadata and code block:

# VibeSpec: 1.5

# --- Patch #1: replace greet() in foo.py
patch_type: replace_function
file: foo.py
--- code: |
    def greet(name):
        print(f"Greetings, {name}!")

# --- Patch #2: add farewell() to foo.py
patch_type: add_function
file: foo.py
--- code: |
    def farewell(name):
        print(f"Goodbye, {name}!")

Parsing rules

    The first non‑empty line must declare # VibeSpec: 1.5.

    Each patch section begins at a line starting with patch_type:.

    Metadata lines continue until the line --- code:.

    Everything indented under --- code: is the literal code block.

    Blank lines or comment dividers (# --- …) between patches are optional.

Supported patch types

All patch types from v1.4 are supported inside a multi‑patch bundle:

    add_function

    add_method

    add_class

    add_block

    remove_function

    remove_method

    remove_class

    remove_block

Each patched in the order it appears in the file.
Backwards compatibility

    A .vibe file with only one patch (and VibeSpec: 1.0–1.4) continues to work as before.

    A .vibe with VibeSpec: 1.5 but only one patch is treated just like v1.4.

Version history

    v1.0 – initial add/replace

    v1.2 – add_block

    v1.4 – name‑only removals

    v1.5 – multi‑patch bundles


---

```markdown
# Vibe Patch Toolkit

…your existing intro…

## v1.5: Multi‑Patch Bundles

You can now group multiple patches in a single `.vibe` file. The CLI (`lint`, `preview`, `apply`) and UI will parse and apply them in order.

### Example

```yaml
# VibeSpec: 1.5

# 1) Replace greet()
patch_type: replace_function
file: hello.py
--- code: |
    def greet(name):
        print(f"Greetings, {name}!")

# 2) Add farewell()
patch_type: add_function
file: hello.py
--- code: |
    def farewell(name):
        print(f"Goodbye, {name}!")

CLI

# Validate all patches
python vibe_cli.py lint path/to/multi.vibe

# Preview all in sequence
python vibe_cli.py preview path/to/multi.vibe [repo_dir]

# Apply all at once
python vibe_cli.py apply path/to/multi.vibe [repo_dir]

Browser UI

    Load File – pick your .py.

    Load Patch – pick your multi‑patch .vibe (diff shown automatically).

    Accept – commits all patches to disk.

Continuous Integration

Your existing CI workflow will now also validate multi‑patch bundles. No changes needed—just commit your .vibe fixtures and run:

python tests/regression_tester.py

Enjoy chaining patches atomically with v1.5! 🚀