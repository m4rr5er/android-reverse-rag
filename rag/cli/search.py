from __future__ import annotations

try:
    from _bootstrap import bootstrap
except ImportError:
    from rag.cli._bootstrap import bootstrap

bootstrap()

import argparse

from rag.core.config import load_config
from rag.core.documents import neighboring_chunks
from rag.core.searcher import search


def main() -> int:
    parser = argparse.ArgumentParser(description="Search the local reverse engineering RAG index.")
    parser.add_argument("query", help="Keyword query, for example: JNI_OnLoad RegisterNatives")
    parser.add_argument("--top-k", type=int, default=None, help="Number of results to return.")
    parser.add_argument("--type", dest="source_type", default=None, help="Filter by source type: html, markdown, text, code.")
    parser.add_argument("--mode", choices=("any", "all"), default="any", help="Match any query token or require all tokens.")
    parser.add_argument("--show-full", action="store_true", help="Print full chunk text instead of a snippet.")
    parser.add_argument("--context", type=int, default=0, help="Also print N neighboring chunks before/after each result.")
    args = parser.parse_args()

    config = load_config()
    results = search(config, args.query, top_k=args.top_k, source_type=args.source_type, mode=args.mode)

    if not results:
        print("no results")
        return 0

    for index, result in enumerate(results, start=1):
        body = result.text if args.show_full else result.snippet
        print(f"[{index}] score={result.score:.4f} source_type={result.source_type}")
        print(f"source: {result.source_path}")
        print(f"title: {result.title}")
        print(f"section: {result.section}")
        print()
        print(body.strip())
        if args.context > 0:
            neighbors = neighboring_chunks(config, result.chunk_id, args.context)
            if neighbors:
                print()
                print(f"-- context +/- {args.context} chunks --")
                for neighbor in neighbors:
                    print(f"[context chunk {neighbor.chunk_index}] section: {neighbor.section}")
                    print(neighbor.text.strip())
                    print()
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
