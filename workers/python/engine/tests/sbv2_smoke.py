"""SBV2 サーバのスモークテスト。

前提: third_party/Style-Bert-VITS2 で `python server_fastapi.py` 済み（localhost:5000）。
実行: ..\\.venv\\Scripts\\python tests\\sbv2_smoke.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

OUT = Path(__file__).parent.parent / "output" / "sbv2_smoke"
BASE = "http://127.0.0.1:5000"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    r = httpx.get(f"{BASE}/models", timeout=30.0)
    models = r.json()
    print(f"✓ /models: {len(models)} モデル読み込み済み")

    for name, model in (("male", "jvnv-M1-jp"), ("female", "jvnv-F1-jp")):
        resp = httpx.post(f"{BASE}/voice", data={
            "text": "こんにちは。これは Style-Bert-VITS2 の動作確認です。",
            "model_name": model,
            "speaker_id": 0,
            "style": "Neutral",
            "style_weight": 0.8,
            "sdp_ratio": 0.2,
            "noise": 0.6,
            "noise_w": 0.8,
            "length": 1.0,
            "auto_split": "true",
            "language": "JP",
        }, timeout=300.0)
        resp.raise_for_status()
        out = OUT / f"{name}.wav"
        out.write_bytes(resp.content)
        print(f"✓ {model} → {out} ({len(resp.content) / 1024:.0f} KB)")

    print("スモークテスト成功 ✅")


if __name__ == "__main__":
    main()
