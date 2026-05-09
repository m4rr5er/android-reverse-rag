from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from rag.core.chunking import split_code_sections
from rag.core.config import RAGConfig
from rag.core.indexer import ingest
from rag.core.parsers import parse_file
from rag.core.searcher import search


class P1Tests(unittest.TestCase):
    def test_incremental_ingest_prunes_deleted_files(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir)
            corpus = root / "corpus"
            data = root / "data"
            corpus.mkdir()
            source = corpus / "note.md"
            source.write_text("# Frida\n\nRegisterNatives hook notes", encoding="utf-8")
            config = RAGConfig(
                project_root=root,
                corpus_dir=corpus,
                data_dir=data,
                database_path=data / "rag.sqlite",
            )

            first = ingest(config, full=True)
            self.assertEqual(first["indexed"], 1)
            self.assertEqual(len(search(config, "RegisterNatives")), 1)

            source.unlink()
            second = ingest(config)
            self.assertEqual(second["deleted"], 1)
            self.assertEqual(search(config, "RegisterNatives"), [])

    def test_docx_parser_extracts_paragraph_text(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir)
            docx_path = root / "sample.docx"
            create_minimal_docx(docx_path, "JNI_OnLoad RegisterNatives")

            parsed = parse_file(docx_path, root)
            self.assertEqual(parsed.source_type, "docx")
            self.assertIn("JNI_OnLoad RegisterNatives", parsed.text)

    def test_pdf_basic_parser_extracts_simple_text_stream(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir)
            pdf_path = root / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nstream\n(JNI_OnLoad RegisterNatives) Tj\nendstream\n%%EOF")

            parsed = parse_file(pdf_path, root)
            self.assertEqual(parsed.source_type, "pdf")
            self.assertIn("JNI_OnLoad RegisterNatives", parsed.text)

    def test_code_chunking_uses_smali_method_sections(self) -> None:
        smali = """.class public Lcom/example/MainActivity;

.method public static native check()V
    .registers 1
    return-void
.end method

.method private bypassTracerPid()V
    .registers 1
    return-void
.end method
"""
        sections = split_code_sections(smali, "smali", 1200)
        names = [name for name, _ in sections]
        self.assertTrue(any("check" in name for name in names))
        self.assertTrue(any("bypassTracerPid" in name for name in names))

    def test_html_parser_extracts_tables_and_inline_images(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir)
            html_path = root / "sample.html"
            html_path.write_text(
                """
                <html>
                  <head><title>风控表格</title></head>
                  <body>
                    <table>
                      <tr><th>参数</th><th>含义</th></tr>
                      <tr><td>x-mini-sig</td><td>签名字段</td></tr>
                    </table>
                    <img alt="流程图" src="data:image/png;base64,iVBORw0KGgo=">
                  </body>
                </html>
                """,
                encoding="utf-8",
            )

            parsed = parse_file(html_path, root, image_output_dir=root / "data" / "images")
            self.assertIn("| 参数 | 含义 |", parsed.text)
            self.assertIn("| x-mini-sig | 签名字段 |", parsed.text)
            self.assertIn("[Image 1: 流程图]", parsed.text)
            self.assertEqual(parsed.metadata["table_count"], 1)
            image = parsed.metadata["images"][0]
            self.assertEqual(image["src"], "[inline-image]")
            self.assertEqual(image["mime_type"], "image/png")
            self.assertTrue((root / image["local_path"]).exists())


def create_minimal_docx(path: Path, text: str) -> None:
    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>{text}</w:t></w:r></w:p>
  </w:body>
</w:document>
"""
    core_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
  xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:title>sample</dc:title>
</cp:coreProperties>
"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("docProps/core.xml", core_xml)


if __name__ == "__main__":
    unittest.main()
