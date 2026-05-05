# Port & URL Monitor

A lightweight Windows desktop app that monitors local ports and remote URLs, showing real-time status on a dark-themed dashboard. Get notified instantly via Windows Toast Notifications when a target goes offline.

## Quick Start

### Option A: Run the .exe (no Python needed)

1. Copy `PortMonitor.exe` from the `dist/` folder to any directory
2. Double-click to launch
3. Start adding targets to monitor

### Option B: Run from source

```
pip install requests plyer
python monitor.py
```

## How to Use

### Adding a Target

1. Click **Add**
2. Fill in:
   - **Name** — A friendly label (e.g. "Google", "My API Server"). Optional but helpful.
   - **Host** — The address to monitor (e.g. `google.com`, `192.168.1.10`, `localhost`)
   - **Port** — The port number (auto-fills to 443 for URL-type hosts)
3. Click **Save**

### Editing a Target

1. Select a target in the list
2. Click **Edit**
3. Update the fields and click **Save**

### Removing a Target

1. Select a target in the list
2. Click **Remove**

### Adjusting Settings

1. Click **Settings** (right side of the button bar)
2. Change:
   - **Check Interval (s)** — How often targets are pinged (default: 30 seconds)
   - **Timeout (s)** — How long to wait for a response before marking offline (default: 5 seconds)
3. Click **Save**

## Status Indicators

| Color | Meaning |
|-------|---------|
| Green | Online — target is reachable |
| Red   | Offline — target is not responding |
| Gray  | Unknown — not yet checked |

## Notifications

When a target transitions from Online to Offline, a Windows Toast Notification appears in the bottom-right corner. Duplicate notifications are suppressed — you'll only be notified once per outage until the target comes back online.

## Data Storage

Your target list is saved automatically to `targets.json` in the same folder as the app. This file:

- Is created automatically on first use
- Updates every time you add, edit, or remove a target
- Persists across restarts
- Can be opened in Notepad for manual edits if needed

## Target Types

The app automatically classifies targets:

- **Port** — IP addresses (e.g. `192.168.1.1`) and plain hostnames (e.g. `localhost`). Checked via TCP socket connection.
- **URL** — Domain names (e.g. `google.com`, `api.example.org`). Checked via HTTPS GET request (HTTP for port 80).

## Building the .exe Yourself

```
pip install pyinstaller
pyinstaller --onefile --windowed --name "PortMonitor" monitor.py
```

Output: `dist/PortMonitor.exe`

## Requirements (source only)

- Python 3.10+
- `requests`
- `plyer`
- `tkinter` (included with Python on Windows)
