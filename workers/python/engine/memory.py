"""Memory Engine — Phase 1 の中核。

SQLite 1 ファイルに物語の全状態を永続化する:

- characters      : キャラクター + Voice Profile + 直近の感情状態
- relationships   : キャラクター間の関係性
- scenes          : 場面・時間帯・雰囲気の推移
- chunk_analysis  : 解析済みチャンク（resume の基準）
- memories(+FTS5) : キャラクターの感情記憶と本文の全文検索
- segments        : 演技指示済みセグメント（audio_path でTTS進捗管理）
- events          : Event Log（Single Source of Truth）

「前の章で怒っていたから今の声も少し険しい」は get_carryover() が担う。
将来 C++ Core に移植するときはこのスキーマとイベント種別が契約になる。
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from models import (Character, CharacterCasting, DirectedSegment, Dossier,
                    Relationship, Series, StoryState, VoiceProfile, VoiceState)
import schema as contracts


def _spaced(text: str) -> str:
    """CJK 文字を 1 字ずつスペース区切りにする（FTS5 の日本語対応）。

    デフォルトの unicode61 トークナイザーは「鈴の音がした」を 1 トークン扱い
    するため、書き込み時に分割しておき、検索時はフレーズ検索で連続性を担保する。
    """
    parts = re.findall(r"[A-Za-z0-9]+|\S", text)
    return " ".join(parts)


def _fts_query(query: str) -> str:
    terms = query.split()
    out: list[str] = []
    for term in terms:
        if re.fullmatch(r"[A-Za-z0-9]+", term):
            out.append(term)
        else:
            out.append(f'"{_spaced(term)}"')
    return " ".join(out)

SCHEMA = """
CREATE TABLE IF NOT EXISTS books(
  id TEXT PRIMARY KEY, title TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS characters(
  book_id TEXT, id TEXT, name TEXT, gender TEXT, age TEXT, role TEXT,
  traits TEXT, voice_json TEXT,
  first_chunk INTEGER, last_emotion TEXT, last_intensity REAL, last_chunk INTEGER,
  personality TEXT, speech_style TEXT, baseline TEXT, erange REAL,
  voice_internal_json TEXT,
  PRIMARY KEY(book_id, id));
CREATE TABLE IF NOT EXISTS relationships(
  book_id TEXT, src_id TEXT, dst_id TEXT, label TEXT, type TEXT,
  PRIMARY KEY(book_id, src_id, dst_id));
CREATE TABLE IF NOT EXISTS scenes(
  book_id TEXT, chapter INTEGER, chunk_index INTEGER,
  description TEXT, time_of_day TEXT, mood TEXT);
CREATE TABLE IF NOT EXISTS chunk_analysis(
  book_id TEXT, chunk_index INTEGER, chapter INTEGER,
  PRIMARY KEY(book_id, chunk_index));
CREATE TABLE IF NOT EXISTS memories(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  book_id TEXT, chunk_index INTEGER, character_id TEXT,
  kind TEXT, emotion TEXT, intensity REAL, content TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
  content, book_id UNINDEXED, chunk_index UNINDEXED,
  character_id UNINDEXED, kind UNINDEXED);
CREATE TABLE IF NOT EXISTS segments(
  book_id TEXT, id TEXT, chapter INTEGER, chunk_index INTEGER,
  type TEXT, speaker TEXT, text TEXT,
  emotion TEXT, intensity REAL, performance TEXT, audio_path TEXT,
  PRIMARY KEY(book_id, id));
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, type TEXT, payload TEXT);
-- ---- Job System (ADR-0003): Event Log が SSOT。ここは進捗/checkpoint のみ ----
CREATE TABLE IF NOT EXISTS jobs(
  id TEXT PRIMARY KEY, book_id TEXT, type TEXT, status TEXT,
  payload TEXT, error TEXT,
  created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS job_steps(
  job_id TEXT, seq INTEGER, name TEXT, status TEXT,
  progress INTEGER DEFAULT 0, progress_total INTEGER DEFAULT 0,
  checkpoint TEXT, error TEXT,
  started_at TEXT, finished_at TEXT, updated_at TEXT,
  PRIMARY KEY(job_id, seq));
CREATE TABLE IF NOT EXISTS job_artifacts(
  job_id TEXT, step_seq INTEGER, kind TEXT, path TEXT, created_at TEXT,
  PRIMARY KEY(job_id, step_seq, kind, path));
-- ---- Scene Context (3.5Q): VoiceState の永続化 + SceneEvent ログ ----
CREATE TABLE IF NOT EXISTS voice_states(
  book_id TEXT, character_id TEXT, state_json TEXT,
  updated_chunk INTEGER, updated_at TEXT,
  PRIMARY KEY(book_id, character_id));
CREATE TABLE IF NOT EXISTS scene_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  book_id TEXT, chunk_index INTEGER, category TEXT, description TEXT,
  intensity REAL, targets TEXT, tone TEXT);
-- ---- Dynamic Voice Registry & Series & Castings ----
CREATE TABLE IF NOT EXISTS voice_registry(
  voice_id TEXT PRIMARY KEY, label TEXT, gender TEXT, age TEXT,
  base_pitch REAL, base_pace REAL, base_energy REAL,
  tts_voice TEXT, sbv2_model_name TEXT, sbv2_model_id INTEGER, sbv2_style TEXT,
  source TEXT, tags TEXT, description TEXT, profile_json TEXT,
  created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS series(
  id TEXT PRIMARY KEY, title TEXT, description TEXT, castings_json TEXT,
  created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS character_castings(
  book_id TEXT, character_id TEXT, character_name TEXT,
  voice_id TEXT, voice_internal_id TEXT, is_locked INTEGER DEFAULT 0,
  notes TEXT,
  PRIMARY KEY(book_id, character_id));
CREATE INDEX IF NOT EXISTS idx_segments_speaker ON segments(book_id, speaker);
CREATE INDEX IF NOT EXISTS idx_memories_char ON memories(book_id, character_id);
CREATE INDEX IF NOT EXISTS idx_castings_book ON character_castings(book_id);
-- ==== VoiceMem Dual-Brain (Phase 4) ====
-- 左脳: 階層的ファクト記憶 Schema -> Entity -> MemItem
CREATE TABLE IF NOT EXISTS lb_schemas(
  schema_id TEXT PRIMARY KEY, label TEXT, book_id TEXT);
CREATE TABLE IF NOT EXISTS lb_entities(
  entity_id TEXT PRIMARY KEY, schema_id TEXT, label TEXT,
  entity_type TEXT, book_id TEXT);
CREATE TABLE IF NOT EXISTS lb_memitems(
  item_id TEXT PRIMARY KEY, entity_id TEXT, chunk_index INTEGER,
  content TEXT, importance REAL, chapter INTEGER, book_id TEXT);
-- 左脳: クラスタ（動的昇格）
CREATE TABLE IF NOT EXISTS lb_clusters(
  cluster_id TEXT PRIMARY KEY, label TEXT, memitem_ids TEXT,
  cohesion_score REAL, chapter_range TEXT, book_id TEXT,
  created_at TEXT, promoted_chunk INTEGER);
-- 右脳: 定常特性（Independent Node）
CREATE TABLE IF NOT EXISTS rb_independent(
  character_id TEXT PRIMARY KEY,
  core_personality TEXT, core_trauma TEXT, core_values TEXT,
  core_fears TEXT, core_desires TEXT,
  baseline_voice_state TEXT);
-- 右脳: 動的ノード（Dynamic Node）
CREATE TABLE IF NOT EXISTS rb_dynamic(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  character_id TEXT, chunk_index INTEGER,
  voice_state TEXT, toward_character TEXT,
  emotion_label TEXT, intensity REAL, decay_factor REAL,
  trigger_event TEXT, book_id TEXT, created_at TEXT);
-- クロスグラフリンク L^{IA}
CREATE TABLE IF NOT EXISTS cross_links(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  left_item_id TEXT, left_type TEXT DEFAULT 'memitem',
  right_node_id TEXT, link_type TEXT, strength REAL,
  chunk_index INTEGER, book_id TEXT);
-- VoiceMem インデックス
CREATE INDEX IF NOT EXISTS idx_lb_memitems_entity ON lb_memitems(entity_id);
CREATE INDEX IF NOT EXISTS idx_lb_memitems_chunk ON lb_memitems(book_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_rb_dynamic_char ON rb_dynamic(character_id, book_id);
CREATE INDEX IF NOT EXISTS idx_rb_dynamic_chunk ON rb_dynamic(book_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_cross_left ON cross_links(left_item_id, book_id);
CREATE INDEX IF NOT EXISTS idx_cross_right ON cross_links(right_node_id, book_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MemoryEngine:
    """SQLite で物語状態を管理する Memory Engine。"""

    # Phase 1 DB → Phase 2 の列追加マイグレーション
    _MIGRATIONS = [
        ("characters", "personality", "TEXT"),
        ("characters", "speech_style", "TEXT"),
        ("characters", "baseline", "TEXT"),
        ("characters", "erange", "REAL"),
        ("characters", "voice_internal_json", "TEXT"),
        ("relationships", "type", "TEXT"),
        ("books", "series_id", "TEXT"),
    ]

    def _migrate(self) -> None:
        for table, col, typ in self._MIGRATIONS:
            cols = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        self.conn.commit()

    def __init__(self, db_path: Path, book_id: str, title: str = "") -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.execute(
            "INSERT OR IGNORE INTO books(id, title, created_at) VALUES(?,?,?)",
            (book_id, title or book_id, _now()),
        )
        self.conn.commit()
        self.book_id = book_id

    # -------------------------------------------------------------- events

    def append_event(self, type_: str, **payload) -> None:
        self.conn.execute(
            "INSERT INTO events(ts, type, payload) VALUES(?,?,?)",
            (_now(), type_, json.dumps(payload, ensure_ascii=False)),
        )
        self.conn.commit()

    def events_tail(self, limit: int = 20) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT ts, type, payload FROM events ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()

    def count_events(self, type_: str | None = None) -> int:
        if type_:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n FROM events WHERE type=?", (type_,)).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()
        return int(row["n"])

    # -------------------------------------------------------------- characters

    def upsert_character(self, ch: Character, chunk_index: int) -> None:
        self.conn.execute(
            """INSERT INTO characters(book_id, id, name, gender, age, role, traits,
                                      voice_json, first_chunk, last_emotion,
                                      last_intensity, last_chunk,
                                      personality, speech_style, baseline, erange,
                                      voice_internal_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(book_id, id) DO UPDATE SET
                 name=excluded.name, gender=excluded.gender, age=excluded.age,
                 role=excluded.role, traits=excluded.traits,
                 personality=excluded.personality, speech_style=excluded.speech_style,
                 baseline=excluded.baseline, erange=excluded.erange,
                 voice_internal_json=excluded.voice_internal_json""",
            (self.book_id, ch.id, ch.name, ch.gender, ch.age, ch.role,
             json.dumps(ch.traits, ensure_ascii=False),
             ch.voice.model_dump_json() if ch.voice else None,
             chunk_index, ch.last_emotion, ch.last_intensity, ch.last_chunk,
             json.dumps(ch.personality, ensure_ascii=False), ch.speech_style,
             ch.emotional_baseline, ch.emotional_range,
             ch.voice_internal.model_dump_json() if ch.voice_internal else None),
        )
        self.conn.commit()

    def update_emotional_state(self, char_id: str, emotion: str,
                               intensity: float, chunk_index: int) -> None:
        self.conn.execute(
            """UPDATE characters SET last_emotion=?, last_intensity=?, last_chunk=?
               WHERE book_id=? AND id=?""",
            (emotion, intensity, chunk_index, self.book_id, char_id),
        )
        self.conn.commit()

    def save_voice_profile(self, ch: Character) -> None:
        """External / Internal 両方の Voice Profile を保存する。"""
        sets: list[str] = []
        params: list[object] = []
        if ch.voice is not None:
            sets.append("voice_json=?")
            params.append(ch.voice.model_dump_json())
        if ch.voice_internal is not None:
            sets.append("voice_internal_json=?")
            params.append(ch.voice_internal.model_dump_json())
        if not sets:
            return
        params += [self.book_id, ch.id]
        self.conn.execute(
            f"UPDATE characters SET {', '.join(sets)} WHERE book_id=? AND id=?",
            params,
        )
        self.conn.commit()

    # ------------------------------------------------------- voice state (3.5Q)

    _VOICE_STATE_KEYS = ("tension", "fatigue", "confidence", "excitement",
                         "fear", "anger", "sadness", "embarrassment")

    def get_voice_state(self, character_id: str) -> VoiceState | None:
        """永続化された演技状態（無ければ None）。"""
        row = self.conn.execute(
            "SELECT state_json FROM voice_states WHERE book_id=? AND character_id=?",
            (self.book_id, character_id),
        ).fetchone()
        return VoiceState.model_validate_json(row["state_json"]) if row else None

    def save_voice_state(self, character_id: str, state: VoiceState,
                         chunk_index: int | None = None) -> None:
        """VoiceState を保存し、変化があれば Event Log にも流す（SSOT 原則）。"""
        old = self.get_voice_state(character_id)
        self.conn.execute(
            """INSERT INTO voice_states(book_id, character_id, state_json,
                                        updated_chunk, updated_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(book_id, character_id) DO UPDATE SET
                 state_json=excluded.state_json,
                 updated_chunk=excluded.updated_chunk,
                 updated_at=excluded.updated_at""",
            (self.book_id, character_id, state.model_dump_json(),
             chunk_index, _now()),
        )
        self.conn.commit()
        if old is None or old != state:
            base = old or VoiceState()
            delta = {k: round(getattr(state, k) - getattr(base, k), 3)
                     for k in self._VOICE_STATE_KEYS
                     if getattr(state, k) != getattr(base, k)}
            self.append_event("VOICE_STATE_CHANGED", character=character_id,
                              delta=delta, chunk=chunk_index)

    def add_scene_event(self, chunk_index: int, category: str, description: str,
                        intensity: float, targets: list[str],
                        tone: str = "neutral") -> None:
        """SceneEvent を記録し、Event Log にも流す（3.5Q）。"""
        self.conn.execute(
            """INSERT INTO scene_events(book_id, chunk_index, category,
                                        description, intensity, targets, tone)
               VALUES(?,?,?,?,?,?,?)""",
            (self.book_id, chunk_index, category, description,
             intensity, json.dumps(targets, ensure_ascii=False), tone),
        )
        self.conn.commit()
        self.append_event("SCENE_EVENT", chunk=chunk_index, category=category,
                          intensity=round(intensity, 3),
                          targets=targets, tone=tone)

    def scene_tone(self, chunk_index: int) -> str:
        """チャンクに記録された Scene Tone（無ければ neutral）。"""
        row = self.conn.execute(
            """SELECT tone FROM scene_events
               WHERE book_id=? AND chunk_index=? ORDER BY id DESC LIMIT 1""",
            (self.book_id, chunk_index),
        ).fetchone()
        return str(row["tone"]) if row and row["tone"] else "neutral"

    def upsert_relationship(self, src_id: str, dst_id: str, label: str,
                            type_: str = "other") -> None:
        """有向関係を保存。対称な型は逆向きも自動生成する。"""
        if not src_id or not dst_id or src_id == dst_id:
            return
        self.conn.execute(
            """INSERT INTO relationships(book_id, src_id, dst_id, label, type) VALUES(?,?,?,?,?)
               ON CONFLICT(book_id, src_id, dst_id) DO UPDATE SET
                 label=excluded.label, type=excluded.type""",
            (self.book_id, src_id, dst_id, label, type_),
        )
        if type_ in contracts.SYMMETRIC_RELATIONSHIPS:
            # 逆向きは「無い場合だけ」自動生成（既存の有向エッジは上書きしない）
            self.conn.execute(
                """INSERT INTO relationships(book_id, src_id, dst_id, label, type) VALUES(?,?,?,?,?)
                   ON CONFLICT(book_id, src_id, dst_id) DO NOTHING""",
                (self.book_id, dst_id, src_id, label, type_),
            )
        self.conn.commit()

    def relationship_pairs(self) -> set[tuple[str, str]]:
        """既存の有向エッジ (src, dst) の集合（イベント重複排除用）。"""
        rows = self.conn.execute(
            "SELECT src_id, dst_id FROM relationships WHERE book_id=?",
            (self.book_id,),
        ).fetchall()
        return {(r["src_id"], r["dst_id"]) for r in rows}

    def get_relationship(self, src_id: str, dst_id: str) -> Relationship | None:
        """src → dst の有向関係を返す。

        直接のエッジが無い場合は逆向きを探し、非対称な型は
        演出用に反転不能な意味へ落として返す（loves の逆は other）。
        """
        row = self.conn.execute(
            """SELECT type, label FROM relationships
               WHERE book_id=? AND src_id=? AND dst_id=?""",
            (self.book_id, src_id, dst_id),
        ).fetchone()
        if row:
            return Relationship(type=row["type"] or "other", label=row["label"] or "")
        row = self.conn.execute(
            """SELECT type, label FROM relationships
               WHERE book_id=? AND src_id=? AND dst_id=?""",
            (self.book_id, dst_id, src_id),
        ).fetchone()
        if row:
            t = row["type"] or "other"
            if t in contracts.SYMMETRIC_RELATIONSHIPS or t == "other":
                return Relationship(type=t, label=row["label"] or "")
            # 非対称（loves / respects / trusts / despises / owes）の逆向き
            return Relationship(type="other", label=f"相手からの片方向: {t}")
        return None

    def get_dossier(self, char_id: str, listener_id: str | None,
                    chunk_index: int, state: StoryState) -> Dossier | None:
        """Voice Director へ渡す Dossier を組み立てる（Memory Engine の集約点）。

        人物 + 聞き手との関係 + 感情の余韻 + 直近の感情記憶 + 場面 → 1 オブジェクト。
        """
        character = state.characters.get(char_id)
        if character is None:
            return None
        listener = state.characters.get(listener_id) if listener_id else None
        relationship = (
            self.get_relationship(char_id, listener_id) if listener_id else None
        )
        carryover = self.get_carryover(char_id, chunk_index)
        rows = self.conn.execute(
            """SELECT emotion, intensity, content FROM memories
               WHERE book_id=? AND character_id=? AND kind='emotion'
               ORDER BY id DESC LIMIT 3""",
            (self.book_id, char_id),
        ).fetchall()
        recent = [
            f"{r['emotion']}({r['intensity']:.1f}): {(r['content'] or '')[:40]}"
            for r in rows
        ]
        return Dossier(
            character=character,
            listener=listener,
            relationship=relationship,
            carryover=carryover,
            recent=recent,
            scene=state.scene,
            mood=state.mood,
        )

    def load_state(self) -> StoryState:
        """DB から StoryState を再構築する（resume の土台）。"""
        state = StoryState()
        rows = self.conn.execute(
            "SELECT * FROM characters WHERE book_id=? ORDER BY first_chunk, id",
            (self.book_id,),
        ).fetchall()
        for row in rows:
            voice = None
            if row["voice_json"]:
                voice = VoiceProfile.model_validate_json(row["voice_json"])
            voice_internal = None
            if row["voice_internal_json"]:
                voice_internal = VoiceProfile.model_validate_json(row["voice_internal_json"])
            state.characters[row["id"]] = Character(
                id=row["id"], name=row["name"], gender=row["gender"] or "unknown",
                age=row["age"] or "adult", role=row["role"] or "",
                traits=json.loads(row["traits"] or "[]"),
                personality=json.loads(row["personality"] or "[]"),
                speech_style=row["speech_style"] or "",
                emotional_baseline=row["baseline"] or "neutral",
                emotional_range=(row["erange"] if row["erange"] is not None else 0.5),
                voice=voice,
                voice_internal=voice_internal,
                last_emotion=row["last_emotion"],
                last_intensity=row["last_intensity"],
                last_chunk=row["last_chunk"],
            )
        rels = self.conn.execute(
            "SELECT src_id, dst_id, type, label FROM relationships WHERE book_id=?",
            (self.book_id,),
        ).fetchall()
        for rel in rels:
            if rel["src_id"] in state.characters:
                state.characters[rel["src_id"]].relationships[rel["dst_id"]] = Relationship(
                    type=rel["type"] or "other", label=rel["label"] or "")
        scene = self.conn.execute(
            """SELECT description, time_of_day, mood FROM scenes
               WHERE book_id=? ORDER BY rowid DESC LIMIT 1""",
            (self.book_id,),
        ).fetchone()
        if scene:
            state.scene = scene["description"] or ""
            state.time_of_day = scene["time_of_day"] or ""
            state.mood = scene["mood"] or ""
        return state

    # -------------------------------------------------------------- carryover

    def get_carryover(self, char_id: str, chunk_index: int,
                      window: int = 2, decay: float = 0.55) -> tuple[str, float] | None:
        """直近の強い感情を減衰させて引き継ぐ。

        「前の章で怒っていた → 次のチャンクも少し険しい」の正体。
        neutral / 弱すぎる感情 / window 超過は引き継がない。
        """
        row = self.conn.execute(
            """SELECT last_emotion, last_intensity, last_chunk FROM characters
               WHERE book_id=? AND id=?""",
            (self.book_id, char_id),
        ).fetchone()
        if not row or not row["last_emotion"] or row["last_emotion"] == "neutral":
            return None
        intensity = row["last_intensity"] or 0.0
        gap = chunk_index - (row["last_chunk"] or 0)
        if gap < 0 or gap > window or intensity < 0.4:
            return None
        return row["last_emotion"], round(intensity * (decay ** gap), 3)

    # -------------------------------------------------------------- scenes / chunks

    def add_scene(self, chapter: int, chunk_index: int, description: str,
                  time_of_day: str, mood: str) -> None:
        if not (description or time_of_day or mood):
            return
        self.conn.execute(
            """INSERT INTO scenes(book_id, chapter, chunk_index,
                                  description, time_of_day, mood)
               VALUES(?,?,?,?,?,?)""",
            (self.book_id, chapter, chunk_index, description, time_of_day, mood),
        )
        self.conn.commit()

    def mark_chunk_analyzed(self, chunk_index: int, chapter: int) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO chunk_analysis(book_id, chunk_index, chapter) VALUES(?,?,?)",
            (self.book_id, chunk_index, chapter),
        )
        self.conn.commit()

    def analyzed_chunks(self) -> set[int]:
        rows = self.conn.execute(
            "SELECT chunk_index FROM chunk_analysis WHERE book_id=?",
            (self.book_id,),
        ).fetchall()
        return {int(r["chunk_index"]) for r in rows}

    # -------------------------------------------------------------- memories + FTS5

    def add_memory(self, chunk_index: int, character_id: str | None, kind: str,
                   emotion: str, intensity: float, content: str) -> None:
        self.conn.execute(
            """INSERT INTO memories(book_id, chunk_index, character_id,
                                    kind, emotion, intensity, content)
               VALUES(?,?,?,?,?,?,?)""",
            (self.book_id, chunk_index, character_id, kind, emotion, intensity, content),
        )
        self.conn.execute(
            """INSERT INTO memories_fts(content, book_id, chunk_index,
                                        character_id, kind)
               VALUES(?,?,?,?,?)""",
            (_spaced(content), self.book_id, chunk_index, character_id or "", kind),
        )
        self.conn.commit()

    def search(self, query: str, limit: int = 10,
               with_book: bool = False) -> list[sqlite3.Row]:
        """FTS5 全文検索（memories_fts に対して）。日本語はフレーズ検索に変換。

        with_book=True なら書籍を横断して検索し、結果に book_id を含める
        （CLI の --search デモ用）。デフォルトは自書籍のみ。
        """
        cols = "book_id, " if with_book else ""
        filt = "" if with_book else "AND book_id=?"
        params: list[object] = [_fts_query(query)]
        if not with_book:
            params.append(self.book_id)
        params.append(limit)
        return self.conn.execute(
            f"""SELECT {cols}chunk_index, character_id, kind,
                       snippet(memories_fts, 0, '<<', '>>', '…', 8) AS hit
                FROM memories_fts
                WHERE memories_fts MATCH ? {filt}
                ORDER BY rank LIMIT ?""",
            params,
        ).fetchall()

    def close(self) -> None:
        self.conn.close()

    # -------------------------------------------------------------- segments

    def count_segments(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM segments WHERE book_id=?",
            (self.book_id,),
        ).fetchone()
        return int(row["n"])

    def save_segment(self, seg: DirectedSegment) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO segments(book_id, id, chapter, chunk_index,
                    type, speaker, text, emotion, intensity, performance, audio_path)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (self.book_id, seg.id, seg.chapter, seg.chunk_index, seg.type,
             seg.speaker, seg.text, seg.emotion, seg.intensity,
             seg.performance.model_dump_json() if seg.performance else None,
             None),
        )
        self.conn.commit()

    def load_segments(self) -> list[DirectedSegment]:
        rows = self.conn.execute(
            "SELECT * FROM segments WHERE book_id=? ORDER BY id",
            (self.book_id,),
        ).fetchall()
        out: list[DirectedSegment] = []
        for row in rows:
            out.append(DirectedSegment(
                id=row["id"], type=row["type"], speaker=row["speaker"],
                text=row["text"], emotion=row["emotion"],
                intensity=row["intensity"], chapter=row["chapter"],
                chunk_index=row["chunk_index"],
                performance=json.loads(row["performance"]) if row["performance"] else None,
            ))
        return out

    def set_audio(self, segment_id: str, path: str) -> None:
        self.conn.execute(
            "UPDATE segments SET audio_path=? WHERE book_id=? AND id=?",
            (path, self.book_id, segment_id),
        )
        self.conn.commit()

    def audio_done(self) -> set[str]:
        rows = self.conn.execute(
            "SELECT id FROM segments WHERE book_id=? AND audio_path IS NOT NULL",
            (self.book_id,),
        ).fetchall()
        return {r["id"] for r in rows}

    def audio_paths(self) -> list[tuple[str, str]]:
        rows = self.conn.execute(
            """SELECT id, audio_path FROM segments
               WHERE book_id=? AND audio_path IS NOT NULL ORDER BY id""",
            (self.book_id,),
        ).fetchall()
        return [(r["id"], r["audio_path"]) for r in rows]

    def audio_segments(self) -> list[tuple[str, int, str]]:
        """音声済みセグメントを (id, chapter, path) で順番に返す（M4B チャプター用）。"""
        rows = self.conn.execute(
            """SELECT id, chapter, audio_path FROM segments
               WHERE book_id=? AND audio_path IS NOT NULL ORDER BY id""",
            (self.book_id,),
        ).fetchall()
        return [(r["id"], int(r["chapter"]), r["audio_path"]) for r in rows]

    def chapter_titles(self) -> dict[int, str]:
        """章ごとの最初のシーン説明をチャプタータイトルとして返す。"""
        titles: dict[int, str] = {}
        rows = self.conn.execute(
            """SELECT chapter, description FROM scenes
               WHERE book_id=? AND IFNULL(description,'')<>''
               ORDER BY chapter, rowid""",
            (self.book_id,),
        ).fetchall()
        for r in rows:
            titles.setdefault(int(r["chapter"]), str(r["description"]))
        return titles

    def book_title(self) -> str:
        row = self.conn.execute(
            "SELECT title FROM books WHERE id=?", (self.book_id,)).fetchone()
        return str(row["title"]) if row and row["title"] else self.book_id

    # -------------------------------------------------------------- voice_registry

    def register_voice_profile(self, profile: VoiceProfile) -> None:
        """ボイスプロファイルをグローバルレジストリに登録・更新する。"""
        now = _now()
        self.conn.execute(
            """INSERT INTO voice_registry(
                 voice_id, label, gender, age, base_pitch, base_pace, base_energy,
                 tts_voice, sbv2_model_name, sbv2_model_id, sbv2_style,
                 source, tags, description, profile_json, created_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(voice_id) DO UPDATE SET
                 label=excluded.label, gender=excluded.gender, age=excluded.age,
                 base_pitch=excluded.base_pitch, base_pace=excluded.base_pace,
                 base_energy=excluded.base_energy, tts_voice=excluded.tts_voice,
                 sbv2_model_name=excluded.sbv2_model_name, sbv2_model_id=excluded.sbv2_model_id,
                 sbv2_style=excluded.sbv2_style, source=excluded.source,
                 tags=excluded.tags, description=excluded.description,
                 profile_json=excluded.profile_json, updated_at=excluded.updated_at""",
            (profile.voice_id, profile.label, profile.gender, profile.age,
             profile.base_pitch, profile.base_pace, profile.base_energy,
             profile.tts_voice, profile.sbv2_model_name, profile.sbv2_model_id,
             profile.sbv2_style, profile.source,
             json.dumps(profile.tags, ensure_ascii=False),
             profile.description, profile.model_dump_json(),
             now, now),
        )
        self.conn.commit()

    def get_voice_profile(self, voice_id: str) -> VoiceProfile | None:
        """レジストリからボイスプロファイルを取得する。"""
        row = self.conn.execute(
            "SELECT profile_json FROM voice_registry WHERE voice_id=?", (voice_id,)
        ).fetchone()
        return VoiceProfile.model_validate_json(row["profile_json"]) if row else None

    def list_voice_profiles(self, gender: str | None = None,
                            source: str | None = None) -> list[VoiceProfile]:
        """登録済みボイスプロファイルを一覧取得する。"""
        clauses: list[str] = []
        params: list[object] = []
        if gender:
            clauses.append("gender=?")
            params.append(gender)
        if source:
            clauses.append("source=?")
            params.append(source)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"SELECT profile_json FROM voice_registry {where} ORDER BY created_at ASC, voice_id ASC",
            params,
        ).fetchall()
        return [VoiceProfile.model_validate_json(r["profile_json"]) for r in rows]

    def delete_voice_profile(self, voice_id: str) -> bool:
        """ボイスプロファイルを削除する（builtinは削除不可）。"""
        row = self.conn.execute(
            "SELECT source FROM voice_registry WHERE voice_id=?", (voice_id,)
        ).fetchone()
        if not row or row["source"] == "builtin":
            return False
        self.conn.execute("DELETE FROM voice_registry WHERE voice_id=?", (voice_id,))
        self.conn.commit()
        return True

    # -------------------------------------------------------------- series

    def upsert_series(self, series: Series) -> None:
        """シリーズを作成・更新する。"""
        now = _now()
        created = series.created_at or now
        self.conn.execute(
            """INSERT INTO series(id, title, description, castings_json, created_at, updated_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 title=excluded.title, description=excluded.description,
                 castings_json=excluded.castings_json, updated_at=excluded.updated_at""",
            (series.id, series.title, series.description,
             json.dumps(series.castings, ensure_ascii=False),
             created, now),
        )
        self.conn.commit()

    def get_series(self, series_id: str) -> Series | None:
        row = self.conn.execute(
            "SELECT * FROM series WHERE id=?", (series_id,)
        ).fetchone()
        if not row:
            return None
        return Series(
            id=row["id"],
            title=row["title"] or "",
            description=row["description"] or "",
            castings=json.loads(row["castings_json"] or "{}"),
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
        )

    def list_series(self) -> list[Series]:
        rows = self.conn.execute("SELECT * FROM series ORDER BY title ASC").fetchall()
        return [
            Series(
                id=r["id"],
                title=r["title"] or "",
                description=r["description"] or "",
                castings=json.loads(r["castings_json"] or "{}"),
                created_at=r["created_at"] or "",
                updated_at=r["updated_at"] or "",
            )
            for r in rows
        ]

    def set_book_series(self, book_id: str, series_id: str | None) -> None:
        self.conn.execute(
            "UPDATE books SET series_id=? WHERE id=?", (series_id, book_id)
        )
        self.conn.commit()

    def get_book_series_id(self, book_id: str | None = None) -> str | None:
        bid = book_id or self.book_id
        row = self.conn.execute(
            "SELECT series_id FROM books WHERE id=?", (bid,)
        ).fetchone()
        return row["series_id"] if row and row["series_id"] else None

    # -------------------------------------------------------------- character_castings

    def set_character_casting(self, casting: CharacterCasting, book_id: str | None = None) -> None:
        """書籍固有のキャラクター配役を保存する。"""
        bid = book_id or self.book_id
        self.conn.execute(
            """INSERT INTO character_castings(
                 book_id, character_id, character_name, voice_id,
                 voice_internal_id, is_locked, notes)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(book_id, character_id) DO UPDATE SET
                 character_name=excluded.character_name,
                 voice_id=excluded.voice_id,
                 voice_internal_id=excluded.voice_internal_id,
                 is_locked=excluded.is_locked,
                 notes=excluded.notes""",
            (bid, casting.character_id, casting.character_name,
             casting.voice_id, casting.voice_internal_id,
             1 if casting.is_locked else 0, casting.notes),
        )
        self.conn.commit()

    def get_character_castings(self, book_id: str | None = None) -> list[CharacterCasting]:
        bid = book_id or self.book_id
        rows = self.conn.execute(
            "SELECT * FROM character_castings WHERE book_id=? ORDER BY character_id",
            (bid,),
        ).fetchall()
        return [
            CharacterCasting(
                character_id=r["character_id"],
                character_name=r["character_name"] or "",
                voice_id=r["voice_id"],
                voice_internal_id=r["voice_internal_id"],
                is_locked=bool(r["is_locked"]),
                notes=r["notes"] or "",
            )
            for r in rows
        ]

    def get_character_casting(self, character_id: str, book_id: str | None = None) -> CharacterCasting | None:
        bid = book_id or self.book_id
        row = self.conn.execute(
            "SELECT * FROM character_castings WHERE book_id=? AND character_id=?",
            (bid, character_id),
        ).fetchone()
        if not row:
            return None
        return CharacterCasting(
            character_id=row["character_id"],
            character_name=row["character_name"] or "",
            voice_id=row["voice_id"],
            voice_internal_id=row["voice_internal_id"],
            is_locked=bool(row["is_locked"]),
            notes=row["notes"] or "",
        )


