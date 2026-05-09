from __future__ import annotations


MOJIBAKE_MARKERS = set(
    "鏌钖疉椋帶鍙傛暟鍒嗘瀽鍘熷垱瀛ｄ笢骞鏈鏃姹熻嫃寰绯诲垪猻浼氫粠澶村紑濮嬶紝鑻ユ姄鍖呮垨鑰呭叾瀹冨彲浠ョ湅涔嬪墠鐨勬枃绔狅"
)


def read_text(path) -> str:
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

