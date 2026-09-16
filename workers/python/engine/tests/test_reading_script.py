"""Reading Script Layer（ADR-0006）のユニットテスト。

LLM・TTS サーバ・ネットワーク一切不要。
読み辞書、全文かなチェック、ReadingScript 契約を検証する。
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

# engine ディレクトリを path に追加
ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from reading import (
    ReadingDictionary,
    ReadingScript,
    ReadingScriptSegment,
    kanji_chars,
    kanji_residue,
    validate_reading_script,
)
from script_writer import DictionaryScriptWriter


# ============================================================================
# 漢字検出
# ============================================================================


class TestKanjiDetection:
    def test_kanji_chars_basic(self):
        assert kanji_chars("千早振る神") == {"千", "早", "振", "神"}

    def test_kanji_chars_empty(self):
        assert kanji_chars("") == set()
        assert kanji_chars(None) == set()

    def test_kana_and_ascii_not_kanji(self):
        assert kanji_chars("ひらがなカタカナabc123!？") == set()

    def test_kanji_residue_sorted_unique(self):
        residue = kanji_residue("神神様、千早")
        assert residue == sorted(set(residue))
        assert "神" in residue and "千" in residue and "早" in residue


# ============================================================================
# ReadingDictionary
# ============================================================================


class TestReadingDictionary:
    def test_update_and_get(self):
        d = ReadingDictionary()
        d.update("千早", "ちはや")
        assert d.get("千早") == "ちはや"
        assert "千早" in d
        assert len(d) == 1

    def test_update_rejects_empty(self):
        d = ReadingDictionary()
        with pytest.raises(ValueError):
            d.update("", "よみ")
        with pytest.raises(ValueError):
            d.update("表記", "")
        with pytest.raises(ValueError):
            d.update("表記\n改行", "よみ")

    def test_update_many_counts_new(self):
        d = ReadingDictionary({"既存": "きぞん"})
        added = d.update_many({"既存": "きぞん", "新規": "しんき"})
        assert added == 1

    def test_apply_longest_match_wins(self):
        d = ReadingDictionary({"貼付": "はりつけ", "貼付け": "はりつけ"})
        assert d.apply("書類を貼付した") == "書類をはりつけした"

    def test_apply_no_reprocessing(self):
        """置換結果をさらに置換しない（Easy と同じセマンティクス）。"""
        d = ReadingDictionary({"貼付": "はりつけ", "はり": "張り"})
        assert d.apply("貼付する") == "はりつけする"

    def test_apply_longest_surface_first(self):
        d = ReadingDictionary({"千早": "ちはや", "千早振る": "ちはやぶる"})
        assert d.apply("千早振る神") == "ちはやぶる神"

    def test_apply_empty_text(self):
        d = ReadingDictionary({"千早": "ちはや"})
        assert d.apply("") == ""


class TestReadingDictionaryJsonInterop:
    """Easy-Irodori-TTS reading_dictionary.json との相互運用。"""

    def test_save_and_load_roundtrip(self, tmp_path: Path):
        d = ReadingDictionary({"千早": "ちはや", "貼付": "はりつけ"})
        path = tmp_path / "reading_dictionary.json"
        d.save_json(path)
        loaded = ReadingDictionary.load_json(path)
        assert loaded.entries() == d.entries()

    def test_saved_format_is_flat_json(self, tmp_path: Path):
        """Easy の easy_dictionary.load() がそのまま読める形式。"""
        d = ReadingDictionary({"千早": "ちはや"})
        path = tmp_path / "reading_dictionary.json"
        d.save_json(path)
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        assert raw == {"千早": "ちはや"}

    def test_load_missing_file_returns_empty(self, tmp_path: Path):
        d = ReadingDictionary.load_json(tmp_path / "no_such.json")
        assert len(d) == 0

    def test_load_rejects_invalid_format(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
        with pytest.raises(ValueError):
            ReadingDictionary.load_json(path)

    def test_atomic_save_leaves_no_tmp(self, tmp_path: Path):
        path = tmp_path / "reading_dictionary.json"
        ReadingDictionary({"千早": "ちはや"}).save_json(path)
        assert not (tmp_path / "reading_dictionary.json.tmp").exists()


class TestReadingDictionarySqlite:
    def test_save_and_load_roundtrip(self, tmp_path: Path):
        db = tmp_path / "story.db"
        d = ReadingDictionary({"千早": "ちはや", "貼付": "はりつけ"})
        d.save_sqlite(db)
        loaded = ReadingDictionary.load_sqlite(db)
        assert loaded.entries() == d.entries()

    def test_upsert_overwrites(self, tmp_path: Path):
        db = tmp_path / "story.db"
        ReadingDictionary({"千早": "せんそう"}).save_sqlite(db)
        ReadingDictionary({"千早": "ちはや"}).save_sqlite(db)
        loaded = ReadingDictionary.load_sqlite(db)
        assert loaded.get("千早") == "ちはや"

# ============================================================================
# ReadingScript 契約
# ============================================================================


class TestReadingScript:
    def test_uncovered_kanji_reports_residue(self):
        script = ReadingScript(chunk_index=0, segments=[
            ReadingScriptSegment(
                id="seg_001", speaker="narrator",
                text="夕暮れの街を歩いていた。",
                text_reading="ゆうぐれのまちをあるいていた。"),
            ReadingScriptSegment(
                id="seg_002", speaker="chihaya",
                text="千早と申します。",
                text_reading="千早と申します。"),  # 変換漏れ
        ])
        uncovered = script.uncovered_kanji()
        assert set(uncovered) == {"seg_002"}
        assert "千" in uncovered["seg_002"]

    def test_uncovered_kanji_empty_when_all_kana(self):
        script = ReadingScript(segments=[
            ReadingScriptSegment(
                id="seg_001", text="貼付", text_reading="はりつけ"),
        ])
        assert script.uncovered_kanji() == {}

    def test_apply_dictionary_converts_llm_leftover_kanji(self):
        """LLM が漢字表記を残していても、最終適用で辞書が変換する（ADR-0006 §3）。"""
        script = ReadingScript(segments=[
            ReadingScriptSegment(
                id="seg_001", text="千早と申します。",
                text_reading="千早と申します。"),  # LLM が漢字を残した
        ])
        script.apply_dictionary(ReadingDictionary({"千早": "ちはや"}))
        assert script.segments[0].text_reading == "ちはやと申します。"

    def test_original_text_is_preserved(self):
        """原文は失われない（ADR-0006 §1）。"""
        seg = ReadingScriptSegment(
            id="seg_001", text="千早と申します。",
            text_reading="ちはやともうします。")
        assert seg.text == "千早と申します。"


class TestValidateReadingScript:
    def test_valid_doc(self):
        doc = {"segments": [
            {"id": "seg_001", "text": "原文",
             "text_reading": "げんぶん"}]}
        assert validate_reading_script(doc) == []

    def test_missing_segments(self):
        assert validate_reading_script({}) != []

    def test_empty_text(self):
        doc = {"segments": [{"id": "seg_001", "text": " ",
                             "text_reading": "x"}]}
        assert any("text" in e for e in validate_reading_script(doc))

    def test_missing_reading(self):
        doc = {"segments": [{"id": "seg_001", "text": "原文"}]}
        errors = validate_reading_script(doc)
        assert any("text_reading" in e for e in errors)


# ============================================================================
# DictionaryScriptWriter（フォールバック・オフライン）
# ============================================================================


class TestDictionaryScriptWriter:
    def test_applies_dictionary_and_reports_uncovered(self):
        writer = DictionaryScriptWriter()
        result = writer.write_script(
            [{"id": "seg_001", "speaker": "narrator",
              "text": "千早が貼付を剥がす"}],
            ReadingDictionary({"千早": "ちはや", "貼付": "はりつけ"}),
            chunk_index=0,
        )
        seg = result.script.segments[0]
        assert seg.text_reading == "ちはやがはりつけを剥がす"
        # 「剥」は辞書に無いので uncovered に報告される
        assert result.uncovered == {"seg_001": ["剥"]}
        # 原文は保持される
        assert seg.text == "千早が貼付を剥がす"

    def test_no_dictionary_means_raw_passthrough(self):
        writer = DictionaryScriptWriter()
        result = writer.write_script(
            [{"id": "seg_001", "text": "その森には言い伝えがあった"}],
            ReadingDictionary(),
        )
        assert result.script.segments[0].text_reading == "その森には言い伝えがあった"
        assert "伝" in result.uncovered["seg_001"]

