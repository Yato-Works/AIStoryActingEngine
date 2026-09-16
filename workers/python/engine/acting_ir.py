"""Acting IR v1 — TTS-agnostic な演技意図の中間表現。

設計書「AIStoryActingEngine — TTS Abstraction Design」§2, §4 に基づく。

Engine Core は Acting IR だけを出力し、TTS 固有のパラメータ名を一切使わない。
Backend Adapter が Acting IR を各モデル固有形式へ変換する。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from models import Performance, Voicing


# ============================================================================
# Acting IR v1
# ============================================================================

class ActingIR(BaseModel):
    """Acting IR v1 — 演技意図の中間表現。

    Engine Core が出力する「何を、どう演じるか」の意味表現。
    TTS モデル固有のパラメータ名（length, sdp_ratio 等）は含まない。
    """

    version: Literal["1"] = "1"

    # --- 誰が何を言うか ---
    speaker: str                            # voice_id
    text: str

    # --- 演技の意味 ---
    emotion: str = "neutral"                # happy / angry / sad / ...
    emotion_intensity: float = 0.3          # 0.0 .. 1.0
    speaking_rate: float = 1.0              # 0.5 .. 1.5 (1.0 = 標準)
    pitch: float = 0.0                      # -1.0 .. 1.0
    energy: float = 0.8                     # 0.0 .. 1.5
    volume: float = 1.0                     # 0.5 .. 1.5
    pause_before: float = 0.0              # seconds
    pause_after: float = 0.0               # seconds
    style: str = ""                         # narration / dialogue / internal / ...
    voicing: Voicing = "external"           # external / internal / narrator

    # --- 設計書 §6: Backend 固有拡張 ---
    backend_options: dict[str, dict[str, Any]] = Field(default_factory=dict)


# ============================================================================
# Performance → Acting IR 変換
# ============================================================================

def performance_to_ir(text: str, perf: Performance) -> ActingIR:
    """既存の Performance を Acting IR v1 へ変換する。

    既存パイプライン（Director → Performance → TTS）から
    新パイプライン（Director → Performance → ActingIR → Backend）への
    橋渡しを行う。
    """
    return ActingIR(
        speaker=perf.voice,
        text=text,
        emotion=perf.emotion,
        emotion_intensity=perf.intensity,
        speaking_rate=perf.pace,
        pitch=perf.pitch,
        energy=perf.volume,       # Performance.volume ≒ ActingIR.energy
        volume=perf.volume,
        style=perf.style or perf.mode,
        voicing=perf.voicing,
    )
