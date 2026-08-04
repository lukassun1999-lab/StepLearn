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
    from db import update_task, mark_task_failed, mark_task_done

    task_id = task["id"]
    update_task(task_id, {"status": "processing"}, db_path)

    try:
        handler = _PIPELINE_HANDLERS.get(task["task_type"])
        if handler is None:
            raise ValueError(f"Unknown task_type: {task['task_type']}")

        output_data = handler(task, db_path)

        mark_task_done(task_id, output_data, db_path=db_path)

        _create_sampling_checks(task_id, output_data, db_path)
        # P1：grade_only → analysis_only 的自动链已移除。
        # grade_only 现在是一次任务跑完分析主链（engine 声明式链）。
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=5)}"
        try:
            mark_task_failed(task_id, error_msg, db_path)
        except Exception:
            pass  # don't let logging failure crash the worker
        # Refund the quota consumed at upload time so the parent can retry for free
        try:
            input_data = task.get("input_data") or {}
            if isinstance(input_data, str):
                input_data = json.loads(input_data)
            if input_data.get("quota_charged"):
                from db import refund_quota
                refund_quota(task["student_id"], db_path)
        except Exception:
            pass


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


ZOMBIE_RESUME_MAX_AGE_H = 24  # zombies younger than this get auto-resumed
ZOMBIE_MAX_RESUME = 2         # give up after this many auto-resumes


def _recover_tasks():
    """Recover interrupted tasks from a previous server session.

    - pending: re-enqueue (never started).
    - processing (zombie — server died mid-task): auto-resume if fresh,
      otherwise mark failed and refund any charged quota so the parent
      can re-upload without paying twice.
    """
    from db import (get_connection, update_task, mark_task_failed,
                    refund_quota, DB_PATH as default_db)
    import sys
    from datetime import datetime

    try:
        conn = get_connection(default_db)
        rows = conn.execute(
            "SELECT id, student_id, status, input_data, created_at "
            "FROM ai_tasks WHERE status IN ('pending', 'processing') ORDER BY id"
        ).fetchall()
        conn.close()
    except Exception:
        return  # DB might not be ready yet — ignore

    resumed = reaped = 0
    for row in rows:
        input_data = {}
        try:
            input_data = json.loads(row["input_data"] or "{}")
        except Exception:
            pass

        if row["status"] == "pending":
            _task_queue.put((row["id"], default_db))
            resumed += 1
            continue

        # Zombie: at startup no worker can legitimately be running it.
        resumed_count = int(input_data.get("_auto_resumed", 0) or 0)
        try:
            created = datetime.fromisoformat(
                str(row["created_at"]).replace(" ", "T")[:19])
            age_h = (datetime.now() - created).total_seconds() / 3600
        except Exception:
            age_h = float("inf")

        if age_h <= ZOMBIE_RESUME_MAX_AGE_H and resumed_count < ZOMBIE_MAX_RESUME:
            input_data["_auto_resumed"] = resumed_count + 1
            try:
                update_task(row["id"], {
                    "status": "pending",
                    "input_data": json.dumps(input_data, ensure_ascii=False),
                }, default_db)
                _task_queue.put((row["id"], default_db))
                resumed += 1
            except Exception:
                pass
        else:
            try:
                mark_task_failed(
                    row["id"],
                    "服务重启导致任务中断，且已超过自动恢复时限。"
                    "请重新上传（本次额度已退还）",
                    default_db)
                if input_data.get("quota_charged"):
                    refund_quota(row["student_id"], default_db)
                reaped += 1
            except Exception:
                pass

    if resumed or reaped:
        print(f"  [worker] 恢复 {resumed} 个中断任务，收尸 {reaped} 个僵尸任务",
              file=sys.stderr)


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
        # Recover stale pending/processing tasks from previous session
        _recover_tasks()
        # Start the scheduler (weekly book / monthly summary / Saturday weekly report)
        from pipeline.scheduler import start_scheduler
        start_scheduler(lambda task_id, dbp: _task_queue.put((task_id, dbp)))


# ═══════════════════════════════════════════════════
# Daily Scheduler — P1 起迁移至 pipeline/scheduler.py
# （周一错题本 / 月度总结 / 周六条件式周报）
# ═══════════════════════════════════════════════════


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
