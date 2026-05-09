from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from rag.core.chunking import chunk_document
from rag.core.config import RAGConfig, ensure_runtime_dirs
from rag.core.database import clear_db, connect, init_db
from rag.core.models import Chunk, ParsedDocument
from rag.core.parsers import parse_file, supported_file


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def iter_source_files(corpus_dir: Path) -> list[Path]:
    if not corpus_dir.exists():
        return []
    return sorted(path for path in corpus_dir.rglob("*") if supported_file(path))


def ingest(config: RAGConfig, full: bool = False) -> dict[str, int]:
    ensure_runtime_dirs(config)
    conn = connect(config.database_path)
    init_db(conn)
    if full:
        clear_db(conn)

    stats = {
        "seen": 0,
        "indexed": 0,
        "skipped": 0,
        "chunks": 0,
        "failed": 0,
    }

    for path in iter_source_files(config.corpus_dir):
        stats["seen"] += 1
        try:
            document = parse_file(path, config.project_root)
            if not full and unchanged(conn, document):
                stats["skipped"] += 1
                continue
            chunks = chunk_document(document, config.max_chars, config.overlap_chars)
            upsert_document(conn, document, chunks)
            stats["indexed"] += 1
            stats["chunks"] += len(chunks)
        except Exception as exc:
            stats["failed"] += 1
            print(f"[ingest:error] {path}: {exc}")

    conn.commit()
    conn.close()
    return stats


def unchanged(conn, document: ParsedDocument) -> bool:
    row = conn.execute(
        "SELECT sha256, mtime, size_bytes FROM documents WHERE source_path = ?",
        (document.source_path,),
    ).fetchone()
    if row is None:
        return False
    return row["sha256"] == document.sha256 and row["size_bytes"] == document.size_bytes


def upsert_document(conn, document: ParsedDocument, chunks: list[Chunk]) -> None:
    now = utc_now()
    old = conn.execute(
        "SELECT created_at FROM documents WHERE source_path = ?",
        (document.source_path,),
    ).fetchone()
    created_at = old["created_at"] if old else now

    delete_document(conn, document.source_path)
    conn.execute(
        """
        INSERT INTO documents (
            doc_id, source_path, source_type, title, sha256, size_bytes, mtime,
            created_at, updated_at, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document.doc_id,
            document.source_path,
            document.source_type,
            document.title,
            document.sha256,
            document.size_bytes,
            document.mtime,
            created_at,
            now,
            json.dumps(document.metadata, ensure_ascii=False),
        ),
    )

    for chunk in chunks:
        insert_chunk(conn, chunk)


def delete_document(conn, source_path: str) -> None:
    rows = conn.execute(
        "SELECT chunk_id FROM chunks WHERE source_path = ?",
        (source_path,),
    ).fetchall()
    for row in rows:
        conn.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (row["chunk_id"],))
    conn.execute("DELETE FROM documents WHERE source_path = ?", (source_path,))


def insert_chunk(conn, chunk: Chunk) -> None:
    metadata_json = json.dumps(chunk.metadata, ensure_ascii=False)
    conn.execute(
        """
        INSERT INTO chunks (
            chunk_id, doc_id, source_path, source_type, title, section,
            chunk_index, text, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chunk.chunk_id,
            chunk.doc_id,
            chunk.source_path,
            chunk.source_type,
            chunk.title,
            chunk.section,
            chunk.chunk_index,
            chunk.text,
            metadata_json,
        ),
    )
    conn.execute(
        """
        INSERT INTO chunks_fts (chunk_id, title, section, text, source_path)
        VALUES (?, ?, ?, ?, ?)
        """,
        (chunk.chunk_id, chunk.title, chunk.section, chunk.text, chunk.source_path),
    )

