import zipfile
import os

PACKAGE_NAME = "vibe_patch_offline_bundle.zip"
EXCLUDE_DIRS = {"VibeBackups", "__pycache__"}
EXTRA_DIRS = ["static", "ui", "tests", "fonts"]
EXTRA_FILES = ["requirements.txt", "README.md", "server.py"]

def zipdir(zipf, folder, base_folder=""):
    for root, _, files in os.walk(folder):
        if any(excl in root for excl in EXCLUDE_DIRS):
            continue
        for file in files:
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, base_folder or ".")
            zipf.write(full_path, arcname=rel_path)

def package():
    with zipfile.ZipFile(PACKAGE_NAME, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Include all top-level .py files (excluding VibeBackups)
        for root, _, files in os.walk("."):
            if any(excl in root for excl in EXCLUDE_DIRS):
                continue
            for file in files:
                if file.endswith(".py"):
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, ".")
                    zipf.write(full_path, arcname=rel_path)

        # Include extra dirs (ui, static, tests, fonts)
        for d in EXTRA_DIRS:
            if os.path.exists(d):
                print(f"[+] Adding directory: {d}/")
                zipdir(zipf, d)

        # Include extra files
        for f in EXTRA_FILES:
            if os.path.exists(f):
                print(f"[+] Adding file: {f}")
                zipf.write(f)

    print(f"\n[✓] Packaged everything into {PACKAGE_NAME}")

if __name__ == "__main__":
    package()
