"""Story Engine のデータモデル（pydantic）。

将来 C++ Core に移植するときの構造の叩き台。
Voice Profile（キャラ固有・不変）と Performance（セグメント毎・可変）を厳密に分離する。
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Gender = Literal["male", "female", "unknown"]
Age = Literal["child", "young", "adult", "elder"]
SegmentType = Literal["narration", "dialogue", "inner_monologue"]
Mode = Literal["narration", "dialogue", "internal"]


class VoiceProfile(BaseModel):
    """キャラクター固有の声の素（不変）。"""

    voice_id: str
    label: str = ""
    gender: Gender = "unknown"
    age: Age = "adult"
    base_pitch: float = 0.0   # -1.0 .. 1.0
    base_pace: float = 1.0    # 0.5 .. 1.5
    tts_voice: str = ""       # TTSプロバイダ固有のボイス名


class Character(BaseModel):
    id: str
    name: str
    gender: Gender = "unknown"
    age: Age = "adult"
    role: str = ""            # main / side / ...
    traits: list[str] = Field(default_factory=list)
    relationships: dict[str, str] = Field(default_factory=dict)
    voice: Optional[VoiceProfile] = None
    # 直近の感情状態（Memory Engine から供給され、プロンプトと演技に使われる）
    last_emotion: Optional[str] = None
    last_intensity: Optional[float] = None
    last_chunk: Optional[int] = None


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
            rel = ", ".join(f"{k}: {v}" for k, v in ch.relationships.items()) or "なし"
            traits = ", ".join(ch.traits) or "なし"
            line = f"- {ch.name}(id={ch.id}, gender={ch.gender}, traits={traits}, 関係={rel})"
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

    voice: str                       # voice_id
    mode: Mode
    emotion: str
    intensity: float                 # 0.0 .. 1.0
    pace: float                      # 0.5 .. 1.5
    pitch: float                     # -1.0 .. 1.0
    volume: float = 1.0              # 0.5 .. 1.5
    carryover: bool = False          # 前チャンクの感情の余韻を適用したか


class DirectedSegment(Segment):
    """Performance が付与されたセグメント（TTS に渡せる状態）。"""

    performance: Optional[Performance] = None
