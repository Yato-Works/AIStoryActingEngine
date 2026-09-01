"""CastingDirector（配役）と RuleBasedDirector（演出）。

Phase 1: RuleBasedDirector は Memory Engine の get_carryover() を受け取り、
「前のチャンクの強い感情」を減衰させて次の演技に滲ませる。
"""

from __future__ import annotations

from models import Character, DirectedSegment, Performance, Segment, StoryState, VoiceProfile
import schema as contracts

NARRATOR = "narrator"

# ボイスプール（Phase 0 と同じ 4 枠 + ナレーター固定）
VOICE_POOL = [
    VoiceProfile(voice_id="voice_01", label="若い男性", gender="male", age="young",
                 base_pitch=0.05, base_pace=1.05, tts_voice="ja-JP-KeitaNeural"),
    VoiceProfile(voice_id="voice_02", label="若い女性", gender="female", age="young",
                 base_pitch=0.12, base_pace=1.0, tts_voice="ja-JP-NanamiNeural"),
    VoiceProfile(voice_id="voice_03", label="落ち着いた女性", gender="female", age="adult",
                 base_pitch=-0.02, base_pace=0.95, tts_voice="ja-JP-NanamiNeural"),
    VoiceProfile(voice_id="voice_04", label="渋い男性", gender="male", age="elder",
                 base_pitch=-0.10, base_pace=0.90, tts_voice="ja-JP-KeitaNeural"),
]

NARRATOR_VOICE = VoiceProfile(
    voice_id="voice_narrator", label="ナレーター", gender="male", age="adult",
    base_pitch=0.0, base_pace=0.92, tts_voice="ja-JP-KeitaNeural")


class CastingDirector:
    """キャラクターに Voice Profile を割り当てる（割当済みは尊重）。"""

    def assign_voices(self, state: StoryState) -> list[str]:
        assigned: list[str] = []
        used_ids = {ch.voice.voice_id for ch in state.characters.values() if ch.voice}
        for ch in state.characters.values():
            if ch.voice is not None:
                continue
            profile = self._pick(ch, used_ids)
            ch.voice = profile
            used_ids.add(profile.voice_id)
            assigned.append(ch.id)
        return assigned

    @staticmethod
    def _pick(ch: Character, used_ids: set[str]) -> VoiceProfile:
        for profile in VOICE_POOL:
            if profile.voice_id in used_ids:
                continue
            if profile.gender == ch.gender and profile.age == ch.age:
                return profile
        for profile in VOICE_POOL:
            if profile.voice_id not in used_ids:
                return profile
        return VOICE_POOL[0]


class RuleBasedDirector:
    """Performance（感情 × ボイス）を決めるルールベースの演出家。"""

    def direct(self, segment: Segment, state: StoryState,
               carryover: tuple[str, float] | None = None) -> DirectedSegment:
        speaker = state.characters.get(segment.speaker)
        voice_id = speaker.voice.voice_id if (speaker and speaker.voice) else NARRATOR_VOICE.voice_id
        base_pitch = speaker.voice.base_pitch if (speaker and speaker.voice) else 0.0
        base_pace = speaker.voice.base_pace if (speaker and speaker.voice) else 1.0

        mode = contracts.MODES_BY_TYPE.get(segment.type, "narration")
        emotion = contracts.normalize_emotion(segment.emotion)
        intensity = contracts.clamp(segment.intensity, 0.0, 1.0)
        carried = False

        # --- 感情の余韻（Phase 1 の目玉） ---
        if carryover is not None:
            c_emotion, c_intensity = carryover
            weak = emotion == "neutral" or intensity <= 0.3
            if weak and c_intensity >= 0.4:
                # LLM は中立/弱い感情と言ったが、直前の感情が強い → 残響を適用
                emotion = c_emotion
                intensity = contracts.clamp(max(intensity, c_intensity), 0.0, 1.0)
                carried = True
            elif emotion == c_emotion:
                # 同じ感情なら持続として少し強める
                intensity = max(intensity, min(1.0, c_intensity * 0.8))

        pace, pitch, volume = self._style(emotion, intensity)
        performance = Performance(
            voice=voice_id,
            mode=mode,  # type: ignore[arg-type]
            emotion=emotion,
            intensity=intensity,
            pace=round(base_pace * pace, 3),
            pitch=round(base_pitch + pitch, 3),
            volume=volume,
            carryover=carried,
        )
        return DirectedSegment(**segment.model_dump(), performance=performance)

    def _style(self, emotion: str, intensity: float) -> tuple[float, float, float]:
        """(pace倍率, pitch加算, volume) を感情と強度から決める。"""
        boost = intensity  # 0.0..1.0
        table = {
            "calm":      (1.00, 0.00, 1.00),
            "neutral":   (1.00, 0.00, 1.00),
            "happy":     (1.00 + 0.15 * boost, 0.05 + 0.05 * boost, 1.00 + 0.1 * boost),
            "tender":    (0.92 - 0.06 * boost, 0.04 + 0.03 * boost, 0.95),
            "sad":       (0.85 - 0.05 * boost, -0.04 - 0.04 * boost, 0.90 - 0.05 * boost),
            "angry":     (1.10 + 0.15 * boost, -0.02 - 0.08 * boost, 1.10 + 0.25 * boost),
            "fearful":   (1.05 + 0.15 * boost, 0.03 + 0.05 * boost, 0.85),
            "anxious":   (0.95 + 0.08 * boost, 0.02 + 0.03 * boost, 0.95),
            "surprised": (1.08 + 0.12 * boost, 0.06 + 0.06 * boost, 1.05 + 0.15 * boost),
            "sarcastic": (0.95, -0.03, 1.00),
        }
        pace, pitch, volume = table.get(emotion, (1.0, 0.0, 1.0))
        # 心の声は少し遅く・小さく（内省のトーン）
        # → mode 依存の補正は direct() 側ではなくここでは行わない（シンプル保持）
        return pace, pitch, contracts.clamp(volume, 0.5, 1.5)
