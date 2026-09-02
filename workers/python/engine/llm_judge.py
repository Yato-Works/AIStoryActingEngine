"""Phase 3.5N/R - Performance Judge (perceptual QA proxy + acting-correctness)。

注意: HeuristicJudge は本物の LLM ではなく、決定論的なルールベース proxy。
本物の LLM へ差し替え可能な同一インターフェース（evaluate -> JudgeReport）を提供する。
Acoustic QA (3.5I) と組み合わせて「perceptual proxy」として使う。

Phase 3.5R: 「音が綺麗か」ではなく「演技として正しいか」を審査する。
  Story Context + Scene Context + VoiceState + Performance Plan
  + Audio Metrics + Previous Segment
        ↓ Judge
  naturalness / character_consistency / scene_consistency / continuity
        ↓ Decision
  KEEP / RE-PERFORM

- ContextJudge    : 決定論（network 不要）。状態×演技の乖離を検出する
- OllamaJudge     : 実 LLM。失敗時は fallback（既定 ContextJudge）へフォールバック
"""
from __future__ import annotations

import random

from pydantic import BaseModel, Field


JUDGE_PROMPT_TEMPLATE = """以下の音声演技を評価してください。

Text: {text}
Emotion: {emotion} (intensity {intensity})
Intent: {intent}
CharacterState: tension={tension} fatigue={fatigue} confidence={confidence} excitement={excitement}
PerformancePlan: speed={speed} pitch={pitch} energy={energy}

各スコアを 0.0..1.0 で、diagnoses には問題があれば short slug で列挙してください。
"""


JUDGE_CONTEXT_PROMPT = """あなたは音声ドラマの演技監督です。以下の演技を評価してください。

重要: 「音が綺麗か」ではなく「演技として正しいか」を判定してください。
キャラクターの状態・場面・直前の文脈に照らして、この演技が不自然でないかを見てください。

Text: {text}
Emotion: {emotion} (intensity {intensity})
Intent: {intent}
SceneTone: {tone}
CharacterState: {state}
PerformancePlan: speed={speed} pitch={pitch} energy={energy}
PreviousSegmentEmotion: {prev_emotion}
AudioMetrics: {audio_metrics}

例: 直前に友人が死亡した（sadness 0.82）のに energy 0.97 で明るく喋っていたら
character_consistency は低点。音質が完璧でも演技は 0 点です。

以下の JSON のみを返却（各スコア 0.0..1.0）:
{{"naturalness": 0.0, "character_consistency": 0.0, "scene_consistency": 0.0,
  "continuity": 0.0, "acoustic_quality": 0.0,
  "diagnoses": ["problem_slug", ...]}}
"""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "naturalness": {"type": "number"},
        "character_consistency": {"type": "number"},
        "scene_consistency": {"type": "number"},
        "continuity": {"type": "number"},
        "acoustic_quality": {"type": "number"},
        "diagnoses": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["naturalness", "character_consistency", "scene_consistency",
                 "continuity", "acoustic_quality"],
}


class JudgeReport(BaseModel):
    human_ness: float = 0.0
    naturalness: float = 0.0
    character_fit: float = 0.0
    emotion_fit: float = 0.0
    listenability: float = 0.0
    ai_ness: float = 0.0
    # ---- 3.5R: 演技として正しいか（音質とは独立の審査軸）----
    character_consistency: float = 0.0   # VoiceState × Plan の整合
    scene_consistency: float = 0.0       # Scene Tone / 場の緊張 × Plan の整合
    continuity: float = 0.0              # 直前セグメントとの感情連続性
    acoustic_quality: float = 0.0        # 合成音の音響特徴
    diagnoses: list[str] = Field(default_factory=list)
    confidence: float = 0.0


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = _mean(xs)
    return (sum((x - m) ** 2 for x in xs) / n) ** 0.5


def _gap_cov(timing_ms):
    if len(timing_ms) < 2:
        return 0.0
    gaps = [timing_ms[i] - timing_ms[i - 1] for i in range(1, len(timing_ms))]
    m = _mean(gaps)
    return _std(gaps) / (abs(m) or 1.0)


class HeuristicJudge:
    """決定論的 perceptual proxy。LLM と同じ JudgeReport を返す（network 不要）。"""

    def evaluate(self, plan, state=None, intent=None, emotion=None,
                 tone=None, prev_emotion=None, audio_metrics=None, intensity=None):
        """知覚スコア（決定論）。3.5R の context 引数は受け取るが、このクラスでは
        知覚軸のみを評価し、演技正当性軸は ContextJudge が上乗せする。"""
        speed = plan.get("speed", [])
        pitch = plan.get("pitch", [])
        energy = plan.get("energy", [])
        timing = plan.get("timing_ms", [])
        diagnoses = []
        fatigue = state.fatigue if state else 0.0
        confidence = state.confidence if state else 0.0

        if fatigue > 0.6 and _mean(energy) > 0.65:
            diagnoses.append("energy_too_high_for_fatigue")
        if _std(pitch) < 0.02:
            diagnoses.append("pitch_flat")
        if len(timing) >= 2 and _gap_cov(timing) < 0.05:
            diagnoses.append("timing_rigid")
        if intent in ("hesitant_denial", "whispered_confession", "awkward_silence") \
                and _mean(speed) > 1.05:
            diagnoses.append("too_fast_for_hesitation")
        if confidence > 0.7 and intent in ("hesitant_denial", "whispered_confession"):
            diagnoses.append("too_confident_for_intent")
        if not diagnoses:
            diagnoses.append("ok")

        pvar = min(_std(pitch) / 0.15, 1.0)
        evar = min(_std(energy) / 0.25, 1.0)
        naturalness = 0.5 * pvar + 0.3 * evar + 0.2 * min(_gap_cov(timing) / 0.3, 1.0)
        emotion_fit = (1.0
                       - (0.5 if "energy_too_high_for_fatigue" in diagnoses else 0.0)
                       - (0.3 if "too_fast_for_hesitation" in diagnoses else 0.0))
        character_fit = 1.0 - (0.4 if "too_confident_for_intent" in diagnoses else 0.0)
        ai_ness = ((0.5 if "timing_rigid" in diagnoses else 0.0)
                   + (0.3 if "pitch_flat" in diagnoses else 0.0))
        human_ness = max(0.0, min(1.0,
            0.4 * naturalness + 0.25 * emotion_fit + 0.25 * character_fit
            + 0.1 * (1.0 - ai_ness)))
        return JudgeReport(
            human_ness=round(human_ness, 3),
            naturalness=round(naturalness, 3),
            character_fit=round(max(0.0, character_fit), 3),
            emotion_fit=round(max(0.0, emotion_fit), 3),
            listenability=round(0.6 * naturalness + 0.4 * (1.0 - ai_ness), 3),
            ai_ness=round(max(0.0, min(1.0, ai_ness)), 3),
            # 3.5R 軸はこのクラスでは判定しない -> 中立値（問題検出なし）
            character_consistency=1.0,
            scene_consistency=1.0,
            continuity=1.0,
            acoustic_quality=1.0,
            diagnoses=diagnoses,
            confidence=0.8,
        )


# ---- 3.5R: 感情のバランス値（連続性判定用） ----
VALENCE = {
    "happy": 1.0, "tender": 0.8, "surprised": 0.3, "calm": 0.4, "neutral": 0.0,
    "sarcastic": -0.2, "anxious": -0.4, "sad": -0.7, "fearful": -0.7, "angry": -0.8,
}


def evaluate_judge(judge, plan, **context):
    """Judge の evaluate を呼ぶ。

    古いシグネチャ（evaluate(plan, state, intent, emotion) のみ）の Judge には
    対応する引数だけ渡すので、3.5N 時代のカスタム Judge もそのまま使える。
    """
    import inspect
    try:
        params = inspect.signature(judge.evaluate).parameters
    except (TypeError, ValueError):
        return judge.evaluate(plan, **context)
    has_var = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    kw = {k: v for k, v in context.items() if has_var or k in params}
    return judge.evaluate(plan, **kw)


def _state_brief(state):
    if state is None:
        return "none"
    keys = ("tension", "fatigue", "confidence", "excitement",
            "fear", "anger", "sadness", "embarrassment")
    return " ".join(f"{k}={float(getattr(state, k, 0.0)):.2f}" for k in keys)


class ContextJudge:
    """3.5R: 「演技として正しいか」を審査する決定論 Judge（network 不要）。

    音質とは独立に、以下の乖離を検出する:
    - character_consistency: VoiceState × Plan
      （悲しみ 0.82 なのに energy 0.97 -> 演技 0 点。音質が完璧でも）
    - scene_consistency    : Scene Tone / 場の緊張 × Plan
    - continuity           : 直前セグメントからの感情ジャンプ
    - acoustic_quality     : 合成音の音響特徴（clipping / 過剰な無音）
    """

    def __init__(self, base=None):
        self.base = base or HeuristicJudge()

    # -- state × plan の乖離検出 --
    def character_consistency(self, plan, state, diagnoses):
        energy = plan.get("energy", []) or [0.8]
        speed = plan.get("speed", []) or [1.0]
        me, ms = _mean(energy), _mean(speed)
        sad = float(getattr(state, "sadness", 0.0) or 0.0) if state else 0.0
        anger = float(getattr(state, "anger", 0.0) or 0.0) if state else 0.0
        pen = 0.0
        if sad > 0.5 and me > 0.85:
            diagnoses.append("energy_too_high_for_sadness"); pen += 0.45
        if sad > 0.5 and ms > 1.05:
            diagnoses.append("too_fast_for_sadness"); pen += 0.25
        if anger > 0.5 and me < 0.55:
            diagnoses.append("energy_too_low_for_anger"); pen += 0.30
        return max(0.0, 1.0 - pen)

    # -- tone / 緊張 × plan の乖離検出 --
    def scene_consistency(self, plan, state, tone, diagnoses):
        energy = plan.get("energy", []) or [0.8]
        me = _mean(energy)
        tension = float(getattr(state, "tension", 0.0) or 0.0) if state else 0.0
        pen = 0.0
        if tone == "comedy" and me > 0.95:
            diagnoses.append("energy_too_high_for_comedy_tone"); pen += 0.40
        if tension > 0.6 and me < 0.35:
            diagnoses.append("energy_too_low_for_tension"); pen += 0.30
        return max(0.0, 1.0 - pen)

    # -- 直前セグメントとの感情ジャンプ --
    def continuity(self, plan, emotion, prev_emotion, intensity, diagnoses):
        if not prev_emotion:
            return 1.0
        jump = abs(VALENCE.get(str(prev_emotion), 0.0) - VALENCE.get(str(emotion), 0.0))
        if jump <= 0.6 or (intensity is not None and float(intensity) >= 0.7):
            return 1.0  # 強い感情はジャンプを正当化する
        diagnoses.append("abrupt_emotion_shift")
        return max(0.0, 1.0 - 0.5 * (jump - 0.6) / 0.4)

    # -- 合成音の音響特徴 --
    @staticmethod
    def acoustic_quality(audio_metrics, diagnoses):
        if not audio_metrics:
            return 1.0
        acq = 1.0
        if audio_metrics.get("clipping"):
            diagnoses.append("clipping_detected"); acq -= 0.5
        sil = float(audio_metrics.get("silence_ratio", 0.0) or 0.0)
        if sil > 0.5:
            diagnoses.append("too_much_silence"); acq -= min(0.4, (sil - 0.5) + 0.15)
        return max(0.0, acq)

    def evaluate(self, plan, state=None, intent=None, emotion=None,
                 tone=None, prev_emotion=None, audio_metrics=None, intensity=None):
        rep = self.base.evaluate(plan, state=state, intent=intent, emotion=emotion)
        diagnoses = list(rep.diagnoses if rep.diagnoses != ["ok"] else [])
        cc = self.character_consistency(plan, state, diagnoses)
        sc = self.scene_consistency(plan, state, tone, diagnoses)
        ct = self.continuity(plan, emotion, prev_emotion, intensity, diagnoses)
        aq = self.acoustic_quality(audio_metrics, diagnoses)
        if not diagnoses:
            diagnoses = ["ok"]
        # 知覚自然さ + 演技正当性の統合スコア（演技違反は強く効く）
        human_ness = max(0.0, min(1.0, 0.25 * rep.naturalness
                                  + 0.25 * cc + 0.15 * sc + 0.10 * ct
                                  + 0.15 * rep.emotion_fit
                                  + 0.10 * rep.character_fit))
        return rep.model_copy(update={
            "human_ness": round(human_ness, 3),
            "character_consistency": round(cc, 3),
            "scene_consistency": round(sc, 3),
            "continuity": round(ct, 3),
            "acoustic_quality": round(aq, 3),
            "diagnoses": diagnoses,
            "confidence": 0.8,
        })


class OllamaJudge:
    """3.5R: 実 LLM による Performance Judge（全コンテキストを渡して JSON スコア）。

    Story Context + Scene Context + VoiceState + Plan + Audio Metrics +
    Previous Segment を演技監督プロンプトに束ねて LLM に審査させる。
    失敗時（Ollama 未起動 / 応答不良）は fallback（既定 ContextJudge）に
    フォールバックし、diagnoses に judge_llm_fallback を足す。
    テストでは _post 依存を例外にするか、fallback の挙動を検査する。
    """

    def __init__(self, model: str = "qwen3:4b", host: str = "http://localhost:11434",
                 timeout: float = 120.0, fallback=None):
        self.model = model
        self.base_url = host.rstrip("/")
        self.timeout = timeout
        self.fallback = fallback or ContextJudge()

    def _context(self, plan, state, intent, emotion, tone, prev_emotion,
                 audio_metrics, intensity):
        return {
            "text": plan.get("text", ""),
            "emotion": emotion,
            "intensity": intensity,
            "intent": intent,
            "tone": tone or "neutral",
            "state": _state_brief(state),
            "speed": plan.get("speed"),
            "pitch": plan.get("pitch"),
            "energy": plan.get("energy"),
            "prev_emotion": prev_emotion or "none",
            "audio_metrics": audio_metrics or "none",
        }

    def _prompt(self, ctx: dict) -> str:
        return JUDGE_CONTEXT_PROMPT.format(**ctx)

    def evaluate(self, plan, state=None, intent=None, emotion=None,
                 tone=None, prev_emotion=None, audio_metrics=None, intensity=None):
        ctx = self._context(plan, state, intent, emotion, tone, prev_emotion,
                            audio_metrics, intensity)
        try:
            from analyzer import _extract_json, _post_with_retry
            payload = {"model": self.model, "prompt": self._prompt(ctx),
                       "stream": False, "format": JUDGE_SCHEMA, "think": False,
                       "options": {"temperature": 0.1}}
            resp = _post_with_retry(f"{self.base_url}/api/generate", payload,
                                    self.timeout)
            data = resp.get("response") if isinstance(resp, dict) else None
            rep = self._report_from(_extract_json(str(data)))
        except Exception:
            rep = self.fallback.evaluate(plan, state=state, intent=intent,
                                         emotion=emotion, tone=tone,
                                         prev_emotion=prev_emotion,
                                         audio_metrics=audio_metrics,
                                         intensity=intensity)
            diagnoses = list(rep.diagnoses if rep.diagnoses != ["ok"] else [])
            diagnoses.append("judge_llm_fallback")
            rep = rep.model_copy(update={"diagnoses": diagnoses,
                                         "confidence": round(rep.confidence * 0.5, 3)})
        return rep

    def _report_from(self, scores: dict) -> JudgeReport:
        def _f(key):
            try:
                return max(0.0, min(1.0, float(scores.get(key, 0.0))))
            except (TypeError, ValueError):
                return 0.0
        nat = _f("naturalness")
        cc = _f("character_consistency")
        sc = _f("scene_consistency")
        ct = _f("continuity")
        aq = _f("acoustic_quality")
        diag = [str(d) for d in (scores.get("diagnoses") or []) if str(d).strip()]
        human = 0.25 * nat + 0.25 * cc + 0.15 * sc + 0.10 * ct + 0.25 * aq
        return JudgeReport(
            human_ness=round(human, 3),
            naturalness=round(nat, 3),
            character_fit=round(cc, 3),
            emotion_fit=round(sc, 3),
            listenability=round(0.7 * nat + 0.3 * aq, 3),
            ai_ness=round(1.0 - nat, 3),
            character_consistency=round(cc, 3),
            scene_consistency=round(sc, 3),
            continuity=round(ct, 3),
            acoustic_quality=round(aq, 3),
            diagnoses=diag or ["ok"],
            confidence=0.6,
        )


# diagnose -> tweak 戦略（Judge を「採点機」から「演技ディレクター」へ）
DIAGNOSE_TWEAKS = {
    "energy_too_high_for_fatigue": {"energy_scale": 0.82, "extra_breaths": 1},
    "pitch_flat": {"pitch_variation_boost": 0.08},
    "timing_rigid": {"timing_reshuffle": True},
    "too_fast_for_hesitation": {"speed_scale": 0.92},
    "too_confident_for_intent": {"energy_scale": 0.90, "speed_scale": 0.96},
    # ---- 3.5R: 演技正当性違反の修正戦略 ----
    "energy_too_high_for_sadness": {"energy_scale": 0.85, "extra_breaths": 1},
    "too_fast_for_sadness": {"speed_scale": 0.90},
    "energy_too_low_for_anger": {"energy_scale": 1.15},
    "energy_too_high_for_comedy_tone": {"energy_scale": 0.88},
    "energy_too_low_for_tension": {"energy_scale": 1.12},
    "abrupt_emotion_shift": {"timing_reshuffle": True, "extra_breaths": 1},
    "clipping_detected": {"energy_scale": 0.85},
    "too_much_silence": {"timing_reshuffle": True},
}


def diagnose_to_tweak(diagnoses):
    """Judge diagnoses -> plan tweak dict（合成。未知 diagnose は無視）。"""
    tweak = {}
    for d in diagnoses:
        for k, v in DIAGNOSE_TWEAKS.get(d, {}).items():
            if k == "extra_breaths":
                tweak[k] = tweak.get(k, 0) + v
            elif k in ("energy_scale", "speed_scale"):
                tweak[k] = round(tweak.get(k, 1.0) * v, 4)
            else:
                tweak[k] = v
    return tweak


def apply_tweak(plan, tweak, seed=42):
    """tweak を plan に決定論的に適用したコピーを返す（元 plan は変更しない）。"""
    if not tweak:
        return dict(plan)
    rng = random.Random(seed)
    out = dict(plan)
    if "energy_scale" in tweak:
        out["energy"] = [round(e * tweak["energy_scale"], 4) for e in plan.get("energy", [])]
    if "speed_scale" in tweak:
        out["speed"] = [round(s * tweak["speed_scale"], 4) for s in plan.get("speed", [])]
    if "pitch_variation_boost" in tweak:
        boost = tweak["pitch_variation_boost"]
        out["pitch"] = [round(p + rng.uniform(-boost, boost), 4) for p in plan.get("pitch", [])]
    if tweak.get("timing_reshuffle"):
        tm = plan.get("timing_ms", [])
        if len(tm) >= 2:
            out["timing_ms"] = [tm[0]] + [round(t + rng.uniform(-40, 60), 1) for t in tm[1:]]
    out["tweaked"] = True
    return out