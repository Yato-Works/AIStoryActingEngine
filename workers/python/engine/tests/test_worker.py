"""JSON-RPC Worker（ADR-0004）の単体テスト: リクエスト処理・エラー・ジョブ起動。"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from worker import (EngineWorker, INVALID_PARAMS, METHOD_NOT_FOUND, PARSE_ERROR)


def make_worker(tmp_path: Path) -> EngineWorker:
    db_path = tmp_path / "story.db"
    # 実フローでは MemoryEngine が事前にスキーマを生成する前提
    from memory import MemoryEngine
    seed = MemoryEngine(db_path, "seed", title="seed")
    seed.close()

    # テスト用の pipeline_fn: start_job が先行作成した Job を完了状態にする fake
    def fake_pipeline(novel_path, provider_name="edge", resume=True, no_tts=False,
                      model="qwen3:4b", should_stop=None):
        from jobs import COMPLETED, JobManager
        from memory import MemoryEngine
        mem = MemoryEngine(db_path, engine_slug(novel_path), title="")
        try:
            jm = JobManager(mem)
            job_id, _ = jm.resume_or_create("pipeline")
            jm.transition(job_id, COMPLETED)
        finally:
            mem.close()

    return EngineWorker(db_path, pipeline_fn=fake_pipeline)


def engine_slug(path) -> str:
    import main as engine
    return engine._slugify(Path(path).name)


def test_hello_worlds(tmp_path: Path) -> None:
    w = make_worker(tmp_path)
    resp = w.handle_line(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}))
    assert resp["result"] == {"pong": True}

    init = w.handle_line(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "initialize"}))
    assert init["result"]["protocol"] == "aiae.worker/1"
    assert "start_job" in init["result"]["methods"]


def test_parse_error(tmp_path: Path) -> None:
    w = make_worker(tmp_path)
    resp = w.handle_line("{bad json")
    assert resp["error"]["code"] == PARSE_ERROR


def test_method_not_found(tmp_path: Path) -> None:
    w = make_worker(tmp_path)
    resp = w.handle_line(json.dumps({"jsonrpc": "2.0", "id": 5, "method": "nope"}))
    assert resp["error"]["code"] == METHOD_NOT_FOUND


def test_invalid_params(tmp_path: Path) -> None:
    w = make_worker(tmp_path)
    resp = w.handle_line(json.dumps(
        {"jsonrpc": "2.0", "id": 6, "method": "search", "params": {"limit": "x"}}))
    # limit に非数値 → TypeError → INVALID_PARAMS
    assert resp["error"]["code"] == INVALID_PARAMS


def test_list_books_and_search(tmp_path: Path) -> None:
    w = make_worker(tmp_path)
    books = w.handle_line(json.dumps({"jsonrpc": "2.0", "id": 7, "method": "list_books"}))
    assert "books" in books["result"]


def test_start_and_get_job(tmp_path: Path) -> None:
    w = make_worker(tmp_path)
    # start_job は novel パスが無いとエラー
    resp = w.handle_line(json.dumps({"jsonrpc": "2.0", "id": 8, "method": "start_job",
                                     "params": {"novel": "not_exist.txt"}}))
    assert resp["error"]["code"] == INVALID_PARAMS

    # fake_pipeline は novel を使わない想定なので空ファイルを作って通す
    novel = tmp_path / "novel.txt"
    novel.write_text("テスト", encoding="utf-8")
    resp = w.handle_line(json.dumps({"jsonrpc": "2.0", "id": 9, "method": "start_job",
                                     "params": {"novel": str(novel)}}))
    assert "job_id" in resp["result"]
    job_id = resp["result"]["job_id"]

    # fake_pipeline が完了するまで待つ
    deadline = time.time() + 5
    while time.time() < deadline:
        r = w.handle_line(json.dumps({"jsonrpc": "2.0", "id": 10, "method": "get_job",
                                      "params": {"job_id": job_id}}))
        if r["result"]["status"] == "completed":
            break
        time.sleep(0.05)
    assert r["result"]["status"] == "completed"


def test_cancel_job(tmp_path: Path) -> None:
    w = make_worker(tmp_path)
    novel = tmp_path / "novel.txt"
    novel.write_text("テスト", encoding="utf-8")
    resp = w.handle_line(json.dumps({"jsonrpc": "2.0", "id": 11, "method": "start_job",
                                     "params": {"novel": str(novel)}}))
    job_id = resp["result"]["job_id"]
    cancel = w.handle_line(json.dumps({"jsonrpc": "2.0", "id": 12, "method": "cancel_job",
                                       "params": {"job_id": job_id}}))
    assert cancel["result"] == {"job_id": job_id, "cancelling": True}