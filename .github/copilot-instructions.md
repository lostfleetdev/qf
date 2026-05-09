# Copilot Instructions for `qf`

## Build, test, and lint commands

- **Run current tracked app entry point:** `python main.py`
- **Build binaries (documented target in `README.md`):**
  - `uv run nuitka --onefile --windows-icon=qf.ico --product-name=QuickFind src/qf.py -o qf.exe`
  - `uv run nuitka --onefile --windows-icon=qfi.ico --product-name=QuickFindIndexer src/qfi.py -o qfi.exe`
- **Tests:** No test runner or test files are currently configured in tracked files.
- **Lint/type-check:** No lint or type-check commands are currently configured in tracked files.

## High-level architecture

The checked-in Python code is currently a minimal bootstrap (`main.py`), but `README.md` and `docs/index.md` define the intended system architecture:

1. `qfi.exe` is the long-running backend: filesystem indexer + HTTP API server.
2. `qf.exe` is the interactive search client (TUI) that calls qfi's HTTP endpoints.
3. qf is expected to auto-start qfi when qfi is not already running.
4. Search is designed as **path-first ranking** with optional/fallback content search.
5. Persistent state is documented under `%LOCALAPPDATA%\QuickFind\index\` (SQLite index/content DBs), and runtime config under `%APPDATA%\QuickFind\config.json`.

## Key repository-specific conventions

- This project is **Windows-first** (NTFS USN journal, `%APPDATA%`/`%LOCALAPPDATA%`, `.exe` deliverables). Keep Windows path and filesystem assumptions unless explicitly refactoring cross-platform.
- Keep the **qf (client) vs qfi (backend)** boundary clear: qfi owns indexing, storage, and HTTP; qf stays a lightweight interface over that API.
- Preserve the documented search contract that **path relevance outranks content relevance**.
- Preserve documented HTTP endpoints and config shape when implementing code:
  - Endpoints include `/search`, `/stats`, `/health` (and docs also mention `/toggle`).
  - Config keys include `ignored_patterns`, `indexed_extensions`, `http_port`, `auto_start`, `watch_changes`, `result_limit`.
- `README.md` and `docs/index.md` both matter, but they currently differ in some API parameter naming (`c` vs `content` for content search). When implementing or changing API behavior, resolve and update both docs together.
