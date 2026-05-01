# QuickFind

A fast file search tool for Windows. It indexes your filesystem in the background and serves results via TUI or HTTP API.

## Quick start

```
qf                    # Open TUI search
qf --server           # Start HTTP server on port 7890
```

## How it works

**qfi.exe** runs in the background. It indexes files using NTFS USN journal and watches for changes. It also serves the HTTP API.

**qf.exe** is the search interface. It connects to qfi's HTTP API and provides an interactive TUI for searching.

If qfi isn't running, qf starts it automatically.

## Search behavior

File names are searched first. Content is searched second. Path matches always rank higher. Use `--content` to search inside files only.

## HTTP API

```
GET /search?q=query         Search by filename
GET /search?q=query&c=1     Search inside files
GET /stats                  Index stats
GET /health                 Health check
```

## Configuration

Edit `%APPDATA%\QuickFind\config.json`:

```json
{
  "ignored_patterns": ["node_modules", ".git", "__pycache__"],
  "indexed_extensions": [".txt", ".md", ".py", ".js"],
  "http_port": 7890,
  "auto_start": true
}
```

## Files

- Binary: `C:\Program Files\QuickFind\`
- Data: `%LOCALAPPDATA%\QuickFind\`

## Build

```bash
uv run nuitka --onefile --windows-icon=qf.ico --product-name=QuickFind src/qf.py -o qf.exe
uv run nuitka --onefile --windows-icon=qfi.ico --product-name=QuickFindIndexer src/qfi.py -o qfi.exe
```