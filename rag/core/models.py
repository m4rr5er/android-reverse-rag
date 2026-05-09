from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ParsedDocument:
    doc_id: str
    source_path: str
    source_type: str
    title: str
    text: str
    sha256: str
    size_bytes: int
    mtime: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    source_path: str
    source_type: str
    title: str
    section: str
    chunk_index: int
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchResult:
    score: float
    chunk_id: str
    doc_id: str
    source_path: str
    source_type: str
    title: str
    section: str
    text: str
    snippet: str
    metadata: dict[str, Any] = field(default_factory=dict)


def display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()

