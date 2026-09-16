"""pipeline Job（analyze → tts → export）の統合テスト。

Step の戻り値は (kind, path) でなければならない。tts Step が合成件数（int）を
返していたため、実機の --job 実行が「成果物の記録」で TypeError になり、
音声は出来ているのに export まで到達しなかった。ここで契約を固定する。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as engine
from jobs import COMPLETED, JobManager, normalize_artifacts


def _novel(tmp_path: Path) -> Path:
    novel = tmp_path / "novel.txt"
    novel.write_text("テスト用の小説。", encoding="utf-8")
    return novel


def _patch(monkeypatch, tmp_path: Path, calls: list[str]) -> None:
    monkeypatch.setattr(engine, "DB_PATH", tmp_path / "story.db")
    monkeypatch.setattr(engine, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(engine, "analyze_book",
                        lambda *a, **k: calls.append("analyze"))
    monkeypatch.setattr(engine, "synthesize_all",
                        lambda *a, **k: (calls.append("tts"), 0)[1])
    monkeypatch.setattr(engine, "export_contracts", lambda *a, **k: 0)
    monkeypatch.setattr(engine, "export_audio",
                        lambda memory: [("wav", "audiobook.wav")])


def test_pipeline_job_records_step_artifacts(tmp_path, monkeypatch):
    calls: list[str] = []
    _patch(monkeypatch, tmp_path, calls)
    memory = engine.run_pipeline_job(_novel(tmp_path), provider_name="edge")
    try:
        assert calls == ["analyze", "tts"]
        job = memory.conn.execute(
            "SELECT id, status FROM jobs ORDER BY rowid DESC LIMIT 1").fetchone()
        assert job["status"] == COMPLETED
        kind_to_path = {
            r["kind"]: r["path"] for r in memory.conn.execute(
                "SELECT kind, path FROM job_artifacts WHERE job_id=?",
                (job["id"],)).fetchall()}
        # tts Step は合成結果をディレクトリ成果物として登録する
        assert "audio_dir" in kind_to_path
        # export Step の成果物（wav / m4b）も記録される
        assert kind_to_path["wav"] == "audiobook.wav"
    finally:
        memory.close()


def test_pipeline_job_no_tts_skips_synthesis(tmp_path, monkeypatch):
    calls: list[str] = []
    _patch(monkeypatch, tmp_path, calls)
    memory = engine.run_pipeline_job(_novel(tmp_path), provider_name="edge",
                                     no_tts=True)
    try:
        assert calls == ["analyze"]  # tts は実行されない
        assert memory.count_events("STEP_SKIPPED") >= 1
    finally:
        memory.close()


def test_completed_step_is_not_rerun(tmp_path):
    """同じ Job の完了済み Step は fn を呼ばない（冪等・ADR-0003）。"""
    memory = engine.MemoryEngine(tmp_path / "story.db", "b1", title="本")
    try:
        jm = JobManager(memory)
        job = jm.create_job("pipeline")
        calls: list[int] = []
        jm.run_step(job, 1, "analyze", lambda report: calls.append(1))
        jm.run_step(job, 1, "analyze", lambda report: calls.append(2))
        assert calls == [1]
    finally:
        memory.close()


def test_pipeline_job_resume_reuses_job_and_skips_done_steps(tmp_path, monkeypatch):
    """失敗 Job は --resume で再利用され、完了済み Step はやり直さない。"""
    calls: list[str] = []
    _patch(monkeypatch, tmp_path, calls)

    def boom(*a, **k):
        calls.append("tts")
        raise RuntimeError("TTS サーバ停止")

    monkeypatch.setattr(engine, "synthesize_all", boom)
    with pytest.raises(RuntimeError):
        engine.run_pipeline_job(_novel(tmp_path), provider_name="edge")
    assert calls == ["analyze", "tts"]

    calls.clear()
    _patch(monkeypatch, tmp_path, calls)  # synthesize_all を成功に戻す
    memory = engine.run_pipeline_job(_novel(tmp_path), provider_name="edge",
                                     resume=True)
    try:
        assert calls == ["tts"]  # analyze は完了済みなので実行されない
        jobs = memory.conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()
        assert jobs["n"] == 1     # Job は作り直さず再利用
    finally:
        memory.close()


def test_normalize_artifacts_accepts_supported_shapes():
    assert normalize_artifacts(None, "tts") == []
    assert normalize_artifacts([], "tts") == []
    assert normalize_artifacts(("wav", "a.wav"), "tts") == [("wav", "a.wav")]
    assert normalize_artifacts([("wav", "a.wav"), ("m4b", "b.m4b")], "tts") == [
        ("wav", "a.wav"), ("m4b", "b.m4b")]


def test_normalize_artifacts_rejects_wrong_shape():
    with pytest.raises(ValueError) as exc:
        normalize_artifacts(3, "tts")
    # どの Step が何を返したかが分かるメッセージである
    assert "step tts" in str(exc.value)
    assert "3" in str(exc.value)


def test_run_step_reports_bad_return_shape(tmp_path):
    memory = engine.MemoryEngine(tmp_path / "story.db", "b1", title="本")
    try:
        jm = JobManager(memory)
        job = jm.create_job("pipeline")
        with pytest.raises(ValueError):
            jm.run_step(job, 1, "tts", lambda report: 7)
        assert jm._step(job, 1)["status"] == "failed"
    finally:
        memory.close()
