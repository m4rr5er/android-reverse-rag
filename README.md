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
```

## Supported MVP File Types

- HTML: `.html`, `.htm`
- Markdown and text: `.md`, `.markdown`, `.txt`
- Documents: `.pdf`, `.docx`
- Code/config: `.smali`, `.java`, `.kt`, `.js`, `.ts`, `.py`, `.json`, `.xml`, `.c`, `.cpp`, `.h`, `.hpp`

PDF parsing first tries optional libraries (`pypdf`, then `PyMuPDF`) and falls back to a basic built-in extractor for simple text streams. DOCX parsing uses Python standard library XML extraction.

HTML parsing preserves tables as Markdown tables. Inline `data:image/...;base64` images are extracted to `data/images/`, while search snippets keep image markers such as:

```text
[Image 1: 图片] path=data/images/.../image-0001.webp mime=image/webp
```

## Notes

`corpus/`, `data/`, and `index/` are ignored by Git because they may contain private research notes, samples, extracted content, OCR results, or generated indexes.
