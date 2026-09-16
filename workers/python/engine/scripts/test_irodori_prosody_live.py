"""Irodori プロソディ診断 — 全文かな化が「単語ごとに止まる」原因かを確定する。

同じ文を 3 形式で合成して、発話長と沈黙（ポーズ）を定量比較する:
  kanji    : 原文（TTS が自力で読む。誤読リスクあり）
  katakana : OpenJTalk G2P 出力（現行パイプラインが渡しているもの）
  hiragana : 同じ読みをひらがな化したもの

Usage:
    python engine/scripts/test_irodori_prosody_live.py [--host http://127.0.0.1:8088]
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acting_ir import ActingIR
from backends.irodori_backend import IrodoriBackend
from reading_g2p import g2p_kana

SENTENCES = [
    "夕暮れの商店街を、千早は貼付の剥がれた看板の下で立ち尽くしていた。",
    "「思えばいいんじゃない？ 悠斗の脳味噌しだいでしょ」",
    "風が通り抜けるたびに、錆びた看板が低く軋む。",
]


def kata_to_hira(text: str) -> str:
    """カタカナをひらがなへ（長音記号・記号はそのまま）。"""
    out = []
    for ch in text:
        code = ord(ch)
        if 0x30A1 <= code <= 0x30F6:
            out.append(chr(code - 0x60))
        else:
            out.append(ch)
    return "".join(out)


def ffmpeg(path: str, *args: str) -> str:
    r = subprocess.run(["ffmpeg", "-i", path, *args, "-f", "null", "-"],
                       capture_output=True, text=True)
    return r.stderr


def analyze(path: Path) -> dict:
    """発話長と沈黙の定量（-35dB 未満が 0.15s 以上続いた区間を沈黙とする）。"""
    err = ffmpeg(str(path), "-af", "silencedetect=noise=-35dB:d=0.15")
    sils = [float(x) for x in re.findall(r"silence_duration: ([\d.]+)", err)]
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    dur = (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
           ) if m else 0.0
    return {"duration": round(dur, 2), "pauses": len(sils),
            "silence": round(sum(sils), 2),
            "longest": round(max(sils), 2) if sils else 0.0}


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="http://127.0.0.1:8088")
    args = ap.parse_args()

    out_dir = Path(__file__).resolve().parent.parent / "output" / "prosody_check"
    out_dir.mkdir(parents=True, exist_ok=True)
    backend = IrodoriBackend(host=args.host)

    for si, sentence in enumerate(SENTENCES):
        kata = g2p_kana(sentence)
        hira = kata_to_hira(kata)
        variants = [("kanji", sentence), ("katakana", kata), ("hiragana", hira)]
        print(f"\n=== 文{si + 1}: {sentence}")
        for name, text in variants:
            out = out_dir / f"s{si + 1}_{name}.wav"
            start = time.time()
            backend.synthesize(ActingIR(
                speaker="narrator", text=text, emotion="neutral",
                backend_options={"irodori": {"voice": "none"}}), out)
            stats = analyze(out)
            print(f"  [{name:8}] {stats['duration']:6.2f}s "
                  f"pauses={stats['pauses']:2d} silence={stats['silence']:5.2f}s "
                  f"longest={stats['longest']:4.2f}s "
                  f"({time.time() - start:4.1f}s)  text={text[:26]}...")
    print(f"\n[done] {out_dir}")


if __name__ == "__main__":
    main()
