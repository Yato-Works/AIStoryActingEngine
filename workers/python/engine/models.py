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
    tags: list[str] = Field(default_factory=list)  # ["重厚", "渋い", "低音", "成年"]
    description: str = ""
    # --- TTS Abstraction §8: Voice Consistency ---
    # キャラクターごとに Backend 別の設定を保持する。
    # 例: {"sbv2": {"model_name": "jvnv-M1-jp", "style": "Neutral"},
    #       "indextts": {"reference_audio": "kevin_sample.wav"}}
    # 通常の作品再生では 1 キャラクター 1 Backend を固定し、
    # 意図しない声質変化を防ぐ。
    backend_profiles: dict[str, dict] = Field(default_factory=dict)


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


# =================================================================
# VoiceMem Dual-Brain Architecture (Phase 4)
# =================================================================

class LBSchema(BaseModel):
    """左脳: 物語スキーマ（シーン類型）。

    例: 「戦闘」「会話」「回想」「修練」「移動」「日常」
    """
    schema_id: str
    label: str = ""           # 「戦闘シーン」「会話シーン」等
    book_id: str = ""


class LBEntity(BaseModel):
    """左脳: エンティティ（登場人物・場所・アイテム・イベント）。

    各エンティティは特定のスキーマに割り当てられ、ノード間のエッジが
    意味的関係性を保持する。
    """
    entity_id: str
    schema_id: str = ""       # 属するスキーマ
    label: str = ""           # 表示名「ルーデウス」「ブエナ村」
    entity_type: str = ""     # character / location / item / event / organization
    book_id: str = ""


class LBMemItem(BaseModel):
    """左脳: 記憶項目（MemItem）— 階層的最下層の事実記憶。

    各MemItemは特定のEntityに紐付き、物語の特定チャンクで発生した
    具体的な事実を保持する。
    """
    item_id: str
    entity_id: str = ""       # 紐付くEntity
    chunk_index: int = 0
    content: str = ""         # 事実の要約「ルーデウスが水弾を習得」
    importance: float = 0.5    # 0.0-1.0 物語的重要性（転移事件=1.0、朝食=0.1）
    chapter: int = 1
    book_id: str = ""


class LBCluster(BaseModel):
    """左脳: クラスタ — 動的昇格された高次検索クラスタ。

    頻繁に共同検索されるMemItem群が、凝集度スコア ρ(H) > α を超えると
    LLMジャッジ検証を経て独立したクラスタへ昇格する。
    例: 「ブエナ村修練期」「転移事件」「エリス同行期」
    """
    cluster_id: str
    label: str = ""           # 「ブエナ村での幼少期修練」
    memitem_ids: list[str] = Field(default_factory=list)
    cohesion_score: float = 0.0  # ρ(H) 凝集度
    chapter_range: str = ""   # 「1-3」「5-8」
    book_id: str = ""
    created_at: str = ""
    promoted_chunk: int = 0   # 昇格したチャンクindex


class RBIndependent(BaseModel):
    """右脳: 独立ノード（Independent Node）— 定常特性。

    時間変化に対して安定した、キャラクターの本質的な特性。
    VoiceMemの「ユーザーの永続的な性格や価値観」を保持。
    """
    character_id: str
    core_personality: list[str] = Field(default_factory=list)   # ["前向き", "ナイーブ"]
    core_trauma: str = ""      # 「前世の無職による後悔」
    core_values: list[str] = Field(default_factory=list)        # ["努力", "家族の絆"]
    baseline_voice_state: VoiceState = Field(default_factory=VoiceState)
    core_fears: list[str] = Field(default_factory=list)         # ["再び無職になること"]
    core_desires: list[str] = Field(default_factory=list)       # ["魔法で一流になる"]


class RBDynamic(BaseModel):
    """右脳: 動的ノード（Dynamic Node）— 文脈依存の感情傾向。

    チャンクごとに更新される、キャラクターの現在の感情状態。
    VoiceMemの「文脈依存の感情傾向」と「左脳Entityへの動的関連付け」を統合。
    """
    id: Optional[int] = None
    character_id: str
    chunk_index: int = 0
    voice_state: VoiceState = Field(default_factory=VoiceState)
    toward_character: Optional[str] = None   # 対象キャラ（null=一般的感情）
    emotion_label: str = "neutral"
    intensity: float = 0.0
    decay_factor: float = 0.55   # transient=0.45-0.60, persistent=0.85-0.90
    trigger_event: str = ""      # この感情を引き起こした左脳MemItem/Cluster
    book_id: str = ""
    created_at: str = ""


class CrossLink(BaseModel):
    """クロスグラフリンク L^{IA} — 左脳と右脳を横断的に結合。

    「この事実がこの感情を引き起こした」という因果を明示的に保持。
    例: 「パウロとの喧嘩(MemItem)」→「パウロへの怒り(Dynamic Node)」
    """
    id: Optional[int] = None
    left_item_id: str = ""      # lb_memitems.item_id or lb_clusters.cluster_id
    left_type: str = "memitem"  # "memitem" / "cluster"
    right_node_id: str = ""     # rb_dynamic.id (文字列化)
    link_type: str = "caused"   # caused / reinforced / contradicted / triggered
    strength: float = 0.5        # 0.0-1.0 リンクの強度
    chunk_index: int = 0
    book_id: str = ""


class AffectiveSummary(BaseModel):
    """右脳感情状態の要約 — Dossier生成用の軽量表現。

    Top-K=5検索で使用する、コンパクトな感情コンテキスト。
    """
    character_id: str
    current_state: VoiceState = Field(default_factory=VoiceState)
    dominant_emotion: str = "neutral"
    dominant_target: Optional[str] = None   # 感情の対象キャラ
    recent_events: list[str] = Field(default_factory=list)  # 最近の感情変化要因
    persistent_mood: str = ""   # 持続的な気分（「悲しみが癒えかけている」）


class RichDossier(BaseModel):
    """VoiceMem版強化Dossier — 二元脳情報を統合したDirector入力。

    既存のDossier（人物+関係+場面）に加え、左脳の物語クラスタと
    右脳の感情状態、両者の因果リンクを含む。

    Top-K=5設計: 左脳クラスタは最大5件、右脳動的ノードも最大5件、
    クロスリンクも最大5件のみを含める（VoiceMem式省資源設計）。
    """
    # --- 既存Dossierと同等の基本情報 ---
    character: Character
    listener: Optional[Character] = None
    relationship: Optional[Relationship] = None
    carryover: Optional[tuple[str, float]] = None
    recent: list[str] = Field(default_factory=list)
    scene: str = ""
    mood: str = ""

    # --- VoiceMem追加: 左脳（物語記憶）---
    leftbrain_clusters: list[LBCluster] = Field(default_factory=list)
    leftbrain_memitems: list[LBMemItem] = Field(default_factory=list)

    # --- VoiceMem追加: 右脳（感情記憶）---
    rightbrain_independent: Optional[RBIndependent] = None
    rightbrain_dynamics: list[RBDynamic] = Field(default_factory=list)
    affective_summary: Optional[AffectiveSummary] = None

    # --- VoiceMem追加: クロスリンク（因果）---
    cross_links: list[CrossLink] = Field(default_factory=list)

    # --- VoiceMem追加: エピソード文脈 ---
    episode_context: str = ""   # LLM生成の「この時点までの物語要約（300字以内）"

    def to_director_prompt(self) -> str:
        """Voice Director へのプロンプト用テキスト生成。"""
        lines: list[str] = []
        lines.append(f"【キャラクター】{self.character.name}")
        if self.rightbrain_independent:
            rb = self.rightbrain_independent
            if rb.core_personality:
                lines.append(f"  本質的性格: {', '.join(rb.core_personality)}")
            if rb.core_trauma:
                lines.append(f"  核心トラウマ: {rb.core_trauma}")
        if self.affective_summary:
            a = self.affective_summary
            lines.append(f"  現在の感情: {a.dominant_emotion}(強さ{a.current_state.excitement:.1f})")
            if a.persistent_mood:
                lines.append(f"  持続的気分: {a.persistent_mood}")
        if self.leftbrain_clusters:
            lines.append("  関連エピソード:")
            for c in self.leftbrain_clusters[:5]:
                lines.append(f"    • {c.label}")
        if self.cross_links:
            lines.append("  感情の起因:")
            for link in self.cross_links[:5]:
                lines.append(f"    • {link.link_type}(強度{link.strength:.1f})")
        return "\n".join(lines)
