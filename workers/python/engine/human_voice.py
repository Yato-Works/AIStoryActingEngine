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
from llm_judge import evaluate_judge
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


def _acoustic_metrics(wav_path):
    """合成 wav -> Judge へ渡す最小の音響特徴（失敗時は None）。"""
    try:
        from qa import analyze_audio
        feats = analyze_audio(wav_path)
    except Exception:
        return None
    return {
        "peak": feats.get("peak", 0.0),
        "silence_ratio": feats.get("silence_ratio", 0.0),
        "zcr": feats.get("zcr", 0.0),
        "clipping": float(feats.get("peak", 0.0) or 0.0) >= 0.99,
    }


def render_segment(seg, profile, state, provider, out_path, seed=42,
                   qa_threshold=75.0, attempts=2, judge=None, judge_threshold=0.7,
                   tone=None, prev_emotion=None):
    """1 セグメントを HVE で演じる -> composed wav + plan。QA gate + auto re-perform。

    tone は Scene Override (3.5Q)（comedy 等で過剰演技を抑制）。
    prev_emotion は Performance Judge (3.5R) の continuity 審査用。
    judge を渡すと 3.5R の Decision（KEEP / RE-PERFORM）が働く:
    再演技のスコアが改善したときだけ採用し、悪化したら元の演技を KEEP する。
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
        report = evaluate_judge(judge, plan, state=state, intent=plan["intent"],
                                emotion=seg.emotion, intensity=seg.intensity,
                                tone=tone, prev_emotion=prev_emotion,
                                audio_metrics=_acoustic_metrics(composed))
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
        # 再演技は別ファイルへ合成してから比較する（元の演技を壊さない）
        retry_path = out_path.with_name(out_path.stem + ".retry.wav")
        wavs2 = syn.synthesize_segments(segments, new, profile, parts_dir)
        compose_with_breaths(wavs2, breaths, retry_path, parts_dir)
        new_report = None
        if judge is not None:
            new_report = evaluate_judge(judge, new, state=state,
                                        intent=new.get("intent", plan["intent"]),
                                        emotion=seg.emotion, intensity=seg.intensity,
                                        tone=tone, prev_emotion=prev_emotion,
                                        audio_metrics=_acoustic_metrics(retry_path))
            new["judge"] = new_report.model_dump()
        # ---- Decision (3.5R): RE-PERFORM が改善したときだけ採用 ----
        better = (report is None or new_report is None
                  or new_report.human_ness >= report.human_ness)
        if better:
            retry_path.replace(out_path)
            composed = out_path
            plan = new
            if new_report is not None and new_report.diagnoses != ["ok"]:
                plan["tweaked"] = True
        else:
            retry_path.unlink(missing_ok=True)  # KEEP: 元の演技を維持
            if report is not None:
                kept = report.model_dump()
                kept["decision"] = "keep"
                plan["judge"] = kept
    return composed, plan
