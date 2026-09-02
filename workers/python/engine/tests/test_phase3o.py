"""Phase 3.5O - Scene Context tests (scene_context.py, 実装の検証)。"""
from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import VoiceProfile, VoiceState, Performance
from scene_context import SceneEvent, SceneReaction, intent_for


def _seg(text="そうなのか。", emotion="neutral", intensity=0.5):
    perf = Performance(voice="v0", mode="dialogue", emotion=emotion,
                       intensity=intensity, pace=1.0, pitch=0.0)
    return types.SimpleNamespace(text=text, emotion=emotion, intensity=intensity,
                                 performance=perf)


def test_revelation_delta_on_target():
    ev = SceneEvent(description="主人公がヤバい告白", category="revelation",
                    targets=["c1"], intensity=0.9)
    st = SceneReaction(ev).for_character("c1")
    assert st.tension >= 0.4 and st.excitement >= 0.3
    assert st.confidence == 0.0  # 0 - 0.25*0.9 -> clamp 0


def test_non_target_attenuated():
    ev = SceneEvent(description="告白", category="revelation",
                    targets=["c1"], intensity=0.9)
    target = SceneReaction(ev).for_character("c1").tension
    other = SceneReaction(ev).for_character("c2").tension
    assert 0.0 < other < target  # 減衰 x0.4


def test_battle_end_direction():
    ev = SceneEvent(description="敵、逃げたぞ", category="battle_end",
                    targets=["c1"], intensity=1.0)
    st = SceneReaction(ev).for_character("c1", base=VoiceState(tension=0.8))
    assert st.tension < 0.8      # 緊張が下がる
    assert st.fatigue >= 0.4     # 疲労が上がる
    assert st.excitement == 0.0  # 興奮が下がる -> clamp 0


def test_state_clamped():
    ev = SceneEvent(description="裏切り", category="betrayal",
                    targets=["c1"], intensity=1.0)
    st = SceneReaction(ev).for_character("c1", base=VoiceState(tension=0.9))
    assert 0.0 <= st.tension <= 1.0
    assert st.tension == 1.0     # 0.9 + 0.5 -> clamp 1.0


def test_intent_for_category():
    assert intent_for("revelation") == "awkward_silence"
    assert intent_for("battle_end") == "whispered_confession"
    assert intent_for("unknown_cat", "hesitant_denial") == "hesitant_denial"  # フォールバック


def test_plan_for_segment_with_scene_intent():
    from human_voice import plan_for_segment
    prof = VoiceProfile(voice_id="v0")
    seg = _seg("そうなのか。")
    p_emo, _, _ = plan_for_segment(seg, prof, VoiceState(), seed=42)
    p_scene, _, _ = plan_for_segment(seg, prof, VoiceState(), seed=42,
                                     intent="awkward_silence")
    # 同一 seed でも Scene Intent が違えば curve が変わる
    assert p_emo["intent"] != "awkward_silence"
    assert p_scene["intent"] == "awkward_silence"
    assert p_scene["speed"] != p_emo["speed"] or p_scene["pitch"] != p_emo["pitch"]
    # 決定論
    p_again, _, _ = plan_for_segment(seg, prof, VoiceState(), seed=42,
                                     intent="awkward_silence")
    assert p_again["speed"] == p_scene["speed"]