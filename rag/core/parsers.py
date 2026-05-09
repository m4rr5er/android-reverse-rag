from __future__ import annotations

import hashlib
import html
import re
from html.parser import HTMLParser
from pathlib import Path

from rag.core.models import ParsedDocument, display_path


HTML_EXTENSIONS = {".html", ".htm"}
TEXT_EXTENSIONS = {".md", ".markdown", ".txt"}
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
SUPPORTED_EXTENSIONS = HTML_EXTENSIONS | TEXT_EXTENSIONS | CODE_EXTENSIONS


class NormalizingHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.image_paths: list[str] = []
        self._skip_depth = 0
        self._in_title = False
        self._link_href: str | None = None
        self._tag_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): value or "" for key, value in attrs}
        tag = tag.lower()
        self._tag_stack.append(tag)

        if tag in {"script", "style", "nav", "footer", "noscript"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = True
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(tag[1])
            self.parts.append("\n" + "#" * level + " ")
        elif tag in {"p", "div", "section", "article", "br", "li", "tr"}:
            self.parts.append("\n")
        elif tag in {"pre", "code"}:
            self.parts.append("\n```text\n" if tag == "pre" else "`")
        elif tag == "a":
            self._link_href = attrs_dict.get("href") or None
        elif tag == "img":
            src = attrs_dict.get("src", "")
            alt = attrs_dict.get("alt", "")
            if src:
                self.image_paths.append(src)
                label = f"![{alt}]({src})" if alt else f"![image]({src})"
                self.parts.append(f"\n{label}\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "nav", "footer", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = False
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "section", "article", "li", "tr"}:
            self.parts.append("\n")
        elif tag == "pre":
            self.parts.append("\n```\n")
        elif tag == "code":
            self.parts.append("`")
        elif tag == "a":
            if self._link_href:
                self.parts.append(f" ({self._link_href})")
            self._link_href = None
        if self._tag_stack:
            self._tag_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = html.unescape(data)
        if self._in_title:
            self.title_parts.append(text.strip())
            return
        if text.strip():
            self.parts.append(text)

    def normalized_text(self) -> str:
        text = "".join(self.parts)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def title(self) -> str:
        return " ".join(part for part in self.title_parts if part).strip()


def supported_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS


def source_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in HTML_EXTENSIONS:
        return "html"
    if suffix in CODE_EXTENSIONS:
        return "code"
    if suffix in {".md", ".markdown"}:
        return "markdown"
    return "text"


def read_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_file(path: Path, project_root: Path) -> ParsedDocument:
    source_path = display_path(path, project_root)
    source_type = source_type_for(path)
    sha256 = file_sha256(path)
    stat = path.stat()
    raw_text = read_text(path)
    metadata: dict[str, object] = {"parser": source_type}

    if source_type == "html":
        parser = NormalizingHTMLParser()
        parser.feed(raw_text)
        text = parser.normalized_text()
        title = parser.title() or path.stem
        metadata["image_paths"] = parser.image_paths
    else:
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

