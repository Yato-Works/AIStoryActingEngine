"""Document Importer のテスト (TXT, PDF, worker RPC)。"""

from pathlib import Path
import pytest
from pypdf import PdfWriter

from importer import read_text_file, extract_pdf_text, import_book_document, clean_story_text
from worker import EngineWorker
from memory import MemoryEngine


def test_clean_story_text():
    raw = "ルーデウスは《あさ》目を覚ました。\n｜魔術《まじゅつ》の練習をする。\n［＃ここから１字下げ］\n今日も一日が始まる。"
    cleaned = clean_story_text(raw)
    assert "《あさ》" not in cleaned
    assert "《まじゅつ》" not in cleaned
    assert "［＃" not in cleaned
    assert "魔術の練習をする。" in cleaned


def test_import_text_file(tmp_path):
    txt_file = tmp_path / "novel.txt"
    txt_file.write_text("第1章 旅立ち\n\n彼は剣を抜いた。", encoding="utf-8")

    out_file = import_book_document([txt_file], title="旅立ちの書", out_dir=tmp_path / "out")
    assert out_file.exists()
    assert out_file.name == "旅立ちの書.txt"
    content = out_file.read_text(encoding="utf-8")
    assert "第1章 旅立ち" in content


def test_import_pdf_file(tmp_path):
    pdf_file = tmp_path / "sample.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    # pypdfの書き込み確認
    with open(pdf_file, "wb") as f:
        writer.write(f)

    # 空ページの場合は ValueError になる仕様
    with pytest.raises(ValueError, match="テキストレイヤーがありません"):
        extract_pdf_text(pdf_file)


def test_worker_import_document_rpc(tmp_path):
    db_file = tmp_path / "story.db"
    mem = MemoryEngine(db_file, "book_1")
    mem.close()

    worker = EngineWorker(db_file)
    txt_file = tmp_path / "chapter1.txt"
    txt_file.write_text("星詠みの旅人 第1話\n静かな夜空を見上げ、語り手が静かに口を開いた。", encoding="utf-8")

    res = worker.dispatch("import_document", {
        "sources": [str(txt_file)],
        "title": "星詠みの旅人_第1話",
    })
    assert res["ok"] is True
    assert res["title"] == "星詠みの旅人_第1話"
    assert Path(res["novel_path"]).exists()
