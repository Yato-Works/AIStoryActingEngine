"""Phase 3.5N - Performance Judge (perceptual QA proxy)。

注意: HeuristicJudge は本物の LLM ではなく、決定論的なルールベース proxy。
本物の LLM へ差し替え可能な同一インターフェース（evaluate -> JudgeReport）を提供する。
Acoustic QA (3.5I) と組み合わせて「perceptual proxy」として使う。
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


class JudgeReport(BaseModel):
    human_ness: float = 0.0
    naturalness: float = 0.0
    character_fit: float = 0.0
    emotion_fit: float = 0.0
    listenability: float = 0.0
    ai_ness: float = 0.0
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

    def evaluate(self, plan, state=None, intent=None, emotion=None):
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
            diagnoses=diagnoses,
            confidence=0.8,
        )


# diagnose -> tweak 戦略（Judge を「採点機」から「演技ディレクター」へ）
DIAGNOSE_TWEAKS = {
    "energy_too_high_for_fatigue": {"energy_scale": 0.82, "extra_breaths": 1},
    "pitch_flat": {"pitch_variation_boost": 0.08},
    "timing_rigid": {"timing_reshuffle": True},
    "too_fast_for_hesitation": {"speed_scale": 0.92},
    "too_confident_for_intent": {"energy_scale": 0.90, "speed_scale": 0.96},
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