"""Data models — plain dataclasses with explicit serialization.

Using dataclasses instead of Pydantic keeps the dependency count at zero
and makes the JSON conversion obvious and debuggable.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any


def _serialize(value: Any) -> Any:
    """Turn a dataclass field value into something JSON-safe."""
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, list):
        return [_serialize(v) for v in value]
    return value


@dataclass
class FileEntry:
    """One file or directory in the index."""

    path: str
    basename: str
    extension: str = ""
    size: int = 0
    modified: int = 0  # Unix timestamp
    created: int = 0
    is_directory: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "basename": self.basename,
            "extension": self.extension,
            "size": self.size,
            "modified": self.modified,
            "created": self.created,
            "is_directory": self.is_directory,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileEntry:
        return cls(
            path=data["path"],
            basename=data.get("basename", ""),
            extension=data.get("extension", ""),
            size=data.get("size", 0),
            modified=data.get("modified", 0),
            created=data.get("created", 0),
            is_directory=data.get("is_directory", False),
        )


@dataclass
class SearchResult:
    """A single result from a search query — a FileEntry plus a score."""

    path: str
    basename: str
    extension: str = ""
    size: int = 0
    modified: int = 0
    created: int = 0
    is_directory: bool = False
    score: float = 0.0
    match_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "basename": self.basename,
            "extension": self.extension,
            "size": self.size,
            "modified": self.modified,
            "created": self.created,
            "is_directory": self.is_directory,
            "score": self.score,
            "match_type": self.match_type,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SearchResult:
        return cls(
            path=data["path"],
            basename=data.get("basename", ""),
            extension=data.get("extension", ""),
            size=data.get("size", 0),
            modified=data.get("modified", 0),
            created=data.get("created", 0),
            is_directory=data.get("is_directory", False),
            score=data.get("score", 0.0),
            match_type=data.get("match_type", ""),
        )

    @classmethod
    def from_file_entry(cls, entry: FileEntry, score: float = 0.0, match_type: str = "") -> SearchResult:
        """Promote a FileEntry to a SearchResult with a score."""
        return cls(
            path=entry.path,
            basename=entry.basename,
            extension=entry.extension,
            size=entry.size,
            modified=entry.modified,
            created=entry.created,
            is_directory=entry.is_directory,
            score=score,
            match_type=match_type,
        )


@dataclass
class SearchResponse:
    """The full response for a search request."""

    query: str
    results: list[SearchResult] = field(default_factory=list)
    total: int = 0
    time_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "results": [r.to_dict() for r in self.results],
            "total": self.total,
            "time_ms": self.time_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SearchResponse:
        return cls(
            query=data["query"],
            results=[SearchResult.from_dict(r) for r in data.get("results", [])],
            total=data.get("total", 0),
            time_ms=data.get("time_ms", 0.0),
        )


@dataclass
class IndexStats:
    """Summary of what the indexer has collected so far."""

    file_count: int = 0
    total_size: int = 0  # bytes
    last_updated: int = 0  # Unix timestamp
    status: str = "idle"

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_count": self.file_count,
            "total_size": self.total_size,
            "last_updated": self.last_updated,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IndexStats:
        return cls(
            file_count=data.get("file_count", 0),
            total_size=data.get("total_size", 0),
            last_updated=data.get("last_updated", 0),
            status=data.get("status", "idle"),
        )


@dataclass
class ServiceHealth:
    """Current state of the pry background service."""

    status: str = "unknown"  # "running", "stopped", "error"
    uptime_seconds: float = 0.0
    index_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "uptime_seconds": self.uptime_seconds,
            "index_ready": self.index_ready,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ServiceHealth:
        return cls(
            status=data.get("status", "unknown"),
            uptime_seconds=data.get("uptime_seconds", 0.0),
            index_ready=data.get("index_ready", False),
        )
