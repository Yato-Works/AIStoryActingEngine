"""Script Writer の実機テスト（Ollama が必要。CI では実行しない）。

Usage:
    python engine/scripts/test_script_writer_live.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reading import ReadingDictionary
from script_writer import OllamaScriptWriter

SEGMENTS = [
    {"id": "seg_001", "speaker": "narrator",
     "text": "夕暮れの商店街を、千早は貼付の剥がれた看板の下で立ち尽くしていた。"},
    {"id": "seg_002", "speaker": "chihaya",
     "text": "「今日は、どうしようもなく眠いの」"},
    {"id": "seg_003", "speaker": "yuuto",
     "text": "「千早、その言い草は褒め言葉だと思っていいのか？」"},
]

GLOSSARY = {
    "千早": "主人公。15歳の少女。無口で皮肉屋",
    "悠斗": "千早の幼馴染。明るく軽口を叩く",
}


def main() -> None:
    dictionary = ReadingDictionary()
    writer = OllamaScriptWriter(model="qwen3:4b")
    result = writer.write_script(SEGMENTS, dictionary, GLOSSARY, chunk_index=0)

    print("=== 読み台本 ===")
    for seg in result.script.segments:
        print(f"[{seg.id}] 原文:   {seg.text}")
        print(f"[{seg.id}] かな版: {seg.text_reading}")

    print("\n=== 新規の読み提案 ===")
    print(json.dumps(result.new_readings, ensure_ascii=False, indent=2))

    print("\n=== 漢字残留チェック（空なら合格） ===")
    print(json.dumps(result.uncovered, ensure_ascii=False))


if __name__ == "__main__":
    main()
