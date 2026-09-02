from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from director import plan_prosody
from qa import PerformanceEvaluator


def _flat_plan(n=4):
    return {"speed":[1.0]*n, "pitch":[0.0]*n, "energy":[0.7]*n,
            "timing_ms":[0.0, 900.0, 1800.0, 2700.0], "total_ms": 3600.0}


def test_evaluate_plan_keys_and_range():
    q = PerformanceEvaluator()
    p = plan_prosody("realization", 0.4, num_phrases=4, seed=42)
    sc = q.evaluate_plan(p)
    for k in ["HumanLikenessScore","ProsodyScore","TimingScore","PauseScore",
              "EnergyScore","PitchVariationScore","ContinuityScore"]:
        assert k in sc
        assert 0.0 <= sc[k] <= 100.0


def test_evaluate_plan_deterministic():
    q = PerformanceEvaluator()
    p = plan_prosody("happy", 0.5, num_phrases=4, seed=42)
    assert q.evaluate_plan(p) == q.evaluate_plan(p)


def test_varied_plan_scores_higher_prosody_than_flat():
    q = PerformanceEvaluator()
    varied = plan_prosody("realization", 0.5, num_phrases=4, seed=42)
    sc_v = q.evaluate_plan(varied)["ProsodyScore"]
    sc_f = q.evaluate_plan(_flat_plan())["ProsodyScore"]
    assert sc_v > sc_f


def test_evaluate_audio_guarded(tmp_path):
    import shutil, subprocess
    if shutil.which("ffmpeg") is None:
        import pytest; pytest.skip("ffmpeg not available")
    wav = tmp_path / "t.wav"
    r = subprocess.run(["ffmpeg","-y","-f","lavfi","-i",
        "aevalsrc=sin(2*PI*440*t):duration=0.3","-ar","24000","-ac","1",str(wav)],
        capture_output=True)
    if r.returncode != 0:
        import pytest; pytest.skip("lavfi not supported")
    sc = PerformanceEvaluator().evaluate_audio(wav)
    assert "HumanLikenessScore" in sc
    assert 0.0 <= sc["HumanLikenessScore"] <= 100.0
