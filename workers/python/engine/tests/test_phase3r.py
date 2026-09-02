"""Phase 3.5R - Performance Judge のテスト。

「音が綺麗か」ではなく「演技として正しいか」を審査する:
  ContextJudge (決定論) / OllamaJudge (実LLM + fallback) / KEEP / RE-PERFORM Decision
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from models import VoiceProfile, VoiceState
from llm_judge import (ContextJudge, HeuristicJudge, JudgeReport, OllamaJudge,
                       evaluate_judge)


def _plan(energy=1.0, speed=1.0, intent="neutral"):
    return {"intent": intent, "speed": [speed, speed], "pitch": [0.0, 0.0],
            "energy": [energy, energy], "timing_ms": [0.0, 900.0],
            "total_ms": 1800.0}


# ---------------------------------------------------------------- Report 拡張

def test_judge_report_has_acting_axes():
    r = JudgeReport()
    for f in ("character_consistency", "scene_consistency", "continuity",
              "acoustic_quality"):
        assert 0.0 <= getattr(r, f) <= 1.0, f


def test_heuristic_judge_neutral_on_acting_axes():
    """3.5N 互換: HeuristicJudge 単体は演技正当性軸を判定しない（中立 1.0）。"""
    r = HeuristicJudge().evaluate(_plan())
    assert r.character_consistency == 1.0 and r.continuity == 1.0


# ---------------------------------------------------------------- character_consistency

def test_sad_state_with_loud_energy_is_violation():
    """直前のイベントで sadness 0.82 なのに energy 0.97 なら演技 0 点。"""
    j = ContextJudge()
    diag = []
    cc = j.character_consistency(_plan(energy=1.2, speed=1.1),
                                 VoiceState(sadness=0.82), diag)
    assert cc < 0.5
    assert "energy_too_high_for_sadness" in diag
    assert "too_fast_for_sadness" in diag


def test_consistent_acting_is_full_score():
    j = ContextJudge()
    diag = []
    cc = j.character_consistency(_plan(energy=0.4, speed=0.85),
                                 VoiceState(sadness=0.82), diag)
    assert cc == 1.0 and diag == []


def test_anger_needs_energy():
    j = ContextJudge()
    diag = []
    cc = j.character_consistency(_plan(energy=0.3), VoiceState(anger=0.8), diag)
    assert "energy_too_low_for_anger" in diag and cc < 1.0


# ---------------------------------------------------------------- scene_consistency

def test_comedy_tone_suppresses_loud_energy():
    j = ContextJudge()
    diag = []
    sc = j.scene_consistency(_plan(energy=1.2), VoiceState(), "comedy", diag)
    assert "energy_too_high_for_comedy_tone" in diag and sc < 1.0


def test_high_tension_needs_some_energy():
    j = ContextJudge()
    diag = []
    sc = j.scene_consistency(_plan(energy=0.25), VoiceState(tension=0.8),
                             None, diag)
    assert "energy_too_low_for_tension" in diag and sc < 1.0


# ---------------------------------------------------------------- continuity

def test_abrupt_emotion_shift_penalized():
    j = ContextJudge()
    diag = []
    ct = j.continuity(_plan(), "happy", "angry", 0.3, diag)
    assert "abrupt_emotion_shift" in diag and ct < 1.0


def test_strong_intensity_justifies_jump():
    j = ContextJudge()
    diag = []
    ct = j.continuity(_plan(), "happy", "angry", 0.9, diag)
    assert diag == [] and ct == 1.0


def test_no_prev_segment_is_neutral():
    j = ContextJudge()
    diag = []
    assert j.continuity(_plan(), "happy", None, 0.3, diag) == 1.0


# ---------------------------------------------------------------- acoustic_quality

def test_clipping_and_silence_penalized():
    j = ContextJudge()
    diag = []
    aq = j.acoustic_quality({"clipping": True, "silence_ratio": 0.9}, diag)
    assert "clipping_detected" in diag and "too_much_silence" in diag
    assert aq < 0.5
    assert j.acoustic_quality(None, []) == 1.0


# ---------------------------------------------------------------- 統合スコア

def test_violating_plan_scores_lower_overall():
    """音質が同じでも、演技違反 plan の human_ness は下がる（演技として正しいか）。"""
    j = ContextJudge()
    bad = j.evaluate(_plan(energy=1.2, speed=1.1),
                     state=VoiceState(sadness=0.82), emotion="sad",
                     intent="whispered_confession", tone="neutral")
    good = j.evaluate(_plan(energy=0.4, speed=0.85),
                      state=VoiceState(sadness=0.82), emotion="sad",
                      intent="whispered_confession", tone="neutral")
    assert bad.character_consistency < good.character_consistency
    assert bad.human_ness < good.human_ness
    assert bad.human_ness < 0.7  # acoustic が完璧でも演技違反で RE-PERFORM 圏


# ---------------------------------------------------------------- evaluate_judge

def test_evaluate_judge_filters_kwargs_for_old_signature():
    """3.5N 時代の Judge（旧シグネチャ）にも追加 context で壊れない。"""
    class OldJudge:
        def evaluate(self, plan, state=None, intent=None, emotion=None):
            return JudgeReport(human_ness=0.5, diagnoses=["ok"], confidence=0.9)

    r = evaluate_judge(OldJudge(), _plan(), state=VoiceState(),
                       intent="neutral", emotion="sad", tone="comedy",
                       prev_emotion="angry", audio_metrics={"clipping": True})
    assert r.human_ness == 0.5


def test_evaluate_judge_passes_all_for_full_signature():
    r = evaluate_judge(ContextJudge(), _plan(), state=VoiceState(sadness=0.9),
                       intent="neutral", emotion="sad", tone="comedy",
                       prev_emotion="angry", audio_metrics={"clipping": True})
    assert r.character_consistency < 1.0


# ---------------------------------------------------------------- OllamaJudge

def test_ollama_judge_parses_llm_scores(monkeypatch):
    import analyzer

    def fake_post(url, payload, timeout, retries=2):
        assert "/api/generate" in url
        # プロンプトに全コンテキストが乗っていること（演技監督への引き渡し）
        assert "sadness=0.82" in payload["prompt"]
        return {"response": json.dumps({
            "naturalness": 0.9, "character_consistency": 0.4,
            "scene_consistency": 0.8, "continuity": 0.7,
            "acoustic_quality": 0.95, "diagnoses": ["energy_too_high_for_sadness"]})}

    monkeypatch.setattr(analyzer, "_post_with_retry", fake_post)
    r = OllamaJudge().evaluate(_plan(energy=1.2), state=VoiceState(sadness=0.82),
                               intent="neutral", emotion="sad")
    assert r.character_consistency == 0.4
    assert "energy_too_high_for_sadness" in r.diagnoses
    assert r.confidence == 0.6


def test_ollama_judge_falls_back_to_context_judge(monkeypatch):
    import analyzer

    def broken_post(url, payload, timeout, retries=2):
        raise RuntimeError("Ollama 未起動")

    monkeypatch.setattr(analyzer, "_post_with_retry", broken_post)
    r = OllamaJudge().evaluate(_plan(energy=1.2), state=VoiceState(sadness=0.82),
                               intent="neutral", emotion="sad", tone=None)
    assert "judge_llm_fallback" in r.diagnoses
    # fallback は ContextJudge なので演技違反を検出できている
    assert r.character_consistency < 1.0
    assert r.confidence <= 0.5


# ---------------------------------------------------------------- Decision 統合

def _seg(text="大丈夫だよ", emotion="sad", intensity=0.5):
    from models import Performance
    import types
    perf = Performance(voice="v0", mode="dialogue", emotion=emotion,
                       intensity=intensity, pace=1.0, pitch=0.0)
    return types.SimpleNamespace(text=text, emotion=emotion, intensity=intensity,
                                 performance=perf)


class LoudProvider:
    """音響的には無害な wav を返す Fake provider。"""

    name = "fake"

    @staticmethod
    def synthesize(text, perf, out_path):
        import struct
        import wave
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(struct.pack("<h", 0) * 4800)


def test_render_segment_judge_decision(tmp_path):
    """judge あり: plan に judge スコアが載り、retry ファイルが残らない。"""
    import shutil
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not available")
    from human_voice import render_segment
    out = tmp_path / "seg.wav"
    _, plan = render_segment(
        _seg(), VoiceProfile(voice_id="v0"), VoiceState(sadness=0.82),
        LoudProvider(), out, seed=42, qa_threshold=0.0, attempts=2,
        judge=ContextJudge(), judge_threshold=0.99)  # 強制的に RE-PERFORM 判定
    assert out.exists() and out.stat().st_size > 0
    assert "judge" in plan
    jr = plan["judge"]
    for f in ("human_ness", "character_consistency", "scene_consistency",
              "continuity", "acoustic_quality"):
        assert 0.0 <= jr[f] <= 1.0, f
    assert not (tmp_path / "seg.retry.wav").exists()  # 敗者ファイルは消えている


def test_render_segment_keep_decision_metadata(tmp_path):
    """RE-PERFORM が悪化したら元の演技を KEEP し、decision=keep を記録する。"""
    import shutil
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not available")
    from human_voice import render_segment

    class DegradingJudge:
        """1 回目 0.6（RE-PERFORM 判定）、以降 0.3（悪化）-> 必ず KEEP になる。"""
        def __init__(self):
            self.calls = 0

        def evaluate(self, plan, state=None, intent=None, emotion=None):
            self.calls += 1
            return JudgeReport(human_ness=0.6 if self.calls == 1 else 0.3,
                               diagnoses=["ok"], confidence=0.9)

    out = tmp_path / "seg.wav"
    judge = DegradingJudge()
    _, plan = render_segment(_seg(), VoiceProfile(voice_id="v0"), VoiceState(),
                             LoudProvider(), out, seed=42,
                             qa_threshold=0.0, attempts=2,
                             judge=judge, judge_threshold=0.7)
    assert out.exists()
    assert judge.calls == 2  # 初回 + 再演技の審査
    assert plan["judge"]["decision"] == "keep"
    assert plan["judge"]["human_ness"] == 0.6  # 悪い方ではなく元の演技を採用
