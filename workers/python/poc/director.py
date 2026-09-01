"""Voice Director — Voice Profile × セグメント状態 → Performance（演技指示）。

Phase 0 はルールベース。Phase 2 で LLM + Rule Engine のハイブリッドに進化させる。
キャスティング（Voice Profile の割り当て）もここで行う。
"""

from __future__ import annotations

from models import Character, DirectedSegment, Performance, Segment, StoryState, VoiceProfile
from schema import MODES_BY_TYPE, clamp, normalize_emotion

NARRATOR_ID = "narrator"

# ---------------------------------------------------------------- 音声プール

VOICE_POOL: dict[str, VoiceProfile] = {
    "voice_01": VoiceProfile(voice_id="voice_01", label="女性・若年 A", gender="female",
                             age="young", tts_voice="ja-JP-NanamiNeural"),
    "voice_02": VoiceProfile(voice_id="voice_02", label="男性・成人 A", gender="male",
                             age="adult", tts_voice="ja-JP-KeitaNeural"),
    "voice_03": VoiceProfile(voice_id="voice_03", label="女性・成人 B（低め）", gender="female",
                             age="adult", tts_voice="ja-JP-NanamiNeural", base_pitch=-0.12),
    "voice_04": VoiceProfile(voice_id="voice_04", label="男性・若年 B（高め）", gender="male",
                             age="young", tts_voice="ja-JP-KeitaNeural", base_pitch=0.10),
}

NARRATOR_VOICE = VoiceProfile(
    voice_id="voice_narrator", label="ナレーター（落ち着き）", gender="male",
    age="adult", tts_voice="ja-JP-KeitaNeural", base_pace=0.9, base_pitch=-0.05,
)

# ---------------------------------------------------------------- 感情ルール

# emotion → (pace_delta, pitch_delta, volume_delta)
EMOTION_RULES: dict[str, tuple[float, float, float]] = {
    "neutral":   (0.00,  0.00,  0.00),
    "calm":      (-0.03,  0.00, -0.02),
    "happy":     (+0.10, +0.06, +0.05),
    "sad":       (-0.14, +0.03, -0.08),
    "angry":     (+0.16, -0.05, +0.15),
    "fearful":   (+0.15, +0.08, -0.05),
    "anxious":   (-0.04, +0.04, -0.03),
    "surprised": (+0.12, +0.10, +0.10),
    "sarcastic": (-0.02, -0.02,  0.00),
    "tender":    (-0.10, +0.02, -0.06),
}

# モード別の基本ペース調整
MODE_PACE = {"narration": -0.05, "dialogue": 0.00, "internal": -0.12}


# ---------------------------------------------------------------- キャスティング


class CastingDirector:
    """登場キャラクターに Voice Profile を割り当てる。"""

    def assign_voices(self, state: StoryState) -> list[str]:
        """まだボイスのないキャラクターへ Voice Profile を割り当てる。

        Returns: 新しく割り当てたキャラクター名のリスト
        """
        assigned: list[str] = []
        female = male = 0
        for ch in state.characters.values():
            if ch.voice is not None or ch.id == NARRATOR_ID:
                continue
            if ch.gender == "female":
                profile = self._pick(["voice_01", "voice_03"], female, 1.0)
                female += 1
            elif ch.gender == "male":
                profile = self._pick(["voice_02", "voice_04"], male, -1.0)
                male += 1
            else:
                # 性別不明は交互に振る
                if female <= male:
                    profile = self._pick(["voice_01", "voice_03"], female, 1.0)
                    female += 1
                else:
                    profile = self._pick(["voice_02", "voice_04"], male, -1.0)
                    male += 1
            ch.voice = profile
            assigned.append(ch.name)
        return assigned

    @staticmethod
    def _pick(candidates: list[str], index: int, pitch_dir: float) -> VoiceProfile:
        if index < len(candidates):
            return VOICE_POOL[candidates[index]].model_copy()
        # プールを使い切ったらピッチを少しずつずらして再利用
        base = VOICE_POOL[candidates[index % len(candidates)]].model_copy()
        tier = index // len(candidates)
        base.voice_id = f"{base.voice_id}_alt{tier}"
        base.base_pitch = clamp(base.base_pitch + 0.06 * tier * pitch_dir, -1.0, 1.0)
        return base
# ---------------------------------------------------------------- 演技指示


class RuleBasedDirector:
    """セグメント → Performance を決めるルールエンジン。"""

    def direct(self, segment: Segment, state: StoryState) -> DirectedSegment:
        emotion = normalize_emotion(segment.emotion)
        intensity = clamp(segment.intensity, 0.0, 1.0)
        mode = MODES_BY_TYPE[segment.type]

        if segment.speaker == NARRATOR_ID:
            profile = NARRATOR_VOICE
        else:
            character = state.characters.get(segment.speaker)
            profile = NARRATOR_VOICE if (character is None or character.voice is None) else character.voice

        pace_d, pitch_d, vol_d = EMOTION_RULES.get(emotion, EMOTION_RULES["neutral"])
        # 感情が強いほどルールの影響を大きくする
        strength = 0.5 + intensity

        pace = clamp(profile.base_pace + MODE_PACE[mode] + pace_d * strength, 0.5, 1.5)
        pitch = clamp(
            profile.base_pitch + pitch_d * strength + (-0.02 if mode == "internal" else 0.0),
            -1.0, 1.0,
        )
        volume = clamp(1.0 + vol_d * strength + (-0.05 if mode == "internal" else 0.0), 0.5, 1.5)

        directed = DirectedSegment(**segment.model_dump())
        directed.emotion = emotion
        directed.intensity = intensity
        directed.performance = Performance(
            voice=profile.voice_id,
            mode=mode,
            emotion=emotion,
            intensity=round(intensity, 3),
            pace=round(pace, 3),
            pitch=round(pitch, 3),
            volume=round(volume, 3),
        )
        return directed


def resolve_tts_voice(voice_id: str, state: StoryState) -> VoiceProfile:
    """voice_id から TTS 用の VoiceProfile を引き当てる。"""
    if voice_id == NARRATOR_VOICE.voice_id:
        return NARRATOR_VOICE
    for ch in state.characters.values():
        if ch.voice is not None and ch.voice.voice_id == voice_id:
            return ch.voice
    for vp in VOICE_POOL.values():
        if vp.voice_id == voice_id:
            return vp
    raise KeyError(f"未知の voice_id: {voice_id}")

