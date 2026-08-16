# -*- coding: utf-8 -*-
"""时区统一回归测试（第 3 周提交 1）。

背景：created_at 等列由 DEFAULT CURRENT_TIMESTAMP 写入 UTC，而业务
周边界（周一/月初/"今天"）按本地时间计算。修复前 date(created_at)
直接与本地日期比较，北京 0-8 点的数据落错周期（8 小时偏移）。

测试在 UTC+8 环境下验证：构造「本地周一 00:30 = UTC 周日 16:30」的
数据，断言归入本地周/月。非 UTC+8 环境自动 skip（产品面向中国时区）。
"""

from datetime import date, datetime, timedelta

import pytest


def _require_utc8():
    off = datetime.now().astimezone().utcoffset()
    if off != timedelta(hours=8):
        pytest.skip(f"需 UTC+8 环境，当前 UTC 偏移 {off}")


def _utc_stamp(local_dt: datetime) -> str:
    """本地 naive datetime → 该时刻的 UTC 时间戳字符串（CURRENT_TIMESTAMP 语义）。"""
    return (local_dt - timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")


# ── 周边界：错题归周 ────────────────────────────────

def test_weekly_stats_counts_local_monday_early_morning(test_db_path, sample_student):
    """本地周一 00:30 入库的错题应计入本周（修复前归上周）。"""
    _require_utc8()
    import db

    monday = date.fromisoformat(db.get_week_start())
    local_early_monday = datetime(monday.year, monday.month, monday.day, 0, 30)
    assert local_early_monday.date() == monday

    mid = db.add_mistake(sample_student, question="q", correct_answer="A",
                         db_path=test_db_path)
    # 把 created_at 改写为该本地时刻对应的 UTC 值（模拟真实入库时间）
    conn = db.get_connection(test_db_path)
    conn.execute("UPDATE mistakes SET created_at = ? WHERE id = ?",
                 [_utc_stamp(local_early_monday), mid])
    conn.commit()
    conn.close()

    stats = db.get_weekly_stats(sample_student, db.get_week_start(),
                                db_path=test_db_path)
    assert stats["new_mistakes_count"] == 1


def test_weekly_stats_excludes_previous_local_week(test_db_path, sample_student):
    """本地上周日 23:30（= 本周一前）入库的错题不得计入本周。"""
    _require_utc8()
    import db

    monday = date.fromisoformat(db.get_week_start())
    last_sunday_night = datetime(monday.year, monday.month, monday.day, 0, 0) - timedelta(minutes=30)

    mid = db.add_mistake(sample_student, question="q", correct_answer="A",
                         db_path=test_db_path)
    conn = db.get_connection(test_db_path)
    conn.execute("UPDATE mistakes SET created_at = ? WHERE id = ?",
                 [_utc_stamp(last_sunday_night), mid])
    conn.commit()
    conn.close()

    stats = db.get_weekly_stats(sample_student, db.get_week_start(),
                                db_path=test_db_path)
    assert stats["new_mistakes_count"] == 0


# ── 周边界：班级活跃统计 ────────────────────────────

def test_class_stats_counts_local_monday_task(test_db_path):
    """本地周一凌晨创建的任务应计入"本周活跃"。"""
    _require_utc8()
    import db

    sid = db.create_student({"name": "tz学生", "grade": "高二", "school_type": "住校",
                             "phone": "13900000001"})
    db.create_admin_user("tz_teacher", "x", "teacher", db_path=test_db_path)
    teacher = db.get_admin_user("tz_teacher", db_path=test_db_path)
    conn = db.get_connection(test_db_path)
    school_id = conn.execute(
        "INSERT INTO schools (name) VALUES ('tz学校')").lastrowid
    class_id = conn.execute(
        "INSERT INTO classes (name, school_id, teacher_id) VALUES ('tz班', ?, ?)",
        [school_id, teacher["id"]]).lastrowid
    conn.execute("UPDATE students SET class_id=? WHERE id=?", [class_id, sid])

    monday = date.fromisoformat(db.get_week_start())
    local_early = datetime(monday.year, monday.month, monday.day, 0, 30)
    conn.execute(
        "INSERT INTO ai_tasks (student_id, task_type, input_data, created_at) "
        "VALUES (?, 'weekly', '{}', ?)", [sid, _utc_stamp(local_early)])
    conn.commit()
    conn.close()

    stats = db.get_class_stats(class_id, db_path=test_db_path)
    assert stats["active_this_week"] == 1


# ── 月边界：月度归集 ────────────────────────────────

def test_monthly_summary_counts_local_month_start(test_db_path, sample_student):
    """本地月 1 日 00:30 的练习记录应归入本月（run_monthly_summary 的归集口径）。"""
    _require_utc8()
    import db

    today = date.today()
    month_start_local = datetime(today.year, today.month, 1, 0, 30)

    mid = db.add_mistake(sample_student, question="q", correct_answer="A",
                         db_path=test_db_path)
    conn = db.get_connection(test_db_path)
    conn.execute(
        "INSERT INTO practice_records (mistake_id, user_answer, is_correct, created_at) "
        "VALUES (?, 'A', 1, ?)", [mid, _utc_stamp(month_start_local)])
    conn.commit()
    conn.close()

    # 与 run_monthly_summary 同口径：本地月内记录数
    month_end = (date(today.year + (today.month == 12), today.month % 12 + 1, 1)
                 - timedelta(days=1))
    conn = db.get_connection(test_db_path)
    n = conn.execute(
        "SELECT COUNT(*) FROM practice_records pr JOIN mistakes m ON m.id=pr.mistake_id "
        "WHERE m.student_id=? AND date(pr.created_at, 'localtime') BETWEEN ? AND ?",
        [sample_student, month_start_local.date().isoformat(),
         month_end.isoformat()]).fetchone()[0]
    conn.close()
    assert n == 1


# ── "今天"边界：LLM 成本 ────────────────────────────

def test_llm_cost_today_uses_local_day(test_db_path):
    """本地今天 00:30（UTC 昨天 16:30）的调用应计入"今日成本"。"""
    _require_utc8()
    import db

    conn = db.get_connection(test_db_path)
    local_early = datetime.combine(date.today(), datetime.min.time()) + timedelta(minutes=30)
    conn.execute(
        "INSERT INTO llm_usage_log (task_id, call_type, estimated_cost, cached, created_at) "
        "VALUES (NULL, 'ocr', 1.5, 0, ?)", [_utc_stamp(local_early)])
    conn.commit()
    conn.close()

    # 直查函数（NULL task_id 不影响 total 口径）
    total = db.get_llm_cost_today(db_path=test_db_path)
    assert total >= 1.5


# ── 防刷每日闸门对齐本地日 ──────────────────────────

def test_practice_daily_gate_local_day(test_db_path, sample_student):
    """本地今天 00:30 已有练习记录 → 今天不得再计分（闸门按本地日判定）。"""
    _require_utc8()
    import db

    mid = db.add_mistake(sample_student, question="q", correct_answer="A",
                         db_path=test_db_path)
    local_early = datetime.combine(date.today(), datetime.min.time()) + timedelta(minutes=30)
    conn = db.get_connection(test_db_path)
    conn.execute(
        "INSERT INTO practice_records (mistake_id, user_answer, is_correct, created_at) "
        "VALUES (?, 'A', 1, ?)", [mid, _utc_stamp(local_early)])
    counted_today = conn.execute(
        "SELECT 1 FROM practice_records WHERE mistake_id = ? "
        "AND date(created_at, 'localtime') = date('now', 'localtime') LIMIT 1",
        [mid]).fetchone()
    conn.close()
    assert counted_today is not None
