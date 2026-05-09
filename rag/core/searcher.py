from __future__ import annotations

import json
import re

from rag.core.config import RAGConfig, ensure_runtime_dirs
from rag.core.database import connect, init_db
from rag.core.models import SearchResult


QUERY_TOKEN_RE = re.compile(r"[A-Za-z0-9_.$/@:#-]+|[\u4e00-\u9fff]+")


def search(
    config: RAGConfig,
    query: str,
    top_k: int | None = None,
    source_type: str | None = None,
    mode: str = "any",
) -> list[SearchResult]:
    ensure_runtime_dirs(config)
    conn = connect(config.database_path)
    init_db(conn)

    match_query = build_fts_query(query, mode)
    if not match_query:
        return []

    limit = top_k or config.default_top_k
    params: list[object] = [match_query]
    source_filter = ""
    if source_type:
        source_filter = "AND c.source_type = ?"
        params.append(source_type)
    params.append(limit)

    rows = conn.execute(
        f"""
        SELECT
            bm25(chunks_fts) AS score,
            c.chunk_id,
            c.doc_id,
            c.source_path,
            c.source_type,
            c.title,
            c.section,
            c.text,
            c.metadata_json,
            snippet(chunks_fts, 3, '[', ']', '...', 18) AS snippet
        FROM chunks_fts
        JOIN chunks c ON c.chunk_id = chunks_fts.chunk_id
        WHERE chunks_fts MATCH ?
        {source_filter}
        ORDER BY score
        LIMIT ?
        """,
        params,
    ).fetchall()

    results = [
        SearchResult(
            score=float(row["score"]),
            chunk_id=row["chunk_id"],
            doc_id=row["doc_id"],
            source_path=row["source_path"],
            source_type=row["source_type"],
            title=row["title"] or "",
            section=row["section"] or "",
            text=row["text"] or "",
            snippet=row["snippet"] or make_snippet(row["text"] or "", query),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )
        for row in rows
    ]
    conn.close()
    return results


def build_fts_query(query: str, mode: str = "any") -> str:
    tokens = QUERY_TOKEN_RE.findall(query)
    safe_tokens = [token.replace('"', '""') for token in tokens if token.strip()]
    operator = " OR " if mode == "any" else " "
    return operator.join(f'"{token}"' for token in safe_tokens)


def make_snippet(text: str, query: str, width: int = 240) -> str:
    tokens = QUERY_TOKEN_RE.findall(query)
    lowered = text.lower()
    position = -1
    for token in tokens:
        position = lowered.find(token.lower())
        if position >= 0:
            break
    if position < 0:
        position = 0
    start = max(0, position - width // 3)
    end = min(len(text), start + width)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return prefix + text[start:end].strip() + suffix
