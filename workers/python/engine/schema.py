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

# ---------------------------------------------------------------- 関係性の語彙

# 有向: src → dst。対称なものは SYMMETRIC_RELATIONSHIPS に列挙。
RELATIONSHIP_TYPES = {
    "loves",          # 恋愛対象
    "friend",         # 友人（対称）
    "best_friend",    # 親友（対称）
    "family",         # 家族（対称）
    "rival",          # 競争相手（対称）
    "respects",       # 尊敬
    "trusts",         # 信頼
    "despises",       # 軽蔑
    "owes",           # 恩義
    "colleague",      # 同僚・同級（対称）
    "acquaintance",   # 知人（対称）
    "enemy",          # 敵（対称）
    "other",
}

RELATIONSHIP_ALIASES = {
    "love": "loves",
    "crush": "loves",
    "in_love": "loves",
    "romantic": "loves",
    "confessed_to": "loves",
    "friends": "friend",
    "pal": "friend",
    "bff": "best_friend",
    "sibling": "family",
    "brother": "family",
    "sister": "family",
    "parent": "family",
    "child": "family",
    "respect": "respects",
    "mentor": "respects",
    "senpai": "respects",
    "trust": "trusts",
    "hate": "despises",
    "hates": "despises",
    "dislike": "despises",
    "grudge": "despises",
    "debt": "owes",
    "gratitude": "owes",
    "classmate": "colleague",
    "coworker": "colleague",
    "teammate": "colleague",
    "known": "acquaintance",
    "rivalry": "rival",
    "adversary": "enemy",
    "nemesis": "enemy",
}

# 対称な関係（src→dst を保存したら dst→src も自動生成する）
SYMMETRIC_RELATIONSHIPS = {
    "friend", "best_friend", "family", "rival", "colleague", "acquaintance", "enemy",
}

SPEECH_STYLES = {"polite", "casual", "rough", "formal", "cheerful", "quiet", ""}


def normalize_relationship(raw: object, default: str = "other") -> str:
    """LLM 出力の関係語を契約語彙へ正規化する。"""
    if not isinstance(raw, str) or not raw.strip():
        return default
    key = raw.strip().lower().replace(" ", "_").replace("-", "_")
    if key in RELATIONSHIP_TYPES:
        return key
    return RELATIONSHIP_ALIASES.get(key, default)


def normalize_speech_style(raw: object) -> str:
    if not isinstance(raw, str):
        return ""
    key = raw.strip().lower().replace(" ", "_")
    return key if key in SPEECH_STYLES else ""

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
        voicing = perf.get("voicing", "external")
        if voicing not in ("external", "internal", "narrator"):
            errors.append(f"{sid}: 不正な voicing: {voicing!r}")
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
                "voicing": "narrator",
                "style": "Neutral",
                "carryover": False,
                "baseline": False,
                "relationship": "",
            },
        }
    ],
}
