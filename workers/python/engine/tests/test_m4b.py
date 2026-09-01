"""M4B チャプター生成の単体テスト（ffmpeg 不要・純粋関数のみ）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from audio import _chapter_ranges, build_chapter_meta

PASSED = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED
    if not cond:
        print(f"  ✗ {name} {detail}")
        raise AssertionError(name)
    print(f"  ✓ {name}")
    PASSED += 1


# parts: (segment_id, chapter, path) — 再生順
PARTS = [
    ("seg_001", 1, "a.wav"),
    ("seg_002", 1, "b.wav"),
    ("seg_003", 1, "c.wav"),
    ("seg_004", 2, "d.wav"),
    ("seg_005", 3, "e.wav"),
]
# 各 2.0 秒、ギャップ 250ms
DURS = [2.0] * len(PARTS)
GAP = 250

print("[1] 章境界の計算")
ranges = _chapter_ranges(PARTS, DURS, GAP)
check("章は3つ", len(ranges) == 3, str(ranges))
# ch1: seg1+gap+seg2+gap+seg3+gap = 2000*3 + 250*3 = 6750ms（章末の無音は前章に含める）
check("ch1 start=0", ranges[0]["start"] == 0)
check("ch1 end=6750", ranges[0]["end"] == 6750, str(ranges[0]))
check("ch2 start=6750", ranges[1]["start"] == 6750)
check("ch2 end=9000", ranges[1]["end"] == 9000, str(ranges[1]))
check("ch3 start=9000", ranges[2]["start"] == 9000)
check("ch3 end=11000（末尾ギャップなし）", ranges[2]["end"] == 11000, str(ranges[2]))

print("[2] 章が飛んでも連続扱い（チャンクが欠けても安全）")
ranges2 = _chapter_ranges([("s1", 1, "a"), ("s2", 3, "b")], [1.0, 1.0], GAP)
check("2章区間になる", len(ranges2) == 2)
check("章番号は実際の値", ranges2[1]["chapter"] == 3)

print("[3] ffmetadata の生成")
meta = build_chapter_meta(PARTS, DURS, {1: "第1章 冒頭", 2: "第2章 出会い"},
                          title="サンプル小説", gap_ms=GAP)
check("ヘッダ", meta.startswith(";FFMETADATA1\ntitle=サンプル小説"))
check("CHAPTER 3つ", meta.count("[CHAPTER]") == 3)
check("章タイトル1", "title=第1章 冒頭" in meta)
check("章タイトル2", "title=第2章 出会い" in meta)
check("章タイトル3（フォールバック）", "title=第3章" in meta)
check("TIMEBASE", meta.count("TIMEBASE=1/1000") == 3)
check("START/END", "START=0" in meta and "END=6750" in meta)

print("[4] タイトル未指定でも壊れない")
meta2 = build_chapter_meta([("s1", 1, "a")], [1.0], None)
check("CHAPTER 1つ", meta2.count("[CHAPTER]") == 1)
check("フォールバック章名", "title=第1章" in meta2)

print(f"\n全 {PASSED} 項目 OK ✅")
