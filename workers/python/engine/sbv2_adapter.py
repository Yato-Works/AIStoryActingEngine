"""Phase 3.5K - SBV2 Performance Adapter。

Human Voice Engine の演技資産（intent / prosody_curve / VoiceProfile / VoiceState）を
Style-Bert-VITS2 の inference パラメータに翻訳する。TTSプロバイダを演技資産から分離し、
プロバイダを変えても AEP（演出資産）は残る。
"""
from __future__ import annotations

from pathlib import Path

from models import Performance, VoiceProfile


EMOTION_TO_STYLE = {
    "happy": "Joyful", "angry": "Angry", "sad": "Sad", "fearful": "Fearful",
    "surprised": "Surprise", "tender": "Tender", "sarcastic": "Sarcasm",
    "anxious": "Anxious", "calm": "Calm", "neutral": "Neutral",
}

INTENT_TO_EMOTION = {
    "hesitant_denial": "anxious",
    "suppressed_anger": "angry",
    "reluctant_agreement": "tender",
    "whispered_confession": "sad",
    "realization": "surprised",
    "awkward_silence": "calm",
    "suppressed_laughter": "happy",
}
INTENT_TO_STYLE = {
    "hesitant_denial": "Anxious",
    "suppressed_anger": "Angry",
    "reluctant_agreement": "Tender",
    "whispered_confession": "Sad",
    "realization": "Joyful",
    "awkward_silence": "Calm",
    "suppressed_laughter": "Joyful",
}


def intent_to_emotion(intent):
    from director import normalize_intent
    key = normalize_intent(intent)
    return INTENT_TO_EMOTION.get(key, "neutral")


def intent_to_style(intent):
    from director import normalize_intent
    key = normalize_intent(intent)
    return INTENT_TO_STYLE.get(key)


def segment_sbv2_params(idx, plan, profile=None):
    """phrase idx の prosody curve を SBV2 length / f0_adjust / volume へマッピング。"""
    speeds = plan.get("speed", [])
    pitches = plan.get("pitch", [])
    energies = plan.get("energy", [])
    n = len(speeds)
    spd = speeds[idx] if idx < n else 1.0
    pit = pitches[idx] if idx < n else 0.0
    ene = energies[idx] if idx < n else 0.8
    pb = float(getattr(profile, "base_pace", 1.0) or 1.0) if profile else 1.0
    pp = float(getattr(profile, "base_pitch", 0.0) or 0.0) if profile else 0.0
    length = round(max(0.5, min(2.0, (1.0 / max(0.1, spd)) / pb)), 3)
    f0_adjust = round(pp + pit, 4)
    volume = round(max(0.1, min(2.0, ene)), 3)
    return {"length": length, "f0_adjust": f0_adjust, "volume": volume}


class Sbv2PerformanceSynthesizer:
    """Speech Segment を SBV2 provider へ：curve 変調を反映した Performance で合成。"""

    def __init__(self, provider=None):
        self.provider = provider

    def _ensure_provider(self):
        if self.provider is None:
            from tts import StyleBertVITS2Provider
            self.provider = StyleBertVITS2Provider()
        return self.provider

    def _perf_for(self, segment, plan, profile, idx):
        params = segment_sbv2_params(idx, plan, profile)
        emotion = intent_to_emotion(plan.get("intent"))
        style = intent_to_style(plan.get("intent")) or (
            (profile.sbv2_style if profile else None) or "Neutral")
        n = len(plan.get("speed", []))
        intensity = round(max(0.0, min(1.0, 0.3 + params["volume"] * 0.5)), 2)
        pace = plan["speed"][idx] if idx < n else 1.0
        return Performance(
            voice=profile.voice_id if profile else "voice_narrator",
            mode="dialogue",
            emotion=emotion,
            intensity=intensity,
            pace=pace,
            pitch=params["f0_adjust"],
            volume=params["volume"],
            style=style,
            voicing="external",
        )

    def synthesize_segments(self, segments, plan, profile, out_dir):
        """segments(list[SpeechSegment]) + plan -> wav パスリスト。pause は Audio Composer 注入のためスキップ。"""
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        provider = self._ensure_provider()
        wavs = []
        idx = 0
        for seg in segments:
            if seg.type == "pause":
                continue
            perf = self._perf_for(seg, plan, profile, idx if seg.type == "speech" else 0)
            if seg.type == "vocalization":
                perf = Performance(
                    voice=perf.voice, mode=perf.mode, emotion=perf.emotion,
                    intensity=round(perf.intensity * 0.6, 2),
                    pace=perf.pace, pitch=perf.pitch, volume=perf.volume,
                    style=perf.style, voicing=perf.voicing)
            out = out_dir / ("seg_%03d.wav" % len(wavs))
            provider.synthesize(seg.text, perf, out)
            wavs.append(out)
            if seg.type == "speech":
                idx += 1
        return wavs
