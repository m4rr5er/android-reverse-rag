from __future__ import annotations

import json
from dataclasses import dataclass

from rag.core.config import RAGConfig, ensure_runtime_dirs
from rag.core.database import connect, init_db


@dataclass(frozen=True)
class DocumentInfo:
    doc_id: str
    source_path: str
    source_type: str
    title: str
    chunk_count: int
    updated_at: str


@dataclass(frozen=True)
class ChunkInfo:
    chunk_id: str
    doc_id: str
    source_path: str
    source_type: str
    title: str
    section: str
    chunk_index: int
    text: str
    metadata: dict


def list_documents(config: RAGConfig) -> list[DocumentInfo]:
    ensure_runtime_dirs(config)
    conn = connect(config.database_path)
    init_db(conn)
    rows = conn.execute(
        """
        SELECT
            d.doc_id,
            d.source_path,
            d.source_type,
            d.title,
            d.updated_at,
            COUNT(c.chunk_id) AS chunk_count
        FROM documents d
        LEFT JOIN chunks c ON c.doc_id = d.doc_id
        GROUP BY d.doc_id
        ORDER BY d.source_type, d.source_path
        """
    ).fetchall()
    conn.close()
    return [
        DocumentInfo(
            doc_id=row["doc_id"],
            source_path=row["source_path"],
            source_type=row["source_type"],
            title=row["title"] or "",
            chunk_count=row["chunk_count"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


def resolve_document_id(config: RAGConfig, selector: str) -> str | None:
    ensure_runtime_dirs(config)
    conn = connect(config.database_path)
    init_db(conn)
    row = conn.execute(
        """
        SELECT doc_id FROM documents
        WHERE doc_id = ? OR source_path = ? OR source_path LIKE ? OR title LIKE ?
        ORDER BY
          CASE
            WHEN doc_id = ? THEN 0
            WHEN source_path = ? THEN 1
            ELSE 2
          END,
          source_path
        LIMIT 1
        """,
        (selector, selector, f"%{selector}%", f"%{selector}%", selector, selector),
    ).fetchone()
    conn.close()
    return row["doc_id"] if row else None


def document_outline(config: RAGConfig, selector: str) -> list[tuple[str, int, int]]:
    doc_id = resolve_document_id(config, selector)
    if not doc_id:
        return []

    conn = connect(config.database_path)
    rows = conn.execute(
        """
        SELECT section, MIN(chunk_index) AS first_chunk, COUNT(*) AS chunk_count
        FROM chunks
        WHERE doc_id = ?
        GROUP BY section
        ORDER BY first_chunk
        """,
        (doc_id,),
    ).fetchall()
    conn.close()
    return [(row["section"] or "", row["first_chunk"], row["chunk_count"]) for row in rows]


def document_chunks(config: RAGConfig, selector: str, section: str | None = None, limit: int | None = None) -> list[ChunkInfo]:
    doc_id = resolve_document_id(config, selector)
    if not doc_id:
        return []

    conn = connect(config.database_path)
    params: list[object] = [doc_id]
    section_filter = ""
    if section:
        section_filter = "AND (section LIKE ? OR text LIKE ?)"
        params.append(f"%{section}%")
        params.append(f"%{section}%")
    limit_clause = ""
    if limit:
        limit_clause = "LIMIT ?"
        params.append(limit)
    rows = conn.execute(
        f"""
        SELECT * FROM chunks
        WHERE doc_id = ?
        {section_filter}
        ORDER BY chunk_index
        {limit_clause}
        """,
        params,
    ).fetchall()
    conn.close()
    return [row_to_chunk(row) for row in rows]


def neighboring_chunks(config: RAGConfig, chunk_id: str, radius: int) -> list[ChunkInfo]:
    if radius <= 0:
        return []
    conn = connect(config.database_path)
    current = conn.execute(
        "SELECT doc_id, chunk_index FROM chunks WHERE chunk_id = ?",
        (chunk_id,),
    ).fetchone()
    if not current:
        conn.close()
        return []
    rows = conn.execute(
        """
        SELECT * FROM chunks
        WHERE doc_id = ?
          AND chunk_index BETWEEN ? AND ?
        ORDER BY chunk_index
        """,
        (
            current["doc_id"],
            max(0, current["chunk_index"] - radius),
            current["chunk_index"] + radius,
        ),
    ).fetchall()
    conn.close()
    return [row_to_chunk(row) for row in rows if row["chunk_id"] != chunk_id]


def row_to_chunk(row) -> ChunkInfo:
    return ChunkInfo(
        chunk_id=row["chunk_id"],
        doc_id=row["doc_id"],
        source_path=row["source_path"],
        source_type=row["source_type"],
        title=row["title"] or "",
        section=row["section"] or "",
        chunk_index=row["chunk_index"],
        text=row["text"] or "",
        metadata=json.loads(row["metadata_json"] or "{}"),
    )
