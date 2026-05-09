from __future__ import annotations

import base64
import hashlib
import json
import re
import struct
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from rag.core.encoding import read_text, repair_mojibake
from rag.core.models import display_path


MANIFEST_FILE = "media-manifest.json"


@dataclass
class HTMLImage:
    index: int
    src: str
    alt: str = ""
    title: str = ""
    local_path: str = ""
    mime_type: str = ""
    extracted: bool = False
    sha256: str = ""
    size_bytes: int = 0
    width: int | None = None
    height: int | None = None
    ocr_text: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract_data_image(
    src: str,
    source_path: str,
    index: int,
    image_output_dir: Path | None,
    project_root: Path | None,
) -> HTMLImage | None:
    if image_output_dir is None or "," not in src:
        return None

    header, payload = src.split(",", 1)
    match = re.match(r"data:(image/[A-Za-z0-9.+-]+);base64", header)
    if not match:
        return None

    mime_type = match.group(1).lower()
    extension = image_extension(mime_type)
    digest = hashlib.sha256(f"{source_path}:{index}:{payload[:256]}".encode("utf-8")).hexdigest()[:16]
    target_dir = image_output_dir / stable_id(source_path)[:12]
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"image-{index:04d}-{digest}.{extension}"
    if not target.exists():
        try:
            target.write_bytes(base64.b64decode(payload, validate=False))
        except Exception:
            return None

    data = target.read_bytes()
    local_path = display_path(target, project_root) if project_root else str(target)
    width, height = image_dimensions(data, mime_type)
    return HTMLImage(
        index=index,
        src="[inline-image]",
        local_path=local_path,
        mime_type=mime_type,
        extracted=True,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        width=width,
        height=height,
        ocr_text=load_image_ocr_text(target),
        description=load_image_description(target),
    )


def image_extension(mime_type: str) -> str:
    return {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/gif": "gif",
        "image/svg+xml": "svg",
    }.get(mime_type, "bin")


def image_dimensions(data: bytes, mime_type: str) -> tuple[int | None, int | None]:
    try:
        if mime_type == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
            return struct.unpack(">II", data[16:24])
        if mime_type in {"image/jpeg", "image/jpg"}:
            return jpeg_dimensions(data)
        if mime_type == "image/webp" and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            return webp_dimensions(data)
        if mime_type == "image/gif" and data[:6] in {b"GIF87a", b"GIF89a"} and len(data) >= 10:
            width, height = struct.unpack("<HH", data[6:10])
            return width, height
    except Exception:
        return None, None
    return None, None


def jpeg_dimensions(data: bytes) -> tuple[int | None, int | None]:
    offset = 2
    while offset + 9 < len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        offset += 2
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            height, width = struct.unpack(">HH", data[offset + 3 : offset + 7])
            return width, height
        segment_length = struct.unpack(">H", data[offset : offset + 2])[0]
        offset += segment_length
    return None, None


def webp_dimensions(data: bytes) -> tuple[int | None, int | None]:
    chunk = data[12:16]
    if chunk == b"VP8X" and len(data) >= 30:
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return width, height
    if chunk == b"VP8 " and len(data) >= 30:
        width, height = struct.unpack("<HH", data[26:30])
        return width & 0x3FFF, height & 0x3FFF
    if chunk == b"VP8L" and len(data) >= 25:
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None, None


def load_image_ocr_text(path: Path) -> str:
    for suffix in (".ocr.txt", ".txt"):
        sidecar = path.with_suffix(path.suffix + suffix)
        if sidecar.exists():
            return repair_mojibake(read_text(sidecar)).strip()
    try:
        from PIL import Image  # type: ignore
        import pytesseract  # type: ignore
    except ImportError:
        return ""
    try:
        text = pytesseract.image_to_string(Image.open(path), lang="chi_sim+eng")
        return repair_mojibake(text).strip()
    except Exception:
        return ""


def load_image_description(path: Path) -> str:
    for suffix in (".desc.txt", ".description.txt", ".md"):
        sidecar = path.with_suffix(path.suffix + suffix)
        if sidecar.exists():
            return repair_mojibake(read_text(sidecar)).strip()
    return ""


def manifest_path(data_dir: Path) -> Path:
    return data_dir / MANIFEST_FILE


def load_media_manifest(data_dir: Path) -> dict[str, dict[str, Any]]:
    path = manifest_path(data_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_media_manifest(data_dir: Path, manifest: dict[str, dict[str, Any]]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    manifest_path(data_dir).write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def reset_media_manifest(data_dir: Path) -> None:
    save_media_manifest(data_dir, {})


def update_media_manifest(data_dir: Path, source_path: str, images: list[dict[str, Any]]) -> None:
    manifest = load_media_manifest(data_dir)
    manifest = {path: entry for path, entry in manifest.items() if entry.get("source_path") != source_path}
    for image in images:
        local_path = image.get("local_path")
        if not local_path:
            continue
        manifest[local_path] = {"source_path": source_path, **image}
    save_media_manifest(data_dir, manifest)


def garbage_collect_media(data_dir: Path, active_source_paths: set[str]) -> dict[str, int]:
    images_dir = (data_dir / "images").resolve()
    manifest = load_media_manifest(data_dir)
    kept: dict[str, dict[str, Any]] = {}
    deleted_files = 0
    deleted_entries = 0
    active_paths: set[Path] = set()

    for local_path, entry in manifest.items():
        source_path = entry.get("source_path")
        candidate = Path(local_path)
        file_path = (candidate if candidate.is_absolute() else data_dir.parent / candidate).resolve()
        if source_path not in active_source_paths or not file_path.exists():
            deleted_entries += 1
            if is_within(file_path, images_dir) and file_path.exists():
                file_path.unlink()
                deleted_files += 1
            continue
        kept[local_path] = entry
        active_paths.add(file_path)

    if images_dir.exists():
        for file_path in images_dir.rglob("*"):
            if not file_path.is_file():
                continue
            resolved = file_path.resolve()
            if resolved not in active_paths and not file_path.name.endswith((".txt", ".md")):
                file_path.unlink()
                deleted_files += 1

    save_media_manifest(data_dir, kept)
    prune_empty_dirs(images_dir)
    return {"media_deleted_files": deleted_files, "media_deleted_entries": deleted_entries}


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def prune_empty_dirs(root: Path) -> None:
    if not root.exists():
        return
    for directory in sorted((path for path in root.rglob("*") if path.is_dir()), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass


def stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
