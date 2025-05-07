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

    VibeSpec v1.6 supports the following patch types. Decorators are handled natively for all relevant types.

    **Addition of new elements:**
    - `add_function`: Adds a new top-level function. The name is taken from the function definition in the code block. It is intended for adding genuinely new functions.
    - `add_method`: Adds a new method to a specified class. The name is taken from the method definition in the code block.
    - `add_class`: Adds a new class definition. The name is taken from the class definition in the code block.
    - `add_block`: Adds a generic block of code at a specified position (e.g., `start`, `end`, `before` an anchor, `after` an anchor).

    **Replacement of existing elements:**
    - `replace_function`: Replaces an existing top-level function. Requires `name` metadata to identify the target function.
    - `replace_method`: Replaces an existing method in a class. Requires `class` and `name` metadata.
    - `replace_class`: Replaces an existing class definition. Requires `name` metadata.
    - `replace_block`: Replaces a block of code identified by `anchor_start` and `anchor_end` metadata.

    **Removal of elements:**
    - `remove_function`: Removes a top-level function. Requires `name` metadata.
    - `remove_method`: Removes a method from a class. Requires `class` and `name` metadata.
    - `remove_class`: Removes a class definition. Requires `name` metadata.
    - `remove_block`: Removes a block of code identified by `anchor_start` and `anchor_end` metadata.

    Code blocks for `add_*` and `replace_*` types may include decorator lines. When matching existing definitions for `replace_*` or `remove_*` operations by `name`, the system correctly identifies the full extent of the named element, including any decorators.

# Patch 2: Update the "Example – Replace a decorated method"
patch_type: replace_block
file: VibePatchSpec_v1.6.md
anchor_start: "^\\*\\*Example – Replace a decorated method\\*\\*" # Start with the title
anchor_end: "^---" # End before the next horizontal rule or section
--- code: |
    **Example – Replace a decorated method**

    ```yaml
    # VibeSpec: 1.6
    patch_type: replace_method # Corrected patch type
    file: models.py
    class: UserProfile # Example class name
    name: update_activity_summary # Example method name
    --- code: |
        @celery_task(rate_limit='10/m')
        @db_transaction
        def update_activity_summary(self, recent_threshold_days=7):
            # New, optimized implementation
            recent_activity = self.get_activity(days=recent_threshold_days)
            self.summary_score = sum(event.score for event in recent_activity)
            self.last_summary_update = timezone.now()
            self.save(update_fields=['summary_score', 'last_summary_update'])
            logger.info(f"Activity summary updated for user {self.user_id}.")

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

