#!/usr/bin/env python3
"""拾阶而上 — Flask 应用装配层（P2-12 蓝图拆分）。

路由与模板已拆出：
- web/pages.py        页面蓝图（运营后台 + 登录注册 + 家庭端页面）
- api/family_api.py   家庭端 API 蓝图（学生/家长/公开页）
- api/ops_api.py      运营端 API 蓝图（管理后台全部接口）
- web/shared.py       装饰器与共享辅助
- web/templates_*.py  内联 HTML 模板

本文件只做装配：Flask 实例、蓝图注册、流水线注册、后台调度、CLI。
"""

import os
import sys
import threading

from dotenv import load_dotenv
load_dotenv()

from flask import Flask
from werkzeug.security import generate_password_hash

from db import (
    DB_PATH, init_db, get_connection,
    create_admin_user, get_admin_user, list_admin_users,
)
from pipeline_worker import start_worker
import pipeline.cycle_pipeline as cycle_pipeline  # P1: 统一流水线
from web.shared import UPLOAD_DIR, VERSION
from web.pages import pages_bp
from api.family_api import family_api_bp
from api.ops_api import ops_api_bp
from b_end.routes import b_end_bp  # P3-15：B 端封存层（feature flag 守卫）

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key-change-in-prod")
# 会话 cookie 加固 + 上传总量限制（单文件限制见 web.shared._validate_upload）
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=200 * 1024 * 1024,  # 15 张 × ~13MB 余量
)
if os.environ.get("HTTPS_ENABLED") == "true":
    app.config["SESSION_COOKIE_SECURE"] = True

# 注册蓝图（路由路径与拆分前完全一致）
app.register_blueprint(pages_bp)
app.register_blueprint(family_api_bp)
app.register_blueprint(ops_api_bp)
app.register_blueprint(b_end_bp)

# Register pipeline handlers + start worker
cycle_pipeline.register()
start_worker()


# ═══════════════════════════════════════════════════
# Backup Scheduler
# ═══════════════════════════════════════════════════

_backup_scheduler_started = False
_BACKUP_INTERVAL_SECS = 3600  # check every hour


def _backup_scheduler_loop():
    """Background scheduler: run daily/weekly backups at ~03:00."""
    import time
    from datetime import datetime

    while True:
        try:
            now = datetime.now()
            # Daily backup around 03:00
            if now.hour == 3 and now.minute < 10:
                import backup as backup_module
                backup_module.run_backup('daily')
                backup_module.auto_cleanup()
                # Sleep long enough to avoid duplicate run in the same window
                time.sleep(12 * 3600)
                continue
            # Weekly backup on Monday around 03:00
            if now.weekday() == 0 and now.hour == 3 and now.minute < 10:
                import backup as backup_module
                backup_module.run_backup('weekly')
                backup_module.auto_cleanup()
                time.sleep(12 * 3600)
                continue
        except Exception:
            pass
        time.sleep(_BACKUP_INTERVAL_SECS)


def start_backup_scheduler():
    """Start the backup scheduler thread (idempotent)."""
    global _backup_scheduler_started
    if _backup_scheduler_started:
        return
    t = threading.Thread(target=_backup_scheduler_loop, daemon=True,
                         name="backup-scheduler")
    t.start()
    _backup_scheduler_started = True


start_backup_scheduler()


# ═══════════════════════════════════════════════════
# CLI Helpers
# ═══════════════════════════════════════════════════

def _cli_create_user():
    """Create admin user from CLI: python app.py create-admin <username> <password> [role]"""
    if len(sys.argv) < 3:
        print("用法: python app.py create-admin <username> <password> [admin|teacher]")
        return
    username = sys.argv[2]
    password = sys.argv[3]
    role = sys.argv[4] if len(sys.argv) > 4 else "admin"
    if role not in ("admin", "teacher"):
        print(f"错误: role 必须是 admin 或 teacher，收到: {role}")
        return
    init_db()
    existing = get_admin_user(username)
    if existing:
        print(f"错误: 用户 '{username}' 已存在")
        return
    user_id = create_admin_user(username, generate_password_hash(password), role)
    print(f"[OK] 已创建用户: {username} (ID: {user_id}, 角色: {role})")


def _cli_list_users():
    """List all admin users from CLI: python app.py list-admins"""
    init_db()
    users = list_admin_users()
    if not users:
        print("暂无管理员/老师账号")
        return
    print(f"{'ID':<4} {'用户名':<20} {'角色':<10} {'创建时间'}")
    print("-" * 60)
    for u in users:
        print(f"{u['id']:<4} {u['username']:<20} {u['role']:<10} {u['created_at'][:10]}")


def _cli_reset_password():
    """Reset password from CLI: python app.py reset-password <username> <new_password>"""
    if len(sys.argv) < 4:
        print("用法: python app.py reset-password <username> <new_password>")
        return
    username = sys.argv[2]
    new_password = sys.argv[3]
    init_db()
    user = get_admin_user(username)
    if not user:
        print(f"错误: 用户 '{username}' 不存在")
        return
    conn = get_connection()
    conn.execute("UPDATE admin_users SET password_hash = ? WHERE username = ?",
                 [generate_password_hash(new_password), username])
    conn.commit()
    conn.close()
    print(f"[OK] 已重置用户 '{username}' 的密码")


def _cli_clear_students():
    """Clear all student data from CLI: python app.py clear-students"""
    if len(sys.argv) > 2 and sys.argv[2] != '--confirm':
        print("⚠️  此操作将删除所有学生数据，不可恢复！")
        print("   确认请执行: python app.py clear-students --confirm")
        return
    if len(sys.argv) <= 2 or sys.argv[2] != '--confirm':
        print("⚠️  此操作将删除所有学生数据，不可恢复！")
        print("   确认请执行: python app.py clear-students --confirm")
        return

    init_db()
    conn = get_connection()

    tables = [
        'llm_usage_log', 'practice_records', 'practice_sessions', 'aigc_safety_checks',
        'ai_corrections', 'ai_feedback_patterns',
        'mistakes', 'learning_plans', 'plan_updates',
        'weekly_records', 'payments', 'files', 'check_ins',
        'achievements', 'metacognitive_reviews', 'referrals',
        'parent_consents', 'deletion_requests', 'score_history',
        'subscriptions', 'student_profiles',
        'sms_codes', 'questions',
    ]
    for t in tables:
        conn.execute(f"DELETE FROM {t}")
        conn.commit()

    student_count = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DELETE FROM students")
    conn.execute("DELETE FROM audit_logs")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()
    conn.close()

    # Clear upload directory
    import shutil
    for item in os.listdir(UPLOAD_DIR):
        item_path = os.path.join(UPLOAD_DIR, item)
        try:
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)
            else:
                os.remove(item_path)
        except Exception:
            pass

    print(f"[OK] 已清除 {student_count} 个学生及所有关联数据")
    print(f"[OK] 已清空上传目录: {UPLOAD_DIR}")
    print("[OK] 保留: 管理员/教师账号、学校、班级数据")


def _cli_set_super():
    """Set a student as the unlimited super account:
    python app.py set-super <access_code>"""
    if len(sys.argv) < 3:
        print("用法: python app.py set-super <access_code>")
        return
    init_db()
    code = sys.argv[2]
    conn = get_connection()
    student = conn.execute(
        "SELECT s.id AS id, s.name AS name, sub.plan AS plan "
        "FROM students s LEFT JOIN subscriptions sub "
        "ON sub.student_id = s.id WHERE s.access_code = ? OR s.parent_access_code = ?",
        [code, code]).fetchone()
    if not student:
        conn.close()
        print(f"错误: 未找到 access_code 为 '{code}' 的学生（学生码/家长码均可）")
        return
    conn.execute("""
        INSERT INTO subscriptions (student_id, plan, monthly_quota, start_date, status)
        VALUES (?, 'unlimited', 999999, date('now'), 'active')
        ON CONFLICT(student_id) DO UPDATE SET
            plan = 'unlimited', monthly_quota = 999999, status = 'active',
            end_date = NULL
    """, [student["id"]])
    conn.commit()
    conn.close()
    print(f"[OK] 已将 '{student['name']}' (ID: {student['id']}) 设为超级账号（不限次数）")


# ═══════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'create-admin':
        _cli_create_user()
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == 'list-admins':
        _cli_list_users()
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == 'reset-password':
        _cli_reset_password()
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == 'set-super':
        _cli_set_super()
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == 'clear-students':
        _cli_clear_students()
        sys.exit(0)

    init_db()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    print('=' * 50)
    print('  拾阶而上 · 管理系统')
    print(f'  版本: {VERSION}')
    print('  http://localhost:5000')
    print(f'  数据库: {DB_PATH}')
    print(f'  上传目录: {UPLOAD_DIR}')
    print(f'  LLM 缓存: {"开启" if os.environ.get("LLM_CACHE_ENABLED") == "true" else "关闭"}')
    print('=' * 50)
    app.run(host='127.0.0.1', port=5000, debug=False)
