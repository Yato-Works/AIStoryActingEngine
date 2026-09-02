"""Phase 3.5T - judge_live: OllamaJudge と ContextJudge を実機比較する検証スクリプト。

KPI は「人間が聞いて違和感を覚えるか」。その第一歩として、
LLM 演技監督（OllamaJudge）が決定論 Judge（ContextJudge）と同じ方向を
指せるかを、実際の Ollama で確認する。

使い方:
  python judge_live.py                      # qwen3:4b @ localhost:11434
  python judge_live.py --model qwen3:8b --host http://localhost:11434

Scenario（3.5R の例そのまま）:
  直前に友人が死亡（VoiceState: sadness 0.82 / tension 0.71）
  (1) violation  : energy 0.97 / speed 1.08 で明るく —— 音質完璧でも演技は 0 点か?
  (2) consistent : energy 0.45 / speed 0.85 で抑えて —— 正しく高評価か?
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llm_judge import ContextJudge, OllamaJudge
from models import VoiceState

STATE = VoiceState(sadness=0.82, tension=0.71, fatigue=0.30)

SCENARIOS = [
    ("violation", "大丈夫だよ……！", "sad", "whispered_confession",
     {"speed": [1.08, 1.08], "pitch": [0.02, 0.02], "energy": [0.97, 0.97],
      "timing_ms": [0.0, 850.0], "total_ms": 1700.0}),
    ("consistent", "大丈夫だよ……。", "sad", "whispered_confession",
     {"speed": [0.85, 0.85], "pitch": [-0.12, -0.12], "energy": [0.45, 0.45],
      "timing_ms": [0.0, 1150.0], "total_ms": 2300.0}),
]


def _ollama_alive(host: str) -> bool:
    try:
        import httpx
        r = httpx.get(f"{host.rstrip('/')}/api/tags", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


def _setup_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def main() -> None:
    _setup_stdio()
    ap = argparse.ArgumentParser(description="Performance Judge 実機比較")
    ap.add_argument("--model", default="qwen3:4b")
    ap.add_argument("--host", default="http://localhost:11434")
    args = ap.parse_args()

    context_judge = ContextJudge()
    ollama_judge = OllamaJudge(model=args.model, host=args.host, timeout=180.0)
    live = _ollama_alive(args.host)
    print(f"🎭 judge_live: model={args.model} host={args.host} "
          f"ollama={'online' if live else 'OFFLINE（fallback 動作を確認）'}")
    print(f"   scenario: 直前に友人が死亡 -> VoiceState sadness=0.82 tension=0.71\n")

    rows = []
    for name, text, emotion, intent, plan in SCENARIOS:
        plan = dict(plan, intent=intent, text=text)
        ctx = context_judge.evaluate(plan, state=STATE, intent=intent,
                                     emotion=emotion)
        olm = ollama_judge.evaluate(plan, state=STATE, intent=intent,
                                    emotion=emotion, prev_emotion="tender",
                                    audio_metrics={"clipping": False,
                                                   "silence_ratio": 0.05})
        fallback = "judge_llm_fallback" in olm.diagnoses
        rows.append((name, ctx, olm, fallback))
        print(f"  [{name}] \"{text}\"")
        for label, rep in (("ContextJudge", ctx), ("OllamaJudge ", olm)):
            print(f"    {label}: human={rep.human_ness:.2f} "
                  f"char={rep.character_consistency:.2f} "
                  f"scene={rep.scene_consistency:.2f} "
                  f"cont={rep.continuity:.2f} "
                  f"acou={rep.acoustic_quality:.2f} {rep.diagnoses}")
        if fallback:
            print("    ※ OllamaJudge は fallback（ContextJudge）で代行")
        print()

    # 方向の一致検査: violation < consistent が両 Judge で成り立つか
    (v_name, v_ctx, v_olm, v_fb), (c_name, c_ctx, c_olm, c_fb) = rows
    ctx_ok = v_ctx.human_ness < c_ctx.human_ness
    olm_ok = v_olm.human_ness < c_olm.human_ness
    print("✅ ContextJudge : violation < consistent =", ctx_ok)
    print(f"✅ OllamaJudge  : violation < consistent =", olm_ok,
          "（live" if live and not (v_fb or c_fb) else "（fallback or offline）", "）")
    if live and not (v_fb or c_fb):
        print("→ LLM 演技監督は決定論 Judge と同じ方向を指している:"
              "OK" if (ctx_ok and olm_ok) else "→ 方向が割れている: プロンプト要調整")


if __name__ == "__main__":
    main()