"""TTS Provider アダプタ。

ITTSProvider を最初から切っておくのが本プロジェクトの重要原則
（「TTS は交換可能な末端」）。Phase 0 では:

- EdgeTTSProvider    : edge-tts（無料のニューラルボイス、男女複数ボイス、
                       rate/pitch/volume をパフォーマンス値から直接制御可能）
- AivisSpeechProvider: AivisSpeech Engine（ローカル・VOICEVOX互換API）。
                       エンジンが localhost:10101 で起動していれば使用可能。

将来 Style-Bert-VITS2 / Qwen3-TTS はこのインターフェースの実装として追加する。
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path

import httpx

from models import Performance, VoiceProfile


class ITTSProvider(ABC):
    """TTS プロバイダの共通契約。"""

    name: str = "base"

    @abstractmethod
    def synthesize(
        self,
        text: str,
        profile: VoiceProfile,
        performance: Performance,
        out_path: Path,
    ) -> Path:
        """1 セグメントを音声ファイルへ合成する。"""


class EdgeTTSProvider(ITTSProvider):
    """edge-tts アダプタ。Performance 値を rate/pitch/volume にマップする。"""

    name = "edge"

    def synthesize(self, text, profile, performance, out_path):
        import edge_tts  # 遅延 import（他プロバイダ選択時に不要なため）

        rate = f"{round((performance.pace - 1.0) * 100):+d}%"
        pitch_hz = round(performance.pitch * 40)
        pitch = f"{pitch_hz:+d}Hz"
        volume = f"{round((performance.volume - 1.0) * 100):+d}%"

        voice = profile.tts_voice or "ja-JP-NanamiNeural"

        async def _run() -> None:
            communicate = edge_tts.Communicate(
                text, voice, rate=rate, volume=volume, pitch=pitch
            )
            await communicate.save(str(out_path))

        asyncio.run(_run())
        return out_path


class AivisSpeechProvider(ITTSProvider):
    """AivisSpeech Engine（VOICEVOX 互換 HTTP API）アダプタ。

    注意: Phase 0 では emotion/pace 制御は speaker(スタイルID) の選択に限られる。
    セグメント毎の細かい Performance 反映は Phase 4 で強化する。
    """

    name = "aivis"

    def __init__(self, host: str = "http://127.0.0.1:10101", timeout: float = 120.0) -> None:
        self.host = host.rstrip("/")
        self.timeout = timeout

    def synthesize(self, text, profile, performance, out_path):
        # 感情の強さでスタイルを大まかに選ぶ（エンジン側のスタイル構成に依存）
        speaker = 0  # TODO: voice_profiles とのマッピング（Phase 4）
        query = httpx.post(
            f"{self.host}/audio_query",
            params={"text": text, "speaker": speaker},
            timeout=self.timeout,
        )
        query.raise_for_status()
        # Performance を反映できるパラメータがあれば上書き
        q = query.json()
        q["speedScale"] = max(0.5, min(2.0, performance.pace))
        q["pitchScale"] = max(-0.5, min(0.5, performance.pitch * 0.3))
        q["volumeScale"] = max(0.1, min(2.0, performance.volume))
        synth = httpx.post(
            f"{self.host}/synthesis",
            params={"speaker": speaker},
            json=q,
            timeout=self.timeout,
        )
        synth.raise_for_status()
        out_path.write_bytes(synth.content)
        return out_path


def create_provider(name: str) -> ITTSProvider:
    """プロバイダ名からアダプタを生成する。"""
    if name == "edge":
        return EdgeTTSProvider()
    if name == "aivis":
        return AivisSpeechProvider()
    raise ValueError(f"未知の TTS プロバイダ: {name}（edge / aivis が利用可能）")
