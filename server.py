#!/usr/bin/env python3
import logging
import re
import os
import tempfile
import argparse
import shutil
import subprocess
from pathlib import Path

# Make sure send_from_directory is imported
from flask import Flask, request, send_from_directory, Response, jsonify
# Assuming vibe_cli is importable and contains _backup
try:
    import vibe_cli
    from vibe_cli import _backup
except ImportError:
    # Setup basic logging config first to ensure messages are seen
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    logging.error("Failed to import vibe_cli. Backup functionality might be affected.")
    # Define a dummy _backup if needed for the code to run
    def _backup(target_path):
        logging.warning(f"Dummy backup called for {target_path} (vibe_cli not found).")

# -----------------------------------------------------------------------------
#  Global Variables (defaults potentially overridden by args)
# -----------------------------------------------------------------------------
BASE_DIR = Path('.').resolve() # Default BASE_DIR
INITIAL_FILE = None           # Default INITIAL_FILE (string filename)
PORT = 8000                   # Default PORT
HOST = "0.0.0.0"              # Default HOST

# -----------------------------------------------------------------------------
#  Flask setup
# -----------------------------------------------------------------------------
# Assume server.py is the parent of the 'ui' directory where vibe_diff.html lives
STATIC_DIR = Path(__file__).parent.resolve()
UI_SUBDIR = STATIC_DIR / 'ui'
# Define prompt location relative to server.py
PROMPT_FILENAME = "system-prompt.md"

app = Flask(__name__)

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
# Use Flask's logger after app creation if preferred, or stick with root logger
# app.logger.handlers = logging.getLogger().handlers
# app.logger.setLevel(logging.INFO)


# -----------------------------------------------------------------------------
#  Route Definitions (Use app.logger or root logger)
# -----------------------------------------------------------------------------

@app.route('/')
def index():
    logger = logging # Use root logger for simplicity here
    try:
        html_path = UI_SUBDIR / 'vibe_diff.html'
        # logger.info(f"Attempting to serve index from: {html_path}")
        if not html_path.is_file():
             logger.error(f"HTML file not found at {html_path}")
             if not UI_SUBDIR.is_dir():
                 logger.error(f"UI subdirectory not found at {UI_SUBDIR}")
             return f"Error: vibe_diff.html not found in {UI_SUBDIR}.", 500

        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()

        js_injection = ""
        if INITIAL_FILE:
            escaped_filename = INITIAL_FILE.replace('\\', '\\\\').replace("'", "\\'")
            js_injection = f"<script>window.INITIAL_FILE = '{escaped_filename}'; console.log('Server injected INITIAL_FILE:', window.INITIAL_FILE);</script>"
            # logger.info(f"Preparing JS injection for initial file: {INITIAL_FILE}")
        # else: logger.info("No INITIAL_FILE provided, no JS injection.")

        insertion_marker = "require.config({ paths:"
        marker_pos = html_content.find(insertion_marker)
        insertion_point = -1
        if marker_pos != -1:
            end_script_tag_pos = html_content.find('</script>', marker_pos)
            if end_script_tag_pos != -1:
                insertion_point = end_script_tag_pos + len('</script>')

        if insertion_point != -1 and js_injection:
             modified_html = html_content[:insertion_point] + "\n" + js_injection + "\n" + html_content[insertion_point:]
             # logger.info(f"JS injection inserted after config </script> at index {insertion_point}")
        elif js_injection:
             logger.warning("Could not find insertion point after require.config script, attempting append to <head>.")
             head_end_tag = '</head>'
             head_insertion_point = html_content.find(head_end_tag)
             if head_insertion_point != -1:
                  modified_html = html_content[:head_insertion_point] + js_injection + html_content[head_insertion_point:]
             else:
                  logger.error("Could not find </head> tag either. Cannot inject JS.")
                  modified_html = html_content
        else:
             modified_html = html_content

        return modified_html

    except Exception as e:
        logging.error(f"Error serving index page: {e}", exc_info=True) # Use root logger
        return "Internal Server Error", 500


@app.route('/file')
def get_file():
    logger = logging
    fname = request.args.get('file')
    if not fname: logger.error("/file missing 'file'."); return jsonify({'error': "Missing 'file'"}), 400
    target = (BASE_DIR / fname).resolve()
    if not target.is_relative_to(BASE_DIR): logger.warning(f"Outside BASE_DIR: {fname}"); return jsonify({'error': "Invalid path"}), 400
    if not target.is_file(): logger.warning(f"Not found: {target}"); return jsonify({'error': 'Not found'}), 404
    try: return Response(target.read_text(encoding='utf-8'), mimetype='text/plain')
    except Exception as e: logger.error(f"Read error {target}: {e}", exc_info=True); return jsonify({'error': f'Read error: {e}'}), 500

@app.route('/apply', methods=['POST'])
def apply_route():
    # Ensure 'logger' and 'BASE_DIR' are accessible
    logger = logging
    resolved_base_dir = BASE_DIR.resolve()

    data = {}; patch_text = None
    try:
        data = request.get_json(force=True) or {}
        patch_text = data.get('patch')
    except Exception: pass

    if not patch_text:
        patch_text = request.form.get('patch') # Fallback

    if not patch_text:
        logger.error("/apply missing 'patch' data in request.")
        return jsonify({'error': "Missing 'patch' content in request body"}), 400

    tmpdir = Path(tempfile.mkdtemp(prefix="vibe_apply_"))
    try:
        # Write patch to temp file
        patch_file = tmpdir / "upload.vibe"
        patch_file.write_text(patch_text, encoding='utf-8')

        # Load patches
        patches = vibe_cli.load_patches(patch_file)
        if not patches:
            raise ValueError("No valid patches found in provided text.")

        # --- Prepare Existing Files in Temporary Directory ---
        # We only need to copy files that *already exist* in the source repo.
        # apply_patch within vibe_cli will handle creating non-existent ones.
        target_files_in_patch = set()
        for meta, _ in patches:
            relative_path_str = meta.get("file")
            if not relative_path_str:
                raise ValueError("Patch missing required 'file' metadata key.")

            if relative_path_str in target_files_in_patch:
                continue # Avoid processing the same file path multiple times

            src = (BASE_DIR / relative_path_str).resolve()
            dst = (tmpdir / relative_path_str).resolve()

            # --- Security Check ---
            if not src.is_relative_to(resolved_base_dir):
                 if not src.resolve().is_relative_to(resolved_base_dir.resolve()):
                     raise ValueError(f"Invalid path: '{relative_path_str}' resolves outside base directory '{resolved_base_dir}'.")

            # Ensure parent directory exists in tempdir
            dst.parent.mkdir(parents=True, exist_ok=True)

            # --- Copy ONLY if source file exists ---
            if src.is_file():
                dst.write_text(src.read_text(encoding='utf-8'), encoding='utf-8')
                # logger.debug(f"Copied existing file {relative_path_str} to temp dir.")
            # --- No need for an else block to create empty files here ---

            target_files_in_patch.add(relative_path_str)
        # --- End of file preparation ---

        # Apply patches using the updated vibe_cli function
        # This will operate on the copied files and create new ones within tmpdir as needed.
        vibe_cli.apply_patches(patches, tmpdir, dry=False)

        # Collect results from all potentially affected files in tempdir
        results = {}
        processed_files_from_apply = set() # Track files actually touched or created by apply_patches
        for meta, _ in patches: # Re-iterate to get the list of files potentially modified
             fn = meta.get("file")
             if fn and fn not in processed_files_from_apply:
                 target_in_tmp = tmpdir / fn
                 if target_in_tmp.exists(): # Check if apply_patches actually created/modified it
                     results[fn] = target_in_tmp.read_text(encoding='utf-8')
                     processed_files_from_apply.add(fn)
                 else:
                      # This case might occur if a remove_* patch was the only one for a file
                      # or if apply_patch itself errored subtly. Log it.
                      logger.warning(f"File '{fn}' mentioned in patch was not found in temp dir after apply_patches.")


        return jsonify(results), 200

    except (ValueError, FileNotFoundError) as e:
        logger.warning(f"/apply user error: {e}")
        return jsonify({'error': f'Patch application failed: {e}'}), 400
    except Exception as e:
        logger.error(f"/apply unexpected internal error: {e}", exc_info=True)
        return jsonify({'error': f'An internal server error occurred during patch application.'}), 500
    finally:
        if tmpdir.exists():
             try:
                 shutil.rmtree(tmpdir)
             except Exception as cleanup_e:
                  logger.error(f"Error removing temp directory {tmpdir}: {cleanup_e}", exc_info=True)

@app.route("/versions", methods=["GET"])
def list_versions():
    logger = logging
    relative_fname = request.args.get("file");
    if not relative_fname: logger.error("/versions missing 'file'."); return jsonify({'error': "Missing 'file'"}), 400
    target = (BASE_DIR / relative_fname).resolve()
    if not target.is_relative_to(BASE_DIR): logger.warning(f"/versions outside BASE_DIR: {relative_fname}"); return jsonify({'error': "Invalid path"}), 400

    versions = []
    backups_dir = target.parent / "VibeBackups"
    if backups_dir.is_dir():
        import datetime
        try:
            backup_pattern = f"{target.stem}_*{target.suffix}"; entries = sorted(backups_dir.glob(backup_pattern))
            for p in entries:
                try:
                    match = re.search(r"_(\d{8}_\d{6})", p.stem)
                    if match: ts = match.group(1); dt = datetime.datetime.strptime(ts, "%Y%m%d_%H%M%S"); versions.append({"sha": ts, "date": dt.isoformat(), "type": "backup"})
                except Exception as parse_err: logger.warning(f"Backup parse error {p.name}: {parse_err}")
            if versions: versions.sort(key=lambda x: x['date'], reverse=True); return jsonify(versions), 200
        except Exception as backup_err: logger.error(f"Backup access error: {backup_err}", exc_info=True)

    try:
        if not (BASE_DIR / ".git").is_dir(): return jsonify([]), 200
        cmd = ["git", "log", "--pretty=format:%H|%ci", "--", relative_fname]
        process = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, text=True, check=False)
        if process.returncode != 0: return jsonify([]), 200
        out = process.stdout.strip()
        for line in out.splitlines():
            if line:
                try: sha, dt = line.split("|", 1); versions.append({"sha": sha, "date": dt.strip(), "type": "git"})
                except ValueError: logger.warning(f"Git log parse error: {line}")
        return jsonify(versions), 200
    except FileNotFoundError: logger.warning("Git not found."); return jsonify([]), 200
    except Exception as e: logger.error(f"Git versions error: {e}", exc_info=True); return jsonify({'error': 'Version history error'}), 500


@app.route("/version", methods=["GET"])
def get_version():
    logger = logging
    relative_fname = request.args.get("file"); sha = request.args.get("sha")
    if not relative_fname or not sha: logger.error("/version missing params."); return jsonify({'error': "Missing params"}), 400
    target_base = (BASE_DIR / relative_fname)

    if re.fullmatch(r"\d{8}_\d{6}", sha):
        backups_dir = target_base.parent / "VibeBackups"; backup_filename = f"{target_base.stem}_{sha}{target_base.suffix}"; backup_path = backups_dir / backup_filename
        if backup_path.is_file():
            try: return send_from_directory(str(backups_dir), backup_filename, mimetype="text/plain")
            except Exception as e: logger.error(f"Send backup error {backup_path}: {e}", exc_info=True); return jsonify({'error': 'Send error'}), 500

    try:
        if not (BASE_DIR / ".git").is_dir(): return jsonify({'error': 'Not backup/git repo'}), 404
        cmd = ["git", "show", f"{sha}:{relative_fname}"]
        content = subprocess.check_output(cmd, cwd=BASE_DIR, text=True, stderr=subprocess.PIPE)
        return Response(content, mimetype="text/plain")
    except FileNotFoundError: logger.warning("Git not found."); return jsonify({'error': 'Version not found (git cmd failed)'}), 404
    except subprocess.CalledProcessError as e: logger.warning(f"Git show failed: {e.stderr.strip()}"); return jsonify({'error': 'Version not found in Git'}), 404
    except Exception as e: logger.error(f"Git version error: {e}", exc_info=True); return jsonify({'error': 'Git version error'}), 500


@app.route("/revert", methods=["POST"])
def revert_version():
    logger = logging
    payload = request.get_json(force=True) or {}; relative_fname = payload.get("file"); sha = payload.get("sha")
    if not relative_fname or not sha: logger.error("/revert missing params."); return jsonify({'error': "Missing params"}), 400
    target = (BASE_DIR / relative_fname).resolve()
    if not target.is_relative_to(BASE_DIR): logger.warning(f"/revert outside BASE_DIR: {relative_fname}"); return jsonify({'error': "Invalid path"}), 400

    version_content = None
    if re.fullmatch(r"\d{8}_\d{6}", sha):
        backups_dir = target.parent / "VibeBackups"; backup_filename = f"{target.stem}_{sha}{target.suffix}"; backup_path = backups_dir / backup_filename
        if backup_path.is_file():
             try: version_content = backup_path.read_text(encoding='utf-8')
             except Exception as e: logger.error(f"Revert backup read error: {e}", exc_info=True); return jsonify({'error': 'Read backup error'}), 500
    if version_content is None:
         try:
             if not (BASE_DIR / ".git").is_dir(): return jsonify({'error': 'Version not found (not backup/git repo)'}), 404
             cmd = ["git", "show", f"{sha}:{relative_fname}"];
             version_content = subprocess.check_output(cmd, cwd=BASE_DIR, text=True, stderr=subprocess.PIPE)
         except Exception as e: logger.error(f"Revert get version error: {e}", exc_info=True); return jsonify({'error': f'Retrieve version error: {e}'}), 404
    if version_content is None: logger.error("Version content None."); return jsonify({'error': 'Version not found'}), 500

    try: _backup(target)
    except Exception as e: logger.error(f"Revert backup error: {e}", exc_info=True); return jsonify({'error': 'Backup error'}), 500
    try: target.write_text(version_content, encoding='utf-8'); return "", 204
    except Exception as e: logger.error(f"Revert write error: {e}", exc_info=True); return jsonify({'error': f'Write error: {e}'}), 500


# Ensure these imports are available:
# import logging
# from pathlib import Path
# from flask import request, jsonify
# from vibe_cli import _backup # Assuming this is imported correctly

# Replace the accept_changes function in server.py with this version:

@app.route('/accept_changes', methods=['POST'])
def accept_changes():
    logger = logging
    payload = request.get_json(force=True) or {}
    relative_fname = payload.get('file')
    new_text = payload.get('text')

    if not relative_fname or new_text is None:
        logger.error("accept_changes missing 'file' or 'text' in payload.")
        return jsonify({'error': "Missing 'file' or 'text'"}), 400

    try:
        backup_limit = int(payload.get('backupLimit', 20))
    except (ValueError, TypeError):
        backup_limit = 20
    if backup_limit < 0: backup_limit = 20

    target = (BASE_DIR / relative_fname).resolve()
    resolved_base_dir = BASE_DIR.resolve()

    # --- Security Check ---
    if not target.is_relative_to(resolved_base_dir):
        if not target.resolve().is_relative_to(resolved_base_dir.resolve()):
            logger.error(f"accept_changes path outside BASE_DIR: {relative_fname}")
            return jsonify({'error': "Invalid path specified"}), 400

    # --- Ensure parent directory exists ---
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error(f"Error creating parent directory for {target}: {e}", exc_info=True)
        return jsonify({'error': f"Failed to create directory structure: {e}"}), 500

    # --- Check current state and decide action ---
    target_exists = target.is_file()
    current_content = None
    needs_write = True

    if target_exists:
        try:
            current_content = target.read_text(encoding='utf-8')
            if current_content == new_text:
                logger.info(f"Content identical for existing file: {relative_fname}. No action needed.")
                needs_write = False # Skip backup, write, and prune if no change
            else:
                 logger.info(f"Content differs for existing file: {relative_fname}. Will backup and update.")
        except Exception as e:
            logger.error(f"Error reading existing target file {target}: {e}", exc_info=True)
            return jsonify({'error': f"Error reading target file: {e}"}), 500
    else:
        # File does not exist, it's a new file scenario
        logger.info(f"Target file {relative_fname} does not exist. Will be created.")
        # needs_write remains True, no backup needed

    # --- Perform Write Operation (if needed) ---
    backup_performed = False
    if needs_write:
        # --- Perform Backup BEFORE Write (only if file existed) ---
        if target_exists:
            try:
                # Backup the existing file immediately before overwriting
                backup_path = _backup(target)
                backup_performed = True # Flag that a backup was made for pruning later
                logger.info(f"Created backup '{backup_path.name}' for {relative_fname} before update.")
            except Exception as e:
                logger.error(f"Backup creation failed for {target}: {e}", exc_info=True)
                # If backup fails, abort the write for safety
                return jsonify({'error': f"Backup error, aborting save: {e}"}), 500
        # --- End Backup ---

        # --- Write the new content ---
        try:
            target.write_text(new_text, encoding='utf-8')
            action = "created" if not target_exists else "updated"
            logger.info(f"Successfully {action} file: {relative_fname}")
        except Exception as e:
            logger.error(f"Write failed for {target}: {e}", exc_info=True)
            # If write fails after backup, the backup still exists. The file state is now potentially bad.
            # Consider attempting to restore the backup? For now, just report error.
            return jsonify({'error': f"Write error after potential backup: {e}"}), 500
        # --- End Write ---

    # --- Prune Old Backups (only if a backup was made in *this* operation) ---
    # We prune only if the file existed before *and* we successfully backed it up
    if backup_performed and backup_limit >= 0:
        bdir = target.parent / "VibeBackups"
        if bdir.is_dir():
            try:
                backup_pattern = f"{target.stem}_*{target.suffix}"
                all_backups = sorted([p for p in bdir.glob(backup_pattern) if p.is_file()])
                num_backups = len(all_backups)

                if num_backups > backup_limit:
                    num_to_delete = num_backups - backup_limit
                    backups_to_delete = all_backups[:num_to_delete]
                    logger.info(f"Pruning {num_to_delete} old backup(s) for {relative_fname} (limit {backup_limit}).")
                    for bp in backups_to_delete:
                        try: bp.unlink()
                        except OSError as delete_err: logger.error(f"  Error deleting old backup {bp.name}: {delete_err}")
            except Exception as prune_err:
                 logger.error(f"Error during backup pruning for {relative_fname}: {prune_err}", exc_info=True)
    # --- End Pruning ---

    return "", 204 # Success (HTTP 204 No Content)

# *** NEW ROUTE TO SERVE THE PROMPT FILE ***
@app.route('/system-prompt')
def get_system_prompt():
    logger = logging
    prompt_path_abs = STATIC_DIR / PROMPT_FILENAME
    # logger.info(f"Serving system prompt from: {prompt_path_abs}")
    if not prompt_path_abs.is_file(): logger.error(f"Prompt not found: {prompt_path_abs}"); return jsonify({"error": "Prompt not found"}), 404
    try: return send_from_directory(directory=str(STATIC_DIR), path=PROMPT_FILENAME, mimetype='text/markdown')
    except Exception as e: logger.error(f"Send prompt error: {e}", exc_info=True); return jsonify({"error": "Send error"}), 500
# *** END NEW ROUTE ***


# -----------------------------------------------------------------------------
#  Entry point
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Vibe Diff UI Server")
    parser.add_argument("--baseDir", type=str, required=False, default='.', help="Base directory (defaults to cwd)")
    parser.add_argument("--initialFile", type=str, required=False, default=None, help="Optional: Filename to autoload (relative to baseDir)")
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    parser.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")
    try:
        args = parser.parse_args()
        BASE_DIR = Path(args.baseDir).expanduser().resolve()
        INITIAL_FILE = args.initialFile
        PORT = args.port
        HOST = args.host
        if not BASE_DIR.is_dir(): raise ValueError(f"baseDir not valid: {args.baseDir}")
        if INITIAL_FILE and not (BASE_DIR / INITIAL_FILE).is_file(): logging.warning(f"initialFile '{INITIAL_FILE}' not found in '{BASE_DIR}'.")
    except Exception as e: print(f"Arg parse error: {e}"); parser.print_help(); exit(1)

    logging.info(f"Starting Vibe server...")
    logging.info(f"Base Directory: {BASE_DIR}")
    if INITIAL_FILE: logging.info(f"Initial File Hint: {INITIAL_FILE}")
    else: logging.info(f"No initial file specified.")
    logging.info(f"Listening on http://{HOST}:{PORT}")

    app.run(host=HOST, port=PORT, debug=False)
    
