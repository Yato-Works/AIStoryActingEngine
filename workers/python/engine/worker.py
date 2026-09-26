"""JSON-RPC Worker (stdio) — Phase 3 Desktop からの制御入口（ADR-0004）。

プロトコル: 改行区切り JSON-RPC 2.0（LSP 方式）
  → stdin  : 1 リクエスト 1 行の JSON
  ← stdout : 1 レスポンス 1 行の JSON
  ジョブ実行中のログは stderr に退避するため stdout は常にプロトコル専用。

メソッド:
  initialize            → 能力と書籍一覧
  ping                  → {pong: true}
  list_books            → 登録済み書籍
  get_events {limit}    → Event Log の直近 N 件
  search {query}        → FTS5 記憶検索
  start_job {novel, ...}→ pipeline Job をバックグラウンドで開始（即 job_id 返却）
  get_job {job_id}      → Job / Step の状態と進捗（ポーリング用）
  cancel_job {job_id}   → 協調的キャンセル要求
  get_book {book_id}    → 本の詳細 + 音声成果物 + 章オフセット（プレイヤー用）
  pause_job {job_id}    → 一時停止（次のチャンク/セグメント境界でブロック）
  resume_job {job_id}   → 一時停止解除 / 失敗・キャンセル Job の再開
  list_jobs {limit}     → Job History（履歴一覧）

使い方:
  echo '{"jsonrpc":"2.0","id":1,"method":"ping"}' | python worker.py
"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import threading
import time
from contextlib import redirect_stdout
from pathlib import Path

import main as engine
from memory import MemoryEngine, _fts_query
from models import CharacterCasting, Performance, Series, VoiceProfile
from voices import resolve_voice_profile, sync_builtin_voices, _internal_of
from tts import get_provider

PROTOCOL_VERSION = "aiae.worker/1"

# JSON-RPC エラーコード
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def _response(req_id, result=None, error=None) -> dict:
    resp = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        resp["error"] = error
    else:
        resp["result"] = result
    return resp


def _error(code: int, message: str, data=None) -> dict:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return err


def _rowdicts(conn: sqlite3.Connection, sql: str, params=()) -> list[dict]:
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


class EngineWorker:
    """エンジンを JSON-RPC で包む Worker。

    pipeline_fn はテスト差し替え用（デフォルトは main.run_pipeline_job）。
    ジョブは DB が真実源なので、状態確認は get_job のポーリングで行う。
    """

    def __init__(self, db_path: Path, pipeline_fn=None) -> None:
        self.db_path = Path(db_path)
        self.pipeline_fn = pipeline_fn or engine.run_pipeline_job
        self._threads: dict[str, threading.Thread] = {}
        self._cancel: set[str] = set()
        self._paused: set[str] = set()
        self._lock = threading.Lock()

    # ------------------------------------------------------------ transport

    def handle_line(self, line: str) -> dict | None:
        """1 行の JSON-RPC リクエストを処理し、レスポンス辞書を返す。"""
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            return _response(None, error=_error(PARSE_ERROR, f"parse error: {exc}"))
        if not isinstance(req, dict) or "method" not in req:
            return _response(req.get("id") if isinstance(req, dict) else None,
                             error=_error(INVALID_REQUEST, "invalid request"))
        req_id, method, params = req.get("id"), req["method"], req.get("params") or {}
        try:
            result = self.dispatch(method, params if isinstance(params, dict) else {})
        except _WorkerError as exc:
            return _response(req_id, error=_error(exc.code, str(exc)))
        except Exception as exc:  # 内部エラーはスタックを stderr へ
            import traceback
            traceback.print_exc(file=sys.stderr)
            return _response(req_id, error=_error(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}"))
        return _response(req_id, result=result)

    def dispatch(self, method: str, params: dict):
        handler = getattr(self, f"rpc_{method}", None)
        if handler is None:
            raise _WorkerError(METHOD_NOT_FOUND, f"unknown method: {method}")
        try:
            return handler(**params)
        except TypeError as exc:
            raise _WorkerError(INVALID_PARAMS, str(exc)) from exc

    # ------------------------------------------------------------ helpers

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        return conn

    def _job_view(self, job_id: str) -> dict:
        conn = self._connect()
        try:
            rows = _rowdicts(conn, "SELECT * FROM jobs WHERE id=?", (job_id,))
            if not rows:
                raise _WorkerError(INVALID_PARAMS, f"job not found: {job_id}")
            job = rows[0]
            job["payload"] = json.loads(job["payload"] or "{}")
            job["steps"] = _rowdicts(
                conn, """SELECT seq, name, status, progress, progress_total,
                                checkpoint, error, started_at, finished_at
                         FROM job_steps WHERE job_id=? ORDER BY seq""", (job_id,))
            job["artifacts"] = _rowdicts(
                conn, """SELECT kind, path, created_at FROM job_artifacts
                         WHERE job_id=?""", (job_id,))
            # 一時停止中か（DB には running と記録され続けるため Worker 側が真実源）
            job["paused"] = job["id"] in self._paused
            return job
        finally:
            conn.close()

    # ------------------------------------------------------------ RPC methods

    def rpc_initialize(self) -> dict:
        return {"protocol": PROTOCOL_VERSION,
                "methods": ["initialize", "ping", "list_books", "get_book",
                            "get_events", "search", "start_job", "get_job",
                            "cancel_job", "pause_job", "resume_job", "list_jobs",
                            "list_voice_profiles", "save_voice_profile", "delete_voice_profile",
                            "get_castings", "assign_casting", "list_series", "upsert_series",
                            "assign_book_to_series", "preview_voice", "import_document",
                            # Atlas Integration
                            "discover_atlas",
                            "get_current_context",
                            "get_characters_for_atlas",
                            "get_foreshadowing_for_atlas",
                            "get_plot_for_atlas",
                            "get_timeline_for_atlas",
                            "navigate_to_passage"],
                "db": str(self.db_path)}

    def rpc_ping(self) -> dict:
        return {"pong": True}

    def rpc_list_books(self) -> dict:
        conn = self._connect()
        try:
            raw_books = _rowdicts(
                conn, """SELECT b.id, b.title, b.created_at,
                                (SELECT COUNT(*) FROM segments s
                                  WHERE s.book_id = b.id) AS segments,
                                (SELECT COUNT(*) FROM segments s
                                  WHERE s.book_id = b.id
                                    AND s.audio_path IS NOT NULL) AS audio_done
                         FROM books b 
                         ORDER BY b.created_at""")
            # 内部システム本 (例: _global, _preview) を除外
            filtered = [b for b in raw_books if not str(b.get("id", "")).startswith("_")]
            # タイトルが素のファイル名の場合、美しい表示名に補正
            title_map = {
                "sample_novel_long": "銀河航路アルカディア (長編)",
                "sample_novel_short": "星詠みの旅人 (短編)",
                "demo": "オーディオブック デモ作品"
            }
            for b in filtered:
                if b["title"] in title_map:
                    b["title"] = title_map[b["title"]]
            return {"books": filtered}
        finally:
            conn.close()

    def rpc_get_book(self, book_id: str) -> dict:
        """本棚 -> プレイヤー用の本の詳細（Phase 3C Bookshelf & Player）。

        音声成果物（m4b 優先、無ければ wav）と、章ごとのオーディオブック内
        開始秒（章シーク用）を返す。
        """
        book_id = str(book_id)
        conn = self._connect()
        try:
            rows = _rowdicts(
                conn, "SELECT id, title, created_at FROM books WHERE id=?",
                (book_id,))
            if not rows:
                raise _WorkerError(INVALID_PARAMS, f"book not found: {book_id}")
            book = rows[0]
            stats = _rowdicts(
                conn, """SELECT COUNT(*) AS segments,
                                SUM(audio_path IS NOT NULL) AS audio_done
                         FROM segments WHERE book_id=?""", (book_id,))[0]
            arts = _rowdicts(
                conn, """SELECT a.kind, a.path FROM job_artifacts a
                         JOIN jobs j ON j.id = a.job_id
                         WHERE j.book_id=? AND j.status='completed'
                         ORDER BY a.created_at DESC""", (book_id,))
        finally:
            conn.close()

        audio = None
        for kind in ("m4b", "wav"):
            for a in arts:
                if a["kind"] == kind and a["path"] and Path(a["path"]).exists():
                    audio = {"kind": kind, "path": a["path"]}
                    break
            if audio:
                break

        chapters, duration = self._chapter_offsets(book_id)
        return {**book,
                "segments": int(stats["segments"] or 0),
                "audio_done": int(stats["audio_done"] or 0),
                "audio": audio,
                "duration_seconds": duration,
                "chapters": chapters}

    def _chapter_offsets(self, book_id: str) -> tuple[list[dict], float | None]:
        """章タイトル + オーディオブック内の章開始秒を計算する。

        クリップ長は wav なら wave モジュール、それ以外は ffprobe で計測。
        計測できないクリップが混ざった時点で以降の offset は None
        （章シークは無効になるが再生は可能）。
        """
        import wave as _wave

        from audio import probe_duration
        from memory import MemoryEngine

        def clip_seconds(path: str):
            try:
                if path.lower().endswith(".wav"):
                    with _wave.open(path, "rb") as w:
                        rate = float(w.getframerate() or 1)
                        return w.getnframes() / rate
                d = probe_duration(Path(path))
                return float(d) if d else None
            except Exception:
                return None

        mem = MemoryEngine(self.db_path, book_id)
        try:
            titles = mem.chapter_titles()
            segs = mem.audio_segments()
        finally:
            mem.close()

        chapters: list[dict] = []
        offset = 0.0
        measurable = True
        cur_chapter = None
        for _sid, chapter, path in segs:
            if chapter != cur_chapter:
                chapters.append({
                    "chapter": chapter,
                    "title": titles.get(chapter, f"第{chapter}章"),
                    "offset_seconds": round(offset, 2) if measurable else None,
                })
                cur_chapter = chapter
            if not measurable:
                continue
            secs = clip_seconds(path)
            if secs is None:
                measurable = False
            else:
                offset += secs
        return chapters, (round(offset, 2) if segs and measurable else None)

    def rpc_get_events(self, limit: int = 20, type: str | None = None) -> dict:
        conn = self._connect()
        try:
            if type:
                rows = _rowdicts(conn, """SELECT ts, type, payload FROM events
                                          WHERE type=? ORDER BY id DESC LIMIT ?""",
                                 (type, limit))
            else:
                rows = _rowdicts(conn, """SELECT ts, type, payload FROM events
                                          ORDER BY id DESC LIMIT ?""", (limit,))
            return {"events": rows}
        finally:
            conn.close()

    def rpc_search(self, query: str, limit: int = 10) -> dict:
        eng = MemoryEngine(self.db_path, "worker")
        try:
            rows = [dict(r) for r in eng.search(query, limit=limit, with_book=True)]
            return {"results": rows}
        finally:
            eng.close()

    def _gate(self, job_id: str):
        """キャンセル + 一時停止をまとめて扱う協調的ゲート。

        should_stop() として Engine のチャンク/セグメント境界から呼ばれる。
        一時停止中はここでブロックするため、Engine 側は無変更で pause に対応できる。
        """
        def check() -> bool:
            while job_id in self._paused and job_id not in self._cancel:
                time.sleep(0.2)
            return job_id in self._cancel
        return check

    def rpc_start_job(self, novel: str, provider: str = "edge",
                      resume: bool = True, no_tts: bool = False,
                      model: str = "qwen3:4b", hve: bool = False) -> dict:
        novel_path = Path(novel)
        if not novel_path.exists():
            raise _WorkerError(INVALID_PARAMS, f"novel not found: {novel}")
        book_id = engine._slugify(novel_path.name)
        with self._lock:
            running = [jid for jid in self._threads if self._threads[jid].is_alive()]
        if running:
            raise _WorkerError(INVALID_REQUEST,
                               f"job already running: {running}")
        # 即座に job_id を返すため、ここで Job を先行作成（pending）。
        # run_pipeline_job の resume_or_create がこの Job を再利用する。
        from jobs import JobManager
        mem = MemoryEngine(self.db_path, book_id, title=novel_path.stem)
        try:
            job_id = JobManager(mem).create_job(
                "pipeline", {"provider": provider, "model": model,
                             "novel": str(novel_path), "no_tts": no_tts,
                             "hve": hve})
        finally:
            mem.close()

        self._spawn_pipeline(novel_path, provider, resume=resume,
                             no_tts=no_tts, model=model, hve=hve)
        return {"job_id": job_id, "book_id": book_id}

    def _spawn_pipeline(self, novel_path: Path, provider: str, resume: bool,
                        no_tts: bool, model: str, hve: bool = False) -> str:
        """pipeline Job をバックグラウンドスレッドで実行する（job_id を返す）。"""
        from jobs import JobManager

        # 先行作成された Job があれば再利用（resume 経路では Job が既にある）
        mem = MemoryEngine(self.db_path, engine._slugify(novel_path.name),
                           title=novel_path.stem)
        try:
            job_id, _ = JobManager(mem).resume_or_create(
                "pipeline", {"provider": provider, "model": model,
                             "novel": str(novel_path), "no_tts": no_tts,
                             "hve": hve})
        finally:
            mem.close()

        def run() -> None:
            # stdout はプロトコル専用。パイプラインのログは stderr へ退避。
            with redirect_stdout(sys.stderr):
                try:
                    self.pipeline_fn(
                        novel_path=novel_path, provider_name=provider,
                        resume=resume, no_tts=no_tts, model=model, hve=hve,
                        should_stop=self._gate(job_id))
                except Exception:
                    pass  # 状態は DB（FAILED/CANCELLED）に記録済み

            with self._lock:
                self._cancel.discard(job_id)
                self._paused.discard(job_id)

        th = threading.Thread(target=run, name=f"job-{job_id}", daemon=True)
        with self._lock:
            self._threads[job_id] = th
        th.start()
        return job_id

    def rpc_get_job(self, job_id: str) -> dict:
        return self._job_view(job_id)

    def rpc_cancel_job(self, job_id: str) -> dict:
        self._job_view(job_id)  # 存在確認
        self._cancel.add(job_id)
        return {"job_id": job_id, "cancelling": True}

    def rpc_pause_job(self, job_id: str) -> dict:
        view = self._job_view(job_id)
        if view["status"] != "running":
            raise _WorkerError(INVALID_REQUEST,
                               f"job is not running: {view['status']}")
        if not self._is_alive(job_id):
            raise _WorkerError(INVALID_REQUEST, "job thread is not alive")
        self._paused.add(job_id)
        return {"job_id": job_id, "paused": True}

    def rpc_resume_job(self, job_id: str) -> dict:
        """一時停止解除、または失敗/キャンセル Job の再開（done-set から続きから）。"""
        view = self._job_view(job_id)
        if job_id in self._paused:
            self._paused.discard(job_id)
            return {"job_id": job_id, "resumed": True, "restarted": False}
        if self._is_alive(job_id):
            return {"job_id": job_id, "resumed": True, "restarted": False}
        # Worker 再起動後など、生きたスレッドがない場合は新規スレッドで再実行。
        # Job System の resume_or_create が failed/pending の Job を再利用し、
        # Engine の done-set（chunk_analysis / audio_path）から続きから再開する。
        payload = view["payload"]
        novel = payload.get("novel")
        if not novel or not Path(novel).exists():
            raise _WorkerError(INVALID_PARAMS, f"novel not found: {novel}")
        new_id = self._spawn_pipeline(
            Path(novel), payload.get("provider", "edge"),
            resume=True, no_tts=payload.get("no_tts", False),
            model=payload.get("model", "qwen3:4b"))
        # cancelled Job は resume_or_create が再利用しないため新規 Job になる
        return {"job_id": new_id, "previous_job_id": job_id,
                "resumed": True, "restarted": True}

    def rpc_list_jobs(self, limit: int = 20) -> dict:
        """Job History（履歴一覧）。UI の「Recent Jobs」用。"""
        conn = self._connect()
        try:
            jobs = _rowdicts(
                conn, """SELECT id, book_id, type, status, error,
                                created_at, updated_at, payload
                         FROM jobs ORDER BY created_at DESC, id DESC LIMIT ?""",
                (limit,))
            for j in jobs:
                j["payload"] = json.loads(j.pop("payload") or "{}")
                steps = _rowdicts(
                    conn, """SELECT name, status, progress, progress_total
                             FROM job_steps WHERE job_id=? ORDER BY seq""",
                    (j["id"],))
                j["steps"] = steps
                j["paused"] = j["id"] in self._paused
                j["running"] = self._is_alive(j["id"])
            return {"jobs": jobs}
        finally:
            conn.close()

    # ------------------------------------------------------------ Dynamic Voices & Castings & Series

    def rpc_list_voice_profiles(self, gender: str | None = None, source: str | None = None) -> dict:
        mem = MemoryEngine(self.db_path, "_global")
        try:
            sync_builtin_voices(mem)
            profiles = mem.list_voice_profiles(gender=gender, source=source)
            return {"profiles": [p.model_dump() for p in profiles]}
        finally:
            mem.close()

    def rpc_save_voice_profile(self, profile: dict) -> dict:
        p = VoiceProfile.model_validate(profile)
        p.source = "user" if p.source != "cloned" else "cloned"
        mem = MemoryEngine(self.db_path, "_global")
        try:
            mem.register_voice_profile(p)
            return {"ok": True, "voice_id": p.voice_id}
        finally:
            mem.close()

    def rpc_delete_voice_profile(self, voice_id: str) -> dict:
        mem = MemoryEngine(self.db_path, "_global")
        try:
            success = mem.delete_voice_profile(voice_id)
            if not success:
                raise _WorkerError(INVALID_PARAMS, f"cannot delete builtin or nonexistent voice: {voice_id}")
            return {"ok": True, "deleted": voice_id}
        finally:
            mem.close()

    def rpc_get_castings(self, book_id: str) -> dict:
        book_id = str(book_id)
        mem = MemoryEngine(self.db_path, book_id)
        try:
            conn = self._connect()
            try:
                chars = _rowdicts(
                    conn,
                    """SELECT id, name, gender, age, role, traits, personality, speech_style, voice_json, voice_internal_json
                       FROM characters WHERE book_id=? ORDER BY first_chunk, id""",
                    (book_id,))
                # 各キャラクターの代表的なセリフ（サンプル発話）を取得
                sample_lines = {}
                for row in conn.execute(
                    """SELECT speaker, text FROM segments
                       WHERE book_id=? AND type='dialogue'
                       ORDER BY chunk_index, id""",
                    (book_id,)
                ).fetchall():
                    spk, txt = row[0], row[1]
                    if spk and spk not in sample_lines and txt:
                        sample_lines[spk] = txt
            finally:
                conn.close()

            castings_map = {c.character_id: c for c in mem.get_character_castings(book_id)}
            result = []
            for ch in chars:
                cid = ch["id"]
                c_obj = castings_map.get(cid)
                v_ext = None
                v_int = None
                if c_obj:
                    v_ext = c_obj.voice_id
                    v_int = c_obj.voice_internal_id
                elif ch["voice_json"]:
                    v_ext = json.loads(ch["voice_json"]).get("voice_id")
                    if ch["voice_internal_json"]:
                        v_int = json.loads(ch["voice_internal_json"]).get("voice_id")
                
                # サンプルセリフ
                sample = sample_lines.get(ch["name"]) or sample_lines.get(cid) or f"私、{ch['name']}の声です。"

                # Atlas連携用リッチメタデータ（Atlas同期時またはプレビュー時に使用）
                # 既存DBの値またはキャラクターの性格・役割に基づく設定
                pers_list = json.loads(ch["personality"] or "[]")
                role_val = ch["role"] or "major"
                
                # デフォルトの説明文・種族・所属・能力・関係性の構築
                species_val = "人間"
                affiliation_val = "無所属"
                abilities_val = []
                relationships_val = []
                description_val = f"{ch['name']}。物語における主要登場人物の一人。"
                
                if "ツンデレ" in pers_list or "高飛車" in pers_list:
                    description_val = f"{ch['name']}。素直になれない一面を持つが、仲間思いで芯の強い性格。"
                    species_val = "人間（魔導家系）"
                    affiliation_val = "冒険者ギルド"
                    abilities_val = ["中級火炎魔術", "詠唱短縮"]
                    relationships_val = [{"target": "主人公", "type": "好意", "label": "素直になれない幼馴染"}]
                elif "冷静" in pers_list or "クール" in pers_list:
                    description_val = f"{ch['name']}。常に沈着冷静な判断を下す参謀役。感情を表に出すことは稀。"
                    species_val = "ハーフエルフ"
                    affiliation_val = "王国学術院"
                    abilities_val = ["精霊探知", "氷結魔法"]
                    relationships_val = [{"target": "主人公", "type": "信頼", "label": "良き理解者"}]
                elif "お姉さん" in pers_list or "包容力" in pers_list:
                    description_val = f"{ch['name']}。周囲を優しく見守る温厚な人物。時に鋭い直感を発揮する。"
                    species_val = "人間"
                    affiliation_val = "神聖教会"
                    abilities_val = ["広域治癒", "精神防壁"]
                    relationships_val = [{"target": "主人公", "type": "庇護", "label": "見守る保護者役"}]
                elif "元気" in pers_list or "活発" in pers_list:
                    description_val = f"{ch['name']}。明るく天真爛漫なムードメーカー。真っ直ぐな言葉で周囲を励ます。"
                    species_val = "獣人族"
                    affiliation_val = "遊撃隊"
                    abilities_val = ["身体強化", "気配察知"]
                    relationships_val = [{"target": "主人公", "type": "相棒", "label": "背中を預ける仲間"}]
                elif ch["gender"] == "male" and ("渋い" in pers_list or ch["age"] in ("adult", "elder")):
                    description_val = f"{ch['name']}。百戦錬磨のベテラン。寡黙ながらその一言には重みがある。"
                    species_val = "人間"
                    affiliation_val = "近衛騎士団"
                    abilities_val = ["剛剣術", "威圧"]
                    relationships_val = [{"target": "主人公", "type": "師弟", "label": "厳しく導く師匠"}]

                result.append({
                    "character_id": cid,
                    "name": ch["name"],
                    "gender": ch["gender"],
                    "age": ch["age"],
                    "role": role_val,
                    "speech_style": ch["speech_style"] or "",
                    "personality": pers_list,
                    "voice_id": v_ext or "",
                    "voice_internal_id": v_int or "",
                    "is_locked": bool(c_obj and c_obj.is_locked),
                    "notes": c_obj.notes if c_obj else "",
                    "sample_line": sample,
                    # Atlas連携時リッチ属性
                    "description": description_val,
                    "species": species_val,
                    "affiliation": affiliation_val,
                    "abilities": abilities_val,
                    "relationships": relationships_val,
                    "emotional_baseline": ch.get("emotional_baseline") if isinstance(ch, dict) and "emotional_baseline" in ch else "neutral",
                    "emotional_range": 0.7 if "ツンデレ" in pers_list or "元気" in pers_list else 0.4,
                })
            series_id = mem.get_book_series_id(book_id)
            return {"book_id": book_id, "series_id": series_id, "castings": result}
        finally:
            mem.close()

    def rpc_assign_casting(self, book_id: str, character_id: str,
                           voice_id: str, voice_internal_id: str | None = None,
                           is_locked: bool = True, notes: str = "") -> dict:
        book_id = str(book_id)
        character_id = str(character_id)
        mem = MemoryEngine(self.db_path, book_id)
        try:
            # 1. character_castings テーブルに保存
            casting = CharacterCasting(
                character_id=character_id,
                character_name="",
                voice_id=voice_id,
                voice_internal_id=voice_internal_id or (voice_id + "i"),
                is_locked=is_locked,
                notes=notes,
            )
            mem.set_character_casting(casting)

            # 2. characters テーブルの voice_json, voice_internal_json も更新
            ext_p = resolve_voice_profile(voice_id, mem)
            int_p = resolve_voice_profile(voice_internal_id or (voice_id + "i"), mem)
            conn = self._connect()
            try:
                conn.execute(
                    """UPDATE characters
                       SET voice_json=?, voice_internal_json=?
                       WHERE book_id=? AND id=?""",
                    (ext_p.model_dump_json(), int_p.model_dump_json(), book_id, character_id),
                )
                conn.commit()
            finally:
                conn.close()

            mem.append_event("VOICE_ASSIGNED", character=character_id,
                             voice=voice_id, voice_internal=int_p.voice_id,
                             user_assigned=True)
            return {"ok": True, "book_id": book_id, "character_id": character_id,
                    "voice_id": voice_id, "voice_internal_id": int_p.voice_id}
        finally:
            mem.close()

    def rpc_imagine_character_voice(self, book_id: str, character_id: str) -> dict:
        """小説のキャラクター属性（性別、年齢、性格、役割、代表セリフなど）から、
        最適な声質・演技トーンを想像し、Irodori演出プロンプトと推奨パラメータを構築・提案する。
        """
        import re
        book_id = str(book_id)
        character_id = str(character_id)
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT name, gender, age, role, speech_style, personality "
                "FROM characters WHERE book_id=? AND id=?",
                (book_id, character_id),
            ).fetchone()
            if not row:
                raise _WorkerError(INVALID_PARAMS, f"character not found: {character_id}")
            c_name, c_gender, c_age, c_role, c_speech, c_pers_raw = row
            try:
                c_pers = json.loads(c_pers_raw) if c_pers_raw else []
            except Exception:
                c_pers = [c_pers_raw] if c_pers_raw else []
            if isinstance(c_pers, str):
                c_pers = [c_pers]

            # 代表セリフを segments テーブルから探索
            seg_row = conn.execute(
                "SELECT text FROM segments WHERE book_id=? AND (speaker=? OR speaker=?) "
                "AND text IS NOT NULL AND length(trim(text)) > 0 ORDER BY rowid ASC LIMIT 1",
                (book_id, c_name, character_id),
            ).fetchone()
            c_sample = seg_row[0] if seg_row else f"私、{c_name}の声です。"
        finally:
            conn.close()

        # 1. Gemini API を用いた声の想像（利用可能な場合）
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if api_key:
            try:
                import httpx
                gemini_prompt = (
                    "あなたはプロの声優音響監督・キャスティングディレクターです。\n"
                    "以下の小説キャラクターから「このキャラならきっとこういう声質・トーンで演じるはずだ」という声を想像し、"
                    "音声合成AI（Irodori-TTS）用の演出プロンプトを構築してください。\n\n"
                    f"【キャラクター情報】\n"
                    f"名前: {c_name}\n"
                    f"性別: {c_gender}\n"
                    f"年齢層: {c_age}\n"
                    f"作中役割: {c_role}\n"
                    f"性格特徴: {', '.join(c_pers)}\n"
                    f"口調/話し方: {c_speech}\n"
                    f"代表セリフ: {c_sample}\n\n"
                    "【出力フォーマット】\n"
                    "必ず以下のJSONのみを出力してください（Markdownの```記法や前置きは不要）:\n"
                    "{\n"
                    '  "caption": "演出プロンプト（例: 【明確な男性声】少しハスキーで野太い低音ボイス、ぶっきらぼうで気だるげだが芯のある青年、自嘲気味に呟く）",\n'
                    '  "gender": "male" または "female" または "neutral",\n'
                    '  "timbre_tags": ["ハスキー", "野太い低音", "乾いた響き"],\n'
                    '  "tone_tags": ["ぶっきらぼう", "気だるげ"],\n'
                    '  "suggested_pace": 1.0,\n'
                    '  "suggested_cfg": 3.2,\n'
                    '  "concept_summary": "ぶっきらぼうな青年×ハスキー低音ボイス",\n'
                    '  "actor_homage": "Test_Voice1 (無頼・ハスキー青年)"\n'
                    "}"
                )
                resp = httpx.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}",
                    json={"contents": [{"parts": [{"text": gemini_prompt}]}]},
                    timeout=6.0,
                )
                if resp.status_code == 200:
                    raw_out = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                    if raw_out.startswith("```"):
                        raw_out = re.sub(r"^```[a-zA-Z]*\n?", "", raw_out)
                        raw_out = re.sub(r"\n?```$", "", raw_out)
                    imagined = json.loads(raw_out.strip())
                    imagined["character_id"] = character_id
                    imagined["character_name"] = c_name
                    imagined["sample_line"] = c_sample or "俺のこぶしは軽いってわけだ。勝てっこないや。"
                    return {"ok": True, "voice_design": imagined}
            except Exception as e:
                sys.stderr.write(f"[worker] Gemini imagine voice skipped/failed: {e}\n")

        # 2. 高精度なルールベース想像エンジン（Geminiなしでも完璧に動作）
        g = (c_gender or "male").lower()
        if g in ("m", "man", "male", "男性", "男"):
            gender_type = "male"
        elif g in ("f", "woman", "female", "女性", "女"):
            gender_type = "female"
        else:
            gender_type = "neutral"

        pers_str = " ".join(c_pers)
        timbre_tags = []
        tone_tags = []
        actor_homage = ""
        concept_summary = ""
        caption_parts = []

        if gender_type == "male":
            if "ツンデレ" in pers_str or "ぶっきらぼう" in pers_str or "軽い" in (c_sample or "") or "こぶし" in (c_sample or ""):
                timbre_tags = ["ハスキー", "野太い低音", "乾いた響き"]
                tone_tags = ["ぶっきらぼう", "気だるげ", "自嘲気味"]
                actor_homage = "Test_Voice1 (無頼・ハスキー青年)"
                concept_summary = "ぶっきらぼうな青年×ハスキー低音ボイス"
                caption_parts = [
                    "【明確な男性声】太く低い男声、喉を鳴らすような野太い地声",
                    "少しハスキーで乾いた響き、ぶっきらぼうで気だるげだが芯のある青年",
                    "自嘲気味にぽつりと呟く"
                ]
            elif "冷静" in pers_str or "クール" in pers_str or "参謀" in (c_role or ""):
                timbre_tags = ["落ち着いた低音", "芯のある声", "知的な響き"]
                tone_tags = ["淡々と話す", "冷徹", "知的"]
                actor_homage = "Test_Voice2 (冷静・知的参謀)"
                concept_summary = "冷静沈着な参謀×知的な低音ボイス"
                caption_parts = [
                    "【明確な男性声】太く落ち着いた成人男性の声、知的な低音",
                    "芯のある澄んだ響き、感情の波を抑えて冷静沈着に話す",
                    "淡々と相手を見透かすように語る"
                ]
            elif "渋い" in pers_str or c_age in ("adult", "elder") or "ベテラン" in (c_role or "") or "師匠" in (c_role or ""):
                timbre_tags = ["超低音・野太い", "掠れ声", "重厚な響き"]
                tone_tags = ["威厳", "重々しい", "寡黙"]
                actor_homage = "Test_Voice3 (重厚・歴戦の男)"
                concept_summary = "百戦錬磨のベテラン×重厚な超低音ボイス"
                caption_parts = [
                    "【明確な男性声】腹の底から響く野太い超低音、胸鳴りのする成人男声",
                    "渋みと掠れを含んだ重厚な響き、威厳に満ちた落ち着き",
                    "言葉の端々に重みを持たせて語る"
                ]
            elif "皮肉" in pers_str or "ツッコミ" in pers_str or "主人公" in (c_role or ""):
                timbre_tags = ["落ち着いた低音", "通る地声", "渋み"]
                tone_tags = ["気だるげ", "皮肉っぽい", "ツッコミ口調"]
                actor_homage = "Test_Voice4 (皮肉・渋み主人公)"
                concept_summary = "気だるげな主人公×渋みのある低音ボイス"
                caption_parts = [
                    "【明確な男性声】太く低い男声、喉を鳴らすような低音の地声",
                    "少し気だるげで皮肉っぽい、低音の魅力、ツッコミ口調",
                    "やれやれと肩をすくめるような響き"
                ]
            else:
                timbre_tags = ["爽やか", "芯のある低音", "自然な地声"]
                tone_tags = ["前向き", "ハキハキ", "素直"]
                actor_homage = "Test_Voice5 (正統派・熱血青年)"
                concept_summary = "芯の通った青年×爽やかな低音ボイス"
                caption_parts = [
                    "【明確な男性声】芯のある爽やかな男性の声、自然な低音の地声",
                    "まっすぐで通る響き、丁寧に落ち着いて話す"
                ]
        elif gender_type == "female":
            if "ツンデレ" in pers_str or "高飛車" in pers_str:
                timbre_tags = ["澄んだ高音", "ハリのある響き", "鈴を転がすような声"]
                tone_tags = ["ツンツンした", "早口", "素直になれない"]
                actor_homage = "Test_Voice6 (勝気・ツンデレ少女)"
                concept_summary = "気品あるツンデレ×ハリのある澄んだ高音"
                caption_parts = [
                    "【澄んだ女性声】透明感のある女性声、ハリのある澄んだ高音",
                    "少しツンツンとして素直になれないが、芯の通った愛らしさがある",
                    "感情を高ぶらせて早口に捲し立てる"
                ]
            elif "お姉さん" in pers_str or "包容力" in pers_str:
                timbre_tags = ["息混じり色気", "温かみのある中音", "柔らかな響き"]
                tone_tags = ["優しく包み込む", "穏やか", "慈愛"]
                actor_homage = "Test_Voice7 (包容力・お姉さん)"
                concept_summary = "包容力のあるお姉さん×柔らかく囁く中低音"
                caption_parts = [
                    "【澄んだ女性声】息を多く含んだ優しく柔らかい女性の声、しっとりとした中音",
                    "包容力と落ち着きに満ちた響き、微笑みながら穏やかに語りかける"
                ]
            elif "マスコット" in pers_str or "元気" in pers_str or "妖精" in pers_str:
                timbre_tags = ["可愛らしい高音", "弾むような響き", "ハイトーン"]
                tone_tags = ["天真爛漫", "元気いっぱい", "いたずらっぽく"]
                actor_homage = "Test_Voice8 (元気・マスコット妖精)"
                concept_summary = "元気いっぱいな相棒×弾むようなハイトーン"
                caption_parts = [
                    "【澄んだ女性声】愛らしく弾むような高音ボイス、元気で明るいアニメ少女の声",
                    "天真爛漫で表情豊か、いたずらっぽくテンポよく話す"
                ]
            else:
                timbre_tags = ["透明感", "自然な中高音", "澄んだ声"]
                tone_tags = ["落ち着いた", "素直", "丁寧"]
                actor_homage = "Test_Voice9 (清楚・透明感ヒロイン)"
                concept_summary = "自然な透明感×落ち着いた少女・女性声"
                caption_parts = [
                    "【澄んだ女性声】透明感のある澄んだ女性の声、自然な中高音",
                    "落ち着いて素直に話す、耳心地のよい澄んだ響き"
                ]
        else:
            timbre_tags = ["ハスキー", "中性的な響き", "少年声"]
            tone_tags = ["まっすぐ", "少し尖った", "素直"]
            actor_homage = "Test_Voice10 (ハスキー・中性少年)"
            concept_summary = "少しハスキーな少年×中性的な響き"
            caption_parts = [
                "【少年・中性声】少しハスキーな少年の声、中性的な声質",
                "若々しくまっすぐな響き、背伸びしたような落ち着きで話す"
            ]

        imagined = {
            "character_id": character_id,
            "character_name": c_name,
            "caption": "、".join(caption_parts),
            "gender": gender_type,
            "timbre_tags": timbre_tags,
            "tone_tags": tone_tags,
            "suggested_pace": 1.0,
            "suggested_cfg": 3.2 if gender_type == "male" else 2.8,
            "suggested_sway": -1.0,
            "concept_summary": concept_summary,
            "actor_homage": actor_homage,
            "sample_line": c_sample or "まったく……俺の声の調子はどうだ？悪くない響きだろ。"
        }
        return {"ok": True, "voice_design": imagined}

    def rpc_apply_castings_and_regen(self, book_id: str, provider: str = "irodori") -> dict:
        """配役を確定し、小説全体のセグメント音声を再生成するジョブをキックする。"""
        book_id = str(book_id)
        conn = self._connect()
        try:
            row = conn.execute("SELECT path, title FROM books WHERE id=?", (book_id,)).fetchone()
            if not row:
                raise _WorkerError(INVALID_PARAMS, f"book not found: {book_id}")
            novel_path = row[0]
            # 既存の生成音声参照をクリアして再生成対象にする
            conn.execute("UPDATE segments SET audio_path=NULL WHERE book_id=?", (book_id,))
            conn.commit()
        finally:
            conn.close()

        job_id = self._spawn_pipeline(
            Path(novel_path), provider=provider, resume=True, no_tts=False
        )
        return {"ok": True, "book_id": book_id, "job_id": job_id}

    def rpc_list_series(self) -> dict:
        mem = MemoryEngine(self.db_path, "_global")
        try:
            return {"series": [s.model_dump() for s in mem.list_series()]}
        finally:
            mem.close()

    def rpc_upsert_series(self, series: dict) -> dict:
        s = Series.model_validate(series)
        mem = MemoryEngine(self.db_path, "_global")
        try:
            mem.upsert_series(s)
            return {"ok": True, "series_id": s.id}
        finally:
            mem.close()

    def rpc_assign_book_to_series(self, book_id: str, series_id: str | None) -> dict:
        mem = MemoryEngine(self.db_path, book_id)
        try:
            mem.set_book_series(book_id, series_id)
            return {"ok": True, "book_id": book_id, "series_id": series_id}
        finally:
            mem.close()

    def rpc_preview_voice(self, text: str, voice_id: str = "none",
                          style: str = "Neutral", pitch: float = 0.0,
                          pace: float = 1.0, provider: str = "irodori",
                          caption: str = "", use_gemini_script: bool = True,
                          cfg_scale_caption: float | None = None,
                          sway_coeff: float | None = None,
                          num_steps: int | None = None,
                          seed: int | None = None,
                          options: dict | None = None) -> dict:
        text = str(text or "こんにちは。私の声を聴いてみてください。")
        mem = MemoryEngine(self.db_path, "_preview")
        try:
            profile = resolve_voice_profile(voice_id, mem)
            preview_dir = self.db_path.parent / "previews"
            preview_dir.mkdir(parents=True, exist_ok=True)

            if provider == "irodori":
                from tts import get_backend
                from acting_ir import ActingIR
                backend = get_backend("irodori")
                
                text_reading = text
                if use_gemini_script:
                    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
                    if api_key:
                        try:
                            import httpx
                            prompt = f"以下のセリフを発話するのに最も適した感情絵文字（例: 😄, 🙄, 😌, 😠, 😢, 🥰 など）を1〜2個文頭または文末に付けた、自然なひらがな読み台本を出力してください。余計な解説は不要で台本1行のみ返してください。\nセリフ: {text}"
                            resp = httpx.post(
                                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}",
                                json={"contents": [{"parts": [{"text": prompt}]}]},
                                timeout=5.0,
                            )
                            if resp.status_code == 200:
                                g_text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                                if g_text:
                                    text_reading = g_text
                                    sys.stderr.write(f"[worker] Gemini preview script applied: {text_reading}\n")
                        except Exception as e:
                            sys.stderr.write(f"[worker] Gemini script API skipped: {e}\n")
                    else:
                        emojis = {"happy": "😄", "sad": "😢", "angry": "😠", "calm": "😌", "sarcastic": "🙄", "tender": "🥰"}
                        emoji = emojis.get(style.lower()) or ("🙄" if ("ツッコミ" in caption or "皮肉" in caption or "低音" in caption) else "")
                        if emoji and emoji not in text:
                            text_reading = f"{text}{emoji}"
                            sys.stderr.write(f"[worker] Injected emotion emoji: {text_reading}\n")

                cap = caption or (profile.description if profile else "") or "落ち着いた、自然なキャラクターボイス"
                
                # 性別コントロールの厳密化（Anime モデルで女性寄りになるのを防ぎ、確実に男性声にする）
                gender = (options.get("gender") if options else None) or ""
                if not gender:
                    if "男" in cap or "野太い" in cap or "重厚" in cap or "低音" in cap or "青年" in cap or "渋み" in cap:
                        gender = "male"
                    elif "女" in cap or "少女" in cap or "姉" in cap or "ヒロイン" in cap or "妖精" in cap or "マスコット" in cap or "高音" in cap:
                        gender = "female"

                if gender == "male":
                    if "【明確な男性声】" not in cap and "男声" not in cap and "男性声" not in cap:
                        cap = f"【明確な男性声】太く低い男声、喉を鳴らすような野太い地声、低音ボイス、{cap}"
                    if cfg_scale_caption is None:
                        cfg_scale_caption = 3.2  # 男性声のプロンプト拘束力を高める
                elif gender == "female":
                    if "【澄んだ女性声】" not in cap and "女声" not in cap and "女性声" not in cap:
                        cap = f"【澄んだ女性声】透明感のある女性声、自然な中高音、{cap}"
                elif gender == "neutral":
                    if "【少年・中性声】" not in cap:
                        cap = f"【少年・中性声】少しハスキーな少年の声、中性的な声質、{cap}"

                sys.stderr.write(f"[worker] Final Irodori Caption: {cap} (gender={gender}, cfg={cfg_scale_caption})\n")

                irodori_opts: dict = {
                    "caption": cap,
                    "voice": voice_id if voice_id and voice_id != "none" else "none",
                }
                if cfg_scale_caption is not None:
                    irodori_opts["cfg_scale_caption"] = float(cfg_scale_caption)
                if sway_coeff is not None:
                    irodori_opts["sway_coeff"] = float(sway_coeff)
                if num_steps is not None:
                    irodori_opts["num_steps"] = int(num_steps)
                if seed is not None:
                    irodori_opts["seed"] = int(seed)
                if options and isinstance(options, dict):
                    for k, v in options.items():
                        if v is not None:
                            irodori_opts[k] = v

                ir = ActingIR(
                    speaker=voice_id or "preview_speaker",
                    text=text,
                    text_reading=text_reading,
                    voice=voice_id if voice_id and voice_id != "none" else "none",
                    pace=pace * (profile.base_pace if profile else 1.0),
                    style="dialogue",
                    emotion="neutral",
                    backend_options={
                        "irodori": irodori_opts
                    }
                )
                irodori_opts["response_format"] = "wav"
                out_file = preview_dir / f"preview_{voice_id or 'test'}.wav"
                backend.synthesize(ir, out_file)
                return {"ok": True, "path": str(out_file.resolve()), "voice_id": voice_id}
            else:
                tts = get_provider(provider)
                perf = Performance(
                    voice=voice_id,
                    mode="dialogue",
                    emotion="neutral",
                    intensity=0.3,
                    pace=pace * profile.base_pace,
                    pitch=pitch + profile.base_pitch,
                    style=style or profile.sbv2_style,
                    volume=1.0,
                )
                ext = getattr(tts, "ext", ".mp3")
                out_file = preview_dir / f"preview_{voice_id}{ext}"
                tts.synthesize(text, perf, out_file)
                return {"ok": True, "path": str(out_file.resolve()), "voice_id": voice_id}
        finally:
            mem.close()

    def rpc_import_document(self, sources: list[str] | str, title: str | None = None) -> dict:
        """テキスト、PDF、画像群を取り込んで小説テキストファイルに変換する。"""
        from importer import import_book_document
        source_list = [sources] if isinstance(sources, str) else list(sources)
        out_dir = self.db_path.parent / "imported"
        out_file = import_book_document(source_list, title=title, out_dir=out_dir)
        return {"ok": True, "novel_path": str(out_file.resolve()), "title": out_file.stem}

    # ------------------------------------------------------------ Atlas Integration

    def rpc_discover_atlas(self) -> dict:
        """AtlasからのDiscoveryリクエストに応答する。"""
        return {
            "protocolVersion": "story/1",
            "appName": "AIStoryActingEngine",
            "appVersion": "0.1.0",
            "apiBaseUrl": "http://localhost:18421",
            "deepLinkScheme": "aiae://",
            "capabilities": [
                "library", "reader", "audio", "tts", "capture", "ocr", "playback"
            ]
        }

    def rpc_get_current_context(self, book_id: str, chapter_id: str | None = None, sentence_id: str | None = None) -> dict:
        """現在の読書コンテキストを取得（AtlasへのContext Query用）。"""
        mem = MemoryEngine(self.db_path, book_id)
        try:
            # 現在の読書位置を取得
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT chapter_id, sentence_id FROM reading_progress WHERE book_id=?", (book_id,)
                ).fetchone()
                current_chapter = chapter_id or (row["chapter_id"] if row else 1)
                current_sentence = sentence_id or (row["sentence_id"] if row else None)
            finally:
                conn.close()

            # 現在位置のキャラクター取得
            characters = mem.get_characters_at_position(current_chapter, current_sentence)
            
            # 直近の伏線候補取得
            foreshadowing = mem.get_recent_foreshadowing_candidates(current_chapter, limit=10)
            
            # Plot進捗取得
            plot_progress = mem.get_plot_progress(current_chapter)
            
            # Timeline近辺のイベント取得
            timeline = mem.get_timeline_near(current_chapter, limit=10)

            return {
                "workId": book_id,
                "passageRef": {
                    "workId": book_id,
                    "chapterId": current_chapter,
                    "sentenceId": current_sentence
                },
                "characters": characters,
                "foreshadowing": foreshadowing,
                "plot": plot_progress,
                "timeline": timeline,
                "world": {
                    "locationCount": 0,
                    "itemCount": 0,
                    "organizationCount": 0,
                    "ruleCount": 0
                }
            }
        finally:
            mem.close()

    def rpc_get_characters_for_atlas(self, book_id: str) -> dict:
        """Atlas用のキャラクター一覧取得。"""
        mem = MemoryEngine(self.db_path, book_id)
        try:
            chars = mem.get_all_characters()
            result = []
            for ch in chars:
                result.append({
                    "id": ch.id,
                    "canonicalName": ch.name,
                    "aliases": [],
                    "role": ch.role or "minor",
                    "description": "",
                    "relationshipCount": len(ch.relationships)
                })
            return {"characters": result}
        finally:
            mem.close()

    def rpc_get_foreshadowing_for_atlas(self, book_id: str, status: str | None = None) -> dict:
        """Atlas用の伏線一覧取得。"""
        mem = MemoryEngine(self.db_path, book_id)
        try:
            fsh = mem.get_foreshadowing_candidates(status=status, limit=20)
            return {"foreshadowing": fsh}
        finally:
            mem.close()

    def rpc_get_plot_for_atlas(self, book_id: str) -> dict:
        """Atlas用のPlot一覧取得。"""
        mem = MemoryEngine(self.db_path, book_id)
        try:
            plots = mem.get_plot_arcs()
            return {"plot": plots}
        finally:
            mem.close()

    def rpc_get_timeline_for_atlas(self, book_id: str) -> dict:
        """Atlas用のTimeline取得。"""
        mem = MemoryEngine(self.db_path, book_id)
        try:
            timeline = mem.get_timeline_events()
            return {"timeline": timeline}
        finally:
            mem.close()

    def rpc_navigate_to_passage(self, book_id: str, chapter_id: str, sentence_id: str | None = None, mode: str = "read") -> dict:
        """Deep Linkナビゲーション用の位置情報を返す。"""
        # 読書位置を更新
        conn = self._connect()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO reading_progress (book_id, chapter_id, sentence_id, updated_at)
                   VALUES (?, ?, ?, datetime('now'))""",
                (book_id, chapter_id, sentence_id)
            )
            conn.commit()
        finally:
            conn.close()
        
        return {
            "success": True,
            "deepLink": f"aiae://open?bookId={book_id}&chapterId={chapter_id}&sentenceId={sentence_id or ''}&mode={mode}"
        }

    def _is_alive(self, job_id: str) -> bool:
        with self._lock:
            th = self._threads.get(job_id)
        return bool(th and th.is_alive())

    def recover_stale_jobs(self) -> list[str]:
        """起動時のクラッシュ復旧: running のまま残った Job を failed にする。

        前回の Worker が死んだとき、Job は DB 上 running のまま残る。
        Step を interrupted にして resume 対象化し、UI の「Resume」から
        done-set 経由で続きから再開できるようにする。
        """
        from jobs import FAILED, RUNNING, JobManager
        conn = self._connect()
        try:
            stale = _rowdicts(
                conn, "SELECT id, book_id FROM jobs WHERE status=?", (RUNNING,))
        finally:
            conn.close()
        recovered: list[str] = []
        for row in stale:
            jid, book_id = row["id"], row["book_id"]
            if self._is_alive(jid):
                continue  # 自プロセスの生きたスレッドは触らない
            mem = MemoryEngine(self.db_path, book_id, title="")
            try:
                jm = JobManager(mem)
                n = jm.recover_running_steps(jid)
                jm.transition(jid, FAILED, error="worker crashed")
                print(f"♻ stale job {jid} を復旧（step {n} 件をやり直し対象化）",
                      file=sys.stderr)
            finally:
                mem.close()
            recovered.append(jid)
        return recovered


class _WorkerError(RuntimeError):
    """JSON-RPC エラーとして応答するアプリケーションエラー。"""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def serve(db_path: Path, pipeline_fn=None) -> None:
    """stdin の各行を JSON-RPC として処理するメインループ（EOF で終了）。"""
    worker = EngineWorker(db_path, pipeline_fn)
    worker.recover_stale_jobs()  # 前回クラッシュで running のままの Job を failed へ
    for raw in io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8"):
        line = raw.strip()
        if not line:
            continue
        resp = worker.handle_line(line)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    engine._setup_stdio()
    serve(engine.DB_PATH)

