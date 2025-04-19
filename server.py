#!/usr/bin/env python3
import os
import tempfile
import argparse
from pathlib import Path
from flask import Flask, request, send_from_directory, Response
import vibe_cli
import subprocess
from flask import jsonify

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

@app.route("/apply", methods=["POST"])
def apply_route():
    """
    Dry‑run endpoint: returns the patched file text without writing.
    """
    payload = request.get_json(force=True)
    orig  = payload.get("original")
    patch = payload.get("patch")
    if orig is None or patch is None:
        return "Missing 'original' or 'patch' in JSON", 400

    # Create a temp workspace
    tmpdir     = Path(tempfile.mkdtemp())
    patch_path = tmpdir / "patch.vibe"
    patch_path.write_text(patch)

    # Parse the patch to learn which file to modify
    meta, code = vibe_cli.load_patch(patch_path)
    vibe_cli.validate_spec(meta)

    # Write the original content under the correct filename
    orig_path = tmpdir / meta["file"]
    orig_path.parent.mkdir(parents=True, exist_ok=True)
    orig_path.write_text(orig)

    # Perform dry‑run apply
    new_text = vibe_cli.apply_patch(meta, code, tmpdir, dry=True)
    return Response(new_text, mimetype="text/plain")

# Real save: applies patch under BASE_DIR
@app.route("/save", methods=["POST"])
def save_route():
    payload = request.get_json(force=True)
    patch = payload.get("patch")
    if patch is None:
        return "Missing 'patch' in JSON", 400

    # Write the patch to a temp file so we can parse it
    with tempfile.NamedTemporaryFile(mode="w", suffix=".vibe", delete=False) as tf:
        tf.write(patch)
        tmp_path = Path(tf.name)
    try:
        meta, code = vibe_cli.load_patch(tmp_path)
        vibe_cli.validate_spec(meta)
        # Apply into BASE_DIR
        vibe_cli.apply_patch(meta, code, BASE_DIR, dry=False)
    finally:
        os.unlink(tmp_path)

    return "", 204

# -----------------------------------------------------------------------------
#  Version browsing endpoints
# -----------------------------------------------------------------------------

@app.route("/versions", methods=["GET"])
def list_versions():
    """
    GET /versions?file=path/to/file.py
    Returns a JSON list of commits touching that file:
      [ { "sha": "...", "date": "2025-04-18 18:00:00 -0400" }, ... ]
    """
    file = request.args.get("file")
    if not file:
        return "Missing 'file' param", 400

    # git log: SHA|timestamp
    cmd = ["git", "log", "--pretty=format:%H|%ci", "--", file]
    out = subprocess.check_output(cmd, cwd=BASE_DIR).decode()
    lst = []
    for line in out.splitlines():
        sha, dt = line.split("|", 1)
        lst.append({"sha": sha, "date": dt})
    return jsonify(lst)


@app.route("/version", methods=["GET"])
def get_version():
    """
    GET /version?file=path/to/file.py&sha=<commit>
    Returns the file content at that commit.
    """
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
    """
    POST /revert
    JSON { "file": "path/to/file.py", "sha": "<commit>" }
    Overwrites the file on disk with the version at that commit.
    """
    payload = request.get_json(force=True)
    file = payload.get("file")
    sha  = payload.get("sha")
    if not file or not sha:
        return "Missing 'file' or 'sha' in JSON", 400

    cmd = ["git", "show", f"{sha}:{file}"]
    content = subprocess.check_output(cmd, cwd=BASE_DIR).decode()

    target = BASE_DIR / file
    target.write_text(content)
    _log("Reverted {} to {}", file, sha)
    return "", 204

# -----------------------------------------------------------------------------
#  Entry point
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    # Ensure BASE_DIR exists
    if not BASE_DIR.exists():
        raise RuntimeError(f"baseDir does not exist: {BASE_DIR}")
    app.run(host=args.host, port=args.port)
