"""M4B チャプター生成の単体テスト（ffmpeg 不要・純粋関数のみ）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from audio import _chapter_ranges, build_chapter_meta

# parts: (segment_id, chapter, path) — 再生順。各 2.0 秒、ギャップ 250ms。
PARTS = [
    ("seg_001", 1, "a.wav"),
    ("seg_002", 1, "b.wav"),
    ("seg_003", 1, "c.wav"),
    ("seg_004", 2, "d.wav"),
    ("seg_005", 3, "e.wav"),
]
DURS = [2.0] * len(PARTS)
GAP = 250


def test_chapter_ranges_boundaries() -> None:
    ranges = _chapter_ranges(PARTS, DURS, GAP)
    assert len(ranges) == 3, str(ranges)
    # ch1: seg1+gap+seg2+gap+seg3+gap = 2000*3 + 250*3 = 6750ms（章末の無音は前章に含める）
    assert ranges[0] == {"chapter": 1, "start": 0, "end": 6750}, str(ranges[0])
    assert ranges[1] == {"chapter": 2, "start": 6750, "end": 9000}, str(ranges[1])
    # 末尾ギャップは含まない
    assert ranges[2] == {"chapter": 3, "start": 9000, "end": 11000}, str(ranges[2])


def test_chapter_ranges_discontinuous() -> None:
    """章番号が飛んでいてもそのまま区間になる（チャンク欠損でも安全）。"""
    ranges = _chapter_ranges([("s1", 1, "a"), ("s2", 3, "b")], [1.0, 1.0], GAP)
    assert len(ranges) == 2
    assert ranges[1]["chapter"] == 3


def test_build_chapter_meta() -> None:
    meta = build_chapter_meta(PARTS, DURS,
                              {1: "第1章 冒頭", 2: "第2章 出会い"},
                              title="サンプル小説", gap_ms=GAP)
    assert meta.startswith(";FFMETADATA1\ntitle=サンプル小説")
    assert meta.count("[CHAPTER]") == 3
    assert "title=第1章 冒頭" in meta
    assert "title=第2章 出会い" in meta
    assert "title=第3章" in meta  # 未指定章はフォールバック
    assert meta.count("TIMEBASE=1/1000") == 3
    assert "START=0" in meta and "END=6750" in meta


def test_build_chapter_meta_minimal() -> None:
    meta = build_chapter_meta([("s1", 1, "a")], [1.0], None)
    assert meta.count("[CHAPTER]") == 1
    assert "title=第1章" in meta


if __name__ == "__main__":  # 従来の手動実行ランナー
    test_chapter_ranges_boundaries()
    test_chapter_ranges_discontinuous()
    test_build_chapter_meta()
    test_build_chapter_meta_minimal()
    print("全 4 テスト OK ✅")
