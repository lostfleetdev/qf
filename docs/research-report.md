# NTFS indexing research report

Research date: 2026-05-10  
Project: pry (Windows file search tool)  
Scope covers: NTFS USN Journal, MFT, permission model, Python integration, existing implementations.

---

## 1. Architecture overview

A Windows-native file indexer has two sources of filesystem truth:

| Source | What it gives | Speed | Admin required |
|--------|--------------|-------|---------------|
| **USN Journal** (`$UsnJrnl:$J`) | Incremental change records since last read. File creates, deletes, renames, attribute changes. | ~10K records/sec read | **Yes** for `DeviceIoControl` path; No for raw file read of `$J` stream (if accessible) |
| **MFT** (`$MFT`) | Snapshot of every file/directory on the volume. Full path, timestamps, sizes, attributes. | Full scan ~5-10 min for 500K files | **Yes** for `DeviceIoControl` path; No for raw file read (if accessible) |
| **`os.scandir`** | Recursive directory walk. Works everywhere, no privileges. | Slow: minutes for large trees | **No** |

**Production model** (inspired by Everything):  
Privileged service reads MFT+USN via `DeviceIoControl`. Unprivileged client communicates over named pipe or localhost HTTP. The user-facing app never needs admin.

---

## 2. NTFS USN Journal deep-dive

### 2.1 What it is

The USN (Update Sequence Number) Journal is a per-volume NTFS feature that logs every file system change. It lives at `$Extend\$UsnJrnl` with two streams: `$J` (the journal data) and `$Max` (allocation metadata). NTFS 3.0+ / ReFS.

Permanently enabled on Windows 8+. On Vista+ the journal is recreated at boot if missing, so disabling it is futile.

### 2.2 Core Windows API

All operations go through `DeviceIoControl` on a volume handle (`\\.\C:`):

| IOCTL | Code | Purpose | Input struct | Output struct |
|-------|------|---------|-------------|--------------|
| `FSCTL_QUERY_USN_JOURNAL` | `0x000900f4` | Get journal state, IDs, boundaries | None | `USN_JOURNAL_DATA_V1` or `V2` |
| `FSCTL_CREATE_USN_JOURNAL` | `0x000900e7` | Create/resize journal | `CREATE_USN_JOURNAL_DATA` | None |
| `FSCTL_READ_USN_JOURNAL` | `0x000900bb` | Read incremental change records | `READ_USN_JOURNAL_DATA_V0` | Buffer of `USN_RECORD_V2`/`V3` |
| `FSCTL_ENUM_USN_DATA` | `0x000900b3` | Enumerate MFT entries (full scan) | `MFT_ENUM_DATA_V0` | Buffer of `USN_RECORD_V2`/`V3` |
| `FSCTL_GET_NTFS_VOLUME_DATA` | `0x00090060` | Volume info (cluster size, MFT start) | None | `NTFS_VOLUME_DATA_BUFFER` |

### 2.3 USN_RECORD_V2 structure (60 bytes + filename)

```
Offset  Size  Field
0       4     RecordLength        (total bytes including filename)
4       2     MajorVersion        (2 for V2, 3 for V3)
6       2     MinorVersion
8       8     FileReferenceNumber (MFT segment ref of the file)
16      8     ParentFileReferenceNumber
24      8     Usn                 (USN value of this record)
32      8     TimeStamp           (FILETIME, 100-ns intervals since 1601)
40      4     Reason              (bitmask of USN_REASON_* flags)
44      4     SourceInfo
48      4     SecurityId
52      4     FileAttributes
56      2     FileNameLength      (bytes, not chars)
58      2     FileNameOffset      (from start of record, usually 60)
60      ...   FileName            (UTF-16LE, NOT null-terminated)
```

`USN_RECORD_V3` adds 16 bytes for `FileNameHash` at offset 60, shifting `FileName` to offset 76.

### 2.4 Key USN_REASON flags

| Flag | Value | Meaning |
|------|-------|---------|
| `USN_REASON_DATA_OVERWRITE` | `0x00000001` | File data modified |
| `USN_REASON_DATA_EXTEND` | `0x00000002` | File grew |
| `USN_REASON_DATA_TRUNCATION` | `0x00000004` | File shrank |
| `USN_REASON_NAMED_DATA_OVERWRITE` | `0x00000010` | Named stream modified |
| `USN_REASON_NAMED_DATA_EXTEND` | `0x00000020` | Named stream grew |
| `USN_REASON_NAMED_DATA_TRUNCATION` | `0x00000040` | Named stream shrank |
| `USN_REASON_FILE_CREATE` | `0x00000100` | File created |
| `USN_REASON_FILE_DELETE` | `0x00000200` | File deleted |
| `USN_REASON_EA_CHANGE` | `0x00000400` | Extended attributes changed |
| `USN_REASON_SECURITY_CHANGE` | `0x00000800` | Security descriptor changed |
| `USN_REASON_RENAME_OLD_NAME` | `0x00001000` | File was renamed (old name) |
| `USN_REASON_RENAME_NEW_NAME` | `0x00002000` | File was renamed (new name) |
| `USN_REASON_INDEXABLE_CHANGE` | `0x00004000` | Directory index changed |
| `USN_REASON_BASIC_INFO_CHANGE` | `0x00008000` | Attribute change |
| `USN_REASON_HARD_LINK_CHANGE` | `0x00010000` | Hard link added/removed |
| `USN_REASON_COMPRESSION_CHANGE` | `0x00020000` | Compression state changed |
| `USN_REASON_ENCRYPTION_CHANGE` | `0x00040000` | Encryption state changed |
| `USN_REASON_OBJECT_ID_CHANGE` | `0x00080000` | Object ID changed |
| `USN_REASON_REPARSE_POINT_CHANGE` | `0x00100000` | Reparse point changed |
| `USN_REASON_STREAM_CHANGE` | `0x00200000` | Named stream added/removed |
| `USN_REASON_TRANSACTED_CHANGE` | `0x00400000` | TxF transaction |
| `USN_REASON_CLOSE` | `0x80000000` | File handle closed (finalizes event) |

**Important**: A create+write+close sequence may produce multiple records. When `ReturnOnlyOnClose=1` in `READ_USN_JOURNAL_DATA_V0`, only close records are returned.

### 2.5 MFT reference numbers

A 64-bit value encoding:
- Lower 48 bits: Segment number (MFT entry index)
- Upper 16 bits: Sequence number (incremented when entry is reused)

Sequence numbers detect stale references (e.g., a parent directory deleted and a new one at the same MFT slot).

### 2.6 Journal ID and safe resumption

- `USN_JOURNAL_DATA.UsnJournalID`: Stable identifier for the journal instance
- `FirstUsn`: Earliest valid USN still in journal
- `NextUsn`: Next USN that will be assigned

On journal wrap or deletion+recreation, `UsnJournalID` changes. Always check before resuming incremental reads. If the saved cursor `< FirstUsn`, a rescan is needed.

### 2.7 Read loop pseudocode

```
1. Open \\.\C: (GENERIC_READ | GENERIC_WRITE, shared read/write/delete)
2. FSCTL_QUERY_USN_JOURNAL -> get journal ID, NextUsn, FirstUsn
3. If journal ID != saved_id or saved_usn < FirstUsn:
     fall back to os.scandir or FSCTL_ENUM_USN_DATA
4. Loop:
     FSCTL_READ_USN_JOURNAL(start_usn=saved_usn, journal_id=saved_id)
     -> buffer: [next_usn:8][record_1][record_2]...
     Parse records: skip first 8 bytes, iterate by RecordLength
     For each record: extract filename via FileNameOffset/FileNameLength (UTF-16LE)
     Process create/delete/rename
     saved_usn = next_usn from buffer
5. Store saved_usn + journal_id for next run
```

---

## 3. MFT (Master File Table)

### 3.1 Structure

Each MFT record is 1024 bytes (default) beginning with `FILE` signature:
```
Offset  Size  Field
0       4     Signature ("FILE")
4       2     USN offset (update sequence array)
6       2     USN size + 1
8       2     LogFile sequence number (LSN) - low
10      2     LSN - high
12      2     Sequence number
14      2     Hard link count
16      2     Attribute offset
18      2     Flags (1=in-use, 2=directory)
20      4     Real size
24      4     Allocated size
28      8     Base file record (0 if base)
36      2     Next attribute ID
38      2     (padding)
40      4     Record number (Windows 10+)
...
```

After fixup, walk attributes starting at `attribute_offset`.

### 3.2 Key MFT attributes

| Type code | Attribute | Contents |
|-----------|-----------|---------|
| `0x10` | `$STANDARD_INFORMATION` | Timestamps (4), DOS attributes, flags |
| `0x20` | `$ATTRIBUTE_LIST` | Attribute list (sparse files) |
| `0x30` | `$FILE_NAME` | Filename, parent FRN, timestamps, sizes |
| `0x40` | `$VOLUME_VERSION` | Volume info |
| `0x50` | `$OBJECT_ID` | Object ID (GUID) |
| `0x60` | `$SECURITY_DESCRIPTOR` | Security descriptor |
| `0x70` | `$VOLUME_NAME` | Volume label |
| `0x80` | `$VOLUME_INFORMATION` | Volume flags |
| `0x90` | `$DATA` | File content stream |
| `0xA0` | `$INDEX_ROOT` | B-tree root of directory index |
| `0xB0` | `$INDEX_ALLOCATION` | B-tree nodes (non-resident) |
| `0xC0` | `$BITMAP` | Bitmap for $INDEX_ALLOCATION |
| `0xD0` | `$REPARSE_POINT` | Reparse point data |
| `0xE0` | `$EA_INFORMATION` | Extended attribute info |
| `0xF0` | `$EA` | Extended attributes |
| `0x100` | `$LOGGED_UTILITY_STREAM` | Logged utility stream (EFS) |

**`$FILE_NAME` attribute structure**:
```
Offset  Size  Field
0       8     Parent FRN (file reference)
8       8     Created (FILETIME)
16      8     Modified (FILETIME)
24      8     MFT changed (FILETIME)
32      8     Accessed (FILETIME)
40      8     Allocated size
48      8     Real size
56      4     Flags / file attributes
60      4     (padding / reparse info)
64      1     Name length (chars)
65      1     Namespace (0=POSIX, 1=Win32, 2=DOS, 3=Win32+DOS)
66      var   Filename (UTF-16LE)
```

### 3.3 Path reconstruction

Algorithm: build `{FRN -> (parent_FRN, name)}` map from `$FILE_NAME` attributes. Then resolve full paths by walking parent chain (last entry = root = FRN 5 for `\`).

Pseudocode:
```python
# Build map from MFT scan
frn_map = {
    5:      (5, ""),          # root points to itself
    42:     (5, "Users"),
    387:    (42, "Public"),
    ...
}

def resolve_path(frn, cache={}):
    if frn not in cache:
        parent, name = frn_map[frn]
        if frn == parent:  # root
            path = name or "\\"
        else:
            path = resolve_path(parent, cache) + "\\" + name
        cache[frn] = path
    return cache[frn]
```

### 3.4 How Everything does it

Everything runs an `Everything.exe -svc` service that opens the volume with `GENERIC_READ | GENERIC_WRITE`, reads MFT records sequentially via `FSCTL_ENUM_USN_DATA`, builds an in-memory path+name+size+date index. The user-facing GUI communicates via named pipe (`\\.\pipe\Everything`). The service keeps the index current by tailing `FSCTL_READ_USN_JOURNAL`.

---

## 4. Permission model

### 4.1 Operation matrix

| Operation | Volume handle opens? | Admin needed? | Notes |
|-----------|---------------------|---------------|-------|
| Open `\\.\C:` for read | Usually yes for standard user | Not always | Depends on device DACL |
| `FSCTL_QUERY_USN_JOURNAL` | Yes | **Yes** | `ERROR_ACCESS_DENIED` without admin |
| `FSCTL_READ_USN_JOURNAL` | Yes | **Yes** | Core read operation |
| `FSCTL_ENUM_USN_DATA` | Yes | **Yes** | MFT enumeration |
| `FSCTL_CREATE_USN_JOURNAL` | Yes | **Yes** | Admin-only maintenance op |
| Read `$MFT` as file | No | Effectively yes | Protected system file |
| Read `$UsnJrnl:$J` as stream | No | Effectively yes | Protected system file |
| `os.scandir` / `os.walk` | N/A | **No** | Works for any user |

### 4.2 Privilege details

The specific privilege required is `SeManageVolumePrivilege`. It's held by:
- Administrators (enabled by default)
- LOCAL_SYSTEM, NETWORK_SERVICE

Enable in Python via pywin32:
```python
import win32api, win32security, win32con
token = win32security.OpenProcessToken(
    win32api.GetCurrentProcess(),
    win32con.TOKEN_ADJUST_PRIVILEGES | win32con.TOKEN_QUERY
)
win32security.AdjustTokenPrivileges(
    token, False,
    [(win32security.LookupPrivilegeValue(None, "SeManageVolumePrivilege"),
      win32security.SE_PRIVILEGE_ENABLED)]
)
```

`SeBackupPrivilege` and `SeRestorePrivilege` are not substitutes for USN operations.

### 4.3 Everything's service model

```
┌─────────────┐     named pipe     ┌──────────────┐
│  pry.exe      │ ◄──────────────►  │  pri.exe      │
│  (TUI client)│    \\.\pipe\pry     │  (service)   │
│  no admin    │                    │  admin/LOCAL  │
└─────────────┘                    │  _SYSTEM     │
                                    │              │
                                    │ USN Journal  │
                                    │ MFT access   │
                                    └──────────────┘
```

The service opens a named pipe server. Clients connect and send structured requests (search, reindex, stats). Responses are JSON over the pipe. This avoids localhost TCP complexity and is the Everything pattern.

### 4.4 v1 workaround

For v1 (no-admin), the PLAN.md correctly chooses `os.scandir` falling back to directory walk. USN Journal integration requires either:
- An install-time service registration (Windows `sc create`)
- Running `pri` as a separate elevated process (requires UAC prompt)
- Or deferring USN to v2+

---

## 5. Python integration approaches

### 5.1 ctypes (no dependencies)

```python
import ctypes as ct
from ctypes import wintypes as wt

kernel32 = ct.WinDLL("kernel32", use_last_error=True)

# Handles
INVALID_HANDLE_VALUE = ct.c_void_p(-1).value

# Constants
GENERIC_READ    = 0x80000000
GENERIC_WRITE   = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING   = 3

FSCTL_QUERY_USN_JOURNAL  = 0x000900f4
FSCTL_READ_USN_JOURNAL   = 0x000900bb
FSCTL_ENUM_USN_DATA      = 0x000900b3

# CTypes structures
class USN_JOURNAL_DATA_V1(ct.Structure):
    _fields_ = [
        ("UsnJournalID", ct.c_uint64),
        ("FirstUsn", ct.c_int64),
        ("NextUsn", ct.c_int64),
        ("LowestValidUsn", ct.c_int64),
        ("MaxUsn", ct.c_int64),
        ("MaximumSize", ct.c_uint64),
        ("AllocationDelta", ct.c_uint64),
    ]

class USN_RECORD_V2(ct.Structure):
    _fields_ = [
        ("RecordLength", ct.c_uint32),
        ("MajorVersion", ct.c_uint16),
        ("MinorVersion", ct.c_uint16),
        ("FileReferenceNumber", ct.c_uint64),
        ("ParentFileReferenceNumber", ct.c_uint64),
        ("Usn", ct.c_int64),
        ("TimeStamp", ct.c_int64),
        ("Reason", ct.c_uint32),
        ("SourceInfo", ct.c_uint32),
        ("SecurityId", ct.c_uint32),
        ("FileAttributes", ct.c_uint32),
        ("FileNameLength", ct.c_uint16),
        ("FileNameOffset", ct.c_uint16),
    ]

class READ_USN_JOURNAL_DATA_V0(ct.Structure):
    _fields_ = [
        ("StartUsn", ct.c_int64),
        ("ReasonMask", ct.c_uint32),
        ("ReturnOnlyOnClose", ct.c_uint32),
        ("Timeout", ct.c_uint64),
        ("BytesToWaitFor", ct.c_uint64),
        ("UsnJournalID", ct.c_uint64),
    ]

# Open volume
h = kernel32.CreateFileW(
    "\\\\.\\C:",
    GENERIC_READ | GENERIC_WRITE,
    FILE_SHARE_READ | FILE_SHARE_WRITE,
    None,
    OPEN_EXISTING,
    0, None
)

# Query journal
buf = (ct.c_ubyte * 1024)()
ret = ct.wintypes.DWORD()
kernel32.DeviceIoControl(h, FSCTL_QUERY_USN_JOURNAL, None, 0,
                         buf, 1024, ct.byref(ret), None)
jd = USN_JOURNAL_DATA_V1.from_buffer_copy(buf)
```

### 5.2 pywin32 (cleaner, adds dependency)

```python
import win32file
import pywintypes
import struct

FSCTL_QUERY_USN_JOURNAL = 0x000900f4
FSCTL_READ_USN_JOURNAL  = 0x000900bb

h = win32file.CreateFile(
    r"\\.\C:",
    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
    win32file.FILE_SHARE_READ | win32file.FILE_SHARE_WRITE,
    None,
    win32file.OPEN_EXISTING,
    0, None
)

# Query journal
raw, ret = win32file.DeviceIoControl(h, FSCTL_QUERY_USN_JOURNAL, None, 1024)
# raw is bytes, parse with struct.unpack or ctypes.Structure.from_buffer_copy

# Read records
rd = struct.pack("<qIIqqq", start_usn, 0xFFFFFFFF, 0, 0, 0, journal_id)
raw, ret = win32file.DeviceIoControl(h, FSCTL_READ_USN_JOURNAL, rd, 65536)
next_usn = struct.unpack_from("<q", raw, 0)[0]
# iterate records starting at offset 8
```

### 5.3 Record iteration pattern

```python
def iter_usn_records(buffer):
    """Yield (USN_RECORD_V2, filename_str) from a USN output buffer."""
    if len(buffer) < 8:
        return
    next_usn = struct.unpack_from("<q", buffer, 0)[0]
    off = 8
    while off + 60 <= len(buffer):
        rec = USN_RECORD_V2.from_buffer_copy(buffer, off)
        if rec.RecordLength == 0:
            break
        raw_name = buffer[off + rec.FileNameOffset:
                           off + rec.FileNameOffset + rec.FileNameLength]
        name = raw_name.decode("utf-16-le", errors="replace")
        yield (rec, name)
        off += rec.RecordLength
    return next_usn  # or yield this first
```

### 5.4 Existing Python libraries

| Library | Approach | Status | Best for |
|---------|----------|--------|----------|
| **`usnparser`** (PyPI) | Parses `$J` file offline | Last updated 2016 | Forensic analysis |
| **`dissect.ntfs`** | Full NTFS parser, USN + MFT | Active, well-maintained | Offline volume parsing |
| **`analyzeMFT`** | `$MFT` parser | Legacy, Python 2 | MFT record analysis |
| **`pywin32`** | Win32 API wrappers | Active, essential | Live USN/MFT via DeviceIoControl |
| **`ntfs_parse`** | MFT+LogFile+UsnJrnl parser | Archived | Reference implementation |

### 5.5 Non-Python references

| Project | Lang | What |
|---------|------|------|
| **Everything** (voidtools) | C++ | The gold standard. Service + named pipe model. |
| **`usnrs`** | Rust | USN parser from Airbus CERT. CLI + library. |
| **`RustyUsn`** | Rust | USN to JSON converter. |
| **`UsnParser`** | C#/Go | Change journal reader + monitor. |

---

## 6. ReadDirectoryChangesW (no-admin alternative)

### 6.1 Comparison

| Aspect | USN Journal | ReadDirectoryChangesW |
|--------|-------------|----------------------|
| Admin needed | Yes | **No** |
| Scope | Entire volume | Per-directory handle |
| Completeness | Complete, atomic | Can lose events on buffer overflow |
| Speed | ~10K records/sec | Low latency per event |
| Resource use | 1 handle per volume | ~1 handle per watched dir |
| OS limits | Volume count | ~8192 handles/user |
| Directory depth | N/A | Unlimited (recursive) |
| Rename tracking | Paired records | Old+new name events |
| Deleted file info | FRN + name | Name only |

### 6.2 Python with pywin32

```python
import win32file, win32con

h = win32file.CreateFile(
    r"C:\Users",
    win32con.FILE_LIST_DIRECTORY,
    win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
    None,
    win32con.OPEN_EXISTING,
    win32con.FILE_FLAG_BACKUP_SEMANTICS,
    None
)
results = win32file.ReadDirectoryChangesW(
    h, 65536, True,
    win32con.FILE_NOTIFY_CHANGE_FILE_NAME |
    win32con.FILE_NOTIFY_CHANGE_DIR_NAME |
    win32con.FILE_NOTIFY_CHANGE_LAST_WRITE |
    win32con.FILE_NOTIFY_CHANGE_SIZE,
    None, None
)
```

### 6.3 BUFFER_OVERFLOW handling

If events are dropped, `ReadDirectoryChangesW` returns empty results (0 bytes). Detection: check `ERROR_NOTIFY_ENUM_DIR`. On overflow, fall back to a directory rescan of the affected subtree.

### 6.4 When to use which

- **USN Journal**: Production indexing. Fast, complete, but needs admin.
- **ReadDirectoryChangesW**: Real-time notification layer on top of a periodically rebuilt index. No-admin fallback for incremental updates.
- **os.scandir**: Initial index build or rescan when neither USN nor RDCW works.

---

## 7. Design recommendations for pry

### 7.1 Phased approach

**Phase 1 (v1, PLAN.md)**:
- `os.scandir` recursive walk
- SQLite storage, path-only search
- No admin needed
- Ranking: basename exact > prefix > contains > extension > fuzzy

**Phase 2 (v2)**:
- Add `pri` as a Windows service component
- Service opens volume with admin for USN Journal
- Full MFT enumeration for initial index (via `FSCTL_ENUM_USN_DATA`)
- USN Journal tailing for incremental updates
- Named pipe IPC between `pri` and `pry`
- Paths resolved via parent FRN chain (MFT `$FILE_NAME` attributes)

**Phase 3 (v3+)**:
- Content indexing via FTS5
- File watching via ReadDirectoryChangesW as notification layer
- System tray integration
- Installer with service registration

### 7.2 Storage schema considerations for USN

When using USN Journal, store per volume:
```sql
-- Track USN cursor per volume
CREATE TABLE usn_cursors (
    volume TEXT PRIMARY KEY,        -- "C:"
    journal_id INTEGER NOT NULL,    -- UsnJournalID
    next_usn INTEGER NOT NULL,      -- Next USN to read
    last_updated INTEGER NOT NULL   -- indexed_at timestamp
);

-- File reference number caching for path resolution
CREATE TABLE mft_cache (
    frn INTEGER PRIMARY KEY,       -- FileReferenceNumber
    parent_frn INTEGER NOT NULL,
    name TEXT NOT NULL,
    full_path TEXT NOT NULL,
    volume TEXT NOT NULL
);
```

### 7.3 v1 → v2 migration

The key challenge: `os.scandir` yields full paths immediately. USN Journal yields `(FRN, parent_FRN, name)` tuples that require parent-chain resolution. The transition means:
- Change path storage to FRN-based lookups
- Add MFT enumeration pass to build FRN→path cache
- Move index directory to `%LOCALAPPDATA%\pry\index\`
- Add named pipe IPC server to `pri`

### 7.4 Service vs elevated process

| Approach | Pros | Cons |
|----------|------|------|
| Windows Service | Runs at boot, detached from user session | Harder to debug, installer complexity |
| Elevated helper process | Simpler, inherits env | Requires UAC prompt at launch |
| Task Scheduler trigger | No UAC, can run elevated | Slower startup, no continuous process |

Everything uses a service. For pry, an elevated helper process spawned by the TUI (with a one-time UAC prompt) is simpler for v2.

### 7.5 Named pipe protocol sketch

```
Client connects to \\.\pipe\pry

Request (JSON over pipe, null-terminated):
  {"cmd":"search","q":"config","limit":12,"offset":0}
  {"cmd":"stats"}
  {"cmd":"health"}
  {"cmd":"reindex"}

Response (JSON, null-terminated):
  {"status":"ok","results":[...],"total_indexed":100000}
  {"status":"error","message":"..."}
```

---

## 8. Key pitfalls and edge cases

### 8.1 USN Journal specific

- **Journal wrap**: Journal is a circular buffer. `NextUsn - FirstUsn ≤ MaximumSize`. If not polled frequently, records are lost. Detect via `UsnJournalID` change.
- **Non-NTFS volumes**: USB drives (FAT32/exFAT) have no USN Journal. Fallback to `os.scandir`.
- **ReFS**: Supports USN_RECORD_V3 (with `FileNameHash`). Check `MajorVersion`.
- **Performance**: Reading MFT for 500K files is ~5-10 min. Do it once. Incremental reads of USN are sub-second.
- **Deleted files**: You get `USN_REASON_FILE_DELETE`. But if the journal wrapped, you might miss the delete. Solution: periodic full scan.
- **Renames**: Paired `RENAME_OLD_NAME` + `RENAME_NEW_NAME` records. Track by `FileReferenceNumber` (which stays constant).
- **Hard links**: Same `FileReferenceNumber` appears in multiple parent directories. `$FILE_NAME` has multiple entries; `USN_RECORD` shows only one parent per event.

### 8.2 Permission pitfalls

- Opening `\\.\C:` with `GENERIC_READ | GENERIC_WRITE` fails for non-admin on some Windows builds.
- Opening with only `GENERIC_READ` may succeed for the handle but fail for USN IOCTLs.
- Every Windows version may have slightly different volume DACLs.
- UAC does NOT virtualize volume IOCTLs.
- Testing must be done on actual Windows, not WSL.

### 8.3 MFT edge cases

- **Fragmented MFT**: MFT itself can be non-resident with multiple data runs.
- **Base records**: Files with many attributes use multiple MFT records linked via `BaseRecord`.
- **Deleted MFT entries**: Marked with `FILE` flag cleared; sequence number incremented.
- **$ATTRIBUTE_LIST**: For extremely fragmented files, attribute list must be followed.
- **Directories with large contents**: Use `$INDEX_ALLOCATION` `INDX` buffers (16KB blocks).

### 8.4 ReadDirectoryChangesW pitfalls

- **Buffer overflow**: If events arrive faster than reads, you get `ERROR_NOTIFY_ENUM_DIR`. Rescan needed.
- **Handle limit**: ~8,192 per user on NT. One handle per watched directory.
- **Recursive monitoring**: Each subdirectory needs its own handle.
- **UNC paths**: Not supported.

---

## 9. Implementation risk matrix

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| USN Journal admin requirement breaks no-admin v1 constraint | Certain | High | Defer USN to v2; use os.scandir for v1 |
| Journal wraps between reads | Medium | Medium | Store journal ID; detect and rescan |
| MFT enumeration is slow for large volumes | High | Medium | Show progress; run once; cache results |
| Service/permission model complexity | Medium | Medium | Start with elevated process before service |
| Windows version differences in API behavior | Low | High | Test on Win10 + Win11 before release |
| UTF-16 filename edge cases (BOM, surrogates) | Low | Low | Use proper decoding with error handling |
| Hard links appear as duplicate paths | Low | Low | Track by FRN, not path |
| System files/ACLs prevent directory walk | High | Low | Skip with logged count in stats |

---

## 10. Research sources

### Official Microsoft docs
- [Walking a Buffer of Change Journal Records](https://learn.microsoft.com/en-us/windows/win32/fileio/walking-a-buffer-of-change-journal-records)
- [FSCTL_READ_USN_JOURNAL](https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ni-winioctl-fsctl_read_usn_journal)
- [FSCTL_QUERY_USN_JOURNAL](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/ni-ntifs-fsctl_query_usn_journal)
- [FSCTL_ENUM_USN_DATA](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/ni-ntifs-fsctl_enum_usn_data)
- [USN_RECORD_V2 structure](https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ns-winioctl-usn_record_v2)
- [Change Journal Operations](https://learn.microsoft.com/en-us/windows/win32/fileio/change-journal-operations)
- [NTFS Attribute Types](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fscc/a82e9105-2405-4e37-b2c3-28c773902d85)

### Open-source implementations
- [Everything by Voidtools](https://www.voidtools.com/) — reference architecture
- [Everything Service docs](https://www.voidtools.com/support/everything/everything_service/)
- [USN-Journal-Parser (Python)](https://github.com/PoorBillionaire/USN-Journal-Parser) — offline forensic parser
- [analyzeMFT (Python)](https://github.com/rowingdude/analyzeMFT) — MFT parser
- [dissect.ntfs (Python)](https://docs.dissect.tools/en/stable/api/dissect/ntfs/usnjrnl/index.html) — active NTFS parsing library
- [usnrs (Rust)](https://github.com/airbus-cert/usnrs) — USN parser from Airbus CERT
- [ntfs_parse (Python)](https://github.com/NTFSparse/ntfs_parse) — MFT + LogFile + UsnJrnl

### Python API references
- [pywin32 docs](https://timgolden.me.uk/pywin32-docs/) — Tim Golden's reference
- [pywin32 DeviceIoControl](https://timgolden.me.uk/pywin32-docs/win32file__DeviceIoControl_meth.html)
- [ctypes docs](https://docs.python.org/3/library/ctypes.html) — FFI for Windows API
- [watchdog library](https://github.com/gorakhargosh/watchdog) — cross-platform filesystem watcher

### Community/analysis
- SO: [Walking NTFS Change Journal on Windows 10](https://stackoverflow.com/questions/46978678/walking-the-ntfs-change-journal-on-windows-10)
- SO: [USN Journal admin requirements](https://stackoverflow.com/questions/70539976/do-i-need-admin-privileges-to-read-windows-file-system-change-journal)
- [Unprivileged USN journal access (YouTube)](https://www.youtube.com/watch?v=lyg7waSfaxE)
- Wikipedia: [USN Journal](https://en.wikipedia.org/wiki/USN_Journal)
- NTFS Documentation: [Data Runs](https://flatcap.github.io/linux-ntfs/ntfs/concepts/data_runs.html)
- Michael Wager: [NTFS MFT walkthrough](https://mwager.de/cyber_security/2022/01/27/ntfs-mft-example/)
