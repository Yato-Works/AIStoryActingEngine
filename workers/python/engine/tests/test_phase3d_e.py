from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from director import plan_prosody, timing_humanize, normalize_intent
from audio import plan_speech_segments, SpeechSegment, crossfade_concat


def test_plan_prosody_reproducible():
    a = plan_prosody("happy", 0.5, intent="realization", num_phrases=4, seed=42)
    b = plan_prosody("happy", 0.5, intent="realization", num_phrases=4, seed=42)
    assert a == b
    assert a["intent"] == "realization"
    assert len(a["speed"]) == 4
    assert set(a) >= {"speed", "pitch", "energy", "timing_ms", "total_ms"}


def test_plan_prosody_monotonic_timing():
    p = plan_prosody("sad", 0.3, intent="hesitant_denial", num_phrases=5, seed=7)
    assert len(p["speed"]) == 5
    assert p["timing_ms"][0] == 0.0
    assert p["timing_ms"] == sorted(p["timing_ms"])
    assert p["total_ms"] > 0


def test_realization_peaks_mid():
    p = plan_prosody("neutral", num_phrases=3, intent="realization", seed=1)
    assert p["energy"][1] == max(p["energy"])


def test_normalize_intent():
    assert normalize_intent("Hesitant Denial") == "hesitant_denial"
    assert normalize_intent(None) == "neutral"
    assert normalize_intent("zzz") == "neutral"


def test_timing_humanize_segments():
    th = timing_humanize("そうだったのか。でも、それなら俺たちはどうすればいい？",
                         intent="hesitant_denial", seed=42)
    assert len(th) == 3
    assert th[0]["text"] == "そうだったのか"
    assert "speed" in th[0]


def test_plan_speech_segments_vocalization():
    segs = plan_speech_segments("え……それは……違う", intent="hesitant_denial")
    types = [s.type for s in segs]
    assert "vocalization" in types
    assert "pause" in types
    assert "speech" in types
    assert segs[-1].text == "違う"


def test_speech_segment_to_dict():
    s = SpeechSegment(type="speech", text="hi")
    d = s.to_dict()
    assert d["type"] == "speech" and d["text"] == "hi"


def test_crossfade_concat(tmp_path):
    import shutil, subprocess
    if shutil.which("ffmpeg") is None:
        import pytest
        pytest.skip("ffmpeg not available")
    a = tmp_path / "a.wav"
    b = tmp_path / "b.wav"
    for f in (a, b):
        r = subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                            "anullsrc=channel_layout=mono", "-t", "0.3",
                            "-ar", "24000", "-ac", "1", str(f)],
                           capture_output=True)
        if r.returncode != 0:
            import pytest
            pytest.skip("lavfi not supported")
    out = tmp_path / "out.wav"
    crossfade_concat([a, b], out, crossfade_ms=40)
    assert out.exists() and out.stat().st_size > 0
