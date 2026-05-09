from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RAGConfig:
    project_root: Path
    corpus_dir: Path
    data_dir: Path
    database_path: Path
    max_chars: int = 1200
    overlap_chars: int = 160
    default_top_k: int = 5


def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "config.yaml").exists() or (candidate / ".git").exists():
            return candidate
    return current


def load_config(project_root: Path | None = None) -> RAGConfig:
    root = find_project_root(project_root)
    config_file = root / "config.yaml"

    values: dict[str, str] = {}
    section = ""
    if config_file.exists():
        for raw_line in config_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.endswith(":") and not line.startswith("-"):
                section = line[:-1].strip()
                continue
            if ":" in line:
                key, value = line.split(":", 1)
                values[f"{section}.{key.strip()}"] = value.strip().strip("'\"")

    corpus_dir = root / values.get("paths.corpus_dir", "corpus")
    data_dir = root / values.get("paths.data_dir", "data")
    database_path = root / values.get("paths.database_path", "data/rag.sqlite")

    return RAGConfig(
        project_root=root,
        corpus_dir=corpus_dir,
        data_dir=data_dir,
        database_path=database_path,
        max_chars=int(values.get("chunking.max_chars", "1200")),
        overlap_chars=int(values.get("chunking.overlap_chars", "160")),
        default_top_k=int(values.get("search.default_top_k", "5")),
    )


def ensure_runtime_dirs(config: RAGConfig) -> None:
    config.corpus_dir.mkdir(parents=True, exist_ok=True)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    (config.project_root / "index").mkdir(parents=True, exist_ok=True)

