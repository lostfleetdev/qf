# QuickFind build plan

This plan turns the current spec scaffold into a working v1. It uses the decisions made on 2026-05-09:

- v1 only searches file paths.
- The HTTP server binds to localhost only.
- Indexing must work without administrator rights.
- The client is a TUI.
- Existing docs should be revised to match the smaller v1 before implementation.

## Current project state

The repository is still at scaffold stage.

- `main.py` prints `Hello from qf!`.
- `pyproject.toml` has no runtime dependencies.
- There is no `src/` package layout yet.
- There is no indexer, search engine, HTTP API, TUI, Windows startup integration, packaging, or test suite.
- `README.md` and `docs/index.md` describe a larger product than the code currently implements.

The immediate goal is not to build the full documented product. The immediate goal is to build a small, testable v1 that can index paths, search them quickly, and expose the result through a local HTTP API and TUI.

## v1 scope

### In scope

- Windows-first path indexing.
- No-admin indexing through normal directory walking.
- SQLite database for indexed paths and file metadata.
- Path-only ranking.
- Local HTTP API bound to `127.0.0.1`.
- TUI client that talks to the HTTP API.
- Basic config file support.
- Basic tests.
- Revised docs that describe what v1 actually does.

### Out of scope

- NTFS USN journal integration.
- MFT parsing.
- Content indexing.
- PDF, DOCX, image metadata, archive metadata, and EXIF parsing.
- System tray integration.
- Windows installer.
- Auto-start registration.
- Public LAN API.
- Service mode.
- Performance claims like "10,000 changes per second" until measured.

## Architecture

The project keeps the documented split:

- `qfi` is the backend process. It owns indexing, storage, search, and HTTP.
- `qf` is the user-facing client. It stays thin and talks to `qfi` over localhost HTTP.


Suggested entry points:

```toml
[project.scripts]
qfi = "qf.cli:run_indexer"
qf = "qf.cli:run_client"
```

## HTTP framework choice

Use Flask for v1.

FastAPI is a strong framework, but it adds ASGI, Uvicorn, type-driven request validation, and OpenAPI concepts. Those are useful later, but they are extra concepts for a beginner building a local-only API.

Flask is easier to read for this v1:

```python
@app.get("/search")
def search():
    query = request.args.get("q", "")
    return jsonify(...)
```

That is enough for `/health`, `/stats`, and `/search`. Flask also has a built-in test client, which keeps API tests simple.

Decision: use Flask now, revisit FastAPI only if the API grows enough to need typed request/response models or generated API docs.

Sources checked:

- Flask quickstart: https://flask.palletsprojects.com/en/stable/quickstart/
- Flask testing docs: https://flask.palletsprojects.com/en/stable/testing/
- FastAPI manual server docs: https://fastapi.tiangolo.com/deployment/manually/

## Local-only API contract

Bind only to:

```text
127.0.0.1:7890
```

Do not bind to `0.0.0.0` in v1.

Endpoints:

```text
GET /health
GET /stats
GET /search?q=<query>&limit=12&offset=0
POST /reindex
```

Drop `/toggle` from v1. It is a tray/service control feature, and v1 has no tray.

Search response:

```json
{
  "query": "config",
  "results": [
    {
      "path": "C:\\Users\\me\\project\\config.yaml",
      "score": 100,
      "match_type": "basename_exact",
      "size": 1024,
      "modified": "2026-05-09T10:30:00Z"
    }
  ],
  "total_indexed": 145000,
  "search_time_ms": 2
}
```

Use `content` nowhere in v1. There is no content search yet.

## Storage

Use one SQLite database:

```text
%LOCALAPPDATA%\QuickFind\index\main.db
```

Initial schema:

```sql
CREATE TABLE files (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    drive TEXT NOT NULL,
    basename TEXT NOT NULL,
    parent TEXT NOT NULL,
    extension TEXT NOT NULL,
    size INTEGER NOT NULL,
    modified INTEGER NOT NULL,
    created INTEGER,
    indexed_at INTEGER NOT NULL
);

CREATE INDEX idx_files_basename ON files(basename);
CREATE INDEX idx_files_extension ON files(extension);
CREATE INDEX idx_files_modified ON files(modified);
CREATE INDEX idx_files_parent ON files(parent);
```

Do not add FTS5 in v1 unless normal SQLite queries are too slow after measurement. Path search can start with normalized columns and targeted `LIKE` queries.

## Config

Use:

```text
%APPDATA%\QuickFind\config.json
```

v1 config:

```json
{
  "roots": ["C:\\Users\\raman"],
  "ignored_patterns": [
    "node_modules",
    ".git",
    ".svn",
    ".hg",
    "venv",
    ".venv",
    "env",
    ".env",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
    "out",
    ".idea",
    ".vscode",
    "target",
    "bin",
    "obj"
  ],
  "http_host": "127.0.0.1",
  "http_port": 7890,
  "result_limit": 12
}
```

Question still open: default root should probably be the user's home directory, not the whole drive. Whole-drive indexing without admin can produce many permission failures and slow first-run behavior.

## Indexing plan

Use `os.scandir` recursively for v1.

Behavior:

- Walk configured roots.
- Skip ignored directories by name.
- Catch permission errors and continue.
- Store path, basename, parent, extension, size, modified time, created time, and indexed timestamp.
- Use batched SQLite writes.
- Rebuild should use a temporary table or transaction so a failed rebuild does not destroy the last usable index.

No-admin rule:

- Never require elevation in v1.
- If a directory cannot be read, skip it and count it in stats.
- Expose skipped directory count through `/stats`.

Incremental updates:

- v1 can start with manual rebuild and optional periodic rescan.
- Do not add filesystem watching until the first path-only search is working and tested.

## Ranking plan

Implement deterministic path-first scoring:

| Match type | Score |
| --- | ---: |
| Exact basename without extension | 100 |
| Exact basename with extension | 95 |
| Basename starts with query | 80 |
| Basename contains query | 60 |
| Extension exact match | 50 |
| Parent segment exact match | 35 |
| Full path contains query | 25 |
| Fuzzy basename match | 20 |

Boosts:

- Modified in last 7 days: `+5`
- Modified in last 30 days: `+2`

Do not implement frequency boost in v1 unless the TUI records opens. There is no access history yet.

Normalize matching:

- Case-insensitive.
- Slash-insensitive where useful.
- Trim whitespace.
- Treat quoted strings as plain text in v1.

## TUI plan

Use Textual for the TUI.

Initial screens:

- Search input at the top.
- Result list in the main panel.
- Detail panel showing full path, size, modified time, and match type.
- Status bar showing backend state and total indexed files.

Keyboard behavior:

- Type to search.
- Up/down moves selection.
- Enter opens selected file with Windows default application.
- Ctrl+R triggers reindex.
- Esc quits.

The TUI should start `qfi` if it is not running. For v1, keep this simple:

- Check `GET /health`.
- If it fails, spawn `qfi`.
- Wait briefly and retry `/health`.
- If it still fails, show a clear error.

## Documentation plan

Revise docs before coding so they match v1.

Changes needed:

- State that v1 is path-only.
- Move NTFS USN, MFT, content indexing, tray, installer, and packaging into "future work".
- Remove claims about resource usage until measured.
- Remove content API parameters from v1 docs.
- Remove `/toggle` from v1 docs.
- Document localhost-only HTTP binding.
- Document no-admin indexing and skipped-directory behavior.
- Keep the `qfi` and `qf` split clear.

Files to revise:

- `README.md`
- `docs/index.md`
- `.github/copilot-instructions.md` if its API notes conflict with the revised docs

Note: `.github/` and `AGENTS.md` are currently untracked in this working tree. Do not rewrite them without checking whether they are user-owned local files.

## Implementation milestones

### Milestone 0: toolchain repair

Goal: make the project runnable through the documented workflow.

Tasks:

- Fix the local `uv` install or shim.
- Confirm `uv sync` works.
- Confirm `uv run python main.py` works.
- Add a basic test command once tests exist.

Acceptance:

- `uv run python main.py` works in PowerShell.

### Milestone 1: docs match v1

Goal: make the project honest before implementation starts.

Tasks:

- Rewrite `README.md` for v1 scope.
- Rewrite `docs/index.md` for v1 architecture.
- Add a short "future work" section for USN, content search, tray, packaging, and installer.

Acceptance:

- Docs no longer imply content search, NTFS USN, tray, or installer exist in v1.
- API docs only list v1 endpoints.

### Milestone 2: package skeleton

Goal: replace the stub with a real package layout.

Tasks:

- Create `src/qf/`.
- Add script entry points for `qf` and `qfi`.
- Add placeholder CLI commands.
- Add pytest.
- Add ruff if we want linting early.

Acceptance:

- `uv run qf --help` works.
- `uv run qfi --help` works.
- `uv run pytest` runs.

### Milestone 3: config and paths

Goal: centralize Windows paths and config behavior.

Tasks:

- Implement app data path resolution.
- Implement config loading with defaults.
- Validate root paths.
- Add tests for missing config, partial config, and bad config.

Acceptance:

- The app can run without an existing config file.
- Tests cover config defaults and overrides.

### Milestone 4: SQLite storage

Goal: create a durable path index.

Tasks:

- Implement schema creation.
- Implement batched upsert.
- Implement stats query.
- Implement simple search queries.
- Add storage tests using temporary databases.

Acceptance:

- Tests can insert and query file records.
- Re-running schema initialization is safe.

### Milestone 5: index rebuild

Goal: index configured roots without admin rights.

Tasks:

- Implement recursive scanner with ignored directory support.
- Catch permission errors.
- Write batches to SQLite.
- Track indexed file count, skipped directory count, and rebuild duration.
- Add tests with temporary directories.

Acceptance:

- Rebuild indexes a temp directory correctly.
- Ignored directories are skipped.
- Permission failures do not crash the rebuild.

### Milestone 6: path ranking

Goal: return useful results from path-only search.

Tasks:

- Implement ranking in a pure module.
- Unit-test exact, prefix, contains, extension, path segment, and fuzzy cases.
- Add modified-time boost tests.

Acceptance:

- Ranking tests define the expected ordering.
- Search returns stable ordering for equal scores.

### Milestone 7: local HTTP API

Goal: expose the backend over localhost.

Tasks:

- Add Flask app factory.
- Implement `/health`.
- Implement `/stats`.
- Implement `/search`.
- Implement `/reindex`.
- Add Flask test client tests.

Acceptance:

- Server binds to `127.0.0.1`.
- API tests run without starting a real network server.
- `/search` returns the documented JSON shape.

### Milestone 8: TUI client

Goal: provide the main user interface.

Tasks:

- Add Textual dependency.
- Build search input and result list.
- Call the local API as the query changes.
- Show backend health.
- Add "open selected file" behavior.
- Add "trigger reindex" behavior.

Acceptance:

- `qf` opens the TUI.
- Search results update from the local backend.
- Enter opens a selected result on Windows.

### Milestone 9: basic release build

Goal: package only after the app works.

Tasks:

- Decide Nuitka vs PyInstaller after testing dependency behavior.
- Create build scripts.
- Add icon assets only when needed.
- Document manual install instructions.

Acceptance:

- A local `.exe` build can run `qf` and `qfi`.
- Build steps are documented and repeatable.

## Research backlog

These areas need deeper research before they enter the product.

### NTFS USN journal

Needed for faster incremental indexing later.

Research questions:

- Which operations work without admin?
- What Python API should call `DeviceIoControl` safely?
- How should journal IDs and deleted records be handled?
- What fallback behavior is needed for non-NTFS volumes?

Starting source:

- Microsoft `FSCTL_READ_USN_JOURNAL`: https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ni-winioctl-fsctl_read_usn_journal

### Content search

Not in v1.

Research questions:

- Should content live in the same DB or a separate DB?
- Should FTS5 use internal content or external content tables?
- Which file types are worth supporting first?
- How should parsing failures and huge files be handled?

Starting source:

- SQLite FTS5 docs: https://www.sqlite.org/fts5.html

### Tray and startup

Not in v1.

Research questions:

- Should `qfi` be a tray app, a background process, or both?
- How should the tray process coordinate with Flask's server loop?
- Should startup use registry `Run`, Task Scheduler, or installer-created shortcuts?

Starting source:

- pystray docs: https://pystray.readthedocs.io/en/latest/usage.html

### Packaging

Not in v1.

Research questions:

- Does Nuitka package Flask, Textual, and Windows open-file behavior cleanly?
- Are data files or hidden imports needed?
- Is PyInstaller simpler for the first Windows build?

Starting source:

- Nuitka manual: https://nuitka.net/user-documentation/user-manual.html

## Risks

- Whole-drive no-admin indexing may be slow and noisy because many folders will be unreadable.
- Flask's built-in server is fine for local development and lightweight local use, but we should test shutdown and long-running behavior before relying on it as a daemon.
- TUI process management can get messy if `qf` starts `qfi` and then crashes. Keep pid/log handling simple but explicit.
- The docs currently describe future features as if they already exist. That should be fixed before code work starts.
- `uv` is currently broken in this shell. Dependency work should wait until that is fixed.

## Immediate next steps

1. Fix `uv` locally.
2. Revise `README.md` and `docs/index.md` to match this plan.
3. Create the `src/qf/` package skeleton.
4. Add config, SQLite storage, and ranking tests.
5. Build the path-only backend before starting the TUI.
