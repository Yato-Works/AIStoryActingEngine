"""Irodori Backend の実機 E2E テスト（Irodori-TTS-Server が必要）。

Usage:
    python engine/scripts/test_irodori_e2e_live.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acting_ir import ActingIR
from backends.irodori_backend import IrodoriBackend


def main() -> None:
    # 演者さん（Irodori）に読み台本（全文かな）を渡して演技してもらう
    ir = ActingIR(
        speaker="narrator",
        text="千早は貼付の剥がれた看板の下で立ち尽くしていた。",
        emotion="sad",
        emotion_intensity=0.8,
        speaking_rate=1.0,
        backend_options={"irodori": {
            # Script Writer（台本家AI）が書いた読み台本
            "text_reading": "ゆうぐれのしょうてんがいを、ちはやははりつけの"
                            "はがれたかんばんのしたでたちつくしていた。",
            "voice": "none",       # 文字のみ（VoiceDesign）
            "emoji": False,
        }},
    )

    backend = IrodoriBackend(host="http://127.0.0.1:8088")
    report = backend.manifest() and None
    out = Path(__file__).resolve().parent.parent / "output" / "irodori_e2e.wav"
    start = time.time()
    result = backend.synthesize(ir, out)
    print(f"[saved] {out} ({out.stat().st_size} bytes, {time.time()-start:.1f}s)")
    print("[warnings]", [w.warning for w in result.warnings if w.parameter != "text_reading"])
    print("[caption]", next(e.resolved for e in result.entries
                            if e.parameter == "emotion"))


if __name__ == "__main__":
    main()
