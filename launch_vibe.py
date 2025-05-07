'''
Launcher for ./server.py that captured filename and base directory and passed that over to the server.
'''
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import subprocess
import sys
import os
import threading # To run the server without blocking the GUI
from pathlib import Path
import webbrowser
import argparse # Added for command-line arguments
import tkinter.font as tkFont # Added for font manipulation

# --- Configuration ---
SERVER_SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "server.py")
SERVER_HOST_FOR_BROWSER = "127.0.0.1"
SERVER_PORT = 8000
DEFAULT_FONT_SIZE = 12

# --- Argument Parsing for Font Size ---
APP_FONT_SIZE = DEFAULT_FONT_SIZE
_parser = argparse.ArgumentParser(description="Vibe Server Launcher with configurable font size.")
_parser.add_argument(
    "--fontsize",
    type=int,
    help=f"Set the base font size for the GUI (default: {DEFAULT_FONT_SIZE})"
)
try:
    _cli_args = _parser.parse_args()
    if _cli_args.fontsize is not None:
        if 0 < _cli_args.fontsize < 72:
            APP_FONT_SIZE = _cli_args.fontsize
        else:
            print(
                f"Warning: Invalid font size '{_cli_args.fontsize}' provided. "
                f"Font size must be positive and less than 72. Using default {DEFAULT_FONT_SIZE}.",
                file=sys.stderr
            )
except SystemExit:
    sys.exit()
except Exception as e:
    print(f"Error parsing command line arguments: {e}", file=sys.stderr)
    pass

# Global variable to hold the server process if running
server_process = None
selected_full_path = None
derived_base_dir = None
derived_filename = None

def select_edit_file():
    """
    Opens a dialog to select an existing file or specify a new file,
    derives paths, and updates the entry field.
    Note: The font size of this native OS file dialog is controlled by system settings,
    not by this application's font settings.
    """
    global selected_full_path, derived_base_dir, derived_filename

    # Use the last derived_base_dir as initialdir for subsequent selections.
    # Default to current working directory if nothing selected yet.
    start_dir = str(derived_base_dir) if derived_base_dir else str(Path.cwd())

    # Using asksaveasfilename allows selecting an existing file or typing a new one.
    filename_path = filedialog.asksaveasfilename(
        title="Select or Create Initial Python File",
        defaultextension=".py", # Suggest .py extension, appends if user omits it
        filetypes=(
            ("Python files", "*.py"),
            ("All files", "*.*")
        ),
        initialdir=start_dir # Set the initial directory
    )

    if filename_path: # If a path was returned (user didn't cancel)
        try:
            selected_full_path = Path(filename_path).resolve()
            derived_base_dir = selected_full_path.parent
            derived_filename = selected_full_path.name # Get just the filename
            base_file_var.set(str(selected_full_path)) # Display full path
            launch_button.config(state=tk.NORMAL)
            log_output(f"Selected File Path: {selected_full_path}")
            log_output(f"Derived Base Dir: {derived_base_dir}")
            log_output(f"Derived Filename: {derived_filename}")
        except Exception as e:
             messagebox.showerror("Error", f"Could not process file path: {e}")
             base_file_var.set("")
             launch_button.config(state=tk.DISABLED)
             selected_full_path = derived_base_dir = derived_filename = None


def launch_server():
    """Launches the server.py script in a separate process."""
    global server_process, derived_base_dir, derived_filename
    # Check if derived values are valid
    if not derived_base_dir or not derived_filename:
        messagebox.showerror("Error", "Please select or specify a valid Initial File first.")
        return
    if not os.path.isdir(derived_base_dir): # Base directory must exist
         messagebox.showerror("Error", f"Derived Base Directory is not valid or does not exist:\n{derived_base_dir}")
         return
    # The check for os.path.exists(os.path.join(derived_base_dir, derived_filename))
    # has been removed here because `asksaveasfilename` allows specifying a new file
    # that doesn't exist yet. The server.py script should handle creating it.
    if not derived_filename: # Should not happen if dialog returns a path
        messagebox.showerror("Error", "No filename was specified.")
        return
    if not os.path.exists(SERVER_SCRIPT_PATH):
         messagebox.showerror("Error", f"Server script not found at:\n{SERVER_SCRIPT_PATH}")
         return

    if server_process and server_process.poll() is None:
        messagebox.showwarning("Warning", "Server seems to be already running.")
        return

    command = [
        sys.executable,
        SERVER_SCRIPT_PATH,
        "--baseDir", str(derived_base_dir),
        "--initialFile", derived_filename,
    ]

    log_output(f"Attempting to launch server...")
    log_output(f"Command: {' '.join(command)}")

    try:
        server_process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        log_output(f"Server process started (PID: {server_process.pid}).")
        log_output("Monitoring server output below...")
        log_output(f"Access UI at: http://{SERVER_HOST_FOR_BROWSER}:{SERVER_PORT}")

        url_to_open = f"http://{SERVER_HOST_FOR_BROWSER}:{SERVER_PORT}"
        root.after(1000, lambda: webbrowser.open_new_tab(url_to_open))
        log_output(f"Attempting to open browser at {url_to_open} ...")
        
        launch_button.config(state=tk.DISABLED)
        browse_button.config(state=tk.DISABLED)
        stop_button.config(state=tk.NORMAL)

        threading.Thread(target=read_output, args=(server_process.stdout, "STDOUT"), daemon=True).start()
        threading.Thread(target=read_output, args=(server_process.stderr, "STDERR"), daemon=True).start()
        threading.Thread(target=monitor_server_process, daemon=True).start()

    except FileNotFoundError:
        messagebox.showerror("Error", f"Could not find Python or server script.\nCheck paths.\nCommand: {command}")
        log_output("Error: Failed to start server process (FileNotFoundError).")
    except Exception as e:
        messagebox.showerror("Error", f"Failed to launch server:\n{e}")
        log_output(f"Error: Failed to launch server: {e}")

def read_output(pipe, pipe_name):
    try:
        while True:
            line = pipe.readline()
            if not line:
                break
            log_output(f"[{pipe_name}] {line.strip()}")
        pipe.close()
        log_output(f"[{pipe_name}] Pipe closed.")
    except Exception as e:
        log_output(f"Error reading {pipe_name}: {e}")

def log_output(message):
    def append_message():
        if output_text.winfo_exists(): # Check if widget still exists
            output_text.config(state=tk.NORMAL)
            output_text.insert(tk.END, message + "\n")
            output_text.see(tk.END)
            output_text.config(state=tk.DISABLED)
    if root and root.winfo_exists():
        root.after(0, append_message)
    else:
        print(message)

def stop_server():
    global server_process
    if server_process and server_process.poll() is None:
        log_output("Attempting to stop server...")
        try:
            server_process.terminate()
            try:
                server_process.wait(timeout=2)
                log_output("Server process terminated.")
            except subprocess.TimeoutExpired:
                log_output("Server did not terminate gracefully, killing...")
                server_process.kill()
                server_process.wait()
                log_output("Server process killed.")
        except Exception as e:
            log_output(f"Error trying to stop server: {e}")
            messagebox.showerror("Error", f"Could not stop server:\n{e}")
        finally:
            server_process = None
            reset_ui_state()
    else:
        log_output("Server is not running or already stopped.")
        reset_ui_state()

def monitor_server_process():
    global server_process
    if server_process:
        return_code = server_process.poll()
        if return_code is not None:
            log_output(f"Server process exited with code: {return_code}")
            server_process = None
            if root and root.winfo_exists():
                 root.after(0, reset_ui_state)
        else:
            if root and root.winfo_exists():
                root.after(1000, monitor_server_process)

def reset_ui_state():
     if launch_button.winfo_exists(): # Check widgets before configuring
        launch_button.config(state=tk.NORMAL if base_file_var.get() else tk.DISABLED)
        browse_button.config(state=tk.NORMAL)
        stop_button.config(state=tk.DISABLED)

def on_closing():
    if server_process and server_process.poll() is None:
        if messagebox.askokcancel("Quit", "Server is running. Stop server and quit?"):
            stop_server() # This will call reset_ui_state
            root.destroy()
        # If user cancels, do nothing, window remains open
    else:
        root.destroy()

# --- Set up GUI ---
root = tk.Tk()
root.title("Vibe Server Launcher")

default_tk_font = tkFont.nametofont("TkDefaultFont")
default_tk_font.configure(size=APP_FONT_SIZE)
root.option_add("*Font", default_tk_font)
current_font_family = default_tk_font.actual().get("family", "Arial")
specific_widget_font_tuple = (current_font_family, APP_FONT_SIZE)

base_file_var = tk.StringVar()

file_frame = tk.Frame(root, pady=5)
file_frame.pack(fill=tk.X, padx=10)
tk.Label(file_frame, text="File to Edit:").pack(side=tk.LEFT)
file_entry = tk.Entry(file_frame, textvariable=base_file_var, state='readonly', width=50)
file_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
browse_button = tk.Button(file_frame, text="Browse...", command=select_edit_file)
browse_button.pack(side=tk.LEFT)

button_frame = tk.Frame(root, pady=5)
button_frame.pack(fill=tk.X, padx=10)
launch_button = tk.Button(button_frame, text="Launch Server", command=launch_server, state=tk.DISABLED)
launch_button.pack(side=tk.LEFT, padx=5)
stop_button = tk.Button(button_frame, text="Stop Server", command=stop_server, state=tk.DISABLED)
stop_button.pack(side=tk.LEFT, padx=5)

log_frame = tk.LabelFrame(root, text="Server Output", padx=10, pady=10, font=specific_widget_font_tuple)
log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
output_text = scrolledtext.ScrolledText(log_frame, height=15, width=80, state=tk.DISABLED, wrap=tk.WORD, font=specific_widget_font_tuple)
output_text.pack(fill=tk.BOTH, expand=True)

root.protocol("WM_DELETE_WINDOW", on_closing)

if 'root' in globals() and root.winfo_exists():
    root.mainloop()
