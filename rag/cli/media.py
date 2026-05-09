from __future__ import annotations

try:
    from _bootstrap import bootstrap
except ImportError:
    from rag.cli._bootstrap import bootstrap

bootstrap()

import argparse

from rag.core.config import load_config
from rag.core.database import connect, init_db
from rag.core.media import garbage_collect_media, load_media_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect or clean extracted media files.")
    parser.add_argument("action", choices=("list", "gc"), help="List extracted media or garbage-collect orphan files.")
    args = parser.parse_args()

    config = load_config()
    if args.action == "list":
        manifest = load_media_manifest(config.data_dir)
        if not manifest:
            print("no media")
            return 0
        for index, (path, entry) in enumerate(sorted(manifest.items()), start=1):
            label = entry.get("alt") or entry.get("title") or f"image-{index}"
            size = entry.get("size_bytes") or 0
            mime = entry.get("mime_type") or ""
            source = entry.get("source_path") or ""
            print(f"[{index}] {path} mime={mime} size={size} label={label}")
            print(f"source: {source}")
        return 0

    conn = connect(config.database_path)
    init_db(conn)
    active_rows = conn.execute("SELECT source_path FROM documents").fetchall()
    conn.close()
    stats = garbage_collect_media(config.data_dir, {row["source_path"] for row in active_rows})
    print(f"media gc complete: deleted_files={stats['media_deleted_files']} deleted_entries={stats['media_deleted_entries']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

