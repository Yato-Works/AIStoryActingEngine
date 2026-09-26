"""Gemini 台本演出 ＆ Irodori-TTS Animeモデルの統合動作確認スクリプト。

使い方:
  python workers/python/engine/scripts/test_gemini_irodori_live.py
  python workers/python/engine/scripts/test_gemini_irodori_live.py --text "任意のテキスト"
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_DIR))

from acting_ir import ActingIR
from backends.irodori_backend import IrodoriBackend
from reading import ReadingDictionary
from script_writer import GeminiScriptWriter, OpenJTalkScriptWriter


def main() -> None:
    parser = argparse.ArgumentParser(description="Gemini 台本 + Irodori Anime 音声合成テスト")
    parser.add_argument(
        "--text",
        default="夕暮れの商店街を、千早は、貼付のはがれた看板の下で立ち尽くしていた。「千早！待たせてごめん！」「……ううん。私も、今来たとこ」",
        help="読み上げ対象の小説テキスト",
    )
    parser.add_argument("--host", default=os.environ.get("IRODORI_HOST", "http://127.0.0.1:8088"))
    parser.add_argument("--voice", default="none")
    parser.add_argument("--out", default="output/gemini_irodori_test.wav")
    args = parser.parse_args()

    print(f"📖 原文: {args.text}")

    dictionary = ReadingDictionary({"千早": "ちはや", "貼付": "はりつけ"})
    segments = [{"id": "seg_001", "speaker": "ナレーション / 千早", "text": args.text}]

    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        print("🌟 GeminiScriptWriter で演出台本を生成中...")
        writer = GeminiScriptWriter(api_key=api_key)
        res = writer.write_script(segments, dictionary)
        reading_text = res.script.segments[0].text_reading
    else:
        print("💡 GEMINI_API_KEY 未検出のため、デモ用Gemini演出台本を使用します:")
        reading_text = "ゆうぐれの しょうてんがいを、ちはやは、はりつけの はがれた かんばんの したで 🥺たちつくしていた。『ちはや！またせてごめん！』『……😮‍💨ううん。わたしも、いま きたところ🤭』"

    print(f"🎭 演出台本 (かな＋絵文字): {reading_text}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"🎙️ Irodori-TTS ({args.host}) で音声合成中...")
    backend = IrodoriBackend(host=args.host)
    ir = ActingIR(
        speaker="千早",
        text=args.text,
        backend_options={
            "irodori": {
                "text_reading": reading_text,
                "voice": args.voice,
                "caption": "明るく可愛いアニメ声の少女で、感情を豊かに話す",
            }
        },
    )

    try:
        backend.synthesize(ir, out_path)
        print(f"✅ 生成成功！ 保存先: {out_path.resolve()}")
    except Exception as exc:
        print(f"❌ 合成エラー (サーバーが起動しているか確認してください): {exc}")


if __name__ == "__main__":
    main()
