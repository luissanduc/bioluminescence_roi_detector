import traceback
import os
import subprocess
import sys

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox
    TK_AVAILABLE = True
except Exception:
    TK_AVAILABLE = False

from bioluminescence_roi_detector import process_all_folders


def _pick_directory_native():
    """Pick a directory without tkinter when possible."""
    if sys.platform == "darwin":
        script = 'POSIX path of (choose folder with prompt "Select IVIS parent directory")'
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        if result.returncode == 0:
            selected = result.stdout.strip()
            return selected if selected else None
        return None

    if os.name == "nt":
        ps = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$dlg = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$dlg.Description = 'Select IVIS parent directory'; "
            "$dlg.ShowNewFolderButton = $false; "
            "if ($dlg.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) "
            "{ Write-Output $dlg.SelectedPath }"
        )
        result = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
        if result.returncode == 0:
            selected = result.stdout.strip()
            return selected if selected else None
        return None

    selected = input("Enter full path to IVIS parent directory: ").strip()
    return selected or None


def main():
    cm_policy = "skip"

    if TK_AVAILABLE:
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(
            "Bioluminescence ROI Detector",
            "Select the parent directory that contains your IVIS subfolders.\n"
            "The tool will process all matching folders recursively.\n"
            "Safety mode is fixed to SKIP folders when cm/pixel fallback occurs.",
        )
        selected_dir = filedialog.askdirectory(title="Select IVIS parent directory")
        if not selected_dir:
            messagebox.showinfo("Bioluminescence ROI Detector", "No folder selected. Exiting.")
            return
    else:
        print("tkinter is not available; using OS-native/terminal fallback prompts.")
        selected_dir = _pick_directory_native()
        if not selected_dir:
            print("No folder selected. Exiting.")
            return
        print("Safety mode is fixed to SKIP when cm/pixel fallback occurs.")

    try:
        process_all_folders(selected_dir, cm_fallback_policy=cm_policy)
    except Exception as exc:
        if TK_AVAILABLE:
            messagebox.showerror(
                "Bioluminescence ROI Detector",
                f"Processing failed:\n{exc}\n\n{traceback.format_exc()}",
            )
        else:
            print(f"Processing failed: {exc}")
            print(traceback.format_exc())
        return

    if TK_AVAILABLE:
        messagebox.showinfo(
            "Bioluminescence ROI Detector",
            "Processing complete. Check terminal output for per-folder details.",
        )
    else:
        print("Processing complete. Check terminal output for per-folder details.")


if __name__ == "__main__":
    main()
