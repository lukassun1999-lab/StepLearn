#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
后台异步 Pipeline 执行器
Python threading + queue.Queue — 无外部依赖。
"""

import json
import os
import queue
import random
import threading
import traceback
import weakref

# ═══════════════════════════════════════════════════
# Task Queue & Worker Threads
# ═══════════════════════════════════════════════════

PIPELINE_WORKERS = int(os.environ.get("PIPELINE_WORKERS", "3"))

_task_queue = queue.Queue()
_worker_threads = []
_worker_lock = threading.Lock()

# Per-student locks: serialize tasks for the same student to prevent DB races
_student_locks = weakref.WeakValueDictionary()
_student_locks_lock = threading.Lock()


def _get_student_lock(student_id):
    if student_id is None:
        return None
    with _student_locks_lock:
        lock = _student_locks.get(student_id)
        if lock is None:
            lock = threading.Lock()
            _student_locks[student_id] = lock
        return lock


def _create_sampling_checks(task_id: int, output_data: dict, db_path: str) -> None:
    """After a task completes, randomly sample generated content for quality review."""
    from db import create_safety_check, get_connection

    if not output_data:
        return

    stage = output_data.get("stage", "")
    mistake_ids = output_data.get("mistake_ids", [])
    student_id = output_data.get("student_id")

    samples = []

    if stage == "grading_done":
        # Sample recent practice records for this student
        conn = get_connection(db_path)
        rows = conn.execute("""
            SELECT pr.id, pr.user_answer, pr.is_correct, pr.feedback,
                   m.question, m.correct_answer
            FROM practice_records pr
            JOIN mistakes m ON m.id = pr.mistake_id
            WHERE m.student_id = ?
            ORDER BY pr.created_at DESC
            LIMIT 10
        """, [student_id]).fetchall()
        conn.close()
        chosen = random.sample(rows, min(2, len(rows))) if rows else []
        for r in chosen:
            snapshot = (
                f"题目：{r['question'][:120]}... | "
                f"学生答案：{r['user_answer'] or '（未识别）'} | "
                f"AI判定：{'对' if r['is_correct'] else '错'} | "
                f"反馈：{(r['feedback'] or '')[:80]}"
            )
            samples.append(("feedback", snapshot))
    elif mistake_ids:
        # Onboarding / Stage A: sample from generated mistakes
        conn = get_connection(db_path)
        placeholders = ",".join("?" for _ in mistake_ids)
        rows = conn.execute(f"""
            SELECT id, question, question_type, knowledge_points, difficulty
            FROM mistakes WHERE id IN ({placeholders})
        """, list(mistake_ids)).fetchall()
        conn.close()
        chosen = random.sample(rows, min(2, len(rows))) if rows else []
        for r in chosen:
            try:
                kps = json.loads(r["knowledge_points"] or "[]")
            except Exception:
                kps = []
            snapshot = (
                f"题目：{r['question'][:120]}... | "
                f"题型：{r['question_type'] or '-'} | "
                f"知识点：{', '.join(kps) if kps else '-'} | "
                f"难度：{r['difficulty']}"
            )
            samples.append(("mistake", snapshot))

    for content_type, snapshot in samples:
        try:
            create_safety_check(task_id, content_type, snapshot, db_path=db_path)
        except Exception:
            pass


def _process_task(task, db_path):
    """Execute a single task under the caller's lock."""
    from db import update_task, mark_task_failed, mark_task_done, create_task

    task_id = task["id"]
    update_task(task_id, {"status": "processing"}, db_path)

    try:
        handler = _PIPELINE_HANDLERS.get(task["task_type"])
        if handler is None:
            raise ValueError(f"Unknown task_type: {task['task_type']}")

        output_data = handler(task, db_path)

        needs_review = int(output_data.get("needs_review", False))
        mark_task_done(task_id, output_data, needs_review=needs_review,
                      db_path=db_path)

        _create_sampling_checks(task_id, output_data, db_path)

        # Auto-chain: grade_only → analysis_only (so exercises + report are generated)
        input_data = task.get("input_data") or {}
        if isinstance(input_data, str):
            try:
                input_data = json.loads(input_data)
            except Exception:
                input_data = {}
        stage = input_data.get("stage", "")
        if task["task_type"] == "weekly" and stage == "grade_only" and output_data.get("mistakes_count", 0) > 0:
            next_task_id = create_task(
                student_id=task["student_id"],
                task_type="weekly",
                input_data={"stage": "analysis_only"},
                db_path=db_path,
            )
            _task_queue.put((next_task_id, db_path))
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=5)}"
        try:
            mark_task_failed(task_id, error_msg, db_path)
        except Exception:
            pass  # don't let logging failure crash the worker


def _worker_loop():
    """Background worker: pull tasks and execute pipeline."""
    from db import get_task

    while True:
        try:
            task_id, db_path = _task_queue.get()
            try:
                task = get_task(task_id, db_path)
                if task is None:
                    continue

                student_id = task.get("student_id")
                student_lock = _get_student_lock(student_id)
                if student_lock:
                    with student_lock:
                        _process_task(task, db_path)
                else:
                    _process_task(task, db_path)
            finally:
                _task_queue.task_done()
        except Exception:
            # Never let an unexpected queue-level error kill the worker thread.
            traceback.print_exc()


def start_worker():
    """Start the background worker threads (idempotent)."""
    global _worker_threads
    with _worker_lock:
        if _worker_threads:
            return
        for i in range(PIPELINE_WORKERS):
            t = threading.Thread(
                target=_worker_loop,
                daemon=True,
                name=f"pipeline-worker-{i}",
            )
            t.start()
            _worker_threads.append(t)


def enqueue_task(task_id: int, db_path: str = None):
    """Enqueue a task for background execution. Non-blocking."""
    from db import DB_PATH as default_path
    _task_queue.put((task_id, db_path or default_path))
    start_worker()


# ═══════════════════════════════════════════════════
# Pipeline Handler Registry
# ═══════════════════════════════════════════════════

_PIPELINE_HANDLERS = {}


def register_handler(task_type: str, handler_func):
    """Register a pipeline handler for a given task_type."""
    _PIPELINE_HANDLERS[task_type] = handler_func


# ── Default / stub handlers (replaced in Phase 1-2) ─

def _stub_onboarding(task, db_path):
    """Stub: onboarding pipeline (Phase 1)."""
    return {
        "needs_review": False,
        "message": "Onboarding pipeline not yet implemented (Phase 1)",
    }


def _stub_weekly(task, db_path):
    """Stub: weekly pipeline (Phase 2)."""
    return {
        "needs_review": False,
        "message": "Weekly pipeline not yet implemented (Phase 2)",
    }


register_handler("onboarding", _stub_onboarding)
register_handler("weekly", _stub_weekly)


# ═══════════════════════════════════════════════════
# Status helpers (called from pipeline code)
# ═══════════════════════════════════════════════════

def emit_progress(task_id: int, current_step: str, progress: int,
                  db_path: str = None):
    """Called from pipeline code to update task progress."""
    from db import update_task_progress, DB_PATH
    update_task_progress(task_id, current_step, progress,
                         db_path or DB_PATH)


# ═══════════════════════════════════════════════════
# Test
# ═══════════════════════════════════════════════════

if __name__ == "__main__":
    import sys, os, time
    sys.path.insert(0, os.path.dirname(__file__))

    from db import init_db, create_student, create_task, get_task

    init_db()
    sid = create_student({"name": "测试学生", "grade": "高二"})
    print(f"Student {sid} created")

    # Create a test task
    tid = create_task(sid, "onboarding", {"test": True})
    print(f"Task {tid} created")

    # Enqueue
    enqueue_task(tid)
    print("Task enqueued, waiting for worker...")
    time.sleep(2)

    # Check result
    task = get_task(tid)
    print(f"Task status: {task['status']}")
    if task["status"] == "done":
        print(f"Output: {task['output_data']}")
    elif task["status"] == "failed":
        print(f"Error: {task['error_message']}")

    print("pipeline_worker.py OK")
