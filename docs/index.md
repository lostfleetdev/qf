# QuickFind

A fast, lightweight file search tool for Windows. It indexes your filesystem in the background and serves results via TUI or HTTP API.

## What it does

QuickFind watches your filesystem and keeps an index up to date. When you search, it returns results instantly—no waiting for a filesystem scan.

Think of it as Everything for the command line, with an HTTP interface for scripting and integration with other tools.

## Components

### qfi.exe

The indexer and HTTP server combined. It:

- Starts automatically when Windows boots (optional, enabled by default)
- Starts the HTTP server by default on port 7890
- Indexes files using NTFS USN journal for speed
- Watches for changes in real-time
- Runs in the system tray when started manually
- Tray icon shows server status (green = running, gray = stopped)

**Tray menu options:**
- Search (opens qf.exe)
- Toggle Server (enable/disable HTTP API)
- Rebuild Index
- Exit

The indexer stores data in `%LOCALAPPDATA%\QuickFind\index\`. This includes the SQLite database with file paths, metadata, and full-text indexes for supported file types.

### qf.exe

The search interface. It's a TUI app that connects to qfi's HTTP API.

- Opens an interactive terminal UI for browsing and searching
- Fuzzy matching, keyboard navigation, preview panel
- Starts qfi automatically if it's not running

## Search Algorithm

QuickFind uses a two-phase search with confidence-based ranking.

### Phase 1: Path Matching

File paths are searched first, always. Matches are scored and sorted by confidence:

| Match Type | Score | Example |
|------------|-------|---------|
| Exact basename | 100 | `config.yaml` for query "config" |
| Basename starts with | 80 | `config_backup.yaml` for "config" |
| Basename contains | 60 | `my_config.yaml` for "config" |
| Fuzzy basename | 40 | `cnfgtion.yaml` for "config" |
| Path segment exact | 30 | `C:\project\config\file.yaml` for "config" |
| Path segment fuzzy | 20 | `C:\project\cnfgs\file.yaml` for "config" |

**Recency boost**: Files modified in the last 7 days get +5 points.
**Frequency boost**: Recently accessed files get +3 points.

### Phase 2: Content Matching

Content is searched only when:
- Query contains `--content` flag
- Query has spaces or quotes (assumed to be content search)
- Path matches are insufficient (< 5 results)

Content matches score 1-30 points based on:
- Number of matches in file
- Position of match (title > body > comments)
- Match proximity to start of file

### Final Ranking

```
total_score = path_score + content_score + recency_boost + frequency_boost
```

Results are sorted by `total_score` descending. Top 12 results returned by default.

## HTTP API

```
GET /search?q=query&limit=12&content=0
```

**Response:**
```json
{
  "query": "config",
  "results": [
    {
      "path": "C:\\Users\\me\\config.yaml",
      "score": 100,
      "match_type": "basename_exact",
      "size": 1024,
      "modified": "2025-01-15T10:30:00Z"
    }
  ],
  "total_indexed": 145000,
  "search_time_ms": 2
}
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| q | required | Search query |
| limit | 12 | Max results to return |
| content | 0 | Search inside files (1) |
| offset | 0 | Pagination offset |

**Other endpoints:**
```
GET /stats        Index statistics (file count, size, last update)
GET /health       Service health check
GET /toggle       Toggle HTTP server on/off
```

## Ignored folders

By default, QuickFind skips common library and dependency directories:

- `node_modules`
- `.git`, `.svn`, `.hg`
- `venv`, `.venv`, `env`, `.env`
- `__pycache__`, `.pytest_cache`
- `dist`, `build`, `out`
- `.idea`, `.vscode`
- `target` (Rust/Cargo)
- `bin`, `obj` (.NET)

You can customize this in the config file.

## Configuration

Config lives in `%APPDATA%\QuickFind\config.json`.

```json
{
  "ignored_patterns": ["node_modules", ".git", "__pycache__"],
  "indexed_extensions": [".txt", ".md", ".py", ".js", ".rs", ".go"],
  "http_port": 7890,
  "auto_start": true,
  "watch_changes": true,
  "result_limit": 12
}
```

## Technical Details

### NTFS USN Journal

QuickFind uses the NTFS Update Sequence Number (USN) journal to track file changes. This is the same mechanism Everything uses.

- **No admin rights required** for basic operation
- **Real-time updates** when files are created, modified, or deleted
- **Fast**: Can process ~10,000 changes per second
- **Efficient**: Only stores changes, not full file scans

The USN journal lives in the MFT and records:
- File creation/deletion
- File modification
- Renames
- Security changes

On first run, QuickFind reads the MFT directly to build the initial index. After that, only USN journal deltas are processed.

### SQLite Storage

Two databases in `%LOCALAPPDATA%\QuickFind\index\`:

**main.db** - File index
```sql
CREATE TABLE files (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    basename TEXT NOT NULL,
    size INTEGER,
    modified INTEGER,
    created INTEGER,
    attributes INTEGER
);
CREATE INDEX idx_basename ON files(basename);
CREATE INDEX idx_modified ON files(modified);
```

**content.db** - Full-text search
```sql
CREATE VIRTUAL TABLE content USING fts5(
    path,
    content,
    tokenize='unicode61 remove_diacritics 2'
);
```

### FTS5 (Full-Text Search)

SQLite's built-in full-text search engine. Zero external dependencies.

- **Inverted index**: Maps words to documents containing them
- **BM25 ranking**: Scores results by relevance
- **Unicode tokenization**: Handles any language
- **Prefix search**: `config*` matches `configuration`, `config.yaml`
- **Phrase search**: `"hello world"` matches exact phrase

### Initial Index Build

On first run or after rebuild:

1. Parse MFT for all files (requires admin for full access, falls back to walk)
2. Build SQLite index with paths and metadata
3. Queue text files for content extraction
4. Update USN journal cursor for future delta updates

Typical time: ~5-10 minutes for 500,000 files.

## File types indexed

- **Documents**: txt, md, docx, pdf, rtf
- **Code**: All major languages via extension matching
- **Config**: json, yaml, toml, ini, xml
- **Images**: Metadata extraction (EXIF for jpg, dimensions for all)
- **Archives**: zip, tar (file listing only)

## Resource usage

| State | RAM | CPU |
|-------|-----|-----|
| Idle (watching) | 30-50 MB | <1% |
| Building index | 100-200 MB | 5-15% |
| Content extraction | 50-100 MB | 10-20% |

## Installation

Binaries install to `C:\Program Files\QuickFind\`. Data goes to `%LOCALAPPDATA%\QuickFind\`.

```
qf --install    # Set up auto-start service and initialize index
```

The installer registers qfi.exe to start with Windows.

## Development

Built with Python. Uses SQLite FTS5 for full-text search. Packaged with Nuitka for a standalone .exe.