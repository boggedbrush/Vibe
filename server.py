#!/usr/bin/env python3
import re
import os
import tempfile
import argparse
import shutil
import subprocess
from pathlib import Path

from flask import Flask, request, send_from_directory, Response, jsonify

import vibe_cli

# -----------------------------------------------------------------------------
#  Parse command-line args
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
    default=8088,
    help="Port to listen on (default: 8088)"
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
#  Apply (preview) route – supports multi-patch bundles
# -----------------------------------------------------------------------------
@app.route('/apply', methods=['POST'])
def apply_route():
    data = {}
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        pass
    patch_text = data.get('patch') or request.form.get('patch')
    if not patch_text:
        return "Missing 'patch' payload (expecting JSON or form-field 'patch')", 400

    tmpdir = Path(tempfile.mkdtemp())
    patch_file = tmpdir / "upload.vibe"
    patch_file.write_text(patch_text)

    patches = vibe_cli.load_patches(patch_file)

    for meta, _ in patches:
        src = BASE_DIR / meta["file"]
        dst = tmpdir / meta["file"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text())

    vibe_cli.apply_patches(patches, tmpdir, dry=False)

    results = {}
    for meta, _ in patches:
        fn = meta["file"]
        results[fn] = (tmpdir / fn).read_text()

    shutil.rmtree(tmpdir)
    return jsonify(results), 200

# -----------------------------------------------------------------------------
#  Save (commit) route – single-patch only
# -----------------------------------------------------------------------------
@app.route('/save', methods=['POST'])
def save_route():
    payload = request.get_json(force=True) or {}
    patch = payload.get('patch')
    if not patch:
        return "Missing 'patch' in JSON", 400

    with tempfile.NamedTemporaryFile(mode='w', suffix='.vibe', delete=False) as tf:
        tf.write(patch)
        tmp_path = Path(tf.name)
    try:
        meta, code = vibe_cli.load_patch(tmp_path)
        vibe_cli.validate_spec(meta)
        try:
            vibe_cli.apply_patch(meta, code, BASE_DIR, dry=False)
        except Exception as e:
            return jsonify({"error": str(e)}), 400
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

    target = BASE_DIR / file
    backups = target.parent / "VibeBackups"
    if backups.is_dir():
        import datetime
        entries = sorted(backups.glob(f"{target.stem}_*.py"))
        lst = []
        for p in entries:
            ts = p.stem.split("_", 1)[1]
            dt = datetime.datetime.strptime(ts, "%Y%m%d_%H%M%S")
            lst.append({"sha": ts, "date": dt.isoformat(), "backupFile": p.name})
        return jsonify(lst), 200

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
    sha = request.args.get("sha")
    if not file or not sha:
        return "Missing 'file' or 'sha' param", 400

    if re.fullmatch(r"\d{8}_\d{6}", sha):
        backups = BASE_DIR / Path(file).parent / "VibeBackups"
        candidate = backups / f"{Path(file).stem}_{sha}{Path(file).suffix}"
        if candidate.exists():
            return send_from_directory(str(backups), candidate.name, mimetype="text/plain")
        else:
            return "Backup not found", 404
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
    sha = payload.get("sha")
    if not file or not sha:
        return "Missing 'file' or 'sha' in JSON", 400

    cmd = ["git", "show", f"{sha}:{file}"]
    content = subprocess.check_output(cmd, cwd=BASE_DIR).decode()
    target = BASE_DIR / file
    target.write_text(content)
    return "", 204

# -----------------------------------------------------------------------------
#  Accept Changes route – full-file overwrite without duplicate backups
# -----------------------------------------------------------------------------
@app.route('/accept_changes', methods=['POST'])
def accept_changes():
    payload = request.get_json(force=True) or {}
    fname = payload.get('file')
    new_text = payload.get('text')
    if not fname or new_text is None:
        return jsonify({'error': "Missing 'file' or 'text' in JSON"}), 400

    target = BASE_DIR / fname
    if not target.exists():
        return jsonify({'error': f"File not found: {fname}"}), 404

    # Only create a backup if the most recent backup differs from current content
    bdir = target.parent / "VibeBackups"
    old_text = target.read_text()
    if bdir.is_dir():
        backups = sorted(bdir.glob(f"{target.stem}_*.py"))
        if backups:
            latest = backups[-1]
            if latest.read_text() != old_text:
                from vibe_cli import _backup
                _backup(target)
        else:
            from vibe_cli import _backup
            _backup(target)
    else:
        from vibe_cli import _backup
        _backup(target)

    # Overwrite with new content
    target.write_text(new_text)
    return "", 204

@app.route('/file')
def get_file():
    file = request.args.get('file')
    if not file:
        return 'Missing file param', 400
    p = BASE_DIR / file
    if not p.exists():
        return 'Not found', 404
    return Response(p.read_text(), mimetype='text/plain')

# -----------------------------------------------------------------------------
#  Entry point
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    if not BASE_DIR.exists():
        raise RuntimeError(f"baseDir does not exist: {BASE_DIR}")
    app.run(host=args.host, port=args.port)
