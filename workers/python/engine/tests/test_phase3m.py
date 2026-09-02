from __future__ import annotations
import sys
import types
import wave
import struct
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import VoiceProfile, VoiceState, Performance
from human_voice import plan_for_segment, seed_for, render_segment


def _write_silence(path, secs=0.3, rate=24000):
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(rate * secs)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 0) * n)


class FakeProvider:
    name = "fake"
    def __init__(self):
        self.calls = []
    def synthesize(self, text, perf, out_path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _write_silence(out_path, secs=0.2 + 0.05 * len(text))
        self.calls.append((text, perf.pace, perf.pitch, perf.style, perf.emotion, perf.intensity))


def _seg(text="え……でも……本当に？", emotion="anxious", intensity=0.6):
    perf = Performance(voice="v0", mode="dialogue", emotion=emotion,
                       intensity=intensity, pace=1.0, pitch=0.0)
    return types.SimpleNamespace(text=text, emotion=emotion, intensity=intensity,
                                 performance=perf)


def test_seed_for_deterministic():
    assert seed_for("seg_001") == seed_for("seg_001")
    assert seed_for("seg_001") != seed_for("seg_002")


def test_plan_for_segment_wire():
    prof = VoiceProfile(voice_id="v0")
    plan, segs, breaths = plan_for_segment(_seg(), prof, VoiceState(tension=0.5), seed=42)
    assert plan["intent"] == "hesitant_denial"
    assert len(segs) == 4
    assert len(plan["speed"]) == 2
    assert [s.type for s in segs] == ["vocalization", "speech", "pause", "speech"]


def test_render_segment_composes(tmp_path):
    import shutil
    if shutil.which("ffmpeg") is None:
        import pytest; pytest.skip("ffmpeg not available")
    out = tmp_path / "seg.wav"
    composed, plan = render_segment(_seg(), VoiceProfile(voice_id="v0"),
                                    VoiceState(tension=0.4), FakeProvider(), out, seed=42)
    assert out.exists() and out.stat().st_size > 0
    assert len(plan["speed"]) == 2


def test_render_segment_seed_reproducible(tmp_path):
    import shutil
    if shutil.which("ffmpeg") is None:
        import pytest; pytest.skip("ffmpeg not available")
    prof = VoiceProfile(voice_id="v0")
    a, pa = render_segment(_seg(), prof, VoiceState(tension=0.4), FakeProvider(), tmp_path / "a.wav", seed=42)
    b, pb = render_segment(_seg(), prof, VoiceState(tension=0.4), FakeProvider(), tmp_path / "b.wav", seed=42)
    assert pa["speed"] == pb["speed"] and pa["total_ms"] == pb["total_ms"]
