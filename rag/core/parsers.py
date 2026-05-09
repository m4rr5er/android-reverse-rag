from __future__ import annotations

import hashlib
from pathlib import Path

from rag.core.document_parsers import parse_docx, parse_pdf
from rag.core.encoding import mojibake_score, read_text, repair_mojibake
from rag.core.html_parser import NormalizingHTMLParser
from rag.core.models import ParsedDocument, display_path


HTML_EXTENSIONS = {".html", ".htm"}
TEXT_EXTENSIONS = {".md", ".markdown", ".txt"}
DOC_EXTENSIONS = {".pdf", ".docx"}
CODE_EXTENSIONS = {
    ".smali",
    ".java",
    ".kt",
    ".js",
    ".ts",
    ".py",
    ".json",
    ".xml",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
}
SUPPORTED_EXTENSIONS = HTML_EXTENSIONS | TEXT_EXTENSIONS | DOC_EXTENSIONS | CODE_EXTENSIONS


def supported_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS


def source_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in HTML_EXTENSIONS:
        return "html"
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".docx":
        return "docx"
    if suffix in CODE_EXTENSIONS:
        return "code"
    if suffix in {".md", ".markdown"}:
        return "markdown"
    return "text"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_file(path: Path, project_root: Path, image_output_dir: Path | None = None) -> ParsedDocument:
    source_path = display_path(path, project_root)
    source_type = source_type_for(path)
    sha256 = file_sha256(path)
    stat = path.stat()
    metadata: dict[str, object] = {"parser": source_type}

    if source_type == "html":
        raw_text = read_text(path)
        parser = NormalizingHTMLParser(source_path=source_path, image_output_dir=image_output_dir, project_root=project_root)
        parser.feed(raw_text)
        text = parser.normalized_text()
        title = parser.title() or path.stem
        metadata["image_paths"] = parser.image_paths
        metadata["images"] = [image.to_dict() for image in parser.images]
        metadata["table_count"] = len(parser.tables)
    elif source_type == "pdf":
        text, page_count, parser_name = parse_pdf(path)
        title = path.stem
        metadata["parser"] = parser_name
        metadata["page_count"] = page_count
    elif source_type == "docx":
        text, title = parse_docx(path)
        title = title or path.stem
    else:
        raw_text = read_text(path)
        text = raw_text.strip()
        title = path.stem
        if source_type == "code":
            metadata["language"] = path.suffix.lower().lstrip(".")

    return ParsedDocument(
        doc_id=stable_id(source_path),
        source_path=source_path,
        source_type=source_type,
        title=title,
        text=text,
        sha256=sha256,
        size_bytes=stat.st_size,
        mtime=stat.st_mtime,
        metadata=metadata,
    )


__all__ = [
    "parse_file",
    "supported_file",
    "source_type_for",
    "read_text",
    "repair_mojibake",
    "mojibake_score",
    "file_sha256",
    "stable_id",
]

