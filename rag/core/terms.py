from __future__ import annotations

import re


ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9_.$/@:#-]{2,}")
CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")


def generate_chunk_terms(*texts: str, max_terms: int = 8000) -> list[str]:
    terms: set[str] = set()
    for text in texts:
        if not text:
            continue
        for token in ASCII_TOKEN_RE.findall(text):
            terms.add(token.lower())
        for run in CJK_RUN_RE.findall(text):
            for gram in cjk_ngrams(run):
                terms.add(gram)
        if len(terms) >= max_terms:
            break
    return sorted(terms)[:max_terms]


def query_term_groups(query: str) -> list[list[str]]:
    groups: list[list[str]] = []
    for token in re.findall(r"[A-Za-z0-9_.$/@:#-]+|[\u4e00-\u9fff]+", query):
        if not token.strip():
            continue
        if any("\u4e00" <= char <= "\u9fff" for char in token):
            groups.append(cjk_ngrams(token) or [token])
        else:
            groups.append([token.lower()])
    return groups


def cjk_ngrams(text: str) -> list[str]:
    if len(text) <= 2:
        return [text]
    grams: set[str] = set()
    for size in (2, 3, 4):
        if len(text) < size:
            continue
        for index in range(0, len(text) - size + 1):
            grams.add(text[index : index + size])
    grams.add(text)
    return sorted(grams)

