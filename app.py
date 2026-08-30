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
from werkzeug.middleware.proxy_fix import ProxyFix
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

# 反向代理后取真实客户端 IP：限流（web.shared._code_*）按 request.remote_addr
# 聚合，若不信任上游代理的 X-Forwarded-For，所有用户会坍缩成代理 IP（127.0.0.1），
# 6 次集体输错即全站封锁。仅在真有单层可信代理（如 nginx/gunicorn）时开启，
# 直连开发环境保持关闭，避免客户端伪造 XFF 绕过限流。
if os.environ.get("TRUST_PROXY_HEADERS") == "true":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# 注册蓝图（路由路径与拆分前完全一致）
app.register_blueprint(pages_bp)
app.register_blueprint(family_api_bp)
app.register_blueprint(ops_api_bp)
app.register_blueprint(b_end_bp)

# Register pipeline handlers + start worker
cycle_pipeline.register()
start_worker()


def _warn_demo_backend() -> None:
    """LLM 无 API key（demo 模式）时写运营告警 + 启动日志。

    静默降级曾导致：无 key 部署后所有 AI 产出均为占位数据而运营无感知。
    create_alert 自带等价活跃告警去重（重启不重复造）。
    """
    try:
        import llm
        if llm.BACKEND != "demo":
            return
        log.warning("LLM 后端为 demo 模式：未配置 API key，所有 AI 产出均为占位数据")
        from db import create_alert
        create_alert(
            alert_type="demo_mode", level="warning",
            message="LLM 未配置 API key，当前为演示模式：所有 AI 产出"
                    "（错题分析/练习/周报）均为占位数据，请在 .env 配置 "
                    "ANTHROPIC_API_KEY 或 LLM_API_KEY 后重启",
            related_id="total",
        )
    except Exception:
        log.warning("demo 模式告警写入失败", exc_info=True)


_warn_demo_backend()


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
    from datetime import timedelta, timezone

    def _fresh(ts, window):
        if ts is None:
            return False
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)  # DB 读出为 naive，按 UTC 解释
        return (now - ts) < window

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


def _cli_doctor():
    """运行体检: python app.py doctor
    检查 LLM 配置与连通性、OCR 依赖、数据库完整性、任务队列积压、
    备份新鲜度、磁盘空间与生产配置。返回退出码（0 正常 / 1 有异常项）。
    """
    import shutil
    import time as _time
    from datetime import datetime, timezone
    from db import PROJECT_ROOT

    counts = {"ok": 0, "warn": 0, "fail": 0}

    def _emit(level: str, msg: str) -> None:
        counts[level] += 1
        tag = {"ok": "[OK]  ", "warn": "[WARN]", "fail": "[FAIL]"}[level]
        print(f"  {tag} {msg}")

    print(f"拾阶而上 v{VERSION} 运行体检")
    print("=" * 60)

    # ── 1. LLM 配置与连通性 ──────────────────────────
    print("\n▶ LLM")
    import llm
    if llm.BACKEND == "demo":
        _emit("warn", "LLM 为 demo 模式：未配置 API key，所有 AI 产出均为占位数据")
        _emit("warn", "修复：在 .env 配置 ANTHROPIC_API_KEY 或 LLM_API_KEY 后重启")
    else:
        endpoint = llm.ANTHROPIC_BASE_URL if llm.BACKEND == "anthropic" else llm.LLM_BASE_URL
        _emit("ok", f"后端 {llm.BACKEND} · 文本模型 {llm.DEFAULT_MODEL} · "
                    f"视觉模型 {llm.VISION_MODEL}" + (f" · 端点 {endpoint}" if endpoint else ""))

        def _ping_llm():
            t0 = _time.time()
            try:
                if llm.BACKEND == "anthropic":
                    import anthropic
                    kwargs = dict(api_key=llm.ANTHROPIC_KEY)
                    if llm.ANTHROPIC_BASE_URL:
                        kwargs["base_url"] = llm.ANTHROPIC_BASE_URL
                    client = anthropic.Anthropic(**kwargs)
                    resp = client.messages.create(
                        model=llm.DEFAULT_MODEL, max_tokens=8, timeout=15,
                        messages=[{"role": "user", "content": "请只回复:OK"}])
                    reply = (resp.content[0].text or "").strip()
                else:
                    from openai import OpenAI
                    client = OpenAI(api_key=llm.LLM_API_KEY,
                                    base_url=llm.LLM_BASE_URL or None,
                                    timeout=15, max_retries=0)
                    resp = client.chat.completions.create(
                        model=llm.DEFAULT_MODEL, max_tokens=8, temperature=0,
                        messages=[{"role": "user", "content": "请只回复:OK"}])
                    reply = (resp.choices[0].message.content or "").strip()
                return True, f"{_time.time() - t0:.1f}s · 模型响应: {reply[:20]!r}"
            except Exception as e:
                return False, f"{_time.time() - t0:.1f}s · {type(e).__name__}: {str(e)[:120]}"

        net_ok, net_msg = _ping_llm()
        _emit("ok" if net_ok else "fail", f"API 连通性: {net_msg}")

    # ── 2. OCR 依赖 ─────────────────────────────────
    print("\n▶ OCR")
    _emit("ok", f"OCR_BACKEND={llm.OCR_BACKEND}（auto=vision 优先，Tesseract 兜底）")
    import glob
    traineddata = glob.glob(os.path.join(PROJECT_ROOT, "tessdata", "*.traineddata*"))
    if traineddata:
        langs = ", ".join(os.path.basename(p).split(".")[0] for p in sorted(traineddata))
        _emit("ok", f"Tesseract 语言包: {langs}")
    else:
        _emit("warn", "tessdata/ 下无语言包，Tesseract 兜底不可用")
    from skills_bridge import OCR_WRAPPER
    if os.path.exists(OCR_WRAPPER):
        _emit("ok", f"OCR 包装脚本存在: {os.path.basename(OCR_WRAPPER)}")
    else:
        _emit("fail", f"OCR 包装脚本缺失: {OCR_WRAPPER}")
    if llm.OCR_BACKEND in ("auto", "tesseract"):
        if shutil.which("node"):
            _emit("ok", "Node.js 可用（Tesseract.js 运行时）")
        else:
            _emit("warn", "未找到 node 命令，Tesseract.js 兜底将不可用"
                          "（仅 vision OCR 可用时影响有限）")

    # ── 2.5 PDF 导出字体 ─────────────────────────────
    print("\n▶ PDF 导出")
    import report_templates as _rt
    probe = next(_rt._iter_cjk_font_paths(), None)
    if probe is None:
        _emit("fail", "未找到任何可用 CJK 字体（自带 + 系统均无），"
                      "练习卷 PDF 中文将变占位字形（英文兜底版式）")
    else:
        source = "自带" if probe == _rt._BUNDLED_CJK_FONT else "系统"
        try:
            _rt._register_cjk_ttf("CJK-DoctorProbe", probe)
            _emit("ok", f"中文字体可注册（{source}）: {os.path.basename(probe)}")
        except Exception as e:
            _emit("fail", f"中文字体注册失败: {os.path.basename(probe)}（{e}）")

    # ── 3. 数据库 ───────────────────────────────────
    print("\n▶ 数据库")
    init_db()  # 幂等：建表 + 补迁移
    size_mb = os.path.getsize(DB_PATH) / 1048576
    _emit("ok", f"数据库 {DB_PATH} · {size_mb:.1f} MB")
    conn = get_connection()
    journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
    if str(journal).lower() == "wal":
        _emit("ok", "WAL 模式已启用")
    else:
        _emit("warn", f"journal_mode={journal}（预期 wal）")
    quick = conn.execute("PRAGMA quick_check").fetchone()[0]
    if str(quick).lower() == "ok":
        _emit("ok", "quick_check 通过（数据库完整性正常）")
    else:
        _emit("fail", f"quick_check 异常: {quick}（先用 backups/ 恢复，勿覆盖）")
    tables = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    _emit("ok", f"共 {tables} 张表")
    stuck = conn.execute(
        "SELECT COUNT(*) FROM ai_tasks WHERE status IN ('pending','processing') "
        "AND created_at < datetime('now', '-2 hours')").fetchone()[0]
    if stuck:
        _emit("warn", f"{stuck} 个任务 pending/processing 超过 2 小时"
                      "（服务未启动或 worker 僵尸；重启后自动复活/退额度）")
    else:
        _emit("ok", "任务队列无积压（无超 2 小时未完成任务）")
    failed_7d = conn.execute(
        "SELECT COUNT(*) FROM ai_tasks WHERE status='failed' "
        "AND created_at > datetime('now', '-7 days')").fetchone()[0]
    if failed_7d:
        _emit("warn", f"近 7 天 {failed_7d} 个任务失败（运营后台可查 error_message）")
    conn.close()

    # ── 4. 备份 ─────────────────────────────────────
    print("\n▶ 备份")
    daily_at, weekly_at = _latest_backup_times()
    now_utc = datetime.now(timezone.utc)
    if daily_at is None:
        _emit("warn", "尚无 daily 备份（首次启动 30 分钟内会自动执行）")
    else:
        age_h = (now_utc - _ensure_utc(daily_at)).total_seconds() / 3600
        if age_h > 48:
            _emit("warn", f"最近 daily 备份已是 {age_h:.0f} 小时前（服务是否在运行？）")
        else:
            _emit("ok", f"最近 daily 备份: {age_h:.1f} 小时前")
    if weekly_at is None:
        _emit("warn", "尚无 weekly 备份")
    else:
        age_d = (now_utc - _ensure_utc(weekly_at)).total_seconds() / 86400
        if age_d > 8:
            _emit("warn", f"最近 weekly 备份已是 {age_d:.0f} 天前")
        else:
            _emit("ok", f"最近 weekly 备份: {age_d:.1f} 天前")

    # ── 5. 磁盘与目录 ───────────────────────────────
    print("\n▶ 磁盘与目录")
    targets = [
        ("数据库所在盘", os.path.dirname(os.path.abspath(DB_PATH))),
        ("上传目录", UPLOAD_DIR),
    ]
    for label, path in targets:
        total, _used, free = shutil.disk_usage(path)
        free_gb = free / 2**30
        if free_gb < 1:
            _emit("fail", f"{label}剩余空间仅 {free_gb:.2f} GB（{path}）")
        elif free_gb < 5:
            _emit("warn", f"{label}剩余空间 {free_gb:.1f} GB，建议清理（{path}）")
        else:
            _emit("ok", f"{label}剩余空间 {free_gb:.1f} GB")
    for label, path in [
        ("上传目录", UPLOAD_DIR),
        ("日志目录", os.path.join(PROJECT_ROOT, "logs")),
        ("备份目录", os.path.join(PROJECT_ROOT, "backups")),
        ("LLM 缓存目录", llm.CACHE_DIR),
    ]:
        if not os.path.isdir(path):
            _emit("warn", f"{label}不存在: {path}")
            continue
        try:
            probe = os.path.join(path, ".doctor_probe")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
            _emit("ok", f"{label}可写: {path}")
        except Exception as e:
            _emit("fail", f"{label}不可写: {path}（{e}）")

    # ── 6. 生产配置 ─────────────────────────────────
    print("\n▶ 生产配置")
    if os.environ.get("FLASK_SECRET_KEY", "") in ("", "dev-secret-key-change-in-prod"):
        _emit("warn", "FLASK_SECRET_KEY 使用默认/空值，生产环境必须替换")
    else:
        _emit("ok", "FLASK_SECRET_KEY 已自定义")
    if os.environ.get("HTTPS_ENABLED") == "true":
        _emit("ok", "HTTPS_ENABLED=true（会话 cookie 已加固）")
    else:
        _emit("warn", "HTTPS_ENABLED 未开启（反代终结 TLS 后请置 true）")
    if os.environ.get("CONSENT_REQUIRED") == "true":
        _emit("ok", "CONSENT_REQUIRED=true（无监护人同意禁止上传）")
    else:
        _emit("warn", "CONSENT_REQUIRED 未开启（商用前建议开启，见 README 数据合规）")

    print("\n" + "=" * 60)
    print(f"体检完成: {counts['ok']} 项正常 · {counts['warn']} 项警告 · "
          f"{counts['fail']} 项异常")
    return 1 if counts["fail"] else 0


def _ensure_utc(dt):
    """backups.created_at 读出为 naive UTC，统一挂 UTC 时区用于差值计算。"""
    from datetime import timezone
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


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
    if len(sys.argv) > 1 and sys.argv[1] == 'doctor':
        sys.exit(_cli_doctor())

    init_db()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    import llm as _llm
    log.info('=' * 50)
    log.info('拾阶而上 · 管理系统 v%s', VERSION)
    log.info('http://localhost:5000')
    log.info('数据库: %s', DB_PATH)
    log.info('上传目录: %s', UPLOAD_DIR)
    log.info('LLM 缓存: %s', '开启' if os.environ.get('LLM_CACHE_ENABLED') == 'true' else '关闭')
    if _llm.BACKEND == 'demo':
        log.warning('⚠️  LLM: DEMO 模式 — 未配置 API key，所有 AI 产出均为占位数据')
    log.info('=' * 50)
    app.run(host='127.0.0.1', port=5000, debug=False)
