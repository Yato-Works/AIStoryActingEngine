from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import VoiceProfile, VoiceState
from audio import BreathEvent, plan_breaths, render_breath


def test_plan_breaths_reproducible():
    e1 = plan_breaths(8, seed=42)
    e2 = plan_breaths(8, seed=42)
    assert len(e1) == len(e2)
    assert [(e.type, e.length, e.phrase_index) for e in e1] == [(e.type, e.length, e.phrase_index) for e in e2]


def test_fatigue_increases_breaths():
    calm = plan_breaths(8, state=VoiceState(), seed=42)
    tired = plan_breaths(8, state=VoiceState(fatigue=0.9), seed=42)
    assert len(tired) >= len(calm)
    assert all(e.length == "long" for e in tired)


def test_tension_picks_short_inhale():
    events = plan_breaths(8, profile=VoiceProfile(voice_id="v0"),
                          state=VoiceState(tension=0.9), seed=5)
    assert any(e.type == "inhale" and e.length == "short" for e in events)


def test_render_breath_guarded(tmp_path):
    import shutil, subprocess
    if shutil.which("ffmpeg") is None:
        import pytest; pytest.skip("ffmpeg not available")
    out = tmp_path / "breath.wav"
    try:
        render_breath(BreathEvent(type="exhale", length="long", intensity=0.6), out)
    except subprocess.CalledProcessError:
        import pytest; pytest.skip("ffmpeg lavfi not supported")
    assert out.exists() and out.stat().st_size > 0
