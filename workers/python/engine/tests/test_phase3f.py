from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import VoiceProfile, VoiceState, Character
from director import plan_prosody, apply_voice_state, voice_vocalization


def test_voice_profile_new_fields_defaults():
    vp = VoiceProfile(voice_id="v0")
    assert vp.base_energy == 0.8
    assert vp.habits == {}
    assert vp.sentence_end_drop == 0.0
    assert vp.emotional_reactivity == 0.5


def test_voice_state_defaults():
    st = VoiceState()
    assert (st.tension, st.fatigue, st.confidence, st.excitement) == (0.0,)*4


def test_character_has_voice_state():
    c = Character(id="c", name="A", voice_state=VoiceState(tension=0.5))
    assert c.voice_state.tension == 0.5


def test_apply_voice_state_tension_raises_pitch_lowers_speed():
    base = plan_prosody("angry", 0.6, intent="suppressed_anger", num_phrases=4, seed=42)
    prof = VoiceProfile(voice_id="v0")
    relaxed = apply_voice_state(base, prof, VoiceState())
    tense = apply_voice_state(base, prof, VoiceState(tension=1.0))
    assert sum(tense["pitch"]) > sum(relaxed["pitch"])
    assert sum(tense["speed"]) < sum(relaxed["speed"])


def test_apply_voice_state_excited_raises_energy():
    base = plan_prosody("neutral", 0.3, num_phrases=4, seed=3)
    prof = VoiceProfile(voice_id="v0")
    calm = apply_voice_state(base, prof, VoiceState())
    excited = apply_voice_state(base, prof, VoiceState(excitement=1.0))
    assert sum(excited["energy"]) > sum(calm["energy"])


def test_apply_voice_state_reproducible():
    base = plan_prosody("sad", 0.5, intent="hesitant_denial", num_phrases=4, seed=9)
    prof = VoiceProfile(voice_id="v0", pause_tendency=0.7, hesitation=0.6)
    a = apply_voice_state(base, prof, VoiceState(tension=0.5))
    b = apply_voice_state(base, prof, VoiceState(tension=0.5))
    assert a == b


def test_voice_vocalization_habit():
    prof = VoiceProfile(voice_id="v0", habits={"thinking":"n~","disbelief":"no way","surprise":"eh?"})
    assert voice_vocalization(prof, "hesitant_denial") == "no way"
    assert voice_vocalization(prof, "awkward_silence") == "n~"
    assert voice_vocalization(prof, "realization") == "n~"
