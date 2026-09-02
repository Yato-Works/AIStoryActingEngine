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


def emotion_style(emotion: str, intensity: float = 0.3, seed: int | None = 42) -> tuple[float, float, float]:
    """感情・強度・seed -> (pace倍率, pitch加算, volume)。

    3.5C Micro Prosody: seed 固定で再現可能な micro variation。
    seed は character_seed ^ emotion_seed ^ scene_seed ^ utterance_seed を推奨。
    毎回同じ固定値震えを防ぐ。"""
    (p0, pb), (q0, qb), (r0, rb) = _EMOTION_STYLE.get(
        contracts.normalize_emotion(emotion), _EMOTION_STYLE_DEFAULT)
    boost = contracts.clamp(intensity, 0.0, 1.0)
    pace = p0 + pb * boost
    pitch = q0 + qb * boost
    volume = r0 + rb * boost
    import random as _rng
    rng = _rng.Random(seed)
    pace += rng.uniform(-0.02, 0.02)
    pitch += rng.uniform(-0.04, 0.04)
    volume += rng.uniform(-0.03, 0.03)
    return round(pace, 4), round(pitch, 4), contracts.clamp(round(volume, 4), 0.5, 1.5)


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

# ---------------------------------------------------------------- 3.5D Time-based Prosody
# "emotion_style" (Micro Variation v1) は声全体のパラメータを揺らすだけ。
# ここでは "演技を時間軸上でどう聴かせるか" を決める phrase-level curve を返す。
# seed 固定 -> 同じ Story/Character/Scene/Seed なら同じ Performance (再生可能)。

INTENT_SHAPES = {
    "neutral":              {"speed":[1.00,1.00,1.00,1.00], "pitch":[0.00,0.00,0.00,0.00], "energy":[0.85,0.85,0.85,0.85]},
    "hesitant_denial":      {"speed":[0.88,0.80,1.00,0.85], "pitch":[-0.05,-0.10,0.00,-0.05], "energy":[0.60,0.45,0.70,0.55]},
    "reluctant_agreement":  {"speed":[0.90,0.80,0.85,1.00], "pitch":[-0.02,-0.03,0.00,0.03], "energy":[0.55,0.50,0.60,0.85]},
    "suppressed_anger":     {"speed":[0.95,0.90,1.00,0.80], "pitch":[0.00,0.00,0.04,-0.06], "energy":[0.55,0.50,0.90,0.40]},
    "realization":          {"speed":[0.82,1.00,1.18,1.00], "pitch":[0.00,0.05,0.14,0.06], "energy":[0.40,0.60,1.00,0.75]},
    "whispered_confession": {"speed":[0.85,0.90,0.95,0.80], "pitch":[-0.06,-0.04,0.00,-0.03], "energy":[0.30,0.35,0.40,0.30]},
    "awkward_silence":      {"speed":[0.70,1.00,0.60,0.90], "pitch":[-0.04,0.00,-0.02,0.01], "energy":[0.20,0.60,0.15,0.50]},
    "deadpan":              {"speed":[1.00,0.95,1.05,1.00], "pitch":[0.00,0.00,0.00,0.00], "energy":[0.65,0.60,0.70,0.65]},
    "suppressed_laughter":  {"speed":[0.88,1.12,0.92,0.88], "pitch":[0.00,0.10,0.05,0.00], "energy":[0.40,0.95,0.60,0.45]},
}


def normalize_intent(raw):
    """LLM 出力の intent 語彙を INTENT_SHAPES キーへ正規化。未知は neutral。"""
    if not isinstance(raw, str) or not raw.strip():
        return "neutral"
    key = raw.strip().lower().replace(" ", "_")
    return key if key in INTENT_SHAPES else "neutral"


EMOTION_TO_INTENT = {
    "anxious": "hesitant_denial",
    "angry": "suppressed_anger",
    "sad": "whispered_confession",
    "surprised": "realization",
    "happy": "suppressed_laughter",
    "fearful": "awkward_silence",
    "tender": "reluctant_agreement",
    "sarcastic": "suppressed_anger",
}


def emotion_to_intent(emotion):
    """emotion -> Intent への推定（未知は neutral）。Voice Director が決める本来の Intent は、
    後で LLM/シーン文脈から上書きされる。"""
    from schema import normalize_emotion
    return EMOTION_TO_INTENT.get(normalize_emotion(emotion))


def _interp_shape(anchors, n):
    """4-anchored intent shape を n phrases 用に補間/間引き。"""
    if n <= 0:
        return []
    if n == 1:
        return [sum(anchors) / len(anchors)]
    if n == len(anchors):
        return list(anchors)
    if n < len(anchors):
        return [anchors[int(round(i * (len(anchors) - 1) / (n - 1)))] for i in range(n)]
    out = []
    for k in range(n):
        x = k * (len(anchors) - 1) / (n - 1)
        i0 = int(x)
        frac = x - i0
        i1 = min(i0 + 1, len(anchors) - 1)
        out.append(anchors[i0] + (anchors[i1] - anchors[i0]) * frac)
    return out


def plan_prosody(emotion="neutral", intensity=0.3, intent=None, num_phrases=4,
                 seed=42, base_phrase_ms=920.0):
    """Time-based Prosody: phrase-level speed/pitch/energy + timing_ms。

    毎回同じ固定値震えを避ける seed-based phrase-local micro jitter を加えるが、
    seed 固定なら再生可能。"""
    import random as _random
    intent_key = normalize_intent(intent)
    shape = INTENT_SHAPES[intent_key]
    base_pace, base_pitch, base_volume = emotion_style(emotion, intensity, seed=seed)
    speed = _interp_shape(shape["speed"], num_phrases)
    pitch = _interp_shape(shape["pitch"], num_phrases)
    energy = _interp_shape(shape["energy"], num_phrases)
    cur_sp, cur_pi, cur_en, timing = [], [], [], []
    onset = 0.0
    for i in range(num_phrases):
        ms = speed[i] * base_pace
        mi = pitch[i] + base_pitch
        me = energy[i] * base_volume
        local = _random.Random(seed ^ (i * 7919) ^ 0x9E37)
        ms += local.uniform(-0.015, 0.015)
        mi += local.uniform(-0.030, 0.030)
        me += local.uniform(-0.020, 0.020)
        cur_sp.append(round(contracts.clamp(ms, 0.5, 1.5), 4))
        cur_pi.append(round(contracts.clamp(mi, -1.0, 1.0), 4))
        cur_en.append(round(contracts.clamp(me, 0.2, 1.5), 4))
        timing.append(round(onset, 1))
        onset += base_phrase_ms / cur_sp[-1]
    return {
        "intent": intent_key,
        "speed": cur_sp,
        "pitch": cur_pi,
        "energy": cur_en,
        "timing_ms": timing,
        "total_ms": round(onset, 1),
    }


def timing_humanize(text, emotion="neutral", intent=None, seed=42):
    """Text -> humanized phrase timing (semantic phrase boundary)。

    文章を「。、！？」等の意味区切りで phrase に切り、plan_prosody の phrase curve を当てる。
    単純句点分割ではなく Voice Director が breath unit で区切るイメージ。"""
    import re as _re
    raw = _re.split(r"[。、．，！？!?]", text)
    phrases = [ph.strip() for ph in raw if ph.strip()]
    n = max(len(phrases), 1)
    plan = plan_prosody(emotion, intent=intent, num_phrases=n, seed=seed)
    return [{"text": phrases[i],
             "speed": plan["speed"][i],
             "pitch": plan["pitch"][i],
             "energy": plan["energy"][i],
             "onset_ms": plan["timing_ms"][i]} for i in range(n)]

# ---------------------------------------------------------------- 3.5F Character Voice Memory
# VoiceProfile = キャラクターの演技DNA（不変）。VoiceState = 現在の演技状態（可変）。
# apply_voice_state は time-based prosody curve を state x profile で変調し、
# 「同じ台詞でもキャラ・状態によって全く違う発話」を実現する。

def _state_deltas(state):
    """VoiceState -> (speed_mult, pitch_add, energy_mult, pause_mult, breath_freq, hesitation)。"""
    if state is None:
        return 1.0, 0.0, 1.0, 1.0, 0.0, 0.0
    t = float(state.tension); f = float(state.fatigue)
    c = float(state.confidence); e = float(state.excitement)
    # ---- 3.5Q: SceneEvent 由来の拡張状態（無い属性は 0 扱いで後方互換）----
    fe = float(getattr(state, "fear", 0.0) or 0.0)
    an = float(getattr(state, "anger", 0.0) or 0.0)
    sa = float(getattr(state, "sadness", 0.0) or 0.0)
    em = float(getattr(state, "embarrassment", 0.0) or 0.0)
    speed = (1.0 + 0.10 * e + 0.08 * c - 0.12 * f - 0.06 * t
             + 0.10 * an - 0.08 * sa)
    pitch = (0.03 * e + 0.05 * c - 0.08 * f + 0.06 * t
             + 0.08 * fe + 0.05 * an - 0.06 * sa)
    energy = (1.0 + 0.15 * e + 0.10 * c - 0.15 * f - 0.10 * t
              + 0.20 * an - 0.15 * sa - 0.05 * fe)
    pause = 1.0 + 0.20 * t + 0.15 * f - 0.10 * c + 0.15 * fe + 0.10 * em
    breath = 0.30 * t + 0.35 * f - 0.15 * e + 0.25 * fe + 0.10 * em
    hesit = 0.40 * t + 0.25 * f - 0.20 * c + 0.30 * em + 0.20 * fe
    return speed, pitch, energy, pause, breath, hesit


def _timing_jitter(seed, idx):
    """キャラクター固有のタイミング癖：seed 固定で再生可能な onset jitter。"""
    import random as _r
    r = _r.Random(seed ^ (idx * 7919) ^ 0x5A5A5A5A)
    return r.uniform(-1.0, 1.0)


def apply_voice_state(plan, profile, state=None, seed=42):
    """3.5F/3.5H: plan_prosody curve に VoiceProfile + VoiceState の変調を適用。seed 固定で再生可能。

    timing_habit はキャラクター固有の「喋りのタイミング癖」（3.5H Timing Humanization）
    を phrase onset に微小オフセットとして加える。"""
    import copy
    p = copy.deepcopy(plan)
    spd_s, pit_s, ene_s, pause_s, breath_s, hesit_s = _state_deltas(state)
    pb = float(getattr(profile, "base_pace", 1.0) or 1.0)
    pp = float(getattr(profile, "base_pitch", 0.0) or 0.0)
    pe = float(getattr(profile, "base_energy", 0.8) or 0.8)
    drop = float(getattr(profile, "sentence_end_drop", 0.0) or 0.0)
    emp = float(getattr(profile, "emphasis_strength", 0.0) or 0.0)
    pause_tend = float(getattr(profile, "pause_tendency", 0.0) or 0.0)
    hesit_tr = float(getattr(profile, "hesitation", 0.0) or 0.0)
    timing_habit = float(getattr(profile, "timing_habit", 0.0) or 0.0)
    n = len(p["speed"])
    total = float(p.get("total_ms", 0.0))
    base_ms = (total / n) if (n and total) else 920.0
    on = 0.0
    ns, nppitch, ne, nt = [], [], [], []
    for i in range(n):
        s = p["speed"][i] * pb * spd_s
        pi = p["pitch"][i] + pp + pit_s
        en = p["energy"][i] * pe * (0.5 + 0.5 * ene_s)
        if i == n - 1:
            s *= (1.0 - 0.12 * drop)
            pi -= 0.05 * drop
        if emp > 0 and i == n // 2:
            s *= (1.0 + 0.05 * emp)
            en *= (1.0 + 0.08 * emp)
            pi += 0.03 * emp
        s = round(contracts.clamp(s, 0.5, 1.5), 4)
        pi = round(contracts.clamp(pi, -1.0, 1.0), 4)
        en = round(contracts.clamp(en, 0.2, 1.5), 4)
        ns.append(s); nppitch.append(pi); ne.append(en)
        nt.append(round(on, 1))
        gap = base_ms / s
        if i > 0:
            gap += (pause_tend * 0.5 + hesit_tr * 0.4 + max(hesit_s, 0.0)) * 150.0
            gap += timing_habit * _timing_jitter(seed, i) * 40.0
        on += gap
    p["speed"] = ns; p["pitch"] = nppitch; p["energy"] = ne
    p["timing_ms"] = nt; p["total_ms"] = round(on, 1)
    p["pause_tendency"] = round(pause_tend * pause_s, 3)
    p["hesitation"] = round(hesit_tr + max(hesit_s, 0.0), 3)
    p["breath_frequency"] = round(max(breath_s, 0.0), 3)
    return p


def voice_vocalization(profile, intent_key):
    """3.5F: intent に応じてキャラクター特有の口頭語/躊躇を返す（habits テーブル）。"""
    habits = dict(getattr(profile, "habits", {}) or {})
    mapping = {
        "hesitant_denial": habits.get("disbelief"),
        "reluctant_agreement": habits.get("thinking"),
        "suppressed_laughter": habits.get("surprise"),
        "awkward_silence": habits.get("thinking"),
    }
    return mapping.get(intent_key) or habits.get("thinking") or "え"
