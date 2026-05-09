from __future__ import annotations

import tempfile
import unittest
import zipfile
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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

    def test_chinese_term_index_supports_substring_search(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir)
            corpus = root / "corpus"
            data = root / "data"
            corpus.mkdir()
            source = corpus / "note.md"
            source.write_text("# 逆向笔记\n\n这里记录风控设备指纹和参数分析。", encoding="utf-8")
            config = RAGConfig(project_root=root, corpus_dir=corpus, data_dir=data, database_path=data / "rag.sqlite")

            ingest(config, full=True)
            results = search(config, "设备指纹", top_k=3)
            self.assertEqual(len(results), 1)
            self.assertIn("风控设备指纹", results[0].text)

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
                    <table><caption>字段表</caption>
                      <tr><th>参数</th><th>含义</th></tr>
                      <tr><td rowspan="2">x-mini-sig</td><td>签名字段</td></tr>
                      <tr><td colspan="1">请求签名</td></tr>
                    </table>
                    <img alt="流程图" src="data:image/png;base64,iVBORw0KGgo=">
                  </body>
                </html>
                """,
                encoding="utf-8",
            )

            parsed = parse_file(html_path, root, image_output_dir=root / "data" / "images")
            self.assertIn("Table: 字段表", parsed.text)
            self.assertIn("| 参数 | 含义 |", parsed.text)
            self.assertIn("| x-mini-sig | 签名字段 |", parsed.text)
            self.assertIn("| x-mini-sig | 请求签名 |", parsed.text)
            self.assertIn("[Image 1: 流程图]", parsed.text)
            self.assertEqual(parsed.metadata["table_count"], 1)
            image = parsed.metadata["images"][0]
            self.assertEqual(image["src"], "[inline-image]")
            self.assertEqual(image["mime_type"], "image/png")
            self.assertTrue((root / image["local_path"]).exists())

            image_path = root / image["local_path"]
            image_path.with_suffix(image_path.suffix + ".ocr.txt").write_text("图片中包含 JNI_OnLoad 流程", encoding="utf-8")
            image_path.with_suffix(image_path.suffix + ".desc.txt").write_text("风控流程图", encoding="utf-8")
            reparsed = parse_file(html_path, root, image_output_dir=root / "data" / "images")
            self.assertIn("ocr=图片中包含 JNI_OnLoad 流程", reparsed.text)
            self.assertIn("description=风控流程图", reparsed.text)

    def test_media_gc_removes_orphaned_extracted_images(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            root = Path(temp_dir)
            corpus = root / "corpus"
            data = root / "data"
            corpus.mkdir()
            source = corpus / "sample.html"
            source.write_text(
                '<html><body><img alt="图" src="data:image/png;base64,iVBORw0KGgo="></body></html>',
                encoding="utf-8",
            )
            config = RAGConfig(project_root=root, corpus_dir=corpus, data_dir=data, database_path=data / "rag.sqlite")

            ingest(config, full=True)
            image_files = list((data / "images").rglob("*.png"))
            self.assertEqual(len(image_files), 1)

            source.unlink()
            stats = ingest(config)
            self.assertEqual(stats["deleted"], 1)
            self.assertGreaterEqual(stats["media_deleted_files"], 1)
            self.assertEqual(list((data / "images").rglob("*.png")), [])


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
