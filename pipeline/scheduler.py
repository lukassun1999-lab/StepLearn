#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定时任务调度器（自 pipeline_worker.py 迁出）：

- 周错题本（weekly_mistake_book）：窗口去重每周一次；窗口 = 本周一 0 点起，
  周一当天错过（服务宕机）则本周内任意天补跑，不再永久跳过
- 月度总结（monthly_summary）：同上，窗口 = 本月 1 日 0 点起
- 周六及以后：条件式自动周报（D3 决策）——仅本周有分析数据
  （paper_analyzed=1）的学生出周报；无数据不出（避免空报）；
  与手动补发共用同一节点，DB 级窗口去重（本周六起）防双发。
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


def _has_task_since(conn, student_id: int, stage_kw: str, since_utc: str) -> bool:
    """窗口去重：该学生自 since_utc（UTC）起是否已有同 stage 任务。

    created_at 为 UTC（CURRENT_TIMESTAMP），since_utc 由调用方按 UTC 计算。
    """
    row = conn.execute(
        "SELECT id FROM ai_tasks WHERE student_id=? AND task_type='weekly' "
        "AND input_data LIKE ? AND created_at >= ? "
        "AND status NOT IN ('failed','cancelled') LIMIT 1",
        [student_id, f"%{stage_kw}%", since_utc]
    ).fetchone()
    return row is not None


def _week_start_utc(now) -> str:
    """本周一的 UTC 0 点（本地 now 换算 UTC 后回退到周一）。"""
    from datetime import datetime, timedelta, timezone
    utc_now = now.astimezone(timezone.utc) if now.tzinfo else now
    monday = utc_now - timedelta(days=utc_now.weekday())
    return monday.strftime("%Y-%m-%d") + " 00:00:00"


def _month_start_utc(now) -> str:
    from datetime import timezone
    utc_now = now.astimezone(timezone.utc) if now.tzinfo else now
    return utc_now.strftime("%Y-%m") + "-01 00:00:00"


def _saturday_start_utc(now) -> str:
    """最近一个周六的 UTC 0 点（周六/周日触发窗口的起点）。

    从本周一 +5 天推得：周六当天 = 今天；周日 = 昨天。
    """
    from datetime import timedelta, timezone
    utc_now = now.astimezone(timezone.utc) if now.tzinfo else now
    monday = utc_now - timedelta(days=utc_now.weekday())
    saturday = monday + timedelta(days=5)
    return saturday.strftime("%Y-%m-%d") + " 00:00:00"


def _trigger_batch_tasks(stage: str, db_path: str):
    """Create summarization tasks for all active students.

    DB-level window dedup: skip a student if a non-failed task for the same
    stage already exists within the target window (this week's Monday for
    weekly books / this month's 1st for monthly). Server restarts and
    missed days are covered — the task fires on the next loop pass.
    """
    import db as dbmod
    from datetime import datetime
    try:
        conn = dbmod.get_connection(db_path)
        students = conn.execute(
            "SELECT id FROM students WHERE status = 'active'"
        ).fetchall()
        now = datetime.now()
        if stage == "monthly_summary":
            since = _month_start_utc(now)
        else:
            since = _week_start_utc(now)
        count = 0
        for s in students:
            sid = s["id"]
            if _has_task_since(conn, sid, stage, since):
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
    from datetime import datetime
    try:
        conn = dbmod.get_connection(db_path)
        students = conn.execute(
            "SELECT id FROM students WHERE status = 'active'"
        ).fetchall()
        week_start = dbmod.get_week_start()
        since = _saturday_start_utc(datetime.now())
        count = 0
        for s in students:
            sid = s["id"]
            wr = conn.execute(
                "SELECT paper_analyzed FROM weekly_records "
                "WHERE student_id=? AND week_start=? AND kind='weekly'",
                [sid, week_start]).fetchone()
            if not wr or not wr["paper_analyzed"]:
                continue  # 本周无数据 → 不出空报
            # 窗口去重：本周六以来已出过（手动补发或自动）则跳过
            if _has_task_since(conn, sid, "report_only", since):
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
    """Background scheduler: hourly check; batch triggers with window catch-up."""
    global _last_scheduler_run
    while True:
        try:
            import db as dbmod
            default_db = dbmod.DB_PATH
            now = datetime.now()
            today_key = now.strftime("%Y-%m-%d")

            # 每日一次节流（08:00 后）；正确性由 _trigger_* 的 DB 级窗口去重
            # 保证（重启会重置本内存标记，但窗口查询防重复建任务）。
            if _last_scheduler_run != today_key and now.hour >= 8:
                _last_scheduler_run = today_key

                # 周错题本 / 月度总结：窗口去重保证每周/每月仅一次，
                # 窗口开启后任意天补跑（周一/1 日当天宕机不再永久跳过）
                _trigger_batch_tasks("weekly_mistake_book", default_db)
                _trigger_batch_tasks("monthly_summary", default_db)

                # 周报：仅本周六及以后触发（本周六以来未出过才补）
                if now.weekday() >= 5:
                    _trigger_weekly_reports(default_db)
        except Exception:
            pass

        time.sleep(3600)
