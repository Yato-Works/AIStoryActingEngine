"""Phase 3.5P - HVE パイプライン統合のテスト（main.synthesize_all + --hve）。"""
from __future__ import annotations

import struct
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import main as engine
from memory import MemoryEngine
from models import (Character, DirectedSegment, Performance, VoiceProfile,
                    VoiceState)
from voices import NARRATOR_VOICE, NARRATOR_VOICE_INTERNAL


class FakeProvider:
    name = "fake"
    ext = ".mp3"

    def __init__(self):
        self.calls = []

    def synthesize(self, text, perf, out_path):
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(struct.pack("<h", 0) * 4800)  # 0.2s silence
        self.calls.append((text, str(out_path)))


def _perf(voice: str, mode: str, emotion: str) -> Performance:
    return Performance(voice=voice, mode=mode, emotion=emotion,
                       intensity=0.6, pace=1.0, pitch=0.0)


def _setup(tmp_path: Path) -> MemoryEngine:
    """キャラ 1 人（External/Internal ボイス付き）+ セグメント 2 つの DB。"""
    mem = MemoryEngine(tmp_path / "story.db", "hve_test", title="HVE Test")
    ch = Character(
        id="c1", name="太郎", gender="male",
        voice=VoiceProfile(voice_id="voice_01", gender="male",
                           sbv2_model_name="jvnv-M1-jp"),
        voice_internal=VoiceProfile(voice_id="voice_01i", gender="male",
                                    sbv2_model_name="jvnv-M1-jp"),
        voice_state=VoiceState(tension=0.4),
    )
    mem.upsert_character(ch, 0)
    mem.save_voice_profile(ch)

    segs = [
        DirectedSegment(id="seg_001", type="dialogue", speaker="c1",
                        text="え？そうなの？", emotion="surprised",
                        intensity=0.6, chapter=1, chunk_index=0,
                        performance=_perf("voice_01", "dialogue", "surprised")),
        DirectedSegment(id="seg_002", type="narration", speaker="narrator",
                        text="夜が更けていく。", emotion="neutral",
                        intensity=0.3, chapter=1, chunk_index=0,
                        performance=_perf("voice_narrator", "narration", "neutral")),
    ]
    for s in segs:
        mem.save_segment(s)
    return mem


def test_hve_profile_table_builds_from_casting(tmp_path):
    mem = _setup(tmp_path)
    try:
        table = engine._hve_profile_table(mem)
    finally:
        mem.close()
    # キャスティング済み External/Internal とナレーター両方が揃う
    assert "voice_01" in table and "voice_01i" in table
    assert NARRATOR_VOICE.voice_id in table
    assert NARRATOR_VOICE_INTERNAL.voice_id in table
    for vid, (prof, st) in table.items():
        assert isinstance(prof, VoiceProfile) and prof.voice_id == vid
        assert isinstance(st, VoiceState) and 0.0 <= st.tension <= 1.0


def test_hve_on_composes_wav(tmp_path, monkeypatch):
    if pytest.importorskip("shutil").which("ffmpeg") is None:
        pytest.skip("ffmpeg not available")
    provider = FakeProvider()
    monkeypatch.setattr(engine, "get_provider", lambda name: provider)
    monkeypatch.setattr(engine, "OUT_DIR", tmp_path / "out")
    mem = _setup(tmp_path)
    try:
        n = engine.synthesize_all(mem, "fake", hve=True)
    finally:
        mem.close()
    assert n == 2
    # HVE 経由 -> 常に .wav。プロバイダ synthesize は performance synth 経由で呼ばれる
    for seg_id in ("seg_001", "seg_002"):
        clip = tmp_path / "out" / "hve_test" / "audio" / f"{seg_id}.wav"
        assert clip.exists() and clip.stat().st_size > 0, clip
    assert provider.calls  # Sbv2PerformanceSynthesizer -> provider.synthesize


def test_hve_off_keeps_provider_path(tmp_path, monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(engine, "get_provider", lambda name: provider)
    monkeypatch.setattr(engine, "OUT_DIR", tmp_path / "out")
    mem = _setup(tmp_path)
    try:
        n = engine.synthesize_all(mem, "fake")
    finally:
        mem.close()
    assert n == 2
    # デフォルトは従来通り provider.ext を使い、provider.synthesize を直接呼ぶ
    assert len(provider.calls) == 2
    for seg_id in ("seg_001", "seg_002"):
        clip = tmp_path / "out" / "hve_test" / "audio" / f"{seg_id}.mp3"
        assert clip.exists(), clip


def test_hve_resume_skips_done(tmp_path, monkeypatch):
    if pytest.importorskip("shutil").which("ffmpeg") is None:
        pytest.skip("ffmpeg not available")
    provider = FakeProvider()
    monkeypatch.setattr(engine, "get_provider", lambda name: provider)
    monkeypatch.setattr(engine, "OUT_DIR", tmp_path / "out")
    mem = _setup(tmp_path)
    try:
        assert engine.synthesize_all(mem, "fake", hve=True) == 2
        assert engine.synthesize_all(mem, "fake", hve=True, resume=True) == 0
    finally:
        mem.close()


def test_unknown_voice_falls_back(tmp_path, monkeypatch):
    """voice_id がテーブルに無くてもデフォルト VoiceProfile で落ちない。"""
    if pytest.importorskip("shutil").which("ffmpeg") is None:
        pytest.skip("ffmpeg not available")
    provider = FakeProvider()
    monkeypatch.setattr(engine, "get_provider", lambda name: provider)
    monkeypatch.setattr(engine, "OUT_DIR", tmp_path / "out")
    mem = MemoryEngine(tmp_path / "story.db", "hve_test", title="HVE Test")
    mem.save_segment(DirectedSegment(
        id="seg_001", type="dialogue", speaker="cX", text="……そう。",
        emotion="sad", intensity=0.5, chapter=1, chunk_index=0,
        performance=_perf("voice_99", "dialogue", "sad")))
    try:
        assert engine.synthesize_all(mem, "fake", hve=True) == 1
    finally:
        mem.close()
    assert (tmp_path / "out" / "hve_test" / "audio" / "seg_001.wav").exists()


def test_worker_start_job_accepts_hve(tmp_path):
    """rpc_start_job が hve パラメータを受け、payload に記録する。"""
    from worker import EngineWorker

    w = EngineWorker(tmp_path / "worker.db")
    novel = tmp_path / "novel.txt"
    novel.write_text("1行目\n\n2行目", encoding="utf-8")
    # スレッド起動を避けるため _spawn_pipeline を差し替える
    w._spawn_pipeline = lambda *a, **k: "spawned"
    res = w.rpc_start_job(novel=str(novel), hve=True)
    assert res["book_id"] == "novel"
    job = w._job_view(res["job_id"])
    assert job["payload"]["hve"] is True
