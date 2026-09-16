"""Reading Script Layer — 読み辞書と全文かな化の決定論的処理。

ADR-0006 に基づく。LLM を使わない部分（辞書・適用・検証）を担う。
LLM 部分（Script Writer）は script_writer.py を参照。

原則: TTS に渡すテキストは原則かなのみ（all-kana）。
原文は ReadingScript セグメントに text として保持され、失われない。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from pathlib import Path

from pydantic import BaseModel, Field

# ============================================================================
# 漢字検出
# ============================================================================

# CJK 統合漢字 + 拡張A（通常の日本語テキストに出る漢字の範囲）
_KANJI_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def kanji_chars(text: str) -> set[str]:
    """テキストに含まれる漢字の集合を返す。"""
    return set(_KANJI_RE.findall(text or ""))


def kanji_residue(text: str) -> list[str]:
    """全文かな化チェック用: 残っている漢字を重複なく返す（sort済み）。"""
    return sorted(kanji_chars(text))


# ============================================================================
# ReadingDictionary — 表記 → 読み のフラット辞書
# ============================================================================

# Easy-Irodori-TTS (config/reading_dictionary.json) と同一形式:
#   {"表記": "読み", ...}
# 形式を相互運用可能に保つため、JSON はこのフラット構造を使う。

_ENTRY_MAX_WORD = 100
_ENTRY_MAX_READING = 200


class ReadingDictionary:
    """表記 → 読み の決定論的辞書。

    適用は最長一致で行い、置換結果を再処理しない
    （Easy-Irodori-TTS の easy_dictionary.apply と同じセマンティクス）。
    """

    def __init__(self, entries: dict[str, str] | None = None) -> None:
        self._entries: dict[str, str] = {}
        self._lock = threading.RLock()
        for word, reading in (entries or {}).items():
            self.update(word, reading)

    # --- エントリ操作 -------------------------------------------------------

    def update(self, word: str, reading: str) -> None:
        """エントリを登録・更新する。空文字や長すぎる入力は拒否する。"""
        word = str(word or "").strip()
        reading = str(reading or "").strip()
        if not word or not reading:
            raise ValueError("表記と読みの両方が必要です")
        if len(word) > _ENTRY_MAX_WORD or len(reading) > _ENTRY_MAX_READING:
            raise ValueError(
                f"表記は{_ENTRY_MAX_WORD}文字、読みは{_ENTRY_MAX_READING}文字までです")
        if "\n" in word or "\n" in reading:
            raise ValueError("改行を含むエントリは登録できません")
        with self._lock:
            self._entries[word] = reading

    def update_many(self, entries: dict[str, str]) -> int:
        """複数エントリを登録し、新規追加された件数を返す。"""
        added = 0
        with self._lock:
            for word, reading in entries.items():
                word = str(word or "").strip()
                reading = str(reading or "").strip()
                if word and reading and word not in self._entries:
                    added += 1
                if word and reading:
                    self.update(word, reading)
        return added

    def get(self, word: str) -> str | None:
        with self._lock:
            return self._entries.get(word.strip())

    def remove(self, word: str) -> bool:
        with self._lock:
            return self._entries.pop(word.strip(), None) is not None

    def entries(self) -> dict[str, str]:
        with self._lock:
            return dict(self._entries)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def __contains__(self, word: str) -> bool:
        return self.get(word) is not None

    # --- 適用 ---------------------------------------------------------------

    def apply(self, text: str) -> str:
        """辞書の全エントリを最長一致で置換する。

        置換結果の文字列をさらに置換することはない
        （「貼付」→「はりつけ」の「はりつけ」は再処理されない）。
        """
        with self._lock:
            entries = dict(self._entries)
        if not entries or not text:
            return text
        pattern = "|".join(
            re.escape(k) for k in sorted(entries, key=len, reverse=True))
        return re.sub(pattern, lambda m: entries[m.group()], text)


    # --- 永続化: JSON（Easy-Irodori-TTS 互換） ------------------------------

    @classmethod
    def load_json(cls, path: str | Path) -> "ReadingDictionary":
        """JSON ファイルから読み込む。ファイルが無ければ空の辞書を返す。

        形式は Easy-Irodori-TTS の reading_dictionary.json と同一
        （BOM 付き UTF-8 も許容）。
        """
        p = Path(path)
        if not p.exists():
            return cls()
        raw = json.loads(p.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict) or any(
                not isinstance(k, str) or not isinstance(v, str)
                for k, v in raw.items()):
            raise ValueError(f"読み辞書の形式が不正です: {p}")
        return cls(raw)

    def save_json(self, path: str | Path) -> None:
        """JSON ファイルへ原子的に保存する（Easy-Irodori-TTS 互換形式）。"""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        with self._lock:
            data = json.dumps(self._entries, ensure_ascii=False, indent=2) + "\n"
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, p)

    # --- 永続化: SQLite ------------------------------------------------------

    @classmethod
    def load_sqlite(cls, db_path: str | Path) -> "ReadingDictionary":
        """SQLite の readings テーブルから読み込む（無ければ作成）。"""
        conn = sqlite3.connect(str(db_path))
        try:
            _ensure_readings_table(conn)
            rows = conn.execute(
                "SELECT surface, reading FROM readings").fetchall()
            return cls({surface: reading for surface, reading in rows})
        finally:
            conn.close()

    def save_sqlite(self, db_path: str | Path) -> None:
        """SQLite の readings テーブルへ全エントリを upsert する。"""
        conn = sqlite3.connect(str(db_path))
        try:
            _ensure_readings_table(conn)
            with self._lock:
                rows = [(w, r) for w, r in self._entries.items()]
            conn.executemany(
                "INSERT INTO readings(surface, reading) VALUES(?, ?) "
                "ON CONFLICT(surface) DO UPDATE SET reading=excluded.reading",
                rows)
            conn.commit()
        finally:
            conn.close()


def _ensure_readings_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS readings ("
        "  surface TEXT PRIMARY KEY,"
        "  reading TEXT NOT NULL)")
    conn.commit()


# ============================================================================
# ReadingScript — 台本（原文 + かな版）の契約
# ============================================================================


class ReadingScriptSegment(BaseModel):
    """1 セグメント分の読み台本。原文とかな版を両方保持する。"""

    id: str
    speaker: str = ""
    text: str                                # 原文（字幕・記憶・検索用）
    text_reading: str = ""                   # 全文かな版（TTS に渡す）


class ReadingScript(BaseModel):
    """チャンク単位の読み台本。ADR-0006 §1 の契約。"""

    version: str = "1"
    chunk_index: int = 0
    segments: list[ReadingScriptSegment] = Field(default_factory=list)

    def uncovered_kanji(self) -> dict[str, list[str]]:
        """かな版に漢字が残っているセグメントを報告する。

        Returns:
            dict: {segment_id: [残っている漢字, ...]}
                  空 dict なら全文かな化が完了している。
        """
        return {
            seg.id: kanji_residue(seg.text_reading)
            for seg in self.segments
            if kanji_residue(seg.text_reading)
        }

    def apply_dictionary(self, dictionary: ReadingDictionary) -> None:
        """全セグメントの text_reading に辞書を適用して正規化する。

        辞書は Script Writer の LLM 出力よりも強い（ADR-0006 §3）。
        """
        for seg in self.segments:
            seg.text_reading = dictionary.apply(seg.text_reading)


def validate_reading_script(doc: dict) -> list[str]:
    """ReadingScript の JSON を検証し、問題のリストを返す（空なら OK）。"""
    errors: list[str] = []
    segments = doc.get("segments")
    if not isinstance(segments, list) or not segments:
        return ["'segments' は空でない配列である必要があります"]
    for seg in segments:
        sid = seg.get("id", "?")
        if not isinstance(seg.get("text"), str) or not seg["text"].strip():
            errors.append(f"{sid}: text が空です")
        if not isinstance(seg.get("text_reading"), str):
            errors.append(f"{sid}: text_reading がありません")
        elif not seg["text_reading"].strip():
            errors.append(f"{sid}: text_reading が空です")
    return errors
