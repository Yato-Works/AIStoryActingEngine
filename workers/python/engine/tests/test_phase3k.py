from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import VoiceProfile, VoiceState
from director import plan_prosody, apply_voice_state
from audio import plan_speech_segments, SpeechSegment
from sbv2_adapter import (Sbv2PerformanceSynthesizer, segment_sbv2_params,
                          intent_to_emotion, intent_to_style)


class FakeProvider:
    name = "fake"
    def __init__(self):
        self.calls = []
    def synthesize(self, text, perf, out_path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"FAKE" + text.encode("utf-8"))
        self.calls.append((text, perf.pace, perf.pitch, perf.volume, perf.style, perf.emotion))


def test_segment_params_from_curve():
    plan = apply_voice_state(
        plan_prosody("happy", 0.5, intent="realization", num_phrases=4, seed=42),
        VoiceProfile(voice_id="v0"), VoiceState(), seed=42)
    prof = VoiceProfile(voice_id="v0")
    for i in range(4):
        params = segment_sbv2_params(i, plan, prof)
        expected = round(max(0.5, min(2.0, (1.0 / max(0.1, plan["speed"][i])) / 1.0)), 3)
        assert params["length"] == expected
        assert -1.0 <= params["f0_adjust"] <= 1.0


def test_intent_mapping():
    assert intent_to_emotion("hesitant denial") == "anxious"
    assert intent_to_style("suppressed_anger") == "Angry"
    assert intent_to_emotion(None) == "neutral"


def test_synthesize_segments_uses_curve_and_intent(tmp_path):
    plan = apply_voice_state(
        plan_prosody("anxious", 0.5, intent="hesitant_denial", num_phrases=3, seed=7),
        VoiceProfile(voice_id="v0", base_pace=0.96), VoiceState(), seed=7)
    prof = VoiceProfile(voice_id="v0", base_pace=0.96)
    segs = plan_speech_segments("え……でも……本当に？", intent="hesitant_denial")
    prov = FakeProvider()
    syn = Sbv2PerformanceSynthesizer(provider=prov)
    wavs = syn.synthesize_segments(segs, plan, prof, tmp_path)
    assert len(wavs) == 3
    assert prov.calls[0][0] == "え"
    assert prov.calls[1][0] == "でも"
    assert prov.calls[2][0] == "本当に？"
    assert all(w.exists() for w in wavs)


def test_synthesize_segments_skips_pause(tmp_path):
    plan = apply_voice_state(
        plan_prosody("neutral", 0.3, intent="awkward_silence", num_phrases=4, seed=5),
        VoiceProfile(voice_id="v0"), VoiceState(), seed=5)
    segs = [SpeechSegment(type="speech", text="hi"),
            SpeechSegment(type="pause", kind="hesitation", duration_ms=320),
            SpeechSegment(type="speech", text="bye")]
    prov = FakeProvider()
    wavs = Sbv2PerformanceSynthesizer(provider=prov).synthesize_segments(segs, plan, VoiceProfile(voice_id="v0"), tmp_path)
    assert len(wavs) == 2
    assert [c[0] for c in prov.calls] == ["hi", "bye"]


def test_vocalization_uses_habit_intent_style(tmp_path):
    plan = apply_voice_state(plan_prosody("sad", 0.4, num_phrases=2, seed=11),
                             VoiceProfile(voice_id="v0"), VoiceState(), seed=11)
    segs = [SpeechSegment(type="vocalization", text="え", strength=0.5),
            SpeechSegment(type="speech", text="あ")]
    prov = FakeProvider()
    Sbv2PerformanceSynthesizer(provider=prov).synthesize_segments(segs, plan, VoiceProfile(voice_id="v0"), tmp_path)
    assert len(prov.calls) == 2
    assert prov.calls[0][0] == "え"
