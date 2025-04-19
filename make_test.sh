cd tests

# Define the base hello.py content once
read -r -d '' HELLO << 'EOF'
# hello.py
def greet(name):
    print(f"Hello, {name}!")

class Greeter:
    def __init__(self, name):
        print(f'Hello {name}')
EOF

# Create each test folder and write hello.py
for dir in add_block_start add_block_end add_block_default add_block_before_anchor add_block_after_anchor; do
  mkdir -p "$dir"
  printf "%s\n" "$HELLO" > "$dir/hello.py"
done

# add_block_start
cat > add_block_start/add_block_start.vibe << 'EOF'
# VibeSpec: 1.2
patch_type: add_block
file: hello.py
position: start
--- code: |
  # >>> Inserted at top
  import logging
  logging.basicConfig(level=logging.INFO)
EOF

# add_block_end
cat > add_block_end/add_block_end.vibe << 'EOF'
# VibeSpec: 1.2
patch_type: add_block
file: hello.py
position: end
--- code: |
  # >>> Inserted at EOF
  if __name__ == "__main__":
      greet("World")
EOF

# add_block_default (position omitted = end)
cat > add_block_default/add_block_default.vibe << 'EOF'
# VibeSpec: 1.2
patch_type: add_block
file: hello.py
--- code: |
  # >>> Default append at EOF
  print("Finished patch tests")
EOF

# add_block_before_anchor
cat > add_block_before_anchor/add_block_before_anchor.vibe << 'EOF'
# VibeSpec: 1.2
patch_type: add_block
file: hello.py
position: before
anchor: "^class Greeter"
--- code: |
  # >>> Inserted before Greeter class
  def helper():
      return True
EOF

# add_block_after_anchor
cat > add_block_after_anchor/add_block_after_anchor.vibe << 'EOF'
# VibeSpec: 1.2
patch_type: add_block
file: hello.py
position: after
anchor: "^def greet"
--- code: |
  # >>> Inserted after the greet() function
  greet = wrap_with_logging(greet)
EOF

echo "All add_block test directories created."
