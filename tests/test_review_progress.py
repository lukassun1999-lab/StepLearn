# -*- coding: utf-8 -*-
"""记忆进度 / 遗忘曲线可视化测试。

覆盖 db.get_review_progress 的统计口径与 render_weekly_report 的「🧠 记忆进度」板块。

关键口径：
- 掌握 = 连对 2 次（与 record_practice 一致），已掌握的错题不再进复习队列；
- newly_mastered 必须按 practice_records 的**时间点**重算连续答对，不能读 mistakes
  当前值 —— 否则"早就掌握、本周只是被批改练习带到一次"的错题会被误计为本周新攻克
  （批改任务取题 unmastered_only=False，确实会带上已练对的题）；
- 时区（db/core.py 时区约定）：practice_records.created_at 是 UTC（SQL 侧必须加
  'localtime'），mistakes.last_reviewed_at / next_review_at 是本地（不得再加）。
"""

from datetime import date, datetime, timedelta

import db
from db.learning import _EBBINGHAUS_INTERVALS, record_practice


def _add(db_path, sid):
    return db.add_mistake(
        student_id=sid, source_exam="t", question="Q",
        question_type="单项选择", correct_answer="A", user_answer="B",
        db_path=db_path)


def _week():
    """本周的 (week_start, week_end)。"""
    start = db.get_week_start()
    end = (date.fromisoformat(start) + timedelta(days=6)).isoformat()
    return start, end


def _utc_stamp(local_dt: datetime) -> str:
    """本地 naive datetime → UTC 时间戳字符串（CURRENT_TIMESTAMP 语义）。

    偏移按运行环境的实际时区计算，不硬编码 +8，测试可跨时区运行。
    """
    offset = datetime.now().astimezone().utcoffset() or timedelta(0)
    return (local_dt - offset).strftime("%Y-%m-%d %H:%M:%S")


# ── 统计口径 ────────────────────────────────────────

def test_newly_mastered_counts_this_week(test_db_path, sample_student):
    """本周连对 2 次 → 本周新攻克 1 道，且离开复习队列。"""
    mid = _add(test_db_path, sample_student)
    record_practice(mid, "A", True, db_path=test_db_path)
    record_practice(mid, "A", True, db_path=test_db_path)

    p = db.get_review_progress(sample_student, *_week(), db_path=test_db_path)
    assert p["total"] == 1
    assert p["mastered"] == 1
    assert p["newly_mastered"] == 1
    assert p["active"] == 0


def test_previously_mastered_mistake_not_counted_as_new(test_db_path, sample_student):
    """上周就掌握、本周没有新答题的错题不得计入"本周新攻克"。

    这条是本模块的核心回归：只看 mistakes.consecutive_correct 会把本周被批改
    练习带到一次的已掌握错题误算成新攻克。
    """
    mid = _add(test_db_path, sample_student)
    record_practice(mid, "A", True, db_path=test_db_path)
    record_practice(mid, "A", True, db_path=test_db_path)

    # 把两次练习记录推回上周（仍保持连对 2 次 → 掌握状态不变）
    start, _ = _week()
    last_week = datetime.fromisoformat(f"{start}T10:00:00") - timedelta(days=7)
    conn = db.get_connection(test_db_path)
    conn.execute("UPDATE practice_records SET created_at = ? WHERE mistake_id = ?",
                 [_utc_stamp(last_week), mid])
    conn.commit()
    conn.close()

    p = db.get_review_progress(sample_student, *_week(), db_path=test_db_path)
    assert p["mastered"] == 1, "上周掌握的题当前仍是已掌握"
    assert p["newly_mastered"] == 0, "但不是本周新攻克"


def test_mastery_week_boundary_is_strict(test_db_path, sample_student):
    """周一 00:00 整的那次答对属于本周（周初判定用严格早于周一 00:00）。"""
    mid = _add(test_db_path, sample_student)
    record_practice(mid, "A", True, db_path=test_db_path)
    record_practice(mid, "A", True, db_path=test_db_path)

    start, _ = _week()
    conn = db.get_connection(test_db_path)
    conn.execute("UPDATE practice_records SET created_at = ? WHERE mistake_id = ?",
                 [_utc_stamp(datetime.fromisoformat(f"{start}T00:00:00")), mid])
    conn.commit()
    conn.close()

    p = db.get_review_progress(sample_student, *_week(), db_path=test_db_path)
    assert p["newly_mastered"] == 1


def test_failed_after_mastery_not_counted(test_db_path, sample_student):
    """本周掌握后又答错（连对清零）→ 不算新攻克，回到复习队列。"""
    mid = _add(test_db_path, sample_student)
    record_practice(mid, "A", True, db_path=test_db_path)
    record_practice(mid, "A", True, db_path=test_db_path)   # 达成掌握
    record_practice(mid, "B", False, db_path=test_db_path)  # 又错了

    p = db.get_review_progress(sample_student, *_week(), db_path=test_db_path)
    assert p["mastered"] == 0
    assert p["newly_mastered"] == 0
    assert p["active"] == 1


def test_curve_shape_labels_and_counts(test_db_path, sample_student):
    """curve 是完整 8 阶阶梯（含 0 计数档），标签由间隔表派生，计数只统计未掌握题。"""
    mastered = _add(test_db_path, sample_student)
    record_practice(mastered, "A", True, db_path=test_db_path)
    record_practice(mastered, "A", True, db_path=test_db_path)

    stage1 = _add(test_db_path, sample_student)
    record_practice(stage1, "A", True, db_path=test_db_path)   # → stage 1

    _add(test_db_path, sample_student)                          # 从未练习 → stage 0

    p = db.get_review_progress(sample_student, *_week(), db_path=test_db_path)
    curve = p["curve"]
    assert len(curve) == len(_EBBINGHAUS_INTERVALS) == 8
    assert [c["label"] for c in curve] == [
        "1小时", "1天", "2天", "4天", "7天", "15天", "30天", "60天"]
    assert [c["hours"] for c in curve] == _EBBINGHAUS_INTERVALS
    assert sum(c["count"] for c in curve) == p["active"] == 2
    assert p["stage_distribution"][0] == 1
    assert p["stage_distribution"][1] == 1


def test_due_now_and_upcoming_3d(test_db_path, sample_student):
    """逾期未练计入 due_now；3 天内到期计入 upcoming_3d；远期都不计。"""
    start, _ = _week()
    now = datetime.now()
    overdue = _add(test_db_path, sample_student)
    soon = _add(test_db_path, sample_student)
    later = _add(test_db_path, sample_student)

    conn = db.get_connection(test_db_path)
    for mid, when in ((overdue, now - timedelta(hours=2)),
                      (soon, now + timedelta(days=1)),
                      (later, now + timedelta(days=10))):
        conn.execute("UPDATE mistakes SET next_review_at = ? WHERE id = ?",
                     [when.isoformat(timespec="seconds"), mid])
    conn.commit()
    conn.close()

    p = db.get_review_progress(sample_student, start, None, db_path=test_db_path)
    assert p["due_now"] == 1
    assert p["upcoming_3d"] == 1


def test_regressed_counts_repeated_failure(test_db_path, sample_student):
    """练过多次仍停在低阶 → 反复忘信号。"""
    mid = _add(test_db_path, sample_student)
    record_practice(mid, "B", False, db_path=test_db_path)
    record_practice(mid, "B", False, db_path=test_db_path)

    p = db.get_review_progress(sample_student, *_week(), db_path=test_db_path)
    assert p["regressed"] == 1


def test_no_week_range_skips_newly_mastered(test_db_path, sample_student):
    """不传周区间时 newly_mastered 归零，其余统计照常（供非周报调用方使用）。"""
    mid = _add(test_db_path, sample_student)
    record_practice(mid, "A", True, db_path=test_db_path)

    p = db.get_review_progress(sample_student, db_path=test_db_path)
    assert p["newly_mastered"] == 0
    assert p["active"] == 1


# ── 报告渲染 ────────────────────────────────────────

def _sample_progress(**over):
    rp = {
        "total": 10, "mastered": 4, "active": 6, "newly_mastered": 2,
        "due_now": 1, "upcoming_3d": 2, "regressed": 0,
        "stage_distribution": {0: 2, 1: 3, 5: 1},
        "curve": [
            {"stage": i, "label": f"S{i}", "hours": h, "count": c}
            for i, (h, c) in enumerate(zip(
                _EBBINGHAUS_INTERVALS, [2, 3, 0, 0, 0, 1, 0, 0]))
        ],
    }
    rp.update(over)
    return rp


def _render(**over):
    from report_templates import render_weekly_report
    return render_weekly_report(
        student_name="小明", week_start="2026-08-10", week_end="2026-08-16",
        new_mistakes=5, mastered_count=2, weak_areas=[],
        review_progress=_sample_progress(**over),
    )


def test_weekly_report_renders_memory_section():
    html = _render()
    assert "记忆进度" in html
    assert "本周新攻克" in html
    assert "已掌握（占 40%）" in html     # mastered/total = 4/10
    assert "待复习" in html
    assert "到了复习时间还没练" in html   # due_now 分支


def test_memory_section_reports_regressed_when_no_overdue():
    html = _render(due_now=0, regressed=3)
    assert "练过多次仍不稳定" in html
    assert "到了复习时间还没练" not in html


def test_memory_section_all_clear():
    html = _render(due_now=0, regressed=0)
    assert "复习节奏正常" in html


def test_weekly_report_without_review_progress():
    """向后兼容：不传 review_progress 时不渲染该板块。"""
    from report_templates import render_weekly_report
    html = render_weekly_report(
        student_name="小明", week_start="2026-08-10", week_end="2026-08-16",
        new_mistakes=0, mastered_count=0, weak_areas=[],
    )
    assert "记忆进度" not in html


def test_weekly_report_skips_section_when_no_mistakes():
    """没有任何错题（total=0）时不渲染空板块。"""
    from report_templates import render_weekly_report
    html = render_weekly_report(
        student_name="小明", week_start="2026-08-10", week_end="2026-08-16",
        new_mistakes=0, mastered_count=0, weak_areas=[],
        review_progress={"total": 0, "mastered": 0, "active": 0,
                         "newly_mastered": 0, "curve": []},
    )
    assert "记忆进度" not in html
