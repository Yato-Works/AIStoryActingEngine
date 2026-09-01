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

from models import Character, DirectedSegment, StoryState, VoiceProfile


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
  PRIMARY KEY(book_id, id));
CREATE TABLE IF NOT EXISTS relationships(
  book_id TEXT, src_id TEXT, dst_id TEXT, label TEXT,
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
CREATE INDEX IF NOT EXISTS idx_segments_speaker ON segments(book_id, speaker);
CREATE INDEX IF NOT EXISTS idx_memories_char ON memories(book_id, character_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MemoryEngine:
    """SQLite で物語状態を管理する Memory Engine。"""

    def __init__(self, db_path: Path, book_id: str, title: str = "") -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
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
                                      last_intensity, last_chunk)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(book_id, id) DO UPDATE SET
                 name=excluded.name, gender=excluded.gender, age=excluded.age,
                 role=excluded.role, traits=excluded.traits""",
            (self.book_id, ch.id, ch.name, ch.gender, ch.age, ch.role,
             json.dumps(ch.traits, ensure_ascii=False),
             ch.voice.model_dump_json() if ch.voice else None,
             chunk_index, ch.last_emotion, ch.last_intensity, ch.last_chunk),
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
        if ch.voice is None:
            return
        self.conn.execute(
            "UPDATE characters SET voice_json=? WHERE book_id=? AND id=?",
            (ch.voice.model_dump_json(), self.book_id, ch.id),
        )
        self.conn.commit()

    def upsert_relationship(self, src_id: str, dst_id: str, label: str) -> None:
        self.conn.execute(
            """INSERT INTO relationships(book_id, src_id, dst_id, label) VALUES(?,?,?,?)
               ON CONFLICT(book_id, src_id, dst_id) DO UPDATE SET label=excluded.label""",
            (self.book_id, src_id, dst_id, label),
        )
        self.conn.commit()

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
            state.characters[row["id"]] = Character(
                id=row["id"], name=row["name"], gender=row["gender"] or "unknown",
                age=row["age"] or "adult", role=row["role"] or "",
                traits=json.loads(row["traits"] or "[]"),
                voice=voice,
                last_emotion=row["last_emotion"],
                last_intensity=row["last_intensity"],
                last_chunk=row["last_chunk"],
            )
        rels = self.conn.execute(
            "SELECT src_id, dst_id, label FROM relationships WHERE book_id=?",
            (self.book_id,),
        ).fetchall()
        for rel in rels:
            if rel["src_id"] in state.characters:
                state.characters[rel["src_id"]].relationships[rel["dst_id"]] = rel["label"]
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

    def search(self, query: str, limit: int = 10) -> list[sqlite3.Row]:
        """FTS5 全文検索（memories_fts に対して）。日本語はフレーズ検索に変換。"""
        return self.conn.execute(
            """SELECT chunk_index, character_id, kind,
                      snippet(memories_fts, 0, '<<', '>>', '…', 8) AS hit
               FROM memories_fts
               WHERE memories_fts MATCH ? AND book_id=?
               ORDER BY rank LIMIT ?""",
            (_fts_query(query), self.book_id, limit),
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


