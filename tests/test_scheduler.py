# -*- coding: utf-8 -*-
"""调度可靠性回归测试（第 2 周提交 4）。

覆盖：
- 备份决策函数：错过 03:00 窗口全天补跑、weekly 分支不再被 daily 遮蔽、
  24h/7d 新鲜度去重
- 调度器窗口去重：本周一以来有任务不重建、无任务补建、
  周报仅周六后触发且周六以来去重
"""

from datetime import datetime, timedelta, timezone


def _utc(y, m, d, h=12, wd=None):
    return datetime(y, m, d, h, tzinfo=timezone.utc)


# ── 备份决策（app._should_run_backup 纯函数）────────

def test_backup_fires_all_day_after_3am():
    from app import _should_run_backup
    # 03:00 后任意时刻，无历史备份 → daily 触发（原实现仅 03:00-03:10 窗口）
    for hour in (3, 9, 15, 23):
        run_daily, run_weekly = _should_run_backup(_utc(2026, 8, 12, hour), None, None)
        assert run_daily is True, f"hour={hour} 应补跑 daily"
        assert run_weekly is True


def test_backup_not_before_3am():
    from app import _should_run_backup
    run_daily, run_weekly = _should_run_backup(_utc(2026, 8, 12, 2), None, None)
    assert run_daily is False
    assert run_weekly is False


def test_backup_fresh_dedup():
    from app import _should_run_backup
    now = _utc(2026, 8, 12, 10)
    # 6 小时前已有 daily、2 天前已有 weekly → 都不重跑
    run_daily, run_weekly = _should_run_backup(
        now, now - timedelta(hours=6), now - timedelta(days=2))
    assert run_daily is False
    assert run_weekly is False
    # 25 小时前的 daily → 过期重跑
    run_daily, _ = _should_run_backup(
        now, now - timedelta(hours=25), now - timedelta(days=2))
    assert run_daily is True
    # 8 天前的 weekly → 过期重跑
    _, run_weekly = _should_run_backup(
        now, now - timedelta(hours=1), now - timedelta(days=8))
    assert run_weekly is True


def test_backup_weekly_no_longer_shadowed():
    from app import _should_run_backup
    # 原缺陷：周一 03:00 时 daily 分支先命中并 sleep(12h)，weekly 分支不可达。
    # 现在：daily 24h 内已备份时 weekly 仍会执行。
    now = _utc(2026, 8, 10, 3, )  # 周一
    run_daily, run_weekly = _should_run_backup(
        now, now - timedelta(hours=1), now - timedelta(days=8))
    assert run_daily is False
    assert run_weekly is True


# ── 调度器窗口计算（pipeline.scheduler）─────────────

def test_week_start_utc():
    from pipeline.scheduler import _week_start_utc
    # 2026-08-12 是周三 → 本周一 = 2026-08-10
    assert _week_start_utc(datetime(2026, 8, 12, 15)) == "2026-08-10 00:00:00"
    # 周一当天 → 当天
    assert _week_start_utc(datetime(2026, 8, 10, 8)) == "2026-08-10 00:00:00"
    # 周日 → 本周一（往前退 6 天）
    assert _week_start_utc(datetime(2026, 8, 16, 9)) == "2026-08-10 00:00:00"


def test_month_start_utc():
    from pipeline.scheduler import _month_start_utc
    assert _month_start_utc(datetime(2026, 8, 15)) == "2026-08-01 00:00:00"


def test_saturday_start_utc():
    from pipeline.scheduler import _saturday_start_utc
    # 周六当天 → 当天；周六前 → 本周六（未来）；周日 → 昨天（最近的周六）
    assert _saturday_start_utc(datetime(2026, 8, 15, 9)) == "2026-08-15 00:00:00"
    assert _saturday_start_utc(datetime(2026, 8, 13, 9)) == "2026-08-15 00:00:00"
    assert _saturday_start_utc(datetime(2026, 8, 16, 9)) == "2026-08-15 00:00:00"


def _task_count(test_db_path, student_id, kw):
    import db
    conn = db.get_connection(test_db_path)
    n = conn.execute(
        "SELECT COUNT(*) FROM ai_tasks WHERE student_id=? AND input_data LIKE ?",
        [student_id, f"%{kw}%"]).fetchone()[0]
    conn.close()
    return n


def test_batch_dedup_within_window(test_db_path, sample_student, frozen_past_saturday):
    """窗口内已有同 stage 任务 → 不重建；无 → 补建。
    （会话级共享库含其他测试学生，断言只看本学生。）"""
    import db
    from pipeline import scheduler

    # 模拟本周一已创建过 weekly_mistake_book 任务（created_at=UTC 现在）
    db.create_task(sample_student, "weekly",
                   {"stage": "weekly_mistake_book"}, db_path=test_db_path)
    scheduler._enqueue_fn = lambda tid, dbp: None
    scheduler._trigger_batch_tasks("weekly_mistake_book", test_db_path)
    assert _task_count(test_db_path, sample_student, "weekly_mistake_book") == 1

    # monthly_summary：本月无任务 → 补建
    scheduler._trigger_batch_tasks("monthly_summary", test_db_path)
    assert _task_count(test_db_path, sample_student, "monthly_summary") == 1

    # 再跑一次 → 已建过，不再建
    scheduler._trigger_batch_tasks("monthly_summary", test_db_path)
    assert _task_count(test_db_path, sample_student, "monthly_summary") == 1


def test_weekly_report_dedup_since_saturday(test_db_path, sample_student, frozen_past_saturday):
    """本周六以来已有 report_only → 不重复出报。"""
    import db
    from pipeline import scheduler

    # 本周有分析数据才出报：先造 weekly_records
    conn = db.get_connection(test_db_path)
    conn.execute(
        "INSERT INTO weekly_records (student_id, week_start, kind, paper_analyzed) "
        "VALUES (?, ?, 'weekly', 1)",
        [sample_student, db.get_week_start()])
    conn.commit()
    conn.close()

    scheduler._enqueue_fn = lambda tid, dbp: None
    scheduler._trigger_weekly_reports(test_db_path)
    assert _task_count(test_db_path, sample_student, "report_only") == 1

    # 周六以来已有 → 不再建（原实现按当日去重，重启/跨日会重复）
    scheduler._trigger_weekly_reports(test_db_path)
    assert _task_count(test_db_path, sample_student, "report_only") == 1
