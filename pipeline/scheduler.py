#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定时任务调度器（自 pipeline_worker.py 迁出）：

- 每周一 08:00 后：为全体活跃学生生成上周错题本（weekly_mistake_book）
- 每月 1 日 08:00 后：为全体活跃学生生成上月总结（monthly_summary）
- 每周六 08:00 后：条件式自动周报（D3 决策）——仅本周有分析数据
  （paper_analyzed=1）的学生出周报；无数据不出（避免空报）；
  与手动 report_only 共用同一节点，DB 级当日去重防双发。
"""

import sys
import threading
import time
from datetime import datetime

_scheduler_thread = None
_last_scheduler_run = None  # date string to prevent duplicate runs
_enqueue_fn = None          # 由 pipeline_worker.start_worker 注入


def start_scheduler(enqueue_fn):
    """启动调度器线程（幂等）。enqueue_fn(task_id, db_path) 入队回调。"""
    global _scheduler_thread, _enqueue_fn
    _enqueue_fn = enqueue_fn
    if _scheduler_thread is not None:
        return
    _scheduler_thread = threading.Thread(
        target=_scheduler_loop, daemon=True, name="pipeline-scheduler")
    _scheduler_thread.start()


def _trigger_batch_tasks(stage: str, db_path: str):
    """Create summarization tasks for all active students.

    DB-level dedup: skip a student if a non-failed task for the same
    stage already exists today. (The in-memory _last_scheduler_run resets
    on every server restart, which previously caused duplicate
    weekly_book/monthly tasks per restart.)
    """
    import db as dbmod
    try:
        conn = dbmod.get_connection(db_path)
        students = conn.execute(
            "SELECT id FROM students WHERE status = 'active'"
        ).fetchall()
        count = 0
        for s in students:
            sid = s["id"]
            # created_at 为 UTC（CURRENT_TIMESTAMP），用 date('now')（同为 UTC）
            # 做当日去重，避免本地时区与 UTC 混用导致跨午夜重复
            existing = conn.execute(
                "SELECT id FROM ai_tasks WHERE student_id=? AND task_type='weekly' "
                "AND input_data LIKE ? AND date(created_at)=date('now') "
                "AND status NOT IN ('failed','cancelled') LIMIT 1",
                [sid, f"%{stage}%"]
            ).fetchone()
            if existing:
                continue
            task_id = dbmod.create_task(
                student_id=sid, task_type="weekly",
                input_data={"stage": stage},
                db_path=db_path,
            )
            if _enqueue_fn:
                _enqueue_fn(task_id, db_path)
            count += 1
        conn.close()
        if count:
            print(f"  [scheduler] 已为 {count} 个学生创建 {stage} 任务",
                  file=sys.stderr)
    except Exception:
        import traceback
        traceback.print_exc()


def _trigger_weekly_reports(db_path: str):
    """周六条件式自动周报（D3）：本周有分析数据才出，避免空报。"""
    import db as dbmod
    try:
        conn = dbmod.get_connection(db_path)
        students = conn.execute(
            "SELECT id FROM students WHERE status = 'active'"
        ).fetchall()
        week_start = dbmod.get_week_start()
        count = 0
        for s in students:
            sid = s["id"]
            wr = conn.execute(
                "SELECT paper_analyzed FROM weekly_records "
                "WHERE student_id=? AND week_start=? AND kind='weekly'",
                [sid, week_start]).fetchone()
            if not wr or not wr["paper_analyzed"]:
                continue  # 本周无数据 → 不出空报
            # 当日去重（UTC 自洽）：手动补发（report_only）或已自动出过则跳过
            existing = conn.execute(
                "SELECT id FROM ai_tasks WHERE student_id=? AND task_type='weekly' "
                "AND input_data LIKE ? AND date(created_at)=date('now') "
                "AND status NOT IN ('failed','cancelled') LIMIT 1",
                [sid, "%report_only%"]
            ).fetchone()
            if existing:
                continue
            task_id = dbmod.create_task(
                student_id=sid, task_type="weekly",
                input_data={"stage": "report_only", "auto": True},
                db_path=db_path,
            )
            if _enqueue_fn:
                _enqueue_fn(task_id, db_path)
            count += 1
        conn.close()
        if count:
            print(f"  [scheduler] 已为 {count} 个学生创建本周周报任务",
                  file=sys.stderr)
    except Exception:
        import traceback
        traceback.print_exc()


def _scheduler_loop():
    """Background scheduler: hourly check; batch triggers on Monday / 1st / Saturday."""
    global _last_scheduler_run
    while True:
        try:
            import db as dbmod
            default_db = dbmod.DB_PATH
            now = datetime.now()
            today_key = now.strftime("%Y-%m-%d")

            # Only run once per day, after 08:00
            if _last_scheduler_run != today_key and now.hour >= 8:
                _last_scheduler_run = today_key

                # Monday → weekly mistake books for last week
                if now.weekday() == 0:
                    _trigger_batch_tasks("weekly_mistake_book", default_db)

                # 1st of month → monthly summaries for last month
                if now.day == 1:
                    _trigger_batch_tasks("monthly_summary", default_db)

                # Saturday → conditional weekly reports for this week (D3)
                if now.weekday() == 5:
                    _trigger_weekly_reports(default_db)
        except Exception:
            pass

        time.sleep(3600)
