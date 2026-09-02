from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import VoiceProfile
from director import plan_prosody, apply_voice_state


def test_timing_habit_changes_total_ms():
    base = plan_prosody("happy", 0.5, num_phrases=4, seed=42)
    plain = apply_voice_state(base, VoiceProfile(voice_id="v0"))
    habit = apply_voice_state(base, VoiceProfile(voice_id="v0", timing_habit=1.0))
    assert plain["total_ms"] != habit["total_ms"]


def test_timing_habit_reproducible():
    base = plan_prosody("neutral", 0.3, intent="realization", num_phrases=4, seed=9)
    prof = VoiceProfile(voice_id="v0", timing_habit=0.8, pause_tendency=0.5)
    a = apply_voice_state(base, prof, seed=42)
    b = apply_voice_state(base, prof, seed=42)
    assert a == b
