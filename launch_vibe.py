import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import subprocess
import sys
import os
import threading # To run the server without blocking the GUI
from pathlib import Path
import webbrowser # <-- Import webbrowser

# --- Configuration ---
SERVER_SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "server.py")
SERVER_HOST_FOR_BROWSER = "127.0.0.1"
# Make port easily configurable if needed later
SERVER_PORT = 8000

# Global variable to hold the server process if running
server_process = None
# Use separate vars for clarity
selected_full_path = None
derived_base_dir = None
derived_filename = None

def select_edit_file():
    """Opens a dialog to select a file, derives paths, and updates the entry field."""
    global selected_full_path, derived_base_dir, derived_filename
    filename = filedialog.askopenfilename(
        title="Select Initial Python File",
        filetypes=(
            ("Python files", "*.py"),
            ("All files", "*.*")
        )
    )
    if filename:
        try:
            selected_full_path = Path(filename).resolve()
            derived_base_dir = selected_full_path.parent
            derived_filename = selected_full_path.name # Get just the filename
            base_file_var.set(str(selected_full_path)) # Display full path
            launch_button.config(state=tk.NORMAL)
            log_output(f"Selected File: {selected_full_path}")
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
        messagebox.showerror("Error", "Please select a valid Initial File first.")
        return
    if not os.path.isdir(derived_base_dir):
         messagebox.showerror("Error", f"Derived Base Directory is not valid:\n{derived_base_dir}")
         return
    if not os.path.exists(os.path.join(derived_base_dir, derived_filename)):
        messagebox.showerror("Error", f"Selected file not found:\n{os.path.join(derived_base_dir, derived_filename)}")
        return
    if not os.path.exists(SERVER_SCRIPT_PATH):
         messagebox.showerror("Error", f"Server script not found at:\n{SERVER_SCRIPT_PATH}")
         return

    if server_process and server_process.poll() is None:
        messagebox.showwarning("Warning", "Server seems to be already running.")
        return

    # Construct the command using derived parts
    command = [
        sys.executable,
        SERVER_SCRIPT_PATH,
        "--baseDir", str(derived_base_dir),
        "--initialFile", derived_filename, # Pass only the filename
        # "--port", str(SERVER_PORT) # If needed
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


        # --- Open Browser ---
        url_to_open = f"http://{SERVER_HOST_FOR_BROWSER}:{SERVER_PORT}"
        # Wait a tiny bit for server to potentially bind port before opening browser
        root.after(1000, lambda: webbrowser.open_new_tab(url_to_open))
        log_output(f"Attempting to open browser at {url_to_open} ...")
        # --- End Open Browser ---
        
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

# --- Functions read_output, log_output, stop_server, monitor_server_process, reset_ui_state, on_closing remain the same ---
# ... (Paste the rest of the functions from the previous correct version here) ...
def read_output(pipe, pipe_name):
    """Reads output from the server process pipe and logs it."""
    try:
        while True:
            line = pipe.readline()
            if not line:
                break
            log_output(f"[{pipe_name}] {line.strip()}")
        pipe.close() # Close the pipe when done reading
        log_output(f"[{pipe_name}] Pipe closed.")
    except Exception as e:
        log_output(f"Error reading {pipe_name}: {e}")

def log_output(message):
    """Appends a message to the text area, ensuring GUI updates happen on the main thread."""
    def append_message():
        output_text.config(state=tk.NORMAL)
        output_text.insert(tk.END, message + "\n")
        output_text.see(tk.END) # Scroll to the end
        output_text.config(state=tk.DISABLED)
    # Schedule the GUI update in the main Tkinter thread
    root.after(0, append_message)

def stop_server():
    """Attempts to terminate the running server process."""
    global server_process
    if server_process and server_process.poll() is None: # Check if process exists and is running
        log_output("Attempting to stop server...")
        try:
            server_process.terminate() # Ask nicely first
            try:
                # Wait a short time for termination
                server_process.wait(timeout=2)
                log_output("Server process terminated.")
            except subprocess.TimeoutExpired:
                log_output("Server did not terminate gracefully, killing...")
                server_process.kill() # Force kill if necessary
                server_process.wait() # Wait for kill
                log_output("Server process killed.")
        except Exception as e:
            log_output(f"Error trying to stop server: {e}")
            messagebox.showerror("Error", f"Could not stop server:\n{e}")
        finally:
            server_process = None
            reset_ui_state() # Re-enable buttons
    else:
        log_output("Server is not running or already stopped.")
        reset_ui_state() # Ensure UI is reset even if process was already gone

def monitor_server_process():
    """Periodically checks if the server process has exited."""
    global server_process
    if server_process:
        return_code = server_process.poll()
        if return_code is not None: # Process has terminated
            log_output(f"Server process exited with code: {return_code}")
            server_process = None
            root.after(0, reset_ui_state) # Schedule UI reset in main thread
        else:
            # Check again later
            root.after(1000, monitor_server_process) # Check every second

def reset_ui_state():
     """Resets buttons to their initial enabled/disabled state."""
     launch_button.config(state=tk.NORMAL if base_file_var.get() else tk.DISABLED)
     browse_button.config(state=tk.NORMAL)
     stop_button.config(state=tk.DISABLED)


def on_closing():
    """Handles window closing: stops server if running."""
    if server_process and server_process.poll() is None:
        if messagebox.askokcancel("Quit", "Server is running. Stop server and quit?"):
            stop_server()
            root.destroy()
    else:
        root.destroy()

# --- Set up GUI ---
root = tk.Tk()
root.title("Vibe Server Launcher")

base_file_var = tk.StringVar()

# Frame for directory selection
file_frame = tk.Frame(root, pady=5)
file_frame.pack(fill=tk.X, padx=10)

tk.Label(file_frame, text="File to Edit:").pack(side=tk.LEFT)
file_entry = tk.Entry(file_frame, textvariable=base_file_var, state='readonly', width=50)
file_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
browse_button = tk.Button(file_frame, text="Browse...", command=select_edit_file)
browse_button.pack(side=tk.LEFT)

# Frame for control buttons
button_frame = tk.Frame(root, pady=5)
button_frame.pack(fill=tk.X, padx=10)

launch_button = tk.Button(button_frame, text="Launch Server", command=launch_server, state=tk.DISABLED)
launch_button.pack(side=tk.LEFT, padx=5)

stop_button = tk.Button(button_frame, text="Stop Server", command=stop_server, state=tk.DISABLED)
stop_button.pack(side=tk.LEFT, padx=5)


# Output log area
log_frame = tk.LabelFrame(root, text="Server Output", padx=10, pady=10)
log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

output_text = scrolledtext.ScrolledText(log_frame, height=15, width=80, state=tk.DISABLED, wrap=tk.WORD)
output_text.pack(fill=tk.BOTH, expand=True)

# Handle window close event
root.protocol("WM_DELETE_WINDOW", on_closing)

root.mainloop()
