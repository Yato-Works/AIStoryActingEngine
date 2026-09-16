"""Irodori 読み台本の実機確認（Irodori-TTS-Server が必要）。

「読み間違え」の切り分け用: 問題になった文だけを OpenJTalk でかな化して
合成し、かなが正しいかを耳で確認できる WAV を並べて出力する。

Usage:
    python engine/scripts/test_irodori_reading_check_live.py
    python engine/scripts/test_irodori_reading_check_live.py --text-file samples/sample_novel_short.txt
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acting_ir import ActingIR
from backends.irodori_backend import IrodoriBackend
from reading import ReadingDictionary
from script_writer import OpenJTalkScriptWriter

DEFAULT_SENTENCES = [
    "悠斗は大げさに肩をすくめてみせた。",          # 大げさ → オーゲサ
    "「思えばいいんじゃない？ 悠斗の脳味噌しだいでしょ」",  # 脳味噌 → ノーミソ
    "夕暮れの商店街を、千早は貼付の剥がれた看板の下で立ち尽くしていた。",
]


def _load_sentences(args) -> list[str]:
    if args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8")
        return [line.strip() for line in text.splitlines() if line.strip()]
    return DEFAULT_SENTENCES


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="http://127.0.0.1:8088")
    ap.add_argument("--text-file", default="")
    ap.add_argument("--out-dir", default="")
    args = ap.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else (
        Path(__file__).resolve().parent.parent / "output" / "reading_check")
    out_dir.mkdir(parents=True, exist_ok=True)

    sentences = _load_sentences(args)
    payload = [{"id": f"seg_{i:03d}", "speaker": "narrator", "text": s}
               for i, s in enumerate(sentences)]
    # 辞書は engine/data/readings.json（無ければ空）
    dict_path = Path(__file__).resolve().parent.parent / "data" / "readings.json"
    dictionary = ReadingDictionary.load_json(dict_path)
    result = OpenJTalkScriptWriter().write_script(
        payload, dictionary, chunk_index=0)

    backend = IrodoriBackend(host=args.host)
    for i, seg in enumerate(result.script.segments):
        out = out_dir / f"{seg.id}.wav"
        start = time.time()
        backend.synthesize(ActingIR(
            speaker=seg.speaker, text=seg.text, emotion="neutral",
            backend_options={"irodori": {"text_reading": seg.text_reading,
                                         "voice": "none"}}), out)
        print(f"[{i + 1}/{len(sentences)}] {out.name} "
              f"({out.stat().st_size} bytes, {time.time() - start:.1f}s)")
        print(f"    原文: {seg.text}")
        print(f"    かな: {seg.text_reading}")
    if result.uncovered:
        print("[漢字残留]", result.uncovered)
    print(f"[done] {out_dir}")


if __name__ == "__main__":
    main()
