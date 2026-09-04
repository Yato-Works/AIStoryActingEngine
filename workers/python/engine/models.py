"""Story Engine のデータモデル（pydantic）。

将来 C++ Core に移植するときの構造の叩き台。
Voice Profile（キャラ固有・不変）と Performance（セグメント毎・可変）を厳密に分離する。

Phase 2: Character Intelligence
- Character に personality / speech_style / emotional_baseline / emotional_range を追加
- Relationship を型付き有向グラフ（loves / friend / rival ...）に拡張
- 同一キャラに External（外向き）と Internal（内面）の 2 声を持たせる
- Dossier: Director への唯一の入力（人物+関係+場+記憶を 1 オブジェクトに）
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Gender = Literal["male", "female", "unknown"]
Age = Literal["child", "young", "adult", "elder"]
SegmentType = Literal["narration", "dialogue", "inner_monologue"]
Mode = Literal["narration", "dialogue", "internal"]
Voicing = Literal["external", "internal", "narrator"]


class VoiceProfile(BaseModel):
    """キャラクター固有の声の素（不変）。

    tts_voice は edge-tts 等のボイス名、sbv2_style は Style-Bert-VITS2 の
    style（=モデル内スピーカー）名。どちらかを使うプロバイダ側で解釈する。
    """

    voice_id: str
    label: str = ""
    gender: Gender = "unknown"
    age: Age = "adult"
    base_pitch: float = 0.0   # -1.0 .. 1.0
    base_pace: float = 1.0    # 0.5 .. 1.5
    tts_voice: str = ""       # TTSプロバイダ固有のボイス名
    sbv2_model_name: str = "jvnv-M1-jp"  # Style-Bert-VITS2 の model_assets 内ディレクトリ名
    sbv2_model_id: int = 0    # model_name 未指定時のフォールバック
    sbv2_style: str = "Neutral"
    base_energy: float = 0.8            # 0.5 .. 1.5
    hesitation: float = 0.0            # 0.0 .. 1.0  (言い出し早さ)
    pause_tendency: float = 0.0        # 0.0 .. 1.0  (間を取りやすさ)
    breath_frequency: float = 0.0      # 0.0 .. 1.0  (呼吸の多さ)
    sentence_end_drop: float = 0.0     # 0.0 .. 1.0  (語尾下げ)
    emphasis_strength: float = 0.0     # 0.0 .. 1.0  (強調傾向)
    emotional_reactivity: float = 0.5  # 0.0 .. 1.0  (感情起伍の激しさ)
    habits: dict[str, str] = Field(default_factory=dict)  # thinking/surprise/disbelief 口頭語
    timing_habit: float = 0.0      # 0.0 .. 1.0  (response delay / timing癖)
    source: str = "builtin"        # builtin / user / cloned
    tags: list[str] = Field(default_factory=list)  # ["杉田智和風", "渋い", "低音", "中年"]
    description: str = ""


class Series(BaseModel):
    """複数巻（1巻、2巻...）を束ねるシリーズ単位。声の引き継ぎ設定を保持。"""

    id: str
    title: str
    description: str = ""
    # character_name or id -> {"voice_id": "...", "voice_internal_id": "..."}
    castings: dict[str, dict[str, str]] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


class CharacterCasting(BaseModel):
    """書籍またはシリーズにおけるキャラクターへのボイス配役。"""

    character_id: str
    character_name: str = ""
    voice_id: str
    voice_internal_id: Optional[str] = None
    is_locked: bool = False  # ユーザーが明示的に指定した場合はTrue（自動再配役で上書きしない）
    notes: str = ""


class VoiceState(BaseModel):
    """キャラクターの現在の演技状態（可変）。

    tension / fatigue / confidence / excitement はそれぞれ 0.0..1.0。
    apply_voice_state が time-based prosody curve に変調を加える。
    Phase 3.5Q: fear / anger / sadness / embarrassment を追加
    （SceneEvent のデルタ受け口。既存 4 状態と同様に 0.0..1.0、デフォルト 0）。
    """

    tension: float = 0.0
    fatigue: float = 0.0
    confidence: float = 0.0
    excitement: float = 0.0
    fear: float = 0.0
    anger: float = 0.0
    sadness: float = 0.0
    embarrassment: float = 0.0

class Relationship(BaseModel):
    """キャラクター src → dst の有向関係。"""

    type: str = "other"       # 契約語彙は schema.RELATIONSHIP_TYPES
    label: str = ""           # 自由テキスト（「告白の相手」等）


class Character(BaseModel):
    id: str
    name: str
    gender: Gender = "unknown"
    age: Age = "adult"
    role: str = ""            # main / side / ...
    traits: list[str] = Field(default_factory=list)
    # --- Phase 2: Character Intelligence ---
    personality: list[str] = Field(default_factory=list)   # ["calm", "awkward"]
    speech_style: str = ""                                 # polite / casual / rough / formal
    emotional_baseline: str = "neutral"                    # 普段の感情の基調
    emotional_range: float = 0.5                           # 0.0(静) .. 1.0(激しい起伏)
    relationships: dict[str, Relationship] = Field(default_factory=dict)
    voice: Optional[VoiceProfile] = None                   # External（外向き）
    voice_internal: Optional[VoiceProfile] = None          # Internal（内面）
    # 直近の感情状態（Memory Engine から供給され、プロンプトと演技に使われる）
    last_emotion: Optional[str] = None
    last_intensity: Optional[float] = None
    last_chunk: Optional[int] = None
    voice_state: Optional[VoiceState] = None   # 現在の演技状態（Phase 3.5F）


class Dossier(BaseModel):
    """Voice Director への唯一の入力。Memory Engine が組み立てる「身辺調査書」。"""

    character: Character
    listener: Optional[Character] = None          # このセグメントの聞き手（不明なら None）
    relationship: Optional[Relationship] = None   # speaker → listener の関係
    carryover: Optional[tuple[str, float]] = None # 直近チャンクの感情残響
    recent: list[str] = Field(default_factory=list)  # 直近の感情記憶（新しい順）
    scene: str = ""
    mood: str = ""


class StoryState(BaseModel):
    """物語の現在状態。チャンク解析のたびに更新される「記憶」。"""

    scene: str = ""
    time_of_day: str = ""
    mood: str = ""
    characters: dict[str, Character] = Field(default_factory=dict)

    def summary(self) -> str:
        """LLM プロンプトに渡す用の要約。感情の余韻も含む。"""
        lines: list[str] = []
        if self.scene:
            lines.append(f"- 場面: {self.scene}")
        if self.time_of_day:
            lines.append(f"- 時間帯: {self.time_of_day}")
        if self.mood:
            lines.append(f"- 雰囲気: {self.mood}")
        for ch in self.characters.values():
            rel = ", ".join(
                f"{k}({v.type}: {v.label})" for k, v in ch.relationships.items()
            ) or "なし"
            traits = ", ".join(ch.traits) or "なし"
            pers = ", ".join(ch.personality) or "なし"
            line = (f"- {ch.name}(id={ch.id}, gender={ch.gender}, age={ch.age}, "
                    f"role={ch.role}, 性格={pers}, traits={traits}, "
                    f"話し方={ch.speech_style or 'unknown'}, 関係={rel})")
            if ch.emotional_baseline != "neutral":
                line += f" ※感情の基調: {ch.emotional_baseline}(起伏{ch.emotional_range:.1f})"
            if ch.last_emotion and ch.last_emotion != "neutral":
                line += f" ※直近の感情: {ch.last_emotion}(強さ{ch.last_intensity:.1f}, チャンク{ch.last_chunk})"
            lines.append(line)
        return "\n".join(lines) if lines else "- まだ何もわかっていない"


class Segment(BaseModel):
    """解析結果の最小発話単位。"""

    id: str
    type: SegmentType
    speaker: str                     # "narrator" またはキャラクター id
    text: str
    emotion: str = "neutral"
    intensity: float = 0.3           # 0.0 .. 1.0
    chapter: int = 1
    chunk_index: int = 0


class Performance(BaseModel):
    """Voice Director が生成する演技指示。TTS への入力契約。"""

    voice: str                       # voice_id（voicing に応じて external/internal を解決済み）
    mode: Mode
    emotion: str
    intensity: float                 # 0.0 .. 1.0
    pace: float                      # 0.5 .. 1.5
    pitch: float                     # -1.0 .. 1.0
    volume: float = 1.0              # 0.5 .. 1.5
    voicing: Voicing = "external"    # external(外向き) / internal(内面) / narrator
    style: str = ""                  # TTS 固有のスタイル名（SBV2 の style 等）
    carryover: bool = False          # 前チャンクの感情の余韻を適用したか
    baseline: bool = False           # 感情の基調（emotional_baseline）を適用したか
    relationship: str = ""           # 演出に使った関係タイプ（loves 等）


class DirectedSegment(Segment):
    """Performance が付与されたセグメント（TTS に渡せる状態）。"""

    performance: Optional[Performance] = None

