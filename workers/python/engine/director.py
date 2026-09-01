"""CastingDirector（配役）と RuleBasedDirector / CharacterAwareDirector（演出）。

Phase 2: Character Intelligence
- CastingDirector は External（外向き）と Internal（内面）の 2 声を割り当てる。
  LLM キャスティング（suggest_voice）に失敗したら性別・年齢ルールへフォールバック。
- CharacterAwareDirector は Dossier（人物+関係+記憶）だけを入力に演技を決める:
  「同じ台詞でも、好きな相手に言う時と怒っている相手に言う時で演じ分ける」。
"""

from __future__ import annotations

from models import Character, Dossier, DirectedSegment, Performance, Segment, StoryState, VoiceProfile
import schema as contracts
from voices import (NARRATOR, NARRATOR_VOICE,  # noqa: F401  (再輸出: 後方互換)
                    NARRATOR_VOICE_INTERNAL, INTERNAL_POOL, VOICE_POOL)

# 感情 → ((pace定数, pace強度係数), (pitch定数, pitch強度係数), (volume定数, volume強度係数))
# 値 = 定数 + 強度係数 × intensity。RuleBased / CharacterAware 共通。
_EMOTION_STYLE = {
    "calm":      ((1.00, 0.00), (0.00, 0.00), (1.00, 0.00)),
    "neutral":   ((1.00, 0.00), (0.00, 0.00), (1.00, 0.00)),
    "happy":     ((1.00, 0.15), (0.05, 0.05), (1.00, 0.10)),
    "tender":    ((0.92, -0.06), (0.04, 0.03), (0.95, 0.00)),
    "sad":       ((0.85, -0.05), (-0.04, -0.04), (0.90, -0.05)),
    "angry":     ((1.10, 0.15), (-0.02, -0.08), (1.10, 0.25)),
    "fearful":   ((1.05, 0.15), (0.03, 0.05), (0.85, 0.00)),
    "anxious":   ((0.95, 0.08), (0.02, 0.03), (0.95, 0.00)),
    "surprised": ((1.08, 0.12), (0.06, 0.06), (1.05, 0.15)),
    "sarcastic": ((0.95, 0.00), (-0.03, 0.00), (1.00, 0.00)),
}
_EMOTION_STYLE_DEFAULT = ((1.0, 0.0), (0.0, 0.0), (1.0, 0.0))


def emotion_style(emotion: str, intensity: float) -> tuple[float, float, float]:
    """感情と強度 → (pace倍率, pitch加算, volume)。強度で係数が強まる。"""
    (p0, pb), (q0, qb), (r0, rb) = _EMOTION_STYLE.get(emotion, _EMOTION_STYLE_DEFAULT)
    boost = intensity  # 0.0..1.0
    pace = p0 + pb * boost
    pitch = q0 + qb * boost
    volume = r0 + rb * boost
    return pace, pitch, contracts.clamp(volume, 0.5, 1.5)




class CastingDirector:
    """キャラクターに External / Internal の Voice Profile を割り当てる。

    suggest（LLM キャスティング関数）が渡されれば提案を採用し、
    失敗・不備なら性別/年齢ルールへフォールバックする。
    """

    def assign_voices(self, state: StoryState,
                      suggest=None) -> list[str]:
        """新規に声を割り当てたキャラの id リストを返す。"""
        assigned: list[str] = []
        used_ext = {ch.voice.voice_id for ch in state.characters.values() if ch.voice}
        used_int = {ch.voice_internal.voice_id
                    for ch in state.characters.values() if ch.voice_internal}
        for ch in state.characters.values():
            was_new = ch.voice is None or ch.voice_internal is None
            if ch.voice is None:
                ch.voice = self._pick_llm(ch, suggest, used_ext, internal=False) \
                    or self._pick(ch, used_ext, VOICE_POOL)
                used_ext.add(ch.voice.voice_id)
            if ch.voice_internal is None:
                ch.voice_internal = self._pick_llm(ch, suggest, used_int, internal=True) \
                    or self._pick(ch, used_int, INTERNAL_POOL)
                used_int.add(ch.voice_internal.voice_id)
            if was_new:
                assigned.append(ch.id)
        return assigned

    @staticmethod
    def _pick_llm(ch: Character, suggest, used_ids: set[str],
                  internal: bool) -> VoiceProfile | None:
        if suggest is None:
            return None
        key = "internal" if internal else "external"
        pool = INTERNAL_POOL if internal else VOICE_POOL
        try:
            proposal = suggest(ch.model_dump()) or {}
            prop = proposal.get(key) or {}
            vid = str(prop.get("voice_id") or "")
            cand = next((p for p in pool if p.voice_id == vid and vid not in used_ids), None)
            if cand is None:
                return None
            data = cand.model_dump()
            if "pitch" in prop:
                data["base_pitch"] = contracts.clamp(prop["pitch"], -1.0, 1.0)
            if "pace" in prop:
                data["base_pace"] = contracts.clamp(prop["pace"], 0.5, 1.5)
            return VoiceProfile(**data)
        except Exception:
            return None

    @staticmethod
    def _pick(ch: Character, used_ids: set[str],
              pool: list[VoiceProfile]) -> VoiceProfile:
        for profile in pool:
            if profile.voice_id in used_ids:
                continue
            if profile.gender == ch.gender and profile.age == ch.age:
                return profile
        for profile in pool:
            if profile.voice_id not in used_ids:
                return profile
        return pool[0]


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
        """(pace倍率, pitch加算, volume) を感情と強度から決める（共通実装に委譲）。"""
        return emotion_style(emotion, intensity)


# ----------------------------------------------------------------
# Phase 2: CharacterAwareDirector
# ----------------------------------------------------------------

# 関係タイプ → 演技の微調整（相手がいる台詞にのみ適用）
# (pitch加算, pace加算, volume加算)
RELATIONSHIP_STYLE = {
    "loves":       (0.04, -0.05, -0.05),   # 柔らかく、少し甘く
    "best_friend": (0.03, 0.00, 0.00),
    "friend":      (0.02, 0.00, 0.00),
    "family":      (0.02, -0.03, -0.05),
    "rival":       (0.00, 0.05, 0.10),     # 張り詰める
    "enemy":       (-0.04, 0.03, 0.12),    # 冷たく張り上げる
    "despises":    (-0.06, -0.02, 0.05),   # 低位の声で突き放す
    "respects":    (-0.02, -0.06, -0.05),  # 慎重に、少し下げて
    "trusts":      (0.03, -0.02, -0.05),
    "owes":        (-0.02, -0.06, -0.05),  # 恐縮
    "colleague":   (0.00, 0.00, 0.00),
    "acquaintance": (0.00, 0.00, 0.00),
    "other":       (0.00, 0.00, 0.00),
}

# 話し方（speech_style）→ 演技の微調整
SPEECH_STYLE_MOD = {
    "polite":   (0.00, -0.08, -0.05),
    "formal":   (0.00, -0.06, -0.03),
    "casual":   (0.00, 0.00, 0.00),
    "cheerful": (0.04, 0.05, 0.05),
    "rough":    (-0.03, 0.06, 0.10),
    "quiet":    (0.00, -0.06, -0.15),
}


class CharacterAwareDirector:
    """Dossier（人物+関係+記憶）だけを入力に Performance を決める演出家。

    - 感情の余韻（carryover）: Phase 1 と同じ減衰ルール
    - 感情の基調（emotional_baseline）: 中立/弱い感情が基調へ滲む
    - 関係性: dialogue で相手ごとに pitch/pace/volume を微調整
    - 話し方: speech_style で常時調整
    - 内面: inner_monologue は Internal 声 + 低く静か遅く
    """

    def direct(self, segment: Segment, dossier: Dossier) -> DirectedSegment:
        speaker = dossier.character
        mode = contracts.MODES_BY_TYPE.get(segment.type, "narration")
        emotion = contracts.normalize_emotion(segment.emotion)
        intensity = contracts.clamp(segment.intensity, 0.0, 1.0)
        carried = False
        baseline_applied = False

        # --- 1. 感情の余韻（前チャンクの強い感情の残響） ---
        carryover = dossier.carryover
        if carryover is not None:
            c_emotion, c_intensity = carryover
            weak = emotion == "neutral" or intensity <= 0.3
            if weak and c_intensity >= 0.4:
                emotion = c_emotion
                intensity = contracts.clamp(max(intensity, c_intensity), 0.0, 1.0)
                carried = True
            elif emotion == c_emotion:
                intensity = max(intensity, min(1.0, c_intensity * 0.8))

        # --- 2. 感情の基調（その人の「普段の色」へ中立が滲む） ---
        if (not carried and emotion in ("neutral", "calm")
                and speaker.emotional_baseline not in ("neutral", "calm", "")):
            emotion = speaker.emotional_baseline
            intensity = contracts.clamp(
                max(intensity, 0.15 + 0.25 * speaker.emotional_range), 0.0, 1.0)
            baseline_applied = True

        # --- 3. 感情 × 強度 → 基本スタイル ---
        pace, pitch, volume = self._style(emotion, intensity)

        # --- 4. 関係性による演じ分け（聞き手がいる台詞のみ） ---
        rel_type = ""
        if dossier.relationship is not None and mode == "dialogue":
            rel_type = dossier.relationship.type or "other"
            rp, rr, rv = RELATIONSHIP_STYLE.get(rel_type, (0.0, 0.0, 0.0))
            pitch += rp
            pace += rr
            volume += rv

        # --- 5. 話し方（speech_style）の常時調整 ---
        sm_p, sm_r, sm_v = SPEECH_STYLE_MOD.get(speaker.speech_style, (0.0, 0.0, 0.0))
        pitch += sm_p
        pace += sm_r
        volume += sm_v

        # --- 6. ボイス解決（external / internal） ---
        is_internal = mode == "internal"
        profile = speaker.voice_internal if is_internal else speaker.voice
        if speaker.id == NARRATOR:
            voicing = "narrator"
        else:
            voicing = "internal" if is_internal else "external"
        if profile is not None:
            voice_id = profile.voice_id
            base_pitch = profile.base_pitch
            base_pace = profile.base_pace
            style = profile.sbv2_style
        else:
            voice_id = NARRATOR_VOICE.voice_id
            base_pitch, base_pace = 0.0, 1.0
            style = NARRATOR_VOICE.sbv2_style

        if is_internal:
            pace -= 0.06      # 内省は遅く
            pitch -= 0.05     # 低く
            volume *= 0.80    # 静かに

        performance = Performance(
            voice=voice_id,
            mode=mode,  # type: ignore[arg-type]
            emotion=emotion,
            intensity=intensity,
            pace=round(contracts.clamp(base_pace * pace, 0.5, 1.5), 3),
            pitch=round(contracts.clamp(base_pitch + pitch, -1.0, 1.0), 3),
            volume=round(contracts.clamp(volume, 0.5, 1.5), 3),
            voicing=voicing,  # type: ignore[arg-type]
            style=style,
            carryover=carried,
            baseline=baseline_applied,
            relationship=rel_type,
        )
        return DirectedSegment(**segment.model_dump(), performance=performance)

    def _style(self, emotion: str, intensity: float) -> tuple[float, float, float]:
        """(pace倍率, pitch加算, volume) を感情と強度から決める（共通実装に委譲）。"""
        return emotion_style(emotion, intensity)
