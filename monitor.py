"""
Port & URL Monitor
===================
A Windows desktop application that monitors local ports and remote URLs,
providing real-time status updates on a dark-themed tkinter dashboard.
Alerts the user via Windows Toast Notifications when a target goes offline.
Runs monitoring in background threads and persists target data to a local JSON file.
"""

# =============================================================================
# Imports
# =============================================================================

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import socket
import json
import re
import sys
import os

import requests
from plyer import notification

# =============================================================================
# Constants
# =============================================================================

CHECK_INTERVAL = 30   # Seconds between monitoring cycles
TIMEOUT = 5           # Seconds before a network check times out
DATA_FILE = "targets.json"  # Local file for persisting target list

# =============================================================================
# Target Data Model
# =============================================================================

class Target:
    """A network endpoint to monitor (local port or remote URL)."""

    def __init__(self, host: str, port: int, target_type: str,
                 name: str = "", status: str = "Unknown", notified: bool = False):
        self.name = name                # friendly label for easy recognition
        self.host = host
        self.port = port
        self.target_type = target_type  # "port" or "url"
        self.status = status            # "Online", "Offline", or "Unknown"
        self.notified = notified        # True if offline notification was sent


# =============================================================================
# Validation and Classification
# =============================================================================

def validate_target(host: str, port_str: str) -> tuple[bool, str]:
    """Validate host and port input.

    Returns (True, "") if valid, or (False, error_message) if invalid.
    Host must be non-empty after stripping whitespace.
    Port must be an integer in the range 1–65535.
    """
    if not host or not host.strip():
        return False, "Host cannot be empty."

    try:
        port = int(port_str)
    except (ValueError, TypeError):
        return False, "Port must be a valid integer."

    if port < 1 or port > 65535:
        return False, "Port must be in the range 1–65535."

    return True, ""


def classify_target(host: str) -> str:
    """Classify a host as 'url' or 'port'.

    Returns 'url' if the host contains a dot and is NOT a pure IPv4 address
    (e.g. 192.168.1.1). Returns 'port' otherwise.
    """
    if "." not in host:
        return "port"

    # Check if host is a pure IPv4 address (e.g. 192.168.1.1)
    ipv4_pattern = r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"
    if re.match(ipv4_pattern, host.strip()):
        return "port"

    return "url"


# =============================================================================
# Target List Management
# =============================================================================

def add_target(targets: list, host: str, port: int, target_type: str) -> Target:
    """Create a new Target and append it to the list.

    Returns the newly created Target.
    """
    target = Target(host=host, port=port, target_type=target_type)
    targets.append(target)
    return target


def remove_target(targets: list, index: int) -> Target:
    """Remove and return the target at the given index."""
    return targets.pop(index)


def edit_target(target: Target, host: str, port: int, target_type: str) -> None:
    """Update an existing target's fields in place."""
    target.host = host
    target.port = port
    target.target_type = target_type


# =============================================================================
# Persistence Manager
# =============================================================================

def save_targets(targets: list[Target], filepath: str) -> None:
    """Serialize the target list to JSON and write to filepath.

    Only persists host, port, and target_type. Runtime-only fields
    (status, notified) are excluded.
    """
    data = [
        {"name": t.name, "host": t.host, "port": t.port, "target_type": t.target_type}
        for t in targets
    ]
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except IOError as e:
        print(f"Warning: could not save targets to {filepath}: {e}", file=sys.stderr)


def load_targets(filepath: str) -> list[Target]:
    """Load targets from a JSON file.

    Returns an empty list if the file is missing or contains invalid JSON.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        print(f"Warning: {filepath} contains invalid JSON, starting with empty list.", file=sys.stderr)
        return []

    return [
        Target(host=item["host"], port=item["port"],
               target_type=item["target_type"], name=item.get("name", ""))
        for item in data
    ]


# =============================================================================
# Network Checkers
# =============================================================================

def check_port(host: str, port: int, timeout: float = 5.0) -> bool:
    """Attempt a TCP socket connection to host:port.

    Returns True if connect_ex() returns 0 (success), False otherwise.
    Always closes the socket in a finally block.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(timeout)
        result = s.connect_ex((host, port))
        return result == 0
    except Exception:
        return False
    finally:
        s.close()


def check_url(host: str, port: int, timeout: float = 5.0) -> bool:
    """Send an HTTP(S) GET request to host:port.

    Uses http:// for port 80, https:// for all other ports.
    Returns True if the response status code is < 400, False on any
    exception or 4xx/5xx response.
    """
    scheme = "http" if port == 80 else "https"
    url = f"{scheme}://{host}:{port}"
    try:
        resp = requests.get(url, timeout=timeout)
        return resp.status_code < 400
    except Exception:
        return False

# =============================================================================
# Alarm System
# =============================================================================

def send_notification(target: Target) -> None:
    """Send a Windows Toast Notification for an offline target using plyer.

    Wraps the call in try/except so notification backend failures
    (e.g. running on a non-Windows system) are logged but never crash.
    """
    try:
        label = f"{target.name} ({target.host}:{target.port})" if target.name else f"{target.host}:{target.port}"
        notification.notify(
            title="Target Offline",
            message=f"{label} is offline.",
            timeout=5,
        )
    except Exception as e:
        print(f"Warning: could not send notification: {e}", file=sys.stderr)


def update_target_status(target: Target, is_online: bool, notify_func: callable) -> None:
    """Handle target state transitions and trigger notifications.

    - Online result: set status to "Online", reset notified to False.
    - Offline result: set status to "Offline". If previous status was
      "Online" and notified is False, call notify_func(target) and set
      notified to True. Otherwise suppress duplicate notification.
    """
    if is_online:
        target.status = "Online"
        target.notified = False
    else:
        previous_status = target.status
        target.status = "Offline"
        if previous_status != "Offline" and not target.notified:
            notify_func(target)
            target.notified = True



# =============================================================================
# Monitor Thread
# =============================================================================

def monitor_loop(targets: list, lock: threading.Lock,
                 stop_event: threading.Event, update_callback: callable,
                 get_settings: callable = None) -> None:
    """Background loop that checks all targets every check_interval seconds.

    On each cycle:
      1. Acquire lock, snapshot the target list, release lock.
      2. Check each target using check_port or check_url.
      3. Acquire lock, update each target's status via update_target_status.
      4. Call update_callback to refresh the GUI.
      5. Sleep in 1-second increments, checking stop_event for responsive shutdown.
    """
    while not stop_event.is_set():
        # --- get current settings ---
        if get_settings:
            interval, timeout = get_settings()
        else:
            interval, timeout = CHECK_INTERVAL, TIMEOUT

        # --- snapshot targets under lock ---
        with lock:
            snapshot = list(targets)

        # --- check each target (no lock held) ---
        results = []
        for target in snapshot:
            if stop_event.is_set():
                return
            if target.target_type == "url":
                is_online = check_url(target.host, target.port, timeout)
            else:
                is_online = check_port(target.host, target.port, timeout)
            results.append((target, is_online))

        # --- update statuses under lock ---
        with lock:
            for target, is_online in results:
                update_target_status(target, is_online, send_notification)

        # --- notify GUI ---
        update_callback()

        # --- sleep in 1-second increments for responsive shutdown ---
        for _ in range(interval):
            if stop_event.is_set():
                return
            stop_event.wait(1)


# =============================================================================
# GUI – MonitorApp
# =============================================================================

class MonitorApp:
    """Dark-themed tkinter dashboard for managing and monitoring targets."""

    # -- colour palette -------------------------------------------------------
    BG           = "#1e1e1e"
    FG           = "#d4d4d4"
    FIELD_BG     = "#252526"
    SELECTED_BG  = "#264f78"
    BUTTON_BG    = "#333333"
    ONLINE_FG    = "#4ec9b0"
    OFFLINE_FG   = "#f44747"
    UNKNOWN_FG   = "#d4d4d4"

    def __init__(self, root: tk.Tk):
        self.root = root
        self.targets: list[Target] = []
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.check_interval = CHECK_INTERVAL
        self.timeout = TIMEOUT

        # -- window setup -----------------------------------------------------
        self.root.title("Port & URL Monitor")
        self.root.geometry("700x400")
        self.root.configure(bg=self.BG)

        # -- ttk style (dark theme) -------------------------------------------
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("Treeview",
                        background=self.FIELD_BG,
                        foreground=self.FG,
                        fieldbackground=self.FIELD_BG,
                        borderwidth=0,
                        rowheight=24)
        style.configure("Treeview.Heading",
                        background=self.BUTTON_BG,
                        foreground=self.FG,
                        borderwidth=0)
        style.map("Treeview",
                  background=[("selected", self.SELECTED_BG)],
                  foreground=[("selected", self.FG)])

        # -- treeview (target list) -------------------------------------------
        columns = ("Name", "Host", "Port", "Type", "Status")
        self.tree = ttk.Treeview(self.root, columns=columns,
                                 show="headings", selectmode="browse")
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, anchor="center")
        self.tree.column("Name", width=120)
        self.tree.column("Host", width=160)

        # status colour tags
        self.tree.tag_configure("Online",  foreground=self.ONLINE_FG)
        self.tree.tag_configure("Offline", foreground=self.OFFLINE_FG)
        self.tree.tag_configure("Unknown", foreground=self.UNKNOWN_FG)

        self.tree.pack(fill="both", expand=True, padx=8, pady=(8, 4))

        # -- button bar -------------------------------------------------------
        btn_frame = tk.Frame(self.root, bg=self.BG)
        btn_frame.pack(fill="x", padx=8, pady=(4, 8))

        btn_opts = dict(bg=self.BUTTON_BG, fg=self.FG,
                        activebackground=self.SELECTED_BG,
                        activeforeground=self.FG,
                        relief="flat", padx=12, pady=4)

        tk.Button(btn_frame, text="Add",    command=self.add_target,
                  **btn_opts).pack(side="left", padx=(0, 4))
        tk.Button(btn_frame, text="Edit",   command=self.edit_target,
                  **btn_opts).pack(side="left", padx=4)
        tk.Button(btn_frame, text="Remove", command=self.remove_target,
                  **btn_opts).pack(side="left", padx=4)
        tk.Button(btn_frame, text="Settings", command=self.edit_settings,
                  **btn_opts).pack(side="right", padx=4)

        # -- startup: load persisted targets and start monitoring -------------
        self.targets = load_targets(DATA_FILE)
        self.refresh_display()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._start_monitoring()

    # -- display refresh ------------------------------------------------------

    def refresh_display(self) -> None:
        """Clear and repopulate the Treeview with current target statuses."""
        for item in self.tree.get_children():
            self.tree.delete(item)

        with self.lock:
            for target in self.targets:
                tag = target.status  # "Online", "Offline", or "Unknown"
                self.tree.insert("", "end",
                                 values=(target.name, target.host, target.port,
                                         target.target_type, target.status),
                                 tags=(tag,))

    # -- dialog helper --------------------------------------------------------

    def _open_dialog(self, title: str, name_default: str = "",
                     host_default: str = "",
                     port_default: str = "", callback=None) -> None:
        """Open a Toplevel dialog for adding or editing a target.

        Parameters
        ----------
        title : str
            Window title for the dialog.
        name_default / host_default / port_default : str
            Pre-filled values for the entry fields.
        callback : callable(name: str, host: str, port_str: str) | None
            Called with the validated inputs when the user clicks Save.
        """
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.geometry("340x200")
        dlg.configure(bg=self.BG)
        dlg.resizable(False, False)
        dlg.grab_set()  # make dialog modal

        # -- Name row ---------------------------------------------------------
        tk.Label(dlg, text="Name:", bg=self.BG, fg=self.FG).grid(
            row=0, column=0, padx=12, pady=(16, 4), sticky="e")
        name_var = tk.StringVar(value=name_default)
        name_entry = tk.Entry(dlg, textvariable=name_var,
                              bg=self.FIELD_BG, fg=self.FG,
                              insertbackground=self.FG, width=28)
        name_entry.grid(row=0, column=1, padx=(0, 12), pady=(16, 4))

        # -- Host row ---------------------------------------------------------
        tk.Label(dlg, text="Host:", bg=self.BG, fg=self.FG).grid(
            row=1, column=0, padx=12, pady=4, sticky="e")
        host_var = tk.StringVar(value=host_default)
        host_entry = tk.Entry(dlg, textvariable=host_var,
                              bg=self.FIELD_BG, fg=self.FG,
                              insertbackground=self.FG, width=28)
        host_entry.grid(row=1, column=1, padx=(0, 12), pady=4)

        # -- Port row ---------------------------------------------------------
        tk.Label(dlg, text="Port:", bg=self.BG, fg=self.FG).grid(
            row=2, column=0, padx=12, pady=4, sticky="e")
        port_var = tk.StringVar(value=port_default)
        port_entry = tk.Entry(dlg, textvariable=port_var,
                              bg=self.FIELD_BG, fg=self.FG,
                              insertbackground=self.FG, width=28)
        port_entry.grid(row=2, column=1, padx=(0, 12), pady=4)

        # Auto-fill port 443 when host looks like a URL and port is empty
        def _on_host_focus_out(event):
            host = host_var.get().strip()
            if host and not port_var.get().strip():
                if classify_target(host) == "url":
                    port_var.set("443")

        host_entry.bind("<FocusOut>", _on_host_focus_out)

        # -- Button row -------------------------------------------------------
        btn_frame = tk.Frame(dlg, bg=self.BG)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=(12, 8))

        btn_opts = dict(bg=self.BUTTON_BG, fg=self.FG,
                        activebackground=self.SELECTED_BG,
                        activeforeground=self.FG,
                        relief="flat", padx=12, pady=4)

        def on_save():
            host = host_var.get().strip()
            port_str = port_var.get().strip()
            valid, err = validate_target(host, port_str)
            if not valid:
                messagebox.showerror("Invalid Input", err, parent=dlg)
                return
            if callback:
                callback(name_var.get().strip(), host, port_str)
            dlg.destroy()

        tk.Button(btn_frame, text="Save", command=on_save,
                  **btn_opts).pack(side="left", padx=(0, 8))
        tk.Button(btn_frame, text="Cancel", command=dlg.destroy,
                  **btn_opts).pack(side="left")

        name_entry.focus_set()

    # -- target actions -------------------------------------------------------

    def add_target(self) -> None:
        """Open a dialog to add a new target."""

        def _on_add(name: str, host: str, port_str: str):
            target_type = classify_target(host)
            port = int(port_str)
            with self.lock:
                new_target = Target(host=host, port=port,
                                    target_type=target_type, name=name)
                self.targets.append(new_target)
                save_targets(self.targets, DATA_FILE)
            self.refresh_display()

        self._open_dialog("Add Target", callback=_on_add)

    def edit_target(self) -> None:
        """Open a dialog pre-filled with the selected target's values."""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("No Selection",
                                   "Please select a target to edit.")
            return

        item = selected[0]
        idx = self.tree.index(item)

        with self.lock:
            if idx >= len(self.targets):
                return
            target = self.targets[idx]
            current_name = target.name
            current_host = target.host
            current_port = str(target.port)

        def _on_edit(name: str, host: str, port_str: str):
            target_type = classify_target(host)
            port = int(port_str)
            with self.lock:
                if idx < len(self.targets):
                    t = self.targets[idx]
                    t.name = name
                    t.host = host
                    t.port = port
                    t.target_type = target_type
                    save_targets(self.targets, DATA_FILE)
            self.refresh_display()

        self._open_dialog("Edit Target",
                          name_default=current_name,
                          host_default=current_host,
                          port_default=current_port,
                          callback=_on_edit)

    def remove_target(self) -> None:
        """Remove the selected target from the list."""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("No Selection",
                                   "Please select a target to remove.")
            return

        item = selected[0]
        idx = self.tree.index(item)

        with self.lock:
            if idx < len(self.targets):
                self.targets.pop(idx)
                save_targets(self.targets, DATA_FILE)
        self.refresh_display()

    def edit_settings(self) -> None:
        """Open a dialog to edit check interval and timeout."""
        dlg = tk.Toplevel(self.root)
        dlg.title("Settings")
        dlg.geometry("300x160")
        dlg.configure(bg=self.BG)
        dlg.resizable(False, False)
        dlg.grab_set()

        tk.Label(dlg, text="Check Interval (s):", bg=self.BG, fg=self.FG).grid(
            row=0, column=0, padx=12, pady=(16, 4), sticky="e")
        interval_var = tk.StringVar(value=str(self.check_interval))
        tk.Entry(dlg, textvariable=interval_var, bg=self.FIELD_BG, fg=self.FG,
                 insertbackground=self.FG, width=10).grid(
            row=0, column=1, padx=(0, 12), pady=(16, 4))

        tk.Label(dlg, text="Timeout (s):", bg=self.BG, fg=self.FG).grid(
            row=1, column=0, padx=12, pady=4, sticky="e")
        timeout_var = tk.StringVar(value=str(self.timeout))
        tk.Entry(dlg, textvariable=timeout_var, bg=self.FIELD_BG, fg=self.FG,
                 insertbackground=self.FG, width=10).grid(
            row=1, column=1, padx=(0, 12), pady=4)

        btn_frame = tk.Frame(dlg, bg=self.BG)
        btn_frame.grid(row=2, column=0, columnspan=2, pady=(12, 8))

        btn_opts = dict(bg=self.BUTTON_BG, fg=self.FG,
                        activebackground=self.SELECTED_BG,
                        activeforeground=self.FG,
                        relief="flat", padx=12, pady=4)

        def on_save():
            try:
                new_interval = int(interval_var.get().strip())
                new_timeout = int(timeout_var.get().strip())
            except ValueError:
                messagebox.showerror("Invalid Input",
                                     "Values must be valid integers.", parent=dlg)
                return
            if new_interval < 1:
                messagebox.showerror("Invalid Input",
                                     "Check interval must be at least 1 second.", parent=dlg)
                return
            if new_timeout < 1:
                messagebox.showerror("Invalid Input",
                                     "Timeout must be at least 1 second.", parent=dlg)
                return
            self.check_interval = new_interval
            self.timeout = new_timeout
            dlg.destroy()

        tk.Button(btn_frame, text="Save", command=on_save,
                  **btn_opts).pack(side="left", padx=(0, 8))
        tk.Button(btn_frame, text="Cancel", command=dlg.destroy,
                  **btn_opts).pack(side="left")

    # -- monitoring lifecycle -------------------------------------------------

    def _schedule_refresh(self) -> None:
        """Schedule a GUI refresh from the monitor thread.

        Uses root.after(0, ...) to safely push the update onto the
        main tkinter thread.
        """
        self.root.after(0, self.refresh_display)

    def _get_settings(self) -> tuple[int, float]:
        """Return current (check_interval, timeout) for the monitor thread."""
        return self.check_interval, self.timeout

    def _start_monitoring(self) -> None:
        """Create and start the background monitor thread as a daemon."""
        self._monitor_thread = threading.Thread(
            target=monitor_loop,
            args=(self.targets, self.lock, self.stop_event,
                  self._schedule_refresh, self._get_settings),
            daemon=True,
        )
        self._monitor_thread.start()

    def on_close(self) -> None:
        """Signal the monitor thread to stop and destroy the root window."""
        self.stop_event.set()
        self.root.destroy()


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    root = tk.Tk()
    app = MonitorApp(root)
    root.mainloop()
