"""Phase 3.5O/Q - Scene Context: Scene Event -> Character mental state -> Performance。

Scene は Performance Planner に直接入らない。
SceneReaction が VoiceState（3.5F）だけを変化させ、既存アーキテクチャを維持する。

  Story -> SceneEvent -> VoiceState -> VoiceProfile -> Performance Plan -> HVE

Phase 3.5Q で追加:
- カテゴリ語彙の拡張（arrival / departure / realization / danger / victory / loss /
  embarrassment / silence / comedy）
- 明示的 state_delta: LLM / 手動入力がカテゴリ既定のデルタを上書きできる
  （「出来事 → 状態変化量」だけを外部から受け取り、演技は既存機構に任せる）
- State Decay: イベントに触れなかった VoiceState は毎チャンク基線(0)へ減衰する
  （「怒る → 強い → 数発話 → 徐々に通常へ」の人間っぽい回帰）
- Scene Tone: comedy 等のトーンで過剰演技を抑制する（キャラの感情 ≠ 必ず大声）
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from models import VoiceState

# VoiceState の全キー（SceneReaction / decay / delta 検証で共用）
STATE_KEYS = ("tension", "fatigue", "confidence", "excitement",
              "fear", "anger", "sadness", "embarrassment")


class SceneEvent(BaseModel):
    """シーンで起きたイベント（解析 or 手動入力）。原文を改変しない演出のみ扱う。"""

    description: str
    category: str = "neutral"   # CATEGORY_DELTAS のキー（不明は neutral 扱い）
    targets: list[str] = Field(default_factory=list)  # 直接影響を受けるキャラ id
    intensity: float = 0.5      # 0.0 .. 1.0
    chunk_index: int = 0
    # 3.5Q: 明示的デルタ（カテゴリ既定を上書き）。未知のキーは無視される。
    state_delta: dict[str, float] = Field(default_factory=dict)


# イベントカテゴリ -> VoiceState へのデルタ（0..1 にクランプされる）。
# キーは STATE_KEYS の一部でもよい（無いキーは 0 扱い）。
CATEGORY_DELTAS = {
    "revelation": {"tension": 0.45, "fatigue": 0.05, "confidence": -0.25, "excitement": 0.35, "fear": 0.10},
    "battle_end": {"tension": -0.35, "fatigue": 0.40, "confidence": 0.10, "excitement": -0.45},
    "confession": {"tension": 0.30, "fatigue": 0.00, "confidence": -0.15, "excitement": 0.25, "embarrassment": 0.20},
    "betrayal":   {"tension": 0.50, "fatigue": 0.10, "confidence": -0.30, "excitement": 0.15, "anger": 0.35},
    "relief":     {"tension": -0.45, "fatigue": -0.05, "confidence": 0.20, "excitement": -0.20},
    # ---- 3.5Q 追加語彙 ----
    "arrival":       {"tension": 0.15, "excitement": 0.20},
    "departure":     {"sadness": 0.30, "tension": -0.10, "excitement": -0.15},
    "realization":   {"tension": 0.20, "excitement": 0.30, "confidence": 0.05, "fear": 0.10},
    "danger":        {"fear": 0.45, "tension": 0.40, "excitement": 0.20, "confidence": -0.15},
    "victory":       {"confidence": 0.35, "excitement": 0.35, "tension": -0.30, "anger": -0.20},
    "loss":          {"sadness": 0.45, "tension": 0.15, "confidence": -0.25, "excitement": -0.30},
    "embarrassment": {"embarrassment": 0.50, "tension": 0.25, "confidence": -0.25},
    "silence":       {"excitement": -0.30, "tension": 0.10},
    "comedy":        {"tension": -0.30, "excitement": 0.25, "confidence": 0.10, "embarrassment": 0.10},
    "neutral":    {"tension": 0.00, "fatigue": 0.00, "confidence": 0.00, "excitement": 0.00},
}

# イベントカテゴリ -> Intent 上書き（director.INTENT_SHAPES に実在する名のみ）
CATEGORY_INTENT = {
    "revelation": "awkward_silence",
    "battle_end": "whispered_confession",
    "confession": "hesitant_denial",
    "betrayal": "suppressed_anger",
    "relief": "deadpan",
}


def intent_for(category, emotion_intent=None):
    """イベントカテゴリからの Intent 推定。emotion 由来の Intent より優先される。"""
    return CATEGORY_INTENT.get(category, emotion_intent)


# ---- Scene Tone（3.5Q）: トーンによる演技抑制（キャラの感情 ≠ 必ず大声）----

TONE_CATEGORY = {"comedy": "comedy"}      # category -> scene tone
TONE_ENERGY_SCALE = {"comedy": 0.85}      # tone -> energy 倍率（過剰演技の抑制）


def tone_for_events(events) -> str:
    """イベント列からシーンのトーンを決める（決定論・先勝ち）。"""
    for ev in events or []:
        tone = TONE_CATEGORY.get(getattr(ev, "category", ""))
        if tone:
            return tone
    return "neutral"


def tone_energy_scale(tone) -> float:
    """トーンに応じた energy 倍率。未定義トーンは 1.0（無調整）。"""
    return TONE_ENERGY_SCALE.get(tone, 1.0)


def _clamp(v):
    return max(0.0, min(1.0, v))


def decay_state(state: VoiceState, steps: int = 1, factor: float = 0.55) -> VoiceState:
    """State Decay（3.5Q）: イベントに触れない状態は基線(0)へ減衰する。

    steps チャンク分の減衰を 1 回で適用する（factor^steps）。
    「怒る → 強くなる → 数発話 → 徐々に通常へ」の人間っぽい回帰。決定論。
    """
    f = factor ** max(0, steps)
    return VoiceState(**{k: round(_clamp(getattr(state, k) * f), 6)
                         for k in STATE_KEYS})


def scene_events_from_analysis(analysis, known_ids=None, chunk_index: int = 0
                               ) -> list[SceneEvent]:
    """LLM 解析結果の scene_events -> 検証済み SceneEvent リスト（3.5Q）。

    不明カテゴリは neutral へ、intensity は 0..1 にクランプ、targets は
    known_ids（判明済みキャラ id）にフィルタ、state_delta は未知キーを捨てる。
    LLM の出力揺れを吸収する唯一の入口（ここを通らない生値は使わない）。
    """
    raw = (analysis or {}).get("scene_events") if isinstance(analysis, dict) else None
    events: list[SceneEvent] = []
    if not isinstance(raw, list):
        return events
    for item in raw:
        if not isinstance(item, dict):
            continue
        cat = str(item.get("category") or "neutral").strip() or "neutral"
        if cat not in CATEGORY_DELTAS:
            cat = "neutral"
        try:
            inten = float(item.get("intensity", 0.5))
        except (TypeError, ValueError):
            inten = 0.5
        targets: list[str] = []
        raw_targets = item.get("targets")
        if isinstance(raw_targets, list):
            for t in raw_targets:
                tid = str(t).strip()
                if tid and (known_ids is None or tid in known_ids):
                    targets.append(tid)
        delta: dict[str, float] = {}
        raw_delta = item.get("state_delta")
        if isinstance(raw_delta, dict):
            for k, v in raw_delta.items():
                if k in STATE_KEYS:
                    try:
                        delta[k] = float(v)
                    except (TypeError, ValueError):
                        continue
        events.append(SceneEvent(
            description=str(item.get("description") or ""),
            category=cat,
            targets=targets,
            intensity=max(0.0, min(1.0, inten)),
            chunk_index=chunk_index,
            state_delta=delta,
        ))
    return events


class SceneReaction:
    """1 つの SceneEvent を全キャラの VoiceState へ変換する（決定論・副作用なし）。

    - targets に含まれるキャラはフル効果（x event.intensity）
    - それ以外は減衰（x0.4 x event.intensity）: 場の空気が周囲にも伝播する
    - event.state_delta があればカテゴリ既定を上書きする（3.5Q）
    """

    ATTENUATION = 0.4

    def __init__(self, event: SceneEvent):
        self.event = event

    def for_character(self, char_id, base=None):
        """char_id のイベント後 VoiceState を返す。base が無ければゼロから。"""
        base = base or VoiceState()
        d = dict(CATEGORY_DELTAS.get(self.event.category, CATEGORY_DELTAS["neutral"]))
        for k, v in (self.event.state_delta or {}).items():
            if k in STATE_KEYS:
                d[k] = float(v)
        scale = self.event.intensity
        if char_id not in self.event.targets:
            scale *= self.ATTENUATION
        return VoiceState(**{
            k: _clamp(getattr(base, k) + d.get(k, 0.0) * scale)
            for k in STATE_KEYS
        })