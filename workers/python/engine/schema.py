"""performance.json 等の JSON 契約定義。

このモジュールは C++ Core と Python Worker の間の「契約」の元典。
フィールド名・語彙・バリデーションはここだけで管理する。
"""

from __future__ import annotations

# ---------------------------------------------------------------- 語彙

SEGMENT_TYPES = {"narration", "dialogue", "inner_monologue"}

EMOTIONS = {
    "neutral",
    "calm",
    "happy",
    "sad",
    "angry",
    "fearful",
    "anxious",
    "surprised",
    "sarcastic",
    "tender",
}

# LLM が語彙外の感情語を返したときの正規化マップ
EMOTION_ALIASES = {
    "uneasy": "anxious",
    "worried": "anxious",
    "nervous": "anxious",
    "impatient": "anxious",
    "joy": "happy",
    "cheerful": "happy",
    "excited": "happy",
    "glad": "happy",
    "anger": "angry",
    "irritated": "angry",
    "frustrated": "angry",
    "sorrow": "sad",
    "gloomy": "sad",
    "melancholy": "sad",
    "lonely": "sad",
    "scared": "fearful",
    "afraid": "fearful",
    "terrified": "fearful",
    "shock": "surprised",
    "astonished": "surprised",
    "shy": "tender",
    "gentle": "tender",
    "kind": "tender",
    "loving": "tender",
    "serious": "calm",
    "relaxed": "calm",
    "quiet": "calm",
}

# セグメント種別 → 演技モード
MODES_BY_TYPE = {
    "narration": "narration",
    "dialogue": "dialogue",
    "inner_monologue": "internal",
}

# ---------------------------------------------------------------- 正規化


def normalize_emotion(raw: object, default: str = "neutral") -> str:
    """LLM 出力の感情語を契約語彙へ正規化する。"""
    if not isinstance(raw, str) or not raw.strip():
        return default
    key = raw.strip().lower().replace(" ", "_")
    if key in EMOTIONS:
        return key
    return EMOTION_ALIASES.get(key, default)


def normalize_segment_type(raw: object, default: str = "narration") -> str:
    if not isinstance(raw, str):
        return default
    key = raw.strip().lower().replace(" ", "_").replace("-", "_")
    if key in SEGMENT_TYPES:
        return key
    aliases = {"monologue": "inner_monologue", "thought": "inner_monologue",
               "speech": "dialogue", "line": "dialogue", "description": "narration"}
    return aliases.get(key, default)


def clamp(value: float, low: float, high: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return low
    return max(low, min(high, v))


# ---------------------------------------------------------------- バリデーション


def validate_performance_doc(doc: dict) -> list[str]:
    """performance.json の内容を検証し、問題のリストを返す（空ならOK）。"""
    errors: list[str] = []
    segments = doc.get("segments")
    if not isinstance(segments, list) or not segments:
        return ["'segments' は空でない配列である必要があります"]

    for seg in segments:
        sid = seg.get("id", "?")
        if seg.get("type") not in SEGMENT_TYPES:
            errors.append(f"{sid}: 不正な type: {seg.get('type')!r}")
        if not isinstance(seg.get("text"), str) or not seg["text"].strip():
            errors.append(f"{sid}: text が空です")
        if not isinstance(seg.get("speaker"), str) or not seg["speaker"]:
            errors.append(f"{sid}: speaker がありません")
        perf = seg.get("performance")
        if not isinstance(perf, dict):
            errors.append(f"{sid}: performance がありません")
            continue
        for key in ("voice", "emotion", "intensity", "pace", "pitch"):
            if key not in perf:
                errors.append(f"{sid}: performance.{key} がありません")
        if perf.get("emotion") not in EMOTIONS:
            errors.append(f"{sid}: 不正な emotion: {perf.get('emotion')!r}")
    return errors


PERFORMANCE_EXAMPLE = {
    "chapter": 1,
    "segments": [
        {
            "id": "seg_001",
            "type": "narration",
            "speaker": "narrator",
            "text": "夕暮れの街を、彼は一人で歩いていた。",
            "emotion": "calm",
            "intensity": 0.2,
            "performance": {
                "voice": "voice_narrator",
                "mode": "narration",
                "emotion": "calm",
                "intensity": 0.2,
                "pace": 0.9,
                "pitch": 0.0,
                "volume": 1.0,
                "carryover": False,
            },
        }
    ],
}
