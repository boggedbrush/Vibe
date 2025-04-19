# ========= .github/workflows/vibe-ci.yml =========
mkdir -p .github/workflows
cat > .github/workflows/vibe-ci.yml <<'EOF'
name: Vibe Patch CI

on:
  push:
    branches: [ main ]
  pull_request:

jobs:
  lint-spec:
    runs-on: ubuntu-latest
    steps:
      - name: ⬇️  Checkout
        uses: actions/checkout@v4

      - name: 🐍  Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: 📦  Install runtime deps
        run: python -m pip install --upgrade pip

      - name: ✅  Lint sample patch
        run: python vibe_cli.py lint tests/sample_patch.vibe
EOF
# ========= tests/sample_patch.vibe =========
mkdir -p tests
cat > tests/sample_patch.vibe <<'EOF'
# VibeSpec: 1.0
patch_type: add_function
file: demo.py
--- code: |
    def hello():
        print("Hello from CI!")
EOF
# ========= demo.py =========
echo "pass" > demo.py
