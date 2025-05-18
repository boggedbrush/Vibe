import os
import json  
from dotenv import load_dotenv
# LLM SDKs will be imported within the /generate-patch route to avoid import errors
# if a particular SDK is not installed but its provider isn't selected.
# Ensure flask, jsonify, request are imported, e.g.:
# from flask import Flask, request, jsonify, send_from_directory, abort

#!/usr/bin/env python3
import sys
import logging
import re
import os
import tempfile
import argparse
import shutil
import subprocess
from pathlib import Path
from dotenv import load_dotenv
import google.generativeai as genai

# Make sure send_from_directory is imported
from flask import Flask, request, send_from_directory, Response, jsonify
# Assuming vibe_cli is importable and contains _backup

# Setup basic logging config first to ensure messages are seen
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)])

try:
    import vibe_cli
    from vibe_cli import _backup
except ImportError:
    def _backup(target_path):
        logging.warning(
            f"Dummy backup called for {target_path} (vibe_cli not found).")

logging.info("--- server.py script started (TOP LEVEL PRINT) ---") # <--- ADD THIS
# -----------------------------------------------------------------------------
#  Global Variables & Configuration
# -----------------------------------------------------------------------------
BASE_DIR = Path('.').resolve()
INITIAL_FILE = None
PORT = 8000
HOST = "0.0.0.0"

# Load environment variables from .env file if it exists
env_loaded = load_dotenv()
if env_loaded:
    logging.info(".env file loaded successfully.")
else:
    logging.info(
        ".env file not found or not loaded. Relying on system environment variables.")

# --- Global Configuration for GenAI (MUST be at module level) ---
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
SYSTEM_PROMPT_CONTENT = "You are VibePatchGPT. Output only valid Vibe Patch YAML."  # Default
genai_configured = False  # Initialize to False

# Define prompt location relative to server.py
STATIC_DIR = Path(__file__).parent.resolve()
PROMPT_FILENAME = "system-prompt.md"  # This is for the /system-prompt endpoint
# Path for LLM to load its system prompt
llm_system_prompt_path = STATIC_DIR / "system-prompt.md"

if llm_system_prompt_path.is_file():
    try:
        SYSTEM_PROMPT_CONTENT = llm_system_prompt_path.read_text(
            encoding='utf-8')
        logging.info(
            f"Successfully loaded system prompt for LLM from {llm_system_prompt_path}")
    except Exception as e:
        logging.error(
            f"Failed to load system prompt for LLM from {llm_system_prompt_path}: {e}. Using default.")
else:
    logging.warning(
        f"System prompt file for LLM not found at {llm_system_prompt_path}. Using default.")

# --- Configure GenAI SDK ---
logging.info("Attempting to configure Google AI SDK...")
if GOOGLE_API_KEY:
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        logging.info("Google AI SDK genai.configure() called successfully.")
        genai_configured = True
    except Exception as e:
        logging.error(f"Error configuring Google GenAI SDK with API key: {e}")
        genai_configured = False
else:
    logging.warning(
        "GOOGLE_API_KEY not found in environment. LLM generation will be disabled.")
    genai_configured = False
# --- End Global Configuration for GenAI ---


# -----------------------------------------------------------------------------
#  Flask setup
# -----------------------------------------------------------------------------
UI_SUBDIR = STATIC_DIR / 'ui'
# --- Load Environment Variables ---
load_dotenv()

# --- Configuration ---
VIBE_SYSTEM_PROMPT = """# VibePatchGPT System Prompt

You are **VibePatchGPT**, an assistant that speaks **only** in valid Vibe Patch files. You support **VibeSpec v1.6** (multi‑patch bundles and decorator handling) and all patch types from v1.4+. When the user asks for a patch, output **only** the `.vibe` YAML+code content—no explanations, no extra text. Always provide patches in a yaml code block.

---

## Spec Summary

1.  **Header**
    Every file must begin with:
    ```yaml
    # VibeSpec: 1.6
    ```

2.  **Patch Sections**
    Each patch starts at a line beginning with `patch_type:`. Metadata lines follow until `--- code:`. Everything indented under `--- code:` is the literal code block.

### Metadata Keys

- `patch_type`: one of:
  - `add_function`, `replace_function`, `remove_function`
  - `add_method`, `replace_method`, `remove_method`
  - `add_class`, `replace_class`, `remove_class`
  - `add_block`, `remove_block`, `replace_block`
- `file`: relative path to the target file
- `class`: required for method patches
- `name`: required for named removals (`remove_*`) and replacements (`replace_function`, `replace_method`, `replace_class`)
- `position`: for `add_block` (`start`, `end`, `before`, `after`)
- `anchor`: for `add_block` before/after
- `anchor_start` & `anchor_end`: for `remove_block` and `replace_block` by range

### Code Block

```yaml
--- code: |
    <exact code snippet>
```

---
Always output only the patch YAML content. No extra text.
"""

# --- API Key Check ---
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
app = Flask(__name__)


# -----------------------------------------------------------------------------
#  Route Definitions
# -----------------------------------------------------------------------------

@app.route('/generate-patch', methods=['POST'])
def generate_patch_route():
    print("--- /generate-patch: VERY FIRST LINE INSIDE FUNCTION ---") # EXTREME DEBUG
    data = request.get_json()
    if not data:
        print("--- /generate-patch: ERROR - No JSON data received ---")  # DEBUG
        return jsonify({"error": "Invalid JSON payload"}), 400

    prompt = data.get('prompt')
    filename = data.get('filename')
    file_content = data.get('file_content')
    llm_provider = data.get('llm_provider')

    # Ensure VIBE_SYSTEM_PROMPT is accessible here, assumed to be a global
    # constant
    print(
        f"--- /generate-patch ROUTE ENTRY. Provider: '{llm_provider}', Prompt: '{
            str(prompt)[
                :30]}...' ---")  # DEBUG

    if not prompt or not llm_provider:
        print(
            f"--- /generate-patch: ERROR - Missing prompt or provider. Provider: '{llm_provider}', Prompt given: {
                bool(prompt)} ---")  # DEBUG
        return jsonify({"error": "Prompt and LLM provider are required"}), 400

    patch_text_response = f"# Error: LLM provider '{llm_provider}' not recognized or failed."
    final_patch_code = ""  # Initialize to ensure it's defined

    try:
        # DEBUG
        print(
            f"--- /generate-patch: TRY block entered for provider '{llm_provider}' ---")
        if llm_provider == "gemini":
            print("--- /generate-patch: Matched 'gemini' ---")  # DEBUG
            if not GOOGLE_API_KEY:
                # DEBUG
                print("--- /generate-patch: GEMINI_API_KEY IS MISSING/FALSE ---")
                return jsonify(
                    {"error": "Gemini API key not configured on server"}), 503
            print("--- /generate-patch: GEMINI_API_KEY IS PRESENT ---")  # DEBUG

            try:
                import google.generativeai as genai
                # DEBUG
                print("--- /generate-patch: Successfully imported Google SDK ---")
            except ImportError as ie:
                print(
                    # DEBUG
                    f"--- /generate-patch: FAILED TO IMPORT GOOGLE SDK: {ie} ---")
                return jsonify(
                    {"error": f"Google SDK not installed or found: {ie}"}), 500

            genai.configure(api_key=GOOGLE_API_KEY)
            model = genai.GenerativeModel('gemini-1.5-flash-latest')
            print("--- /generate-patch: Google client initialized ---")  # DEBUG

            llm_payload_prompt = (
                f"{VIBE_SYSTEM_PROMPT}\\n\\n"
                f"The user wants to modify the file: '{
                    filename or 'unspecified_file.py'}'\\n"
                f"Current file content is:\\n```python\\n{
                    file_content or '# File is empty or not provided.'}\\n```\\n\\n"
                f"User's request: \"{prompt}\"\\n\\n"
                f"Please generate a Vibe Patch to achieve this. Ensure the `file:` key in the patch is correctly set to '{
                    filename or 'unspecified_file.py'}'."
            )
            # DEBUG
            print(
                f"--- /generate-patch: Sending to Gemini (user prompt snippet): {prompt[:100]}... ---")
            response = model.generate_content(llm_payload_prompt)
            patch_text_response = response.text
            print("--- /generate-patch: Received response from Gemini ---")  # DEBUG
            if not patch_text_response.strip().startswith("```yaml"):
                patch_text_response = f"```yaml\\n{
                    patch_text_response.strip()}\\n```"

        elif llm_provider == "anthropic":
            print("--- /generate-patch: Matched 'anthropic' ---")  # DEBUG
            if not ANTHROPIC_API_KEY:
                # DEBUG
                print("--- /generate-patch: ANTHROPIC_API_KEY IS MISSING/FALSE ---")
                return jsonify(
                    {"error": "Anthropic API key not configured on server"}), 503

            print("--- /generate-patch: ANTHROPIC_API_KEY IS PRESENT ---")  # DEBUG

            try:
                from anthropic import Anthropic
                # DEBUG
                print("--- /generate-patch: Successfully imported Anthropic SDK ---")
            except ImportError as ie:
                print(
                    # DEBUG
                    f"--- /generate-patch: FAILED TO IMPORT ANTHROPIC SDK: {ie} ---")
                return jsonify(
                    {"error": f"Anthropic SDK not installed or found: {ie}"}), 500

            client = Anthropic(api_key=ANTHROPIC_API_KEY)
            print("--- /generate-patch: Anthropic client initialized ---")  # DEBUG

            print(
                f"--- /generate-patch: Sending to Anthropic (user prompt snippet): {
                    str(prompt)[
                        :100]}... ---")  # TARGET DEBUG

            user_message_for_anthropic = (
                f"The user wants to modify the file: '{
                    filename or 'unspecified_file.py'}'\\n"
                f"Current file content is:\\n```python\\n{
                    file_content or '# File is empty or not provided.'}\\n```\\n\\n"
                f"User's request: \"{prompt}\"\\n\\n"
                f"Please generate a Vibe Patch to achieve this. Ensure the `file:` key in the patch is correctly set to '{
                    filename or 'unspecified_file.py'}'."
            )
            message = client.messages.create(
                model="claude-3-opus-20240229",
                max_tokens=3500,
                system=VIBE_SYSTEM_PROMPT,
                messages=[{"role": "user",
                           "content": user_message_for_anthropic}]
            )
            patch_text_response = message.content[0].text
            print("--- /generate-patch: Received response from Anthropic ---")  # DEBUG
            if not patch_text_response.strip().startswith("```yaml"):
                patch_text_response = f"```yaml\\n{
                    patch_text_response.strip()}\\n```"

        elif llm_provider == "openai":
            print("--- /generate-patch: Matched 'openai' ---")  # DEBUG
            if not OPENAI_API_KEY:
                # DEBUG
                print("--- /generate-patch: OPENAI_API_KEY IS MISSING/FALSE ---")
                return jsonify(
                    {"error": "OpenAI API key not configured on server"}), 503
            print("--- /generate-patch: OPENAI_API_KEY IS PRESENT ---")  # DEBUG

            try:
                from openai import OpenAI
                # DEBUG
                print("--- /generate-patch: Successfully imported OpenAI SDK ---")
            except ImportError as ie:
                print(
                    # DEBUG
                    f"--- /generate-patch: FAILED TO IMPORT OPENAI SDK: {ie} ---")
                return jsonify(
                    {"error": f"OpenAI SDK not installed or found: {ie}"}), 500

            client = OpenAI(api_key=OPENAI_API_KEY)
            print("--- /generate-patch: OpenAI client initialized ---")  # DEBUG

            llm_payload_prompt_openai = (  # Renamed to avoid conflict if it were global
                f"The user wants to modify the file: '{
                    filename or 'unspecified_file.py'}'\\n"
                f"Current file content is:\\n```python\\n{
                    file_content or '# File is empty or not provided.'}\\n```\\n\\n"
                f"User's request: \"{prompt}\"\\n\\n"
                f"Please generate a Vibe Patch to achieve this. Ensure the `file:` key in the patch is correctly set to '{
                    filename or 'unspecified_file.py'}'."
            )
            # DEBUG
            print(
                f"--- /generate-patch: Sending to OpenAI (user prompt snippet): {prompt[:100]}... ---")
            completion = client.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[
                    {"role": "system", "content": VIBE_SYSTEM_PROMPT},
                    {"role": "user", "content": llm_payload_prompt_openai}
                ]
            )
            patch_text_response = completion.choices[0].message.content
            print("--- /generate-patch: Received response from OpenAI ---")  # DEBUG
            if not patch_text_response.strip().startswith("```yaml"):
                patch_text_response = f"```yaml\\n{
                    patch_text_response.strip()}\\n```"

        else:
            # DEBUG
            print(
                f"--- /generate-patch: ERROR - Unknown provider: '{llm_provider}' ---")
            return jsonify(
                {"error": f"Unsupported LLM provider: {llm_provider}"}), 400

        # Extract content from markdown code block
        final_patch_code = patch_text_response.strip()
        if final_patch_code.startswith("```yaml"):
            final_patch_code = final_patch_code.split(
                "```yaml", 1)[1].split("```", 1)[0].strip()
        elif final_patch_code.startswith("```"):
            final_patch_code = final_patch_code.split(
                "```", 1)[1].split("```", 1)[0].strip()

        # DEBUG
        print(
            f"--- /generate-patch: Successfully processed provider '{llm_provider}'. Returning patch. ---")
        return jsonify({"patch_content": final_patch_code})

    except Exception as e:
        # DEBUG
        print(
            f"--- /generate-patch: EXCEPTION in TRY block for '{llm_provider}'. Error: {str(e)} ---")
        import traceback
        traceback.print_exc()
        return jsonify(
            {"error": f"Failed to generate patch. Check server logs. Details: {str(e)[:150]}"}), 500

    # This part should ideally not be reached if the logic above is complete.
    # DEBUG
    print(
        f"--- /generate-patch: Fallthrough - Reached end of function unexpectedly for provider '{llm_provider}' ---")
    return jsonify(
        {"error": "Reached end of function unexpectedly after try-except block."}), 500

@app.route('/')
def index():
    logger = logging
    try:
        html_path = UI_SUBDIR / 'vibe_diff.html'
        if not html_path.is_file():
            logger.error(f"HTML file not found at {html_path}")
            return f"Error: vibe_diff.html not found in {UI_SUBDIR}.", 500
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        js_injection = ""
        if INITIAL_FILE:
            escaped_filename = INITIAL_FILE.replace(
                '\\', '\\\\').replace("'", "\\'")
            js_injection = f"<script>window.INITIAL_FILE = '{escaped_filename}'; console.log('Server injected INITIAL_FILE:', window.INITIAL_FILE);</script>"
        insertion_marker = "require.config({ paths:"
        marker_pos = html_content.find(insertion_marker)
        insertion_point = -1
        if marker_pos != -1:
            end_script_tag_pos = html_content.find('</script>', marker_pos)
            if end_script_tag_pos != -1:
                insertion_point = end_script_tag_pos + len('</script>')
        if insertion_point != -1 and js_injection:
            modified_html = html_content[:insertion_point] + "\n" + \
                js_injection + "\n" + html_content[insertion_point:]
        elif js_injection:
            logger.warning(
                "Could not find insertion point for JS, attempting append to <head>.")
            head_end_tag = '</head>'
            head_insertion_point = html_content.find(head_end_tag)
            if head_insertion_point != -1:
                modified_html = html_content[:head_insertion_point] + \
                    js_injection + html_content[head_insertion_point:]
            else:
                logger.error("Could not find </head> tag. Cannot inject JS.")
                modified_html = html_content
        else:
            modified_html = html_content
        return modified_html
    except Exception as e:
        logging.error(f"Error serving index page: {e}", exc_info=True)
        return "Internal Server Error", 500


@app.route('/file')
def get_file():
    logger = logging
    fname = request.args.get('file')
    if not fname:
        logger.error("/file missing 'file'.")
        return jsonify({'error': "Missing 'file'"}), 400
    target = (BASE_DIR / fname).resolve()
    if not target.is_relative_to(BASE_DIR):
        logger.warning(f"Outside BASE_DIR: {fname}")
        return jsonify({'error': "Invalid path"}), 400
    if not target.is_file():
        logger.warning(f"Not found: {target}")
        return jsonify({'error': 'Not found'}), 404
    try:
        return Response(target.read_text(
            encoding='utf-8'), mimetype='text/plain')
    except Exception as e:
        logger.error(f"Read error {target}: {e}", exc_info=True)
        return jsonify({'error': f'Read error: {e}'}), 500


@app.route('/apply', methods=['POST'])
def apply_route():
    logger = logging
    resolved_base_dir = BASE_DIR.resolve()
    data = {}
    patch_text = None
    context_filename = None
    try:
        data = request.get_json(force=True) or {}
        patch_text = data.get('patch')
        context_filename = data.get('file')
    except Exception as e:
        logger.error(f"/apply error parsing JSON: {e}")
    if not patch_text:
        patch_text = request.form.get('patch')
    if not patch_text:
        logger.error("/apply missing 'patch' content in request body.")
        return jsonify(
            {'error': "Missing 'patch' content in request body"}), 400

    tmpdir = Path(tempfile.mkdtemp(prefix="vibe_apply_"))
    try:
        patch_file = tmpdir / "upload.vibe"
        patch_file.write_text(patch_text, encoding='utf-8')
        logger.debug(
            f"--- APPLY ROUTE --- Patch text being written to temp file:\n{patch_text[:500]}...")
        patches = vibe_cli.load_patches(patch_file)
        if not patches:
            raise ValueError(
                "No valid patches found in provided text by vibe_cli.load_patches.")

        target_files_in_patch = set()
        for meta, _ in patches:
            relative_path_str = meta.get("file")
            if not relative_path_str:
                logger.error(
                    f"--- APPLY ROUTE --- Problematic patch metadata: {meta}")
                raise ValueError("Patch missing required 'file' metadata key.")
            if relative_path_str in target_files_in_patch:
                continue
            src = (BASE_DIR / relative_path_str).resolve()
            dst = (tmpdir / relative_path_str).resolve()
            if not src.is_relative_to(resolved_base_dir) and not src.resolve(
            ).is_relative_to(resolved_base_dir.resolve()):
                raise ValueError(
                    f"Invalid path: '{relative_path_str}' resolves outside base directory '{resolved_base_dir}'.")
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_file():
                dst.write_text(
                    src.read_text(
                        encoding='utf-8'),
                    encoding='utf-8')
            target_files_in_patch.add(relative_path_str)

        vibe_cli.apply_patches(patches, tmpdir, dry=False)
        results = {}
        processed_files_from_apply = set()
        for meta, _ in patches:
            fn = meta.get("file")
            if fn and fn not in processed_files_from_apply:
                target_in_tmp = tmpdir / fn
                if target_in_tmp.exists():
                    results[fn] = target_in_tmp.read_text(encoding='utf-8')
                    processed_files_from_apply.add(fn)
                else:
                    logger.warning(
                        f"File '{fn}' mentioned in patch was not found in temp dir after apply_patches.")
        return jsonify(results), 200
    except (ValueError, FileNotFoundError) as e:
        logger.warning(f"/apply user error: {e}", exc_info=True)
        return jsonify({'error': f'Patch application failed: {e}'}), 400
    except Exception as e:
        logger.error(f"/apply unexpected internal error: {e}", exc_info=True)
        return jsonify(
            {'error': f'An internal server error occurred during patch application.'}), 500
    finally:
        if tmpdir.exists():
            try:
                shutil.rmtree(tmpdir)
            except Exception as cleanup_e:
                logger.error(
                    f"Error removing temp directory {tmpdir}: {cleanup_e}",
                    exc_info=True)


@app.route("/versions", methods=["GET"])
def list_versions():
    logger = logging
    relative_fname = request.args.get("file")
    if not relative_fname:
        logger.error("/versions missing 'file'.")
        return jsonify({'error': "Missing 'file'"}), 400
    target = (BASE_DIR / relative_fname).resolve()
    if not target.is_relative_to(BASE_DIR):
        logger.warning(f"/versions outside BASE_DIR: {relative_fname}")
        return jsonify({'error': "Invalid path"}), 400
    versions = []
    backups_dir = target.parent / "VibeBackups"
    if backups_dir.is_dir():
        import datetime
        try:
            backup_pattern = f"{target.stem}_*{target.suffix}"
            entries = sorted(backups_dir.glob(backup_pattern))
            for p in entries:
                try:
                    match = re.search(r"_(\d{8}_\d{6})", p.stem)
                    if match:
                        ts = match.group(1)
                        dt = datetime.datetime.strptime(ts, "%Y%m%d_%H%M%S")
                        versions.append(
                            {"sha": ts, "date": dt.isoformat(), "type": "backup"})
                except Exception as parse_err:
                    logger.warning(f"Backup parse error {p.name}: {parse_err}")
            # No return here yet, let git versions be appended if they exist
        except Exception as backup_err:
            logger.error(f"Backup access error: {backup_err}", exc_info=True)

    try:
        if (BASE_DIR / ".git").is_dir():
            cmd = [
                "git",
                "log",
                "--pretty=format:%H|%ci",
                "--",
                relative_fname]
            process = subprocess.run(
                cmd,
                cwd=BASE_DIR,
                capture_output=True,
                text=True,
                check=False)
            if process.returncode == 0:
                out = process.stdout.strip()
                for line in out.splitlines():
                    if line:
                        try:
                            sha, dt = line.split("|", 1)
                            versions.append(
                                {"sha": sha, "date": dt.strip(), "type": "git"})
                        except ValueError:
                            logger.warning(f"Git log parse error: {line}")
    except FileNotFoundError:
        logger.warning("Git not found for version listing.")
    except Exception as e:
        logger.error(f"Git versions error: {e}", exc_info=True)

    if versions:
        versions.sort(key=lambda x: x['date'], reverse=True)
    for i, v in enumerate(versions):
        logging.info(
            f"[DEBUG] Version[{i}]: type={
                v.get('type')} sha={
                v.get('sha')} date={
                v.get('date')}")
    return jsonify(versions), 200


@app.route("/version", methods=["GET"])
def get_version():
    logger = logging
    relative_fname = request.args.get("file")
    sha = request.args.get("sha")
    if not relative_fname or not sha:
        logger.error("/version missing params.")
        return jsonify({'error': "Missing params"}), 400
    target_base = (BASE_DIR / relative_fname)
    if re.fullmatch(r"\d{8}_\d{6}", sha):
        backups_dir = target_base.parent / "VibeBackups"
        backup_filename = f"{target_base.stem}_{sha}{target_base.suffix}"
        backup_path = backups_dir / backup_filename
        if backup_path.is_file():
            try:
                return send_from_directory(
                    str(backups_dir.resolve()), backup_filename, mimetype="text/plain")
            except Exception as e:
                logger.error(
                    f"Send backup error {backup_path}: {e}",
                    exc_info=True)
                return jsonify({'error': 'Send error'}), 500
    try:
        if not (BASE_DIR / ".git").is_dir():
            return jsonify({'error': 'Not a backup and not a git repo'}), 404
        cmd = ["git", "show", f"{sha}:{relative_fname}"]
        content = subprocess.check_output(
            cmd, cwd=BASE_DIR, text=True, stderr=subprocess.PIPE)
        return Response(content, mimetype="text/plain")
    except FileNotFoundError:
        logger.warning("Git not found for getting version content.")
        return jsonify({'error': 'Version not found (git cmd failed)'}), 404
    except subprocess.CalledProcessError as e:
        logger.warning(f"Git show failed: {e.stderr.strip()}")
        return jsonify({'error': 'Version not found in Git'}), 404
    except Exception as e:
        logger.error(f"Git version error: {e}", exc_info=True)
        return jsonify({'error': 'Git version error'}), 500


@app.route("/revert", methods=["POST"])
def revert_version():
    logger = logging
    payload = request.get_json(force=True) or {}
    relative_fname = payload.get("file")
    sha = payload.get("sha")
    if not relative_fname or not sha:
        logger.error("/revert missing params.")
        return jsonify({'error': "Missing params"}), 400
    target = (BASE_DIR / relative_fname).resolve()
    if not target.is_relative_to(BASE_DIR):
        logger.warning(f"/revert outside BASE_DIR: {relative_fname}")
        return jsonify({'error': "Invalid path"}), 400
    version_content = None
    if re.fullmatch(r"\d{8}_\d{6}", sha):
        backups_dir = target.parent / "VibeBackups"
        backup_filename = f"{target.stem}_{sha}{target.suffix}"
        backup_path = backups_dir / backup_filename
        if backup_path.is_file():
            try:
                version_content = backup_path.read_text(encoding='utf-8')
            except Exception as e:
                logger.error(f"Revert backup read error: {e}", exc_info=True)
                return jsonify({'error': 'Read backup error'}), 500
    if version_content is None:
        try:
            if not (BASE_DIR / ".git").is_dir():
                return jsonify(
                    {'error': 'Version not found (not backup/git repo)'}), 404
            cmd = ["git", "show", f"{sha}:{relative_fname}"]
            version_content = subprocess.check_output(
                cmd, cwd=BASE_DIR, text=True, stderr=subprocess.PIPE)
        except Exception as e:
            logger.error(f"Revert get version error: {e}", exc_info=True)
            return jsonify({'error': f'Retrieve version error: {e}'}), 404
    if version_content is None:
        logger.error("Version content None.")
        return jsonify({'error': 'Version not found'}), 500
    try:
        _backup(target)
    except Exception as e:
        logger.error(f"Revert backup error: {e}", exc_info=True)
        return jsonify({'error': 'Backup error'}), 500
    try:
        target.write_text(version_content, encoding='utf-8')
        return "", 204
    except Exception as e:
        logger.error(f"Revert write error: {e}", exc_info=True)
        return jsonify({'error': f'Write error: {e}'}), 500


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
    if backup_limit < 0:
        backup_limit = 20
    target = (BASE_DIR / relative_fname).resolve()
    resolved_base_dir = BASE_DIR.resolve()
    if not target.is_relative_to(resolved_base_dir) and not target.resolve(
    ).is_relative_to(resolved_base_dir.resolve()):
        logger.error(f"accept_changes path outside BASE_DIR: {relative_fname}")
        return jsonify({'error': "Invalid path specified"}), 400
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error(
            f"Error creating parent directory for {target}: {e}",
            exc_info=True)
        return jsonify(
            {'error': f"Failed to create directory structure: {e}"}), 500
    target_exists = target.is_file()
    current_content = None
    needs_write = True
    if target_exists:
        try:
            current_content = target.read_text(encoding='utf-8')
            if current_content == new_text:
                logger.info(
                    f"Content identical for existing file: {relative_fname}. No action needed.")
                needs_write = False
            else:
                logger.info(
                    f"Content differs for existing file: {relative_fname}. Will backup and update.")
        except Exception as e:
            logger.error(
                f"Error reading existing target file {target}: {e}",
                exc_info=True)
            return jsonify({'error': f"Error reading target file: {e}"}), 500
    else:
        logger.info(
            f"Target file {relative_fname} does not exist. Will be created.")
    backup_performed = False
    if needs_write:
        if target_exists:
            try:
                backup_path = _backup(target)
                backup_performed = True
                logger.info(
                    f"Created backup '{
                        backup_path.name}' for {relative_fname} before update.")
            except Exception as e:
                logger.error(
                    f"Backup creation failed for {target}: {e}",
                    exc_info=True)
                return jsonify(
                    {'error': f"Backup error, aborting save: {e}"}), 500
        try:
            target.write_text(new_text, encoding='utf-8')
            action = "created" if not target_exists else "updated"
            logger.info(f"Successfully {action} file: {relative_fname}")
        except Exception as e:
            logger.error(f"Write failed for {target}: {e}", exc_info=True)
            return jsonify(
                {'error': f"Write error after potential backup: {e}"}), 500
    if backup_performed and backup_limit >= 0:
        bdir = target.parent / "VibeBackups"
        if bdir.is_dir():
            try:
                backup_pattern = f"{target.stem}_*{target.suffix}"
                all_backups = sorted(
                    [p for p in bdir.glob(backup_pattern) if p.is_file()])
                num_backups = len(all_backups)
                if num_backups > backup_limit:
                    num_to_delete = num_backups - backup_limit
                    backups_to_delete = all_backups[:num_to_delete]
                    logger.info(
                        f"Pruning {num_to_delete} old backup(s) for {relative_fname} (limit {backup_limit}).")
                    for bp in backups_to_delete:
                        try:
                            bp.unlink()
                        except OSError as delete_err:
                            logger.error(
                                f"  Error deleting old backup {
                                    bp.name}: {delete_err}")
            except Exception as prune_err:
                logger.error(
                    f"Error during backup pruning for {relative_fname}: {prune_err}",
                    exc_info=True)
    return "", 204


@app.route('/system-prompt')
def get_system_prompt_for_copy():  # Renamed to avoid conflict if you want a different prompt for LLM
    logger = logging
    # This uses PROMPT_FILENAME which is "system-prompt.md" for the Copy button
    prompt_path_abs = STATIC_DIR / PROMPT_FILENAME
    if not prompt_path_abs.is_file():
        logger.error(f"Prompt not found for copy: {prompt_path_abs}")
        return jsonify({"error": "Prompt not found"}), 404
    try:
        return send_from_directory(directory=str(
            STATIC_DIR), path=PROMPT_FILENAME, mimetype='text/markdown')
    except Exception as e:
        logger.error(f"Send prompt error: {e}", exc_info=True)
        return jsonify({"error": "Send error"}), 500


if False:
    @app.route('/llm/status', methods=['GET'])
    def get_llm_status():
        logger = logging
        return jsonify({"configured": genai_configured})

@app.route('/llm/status', methods=['GET'])
def llm_status():
    # Assuming GOOGLE_API_KEY, etc., are global as defined in Patch 2
    # and jsonify is imported
    status = {
        "gemini": bool(GOOGLE_API_KEY),
        "anthropic": bool(ANTHROPIC_API_KEY),
        "openai": bool(OPENAI_API_KEY)
        # Add other providers here as you implement them
    }
    return jsonify(status)


# -----------------------------------------------------------------------------
#  Entry point
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Vibe Diff UI Server")
    parser.add_argument(
        "--baseDir",
        type=str,
        required=False,
        default='.',
        help="Base directory (defaults to cwd)")
    parser.add_argument(
        "--initialFile",
        type=str,
        required=False,
        default=None,
        help="Optional: Filename to autoload (relative to baseDir)")
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port (default: 8000)")
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host (default: 0.0.0.0)")
    try:
        args = parser.parse_args()
        BASE_DIR = Path(args.baseDir).expanduser().resolve()
        INITIAL_FILE = args.initialFile
        PORT = args.port
        HOST = args.host
        if not BASE_DIR.is_dir():
            raise ValueError(f"baseDir not valid: {args.baseDir}")
        if INITIAL_FILE and not (BASE_DIR / INITIAL_FILE).is_file():
            logging.warning(
                f"initialFile '{INITIAL_FILE}' not found in '{BASE_DIR}'.")
    except Exception as e:
        logging.error(f"Argument parsing error: {e}")
        parser.print_help()
        sys.exit(1)

    logging.info(f"Starting Vibe server...")
    logging.info(f"Base Directory: {BASE_DIR}")
    if INITIAL_FILE:
        logging.info(f"Initial File Hint: {INITIAL_FILE}")
    else:
        logging.info(f"No initial file specified.")
    logging.info(f"GenAI Configured: {genai_configured}")
    logging.info(f"Listening on http://{HOST}:{PORT}")

    app.run(host=HOST, port=PORT, debug=False)
