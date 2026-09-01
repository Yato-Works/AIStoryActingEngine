"""Job System（ADR-0003）の単体テスト: 状態遷移・冪等性・resume・成果物。"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from jobs import (CANCELLED, COMPLETED, FAILED, JobManager, JobSystemError,
                  PENDING, RUNNING, SKIPPED)
from memory import MemoryEngine


def make_engine(tmp_path: Path) -> MemoryEngine:
    return MemoryEngine(tmp_path / "test.db", "b1", title="テスト本")


def test_transition_guard(tmp_path: Path) -> None:
    eng = make_engine(tmp_path)
    jm = JobManager(eng)
    job = jm.create_job("pipeline")
    assert jm.get_job(job)["status"] == PENDING

    jm.transition(job, RUNNING)
    jm.transition(job, COMPLETED)
    assert jm.get_job(job)["status"] == COMPLETED

    # 終端からの遷移は拒否
    try:
        jm.transition(job, RUNNING)
        raise AssertionError("終端からの遷移が許された")
    except JobSystemError:
        pass

    # 同一状態への遷移は冪等（例外を出さない）
    jm2 = JobManager(eng)
    jm2.transition(job, COMPLETED)

    # failed → running の復帰は許可
    job2 = jm.create_job("pipeline")
    jm.transition(job2, RUNNING)
    jm.transition(job2, FAILED, error="x")
    jm.transition(job2, RUNNING)
    assert jm.get_job(job2)["status"] == RUNNING

    # cancelled は終端
    jm.transition(job2, CANCELLED)
    try:
        jm.transition(job2, RUNNING)
        raise AssertionError("cancelled からの遷移が許された")
    except JobSystemError:
        pass


def test_run_step_success_and_idempotence(tmp_path: Path) -> None:
    eng = make_engine(tmp_path)
    jm = JobManager(eng)
    job = jm.create_job("pipeline")
    jm.transition(job, RUNNING)
    calls: list[int] = []

    def fn(report) -> tuple[str, str]:
        calls.append(1)
        report(3, {"position": 3})
        return ("wav", "out/audiobook.wav")

    jm.run_step(job, 1, "tts", fn, progress_total=10)
    assert len(calls) == 1
    step = jm._step(job, 1)
    assert step["status"] == COMPLETED
    assert step["progress"] == 3 and step["progress_total"] == 10
    assert "position" in step["checkpoint"]

    # 完了済み Step は再実行されない（冪等）
    jm.run_step(job, 1, "tts", fn, progress_total=10)
    assert len(calls) == 1

    # 成果物が記録されている
    art = eng.conn.execute(
        "SELECT kind, path FROM job_artifacts WHERE job_id=?", (job,)).fetchone()
    assert art["kind"] == "wav" and art["path"] == "out/audiobook.wav"

    # Event Log に流れている（SSOT 原則）
    types = {r["type"] for r in eng.conn.execute(
        "SELECT type FROM events").fetchall()}
    assert {"JOB_CREATED", "JOB_STARTED", "STEP_STARTED", "STEP_COMPLETED"} <= types


def test_run_step_failure(tmp_path: Path) -> None:
    eng = make_engine(tmp_path)
    jm = JobManager(eng)
    job = jm.create_job("pipeline")
    jm.transition(job, RUNNING)

    def bad(report) -> None:
        report(2, {"segment": "seg_002"})
        raise RuntimeError("TTS サーバ死亡")

    try:
        jm.run_step(job, 2, "tts", bad, progress_total=10)
        raise AssertionError("例外が再raiseされていない")
    except RuntimeError as exc:
        assert "TTS サーバ死亡" in str(exc)

    step = jm._step(job, 2)
    assert step["status"] == FAILED
    assert "TTS サーバ死亡" in step["error"]
    assert step["checkpoint"] == '{"segment": "seg_002"}'  # 進捗は保存済み
    assert any(r["type"] == "STEP_FAILED" for r in eng.conn.execute(
        "SELECT type FROM events").fetchall())

    # failed からの再実行は可能 → 成功すれば completed
    jm.run_step(job, 2, "tts", lambda report: None, progress_total=10)
    assert jm._step(job, 2)["status"] == COMPLETED


def test_resume_after_crash(tmp_path: Path) -> None:
    """クラッシュシミュレーション: running のまま死んだ Step を復旧して再開。"""
    eng = make_engine(tmp_path)
    jm = JobManager(eng)
    job = jm.create_job("pipeline")
    jm.transition(job, RUNNING)
    jm.ensure_step(job, 1, "tts", progress_total=5)
    jm.start_step(job, 1)
    jm.set_step_progress(job, 1, 3, {"segment": "seg_003"})
    # --- ここで Worker 死亡（finish_step されない） ---

    # 再起動: 新しい JobManager で復旧 → 再実行
    jm2 = JobManager(eng)
    job_id2, resumed = jm2.resume_or_create("pipeline")
    assert job_id2 == job and resumed
    assert jm2.recover_running_steps(job) == 1
    assert jm._step(job, 1)["status"] == FAILED  # failed になり resume 対象化

    done = {"seg_001", "seg_002", "seg_003"}  # done-set の代役（DBが真実源の想定）
    processed: list[str] = []

    def fn(report) -> None:
        for seg in ("seg_001", "seg_002", "seg_003", "seg_004", "seg_005"):
            if seg in done:  # ← resume の本体: 済み分をスキップ
                continue
            processed.append(seg)
            done.add(seg)
            report(len(done), {"segment": seg})

    jm2.run_step(job, 1, "tts", fn, progress_total=5)
    assert processed == ["seg_004", "seg_005"]  # 続きからだけ実行
    assert jm._step(job, 1)["status"] == COMPLETED
    assert jm._step(job, 1)["checkpoint"] == '{"segment": "seg_005"}'


def test_resume_or_create(tmp_path: Path) -> None:
    eng = make_engine(tmp_path)
    jm = JobManager(eng)
    job = jm.create_job("pipeline")

    # 未完了 Job は再利用される
    job2, resumed = jm.resume_or_create("pipeline")
    assert job2 == job and resumed

    # 完了 Job は新規作成される
    jm.transition(job, COMPLETED)
    job3, resumed = jm.resume_or_create("pipeline")
    assert job3 != job and not resumed


def test_skipped_step(tmp_path: Path) -> None:
    eng = make_engine(tmp_path)
    jm = JobManager(eng)
    job = jm.create_job("pipeline")
    jm.transition(job, RUNNING)
    jm.ensure_step(job, 2, "tts")
    jm.finish_step(job, 2, skip=True)
    assert jm._step(job, 2)["status"] == SKIPPED
    assert any(r["type"] == "STEP_SKIPPED" for r in eng.conn.execute(
        "SELECT type FROM events").fetchall())
    # skipped からの再開は不可
    try:
        jm.start_step(job, 2)
        raise AssertionError("skipped からの再開が許された")
    except JobSystemError:
        pass
