"""Phase 3.5M - Human Voice Engine: segment -> Performance -> composed wav (+ QA gate)。

Text-to-Speech ではなく Text-to-Character-Performance-to-Speech。
1 segment の合成を Voice Director (intent/emotion/prosody_curve) + VoiceProfile/State +
Breath Engine で "演じる"。QA スコアが低ければ Auto Re-performance まで回す。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from models import VoiceProfile, VoiceState
from director import plan_prosody, apply_voice_state, normalize_intent, emotion_to_intent
from audio import plan_speech_segments, plan_breaths, render_breath, crossfade_concat
from sbv2_adapter import Sbv2PerformanceSynthesizer
from qa import PerformanceEvaluator, AutoReperformer
from schema import clamp
from scene_context import tone_energy_scale


def seed_for(seg_id, seed=42):
    """seg.id から決定論的な seed を生成（再生可能）。"""
    return (seed + int(hashlib.sha256(str(seg_id).encode("utf-8")).hexdigest()[:8], 16)) % 100000


def plan_for_segment(seg, profile, state, seed=42, intent=None, tone=None):
    """Text -> Speech Segments + Time-based Prosody + Breath plan（pure, deterministic）。

    intent を渡すと Scene Context (3.5O) 由来の Intent が emotion 由来より優先される。
    tone を渡すと Scene Override (3.5Q) が効く: comedy は過剰演技を抑制する
    （キャラの感情 ≠ 必ず大声）。
    """
    intent = intent or emotion_to_intent(seg.emotion) or "neutral"
    segments = plan_speech_segments(seg.text, intent=intent)
    n = sum(1 for s in segments if s.type == "speech") or 1
    plan = plan_prosody(seg.emotion, seg.intensity, intent=intent, num_phrases=n, seed=seed)
    plan = apply_voice_state(plan, profile, state, seed=seed)
    plan["intent"] = intent
    if tone:
        scale = tone_energy_scale(tone)
        if scale != 1.0:
            plan["energy"] = [round(clamp(e * scale, 0.2, 1.5), 4)
                              for e in plan["energy"]]
        plan["tone"] = tone
    breaths = plan_breaths(n, profile=profile, state=state, emotion=seg.emotion,
                           intent=intent, seed=seed)
    return plan, segments, breaths


def compose_with_breaths(wavs, breaths, out_path, parts_dir):
    """vox/speech wavs + breath events -> micro crossfade で 1 本の wav。"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    parts_dir = Path(parts_dir); parts_dir.mkdir(parents=True, exist_ok=True)
    breath_by_idx = {b.phrase_index: b for b in breaths}
    items = []
    for i, w in enumerate(wavs):
        if i in breath_by_idx:
            items.append(render_breath(breath_by_idx[i], parts_dir / ("breath_%d.wav" % i)))
        items.append(w)
    if not items:
        raise ValueError("合成する音声がありません")
    crossfade_concat(items, out_path, crossfade_ms=30)
    return out_path


def render_segment(seg, profile, state, provider, out_path, seed=42,
                   qa_threshold=75.0, attempts=2, judge=None, judge_threshold=0.7,
                   tone=None):
    """1 セグメントを HVE で演じる -> composed wav + plan。QA gate + auto re-perform。

    tone は Scene Override (3.5Q)（comedy 等で過剰演技を抑制）。
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    parts_dir = out_path.parent / (out_path.stem + ".parts")
    parts_dir.mkdir(parents=True, exist_ok=True)
    plan, segments, breaths = plan_for_segment(seg, profile, state, seed=seed, tone=tone)
    syn = Sbv2PerformanceSynthesizer(provider=provider)
    wavs = syn.synthesize_segments(segments, plan, profile, parts_dir)
    composed = compose_with_breaths(wavs, breaths, out_path, parts_dir)
    report = None
    if judge is not None:
        report = judge.evaluate(plan, state=state, intent=plan["intent"], emotion=seg.emotion)
        plan["judge"] = report.model_dump()
    need_retry = (PerformanceEvaluator().evaluate_plan(plan)["HumanLikenessScore"] < qa_threshold
                  or (report is not None and report.human_ness < judge_threshold))
    if need_retry and attempts > 0:
        new = AutoReperformer(seed=seed + 1).reperform(
            seg.emotion, plan["intent"], num_phrases=len(plan["speed"]),
            profile=profile, state=state, attempts=attempts)
        if report is not None and report.diagnoses != ["ok"]:
            from llm_judge import diagnose_to_tweak, apply_tweak
            new = apply_tweak(new, diagnose_to_tweak(report.diagnoses), seed=seed + 1)
        wavs2 = syn.synthesize_segments(segments, new, profile, parts_dir)
        composed = compose_with_breaths(wavs2, breaths, out_path, parts_dir)
        plan = new
        if report is not None:
            plan["judge"] = report.model_dump()
        if report is not None and report.diagnoses != ["ok"]:
            plan["tweaked"] = True
    return composed, plan
