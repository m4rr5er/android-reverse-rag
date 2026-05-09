from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
  doc_id TEXT PRIMARY KEY,
  source_path TEXT NOT NULL UNIQUE,
  source_type TEXT NOT NULL,
  title TEXT,
  sha256 TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  mtime REAL NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS chunks (
  chunk_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  source_path TEXT NOT NULL,
  source_type TEXT NOT NULL,
  title TEXT,
  section TEXT,
  chunk_index INTEGER NOT NULL,
  text TEXT NOT NULL,
  metadata_json TEXT,
  FOREIGN KEY (doc_id) REFERENCES documents(doc_id) ON DELETE CASCADE
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  chunk_id UNINDEXED,
  title,
  section,
  text,
  source_path UNINDEXED,
  tokenize = "unicode61 tokenchars '_.$/@:#-'"
);
"""


def connect(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(database_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def clear_db(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM chunks_fts")
    conn.execute("DELETE FROM chunks")
    conn.execute("DELETE FROM documents")
    conn.commit()


def has_fts5(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.__fts_check USING fts5(x)")
        conn.execute("DROP TABLE IF EXISTS temp.__fts_check")
        return True
    except sqlite3.OperationalError:
        return False

