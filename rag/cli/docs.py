from __future__ import annotations

try:
    from _bootstrap import bootstrap
except ImportError:
    from rag.cli._bootstrap import bootstrap

bootstrap()

import argparse

from rag.core.config import load_config
from rag.core.documents import document_chunks, document_outline, list_documents


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect indexed documents and sections.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List indexed documents.")

    outline = subparsers.add_parser("outline", help="Show section outline for a document.")
    outline.add_argument("selector", help="Document id, title fragment, or source path fragment.")

    show = subparsers.add_parser("show", help="Print chunks from a document.")
    show.add_argument("selector", help="Document id, title fragment, or source path fragment.")
    show.add_argument("--section", default=None, help="Only show sections matching this fragment.")
    show.add_argument("--limit", type=int, default=None, help="Maximum chunks to print.")

    args = parser.parse_args()
    config = load_config()

    if args.command == "list":
        docs = list_documents(config)
        if not docs:
            print("no documents")
            return 0
        for index, doc in enumerate(docs, start=1):
            print(f"[{index}] type={doc.source_type} chunks={doc.chunk_count}")
            print(f"source: {doc.source_path}")
            print(f"title: {doc.title}")
            print(f"updated_at: {doc.updated_at}")
            print()
        return 0

    if args.command == "outline":
        outline_rows = document_outline(config, args.selector)
        if not outline_rows:
            print("no document or no sections")
            return 0
        for index, (section, first_chunk, chunk_count) in enumerate(outline_rows, start=1):
            print(f"[{index}] chunk={first_chunk} count={chunk_count} section={section}")
        return 0

    chunks = document_chunks(config, args.selector, section=args.section, limit=args.limit)
    if not chunks:
        print("no chunks")
        return 0
    for chunk in chunks:
        print(f"[chunk {chunk.chunk_index}] source_type={chunk.source_type}")
        print(f"source: {chunk.source_path}")
        print(f"title: {chunk.title}")
        print(f"section: {chunk.section}")
        print()
        print(chunk.text.strip())
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

