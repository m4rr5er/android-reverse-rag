# android-reverse-rag

Local RAG knowledge base for Android reverse engineering, Frida, JNI, smali, native analysis, and anti-debugging research.

This MVP uses a local CLI and SQLite FTS5 keyword search. It is designed so future API server, MCP tools, OCR, PDF parsing, and vector search can reuse the same `rag.core` modules.

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

Search:

```powershell
python .\rag\cli\search.py "frida 检测"
python .\rag\cli\search.py "RegisterNatives"
python .\rag\cli\search.py "ollvm 字符串加密" --top-k 10
python .\rag\cli\search.py "JNI_OnLoad RegisterNatives" --type code
```

## Supported MVP File Types

- HTML: `.html`, `.htm`
- Markdown and text: `.md`, `.markdown`, `.txt`
- Code/config: `.smali`, `.java`, `.kt`, `.js`, `.ts`, `.py`, `.json`, `.xml`, `.c`, `.cpp`, `.h`, `.hpp`

## Notes

`corpus/`, `data/`, and `index/` are ignored by Git because they may contain private research notes, samples, extracted content, OCR results, or generated indexes.

