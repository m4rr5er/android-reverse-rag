from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from pathlib import Path

from rag.core.encoding import repair_mojibake
from rag.core.media import HTMLImage, extract_data_image


class NormalizingHTMLParser(HTMLParser):
    def __init__(self, source_path: str = "", image_output_dir: Path | None = None, project_root: Path | None = None) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.image_paths: list[str] = []
        self.images: list[HTMLImage] = []
        self.tables: list[list[list[str]]] = []
        self.source_path = source_path
        self.image_output_dir = image_output_dir
        self.project_root = project_root
        self._skip_depth = 0
        self._in_title = False
        self._link_href: str | None = None
        self._tag_stack: list[str] = []
        self._table_depth = 0
        self._current_table: list[list[str]] = []
        self._current_row: list[str] = []
        self._current_cell_parts: list[str] | None = None
        self._current_cell_colspan = 1
        self._current_cell_rowspan = 1
        self._current_col = 0
        self._rowspans: dict[int, tuple[int, str]] = {}
        self._in_caption = False
        self._caption_parts: list[str] = []

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
        elif tag == "table":
            self._table_depth += 1
            if self._table_depth == 1:
                self._current_table = []
                self._rowspans = {}
                self._caption_parts = []
            return
        elif self._table_depth and tag == "caption":
            self._in_caption = True
            self._caption_parts = []
            return
        elif self._table_depth and tag == "tr":
            self._current_row = []
            self._current_col = 0
            return
        elif self._table_depth and tag in {"td", "th"}:
            self.fill_rowspan_cells()
            self._current_cell_parts = []
            self._current_cell_colspan = parse_span(attrs_dict.get("colspan", "1"))
            self._current_cell_rowspan = parse_span(attrs_dict.get("rowspan", "1"))
            return
        elif self._table_depth and tag == "br" and self._current_cell_parts is not None:
            self._current_cell_parts.append("\n")
            return
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
            self.add_image(attrs_dict)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "nav", "footer", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = False
        elif tag == "caption" and self._table_depth:
            self._in_caption = False
            return
        elif tag in {"td", "th"} and self._table_depth:
            if self._current_cell_parts is not None:
                text = clean_cell_text("".join(self._current_cell_parts))
                for offset in range(self._current_cell_colspan):
                    self._current_row.append(text)
                    if self._current_cell_rowspan > 1:
                        self._rowspans[self._current_col + offset] = (self._current_cell_rowspan - 1, text)
                self._current_col += self._current_cell_colspan
                self._current_cell_parts = None
            return
        elif tag == "tr" and self._table_depth:
            self.fill_rowspan_cells(fill_all=True)
            if any(cell for cell in self._current_row):
                self._current_table.append(self._current_row)
            self._current_row = []
            return
        elif tag == "table" and self._table_depth:
            self._table_depth -= 1
            if self._table_depth == 0 and self._current_table:
                self.tables.append(self._current_table)
                caption = clean_cell_text("".join(self._caption_parts))
                self.parts.append("\n\n" + render_markdown_table(self._current_table, caption) + "\n\n")
                self._current_table = []
                self._rowspans = {}
            return
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
        if self._table_depth and self._in_caption:
            self._caption_parts.append(text)
            return
        if self._table_depth and self._current_cell_parts is not None:
            if text.strip():
                self._current_cell_parts.append(text)
            return
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

    def fill_rowspan_cells(self, fill_all: bool = False) -> None:
        while self._current_col in self._rowspans:
            remaining, text = self._rowspans[self._current_col]
            self._current_row.append(text)
            if remaining <= 1:
                del self._rowspans[self._current_col]
            else:
                self._rowspans[self._current_col] = (remaining - 1, text)
            self._current_col += 1
        if fill_all:
            for col in sorted(col for col in self._rowspans if col >= self._current_col):
                while self._current_col < col:
                    self._current_row.append("")
                    self._current_col += 1
                self.fill_rowspan_cells()

    def add_image(self, attrs: dict[str, str]) -> None:
        src = attrs.get("src", "").strip() or attrs.get("data-src", "").strip() or attrs.get("data-original", "").strip()
        if not src:
            return

        alt = repair_mojibake(html.unescape(attrs.get("alt", "").strip()))
        title = repair_mojibake(html.unescape(attrs.get("title", "").strip()))
        image = HTMLImage(index=len(self.images) + 1, src=src, alt=alt, title=title)

        if src.startswith("data:"):
            extracted = extract_data_image(src, self.source_path, image.index, self.image_output_dir, self.project_root)
            if extracted:
                extracted.alt = alt
                extracted.title = title
                image = extracted
                self.image_paths.append(image.local_path)
            safe_src = image.local_path or "[inline-image]"
            image.src = "[inline-image]"
        else:
            safe_src = src
            self.image_paths.append(src)

        self.images.append(image)
        image_text = image_marker(image)
        if self._table_depth and self._current_cell_parts is not None:
            self._current_cell_parts.append(image_text)
        self.parts.append("\n" + image_text + "\n")
        if not image.local_path:
            label = image.alt or image.title or f"image-{image.index}"
            self.parts.append(f"![{label}]({safe_src})\n")


def parse_span(value: str) -> int:
    try:
        return max(1, min(50, int(value)))
    except ValueError:
        return 1


def clean_cell_text(text: str) -> str:
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def render_markdown_table(rows: list[list[str]], caption: str = "") -> str:
    if not rows:
        return ""

    width = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (width - len(row)) for row in rows]
    escaped_rows = [[escape_table_cell(cell) for cell in row] for row in normalized_rows]

    lines: list[str] = []
    if caption:
        lines.append(f"Table: {caption}")
        lines.append("")
    lines.append("| " + " | ".join(escaped_rows[0]) + " |")
    if len(escaped_rows) > 1:
        lines.append("| " + " | ".join("---" for _ in range(width)) + " |")
        lines.extend("| " + " | ".join(row) + " |" for row in escaped_rows[1:])
    return "\n".join(lines)


def escape_table_cell(text: str) -> str:
    text = text.replace("|", "\\|")
    text = re.sub(r"\s*\n\s*", "<br>", text)
    return text.strip()


def image_marker(image: HTMLImage) -> str:
    label = image.alt or image.title or f"image-{image.index}"
    details = [f"[Image {image.index}: {label}]"]
    if image.local_path:
        details.append(f"path={image.local_path}")
    elif image.src != "[inline-image]":
        details.append(f"src={image.src}")
    if image.mime_type:
        details.append(f"mime={image.mime_type}")
    if image.width and image.height:
        details.append(f"size={image.width}x{image.height}")
    if image.description:
        details.append(f"description={one_line(image.description, 160)}")
    if image.ocr_text:
        details.append(f"ocr={one_line(image.ocr_text, 200)}")
    return " ".join(details)


def one_line(text: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", text).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."

