"""AivisSpeech Backend Adapter.

AivisSpeech Engine (VOICEVOX 互換 HTTP API) を TTSBackend として実装。

Capability:
    speaking_rate:     native      — speedScale パラメータで直接制御
    pitch:             native      — pitchScale パラメータで直接制御
    volume:            native      — volumeScale パラメータで直接制御
    emotion:           unsupported — API レベルでの感情制御なし
    speaker_cloning:   unsupported — 事前定義の speaker のみ
"""

from __future__ import annotations

from pathlib import Path

from acting_ir import ActingIR
from tts_backend import (
    BackendManifest, CapabilityLevel, ResolutionReport, TTSBackend,
)

_MANIFEST = BackendManifest(
    backend="aivis",
    version="0.1.0",
    capabilities={
        "speaker_cloning":   CapabilityLevel.UNSUPPORTED,
        "emotion":           CapabilityLevel.UNSUPPORTED,
        "emotion_intensity": CapabilityLevel.UNSUPPORTED,
        "speaking_rate":     CapabilityLevel.NATIVE,
        "pitch":             CapabilityLevel.NATIVE,
        "energy":            CapabilityLevel.UNSUPPORTED,
        "volume":            CapabilityLevel.NATIVE,
        "pause":             CapabilityLevel.UNSUPPORTED,
        "style":             CapabilityLevel.UNSUPPORTED,
    },
)


class AivisBackend(TTSBackend):
    """AivisSpeech Engine の Backend Adapter。"""

    def __init__(self, host: str = "http://127.0.0.1:10101",
                 speaker: int = 0) -> None:
        self.base_url = host.rstrip("/")
        self.speaker = speaker

    def manifest(self) -> BackendManifest:
        return _MANIFEST

    def synthesize(self, ir: ActingIR, out_path: Path) -> ResolutionReport:
        import httpx

        report = ResolutionReport(backend="aivis")

        # --- Speaker 解決 ---
        # backend_options で speaker_id を指定可能（設計書 §6）
        aivis_opts = ir.backend_options.get("aivis", {})
        speaker_id = aivis_opts.get("speaker_id", self.speaker)
        report.add("speaker", ir.speaker, CapabilityLevel.NATIVE, speaker_id)

        # --- Speaking Rate → speedScale (native) ---
        speed = max(0.5, min(2.0, ir.speaking_rate))
        report.add("speaking_rate", ir.speaking_rate,
                   CapabilityLevel.NATIVE, speed)

        # --- Pitch → pitchScale (native) ---
        pitch = max(-0.5, min(0.5, ir.pitch))
        report.add("pitch", ir.pitch, CapabilityLevel.NATIVE, pitch)

        # --- Volume → volumeScale (native) ---
        volume = max(0.1, min(2.0, ir.volume))
        report.add("volume", ir.volume, CapabilityLevel.NATIVE, volume)

        # --- Unsupported パラメータ ---
        if ir.emotion != "neutral":
            report.add("emotion", ir.emotion, CapabilityLevel.UNSUPPORTED, None,
                       warning=f"AivisSpeech does not support emotion control; "
                               f"'{ir.emotion}' was ignored")

        # --- 合成 ---
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        query = httpx.post(
            f"{self.base_url}/audio_query",
            params={"text": ir.text, "speaker": speaker_id},
            timeout=60.0,
        ).json()
        query["speedScale"] = speed
        query["pitchScale"] = pitch
        query["volumeScale"] = volume
        wav = httpx.post(
            f"{self.base_url}/synthesis",
            params={"speaker": speaker_id},
            json=query,
            timeout=120.0,
        ).content
        out_path.write_bytes(wav)

        return report
