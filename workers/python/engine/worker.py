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
                "methods": ["initialize", "ping", "list_books", "get_events",
                            "search", "start_job", "get_job", "cancel_job",
                            "pause_job", "resume_job", "list_jobs"],
                "db": str(self.db_path)}

    def rpc_ping(self) -> dict:
        return {"pong": True}

    def rpc_list_books(self) -> dict:
        conn = self._connect()
        try:
            return {"books": _rowdicts(
                conn, "SELECT id, title, created_at FROM books ORDER BY created_at")}
        finally:
            conn.close()

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

