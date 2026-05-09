from __future__ import annotations

import hashlib
import html
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib
from html.parser import HTMLParser
from pathlib import Path

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
MOJIBAKE_MARKERS = set("鏌钖疉椋帶鍙傛暟鍒嗘瀽鍘熷垱瀛ｄ笢骞鏈鏃姹熻嫃寰绯诲垪猻浼氫粠澶村紑濮嬶紝鑻ユ姄鍖呮垨鑰呭叾瀹冨彲浠ョ湅涔嬪墠鐨勬枃绔狅")


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
                if src.startswith("data:"):
                    safe_src = "[inline-image]"
                else:
                    safe_src = src
                    self.image_paths.append(src)
                label = f"![{alt}]({safe_src})" if alt else f"![image]({safe_src})"
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
        text = repair_mojibake(html.unescape(data))
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
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".docx":
        return "docx"
    if suffix in CODE_EXTENSIONS:
        return "code"
    if suffix in {".md", ".markdown"}:
        return "markdown"
    return "text"


def read_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return repair_mojibake(data.decode(encoding))
        except UnicodeDecodeError:
            continue
    return repair_mojibake(data.decode("utf-8", errors="replace"))


def repair_mojibake(text: str) -> str:
    """Repair common UTF-8 text that was decoded as GBK and saved again."""
    original_score = mojibake_score(text)
    if original_score < 2:
        return text
    for encoding in ("gb18030", "gbk", "cp936"):
        try:
            candidate = text.encode(encoding, errors="replace").decode("utf-8", errors="replace")
        except UnicodeError:
            continue
        candidate_score = mojibake_score(candidate)
        if candidate_score * 3 < original_score:
            return candidate
    return text


def mojibake_score(text: str) -> int:
    sample = text[:1000000]
    marker_count = sum(1 for char in sample if char in MOJIBAKE_MARKERS)
    replacement_count = sample.count("�")
    latin_mojibake = sample.count("Ã") + sample.count("Â") + sample.count("â€")
    return marker_count * 4 + replacement_count + latin_mojibake * 3


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
    metadata: dict[str, object] = {"parser": source_type}

    if source_type == "html":
        raw_text = read_text(path)
        parser = NormalizingHTMLParser()
        parser.feed(raw_text)
        text = parser.normalized_text()
        title = parser.title() or path.stem
        metadata["image_paths"] = parser.image_paths
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


def parse_docx(path: Path) -> tuple[str, str]:
    paragraphs: list[str] = []
    title = ""
    with zipfile.ZipFile(path) as archive:
        if "docProps/core.xml" in archive.namelist():
            core = ET.fromstring(archive.read("docProps/core.xml"))
            for node in core.iter():
                if node.tag.endswith("title") and node.text:
                    title = node.text.strip()
                    break
        document = ET.fromstring(archive.read("word/document.xml"))

    body = first_child_ending(document, "body")
    if body is None:
        body = document
    for child in body:
        if child.tag.endswith("p"):
            text = paragraph_text(child)
            if text:
                paragraphs.append(text)
        elif child.tag.endswith("tbl"):
            for row in child.iter():
                if row.tag.endswith("tr"):
                    cells = [paragraph_text(cell) for cell in row if cell.tag.endswith("tc")]
                    cells = [cell for cell in cells if cell]
                    if cells:
                        paragraphs.append(" | ".join(cells))

    return "\n\n".join(paragraphs).strip(), title


def first_child_ending(node: ET.Element, suffix: str) -> ET.Element | None:
    for child in node:
        if child.tag.endswith(suffix):
            return child
    return None


def paragraph_text(node: ET.Element) -> str:
    parts: list[str] = []
    for child in node.iter():
        if child.tag.endswith("t") and child.text:
            parts.append(child.text)
        elif child.tag.endswith("tab"):
            parts.append("\t")
        elif child.tag.endswith("br"):
            parts.append("\n")
    return "".join(parts).strip()


def parse_pdf(path: Path) -> tuple[str, int | None, str]:
    pypdf_result = parse_pdf_with_pypdf(path)
    if pypdf_result:
        return (*pypdf_result, "pypdf")

    pymupdf_result = parse_pdf_with_pymupdf(path)
    if pymupdf_result:
        return (*pymupdf_result, "pymupdf")

    text = parse_pdf_basic(path)
    return text, None, "pdf-basic"


def parse_pdf_with_pypdf(path: Path) -> tuple[str, int] | None:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        return None
    try:
        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(page.strip() for page in pages if page.strip()), len(reader.pages)
    except Exception:
        return None


def parse_pdf_with_pymupdf(path: Path) -> tuple[str, int] | None:
    try:
        import fitz  # type: ignore
    except ImportError:
        return None
    try:
        document = fitz.open(str(path))
        pages = [page.get_text("text") for page in document]
        page_count = document.page_count
        document.close()
        return "\n\n".join(page.strip() for page in pages if page.strip()), page_count
    except Exception:
        return None


def parse_pdf_basic(path: Path) -> str:
    data = path.read_bytes()
    stream_texts: list[str] = []
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, flags=re.S):
        stream = match.group(1)
        for candidate in (try_zlib(stream), stream):
            if not candidate:
                continue
            extracted = extract_pdf_literals(candidate)
            if extracted:
                stream_texts.append(extracted)
                break
    if stream_texts:
        return "\n\n".join(stream_texts)
    fallback = data.decode("latin-1", errors="ignore")
    return "\n".join(extract_readable_lines(fallback))


def try_zlib(data: bytes) -> bytes | None:
    try:
        return zlib.decompress(data)
    except zlib.error:
        return None


def extract_pdf_literals(data: bytes) -> str:
    text = data.decode("latin-1", errors="ignore")
    literals = re.findall(r"\((?:\\.|[^\\)])*\)\s*Tj", text)
    array_literals = re.findall(r"\[(.*?)\]\s*TJ", text, flags=re.S)
    parts: list[str] = []
    for literal in literals:
        parts.append(unescape_pdf_literal(literal.rsplit(")", 1)[0][1:]))
    for array in array_literals:
        for literal in re.findall(r"\((?:\\.|[^\\)])*\)", array):
            parts.append(unescape_pdf_literal(literal[1:-1]))
    return " ".join(part for part in parts if part).strip()


def unescape_pdf_literal(value: str) -> str:
    value = value.replace(r"\(", "(").replace(r"\)", ")").replace(r"\\", "\\")
    value = value.replace(r"\n", "\n").replace(r"\r", "\n").replace(r"\t", "\t")
    return value


def extract_readable_lines(text: str) -> list[str]:
    lines = []
    for line in text.splitlines():
        cleaned = re.sub(r"[^\x09\x0a\x0d\x20-\x7e\u4e00-\u9fff]+", " ", line).strip()
        if len(cleaned) >= 24 and sum(char.isalpha() or "\u4e00" <= char <= "\u9fff" for char in cleaned) >= 8:
            lines.append(cleaned)
    return lines
