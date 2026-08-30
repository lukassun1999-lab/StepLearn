#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""学生与账号：学生 CRUD、画像、注册认证、学校班级、推荐裂变、教师档案、后台账号。

从 db.py 拆出（2026-08 第 3 周提交 5）；db 包门面继续对外提供全部符号。
"""

import json
import random
import secrets
import sqlite3
import string
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from db.core import DB_PATH, PRICING, _now_iso, get_connection
from db.operations import get_setting
from db.subscriptions import _subscription_status
# ═══════════════════════════════════════════════════
# Teacher / Institution Profile
# ═══════════════════════════════════════════════════

def get_teacher_profile(teacher_id: int = None, db_path: str = DB_PATH) -> Dict[str, Any]:
    """Return the profile for a specific teacher, or empty defaults."""
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM teacher_profile WHERE teacher_id = ?", [teacher_id]).fetchone()
    conn.close()
    if row:
        return dict(row)
    return {
        "teacher_id": teacher_id,
        "institution_name": "",
        "teacher_name": "",
        "avatar_filename": "",
        "teaching_years": "",
        "specialty": "",
        "philosophy": "",
        "contact_info": "",
    }


def save_teacher_profile(teacher_id: int, data: Dict[str, Any], db_path: str = DB_PATH) -> None:
    """Save teacher's institution profile."""
    conn = get_connection(db_path)
    conn.execute("""
        INSERT INTO teacher_profile (teacher_id, institution_name, teacher_name, avatar_filename,
                                     teaching_years, specialty, philosophy, contact_info)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(teacher_id) DO UPDATE SET
            institution_name = excluded.institution_name,
            teacher_name = excluded.teacher_name,
            avatar_filename = excluded.avatar_filename,
            teaching_years = excluded.teaching_years,
            specialty = excluded.specialty,
            philosophy = excluded.philosophy,
            contact_info = excluded.contact_info,
            updated_at = CURRENT_TIMESTAMP
    """, [teacher_id,
          data.get("institution_name", ""),
          data.get("teacher_name", ""),
          data.get("avatar_filename", "") or "",
          data.get("teaching_years", ""),
          data.get("specialty", ""),
          data.get("philosophy", ""),
          data.get("contact_info", ""),
    ])
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════
# Auth / Admin Users
# ═══════════════════════════════════════════════════

def create_admin_user(username: str, password_hash: str, role: str = "teacher",
                      subject: str = None, db_path: str = DB_PATH) -> int:
    """Create a new admin/teacher user. Returns user id."""
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO admin_users (username, password_hash, role, subject) VALUES (?, ?, ?, ?)",
            [username, password_hash, role, subject or '英语'],
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_admin_user(username: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Get admin user by username. Returns dict with id, username, password_hash, role."""
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT id, username, password_hash, role, created_at FROM admin_users WHERE username = ?",
        [username],
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_admin_users(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """List all admin/teacher users (without password_hash)."""
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT id, username, role, created_at FROM admin_users ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_admin_user(user_id: int, db_path: str = DB_PATH) -> bool:
    """Delete an admin user by id. Returns True if deleted."""
    conn = get_connection(db_path)
    cur = conn.execute("DELETE FROM admin_users WHERE id = ?", [user_id])
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


# ═══════════════════════════════════════════════════
# Referral / Viral Growth
# ═══════════════════════════════════════════════════

def _generate_referral_code(conn: sqlite3.Connection) -> str:
    """Generate a unique 8-character referral code."""
    import random
    import string
    for _ in range(100):
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        existing = conn.execute("SELECT id FROM referrals WHERE invite_code = ?", [code]).fetchone()
        if not existing:
            return code
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))


def get_or_create_referral_code(student_id: int, db_path: str = DB_PATH) -> str:
    """Get or create an invite code for a student. Returns invite_code."""
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT invite_code FROM referrals WHERE referrer_student_id = ? LIMIT 1",
        [student_id]
    ).fetchone()
    if row:
        conn.close()
        return row["invite_code"]

    code = _generate_referral_code(conn)
    conn.execute("""
        INSERT INTO referrals (referrer_student_id, invite_code, status)
        VALUES (?, ?, 'active')
    """, [student_id, code])
    conn.commit()
    conn.close()
    return code


def record_referral(invite_code: str, referred_student_id: int,
                    db_path: str = DB_PATH) -> bool:
    """Record that a new student was referred by invite_code."""
    conn = get_connection(db_path)
    ref = conn.execute(
        "SELECT * FROM referrals WHERE invite_code = ?",
        [invite_code]
    ).fetchone()
    if not ref:
        conn.close()
        return False
    if ref["referrer_student_id"] == referred_student_id:
        conn.close()
        return False  # cannot refer self
    if ref["referred_student_id"] is not None:
        # Code already used; create a new referral record for the same referrer
        pass

    reward_weeks = int(get_setting("referral_reward_weeks", db_path) or "1")
    if ref["referred_student_id"] is None:
        conn.execute("""
            UPDATE referrals
            SET referred_student_id = ?, reward_weeks = ?, status = 'converted'
            WHERE id = ?
        """, [referred_student_id, reward_weeks, ref["id"]])
    else:
        conn.execute("""
            INSERT INTO referrals (referrer_student_id, referred_student_id, invite_code, reward_weeks, status)
            VALUES (?, ?, ?, ?, 'converted')
        """, [ref["referrer_student_id"], referred_student_id, invite_code, reward_weeks])
    conn.commit()
    conn.close()
    return True


def get_student_referrals(student_id: int, db_path: str = DB_PATH) -> Dict[str, Any]:
    """Get referral info for a student."""
    conn = get_connection(db_path)
    invite_code = conn.execute(
        "SELECT invite_code FROM referrals WHERE referrer_student_id = ? LIMIT 1",
        [student_id]
    ).fetchone()

    rows = conn.execute("""
        SELECT r.*, s.name as referred_name
        FROM referrals r
        LEFT JOIN students s ON s.id = r.referred_student_id
        WHERE r.referrer_student_id = ? AND r.referred_student_id IS NOT NULL
        ORDER BY r.created_at DESC
    """, [student_id]).fetchall()

    conn.close()
    return {
        "invite_code": invite_code["invite_code"] if invite_code else None,
        "referrals": [dict(r) for r in rows],
        "converted_count": len(rows),
        "total_reward_weeks": sum(r["reward_weeks"] or 0 for r in rows),
    }


def get_referral_stats(db_path: str = DB_PATH) -> Dict[str, Any]:
    """Get overall referral stats."""
    conn = get_connection(db_path)
    total_invites = conn.execute("SELECT COUNT(DISTINCT invite_code) FROM referrals").fetchone()[0]
    total_converted = conn.execute(
        "SELECT COUNT(*) FROM referrals WHERE referred_student_id IS NOT NULL"
    ).fetchone()[0]
    total_reward_weeks = conn.execute(
        "SELECT COALESCE(SUM(reward_weeks), 0) FROM referrals WHERE referred_student_id IS NOT NULL"
    ).fetchone()[0]

    top_referrers = conn.execute("""
        SELECT s.name, COUNT(*) as count, SUM(r.reward_weeks) as weeks
        FROM referrals r
        JOIN students s ON s.id = r.referrer_student_id
        WHERE r.referred_student_id IS NOT NULL
        GROUP BY r.referrer_student_id
        ORDER BY count DESC
        LIMIT 10
    """).fetchall()

    conn.close()
    return {
        "total_invites": total_invites,
        "total_converted": total_converted,
        "conversion_rate": round(total_converted / max(total_invites, 1) * 100, 1),
        "total_reward_weeks": total_reward_weeks,
        "top_referrers": [dict(r) for r in top_referrers],
    }


def lookup_referrer_by_code(invite_code: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Find the referrer student by invite code."""
    conn = get_connection(db_path)
    row = conn.execute("""
        SELECT s.* FROM referrals r
        JOIN students s ON s.id = r.referrer_student_id
        WHERE r.invite_code = ?
        LIMIT 1
    """, [invite_code]).fetchone()
    conn.close()
    return dict(row) if row else None


# ═══════════════════════════════════════════════════
# Student Operations (保留原 app.py CRUD)
# ═══════════════════════════════════════════════════

def get_all_students(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT s.*, sub.plan, sub.status as sub_status, sub.end_date as sub_end_date,
               COALESCE(sub.plan, 'trial') as plan_label,
               COALESCE(stu_cost.cost, 0) as month_cost
        FROM students s
        LEFT JOIN subscriptions sub ON sub.student_id = s.id
        LEFT JOIN (
            SELECT t.student_id, SUM(l.estimated_cost) as cost
            FROM llm_usage_log l
            JOIN ai_tasks t ON t.id = l.task_id
            WHERE strftime('%Y-%m', l.created_at) = strftime('%Y-%m', 'now') AND l.cached = 0
            GROUP BY t.student_id
        ) stu_cost ON stu_cost.student_id = s.id
        WHERE s.status = 'active'
        ORDER BY s.name
    """).fetchall()
    conn.close()
    plan_labels = {p: info["label"] for p, info in PRICING.items()}
    results = []
    for r in rows:
        d = dict(r)
        plan = d.get("plan") or "trial"
        d["plan_label"] = plan_labels.get(plan, plan)
        # Auto-correct status based on date
        d["sub_status"] = _subscription_status(d.get("sub_end_date")) if d.get("sub_status") else "active"
        # Compute days remaining for easier frontend display
        end_date_str = d.get("sub_end_date")
        d["days_remaining"] = None
        if end_date_str:
            try:
                d["days_remaining"] = (date.fromisoformat(end_date_str) - date.today()).days
            except (ValueError, TypeError):
                pass
        results.append(d)
    return results


def get_student(student_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    row = conn.execute("""
        SELECT s.*, sub.plan, sub.status as sub_status
        FROM students s
        LEFT JOIN subscriptions sub ON sub.student_id = s.id
        WHERE s.id = ?
    """, [student_id]).fetchone()
    conn.close()
    return dict(row) if row else None


def create_student(data: Dict[str, Any], db_path: str = DB_PATH) -> int:
    conn = get_connection(db_path)
    cur = conn.execute("""
        INSERT INTO students (name, grade, school_type, english_score, target_score,
            parent_name, parent_wechat, parent_phone, notes, access_code, parent_access_code)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        data["name"], data.get("grade", "高二"), data.get("school_type", "住校"),
        data.get("english_score"), data.get("target_score"),
        data.get("parent_name"), data.get("parent_wechat"), data.get("parent_phone"),
        data.get("notes"),
        data.get("access_code") or _generate_access_code(conn, "students", "access_code"),
        data.get("parent_access_code") or _generate_access_code(conn, "students", "parent_access_code"),
    ])
    student_id = cur.lastrowid

    # Auto-create subscription（按 PRICING 填充额度，避免运行时建号额度为 0）
    plan = data.get("plan", "trial")
    if plan not in PRICING:
        plan = "trial"
    plan_info = PRICING[plan]
    # 付费套餐建号即计时；trial/unlimited 为一次性池，不设有效期
    end_date = None
    if plan in ("monthly", "yearly"):
        end_date = (date.today() + timedelta(days=30 if plan == "monthly" else 365)).isoformat()
    try:
        conn.execute("""
            INSERT INTO subscriptions
                (student_id, plan, monthly_quota, reset_month, start_date, end_date, status)
            VALUES (?, ?, ?, ?, date('now', 'localtime'), ?, 'active')
        """, [student_id, plan, plan_info["monthly_quota"],
              date.today().strftime("%Y-%m"), end_date])
        conn.commit()
    finally:
        conn.close()
    return student_id


def update_student(student_id: int, data: Dict[str, Any], db_path: str = DB_PATH) -> bool:
    conn = get_connection(db_path)
    try:
        conn.execute("""
            UPDATE students SET name=?, grade=?, school_type=?, english_score=?,
                target_score=?, parent_name=?, parent_wechat=?, parent_phone=?, notes=?
            WHERE id=?
        """, [
            data["name"], data.get("grade"), data.get("school_type"),
            data.get("english_score"), data.get("target_score"),
            data.get("parent_name"), data.get("parent_wechat"), data.get("parent_phone"),
            data.get("notes"), student_id
        ])
        plan = data.get("plan")
        if plan:
            if plan not in PRICING:
                plan = "trial"
            # UPSERT：只更新套餐与额度，保留 used_count/end_date/price/start_date，
            # 避免"改套餐 = 清空当月用量/变成永久有效"的老问题
            conn.execute("""
                INSERT INTO subscriptions
                    (student_id, plan, monthly_quota, reset_month, start_date, status)
                VALUES (?, ?, ?, ?,
                        COALESCE((SELECT start_date FROM subscriptions WHERE student_id=?), date('now', 'localtime')),
                        'active')
                ON CONFLICT(student_id) DO UPDATE SET
                    plan = excluded.plan,
                    monthly_quota = excluded.monthly_quota
            """, [student_id, plan, PRICING[plan]["monthly_quota"],
                  date.today().strftime("%Y-%m"), student_id])
        conn.commit()
    finally:
        conn.close()
    return True


def _generate_access_code(conn: sqlite3.Connection, table: str, column: str) -> str:
    """Generate a unique access code.

    加密随机 token_urlsafe(8)（约 11 位）：6 位数字仅 90 万空间且非加密随机，
    公开接口凭码即可读学生数据，可被暴力枚举（安全审查 P0）。存量 6 位码
    继续有效（仅影响新生成）。
    """
    import secrets
    for _ in range(100):
        code = secrets.token_urlsafe(8)
        existing = conn.execute(
            f"SELECT id FROM {table} WHERE {column} = ?", [code]
        ).fetchone()
        if not existing:
            return code
    raise RuntimeError("无法生成唯一 access_code")


# ═══════════════════════════════════════════════════
# Student Profile Operations (参考 chat.md 六大部分)
# ═══════════════════════════════════════════════════

def get_student_profile(student_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Get student profile (1:1 with students). Returns None if not created yet."""
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM student_profiles WHERE student_id = ?", [student_id]).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    json_fields = {
        "time_map", "assessments", "plan_choices", "recent_scores",
        "weak_question_types", "peak_energy_slots", "learning_style_detail",
    }
    for field in json_fields:
        try:
            d[field] = json.loads(d.get(field) or "{}")
        except Exception:
            d[field] = {}
    return d


def save_student_profile(student_id: int, data: Dict[str, Any], db_path: str = DB_PATH) -> None:
    """Create or update student profile."""
    conn = get_connection(db_path)

    json_fields = {
        "time_map", "assessments", "plan_choices", "recent_scores",
        "weak_question_types", "peak_energy_slots", "parent_task_progress",
        "learning_style_detail",
    }
    profile_fields = [
        "gender", "semester", "academic_goal", "subject_choice", "textbook_version",
        "time_map", "weekly_available_hours", "peak_energy_slots", "committed_english_minutes",
        "recent_scores", "weak_areas", "weak_question_types", "score_loss_reason",
        "confused_grammar", "existing_resources", "vocab_direction",
        "learning_style", "learning_style_detail", "learning_medium", "vocab_habit", "attention_weakness",
        "effective_methods", "ineffective_methods", "english_identity",
        "assessments",
        "target_timeline", "one_month_goal", "parent_availability",
        "supervision_needed", "study_environment",
        "least_favorite_task", "preferred_intensity", "aspirational_use",
        "plan_choices", "plan_name", "plan_code_name", "parent_task_progress",
    ]

    values = []
    for field in profile_fields:
        val = data.get(field)
        if field in json_fields and val is not None:
            if isinstance(val, str):
                val = val.strip()
                if not val:
                    val = None
                else:
                    try:
                        val = json.loads(val)
                    except Exception:
                        # For free-text fields that are meant to be JSON objects,
                        # wrap plain text so it round-trips.
                        if field == "time_map":
                            val = {"description": val}
            if val is not None:
                val = json.dumps(val, ensure_ascii=False)
        values.append(val)

    placeholders = ", ".join("?" for _ in profile_fields)
    columns = ", ".join(profile_fields)
    conn.execute(f"""
        INSERT INTO student_profiles (student_id, {columns}, updated_at)
        VALUES (?, {placeholders}, ?)
        ON CONFLICT(student_id) DO UPDATE SET
            {", ".join(f"{f} = excluded.{f}" for f in profile_fields)},
            updated_at = excluded.updated_at
    """, [student_id] + values + [_now_iso()])
    conn.commit()
    conn.close()


def has_student_profile(student_id: int, db_path: str = DB_PATH) -> bool:
    """Check if a student has a profile."""
    conn = get_connection(db_path)
    row = conn.execute("SELECT 1 FROM student_profiles WHERE student_id = ?", [student_id]).fetchone()
    conn.close()
    return row is not None


# ═══════════════════════════════════════════════════
# L3 学生长期记忆（跨月画像；月度总结刷新，方案生成消费）
# ═══════════════════════════════════════════════════

_MEMORY_JSON_FIELDS = ("recurring_causes", "effective_methods")


def get_student_memory(student_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Get the student's L3 long-term memory. Returns None if never generated."""
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM student_memory WHERE student_id = ?",
                       [student_id]).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for field in _MEMORY_JSON_FIELDS:
        try:
            d[field] = json.loads(d.get(field) or "[]")
        except Exception:
            d[field] = []
    return d


def save_student_memory(student_id: int, memory: Dict[str, Any],
                        db_path: str = DB_PATH) -> None:
    """Create or update the student's L3 long-term memory (upsert)."""
    conn = get_connection(db_path)
    conn.execute("""
        INSERT INTO student_memory (student_id, memory_summary, learner_type,
                                    recurring_causes, effective_methods,
                                    source_month, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(student_id) DO UPDATE SET
            memory_summary = excluded.memory_summary,
            learner_type = excluded.learner_type,
            recurring_causes = excluded.recurring_causes,
            effective_methods = excluded.effective_methods,
            source_month = excluded.source_month,
            updated_at = excluded.updated_at
    """, [
        student_id,
        memory.get("memory_summary", ""),
        memory.get("learner_type", ""),
        json.dumps(memory.get("recurring_causes") or [], ensure_ascii=False),
        json.dumps(memory.get("effective_methods") or [], ensure_ascii=False),
        memory.get("source_month"),
        _now_iso(),
    ])
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════
# Schools & Classes
# ═══════════════════════════════════════════════════

def create_school(name: str, aliases: List[str] = None, region: str = None,
                  db_path: str = DB_PATH) -> int:
    conn = get_connection(db_path)
    cur = conn.execute(
        "INSERT INTO schools (name, aliases, region) VALUES (?, ?, ?)",
        [name, json.dumps(aliases or [], ensure_ascii=False), region],
    )
    conn.commit()
    school_id = cur.lastrowid
    conn.close()
    return school_id


def get_school(school_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM schools WHERE id = ?", [school_id]).fetchone()
    conn.close()
    if row:
        d = dict(row)
        try:
            d["aliases"] = json.loads(d.get("aliases") or "[]")
        except (json.JSONDecodeError, TypeError):
            d["aliases"] = []
        return d
    return None


def search_schools(keyword: str, limit: int = 10, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Fuzzy search schools by name or aliases."""
    if not keyword or not keyword.strip():
        return []
    conn = get_connection(db_path)
    like = f"%{keyword.strip()}%"
    rows = conn.execute(
        "SELECT * FROM schools WHERE name LIKE ? OR aliases LIKE ? ORDER BY name LIMIT ?",
        [like, like, limit],
    ).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        try:
            d["aliases"] = json.loads(d.get("aliases") or "[]")
        except (json.JSONDecodeError, TypeError):
            d["aliases"] = []
        results.append(d)
    return results


def get_all_schools(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    rows = conn.execute("SELECT * FROM schools ORDER BY name").fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        try:
            d["aliases"] = json.loads(d.get("aliases") or "[]")
        except (json.JSONDecodeError, TypeError):
            d["aliases"] = []
        results.append(d)
    return results


def update_school(school_id: int, data: Dict[str, Any], db_path: str = DB_PATH) -> None:
    conn = get_connection(db_path)
    fields = []
    values = []
    for key in ("name", "region"):
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key])
    if "aliases" in data:
        fields.append("aliases = ?")
        values.append(json.dumps(data["aliases"], ensure_ascii=False))
    if fields:
        values.append(school_id)
        conn.execute(f"UPDATE schools SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
    conn.close()


def delete_school(school_id: int, db_path: str = DB_PATH) -> None:
    conn = get_connection(db_path)
    conn.execute("DELETE FROM schools WHERE id = ?", [school_id])
    conn.commit()
    conn.close()


def _generate_class_code(conn) -> str:
    """Generate a unique 6-digit class code."""
    import random
    for _ in range(100):
        code = f"{random.randint(100000, 999999)}"
        exists = conn.execute("SELECT 1 FROM classes WHERE class_code = ?", [code]).fetchone()
        if not exists:
            return code
    raise RuntimeError("Cannot generate unique class code")


def create_class(school_id: int, name: str, grade: str = None,
                 teacher_id: int = None, db_path: str = DB_PATH) -> Dict[str, Any]:
    conn = get_connection(db_path)
    class_code = _generate_class_code(conn)
    cur = conn.execute(
        "INSERT INTO classes (school_id, name, grade, teacher_id, class_code) VALUES (?, ?, ?, ?, ?)",
        [school_id, name, grade, teacher_id, class_code],
    )
    conn.commit()
    class_id = cur.lastrowid
    row = conn.execute("SELECT * FROM classes WHERE id = ?", [class_id]).fetchone()
    conn.close()
    return dict(row)


def get_class(class_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    row = conn.execute("""
        SELECT c.*, s.name as school_name
        FROM classes c
        JOIN schools s ON s.id = c.school_id
        WHERE c.id = ?
    """, [class_id]).fetchone()
    conn.close()
    return dict(row) if row else None


def get_class_by_code(class_code: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    row = conn.execute("""
        SELECT c.*, s.name as school_name
        FROM classes c
        JOIN schools s ON s.id = c.school_id
        WHERE c.class_code = ?
    """, [class_code]).fetchone()
    conn.close()
    return dict(row) if row else None


def get_classes_by_school(school_id: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT c.*, au.username as teacher_name
        FROM classes c
        LEFT JOIN admin_users au ON au.id = c.teacher_id
        WHERE c.school_id = ?
        ORDER BY c.name
    """, [school_id]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_classes_by_teacher(teacher_id: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT c.*, s.name as school_name
        FROM classes c
        JOIN schools s ON s.id = c.school_id
        WHERE c.teacher_id = ?
        ORDER BY s.name, c.name
    """, [teacher_id]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_class(class_id: int, data: Dict[str, Any], db_path: str = DB_PATH) -> None:
    conn = get_connection(db_path)
    fields = []
    values = []
    for key in ("name", "grade", "teacher_id"):
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key])
    if fields:
        values.append(class_id)
        conn.execute(f"UPDATE classes SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
    conn.close()


def delete_class(class_id: int, db_path: str = DB_PATH) -> None:
    conn = get_connection(db_path)
    conn.execute("UPDATE students SET class_id = NULL WHERE class_id = ?", [class_id])
    conn.execute("DELETE FROM classes WHERE id = ?", [class_id])
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════
# Student Registration & Auth
# ═══════════════════════════════════════════════════

def register_student(phone: str, password_hash: str, name: str,
                     school_id: int, class_id: int,
                     grade: str = None, textbook_version: str = None,
                     db_path: str = DB_PATH) -> int:
    """Register a new student account with phone login."""
    conn = get_connection(db_path)
    existing = conn.execute("SELECT id FROM students WHERE phone = ?", [phone]).fetchone()
    if existing:
        conn.close()
        raise ValueError("该手机号已注册")
    access_code = _generate_access_code(conn, "students", "access_code")
    parent_access_code = _generate_access_code(conn, "students", "parent_access_code")
    cur = conn.execute("""
        INSERT INTO students (name, grade, phone, password_hash, school_id, class_id,
                              access_code, parent_access_code, textbook_version, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
    """, [name, grade or "高二", phone, password_hash, school_id, class_id,
          access_code, parent_access_code, textbook_version])
    student_id = cur.lastrowid
    conn.execute(
        "INSERT INTO subscriptions (student_id, plan, start_date) VALUES (?, 'trial', ?)",
        [student_id, date.today().isoformat()],
    )
    conn.commit()
    conn.close()
    return student_id


def get_student_by_phone(phone: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    row = conn.execute("""
        SELECT s.*, sc.name as school_name, cl.name as class_name
        FROM students s
        LEFT JOIN schools sc ON sc.id = s.school_id
        LEFT JOIN classes cl ON cl.id = s.class_id
        WHERE s.phone = ? AND s.status = 'active'
    """, [phone]).fetchone()
    conn.close()
    return dict(row) if row else None


def get_students_by_class(class_id: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT s.id, s.name, s.grade, s.phone, s.english_score, s.target_score,
               s.access_code, s.created_at, s.status
        FROM students s
        WHERE s.class_id = ? AND s.status = 'active'
        ORDER BY s.name
    """, [class_id]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_students_by_teacher(teacher_id: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Get all students in classes assigned to a teacher.
    In C-end mode (no class), fall back to all active students."""
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT s.id, s.name, s.grade, s.phone, s.english_score, s.target_score,
               s.access_code, s.created_at, s.status,
               cl.name as class_name, sc.name as school_name
        FROM students s
        LEFT JOIN classes cl ON cl.id = s.class_id
        LEFT JOIN schools sc ON sc.id = cl.school_id
        WHERE (cl.teacher_id = ? OR s.class_id IS NULL) AND s.status = 'active'
        ORDER BY s.name
    """, [teacher_id]).fetchall()
    conn.close()
    return [dict(r) for r in rows]

