from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
import zlib
from pathlib import Path


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
            rows = []
            for row in child.iter():
                if row.tag.endswith("tr"):
                    cells = [paragraph_text(cell) for cell in row if cell.tag.endswith("tc")]
                    cells = [cell for cell in cells if cell]
                    if cells:
                        rows.append(cells)
            if rows:
                paragraphs.append(render_plain_table(rows))

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


def render_plain_table(rows: list[list[str]]) -> str:
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    return "\n".join(" | ".join(row) for row in normalized)


def parse_pdf(path: Path) -> tuple[str, int | None, str]:
    for parser in (parse_pdf_with_pypdf, parse_pdf_with_pymupdf, parse_pdf_with_pdfplumber):
        result = parser(path)
        if result and result[0].strip():
            return result
    ocr_result = parse_pdf_with_ocr(path)
    if ocr_result and ocr_result[0].strip():
        return ocr_result
    text = parse_pdf_basic(path)
    return text, None, "pdf-basic"


def parse_pdf_with_pypdf(path: Path) -> tuple[str, int, str] | None:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        return None
    try:
        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(page.strip() for page in pages if page.strip()), len(reader.pages), "pypdf"
    except Exception:
        return None


def parse_pdf_with_pymupdf(path: Path) -> tuple[str, int, str] | None:
    try:
        import fitz  # type: ignore
    except ImportError:
        return None
    try:
        document = fitz.open(str(path))
        pages = [page.get_text("text") for page in document]
        page_count = document.page_count
        document.close()
        return "\n\n".join(page.strip() for page in pages if page.strip()), page_count, "pymupdf"
    except Exception:
        return None


def parse_pdf_with_pdfplumber(path: Path) -> tuple[str, int, str] | None:
    try:
        import pdfplumber  # type: ignore
    except ImportError:
        return None
    try:
        pages: list[str] = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                tables = page.extract_tables() or []
                table_text = "\n\n".join(render_plain_table([[cell or "" for cell in row] for row in table]) for table in tables)
                pages.append("\n\n".join(part for part in (page_text, table_text) if part.strip()))
            return "\n\n".join(page.strip() for page in pages if page.strip()), len(pdf.pages), "pdfplumber"
    except Exception:
        return None


def parse_pdf_with_ocr(path: Path) -> tuple[str, int, str] | None:
    try:
        import fitz  # type: ignore
        from PIL import Image  # type: ignore
        import pytesseract  # type: ignore
    except ImportError:
        return None
    try:
        document = fitz.open(str(path))
        pages: list[str] = []
        for page in document:
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
            text = pytesseract.image_to_string(image, lang="chi_sim+eng")
            if text.strip():
                pages.append(text.strip())
        page_count = document.page_count
        document.close()
        return "\n\n".join(pages), page_count, "pdf-ocr"
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
