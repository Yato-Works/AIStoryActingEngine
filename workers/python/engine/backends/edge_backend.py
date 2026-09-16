"""Edge TTS Backend Adapter.

Microsoft Edge の音声ネットワーク (edge-tts) を TTSBackend として実装。

Capability:
    speaking_rate: native   — edge-tts の rate パラメータで直接制御
    pitch:         native   — edge-tts の pitch パラメータで直接制御
    volume:        native   — edge-tts の volume パラメータで直接制御
    emotion:       unsupported — edge-tts は感情制御を持たない
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from acting_ir import ActingIR
from tts_backend import (
    BackendManifest, CapabilityLevel, ResolutionReport, TTSBackend,
)

# voice_id → edge-tts ボイス名マップ（既存 tts.py と同一）
_VOICE_NAME_MAP = {
    "voice_01":  "ja-JP-KeitaNeural",
    "voice_02":  "ja-JP-NanamiNeural",
    "voice_03":  "ja-JP-NanamiNeural",
    "voice_04":  "ja-JP-KeitaNeural",
    "voice_05":  "ja-JP-NanamiNeural",
    "voice_06":  "ja-JP-KeitaNeural",
    "voice_07":  "ja-JP-NanamiNeural",
    "voice_narrator":  "ja-JP-KeitaNeural",
    "voice_01i": "ja-JP-KeitaNeural",
    "voice_02i": "ja-JP-NanamiNeural",
    "voice_03i": "ja-JP-NanamiNeural",
    "voice_04i": "ja-JP-KeitaNeural",
    "voice_05i": "ja-JP-NanamiNeural",
    "voice_06i": "ja-JP-KeitaNeural",
    "voice_07i": "ja-JP-NanamiNeural",
    "voice_narratori": "ja-JP-KeitaNeural",
}

_MANIFEST = BackendManifest(
    backend="edge",
    version="0.1.0",
    capabilities={
        "speaker_cloning": CapabilityLevel.UNSUPPORTED,
        "emotion":         CapabilityLevel.UNSUPPORTED,
        "emotion_intensity": CapabilityLevel.UNSUPPORTED,
        "speaking_rate":   CapabilityLevel.NATIVE,
        "pitch":           CapabilityLevel.NATIVE,
        "energy":          CapabilityLevel.UNSUPPORTED,
        "volume":          CapabilityLevel.NATIVE,
        "pause":           CapabilityLevel.UNSUPPORTED,
        "style":           CapabilityLevel.UNSUPPORTED,
    },
)


def _rate_str(speaking_rate: float) -> str:
    """speaking_rate (1.0=normal) → edge-tts rate 文字列 ("+10%" 形式)。"""
    pct = int(round((speaking_rate - 1.0) * 100))
    return f"{pct:+d}%"


def _pitch_str(pitch: float) -> str:
    """-1.0..1.0 → edge-tts pitch 文字列 ("+10Hz" 形式)。"""
    hz = int(round(pitch * 30))
    return f"{hz:+d}Hz"


def _volume_str(volume: float) -> str:
    """0.5..1.5 → edge-tts volume 文字列 ("+10%" 形式)。"""
    pct = int(round((volume - 1.0) * 50))
    return f"{pct:+d}%"


class EdgeBackend(TTSBackend):
    """Edge TTS の Backend Adapter。"""

    def __init__(self, default_voice: str = "ja-JP-NanamiNeural") -> None:
        self.default_voice = default_voice

    def manifest(self) -> BackendManifest:
        return _MANIFEST

    def synthesize(self, ir: ActingIR, out_path: Path) -> ResolutionReport:
        import edge_tts

        report = ResolutionReport(backend="edge")

        # --- Speaker 解決 ---
        voice = _VOICE_NAME_MAP.get(ir.speaker, ir.speaker)
        if not voice or voice == ir.speaker:
            voice = self.default_voice
        report.add("speaker", ir.speaker, CapabilityLevel.NATIVE, voice)

        # --- Native パラメータ ---
        rate = _rate_str(ir.speaking_rate)
        report.add("speaking_rate", ir.speaking_rate, CapabilityLevel.NATIVE, rate)

        pitch = _pitch_str(ir.pitch)
        report.add("pitch", ir.pitch, CapabilityLevel.NATIVE, pitch)

        volume = _volume_str(ir.volume)
        report.add("volume", ir.volume, CapabilityLevel.NATIVE, volume)

        # --- Unsupported パラメータ（記録のみ） ---
        if ir.emotion != "neutral":
            report.add("emotion", ir.emotion, CapabilityLevel.UNSUPPORTED, None,
                       warning=f"Edge TTS does not support emotion control; "
                               f"'{ir.emotion}' was ignored")
        if ir.emotion_intensity > 0.0:
            report.add("emotion_intensity", ir.emotion_intensity,
                       CapabilityLevel.UNSUPPORTED, None)

        # --- 合成 ---
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        communicate = edge_tts.Communicate(
            ir.text, voice, rate=rate, pitch=pitch, volume=volume,
        )
        asyncio.run(communicate.save(str(out_path)))

        return report
