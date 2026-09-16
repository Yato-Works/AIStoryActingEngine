"""Script Writer（台本家AI）のユニットテスト。

LLM サーバ・ネットワーク不要。Ollama はモックで検証する。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# engine ディレクトリを path に追加
ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from reading import ReadingDictionary
from script_writer import (
    DictionaryScriptWriter,
    OllamaScriptWriter,
    ScriptWriterResult,
)


def _ollama_response(segments: list[dict], readings: list[dict] | None = None):
    """Ollama /api/generate のレスポンスを模倣する。"""
    import json as _json
    body = _json.dumps({
        "segments": segments,
        "readings": readings or [],
    }, ensure_ascii=False)
    return {"response": body}


SEGMENTS = [
    {"id": "seg_001", "speaker": "narrator", "text": "夕暮れの街を、彼は歩いていた。"},
    {"id": "seg_002", "speaker": "chihaya", "text": "私は千早です。"},
]


class TestOllamaScriptWriter:
    def test_full_kana_conversion_and_readings(self):
        """LLM が全文かなと人名の読みを返すケース。"""
        writer = OllamaScriptWriter()
        llm_segments = [
            {"id": "seg_001", "text_reading": "ゆうぐれのまちを、かれはあるいていた。"},
            {"id": "seg_002", "text_reading": "わたしは千早です。"},
        ]
        llm_readings = [{"surface": "千早", "reading": "ちはや"}]
        with patch("script_writer._post_with_retry",
                   return_value=_ollama_response(llm_segments, llm_readings)):
            result = writer.write_script(SEGMENTS, ReadingDictionary())
        segs = {s.id: s for s in result.script.segments}
        assert segs["seg_001"].text_reading == "ゆうぐれのまちを、かれはあるいていた。"
        # 提案された readings が text_reading に即座に反映される（カタカナ注入）
        assert segs["seg_002"].text_reading == "わたしはチハヤです。"
        assert result.new_readings == {"千早": "ちはや"}
        assert result.uncovered == {}

    def test_dictionary_wins_over_llm(self):
        """辞書に登録済みの表記は LLM に渡る前にかな化される（ADR-0006 §3）。

        辞書の読み（例え珍しい読みでも）がそのまま LLM への入力になるため、
        「辞書が LLM より強い」ことが構造的に保証される。
        """
        writer = OllamaScriptWriter(model="qwen3:4b")
        captured = {}

        def fake_post(url, payload, timeout, retries=2):
            captured["prompt"] = payload["prompt"]
            # LLM は入力に含まれる辞書読みをそのまま保持して返す
            llm_segments = [
                {"id": "seg_001",
                 "text_reading": "ゆうぐれのまちを、かれはあるいていた。"},
                {"id": "seg_002", "text_reading": "わたしはせんそうです。"},
            ]
            return _ollama_response(llm_segments)

        with patch("script_writer._post_with_retry", side_effect=fake_post):
            result = writer.write_script(
                SEGMENTS, ReadingDictionary({"千早": "せんそう"}))
        # プロンプト時点で辞書読みが適用されている（「私」は辞書に無いため漢字のまま）
        # 読みはカタカナ注入（後段の G2P 再解析で読みが壊れないように）
        assert "私はセンソウです。" in captured["prompt"]
        segs = {s.id: s for s in result.script.segments}
        # LLM ライター経路は G2P を通さないため、LLM が返した表記がそのまま残る
        # （このモックはひらがなで返している）。
        assert segs["seg_002"].text_reading == "わたしはせんそうです。"
        # 原文は漢字のまま保持される
        assert segs["seg_002"].text == "私は千早です。"

    def test_missing_segment_id_falls_back_to_dictionary(self):
        """LLM が id を欠落しても、辞書適用済みテキストでセグメントが失われない。"""
        writer = OllamaScriptWriter()
        llm_segments = [{"id": "seg_001",
                         "text_reading": "ゆうぐれのまちを、かれはあるいていた。"}]
        with patch("script_writer._post_with_retry",
                   return_value=_ollama_response(llm_segments)):
            result = writer.write_script(
                SEGMENTS, ReadingDictionary({"千早": "ちはや"}))
        segs = {s.id: s for s in result.script.segments}
        # フォールバックは辞書適用のみ（「私」は辞書に無いので漢字が残る）
        assert segs["seg_002"].text_reading == "私はチハヤです。"
        assert result.uncovered == {"seg_002": ["私"]}

    def test_ollama_payload_shape(self):
        """Ollama への payload が analyzer と同じ規約（format 強制等）か。"""
        writer = OllamaScriptWriter(model="qwen3:4b")
        captured = {}

        def fake_post(url, payload, timeout, retries=2):
            captured["url"] = url
            captured["payload"] = payload
            return _ollama_response(
                [{"id": s["id"], "text_reading": s["text"]} for s in SEGMENTS])

        with patch("script_writer._post_with_retry", side_effect=fake_post):
            writer.write_script(SEGMENTS, ReadingDictionary(), chunk_index=2)
        assert captured["url"] == "http://localhost:11434/api/generate"
        assert captured["payload"]["model"] == "qwen3:4b"
        assert captured["payload"]["stream"] is False
        assert "format" in captured["payload"]
        assert "チャンク 3" in captured["payload"]["prompt"]
