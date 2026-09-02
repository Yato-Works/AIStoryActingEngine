"""Phase 3.5Q - Scene Context Integration のテスト。

因果: Story -> SceneEvent -> VoiceState -> VoiceProfile -> Performance Plan -> HVE
を検証する（明示的 state_delta / State Decay / Scene Override / 永続化）。
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from models import Character, Performance, VoiceProfile, VoiceState
from scene_context import (SceneEvent, SceneReaction, STATE_KEYS,
                           decay_state, scene_events_from_analysis,
                           tone_energy_scale, tone_for_events)


def _ev(category="danger", targets=("c1",), intensity=1.0, **kw):
    return SceneEvent(description="テスト用イベント", category=category,
                      targets=list(targets), intensity=intensity, **kw)


# ---------------------------------------------------------------- VoiceState 拡張

def test_voice_state_has_eight_fields():
    st = VoiceState()
    for k in STATE_KEYS:
        assert getattr(st, k) == 0.0, k
    st2 = VoiceState(tension=0.5, fear=0.7)
    assert st2.fear == 0.7 and st2.tension == 0.5


# ---------------------------------------------------------------- カテゴリ別デルタ

def test_danger_raises_fear_and_tension():
    st = SceneReaction(_ev("danger", ["c1"], 0.8)).for_character("c1")
    assert st.fear >= 0.3 and st.tension >= 0.3
    assert st.confidence < 0.5


def test_victory_calms_and_confidence_up():
    st = SceneReaction(_ev("victory", ["c1"], 1.0)).for_character(
        "c1", base=VoiceState(tension=0.8))
    assert st.confidence >= 0.3 and st.tension < 0.8


def test_loss_raises_sadness():
    st = SceneReaction(_ev("loss", ["c1"], 0.9)).for_character("c1")
    assert st.sadness >= 0.35
    assert st.excitement < 0.1


def test_comedy_lowers_tension():
    st = SceneReaction(_ev("comedy", ["c1"], 1.0)).for_character(
        "c1", base=VoiceState(tension=0.6))
    assert st.tension < 0.6


# ---------------------------------------------------------------- 明示的 state_delta

def test_explicit_state_delta_overrides_category():
    """ユーザ指定の JSON 例: realization + state_delta がそのまま効く。"""
    ev = _ev("realization", ["alice"], 1.0,
             state_delta={"tension": -0.25, "confidence": 0.18, "excitement": 0.31})
    st = SceneReaction(ev).for_character("alice")
    assert st.tension == 0.0            # 0 - 0.25 -> clamp 0
    assert abs(st.confidence - 0.18) < 1e-9
    assert abs(st.excitement - 0.31) < 1e-9


def test_state_delta_scales_with_intensity():
    ev = _ev("neutral", ["c1"], 0.5, state_delta={"tension": 0.4})
    st = SceneReaction(ev).for_character("c1")
    assert abs(st.tension - 0.2) < 1e-9


def test_unknown_delta_key_is_ignored():
    st = SceneReaction(_ev("neutral", ["c1"], 1.0,
                           state_delta={"hoge": 0.9, "fear": 0.2})).for_character("c1")
    assert st.fear == 0.2
    for k in STATE_KEYS:
        assert 0.0 <= getattr(st, k) <= 1.0


def test_non_target_attenuated_with_new_fields():
    ev = _ev("danger", ["c1"], 1.0)
    target = SceneReaction(ev).for_character("c1").fear
    other = SceneReaction(ev).for_character("c2").fear
    assert 0.0 < other < target

# ---------------------------------------------------------------- State Decay

def test_decay_reduces_state():
    st = decay_state(VoiceState(tension=0.8, anger=0.6), steps=1)
    assert 0.0 < st.tension < 0.8
    assert 0.0 < st.anger < 0.6


def test_decay_repeated_returns_to_baseline():
    st = VoiceState(tension=1.0, anger=1.0)
    for _ in range(6):
        st = decay_state(st)
    assert st.tension < 0.05 and st.anger < 0.05


def test_decay_is_monotonic_and_deterministic():
    a = decay_state(VoiceState(tension=0.9), steps=2)
    b = decay_state(VoiceState(tension=0.9), steps=2)
    one = decay_state(VoiceState(tension=0.9))
    two = decay_state(decay_state(VoiceState(tension=0.9)))
    assert a == b
    assert two.tension < one.tension


# ---------------------------------------------------------------- Scene Tone

def test_tone_for_events():
    assert tone_for_events([_ev("comedy")]) == "comedy"
    assert tone_for_events([_ev("danger")]) == "neutral"
    assert tone_for_events([]) == "neutral"
    assert tone_energy_scale("comedy") < 1.0
    assert tone_energy_scale("neutral") == 1.0


def _seg(text="え？そうなの？", emotion="surprised", intensity=0.8):
    perf = Performance(voice="v0", mode="dialogue", emotion=emotion,
                       intensity=intensity, pace=1.0, pitch=0.0)
    return types.SimpleNamespace(text=text, emotion=emotion, intensity=intensity,
                                 performance=perf)


def test_comedy_tone_suppresses_energy():
    """Scene Override: ギャグ場面でも過剰演技（大声）にしない。"""
    from human_voice import plan_for_segment
    prof = VoiceProfile(voice_id="v0")
    base, _, _ = plan_for_segment(_seg(), prof, VoiceState(), seed=42)
    comedy, _, _ = plan_for_segment(_seg(), prof, VoiceState(), seed=42, tone="comedy")
    assert "tone" not in base and comedy["tone"] == "comedy"
    assert all(c <= b for c, b in zip(comedy["energy"], base["energy"]))
    # 決定論
    again, _, _ = plan_for_segment(_seg(), prof, VoiceState(), seed=42, tone="comedy")
    assert again["energy"] == comedy["energy"]


# ---------------------------------------------------------------- 解析結果の正規化

def test_scene_events_from_analysis_normalizes():
    analysis = {"scene_events": [
        {"category": "danger", "description": "崖から転落", "intensity": 2.0,
         "targets": ["c1", "ghost"]},
        {"category": "mystery", "intensity": "x", "targets": "not-a-list"},
        "not-a-dict",
        {"category": "comedy", "intensity": 0.4,
         "state_delta": {"tension": -0.5, "bogus": 1.0}},
    ]}
    events = scene_events_from_analysis(analysis, known_ids={"c1", "c2"},
                                        chunk_index=3)
    assert len(events) == 3
    e0, e1, e2 = events
    assert e0.category == "danger" and e0.intensity == 1.0   # clamp
    assert e0.targets == ["c1"]                              # 未知 id をフィルタ
    assert e0.chunk_index == 3
    assert e1.category == "neutral" and e1.intensity == 0.5  # 不明 category + 無効 intensity
    assert e2.category == "comedy" and e2.state_delta == {"tension": -0.5}
    assert "bogus" not in e2.state_delta


def test_scene_events_from_analysis_empty_shapes():
    assert scene_events_from_analysis(None) == []
    assert scene_events_from_analysis({}) == []
    assert scene_events_from_analysis({"scene_events": "nope"}) == []

# ---------------------------------------------------------------- パイプライン統合

def _make_memory(tmp_path):
    from memory import MemoryEngine
    return MemoryEngine(tmp_path / "story.db", "q_test", title="Q Test")


def _make_state(*cids):
    from models import StoryState
    st = StoryState()
    for cid in cids:
        st.characters[cid] = Character(id=cid, name=cid)
    return st


def test_memory_voice_state_roundtrip(tmp_path):
    from memory import MemoryEngine
    mem = _make_memory(tmp_path)
    try:
        assert mem.get_voice_state("c1") is None
        mem.save_voice_state("c1", VoiceState(tension=0.5, fear=0.3), 2)
        got = mem.get_voice_state("c1")
        assert got is not None and got.tension == 0.5 and got.fear == 0.3
        # 再構築（別インスタンス）しても読める＝resume でも状態が生きる
        mem.close()
        mem = MemoryEngine(tmp_path / "story.db", "q_test", title="Q Test")
        assert mem.get_voice_state("c1").tension == 0.5
        # 変化時のみイベントが流れる
        n0 = mem.count_events("VOICE_STATE_CHANGED")
        mem.save_voice_state("c1", mem.get_voice_state("c1"), 3)  # 変化なし
        assert mem.count_events("VOICE_STATE_CHANGED") == n0
        mem.save_voice_state("c1", VoiceState(tension=0.2, fear=0.3), 4)
        assert mem.count_events("VOICE_STATE_CHANGED") == n0 + 1
    finally:
        mem.close()


def test_apply_scene_events_full_causal_chain(tmp_path):
    """targets はフル効果、bystander は減衰、無関係キャラは decay。"""
    import main as engine
    mem = _make_memory(tmp_path)
    try:
        state = _make_state("alice", "bob", "carol")
        # carol は前チャンクで怒っていた（無関係チャンクで減衰する）
        mem.save_voice_state("carol", VoiceState(anger=0.6, tension=0.4), 0)
        n_vs = mem.count_events("VOICE_STATE_CHANGED")  # 事前準備分を基線に
        events = scene_events_from_analysis(
            {"scene_events": [{"category": "danger", "description": "敵襲",
                               "intensity": 1.0, "targets": ["alice"]}]},
            known_ids={"alice", "bob", "carol"}, chunk_index=1)
        engine._apply_scene_events(mem, state, events, 1)
        # targets: フル効果
        alice = mem.get_voice_state("alice")
        assert alice.fear == pytest.approx(0.45, abs=1e-6)
        assert alice.tension == pytest.approx(0.40, abs=1e-6)
        # bystander: x0.4 減衰で場の空気が伝播
        bob = mem.get_voice_state("bob")
        assert bob.fear == pytest.approx(0.18, abs=1e-6)
        # 無関係キャラ: decay x0.55
        carol = mem.get_voice_state("carol")
        assert carol.anger == pytest.approx(0.33, abs=1e-6)
        # メモリ上の state も更新されている（次の処理に反映）
        assert state.characters["alice"].voice_state.fear == alice.fear
        # Event Log にも記録されている（SSOT）
        assert mem.count_events("SCENE_EVENT") == 1
        assert mem.count_events("VOICE_STATE_CHANGED") == n_vs + 3
    finally:
        mem.close()


def test_apply_scene_events_no_events_decays_only(tmp_path):
    """イベントが無いチャンクでも減衰だけは走る（徐々に通常へ）。"""
    import main as engine
    mem = _make_memory(tmp_path)
    try:
        state = _make_state("alice")
        mem.save_voice_state("alice", VoiceState(tension=1.0), 0)
        engine._apply_scene_events(mem, state, [], 1)
        assert mem.get_voice_state("alice").tension == pytest.approx(0.55, abs=1e-6)
        assert mem.count_events("SCENE_EVENT") == 0
    finally:
        mem.close()


def test_scene_tone_persisted_per_chunk(tmp_path):
    mem = _make_memory(tmp_path)
    try:
        assert mem.scene_tone(5) == "neutral"
        mem.add_scene_event(5, "comedy", "転んで笑った", 0.6, ["c1"], "comedy")
        assert mem.scene_tone(5) == "comedy"
        assert mem.scene_tone(6) == "neutral"
        assert mem.count_events("SCENE_EVENT") == 1
    finally:
        mem.close()


def test_hve_profile_table_uses_persisted_voice_state(tmp_path):
    """3.5Q の永続化 VoiceState が HVE の profile テーブルまで届く。"""
    import main as engine
    mem = _make_memory(tmp_path)
    try:
        ch = Character(id="c1", name="太郎", gender="male",
                       voice=VoiceProfile(voice_id="voice_01", gender="male"))
        mem.upsert_character(ch, 0)
        mem.save_voice_profile(ch)
        mem.save_voice_state("c1", VoiceState(tension=0.7, fear=0.2), 1)
        table = engine._hve_profile_table(mem)
        prof, st = table["voice_01"]
        assert prof.voice_id == "voice_01"
        assert st.tension == pytest.approx(0.7) and st.fear == pytest.approx(0.2)
    finally:
        mem.close()


def test_director_uses_extended_states_for_prosody(tmp_path=None):
    """fear/anger/sadness が prosody に反映される（既存 4 状態と同じ経路）。"""
    from director import apply_voice_state, plan_prosody
    prof = VoiceProfile(voice_id="v0")
    plan = plan_prosody("angry", 0.9, num_phrases=3, seed=42)
    angry = apply_voice_state(plan, prof, VoiceState(anger=1.0), seed=42)
    sad = apply_voice_state(plan, prof, VoiceState(sadness=1.0), seed=42)
    calm = apply_voice_state(plan, prof, VoiceState(), seed=42)
    # 怒りは energy を上げ、悲しみは下げる
    assert max(angry["energy"]) > max(calm["energy"])
    assert max(sad["energy"]) < max(calm["energy"])
    # 悲しみは遅くなる
    assert max(sad["speed"]) < max(calm["speed"])
