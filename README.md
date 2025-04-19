## v2.0‑beta: Split‑Screen UI & HTTP Wrapper

A brand‑new browser‑based UI for visual patch review + one‑click apply.

### Launch the HTTP server

```bash
pip install flask
python server.py --baseDir .

This serves the UI at http://localhost:8000/.
Using the UI

    Load File – pick your .py file

    Load Patch – pick a .vibe patch (dry‑run & diff shown automatically)

    Accept – applies the patch to disk under --baseDir and refreshes the UI

Running regression tests

python make_expected.py
python tests/regression_tester.py

Continuous integration

We’ve added a GitHub Actions workflow (see .github/workflows/v2-ci.yml) that installs dependencies, runs make_expected.py, and verifies every patch case on each push or PR.


---

### 2. Create **.github/workflows/v2-ci.yml**

Create the folder if needed and then the file:

```bash
mkdir -p .github/workflows
cat > .github/workflows/v2-ci.yml << 'EOF'
name: Vibe Patch v2 CI

on:
  push:
    branches: [ main ]
  pull_request:

jobs:
  build-and-test:
    runs-on: ubuntu-latest

    steps:
      - name: ⬇️ Check out
        uses: actions/checkout@v4

      - name: 🐍 Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: 📦 Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install flask

      - name: ✅ Run regression tests
        run: python tests/regression_tester.py