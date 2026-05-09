from __future__ import annotations

import hashlib
import re

from rag.core.models import Chunk, ParsedDocument


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
PYTHON_SYMBOL_RE = re.compile(r"^\s*(?:async\s+def|def|class)\s+([A-Za-z_][\w]*)", re.M)
SMALI_METHOD_RE = re.compile(r"^\.method\b.*$", re.M)
GENERIC_SYMBOL_RE = re.compile(
    r"^\s*(?:public|private|protected|static|final|internal|export|inline|suspend|native|\s)*"
    r"(?:class|interface|enum|object|fun|function)\s+([A-Za-z_$][\w$]*)",
    re.M,
)
GENERIC_METHOD_RE = re.compile(
    r"^\s*(?:public|private|protected|static|final|native|synchronized|override|inline|\s)+"
    r"[\w<>\[\].?$]+\s+([A-Za-z_$][\w$]*)\s*\([^;{}]*\)\s*(?:throws\s+[\w.,\s]+)?\{?",
    re.M,
)


def chunk_document(document: ParsedDocument, max_chars: int = 1200, overlap_chars: int = 160) -> list[Chunk]:
    if not document.text:
        return []

    if document.source_type == "code":
        language = str(document.metadata.get("language", ""))
        raw_sections = split_code_sections(document.text, language, max_chars)
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


def split_code_sections(text: str, language: str, max_chars: int) -> list[tuple[str, str]]:
    if language == "smali":
        sections = split_smali_methods(text)
    elif language == "py":
        sections = split_by_symbols(text, PYTHON_SYMBOL_RE)
    elif language in {"java", "kt", "js", "ts", "c", "cpp", "h", "hpp"}:
        sections = split_by_symbols(text, GENERIC_SYMBOL_RE)
        if len(sections) <= 1:
            sections = split_by_symbols(text, GENERIC_METHOD_RE)
    else:
        sections = []

    if not sections:
        sections = [("code", part) for part in split_code_blocks(text, max_chars)]
    return merge_small_code_sections(sections, max_chars)


def split_smali_methods(text: str) -> list[tuple[str, str]]:
    matches = list(SMALI_METHOD_RE.finditer(text))
    if not matches:
        return []

    sections: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        preamble = text[: matches[0].start()].strip()
        if preamble:
            sections.append(("class-header", preamble))

    for index, match in enumerate(matches):
        start = match.start()
        end_match = re.search(r"^\.end method\b.*$", text[start:], flags=re.M)
        if end_match:
            end = start + end_match.end()
        else:
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section = smali_method_name(match.group(0)) or f"method-{index}"
        sections.append((section, text[start:end].strip()))
    return sections


def smali_method_name(line: str) -> str:
    match = re.search(r"([<>\w$]+)\s*\(", line)
    return match.group(1) if match else line.strip()


def split_by_symbols(text: str, pattern: re.Pattern[str]) -> list[tuple[str, str]]:
    matches = list(pattern.finditer(text))
    if not matches:
        return []

    sections: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        preamble = text[: matches[0].start()].strip()
        if preamble:
            sections.append(("preamble", preamble))

    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        name = match.group(1) if match.groups() else f"symbol-{index}"
        sections.append((name, text[start:end].strip()))
    return sections


def merge_small_code_sections(sections: list[tuple[str, str]], max_chars: int) -> list[tuple[str, str]]:
    merged: list[tuple[str, str]] = []
    current_names: list[str] = []
    current_parts: list[str] = []
    current_size = 0

    for name, text in sections:
        if len(text) > max_chars:
            if current_parts:
                merged.append((", ".join(current_names), "\n\n".join(current_parts)))
                current_names = []
                current_parts = []
                current_size = 0
            merged.append((name, text))
            continue

        next_size = current_size + len(text) + 2
        if current_parts and next_size > max_chars:
            merged.append((", ".join(current_names), "\n\n".join(current_parts)))
            current_names = []
            current_parts = []
            current_size = 0
        current_names.append(name)
        current_parts.append(text)
        current_size += len(text) + 2

    if current_parts:
        merged.append((", ".join(current_names), "\n\n".join(current_parts)))
    return merged


def split_code_blocks(text: str, max_chars: int) -> list[str]:
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
