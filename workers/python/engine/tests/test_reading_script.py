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
    READING_SCRIPT_JSON,
    READING_SCRIPT_TEXT,
    ReadingDictionary,
    ReadingScript,
    ReadingScriptSegment,
    kanji_chars,
    kanji_residue,
    load_reading_script,
    merge_reading_script_doc,
    reading_script_doc,
    render_reading_script_text,
    save_reading_script,
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
# OpenJTalk G2P（pyopenjtalk が導入済みの環境のみ）
# ============================================================================

import pytest

from reading_g2p import g2p_kana, openjtalk_available

requires_openjtalk = pytest.mark.skipif(not openjtalk_available(),
                                        reason="pyopenjtalk 未導入")


@pytest.mark.skipif(not openjtalk_available(), reason="pyopenjtalk 未導入")
class TestOpenJTalkG2P:
    def test_okagesa_read_correctly(self):
        """実機事故（LLM: おおげすさ）の回帰テスト。"""
        out = g2p_kana("大げさ")
        assert out in ("オーゲサ", "おおげさ", "オーゲサナ", "おおげさな")

    def test_noumiso_read_correctly(self):
        out = g2p_kana("脳味噌")
        assert out in ("ノーミソ", "のうみそ", "ノウミソ")

    def test_yuugure_read_correctly(self):
        out = g2p_kana("夕暮れ")
        assert out in ("ユーグレ", "ゆうぐれ", "ユウグレ")

    def test_punctuation_preserved(self):
        out = g2p_kana("走る。走る？")
        assert "。" in out and "？" in out

    def test_dictionary_wins_before_g2p(self):
        """辞書（貼付=はりつけ）→ G2P の順なので、OpenJTalk のチョーフ誤読を上書きできる。"""
        from reading import ReadingDictionary
        from script_writer import OpenJTalkScriptWriter
        result = OpenJTalkScriptWriter().write_script(
            [{"id": "seg_001", "text": "書類を貼付する"}],
            ReadingDictionary({"貼付": "はりつけ"}),
        )
        reading = result.script.segments[0].text_reading
        assert "チョーフ" not in reading and "ちょうふ" not in reading
        assert "はりつけ" in reading or "ハリツケ" in reading


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


# ============================================================================
# 監査成果物（ADR-0006 §6）— 読み台本の保存と目視検証
# ============================================================================


class TestReadingScriptArtifact:
    def _segments(self):
        return [
            (0, [
                ReadingScriptSegment(id="seg_000", speaker="narrator",
                                     text="夕暮れの商店街を歩いた。",
                                     text_reading="ユーグレノショーテンガイヲアルイタ。"),
                ReadingScriptSegment(id="seg_001", speaker="chihaya",
                                     text="千早は看板を見た。",
                                     text_reading="チハヤワ看板ヲミタ。"),
            ]),
        ]

    def test_doc_keeps_text_and_reading(self):
        doc = reading_script_doc(self._segments(), book_id="sample",
                                 writer="openjtalk")
        assert doc["version"] == "1"
        assert doc["book_id"] == "sample"
        assert doc["writer"] == "openjtalk"
        seg = doc["segments"][0]
        assert seg["id"] == "seg_000" and seg["chunk_index"] == 0
        assert seg["speaker"] == "narrator"
        assert seg["text"] == "夕暮れの商店街を歩いた。"
        assert seg["text_reading"] == "ユーグレノショーテンガイヲアルイタ。"

    def test_doc_reports_residue_and_validates(self):
        doc = reading_script_doc(self._segments(), book_id="sample")
        # かな版に「看板」が残っているセグメントだけが報告される
        assert doc["residue"] == {"seg_001": ["板", "看"]}
        # performance.json と同じ流儀の検証を通す（契約互換）
        assert validate_reading_script(doc) == []

    def test_doc_accepts_issue_objects(self):
        class _Issue:  # ReadingIssue（pydantic）と同じ属性を持つ
            kind = "kanji_residue"
            segment_id = "seg_001"
            detail = "漢字が残存: 看板"

        doc = reading_script_doc(self._segments(), judge_issues=[_Issue()])
        assert doc["judge"]["ok"] is False
        assert doc["judge"]["issues"] == [{
            "kind": "kanji_residue", "segment_id": "seg_001",
            "detail": "漢字が残存: 看板"}]

    def test_render_text_pairs_original_and_kana(self):
        doc = reading_script_doc(self._segments(), book_id="sample",
                                 writer="openjtalk")
        text = render_reading_script_text(doc)
        assert "# 読み台本 sample" in text
        assert "# 台本家: openjtalk" in text
        assert "原文: 夕暮れの商店街を歩いた。" in text
        assert "かな: ユーグレノショーテンガイヲアルイタ。" in text
        assert "[seg_001] chihaya (ch1)" in text

    def test_render_text_reports_residue_and_issues(self):
        class _Issue:
            kind = "kanji_residue"
            segment_id = "seg_001"
            detail = "漢字が残存: 看板"

        doc = reading_script_doc(self._segments(), judge_issues=[_Issue()])
        text = render_reading_script_text(doc)
        assert "# 読み審査: 要確認" in text
        assert "⚠ 漢字残留 seg_001: 板看" in text
        assert "⚖ [kanji_residue] seg_001" in text

    def test_save_and_load_roundtrip(self, tmp_path):
        doc = reading_script_doc(self._segments(), book_id="sample",
                                 writer="openjtalk", dictionary_path="data/x.json")
        json_path, txt_path = save_reading_script(tmp_path / "book", doc)
        assert json_path.name == READING_SCRIPT_JSON
        assert txt_path.name == READING_SCRIPT_TEXT
        loaded = load_reading_script(json_path)
        assert loaded["segments"] == doc["segments"]
        assert loaded["judge"]["ok"] is True
        assert txt_path.read_text(encoding="utf-8").startswith("# 読み台本 sample")
        # 一時ファイルを残さない（原子的保存）
        leftovers = [p.name for p in (tmp_path / "book").iterdir()
                     if p.suffix == ".tmp"]
        assert leftovers == []

    def test_save_creates_directory(self, tmp_path):
        target = tmp_path / "deep" / "book"
        json_path, _ = save_reading_script(
            target, reading_script_doc([], book_id="empty"))
        assert json_path.exists()

    def test_empty_chunks_yield_valid_empty_doc(self):
        doc = reading_script_doc([], book_id="empty")
        assert doc["segments"] == [] and doc["residue"] == {}
        assert doc["judge"] == {"ok": True, "issues": []}


# ============================================================================
# 監査成果物の統合（--resume で部分実行しても本全体を映す）
# ============================================================================


class TestMergeReadingScript:
    def _doc(self, segments, issues=None):
        chunks = []
        for seg in segments:
            chunks.append((seg["chunk_index"], [
                ReadingScriptSegment(id=seg["id"], speaker=seg.get("speaker", ""),
                                     text=seg["text"],
                                     text_reading=seg["text_reading"])]))
        return reading_script_doc(chunks, book_id="book", writer="openjtalk",
                                  judge_issues=issues)

    def test_first_run_passes_new_doc_through(self):
        new = self._doc([{"id": "seg_000", "chunk_index": 0,
                          "text": "夕暮れ。", "text_reading": "ユーグレ。"}])
        assert merge_reading_script_doc(None, new) == new
        assert merge_reading_script_doc({}, new) == new

    def test_keeps_untouched_segments_from_existing(self):
        existing = self._doc([
            {"id": "seg_000", "chunk_index": 0, "text": "一。", "text_reading": "イチ。"},
            {"id": "seg_001", "chunk_index": 1, "text": "二。", "text_reading": "ニ。"},
        ])
        # resume で未合成だった ch2 だけを作り直した状況
        new = self._doc([{"id": "seg_001", "chunk_index": 1,
                          "text": "二。", "text_reading": "ニカイ。"}])
        merged = merge_reading_script_doc(existing, new)
        by_id = {s["id"]: s["text_reading"] for s in merged["segments"]}
        assert by_id == {"seg_000": "イチ。", "seg_001": "ニカイ。"}
        # 並びは (chunk_index, id)
        assert [s["id"] for s in merged["segments"]] == ["seg_000", "seg_001"]

    def test_keeps_issues_of_untouched_segments(self):
        class _Issue:
            kind = "kanji_residue"
            segment_id = "seg_000"
            detail = "漢字が残存: 一"

        existing = reading_script_doc(
            [(0, [ReadingScriptSegment(id="seg_000", text="一。",
                                       text_reading="一。")])],
            book_id="book", judge_issues=[_Issue()])
        new = self._doc([{"id": "seg_001", "chunk_index": 1,
                          "text": "二。", "text_reading": "ニ。"}])
        merged = merge_reading_script_doc(existing, new)
        assert merged["judge"]["ok"] is False
        assert [i["segment_id"] for i in merged["judge"]["issues"]] == ["seg_000"]
        assert merged["residue"] == {"seg_000": ["一"]}

    def test_rerun_clears_stale_residue_for_touched_segment(self):
        existing = reading_script_doc(
            [(0, [ReadingScriptSegment(id="seg_000", text="千早。",
                                       text_reading="千早。")])], book_id="book")
        assert existing["residue"] == {"seg_000": ["千", "早"]}
        # 辞書修正後に同じセグメントを作り直すと残留は消える
        new = self._doc([{"id": "seg_000", "chunk_index": 0,
                          "text": "千早。", "text_reading": "チハヤ。"}])
        merged = merge_reading_script_doc(existing, new)
        assert merged["residue"] == {} and merged["judge"]["ok"] is True

    def test_prunes_segments_missing_from_db(self):
        """再解析で置換されて消えたセグメントは監査ファイルからも落とす。"""
        existing = self._doc([
            {"id": "seg_000", "chunk_index": 0, "text": "一。", "text_reading": "イチ。"},
            {"id": "seg_009", "chunk_index": 1, "text": "九。", "text_reading": "キュウ。"},
        ])
        new = self._doc([{"id": "seg_001", "chunk_index": 1,
                          "text": "二。", "text_reading": "ニ。"}])
        merged = merge_reading_script_doc(existing, new,
                                          valid_ids={"seg_000", "seg_001"})
        assert [s["id"] for s in merged["segments"]] == ["seg_000", "seg_001"]

    def test_pruned_segment_issues_are_not_kept(self):
        class _Issue:
            kind = "kanji_residue"
            segment_id = "seg_009"
            detail = "漢字が残存: 九"

        existing = reading_script_doc(
            [(1, [ReadingScriptSegment(id="seg_009", text="九。",
                                       text_reading="九。")])],
            book_id="book", judge_issues=[_Issue()])
        new = self._doc([{"id": "seg_000", "chunk_index": 0,
                          "text": "一。", "text_reading": "イチ。"}])
        merged = merge_reading_script_doc(existing, new, valid_ids={"seg_000"})
        assert merged["judge"] == {"ok": True, "issues": []}
        assert merged["residue"] == {}

    def test_tracks_writers_and_timestamps(self):
        existing = self._doc([{"id": "seg_000", "chunk_index": 0,
                               "text": "一。", "text_reading": "イチ。"}])
        existing["created_at"] = "2026-01-01T00:00:00+00:00"
        new = reading_script_doc(
            [], book_id="book", writer="llm", created_at="2026-01-02T00:00:00+00:00")
        merged = merge_reading_script_doc(existing, new)
        assert merged["writers"] == ["llm", "openjtalk"]
        assert merged["created_at"] == "2026-01-01T00:00:00+00:00"
        assert merged["updated_at"] == "2026-01-02T00:00:00+00:00"
        # 統合結果も validate_reading_script を通る
        assert validate_reading_script(merged) == []


class TestReadingScriptMerge:
    """部分再実行（--resume）で監査ファイルを痩せさせない。"""

    def _doc(self, segments, *, writer="openjtalk", issues=None, residue=None):
        return {
            "version": "1", "book_id": "sample", "writer": writer,
            "segments": segments, "created_at": "2026-01-01T00:00:00+00:00",
            "judge": {"ok": not (issues or []), "issues": issues or []},
            "residue": residue or {},
        }

    def _seg(self, sid, chunk, text, reading):
        return {"id": sid, "chunk_index": chunk, "speaker": "narrator",
                "text": text, "text_reading": reading}

    def test_untouched_segments_are_kept(self):
        existing = self._doc([
            self._seg("seg_000", 0, "一番目", "イチバンメ"),
            self._seg("seg_001", 0, "二番目", "ニバンメ"),
            self._seg("seg_002", 1, "三番目", "サンバンメ"),
        ])
        new = self._doc([self._seg("seg_002", 1, "三番目", "サンバンメ・改")])
        merged = merge_reading_script_doc(existing, new)
        ids = [s["id"] for s in merged["segments"]]
        assert ids == ["seg_000", "seg_001", "seg_002"]
        assert merged["segments"][-1]["text_reading"] == "サンバンメ・改"
        assert merged["created_at"] == "2026-01-01T00:00:00+00:00"
        assert merged["updated_at"] == new["created_at"]

    def test_replaced_segment_residue_and_issues_are_refreshed(self):
        existing = self._doc(
            [self._seg("seg_000", 0, "看板", "カンバン")],
            issues=[{"kind": "kanji_residue", "segment_id": "seg_000",
                     "detail": "漢字が残存: 看板"}],
            residue={"seg_000": ["板", "看"]})
        # 今回は seg_000 が正しくかな化された
        new = self._doc([self._seg("seg_000", 0, "看板", "カンバン")])
        merged = merge_reading_script_doc(existing, new)
        assert merged["residue"] == {}
        assert merged["judge"] == {"ok": True, "issues": []}

    def test_kept_segment_issues_survive(self):
        existing = self._doc(
            [self._seg("seg_000", 0, "過去", "カコ")],
            issues=[{"kind": "length_drift", "segment_id": "seg_000",
                     "detail": "短すぎる"}],
            residue={"seg_000": ["過"]})
        new = self._doc([self._seg("seg_005", 2, "新しい", "アタラシイ")])
        merged = merge_reading_script_doc(existing, new)
        assert merged["residue"] == {"seg_000": ["過"]}
        assert merged["judge"]["ok"] is False
        assert merged["judge"]["issues"][0]["segment_id"] == "seg_000"

    def test_writers_are_accumulated(self):
        existing = self._doc([self._seg("seg_000", 0, "あ", "ア")],
                             writer="llm")
        new = self._doc([self._seg("seg_001", 0, "い", "イ")],
                        writer="openjtalk")
        merged = merge_reading_script_doc(existing, new)
        assert merged["writers"] == ["llm", "openjtalk"]
        assert "# 台本家: llm,openjtalk" in render_reading_script_text(merged)

    def test_no_existing_doc_returns_new(self):
        new = self._doc([self._seg("seg_000", 0, "あ", "ア")])
        assert merge_reading_script_doc(None, new) is new
        assert merge_reading_script_doc({}, new) is new

    def test_sorted_by_chunk_then_id(self):
        existing = self._doc([self._seg("seg_009", 1, "あ", "ア")])
        new = self._doc([self._seg("seg_001", 0, "い", "イ")])
        merged = merge_reading_script_doc(existing, new)
        assert [s["id"] for s in merged["segments"]] == ["seg_001", "seg_009"]

    def test_valid_ids_drop_segments_removed_by_reanalysis(self):
        """再解析で置き換えられて消えたセグメントの記録は残さない（DB が真実源）。"""
        existing = self._doc(
            [self._seg("seg_000", 0, "古い", "フルイ"),
             self._seg("seg_005", 0, "残る", "ノコル")],
            issues=[{"kind": "length_drift", "segment_id": "seg_000",
                     "detail": "古い指摘"}],
            residue={"seg_000": ["古"]})
        new = self._doc([self._seg("seg_001", 0, "新しい", "アタラシイ")])
        merged = merge_reading_script_doc(
            existing, new, valid_ids={"seg_001", "seg_005"})
        assert [s["id"] for s in merged["segments"]] == ["seg_001", "seg_005"]
        assert merged["residue"] == {}
        assert merged["judge"] == {"ok": True, "issues": []}

    def test_valid_ids_none_keeps_everything(self):
        existing = self._doc([self._seg("seg_000", 0, "古い", "フルイ")])
        new = self._doc([self._seg("seg_001", 0, "新しい", "アタラシイ")])
        merged = merge_reading_script_doc(existing, new, valid_ids=None)
        assert [s["id"] for s in merged["segments"]] == ["seg_000", "seg_001"]


