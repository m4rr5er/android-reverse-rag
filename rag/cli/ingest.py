from __future__ import annotations

try:
    from _bootstrap import bootstrap
except ImportError:
    from rag.cli._bootstrap import bootstrap

bootstrap()

import argparse

from rag.core.config import load_config
from rag.core.indexer import ingest


def main() -> int:
    parser = argparse.ArgumentParser(description="Index local reverse engineering materials.")
    parser.add_argument("--full", action="store_true", help="Clear and rebuild the whole SQLite index.")
    args = parser.parse_args()

    config = load_config()
    stats = ingest(config, full=args.full)
    print(
        "ingest complete: "
        f"seen={stats['seen']} indexed={stats['indexed']} "
        f"skipped={stats['skipped']} chunks={stats['chunks']} "
        f"deleted={stats['deleted']} failed={stats['failed']}"
    )
    return 1 if stats["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
