#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运营域：任务、文件、周记录、学习方案、纠错回路、审计、告警、备份、题库、LLM 用量与成本闸门。

从 db.py 拆出（2026-08 第 3 周提交 5）；db 包门面继续对外提供全部符号。
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from db.core import DB_PATH, _now_iso, get_connection, get_week_start

log = logging.getLogger(__name__)
# ═══════════════════════════════════════════════════
# AI Task Operations
# ═══════════════════════════════════════════════════

def create_task(student_id: int, task_type: str, input_data: Dict = None,
                week_start: str = None, total_steps: int = 7,
                db_path: str = DB_PATH) -> int:
    conn = get_connection(db_path)
    cur = conn.execute("""
        INSERT INTO ai_tasks (student_id, task_type, input_data, week_start, total_steps, status)
        VALUES (?, ?, ?, ?, ?, 'pending')
    """, [student_id, task_type, json.dumps(input_data or {}, ensure_ascii=False),
          week_start or get_week_start(), total_steps])
    conn.commit()
    conn.close()
    return cur.lastrowid


def get_task(task_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM ai_tasks WHERE id = ?", [task_id]).fetchone()
    conn.close()
    if row is None:
        return None
    d = dict(row)
    d["input_data"] = json.loads(d.get("input_data", "{}"))
    d["output_data"] = json.loads(d.get("output_data", "{}")) if d.get("output_data") else None
    return d


def update_task(task_id: int, updates: Dict[str, Any], db_path: str = DB_PATH) -> bool:
    if not updates:
        return False
    conn = get_connection(db_path)
    row = conn.execute("SELECT id FROM ai_tasks WHERE id = ?", [task_id]).fetchone()
    if not row:
        conn.close()
        return False
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values())
    conn.execute(f"UPDATE ai_tasks SET {set_clause} WHERE id = ?", values + [task_id])
    conn.commit()
    conn.close()
    return True


def mark_task_done(task_id: int, output_data: Dict = None,
                   db_path: str = DB_PATH) -> None:
    # P3-13：审核闸门移除，needs_review 恒 0（列保留以兼容历史数据）
    conn = get_connection(db_path)
    conn.execute("""
        UPDATE ai_tasks SET status = 'done', output_data = ?, needs_review = 0,
        progress = 100, completed_at = ?
        WHERE id = ?
    """, [json.dumps(output_data or {}, ensure_ascii=False), _now_iso(), task_id])
    conn.commit()
    conn.close()


def mark_task_failed(task_id: int, error_message: str, db_path: str = DB_PATH) -> None:
    conn = get_connection(db_path)
    conn.execute("""
        UPDATE ai_tasks SET status = 'failed', error_message = ?, completed_at = ?
        WHERE id = ?
    """, [error_message, _now_iso(), task_id])
    conn.commit()
    conn.close()


def update_task_progress(task_id: int, current_step: str, progress: int,
                         db_path: str = DB_PATH) -> None:
    conn = get_connection(db_path)
    conn.execute("""
        UPDATE ai_tasks SET status = 'processing', current_step = ?, progress = ?
        WHERE id = ?
    """, [current_step, progress, task_id])
    conn.commit()
    conn.close()


def get_pending_tasks(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT * FROM ai_tasks WHERE status = 'pending' ORDER BY created_at ASC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════
# File Operations
# ═══════════════════════════════════════════════════

def add_file(student_id: int, uploader_role: str, file_type: str,
             filename: str, original_filename: str, week_start: str = None,
             file_size: int = 0, mime_type: str = "",
             db_path: str = DB_PATH) -> int:
    conn = get_connection(db_path)
    cur = conn.execute("""
        INSERT INTO files (student_id, uploader_role, file_type, filename,
            original_filename, week_start, file_size, mime_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, [student_id, uploader_role, file_type, filename, original_filename,
          week_start or get_week_start(), file_size, mime_type])
    conn.commit()
    conn.close()
    return cur.lastrowid


def get_file(file_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM files WHERE id = ?", [file_id]).fetchone()
    conn.close()
    return dict(row) if row else None


def get_student_files(student_id: int, file_type: str = None,
                      db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    query = "SELECT * FROM files WHERE student_id = ?"
    params = [student_id]
    if file_type:
        query += " AND file_type = ?"
        params.append(file_type)
    query += " ORDER BY created_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════
# Weekly Records Operations
# ═══════════════════════════════════════════════════

def get_or_create_weekly_record(student_id: int, week_start: str = None,
                                kind: str = "weekly",
                                db_path: str = DB_PATH) -> Dict[str, Any]:
    """获取或创建 Cycle 记录（weekly_records 表，kind: weekly|diagnostic）。"""
    if week_start is None:
        week_start = get_week_start()
    conn = get_connection(db_path)
    row = conn.execute("""
        SELECT * FROM weekly_records
        WHERE student_id = ? AND week_start = ? AND kind = ?
    """, [student_id, week_start, kind]).fetchone()
    if not row:
        conn.execute("""
            INSERT OR IGNORE INTO weekly_records (student_id, week_start, kind)
            VALUES (?, ?, ?)
        """, [student_id, week_start, kind])
        conn.commit()
        row = conn.execute("""
            SELECT * FROM weekly_records
            WHERE student_id = ? AND week_start = ? AND kind = ?
        """, [student_id, week_start, kind]).fetchone()
    conn.close()
    return dict(row)


def update_weekly_record(student_id: int, week_start: str = None,
                         kind: str = "weekly", db_path: str = DB_PATH,
                         **fields) -> bool:
    if week_start is None:
        week_start = get_week_start()
    # ensure record exists
    get_or_create_weekly_record(student_id, week_start, kind, db_path)
    conn = get_connection(db_path)
    fields["updated_at"] = _now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values())
    conn.execute(f"""
        UPDATE weekly_records SET {set_clause}
        WHERE student_id = ? AND week_start = ? AND kind = ?
    """, values + [student_id, week_start, kind])
    conn.commit()
    conn.close()
    return True


# ═══════════════════════════════════════════════════
# Learning Plan Operations
# ═══════════════════════════════════════════════════

def save_learning_plan(student_id: int, plan_data: Dict, weak_point_matrix: List = None,
                       db_path: str = DB_PATH) -> None:
    conn = get_connection(db_path)
    conn.execute("""
        INSERT OR REPLACE INTO learning_plans (student_id, plan_data, weak_point_matrix, updated_at)
        VALUES (?, ?, ?, ?)
    """, [student_id, json.dumps(plan_data, ensure_ascii=False),
          json.dumps(weak_point_matrix or [], ensure_ascii=False), _now_iso()])
    conn.commit()
    conn.close()


def get_learning_plan(student_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM learning_plans WHERE student_id = ?",
                       [student_id]).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["plan_data"] = json.loads(d.get("plan_data", "{}"))
    d["weak_point_matrix"] = json.loads(d.get("weak_point_matrix", "[]"))
    return d


def add_plan_update(student_id: int, week_start: str, change_summary: Dict,
                    ai_clinic_content: str = "", db_path: str = DB_PATH) -> int:
    conn = get_connection(db_path)
    cur = conn.execute("""
        INSERT INTO plan_updates (student_id, week_start, change_summary, ai_clinic_content)
        VALUES (?, ?, ?, ?)
    """, [student_id, week_start, json.dumps(change_summary, ensure_ascii=False),
          ai_clinic_content])
    conn.commit()
    conn.close()
    return cur.lastrowid


# ═══════════════════════════════════════════════════
# AI Correction Operations
# ═══════════════════════════════════════════════════

def create_correction(
    task_id: int,
    student_id: int,
    content_type: str,
    target_field: str,
    corrected_value: Any,
    target_id: int = None,
    original_value: Any = None,
    reason: str = "",
    reviewed_by: str = "",
    apply: bool = True,
    db_path: str = DB_PATH,
) -> int:
    """Create an AI correction record and optionally apply it to the target table.

    Supported content_type / target_field combinations:
      - mistake: question, correct_answer, explanation, knowledge_points, difficulty, question_type
      - grading: is_correct, feedback
      - question: question_text, correct_answer, explanation, knowledge_points, difficulty, question_type
    """
    # Normalize values for storage
    if isinstance(corrected_value, (list, dict)):
        corrected_value = json.dumps(corrected_value, ensure_ascii=False)
    if original_value is not None and isinstance(original_value, (list, dict)):
        original_value = json.dumps(original_value, ensure_ascii=False)

    conn = get_connection(db_path)
    cur = conn.execute("""
        INSERT INTO ai_corrections
            (task_id, student_id, content_type, target_id, target_field,
             original_value, corrected_value, reason, reviewed_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        task_id, student_id, content_type, target_id, target_field,
        original_value, corrected_value, reason, reviewed_by,
    ])
    correction_id = cur.lastrowid
    conn.commit()
    conn.close()

    if apply:
        _apply_correction_to_target(
            correction_id=correction_id,
            content_type=content_type,
            target_id=target_id,
            target_field=target_field,
            corrected_value=corrected_value,
            db_path=db_path,
        )
        record_feedback_pattern(
            content_type=content_type,
            target_field=target_field,
            corrected_value=corrected_value,
            target_id=target_id,
            db_path=db_path,
        )
    return correction_id


def _apply_correction_to_target(
    correction_id: int,
    content_type: str,
    target_id: int,
    target_field: str,
    corrected_value: Any,
    db_path: str = DB_PATH,
) -> bool:
    """Apply a correction to its target record."""
    if not target_id:
        return False

    conn = get_connection(db_path)
    applied = False
    try:
        if content_type == "mistake":
            row = conn.execute(
                "SELECT * FROM mistakes WHERE id = ?", [target_id]
            ).fetchone()
            if row:
                updates = _build_correction_updates(
                    target_field=target_field,
                    corrected_value=corrected_value,
                    current_value=row[target_field] if target_field in row.keys() else None,
                )
                if updates:
                    set_clause = ", ".join(f"{k} = ?" for k in updates)
                    conn.execute(
                        f"UPDATE mistakes SET {set_clause}, last_reviewed_at = ? WHERE id = ?",
                        list(updates.values()) + [_now_iso(), target_id],
                    )
                    applied = True

        elif content_type == "question":
            # Map correction field names to question table column names
            field_map = {
                "question": "question_text",
                "question_text": "question_text",
                "correct_answer": "correct_answer",
                "explanation": "explanation",
                "knowledge_points": "knowledge_points",
                "difficulty": "difficulty",
                "question_type": "question_type",
            }
            col = field_map.get(target_field)
            if col:
                updates = _build_correction_updates(
                    target_field=target_field,
                    corrected_value=corrected_value,
                )
                if updates:
                    set_clause = ", ".join(f"{col} = ?" for col in updates.values())
                    # Actually build updates with mapped column names
                    mapped_updates = {}
                    for k, v in updates.items():
                        mapped_updates[field_map.get(k, k)] = v
                    set_clause = ", ".join(f"{k} = ?" for k in mapped_updates)
                    conn.execute(
                        f"UPDATE questions SET {set_clause} WHERE id = ?",
                        list(mapped_updates.values()) + [target_id],
                    )
                    applied = True

        elif content_type == "grading":
            pr = conn.execute(
                "SELECT * FROM practice_records WHERE id = ?", [target_id]
            ).fetchone()
            if pr:
                updates = {}
                if target_field == "is_correct":
                    updates["is_correct"] = 1 if str(corrected_value).lower() in ("1", "true", "yes", "对") else 0
                elif target_field == "feedback":
                    updates["feedback"] = corrected_value
                if updates:
                    set_clause = ", ".join(f"{k} = ?" for k in updates)
                    conn.execute(
                        f"UPDATE practice_records SET {set_clause} WHERE id = ?",
                        list(updates.values()) + [target_id],
                    )
                    # Recalculate mistake mastery based on full practice history
                    _recalculate_mistake_stats(pr["mistake_id"], conn)
                    applied = True

        if applied:
            conn.execute(
                "UPDATE ai_corrections SET status = 'applied' WHERE id = ?",
                [correction_id],
            )
        conn.commit()
    finally:
        conn.close()
    return applied


def _build_correction_updates(target_field: str, corrected_value: Any,
                              current_value: Any = None) -> Dict[str, Any]:
    """Convert correction field/value into a dict of column updates."""
    updates = {}
    if target_field in ("question", "question_text"):
        updates["question"] = corrected_value
    elif target_field == "correct_answer":
        updates["correct_answer"] = corrected_value
    elif target_field == "explanation":
        updates["explanation"] = corrected_value
    elif target_field == "knowledge_points":
        if isinstance(corrected_value, str):
            try:
                corrected_value = json.loads(corrected_value)
            except Exception:
                corrected_value = [v.strip() for v in corrected_value.split(",") if v.strip()]
        updates["knowledge_points"] = json.dumps(corrected_value or [], ensure_ascii=False)
    elif target_field == "difficulty":
        try:
            updates["difficulty"] = int(corrected_value)
        except Exception:
            updates["difficulty"] = current_value if current_value is not None else 2
    elif target_field == "question_type":
        updates["question_type"] = corrected_value
    return updates


def _recalculate_mistake_stats(mistake_id: int, conn: sqlite3.Connection) -> None:
    """Recalculate review_count, consecutive_correct and mastery_level
    for a mistake from its practice history.
    """
    rows = conn.execute(
        "SELECT is_correct FROM practice_records WHERE mistake_id = ? ORDER BY created_at ASC",
        [mistake_id],
    ).fetchall()
    review_count = len(rows)
    consecutive_correct = 0
    for r in rows:
        if r["is_correct"]:
            consecutive_correct += 1
        else:
            consecutive_correct = 0
    mastery_level = min(100, consecutive_correct * 34 + review_count * 5)
    conn.execute("""
        UPDATE mistakes
        SET review_count = ?, consecutive_correct = ?, mastery_level = ?, last_reviewed_at = ?
        WHERE id = ?
    """, [review_count, consecutive_correct, mastery_level, _now_iso(), mistake_id])


def get_correction(correction_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM ai_corrections WHERE id = ?", [correction_id]).fetchone()
    conn.close()
    if row is None:
        return None
    return _parse_correction_row(row)


def get_task_corrections(task_id: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM ai_corrections WHERE task_id = ? ORDER BY created_at DESC",
        [task_id],
    ).fetchall()
    conn.close()
    return [_parse_correction_row(r) for r in rows]


def get_student_corrections(student_id: int, limit: int = 50, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    rows = conn.execute(
        """SELECT c.*, s.name as student_name
           FROM ai_corrections c
           JOIN students s ON s.id = c.student_id
           WHERE c.student_id = ?
           ORDER BY c.created_at DESC LIMIT ?""",
        [student_id, limit],
    ).fetchall()
    conn.close()
    return [_parse_correction_row(r) for r in rows]


def _parse_correction_row(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    if d.get("target_field") == "knowledge_points" and isinstance(d.get("corrected_value"), str):
        try:
            d["corrected_value"] = json.loads(d["corrected_value"])
        except Exception:
            pass
    if d.get("target_field") == "knowledge_points" and isinstance(d.get("original_value"), str):
        try:
            d["original_value"] = json.loads(d["original_value"])
        except Exception:
            pass
    return d


def revert_correction(correction_id: int, db_path: str = DB_PATH) -> bool:
    """Revert a correction. Only mistakes/questions support value rollback;
    grading corrections require a new correction record instead of revert."""
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT * FROM ai_corrections WHERE id = ? AND status = 'applied'",
        [correction_id],
    ).fetchone()
    if not row:
        conn.close()
        return False

    content_type = row["content_type"]
    target_id = row["target_id"]
    target_field = row["target_field"]
    original_value = row["original_value"]

    try:
        if content_type in ("mistake", "question") and original_value is not None:
            updates = _build_correction_updates(target_field, original_value)
            if updates:
                if content_type == "mistake":
                    table = "mistakes"
                    pk = "id"
                else:
                    table = "questions"
                    pk = "id"
                    mapped_updates = {}
                    field_map = {
                        "question": "question_text",
                        "question_text": "question_text",
                        "correct_answer": "correct_answer",
                        "explanation": "explanation",
                        "knowledge_points": "knowledge_points",
                        "difficulty": "difficulty",
                        "question_type": "question_type",
                    }
                    for k, v in updates.items():
                        mapped_updates[field_map.get(k, k)] = v
                    updates = mapped_updates
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE {table} SET {set_clause} WHERE {pk} = ?",
                    list(updates.values()) + [target_id],
                )
        elif content_type == "grading" and target_id:
            # For grading, revert is not safe without original value snapshot;
            # mark as reverted but leave practice_records to be fixed by a new correction.
            pass

        conn.execute(
            "UPDATE ai_corrections SET status = 'reverted' WHERE id = ?",
            [correction_id],
        )
        conn.commit()
    finally:
        conn.close()
    return True


def record_feedback_pattern(
    content_type: str,
    target_field: str,
    corrected_value: Any,
    target_id: int = None,
    db_path: str = DB_PATH,
) -> None:
    """Aggregate a correction into the feedback pattern table for prompt enhancement."""
    issue_type_map = {
        "correct_answer": "wrong_answer",
        "is_correct": "wrong_grading",
        "explanation": "wrong_explanation",
        "knowledge_points": "wrong_knowledge_point",
        "question": "wrong_question",
        "question_text": "wrong_question",
        "question_type": "wrong_question",
        "difficulty": "wrong_difficulty",
    }
    issue_type = issue_type_map.get(target_field, "other")

    knowledge_point = ""
    if target_id and content_type == "mistake":
        from db.learning import get_mistake  # 惰性：避免 operations↔learning 环
        m = get_mistake(target_id, db_path)
        if m:
            kps = m.get("knowledge_points", [])
            if isinstance(kps, str):
                try:
                    kps = json.loads(kps)
                except Exception:
                    kps = []
            knowledge_point = kps[0] if kps else ""

    if isinstance(corrected_value, (list, dict)):
        corrected_value = json.dumps(corrected_value, ensure_ascii=False)

    conn = get_connection(db_path)
    existing = conn.execute(
        """SELECT id, occurrence_count FROM ai_feedback_patterns
           WHERE knowledge_point = ? AND content_type = ? AND issue_type = ?
             AND corrected_value = ?""",
        [knowledge_point, content_type, issue_type, corrected_value],
    ).fetchone()

    now = _now_iso()
    if existing:
        conn.execute(
            """UPDATE ai_feedback_patterns
               SET occurrence_count = occurrence_count + 1, last_seen_at = ?
               WHERE id = ?""",
            [now, existing["id"]],
        )
    else:
        conn.execute("""
            INSERT INTO ai_feedback_patterns
                (knowledge_point, content_type, issue_type, corrected_value, last_seen_at)
            VALUES (?, ?, ?, ?, ?)
        """, [knowledge_point, content_type, issue_type, corrected_value, now])
    conn.commit()
    conn.close()


def get_recent_correction_hints(
    knowledge_points: List[str],
    content_type: str,
    days: int = 30,
    limit: int = 5,
    db_path: str = DB_PATH,
) -> str:
    """Return a human-readable hint string of recent corrections relevant to the given
    knowledge points and content type. Empty string if none.
    """
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    conn = get_connection(db_path)
    if knowledge_points:
        placeholders = ",".join("?" for _ in knowledge_points)
        rows = conn.execute(f"""
            SELECT knowledge_point, issue_type, corrected_value, occurrence_count
            FROM ai_feedback_patterns
            WHERE knowledge_point IN ({placeholders})
              AND content_type = ?
              AND last_seen_at >= ?
            ORDER BY occurrence_count DESC, last_seen_at DESC
            LIMIT ?
        """, list(knowledge_points) + [content_type, since, limit]).fetchall()
    else:
        rows = conn.execute("""
            SELECT knowledge_point, issue_type, corrected_value, occurrence_count
            FROM ai_feedback_patterns
            WHERE content_type = ?
              AND last_seen_at >= ?
            ORDER BY occurrence_count DESC, last_seen_at DESC
            LIMIT ?
        """, [content_type, since, limit]).fetchall()
    conn.close()

    if not rows:
        return ""

    lines = ["【近期老师纠错参考，请特别注意避免同类问题】"]
    issue_labels = {
        "wrong_answer": "答案错误",
        "wrong_explanation": "解析错误",
        "wrong_knowledge_point": "知识点归类错误",
        "wrong_grading": "批改判定错误",
        "wrong_question": "题干错误",
        "wrong_difficulty": "难度不当",
        "other": "其他",
    }
    for r in rows:
        label = issue_labels.get(r["issue_type"], r["issue_type"])
        lines.append(
            f"- 知识点「{r['knowledge_point'] or '通用'}」{label}，"
            f"共出现 {r['occurrence_count']} 次；正确参考：{r['corrected_value']}"
        )
    return "\n".join(lines)


def get_correction_stats(days: int = 7, db_path: str = DB_PATH) -> Dict[str, Any]:
    """Return correction statistics for dashboard trend card."""
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    conn = get_connection(db_path)
    total = conn.execute(
        "SELECT COUNT(*) FROM ai_corrections WHERE created_at >= ?", [since]
    ).fetchone()[0]
    reverted = conn.execute(
        "SELECT COUNT(*) FROM ai_corrections WHERE created_at >= ? AND status = 'reverted'",
        [since],
    ).fetchone()[0]
    top_points = conn.execute("""
        SELECT m.knowledge_points, COUNT(*) as cnt
        FROM ai_corrections c
        LEFT JOIN mistakes m ON m.id = c.target_id AND c.content_type = 'mistake'
        WHERE c.created_at >= ?
        GROUP BY m.knowledge_points
        ORDER BY cnt DESC
        LIMIT 3
    """, [since]).fetchall()
    conn.close()

    # knowledge_points is JSON string; flatten first-level array
    point_counts: Dict[str, int] = {}
    for r in top_points:
        kps = r["knowledge_points"] or "[]"
        try:
            kps = json.loads(kps)
        except Exception:
            kps = []
        if kps and isinstance(kps, list):
            for p in kps:
                point_counts[p] = point_counts.get(p, 0) + r["cnt"]
    sorted_points = sorted(point_counts.items(), key=lambda x: x[1], reverse=True)[:3]

    return {
        "total": total,
        "reverted": reverted,
        "effective": total - reverted,
        "repeat_ratio": round((total - reverted) / total, 2) if total else 0.0,
        "top_knowledge_points": [{"point": p, "count": c} for p, c in sorted_points],
    }


def log_audit(actor_type: str, action: str, actor_id: str = None,
              target_type: str = None, target_id: str = None,
              details: Dict = None, ip_address: str = "",
              db_path: str = DB_PATH) -> int:
    """Write an audit log entry."""
    conn = get_connection(db_path)
    cur = conn.execute("""
        INSERT INTO audit_logs (actor_type, actor_id, action, target_type, target_id, details, ip_address)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, [actor_type, actor_id, action, target_type, target_id,
          json.dumps(details or {}, ensure_ascii=False), ip_address])
    conn.commit()
    conn.close()
    return cur.lastrowid


def get_audit_logs(limit: int = 100, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Get recent audit logs."""
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT * FROM audit_logs
        ORDER BY created_at DESC
        LIMIT ?
    """, [limit]).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        try:
            d["details"] = json.loads(d.get("details", "{}"))
        except Exception:
            d["details"] = {}
        results.append(d)
    return results


# ═══════════════════════════════════════════════════
# Observability: Task Failure Monitoring
# ═══════════════════════════════════════════════════

def get_task_failure_stats(days: int = 7, db_path: str = DB_PATH) -> Dict[str, Any]:
    """Return task failure/rejection statistics for the last N days."""
    conn = get_connection(db_path)
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")

    total = conn.execute(
        "SELECT COUNT(*) FROM ai_tasks WHERE created_at >= ?",
        [since]
    ).fetchone()[0]
    failed = conn.execute(
        "SELECT COUNT(*) FROM ai_tasks WHERE status = 'failed' AND created_at >= ?",
        [since]
    ).fetchone()[0]
    rejected = conn.execute(
        "SELECT COUNT(*) FROM ai_tasks WHERE status = 'rejected' AND created_at >= ?",
        [since]
    ).fetchone()[0]

    # Daily breakdown
    rows = conn.execute("""
        SELECT date(created_at) as day,
               COUNT(*) as total,
               SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
               SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected
        FROM ai_tasks
        WHERE created_at >= ?
        GROUP BY date(created_at)
        ORDER BY day DESC
    """, [since]).fetchall()
    daily = [dict(r) for r in rows]

    # By task type
    type_rows = conn.execute("""
        SELECT task_type,
               COUNT(*) as total,
               SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
               SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected
        FROM ai_tasks
        WHERE created_at >= ?
        GROUP BY task_type
    """, [since]).fetchall()
    by_type = [dict(r) for r in type_rows]

    conn.close()
    return {
        "days": days,
        "total": total,
        "failed": failed,
        "rejected": rejected,
        "failure_rate": round(failed / max(total, 1) * 100, 1),
        "daily_breakdown": daily,
        "by_type": by_type,
    }


def get_recent_failed_tasks(limit: int = 20, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Return recent failed tasks with student name and error message."""
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT t.id, t.student_id, t.task_type, t.status, t.error_message,
               t.created_at, t.completed_at, s.name as student_name
        FROM ai_tasks t
        JOIN students s ON s.id = t.student_id
        WHERE t.status IN ('failed', 'rejected')
        ORDER BY t.completed_at DESC NULLS LAST, t.created_at DESC
        LIMIT ?
    """, [limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════
# Observability: Audit Logs
# ═══════════════════════════════════════════════════

def get_audit_logs_filtered(
    limit: int = 100,
    offset: int = 0,
    actor_type: str = None,
    action: str = None,
    target_type: str = None,
    since: str = None,
    db_path: str = DB_PATH,
) -> List[Dict[str, Any]]:
    """Get audit logs with optional filters."""
    conn = get_connection(db_path)
    where = ["1=1"]
    params = []
    if actor_type:
        where.append("actor_type = ?")
        params.append(actor_type)
    if action:
        where.append("action = ?")
        params.append(action)
    if target_type:
        where.append("target_type = ?")
        params.append(target_type)
    if since:
        where.append("created_at >= ?")
        params.append(since)

    sql = f"""
        SELECT * FROM audit_logs
        WHERE {' AND '.join(where)}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """
    rows = conn.execute(sql, params + [limit, offset]).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        try:
            d["details"] = json.loads(d.get("details", "{}"))
        except Exception:
            d["details"] = {}
        results.append(d)
    return results


def get_audit_log_actions(db_path: str = DB_PATH) -> List[str]:
    """Return distinct actions in audit_logs for filter dropdown."""
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT DISTINCT action FROM audit_logs WHERE action IS NOT NULL ORDER BY action"
    ).fetchall()
    conn.close()
    return [r["action"] for r in rows]


# ═══════════════════════════════════════════════════
# Observability: Alerts
# ═══════════════════════════════════════════════════

def create_alert(
    alert_type: str,
    level: str,
    message: str,
    related_id: str = None,
    details: Dict = None,
    db_path: str = DB_PATH,
) -> int:
    """Create a new alert if an equivalent active one does not already exist."""
    conn = get_connection(db_path)
    existing = conn.execute("""
        SELECT id FROM alerts
        WHERE alert_type = ? AND level = ? AND related_id = ? AND dismissed = 0
    """, [alert_type, level, related_id or ""]).fetchone()
    if existing:
        conn.close()
        return existing["id"]

    cur = conn.execute("""
        INSERT INTO alerts (alert_type, level, message, related_id, details)
        VALUES (?, ?, ?, ?, ?)
    """, [alert_type, level, message, related_id or "",
          json.dumps(details or {}, ensure_ascii=False)])
    conn.commit()
    conn.close()
    return cur.lastrowid


def dismiss_alert(alert_id: int, db_path: str = DB_PATH) -> bool:
    """Dismiss an active alert."""
    conn = get_connection(db_path)
    row = conn.execute("SELECT id FROM alerts WHERE id = ? AND dismissed = 0", [alert_id]).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute(
        "UPDATE alerts SET dismissed = 1, dismissed_at = ? WHERE id = ?",
        [_now_iso(), alert_id],
    )
    conn.commit()
    conn.close()
    return True


def get_active_alerts(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Return all active (non-dismissed) alerts."""
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT * FROM alerts
        WHERE dismissed = 0
        ORDER BY created_at DESC
        LIMIT 50
    """).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        try:
            d["details"] = json.loads(d.get("details", "{}"))
        except Exception:
            d["details"] = {}
        results.append(d)
    return results


def get_cost_alert_status(db_path: str = DB_PATH) -> Dict[str, Any]:
    """Check cost budgets and return active/would-be alert status."""
    budgets = get_budgets(db_path)
    monthly_total_budget = budgets.get("monthly_total_budget", 100.0)
    monthly_student_budget = budgets.get("monthly_student_budget", 20.0)

    threshold_setting = get_setting("cost_alert_threshold_pct", db_path)
    threshold_pct = float(threshold_setting) if threshold_setting else 80.0
    threshold = threshold_pct / 100.0

    month_cost = get_llm_cost_this_month(db_path)
    alerts = []

    month_pct = round(month_cost / max(monthly_total_budget, 0.01) * 100, 1)
    if month_cost >= monthly_total_budget:
        alerts.append({
            "type": "cost_total",
            "level": "critical",
            "message": f"月度总成本 ${month_cost:.4f} 已超过预算 ${monthly_total_budget:.2f}",
            "current": month_cost,
            "threshold": monthly_total_budget,
            "pct": month_pct,
        })
    elif month_cost >= monthly_total_budget * threshold:
        alerts.append({
            "type": "cost_total",
            "level": "warning",
            "message": f"月度总成本已达预算的 {month_pct}% (${month_cost:.4f} / ${monthly_total_budget:.2f})",
            "current": month_cost,
            "threshold": monthly_total_budget,
            "pct": month_pct,
        })

    # Per-student checks (llm_usage_log has task_id, join ai_tasks for student_id)
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT t.student_id, SUM(l.estimated_cost) as cost
        FROM llm_usage_log l
        JOIN ai_tasks t ON t.id = l.task_id
        WHERE l.cached = 0
          AND strftime('%Y-%m', l.created_at) = strftime('%Y-%m', 'now')
        GROUP BY t.student_id
        HAVING cost >= ?
    """, [monthly_student_budget * threshold]).fetchall()
    conn.close()

    for r in rows:
        sid = r["student_id"]
        cost = r["cost"]
        pct = round(cost / max(monthly_student_budget, 0.01) * 100, 1)
        from db.students import get_student  # 惰性：避免 operations↔students 环
        student = get_student(sid, db_path)
        student_name = student["name"] if student else f"学生{sid}"
        if cost >= monthly_student_budget:
            alerts.append({
                "type": "cost_student",
                "level": "critical",
                "related_id": str(sid),
                "message": f"{student_name} 本月成本 ${cost:.4f} 已超过单人预算 ${monthly_student_budget:.2f}",
                "current": cost,
                "threshold": monthly_student_budget,
                "pct": pct,
            })
        else:
            alerts.append({
                "type": "cost_student",
                "level": "warning",
                "related_id": str(sid),
                "message": f"{student_name} 本月成本已达单人预算的 {pct}% (${cost:.4f} / ${monthly_student_budget:.2f})",
                "current": cost,
                "threshold": monthly_student_budget,
                "pct": pct,
            })

    return {
        "alerts": alerts,
        "monthly_pct": month_pct,
        "threshold_pct": threshold_pct,
        "any_alert": len(alerts) > 0,
        "month_cost": month_cost,
        "monthly_budget": monthly_total_budget,
    }


# ═══════════════════════════════════════════════════
# Observability: Backups
# ═══════════════════════════════════════════════════

def record_backup(backup_path: str, backup_type: str, file_size: int,
                  db_path: str = DB_PATH) -> int:
    """Record a backup in the backups table."""
    conn = get_connection(db_path)
    cur = conn.execute("""
        INSERT INTO backups (backup_path, backup_type, file_size)
        VALUES (?, ?, ?)
    """, [backup_path, backup_type, file_size])
    conn.commit()
    conn.close()
    return cur.lastrowid


def get_backups(limit: int = 50, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Return backup history."""
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT * FROM backups
        ORDER BY created_at DESC
        LIMIT ?
    """, [limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def cleanup_old_backups(daily_keep: int = 7, weekly_keep: int = 4,
                        db_path: str = DB_PATH) -> Dict[str, Any]:
    """Remove old backup files and records according to retention policy."""
    import os
    conn = get_connection(db_path)
    deleted = []

    for backup_type, keep in [("daily", daily_keep), ("weekly", weekly_keep)]:
        rows = conn.execute("""
            SELECT id, backup_path FROM backups
            WHERE backup_type = ?
            ORDER BY created_at DESC
        """, [backup_type]).fetchall()
        for row in rows[keep:]:
            path = row["backup_path"]
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
            conn.execute("DELETE FROM backups WHERE id = ?", [row["id"]])
            deleted.append(path)

    conn.commit()
    conn.close()
    return {"deleted_count": len(deleted), "deleted_paths": deleted}


# ═══════════════════════════════════════════════════
# Question Bank
# ═══════════════════════════════════════════════════

def save_question(question_data: Dict[str, Any], db_path: str = DB_PATH) -> int:
    """Save a question to the question bank. Returns question id."""
    conn = get_connection(db_path)
    cur = conn.execute("""
        INSERT INTO questions (question_text, question_type, correct_answer, explanation,
            knowledge_points, difficulty, source, source_mistake_id, usage_count, enabled)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 1)
    """, [
        question_data.get("question_text", ""),
        question_data.get("question_type", ""),
        question_data.get("correct_answer", ""),
        question_data.get("explanation", ""),
        json.dumps(question_data.get("knowledge_points", []), ensure_ascii=False),
        question_data.get("difficulty", 2),
        question_data.get("source", "llm"),
        question_data.get("source_mistake_id"),
    ])
    conn.commit()
    conn.close()
    return cur.lastrowid


def get_question(question_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM questions WHERE id = ?", [question_id]).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["knowledge_points"] = json.loads(d.get("knowledge_points", "[]"))
    return d


def get_questions(knowledge_point: str = None, question_type: str = None,
                  enabled_only: bool = True, limit: int = 100,
                  db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Get questions from bank with optional filters."""
    conn = get_connection(db_path)
    query = "SELECT * FROM questions WHERE 1=1"
    params = []
    if enabled_only:
        query += " AND enabled = 1"
    if question_type:
        query += " AND question_type = ?"
        params.append(question_type)
    if knowledge_point:
        query += " AND knowledge_points LIKE ?"
        params.append(f"%{knowledge_point}%")
    query += " ORDER BY usage_count DESC, created_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["knowledge_points"] = json.loads(d.get("knowledge_points", "[]"))
        results.append(d)
    return results


def find_similar_questions(knowledge_points: List[str], question_type: str = None,
                           difficulty: int = None, limit: int = 5,
                           db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Find questions matching any of the given knowledge points."""
    if not knowledge_points:
        return []
    conn = get_connection(db_path)

    # Build LIKE conditions for each knowledge point
    conditions = []
    params = []
    for kp in knowledge_points:
        conditions.append("knowledge_points LIKE ?")
        params.append(f"%{kp}%")

    query = f"SELECT * FROM questions WHERE enabled = 1 AND ({' OR '.join(conditions)})"
    if question_type:
        query += " AND question_type = ?"
        params.append(question_type)
    if difficulty is not None:
        query += " AND difficulty = ?"
        params.append(difficulty)
    query += " ORDER BY usage_count ASC, created_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["knowledge_points"] = json.loads(d.get("knowledge_points", "[]"))
        results.append(d)
    return results


def increment_question_usage(question_ids: List[int], db_path: str = DB_PATH) -> None:
    """Increment usage_count for used questions."""
    if not question_ids:
        return
    conn = get_connection(db_path)
    placeholders = ",".join("?" * len(question_ids))
    conn.execute(f"""
        UPDATE questions SET usage_count = usage_count + 1
        WHERE id IN ({placeholders})
    """, question_ids)
    conn.commit()
    conn.close()


def update_question(question_id: int, updates: Dict[str, Any],
                    db_path: str = DB_PATH) -> bool:
    """Update a question in the bank."""
    if not updates:
        return False
    allowed = {"question_text", "question_type", "correct_answer", "explanation",
               "knowledge_points", "difficulty", "enabled"}
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        return False

    if "knowledge_points" in filtered and isinstance(filtered["knowledge_points"], list):
        filtered["knowledge_points"] = json.dumps(filtered["knowledge_points"], ensure_ascii=False)

    conn = get_connection(db_path)
    row = conn.execute("SELECT id FROM questions WHERE id = ?", [question_id]).fetchone()
    if not row:
        conn.close()
        return False
    set_clause = ", ".join(f"{k} = ?" for k in filtered)
    conn.execute(f"UPDATE questions SET {set_clause} WHERE id = ?",
                 list(filtered.values()) + [question_id])
    conn.commit()
    conn.close()
    return True


def get_question_bank_stats(db_path: str = DB_PATH) -> Dict[str, Any]:
    """Get question bank statistics."""
    conn = get_connection(db_path)
    total = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    enabled = conn.execute("SELECT COUNT(*) FROM questions WHERE enabled = 1").fetchone()[0]
    used = conn.execute("SELECT COUNT(*) FROM questions WHERE usage_count > 0").fetchone()[0]
    total_usage = conn.execute("SELECT COALESCE(SUM(usage_count), 0) FROM questions").fetchone()[0]

    # Top knowledge points
    rows = conn.execute("SELECT knowledge_points FROM questions WHERE enabled = 1").fetchall()
    kp_counts: Dict[str, int] = {}
    for r in rows:
        for kp in json.loads(r["knowledge_points"] or "[]"):
            kp_counts[kp] = kp_counts.get(kp, 0) + 1
    top_kp = sorted(kp_counts.items(), key=lambda x: -x[1])[:10]

    conn.close()
    return {
        "total_questions": total,
        "enabled_questions": enabled,
        "used_questions": used,
        "total_usage": total_usage,
        "reuse_rate": round(used / max(total, 1) * 100, 1),
        "top_knowledge_points": [{"knowledge_point": kp, "count": c} for kp, c in top_kp],
    }


# ═══════════════════════════════════════════════════
# LLM Usage Logging
# ═══════════════════════════════════════════════════

def log_llm_usage(task_id: int = None, call_type: str = "", model: str = "",
                  prompt_tokens: int = 0, output_tokens: int = 0,
                  estimated_cost: float = 0.0, duration_ms: int = 0,
                  retry_count: int = 0, cached: int = 0,
                  db_path: str = DB_PATH) -> int:
    conn = get_connection(db_path)
    cur = conn.execute("""
        INSERT INTO llm_usage_log (task_id, call_type, model, prompt_tokens,
            output_tokens, estimated_cost, duration_ms, retry_count, cached)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [task_id, call_type, model, prompt_tokens, output_tokens,
          estimated_cost, duration_ms, retry_count, cached])
    conn.commit()
    conn.close()
    return cur.lastrowid


def get_llm_cost_today(db_path: str = DB_PATH) -> float:
    conn = get_connection(db_path)
    row = conn.execute("""
        SELECT COALESCE(SUM(estimated_cost), 0) FROM llm_usage_log
        WHERE date(created_at, 'localtime') = date('now', 'localtime') AND cached = 0
    """).fetchone()
    conn.close()
    return row[0]


def get_llm_cost_this_month(db_path: str = DB_PATH) -> float:
    conn = get_connection(db_path)
    row = conn.execute("""
        SELECT COALESCE(SUM(estimated_cost), 0) FROM llm_usage_log
        WHERE strftime('%Y-%m', created_at, 'localtime') = strftime('%Y-%m', 'now', 'localtime') AND cached = 0
    """).fetchone()
    conn.close()
    return row[0]


# ═══════════════════════════════════════════════════
# Cost Guard & Budgeting
# ═══════════════════════════════════════════════════

DEFAULT_BUDGETS = {
    "monthly_total_budget": "100.0",    # USD
    "monthly_student_budget": "20.0",   # USD per student
    # weekly_question_target 已于 2026-08-04 移除：练习题数量策略改为每错题 2 题、不设总量上限
}

FEATURE_FLAGS = {
    "feature_school_enabled": "false",
    "feature_teacher_enabled": "false",
}


def is_feature_enabled(key: str, db_path: str = DB_PATH) -> bool:
    val = get_setting(key, db_path)
    if val is None:
        val = FEATURE_FLAGS.get(key, "false")
    return str(val).lower() in ("true", "1", "yes")


def get_setting(key: str, db_path: str = DB_PATH) -> Optional[str]:
    conn = get_connection(db_path)
    row = conn.execute("SELECT value FROM settings WHERE key = ?", [key]).fetchone()
    conn.close()
    return row["value"] if row else DEFAULT_BUDGETS.get(key)


def set_setting(key: str, value: str, db_path: str = DB_PATH) -> None:
    conn = get_connection(db_path)
    conn.execute("""
        INSERT OR REPLACE INTO settings (key, value, updated_at)
        VALUES (?, ?, ?)
    """, [key, value, _now_iso()])
    conn.commit()
    conn.close()


def get_budgets(db_path: str = DB_PATH) -> Dict[str, float]:
    """Return current budget settings."""
    return {
        "monthly_total_budget": float(get_setting("monthly_total_budget", db_path) or "100.0"),
        "monthly_student_budget": float(get_setting("monthly_student_budget", db_path) or "20.0"),
    }


def get_student_llm_cost(student_id: int, period: str = "month", db_path: str = DB_PATH) -> float:
    """Get LLM cost for a specific student. period: 'month' | 'today' | 'total'."""
    conn = get_connection(db_path)
    if period == "today":
        row = conn.execute("""
            SELECT COALESCE(SUM(l.estimated_cost), 0)
            FROM llm_usage_log l
            JOIN ai_tasks t ON t.id = l.task_id
            WHERE t.student_id = ? AND date(l.created_at, 'localtime') = date('now', 'localtime') AND l.cached = 0
        """, [student_id]).fetchone()
    elif period == "month":
        row = conn.execute("""
            SELECT COALESCE(SUM(l.estimated_cost), 0)
            FROM llm_usage_log l
            JOIN ai_tasks t ON t.id = l.task_id
            WHERE t.student_id = ? AND strftime('%Y-%m', l.created_at, 'localtime') = strftime('%Y-%m', 'now', 'localtime') AND l.cached = 0
        """, [student_id]).fetchone()
    else:  # total
        row = conn.execute("""
            SELECT COALESCE(SUM(l.estimated_cost), 0)
            FROM llm_usage_log l
            JOIN ai_tasks t ON t.id = l.task_id
            WHERE t.student_id = ? AND l.cached = 0
        """, [student_id]).fetchone()
    conn.close()
    return row[0]


def get_llm_cost_breakdown(period: str = "month", db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Get cost grouped by student."""
    conn = get_connection(db_path)
    if period == "today":
        date_filter = "date(l.created_at, 'localtime') = date('now', 'localtime')"
    elif period == "month":
        date_filter = "strftime('%Y-%m', l.created_at, 'localtime') = strftime('%Y-%m', 'now', 'localtime')"
    else:
        date_filter = "1=1"

    rows = conn.execute(f"""
        SELECT s.id, s.name, s.grade,
               COALESCE(SUM(l.estimated_cost), 0) as cost,
               COUNT(l.id) as calls
        FROM students s
        LEFT JOIN ai_tasks t ON t.student_id = s.id
        LEFT JOIN llm_usage_log l ON l.task_id = t.id AND l.cached = 0 AND {date_filter}
        WHERE s.status = 'active'
        GROUP BY s.id
        ORDER BY cost DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def check_cost_budget(student_id: int, db_path: str = DB_PATH) -> Dict[str, Any]:
    """Check if a new task would exceed budget. Returns dict with allowed and reasons."""
    budgets = get_budgets(db_path)
    total_month = get_llm_cost_this_month(db_path)
    student_month = get_student_llm_cost(student_id, "month", db_path)

    allowed = True
    reasons = []

    if total_month >= budgets["monthly_total_budget"]:
        allowed = False
        reasons.append(
            f"月度总成本 ${total_month:.4f} 已达到预算 ${budgets['monthly_total_budget']:.2f}"
        )

    if student_month >= budgets["monthly_student_budget"]:
        allowed = False
        reasons.append(
            f"该学生本月成本 ${student_month:.4f} 已达到单人预算 ${budgets['monthly_student_budget']:.2f}"
        )

    return {
        "allowed": allowed,
        "reasons": reasons,
        "total_month": round(total_month, 6),
        "student_month": round(student_month, 6),
        "monthly_total_budget": budgets["monthly_total_budget"],
        "monthly_student_budget": budgets["monthly_student_budget"],
    }

