#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web 共享层：装饰器、通用辅助与全局常量（P2-12 自 app.py 拆出）。"""

import functools
import os
import threading
import time
import uuid
from typing import Optional

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

def staff_required(f):
    """Decorator: require an ops account (admin or teacher).

    学生登录态同样持有 session['user_id']，login_required 拦不住；
    运营端接口一律用本装饰器（或更严格的 admin_required）。
    """
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"error": "unauthorized", "login_url": "/login"}), 401
            return redirect("/login")
        if session.get("user_role") not in ("admin", "teacher"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "forbidden", "message": "需要运营账号权限"}), 403
            return "<h2>需要运营账号权限</h2>", 403
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
    """Resolve student_id from access_code. Returns (student_id, error_response).

    访问码暴力枚举防护：同一 IP 短时间内大量无效 code 查询 → 临时封禁
    （6 次失败 / 15 分钟滑动窗口，按 IP 聚合）。此函数是全部
    /api/public/<code>/* 端点的唯一 code 校验入口，封禁在此统一生效。
    单进程内存计数即可（多 worker 部署时需换共享存储）。
    """
    now = _now_s()
    # 封禁短路（纯读路径，不计数）——返回与"code 无效"完全一致的 404，
    # 不泄露"该 code 其实存在"的信息
    if _code_ip_blocked(now):
        return None, (jsonify({"error": "invalid or expired code"}), 404)
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM students WHERE access_code = ? AND status = 'active'", [code]
    ).fetchone()
    conn.close()
    if not row:
        _code_fail_rate_limit(now)
        return None, (jsonify({"error": "invalid or expired code"}), 404)
    # 命中即清零：正常用户偶尔输错几次后成功，不应被锁
    _code_clear_ip_failures()
    return row["id"], None


# ═══════════════════════════════════════════════════
# 访问码失败限流（滑动窗口，按 IP 聚合）
# ═══════════════════════════════════════════════════
# 按 IP 聚合而不是按 IP+code：攻击者换着 code 试也能被同一计数累计命中，
# 这正是暴力枚举防护的目的。纯读路径不加锁（最坏容忍并发下误判一次）。
_code_limit = {}          # ip -> [失败时间戳...]
_code_limit_lock = threading.Lock()
_CODE_MAX_FAILS = 6       # 窗口内失败达到该数即封锁（放行 5 次）
_CODE_WINDOW_S = 900      # 15 分钟


def _now_s() -> float:
    return time.monotonic()


def _code_fails(ip: str) -> list:
    return _code_limit.get(ip, ())


def _code_ip_blocked(now: float) -> bool:
    ip = request.remote_addr or "unknown"
    cutoff = now - _CODE_WINDOW_S
    return sum(1 for t in _code_fails(ip) if t > cutoff) >= _CODE_MAX_FAILS


def _code_fail_rate_limit(now: float) -> bool:
    """记录一次失败；返回是否已超限（True=应拒绝后续请求）。"""
    ip = request.remote_addr or "unknown"
    with _code_limit_lock:
        ts = list(_code_limit.get(ip, ()))
        cutoff = now - _CODE_WINDOW_S
        ts = [t for t in ts if t > cutoff]
        ts.append(now)
        _code_limit[ip] = ts
        if len(_code_limit) > 4096:  # 防内存无限增长：顺带清理过期 IP
            for k, v in list(_code_limit.items()):
                if not v or v[-1] <= cutoff:
                    del _code_limit[k]
    return len(ts) >= _CODE_MAX_FAILS


def _code_clear_ip_failures() -> None:
    ip = request.remote_addr or "unknown"
    with _code_limit_lock:
        _code_limit.pop(ip, None)


def _reset_code_rate_limit() -> None:
    """测试隔离：清空全部计数（conftest autouse 调用）。"""
    with _code_limit_lock:
        _code_limit.clear()

def _extract_options(question_text):
    """Extract A/B/C/D options from question text if embedded."""
    import re
    options = re.findall(r'([A-D])\.\s*(.+?)(?=\s*[A-D]\.|$)', question_text)
    if len(options) >= 3:
        return [{"key": k, "text": v.strip()} for k, v in options]
    return []


def _resolve_file_path(f):
    """解析文件磁盘路径，返回存在的路径或 None。

    兼容历史目录命名偏差：海报曾存于 <file_type>s（posters）目录，
    而 file_type 为 poster（单数）。
    """
    for d in (f["file_type"], f["file_type"] + "s"):
        p = os.path.join(UPLOAD_DIR, str(f["student_id"]), d, f["filename"])
        if os.path.exists(p):
            return p
    return None

# 上传白名单：扩展名（试卷照片/答题卡，OCR 流水线按图片处理）
ALLOWED_UPLOAD_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.heic', '.bmp', '.gif', '.pdf'}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 单文件 20MB
# file_type 兼作目录名，只允许小写字母/下划线（防路径穿越）
_ALLOWED_FILE_TYPES = {'test_paper', 'answer_sheet', 'exercise', 'report',
                       'poster', 'other'}


def _sanitize_file_type(file_type: str) -> str:
    ft = (file_type or 'other').strip().lower()
    if ft in _ALLOWED_FILE_TYPES:
        return ft
    import re
    if re.fullmatch(r'[a-z_]{1,32}', ft):
        return ft
    return 'other'


def _validate_upload(file) -> Optional[str]:
    """返回错误信息（str）或 None（通过）。"""
    if not file or not file.filename:
        return "缺少文件"
    ext = os.path.splitext(file.filename)[1].lower()
    if ext and ext not in ALLOWED_UPLOAD_EXTS:
        return f"不支持的文件类型: {ext}（仅支持图片/PDF）"
    # 读取前先看 content_length（若提供）；否则读流校验大小
    if file.content_length and file.content_length > MAX_UPLOAD_BYTES:
        return "文件超过 20MB 限制"
    return None


def _save_uploaded_file(file, student_id: int, file_type: str, uploader_role: str) -> int:
    """Save a single uploaded file and return its file_id."""
    err = _validate_upload(file)
    if err:
        raise ValueError(err)
    ext = os.path.splitext(file.filename)[1].lower() or '.jpg'
    stored_name = f"{uuid.uuid4().hex}{ext}"
    student_dir = os.path.join(UPLOAD_DIR, str(student_id), _sanitize_file_type(file_type))
    os.makedirs(student_dir, exist_ok=True)
    filepath = os.path.join(student_dir, stored_name)
    file.save(filepath)
    if os.path.getsize(filepath) > MAX_UPLOAD_BYTES:
        os.remove(filepath)
        raise ValueError("文件超过 20MB 限制")
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
