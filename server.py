#!/usr/bin/env python3
import os
import tempfile
import argparse
import shutil
import subprocess
from pathlib import Path

from flask import Flask, request, send_from_directory, Response, jsonify

import vibe_cli

# -----------------------------------------------------------------------------
#  Parse command‑line args
# -----------------------------------------------------------------------------
parser = argparse.ArgumentParser(description="Run Vibe Patch HTTP server")
parser.add_argument(
    "--baseDir",
    default=".",
    help="Base directory under which patches are applied (default: project root)"
)
parser.add_argument(
    "--host",
    default="0.0.0.0",
    help="Host to bind the Flask app (default: 0.0.0.0)"
)
parser.add_argument(
    "--port",
    type=int,
    default=8000,
    help="Port to listen on (default: 8000)"
)
args = parser.parse_args()
BASE_DIR = Path(args.baseDir).resolve()

# -----------------------------------------------------------------------------
#  Flask setup
# -----------------------------------------------------------------------------
app = Flask(__name__, static_folder="ui", static_url_path="")

# Serve the UI at /
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "vibe_diff.html")

# -----------------------------------------------------------------------------
#  Apply (preview) route – supports multi‑patch bundles
# -----------------------------------------------------------------------------
@app.route('/apply', methods=['POST'])
def apply_route():
    # Load patch text from JSON or form
    data = {}
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        pass
    patch_text = data.get('patch') or request.form.get('patch')
    if not patch_text:
        return "Missing 'patch' payload (expecting JSON or form‑field 'patch')", 400

    # 1) Dump the uploaded .vibe into a temp file
    tmpdir     = Path(tempfile.mkdtemp())
    patch_file = tmpdir / "upload.vibe"
    patch_file.write_text(patch_text)

    # 2) Parse out one or more patches
    patches = vibe_cli.load_patches(patch_file)

    # 3) Copy each target file into tmpdir
    for meta, _ in patches:
        src = BASE_DIR / meta["file"]
        dst = tmpdir   / meta["file"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text())

    # 4) Apply all patches in dry‑run mode
    vibe_cli.apply_patches(patches, tmpdir, dry=False)

    # 5) Read back each patched file
    results = {}
    for meta, _ in patches:
        fn = meta["file"]
        results[fn] = (tmpdir / fn).read_text()

    # 6) Cleanup and respond
    shutil.rmtree(tmpdir)
    return jsonify(results), 200

# -----------------------------------------------------------------------------
#  Save (commit) route – single‐patch only
# -----------------------------------------------------------------------------
@app.route("/save", methods=["POST"])
def save_route():
    payload = request.get_json(force=True) or {}
    patch = payload.get("patch")
    if not patch:
        return "Missing 'patch' in JSON", 400

    # Write the patch to a temp file so we can parse it
    with tempfile.NamedTemporaryFile(mode="w", suffix=".vibe", delete=False) as tf:
        tf.write(patch)
        tmp_path = Path(tf.name)
    try:
        meta, code = vibe_cli.load_patch(tmp_path)
        vibe_cli.validate_spec(meta)
        vibe_cli.apply_patch(meta, code, BASE_DIR, dry=False)
    finally:
        os.unlink(tmp_path)

    return "", 204

# -----------------------------------------------------------------------------
#  Version browsing endpoints
# -----------------------------------------------------------------------------
@app.route("/versions", methods=["GET"])
def list_versions():
    file = request.args.get("file")
    if not file:
        return "Missing 'file' param", 400

    cmd = ["git", "log", "--pretty=format:%H|%ci", "--", file]
    out = subprocess.check_output(cmd, cwd=BASE_DIR).decode()
    lst = []
    for line in out.splitlines():
        sha, dt = line.split("|", 1)
        lst.append({"sha": sha, "date": dt})
    return jsonify(lst), 200

@app.route("/version", methods=["GET"])
def get_version():
    file = request.args.get("file")
    sha  = request.args.get("sha")
    if not file or not sha:
        return "Missing 'file' or 'sha' param", 400

    cmd = ["git", "show", f"{sha}:{file}"]
    try:
        content = subprocess.check_output(cmd, cwd=BASE_DIR).decode()
    except subprocess.CalledProcessError:
        return "Could not retrieve version", 500
    return Response(content, mimetype="text/plain")

@app.route("/revert", methods=["POST"])
def revert_version():
    payload = request.get_json(force=True) or {}
    file = payload.get("file")
    sha  = payload.get("sha")
    if not file or not sha:
        return "Missing 'file' or 'sha' in JSON", 400

    cmd = ["git", "show", f"{sha}:{file}"]
    content = subprocess.check_output(cmd, cwd=BASE_DIR).decode()

    target = BASE_DIR / file
    target.write_text(content)
    return "", 204

# -----------------------------------------------------------------------------
#  Entry point
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    if not BASE_DIR.exists():
        raise RuntimeError(f"baseDir does not exist: {BASE_DIR}")
    app.run(host=args.host, port=args.port)
