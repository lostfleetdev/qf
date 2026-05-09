# pry

`pry` is an early-stage Python project for a Windows-first file search tool.

At the moment, this repository contains a minimal runnable entrypoint plus product docs that describe the intended architecture.

## Current status

This project is in **prototype/spec phase**.

- Implemented now: a basic Python entrypoint (`main.py`).
- Documented target: indexer + HTTP API + TUI workflow (`docs/index.md`).
- Missing from current codebase: search engine, indexing pipeline, API server, TUI client, Windows packaging assets, and tests.

## Quick start

### Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)



## QuickFind system 

- NTFS USN-based indexing
- SQLite + FTS5 storage
- HTTP search API
- TUI client and tray integration
- Windows installer flow

These components are not yet present in source form here.

## Roadmap to a deployable build

1. Create a real package layout (`src/pry/`) with modules for indexer, API, and CLI/TUI.
2. Implement SQLite schema + index update pipeline.
3. Add HTTP API endpoints and health/stats handlers.
4. Add tests (unit + integration) and CI checks.
5. Add executable packaging (Nuitka/PyInstaller) after core behavior is stable.
