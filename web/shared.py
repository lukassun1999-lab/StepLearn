#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web 共享层：装饰器、通用辅助与全局常量（P2-12 自 app.py 拆出）。"""

import functools
import os
import uuid

from flask import jsonify, redirect, request, session

from db import add_file, get_connection, is_feature_enabled
from pipeline_worker import enqueue_task

# app.py 位于项目根，web/ 在其下一层 → uploads 仍指向项目根/uploads
UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")

def _get_version():
    try:
        import subprocess
        return subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=os.path.dirname(__file__),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return 'dev'

def login_required(f):
    """Decorator: require user to be logged in."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            # API routes return 401, page routes redirect to login
            if request.path.startswith("/api/"):
                return jsonify({"error": "unauthorized", "login_url": "/login"}), 401
            return redirect("/login")
        return f(*args, **kwargs)
    return wrapper

def admin_required(f):
    """Decorator: require admin role."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"error": "unauthorized"}), 401
            return redirect("/login")
        if session.get("user_role") != "admin":
            if request.path.startswith("/api/"):
                return jsonify({"error": "forbidden", "message": "需要管理员权限"}), 403
            return "<h2>需要管理员权限</h2>", 403
        return f(*args, **kwargs)
    return wrapper

# P3-13：student_required 装饰器已删除（session 态学生端点全部移除）。

def feature_required(flag: str):
    """Decorator: return 404 if a feature flag is disabled."""
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if not is_feature_enabled(flag):
                if request.path.startswith("/api/"):
                    return jsonify({"error": "feature disabled"}), 404
                return "功能暂未开放", 404
            return f(*args, **kwargs)
        return wrapper
    return decorator

def _resolve_student_by_code(code):
    """Resolve student_id from access_code. Returns (student_id, error_response)."""
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM students WHERE access_code = ? AND status = 'active'", [code]
    ).fetchone()
    conn.close()
    if not row:
        return None, (jsonify({"error": "invalid or expired code"}), 404)
    return row["id"], None

def _extract_options(question_text):
    """Extract A/B/C/D options from question text if embedded."""
    import re
    options = re.findall(r'([A-D])\.\s*(.+?)(?=\s*[A-D]\.|$)', question_text)
    if len(options) >= 3:
        return [{"key": k, "text": v.strip()} for k, v in options]
    return []

def _save_uploaded_file(file, student_id: int, file_type: str, uploader_role: str) -> int:
    """Save a single uploaded file and return its file_id."""
    ext = os.path.splitext(file.filename)[1] or '.jpg'
    stored_name = f"{uuid.uuid4().hex}{ext}"
    student_dir = os.path.join(UPLOAD_DIR, str(student_id), file_type)
    os.makedirs(student_dir, exist_ok=True)
    filepath = os.path.join(student_dir, stored_name)
    file.save(filepath)
    return add_file(
        student_id=student_id, uploader_role=uploader_role,
        file_type=file_type, filename=stored_name,
        original_filename=file.filename,
        file_size=os.path.getsize(filepath),
        mime_type=file.content_type or '',
    )

def _count_retry_chain(task_id: int, db_path: str = None):
    """Count how many auto/parent retries led to this task."""
    from db import get_task, DB_PATH
    db_path = db_path or DB_PATH
    count = 0
    current_id = task_id
    seen = set()
    while current_id:
        if current_id in seen:
            break
        seen.add(current_id)
        task = get_task(current_id, db_path)
        if not task:
            break
        parent_id = task.get("parent_task_id")
        if parent_id:
            count += 1
            current_id = parent_id
        else:
            # Fallback to input_data retry_from
            input_data = task.get("input_data") or {}
            if isinstance(input_data, str):
                try:
                    import json
                    input_data = json.loads(input_data)
                except Exception:
                    input_data = {}
            current_id = input_data.get("retry_from")
            if current_id:
                count += 1
            else:
                break
    return count

def _build_correction_summary(items: list) -> str:
    """Build a concise teacher_notes string from structured corrections."""
    if not items:
        return ""
    lines = ["【老师纠错】"]
    for item in items:
        ct = item.get("content_type", "")
        field = item.get("target_field", "")
        corrected = item.get("corrected_value", "")
        if isinstance(corrected, (list, dict)):
            import json
            corrected = json.dumps(corrected, ensure_ascii=False)
        reason = item.get("reason", "").strip()
        line = f"- {ct}/{field} 应改为：{corrected}"
        if reason:
            line += f"（原因：{reason}）"
        lines.append(line)
    return "\n".join(lines)

def _enqueue_correction_rerun(task: dict, corrections: list,
                              db_path: str = None):
    """Create and enqueue a rerun task carrying correction hints.

    Returns the new task id, or None if retry limit reached.
    """
    from db import create_task, update_task, DB_PATH
    db_path = db_path or DB_PATH

    task_id = task["id"]
    if _count_retry_chain(task_id, db_path) >= 3:
        return None

    input_data = task.get("input_data") or {}
    if isinstance(input_data, str):
        try:
            import json
            input_data = json.loads(input_data)
        except Exception:
            input_data = {}

    # Merge prior teacher_notes with new correction summary
    prior_notes = input_data.get("teacher_notes", "")
    correction_notes = _build_correction_summary(corrections)
    combined_notes = "\n\n".join(filter(None, [prior_notes, correction_notes])).strip()

    rerun_input = dict(input_data)
    rerun_input["teacher_notes"] = combined_notes
    rerun_input["retry_from"] = task_id
    rerun_input["auto_retry"] = True
    rerun_input["corrections_summary"] = [
        {"content_type": c.get("content_type"),
         "target_field": c.get("target_field"),
         "corrected_value": c.get("corrected_value"),
         "reason": c.get("reason", "")}
        for c in corrections
    ]

    new_task_id = create_task(
        student_id=task["student_id"],
        task_type=task["task_type"],
        input_data=rerun_input,
        week_start=task.get("week_start"),
        db_path=db_path,
    )
    update_task(new_task_id, {"parent_task_id": task_id}, db_path=db_path)
    enqueue_task(new_task_id, db_path=db_path)
    return new_task_id


VERSION = _get_version()
