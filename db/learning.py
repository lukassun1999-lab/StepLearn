#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""学习域：错题、间隔复习、练习场次、成绩、打卡、成就墙、时间轴、元认知复盘、公开摘要。

从 db.py 拆出（2026-08 第 3 周提交 5）；db 包门面继续对外提供全部符号。
"""

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from db.core import DB_PATH, _now_iso, get_connection, get_week_start
from db.operations import get_learning_plan
from db.students import get_student, get_student_profile
from db.subscriptions import get_subscription_summary
# ═══════════════════════════════════════════════════
# Mistake Book Operations (兼容 data_manager.py API)
# ═══════════════════════════════════════════════════

def add_mistake(
    student_id: int,
    source_exam: str = "",
    question: str = "",
    question_type: str = "",
    correct_answer: str = "",
    user_answer: str = "",
    explanation: str = "",
    knowledge_points: List[str] = None,
    difficulty: int = 2,
    error_cause: str = "",
    cause_evidence: str = "",
    passage: str = "",
    source_task_id: int = None,
    db_path: str = DB_PATH,
) -> int:
    """Add a new mistake. Returns the integer mistake ID.

    source_task_id：由流水线 analyze 节点写入，断点续跑重放时用于
    定位并清理本任务上一次尝试的残留（幂等）。
    """
    conn = get_connection(db_path)
    now = _now_iso()
    cur = conn.execute("""
        INSERT INTO mistakes (student_id, source_exam, question, question_type,
            correct_answer, user_answer, explanation, knowledge_points, difficulty,
            error_cause, cause_evidence, passage, source_task_id,
            next_review_at, review_interval_hours, review_stage, last_reviewed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        student_id, source_exam, question, question_type,
        correct_answer, user_answer, explanation,
        json.dumps(knowledge_points or [], ensure_ascii=False), difficulty,
        error_cause, cause_evidence, passage, source_task_id,
        now, 1.0, 0, now
    ])
    conn.commit()
    conn.close()
    return cur.lastrowid


def purge_task_mistakes(task_id: int, db_path: str = DB_PATH) -> int:
    """删除某次任务写入的全部错题及其从属数据（练习记录/题库引用/场次）。

    analyze 节点重放（僵尸任务断点续跑）前调用，保证幂等：
    崩溃窗口 [错题已入库, advance_cycle 未落] 内复活不会造成错题翻倍。
    返回删除的错题数。
    """
    conn = get_connection(db_path)
    try:
        conn.execute("""
            UPDATE questions SET source_mistake_id = NULL
            WHERE source_mistake_id IN (
                SELECT id FROM mistakes WHERE source_task_id = ?)
        """, [task_id])
        conn.execute("""
            DELETE FROM practice_records WHERE mistake_id IN (
                SELECT id FROM mistakes WHERE source_task_id = ?)
        """, [task_id])
        cur = conn.execute(
            "DELETE FROM mistakes WHERE source_task_id = ?", [task_id])
        conn.execute(
            "DELETE FROM practice_sessions WHERE source_task_id = ?", [task_id])
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def get_mistake(mistake_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM mistakes WHERE id = ?", [mistake_id]).fetchone()
    conn.close()
    if row is None:
        return None
    d = dict(row)
    d["knowledge_points"] = json.loads(d.get("knowledge_points", "[]"))
    return d


def save_cause_profile(student_id: int, profile: Dict[str, Any],
                       db_path: str = DB_PATH) -> None:
    """Upsert a student's error-cause profile (错因因果链画像)."""
    conn = get_connection(db_path)
    conn.execute("""
        INSERT INTO cause_profiles (student_id, primary_cause, primary_evidence,
            cause_chain, secondary_causes, priority_kps, plain_language, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(student_id) DO UPDATE SET
            primary_cause=excluded.primary_cause,
            primary_evidence=excluded.primary_evidence,
            cause_chain=excluded.cause_chain,
            secondary_causes=excluded.secondary_causes,
            priority_kps=excluded.priority_kps,
            plain_language=excluded.plain_language,
            updated_at=excluded.updated_at
    """, [
        student_id,
        profile.get("primary_cause") or "",
        profile.get("primary_evidence") or "",
        json.dumps(profile.get("cause_chain") or [], ensure_ascii=False),
        json.dumps(profile.get("secondary_causes") or [], ensure_ascii=False),
        json.dumps(profile.get("priority_kps") or [], ensure_ascii=False),
        profile.get("plain_language") or "",
        _now_iso(),
    ])
    conn.commit()
    conn.close()


def get_cause_profile(student_id: int,
                      db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Read a student's error-cause profile; JSON fields decoded."""
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT * FROM cause_profiles WHERE student_id = ?", [student_id]).fetchone()
    conn.close()
    if row is None:
        return None
    d = dict(row)
    for k in ("cause_chain", "secondary_causes", "priority_kps"):
        try:
            d[k] = json.loads(d[k] or "[]")
        except Exception:
            d[k] = []
    return d


def save_cause_profile_history(student_id: int, week_start: str, profile: Dict[str, Any],
                               cause_counts: Dict[str, int] = None,
                               db_path: str = DB_PATH) -> None:
    """Upsert a student's per-week error-cause snapshot (跨周对比数据源)。"""
    counts = cause_counts or {}
    conn = get_connection(db_path)
    conn.execute("""
        INSERT INTO cause_profile_history (student_id, week_start, primary_cause,
            cause_counts, total_count, profile_snapshot, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(student_id, week_start) DO UPDATE SET
            primary_cause=excluded.primary_cause,
            cause_counts=excluded.cause_counts,
            total_count=excluded.total_count,
            profile_snapshot=excluded.profile_snapshot
    """, [
        student_id, week_start, profile.get("primary_cause") or "",
        json.dumps(counts, ensure_ascii=False), sum(counts.values()),
        json.dumps(profile, ensure_ascii=False), _now_iso(),
    ])
    conn.commit()
    conn.close()


def get_cause_profile_history(student_id: int, week_start: str = None,
                              before: str = None,
                              db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """取错因画像历史：
    - week_start 指定 → 该周记录
    - before 指定 → 早于该周的最新一条（上周对比用）
    - 都未指定 → 最近一条
    JSON 字段解码后返回。
    """
    conn = get_connection(db_path)
    if week_start:
        row = conn.execute(
            "SELECT * FROM cause_profile_history WHERE student_id = ? AND week_start = ?",
            [student_id, week_start]).fetchone()
    elif before:
        row = conn.execute(
            "SELECT * FROM cause_profile_history WHERE student_id = ? AND week_start < ?"
            " ORDER BY week_start DESC LIMIT 1",
            [student_id, before]).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM cause_profile_history WHERE student_id = ?"
            " ORDER BY week_start DESC LIMIT 1",
            [student_id]).fetchone()
    conn.close()
    if row is None:
        return None
    d = dict(row)
    for k in ("cause_counts", "profile_snapshot"):
        try:
            d[k] = json.loads(d[k] or "{}")
        except Exception:
            d[k] = {}
    return d


def record_unmapped_kps(labels: List[str], db_path: str = DB_PATH) -> None:
    """记录未识别知识点标签（受控词表归一化未命中），按标签累加频次。
    用于定期查看高频未识别词，补充词表 aliases 或新增条目。"""
    labels = [l for l in (labels or []) if isinstance(l, str) and l.strip()]
    if not labels:
        return
    conn = get_connection(db_path)
    now = _now_iso()
    for label in labels:
        conn.execute("""
            INSERT INTO unmapped_kps (label, count, first_seen, last_seen)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(label) DO UPDATE SET
                count = count + 1, last_seen = excluded.last_seen
        """, [label.strip(), now, now])
    conn.commit()
    conn.close()


def get_unmapped_kps(top_n: int = 50, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """取未识别知识点池（按频次降序），供词表补充决策。"""
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT label, count, first_seen, last_seen FROM unmapped_kps"
        " ORDER BY count DESC LIMIT ?", [top_n]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_mistake(mistake_id: int, updates: Dict[str, Any], db_path: str = DB_PATH) -> bool:
    if not updates:
        return False
    conn = get_connection(db_path)
    row = conn.execute("SELECT id FROM mistakes WHERE id = ?", [mistake_id]).fetchone()
    if not row:
        conn.close()
        return False
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values())
    conn.execute(f"UPDATE mistakes SET {set_clause}, last_reviewed_at = ? WHERE id = ?",
                 values + [_now_iso(), mistake_id])
    conn.commit()
    conn.close()
    return True


# ═══════════════════════════════════════════════════
# Spaced Repetition (Ebbinghaus intervals)
# ═══════════════════════════════════════════════════

_EBBINGHAUS_INTERVALS = [
    1.0,     # Stage 0: 1 hour
    24.0,    # Stage 1: 1 day
    48.0,    # Stage 2: 2 days
    96.0,    # Stage 3: 4 days
    168.0,   # Stage 4: 7 days
    360.0,   # Stage 5: 15 days
    720.0,   # Stage 6: 30 days
    1440.0,  # Stage 7: 60 days
]
_MAX_REVIEW_STAGE = len(_EBBINGHAUS_INTERVALS) - 1


def _next_review_at(stage: int, from_time: datetime = None) -> str:
    """Calculate the next review timestamp for a given stage."""
    if stage > _MAX_REVIEW_STAGE:
        stage = _MAX_REVIEW_STAGE
    interval_hours = _EBBINGHAUS_INTERVALS[stage]
    base = from_time or datetime.now()
    return (base + timedelta(hours=interval_hours)).isoformat(timespec="seconds")


def record_practice(mistake_id: int, user_answer: str, is_correct: bool,
                    feedback: str = "", db_path: str = DB_PATH) -> bool:
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM mistakes WHERE id = ?", [mistake_id]).fetchone()
    if not row:
        conn.close()
        return False

    now = _now_iso()

    # 插入练习记录
    conn.execute("""
        INSERT INTO practice_records (mistake_id, user_answer, is_correct, feedback)
        VALUES (?, ?, ?, ?)
    """, [mistake_id, user_answer, int(is_correct), feedback])

    # Ebbinghaus scheduling
    cur_stage = row["review_stage"] or 0
    new_review_count = (row["review_count"] or 0) + 1

    if is_correct:
        new_consecutive = (row["consecutive_correct"] or 0) + 1
        # Advance to next stage
        new_stage = min(_MAX_REVIEW_STAGE, cur_stage + 1)
        # Mastery: blend stage progress and consecutive streak
        new_mastery = min(100, int(new_stage / _MAX_REVIEW_STAGE * 70 + new_consecutive * 10))
    else:
        new_consecutive = 0
        # Reset to stage 1 (1 day) on error — partial reset, not back to zero
        new_stage = 1
        new_mastery = max(0, int(cur_stage / _MAX_REVIEW_STAGE * 50))

    new_interval = _EBBINGHAUS_INTERVALS[new_stage]
    next_review = _next_review_at(new_stage)

    conn.execute("""
        UPDATE mistakes SET
            review_count = ?, consecutive_correct = ?, mastery_level = ?,
            last_reviewed_at = ?, next_review_at = ?,
            review_interval_hours = ?, review_stage = ?
        WHERE id = ?
    """, [new_review_count, new_consecutive, new_mastery,
          now, next_review, new_interval, new_stage, mistake_id])
    conn.commit()
    conn.close()
    return True


def get_due_reviews(student_id: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Get mistakes due for review now (next_review_at <= now) for a student."""
    conn = get_connection(db_path)
    now = _now_iso()
    rows = conn.execute("""
        SELECT * FROM mistakes
        WHERE student_id = ? AND consecutive_correct < 2
          AND next_review_at IS NOT NULL AND next_review_at <= ?
        ORDER BY next_review_at ASC
    """, [student_id, now]).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["knowledge_points"] = json.loads(d.get("knowledge_points", "[]"))
        d["is_mastered"] = d.get("consecutive_correct", 0) >= 2
        results.append(d)
    return results


def get_review_stats(student_id: int, db_path: str = DB_PATH) -> Dict[str, Any]:
    """Get spaced repetition review stats for a student."""
    conn = get_connection(db_path)
    now = _now_iso()
    due_count = conn.execute("""
        SELECT COUNT(*) FROM mistakes
        WHERE student_id = ? AND consecutive_correct < 2
          AND next_review_at IS NOT NULL AND next_review_at <= ?
    """, [student_id, now]).fetchone()[0]

    # Upcoming reviews in next 3 days
    cutoff = (datetime.now() + timedelta(days=3)).isoformat(timespec="seconds")
    upcoming = conn.execute("""
        SELECT COUNT(*) FROM mistakes
        WHERE student_id = ? AND consecutive_correct < 2
          AND next_review_at IS NOT NULL AND next_review_at > ? AND next_review_at <= ?
    """, [student_id, now, cutoff]).fetchone()[0]

    # Stage distribution
    stage_rows = conn.execute("""
        SELECT review_stage, COUNT(*) as cnt FROM mistakes
        WHERE student_id = ? AND consecutive_correct < 2
        GROUP BY review_stage
    """, [student_id]).fetchall()
    conn.close()

    stage_dist = {r["review_stage"]: r["cnt"] for r in stage_rows}

    return {
        "due_now": due_count,
        "upcoming_3d": upcoming,
        "stage_distribution": stage_dist,
        "total_active": sum(stage_dist.values()),
    }


def is_mastered(mistake_id: int, db_path: str = DB_PATH) -> bool:
    conn = get_connection(db_path)
    row = conn.execute("SELECT consecutive_correct FROM mistakes WHERE id = ?",
                       [mistake_id]).fetchone()
    conn.close()
    if row is None:
        return False
    return row["consecutive_correct"] >= 2


def get_unmastered_mistakes(student_id: int = None, knowledge_point: str = None,
                            db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    query = "SELECT * FROM mistakes WHERE consecutive_correct < 2"
    params = []
    if student_id is not None:
        query += " AND student_id = ?"
        params.append(student_id)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["knowledge_points"] = json.loads(d.get("knowledge_points", "[]"))
        if knowledge_point and knowledge_point not in d["knowledge_points"]:
            continue
        results.append(d)
    return results


def get_weak_knowledge_points(student_id: int = None, top_n: int = 5,
                              db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    query = "SELECT knowledge_points, consecutive_correct FROM mistakes"
    params = []
    if student_id is not None:
        query += " WHERE student_id = ?"
        params.append(student_id)
    rows = conn.execute(query, params).fetchall()
    conn.close()

    kp_stats: Dict[str, Dict[str, int]] = {}
    for r in rows:
        for kp in json.loads(r["knowledge_points"] or "[]"):
            if kp not in kp_stats:
                kp_stats[kp] = {"total": 0, "mastered": 0, "unmastered": 0}
            kp_stats[kp]["total"] += 1
            if r["consecutive_correct"] >= 2:
                kp_stats[kp]["mastered"] += 1
            else:
                kp_stats[kp]["unmastered"] += 1

    sorted_kp = sorted(
        kp_stats.items(),
        key=lambda x: (-x[1]["unmastered"], x[1]["mastered"] / max(x[1]["total"], 1)),
    )
    return [
        {
            "knowledge_point": kp,
            "total_mistakes": s["total"],
            "unmastered": s["unmastered"],
            "mastery_rate": round(s["mastered"] / s["total"] * 100, 1),
        }
        for kp, s in sorted_kp[:top_n]
    ]


# ═══════════════════════════════════════════════════
# Session Operations
# ═══════════════════════════════════════════════════

def create_session(student_id: int, exam_name: str = "",
                   source_task_id: int = None,
                   db_path: str = DB_PATH) -> int:
    conn = get_connection(db_path)
    cur = conn.execute("""
        INSERT INTO practice_sessions (student_id, exam_name, status, source_task_id)
        VALUES (?, ?, 'analyzing', ?)
    """, [student_id, exam_name, source_task_id])
    conn.commit()
    conn.close()
    return cur.lastrowid


def get_session(session_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM practice_sessions WHERE id = ?",
                       [session_id]).fetchone()
    conn.close()
    if row is None:
        return None
    d = dict(row)
    d["mistake_ids"] = json.loads(d.get("mistake_ids", "[]"))
    return d


def update_session(session_id: int, updates: Dict[str, Any],
                   db_path: str = DB_PATH) -> bool:
    if not updates:
        return False
    conn = get_connection(db_path)
    row = conn.execute("SELECT id FROM practice_sessions WHERE id = ?",
                       [session_id]).fetchone()
    if not row:
        conn.close()
        return False
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values())
    conn.execute(f"UPDATE practice_sessions SET {set_clause}, updated_at = ? WHERE id = ?",
                 values + [_now_iso(), session_id])
    conn.commit()
    conn.close()
    return True


def add_mistake_to_session(session_id: int, mistake_id: int,
                           db_path: str = DB_PATH) -> bool:
    conn = get_connection(db_path)
    row = conn.execute("SELECT mistake_ids FROM practice_sessions WHERE id = ?",
                       [session_id]).fetchone()
    if not row:
        conn.close()
        return False
    ids = json.loads(row["mistake_ids"] or "[]")
    if mistake_id not in ids:
        ids.append(mistake_id)
    conn.execute("UPDATE practice_sessions SET mistake_ids = ?, updated_at = ? WHERE id = ?",
                 [json.dumps(ids), _now_iso(), session_id])
    conn.commit()
    conn.close()
    return True


def list_sessions(student_id: int = None, status: str = None,
                  db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    query = "SELECT * FROM practice_sessions WHERE 1=1"
    params = []
    if student_id is not None:
        query += " AND student_id = ?"
        params.append(student_id)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY updated_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_next_practice_target(session_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    session = get_session(session_id, db_path)
    if not session:
        return None
    for mid in session.get("mistake_ids", []):
        if not is_mastered(mid, db_path):
            return get_mistake(mid, db_path)
    return None


def is_session_completed(session_id: int, db_path: str = DB_PATH) -> bool:
    session = get_session(session_id, db_path)
    if not session:
        return False
    for mid in session.get("mistake_ids", []):
        if not is_mastered(mid, db_path):
            return False
    return True


# ═══════════════════════════════════════════════════
# Score History & Learning Analytics
# ═══════════════════════════════════════════════════

def record_score(student_id: int, score: float, score_type: str = "weekly_test",
                 source_task_id: int = None, week_start: str = None,
                 note: str = "", db_path: str = DB_PATH) -> int:
    """Record a score for a student. Returns score_history id."""
    conn = get_connection(db_path)
    cur = conn.execute("""
        INSERT INTO score_history (student_id, score, score_type, source_task_id, week_start, note)
        VALUES (?, ?, ?, ?, ?, ?)
    """, [student_id, score, score_type, source_task_id,
          week_start or get_week_start(), note])
    conn.commit()
    conn.close()
    return cur.lastrowid


def get_score_history(student_id: int, limit: int = 20, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Get score history for a student."""
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT * FROM score_history
        WHERE student_id = ?
        ORDER BY created_at ASC
        LIMIT ?
    """, [student_id, limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_student_learning_stats(student_id: int, db_path: str = DB_PATH) -> Dict[str, Any]:
    """Get comprehensive learning stats for a single student."""
    conn = get_connection(db_path)

    student = get_student(student_id, db_path)

    # Score history
    scores = get_score_history(student_id, limit=50, db_path=db_path)

    # Mistake stats
    mistake_stats = conn.execute("""
        SELECT
            COUNT(*) as total_mistakes,
            SUM(CASE WHEN consecutive_correct >= 2 THEN 1 ELSE 0 END) as mastered_mistakes,
            SUM(review_count) as total_reviews
        FROM mistakes
        WHERE student_id = ?
    """, [student_id]).fetchone()

    # Knowledge points mastery
    kp_rows = conn.execute("""
        SELECT knowledge_points, consecutive_correct
        FROM mistakes
        WHERE student_id = ?
    """, [student_id]).fetchall()

    kp_stats: Dict[str, Dict[str, int]] = {}
    for r in kp_rows:
        for kp in json.loads(r["knowledge_points"] or "[]"):
            if kp not in kp_stats:
                kp_stats[kp] = {"total": 0, "mastered": 0}
            kp_stats[kp]["total"] += 1
            if r["consecutive_correct"] >= 2:
                kp_stats[kp]["mastered"] += 1

    # Sort by total mistakes descending
    kp_list = sorted(
        [{"knowledge_point": kp, **s,
          "mastery_rate": round(s["mastered"] / s["total"] * 100, 1)}
         for kp, s in kp_stats.items()],
        key=lambda x: (-x["total"], -x["mastery_rate"])
    )

    # Weekly activity (last 8 weeks)
    weekly_rows = conn.execute("""
        SELECT week_start, paper_submitted, paper_analyzed, exercises_sent,
               exercises_completed, exercises_graded, report_sent
        FROM weekly_records
        WHERE student_id = ?
        ORDER BY week_start DESC
        LIMIT 8
    """, [student_id]).fetchall()

    # Practice accuracy (recent 30 records)
    practice_rows = conn.execute("""
        SELECT pr.is_correct
        FROM practice_records pr
        JOIN mistakes m ON m.id = pr.mistake_id
        WHERE m.student_id = ?
        ORDER BY pr.created_at DESC
        LIMIT 30
    """, [student_id]).fetchall()

    # Recent check-ins (last 14 days) for streak achievement
    since = (date.today() - timedelta(days=14)).isoformat()
    check_in_rows = conn.execute("""
        SELECT DISTINCT check_in_date FROM check_ins
        WHERE student_id = ? AND check_in_date >= ?
        ORDER BY check_in_date DESC
    """, [student_id, since]).fetchall()

    conn.close()

    total_practice = len(practice_rows)
    correct_practice = sum(1 for r in practice_rows if r["is_correct"])
    practice_accuracy = round(correct_practice / total_practice * 100, 1) if total_practice > 0 else 0

    # Generate data-driven achievement cards
    achievements = []
    mastered_kps = [kp for kp in kp_list if kp.get("mastery_rate", 0) >= 80]
    if mastered_kps:
        top_kps = ", ".join(kp["knowledge_point"] for kp in mastered_kps[:5])
        more = f"等 {len(mastered_kps)} 个" if len(mastered_kps) > 5 else ""
        achievements.append({
            "title": "🎯 知识点突破",
            "content": f"已掌握 {len(mastered_kps)} 个知识点：{top_kps}{more}。把这些本领刻进长期记忆！",
            "source": "mistake_book",
        })

    mastered_count = mistake_stats["mastered_mistakes"] or 0
    if mastered_count > 0:
        achievements.append({
            "title": "✅ 错题攻克",
            "content": f"累计 {mastered_count} 道错题已被你拿下，连续答对 2 次，正式移出薄弱清单。",
            "source": "mistake_book",
        })

    if practice_accuracy >= 70 and total_practice >= 5:
        achievements.append({
            "title": "📈 稳定发挥",
            "content": f"近期 {total_practice} 次练习正确率达到 {practice_accuracy}%，状态在线，继续保持！",
            "source": "practice",
        })
    elif practice_accuracy >= 50 and total_practice >= 5:
        achievements.append({
            "title": "🚧 稳步提升",
            "content": f"近期练习正确率 {practice_accuracy}%，错题正在变成你的台阶。",
            "source": "practice",
        })

    # Check-in streak
    if check_in_rows:
        today = date.today().isoformat()
        streak = 0
        for i, r in enumerate(check_in_rows):
            expected = (date.today() - timedelta(days=i)).isoformat()
            if r["check_in_date"] == expected:
                streak += 1
            else:
                break
        if streak >= 1:
            achievements.append({
                "title": "🔥 连续打卡",
                "content": f"已连续打卡 {streak} 天。习惯的力量，比天赋更可靠。",
                "source": "check_in",
            })

    # Spaced repetition stats
    review_stats = get_review_stats(student_id, db_path=db_path)

    return {
        "student": student,
        "target_score": student.get("target_score") if student else None,
        "current_score": student.get("english_score") if student else None,
        "scores": scores,
        "score_trend": [s["score"] for s in scores],
        "mistakes": {
            "total": mistake_stats["total_mistakes"] or 0,
            "mastered": mastered_count,
            "in_progress": (mistake_stats["total_mistakes"] or 0) - (mistake_stats["mastered_mistakes"] or 0),
            "total_reviews": mistake_stats["total_reviews"] or 0,
            "due_now": review_stats["due_now"],
            "upcoming_3d": review_stats["upcoming_3d"],
        },
        "knowledge_points": kp_list,
        "weekly_activity": [dict(r) for r in weekly_rows],
        "practice_accuracy": practice_accuracy,
        "practice_count_recent": total_practice,
        "achievements": achievements,
        "earned_achievements": check_and_award_achievements(student_id, db_path=db_path),
    }


# ═══════════════════════════════════════════════════
# Achievement Wall — 成就墙
# ═══════════════════════════════════════════════════

# Achievement definitions: (key, title_template, description_template, icon, tiers)
# Each tier is (suffix, threshold, label) — e.g. ("_5", 5, "5道")
ACHIEVEMENT_DEFS = [
    # ── 错题攻克 ──
    {
        "key": "mistake_slayer",
        "title": "错题克星",
        "icon": "⚔️",
        "description": "累计攻克 {threshold} 道错题",
        "tiers": [
            ("_5", 5, "5道"), ("_10", 10, "10道"), ("_25", 25, "25道"), ("_50", 50, "50道"),
        ],
        "check": lambda stats: stats.get("mastered_mistakes", 0),
    },
    # ── 知识点突破 ──
    {
        "key": "kp_master",
        "title": "学识渊博",
        "icon": "📚",
        "description": "掌握 {threshold} 个知识点（掌握率≥80%）",
        "tiers": [
            ("_3", 3, "3个"), ("_5", 5, "5个"), ("_10", 10, "10个"), ("_20", 20, "20个"),
        ],
        "check": lambda stats: stats.get("mastered_kp_count", 0),
    },
    # ── 连续打卡 ──
    {
        "key": "streak",
        "title": "打卡先锋",
        "icon": "🔥",
        "description": "连续打卡 {threshold} 天",
        "tiers": [
            ("_3", 3, "3天"), ("_7", 7, "7天"), ("_14", 14, "14天"), ("_30", 30, "30天"),
        ],
        "check": lambda stats: stats.get("check_in_streak", 0),
    },
    # ── 练习正确率 ──
    {
        "key": "accuracy",
        "title": "精准练习",
        "icon": "🎯",
        "description": "近期练习正确率达到 {threshold}%（至少20次）",
        "tiers": [
            ("_70", 70, "70%"), ("_80", 80, "80%"), ("_90", 90, "90%"),
        ],
        "check": lambda stats: stats.get("practice_accuracy", 0) if stats.get("practice_count_recent", 0) >= 20 else 0,
    },
    # ── 活跃周数 ──
    {
        "key": "active_weeks",
        "title": "持之以恒",
        "icon": "📅",
        "description": "累计活跃 {threshold} 周",
        "tiers": [
            ("_4", 4, "4周"), ("_8", 8, "8周"), ("_16", 16, "16周"),
        ],
        "check": lambda stats: stats.get("active_weeks", 0),
    },
    # ── 分数跃升 ──
    {
        "key": "score_jump",
        "title": "飞跃进步",
        "icon": "🚀",
        "description": "英语成绩提升 {threshold} 分",
        "tiers": [
            ("_5", 5, "5分"), ("_10", 10, "10分"), ("_20", 20, "20分"),
        ],
        "check": lambda stats: stats.get("score_improvement", 0),
    },
    # ── 艾宾浩斯毕业 ──
    {
        "key": "ebbinghaus_master",
        "title": "记忆大师",
        "icon": "🧠",
        "description": "有 {threshold} 道错题完成全部8阶艾宾浩斯复习",
        "tiers": [
            ("_1", 1, "1道"), ("_5", 5, "5道"), ("_10", 10, "10道"),
        ],
        "check": lambda stats: stats.get("ebbinghaus_graduated", 0),
    },
    # ── 全勤周 ──
    {
        "key": "perfect_week",
        "title": "完美一周",
        "icon": "🌟",
        "description": "一周内打卡满 {threshold} 天",
        "tiers": [
            ("_5", 5, "5天"), ("_7", 7, "7天"),
        ],
        "check": lambda stats: stats.get("max_weekly_checkins", 0),
    },
    # ── 首次突破 ──
    {
        "key": "first_blood",
        "title": "初露锋芒",
        "icon": "💡",
        "description": "首次攻克错题，迈出第一步",
        "tiers": [
            ("", 1, "首次"),
        ],
        "check": lambda stats: 1 if stats.get("mastered_mistakes", 0) >= 1 else 0,
    },
    # ── 全面掌握 ──
    {
        "key": "full_mastery",
        "title": "学霸认证",
        "icon": "👑",
        "description": "本学期所有知识点掌握率达到100%",
        "tiers": [
            ("", 1, "达成"),
        ],
        "check": lambda stats: 1 if stats.get("all_kps_mastered", False) else 0,
    },
]


def _gather_achievement_stats(student_id: int, db_path: str = DB_PATH) -> Dict[str, Any]:
    """Collect all stats needed for achievement checking."""
    conn = get_connection(db_path)

    # Mastered mistake count
    mastered_mistakes = conn.execute(
        "SELECT COUNT(*) FROM mistakes WHERE student_id = ? AND consecutive_correct >= 2",
        [student_id],
    ).fetchone()[0]

    # Knowledge points with >= 80% mastery rate
    kp_rows = conn.execute(
        "SELECT knowledge_points, consecutive_correct FROM mistakes WHERE student_id = ?",
        [student_id],
    ).fetchall()
    kp_stats: Dict[str, Dict[str, int]] = {}
    for r in kp_rows:
        for kp in json.loads(r["knowledge_points"] or "[]"):
            if kp not in kp_stats:
                kp_stats[kp] = {"total": 0, "mastered": 0}
            kp_stats[kp]["total"] += 1
            if r["consecutive_correct"] >= 2:
                kp_stats[kp]["mastered"] += 1
    mastered_kp_count = sum(
        1 for s in kp_stats.values()
        if s["total"] > 0 and s["mastered"] / s["total"] >= 0.8
    )
    all_kps_mastered = len(kp_stats) > 0 and all(
        s["total"] > 0 and s["mastered"] / s["total"] >= 0.8
        for s in kp_stats.values()
    )

    # Check-in streak (consecutive days ending today)
    today = date.today()
    check_in_rows = conn.execute(
        "SELECT DISTINCT check_in_date FROM check_ins WHERE student_id = ? ORDER BY check_in_date DESC LIMIT 60",
        [student_id],
    ).fetchall()
    streak = 0
    for i, r in enumerate(check_in_rows):
        expected = (today - timedelta(days=i)).isoformat()
        if r["check_in_date"] == expected:
            streak += 1
        else:
            break

    # Max weekly check-ins (best week ever)
    max_weekly = 0
    if check_in_rows:
        week_counts: Dict[str, int] = {}
        for r in check_in_rows:
            d = date.fromisoformat(r["check_in_date"])
            week_start = (d - timedelta(days=d.weekday())).isoformat()
            week_counts[week_start] = week_counts.get(week_start, 0) + 1
        max_weekly = max(week_counts.values()) if week_counts else 0

    # Practice accuracy (recent 30)
    practice_rows = conn.execute(
        "SELECT pr.is_correct FROM practice_records pr "
        "JOIN mistakes m ON m.id = pr.mistake_id WHERE m.student_id = ? "
        "ORDER BY pr.created_at DESC LIMIT 30",
        [student_id],
    ).fetchall()
    total_practice = len(practice_rows)
    correct_practice = sum(1 for r in practice_rows if r["is_correct"])
    practice_accuracy = round(correct_practice / total_practice * 100, 1) if total_practice > 0 else 0

    # Score improvement
    score_rows = conn.execute(
        "SELECT score FROM score_history WHERE student_id = ? ORDER BY created_at ASC",
        [student_id],
    ).fetchall()
    score_improvement = 0
    if len(score_rows) >= 2:
        first_score = score_rows[0]["score"] or 0
        latest_score = score_rows[-1]["score"] or 0
        score_improvement = max(0, round(latest_score - first_score, 1))

    # Active weeks (weeks with any record)
    active_weeks = conn.execute(
        "SELECT COUNT(DISTINCT week_start) FROM weekly_records WHERE student_id = ?",
        [student_id],
    ).fetchone()[0]

    # Ebbinghaus graduates (review_stage >= 7)
    ebbinghaus_graduated = conn.execute(
        "SELECT COUNT(*) FROM mistakes WHERE student_id = ? AND review_stage >= 7 AND consecutive_correct >= 2",
        [student_id],
    ).fetchone()[0]

    conn.close()

    return {
        "mastered_mistakes": mastered_mistakes,
        "mastered_kp_count": mastered_kp_count,
        "all_kps_mastered": all_kps_mastered,
        "check_in_streak": streak,
        "max_weekly_checkins": max_weekly,
        "practice_accuracy": practice_accuracy,
        "practice_count_recent": total_practice,
        "score_improvement": score_improvement,
        "active_weeks": active_weeks,
        "ebbinghaus_graduated": ebbinghaus_graduated,
    }


def check_and_award_achievements(student_id: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Check all achievement conditions and award any newly earned ones.
    Returns list of newly awarded achievements."""
    stats = _gather_achievement_stats(student_id, db_path)
    conn = get_connection(db_path)

    # Get already-earned achievement keys
    existing = set(
        r[0] for r in conn.execute(
            "SELECT achievement_key FROM achievements WHERE student_id = ?",
            [student_id],
        ).fetchall()
    )

    newly_awarded = []
    now = _now_iso()

    for adef in ACHIEVEMENT_DEFS:
        base_key = adef["key"]
        current_value = adef["check"](stats)
        for suffix, threshold, label in adef["tiers"]:
            ach_key = f"{base_key}{suffix}"
            if ach_key in existing:
                continue
            if current_value >= threshold:
                try:
                    conn.execute(
                        "INSERT INTO achievements (student_id, achievement_key, title, description, icon, tier, earned_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        [
                            student_id, ach_key,
                            adef["title"] + " " + label,
                            adef["description"].format(threshold=label),
                            adef["icon"],
                            adef["tiers"].index((suffix, threshold, label)) + 1,
                            now,
                        ],
                    )
                    conn.commit()
                    newly_awarded.append({
                        "achievement_key": ach_key,
                        "title": adef["title"] + " " + label,
                        "description": adef["description"].format(threshold=label),
                        "icon": adef["icon"],
                        "tier": adef["tiers"].index((suffix, threshold, label)) + 1,
                        "earned_at": now,
                    })
                    existing.add(ach_key)
                except sqlite3.IntegrityError:
                    pass  # Race condition, already exists

    conn.close()
    return newly_awarded


def get_student_achievements(student_id: int, db_path: str = DB_PATH) -> Dict[str, Any]:
    """Get all earned achievements and progress toward locked ones."""
    conn = get_connection(db_path)
    earned_rows = conn.execute(
        "SELECT * FROM achievements WHERE student_id = ? ORDER BY earned_at DESC",
        [student_id],
    ).fetchall()
    conn.close()

    earned = [dict(r) for r in earned_rows]
    earned_keys = {r["achievement_key"] for r in earned}

    # Build progress list: all achievements with locked/unlocked status
    stats = _gather_achievement_stats(student_id, db_path)
    all_achievements = []
    for adef in ACHIEVEMENT_DEFS:
        current_value = adef["check"](stats)
        for suffix, threshold, label in adef["tiers"]:
            ach_key = f"{adef['key']}{suffix}"
            is_earned = ach_key in earned_keys
            # Find the earned record if it exists
            earned_record = next((e for e in earned if e["achievement_key"] == ach_key), None)
            all_achievements.append({
                "achievement_key": ach_key,
                "title": adef["title"] + " " + label,
                "description": adef["description"].format(threshold=label),
                "icon": adef["icon"],
                "tier": adef["tiers"].index((suffix, threshold, label)) + 1,
                "threshold": threshold,
                "current": min(current_value, threshold),
                "progress_pct": round(min(current_value / max(threshold, 1), 1.0) * 100),
                "earned": is_earned,
                "earned_at": earned_record["earned_at"] if earned_record else None,
            })

    return {
        "earned": earned,
        "earned_count": len(earned),
        "total_count": len(all_achievements),
        "all": all_achievements,
    }


# ═══════════════════════════════════════════════════
# Learning Path Timeline — 学习路径时间轴
# ═══════════════════════════════════════════════════

def get_student_timeline(student_id: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Generate a chronological learning path timeline for a student.
    Returns a list of milestone dicts sorted by date ascending."""
    conn = get_connection(db_path)
    milestones = []

    # 1. 入学诊断 — first learning plan
    plan_row = conn.execute(
        "SELECT generated_at FROM learning_plans WHERE student_id = ? ORDER BY generated_at ASC LIMIT 1",
        [student_id],
    ).fetchone()
    if plan_row and plan_row["generated_at"]:
        milestones.append({
            "date": plan_row["generated_at"][:10],
            "icon": "🎓",
            "title": "入学诊断",
            "description": "AI 生成首份个性化学习方案，学习之旅正式启航",
            "type": "enrollment",
        })

    # 2. 首次攻克错题
    first_mastered = conn.execute(
        "SELECT created_at, question FROM mistakes WHERE student_id = ? AND consecutive_correct >= 2 ORDER BY last_reviewed_at ASC LIMIT 1",
        [student_id],
    ).fetchone()
    if first_mastered and first_mastered["created_at"]:
        q_preview = (first_mastered["question"] or "")[:30]
        milestones.append({
            "date": first_mastered["created_at"][:10],
            "icon": "✅",
            "title": "首次攻克错题",
            "description": f"「{q_preview}...」连续答对，移出错题本",
            "type": "first_mastery",
        })

    # 3. 首次分数进步
    score_rows = conn.execute(
        "SELECT created_at, score FROM score_history WHERE student_id = ? ORDER BY created_at ASC",
        [student_id],
    ).fetchall()
    if len(score_rows) >= 2:
        first_score = score_rows[0]["score"] or 0
        for r in score_rows[1:]:
            if (r["score"] or 0) > first_score:
                improvement = round((r["score"] or 0) - first_score, 1)
                milestones.append({
                    "date": r["created_at"][:10],
                    "icon": "📈",
                    "title": "首次进步",
                    "description": f"英语成绩从 {first_score} 提升到 {r['score']}（+{improvement}分）",
                    "type": "first_score_up",
                })
                break

    # 4 & 5. 连续打卡里程碑
    check_in_rows = conn.execute(
        "SELECT DISTINCT check_in_date FROM check_ins WHERE student_id = ? ORDER BY check_in_date ASC",
        [student_id],
    ).fetchall()
    if check_in_rows:
        # Find the first date when streak hit 3, 7, 14, 30
        targets = [3, 7, 14, 30]
        streak = 0
        prev_date = None
        hit_targets = set()
        for r in check_in_rows:
            d = date.fromisoformat(r["check_in_date"])
            if prev_date and (d - prev_date).days == 1:
                streak += 1
            else:
                streak = 1
            prev_date = d
            for t in targets:
                if streak >= t and t not in hit_targets:
                    hit_targets.add(t)
                    label = f"{t}天" if t <= 7 else f"{t//7}周" if t % 7 == 0 else f"{t}天"
                    milestones.append({
                        "date": d.isoformat(),
                        "icon": "🔥",
                        "title": f"连续打卡{label}",
                        "description": f"连续坚持 {t} 天，习惯正在养成",
                        "type": f"streak_{t}",
                    })

    # 6. 连续3周达标 (completion rate >= 80%)
    weekly_rows = conn.execute(
        "SELECT week_start, paper_submitted, exercises_completed, exercises_sent "
        "FROM weekly_records WHERE student_id = ? ORDER BY week_start ASC",
        [student_id],
    ).fetchall()
    consecutive_good = 0
    for wr in weekly_rows:
        sent = wr["exercises_sent"] or 0
        done = wr["exercises_completed"] or 0
        rate = done / max(sent, 1)
        if wr["paper_submitted"] and rate >= 0.8:
            consecutive_good += 1
        else:
            consecutive_good = 0
        if consecutive_good >= 3:
            milestones.append({
                "date": wr["week_start"],
                "icon": "🌟",
                "title": "连续达标",
                "description": "连续 3 周完成率 ≥ 80%，进入稳定上升通道",
                "type": "consistent_3w",
            })
            break

    # 7. 掌握过半知识点
    kp_rows = conn.execute(
        "SELECT knowledge_points, consecutive_correct, created_at FROM mistakes WHERE student_id = ? ORDER BY created_at ASC",
        [student_id],
    ).fetchall()
    kp_best: Dict[str, Dict[str, Any]] = {}
    for r in kp_rows:
        for kp in json.loads(r["knowledge_points"] or "[]"):
            if kp not in kp_best:
                kp_best[kp] = {"mastered": False, "first_date": r["created_at"]}
            if r["consecutive_correct"] >= 2:
                kp_best[kp]["mastered"] = True
    total_kp = len(kp_best)
    if total_kp > 0:
        # Walk through time to find when mastery crossed 50%
        mastered_so_far = 0
        kp_mastered_at: Dict[str, str] = {}
        for r in kp_rows:
            for kp in json.loads(r["knowledge_points"] or "[]"):
                if kp not in kp_mastered_at and r["consecutive_correct"] >= 2:
                    kp_mastered_at[kp] = r["created_at"]
                    mastered_so_far += 1
                    if mastered_so_far >= total_kp / 2 and not any(
                        m["type"] == "half_mastered" for m in milestones
                    ):
                        milestones.append({
                            "date": r["created_at"][:10],
                            "icon": "🏆",
                            "title": "掌握过半",
                            "description": f"已掌握 {total_kp} 个知识点中的过半（{mastered_so_far}个），稳步推进",
                            "type": "half_mastered",
                        })
        # All mastered?
        if mastered_so_far >= total_kp:
            milestones.append({
                "date": max(kp_mastered_at.values())[:10] if kp_mastered_at else "",
                "icon": "👑",
                "title": "全科掌握",
                "description": f"全部 {total_kp} 个知识点已掌握",
                "type": "all_mastered",
            })

    # 8. 达成目标分数
    student = conn.execute(
        "SELECT target_score FROM students WHERE id = ?", [student_id]
    ).fetchone()
    target = student["target_score"] if student else None
    if target and score_rows:
        for r in score_rows:
            if (r["score"] or 0) >= target:
                milestones.append({
                    "date": r["created_at"][:10],
                    "icon": "🎯",
                    "title": "达成目标",
                    "description": f"英语成绩达到 {r['score']} 分，达成目标 {target} 分！",
                    "type": "target_reached",
                })
                break

    # 9. 艾宾浩斯毕业
    first_ebb_graduate = conn.execute(
        "SELECT created_at, question FROM mistakes WHERE student_id = ? AND review_stage >= 7 AND consecutive_correct >= 2 ORDER BY last_reviewed_at ASC LIMIT 1",
        [student_id],
    ).fetchone()
    if first_ebb_graduate:
        q_preview = (first_ebb_graduate["question"] or "")[:30]
        milestones.append({
            "date": first_ebb_graduate["created_at"][:10],
            "icon": "🧠",
            "title": "记忆大师",
            "description": f"首道错题完成全部 8 阶艾宾浩斯复习：{q_preview}...",
            "type": "ebbinghaus_grad",
        })

    # 10. 错题攻克 10 道
    mastered_count = conn.execute(
        "SELECT COUNT(*) FROM mistakes WHERE student_id = ? AND consecutive_correct >= 2",
        [student_id],
    ).fetchone()[0]
    if mastered_count >= 10:
        # Find the date of the 10th mastered mistake
        tenth = conn.execute(
            "SELECT last_reviewed_at FROM mistakes WHERE student_id = ? AND consecutive_correct >= 2 ORDER BY last_reviewed_at ASC LIMIT 1 OFFSET 9",
            [student_id],
        ).fetchone()
        if tenth:
            milestones.append({
                "date": tenth["last_reviewed_at"][:10],
                "icon": "⚔️",
                "title": "错题克星·10道",
                "description": f"累计攻克 10 道错题，稳步消灭薄弱点",
                "type": "mistake_10",
            })

    # 11. 练习 50 次
    practice_count = conn.execute(
        "SELECT COUNT(*) FROM practice_records pr JOIN mistakes m ON m.id = pr.mistake_id WHERE m.student_id = ?",
        [student_id],
    ).fetchone()[0]
    if practice_count >= 50:
        fiftieth = conn.execute(
            "SELECT pr.created_at FROM practice_records pr JOIN mistakes m ON m.id = pr.mistake_id WHERE m.student_id = ? ORDER BY pr.created_at ASC LIMIT 1 OFFSET 49",
            [student_id],
        ).fetchone()
        if fiftieth:
            milestones.append({
                "date": fiftieth["created_at"][:10],
                "icon": "💪",
                "title": "练习达人",
                "description": "累计完成 50 次练习，量变引起质变",
                "type": "practice_50",
            })

    # 12. 首次满分
    if score_rows:
        for r in score_rows:
            if (r["score"] or 0) >= 100:
                milestones.append({
                    "date": r["created_at"][:10],
                    "icon": "💯",
                    "title": "满分突破",
                    "description": "首次取得满分成绩！",
                    "type": "perfect_score",
                })
                break

    conn.close()

    # Sort by date
    milestones.sort(key=lambda m: m["date"])
    return milestones


# ═══════════════════════════════════════════════════
# Metacognitive Review — 元认知复盘表
# ═══════════════════════════════════════════════════

# （get_week_start 曾在此重复定义并遮蔽前一份，2026-08 删除）


def get_or_create_metacognitive_review(student_id: int, week_start: str = None,
                                        db_path: str = DB_PATH) -> Dict[str, Any]:
    """Get existing review for a week, or create a new one from the AI template."""
    if week_start is None:
        week_start = get_week_start()
    conn = get_connection(db_path)

    # Check existing
    row = conn.execute(
        "SELECT * FROM metacognitive_reviews WHERE student_id = ? AND week_start = ?",
        [student_id, week_start],
    ).fetchone()

    if row:
        d = dict(row)
        for field in ["template_questions", "child_answers", "parent_answers"]:
            try:
                d[field] = json.loads(d.get(field) or "{}")
            except Exception:
                d[field] = {}
        conn.close()
        return d

    # Create new from AI template in learning_plan
    plan = get_learning_plan(student_id, db_path=db_path)
    plan_data = plan.get("plan_data", {}) if plan else {}
    if isinstance(plan_data, str):
        try:
            plan_data = json.loads(plan_data)
        except Exception:
            plan_data = {}
    meta_review = plan_data.get("metacognitive_review", {})
    if isinstance(meta_review, str):
        try:
            meta_review = json.loads(meta_review)
        except Exception:
            meta_review = {}

    template = {
        "child_reflection": meta_review.get("child_reflection", [
            "这周学习中最有成就感的一件事是什么？",
            "哪个知识点让你觉得最难？你是怎么应对的？",
            "下周你想在哪方面做得更好？",
        ]),
        "parent_observation": meta_review.get("parent_observation", [
            "这周孩子在学习上有什么让你惊喜的表现？",
            "你观察到孩子在学习习惯上有什么变化？",
        ]),
    }

    try:
        conn.execute(
            "INSERT INTO metacognitive_reviews (student_id, week_start, template_questions, status) VALUES (?, ?, ?, 'draft')",
            [student_id, week_start, json.dumps(template, ensure_ascii=False)],
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # Race condition

    conn.close()
    return {
        "student_id": student_id,
        "week_start": week_start,
        "template_questions": template,
        "child_answers": {},
        "parent_answers": {},
        "child_mood": None,
        "parent_mood": None,
        "child_note": None,
        "parent_note": None,
        "status": "draft",
    }


def submit_metacognitive_review(student_id: int, week_start: str,
                                 child_answers: Dict = None,
                                 parent_answers: Dict = None,
                                 child_mood: int = None,
                                 parent_mood: int = None,
                                 child_note: str = None,
                                 parent_note: str = None,
                                 db_path: str = DB_PATH) -> bool:
    """Save a metacognitive review (draft or submit)."""
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT id FROM metacognitive_reviews WHERE student_id = ? AND week_start = ?",
        [student_id, week_start],
    ).fetchone()
    if not row:
        conn.close()
        # Auto-create
        get_or_create_metacognitive_review(student_id, week_start, db_path)
        conn = get_connection(db_path)
        row = conn.execute(
            "SELECT id FROM metacognitive_reviews WHERE student_id = ? AND week_start = ?",
            [student_id, week_start],
        ).fetchone()
        if not row:
            conn.close()
            return False

    conn.execute(
        """UPDATE metacognitive_reviews SET
            child_answers = ?, parent_answers = ?,
            child_mood = ?, parent_mood = ?,
            child_note = ?, parent_note = ?,
            status = 'submitted', submitted_at = ?
        WHERE id = ?""",
        [
            json.dumps(child_answers or {}, ensure_ascii=False),
            json.dumps(parent_answers or {}, ensure_ascii=False),
            child_mood, parent_mood,
            child_note, parent_note,
            _now_iso(), row["id"],
        ],
    )
    conn.commit()
    conn.close()
    return True


def get_metacognitive_reviews(student_id: int, limit: int = 10,
                               db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Get all metacognitive reviews for a student, newest first."""
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM metacognitive_reviews WHERE student_id = ? ORDER BY week_start DESC LIMIT ?",
        [student_id, limit],
    ).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        for field in ["template_questions", "child_answers", "parent_answers"]:
            try:
                d[field] = json.loads(d.get(field) or "{}")
            except Exception:
                d[field] = {}
        results.append(d)
    return results


# ═══════════════════════════════════════════════════
# Student Learning Loop (Check-ins + Mistake Book)
# ═══════════════════════════════════════════════════

def record_check_in(student_id: int, check_in_date: str = None, content: str = "",
                    duration_minutes: int = 0, source: str = "manual",
                    db_path: str = DB_PATH) -> int:
    """Record a student check-in. Returns check_in id."""
    conn = get_connection(db_path)
    date_str = check_in_date or date.today().isoformat()
    cur = conn.execute("""
        INSERT OR REPLACE INTO check_ins (student_id, check_in_date, content, duration_minutes, source)
        VALUES (?, ?, ?, ?, ?)
    """, [student_id, date_str, content, duration_minutes, source])
    conn.commit()
    conn.close()
    return cur.lastrowid


def get_check_ins(student_id: int, limit: int = 30, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Get recent check-ins for a student."""
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT * FROM check_ins
        WHERE student_id = ?
        ORDER BY check_in_date DESC
        LIMIT ?
    """, [student_id, limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_check_in_calendar(student_id: int, days: int = 30, db_path: str = DB_PATH) -> List[str]:
    """Get list of dates with check-ins in last N days."""
    conn = get_connection(db_path)
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT DISTINCT check_in_date FROM check_ins
        WHERE student_id = ? AND check_in_date >= ?
        ORDER BY check_in_date DESC
    """, [student_id, since]).fetchall()
    conn.close()
    return [r["check_in_date"] for r in rows]


def get_weekly_completion_rate(student_id: int, week_start: str,
                               db_path: str = DB_PATH) -> float:
    """
    Calculate weekly completion rate based on check-ins, weekly exercise status,
    and parent task completion. Returns a float between 0 and 1.
    """
    from datetime import timedelta as _timedelta
    conn = get_connection(db_path)

    # Count check-ins in the week
    week_start_dt = date.fromisoformat(week_start)
    week_end_dt = week_start_dt + _timedelta(days=6)
    week_end = week_end_dt.isoformat()

    check_in_rows = conn.execute("""
        SELECT COUNT(DISTINCT check_in_date) AS cnt FROM check_ins
        WHERE student_id = ? AND check_in_date >= ? AND check_in_date <= ?
    """, [student_id, week_start, week_end]).fetchall()
    check_in_days = check_in_rows[0]["cnt"] if check_in_rows else 0

    # Weekly exercise completion status
    weekly_row = conn.execute("""
        SELECT exercises_completed FROM weekly_records
        WHERE student_id = ? AND week_start = ?
    """, [student_id, week_start]).fetchone()
    exercise_completed = bool(weekly_row and weekly_row["exercises_completed"])

    # Parent task completion rate
    parent_task_rate = 0.0
    profile = get_student_profile(student_id, db_path=db_path)
    if profile:
        ptp = profile.get("parent_task_progress", {})
        if isinstance(ptp, dict) and ptp:
            total_tasks = len(ptp)
            completed_tasks = sum(1 for v in ptp.values() if v)
            parent_task_rate = completed_tasks / total_tasks if total_tasks > 0 else 0.0

    conn.close()

    # Base rate from check-ins (expect at least 4 days out of 7)
    check_in_rate = min(1.0, check_in_days / 4.0) if check_in_days > 0 else 0.0
    # If weekly exercise completed, ensure at least 70%
    if exercise_completed:
        check_in_rate = max(check_in_rate, 0.7)

    # Blend: 60% student activity + 40% parent engagement
    blended_rate = check_in_rate * 0.6 + parent_task_rate * 0.4
    return round(min(1.0, max(0.0, blended_rate)), 2)


def get_student_mistake_book(student_id: int, mastered: bool = False,
                             db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Get mistake book for a student. By default returns unmastered mistakes."""
    conn = get_connection(db_path)
    query = "SELECT * FROM mistakes WHERE student_id = ?"
    params = [student_id]
    if not mastered:
        query += " AND consecutive_correct < 2"
    query += " ORDER BY created_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["knowledge_points"] = json.loads(d.get("knowledge_points", "[]"))
        d["is_mastered"] = d.get("consecutive_correct", 0) >= 2
        results.append(d)
    return results


def mark_mistake_mastered(mistake_id: int, db_path: str = DB_PATH) -> bool:
    """Mark a mistake as mastered by setting consecutive_correct to 2."""
    conn = get_connection(db_path)
    row = conn.execute("SELECT id FROM mistakes WHERE id = ?", [mistake_id]).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute("""
        UPDATE mistakes SET consecutive_correct = 2, mastery_level = 100, last_reviewed_at = ?
        WHERE id = ?
    """, [_now_iso(), mistake_id])
    conn.commit()
    conn.close()
    return True


def get_student_public_summary(code: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Get public summary for student page by access_code.

    字段白名单：公开页严禁返回整行 students（曾 SELECT * 泄漏
    phone/password_hash/家长微信等，安全审查 P0）。
    """
    conn = get_connection(db_path)
    student = conn.execute(
        "SELECT id, name, grade, school_type, english_score, target_score, "
        "gender, textbook_version, semester, status, created_at "
        "FROM students WHERE access_code = ? AND status = 'active'", [code]
    ).fetchone()
    if not student:
        conn.close()
        return None

    student_id = student["id"]

    # Mistakes
    mistakes = get_student_mistake_book(student_id, mastered=False, db_path=db_path)
    mastered_mistakes = get_student_mistake_book(student_id, mastered=True, db_path=db_path)

    # Scores
    scores = get_score_history(student_id, limit=12, db_path=db_path)

    # Check-ins
    check_ins = get_check_in_calendar(student_id, days=800, db_path=db_path)

    # Weekly activity
    weekly_rows = conn.execute("""
        SELECT week_start, paper_submitted, exercises_sent, exercises_graded, report_sent
        FROM weekly_records
        WHERE student_id = ?
        ORDER BY week_start DESC
        LIMIT 8
    """, [student_id]).fetchall()

    # Learning plan
    plan = get_learning_plan(student_id, db_path=db_path)

    # Weak points
    weak_points = get_weak_knowledge_points(student_id, top_n=8, db_path=db_path)

    # Spaced repetition review stats
    review_stats = get_review_stats(student_id, db_path=db_path)
    due_reviews = get_due_reviews(student_id, db_path=db_path)

    # Student profile (for learning style radar chart)
    profile = get_student_profile(student_id, db_path=db_path)
    learning_style = None
    if profile:
        ls_detail = profile.get("learning_style_detail", {})
        if isinstance(ls_detail, dict) and any(
            ls_detail.get(k) for k in ["visual", "auditory", "kinesthetic", "read_write"]
        ):
            learning_style = ls_detail

    conn.close()

    return {
        "student": dict(student),
        "mistakes": mistakes,
        "mistakes_count": len(mistakes),
        "mastered_count": len(mastered_mistakes),
        "due_reviews": due_reviews,
        "due_review_count": len(due_reviews),
        "review_stats": review_stats,
        "learning_style": learning_style,
        "scores": scores,
        "check_ins": check_ins,
        "weekly_activity": [dict(r) for r in weekly_rows],
        "learning_plan": plan,
        "weak_points": weak_points,
    }

