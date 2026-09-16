"""Reading Judge（読み台本審査）のユニットテスト。LLM はモックで検証する。

LLM・TTS サーバ・ネットワーク一切不要。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

# engine ディレクトリを path に追加
ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from reading_judge import (
    ContextReadingJudge,
    OllamaReadingJudge,
    ReadingJudgeReport,
    judge_reading_chunk,
    judge_reading_segment,
)

# ============================================================================
# 決定論審査
# ============================================================================


class TestDeterministicJudge:
    def test_clean_kana_passes(self):
        issues = judge_reading_segment("千早と申します。", "ちはやともうします。",
                                       "seg_001")
        assert issues == []

    def test_kanji_residue_detected(self):
        issues = judge_reading_segment("千早と申します。", "千早ともうします。",
                                       "seg_001")
        assert len(issues) == 1
        assert issues[0].kind == "kanji_residue"
        assert "千" in issues[0].detail

    def test_length_drift_detected(self):
        # 省略・要約の疑い（0.9 未満）
        issues = judge_reading_segment(
            "千早は貼付の剥がれた看板の下で立ち尽くしていた。",
            "ちはや、はりつけ。", "seg_001")
        assert "length_drift" in {i.kind for i in issues}

    def test_natural_kana_expansion_passes(self):
        # かな化は通常 1.2〜2 倍に長くなる → 問題なし
        issues = judge_reading_segment("彼は歩いていた。",
                                       "かれはあるいていた。", "seg_001")
        assert issues == []

    def test_chunk_judge_collects_all(self):
        report = judge_reading_chunk([
            ("seg_001", "千早", "ちはや"),
            ("seg_002", "今日", "今日"),     # 残留
            ("seg_003", "千早は貼付の剥がれた看板の下で立ち尽くしていた。",
             "ちはや、はりつけ。"),          # 省略疑い
        ])
        assert sorted(i.kind for i in report.issues) == \
            ["kanji_residue", "length_drift"]
        assert not report.ok

    def test_facade_matches_function(self):
        report = ContextReadingJudge().judge([("seg_001", "千早", "ちはや")])
        assert report.ok


# ============================================================================
# LLM 審査（モック）
# ============================================================================


class TestOllamaReadingJudge:
    def test_ok_verdict_returns_no_issues(self):
        judge = OllamaReadingJudge()
        resp = {"response": '{"ok": true, "issues": []}'}
        with patch("httpx.post") as fake:
            fake.return_value.json.return_value = resp
            fake.return_value.raise_for_status = lambda: None
            issues = judge.check_meaning("千早と申します。",
                                         "ちはやともうします。", "seg_001")
        assert issues == []

    def test_drift_verdict_returns_issues(self):
        judge = OllamaReadingJudge()
        resp = {"response": json.dumps({
            "ok": False,
            "issues": ["「申します」の丁寧さが失われている"]}, ensure_ascii=False)}
        with patch("httpx.post") as fake:
            fake.return_value.json.return_value = resp
            fake.return_value.raise_for_status = lambda: None
            issues = judge.check_meaning("千早と申します。",
                                         "ちはやだよ。", "seg_001")
        assert len(issues) == 1
        assert issues[0].kind == "meaning_drift"

    def test_llm_failure_is_reported_not_swallowed(self):
        judge = OllamaReadingJudge()
        with patch("httpx.post", side_effect=RuntimeError("boom")):
            issues = judge.check_meaning("原文", "かな", "seg_001")
        assert len(issues) == 1
        assert "失敗" in issues[0].detail
