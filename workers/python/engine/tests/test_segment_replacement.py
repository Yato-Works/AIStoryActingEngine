"""再解析時のセグメント置換（重複防止）のテスト。

実機事故: 同じ小説を再解析すると segments が「別 ID の重複行」として積み上がり、
audiobook.wav が同じ文を 3 回繰り返した。原因は start_no = count_segments()。
ここでは DB レベルで「再解析しても件数と ID が変わらない」ことを固定する。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memory import MemoryEngine
from models import DirectedSegment, Performance


def _seg(seg_id: str, chunk_index: int, text: str) -> DirectedSegment:
    return DirectedSegment(
        id=seg_id, type="narration", speaker="narrator", text=text,
        emotion="neutral", intensity=0.3, chapter=1,
        chunk_index=chunk_index,
        performance=Performance(voice="voice_narrator", mode="narration",
                                emotion="neutral", intensity=0.3,
                                pace=1.0, pitch=0.0))


def _ids(mem: MemoryEngine) -> list[str]:
    return [s.id for s in mem.load_segments()]


def test_delete_chunk_segments_targets_only_that_chunk(tmp_path: Path) -> None:
    mem = MemoryEngine(tmp_path / "story.db", "book")
    try:
        mem.save_segment(_seg("seg_000", 0, "chunk0-a"))
        mem.save_segment(_seg("seg_001", 0, "chunk0-b"))
        mem.save_segment(_seg("seg_002", 1, "chunk1-a"))
        assert mem.delete_chunk_segments(0) == 2
        assert _ids(mem) == ["seg_002"]
        assert mem.delete_chunk_segments(9) == 0  # 存在しないチャンクは 0
    finally:
        mem.close()


def test_delete_chunk_segments_clears_audio_path(tmp_path: Path) -> None:
    """削除すると audio_path も消えるので、次回 TTS で再合成される。"""
    mem = MemoryEngine(tmp_path / "story.db", "book")
    try:
        mem.save_segment(_seg("seg_000", 0, "chunk0-a"))
        mem.set_audio("seg_000", "/tmp/seg_000.wav")
        assert mem.audio_done() == {"seg_000"}
        mem.delete_chunk_segments(0)
        assert mem.audio_done() == set()
    finally:
        mem.close()


def test_segment_start_no_counts_only_preceding_chunks(tmp_path: Path) -> None:
    mem = MemoryEngine(tmp_path / "story.db", "book")
    try:
        assert mem.segment_start_no(0) == 0
        mem.save_segment(_seg("seg_000", 0, "chunk0-a"))
        mem.save_segment(_seg("seg_001", 0, "chunk0-b"))
        mem.save_segment(_seg("seg_002", 1, "chunk1-a"))
        # 自分より前のチャンクの件数だけを数える（全体件数ではない）
        assert mem.segment_start_no(1) == 2
        assert mem.segment_start_no(2) == 3
    finally:
        mem.close()


def test_reanalysis_does_not_duplicate(tmp_path: Path) -> None:
    """同じチャンクを 3 回解析しても、件数も ID も 1 回目と同じ。"""
    mem = MemoryEngine(tmp_path / "story.db", "book")
    try:
        def analyze_chunk(chunk_index: int, texts: list[str]) -> list[str]:
            mem.delete_chunk_segments(chunk_index)
            start_no = mem.segment_start_no(chunk_index)
            ids = []
            for i, text in enumerate(texts):
                seg_id = f"seg_{start_no + i:03d}"
                mem.save_segment(_seg(seg_id, chunk_index, text))
                ids.append(seg_id)
            return ids

        first = analyze_chunk(0, ["あ", "い", "う"])
        analyze_chunk(1, ["え", "お"])
        for _ in range(2):  # 再解析を 2 回
            again = analyze_chunk(0, ["あ", "い", "う"])
            assert again == first  # ID が安定している
        assert len(_ids(mem)) == 5  # 重複が積み上がらない
        assert _ids(mem) == ["seg_000", "seg_001", "seg_002", "seg_003", "seg_004"]
    finally:
        mem.close()


def test_reanalysis_after_text_change_replaces_content(tmp_path: Path) -> None:
    """本文が変わってセグメント数が減っても、古い行は残らない。"""
    mem = MemoryEngine(tmp_path / "story.db", "book")
    try:
        mem.delete_chunk_segments(0)
        mem.save_segment(_seg("seg_000", 0, "旧A"))
        mem.save_segment(_seg("seg_001", 0, "旧B"))
        mem.save_segment(_seg("seg_002", 0, "旧C"))

        mem.delete_chunk_segments(0)
        start_no = mem.segment_start_no(0)
        mem.save_segment(_seg(f"seg_{start_no:03d}", 0, "新A"))
        rows = mem.load_segments()
        assert [s.text for s in rows] == ["新A"]
    finally:
        mem.close()
