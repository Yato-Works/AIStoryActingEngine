from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qa import AutoReperformer, PerformanceEvaluator
from models import VoiceProfile


def test_reperform_returns_scored_plan():
    rep = AutoReperformer(seed=42)
    res = rep.reperform("realization", intent="realization", num_phrases=4, attempts=3)
    assert "best_score" in res
    assert 0.0 <= res["best_score"] <= 100.0
    assert len(res["speed"]) == 4


def test_reperform_deterministic():
    rep = AutoReperformer(seed=42)
    a = rep.reperform("happy", intent="whispered_confession", num_phrases=4, attempts=3)
    b = rep.reperform("happy", intent="whispered_confession", num_phrases=4, attempts=3)
    assert a["best_score"] == b["best_score"]
    assert a["speed"] == b["speed"]


def test_reperform_with_profile():
    rep = AutoReperformer(seed=7)
    prof = VoiceProfile(voice_id="v0", timing_habit=0.6, pause_tendency=0.5)
    res = rep.reperform("sad", intent="hesitant_denial", num_phrases=5,
                        profile=prof, attempts=2)
    assert res["best_score"] >= 0.0
