"""TTS プロバイダ抽象（ITTSProvider）と実装。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol

from models import Performance


class ITTSProvider(Protocol):
    """Performance → 音声ファイル。"""

    name: str

    def synthesize(self, text: str, perf: Performance, out_path: Path) -> None: ...


def _rate_str(pace: float) -> str:
    pct = int(round((pace - 1.0) * 100))
    return f"{pct:+d}%"


def _pitch_str(pitch: float) -> str:
    # -1.0..1.0 → -30..+30 Hz（edge-tts は "+10Hz" 形式の整数を要求する）
    hz = int(round(pitch * 30))
    return f"{hz:+d}Hz"


def _volume_str(volume: float) -> str:
    pct = int(round((volume - 1.0) * 50))
    return f"{pct:+d}%"


class EdgeTTSProvider:
    """edge-tts（Microsoft Edge の音声ネットワーク）を使う実装。"""

    name = "edge"

    def __init__(self, default_voice: str = "ja-JP-NanamiNeural") -> None:
        self.default_voice = default_voice

    def synthesize(self, text: str, perf: Performance, out_path: Path) -> None:
        import edge_tts

        voice = perf.voice or self.default_voice
        voice = _VOICE_NAME_MAP.get(voice, voice)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        communicate = edge_tts.Communicate(
            text,
            voice,
            rate=_rate_str(perf.pace),
            pitch=_pitch_str(perf.pitch),
            volume=_volume_str(perf.volume),
        )
        asyncio.run(communicate.save(str(out_path)))


class AivisSpeechProvider:
    """AivisSpeech Engine (http://127.0.0.1:10101) を使う実装。Phase 4 で本格対応。"""

    name = "aivis"

    def __init__(self, host: str = "http://127.0.0.1:10101", speaker: int = 0) -> None:
        self.base_url = host.rstrip("/")
        self.speaker = speaker  # TODO: キャラごとの style_id 割当

    def synthesize(self, text: str, perf: Performance, out_path: Path) -> None:
        import httpx

        out_path.parent.mkdir(parents=True, exist_ok=True)
        query = httpx.post(
            f"{self.base_url}/audio_query",
            params={"text": text, "speaker": self.speaker}, timeout=60.0,
        ).json()
        speed = max(0.5, min(2.0, perf.pace))
        query["speedScale"] = speed
        query["pitchScale"] = max(-0.5, min(0.5, perf.pitch))
        query["volumeScale"] = max(0.1, min(2.0, perf.volume))
        wav = httpx.post(
            f"{self.base_url}/synthesis",
            params={"speaker": self.speaker}, json=query, timeout=120.0,
        ).content
        out_path.write_bytes(wav)


# voice_id → edge-tts ボイス名（poC と同じマップ）
_VOICE_NAME_MAP = {
    "voice_01": "ja-JP-KeitaNeural",
    "voice_02": "ja-JP-NanamiNeural",
    "voice_03": "ja-JP-NanamiNeural",
    "voice_04": "ja-JP-KeitaNeural",
    "voice_narrator": "ja-JP-KeitaNeural",
}


def get_provider(name: str) -> ITTSProvider:
    if name == "aivis":
        return AivisSpeechProvider()
    return EdgeTTSProvider()
