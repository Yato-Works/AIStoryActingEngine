"""Irodori-TTS Backend Adapter（Irodori OpenAI TTS Server 用）。

Aratako/Irodori-TTS-Server（OpenAI 互換 POST /v1/audio/speech）を
TTSBackend として実装する。ターゲット: Aratako/Irodori-TTS-v4-Small 系。

Capability:
    speaker_cloning:   native       — voice（voices.json）/ ref_wav / ref_embed
    emotion:           instruction  — VoiceDesign の caption 文に変換
    emotion_intensity: instruction  — caption の強調表現に変換
    speaking_rate:     native       — OpenAI speed パラメータ（0.25..4.0）
    pitch:             unsupported
    energy/volume:     unsupported
    pause:             unsupported（連結は audio.py 側で行う）
    style:             instruction  — caption に織り込む
    text_reading:      instruction  — 読み台本（全文かな）を受け入れる（ADR-0006）

backend_options["irodori"] で受け取れる拡張:
    voice: str              — voices.json のボイス名（既定: "none" = 文字のみ）
    caption: str            — 明示的な演出キャプション（build_caption より優先）
    text_reading: str       — Script Writer が作った全文かなテキスト
    dictionary: ReadingDictionary — 辞書を適用してから送る
    emoji: bool             — 感情絵文字を文末に注入（既定 False）
    server: dict            — IrodoriOptions への追加フィールド（そのまま透過）
"""

from __future__ import annotations

import os
from pathlib import Path

from acting_ir import ActingIR
from tts_backend import (
    BackendManifest, CapabilityLevel, ResolutionReport, TTSBackend,
)

# ============================================================================
# 感情 → 絵文字（ネイティブのスタイル制御。文末に注入する）
# ============================================================================

EMOTION_EMOJI = {
    "happy": "😄", "angry": "😠", "sad": "😢", "fearful": "😨",
    "anxious": "😟", "surprised": "😲", "sarcastic": "🙃",
    "tender": "🥰", "calm": "😌",
}

# ============================================================================
# 感情 → caption 文（instruction 変換）
# ============================================================================

_EMOTION_CAPTION = {
    "neutral":   "落ち着いた、中立的な口調で話す",
    "calm":      "穏やかで静かな口調で落ち着いて話す",
    "happy":     "明るく楽しそうな口調で話す",
    "sad":       "悲しげな口調で弱々しく話す",
    "angry":     "怒りを含んだ鋭い口調で話す",
    "fearful":   "怯えた様子で震える声で話す",
    "anxious":   "不安そうで落ち着きのない口調で話す",
    "surprised": "驚いた様子で声を上げて話す",
    "sarcastic": "皮肉っぽく、わざとらしく聞こえる口調で話す",
    "tender":    "優しく愛情のこもった柔らかい口調で話す",
}

_INTENSITY_MODIFIER = {
    "low":    "わずかに",
    "mid":    "",
    "high":   "強く、はっきりと",
}


def _intensity_tier(intensity: float) -> str:
    if intensity < 0.34:
        return "low"
    if intensity < 0.67:
        return "mid"
    return "high"


def build_caption(ir: ActingIR) -> str:
    """ActingIR から VoiceDesign 用の演出キャプション文を組み立てる。

    感情・強度・話し方モード（narration/dialogue/internal）を
    自然文の演出指示に変換する。
    """
    parts: list[str] = []

    tier = _intensity_tier(ir.emotion_intensity)
    base = _EMOTION_CAPTION.get(ir.emotion, _EMOTION_CAPTION["neutral"])
    if tier == "low" and ir.emotion != "neutral":
        parts.append(f"{_INTENSITY_MODIFIER['low']}{base}")
    elif tier == "high":
        parts.append(f"{_INTENSITY_MODIFIER['high']}{base}")
    else:
        parts.append(base)

    if ir.voicing == "internal" or ir.style == "internal":
        parts.append("内面の独り言として、低く静かに、他人に聞かせない声で")
    elif ir.voicing == "narrator" or ir.style == "narration":
        parts.append("物語の語り手として、聞き手に届く落ち着いた声で")
    elif ir.style == "dialogue":
        parts.append("対話の中で、目の前の相手に向けて話している")

    return "。".join(parts) + "。"


_MANIFEST = BackendManifest(
    backend="irodori",
    version="0.1.0",
    capabilities={
        "speaker_cloning":   CapabilityLevel.NATIVE,
        "emotion":           CapabilityLevel.INSTRUCTION,
        "emotion_intensity": CapabilityLevel.INSTRUCTION,
        "speaking_rate":     CapabilityLevel.NATIVE,
        "pitch":             CapabilityLevel.UNSUPPORTED,
        "energy":            CapabilityLevel.UNSUPPORTED,
        "volume":            CapabilityLevel.UNSUPPORTED,
        "pause":             CapabilityLevel.UNSUPPORTED,
        "style":             CapabilityLevel.INSTRUCTION,
        # ADR-0006: 読み台本（全文かな）を受け入れる能力
        "text_reading":      CapabilityLevel.INSTRUCTION,
    },
)

class IrodoriBackend(TTSBackend):
    """Irodori OpenAI TTS Server の Backend Adapter。

    演者さんメタファー（ADR-0006）: この Backend は「声は天才だが
    漢字が読めない演者さん」。Script Writer の読み台本（text_reading）
    を渡された場合はそれを読み、そうでなければ原文をそのまま渡す。
    """

    def __init__(self, host: str | None = None,
                 api_key: str | None = None,
                 model: str = "irodori-tts",
                 default_voice: str = "none",
                 response_format: str = "wav",
                 timeout: float | None = None) -> None:
        self.base_url = (host or os.environ.get(
            "IRODORI_HOST", "http://127.0.0.1:8088")).rstrip("/")
        self.api_key = api_key or os.environ.get("IRODORI_API_KEY")
        self.model = model
        self.default_voice = default_voice
        self.response_format = response_format
        # GPU 飽和時（デスクトップアプリが VRAM を占有）は 1 合成に
        # 数分かかることがある。IRODORI_TIMEOUT 秒で調整できる。
        self.timeout = float(
            timeout if timeout is not None
            else os.environ.get("IRODORI_TIMEOUT", "600"))

    def manifest(self) -> BackendManifest:
        return _MANIFEST

    # --- テキスト解決（読み台本の消費、ADR-0006 §5） ------------------------

    def resolve_text(self, ir: ActingIR) -> tuple[str, str]:
        """送信するテキストと、解決方法の説明を返す。

        優先順位:
        1. backend_options["irodori"]["text_reading"]（Script Writer の台本）
        2. backend_options["irodori"]["dictionary"] を原文に適用
        3. 原文をそのまま
        """
        opts = ir.backend_options.get("irodori", {})
        text_reading = opts.get("text_reading")
        if isinstance(text_reading, str) and text_reading.strip():
            return text_reading.strip(), "reading-script"
        dictionary = opts.get("dictionary")
        if dictionary is not None and len(dictionary):
            return dictionary.apply(ir.text), "dictionary"
        return ir.text, "raw"

    # --- 合成 ----------------------------------------------------------------

    def synthesize(self, ir: ActingIR, out_path: Path) -> ResolutionReport:
        import httpx

        report = ResolutionReport(backend="irodori")
        opts = ir.backend_options.get("irodori", {})

        # --- Text / 読み台本 (instruction, ADR-0006) ---
        text, source = self.resolve_text(ir)
        report.add("text_reading", ir.text, CapabilityLevel.INSTRUCTION, text,
                   warning=None if source != "raw" else
                   "読み台本なしで原文を送信: 漢字の誤読リスクあり（ADR-0006）")

        # --- Emotion → caption (instruction) ---
        caption = opts.get("caption") or build_caption(ir)
        report.add("emotion", ir.emotion, CapabilityLevel.INSTRUCTION, caption)

        # --- Emotion intensity → caption に織り込み済み ---
        report.add("emotion_intensity", ir.emotion_intensity,
                   CapabilityLevel.INSTRUCTION, _intensity_tier(
                       ir.emotion_intensity))

        # --- Speaking rate → OpenAI speed (native) ---
        speed = round(max(0.25, min(4.0, ir.speaking_rate)), 3)
        report.add("speaking_rate", ir.speaking_rate,
                   CapabilityLevel.NATIVE, speed)

        # --- 未対応パラメータは黙って無視しない（設計書 §5） ---
        report.add("pitch", ir.pitch, CapabilityLevel.UNSUPPORTED, None,
                   warning="Irodori は pitch 制御に対応していません")
        report.add("volume", ir.volume, CapabilityLevel.UNSUPPORTED, None,
                   warning="Irodori は volume 制御に対応していません")
        report.add("pause", (ir.pause_before, ir.pause_after),
                   CapabilityLevel.UNSUPPORTED, None,
                   warning="pause は audio.py 側の連結で処理してください")

        # --- 絵文字注入（ネイティブのスタイル制御） ---
        if opts.get("emoji") and ir.emotion in EMOTION_EMOJI:
            text = f"{text}{EMOTION_EMOJI[ir.emotion]}"

        # --- リクエスト構築 ---
        # server_opts で IrodoriOptions を透過制御できる。
        # 特に chunking_enabled/chunk_min_chars はサーバー側のテキスト分割合成
        # （既定 min_chars=80、「、」でも分割）の制御に使う。サーバーは分割
        # チャンクを無音なしで連結するため、文節の継ぎ目が硬く聞こえる
        # （「かくかく」症状）場合は chunking_enabled=False で無効化できる。
        server_opts: dict = dict(opts.get("server") or {})
        if "chunking_enabled" not in server_opts:
            env_chunk = os.environ.get("IRODORI_CHUNKING")
            if env_chunk is not None:
                server_opts["chunking_enabled"] = env_chunk.strip() in (
                    "1", "true", "yes", "on")
        body: dict = {
            "model": self.model,
            "input": text,
            "voice": opts.get("voice", self.default_voice),
            "response_format": opts.get(
                "response_format", self.response_format),
            "speed": speed,
            "irodori": {
                "caption": caption,
                **server_opts,
            },
        }

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        resp = httpx.post(f"{self.base_url}/v1/audio/speech", json=body,
                          headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        out_path.write_bytes(resp.content)
        return report

