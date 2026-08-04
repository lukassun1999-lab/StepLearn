#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for pipeline worker concurrency and LLM client thread-safety.
"""

import json
import os
import sys
import threading
import time

import pytest

# Ensure project root is importable
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import pipeline_worker


@pytest.fixture
def reset_handlers():
    """Save/restore pipeline handlers so test mocks don't leak."""
    original = dict(pipeline_worker._PIPELINE_HANDLERS)
    yield
    pipeline_worker._PIPELINE_HANDLERS.clear()
    pipeline_worker._PIPELINE_HANDLERS.update(original)


@pytest.fixture
def fresh_worker_pool(monkeypatch):
    """Reset the worker thread list so start_worker() can spawn a fresh pool."""
    monkeypatch.setattr(pipeline_worker, "_worker_threads", [])


def test_worker_pool_starts_configurable_count(monkeypatch, fresh_worker_pool):
    monkeypatch.setattr(pipeline_worker, "PIPELINE_WORKERS", 2)

    pipeline_worker.start_worker()

    assert len(pipeline_worker._worker_threads) == 2
    names = [t.name for t in pipeline_worker._worker_threads]
    assert "pipeline-worker-0" in names
    assert "pipeline-worker-1" in names


def test_start_worker_is_idempotent(monkeypatch, fresh_worker_pool):
    monkeypatch.setattr(pipeline_worker, "PIPELINE_WORKERS", 2)

    pipeline_worker.start_worker()
    first_threads = list(pipeline_worker._worker_threads)

    pipeline_worker.start_worker()
    second_threads = list(pipeline_worker._worker_threads)

    assert first_threads == second_threads


def test_same_student_tasks_serialize(test_db_path, reset_handlers):
    timeline = []
    lock = threading.Lock()

    def mock_handler(task, db_path):
        sid = task["student_id"]
        with lock:
            timeline.append(("start", sid, time.time()))
        time.sleep(0.3)
        with lock:
            timeline.append(("end", sid, time.time()))
        return {"needs_review": False}

    pipeline_worker.register_handler("test_serialize", mock_handler)

    from db import create_student, create_task

    sid = create_student({"name": "Serialize Student", "grade": "高二"}, db_path=test_db_path)
    tid1 = create_task(sid, "test_serialize", {}, db_path=test_db_path)
    tid2 = create_task(sid, "test_serialize", {}, db_path=test_db_path)

    pipeline_worker.start_worker()
    # Give worker threads a moment to reach queue.get()
    time.sleep(0.1)

    pipeline_worker.enqueue_task(tid1, test_db_path)
    pipeline_worker.enqueue_task(tid2, test_db_path)
    pipeline_worker._task_queue.join()

    assert len(timeline) == 4
    # First task must finish before the second starts.
    assert timeline[1][0] == "end"
    assert timeline[2][0] == "start"
    assert timeline[1][2] <= timeline[2][2]


def test_different_student_tasks_run_in_parallel(test_db_path, reset_handlers):
    timeline = []
    lock = threading.Lock()

    def mock_handler(task, db_path):
        sid = task["student_id"]
        with lock:
            timeline.append(("start", sid, time.time()))
        time.sleep(0.4)
        with lock:
            timeline.append(("end", sid, time.time()))
        return {"needs_review": False}

    pipeline_worker.register_handler("test_parallel", mock_handler)

    from db import create_student, create_task

    sid1 = create_student({"name": "Parallel A", "grade": "高二"}, db_path=test_db_path)
    sid2 = create_student({"name": "Parallel B", "grade": "高二"}, db_path=test_db_path)
    tid1 = create_task(sid1, "test_parallel", {}, db_path=test_db_path)
    tid2 = create_task(sid2, "test_parallel", {}, db_path=test_db_path)

    pipeline_worker.start_worker()
    # Give worker threads a moment to reach queue.get()
    time.sleep(0.1)

    start = time.time()
    pipeline_worker.enqueue_task(tid1, test_db_path)
    pipeline_worker.enqueue_task(tid2, test_db_path)
    pipeline_worker._task_queue.join()
    elapsed = time.time() - start

    # Two 0.4s tasks in parallel should complete well under 0.8s.
    assert elapsed < 0.8
    # Their executions must overlap: latest start < earliest end.
    start_times = [e[2] for e in timeline if e[0] == "start"]
    end_times = [e[2] for e in timeline if e[0] == "end"]
    assert max(start_times) < min(end_times)


def test_get_client_singleton_is_thread_safe(monkeypatch):
    import llm

    monkeypatch.setattr(llm, "_client_cache", {})
    results = []
    lock = threading.Lock()

    def caller():
        client = llm.get_client()
        with lock:
            results.append(client)

    threads = [threading.Thread(target=caller) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 20
    assert len(set(id(c) for c in results)) == 1


def test_get_client_different_models_do_not_interfere(monkeypatch):
    import llm

    monkeypatch.setattr(llm, "_client_cache", {})

    default_client = llm.get_client()
    vision_client = llm.get_client(model="kimi-k2.6")
    default_again = llm.get_client()

    assert default_client is default_again
    assert default_client is not vision_client
    assert default_client.model == llm.DEFAULT_MODEL
    assert vision_client.model == "kimi-k2.6"


def test_cache_writes_are_atomic_and_thread_safe(tmp_path, monkeypatch):
    import llm

    cache_dir = str(tmp_path / "llm_cache")
    monkeypatch.setattr(llm, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(llm, "CACHE_ENABLED", True)

    client = llm.LLMClient()
    key = "shared_key"
    errors = []
    lock = threading.Lock()

    def writer(value):
        try:
            client._cache_set(key, {"value": value})
        except Exception as e:
            with lock:
                errors.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    cache_file = os.path.join(cache_dir, f"{key}.json")
    assert os.path.exists(cache_file)
    with open(cache_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "value" in data
