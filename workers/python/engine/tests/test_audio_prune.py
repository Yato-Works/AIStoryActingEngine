"""孤児クリップ掃除のテスト（再解析で置換された旧 ID の音声を残さない）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from audio import prune_orphan_audio


def _make(audio_dir: Path, *names: str) -> None:
    audio_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        (audio_dir / name).write_bytes(b"RIFF0000WAVE")


def test_prune_removes_only_orphans(tmp_path):
    audio_dir = tmp_path / "book" / "audio"
    _make(audio_dir, "seg_000.wav", "seg_001.wav", "seg_010.wav", "seg_026.wav")
    removed = prune_orphan_audio(tmp_path / "book", {"seg_000", "seg_001"})
    assert sorted(removed) == ["seg_010.wav", "seg_026.wav"]
    assert sorted(p.name for p in audio_dir.iterdir()) == [
        "seg_000.wav", "seg_001.wav"]


def test_prune_keeps_everything_when_no_orphans(tmp_path):
    audio_dir = tmp_path / "book" / "audio"
    _make(audio_dir, "seg_000.wav")
    assert prune_orphan_audio(tmp_path / "book", {"seg_000"}) == []
    assert (audio_dir / "seg_000.wav").exists()


def test_prune_missing_dir_is_noop(tmp_path):
    assert prune_orphan_audio(tmp_path / "nothing", {"seg_000"}) == []
