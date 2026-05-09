from __future__ import annotations

import hashlib
import re

from rag.core.models import Chunk, ParsedDocument


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def chunk_document(document: ParsedDocument, max_chars: int = 1200, overlap_chars: int = 160) -> list[Chunk]:
    if not document.text:
        return []

    if document.source_type == "code":
        raw_sections = [("code", part) for part in split_code(document.text, max_chars)]
    else:
        raw_sections = split_markdownish(document.text)

    chunks: list[Chunk] = []
    chunk_index = 0
    for section, text in raw_sections:
        for piece in split_long_text(text, max_chars, overlap_chars):
            cleaned = piece.strip()
            if not cleaned:
                continue
            chunks.append(
                Chunk(
                    chunk_id=stable_chunk_id(document.doc_id, chunk_index, cleaned),
                    doc_id=document.doc_id,
                    source_path=document.source_path,
                    source_type=document.source_type,
                    title=document.title,
                    section=section or f"chunk-{chunk_index}",
                    chunk_index=chunk_index,
                    text=cleaned,
                    metadata=dict(document.metadata),
                )
            )
            chunk_index += 1
    return chunks


def split_markdownish(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_section = "intro"
    current_lines: list[str] = []

    for line in text.splitlines():
        match = HEADING_RE.match(line.strip())
        if match and current_lines:
            sections.append((current_section, "\n".join(current_lines).strip()))
            current_lines = []
        if match:
            current_section = match.group(2).strip()
        current_lines.append(line)

    if current_lines:
        sections.append((current_section, "\n".join(current_lines).strip()))

    if not sections:
        return [("content", text)]
    return sections


def split_code(text: str, max_chars: int) -> list[str]:
    paragraphs = re.split(r"\n\s*\n", text)
    chunks: list[str] = []
    buffer: list[str] = []
    size = 0

    for paragraph in paragraphs:
        paragraph = paragraph.rstrip()
        if not paragraph:
            continue
        next_size = size + len(paragraph) + 2
        if buffer and next_size > max_chars:
            chunks.append("\n\n".join(buffer))
            buffer = []
            size = 0
        buffer.append(paragraph)
        size += len(paragraph) + 2

    if buffer:
        chunks.append("\n\n".join(buffer))
    return chunks or [text]


def split_long_text(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    paragraphs = re.split(r"(\n\s*\n)", text)
    pieces: list[str] = []
    buffer = ""

    for part in paragraphs:
        if len(buffer) + len(part) <= max_chars:
            buffer += part
            continue
        if buffer.strip():
            pieces.extend(split_oversized(buffer, max_chars, overlap_chars))
        buffer = part

    if buffer.strip():
        pieces.extend(split_oversized(buffer, max_chars, overlap_chars))
    return pieces


def split_oversized(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    pieces: list[str] = []
    start = 0
    step = max(1, max_chars - overlap_chars)
    while start < len(text):
        end = min(len(text), start + max_chars)
        pieces.append(text[start:end])
        if end >= len(text):
            break
        start += step
    return pieces


def stable_chunk_id(doc_id: str, chunk_index: int, text: str) -> str:
    value = f"{doc_id}:{chunk_index}:{text}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

