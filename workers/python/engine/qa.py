"""Phase 3.5I - Performance QA / Human-Likeness Evaluator。

Text-to-Speech 品質ではなく、Text-to-Performance 品質をスコアする。
evaluate_plan   : prosody curve / timing / pause / energy / pitch-variation （純粋&決定論）
evaluate_audio  : 実Waveの clipping / silence / energy-variation / zcr
"""
from __future__ import annotations

import math
import struct
import wave
from pathlib import Path


def load_pcm(path):
    """16bit / 8bit mono PCM を samples list + rate に。"""
    with wave.open(str(path), "rb") as w:
        n = w.getnframes()
        ch = w.getnchannels()
        sw = w.getsampwidth()
        rate = w.getframerate()
        raw = w.readframes(n)
    fmt = "<" + ("h" if sw == 2 else "B") * (n * ch)
    samples = list(struct.unpack(fmt, raw))
    if ch > 1:
        samples = samples[::ch]
    scale = 32768.0 if sw == 2 else 1.0
    return samples, rate, scale


def analyze_audio(path):
    """wav -> 音響特徴量(dict)。numpy 不要、Pure stdlib。"""
    samples, rate, scale = load_pcm(path)
    n = len(samples)
    frame = max(rate // 100, 1)   # 10ms windows
    rms = []
    for i in range(0, n, frame):
        chunk = samples[i:i + frame]
        if not chunk:
            break
        rms.append(math.sqrt(sum((x / scale) ** 2 for x in chunk) / len(chunk)))
    peak = max((abs(x) for x in samples), default=0.0) / scale
    maxrms = max(rms) if rms else 0.0
    norm = [r / (maxrms or 1.0) for r in rms]
    silence = sum(1 for r in norm if r < 0.02) / max(len(norm), 1)
    avg = sum(norm) / len(norm) if norm else 0.0
    std = (sum((r - avg) ** 2 for r in norm) / len(norm)) ** 0.5 if norm else 0.0
    zcr = 0.0
    if len(samples) > 1:
        zcr = sum(1 for i in range(1, len(samples))
                  if (samples[i] >= 0) != (samples[i - 1] >= 0)) / len(samples)
    return {
        "rate": rate, "samples": n, "rms": rms, "peak": peak,
        "silence_ratio": silence, "energy_variation": std,
        "max_rms": maxrms, "zcr": zcr,
    }


def _variation_score(vals):
    n = len(vals)
    if n < 2:
        return 50.0
    m = sum(vals) / n
    std = (sum((v - m) ** 2 for v in vals) / n) ** 0.5
    return round(100.0 * min(std / (abs(m) + 0.1), 1.0), 1)


def _gap_stats(timing_ms):
    if len(timing_ms) < 2:
        return [], 0.0
    gaps = [timing_ms[i] - timing_ms[i - 1] for i in range(1, len(timing_ms))]
    m = sum(gaps) / len(gaps)
    cov = (sum((g - m) ** 2 for g in gaps) / len(gaps)) ** 0.5 / (m or 1.0)
    return gaps, cov


class PerformanceEvaluator:
    """Generated Performance または Audio Wave の human-likeness を評価する。"""

    def evaluate_plan(self, plan):
        speeds = plan.get("speed", [])
        pitches = plan.get("pitch", [])
        energies = plan.get("energy", [])
        timing = plan.get("timing_ms", [])
        gaps, cov = _gap_stats(timing)
        # 自然なタメは多少の揺らぎを許容（CVが小さすぎてもヒッチボール判定）
        timing_score = round(100.0 * (1.0 - min(cov / 0.5, 1.0)), 1) if gaps else 50.0
        # pause naturalness: 暗黙の phrase 間隔が一定幅
        if gaps:
            pause_score = round(100.0 * min(min(gaps) / 80.0, 1.0) if min(gaps) > 0 else 30.0, 1)
        else:
            pause_score = 50.0
        pvar = _variation_score(pitches)
        eval_score = _variation_score(energies)
        continuity = 100.0 if gaps and cov < 0.6 else max(0.0, 100.0 * (1.0 - cov))
        human = (0.25 * pvar + 0.20 * eval_score + 0.20 * timing_score
                 + 0.15 * pause_score + 0.20 * continuity)
        return {
            "HumanLikenessScore": round(human, 1),
            "ProsodyScore": round(0.6 * pvar + 0.4 * timing_score, 1),
            "TimingScore": timing_score,
            "PauseScore": pause_score,
            "EnergyScore": eval_score,
            "PitchVariationScore": pvar,
            "ContinuityScore": round(continuity, 1),
        }

    def evaluate_audio(self, path):
        a = analyze_audio(path)
        # clipping
        clip = 100.0 if a["peak"] < 0.95 else max(0.0, 100.0 - (a["peak"] - 0.95) * 2000.0)
        # silence: 0..0.3 ok, too much bad
        sil = a["silence_ratio"]
        silence_score = 100.0 * (1.0 - min(sil / 0.35, 1.0))
        # zcr: conversational voice is low; too high = noise
        zcr_s = 100.0 if a["zcr"] < 0.15 else max(0.0, 100.0 - a["zcr"] * 400.0)
        # energy variation
        pvars = _variation_score(a["rms"])
        human = 0.30 * pvars + 0.20 * zcr_s + 0.25 * silence_score + 0.25 * clip
        return {
            "HumanLikenessScore": round(max(human, 0.0), 1),
            "EnergyVariationScore": pvars,
            "SilenceScore": round(silence_score, 1),
            "ClippingScore": round(clip, 1),
            "ZeroCrossingScore": round(zcr_s, 1),
            "PeakLevel": round(a["peak"], 3),
        }

# ---------------------------------------------------------------- 3.5J Auto Re-performance
# Evaluate -> KEEP / RETRY(segment) ループ。全体を再生成せず局所再生成する。
class AutoReperformer:
    """QA スコアが低いセグメントを、seed 変化 + intensity 再調整で再演技する。"""

    def __init__(self, evaluator=None, seed=42):
        self.eval = evaluator or PerformanceEvaluator()
        self.seed = seed

    def reperform(self, emotion, intent, num_phrases, profile=None, state=None, attempts=3):
        """同じ intent/props で seed を変えながら再生成。最も QA スコアの高い plan を返す。"""
        from director import plan_prosody, apply_voice_state
        best = None
        best_score = -1.0
        for k in range(attempts):
            plan = plan_prosody(emotion, 0.5, intent=intent, num_phrases=num_phrases,
                                seed=self.seed + k * 1000)
            if profile is not None:
                plan = apply_voice_state(plan, profile, state, seed=self.seed + k * 1000)
            sc = self.eval.evaluate_plan(plan)["HumanLikenessScore"]
            if sc > best_score:
                best_score = sc
                best = plan
        best["reperformed"] = best is not None and best_score < 95.0
        best["best_score"] = round(best_score, 1)
        return best
