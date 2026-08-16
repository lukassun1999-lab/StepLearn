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

from log_setup import setup_logging
setup_logging()

import logging

from flask import Flask
from werkzeug.security import generate_password_hash

log = logging.getLogger(__name__)

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
_BACKUP_CHECK_SECS = 1800  # check every 30 min


def _should_run_backup(now, last_daily_at, last_weekly_at):
    """备份决策（纯函数，便于单测）：

    - daily：每天 03:00 后，且近 24h 内无 daily 备份 → 执行（全天补跑，
      不再限定 03:00-03:10 窗口——错过窗口即永久跳过是原实现的缺陷）
    - weekly：03:00 后且近 7 天无 weekly 备份 → 执行（7 天新鲜度窗口
      本身保证每周一次；原先 weekly 分支被 daily 分支遮蔽，属死代码）
    时间参数为 UTC datetime（backups.created_at 为 CURRENT_TIMESTAMP）。
    """
    from datetime import timedelta

    def _fresh(ts, window):
        return ts is not None and (now - ts) < window

    after_3am = now.hour >= 3
    run_daily = after_3am and not _fresh(last_daily_at, timedelta(hours=24))
    run_weekly = after_3am and not _fresh(last_weekly_at, timedelta(days=7))
    return run_daily, run_weekly


def _latest_backup_times(db_path=None):
    """从 backups 表读最近一次 daily / weekly 备份时间（UTC）。"""
    from datetime import datetime
    from db import get_connection, DB_PATH

    conn = get_connection(db_path or DB_PATH)
    rows = conn.execute(
        "SELECT backup_type, MAX(created_at) AS last_at FROM backups "
        "GROUP BY backup_type").fetchall()
    conn.close()
    result = {}
    for r in rows:
        try:
            result[r["backup_type"]] = datetime.fromisoformat(
                str(r["last_at"]).replace(" ", "T")[:19])
        except Exception:
            result[r["backup_type"]] = None
    return result.get("daily"), result.get("weekly")


def _backup_scheduler_loop():
    """Background scheduler: daily/weekly backups with DB-level dedup + catch-up."""
    import time
    from datetime import datetime, timezone

    while True:
        try:
            # backups.created_at 为 UTC；统一用 UTC 判断，避免本地时区偏差
            last_daily, last_weekly = _latest_backup_times()
            run_daily, run_weekly = _should_run_backup(
                datetime.now(timezone.utc), last_daily, last_weekly)
            if run_daily or run_weekly:
                import backup as backup_module
                if run_daily:
                    backup_module.run_backup('daily')
                if run_weekly:
                    backup_module.run_backup('weekly')
                backup_module.auto_cleanup()
        except Exception:
            log.exception("备份调度循环异常")
        time.sleep(_BACKUP_CHECK_SECS)


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
        VALUES (?, 'unlimited', 999999, date('now', 'localtime'), 'active')
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
    log.info('=' * 50)
    log.info('拾阶而上 · 管理系统 v%s', VERSION)
    log.info('http://localhost:5000')
    log.info('数据库: %s', DB_PATH)
    log.info('上传目录: %s', UPLOAD_DIR)
    log.info('LLM 缓存: %s', '开启' if os.environ.get('LLM_CACHE_ENABLED') == 'true' else '关闭')
    log.info('=' * 50)
    app.run(host='127.0.0.1', port=5000, debug=False)
