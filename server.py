#!/usr/bin/env python3
import logging
import re
import os
import tempfile
import argparse
import shutil
import subprocess
from pathlib import Path

from flask import Flask, request, send_from_directory, Response, jsonify
# Assuming vibe_cli is importable and contains _backup
try:
    import vibe_cli
    from vibe_cli import _backup
except ImportError:
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

# -----------------------------------------------------------------------------
#  Flask setup
# -----------------------------------------------------------------------------
# Assume vibe_diff.html is in the same directory as server.py
STATIC_DIR = Path(__file__).parent.resolve()

UI_SUBDIR = STATIC_DIR / 'ui'

app = Flask(__name__)

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
app.logger.handlers = logging.getLogger().handlers # Use root logger handlers
app.logger.setLevel(logging.INFO)


# -----------------------------------------------------------------------------
#  Route Definitions
# -----------------------------------------------------------------------------

@app.route('/')
def index():
    try:
        html_path = UI_SUBDIR / 'vibe_diff.html'
        app.logger.info(f"Attempting to serve index from: {html_path}")
        if not html_path.is_file():
             app.logger.error(f"HTML file not found at {html_path}")
             # Log separately if dir doesn't exist
             if not UI_SUBDIR.is_dir():
                 app.logger.error(f"UI subdirectory not found at {UI_SUBDIR}")
             return f"Error: vibe_diff.html not found in {UI_SUBDIR}.", 500

        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()

        js_injection = ""
        if INITIAL_FILE: # Check the global variable (string filename)
            escaped_filename = INITIAL_FILE.replace('\\', '\\\\').replace("'", "\\'")
            # Add console log within the injected script itself for browser-side verification
            js_injection = f"<script>window.INITIAL_FILE = '{escaped_filename}'; console.log('Server injected INITIAL_FILE:', window.INITIAL_FILE);</script>"
            app.logger.info(f"Preparing JS injection for initial file: {INITIAL_FILE}")
        else:
            app.logger.info("No INITIAL_FILE provided, no JS injection.")

        # --- Find Insertion Point ---
        # Find the end of the first <script> block which sets up require.config
        # This ensures our variable is defined *before* the main require block runs.
        insertion_marker = "require.config({ paths:"
        marker_pos = html_content.find(insertion_marker)
        insertion_point = -1
        if marker_pos != -1:
            # Find the end of the script tag *after* the marker
            end_script_tag_pos = html_content.find('</script>', marker_pos)
            if end_script_tag_pos != -1:
                insertion_point = end_script_tag_pos + len('</script>')
                # We want to insert *after* this first script tag

        if insertion_point != -1 and js_injection:
             # Insert the injection *after* the first script block and before the second one
             modified_html = html_content[:insertion_point] + "\n" + js_injection + "\n" + html_content[insertion_point:]
             app.logger.info(f"JS injection inserted after config </script> at index {insertion_point}")
        elif js_injection:
             # Fallback: Append to head (less reliable for script execution order)
             app.logger.warning("Could not find insertion point after require.config script, attempting append to <head>.")
             head_end_tag = '</head>'
             head_insertion_point = html_content.find(head_end_tag)
             if head_insertion_point != -1:
                  modified_html = html_content[:head_insertion_point] + js_injection + html_content[head_insertion_point:]
                  app.logger.info(f"JS injection appended before </head> at index {head_insertion_point}")
             else:
                  app.logger.error("Could not find </head> tag either. Cannot inject JS.")
                  modified_html = html_content # Serve unmodified
        else:
             modified_html = html_content # No injection needed

        return modified_html

    except Exception as e:
        app.logger.error(f"Error serving index page: {e}", exc_info=True)
        return "Internal Server Error", 500

# --- Route to get current file content ---
@app.route('/file')
def get_file():
    # 'file' parameter is expected to be the relative filename
    fname = request.args.get('file')
    if not fname:
        app.logger.error("/file endpoint called without 'file' parameter.")
        return jsonify({'error': "Missing 'file' parameter"}), 400

    # Construct full path using global BASE_DIR
    target = (BASE_DIR / fname).resolve()
    app.logger.info(f"Requesting file: {target} (relative to {BASE_DIR})")

    # Security check: Ensure target is within BASE_DIR
    if not target.is_relative_to(BASE_DIR):
         app.logger.warning(f"Attempted access outside BASE_DIR: {fname}")
         return jsonify({'error': "Invalid file path"}), 400

    if not target.is_file():
        app.logger.warning(f"File not found: {target}")
        return jsonify({'error': 'File not found'}), 404

    try:
        # Return content directly for JS fetch
        return Response(target.read_text(encoding='utf-8'), mimetype='text/plain')
    except Exception as e:
         app.logger.error(f"Error reading file {target}: {e}", exc_info=True)
         return jsonify({'error': f'Could not read file: {e}'}), 500


# --- Apply (preview) route – supports multi-patch bundles ---
@app.route('/apply', methods=['POST'])
def apply_route():
    data = {}
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        pass # Might be form data
    patch_text = data.get('patch') or request.form.get('patch')
    # The 'file' key from the payload isn't strictly needed here if the patch itself contains filenames
    # but it's good context if available.
    context_file = data.get('file') # Get the filename context if sent by UI
    if not patch_text:
        app.logger.error("/apply called without 'patch' payload.")
        return jsonify({'error': "Missing 'patch' payload"}), 400
    app.logger.info(f"/apply called for context file: {context_file}")

    tmpdir = Path(tempfile.mkdtemp(prefix="vibe_apply_"))
    try:
        patch_file = tmpdir / "upload.vibe"
        patch_file.write_text(patch_text, encoding='utf-8')

        # Load patches - This function should handle parsing VibeSpec 1.6+
        patches = vibe_cli.load_patches(patch_file)
        if not patches:
             raise ValueError("No valid patches found in the provided text.")

        results = {}
        # Prepare source files in tempdir
        for meta, _ in patches:
            relative_path_str = meta.get("file")
            if not relative_path_str:
                 raise ValueError("Patch metadata missing 'file' key.")
            src = (BASE_DIR / relative_path_str).resolve()
            dst = (tmpdir / relative_path_str).resolve()

            # Security check for source
            if not src.is_relative_to(BASE_DIR):
                raise ValueError(f"Patch references file outside baseDir: {relative_path_str}")
            if not src.is_file():
                raise FileNotFoundError(f"Source file for patch not found: {src}")

            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(src.read_text(encoding='utf-8'), encoding='utf-8')
            app.logger.info(f"Copied {src} to {dst} for applying patch.")

        # Apply patches within the temp directory
        # This function needs to handle all patch types correctly
        app.logger.info(f"Applying {len(patches)} patches in temp dir: {tmpdir}")
        vibe_cli.apply_patches(patches, tmpdir, dry=False) # Assuming this modifies files in tmpdir

        # Read results from modified files in tempdir
        for meta, _ in patches:
            fn = meta["file"]
            results[fn] = (tmpdir / fn).read_text(encoding='utf-8')
            app.logger.info(f"Read applied result for {fn}")

        return jsonify(results), 200

    except Exception as e:
        app.logger.error(f"Error during /apply: {e}", exc_info=True)
        return jsonify({'error': f'Patch application failed: {e}'}), 500 # Return 500 for server errors
    finally:
        # Clean up temp directory
        if tmpdir.exists():
            shutil.rmtree(tmpdir)
            app.logger.info(f"Cleaned up temp dir: {tmpdir}")

# --- Save route - DEPRECATED? '/accept_changes' seems preferred now ---
# Keep it for now if it serves a different purpose (e.g., applying a single patch directly)
@app.route('/save', methods=['POST'])
def save_route():
    app.logger.warning("/save route called (potentially deprecated, use /accept_changes?)")
    # ... (Keep existing logic if needed, ensure it uses global BASE_DIR) ...
    # ... (Make sure vibe_cli functions are correctly imported/used) ...
    return jsonify({"message": "/save not fully implemented based on current flow"}), 501


# --- Version browsing endpoints ---
@app.route("/versions", methods=["GET"])
def list_versions():
    # 'file' parameter is expected to be the relative filename
    relative_fname = request.args.get("file")
    if not relative_fname:
        app.logger.error("/versions called without 'file' parameter.")
        return jsonify({'error': "Missing 'file' parameter"}), 400

    target = (BASE_DIR / relative_fname).resolve()
    # Security check
    if not target.is_relative_to(BASE_DIR):
        app.logger.warning(f"/versions attempted access outside BASE_DIR: {relative_fname}")
        return jsonify({'error': "Invalid file path"}), 400

    app.logger.info(f"Listing versions for: {target}")
    versions = [] # Initialize empty list

    # --- Prioritize VibeBackups ---
    backups_dir = target.parent / "VibeBackups"
    if backups_dir.is_dir():
        import datetime
        try:
            # Use target's suffix dynamically
            backup_pattern = f"{target.stem}_*{target.suffix}"
            # Sort backups naturally if possible (e.g., by timestamp in name)
            entries = sorted(backups_dir.glob(backup_pattern))
            app.logger.info(f"Found {len(entries)} potential backups in {backups_dir} for pattern {backup_pattern}")
            for p in entries:
                try:
                    # Extract timestamp assuming format YYYYMMDD_HHMMSS
                    match = re.search(r"_(\d{8}_\d{6})", p.stem)
                    if match:
                         ts = match.group(1)
                         # Use timestamp as the 'sha' for uniqueness
                         dt = datetime.datetime.strptime(ts, "%Y%m%d_%H%M%S")
                         versions.append({"sha": ts, "date": dt.isoformat(), "type": "backup"})
                    else:
                        app.logger.warning(f"Could not parse timestamp from backup filename: {p.name}")
                except Exception as parse_err:
                    app.logger.warning(f"Error parsing backup file {p.name}: {parse_err}")
            if versions:
                 app.logger.info(f"Returning {len(versions)} versions from VibeBackups.")
                 return jsonify(versions), 200 # Return backups if found
        except Exception as backup_err:
            app.logger.error(f"Error accessing VibeBackups for {target}: {backup_err}", exc_info=True)

    # --- Fallback to Git if no backups found or error ---
    app.logger.info(f"No VibeBackups found or error occurred, trying Git history for {relative_fname}")
    try:
        # Check if BASE_DIR is a git repo root (simple check)
        if not (BASE_DIR / ".git").is_dir():
             app.logger.warning(f"BASE_DIR ({BASE_DIR}) is not a git repository root.")
             return jsonify([]), 200 # Return empty list if not a repo

        # Use relative path for git command
        cmd = ["git", "log", "--pretty=format:%H|%ci", "--", relative_fname]
        app.logger.info(f"Running git command: {cmd} in {BASE_DIR}")
        # Use stderr=subprocess.PIPE to capture potential errors like "not a git repo"
        process = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, text=True, check=False)

        if process.returncode != 0:
            # Log Git error but return empty list, don't crash
            app.logger.warning(f"Git log command failed (exit code {process.returncode}) for {relative_fname}: {process.stderr.strip()}")
            return jsonify([]), 200

        out = process.stdout.strip()
        for line in out.splitlines():
            if line:
                try:
                    sha, dt = line.split("|", 1)
                    versions.append({"sha": sha, "date": dt.strip(), "type": "git"})
                except ValueError:
                    app.logger.warning(f"Could not parse git log line: {line}")
        app.logger.info(f"Returning {len(versions)} versions from Git.")
        return jsonify(versions), 200

    except FileNotFoundError:
        app.logger.warning(f"Git command not found. Cannot retrieve Git versions.")
        return jsonify([]), 200 # Git not installed
    except Exception as e:
        app.logger.error(f"Unexpected error getting git versions for {relative_fname}: {e}", exc_info=True)
        return jsonify({'error': 'Error getting version history'}), 500


@app.route("/version", methods=["GET"])
def get_version():
    # 'file' parameter is expected to be the relative filename
    relative_fname = request.args.get("file")
    sha = request.args.get("sha") # Can be backup timestamp or git SHA
    if not relative_fname or not sha:
        app.logger.error("/version called without 'file' or 'sha' parameter.")
        return jsonify({'error': "Missing 'file' or 'sha' parameter"}), 400

    target_base = (BASE_DIR / relative_fname) # Base for finding backups dir/suffix

    app.logger.info(f"Getting version '{sha}' for file '{relative_fname}'")

    # --- Check if SHA looks like a VibeBackup timestamp ---
    if re.fullmatch(r"\d{8}_\d{6}", sha):
        app.logger.info(f"'{sha}' looks like a VibeBackup timestamp.")
        backups_dir = target_base.parent / "VibeBackups"
        # Construct expected backup filename using target's stem and suffix
        backup_filename = f"{target_base.stem}_{sha}{target_base.suffix}"
        backup_path = backups_dir / backup_filename

        app.logger.info(f"Checking for backup file: {backup_path}")
        if backup_path.is_file():
            try:
                # Use send_from_directory for security and correct mime type handling
                return send_from_directory(str(backups_dir), backup_filename, mimetype="text/plain")
            except Exception as e:
                 app.logger.error(f"Error sending backup file {backup_path}: {e}", exc_info=True)
                 return jsonify({'error': 'Could not send backup file'}), 500
        else:
            app.logger.warning(f"VibeBackup file not found: {backup_path}")
            # Don't immediately 404, could be a git SHA that looks like a date

    # --- Fallback to checking Git ---
    app.logger.info(f"'{sha}' not found as backup or doesn't look like one, trying Git.")
    try:
        # Check if BASE_DIR is a git repo root (simple check)
        if not (BASE_DIR / ".git").is_dir():
             app.logger.warning(f"BASE_DIR ({BASE_DIR}) is not a git repository root. Cannot get git version.")
             # If it wasn't a backup either, now we 404
             return jsonify({'error': 'Version not found (not a backup or git repo)'}), 404

        # Use relative path for git command
        cmd = ["git", "show", f"{sha}:{relative_fname}"]
        app.logger.info(f"Running git command: {cmd} in {BASE_DIR}")
        # Use check=True to raise CalledProcessError if git fails
        content = subprocess.check_output(cmd, cwd=BASE_DIR, text=True, stderr=subprocess.PIPE)
        return Response(content, mimetype="text/plain")

    except FileNotFoundError:
         app.logger.warning(f"Git command not found. Cannot retrieve Git version '{sha}'.")
         return jsonify({'error': 'Version not found (git command failed)'}), 404
    except subprocess.CalledProcessError as e:
        app.logger.warning(f"Git show command failed for {sha}:{relative_fname} (exit code {e.returncode}): {e.stderr.strip()}")
        # SHA might be invalid or file didn't exist at that commit
        return jsonify({'error': 'Version not found in Git history'}), 404
    except Exception as e:
        app.logger.error(f"Unexpected error getting git version {sha} for {relative_fname}: {e}", exc_info=True)
        return jsonify({'error': 'Error getting Git version'}), 500


# --- Route to revert to a specific version ---
@app.route("/revert", methods=["POST"])
def revert_version():
    # This might need more thought - should it create a backup first?
    app.logger.warning("/revert route called.")
    payload = request.get_json(force=True) or {}
    relative_fname = payload.get("file")
    sha = payload.get("sha")
    if not relative_fname or not sha:
        app.logger.error("/revert missing 'file' or 'sha' in JSON payload.")
        return jsonify({'error': "Missing 'file' or 'sha' in JSON"}), 400

    target = (BASE_DIR / relative_fname).resolve()
    # Security check
    if not target.is_relative_to(BASE_DIR):
        app.logger.warning(f"/revert attempted access outside BASE_DIR: {relative_fname}")
        return jsonify({'error': "Invalid file path"}), 400

    app.logger.info(f"Reverting '{relative_fname}' to version '{sha}'")

    # --- Get the content of the specified version ---
    version_content = None
    # Check backup first
    if re.fullmatch(r"\d{8}_\d{6}", sha):
        backups_dir = target.parent / "VibeBackups"
        backup_filename = f"{target.stem}_{sha}{target.suffix}"
        backup_path = backups_dir / backup_filename
        if backup_path.is_file():
             try:
                 version_content = backup_path.read_text(encoding='utf-8')
                 app.logger.info(f"Found content in backup: {backup_path}")
             except Exception as e:
                 app.logger.error(f"Error reading backup {backup_path} for revert: {e}", exc_info=True)
                 return jsonify({'error': 'Could not read backup version for revert'}), 500

    # If not found in backup, try Git
    if version_content is None:
         app.logger.info(f"'{sha}' not found as backup, trying Git for revert.")
         try:
             if not (BASE_DIR / ".git").is_dir():
                 app.logger.warning(f"BASE_DIR ({BASE_DIR}) is not a git repository root. Cannot revert using git.")
                 return jsonify({'error': 'Version not found (not a backup or git repo)'}), 404

             cmd = ["git", "show", f"{sha}:{relative_fname}"]
             app.logger.info(f"Running git command: {cmd} in {BASE_DIR}")
             version_content = subprocess.check_output(cmd, cwd=BASE_DIR, text=True, stderr=subprocess.PIPE)
             app.logger.info(f"Found content in git version: {sha}")
         except Exception as e:
             app.logger.error(f"Failed to get version content ('{sha}') for revert: {e}", exc_info=True)
             # Check specific errors if needed (CalledProcessError, FileNotFoundError)
             return jsonify({'error': f'Could not retrieve version {sha} for revert'}), 404 # 404 if version doesn't exist

    if version_content is None:
         # Should have been caught above, but double-check
         app.logger.error(f"Logic error: version_content is None after checks for revert.")
         return jsonify({'error': 'Version content could not be determined'}), 500

    # --- Perform Backup before Reverting ---
    try:
        app.logger.info(f"Creating backup of current state before reverting {target.name}")
        _backup(target) # Backup the file *before* overwriting
    except Exception as e:
         app.logger.error(f"Failed to create backup before revert for {target.name}: {e}", exc_info=True)
         # Decide policy: stop revert or continue? Let's stop for safety.
         return jsonify({'error': 'Failed to create backup before revert'}), 500

    # --- Overwrite the target file ---
    try:
        target.write_text(version_content, encoding='utf-8')
        app.logger.info(f"Successfully reverted {target.name} to version {sha}")
        return "", 204 # Success - No Content
    except Exception as e:
        app.logger.error(f"Error writing reverted content to {target}: {e}", exc_info=True)
        # If write fails, the backup was still made. The file might be in an odd state.
        return jsonify({'error': f'Failed to write reverted file content: {e}'}), 500


# --- Accept Changes route (Google AI version seems preferred) ---
DEFAULT_BACKUP_LIMIT = 20
@app.route('/accept_changes', methods=['POST'])
def accept_changes():
    payload = request.get_json(force=True) or {}
    # Expect relative filename from UI
    relative_fname = payload.get('file')
    new_text = payload.get('text')

    # --- 1. Input Validation ---
    if not relative_fname or new_text is None:
        app.logger.error("accept_changes: Missing 'file' or 'text' in JSON payload.")
        return jsonify({'error': "Missing 'file' or 'text' in JSON"}), 400

    # Get backup limit
    try:
        backup_limit = int(payload.get('backupLimit', DEFAULT_BACKUP_LIMIT))
        if backup_limit < 0: backup_limit = DEFAULT_BACKUP_LIMIT
    except (ValueError, TypeError):
        backup_limit = DEFAULT_BACKUP_LIMIT
    app.logger.info(f"Accepting changes for '{relative_fname}' with backup limit {backup_limit}")

    target = (BASE_DIR / relative_fname).resolve()

    # Security check
    if not target.is_relative_to(BASE_DIR):
         app.logger.error(f"accept_changes: Attempted access outside BASE_DIR: {relative_fname}")
         return jsonify({'error': "Invalid file path"}), 400

    if not target.is_file():
        app.logger.error(f"accept_changes: File not found or is not a file: {target}")
        return jsonify({'error': f"File not found: {relative_fname}"}), 404

    # --- 2. Backup Creation (Conditional) ---
    bdir = target.parent / "VibeBackups"
    needs_backup = True
    current_content = ""
    try:
        current_content = target.read_text(encoding='utf-8')
        if current_content == new_text:
             app.logger.info(f"accept_changes: New content identical to current for {relative_fname}. Skipping write and backup.")
             return "", 204 # No change needed

        # Check against latest backup only if backups dir exists
        if bdir.is_dir():
            backup_pattern = f"{target.stem}_*{target.suffix}"
            backups = sorted(bdir.glob(backup_pattern))
            if backups:
                latest_backup_path = backups[-1]
                try:
                    if current_content == latest_backup_path.read_text(encoding='utf-8'):
                        needs_backup = False
                        app.logger.info(f"accept_changes: Content matches latest backup {latest_backup_path.name}. Skipping backup.")
                except Exception as e:
                    app.logger.warning(f"accept_changes: Could not read/compare latest backup {latest_backup_path.name}: {e}. Proceeding with backup.")

        if needs_backup:
             app.logger.info(f"accept_changes: Creating backup for {relative_fname}.")
             _backup(target) # Call backup function (ensure it handles dir creation)
        # else: Backup skipped because content matched latest backup

    except Exception as e:
        app.logger.error(f"accept_changes: Error during backup check/creation for {relative_fname}: {e}", exc_info=True)
        return jsonify({'error': f"Failed during backup process: {e}"}), 500

    # --- 3. Overwrite with New Content ---
    try:
        target.write_text(new_text, encoding='utf-8')
        app.logger.info(f"accept_changes: Successfully wrote new content to {relative_fname}.")
    except Exception as e:
        app.logger.error(f"accept_changes: Error writing file {target}: {e}", exc_info=True)
        return jsonify({'error': f"Failed to write file: {e}"}), 500

    # --- 4. Prune Old Backups ---
    if backup_limit >= 0 and bdir.is_dir():
        try:
            backup_pattern = f"{target.stem}_*{target.suffix}"
            all_backups = sorted(bdir.glob(backup_pattern)) # Re-fetch list after potential new backup
            num_backups = len(all_backups)

            if num_backups > backup_limit:
                num_to_delete = num_backups - backup_limit
                backups_to_delete = all_backups[:num_to_delete]
                app.logger.info(f"accept_changes: Pruning {num_to_delete} backups for {relative_fname} (limit {backup_limit}).")
                for backup_path in backups_to_delete:
                    try:
                        backup_path.unlink()
                        app.logger.info(f"  Deleted backup: {backup_path.name}")
                    except OSError as e:
                        app.logger.error(f"  Error deleting backup {backup_path.name}: {e}")
            else:
                 app.logger.info(f"accept_changes: Backup count ({num_backups}) for {relative_fname} is within limit ({backup_limit}). No pruning needed.")
        except Exception as e:
             app.logger.error(f"accept_changes: Error during backup pruning for {relative_fname}: {e}", exc_info=True)
             # Log error during pruning process, but don't fail the request

    return "", 204 # Success


# --- Remove the old_accept_changes route ---
# @app.route('/old_accept_changes', methods=['POST'])
# def old_accept_changes(): ...


# -----------------------------------------------------------------------------
#  Entry point
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Argument Parsing (Moved Inside Main Block) ---
    parser = argparse.ArgumentParser(description="Vibe Diff UI Server")
    parser.add_argument(
        "--baseDir", type=str, required=False, default='.',
        help="Base directory for files and backups. Defaults to the current working directory."
    )
    parser.add_argument("--initialFile", type=str, required=False, default=None,
                        help="Optional: Filename to autoload in the UI (relative to baseDir)")
    parser.add_argument("--port", type=int, default=8000,
                        help="Port to run the server on")
    parser.add_argument("--host", default="0.0.0.0",
                        help="Host to bind the Flask app (default: 0.0.0.0)")

    try:
        args = parser.parse_args()
        # --- Overwrite Globals based on Parsed Args ---
        # Use globals() or directly assign to modify the global variables
        # Ensure BASE_DIR is absolute path
        BASE_DIR = Path(args.baseDir).expanduser().resolve()
        # Store INITIAL_FILE as string (relative path) or None
        INITIAL_FILE = args.initialFile
        PORT = args.port
        HOST = args.host
        # --- End Overwrite Globals ---

        if not BASE_DIR.is_dir():
            raise ValueError(f"Provided baseDir is not a valid directory: {args.baseDir}")

        if INITIAL_FILE:
             # Check if initial file exists relative to the final BASE_DIR
             initial_path_check = BASE_DIR / INITIAL_FILE
             if not initial_path_check.is_file():
                 logging.warning(f"Provided initialFile '{INITIAL_FILE}' not found relative to baseDir '{BASE_DIR}'. UI will attempt to load but may fail.")
                 # Don't clear INITIAL_FILE, let frontend handle potential 404

    except Exception as e:
        print(f"Error parsing arguments: {e}")
        parser.print_help()
        exit(1)
    # --- End Argument Parsing ---

    app.logger.info(f"Starting Vibe server...")
    app.logger.info(f"Base Directory: {BASE_DIR}")
    if INITIAL_FILE:
        app.logger.info(f"Initial File Hint: {INITIAL_FILE}")
    else:
        app.logger.info(f"No initial file specified.")
    app.logger.info(f"Listening on http://{HOST}:{PORT}")

    # Run the Flask app using the parsed host and port
    app.run(host=HOST, port=PORT, debug=False) # Debug=False for stability
