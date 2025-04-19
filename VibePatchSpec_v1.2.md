## VibePatchSpec v1.2

This document extends **VibePatchSpec 1.1** to include the new `add_block` patch type and refine behavior for code‑insertion outside of functions, methods, or classes.

---

### 1. Spec Version

- **VibeSpec**: `1.2`

---

### 2. Common YAML Keys

All patches require these top‑level keys:

```yaml
# VibeSpec: 1.2
patch_type: <type>
file: <relative-path-to-target-file>
```

- `VibeSpec`: must match the spec version, now `1.2`.
- `patch_type`: one of `add_function`, `add_method`, `add_class`, `add_block`.
- `file`: target file path relative to repository root.

Additional keys depend on `patch_type`.

---

### 3. Patch Types

#### 3.1. `add_function`

**Description**: Create or replace a top‑level function.

**YAML**:
```yaml
patch_type: add_function
file: hello.py
--- code: |
  def new_func(args):
      # ...
```

**Behavior**:
1. If a function with the same name exists, replace its entire block.
2. Otherwise, insert the function just before the first class definition (or at EOF if no class), with exactly one blank line:
   - **Before**: one blank line above the new function.
   - **After**: one blank line below the new function.

#### 3.2. `add_method`

**Description**: Create or replace a method inside a class.

**YAML**:
```yaml
patch_type: add_method
file: hello.py
class: Greeter
--- code: |
  def greet(self):
      print("Hi!")
```

**Behavior**:
1. If `class:` is missing or empty, error.
2. If the method exists, replace its block, preserving indentation.
3. Otherwise, append the method at the end of the class body, with exactly one blank line before and after, indented one level deeper than the class.

#### 3.3. `add_class`

**Description**: Create or replace a top‑level class.

**YAML**:
```yaml
patch_type: add_class
file: hello.py
--- code: |
  class Fareweller:
      def say_bye(self):
          print("Bye!")
```

**Behavior**:
1. If a class with the same name exists, replace its entire block.
2. Otherwise, append the class at EOF, with one blank line before the class.

#### 3.4. `add_block`

**Description**: Insert or replace a free‑form code block anywhere in the file.

**YAML**:
```yaml
patch_type: add_block
file: hello.py
position: before   # one of start, end, before, after (default: end)
anchor: "^def greet"  # required if position is before/after
--- code: |
  # free‑form snippet
  import os
```

**Behavior**:
1. **`position: start`**
   - Insert the block at the very top, before any existing lines, followed by one blank line.
2. **`position: end`** (or omitted)
   - Append the block at EOF with one blank line before it.
3. **`position: before | after` + `anchor`**
   - Find the first line matching the given regex anchor.
   - Insert the block immediately before or after that line, ensuring exactly one blank line surrounding the block.
4. If `before`/`after` with no matching anchor, fallback to EOF append.

---

### 4. Dry‑Run (CLI `--dry`)

When running with `vibe_cli.py apply --dry`, the CLI:
- **Prints** the full patched source to stdout instead of writing to disk.
- **Returns** the patched text (for programmatic use).

Example:
```bash
python vibe_cli.py apply tests/add_function.vibe --dry
```

---

### 5. Whitespace & Indentation Rules

- **Top‑level functions**: exactly one blank line before and after; maintain existing file termination newlines.
- **Methods**: indented *4 spaces* from class, with one blank line separating from existing methods.
- **Classes**: top‑level classes have one blank line before; nested structures preserve leading whitespace.
- **Free‑form blocks** (`add_block`): ensure one blank line before and after; regex anchors allow precise placement.

---

_End of VibePatchSpec v1.2._

