"""Style-Bert-VITS2 Backend Adapter.

Style-Bert-VITS2 のローカルサーバ (HTTP API) を TTSBackend として実装。

Capability:
    emotion:         native      — SBV2 の style パラメータにマッピング
    emotion_intensity: native    — style_weight へ変換
    speaking_rate:   native      — length パラメータ（逆数変換）
    pitch:           approximate — f0 調整（SBV2の制御は限定的）
    volume:          approximate — noise/volume パラメータで近似
    speaker_cloning: unsupported — SBV2 は事前学習済みモデルのみ
"""

from __future__ import annotations

import os
from pathlib import Path

from acting_ir import ActingIR
from tts_backend import (
    BackendManifest, CapabilityLevel, ResolutionReport, TTSBackend,
)

# 感情 → SBV2 スタイル名マッピング（既存 sbv2_adapter.py と同一）
EMOTION_TO_STYLE = {
    "happy": "Joyful", "angry": "Angry", "sad": "Sad", "fearful": "Fearful",
    "surprised": "Surprise", "tender": "Tender", "sarcastic": "Sarcasm",
    "anxious": "Anxious", "calm": "Calm", "neutral": "Neutral",
}

_MANIFEST = BackendManifest(
    backend="sbv2",
    version="0.1.0",
    capabilities={
        "speaker_cloning":   CapabilityLevel.UNSUPPORTED,
        "emotion":           CapabilityLevel.NATIVE,
        "emotion_intensity": CapabilityLevel.NATIVE,
        "speaking_rate":     CapabilityLevel.NATIVE,
        "pitch":             CapabilityLevel.APPROXIMATE,
        "energy":            CapabilityLevel.APPROXIMATE,
        "volume":            CapabilityLevel.APPROXIMATE,
        "pause":             CapabilityLevel.UNSUPPORTED,
        "style":             CapabilityLevel.NATIVE,
    },
)


class Sbv2Backend(TTSBackend):
    """Style-Bert-VITS2 の Backend Adapter。"""

    def __init__(self, host: str | None = None,
                 default_model: str = "jvnv-M1-jp",
                 default_style: str = "Neutral") -> None:
        self.base_url = (host or os.environ.get(
            "SBV2_HOST", "http://127.0.0.1:5000")).rstrip("/")
        self.default_model = default_model
        self.default_style = default_style

    def manifest(self) -> BackendManifest:
        return _MANIFEST

    def synthesize(self, ir: ActingIR, out_path: Path) -> ResolutionReport:
        import httpx

        report = ResolutionReport(backend="sbv2")

        # --- Speaker / Model 解決 ---
        # backend_options で SBV2 固有設定を受け取れる（設計書 §6）
        sbv2_opts = ir.backend_options.get("sbv2", {})
        model_name = sbv2_opts.get("model_name", self.default_model)
        report.add("speaker", ir.speaker, CapabilityLevel.NATIVE, model_name)

        # --- Emotion → Style (native) ---
        style = sbv2_opts.get("style")
        if style is None:
            style = EMOTION_TO_STYLE.get(ir.emotion, self.default_style)
        if ir.style and ir.style not in ("narration", "dialogue", "internal"):
            style = ir.style  # 明示的なスタイル指定があれば優先
        report.add("emotion", ir.emotion, CapabilityLevel.NATIVE, style)

        # --- Emotion Intensity → style_weight (native) ---
        style_weight = round(min(1.0, 0.4 + 0.8 * ir.emotion_intensity), 2)
        report.add("emotion_intensity", ir.emotion_intensity,
                   CapabilityLevel.NATIVE, style_weight)

        # --- Speaking Rate → length (native, 逆数変換) ---
        # SBV2 の length は大きいほど遅い（edge-tts の rate とは逆向き）
        length = round(max(0.5, min(2.0, 1.0 / max(0.1, ir.speaking_rate))), 3)
        report.add("speaking_rate", ir.speaking_rate,
                   CapabilityLevel.NATIVE, length)

        # --- Pitch (approximate) ---
        # SBV2 は f0 の直接制御が限定的
        report.add("pitch", ir.pitch, CapabilityLevel.APPROXIMATE, ir.pitch,
                   warning="SBV2 pitch control is approximate via style_weight"
                   if abs(ir.pitch) > 0.3 else None)

        # --- Volume / Energy (approximate) ---
        report.add("volume", ir.volume, CapabilityLevel.APPROXIMATE, ir.volume)

        # --- 合成 ---
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        params = {
            "text": ir.text,
            "model_name": model_name,
            "speaker_id": sbv2_opts.get("speaker_id", 0),
            "style": style,
            "style_weight": style_weight,
            "sdp_ratio": sbv2_opts.get("sdp_ratio", 0.2),
            "noise": sbv2_opts.get("noise", 0.6),
            "noise_w": sbv2_opts.get("noise_w", 0.8),
            "length": length,
            "auto_split": "true",
            "split_interval": 0.5,
            "language": sbv2_opts.get("language", "JP"),
        }
        resp = httpx.post(f"{self.base_url}/voice", params=params, timeout=300.0)
        resp.raise_for_status()
        out_path.write_bytes(resp.content)

        return report
