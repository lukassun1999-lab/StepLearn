#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析域：仪表盘、周统计、班级统计、教师工作量、运营统计。

从 db.py 拆出（2026-08 第 3 周提交 5）；db 包门面继续对外提供全部符号。
"""

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from db.core import DB_PATH, PRICING, get_connection, get_week_start
from db.learning import get_weak_knowledge_points
from db.operations import get_question_bank_stats
from db.subscriptions import get_expiring_subscriptions
def get_weekly_stats(student_id: int, week_start: str, week_end: str = None,
                     db_path: str = DB_PATH) -> Dict[str, Any]:
    conn = get_connection(db_path)
    if week_end is None:
        week_end = (date.fromisoformat(week_start) + timedelta(days=6)).isoformat()

    new_mistakes = conn.execute("""
        SELECT COUNT(*) FROM mistakes
        WHERE student_id = ? AND date(created_at, 'localtime') BETWEEN ? AND ?
    """, [student_id, week_start, week_end]).fetchone()[0]

    # 统计本周掌握的错题（last_reviewed_at 在本周且已达到 mastery）。
    # 注意时区不对称：created_at 为 UTC 默认值需 'localtime'；
    # last_reviewed_at 由 _now_iso() 写入已是本地时间，不得再加修饰符。
    mastered = conn.execute("""
        SELECT COUNT(*) FROM mistakes
        WHERE student_id = ? AND consecutive_correct >= 2
        AND date(last_reviewed_at) BETWEEN ? AND ?
    """, [student_id, week_start, week_end]).fetchone()[0]

    conn.close()
    return {
        "new_mistakes_count": new_mistakes,
        "mastered_count": mastered,
        "weak_areas": get_weak_knowledge_points(student_id, top_n=5, db_path=db_path),
    }


def get_weekly_comparison(student_id: int, week_start: str, weeks: int = 4,
                          db_path: str = DB_PATH) -> Dict[str, Any]:
    """Return multi-week hard metrics for the parent weekly report.

    Returns a dict with:
      - weeks: list of week_start strings (oldest -> current)
      - new_mistakes: list of int counts per week
      - mastered_count: list of int counts per week
      - accuracy: list of score_history accuracy values per week (None if missing)
      - knowledge_point_trends: {kp: [count, ...]} for current top 5 weak areas
      - onboarding_accuracy: first weekly_test score ever recorded (or None)
      - current_accuracy: most recent weekly_test score (or None)
    """
    conn = get_connection(db_path)
    base = date.fromisoformat(week_start)
    week_starts = [(base - timedelta(days=7 * i)).isoformat() for i in range(weeks - 1, -1, -1)]

    # New mistakes per week
    new_mistakes = []
    mastered_count = []
    for ws in week_starts:
        we = (date.fromisoformat(ws) + timedelta(days=6)).isoformat()
        new_mistakes.append(conn.execute("""
            SELECT COUNT(*) FROM mistakes
            WHERE student_id = ? AND date(created_at) BETWEEN ? AND ?
        """, [student_id, ws, we]).fetchone()[0])
        mastered_count.append(conn.execute("""
            SELECT COUNT(*) FROM mistakes
            WHERE student_id = ? AND consecutive_correct >= 2
            AND date(last_reviewed_at) BETWEEN ? AND ?
        """, [student_id, ws, we]).fetchone()[0])

    # Accuracy per week from score_history (weekly_test only)
    accuracy = []
    for ws in week_starts:
        row = conn.execute("""
            SELECT score FROM score_history
            WHERE student_id = ? AND score_type = 'weekly_test' AND week_start = ?
            ORDER BY created_at DESC LIMIT 1
        """, [student_id, ws]).fetchone()
        accuracy.append(row["score"] if row else None)

    # Knowledge point trends for current top 5 weak areas
    weak_areas = get_weak_knowledge_points(student_id, top_n=5, db_path=db_path)
    kp_trends: Dict[str, List[int]] = {}
    for wa in weak_areas:
        kp = wa["knowledge_point"]
        kp_trends[kp] = []
        for ws in week_starts:
            we = (date.fromisoformat(ws) + timedelta(days=6)).isoformat()
            cnt = conn.execute("""
                SELECT COUNT(*) FROM mistakes
                WHERE student_id = ? AND date(created_at) BETWEEN ? AND ?
                AND knowledge_points LIKE ?
            """, [student_id, ws, we, f'%"{kp}"%']).fetchone()[0]
            kp_trends[kp].append(cnt)

    # Knowledge point mastery rate trends for current top 5 weak areas
    kp_mastery_trends = get_knowledge_point_mastery_trends(
        student_id, week_start, weeks, weak_areas=weak_areas, db_path=db_path
    )

    # Onboarding vs current accuracy
    first_score = conn.execute("""
        SELECT score FROM score_history
        WHERE student_id = ? AND score_type = 'weekly_test'
        ORDER BY created_at ASC LIMIT 1
    """, [student_id]).fetchone()
    last_score = conn.execute("""
        SELECT score FROM score_history
        WHERE student_id = ? AND score_type = 'weekly_test'
        ORDER BY created_at DESC LIMIT 1
    """, [student_id]).fetchone()

    conn.close()
    return {
        "weeks": week_starts,
        "new_mistakes": new_mistakes,
        "mastered_count": mastered_count,
        "accuracy": accuracy,
        "knowledge_point_trends": kp_trends,
        "knowledge_point_mastery_trends": kp_mastery_trends,
        "onboarding_accuracy": first_score["score"] if first_score else None,
        "current_accuracy": last_score["score"] if last_score else None,
    }


def get_knowledge_point_mastery_trends(
    student_id: int,
    week_start: str,
    weeks: int = 4,
    weak_areas: List[Dict[str, Any]] = None,
    db_path: str = DB_PATH,
) -> Dict[str, List[float]]:
    """Return weekly mastery rate (0-100) for each top weak knowledge point.

    Mastery rate = percentage of mistakes tagged with this knowledge point that
    had consecutive_correct >= 2 as of the end of each week. Mistakes created
    after a given week are excluded from that week's denominator.

    Returns: {kp_name: [rate_week1, rate_week2, ..., rate_week_current]}
    """
    if weak_areas is None:
        weak_areas = get_weak_knowledge_points(student_id, top_n=5, db_path=db_path)

    kp_names = [wa["knowledge_point"] for wa in weak_areas]
    if not kp_names:
        return {}

    base = date.fromisoformat(week_start)
    week_ends = [
        (base - timedelta(days=7 * i) + timedelta(days=6)).isoformat()
        for i in range(weeks - 1, -1, -1)
    ]

    conn = get_connection(db_path)

    # Map each KP -> mistake ids created on or before each week end.
    kp_mistake_ids: Dict[str, List[int]] = {kp: [] for kp in kp_names}
    all_mistake_ids: set = set()
    for kp in kp_names:
        rows = conn.execute(
            "SELECT id, created_at FROM mistakes WHERE student_id = ? AND knowledge_points LIKE ?",
            [student_id, f'%"{kp}"%'],
        ).fetchall()
        for r in rows:
            mid = r["id"]
            kp_mistake_ids[kp].append((mid, r["created_at"][:10]))
            all_mistake_ids.add(mid)

    if not all_mistake_ids:
        conn.close()
        return {kp: [0.0] * weeks for kp in kp_names}

    # Fetch all practice records for the relevant mistakes.
    placeholders = ",".join("?" for _ in all_mistake_ids)
    pr_rows = conn.execute(
        f"""
        SELECT mistake_id, is_correct, created_at
        FROM practice_records
        WHERE mistake_id IN ({placeholders})
        ORDER BY created_at ASC
        """,
        list(all_mistake_ids),
    ).fetchall()

    pr_by_mistake: Dict[int, List[Dict[str, Any]]] = {}
    for pr in pr_rows:
        mid = pr["mistake_id"]
        pr_by_mistake.setdefault(mid, []).append({
            "is_correct": bool(pr["is_correct"]),
            "created_at": pr["created_at"][:10],
        })

    conn.close()

    result: Dict[str, List[float]] = {}
    for kp in kp_names:
        mistakes = kp_mistake_ids[kp]
        rates: List[float] = []
        for week_end in week_ends:
            # Only count mistakes that existed by the end of this week.
            active_mistakes = [mid for mid, created in mistakes if created <= week_end]
            total = len(active_mistakes)
            if total == 0:
                rates.append(0.0)
                continue

            mastered = 0
            for mid in active_mistakes:
                consecutive = 0
                for p in pr_by_mistake.get(mid, []):
                    if p["created_at"] > week_end:
                        break
                    if p["is_correct"]:
                        consecutive += 1
                    else:
                        consecutive = 0
                if consecutive >= 2:
                    mastered += 1
            rates.append(round(mastered / total * 100, 1))
        result[kp] = rates

    return result


def get_class_learning_stats(db_path: str = DB_PATH) -> Dict[str, Any]:
    """Get class-wide learning stats."""
    conn = get_connection(db_path)

    # Active students count
    total_students = conn.execute(
        "SELECT COUNT(*) FROM students WHERE status='active'"
    ).fetchone()[0]

    # Average current score
    avg_score = conn.execute("""
        SELECT AVG(english_score) FROM students
        WHERE status='active' AND english_score IS NOT NULL
    """).fetchone()[0]

    # Students with target score
    target_rows = conn.execute("""
        SELECT name, english_score, target_score
        FROM students
        WHERE status='active' AND english_score IS NOT NULL AND target_score IS NOT NULL
    """).fetchall()

    # Class weak knowledge points
    kp_rows = conn.execute("""
        SELECT knowledge_points, consecutive_correct
        FROM mistakes m
        JOIN students s ON s.id = m.student_id
        WHERE s.status = 'active'
    """).fetchall()

    kp_stats: Dict[str, Dict[str, int]] = {}
    for r in kp_rows:
        for kp in json.loads(r["knowledge_points"] or "[]"):
            if kp not in kp_stats:
                kp_stats[kp] = {"total": 0, "mastered": 0}
            kp_stats[kp]["total"] += 1
            if r["consecutive_correct"] >= 2:
                kp_stats[kp]["mastered"] += 1

    weak_kp = sorted(
        [{"knowledge_point": kp, **s,
          "mastery_rate": round(s["mastered"] / s["total"] * 100, 1) if s["total"] > 0 else 0}
         for kp, s in kp_stats.items()],
        key=lambda x: (x["mastery_rate"], -x["total"])
    )[:10]

    # Recent score trends (average per week)
    score_trend_rows = conn.execute("""
        SELECT week_start, AVG(score) as avg_score, COUNT(*) as count
        FROM score_history
        WHERE week_start IS NOT NULL
        GROUP BY week_start
        ORDER BY week_start ASC
        LIMIT 12
    """).fetchall()

    conn.close()

    # Progress toward target
    progress_list = []
    for r in target_rows:
        gap = r["target_score"] - r["english_score"]
        progress_list.append({
            "name": r["name"],
            "current": r["english_score"],
            "target": r["target_score"],
            "gap": round(gap, 1),
        })
    progress_list.sort(key=lambda x: x["gap"], reverse=True)

    return {
        "total_students": total_students,
        "average_score": round(avg_score, 1) if avg_score else None,
        "weak_knowledge_points": weak_kp,
        "score_trend": [dict(r) for r in score_trend_rows],
        "students_progress": progress_list,
    }


def get_operations_stats(db_path: str = DB_PATH) -> Dict[str, Any]:
    """Get overall operations stats for compliance dashboard."""
    conn = get_connection(db_path)

    total_tasks = conn.execute("SELECT COUNT(*) FROM ai_tasks").fetchone()[0]
    failed_tasks = conn.execute(
        "SELECT COUNT(*) FROM ai_tasks WHERE status = 'failed'"
    ).fetchone()[0]

    students_without_consent = conn.execute("""
        SELECT COUNT(*) FROM students s
        WHERE s.status = 'active'
          AND NOT EXISTS (SELECT 1 FROM parent_consents pc WHERE pc.student_id = s.id)
    """).fetchone()[0]

    pending_deletions = conn.execute(
        "SELECT COUNT(*) FROM deletion_requests WHERE status = 'pending'"
    ).fetchone()[0]

    pending_safety = conn.execute(
        "SELECT COUNT(*) FROM aigc_safety_checks WHERE safety_status = 'pending'"
    ).fetchone()[0]

    conn.close()

    return {
        "total_tasks": total_tasks,
        "failed_tasks": failed_tasks,
        "failure_rate": round(failed_tasks / max(total_tasks, 1) * 100, 1),
        "students_without_consent": students_without_consent,
        "pending_deletions": pending_deletions,
        "pending_safety_checks": pending_safety,
    }


# ═══════════════════════════════════════════════════
# Teacher Workload / Efficiency
# ═══════════════════════════════════════════════════

def get_teacher_workload_stats(db_path: str = DB_PATH) -> Dict[str, Any]:
    """Get stats for teacher efficiency dashboard.

    P3-13：审核闸门已移除，删除 pending_review / reviewed_* / recent_rejected
    等审核口径统计；保留「本周待上传试卷」这一仍有意义的运营提醒。
    """
    conn = get_connection(db_path)
    week_start = get_week_start()

    # Students needing paper upload this week
    pending_paper = conn.execute("""
        SELECT s.id, s.name, s.grade
        FROM students s
        LEFT JOIN weekly_records wr
               ON wr.student_id = s.id AND wr.week_start = ? AND wr.kind = 'weekly'
        WHERE s.status = 'active'
          AND (wr.paper_submitted IS NULL OR wr.paper_submitted = 0)
        ORDER BY s.name
    """, [week_start]).fetchall()

    conn.close()

    return {
        "pending_paper_uploads": [dict(r) for r in pending_paper],
    }


# ═══════════════════════════════════════════════════
# Dashboard Operations
# ═══════════════════════════════════════════════════

def get_dashboard_stats(db_path: str = DB_PATH) -> Dict[str, Any]:
    conn = get_connection(db_path)
    monday = get_week_start()

    total = conn.execute("SELECT COUNT(*) FROM students WHERE status='active'").fetchone()[0]
    active_subs = conn.execute(
        "SELECT COUNT(*) FROM subscriptions WHERE status='active'"
    ).fetchone()[0]
    trial_count = conn.execute(
        "SELECT COUNT(*) FROM subscriptions WHERE plan='trial' AND status='active'"
    ).fetchone()[0]

    pending_rows = conn.execute("""
        SELECT s.id, s.name, s.grade, sub.plan,
               wr.paper_submitted, wr.paper_analyzed, wr.exercises_sent,
               wr.exercises_completed, wr.exercises_graded, wr.report_sent,
               wr.week_start, wr.stage, wr.updated_at
        FROM students s
        LEFT JOIN subscriptions sub ON sub.student_id = s.id
        LEFT JOIN weekly_records wr
               ON wr.student_id = s.id AND wr.week_start = ? AND wr.kind = 'weekly'
        WHERE s.status = 'active'
        ORDER BY s.name
    """, [monday]).fetchall()

    plan_labels = {p: info["label"] for p, info in PRICING.items()}
    pending_this_week = 0
    pending_list = []

    from domain import cycle as cycle_mod
    for row in pending_rows:
        plan = row["plan"] or "trial"
        rec = dict(row)
        rec["plan_label"] = plan_labels.get(plan, plan)
        # P2-11：链路视角 —— 周期状态机当前态 + 卡住标记
        rec["stage_label"] = cycle_mod.stage_label(rec.get("stage"))
        rec["stuck"] = cycle_mod.is_stuck(rec)
        pending_list.append(rec)
        if not row["exercises_sent"]:
            pending_this_week += 1

    # P3-13：审核队列已删除（D1 决策：审核闸门移除，质量靠抽检+纠错回路）

    # 订阅到期/续费提醒
    expiring = get_expiring_subscriptions(days=7, db_path=db_path)

    # 题库统计
    qb_stats = get_question_bank_stats(db_path=db_path)

    # 老师工作台统计
    teacher_stats = get_teacher_workload_stats(db_path=db_path)

    # 合规统计
    students_without_consent = conn.execute("""
        SELECT COUNT(*) FROM students s
        WHERE s.status = 'active'
          AND NOT EXISTS (SELECT 1 FROM parent_consents pc WHERE pc.student_id = s.id)
    """).fetchone()[0]
    pending_deletions = conn.execute(
        "SELECT COUNT(*) FROM deletion_requests WHERE status = 'pending'"
    ).fetchone()[0]

    conn.close()
    return {
        "total_students": total,
        "active_subscriptions": active_subs,
        "trial_count": trial_count,
        "pending_this_week": pending_this_week,
        "week_start": monday,
        "pending": pending_list,
        "expiring_subscriptions": expiring,
        "question_bank": qb_stats,
        "teacher_workload": teacher_stats,
        "students_without_consent": students_without_consent,
        "pending_deletions": pending_deletions,
    }


def get_class_stats(class_id: int, db_path: str = DB_PATH) -> Dict[str, Any]:
    """Aggregate statistics for a class."""
    conn = get_connection(db_path)

    student_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM students WHERE class_id = ? AND status = 'active'",
        [class_id],
    ).fetchone()["cnt"]

    week_start = get_week_start()
    active_this_week = conn.execute("""
        SELECT COUNT(DISTINCT s.id) as cnt
        FROM students s
        JOIN ai_tasks t ON t.student_id = s.id
        WHERE s.class_id = ? AND s.status = 'active'
          AND date(t.created_at, 'localtime') >= ?
    """, [class_id, week_start]).fetchone()["cnt"]

    mastery_rows = conn.execute("""
        SELECT m.knowledge_points, m.mastery_level
        FROM mistakes m
        JOIN students s ON s.id = m.student_id
        WHERE s.class_id = ? AND s.status = 'active'
    """, [class_id]).fetchall()

    kp_stats: Dict[str, Dict[str, int]] = {}
    for row in mastery_rows:
        try:
            kps = json.loads(row["knowledge_points"] or "[]")
        except (json.JSONDecodeError, TypeError):
            kps = []
        for kp in kps:
            if kp not in kp_stats:
                kp_stats[kp] = {"total": 0, "mastered": 0}
            kp_stats[kp]["total"] += 1
            if row["mastery_level"] >= 2:
                kp_stats[kp]["mastered"] += 1

    weak_points = []
    for kp, stats in kp_stats.items():
        if stats["total"] >= 2:
            error_rate = 1.0 - (stats["mastered"] / stats["total"])
            weak_points.append({"knowledge_point": kp, "error_rate": round(error_rate, 2),
                                "total": stats["total"], "mastered": stats["mastered"]})
    weak_points.sort(key=lambda x: -x["error_rate"])

    total_mistakes = len(mastery_rows)
    mastered_count = sum(1 for r in mastery_rows if r["mastery_level"] >= 2)
    avg_mastery = round(mastered_count / max(total_mistakes, 1) * 100, 1)

    conn.close()
    return {
        "class_id": class_id,
        "student_count": student_count,
        "active_this_week": active_this_week,
        "avg_mastery_rate": avg_mastery,
        "total_mistakes": total_mistakes,
        "mastered_count": mastered_count,
        "weak_points_top5": weak_points[:5],
    }

