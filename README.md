# android-reverse-rag

Local RAG knowledge base for Android reverse engineering, Frida, JNI, smali, native analysis, and anti-debugging research.

This MVP uses a local CLI and SQLite FTS5 keyword search. It is designed so future API server, MCP tools, OCR, and vector search can reuse the same `rag.core` modules.

## Layout

```text
corpus/       Local source material, ignored by Git
data/         SQLite database and generated data, ignored by Git
index/        Reserved for future vector indexes, ignored by Git
rag/core/     Reusable parsing, chunking, indexing, and search logic
rag/cli/      Command-line entry points
examples/     Small safe sample files for testing
tests/        Future test suite
```

## Quick Start

Create the runtime directories:

```powershell
python .\rag\cli\status.py
```

Add your materials under `corpus/`, for example:

```text
corpus/html/frida-bypass.html
corpus/code/MainActivity.smali
corpus/docs/notes.md
```

Build the index:

```powershell
python .\rag\cli\ingest.py --full
```

Update the index incrementally after adding, changing, or deleting files:

```powershell
python .\rag\cli\ingest.py
```

Search:

```powershell
python .\rag\cli\search.py "frida 检测"
python .\rag\cli\search.py "RegisterNatives"
python .\rag\cli\search.py "ollvm 字符串加密" --top-k 10
python .\rag\cli\search.py "JNI_OnLoad RegisterNatives" --type code
python .\rag\cli\search.py "JNI_OnLoad RegisterNatives" --mode all
python .\rag\cli\search.py "设备指纹" --context 1
```

Inspect indexed documents before drilling into a long article:

```powershell
python .\rag\cli\docs.py list
python .\rag\cli\docs.py outline "某红薯"
python .\rag\cli\docs.py show "某红薯" --section "设备指纹" --limit 3
```

Inspect or clean extracted media:

```powershell
python .\rag\cli\media.py list
python .\rag\cli\media.py gc
```

## Supported MVP File Types

- HTML: `.html`, `.htm`
- Markdown and text: `.md`, `.markdown`, `.txt`
- Documents: `.pdf`, `.docx`
- Code/config: `.smali`, `.java`, `.kt`, `.js`, `.ts`, `.py`, `.json`, `.xml`, `.c`, `.cpp`, `.h`, `.hpp`

PDF parsing first tries optional libraries (`pypdf`, then `PyMuPDF`) and falls back to a basic built-in extractor for simple text streams. DOCX parsing uses Python standard library XML extraction.

Chinese queries use SQLite FTS5 first, then a local n-gram term index, then a final substring fallback. This keeps exact reverse-engineering tokens searchable while making Chinese phrase searches such as `设备指纹` reliable.

HTML parsing preserves tables as Markdown tables, including basic `caption`, `rowspan`, and `colspan` handling. Inline `data:image/...;base64` images are extracted to `data/images/`, tracked in `data/media-manifest.json`, and garbage-collected when source documents are removed. Search snippets keep image markers such as:

```text
[Image 1: 图片] path=data/images/.../image-0001.webp mime=image/webp
```

If an image has a sidecar file such as `image.webp.ocr.txt` or `image.webp.desc.txt`, that text is included in the image marker and metadata. If optional OCR dependencies are installed, image/PDF OCR is attempted automatically.

## Notes

`corpus/`, `data/`, and `index/` are ignored by Git because they may contain private research notes, samples, extracted content, OCR results, or generated indexes.
