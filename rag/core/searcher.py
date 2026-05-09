from __future__ import annotations

import json
import re

from rag.core.config import RAGConfig, ensure_runtime_dirs
from rag.core.database import connect, init_db
from rag.core.models import SearchResult
from rag.core.terms import query_term_groups


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

    results = [row_to_result(row, query) for row in rows]
    if len(results) < limit and should_use_substring_fallback(query):
        seen_chunk_ids = {result.chunk_id for result in results}
        term_rows = term_index_search(conn, query, limit - len(results), source_type, mode, seen_chunk_ids)
        term_results = [row_to_result(row, query, fallback=True) for row in term_rows]
        results.extend(term_results)
        seen_chunk_ids.update(result.chunk_id for result in term_results)
    if len(results) < limit and should_use_substring_fallback(query):
        fallback_rows = substring_search(conn, query, limit - len(results), source_type, mode, {result.chunk_id for result in results})
        results.extend(row_to_result(row, query, fallback=True) for row in fallback_rows)
    conn.close()
    return results


def build_fts_query(query: str, mode: str = "any") -> str:
    tokens = QUERY_TOKEN_RE.findall(query)
    safe_tokens = [token.replace('"', '""') for token in tokens if token.strip()]
    operator = " OR " if mode == "any" else " "
    return operator.join(f'"{token}"' for token in safe_tokens)


def should_use_substring_fallback(query: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in query)


def substring_search(conn, query: str, limit: int, source_type: str | None, mode: str, seen_chunk_ids: set[str]):
    tokens = [token for token in QUERY_TOKEN_RE.findall(query) if token.strip()]
    if not tokens or limit <= 0:
        return []

    token_clauses: list[str] = []
    params: list[object] = []
    for token in tokens:
        escaped = escape_like(token)
        clause = """
        (
            c.title LIKE ? ESCAPE '\\' OR
            c.section LIKE ? ESCAPE '\\' OR
            c.text LIKE ? ESCAPE '\\' OR
            c.source_path LIKE ? ESCAPE '\\'
        )
        """
        token_clauses.append(clause)
        params.extend([f"%{escaped}%"] * 4)

    operator = " OR " if mode == "any" else " AND "
    source_filter = ""
    if source_type:
        source_filter = "AND c.source_type = ?"
        params.append(source_type)

    exclude_filter = ""
    if seen_chunk_ids:
        placeholders = ", ".join("?" for _ in seen_chunk_ids)
        exclude_filter = f"AND c.chunk_id NOT IN ({placeholders})"
        params.extend(sorted(seen_chunk_ids))

    params.append(limit)
    return conn.execute(
        f"""
        SELECT
            0.0 AS score,
            c.chunk_id,
            c.doc_id,
            c.source_path,
            c.source_type,
            c.title,
            c.section,
            c.text,
            c.metadata_json,
            NULL AS snippet
        FROM chunks c
        WHERE ({operator.join(token_clauses)})
        {source_filter}
        {exclude_filter}
        ORDER BY c.source_path, c.chunk_index
        LIMIT ?
        """,
        params,
    ).fetchall()


def term_index_search(conn, query: str, limit: int, source_type: str | None, mode: str, seen_chunk_ids: set[str]):
    groups = query_term_groups(query)
    if not groups or limit <= 0:
        return []

    matched_sets: list[set[str]] = []
    for group in groups:
        placeholders = ", ".join("?" for _ in group)
        rows = conn.execute(f"SELECT DISTINCT chunk_id FROM chunk_terms WHERE term IN ({placeholders})", group).fetchall()
        chunk_ids = {row["chunk_id"] for row in rows}
        if chunk_ids:
            matched_sets.append(chunk_ids)

    if not matched_sets:
        return []
    candidate_ids = set.union(*matched_sets) if mode == "any" else set.intersection(*matched_sets)
    candidate_ids.difference_update(seen_chunk_ids)
    if not candidate_ids:
        return []

    placeholders = ", ".join("?" for _ in candidate_ids)
    params: list[object] = sorted(candidate_ids)
    source_filter = ""
    if source_type:
        source_filter = "AND c.source_type = ?"
        params.append(source_type)
    params.append(limit)
    return conn.execute(
        f"""
        SELECT
            0.0 AS score,
            c.chunk_id,
            c.doc_id,
            c.source_path,
            c.source_type,
            c.title,
            c.section,
            c.text,
            c.metadata_json,
            NULL AS snippet
        FROM chunks c
        WHERE c.chunk_id IN ({placeholders})
        {source_filter}
        ORDER BY c.source_path, c.chunk_index
        LIMIT ?
        """,
        params,
    ).fetchall()


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def row_to_result(row, query: str, fallback: bool = False) -> SearchResult:
    score = float(row["score"])
    if fallback:
        score = 0.0
    return SearchResult(
        score=score,
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
