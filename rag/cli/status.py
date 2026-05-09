from __future__ import annotations

try:
    from _bootstrap import bootstrap
except ImportError:
    from rag.cli._bootstrap import bootstrap

bootstrap()

from rag.core.config import load_config
from rag.core.status import collect_status


def main() -> int:
    status = collect_status(load_config())
    for key, value in status.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
