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
                            "assign_book_to_series", "preview_voice", "import_document"],
                "db": str(self.db_path)}

    def rpc_ping(self) -> dict:
        return {"pong": True}

    def rpc_list_books(self) -> dict:
        conn = self._connect()
        try:
            return {"books": _rowdicts(
                conn, """SELECT b.id, b.title, b.created_at,
                                (SELECT COUNT(*) FROM segments s
                                  WHERE s.book_id = b.id) AS segments,
                                (SELECT COUNT(*) FROM segments s
                                  WHERE s.book_id = b.id
                                    AND s.audio_path IS NOT NULL) AS audio_done
                         FROM books b ORDER BY b.created_at""")}
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
                result.append({
                    "character_id": cid,
                    "name": ch["name"],
                    "gender": ch["gender"],
                    "age": ch["age"],
                    "role": ch["role"],
                    "personality": json.loads(ch["personality"] or "[]"),
                    "voice_id": v_ext or "",
                    "voice_internal_id": v_int or "",
                    "is_locked": bool(c_obj and c_obj.is_locked),
                    "notes": c_obj.notes if c_obj else "",
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
            mem.set_character_casting(casting, book_id=book_id)

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

    def rpc_preview_voice(self, text: str, voice_id: str,
                          style: str = "Neutral", pitch: float = 0.0,
                          pace: float = 1.0, provider: str = "edge") -> dict:
        text = str(text or "こんにちは。私の声を聴いてみてください。")
        mem = MemoryEngine(self.db_path, "_preview")
        try:
            profile = resolve_voice_profile(voice_id, mem)
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
            preview_dir = self.db_path.parent / "previews"
            preview_dir.mkdir(parents=True, exist_ok=True)
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


    # ------------------------------------------------------------ recovery

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

