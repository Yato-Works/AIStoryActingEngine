"""Phase 3.5N - Performance Judge tests (llm_judge.py, 実装の検証)。"""
from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import VoiceProfile, VoiceState, Performance
from llm_judge import (HeuristicJudge, JudgeReport, diagnose_to_tweak,
                       apply_tweak)


def _seg(text="そうなのか。", emotion="neutral", intensity=0.5):
    perf = Performance(voice="v0", mode="dialogue", emotion=emotion,
                       intensity=intensity, pace=1.0, pitch=0.0)
    return types.SimpleNamespace(text=text, emotion=emotion, intensity=intensity,
                                 performance=perf)


def _flat_plan():
    return {"speed": [1.0, 1.0], "pitch": [0.0, 0.0], "energy": [0.9, 0.9],
            "timing_ms": [0.0, 1200.0], "intent": "neutral"}


def test_judge_report_schema():
    r = HeuristicJudge().evaluate(_flat_plan(), state=VoiceState(fatigue=0.9))
    assert isinstance(r, JudgeReport)
    for f in ("human_ness", "naturalness", "character_fit", "emotion_fit",
              "listenability", "ai_ness", "confidence"):
        assert 0.0 <= getattr(r, f) <= 1.0, f
    assert isinstance(r.diagnoses, list) and r.diagnoses


def test_judge_detects_energy_for_fatigue():
    r = HeuristicJudge().evaluate(_flat_plan(), state=VoiceState(fatigue=0.9))
    assert "energy_too_high_for_fatigue" in r.diagnoses
    assert r.emotion_fit < 1.0


def test_judge_deterministic():
    a = HeuristicJudge().evaluate(_flat_plan(), state=VoiceState(fatigue=0.9))
    b = HeuristicJudge().evaluate(_flat_plan(), state=VoiceState(fatigue=0.9))
    assert a == b


def test_diagnose_to_tweak_and_apply():
    t = diagnose_to_tweak(["energy_too_high_for_fatigue", "pitch_flat"])
    assert t["energy_scale"] < 1.0 and t["extra_breaths"] == 1
    assert "pitch_variation_boost" in t
    plan = _flat_plan()
    new = apply_tweak(plan, t, seed=7)
    assert new["energy"][0] < plan["energy"][0]   # energy が下がる
    assert plan == _flat_plan()                   # 元 plan は非破壊
    # 決定論
    assert apply_tweak(plan, t, seed=7) == new
    assert diagnose_to_tweak(["ok"]) == {}


def test_render_segment_with_judge_reperforms(tmp_path):
    import shutil
    if shutil.which("ffmpeg") is None:
        import pytest; pytest.skip("ffmpeg not available")

    from human_voice import render_segment

    class StrictJudge:
        """human_ness 0.5 + 実 diagnose を必ず返す stub（LLM 差し替え interface 検証）。"""
        def evaluate(self, plan, state=None, intent=None, emotion=None):
            return JudgeReport(human_ness=0.5, diagnoses=["energy_too_high_for_fatigue"],
                               confidence=0.9)

    class FakeProvider:
        name = "fake"
        def synthesize(self, text, perf, out_path):
            import wave, struct
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(out_path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(struct.pack("<h", 0) * 4800)  # 0.2s silence

    # judge なしベースライン（judge なし -> human_voice 内の acoustic QA が発火しない閾値）
    out_a = tmp_path / "a.wav"
    _, plan_base = render_segment(_seg(), VoiceProfile(voice_id="v0"), VoiceState(),
                                  FakeProvider(), out_a, seed=42,
                                  qa_threshold=0.0, attempts=0)
    assert "judge" not in plan_base

    # judge あり -> diagnose による tweak が plan に反映される
    out_b = tmp_path / "b.wav"
    _, plan_j = render_segment(_seg(), VoiceProfile(voice_id="v0"), VoiceState(),
                               FakeProvider(), out_b, seed=42,
                               qa_threshold=0.0, attempts=2,
                               judge=StrictJudge(), judge_threshold=0.7)
    assert plan_j["judge"]["human_ness"] == 0.5
    assert plan_j.get("tweaked") is True
    # energy が tweak で下がっている
    assert all(j <= b for j, b in zip(plan_j["energy"], plan_base["energy"]))