#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合规域：监护人同意（版本化/撤回）、注销级联删除、AI 内容抽检。

从 db.py 拆出（2026-08 第 3 周提交 5）；db 包门面继续对外提供全部符号。
"""

import json
import os
import shutil
import sqlite3
from typing import Any, Dict, List, Optional

from db.core import DB_PATH, PROJECT_ROOT, _now_iso, get_connection
# ═══════════════════════════════════════════════════
# Compliance & Operations
# ═══════════════════════════════════════════════════

def record_parent_consent(student_id: int, consented_by: str, contact: str = "",
                            ip_address: str = "", notes: str = "",
                            consent_version: str = "v1",
                            db_path: str = DB_PATH) -> int:
    """Record parent consent for student data processing.

    consent_version：同意书版本号，政策变更后新记录携带新版本，
    便于审计「该学生同意的是哪一版条款」。
    """
    conn = get_connection(db_path)
    try:
        cur = conn.execute("""
            INSERT INTO parent_consents
                (student_id, consented_by, contact, ip_address, notes, consent_version)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [student_id, consented_by, contact, ip_address, notes, consent_version])
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def has_parent_consent(student_id: int, db_path: str = DB_PATH) -> bool:
    """Check if parent consent exists for a student（已撤回的同意不算数）。"""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT id FROM parent_consents "
            "WHERE student_id = ? AND withdrawn_at IS NULL LIMIT 1",
            [student_id]
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_students_without_consent(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Get active students without parent consent."""
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT s.* FROM students s
        WHERE s.status = 'active'
          AND NOT EXISTS (
              SELECT 1 FROM parent_consents pc WHERE pc.student_id = s.id
          )
        ORDER BY s.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def request_data_deletion(student_id: int, requested_by: str, reason: str = "",
                          db_path: str = DB_PATH) -> int:
    """Create a data deletion request."""
    conn = get_connection(db_path)
    cur = conn.execute("""
        INSERT INTO deletion_requests (student_id, requested_by, reason)
        VALUES (?, ?, ?)
    """, [student_id, requested_by, reason])
    conn.commit()
    conn.close()
    return cur.lastrowid


def process_data_deletion(request_id: int, db_path: str = DB_PATH) -> bool:
    """处理删除请求：硬删全部个人数据（PIPL），仅保留两类记录。

    保留：
    - payments：金额/日期/套餐留档（财务/税务要求），经匿名学生存根关联
    - deletion_requests：本行标记 completed 作审计轨迹
    其余从属数据（错题/任务/文件/画像/订阅等）连同磁盘上传目录一并删除；
    students 行保留无 PII 的匿名存根（status='deleted'）供对账外键不悬空。
    """
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT student_id FROM deletion_requests WHERE id = ?", [request_id]
        ).fetchone()
        if not row:
            return False
        student_id = row["student_id"]

        # 匿名化前先取手机号（sms_codes 按手机号关联，学生行稍后清空 PII）
        stu = conn.execute(
            "SELECT phone, parent_phone FROM students WHERE id = ?",
            [student_id]).fetchone()
        phones = {stu["phone"], stu["parent_phone"]} - {None, ""} if stu else set()

        # 题库题保留（可跨学生复用），仅切断对已删错题的引用
        conn.execute("""
            UPDATE questions SET source_mistake_id = NULL
            WHERE source_mistake_id IN (SELECT id FROM mistakes WHERE student_id = ?)
        """, [student_id])
        # 练习记录挂在错题下，先删
        conn.execute("""
            DELETE FROM practice_records WHERE mistake_id IN (
                SELECT id FROM mistakes WHERE student_id = ?)
        """, [student_id])
        # 任务从属表键在 task_id，先于 ai_tasks 删除（子查询依赖其行存在）
        conn.execute("""
            DELETE FROM llm_usage_log WHERE task_id IN (
                SELECT id FROM ai_tasks WHERE student_id = ?)
        """, [student_id])
        conn.execute("""
            DELETE FROM aigc_safety_checks WHERE task_id IN (
                SELECT id FROM ai_tasks WHERE student_id = ?)
        """, [student_id])
        # 其余按 FK 依赖顺序硬删（键均为 student_id）
        for table in (
            "mistakes", "practice_sessions",
            "ai_corrections", "ai_tasks",
            "files", "learning_plans", "plan_updates", "weekly_records",
            "score_history", "check_ins", "achievements",
            "metacognitive_reviews", "parent_consents",
            "subscriptions", "student_profiles",
            "cause_profiles", "cause_profile_history",
        ):
            conn.execute(f"DELETE FROM {table} WHERE student_id = ?", [student_id])
        # referrals 键为 referrer/referred 双向；sms_codes 按手机号关联
        conn.execute(
            "DELETE FROM referrals WHERE referrer_student_id = ? OR referred_student_id = ?",
            [student_id, student_id])
        for ph in phones:
            conn.execute("DELETE FROM sms_codes WHERE phone = ?", [ph])
        # 审计日志无 student_id 列：按 actor/target 关联清除含该学生的行
        conn.execute(
            "DELETE FROM audit_logs WHERE actor_id = ? OR target_id = ?",
            [str(student_id), str(student_id)])

        # 学生行 → 无 PII 匿名存根（保留 id 供 payments 外键与对账）
        conn.execute("""
            UPDATE students SET
                name = '已注销学生', grade = '', school_type = '',
                english_score = NULL, target_score = NULL,
                parent_name = NULL, parent_wechat = NULL, parent_phone = NULL,
                notes = NULL, phone = NULL, password_hash = NULL,
                gender = NULL, textbook_version = NULL, semester = NULL,
                school_id = NULL, class_id = NULL,
                status = 'deleted', access_code = NULL, parent_access_code = NULL
            WHERE id = ?
        """, [student_id])

        conn.execute(
            "UPDATE deletion_requests SET status = 'completed', processed_at = ? WHERE id = ?",
            [_now_iso(), request_id],
        )
        conn.commit()
    finally:
        conn.close()

    # 磁盘上传目录在 DB 提交后删除（尽力而为，失败不回滚）。
    # 与 web.shared.UPLOAD_DIR 同源：项目根/uploads（db 包比原 db.py 深一层，
    # 用 core.PROJECT_ROOT 定位；不依赖 db_path —— 测试库在临时目录时
    # 路径仍指向真实 uploads）。
    upload_dir = os.path.join(PROJECT_ROOT, "uploads", str(student_id))
    shutil.rmtree(upload_dir, ignore_errors=True)
    return True


def withdraw_parent_consent(student_id: int, withdrawn_by: str, reason: str = "",
                            db_path: str = DB_PATH) -> bool:
    """撤回监护人同意：所有有效同意记录标记 withdrawn_at（保留历史轨迹）。"""
    conn = get_connection(db_path)
    try:
        cur = conn.execute("""
            UPDATE parent_consents SET withdrawn_at = ?
            WHERE student_id = ? AND withdrawn_at IS NULL
        """, [_now_iso(), student_id])
        if reason:
            conn.execute("""
                UPDATE parent_consents SET notes = COALESCE(notes, '') || ?
                WHERE student_id = ? AND withdrawn_at IS NOT NULL
            """, [f"\n[撤回] {withdrawn_by}: {reason}", student_id])
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_pending_deletion_requests(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Get pending data deletion requests."""
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT dr.*, s.name as student_name
        FROM deletion_requests dr
        JOIN students s ON s.id = dr.student_id
        WHERE dr.status = 'pending'
        ORDER BY dr.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_safety_check(task_id: int, content_type: str,
                        content_snapshot: str = "",
                        db_path: str = DB_PATH) -> int:
    """Create an AIGC safety check record."""
    conn = get_connection(db_path)
    cur = conn.execute("""
        INSERT INTO aigc_safety_checks (task_id, content_type, content_snapshot)
        VALUES (?, ?, ?)
    """, [task_id, content_type, content_snapshot])
    conn.commit()
    conn.close()
    return cur.lastrowid


def review_safety_check(check_id: int, safety_status: str, issue_flags: List[str],
                        reviewed_by: str, db_path: str = DB_PATH) -> bool:
    """Review a safety check record."""
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT id FROM aigc_safety_checks WHERE id = ?", [check_id]
    ).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute("""
        UPDATE aigc_safety_checks
        SET safety_status = ?, issue_flags = ?, reviewed_by = ?, reviewed_at = ?
        WHERE id = ?
    """, [safety_status, json.dumps(issue_flags, ensure_ascii=False),
          reviewed_by, _now_iso(), check_id])
    conn.commit()
    conn.close()
    return True


def get_pending_safety_checks(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Get pending AIGC safety checks."""
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT sc.*, s.name as student_name, t.task_type
        FROM aigc_safety_checks sc
        JOIN ai_tasks t ON t.id = sc.task_id
        JOIN students s ON s.id = t.student_id
        WHERE sc.safety_status = 'pending'
        ORDER BY sc.created_at DESC
        LIMIT 50
    """).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["issue_flags"] = json.loads(d.get("issue_flags", "[]"))
        results.append(d)
    return results


def get_safety_check_stats(db_path: str = DB_PATH) -> Dict[str, Any]:
    """Get AIGC safety check statistics."""
    conn = get_connection(db_path)
    total = conn.execute("SELECT COUNT(*) FROM aigc_safety_checks").fetchone()[0]
    pending = conn.execute(
        "SELECT COUNT(*) FROM aigc_safety_checks WHERE safety_status = 'pending'"
    ).fetchone()[0]
    flagged = conn.execute(
        "SELECT COUNT(*) FROM aigc_safety_checks WHERE safety_status = 'flagged'"
    ).fetchone()[0]
    clean = conn.execute(
        "SELECT COUNT(*) FROM aigc_safety_checks WHERE safety_status = 'clean'"
    ).fetchone()[0]
    conn.close()
    return {
        "total_checks": total,
        "pending": pending,
        "flagged": flagged,
        "clean": clean,
    }

