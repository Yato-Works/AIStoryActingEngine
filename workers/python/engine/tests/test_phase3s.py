"""Phase 3.5S/U - 状態別 State Decay (transient/persistent) + A/B Listening tool。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from models import Character, DirectedSegment, Performance, VoiceProfile, VoiceState
from scene_context import (DECAY_RATES, PERSISTENT_STATES, STATE_KEYS,
                           TRANSIENT_STATES, decay_state)


# ------------------------------------------------- 3.5S: transient / persistent

def test_state_sets_partition():
    assert TRANSIENT_STATES | PERSISTENT_STATES == set(STATE_KEYS)
    assert not (TRANSIENT_STATES & PERSISTENT_STATES)
    # ユーザ設計: 怒り/緊張=transient, 悲しみ/自信=persistent 寄り
    assert "anger" in TRANSIENT_STATES and "tension" in TRANSIENT_STATES
    assert "sadness" in PERSISTENT_STATES and "confidence" in PERSISTENT_STATES


def test_sadness_decays_slower_than_anger():
    st = decay_state(VoiceState(anger=0.6, sadness=0.6))
    assert st.anger == pytest.approx(0.6 * DECAY_RATES["anger"], abs=1e-6)
    assert st.sadness > st.anger  # 喪失の悲しみは怒りより長く残る


def test_embarrassment_fades_fastest():
    st = decay_state(VoiceState(embarrassment=0.9, sadness=0.9))
    assert st.embarrassment < st.sadness


def test_explicit_factor_keeps_uniform_behavior():
    """3.5Q 互換: factor を明示したら全状態が一様に減衰する。"""
    st = decay_state(VoiceState(tension=1.0, sadness=1.0), factor=0.55)
    assert st.tension == pytest.approx(0.55, abs=1e-6)
    assert st.sadness == pytest.approx(0.55, abs=1e-6)


def test_default_decay_is_deterministic_and_monotonic():
    a = decay_state(VoiceState(sadness=1.0), steps=2)
    b = decay_state(VoiceState(sadness=1.0), steps=2)
    assert a == b
    one = decay_state(VoiceState(sadness=1.0))
    assert decay_state(VoiceState(sadness=1.0), steps=4).sadness < one.sadness < 1.0


# ------------------------------------------------- 3.5U: A/B Listening tool

class FakeProvider:
    name = "fake"

    @staticmethod
    def synthesize(text, perf, out_path):
        import struct
        import wave
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(struct.pack("<h", 0) * 4800)


def _make_memory(tmp_path, n=2):
    from memory import MemoryEngine
    mem = MemoryEngine(tmp_path / "story.db", "ab_test", title="AB Test")
    ch = Character(id="c1", name="太郎", gender="male",
                   voice=VoiceProfile(voice_id="voice_01", gender="male"))
    mem.upsert_character(ch, 0)
    mem.save_voice_profile(ch)
    for i in range(1, n + 1):
        seg = DirectedSegment(
            id=f"seg_{i:03d}", type="dialogue", speaker="c1", text="え？そうなの？",
            emotion="surprised", intensity=0.6, chapter=1, chunk_index=0,
            performance=Performance(voice="voice_01", mode="dialogue",
                                    emotion="surprised", intensity=0.6,
                                    pace=1.0, pitch=0.0))
        mem.save_segment(seg)
        mem.set_audio(seg.id, f"/dummy/{seg.id}.wav")  # 音声済み扱い
    return mem


@pytest.fixture()
def ab_env(tmp_path, monkeypatch):
    import ab_export
    if pytest.importorskip("shutil").which("ffmpeg") is None:
        pytest.skip("ffmpeg not available")
    monkeypatch.setattr(ab_export, "get_provider", lambda name: FakeProvider())
    return ab_export


def test_ab_session_builds_blind_variants(ab_env, tmp_path):
    mem = _make_memory(tmp_path)
    try:
        out = tmp_path / "session" / "ab_test"
        key = ab_env.build_ab_session(mem, out, limit=2, session_seed=7)
    finally:
        mem.close()
    assert set(key) == {"seg_001", "seg_002"}
    for sid, entry in key.items():
        assert entry["variant_1"] in ("A", "B")
        assert entry["variant_2"] != entry["variant_1"]
        for v in ("variant_1", "variant_2"):
            assert (out / f"{sid}__{v}.wav").exists()
    # 盲検: ファイル名に A/B の種別が出ない
    assert not list(out.glob("*_A.wav")) and not list(out.glob("*_B.wav"))
    # 付属物
    ak = json.loads((out / "answer_key.json").read_text(encoding="utf-8"))
    assert ak["session_seed"] == 7 and ak["segments"] == key
    sheet = (out / "listening_sheet.csv").read_text(encoding="utf-8-sig")
    assert "seg_001" in sheet and "prefer(1/2)" in sheet
    html = (out / "playlist.html").read_text(encoding="utf-8")
    assert "seg_001__variant_1.wav" in html


def test_ab_session_assignment_reproducible(ab_env, tmp_path):
    """同じ session_seed なら同じ盲検割り当て（再構築可能）。"""
    keys = []
    for run in range(2):
        mem = _make_memory(tmp_path / f"run{run}")
        try:
            keys.append(ab_env.build_ab_session(
                mem, tmp_path / f"out{run}" / "ab_test", limit=2, session_seed=11))
        finally:
            mem.close()
    assert keys[0] == keys[1]


def test_ab_session_assignment_changes_with_session_seed(ab_env, tmp_path):
    keys = []
    for s in (0, 5):
        mem = _make_memory(tmp_path / f"s{s}", n=4)
        try:
            keys.append(ab_env.build_ab_session(
                mem, tmp_path / f"o{s}" / "ab_test", limit=4, session_seed=s))
        finally:
            mem.close()
    # session_seed が違えば割り当てが変わる（盲検の意味）
    assert json.dumps(keys[0], sort_keys=True) != json.dumps(keys[1], sort_keys=True)
