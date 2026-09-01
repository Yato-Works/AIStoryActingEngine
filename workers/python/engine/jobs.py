"""Job System — 再開可能なパイプライン実行基盤（ADR-0003）。

設計原則:
- **Event Log が Single Source of Truth**。Job System は新しいログを作らない。
  Job/Step の状態遷移は既存 events テーブルに JOB_* / STEP_* イベントとして流れる。
- 進捗と checkpoint は DB（jobs / job_steps / job_artifacts）。Worker が死んでも
  「どこまで終わったか」を DB から復元できる（Phase 3 の C++ Runtime が監視可能）。
- Step は冪等。completed の Step は再実行しない。running のまま残った Step は
  「中断」とみなし、recover してから fn が done-set / checkpoint から再開する。

状態遷移:
  pending → running → completed | failed
  failed  → running（resume / retry）
  pending → cancelled | skipped / running → cancelled
  completed / cancelled / skipped は終端

Step の細かい再開は、Engine が既に持つ DB の done-set
（chunk_analysis / segments.audio_path）を真実源とし、job_steps.checkpoint は
「観測用の最新位置」として記録する（二重管理を避ける）。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from memory import MemoryEngine

PENDING = "pending"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"
SKIPPED = "skipped"

VALID_TRANSITIONS: dict[str, set[str]] = {
    PENDING: {RUNNING, CANCELLED, SKIPPED},
    RUNNING: {COMPLETED, FAILED, CANCELLED},
    FAILED: {RUNNING, CANCELLED},
    COMPLETED: set(),
    CANCELLED: set(),
    SKIPPED: set(),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobSystemError(RuntimeError):
    pass


class JobManager:
    """jobs / job_steps / job_artifacts を管理する。

    MemoryEngine と同じ SQLite 接続を共有するため、Step 内のセグメント更新と
    進捗更新が同一接続上で整合する（ジョブ状態とデータ状態がズレない）。
    """

    def __init__(self, engine: MemoryEngine) -> None:
        self.engine = engine
        self.conn = engine.conn

    # ------------------------------------------------------------ lifecycle

    def create_job(self, job_type: str, payload: dict | None = None,
                   job_id: str | None = None) -> str:
        job_id = job_id or f"job_{uuid.uuid4().hex[:12]}"
        self.conn.execute(
            """INSERT INTO jobs(id, book_id, type, status, payload,
                                created_at, updated_at)
               VALUES(?,?,?,?,?,?,?)""",
            (job_id, self.engine.book_id, job_type, PENDING,
             json.dumps(payload or {}, ensure_ascii=False), _now(), _now()),
        )
        self.conn.commit()
        self.engine.append_event("JOB_CREATED", job=job_id, type=job_type)
        return job_id

    def resume_or_create(self, job_type: str,
                         payload: dict | None = None) -> tuple[str, bool]:
        """未完了（pending/running/failed）の同種 Job があれば再利用する。

        戻り値は (job_id, resumed)。failed → running への復帰もここで行う。
        """
        row = self.conn.execute(
            """SELECT id FROM jobs
               WHERE book_id=? AND type=? AND status IN (?,?,?)
               ORDER BY created_at DESC, id DESC LIMIT 1""",
            (self.engine.book_id, job_type, PENDING, RUNNING, FAILED),
        ).fetchone()
        if row:
            job_id = row["id"]
            self.transition(job_id, RUNNING)  # failed → running（running は現状維持）
            return job_id, True
        return self.create_job(job_type, payload), False

    def get_job(self, job_id: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise JobSystemError(f"job not found: {job_id}")
        return row

    def transition(self, job_id: str, to_status: str, error: str | None = None) -> None:
        """状態遷移を検証して適用し、Event Log に記録する。同一状態への遷移は冪等。"""
        cur = self.get_job(job_id)["status"]
        if cur == to_status:
            return
        if to_status not in VALID_TRANSITIONS[cur]:
            raise JobSystemError(f"不正な遷移: {cur} → {to_status} (job={job_id})")
        self.conn.execute(
            "UPDATE jobs SET status=?, error=?, updated_at=? WHERE id=?",
            (to_status, error, _now(), job_id),
        )
        self.conn.commit()
        event = {"completed": "JOB_COMPLETED", "failed": "JOB_FAILED",
                 "cancelled": "JOB_CANCELLED"}.get(to_status, "JOB_STARTED")
        payload: dict = {"job": job_id}
        if error:
            payload["error"] = error
        self.engine.append_event(event, **payload)

    # ------------------------------------------------------------ steps

    def ensure_step(self, job_id: str, seq: int, name: str,
                    progress_total: int = 0) -> None:
        self.conn.execute(
            """INSERT OR IGNORE INTO job_steps(job_id, seq, name, status,
                             progress, progress_total, checkpoint)
               VALUES(?,?,?,?,0,?,NULL)""",
            (job_id, seq, name, PENDING, progress_total),
        )
        self.conn.commit()

    def _step(self, job_id: str, seq: int) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM job_steps WHERE job_id=? AND seq=?",
            (job_id, seq)).fetchone()
        if row is None:
            raise JobSystemError(f"step not found: job={job_id} seq={seq}")
        return row

    def start_step(self, job_id: str, seq: int) -> None:
        """Step を running にする。pending / failed / 中断(running) から再開可能。

        checkpoint は保持する（fn 側が続きから再開するため）。
        """
        row = self._step(job_id, seq)
        status = row["status"]
        if status in (COMPLETED, CANCELLED, SKIPPED):
            raise JobSystemError(f"step {seq} は {status}（再実行不可）")
        self.conn.execute(
            """UPDATE job_steps SET status=?, started_at=?,
                     finished_at=NULL, error=NULL, updated_at=?
               WHERE job_id=? AND seq=?""",
            (RUNNING, _now(), _now(), job_id, seq),
        )
        self.conn.commit()
        self.engine.append_event("STEP_STARTED", job=job_id, step=seq,
                                 name=row["name"], resumed=(status == RUNNING))

    def set_step_progress(self, job_id: str, seq: int, progress: int,
                          checkpoint: dict | None = None) -> None:
        """進捗と最新 checkpoint を記録する（C++ Runtime が監視する値）。"""
        self.conn.execute(
            """UPDATE job_steps SET progress=?,
                     progress_total=MAX(progress_total, ?),
                     checkpoint=?, updated_at=?
               WHERE job_id=? AND seq=?""",
            (progress, progress,
             json.dumps(checkpoint, ensure_ascii=False) if checkpoint else None,
             _now(), job_id, seq),
        )
        self.conn.commit()

    def finish_step(self, job_id: str, seq: int, error: str | None = None,
                    skip: bool = False) -> None:
        status = SKIPPED if skip else (FAILED if error else COMPLETED)
        self.conn.execute(
            """UPDATE job_steps SET status=?, error=?, finished_at=?, updated_at=?
               WHERE job_id=? AND seq=?""",
            (status, error, _now(), _now(), job_id, seq),
        )
        self.conn.commit()
        self.engine.append_event(
            {"failed": "STEP_FAILED", "skipped": "STEP_SKIPPED"}.get(status, "STEP_COMPLETED"),
            job=job_id, step=seq, error=error)

    def recover_running_steps(self, job_id: str) -> int:
        """クラッシュで running のまま残った Step を failed に戻す（resume 対象化）。

        戻り値は復旧した Step 数。
        """
        stale = self.conn.execute(
            "SELECT seq FROM job_steps WHERE job_id=? AND status=?",
            (job_id, RUNNING)).fetchall()
        for row in stale:
            self.finish_step(job_id, row["seq"], error="interrupted")
        return len(stale)

    # ------------------------------------------------------------ runner

    def run_step(self, job_id: str, seq: int, name: str, fn,
                 progress_total: int = 0) -> None:
        """Step を冪等に実行する。

        fn(report) を呼び出す。report(progress, checkpoint) で進捗を記録できる。
        fn の戻り値が (kind, path) またはそのリストなら job_artifacts に記録する。
        completed の Step は fn を呼ばずに即 return（冪等）。
        """
        self.ensure_step(job_id, seq, name, progress_total)
        if self._step(job_id, seq)["status"] == COMPLETED:
            print(f"  ⏭ step {seq}({name}) は完了済み — スキップ")
            return

        def report(progress: int, checkpoint: dict | None = None) -> None:
            self.set_step_progress(job_id, seq, progress, checkpoint)

        self.start_step(job_id, seq)
        try:
            artifact = fn(report)
            self.finish_step(job_id, seq)
            arts = artifact if isinstance(artifact, list) else (
                [artifact] if artifact else [])
            for kind, path in arts:
                self.add_artifact(job_id, seq, kind, path)
        except Exception as exc:
            self.finish_step(job_id, seq, error=str(exc))
            raise

    def add_artifact(self, job_id: str, step_seq: int, kind: str, path: str) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO job_artifacts(job_id, step_seq, kind, path, created_at)
               VALUES(?,?,?,?,?)""",
            (job_id, step_seq, kind, path, _now()),
        )
        self.conn.commit()
