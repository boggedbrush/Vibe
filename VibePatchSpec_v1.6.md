# VibePatchSpec v1.6

Version 1.6 adds **decorator support** for functions, methods, and classes within patches.

---

## File format

Every `.vibe` file must start with the spec header:

```yaml
# VibeSpec: 1.6
```

After that you list one or more patch sections, each with its own metadata and code block.

Decorators (`@name(...)`) may appear immediately before `def` or `class` lines in the code block. They are treated as part of the block and maintained when applying or replacing definitions.

---

## Parsing rules

1. **Header:** The first non-empty line must declare `# VibeSpec: 1.6`.
2. **Patches:** Each patch section begins at a line starting with `patch_type:`.
3. **Metadata:** Metadata lines continue until the line `--- code:`.
4. **Code block:** Everything indented under `--- code:` is the literal code block. Decorator lines (`@...`) are included as part of this block.
5. **Multi‑patch bundles:** Supported exactly as in v1.5, unchanged.

---

## Supported patch types

All patch types from v1.5 continue to be supported:

- `add_function`
- `add_method`
- `add_class`
- `add_block`
- `replace_block`
- `remove_function`
- `remove_method`
- `remove_class`
- `remove_block`

Code blocks for `add_*` and `replace_*` may include decorator lines. When matching existing definitions for `replace_*` or `remove_*`, decorator lines are skipped or treated as part of the match.

---

## Using decorators in patches

When you need to add or replace a decorated definition, include the decorator lines in the code block. The patch applier will:

- Recognize `@...` lines immediately preceding `def` or `class` as part of the block.
- Match the definition by name (ignoring decorator syntax) when replacing or removing.

**Example – Add a decorated function**

```yaml
# VibeSpec: 1.6
patch_type: add_function
file: hello.py
--- code: |
    @my_decorator(option=True)
    def decorated_greet(name):
        print(f"Hello, {name}!")
```

**Example – Replace a decorated method**

```yaml
# VibeSpec: 1.6
patch_type: replace_block
file: models.py
--- code: |
    @staticmethod
    def compute(value):
        # optimized implementation
        return value * value
```

---

## Backwards compatibility

- Patches without decorators continue to work as before.
- A `.vibe` file using `VibeSpec: 1.6` but containing no decorator lines is treated identically to v1.5.
- Existing CI, CLI, and UI workflows require no changes beyond specifying v1.6 where decorator support is needed.

---

## Version history

- **v1.0** – initial add/replace definitions
- **v1.2** – support for add_block
- **v1.4** – name‑only removals
- **v1.5** – multi‑patch bundles
- **v1.6** – decorator support for functions, methods, and classes

