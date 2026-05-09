from __future__ import annotations

from rag.core.config import RAGConfig, ensure_runtime_dirs
from rag.core.database import connect, has_fts5, init_db
from rag.core.indexer import iter_source_files


def collect_status(config: RAGConfig) -> dict[str, object]:
    ensure_runtime_dirs(config)
    conn = connect(config.database_path)
    init_db(conn)
    document_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    fts_count = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    fts5_available = has_fts5(conn)
    conn.close()

    return {
        "project_root": str(config.project_root),
        "corpus_dir": str(config.corpus_dir),
        "database_path": str(config.database_path),
        "source_files": len(iter_source_files(config.corpus_dir)),
        "documents": document_count,
        "chunks": chunk_count,
        "fts_rows": fts_count,
        "fts5_available": fts5_available,
    }

