#!/usr/bin/env python3
"""
拾阶而上 — AI 驱动管理系统
Flask 主应用：路由 + 前端页面 + Pipeline 触发
"""

import json
import os
import uuid
import functools
import sys
import threading
from datetime import date, timedelta

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, request, jsonify, render_template_string, send_file, send_from_directory, session, redirect
from werkzeug.security import generate_password_hash, check_password_hash

from db import (
    init_db, get_connection, get_week_start,
    get_all_students, get_student, create_student, update_student,
    get_student_profile, save_student_profile, has_student_profile,
    get_dashboard_stats, get_subscription, save_subscription,
    get_subscription_summary, record_payment, get_payments, PRICING,
    get_or_create_weekly_record, update_weekly_record,
    get_weekly_stats, get_learning_plan, save_learning_plan,
    add_plan_update, get_student_files, add_file, get_file,
    create_task, get_task, get_llm_cost_today, get_llm_cost_this_month,
    get_llm_cost_breakdown, get_student_llm_cost, get_budgets, check_cost_budget,
    set_setting, get_setting, is_feature_enabled,
    record_score, get_score_history, get_student_learning_stats, get_class_learning_stats,
    record_check_in, get_check_ins, get_check_in_calendar,
    get_student_mistake_book, mark_mistake_mastered, get_student_public_summary,
    get_questions, get_question, save_question, update_question, get_question_bank_stats,
    get_teacher_workload_stats,
    get_teacher_profile, save_teacher_profile,
    get_or_create_referral_code, record_referral, get_student_referrals,
    get_referral_stats, lookup_referrer_by_code,
    record_parent_consent, has_parent_consent, get_students_without_consent,
    request_data_deletion, process_data_deletion, get_pending_deletion_requests,
    create_safety_check, review_safety_check, get_pending_safety_checks,
    get_safety_check_stats, log_audit, get_audit_logs, get_operations_stats,
    get_audit_logs_filtered, get_audit_log_actions,
    get_task_failure_stats, get_recent_failed_tasks,
    create_alert, dismiss_alert, get_active_alerts, get_cost_alert_status,
    record_backup, get_backups,
    create_correction, get_task_corrections, revert_correction, get_correction_stats,
    create_admin_user, get_admin_user, list_admin_users, delete_admin_user,
    get_remaining_quota, check_quota, consume_quota,
    search_schools, get_all_schools, create_school, update_school, delete_school, get_school,
    get_classes_by_school, get_classes_by_teacher, create_class, get_class,
    get_class_by_code, update_class, delete_class, get_class_stats,
    register_student, get_student_by_phone, get_students_by_class, get_students_by_teacher,
    DB_PATH,
)
from pipeline_worker import enqueue_task, start_worker
import onboarding_pipeline  # registers the real handler, replacing stub
import weekly_pipeline

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key-change-in-prod")
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")

# Register pipeline handlers + start worker
onboarding_pipeline.register()
weekly_pipeline.register()
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
# Auth Helpers
# ═══════════════════════════════════════════════════

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


def student_required(f):
    """Decorator: require student role (phone-registered student account)."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session or session.get("user_role") != "student":
            if request.path.startswith("/api/"):
                return jsonify({"error": "unauthorized", "login_url": "/login"}), 401
            return redirect("/login")
        return f(*args, **kwargs)
    return wrapper


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

# ═══════════════════════════════════════════════════
# HTML Frontend
# ═══════════════════════════════════════════════════

MAIN_PAGE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>拾阶而上 · 管理系统</title>
<style>
:root {
  --bg: #f8f7f4; --bg-alt: #f1f0ec; --card: #fff;
  --text: #1a1a1a; --text-alt: #37352f; --sub: #6b6b6b; --mute: #9b9b9b;
  --accent: #e07b4b; --accent-hover: #d06a3a; --accent-light: #fef3ed;
  --green: #0f7b4e; --green-light: #effaf3;
  --red: #d93a46; --red-light: #fef4f4;
  --blue: #4b8dc7; --blue-light: #eef5fb;
  --border: #e8e6e1; --shadow-sm: 0 1px 2px rgba(0,0,0,.03);
  --shadow: 0 1px 3px rgba(0,0,0,.06), 0 2px 8px rgba(0,0,0,.02);
  --shadow-lg: 0 4px 24px rgba(0,0,0,.08);
  --radius: 8px;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; background:var(--bg); color:var(--text-alt); line-height:1.6; font-size:.875rem; }
.header { background:var(--card); border-bottom:1px solid var(--border); padding:0 20px; display:flex; align-items:center; height:56px; }
.header h1 { font-size:1.1rem; color:var(--accent); margin-right:auto; font-weight:700; }
.nav { display:flex; gap:2px; overflow-x:auto; -webkit-overflow-scrolling:touch; flex:1; margin:0 12px; }
.nav button { padding:8px 14px; border:none; background:none; border-radius:6px; cursor:pointer; font-size:.8rem; color:var(--sub); white-space:nowrap; transition:all .15s; }
.nav button:hover { background:var(--bg-alt); color:var(--text); }
.nav button.active { background:var(--accent-light); color:var(--accent); font-weight:600; }
.main { max-width:1200px; margin:0 auto; padding:24px 20px; }
.page { display:none; }
.page.active { display:block; }
h2 { font-size:1.15rem; font-weight:600; line-height:1.4; margin-bottom:16px; border-left:3px solid var(--accent); padding-left:12px; color:var(--text); }
.stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:16px; margin-bottom:24px; }
.stat { background:var(--card); border:none; border-radius:10px; padding:20px; box-shadow:var(--shadow); transition:box-shadow .2s; }
.stat:hover { box-shadow:var(--shadow-lg); }
.stat .num { font-size:1.6rem; font-weight:700; color:var(--text); }
.stat .label { font-size:.75rem; color:var(--sub); margin-top:4px; }
.stat.warn .num { color:var(--red); }
.stat.ok .num { color:var(--green); }
.stat.info .num { color:var(--blue); }
table { width:100%; border-collapse:collapse; background:var(--card); border-radius:10px; overflow:hidden; box-shadow:var(--shadow); }
th { background:var(--bg-alt); padding:10px 14px; text-align:left; font-size:.8rem; color:var(--sub); font-weight:600; }
td { padding:10px 14px; border-bottom:1px solid var(--border); font-size:.85rem; color:var(--text-alt); }
tr:last-child td { border-bottom:none; }
.badge { display:inline-block; padding:3px 10px; border-radius:100px; font-size:.75rem; font-weight:600; }
.badge-trial { background:var(--blue-light); color:var(--blue); }
.badge-active { background:var(--green-light); color:var(--green); }
.badge-expired { background:var(--red-light); color:var(--red); }
.badge-paused { background:var(--bg-alt); color:var(--sub); }
.badge-expiring { background:var(--accent-light); color:var(--accent); }
.form-group { margin-bottom:16px; }
.form-group label { display:block; font-size:.8rem; color:var(--sub); margin-bottom:4px; font-weight:600; }
.form-group input, .form-group select, .form-group textarea {
  width:100%; padding:8px 12px; border:1px solid var(--border); border-radius:var(--radius); font-size:.875rem;
  font-family:inherit; background:var(--card); transition:border-color .15s, box-shadow .15s; line-height:1.5;
}
.form-group input:focus, .form-group select:focus, .form-group textarea:focus {
  border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-light); outline:none;
}
.form-group textarea { resize:vertical; min-height:60px; }
.form-row { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
@media (max-width:640px) { .form-row { grid-template-columns:1fr; } }
.btn { padding:8px 20px; border:none; border-radius:var(--radius); cursor:pointer; font-size:.875rem; font-weight:600; transition:all .15s ease; min-height:36px; }
.btn:hover { transform:translateY(-1px); box-shadow:var(--shadow); }
.btn-primary { background:var(--accent); color:#fff; }
.btn-primary:hover { background:var(--accent-hover); }
.btn-green { background:var(--green); color:#fff; }
.btn-outline { background:var(--card); border:1px solid var(--border); color:var(--text); }
.btn-outline:hover { background:var(--bg-alt); border-color:var(--accent); }
.btn-sm { padding:4px 12px; font-size:.8rem; }
.btn-group { display:flex; gap:8px; margin-top:16px; }
.modal-overlay { display:none; position:fixed; top:0;left:0;right:0;bottom:0; background:rgba(0,0,0,.25); backdrop-filter:blur(4px); -webkit-backdrop-filter:blur(4px); z-index:100; align-items:center; justify-content:center; animation:fadeIn .2s ease; }
.modal-overlay.show { display:flex; }
.modal { background:var(--card); border-radius:12px; padding:28px; max-width:560px; width:90%; max-height:80vh; overflow-y:auto; box-shadow:var(--shadow-lg); animation:modalEnter .25s ease; }
.modal h3 { margin-bottom:16px; }
.progress-bar { width:100%; height:8px; background:var(--border); border-radius:100px; overflow:hidden; margin:12px 0; }
.progress-bar .fill { height:100%; background:var(--accent); border-radius:100px; transition:width .3s ease; }
.step-list { margin:12px 0; }
.step-item { padding:8px 12px; margin:4px 0; border-radius:var(--radius); font-size:.85rem; display:flex; align-items:center; gap:8px; }
.step-item.done { background:var(--green-light); color:var(--green); }
.step-item.current { background:var(--accent-light); color:var(--accent); font-weight:600; }
.step-item.pending { background:var(--bg); color:var(--sub); }
.spinner { display:inline-block; width:16px; height:16px; border:2px solid var(--border); border-top:2px solid var(--accent); border-radius:50%; animation:spin 1s linear infinite; }
@keyframes spin { to { transform:rotate(360deg); } }
@keyframes fadeIn { from{opacity:0;} to{opacity:1;} }
@keyframes modalEnter { from{opacity:0;transform:scale(.95) translateY(8px);} to{opacity:1;transform:scale(1) translateY(0);} }
.review-badge { background:var(--red); color:#fff; border-radius:100px; padding:1px 8px; font-size:.7rem; font-weight:700; }
.toast { position:fixed; top:20px; right:20px; padding:12px 20px; border-radius:var(--radius); color:#fff; font-size:.875rem; z-index:200; box-shadow:var(--shadow-lg); animation:fadeIn .3s ease; }
.toast-success { background:var(--green); }
.toast-error { background:var(--red); }
.card { background:var(--card); border:none; border-radius:10px; padding:20px; box-shadow:var(--shadow); margin-bottom:16px; }
.table-wrap { overflow-x:auto; -webkit-overflow-scrolling:touch; }
</style>
</head>
<body>

<div class="header">
  <h1>🏠 拾阶而上</h1>
  <div class="nav">
    <button onclick="switchPage('dashboard')" class="active" data-page="dashboard">概览</button>
    <button onclick="switchPage('students')" data-page="students">学生</button>
    {% if feature_school %}
    <button onclick="switchPage('classes')" data-page="classes">班级管理</button>
    {% endif %}
    <button onclick="switchPage('onboard')" data-page="onboard">入学诊断</button>
    <button onclick="switchPage('weekly')" data-page="weekly">周度服务</button>
    <button onclick="switchPage('analytics')" data-page="analytics">学情看板</button>
    <button onclick="switchPage('bank')" data-page="bank">题库</button>
    <button onclick="switchPage('quality')" data-page="quality">质量抽检</button>
    <button onclick="switchPage('referrals')" data-page="referrals">邀请统计</button>
    <button onclick="switchPage('compliance')" data-page="compliance">合规</button>
    {% if feature_teacher %}
    <button onclick="switchPage('teacher-profile')" data-page="teacher-profile">机构介绍</button>
    {% endif %}
    {% if user_role == 'admin' %}
    <button onclick="switchPage('admin')" data-page="admin">账号管理</button>
    <button onclick="switchPage('observability')" data-page="observability">系统监控</button>
    {% endif %}
  </div>
  <div style="display:flex;align-items:center;gap:12px;margin-left:auto;">
    <span style="font-size:.85em;color:var(--sub);">
      <span style="background:var(--accent-light);color:var(--accent);padding:2px 8px;border-radius:10px;font-size:.75em;font-weight:600;">{% if user_role == 'admin' %}管理员{% else %}老师{% endif %}</span>
      <span id="user-name">{{user_name}}</span>
      {% if user_subject %}<span style="color:var(--blue);font-size:.8em;font-weight:600;margin-left:2px;">{{user_subject}}</span>{% endif %}
    </span>
    <form method="POST" action="/logout" style="display:inline;">
      <button type="submit" class="btn btn-sm btn-outline">退出</button>
    </form>
  </div>
</div>

<script>window.CURRENT_USER_ROLE = "{{user_role}}";</script>

<div class="main">

<!-- ══════ DASHBOARD ══════ -->
<div id="page-dashboard" class="page active">
  <div class="stats" id="stats-bar"></div>

  <!-- Active alerts banner -->
  <div id="dashboard-alert-banner" style="margin-bottom:16px;"></div>

  <!-- Recent failures quick tip -->
  <div id="dashboard-failure-tip" style="margin-bottom:16px; display:none;">
    <div style="background:var(--red-light);color:var(--red);padding:10px 12px;border-radius:6px;font-size:.9em;display:flex;justify-content:space-between;align-items:center;">
      <span id="dashboard-failure-text"></span>
      <button class="btn btn-sm btn-outline" onclick="switchPage('observability')" style="margin-left:12px;">查看详情</button>
    </div>
  </div>

  <!-- Compliance alerts -->
  <div id="dashboard-compliance-banner" style="margin-bottom:16px;"></div>

  <h2>⚠️ 待审核 <span id="review-count" class="review-badge" style="display:none"></span></h2>
  <div style="display:flex;gap:8px;margin-bottom:12px;">
    <button class="btn btn-sm btn-green" onclick="batchApprove()">✅ 批量通过</button>
    <button class="btn btn-sm btn-outline" onclick="batchReject()" style="color:var(--red);">🔁 批量驳回重跑</button>
    <span style="margin-left:auto;font-size:.85em;color:var(--sub);align-self:center;">
      已选 <span id="selected-count">0</span> 项
    </span>
  </div>
  <table id="review-table" style="margin-bottom:24px;">
    <thead><tr><th><input type="checkbox" id="select-all" onclick="toggleSelectAll()"></th><th>学生</th><th>任务类型</th><th>完成时间</th><th>操作</th></tr></thead>
    <tbody></tbody>
  </table>

  {% if feature_school %}
  <h2>👩‍🏫 老师工作台</h2>
  <div class="stats" id="teacher-workload" style="margin-bottom:16px;"></div>

  <h3 style="font-size:1em;margin:16px 0 8px;">⏳ 待上传试卷学生</h3>
  <table id="pending-paper-table" style="margin-bottom:24px;">
    <thead><tr><th>学生</th><th>年级</th><th>操作</th></tr></thead>
    <tbody></tbody>
  </table>
  {% endif %}

  <h2>🧠 AI 纠错趋势（近7天）</h2>
  <div class="stats" id="correction-trend" style="margin-bottom:24px;">
    <div class="stat"><div class="num">-</div><div class="label">纠错总数</div></div>
  </div>

  <h2>⚠️ 订阅/续费提醒</h2>
  <table id="expiring-table" style="margin-bottom:24px;">
    <thead><tr><th>学生</th><th>年级</th><th>套餐</th><th>到期日</th><th>剩余天数</th><th>操作</th></tr></thead>
    <tbody></tbody>
  </table>

  <h2>本周状态</h2>
  <table id="pending-table">
    <thead><tr>
      <th>学生</th><th>年级</th><th>套餐</th><th>试卷提交</th><th>分析完成</th><th>练习题</th><th>批改</th><th>周报</th><th>操作</th>
    </tr></thead>
    <tbody></tbody>
  </table>
  <p style="margin-top:12px;color:var(--sub);font-size:.85em;" id="week-label"></p>

  {% if user_role == 'admin' %}
  <h2 style="margin-top:24px;">💰 API 成本与预算</h2>
  <div class="card" style="margin-bottom:16px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
      <span style="font-size:.85em;color:var(--sub);">本月总成本 / 月度预算</span>
      <span style="font-size:.85em;font-weight:600;" id="budget-text">-</span>
    </div>
    <div class="progress-bar" style="margin:8px 0;"><div class="fill" id="budget-bar" style="width:0%;background:var(--green);"></div></div>
    <p style="font-size:.85em;color:var(--sub);">今日: $<span id="cost-today">-</span> | 本月: $<span id="cost-month">-</span> | 单人月度预算: $<span id="student-budget">-</span></p>
    <div class="form-row" style="margin-top:12px;">
      <div class="form-group" style="margin-bottom:0;"><label style="font-size:.8em;">月度总预算 (USD)</label><input id="budget-total" type="number" step="1" placeholder="100"></div>
      <div class="form-group" style="margin-bottom:0;"><label style="font-size:.8em;">单人月度预算 (USD)</label><input id="budget-student" type="number" step="1" placeholder="20"></div>
    </div>
    <button class="btn btn-sm btn-primary" style="margin-top:8px;" onclick="saveBudget()">保存预算设置</button>
  </div>

  <table id="cost-breakdown-table" style="margin-bottom:24px;">
    <thead><tr><th>学生</th><th>本月调用次数</th><th>本月成本 (USD)</th><th>占单人预算</th></tr></thead>
    <tbody></tbody>
  </table>
  {% endif %}

  <h2 style="margin-top:24px;">🔧 系统状态</h2>
  <div class="card" id="system-status-card" style="margin-bottom:16px;">
    <p style="font-size:.85em;color:var(--sub);">加载中...</p>
  </div>
</div>

<!-- ══════ STUDENTS ══════ -->
<div id="page-students" class="page">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
    <h2 style="margin:0;">学生列表</h2>
    <button class="btn btn-primary" onclick="openStudentModal()">+ 添加学生</button>
  </div>
  <div style="display:flex;gap:12px;align-items:center;margin-bottom:12px;flex-wrap:wrap;">
    <select id="filter-plan" onchange="loadStudents()" style="padding:6px 10px;border-radius:6px;border:1px solid var(--border);font-size:.85em;background:#fff;">
      <option value="">全部套餐</option>
      <option value="trial">体验</option>
      <option value="basic">基础版</option>
      <option value="premium">托管版</option>
    </select>
    <select id="filter-status" onchange="loadStudents()" style="padding:6px 10px;border-radius:6px;border:1px solid var(--border);font-size:.85em;background:#fff;">
      <option value="">全部状态</option>
      <option value="active">有效</option>
      <option value="expired">已过期</option>
      <option value="soon">即将到期（7天内）</option>
    </select>
    <select id="sort-by" onchange="loadStudents()" style="padding:6px 10px;border-radius:6px;border:1px solid var(--border);font-size:.85em;background:#fff;">
      <option value="name">按姓名排序</option>
      <option value="days_remaining">按到期时间排序</option>
      <option value="plan">按套餐排序</option>
    </select>
  </div>
  <table id="students-table">
    <thead><tr>
      <th>姓名</th><th>年级</th><th>类型</th><th>英语分</th><th>目标分</th><th>套餐</th><th>有效期</th><th>状态</th><th>授权</th><th>本月AI成本</th><th>操作</th>
    </tr></thead>
    <tbody></tbody>
  </table>
</div>

<!-- ══════ ONBOARDING ══════ -->
<div id="page-onboard" class="page">
  <h2>新学生入学诊断</h2>
  <p style="color:var(--sub);margin-bottom:16px;">上传学生首张英语试卷 + 基本信息，AI 自动生成首次诊断报告和学习方案。</p>
  <div class="card" style="margin-bottom:24px;">
    <h3>第一步：填写基本信息</h3>
    <div class="form-row">
      <div class="form-group"><label>姓名 *</label><input id="onb-name"></div>
      <div class="form-group"><label>年级</label><select id="onb-grade"><option>高一</option><option selected>高二</option><option>高三</option></select></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>性别</label><select id="onb-gender"><option value="">请选择</option><option>男</option><option>女</option></select></div>
      <div class="form-group"><label>住校/走读</label><select id="onb-school-type"><option selected>住校</option><option>走读</option></select></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>最近英语分数</label><input id="onb-score" type="number" step="0.5"></div>
      <div class="form-group"><label>目标分数</label><input id="onb-target" type="number" step="0.5"></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>套餐</label><select id="onb-plan"><option value="trial" selected>体验（免费）</option><option value="basic">基础版 ¥99/月</option><option value="premium">托管版 ¥299/月</option></select></div>
      <div class="form-group"><label>家长电话</label><input id="onb-parent-phone"></div>
    </div>
    <div class="form-group" style="display:flex;align-items:center;gap:8px;">
      <input type="checkbox" id="onb-parent-consent" style="width:auto;">
      <label for="onb-parent-consent" style="margin-bottom:0;font-weight:400;">家长已同意收集和使用学生学习数据</label>
    </div>
  </div>
  <div class="card" style="margin-bottom:24px;">
    <h3>🎯 第二步：真正个性化的学习，从这里开始</h3>
    <p style="color:var(--accent);margin-bottom:16px;font-size:.92em;line-height:1.8;">
      ⚡️ 花 3 分钟填一填，AI 出的每道题都会「长在」孩子的薄弱点上——比闷头刷 30 道题管用多了
    </p>
    <div style="display:flex;gap:4px;margin-bottom:16px;border-bottom:1px solid var(--border);flex-wrap:wrap;">
      <button class="onb-profile-tab active" data-tab="english" onclick="switchOnbProfileTab('english')" style="padding:8px 16px;border:none;background:none;border-bottom:2px solid var(--accent);font-weight:600;color:var(--text);">📝 英语学情</button>
      <button class="onb-profile-tab" data-tab="traits" onclick="switchOnbProfileTab('traits')" style="padding:8px 16px;border:none;background:none;color:var(--sub);">🧠 学习特质</button>
      <button class="onb-profile-tab" data-tab="goals" onclick="switchOnbProfileTab('goals')" style="padding:8px 16px;border:none;background:none;color:var(--sub);">🎯 目标与支持</button>
    </div>

    <!-- English Tab -->
    <div id="onb-tab-english" class="onb-profile-tab-content" style="display:block;">
      <div class="form-row">
        <div class="form-group"><label>最近3-5次分数范围</label><input id="onb-recent-scores" placeholder="如：85,92,88 或 85-95"></div>
        <div class="form-group"><label>最有挑战的方面</label><input id="onb-weak-areas" placeholder="如：阅读理解长难句"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>失分主要原因</label><input id="onb-score-loss-reason" placeholder="如：知识点不熟练 / 做题方法 / 粗心"></div>
        <div class="form-group"><label>优先提升题型（逗号分隔）</label><input id="onb-weak-question-types" placeholder="完形填空,阅读理解,作文,听力"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>容易混淆的语法点</label><input id="onb-confused-grammar" placeholder="如：定语从句关系词"></div>
        <div class="form-group"><label>已有学习资源</label><input id="onb-existing-resources" placeholder="如：高考词汇书、真题册"></div>
      </div>
      <div class="form-group"><label>词汇方向</label>
        <select id="onb-vocab-direction">
          <option value="">请选择</option>
          <option value="A">A. 匹配教材</option>
          <option value="B">B. 预习教材</option>
          <option value="C">C. 高考高频词汇</option>
          <option value="D">D. 混合模式</option>
        </select>
      </div>
      <div class="form-group"><label>时间全景图（按周安排）</label>
        <div style="border:1px solid var(--border);border-radius:6px;padding:12px;background:var(--bg);">
          <table style="width:100%;font-size:.85em;">
            <thead>
              <tr style="color:var(--sub);">
                <th style="text-align:left;padding:4px;">星期</th>
                <th style="text-align:left;padding:4px;">开始</th>
                <th style="text-align:left;padding:4px;">结束</th>
                <th style="text-align:left;padding:4px;">内容</th>
                <th style="text-align:left;padding:4px;">性质</th>
                <th style="text-align:left;padding:4px;">精力</th>
                <th style="width:30px;"></th>
              </tr>
            </thead>
            <tbody id="onb-time-map-slots"></tbody>
          </table>
          <button class="btn btn-sm btn-outline" onclick="addOnbTimeSlot()" style="margin-top:8px;">+ 添加时段</button>
          <div style="margin-top:10px;">
            <label style="font-size:.8em;color:var(--sub);">补充说明</label>
            <textarea id="onb-time-map-desc" rows="2" placeholder="如：考试周会取消周六上午时段..." style="margin-top:4px;"></textarea>
          </div>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>一周可用学习时长（小时）</label><input id="onb-weekly-available-hours" type="number" step="0.5"></div>
        <div class="form-group"><label>孩子自愿承诺的英语时间（分钟/周）</label><input id="onb-committed-english-minutes" type="number"></div>
      </div>
    </div>

    <!-- Traits Tab -->
    <div id="onb-tab-traits" class="onb-profile-tab-content" style="display:none;">
      <div class="form-row">
        <div class="form-group"><label>学习类型</label>
          <select id="onb-learning-style">
            <option value="">请选择</option>
            <option value="视觉型">视觉型（爱看、爱画、记笔记）</option>
            <option value="听觉型">听觉型（爱听、爱读、跟读）</option>
            <option value="动觉型">动觉型（动笔、拆解、做题）</option>
            <option value="读写型">读写型（阅读+写作）</option>
          </select>
        </div>
        <div class="form-group"><label>学习介质偏好</label>
          <select id="onb-learning-medium">
            <option value="">请选择</option>
            <option value="纸质">纸质资料</option>
            <option value="电子">电子资料</option>
            <option value="混合">混合</option>
          </select>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>背单词习惯</label><input id="onb-vocab-habit" placeholder="如：反复抄写 / 读出声"></div>
        <div class="form-group"><label>容易分心的环节</label><input id="onb-attention-weakness" placeholder="如：做阅读时容易走神"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>过往有效方法</label><input id="onb-effective-methods" placeholder="如：用思维导图记语法"></div>
        <div class="form-group"><label>过往无效方法</label><input id="onb-ineffective-methods" placeholder="如：单纯抄单词"></div>
      </div>
      <div class="form-group"><label>与英语的关系</label>
        <select id="onb-english-identity">
          <option value="">请选择</option>
          <option value="敌人">敌人 / 负担</option>
          <option value="工具">工具 / 任务</option>
          <option value="朋友">朋友 / 技能</option>
          <option value="兴趣">兴趣 / 爱好</option>
        </select>
      </div>
      <hr style="margin:16px 0;border:none;border-top:1px solid var(--border);">
      <p style="font-size:.85em;color:var(--sub);margin-bottom:12px;">小测评结果（可选填）</p>
      <div class="form-row">
        <div class="form-group"><label>注意力极限时长（分钟）</label><input id="onb-attention-minutes" type="number" placeholder="如：25"></div>
        <div class="form-group"><label>词汇量自测等级</label>
          <div style="display:flex;gap:8px;align-items:flex-end;">
            <select id="onb-vocab-level" style="flex:1;">
              <option value="">未测评</option>
              <option value="基础偏弱">基础偏弱</option>
              <option value="基础尚可">基础尚可</option>
              <option value="中上水平">中上水平</option>
              <option value="词汇较强">词汇较强</option>
            </select>
            <button class="btn btn-sm btn-outline" onclick="startVocabTest('onb')" style="white-space:nowrap;padding:6px 14px;">📝 在线测评</button>
          </div>
        </div>
      </div>
      <div class="form-group"><label>学习场景偏好</label>
        <select id="onb-scene-preference">
          <option value="">未测评</option>
          <option value="视觉助记">视觉助记（看+写）</option>
          <option value="音频跟读">音频跟读（听+读）</option>
          <option value="语境句子">语境句子（上下文理解）</option>
        </select>
      </div>
    </div>

    <!-- Goals Tab -->
    <div id="onb-tab-goals" class="onb-profile-tab-content" style="display:none;">
      <div class="form-row">
        <div class="form-group"><label>升学目标</label><input id="onb-academic-goal" placeholder="如：稳住不下滑 / 冲刺130分"></div>
        <div class="form-group"><label>选科情况</label><select id="onb-subject-choice"><option value="">请选择</option><option>文科</option><option>理科</option><option>未分科</option></select></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>教材版本</label><input id="onb-textbook-version" placeholder="如：人教版必修2"></div>
        <div class="form-group"><label>学期</label><select id="onb-semester"><option value="">请选择</option><option>上学期</option><option>下学期</option></select></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>期望进步时间</label><input id="onb-target-timeline" placeholder="如：3个月"></div>
        <div class="form-group"><label>1个月小目标</label><input id="onb-one-month-goal" placeholder="如：阅读理解正确率提升到70%"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>家长每周陪学时间</label><input id="onb-parent-availability" placeholder="如：周末1-2小时"></div>
        <div class="form-group"><label>需要监督吗</label>
          <select id="onb-supervision-needed">
            <option value="0">主要靠孩子自主</option>
            <option value="1">需要每天检查</option>
          </select>
        </div>
      </div>
      <div class="form-group"><label>学习环境</label><input id="onb-study-environment" placeholder="如：独立书房 / 客厅"></div>
      <hr style="margin:16px 0;border:none;border-top:1px solid var(--border);">
      <p style="font-size:.85em;color:var(--sub);margin-bottom:12px;">孩子的心声</p>
      <div class="form-row">
        <div class="form-group"><label>最不想做的事</label><input id="onb-least-favorite-task" placeholder="如：背单词"></div>
        <div class="form-group"><label>期望强度</label>
          <select id="onb-preferred-intensity">
            <option value="">请选择</option>
            <option value="轻松">轻松一点</option>
            <option value="中等">中等</option>
            <option value="上强度">可以上点强度</option>
          </select>
        </div>
      </div>
      <div class="form-group"><label>英语变厉害后想做什么</label><input id="onb-aspirational-use" placeholder="如：看美剧不用字幕"></div>
      <hr style="margin:16px 0;border:none;border-top:1px solid var(--border);">
      <p style="font-size:.85em;color:var(--sub);margin-bottom:12px;">关键抉择</p>
      <div class="form-row">
        <div class="form-group"><label>模块配比</label>
          <select id="onb-module-ratio">
            <option value="">请选择</option>
            <option value="主攻突破">主攻突破型（薄弱模块70%）</option>
            <option value="稳步推进">稳步推进型（词汇50%）</option>
          </select>
        </div>
        <div class="form-group"><label>难度起点</label>
          <select id="onb-difficulty-start">
            <option value="">请选择</option>
            <option value="基础巩固">基础巩固起步</option>
            <option value="中等直入">中等难度直入</option>
          </select>
        </div>
      </div>
      <div class="form-group"><label>每日词汇量</label>
        <select id="onb-daily-vocab">
          <option value="">请选择</option>
          <option value="5">每天5个（轻松）</option>
          <option value="8">每天8个（性价比最高）</option>
          <option value="10">每天10个（挑战）</option>
        </select>
      </div>
      <div class="form-row">
        <div class="form-group"><label>专属计划名称</label><input id="onb-plan-name" placeholder="如：火箭计划"></div>
        <div class="form-group"><label>专属代号</label><input id="onb-plan-code-name" placeholder="如：Rocket-2024"></div>
      </div>
    </div>
  </div>
  <div class="card">
    <h3>第三步：上传试卷照片</h3>
    <div class="form-group"><label>试卷照片（支持 JPG/PNG，最多 15 张）</label><input type="file" id="onb-file" accept="image/*" multiple style="padding:8px;"></div>
    <button class="btn btn-primary" onclick="startOnboarding()">🚀 开始诊断</button>
  </div>
  <div id="onb-progress" style="display:none;margin-top:16px;">
    <div class="progress-bar"><div class="fill" id="onb-bar" style="width:0%"></div></div>
    <div class="step-list" id="onb-steps"></div>
    <p id="onb-result" style="margin-top:12px;"></p>
  </div>
</div>

<!-- ══════ WEEKLY ══════ -->
<div id="page-weekly" class="page">
  <h2>周度服务</h2>
  <div class="card" style="margin-bottom:16px;">
    <div class="form-row">
      <div class="form-group" style="flex:1;"><label>选择学生</label><select id="wk-student"></select></div>
      <div class="form-group" style="flex:1;"><label>试卷照片（最多 15 张）</label><input type="file" id="wk-file" accept="image/*" multiple onchange="onFileSelected()"></div>
    </div>
    <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:8px;">
      <button class="btn btn-primary" onclick="startWeekly('grade_only')">✅ 批改试卷</button>
      <button class="btn btn-outline" onclick="startWeekly('analysis_only')" style="border-color:var(--accent);color:var(--accent);">📋 矩阵分析</button>
      <button class="btn btn-green" onclick="startWeekly('report_only')">📊 生成周报</button>
    </div>
  </div>

  <div id="wk-progress" style="display:none;">
    <div class="progress-bar"><div class="fill" id="wk-bar" style="width:0%"></div></div>
    <div class="step-list" id="wk-steps"></div>
    <p id="wk-result" style="margin-top:12px;"></p>
  </div>
  <h2 style="margin-top:32px;">历史任务</h2>
  <table id="tasks-table">
    <thead><tr><th>学生</th><th>类型</th><th>状态</th><th>结果</th><th>时间</th></tr></thead>
    <tbody></tbody>
  </table>
</div>

<!-- ══════ ANALYTICS ══════ -->
<div id="page-analytics" class="page">
  <h2>📊 班级学情概览</h2>
  <div class="stats" id="class-stats"></div>

  <div class="card" style="margin-bottom:24px;">
    <h3 style="margin-bottom:16px;">班级平均分趋势</h3>
    <div id="class-trend-chart" style="width:100%;height:240px;"></div>
  </div>

  <div class="form-row" style="margin-bottom:16px;">
    <div class="card" style="width:100%;">
      <h3 style="margin-bottom:16px;">班级薄弱知识点 TOP10</h3>
      <div id="class-weak-kp"></div>
    </div>
  </div>

  <h2 style="margin-top:32px;">👤 个人学情</h2>
  <div class="form-row" style="margin-bottom:16px;">
    <div class="form-group" style="margin-bottom:0;">
      <label>选择学生</label>
      <select id="analytics-student" onchange="loadStudentAnalytics()"></select>
    </div>
    <div class="form-group" style="margin-bottom:0;">
      <label></label>
      <button class="btn btn-primary" style="margin-top:20px;" onclick="openScoreModal()">+ 录入分数</button>
    </div>
  </div>

  <div id="student-analytics">
    <div class="stats" id="student-stats"></div>

    <div class="card" style="margin-bottom:24px;">
      <h3 style="margin-bottom:16px;">分数趋势</h3>
      <div id="student-trend-chart" style="width:100%;height:220px;">
        <p style="text-align:center;color:var(--sub);padding-top:80px;">请选择学生查看</p>
      </div>
    </div>

    <div class="form-row" style="margin-bottom:24px;">
      <div class="card" style="width:100%;">
        <h3 style="margin-bottom:16px;">知识点掌握热力图</h3>
        <div id="student-kp-heatmap"></div>
      </div>
    </div>

    <h3>近期练习表现</h3>
    <div id="student-practice-stats" style="margin-bottom:24px;"></div>

    <h3>错题统计</h3>
    <div id="student-mistake-stats" style="margin-bottom:24px;"></div>

    <h3>🛤️ 学习路径时间轴</h3>
    <div id="student-timeline" style="margin-bottom:24px;"></div>

    <h3>🏆 成就墙</h3>
    <div id="student-achievements-wall" style="margin-bottom:24px;"></div>

    <h3>个性化画像</h3>
    <div id="student-profile-summary" style="margin-bottom:24px;"></div>

    <h3>诊断结论</h3>
    <div id="student-diagnosis-conclusion" style="margin-bottom:24px;"></div>

    <h3>动机卡片</h3>
    <div id="student-motivation-cards" style="margin-bottom:24px;"></div>

    <h3>元认知复盘表</h3>
    <div id="student-metacognitive-review" style="margin-bottom:24px;"></div>

    <h3>自适应调整记录</h3>
    <div id="student-plan-adjustments"></div>
  </div>
</div>

<!-- ══════ QUESTION BANK ══════ -->
<div id="page-bank" class="page">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
    <h2 style="margin:0;">🗂️ 题库管理</h2>
    <div class="btn-group" style="margin:0;">
      <input type="text" id="bank-search" placeholder="搜索知识点" style="padding:6px 10px;border:1px solid var(--border);border-radius:6px;font-size:.85em;">
      <button class="btn btn-primary" onclick="loadBank()">搜索</button>
    </div>
  </div>

  <div class="stats" id="bank-stats" style="margin-bottom:16px;"></div>

  <table id="questions-table">
    <thead><tr><th>题目</th><th>题型</th><th>知识点</th><th>难度</th><th>使用次数</th><th>状态</th><th>操作</th></tr></thead>
    <tbody></tbody>
  </table>

  <!-- Question Edit Modal -->
  <div class="modal-overlay" id="q-modal">
    <div class="modal" style="max-width:560px;">
      <h3>编辑题目</h3>
      <input type="hidden" id="q-id">
      <div class="form-group"><label>题干</label><textarea id="q-text" rows="3"></textarea></div>
      <div class="form-row">
        <div class="form-group"><label>题型</label><input id="q-type"></div>
        <div class="form-group"><label>正确答案</label><input id="q-answer"></div>
      </div>
      <div class="form-group"><label>解析</label><textarea id="q-explanation" rows="2"></textarea></div>
      <div class="form-row">
        <div class="form-group"><label>知识点（逗号分隔）</label><input id="q-kp"></div>
        <div class="form-group"><label>难度（1-5）</label><input id="q-difficulty" type="number" min="1" max="5"></div>
      </div>
      <div class="btn-group" style="justify-content:flex-end;">
        <button class="btn btn-outline" onclick="closeQModal()">取消</button>
        <button class="btn btn-primary" onclick="saveQuestion()">保存</button>
      </div>
    </div>
  </div>
</div>

</div>

<!-- ══════ QUALITY SAMPLING ══════ -->
<div id="page-quality" class="page">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
    <h2 style="margin:0;">🔍 AI 内容质量抽检</h2>
    <button class="btn btn-primary" onclick="loadQuality()">刷新</button>
  </div>

  <div class="stats" id="quality-stats" style="margin-bottom:16px;"></div>

  <h3 style="font-size:1em;margin:16px 0 8px;">待抽检</h3>
  <div id="quality-pending-list" style="display:flex;flex-direction:column;gap:12px;">
    <div style="color:var(--sub);text-align:center;padding:24px;">加载中...</div>
  </div>
</div>

<!-- ══════ REFERRALS ══════ -->
<div id="page-referrals" class="page">
  <h2>🎁 邀请统计</h2>
  <div class="stats" id="referral-stats" style="margin-bottom:16px;"></div>

  <div class="card" style="margin-bottom:24px;">
    <h3 style="margin-bottom:12px;">奖励规则配置</h3>
    <div class="form-row">
      <div class="form-group" style="margin-bottom:0;">
        <label>邀请成功奖励周数</label>
        <input id="referral-reward-weeks" type="number" min="0" value="1">
      </div>
    </div>
    <button class="btn btn-primary" style="margin-top:8px;" onclick="saveReferralSettings()">保存设置</button>
  </div>

  <h3 style="font-size:1em;margin:16px 0 8px;">🏆 邀请榜 TOP10</h3>
  <table id="referral-top-table">
    <thead><tr><th>学生</th><th>邀请人数</th><th>累计奖励周数</th></tr></thead>
    <tbody></tbody>
  </table>
</div>

<!-- ══════ CLASSES ══════ -->
{% if feature_school %}
<div id="page-classes" class="page">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
    <h2 style="margin:0;">班级管理</h2>
    <div style="display:flex;gap:8px;">
      {% if user_role == 'admin' %}<button class="btn btn-outline btn-sm" onclick="openSchoolModal()">+ 添加学校</button>{% endif %}
      <button class="btn btn-primary btn-sm" onclick="openClassModal()">+ 创建班级</button>
    </div>
  </div>
  <div id="classes-list"></div>
  <div id="class-detail" style="display:none;">
    <div style="margin-bottom:16px;"><button class="btn btn-outline btn-sm" onclick="backToClasses()">← 返回班级列表</button></div>
    <div id="class-stats-cards" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:16px;"></div>
    <div class="card">
      <h3 style="font-size:.95em;margin-bottom:12px;">全班薄弱知识点 TOP5</h3>
      <div id="class-weak-points"></div>
    </div>
    <div class="card">
      <h3 style="font-size:.95em;margin-bottom:12px;">学生列表</h3>
      <div class="table-wrap">
        <table id="class-students-table">
          <thead><tr><th>姓名</th><th>年级</th><th>手机号</th><th>操作</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>
  </div>
</div>
{% endif %}

{% if user_role == 'admin' %}
<!-- ══════ ADMIN ══════ -->
<div id="page-admin" class="page">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
    <h2 style="margin:0;">账号管理</h2>
    <button class="btn btn-primary" onclick="openAdminModal()">+ 添加账号</button>
  </div>
  <table id="admin-users-table">
    <thead><tr><th>用户名</th><th>角色</th><th>创建时间</th><th>操作</th></tr></thead>
    <tbody></tbody>
  </table>
</div>
<div class="modal-overlay" id="admin-modal">
  <div class="modal">
    <h3 id="admin-modal-title">添加账号</h3>
    <div class="form-group"><label>用户名 *</label><input id="admin-username"></div>
    <div class="form-group"><label>密码 *</label><input type="password" id="admin-password"></div>
    <div class="form-group"><label>角色</label><select id="admin-role"><option value="teacher" selected>老师</option><option value="admin">管理员</option></select></div>
    <div class="btn-group" style="justify-content:flex-end;">
      <button class="btn btn-outline" onclick="closeAdminModal()">取消</button>
      <button class="btn btn-primary" onclick="saveAdminUser()">保存</button>
    </div>
  </div>
</div>

<!-- ══════ OBSERVABILITY ══════ -->
<div id="page-observability" class="page">
  <h2>📊 系统监控</h2>

  <!-- Active Alerts Banner -->
  <div id="obs-alert-banner" style="margin-bottom:16px;"></div>

  <!-- Task Health -->
  <div class="card" style="margin-bottom:24px;">
    <h3 style="margin-bottom:12px;">🩺 任务健康</h3>
    <div class="stats" id="obs-task-stats" style="margin-bottom:16px;"></div>
    <div style="margin-bottom:12px;">
      <strong style="font-size:.9em;">近7天每日失败/驳回趋势</strong>
      <div id="obs-failure-trend" style="height:140px; background:var(--bg); border-radius:6px; padding:12px; margin-top:8px; overflow-x:auto;"></div>
    </div>
    <h4 style="font-size:.9em; margin:16px 0 8px;">最近失败任务</h4>
    <table id="obs-failure-table">
      <thead><tr><th>学生</th><th>任务</th><th>状态</th><th>时间</th><th>错误信息</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <!-- Cost Alerts -->
  <div class="card" style="margin-bottom:24px;">
    <h3 style="margin-bottom:12px;">💰 成本告警</h3>
    <div id="obs-cost-panel"></div>
    {% if user_role == 'admin' %}
    <div class="form-row" style="margin-top:12px;">
      <div class="form-group" style="margin-bottom:0;">
        <label style="font-size:.8em;">告警阈值 (%)</label>
        <input id="obs-alert-threshold" type="number" min="0" max="100" value="80" style="width:80px;">
      </div>
      <div class="form-group" style="margin-bottom:0; align-self:flex-end;">
        <button class="btn btn-sm btn-primary" onclick="saveAlertSettings()">保存阈值</button>
      </div>
    </div>
    {% endif %}
  </div>

  <!-- Audit Logs -->
  <div class="card" style="margin-bottom:24px;">
    <h3 style="margin-bottom:12px;">📋 审计日志</h3>
    <div class="form-row" style="margin-bottom:12px;">
      <div class="form-group" style="margin-bottom:0;">
        <label style="font-size:.8em;">操作类型</label>
        <select id="obs-audit-action"><option value="">全部</option></select>
      </div>
      <div class="form-group" style="margin-bottom:0;">
        <label style="font-size:.8em;">目标类型</label>
        <input id="obs-audit-target" placeholder="如 student">
      </div>
      <div class="form-group" style="margin-bottom:0;">
        <label style="font-size:.8em;">开始日期</label>
        <input id="obs-audit-since" type="date">
      </div>
      <div class="form-group" style="margin-bottom:0; align-self:flex-end;">
        <button class="btn btn-sm btn-primary" onclick="loadAuditLogs()">查询</button>
      </div>
    </div>
    <table id="obs-audit-table">
      <thead><tr><th>时间</th><th>操作者</th><th>动作</th><th>目标</th><th>详情</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <!-- Backups -->
  <div class="card" style="margin-bottom:24px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
      <h3 style="margin:0;">💾 自动备份</h3>
      <button class="btn btn-sm btn-primary" onclick="runManualBackup()">立即备份</button>
    </div>
    <p style="font-size:.85em;color:var(--sub);margin-bottom:12px;">保留策略：最近 7 个 daily 备份 + 最近 4 个 weekly 备份。每天/每周凌晨 3 点自动执行。</p>
    <table id="obs-backup-table">
      <thead><tr><th>时间</th><th>类型</th><th>文件大小</th><th>操作</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>
</div>
{% endif %}

<!-- ══════ COMPLIANCE ══════ -->
<div id="page-compliance" class="page">
  <h2>👨‍👩‍👧 数据合规</h2>

  <!-- Consent Section -->
  <div class="card" style="margin-bottom:24px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
      <h3 style="margin:0;">📝 待家长授权学生</h3>
      <span style="font-size:.85em;color:var(--sub);" id="consent-pending-count">-</span>
    </div>
    <table id="consent-table" style="margin-bottom:12px;">
      <thead><tr><th>学生</th><th>年级</th><th>家长联系方式</th><th>操作</th></tr></thead>
      <tbody></tbody>
    </table>
    <p style="font-size:.85em;color:var(--sub);">在学生详情页也可补录家长授权。授权记录会写入审计日志。</p>
  </div>

  <!-- Deletion Requests Section -->
  <div class="card" style="margin-bottom:24px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
      <h3 style="margin:0;">🗑️ 待处理数据删除申请</h3>
      <span style="font-size:.85em;color:var(--sub);" id="deletion-pending-count">-</span>
    </div>
    <table id="deletion-table">
      <thead><tr><th>学生</th><th>申请人</th><th>原因</th><th>申请时间</th><th>操作</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>
</div>

<!-- Teacher / Institution Profile Page -->
{% if feature_teacher %}
<div id="page-teacher-profile" class="page">
  <h2>🏫 机构与老师介绍</h2>
  <div class="card" style="max-width:640px;">
    <div class="form-row">
      <div class="form-group"><label>机构名称</label><input id="tp-institution" placeholder="拾阶而上"></div>
      <div class="form-group"><label>老师姓名</label><input id="tp-teacher" placeholder="王老师"></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>教龄</label><input id="tp-years" placeholder="8 年高考英语教学经验"></div>
      <div class="form-group"><label>擅长方向</label><input id="tp-specialty" placeholder="阅读理解提分 / 写作冲刺"></div>
    </div>
    <div class="form-group"><label>教学理念</label><input id="tp-philosophy" placeholder="错题不过夜，弱项逐个破"></div>
    <div class="form-group"><label>联系方式（仅对付费家长显示）</label><input id="tp-contact" placeholder="微信：xxx"></div>
    <div class="form-group">
      <label>老师头像</label>
      <input type="file" id="tp-avatar" accept="image/*" style="padding:8px;">
      <p id="tp-avatar-preview" style="font-size:.85em;color:var(--sub);margin-top:6px;"></p>
    </div>
    <button class="btn btn-primary" onclick="saveTeacherProfile()">💾 保存</button>
  </div>
</div>
{% endif %}

<!-- Subscription Modal -->
<div class="modal-overlay" id="sub-modal">
  <div class="modal" style="max-width:520px;">
    <h3 id="sub-modal-title">订阅管理</h3>
    <input type="hidden" id="sub-student-id">

    <div class="form-row">
      <div class="form-group"><label>套餐</label>
        <select id="sub-plan" onchange="updateSubPrice()">
          <option value="trial">体验（免费）</option>
          <option value="basic">基础版 ¥99/月</option>
          <option value="premium">托管版 ¥299/月</option>
        </select>
      </div>
      <div class="form-group"><label>当前状态</label><input id="sub-status" readonly style="background:#f5f2ec;"></div>
    </div>

    <div class="form-row">
      <div class="form-group"><label>有效期至</label><input id="sub-end-date" type="date"></div>
      <div class="form-group"><label>累计缴费</label><input id="sub-total-paid" readonly style="background:#f5f2ec;"></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>本月额度</label><input id="sub-quota" readonly style="background:#f5f2ec;"></div>
      <div class="form-group"><label>本月已用</label><input id="sub-used" readonly style="background:#f5f2ec;"></div>
    </div>

    <div class="btn-group" style="justify-content:flex-end;">
      <button class="btn btn-outline" onclick="closeSubModal()">关闭</button>
      <button class="btn btn-primary" onclick="saveSubPlan()">保存套餐</button>
    </div>

    <hr style="border:none;border-top:1px solid var(--border);margin:24px 0;">

    <h4 style="margin-bottom:12px;">收款记录</h4>
    <div class="form-row">
      <div class="form-group"><label>收款金额（元）</label><input id="pay-amount" type="number" step="0.01" placeholder="0.00"></div>
      <div class="form-group"><label>购买月数</label><input id="pay-weeks" type="number" min="1" value="1"></div>
    </div>
    <div class="form-group"><label>备注</label><input id="pay-note" placeholder="如：微信转账、现金"></div>
    <button class="btn btn-green" style="width:100%;" onclick="recordPayment()">💰 记录收款并续费</button>

    <h4 style="margin:20px 0 8px;">历史记录</h4>
    <table id="payments-table" style="font-size:.85em;">
      <thead><tr><th>日期</th><th>金额</th><th>月数</th><th>备注</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>
</div>

<!-- Score Modal -->
<div class="modal-overlay" id="score-modal">
  <div class="modal" style="max-width:400px;">
    <h3>录入考试分数</h3>
    <input type="hidden" id="score-student-id">
    <div class="form-group"><label>学生</label><input id="score-student-name" readonly style="background:#f5f2ec;"></div>
    <div class="form-row">
      <div class="form-group"><label>分数 *</label><input id="score-value" type="number" step="0.5" placeholder="0-150"></div>
      <div class="form-group"><label>日期</label><input id="score-date" type="date"></div>
    </div>
    <div class="form-group"><label>备注</label><input id="score-note" placeholder="如：月考、期中"></div>
    <div class="btn-group" style="justify-content:flex-end;">
      <button class="btn btn-outline" onclick="closeScoreModal()">取消</button>
      <button class="btn btn-primary" onclick="saveScore()">保存</button>
    </div>
  </div>
</div>

<!-- ══════ MODAL: AI Correction ══════ -->
<div class="modal-overlay" id="correction-modal">
  <div class="modal" style="max-width:760px; padding:0; display:flex; flex-direction:column; max-height:85vh;">
    <div style="padding:20px 24px; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center;">
      <h3 style="margin:0;">📝 AI 内容纠错 <span id="correction-task-info" style="font-size:.7em; color:var(--sub); font-weight:400;"></span></h3>
      <button class="btn btn-sm btn-outline" onclick="closeCorrectionModal()">关闭</button>
    </div>
    <div style="padding:20px 24px; overflow-y:auto; flex:1;">
      <input type="hidden" id="correction-task-id">
      <div id="correction-items" style="display:flex; flex-direction:column; gap:16px;"></div>
      <div class="form-group" style="margin-top:16px;">
        <label>纠错原因（可选，会记入审计日志）</label>
        <input id="correction-reason" placeholder="如：OCR 把答案识别错了 / 知识点应归类为定语从句">
      </div>
    </div>
    <div style="padding:16px 24px; border-top:1px solid var(--border); display:flex; justify-content:space-between; align-items:center;">
      <span id="correction-status" style="font-size:.85em; color:var(--sub);"></span>
      <div class="btn-group" style="gap:8px;">
        <button class="btn btn-outline" onclick="closeCorrectionModal()">取消</button>
        <button class="btn btn-primary" onclick="submitCorrections()">提交纠错</button>
      </div>
    </div>
  </div>
</div>

<!-- ══════ MODAL: Student ══════ -->
<div class="modal-overlay" id="student-modal">
  <div class="modal" style="max-width:720px;">
    <h3 id="student-modal-title">添加学生</h3>

    <!-- Tab navigation -->
    <div style="display:flex;gap:4px;margin-bottom:16px;border-bottom:1px solid var(--border);flex-wrap:wrap;">
      <button class="profile-tab active" data-tab="basic" onclick="switchProfileTab('basic')" style="padding:8px 16px;border:none;background:none;border-bottom:2px solid var(--accent);font-weight:600;color:var(--text);">基本信息</button>
      <button class="profile-tab" data-tab="english" onclick="switchProfileTab('english')" style="padding:8px 16px;border:none;background:none;color:var(--sub);">英语学情</button>
      <button class="profile-tab" data-tab="traits" onclick="switchProfileTab('traits')" style="padding:8px 16px;border:none;background:none;color:var(--sub);">学习特质</button>
      <button class="profile-tab" data-tab="goals" onclick="switchProfileTab('goals')" style="padding:8px 16px;border:none;background:none;color:var(--sub);">目标与支持</button>
    </div>

    <!-- Basic Info Tab -->
    <div id="tab-basic" class="profile-tab-content" style="display:block;">
      <div class="form-row">
        <div class="form-group"><label>姓名 *</label><input id="f-name"></div>
        <div class="form-group"><label>年级</label><select id="f-grade"><option>高一</option><option selected>高二</option><option>高三</option></select></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>性别</label><select id="f-gender"><option value="">请选择</option><option>男</option><option>女</option></select></div>
        <div class="form-group"><label>学期</label><select id="f-semester"><option value="">请选择</option><option>上学期</option><option>下学期</option></select></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>住校/走读</label><select id="f-school-type"><option selected>住校</option><option>走读</option></select></div>
        <div class="form-group"><label>套餐</label><select id="f-plan"><option value="trial">体验</option><option value="basic">基础版</option><option value="premium">托管版</option></select></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>英语成绩</label><input id="f-english-score" type="number" step="0.5"></div>
        <div class="form-group"><label>目标分数</label><input id="f-target-score" type="number" step="0.5"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>升学目标</label><input id="f-academic-goal" placeholder="如：稳住不下滑 / 冲刺130分"></div>
        <div class="form-group"><label>选科情况</label><select id="f-subject-choice"><option value="">请选择</option><option>文科</option><option>理科</option><option>未分科</option></select></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>教材版本</label><input id="f-textbook-version" placeholder="如：人教版必修2"></div>
        <div class="form-group"><label>家长姓名</label><input id="f-parent-name"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>家长微信</label><input id="f-parent-wechat"></div>
        <div class="form-group"><label>家长电话</label><input id="f-parent-phone"></div>
      </div>
      <div class="form-group" style="display:flex;align-items:center;gap:8px;">
        <input type="checkbox" id="f-parent-consent" style="width:auto;">
        <label for="f-parent-consent" style="margin-bottom:0;font-weight:400;">家长已同意收集和使用学生学习数据（未成年人合规授权）</label>
      </div>
      <div class="form-group"><label>备注</label><textarea id="f-notes"></textarea></div>
    </div>

    <!-- English Situation Tab -->
    <div id="tab-english" class="profile-tab-content" style="display:none;">
      <div class="form-row">
        <div class="form-group"><label>最近3-5次分数范围</label><input id="f-recent-scores" placeholder="如：85,92,88 或 85-95"></div>
        <div class="form-group"><label>最有挑战的方面</label><input id="f-weak-areas" placeholder="如：阅读理解长难句"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>失分主要原因</label><input id="f-score-loss-reason" placeholder="如：知识点不熟练 / 做题方法 / 粗心"></div>
        <div class="form-group"><label>优先提升题型（逗号分隔）</label><input id="f-weak-question-types" placeholder="完形填空,阅读理解,作文,听力"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>容易混淆的语法点</label><input id="f-confused-grammar" placeholder="如：定语从句关系词"></div>
        <div class="form-group"><label>已有学习资源</label><input id="f-existing-resources" placeholder="如：高考词汇书、真题册"></div>
      </div>
      <div class="form-group"><label>词汇方向</label>
        <select id="f-vocab-direction">
          <option value="">请选择</option>
          <option value="A">A. 匹配教材</option>
          <option value="B">B. 预习教材</option>
          <option value="C">C. 高考高频词汇</option>
          <option value="D">D. 混合模式</option>
        </select>
      </div>
      <div class="form-group"><label>时间全景图（按周安排）</label>
        <div id="time-map-editor" style="border:1px solid var(--border);border-radius:6px;padding:12px;background:var(--bg);">
          <table style="width:100%;font-size:.85em;">
            <thead>
              <tr style="color:var(--sub);">
                <th style="text-align:left;padding:4px;">星期</th>
                <th style="text-align:left;padding:4px;">开始</th>
                <th style="text-align:left;padding:4px;">结束</th>
                <th style="text-align:left;padding:4px;">内容</th>
                <th style="text-align:left;padding:4px;">性质</th>
                <th style="text-align:left;padding:4px;">精力</th>
                <th style="width:30px;"></th>
              </tr>
            </thead>
            <tbody id="time-map-slots"></tbody>
          </table>
          <button class="btn btn-sm btn-outline" onclick="addTimeSlot()" style="margin-top:8px;">+ 添加时段</button>
          <div style="margin-top:10px;">
            <label style="font-size:.8em;color:var(--sub);">补充说明</label>
            <textarea id="f-time-map-desc" rows="2" placeholder="如：考试周会取消周六上午时段..." style="margin-top:4px;"></textarea>
          </div>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>一周可用学习时长（小时）</label><input id="f-weekly-available-hours" type="number" step="0.5"></div>
        <div class="form-group"><label>孩子自愿承诺的英语时间（分钟/周）</label><input id="f-committed-english-minutes" type="number"></div>
      </div>
    </div>

    <!-- Learning Traits Tab -->
    <div id="tab-traits" class="profile-tab-content" style="display:none;">
      <div class="form-row">
        <div class="form-group"><label>学习类型</label>
          <select id="f-learning-style">
            <option value="">请选择</option>
            <option value="视觉型">视觉型（爱看、爱画、记笔记）</option>
            <option value="听觉型">听觉型（爱听、爱读、跟读）</option>
            <option value="动觉型">动觉型（动笔、拆解、做题）</option>
            <option value="读写型">读写型（阅读+写作）</option>
          </select>
        </div>
        <div class="form-group"><label>AI 学习风格测评</label>
          <div id="learning-style-radar" style="border:1px solid var(--border);border-radius:6px;padding:10px;background:var(--bg);">
            <p style="color:var(--sub);text-align:center;margin:20px 0;">完成首次 AI 诊断后将展示 4 维学习风格雷达图</p>
          </div>
        </div>
        <div class="form-group"><label>学习介质偏好</label>
          <select id="f-learning-medium">
            <option value="">请选择</option>
            <option value="纸质">纸质资料</option>
            <option value="电子">电子资料</option>
            <option value="混合">混合</option>
          </select>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>背单词习惯</label><input id="f-vocab-habit" placeholder="如：反复抄写 / 读出声"></div>
        <div class="form-group"><label>容易分心的环节</label><input id="f-attention-weakness" placeholder="如：做阅读时容易走神"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>过往有效方法</label><input id="f-effective-methods" placeholder="如：用思维导图记语法"></div>
        <div class="form-group"><label>过往无效方法</label><input id="f-ineffective-methods" placeholder="如：单纯抄单词"></div>
      </div>
      <div class="form-group"><label>与英语的关系</label>
        <select id="f-english-identity">
          <option value="">请选择</option>
          <option value="敌人">敌人 / 负担</option>
          <option value="工具">工具 / 任务</option>
          <option value="朋友">朋友 / 技能</option>
          <option value="兴趣">兴趣 / 爱好</option>
        </select>
      </div>
      <hr style="margin:16px 0;border:none;border-top:1px solid var(--border);">
      <p style="font-size:.85em;color:var(--sub);margin-bottom:12px;">小测评结果（可选填）</p>
      <div class="form-row">
        <div class="form-group"><label>注意力极限时长（分钟）</label><input id="f-attention-minutes" type="number" placeholder="如：25"></div>
        <div class="form-group"><label>词汇量自测等级</label>
          <div style="display:flex;gap:8px;align-items:flex-end;">
            <select id="f-vocab-level" style="flex:1;">
              <option value="">未测评</option>
              <option value="基础偏弱">基础偏弱</option>
              <option value="基础尚可">基础尚可</option>
              <option value="中上水平">中上水平</option>
              <option value="词汇较强">词汇较强</option>
            </select>
            <button class="btn btn-sm btn-outline" onclick="startVocabTest('f')" style="white-space:nowrap;padding:6px 14px;">📝 在线测评</button>
          </div>
        </div>
      </div>
      <div class="form-group"><label>学习场景偏好</label>
        <select id="f-scene-preference">
          <option value="">未测评</option>
          <option value="视觉助记">视觉助记（看+写）</option>
          <option value="音频跟读">音频跟读（听+读）</option>
          <option value="语境句子">语境句子（上下文理解）</option>
        </select>
      </div>
    </div>

    <!-- Goals Tab -->
    <div id="tab-goals" class="profile-tab-content" style="display:none;">
      <div class="form-row">
        <div class="form-group"><label>期望进步时间</label><input id="f-target-timeline" placeholder="如：3个月"></div>
        <div class="form-group"><label>1个月小目标</label><input id="f-one-month-goal" placeholder="如：阅读理解正确率提升到70%"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>家长每周陪学时间</label><input id="f-parent-availability" placeholder="如：周末1-2小时"></div>
        <div class="form-group"><label>需要监督吗</label>
          <select id="f-supervision-needed">
            <option value="0">主要靠孩子自主</option>
            <option value="1">需要每天检查</option>
          </select>
        </div>
      </div>
      <div class="form-group"><label>学习环境</label><input id="f-study-environment" placeholder="如：独立书房 / 客厅"></div>
      <hr style="margin:16px 0;border:none;border-top:1px solid var(--border);">
      <p style="font-size:.85em;color:var(--sub);margin-bottom:12px;">孩子的心声</p>
      <div class="form-row">
        <div class="form-group"><label>最不想做的事</label><input id="f-least-favorite-task" placeholder="如：背单词"></div>
        <div class="form-group"><label>期望强度</label>
          <select id="f-preferred-intensity">
            <option value="">请选择</option>
            <option value="轻松">轻松一点</option>
            <option value="中等">中等</option>
            <option value="上强度">可以上点强度</option>
          </select>
        </div>
      </div>
      <div class="form-group"><label>英语变厉害后想做什么</label><input id="f-aspirational-use" placeholder="如：看美剧不用字幕"></div>
      <hr style="margin:16px 0;border:none;border-top:1px solid var(--border);">
      <p style="font-size:.85em;color:var(--sub);margin-bottom:12px;">关键抉择</p>
      <div class="form-row">
        <div class="form-group"><label>模块配比</label>
          <select id="f-module-ratio">
            <option value="">请选择</option>
            <option value="主攻突破">主攻突破型（薄弱模块70%）</option>
            <option value="稳步推进">稳步推进型（词汇50%）</option>
          </select>
        </div>
        <div class="form-group"><label>难度起点</label>
          <select id="f-difficulty-start">
            <option value="">请选择</option>
            <option value="基础巩固">基础巩固起步</option>
            <option value="中等直入">中等难度直入</option>
          </select>
        </div>
      </div>
      <div class="form-group"><label>每日词汇量</label>
        <select id="f-daily-vocab">
          <option value="">请选择</option>
          <option value="5">每天5个（轻松）</option>
          <option value="8">每天8个（性价比最高）</option>
          <option value="10">每天10个（挑战）</option>
        </select>
      </div>
      <div class="form-row">
        <div class="form-group"><label>专属计划名称</label><input id="f-plan-name" placeholder="如：火箭计划"></div>
        <div class="form-group"><label>专属代号</label><input id="f-plan-code-name" placeholder="如：Rocket-2024"></div>
      </div>
    </div>

    <input type="hidden" id="f-student-id">
    <div class="btn-group" style="justify-content:flex-end;margin-top:16px;">
      <button class="btn btn-outline" onclick="closeStudentModal()">取消</button>
      <button class="btn btn-primary" onclick="saveStudent()">保存</button>
    </div>
  </div>
</div>

<!-- ══════ VOCAB TEST MODAL ══════ -->
<div class="modal-overlay" id="vocab-test-modal">
  <div class="modal" style="max-width:480px;text-align:center;">
    <div id="vt-intro">
      <h3 id="vt-title" style="margin-bottom:8px;">📝 词汇量快测</h3>
      <p id="vt-grade-hint" style="color:var(--sub);font-size:.9em;margin-bottom:20px;"></p>
      <div style="background:var(--bg);border-radius:10px;padding:20px;margin-bottom:20px;text-align:left;font-size:.9em;line-height:1.8;">
        <p style="margin-bottom:8px;">📋 <b>测试说明</b></p>
        <p>• 共 <b id="vt-total-q">60</b> 个单词，约 3 分钟</p>
        <p>• 看到单词，诚实判断<b>是否认识</b></p>
        <p>• 题目根据<b id="vt-grade-label">年级</b>要求自动匹配难度</p>
        <p>• 测试结束自动给出词汇量估算</p>
      </div>
      <button class="btn btn-primary" onclick="beginVocabTest()" style="font-size:1.1em;padding:12px 40px;">开始测评 🚀</button>
      <br><button class="btn btn-sm" onclick="closeVocabTest()" style="margin-top:12px;color:var(--sub);">跳过，手动选择</button>
    </div>
    <div id="vt-testing" style="display:none;">
      <div style="margin-bottom:8px;color:var(--sub);font-size:.85em;">
        进度 <span id="vt-progress-text">1/30</span>
        <span id="vt-band-hint" style="margin-left:12px;color:var(--accent);"></span>
      </div>
      <div class="progress-bar" style="margin-bottom:24px;"><div class="fill" id="vt-bar" style="width:0%"></div></div>
      <div style="font-size:2.2em;font-weight:700;margin:32px 0 12px;letter-spacing:1px;" id="vt-word"></div>
      <p style="color:var(--sub);font-size:.85em;margin-bottom:28px;">你认识这个词吗？</p>
      <div style="display:flex;gap:12px;justify-content:center;">
        <button class="btn btn-green" onclick="answerVocab(true)" style="font-size:1.1em;padding:12px 36px;min-width:120px;">✅ 认识</button>
        <button class="btn btn-outline" onclick="answerVocab(false)" style="font-size:1.1em;padding:12px 36px;min-width:120px;">❌ 不认识</button>
      </div>
    </div>
    <div id="vt-result" style="display:none;">
      <h3 style="margin-bottom:16px;">📊 测评结果</h3>
      <div style="background:var(--bg);border-radius:10px;padding:20px;margin-bottom:20px;">
        <div style="font-size:2.5em;font-weight:700;color:var(--accent);" id="vt-est-vocab">0</div>
        <div style="color:var(--sub);font-size:.9em;">估算词汇量</div>
        <div id="vt-level-badge" style="margin-top:12px;"></div>
        <div id="vt-band-detail" style="margin-top:16px;text-align:left;font-size:.85em;"></div>
      </div>
      <button class="btn btn-primary" onclick="applyVocabResult()" style="font-size:1.05em;padding:10px 32px;">✅ 应用结果</button>
      <br><button class="btn btn-sm" onclick="closeVocabTest()" style="margin-top:8px;color:var(--sub);">放弃，不保存</button>
    </div>
  </div>
</div>

<script>
// ── Helpers ──
function toast(msg, type='success') {
  const t = document.createElement('div'); t.className='toast toast-'+type; t.textContent=msg;
  document.body.appendChild(t); setTimeout(()=>t.remove(), 2500);
}
function fmtDate(d) { return d ? d.slice(0,10) : '-'; }
function icon(v) { return v ? '✅' : ''; }

async function viewStudentAnalytics(studentId) {
  switchPage('analytics');
  await loadAnalyticsPage();
  const sel = document.getElementById('analytics-student');
  if (sel && studentId) {
    sel.value = studentId;
    sel.dispatchEvent(new Event('change'));
  }
  window.scrollTo({top: 0, behavior: 'smooth'});
}

async function viewStudentMistakes(studentId) {
  // Look up student access_code and open public page at 成长记录 tab
  try {
    const r = await fetch('/api/students/' + studentId);
    const s = await r.json();
    if (s && s.access_code) {
      window.open('/s/' + s.access_code + '#mistakes', '_blank');
    } else {
      toast('无法获取学生链接');
    }
  } catch(e) {
    toast('获取学生信息失败');
  }
}

// Upload files with progress bar
function uploadFilesWithProgress(fileInput, studentId, fileType, uploaderRole) {
  return new Promise((resolve, reject) => {
    const fd = new FormData();
    for (const f of fileInput.files) fd.append('files', f);
    fd.append('student_id', studentId);
    fd.append('file_type', fileType);
    fd.append('uploader_role', uploaderRole);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/upload');

    // Show progress overlay
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.4);z-index:9999;display:flex;align-items:center;justify-content:center;';
    overlay.innerHTML = '<div style="background:#fff;border-radius:12px;padding:32px 40px;min-width:280px;text-align:center;box-shadow:0 4px 20px rgba(0,0,0,0.15);"><div style="font-size:1rem;font-weight:600;margin-bottom:16px;color:#1a1a1a;">上传中...</div><div style="background:#e8e6e1;border-radius:8px;height:8px;overflow:hidden;"><div id="upload-progress-bar" style="background:var(--accent, #e07b4b);height:100%;width:0%;transition:width 0.2s;"></div></div><div id="upload-progress-text" style="margin-top:10px;font-size:0.85rem;color:#6b6b6b;">0%</div></div>';
    document.body.appendChild(overlay);

    xhr.upload.onprogress = function(e) {
      if (e.lengthComputable) {
        const pct = Math.round((e.loaded / e.total) * 100);
        const bar = document.getElementById('upload-progress-bar');
        const text = document.getElementById('upload-progress-text');
        if (bar) bar.style.width = pct + '%';
        if (text) text.textContent = pct + '%';
      }
    };

    xhr.onload = function() {
      overlay.remove();
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        reject(new Error('Upload failed'));
      }
    };
    xhr.onerror = function() {
      overlay.remove();
      reject(new Error('Network error'));
    };
    xhr.send(fd);
  });
}

// ── Vocab Test ──
const VOCAB_BANKS = {
  '中考核心': {
    min: 0, max: 1600, words: [
      'accident','achieve','active','advantage','afford','announce','apologize','appreciate','attend','attitude','balance','barrier','belong','benefit','bitter','blame','border','bother','brave','breathe','calm','celebrate','challenge','character','charity','climate','communicate','community','compare','complete','concentrate','confident','congratulate','connect','consider','continue','convenient','courage','create','curious','damage','dangerous','decision','decline','defend','deliver','demand','depend','describe','deserve','design','destroy','determine','develop','devote','disappear','discover','distance','disturb','divide','eager','educate','effect','effort','embarrass','emerge','employ','enable','encourage','energy','enormous','enter','environment','escape','especially','eventually','evidence','examine','example','excellent','exchange','exercise','exist','expect','experience','experiment','explain','explore','express','extreme','familiar','favorite','fierce','figure','finance','fluent','forbid','force','fortunate','freedom','frequent','friendship','generous','genuine','global','gradual','grateful','guarantee','guard','handle','hesitate','honest','humorous','identify','ignore','illegal','imagine','immediate','import','impress','improve','include','increase','independent','indicate','influence','inform','innocent','insist','inspire','instruct','intelligent','intend','interview','introduce','invent','investigate','involve','issue','journey','judge','justice','knowledge','laughter','liberal','liberty','lonely','loyal','manage','manner','material','measure','mention','mercy','mild','minority','misunderstand','monitor','moral','motivate','mysterious','narrow','necessary','negotiate','nervous','normal','notice','numerous','observe','obstacle','obvious','operate','opinion','oppose','ordinary','organize','original','overcome','participate','particular','partner','passenger','patience','perfect','perform','permit','persuade','phenomenon','physical','pleasure','poison','polish','political','popular','population','portion','possess','potential','poverty','practical','precious','predict','prefer','prepare','preserve','pretend','prevent','principle','private','probable','proceed','produce','profit','progress','prohibit','promise','promote','proper','protect','protest','proud','provide','publish','punctual','punish','purpose','pursue','qualify','quality','quantity','rapid','rare','realize','reasonable','recognize','recommend','recover','reduce','refer','reflect','regular','reject','relate','relative','relax','relevant','reliable','relief','remain','remark','remarkable','remove','replace','reputation','request','require','research','reserve','resign','resist','resolve','respect','respond','responsible','restore','result','reveal','review','reward','ridiculous','risk','satisfy','scare','schedule','secure','select','sensitive','separate','serious','service','settle','severe','shadow','shallow','shelter','signal','significance','similar','simple','slight','social','somehow','sorrow','source','specific','spiritual','stable','standard','starve','struggle','stubborn','succeed','suffer','sufficient','suggest','suitable','supply','support','suppose','surprise','surround','survive','suspect','symbol','sympathy','system','talent','temperature','temporary','tend','thorough','threaten','tolerate','tough','tradition','transform','tremble','trend','trial','trick','typical','undergo','unique','universal','urban','urge','value','various','victim','violence','virtue','visual','voluntary','volunteer','wander','welfare','widespread','willing','wisdom','witness','worthwhile',
    ]
  },
  '高考基础': {
    min: 1600, max: 2800, words: [
      'abandon','abolish','abroad','abrupt','absence','absolute','absorb','abstract','absurd','abundant','academic','accelerate','accessible','accommodate','accompany','accomplish','accountant','accumulate','accurate','acknowledge','acquire','adapt','adequate','adjust','administration','adopt','aggressive','allocate','alternative','amateur','ambition','analyze','ancestor','anniversary','annual','anticipate','anxiety','apparent','appeal','appetite','applaud','applicant','appoint','approach','appropriate','approve','architecture','arise','arrange','artificial','assess','assign','associate','assume','atmosphere','attach','attempt','authentic','authority','automatic','available','avenue','average','aware','awkward','bargain','barrier','behalf','behave','beneficial','betray','billion','biography','blanket','boundary','budget','burden','calculate','campaign','candidate','capable','capacity','capture','career','catalog','category','caution','ceremony','certificate','champion','characteristic','circumstance','civilization','clarify','classic','classify','collapse','colleague','commercial','commission','commit','committee','companion','compensate','competence','complaint','complex','component','compose','comprehension','compromise','concentrate','concept','concrete','condition','conduct','confidential','confirm','conflict','conscience','conscious','consequence','conservative','considerate','consistent','constant','constitution','construct','consumption','contemporary','contradict','controversial','convenience','conventional','convince','cooperate','correspond','council','criterion','criticize','crucial','cultivate','curiosity','curriculum','deadline','declaration','dedicate','definitely','definition','delegate','deliberate','delicate','democratic','demonstrate','deposit','depression','derive','desperate','destination','dignity','dilemma','dimension','diploma','disability','discipline','discrimination','dismiss','distinction','distinguish','distribute','diverse','domestic','dominate','donation','dramatic','duration','efficient','elaborate','election','elegant','eliminate','embassy','emerge','emergency','emphasis','encounter','endeavor','enforce','enormous','enterprise','enthusiasm','essential','establish','evaluate','evolution','exaggerate','exceed','exception','execute','exhibition','expansion','expense','exploit','extension','extraordinary','facility','faith','fascinating','fatal','flexible','forecast','foundation','fragile','framework','friction','fulfill','fundamental','generate','genuine','govern','graceful','gradual','grateful','guarantee','guidance','harmony','highlight','horizon','household','identical','identity','illustrate','immigrant','impact','implement','implication','impose','incident','incorporate','infect','inflation','ingredient','initiative','innovation','input','inspection','institute','instrument','insurance','integrate','integrity','intellectual','intense','interact','interpret','interrupt','investigation','investment','isolate','jealous','justice','justify','landscape','launch','legislation','liberty','limitation','literature','logical','magnificent','maintain','manufacture','mature','maximum','mechanism','memorial','minimum','moderate','monument','motivation','negotiate','nightmare','nutrition','objective','obligation','occupation','opponent','opportunity','optimistic','origin','outcome','outstanding','overlook','ownership','parliament','passion','patent','patience','patriotic','pension','perceive','permanent','perspective','phenomenon','philosophy','pile','platform','pledge','portion','portrait','possess','potential','precaution','precise','prejudice','premier','prescribe','preserve','primitive','principle','priority','procedure','profession','prohibit','prominent','proportion','prospect','prosperity','psychology','publication','purchase','qualification','radiation','random','reception','reckon','recognition','recommend','recreation','registration','regulate','relevant','reputation','resemble','resolution','restore','restriction','reveal','revenue','revolution','routine','sacrifice','satellite','satisfaction','scholarship','senator','sensitive','sequence','significance','sketch','souvenir','specialist','specify','splendid','sponsor','statistics','status','stimulate','strategy','subjective','submit','subscribe','substitute','sufficient','summarize','superior','supplement','surrender','suspect','suspicion','sustainable','symbol','sympathy','tackle','temporary','tendency','territory','testify','therapy','tolerate','tournament','tragedy','transform','transition','transparent','tremendous','triumph','ultimate','undergo','undertake','unemployment','unique','universal','urban','utilize','valid','verify','version','vessel','veteran','violate','vivid','voluntary','vulnerable','widespread','withdraw','witness','worthwhile',
    ]
  },
  '高考进阶': {
    min: 2800, max: 3800, words: [
      'abolish','abortion','abrupt','absorb','abstract','absurd','abundance','accessory','accommodate','accountability','accumulate','acquaintance','acupuncture','addictive','adolescent','adverse','advocate','aesthetic','aggregate','agony','allege','alleviate','allocate','ambiguous','amend','analogy','anonymous','apparatus','appraisal','aptitude','array','articulate','ascend','ascribe','assassinate','assault','assert','assimilate','astronomy','athletic','atlas','attorney','audit','authentic','authorize','aviation','bankruptcy','barren','bearing','bibliography','bilateral','biochemistry','bishop','bizarre','blaze','blessing','blossom','boycott','breakdown','brewery','brochure','bronze','browse','bruise','brutal','bureaucracy','calorie','cardinal','casualty','catastrophe','cater','cathedral','Catholic','caution','census','champagne','chant','cherish','cholesterol','chronic','chunk','circulation','cite','civic','clamp','clan','clarity','clash','clasp','cloak','clockwise','cluster','coalition','cognitive','coherent','coincide','collaborate','collision','colonial','comet','commemorate','commence','commend','commentary','commitment','commodity','commonplace','commute','compact','compatible','compel','compensate','compilation','complement','complication','comply','compulsory','concede','conceive','conception','concise','condemn','condense','confer','confidential','configuration','conform','confront','congress','conquest','conscientious','consecutive','consensus','console','consolidate','conspicuous','constituent','constrain','contaminate','contemplate','contempt','contend','continuity','contradiction','contrive','convene','conversion','convict','cooperative','cordial','corporate','corpse','correlate','corrode','corrupt','cosmetic','counsel','counterpart','courtesy','cradle','credential','cripple','crisp','criterion','crucial','cruise','culminate','cumulative','curb','cynical','dazzle','deadline','decree','dedicate','deduce','deduct','default','defendant','defiance','deficiency','defy','delegate','deliberate','demographic','denial','denounce','depict','deploy','depreciate','depress','deprive','designate','destined','detach','detain','deteriorate','diagnose','differentiate','diffuse','dignity','dilemma','diligent','dilute','diminish','diploma','directory','disable','disastrous','discern','discharge','disclose','discourse','discrepancy','discrete','discriminate','disperse','displace','disposition','disregard','disrupt','dissipate','distil','distort','diversion','dividend','divine','dock','doctrine','domain','dome','drainage','drastic','drawback','drought','dubious','duplicate','dwarf','dwell','ecological','ecosystem','eject','elapse','elevate','elicit','eligible','elite','eloquent','embark','embed','embody','emigrate','emission','empirical','enact','enclose','endanger','endow','enforcement','enlighten','enrich','enrol','ensemble','entail','entrepreneur','envisage','epidemic','epoch','equator','equivalent','erosion','erroneous','erupt','escort','essence','esteem','eternal','evacuate','evaporate','evoke','exceedingly','excerpt','exempt','exile','exotic','expedition','expenditure','expertise','expire','explicit','exposition','exquisite','extinct','extinguish','extract','extravagant','fabricate','facet','facilitate','feminine','ferry','finite','fiscal','fixture','flaw','foam','foil','foremost','formidable','formulate','foster','fracture','friction','fringe','furious','fusion','futile','galaxy','gasp','gauge','gender','genetic','gigantic','glacier','glamour','gland','gleam','glitter','gloom','gorgeous','gossip','grant','graphic','graze','grieve','grim','grin','groan','guerrilla','gymnasium','habitat','hail','hamper','handicap','harassment','harsh','haul','haunt','hazard','heed','hemisphere','henceforth','herb','heritage','hierarchy','hike','hinder','hitherto','hoist','homogeneous','hospitality','hostage','hover','huddle','humanity','humidity','hurl','hurricane','hypothesis','ideology','idiot','ignite','illuminate','illusion','immerse','immune','impair','impart','imperative','imperial','impetus','implement','implicit','impulse','inaugurate','incentive','incidence','inclination','inclusive','incorporate','incur','indefinite','indicative','indignant','indispensable','induce','indulge','inertia','infectious','inflict','ingenious','inherent','inhibit','initiate','inject','inlet','innovation','innumerable','insane','instantaneous','intact','integral','integrity','intellect','intelligible','intensify','interim','intermittent','intersection','intervene','intimidate','intricate','intrinsic','intuition','invalid','invaluable','invariably','inventory','invert','irony','irrespective','irrigation','irritate','ivory','jeopardize','judicial','junction','jurisdiction','juvenile','kidnap','kit','knit','knob','lace','lame','latitude','layman','leaflet','legacy','legend','legislation','legitimate','lever','levy','liability','likelihood','limb','linear','linger','literacy','locomotive','longitude','loom','lounge','lubricate','luminous','lunar','magnify','manifest','manipulate','manoeuvre','manuscript','marginal','marsh','marshal','masculine','massacre','masterpiece','meadow','mechanism','mediate','medieval','melody','memorandum','menace','merge','metaphor','metropolitan','midst','migrant','militant','mingle','miniature','minimize','misery','missionary','mob','mobilize','mock','momentum','monetary','monopoly','monster','mortal','mortgage','murmur','muscular','mute','mutter','naive','narrative','nasty','necessitate','negligible','negotiate','nominal','nominate','nonetheless','norm','notable','notorious','notwithstanding','nourish','novelty','nurture','oath','obedient','obligation','obscene','obscure','odor','offset','olive','opaque','ordeal','orient','oriental','orientation','originate','ornament','orthodox','outbreak','outfit','outrage','overflow','overhear','overlap','overt','overthrow','overturn','overwhelm','oxide','pamphlet','paradise','paradox','parameter','parasite','pastime','pasture','pathetic','patrol','patron','pedestrian','penalty','pendulum','penetrate','perfection','perfume','periodic','perish','permeate','permissible','perpetual','perplex','persistent','petition','petty','pharmacy','physiological','pilgrim','pirate','plea','plead','plight','plumber','plunge','poke','polar','ponder','porcelain','portray','posterity','posture','practitioner','preach','precede','precedent','precision','predominant','premier','premise','premium','prescription','preside','prestige','presume','pretext','prevalent','prey','probe','proceeding','proclaim','productive','proficiency','profound','progressive','prolong','promising','prone','propaganda','propel','prophet','proposition','prosecute','prospective','prototype','provocative','provoke','proximity','prune','psychiatrist','pumpkin','purify','pursuit','qualitative','quantify','quantitative','quest','quota','radiant','rally','rating','reap','reassure','recede','recipient','reciprocal','recite','reckless','reclaim','reconcile','rectify','recur','redundant','referee','refrain','refuge','refund','refute','regime','rein','rejoice','relay','relentless','remainder','renaissance','repay','repel','repertoire','repression','reproach','resemblance','resent','reside','residential','resonance','restrain','resultant','retain','retort','retrieve','retrospect','revelation','revenge','revive','rhetoric','rigorous','rim','rip','ritual','robust','rot','sacred','safeguard','salute','savage','scandal','scramble','scrap','scrutiny','sculpture','seam','segment','segregate','sentiment','sergeant','serial','shabby','shatter','shepherd','shove','shrewd','shuttle','siege','sieve','signify','silicon','simulate','simultaneously','sip','skeleton','skeptical','skip','slash','slaughter','slot','smuggle','snatch','soar','sociology','solemn','solidarity','solo','sovereign','spacious','sparkle','speciality','specification','spectacle','spectator','spectrum','spice','spiral','splash','spokesman','spontaneous','stabilize','stagger','stalk','stall','stance','staple','statesman','stationary','stereo','stereotype','stern','steward','stitch','straightforward','strand','stray','streamline','stride','strive','stroll','stumble','sturdy','submarine','subordinate','substantial','subtle','successor','sue','suffice','suite','summit','summon','superb','superficial','superintendent','supersonic','surge','susceptible','suspension','suspicious','swamp','symmetry','symphony','symposium','syndrome','synthesis','tablet','tactics','tangle','tariff','tease','tedious','temperament','tempt','tenant','tentative','terrain','testify','testimony','texture','thereafter','thermal','threshold','thrill','throne','tick','tile','tilt','token','toll','torment','toss','toxic','trait','transaction','transcend','transient','transit','traverse','trench','tribe','tribute','trifle','trigger','triple','tropical','tuck','tug','tuition','tumble','turbulent','turnover','ultraviolet','unanimous','underestimate','underlying','undermine','unfold','unify','update','upgrade','uphold','utilize','utmost','vacuum','validity','valve','vegetation','vein','velocity','velvet','ventilate','venture','verdict','verge','versatile','verse','veto','vicious','vocal','vocational','void','vulgar','vulnerable','wardrobe','warehouse','warfare','warrant','watertight','weary','weird','whereby','whirl','wholesale','wither','wreck','yell','zeal',
    ]
  },
  '大学四级': {
    min: 3800, max: 5500, words: [
      'aberration','abrogate','accolade','acquiesce','acrimony','admonish','aesthetic','affable','aggrandize','alacrity','amalgamate','ambidextrous','ameliorate','anachronism','anathema','antediluvian','antithesis','apathetic','aplomb','approbation','arbitrary','arduous','articulate','asperity','assiduous','attenuate','auspicious','avarice','bellicose','belligerent','benevolent','bequeath','besmirch','bifurcate','bilious','blandishment','blasphemy','boisterous','bombastic','brevity','bucolic','cacophony','callous','calumny','candor','capitulate','capricious','castigate','catalyst','caustic','chagrin','charlatan','chicanery','circumlocution','circumspect','clamor','clandestine','clemency','coercion','cogent','commensurate','complacent','complaisant','conciliatory','concomitant','condescend','confound','congenial','conjecture','connoisseur','consternation','contentious','contrite','conundrum','copious','corroborate','credulous','culpable','cursory','dauntless','debacle','decorum','deference','delineate','demagogue','demure','denigrate','deprecate','derelict','desiccate','despondent','destitute','diaphanous','diatribe','dichotomy','diffident','dilatory','diminution','disaffected','discomfit','discursive','disparage','disseminate','dissolution','docile','dogmatic','draconian','dubiety','ebullient','edify','effervescent','efficacious','egregious','elegy','elucidate','emaciated','embellish','emollient','empirical','encomium','endemic','enervate','engender','ephemeral','equanimity','equivocate','erudite','esoteric','ethereal','euphemism','evanescent','exacerbate','excoriate','execrable','exigent','exonerate','expatriate','expeditious','extol','facetious','fallacious','fastidious','fatuous','fecund','felicitous','fervent','flippant','florid','forbearance','fortuitous','fractious','frivolous','fulsome','garrulous','gauche','germane','grandiloquent','gregarious','hackneyed','hapless','harangue','hedonism','hegemony','hermetic','hubris','iconoclast','idiosyncratic','ignominious','imbroglio','immutable','impartial','impecunious','imperious','impertinent','impervious','impetuous','implacable','impudent','impugn','inchoate','incipient','incorrigible','indolent','ineffable','ineluctable','inexorable','ingenuous','inimical','innocuous','inscrutable','insidious','insolvent','intransigent','intrepid','inundate','inveterate','irascible','irreverent','itinerant','juxtapose','kudos','laconic','lambaste','languid','largesse','lassitude','lethargic','levity','litigious','loquacious','lugubrious','magnanimous','malfeasance','malinger','mendacious','mercurial','meretricious','metamorphosis','meticulous','misanthrope','mitigate','mollify','moribund','munificent','myopic','nebulous','nefarious','neophyte','nexus','nonchalant','noxious','obdurate','obfuscate','oblique','obsequious','obsolete','obstinate','officious','omnipotent','omniscient','onerous','opprobrious','ostentatious','palliative','panacea','paradigm','paragon','pariah','parsimonious','partisan','paucity','pedantic','pejorative','penchant','penurious','perennial','perfidious','perfunctory','peripatetic','pernicious','perspicacious','pertinacious','petulant','philanthropic','phlegmatic','placate','platitude','plethora','polemic','pragmatic','precarious','precipitous','preclude','precocious','predilection','preponderance','prescient','presumptuous','prevaricate','primordial','proclivity','prodigious','profligate','prognosticate','proletariat','promulgate','propensity','propitious','prosaic','proscribe','protean','protuberant','provincial','pugnacious','punctilious','pundit','quagmire','quandary','querulous','quintessential','quixotic','quotidian','rancor','rapacious','rarefied','recalcitrant','recant','recondite','redoubtable','refractory','relegate','remonstrate','renascent','repartee','replete','reprobate','reprove','repudiate','requisite','rescind','resilient','resplendent','restive','resurgent','reticent','retrograde','revile','ribald','rife','ruminate','rustic','sagacious','salient','sanctimonious','sanguine','sardonic','savant','scintillate','scrupulous','sedentary','seminal','serendipity','servile','sibilant','solicitous','somnolent','sophistry','specious','sporadic','spurious','squalid','stolid','stringent','strident','subjugate','subliminal','subterfuge','succinct','suffrage','sundry','supercilious','supine','supplicate','surfeit','surreptitious','sycophant','taciturn','tangible','tantamount','temerity','tempestuous','tenacious','tendentious','terse','torpid','tractable','transgress','transitory','trenchant','trepidation','truculent','turgid','ubiquitous','umbrage','unctuous','unequivocal','unprecedented','unscrupulous','upbraid','urbane','usurp','vacillate','vapid','vehement','venal','venerable','verbose','verdant','verisimilitude','vicarious','vicissitude','vigilant','vilify','vindicate','virtuoso','viscous','vitriolic','vituperate','vivacious','vociferous','volatile','voracious','wanton','winsome','wizened','xenophobia','zealous','zenith',
    ]
  }
};

// Grade → bands mapping for test composition
const GRADE_VOCAB_PLAN = {
  '高一': { label: '高一（目标~2000词，高考基础起步）', bands: [
    { name: '中考核心', count: 20, weight: 0.25 },
    { name: '高考基础', count: 24, weight: 0.45 },
    { name: '高考进阶', count: 16, weight: 0.30 },
  ]},
  '高二': { label: '高二（目标~2800词，高考进阶为主）', bands: [
    { name: '中考核心', count: 10, weight: 0.15 },
    { name: '高考基础', count: 20, weight: 0.35 },
    { name: '高考进阶', count: 24, weight: 0.40 },
    { name: '大学四级', count: 6, weight: 0.10 },
  ]},
  '高三': { label: '高三（目标~3500词，冲刺高考）', bands: [
    { name: '高考基础', count: 16, weight: 0.25 },
    { name: '高考进阶', count: 30, weight: 0.55 },
    { name: '大学四级', count: 14, weight: 0.20 },
  ]},
};

let _vtState = null;

function startVocabTest(prefix) {
  // Determine grade: onboarding uses onb-grade, student modal uses f-grade
  const gradeEl = document.getElementById(prefix === 'onb' ? 'onb-grade' : 'f-grade');
  const grade = gradeEl ? gradeEl.value : '高二';
  const plan = GRADE_VOCAB_PLAN[grade] || GRADE_VOCAB_PLAN['高二'];

  // Build test words
  const words = [];
  plan.bands.forEach(band => {
    const pool = VOCAB_BANKS[band.name];
    if (!pool) return;
    const shuffled = [...pool.words].sort(() => Math.random() - 0.5);
    for (let i = 0; i < Math.min(band.count, shuffled.length); i++) {
      words.push({ word: shuffled[i], band: band.name });
    }
  });
  // Shuffle the test order
  words.sort(() => Math.random() - 0.5);

  _vtState = {
    prefix,
    grade,
    plan,
    words,
    currentIdx: 0,
    answers: [],       // {word, band, known: bool}
    total: words.length,
  };

  // Setup intro screen
  document.getElementById('vt-title').textContent = '📝 词汇量快测';
  document.getElementById('vt-grade-hint').textContent = plan.label;
  document.getElementById('vt-total-q').textContent = words.length;
  document.getElementById('vt-grade-label').textContent = grade;
  document.getElementById('vt-intro').style.display = 'block';
  document.getElementById('vt-testing').style.display = 'none';
  document.getElementById('vt-result').style.display = 'none';
  document.getElementById('vocab-test-modal').classList.add('show');
}

function beginVocabTest() {
  document.getElementById('vt-intro').style.display = 'none';
  document.getElementById('vt-testing').style.display = 'block';
  showVocabWord();
}

function showVocabWord() {
  const st = _vtState;
  if (st.currentIdx >= st.total) { finishVocabTest(); return; }
  const item = st.words[st.currentIdx];
  document.getElementById('vt-word').textContent = item.word;
  document.getElementById('vt-progress-text').textContent = `${st.currentIdx + 1}/${st.total}`;
  document.getElementById('vt-bar').style.width = `${((st.currentIdx) / st.total) * 100}%`;
  document.getElementById('vt-band-hint').textContent = '';
}

function answerVocab(known) {
  const st = _vtState;
  const item = st.words[st.currentIdx];
  st.answers.push({ word: item.word, band: item.band, known });
  st.currentIdx++;
  if (st.currentIdx >= st.total) {
    finishVocabTest();
  } else {
    showVocabWord();
  }
}

function finishVocabTest() {
  document.getElementById('vt-testing').style.display = 'none';
  document.getElementById('vt-result').style.display = 'block';

  const st = _vtState;
  // Calculate per-band stats
  const bandStats = {};
  st.answers.forEach(a => {
    if (!bandStats[a.band]) bandStats[a.band] = { total: 0, known: 0 };
    bandStats[a.band].total++;
    if (a.known) bandStats[a.band].known++;
  });

  // Estimate vocab size: weighted sum of band midpoints * recognition rate
  let estVocab = 0;
  let totalWeight = 0;
  Object.entries(bandStats).forEach(([bandName, stats]) => {
    const band = VOCAB_BANKS[bandName];
    if (!band) return;
    const rate = stats.known / stats.total;
    const mid = (band.min + band.max) / 2;
    const weight = stats.total;
    estVocab += mid * rate * weight;
    totalWeight += weight;
  });
  estVocab = Math.round(estVocab / Math.max(totalWeight, 1));

  // Map to level
  let level, levelColor;
  if (estVocab < 1600) { level = '基础偏弱'; levelColor = 'var(--red)'; }
  else if (estVocab < 2500) { level = '基础尚可'; levelColor = 'var(--accent)'; }
  else if (estVocab < 3300) { level = '中上水平'; levelColor = 'var(--blue)'; }
  else { level = '词汇较强'; levelColor = 'var(--green)'; }

  document.getElementById('vt-est-vocab').textContent = estVocab;
  document.getElementById('vt-level-badge').innerHTML = `<span style="display:inline-block;padding:4px 16px;border-radius:16px;font-weight:600;background:${levelColor}20;color:${levelColor};">${level}</span>`;

  // Per-band detail
  const bandOrder = ['中考核心','高考基础','高考进阶','大学四级'];
  document.getElementById('vt-band-detail').innerHTML = bandOrder.filter(b => bandStats[b]).map(b => {
    const s = bandStats[b];
    const rate = Math.round(s.known / s.total * 100);
    const barColor = rate >= 80 ? 'var(--green)' : rate >= 50 ? 'var(--accent)' : 'var(--red)';
    return `<div style="margin-bottom:8px;">
      <div style="display:flex;justify-content:space-between;font-size:.85em;"><span>${b}</span><span>${s.known}/${s.total} (${rate}%)</span></div>
      <div class="progress-bar" style="height:6px;margin-top:2px;"><div class="fill" style="width:${rate}%;background:${barColor};"></div></div>
    </div>`;
  }).join('');

  _vtState.estVocab = estVocab;
  _vtState.level = level;
}

function applyVocabResult() {
  const prefix = _vtState.prefix;
  const selId = prefix === 'onb' ? 'onb-vocab-level' : 'f-vocab-level';
  const sel = document.getElementById(selId);
  if (sel) sel.value = _vtState.level;
  closeVocabTest();
  toast(`词汇测评完成：估算 ${_vtState.estVocab} 词，等级「${_vtState.level}」`);
}

function closeVocabTest() {
  document.getElementById('vocab-test-modal').classList.remove('show');
}

// ── Navigation ──
function switchPage(name) {
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.nav button').forEach(b=>b.classList.remove('active'));
  document.getElementById('page-'+name).classList.add('active');
  const navBtn = document.querySelector(`.nav button[data-page="${name}"]`);
  if (navBtn) navBtn.classList.add('active');
  if (name==='dashboard') loadDashboard();
  if (name==='students') loadStudents();
  if (name==='weekly') loadWeeklyPage();
  if (name==='analytics') loadAnalyticsPage();
  if (name==='bank') loadBankPage();
  if (name==='quality') loadQualityPage();
  if (name==='referrals') loadReferralsPage();
  if (name==='classes') loadClassesPage();
  if (name==='admin') loadAdminPage();
  if (name==='observability') loadObservabilityPage();
  if (name==='compliance') loadCompliance();
  if (name==='teacher-profile') loadTeacherProfilePage();
}

// ── Dashboard ──
async function loadDashboard() {
  const r = await fetch('/api/dashboard'); const d = await r.json();
  document.getElementById('stats-bar').innerHTML = `
    <div class="stat"><div class="num">${d.total_students}</div><div class="label">总学生数</div></div>
    <div class="stat ok"><div class="num">${d.active_subscriptions}</div><div class="label">有效订阅</div></div>
    <div class="stat info"><div class="num">${d.trial_count}</div><div class="label">试用中</div></div>
    <div class="stat warn"><div class="num">${d.pending_this_week}</div><div class="label">本周待处理</div></div>
    <div class="stat" style="background:var(--blue-light);"><div class="num" style="color:var(--blue);">${d.question_bank ? d.question_bank.total_questions : 0}</div><div class="label">题库题目</div></div>
  `;
  document.getElementById('week-label').textContent = '周期：' + d.week_start + ' 起';

  // Review queue
  const rcount = d.review_queue ? d.review_queue.length : 0;
  const rbadge = document.getElementById('review-count');
  if (rcount > 0) { rbadge.style.display = 'inline-block'; rbadge.textContent = rcount; }
  else { rbadge.style.display = 'none'; }
  const rtbody = document.querySelector('#review-table tbody');
  rtbody.innerHTML = '';
  (d.review_queue||[]).forEach(t => {
    let out = {}; let inp = {};
    try { out = JSON.parse(t.output_data || '{}'); } catch(e) {}
    try { inp = JSON.parse(t.input_data || '{}'); } catch(e) {}
    const rid = out.report_file_id || '';
    const mc = out.mistakes_count || '';
    const pids = out.file_ids || inp.file_ids || [];
    const pid = inp.file_id || (pids.length ? pids[0] : '');
    const sid = out.student_id || inp.student_id || '';
    const corrBadge = t.correction_count
      ? ` <span style="background:var(--accent-light);color:var(--accent);padding:2px 6px;border-radius:4px;font-size:.75em;">已纠错 ${t.correction_count} 条</span>`
      : '';
    const scoreHtml = mc ? `<br><a href="javascript:void(0)" onclick="viewStudentAnalytics(${sid})" style="font-size:.8em;color:var(--accent);" title="查看学生错题本和学情">→ 查看 ${mc} 道错题</a>` : '';
    rtbody.innerHTML += `<tr>
      <td><input type="checkbox" class="review-checkbox" value="${t.id}"></td>
      <td><strong>${t.student_name||'?'}</strong><br><span style="color:var(--sub);font-size:.8em;">${t.grade||''}</span></td>
      <td>${t.task_type==='onboarding'?'入学诊断':'周度服务'} ${mc ? '('+mc+'道错题)' : ''}${corrBadge}${scoreHtml}</td>
      <td>${fmtDate(t.completed_at)}</td>
      <td style="white-space:nowrap;">
        ${pid ? `<a href="/api/files/${pid}/download" target="_blank" class="btn btn-sm btn-outline" style="text-decoration:none;" title="查看上传的原卷">📷 原卷</a> ` : ''}
        ${rid ? `<a href="/api/files/${rid}/download" target="_blank" class="btn btn-sm btn-outline" style="text-decoration:none;" title="查看AI生成的诊断报告">📄 报告</a> ` : ''}
        <button class="btn btn-sm btn-green" onclick="approveTask(${t.id})">✅ 通过</button>
        <button class="btn btn-sm btn-outline" onclick="openCorrectionPanel(${t.id})" title="逐条纠错">📝 纠错</button>
        <button class="btn btn-sm btn-outline" onclick="rejectTask(${t.id})" style="color:var(--red);" title="整体驳回重跑">🔁 驳回</button>
      </td>
    </tr>`;
  });

  // Teacher workload
  const tw = d.teacher_workload || {};
  document.getElementById('teacher-workload').innerHTML = `
    <div class="stat warn"><div class="num">${tw.pending_review || 0}</div><div class="label">待审核</div></div>
    <div class="stat ok"><div class="num">${tw.reviewed_today || 0}</div><div class="label">今日已通过</div></div>
    <div class="stat info"><div class="num">${tw.reviewed_this_week || 0}</div><div class="label">本周已处理</div></div>
    <div class="stat"><div class="num">${tw.recent_rejected || 0}</div><div class="label">本周驳回重跑</div></div>
  `;

  // Pending paper uploads
  const pptbody = document.querySelector('#pending-paper-table tbody');
  pptbody.innerHTML = '';
  if (tw.pending_paper_uploads && tw.pending_paper_uploads.length > 0) {
    tw.pending_paper_uploads.forEach(s => {
      pptbody.innerHTML += `<tr>
        <td><strong>${s.name}</strong></td>
        <td>${s.grade || ''}</td>
        <td><button class="btn btn-sm btn-primary" onclick="runWeeklyForStudent(${s.id})">去上传</button></td>
      </tr>`;
    });
  } else {
    pptbody.innerHTML = '<tr><td colspan="3" style="text-align:center;color:var(--sub);">🎉 所有学生本周已上传试卷</td></tr>';
  }

  // AI correction trend
  try {
    const cr = await fetch('/api/corrections/stats?days=7');
    const cs = await cr.json();
    const topPoints = (cs.top_knowledge_points || []).map(p =>
      `<span class="badge badge-blue" style="margin-right:6px;">${p.point} (${p.count})</span>`
    ).join('') || '<span style="color:var(--sub);">暂无</span>';
    document.getElementById('correction-trend').innerHTML = `
      <div class="stat"><div class="num">${cs.total || 0}</div><div class="label">纠错总数</div></div>
      <div class="stat ok"><div class="num">${cs.effective || 0}</div><div class="label">有效纠错</div></div>
      <div class="stat warn"><div class="num">${(cs.repeat_ratio * 100).toFixed(0)}%</div><div class="label">问题重复率</div></div>
      <div class="stat" style="flex:2; min-width:220px;"><div style="font-size:.9em;font-weight:600;margin-bottom:4px;">Top3 易错知识点</div><div>${topPoints}</div></div>
    `;
  } catch(e) { console.error('Correction stats load failed', e); }

  // Reset selection
  document.getElementById('select-all').checked = false;
  updateSelectedCount();

  // Subscription alerts
  const etbody = document.querySelector('#expiring-table tbody');
  etbody.innerHTML = '';
  if (d.expiring_subscriptions && d.expiring_subscriptions.length > 0) {
    d.expiring_subscriptions.forEach(s => {
      const days = s.days_remaining;
      const daysText = days === null ? '-' : (days < 0 ? `已过期 ${-days} 天` : (days === 0 ? '今天到期' : `剩余 ${days} 天`));
      const daysClass = days === null ? '' : (days < 3 ? 'color:var(--red);font-weight:600;' : (days < 7 ? 'color:var(--accent);' : 'color:var(--sub);'));
      etbody.innerHTML += `<tr>
        <td><strong>${s.name}</strong></td>
        <td>${s.grade||''}</td>
        <td><span class="badge badge-${s.plan||'trial'}">${s.plan_label||'试用'}</span></td>
        <td>${s.end_date||'-'}</td>
        <td style="${daysClass}">${daysText}</td>
        <td><button class="btn btn-sm btn-primary" onclick="manageSub(${s.id},'${s.name}')">续费</button></td>
      </tr>`;
    });
  } else {
    etbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--sub);">暂无到期提醒（7天内到期或已过期）</td></tr>';
  }

  // Pending
  const tbody = document.querySelector('#pending-table tbody');
  tbody.innerHTML = '';
  (d.pending||[]).forEach(s => {
    tbody.innerHTML += `<tr>
      <td><strong>${s.name}</strong></td><td>${s.grade}</td>
      <td><span class="badge badge-${s.plan||'trial'}">${s.plan_label||'试用'}</span></td>
      <td>${icon(s.paper_submitted)}</td><td>${icon(s.paper_analyzed)}</td>
      <td>${icon(s.exercises_sent)}</td><td>${icon(s.exercises_graded)}</td>
      <td>${icon(s.report_sent)}</td>
      <td><span style="color:var(--sub);font-size:.8em;">${s.exercises_sent?'已处理':'待上传试卷'}</span></td>
    </tr>`;
  });

  // Cost and budget
  try {
    const cr = await fetch('/api/cost'); const cd = await cr.json();
    document.getElementById('cost-today').textContent = cd.today.toFixed(4);
    document.getElementById('cost-month').textContent = cd.month.toFixed(4);
    document.getElementById('student-budget').textContent = cd.monthly_student_budget.toFixed(2);
    document.getElementById('budget-text').textContent = `$${cd.month.toFixed(2)} / $${cd.monthly_total_budget.toFixed(2)} (${cd.total_budget_used_pct}%)`;

    const bar = document.getElementById('budget-bar');
    bar.style.width = Math.min(cd.total_budget_used_pct, 100) + '%';
    bar.style.background = cd.total_budget_used_pct >= 100 ? 'var(--red)' : (cd.total_budget_used_pct >= 80 ? 'var(--accent)' : 'var(--green)');

    if (document.getElementById('budget-total')) document.getElementById('budget-total').value = cd.monthly_total_budget;
    if (document.getElementById('budget-student')) document.getElementById('budget-student').value = cd.monthly_student_budget;

    const ctbody = document.querySelector('#cost-breakdown-table tbody');
    ctbody.innerHTML = '';
    if (cd.breakdown && cd.breakdown.length > 0) {
      cd.breakdown.forEach(stu => {
        const pct = cd.monthly_student_budget > 0 ? (stu.cost / cd.monthly_student_budget * 100).toFixed(1) : 0;
        const costColor = stu.cost >= cd.monthly_student_budget ? 'color:var(--red);font-weight:600;' : 'color:var(--sub);';
        if (stu.cost > 0 || stu.calls > 0) {
          ctbody.innerHTML += `<tr>
            <td>${stu.name}</td>
            <td>${stu.calls}</td>
            <td style="${costColor}">$${stu.cost.toFixed(4)}</td>
            <td>${pct}%</td>
          </tr>`;
        }
      });
      if (ctbody.innerHTML === '') {
        ctbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--sub);">本月暂无 LLM 调用记录</td></tr>';
      }
    } else {
      ctbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--sub);">本月暂无 LLM 调用记录</td></tr>';
    }
  } catch(e) { console.error('Cost load failed', e); }

  // Active alerts banner
  try {
    await loadObservabilityAlerts('dashboard-alert-banner');
  } catch(e) { console.error('Alerts load failed', e); }

  // Recent failures quick tip
  try {
    const fr = await fetch('/api/tasks/recent-failures?limit=5');
    if (fr.ok) {
      const failures = await fr.json();
      const tip = document.getElementById('dashboard-failure-tip');
      if (failures.length > 0) {
        tip.style.display = 'block';
        document.getElementById('dashboard-failure-text').textContent =
          `⚠️ 近24小时有 ${failures.length} 个任务失败，点击查看详情`;
      } else {
        tip.style.display = 'none';
      }
    }
  } catch(e) { console.error('Failure tip load failed', e); }

  // Compliance alerts
  try {
    const banner = document.getElementById('dashboard-compliance-banner');
    const consentCount = d.students_without_consent || 0;
    const deletionCount = d.pending_deletions || 0;
    if (consentCount === 0 && deletionCount === 0) {
      banner.innerHTML = '';
    } else {
      const items = [];
      if (consentCount > 0) items.push(`⚠️ ${consentCount} 名学生未获得家长数据授权`);
      if (deletionCount > 0) items.push(`🗑️ ${deletionCount} 条数据删除申请待处理`);
      banner.innerHTML = `
        <div style="background:var(--accent-light);color:var(--accent);padding:10px 12px;border-radius:6px;font-size:.9em;display:flex;justify-content:space-between;align-items:center;">
          <span>${items.join(' · ')}</span>
          <button class="btn btn-sm btn-outline" onclick="switchPage('compliance')" style="margin-left:12px;">去处理</button>
        </div>`;
    }
  } catch(e) { console.error('Compliance banner load failed', e); }

  // System status
  try {
    const sr = await fetch('/api/status');
    if (sr.ok) {
      const sd = await sr.json();
      const demoBadge = sd.demo_mode
        ? '<span style="background:var(--accent-light);color:var(--accent);padding:2px 8px;border-radius:4px;font-size:.8em;margin-left:8px;">Demo 模式</span>'
        : '';
      const backendColor = sd.backend === 'demo' ? 'var(--accent)' : 'var(--green)';
      document.getElementById('system-status-card').innerHTML = `
        <div style="display:flex;flex-wrap:wrap;gap:16px;font-size:.9em;">
          <div><span style="color:var(--sub);">LLM 后端：</span><strong style="color:${backendColor};">${sd.backend}</strong>${demoBadge}</div>
          <div><span style="color:var(--sub);">默认模型：</span><strong>${sd.model}</strong></div>
          <div><span style="color:var(--sub);">OCR 后端：</span><strong>${sd.ocr_backend}</strong></div>
          <div><span style="color:var(--sub);">Vision 模型：</span><strong>${sd.vision_model}</strong></div>
        </div>
      `;
    }
  } catch(e) { console.error('Status load failed', e); }
}

// ── Students ──
async function loadStudents() {
  const r = await fetch('/api/students'); const students = await r.json();
  const tbody = document.querySelector('#students-table tbody');

  // Filter controls
  const filterPlan = document.getElementById('filter-plan')?.value || '';
  const filterStatus = document.getElementById('filter-status')?.value || '';
  const sortBy = document.getElementById('sort-by')?.value || 'name';

  let filtered = students;
  if (filterPlan) filtered = filtered.filter(s => (s.plan || 'trial') === filterPlan);
  if (filterStatus === 'active') filtered = filtered.filter(s => s.sub_status === 'active');
  if (filterStatus === 'expired') filtered = filtered.filter(s => s.sub_status === 'expired');
  if (filterStatus === 'soon') filtered = filtered.filter(s => s.days_remaining !== null && s.days_remaining >= 0 && s.days_remaining <= 7);

  filtered.sort((a, b) => {
    if (sortBy === 'name') return a.name.localeCompare(b.name, 'zh');
    if (sortBy === 'plan') return (a.plan || 'trial').localeCompare(b.plan || 'trial');
    if (sortBy === 'days_remaining') {
      const da = a.days_remaining === null ? 99999 : a.days_remaining;
      const db = b.days_remaining === null ? 99999 : b.days_remaining;
      return da - db;
    }
    return 0;
  });

  tbody.innerHTML = '';
  if (filtered.length === 0) {
    tbody.innerHTML = '<tr><td colspan="11" style="text-align:center;color:var(--sub);padding:40px 0;">没有符合条件的学生</td></tr>';
    return;
  }

  filtered.forEach(s => {
    const viewUrl = s.access_code ? `/s/${s.access_code}` : '';
    const validText = s.sub_end_date ? s.sub_end_date.slice(0,10) : (s.sub_status==='expired' ? '已过期' : '未设置');
    const days = s.days_remaining;
    const daysText = days === null ? '-' : (days < 0 ? `已过期 ${-days} 天` : (days === 0 ? '今天到期' : `剩余 ${days} 天`));
    const daysClass = days === null ? '' : (days < 3 ? 'color:var(--red);font-weight:600;' : (days < 7 ? 'color:var(--accent);' : 'color:var(--green);'));
    const rowStyle = days !== null && days < 3 ? 'background:rgba(255,59,48,0.05);' : (days !== null && days < 7 ? 'background:rgba(232,129,59,0.04);' : '');
    const statusText = s.sub_status==='active' ? '有效' : (s.sub_status==='paused' ? '暂停' : '过期');
    let statusBadgeClass = s.sub_status || 'active';
    if (s.sub_status !== 'expired' && days !== null && days >= 0 && days <= 7) statusBadgeClass = 'expiring';
    const costText = s.month_cost ? `$${s.month_cost.toFixed(4)}` : '-';
    const consentBadge = s.has_consent
      ? '<span style="color:var(--green);font-size:.85em;">✅ 已授权</span>'
      : '<span style="color:var(--accent);font-size:.85em;">⚠️ 待授权</span>';
    const consentBtn = s.has_consent
      ? ''
      : `<button class="btn btn-sm btn-outline" onclick="recordConsentFromStudent(${s.id}, '${escapeHtml(s.name)}')" style="margin-top:4px;">补授权</button>`;
    tbody.innerHTML += `<tr style="${rowStyle}">
      <td><strong>${s.name}</strong>${viewUrl ? `<br><a href="${viewUrl}" target="_blank" style="font-size:.75em;color:var(--blue);">📎 学生页</a>` : ''}</td>
      <td>${s.grade}</td><td>${s.school_type}</td>
      <td>${s.english_score||'-'}</td><td>${s.target_score||'-'}</td>
      <td><span class="badge badge-${s.plan||'trial'}">${s.plan_label||'试用'}</span></td>
      <td style="font-size:.85em;">
        <div>${validText}</div>
        <div style="${daysClass}font-size:.78em;margin-top:2px;">${daysText}</div>
      </td>
      <td><span class="badge badge-${statusBadgeClass}">${statusText}</span></td>
      <td>${consentBadge}<br>${consentBtn}</td>
      <td style="font-size:.85em;color:var(--sub);">${costText}</td>
      <td>
        <button class="btn btn-sm btn-outline" onclick="editStudent(${s.id})">编辑</button>
        <button class="btn btn-sm btn-outline" onclick="manageSub(${s.id},'${s.name}')">订阅</button>
        <button class="btn btn-sm btn-outline" onclick="requestDeletion(${s.id}, '${escapeHtml(s.name)}')" style="color:var(--red);">删除申请</button>
      </td>
    </tr>`;
  });
}

async function recordConsentFromStudent(studentId, studentName) {
  const consentedBy = prompt(`补录 ${studentName} 的家长授权\n请输入家长姓名（必填）：`);
  if (!consentedBy || !consentedBy.trim()) return;
  const contact = prompt(`请输入家长联系方式（手机/微信，可选）：`) || '';
  const notes = prompt(`备注（可选）：`) || '';
  const r = await fetch('/api/compliance/consents', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({student_id: studentId, consented_by: consentedBy, contact, notes}),
  });
  if (r.ok) {
    toast('家长授权已记录');
    loadStudents();
    loadDashboard();
  } else {
    toast('授权记录失败', 'error');
  }
}

async function requestDeletion(studentId, studentName) {
  const reason = prompt(`申请删除 ${studentName} 的学习数据\n请输入删除原因（可选）：`) || '';
  if (!confirm('确定要提交数据删除申请吗？提交后需管理员审核执行。')) return;
  const r = await fetch('/api/compliance/deletion-requests', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({student_id: studentId, reason}),
  });
  if (r.ok) {
    toast('删除申请已提交');
    loadCompliance();
    loadDashboard();
  } else {
    toast('提交失败', 'error');
  }
}

// ── Time Map Editor ──
let timeMapSlots = [];

function renderTimeMapSlots() {
  const tbody = document.getElementById('time-map-slots');
  if (!tbody) return;
  const natureColors = { immovable: 'var(--red-light)', hobby: 'var(--green-light)', available: 'var(--accent-light)', fragment: 'var(--blue-light)' };
  const natureLabels = { immovable: '🔴 不可动', hobby: '🟢 爱好', available: '⭐ 可用', fragment: '🔵 碎片' };
  tbody.innerHTML = timeMapSlots.map((slot, idx) => `
    <tr data-idx="${idx}" style="border-bottom:1px solid var(--border);">
      <td style="padding:4px;">
        <select class="tm-day" style="width:72px;font-size:.85em;">
          ${['周一','周二','周三','周四','周五','周六','周日'].map(d => `<option value="${d}" ${slot.day===d?'selected':''}>${d}</option>`).join('')}
        </select>
      </td>
      <td style="padding:4px;"><input class="tm-start" type="time" value="${slot.start||''}" style="width:100px;font-size:.85em;"></td>
      <td style="padding:4px;"><input class="tm-end" type="time" value="${slot.end||''}" style="width:100px;font-size:.85em;"></td>
      <td style="padding:4px;"><input class="tm-content" value="${escapeHtml(slot.content||'')}" placeholder="如：晚自习" style="width:120px;font-size:.85em;"></td>
      <td style="padding:4px;">
        <select class="tm-nature" style="width:88px;font-size:.85em;background:${natureColors[slot.nature||'available']};">
          ${Object.entries(natureLabels).map(([k,l]) => `<option value="${k}" ${slot.nature===k?'selected':''}>${l}</option>`).join('')}
        </select>
      </td>
      <td style="padding:4px;">
        <select class="tm-energy" style="width:80px;font-size:.85em;">
          <option value="peak" ${slot.energy==='peak'?'selected':''}>高峰</option>
          <option value="okay" ${slot.energy==='okay'?'selected':''}>尚可</option>
          <option value="normal" ${slot.energy==='normal'?'selected':''}>一般</option>
        </select>
      </td>
      <td style="padding:4px;text-align:center;">
        <button class="btn btn-sm" onclick="removeTimeSlot(${idx})" style="color:var(--red);font-size:.8em;" title="删除">×</button>
      </td>
    </tr>
  `).join('');
  tbody.querySelectorAll('.tm-nature').forEach(sel => {
    sel.addEventListener('change', function() {
      const colors = { immovable: 'var(--red-light)', hobby: 'var(--green-light)', available: 'var(--accent-light)', fragment: 'var(--blue-light)' };
      this.style.background = colors[this.value] || '';
    });
  });
}

function addTimeSlot() {
  timeMapSlots.push({ day: '周一', start: '', end: '', content: '', nature: 'available', energy: 'normal' });
  renderTimeMapSlots();
}

function removeTimeSlot(idx) {
  timeMapSlots.splice(idx, 1);
  renderTimeMapSlots();
}

function collectTimeMap() {
  const rows = document.querySelectorAll('#time-map-slots tr');
  const slots = [];
  rows.forEach(row => {
    slots.push({
      day: row.querySelector('.tm-day').value,
      start: row.querySelector('.tm-start').value,
      end: row.querySelector('.tm-end').value,
      content: row.querySelector('.tm-content').value.trim(),
      nature: row.querySelector('.tm-nature').value,
      energy: row.querySelector('.tm-energy').value,
    });
  });
  return {
    description: document.getElementById('f-time-map-desc').value.trim(),
    slots: slots,
  };
}

// ── Onboarding Time Map ──
let onbTimeMapSlots = [];

function renderOnbTimeMapSlots() {
  const tbody = document.getElementById('onb-time-map-slots');
  if (!tbody) return;
  const natureColors = { immovable: 'var(--red-light)', hobby: 'var(--green-light)', available: 'var(--accent-light)', fragment: 'var(--blue-light)' };
  const natureLabels = { immovable: '🔴 不可动', hobby: '🟢 爱好', available: '⭐ 可用', fragment: '🔵 碎片' };
  tbody.innerHTML = onbTimeMapSlots.map((slot, idx) => `
    <tr data-idx="${idx}" style="border-bottom:1px solid var(--border);">
      <td style="padding:4px;">
        <select class="onb-tm-day" style="width:72px;font-size:.85em;">
          ${['周一','周二','周三','周四','周五','周六','周日'].map(d => `<option value="${d}" ${slot.day===d?'selected':''}>${d}</option>`).join('')}
        </select>
      </td>
      <td style="padding:4px;"><input class="onb-tm-start" type="time" value="${slot.start||''}" style="width:100px;font-size:.85em;"></td>
      <td style="padding:4px;"><input class="onb-tm-end" type="time" value="${slot.end||''}" style="width:100px;font-size:.85em;"></td>
      <td style="padding:4px;"><input class="onb-tm-content" value="${escapeHtml(slot.content||'')}" placeholder="如：晚自习" style="width:120px;font-size:.85em;"></td>
      <td style="padding:4px;">
        <select class="onb-tm-nature" style="width:88px;font-size:.85em;background:${natureColors[slot.nature||'available']};">
          ${Object.entries(natureLabels).map(([k,l]) => `<option value="${k}" ${slot.nature===k?'selected':''}>${l}</option>`).join('')}
        </select>
      </td>
      <td style="padding:4px;">
        <select class="onb-tm-energy" style="width:80px;font-size:.85em;">
          <option value="peak" ${slot.energy==='peak'?'selected':''}>高峰</option>
          <option value="okay" ${slot.energy==='okay'?'selected':''}>尚可</option>
          <option value="normal" ${slot.energy==='normal'?'selected':''}>一般</option>
        </select>
      </td>
      <td style="padding:4px;text-align:center;">
        <button class="btn btn-sm" onclick="removeOnbTimeSlot(${idx})" style="color:var(--red);font-size:.8em;" title="删除">×</button>
      </td>
    </tr>
  `).join('');
  tbody.querySelectorAll('.onb-tm-nature').forEach(sel => {
    sel.addEventListener('change', function() {
      const colors = { immovable: 'var(--red-light)', hobby: 'var(--green-light)', available: 'var(--accent-light)', fragment: 'var(--blue-light)' };
      this.style.background = colors[this.value] || '';
    });
  });
}

function addOnbTimeSlot() {
  onbTimeMapSlots.push({ day: '周一', start: '', end: '', content: '', nature: 'available', energy: 'normal' });
  renderOnbTimeMapSlots();
}

function removeOnbTimeSlot(idx) {
  onbTimeMapSlots.splice(idx, 1);
  renderOnbTimeMapSlots();
}

function collectOnbTimeMap() {
  const rows = document.querySelectorAll('#onb-time-map-slots tr');
  const slots = [];
  rows.forEach(row => {
    slots.push({
      day: row.querySelector('.onb-tm-day').value,
      start: row.querySelector('.onb-tm-start').value,
      end: row.querySelector('.onb-tm-end').value,
      content: row.querySelector('.onb-tm-content').value.trim(),
      nature: row.querySelector('.onb-tm-nature').value,
      energy: row.querySelector('.onb-tm-energy').value,
    });
  });
  return {
    description: document.getElementById('onb-time-map-desc').value.trim(),
    slots: slots,
  };
}

function renderTimeMapVisualization(slots, description) {
  const days = ['周一','周二','周三','周四','周五','周六','周日'];
  const natureStyles = {
    immovable: {bg:'var(--red-light)', border:'var(--red)', label:'不可动'},
    hobby: {bg:'var(--green-light)', border:'var(--green)', label:'爱好'},
    available: {bg:'var(--accent-light)', border:'var(--accent)', label:'可用'},
    fragment: {bg:'var(--blue-light)', border:'var(--blue)', label:'碎片'},
  };
  const energyLabels = {peak:'🔥高峰', okay:'✅尚可', normal:'➖一般'};
  const byDay = {};
  days.forEach(d => byDay[d] = []);
  slots.forEach(s => { if (byDay[s.day]) byDay[s.day].push(s); });
  return `
    <div style="margin-top:12px;background:var(--card);border:1px solid var(--border);border-radius:6px;padding:12px;">
      <div style="font-size:.85em;font-weight:600;margin-bottom:8px;">时间全景图</div>
      <div style="display:grid;grid-template-columns:repeat(7, 1fr);gap:6px;">
        ${days.map(d => `
          <div style="background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:6px;min-height:80px;">
            <div style="font-size:.75em;color:var(--sub);font-weight:600;margin-bottom:4px;text-align:center;">${d}</div>
            ${byDay[d].length === 0 ? '<div style="font-size:.7em;color:var(--sub);text-align:center;">—</div>' : byDay[d].map(s => {
              const st = natureStyles[s.nature] || natureStyles.available;
              return `<div style="background:${st.bg};border-left:3px solid ${st.border};border-radius:4px;padding:4px 6px;margin-bottom:4px;font-size:.72em;line-height:1.4;">
                <div style="font-weight:600;">${s.start||'?'} - ${s.end||'?'}</div>
                <div style="color:var(--sub);">${escapeHtml(s.content||'')}</div>
                <div style="display:flex;justify-content:space-between;margin-top:2px;">
                  <span>${st.label}</span>
                  <span>${energyLabels[s.energy]||''}</span>
                </div>
              </div>`;
            }).join('')}
          </div>
        `).join('')}
      </div>
      ${description ? `<p style="margin-top:8px;font-size:.8em;color:var(--sub);">备注：${escapeHtml(description)}</p>` : ''}
    </div>
  `;
}

function escapeHtml(text) {
  if (!text) return '';
  return text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function openStudentModal() {
  document.getElementById('student-modal').classList.add('show');
  document.getElementById('student-modal-title').textContent = '添加学生';
  ['name','english-score','target-score','parent-name','parent-wechat','parent-phone','notes','academic-goal','textbook-version','recent-scores','weak-areas','score-loss-reason','weak-question-types','confused-grammar','existing-resources','weekly-available-hours','committed-english-minutes','vocab-habit','attention-weakness','effective-methods','ineffective-methods','target-timeline','one-month-goal','parent-availability','study-environment','least-favorite-task','aspirational-use','plan-name','plan-code-name','time-map-desc'].forEach(f=>document.getElementById('f-'+f).value='');
  document.getElementById('f-grade').value = '高二';
  document.getElementById('f-school-type').value = '住校';
  document.getElementById('f-plan').value = 'trial';
  ['gender','semester','subject-choice','vocab-direction','learning-style','learning-medium','english-identity','vocab-level','scene-preference','supervision-needed','preferred-intensity','module-ratio','difficulty-start','daily-vocab'].forEach(f=>document.getElementById('f-'+f).value='');
  timeMapSlots = [];
  renderTimeMapSlots();
  document.getElementById('f-student-id').value='';
  document.getElementById('f-parent-consent').checked = false;
  switchProfileTab('basic');
}
function closeStudentModal() { document.getElementById('student-modal').classList.remove('show'); }

// ── Profile Tab Navigation ──
function switchProfileTab(tabName) {
  document.querySelectorAll('.profile-tab').forEach(t => {
    t.classList.remove('active');
    t.style.borderBottom = 'none';
    t.style.color = 'var(--sub)';
    t.style.fontWeight = '400';
  });
  document.querySelectorAll('.profile-tab-content').forEach(c => c.style.display = 'none');

  const activeTab = document.querySelector(`.profile-tab[data-tab="${tabName}"]`);
  if (activeTab) {
    activeTab.classList.add('active');
    activeTab.style.borderBottom = '2px solid var(--accent)';
    activeTab.style.color = 'var(--text)';
    activeTab.style.fontWeight = '600';
  }
  const activeContent = document.getElementById('tab-' + tabName);
  if (activeContent) activeContent.style.display = 'block';
}

function switchOnbProfileTab(tabName) {
  document.querySelectorAll('.onb-profile-tab').forEach(t => {
    t.classList.remove('active');
    t.style.borderBottom = 'none';
    t.style.color = 'var(--sub)';
    t.style.fontWeight = '400';
  });
  document.querySelectorAll('.onb-profile-tab-content').forEach(c => c.style.display = 'none');

  const activeTab = document.querySelector(`.onb-profile-tab[data-tab="${tabName}"]`);
  if (activeTab) {
    activeTab.classList.add('active');
    activeTab.style.borderBottom = '2px solid var(--accent)';
    activeTab.style.color = 'var(--text)';
    activeTab.style.fontWeight = '600';
  }
  const activeContent = document.getElementById('onb-tab-' + tabName);
  if (activeContent) activeContent.style.display = 'block';
}

async function editStudent(id) {
  const [r, pr] = await Promise.all([
    fetch('/api/students/' + id),
    fetch('/api/students/' + id + '/profile')
  ]);
  const s = await r.json();
  const profile = pr.ok ? await pr.json() : {};

  document.getElementById('f-student-id').value = s.id;
  document.getElementById('f-name').value = s.name||'';
  document.getElementById('f-grade').value = s.grade||'高二';
  document.getElementById('f-gender').value = s.gender||profile.gender||'';
  document.getElementById('f-semester').value = s.semester||profile.semester||'';
  document.getElementById('f-school-type').value = s.school_type||'住校';
  document.getElementById('f-plan').value = s.plan||'trial';
  document.getElementById('f-english-score').value = s.english_score||'';
  document.getElementById('f-target-score').value = s.target_score||'';
  document.getElementById('f-academic-goal').value = profile.academic_goal||'';
  document.getElementById('f-subject-choice').value = profile.subject_choice||'';
  document.getElementById('f-textbook-version').value = s.textbook_version||profile.textbook_version||'';
  document.getElementById('f-parent-name').value = s.parent_name||'';
  document.getElementById('f-parent-wechat').value = s.parent_wechat||'';
  document.getElementById('f-parent-phone').value = s.parent_phone||'';
  document.getElementById('f-notes').value = s.notes||'';
  document.getElementById('f-parent-consent').checked = !!s.has_consent;

  // English situation
  document.getElementById('f-recent-scores').value = Array.isArray(profile.recent_scores) ? profile.recent_scores.join(',') : (profile.recent_scores||'');
  document.getElementById('f-weak-areas').value = profile.weak_areas||'';
  document.getElementById('f-score-loss-reason').value = profile.score_loss_reason||'';
  document.getElementById('f-weak-question-types').value = Array.isArray(profile.weak_question_types) ? profile.weak_question_types.join(',') : (profile.weak_question_types||'');
  document.getElementById('f-confused-grammar').value = profile.confused_grammar||'';
  document.getElementById('f-existing-resources').value = profile.existing_resources||'';
  document.getElementById('f-vocab-direction').value = profile.vocab_direction||'';
  const tm = (profile.time_map && typeof profile.time_map === 'object') ? profile.time_map : {};
  timeMapSlots = Array.isArray(tm.slots) ? tm.slots : [];
  document.getElementById('f-time-map-desc').value = tm.description || '';
  renderTimeMapSlots();
  document.getElementById('f-weekly-available-hours').value = profile.weekly_available_hours||'';
  document.getElementById('f-committed-english-minutes').value = profile.committed_english_minutes||'';

  // Traits
  document.getElementById('f-learning-style').value = profile.learning_style||'';
  const lsDetail = profile.learning_style_detail || {};
  const hasLsDetail = ['visual','auditory','kinesthetic','read_write'].some(k => Number(lsDetail[k]) > 0);
  document.getElementById('learning-style-radar').innerHTML = hasLsDetail
    ? renderRadarChart(lsDetail, {size: 220})
    : `<p style="color:var(--sub);text-align:center;margin:20px 0;">完成首次 AI 诊断后将展示 4 维学习风格雷达图</p>`;
  document.getElementById('f-learning-medium').value = profile.learning_medium||'';
  document.getElementById('f-vocab-habit').value = profile.vocab_habit||'';
  document.getElementById('f-attention-weakness').value = profile.attention_weakness||'';
  document.getElementById('f-effective-methods').value = profile.effective_methods||'';
  document.getElementById('f-ineffective-methods').value = profile.ineffective_methods||'';
  document.getElementById('f-english-identity').value = profile.english_identity||'';

  const assessments = profile.assessments||{};
  document.getElementById('f-attention-minutes').value = assessments.attention_minutes||'';
  document.getElementById('f-vocab-level').value = assessments.vocab_level||'';
  document.getElementById('f-scene-preference').value = assessments.scene_preference||'';

  // Goals
  document.getElementById('f-target-timeline').value = profile.target_timeline||'';
  document.getElementById('f-one-month-goal').value = profile.one_month_goal||'';
  document.getElementById('f-parent-availability').value = profile.parent_availability||'';
  document.getElementById('f-supervision-needed').value = profile.supervision_needed ? '1' : '0';
  document.getElementById('f-study-environment').value = profile.study_environment||'';
  document.getElementById('f-least-favorite-task').value = profile.least_favorite_task||'';
  document.getElementById('f-preferred-intensity').value = profile.preferred_intensity||'';
  document.getElementById('f-aspirational-use').value = profile.aspirational_use||'';

  const choices = profile.plan_choices||{};
  document.getElementById('f-module-ratio').value = choices.module_ratio||'';
  document.getElementById('f-difficulty-start').value = choices.difficulty_start||'';
  document.getElementById('f-daily-vocab').value = choices.daily_vocab||'';
  document.getElementById('f-plan-name').value = profile.plan_name||'';
  document.getElementById('f-plan-code-name').value = profile.plan_code_name||'';

  switchProfileTab('basic');
  document.getElementById('student-modal-title').textContent = '编辑学生';
  document.getElementById('student-modal').classList.add('show');
}

async function saveStudent() {
  const id = document.getElementById('f-student-id').value;
  const basicData = {
    name: document.getElementById('f-name').value,
    grade: document.getElementById('f-grade').value,
    school_type: document.getElementById('f-school-type').value,
    gender: document.getElementById('f-gender').value,
    semester: document.getElementById('f-semester').value,
    english_score: document.getElementById('f-english-score').value||null,
    target_score: document.getElementById('f-target-score').value||null,
    academic_goal: document.getElementById('f-academic-goal').value,
    subject_choice: document.getElementById('f-subject-choice').value,
    textbook_version: document.getElementById('f-textbook-version').value,
    parent_name: document.getElementById('f-parent-name').value,
    parent_wechat: document.getElementById('f-parent-wechat').value,
    parent_phone: document.getElementById('f-parent-phone').value,
    notes: document.getElementById('f-notes').value,
    plan: document.getElementById('f-plan').value,
    parent_consent: document.getElementById('f-parent-consent').checked,
  };

  const profileData = {
    gender: basicData.gender,
    semester: basicData.semester,
    academic_goal: basicData.academic_goal,
    subject_choice: basicData.subject_choice,
    textbook_version: basicData.textbook_version,
    time_map: collectTimeMap(),
    weekly_available_hours: parseFloat(document.getElementById('f-weekly-available-hours').value)||null,
    committed_english_minutes: parseInt(document.getElementById('f-committed-english-minutes').value)||null,
    recent_scores: document.getElementById('f-recent-scores').value.split(',').map(s=>s.trim()).filter(Boolean),
    weak_areas: document.getElementById('f-weak-areas').value,
    weak_question_types: document.getElementById('f-weak-question-types').value.split(',').map(s=>s.trim()).filter(Boolean),
    score_loss_reason: document.getElementById('f-score-loss-reason').value,
    confused_grammar: document.getElementById('f-confused-grammar').value,
    existing_resources: document.getElementById('f-existing-resources').value,
    vocab_direction: document.getElementById('f-vocab-direction').value,
    learning_style: document.getElementById('f-learning-style').value,
    learning_medium: document.getElementById('f-learning-medium').value,
    vocab_habit: document.getElementById('f-vocab-habit').value,
    attention_weakness: document.getElementById('f-attention-weakness').value,
    effective_methods: document.getElementById('f-effective-methods').value,
    ineffective_methods: document.getElementById('f-ineffective-methods').value,
    english_identity: document.getElementById('f-english-identity').value,
    assessments: {
      attention_minutes: parseInt(document.getElementById('f-attention-minutes').value)||null,
      vocab_level: document.getElementById('f-vocab-level').value,
      scene_preference: document.getElementById('f-scene-preference').value,
    },
    target_timeline: document.getElementById('f-target-timeline').value,
    one_month_goal: document.getElementById('f-one-month-goal').value,
    parent_availability: document.getElementById('f-parent-availability').value,
    supervision_needed: parseInt(document.getElementById('f-supervision-needed').value)||0,
    study_environment: document.getElementById('f-study-environment').value,
    least_favorite_task: document.getElementById('f-least-favorite-task').value,
    preferred_intensity: document.getElementById('f-preferred-intensity').value,
    aspirational_use: document.getElementById('f-aspirational-use').value,
    plan_choices: {
      module_ratio: document.getElementById('f-module-ratio').value,
      difficulty_start: document.getElementById('f-difficulty-start').value,
      daily_vocab: document.getElementById('f-daily-vocab').value,
    },
    plan_name: document.getElementById('f-plan-name').value,
    plan_code_name: document.getElementById('f-plan-code-name').value,
  };

  if (!basicData.name) return toast('姓名必填','error');

  const url = id ? '/api/students/'+id : '/api/students';
  const method = id ? 'PUT' : 'POST';
  const r = await fetch(url, {method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(basicData)});
  if (!r.ok) { toast('保存基本信息失败','error'); return; }
  const student = await r.json();
  const studentId = id || student.id;

  const pr = await fetch('/api/students/' + studentId + '/profile', {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(profileData)
  });
  if (!pr.ok) { toast('保存画像失败','error'); return; }

  toast(id?'已更新':'已添加');
  closeStudentModal();
  loadStudents();
}
async function manageSub(studentId, name) {
  document.getElementById('sub-student-id').value = studentId;
  document.getElementById('sub-modal-title').textContent = name + ' 的订阅管理';
  const r = await fetch('/api/subscriptions/' + studentId);
  let data = {student_id: studentId, plan: 'trial', status_label: '有效', end_date: '', total_paid: 0, payments: []};
  if (r.ok) { data = await r.json(); }

  document.getElementById('sub-plan').value = data.plan || 'trial';
  document.getElementById('sub-status').value = data.status_label || '有效';
  document.getElementById('sub-end-date').value = data.end_date || '';
  document.getElementById('sub-total-paid').value = '¥' + (data.total_paid || 0).toFixed(2);
  document.getElementById('sub-quota').value = (data.monthly_quota || 0) + ' 次';
  document.getElementById('sub-used').value = (data.used_count || 0) + ' 次（剩余 ' + (data.remaining_quota || 0) + ' 次）';
  document.getElementById('pay-amount').value = '';
  document.getElementById('pay-weeks').value = '1';
  document.getElementById('pay-note').value = '';

  // Render payments
  const ptbody = document.querySelector('#payments-table tbody');
  ptbody.innerHTML = '';
  if (data.payments && data.payments.length > 0) {
    data.payments.forEach(p => {
      ptbody.innerHTML += `<tr>
        <td>${fmtDate(p.paid_at)}</td>
        <td>¥${(p.amount||0).toFixed(2)}</td>
        <td>${(p.weeks||1)} 月</td>
        <td>${p.note||'-'}</td>
      </tr>`;
    });
  } else {
    ptbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--sub);">暂无收款记录</td></tr>';
  }

  document.getElementById('sub-modal').classList.add('show');
}
function closeSubModal() { document.getElementById('sub-modal').classList.remove('show'); }
function updateSubPrice() {
  const prices = {trial:0, basic:99, premium:299};
  // Reserved for future auto-fill of renewal amount
}
async function saveSubPlan() {
  const studentId = document.getElementById('sub-student-id').value;
  const plan = document.getElementById('sub-plan').value;
  const endDate = document.getElementById('sub-end-date').value || null;
  const r = await fetch('/api/subscriptions', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({student_id: parseInt(studentId), plan, end_date: endDate})
  });
  if (r.ok) { toast('套餐已更新'); loadStudents(); }
  else { const d = await r.json(); toast(d.error || '保存失败', 'error'); }
}
async function recordPayment() {
  const studentId = document.getElementById('sub-student-id').value;
  const amount = parseFloat(document.getElementById('pay-amount').value);
  const weeks = parseInt(document.getElementById('pay-weeks').value);
  const note = document.getElementById('pay-note').value;
  if (!amount || amount <= 0) return toast('请输入收款金额', 'error');
  if (!weeks || weeks <= 0) return toast('购买月数必须大于0', 'error');

  const r = await fetch('/api/payments', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({student_id: parseInt(studentId), amount, weeks, note})
  });
  if (r.ok) {
    toast('收款已记录，有效期已延长');
    manageSub(studentId, document.getElementById('sub-modal-title').textContent.replace(' 的订阅管理',''));
    loadStudents();
  } else {
    const d = await r.json(); toast(d.error || '记录失败', 'error');
  }
}

// ── Onboarding Pipeline ──
async function startOnboarding() {
  const name = document.getElementById('onb-name').value.trim();
  if (!name) return toast('请填写学生姓名', 'error');
  const fileInput = document.getElementById('onb-file');
  if (!fileInput.files.length) return toast('请上传试卷照片', 'error');
  if (fileInput.files.length > 6) return toast('一次最多上传 6 张图片', 'error');

  // Create student first
  const studentData = {
    name, grade: document.getElementById('onb-grade').value,
    school_type: document.getElementById('onb-school-type').value,
    gender: document.getElementById('onb-gender').value,
    english_score: document.getElementById('onb-score').value||null,
    target_score: document.getElementById('onb-target').value||null,
    plan: document.getElementById('onb-plan').value,
    parent_phone: document.getElementById('onb-parent-phone').value,
    parent_consent: document.getElementById('onb-parent-consent').checked,
  };
  const sr = await fetch('/api/students', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(studentData)});
  if (!sr.ok) { toast('创建学生失败', 'error'); return; }
  const student = await sr.json();

  // Save personalized profile
  const profileData = {
    gender: studentData.gender,
    semester: document.getElementById('onb-semester').value,
    academic_goal: document.getElementById('onb-academic-goal').value,
    subject_choice: document.getElementById('onb-subject-choice').value,
    textbook_version: document.getElementById('onb-textbook-version').value,
    time_map: collectOnbTimeMap(),
    weekly_available_hours: parseFloat(document.getElementById('onb-weekly-available-hours').value)||null,
    committed_english_minutes: parseInt(document.getElementById('onb-committed-english-minutes').value)||null,
    recent_scores: document.getElementById('onb-recent-scores').value.split(',').map(s=>s.trim()).filter(Boolean),
    weak_areas: document.getElementById('onb-weak-areas').value,
    weak_question_types: document.getElementById('onb-weak-question-types').value.split(',').map(s=>s.trim()).filter(Boolean),
    score_loss_reason: document.getElementById('onb-score-loss-reason').value,
    confused_grammar: document.getElementById('onb-confused-grammar').value,
    existing_resources: document.getElementById('onb-existing-resources').value,
    vocab_direction: document.getElementById('onb-vocab-direction').value,
    learning_style: document.getElementById('onb-learning-style').value,
    learning_medium: document.getElementById('onb-learning-medium').value,
    vocab_habit: document.getElementById('onb-vocab-habit').value,
    attention_weakness: document.getElementById('onb-attention-weakness').value,
    effective_methods: document.getElementById('onb-effective-methods').value,
    ineffective_methods: document.getElementById('onb-ineffective-methods').value,
    english_identity: document.getElementById('onb-english-identity').value,
    assessments: {
      attention_minutes: parseInt(document.getElementById('onb-attention-minutes').value)||null,
      vocab_level: document.getElementById('onb-vocab-level').value,
      scene_preference: document.getElementById('onb-scene-preference').value,
    },
    target_timeline: document.getElementById('onb-target-timeline').value,
    one_month_goal: document.getElementById('onb-one-month-goal').value,
    parent_availability: document.getElementById('onb-parent-availability').value,
    supervision_needed: parseInt(document.getElementById('onb-supervision-needed').value)||0,
    study_environment: document.getElementById('onb-study-environment').value,
    least_favorite_task: document.getElementById('onb-least-favorite-task').value,
    preferred_intensity: document.getElementById('onb-preferred-intensity').value,
    aspirational_use: document.getElementById('onb-aspirational-use').value,
    plan_choices: {
      module_ratio: document.getElementById('onb-module-ratio').value,
      difficulty_start: document.getElementById('onb-difficulty-start').value,
      daily_vocab: document.getElementById('onb-daily-vocab').value,
    },
    plan_name: document.getElementById('onb-plan-name').value,
    plan_code_name: document.getElementById('onb-plan-code-name').value,
  };
  try {
    await fetch('/api/students/' + student.id + '/profile', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(profileData)
    });
  } catch(e) { console.error('Failed to save onboarding profile', e); }

  // Upload files with progress
  let upload;
  try {
    upload = await uploadFilesWithProgress(fileInput, student.id, 'test_paper', 'parent');
  } catch(e) {
    toast('上传没成功，再试一次吧', 'error');
    return;
  }

  // Trigger pipeline
  const pr = await fetch('/api/pipeline/run', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({student_id: student.id, task_type: 'onboarding', file_ids: upload.file_ids})
  });
  if (!pr.ok) { toast('启动失败', 'error'); return; }
  const task = await pr.json();

  // Show progress + reset personalized form
  onbTimeMapSlots = [];
  renderOnbTimeMapSlots();
  document.getElementById('onb-progress').style.display = 'block';
  pollTask(task.task_id, 'onb');
}

// ── Weekly Pipeline ──
async function loadWeeklyPage() {
  const students = await (await fetch('/api/students')).json();
  const opts = students.map(s => `<option value="${s.id}">${s.name} (${s.grade})</option>`).join('');
  document.getElementById('wk-student').innerHTML = opts;
  document.getElementById('wk-student-grade').innerHTML = opts;
  // Load history
  const tr = await fetch('/api/tasks');
  const tasks = await tr.json();
  const tbody = document.querySelector('#tasks-table tbody');
  tbody.innerHTML = '';
  tasks.filter(t=>t.task_type==='weekly').slice(0,20).forEach(t => {
    let out = {};
    try { out = JSON.parse(t.output_data || '{}'); } catch(e) {}
    const stage = out.stage || '';
    const info = stage==='exercises_ready' ? `${out.questions_count||'?'}题` :
                 stage==='grading_done' ? `正确${out.correct_count}/${out.total_count}` : '';
    tbody.innerHTML += `<tr>
      <td>${t.student_name||'?'}</td>
      <td>${stage==='exercises_ready'?'生成练习题':stage==='grading_done'?'批改完成':t.status}</td>
      <td><span class="badge badge-${t.status}">${t.status}</span></td>
      <td>${info}</td>
      <td>${fmtDate(t.created_at)}</td>
    </tr>`;
  });
}
async function runWeeklyForStudent(sid) {
  switchPage('weekly');
  document.getElementById('wk-student').value = sid;
}
// Auto-upload when files are selected (stores file_ids for later use)
let pendingFileIds = [];
async function onFileSelected() {
  const fileInput = document.getElementById('wk-file');
  const sid = document.getElementById('wk-student').value;
  if (!sid) { toast('请先选择学生', 'error'); fileInput.value = ''; return; }
  if (!fileInput.files.length) return;
  if (fileInput.files.length > 15) { toast('一次最多上传 15 张图片', 'error'); fileInput.value = ''; return; }

  // Show file names immediately
  const fileNames = Array.from(fileInput.files).map(f => f.name);
  showFileList(fileNames, fileInput.files.length);

  try {
    const upload = await uploadFilesWithProgress(fileInput, sid, 'test_paper', 'parent');
    pendingFileIds = upload.file_ids;
    showFileList(fileNames, fileInput.files.length, true);
  } catch(e) {
    showFileList(fileNames, fileInput.files.length, false);
  }
}

function showFileList(fileNames, total, success) {
  let el = document.getElementById('wk-file-list');
  if (!el) {
    el = document.createElement('div');
    el.id = 'wk-file-list';
    el.style.cssText = 'margin-top:10px;font-size:0.85rem;color:#6b6b6b;';
    document.getElementById('wk-file').parentElement.appendChild(el);
  }
  if (success === undefined) {
    el.innerHTML = `<div>📎 待上传：${fileNames.join('、')}</div>`;
  } else if (success) {
    el.innerHTML = `<div style="color:#0f7b4e;">✅ 已成功上传 ${total} 个文件</div><div style="margin-top:4px;">${fileNames.map(n => '· ' + n).join('<br>')}</div>`;
  } else {
    el.innerHTML = `<div style="color:#d93a46;">❌ 上传失败，请重试</div>`;
  }
}

async function startWeekly(stage) {
  const sid = document.getElementById('wk-student').value;
  if (!sid) return toast('请选择学生', 'error');

  // analysis_only / report_only: no file upload needed
  if (stage === 'analysis_only' || stage === 'report_only') {
    const inputData = {student_id: parseInt(sid), task_type: 'weekly', stage: stage};
    const pr = await fetch('/api/pipeline/run', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(inputData)
    });
    if (!pr.ok) { toast('启动失败', 'error'); return; }
    const task = await pr.json();
    document.getElementById('wk-progress').style.display = 'block';
    pollTask(task.task_id, 'wk');
    return;
  }

  // Use pendingFileIds from auto-upload, or upload now if needed
  let fileIds = pendingFileIds;
  if (!fileIds || !fileIds.length) {
    const fileInput = document.getElementById('wk-file');
    if (!fileInput.files.length) return toast('请先上传照片', 'error');
    if (fileInput.files.length > 15) return toast('一次最多上传 15 张图片', 'error');
    try {
      const upload = await uploadFilesWithProgress(fileInput, sid, 'test_paper', 'parent');
      fileIds = upload.file_ids;
    } catch(e) {
      toast('上传没成功，再试一次吧', 'error');
      return;
    }
  }
  pendingFileIds = []; // clear after use

  const inputData = {student_id: parseInt(sid), task_type: 'weekly', file_ids: fileIds, stage: stage};

  const pr = await fetch('/api/pipeline/run', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(inputData)
  });
  if (!pr.ok) { toast('启动失败', 'error'); return; }
  const task = await pr.json();
  document.getElementById('wk-progress').style.display = 'block';
  pollTask(task.task_id, 'wk');
}

// ─ Task Polling ──
const STEPS_MAP = {
  onboarding: ['初始化', 'OCR识别试卷', '分析错题', '生成薄弱点矩阵', '生成学习方案', '生成诊断报告'],
  weekly: ['初始化', 'OCR识别试卷', '分析错题', '生成薄弱点矩阵', '生成学习方案', '生成分析报告', '生成练习题', '等待学生答案', '批改练习', '生成周报', '更新学习方案'],
  grade_only: ['初始化', 'OCR识别试卷', '分析错题', '保存错题', '完成'],
  analysis_only: ['初始化', '加载学情数据', '生成薄弱点矩阵', '生成学习方案', '生成分析报告', '完成'],
  report_only: ['初始化', '加载学情数据', '生成周报', '完成'],
};

function pollTask(taskId, prefix) {
  const bar = document.getElementById(prefix+'-bar');
  const steps = document.getElementById(prefix+'-steps');
  const result = document.getElementById(prefix+'-result');
  const stepNames = STEPS_MAP[prefix] || [];

  const timer = setInterval(async () => {
    try {
      const r = await fetch('/api/tasks/'+taskId);
      const t = await r.json();

      const pct = t.progress || 0;
      bar.style.width = pct+'%';

      steps.innerHTML = stepNames.map((name, i) => {
        const stepPct = Math.round(100 / stepNames.length);
        let cls = 'pending';
        if (pct >= (i+1)*stepPct) cls = 'done';
        else if (pct >= i*stepPct) cls = 'current';
        return `<div class="step-item ${cls}">
          ${cls==='current'?'<span class="spinner"></span>':(cls==='done'?'✅':'○')}
          ${name}
        </div>`;
      }).join('');

      if (t.status === 'done') {
        clearInterval(timer);
        bar.style.width = '100%';
        const od = t.output_data || {};
        const rid = od.report_file_id;
        const mc = od.mistakes_count;
        const sid = od.student_id;
        result.innerHTML = '<span style="color:var(--accent);">✅ 处理完成</span>';
        if (mc) result.innerHTML += `<br>📝 AI 发现 <strong>${mc}</strong> 道错题` + (sid ? ` <a href="javascript:void(0)" onclick="viewStudentMistakes(${sid})" style="color:var(--accent);font-size:.85em;">→ 查看错题详情</a>` : '');
        if (rid) {
          result.innerHTML += `<br>📄 <a href="/api/files/${rid}/download" target="_blank" class="btn btn-sm btn-green" style="margin-top:8px;text-decoration:none;">📥 下载分析报告</a>`;
          result.innerHTML += `<br><span style="color:var(--sub);font-size:.8em;">报告已生成，点击上方按钮在新窗口查看</span>`;
          // Auto-open report in new tab
          window.open('/api/files/' + rid + '/download', '_blank');
        } else if (!rid && od.stage === 'grading_done') {
          result.innerHTML += `<br><span style="color:var(--sub);font-size:.85em;">💡 请点击「📋 矩阵分析」生成分析报告，或点击「📊 生成周报」出周报</span>`;
        } else {
          result.innerHTML += `<br><span style="color:var(--sub);font-size:.85em;">💡 可前往「概览」审核队列确认报告</span>`;
        }
        loadDashboard();
      } else if (t.status === 'failed') {
        clearInterval(timer);
        result.innerHTML = `<span style="color:var(--red);">❌ 处理失败: ${t.error_message||'出了点小问题'}</span>`;
        if (t.error_message && t.error_message.includes('OCR')) {
          result.innerHTML += '<br><span style="color:var(--sub);">💡 可能是图片质量问题，请确认照片清晰无反光，重新上传试试</span>';
        }
      }
    } catch(e) { clearInterval(timer); }
  }, 2000);
}

// ── Review ──
async function approveTask(taskId) {
  await fetch('/api/tasks/'+taskId+'/approve', {method:'POST'});
  toast('已审核通过'); loadDashboard();
}
async function rejectTask(taskId) {
  const notes = prompt('请输入调整意见（如"OCR识别错误，实际应为定语从句错题""学习方案太简单，请增加更多练习"等）：');
  if (notes === null) return; // cancelled
  const r = await fetch('/api/tasks/'+taskId+'/reject', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({notes})
  });
  if (r.ok) {
    const d = await r.json();
    toast(`已驳回，正在重新生成（新任务 #${d.task_id}）...`);
    loadDashboard();
  } else {
    toast('驳回失败', 'error');
  }
}

function getSelectedReviewIds() {
  return Array.from(document.querySelectorAll('.review-checkbox:checked')).map(cb => parseInt(cb.value));
}

function toggleSelectAll() {
  const checked = document.getElementById('select-all').checked;
  document.querySelectorAll('.review-checkbox').forEach(cb => cb.checked = checked);
  updateSelectedCount();
}

function updateSelectedCount() {
  const count = document.querySelectorAll('.review-checkbox:checked').length;
  document.getElementById('selected-count').textContent = count;
}

// Listen for checkbox changes
document.addEventListener('change', function(e) {
  if (e.target.classList.contains('review-checkbox')) {
    updateSelectedCount();
  }
});

async function batchApprove() {
  const ids = getSelectedReviewIds();
  if (ids.length === 0) return toast('请先选择要审核的任务', 'error');
  if (!confirm(`确定批量通过 ${ids.length} 个任务？`)) return;
  const r = await fetch('/api/tasks/batch/approve', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({task_ids: ids})
  });
  if (r.ok) {
    const d = await r.json();
    toast(`已通过 ${d.approved} 个任务`);
    loadDashboard();
  } else {
    toast('批量通过失败', 'error');
  }
}

async function batchReject() {
  const ids = getSelectedReviewIds();
  if (ids.length === 0) return toast('请先选择要驳回的任务', 'error');
  const notes = prompt(`请输入 ${ids.length} 个任务的统一调整意见（将分别重跑）：`);
  if (notes === null) return;
  const r = await fetch('/api/tasks/batch/reject', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({task_ids: ids, notes})
  });
  if (r.ok) {
    const d = await r.json();
    toast(`已驳回 ${d.rejected} 个任务，生成 ${d.new_task_ids.length} 个新任务重跑`);
    loadDashboard();
  } else {
    toast('批量驳回失败', 'error');
  }
}

// ── Classes ──
let _currentClassId = null;
async function loadClassesPage() {
  const r = await fetch('/api/my-classes');
  if (!r.ok) { toast('加载班级失败', 'error'); return; }
  const classes = await r.json();
  const el = document.getElementById('classes-list');
  document.getElementById('class-detail').style.display = 'none';
  el.style.display = 'block';
  if (!classes.length) {
    el.innerHTML = '<div class="card" style="text-align:center;color:var(--mute);padding:40px;">暂无班级。{% if user_role == "admin" %}请点击右上角「创建班级」。{% else %}请联系管理员分配班级。{% endif %}</div>';
    return;
  }
  el.innerHTML = classes.map(c => `
    <div class="card" style="cursor:pointer;transition:all .15s;" onmouseover="this.style.transform='translateY(-1px)';this.style.boxShadow='var(--shadow-lg)'" onmouseout="this.style.transform='';this.style.boxShadow='var(--shadow)'" onclick="openClassDetail(${c.id})">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <div>
          <strong style="font-size:.95em;">${c.name}</strong>
          <span style="font-size:.75em;color:var(--sub);margin-left:8px;">${c.school_name||''}</span>
          ${c.grade?'<span class="badge badge-blue" style="margin-left:8px;">'+c.grade+'</span>':''}
        </div>
        <div style="text-align:right;">
          <div style="font-size:.75em;color:var(--sub);">班级码</div>
          <div style="font-size:1.1em;font-weight:700;color:var(--accent);letter-spacing:2px;">${c.class_code||'-'}</div>
        </div>
      </div>
    </div>
  `).join('');
}

async function openClassDetail(classId) {
  _currentClassId = classId;
  document.getElementById('classes-list').style.display = 'none';
  document.getElementById('class-detail').style.display = 'block';
  const [statsR, studentsR] = await Promise.all([
    fetch('/api/class/'+classId+'/stats'),
    fetch('/api/class/'+classId+'/students'),
  ]);
  const stats = await statsR.json();
  const students = await studentsR.json();
  document.getElementById('class-stats-cards').innerHTML = `
    <div class="card" style="text-align:center;"><div style="font-size:1.5em;font-weight:700;color:var(--text);">${stats.student_count}</div><div style="font-size:.75em;color:var(--sub);">班级人数</div></div>
    <div class="card" style="text-align:center;"><div style="font-size:1.5em;font-weight:700;color:var(--green);">${stats.active_this_week}</div><div style="font-size:.75em;color:var(--sub);">本周活跃</div></div>
    <div class="card" style="text-align:center;"><div style="font-size:1.5em;font-weight:700;color:var(--accent);">${stats.avg_mastery_rate}%</div><div style="font-size:.75em;color:var(--sub);">平均掌握率</div></div>
    <div class="card" style="text-align:center;"><div style="font-size:1.5em;font-weight:700;color:var(--blue);">${stats.total_mistakes}</div><div style="font-size:.75em;color:var(--sub);">累计错题</div></div>
  `;
  const wp = stats.weak_points_top5 || [];
  document.getElementById('class-weak-points').innerHTML = wp.length
    ? wp.map((w,i) => `<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border);">
        <span style="font-size:.75em;color:var(--mute);width:20px;">${i+1}.</span>
        <span style="flex:1;font-size:.85em;">${w.knowledge_point}</span>
        <span style="font-size:.8em;color:var(--red);font-weight:600;">错误率 ${Math.round(w.error_rate*100)}%</span>
      </div>`).join('')
    : '<div style="color:var(--mute);font-size:.85em;padding:12px 0;">暂无数据</div>';
  const tbody = document.querySelector('#class-students-table tbody');
  tbody.innerHTML = students.map(s => `<tr>
    <td><strong>${s.name}</strong></td>
    <td>${s.grade||'-'}</td>
    <td>${s.phone||'-'}</td>
    <td><button class="btn btn-sm btn-outline" onclick="switchPage('students')">查看学情</button></td>
  </tr>`).join('') || '<tr><td colspan="4" style="text-align:center;color:var(--mute);">暂无学生</td></tr>';
}

function backToClasses() {
  document.getElementById('class-detail').style.display = 'none';
  document.getElementById('classes-list').style.display = 'block';
}

{% if user_role == 'admin' %}
function openSchoolModal() {
  const name = prompt('请输入学校名称：');
  if (!name || !name.trim()) return;
  const aliases = prompt('别名/简称（多个用逗号分隔，可留空）：') || '';
  fetch('/api/schools', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name: name.trim(), aliases: aliases.split(/[,，]/).map(s=>s.trim()).filter(Boolean)})
  }).then(r => { if(r.ok){toast('学校已添加');loadClassesPage();} else r.json().then(d=>toast(d.error||'添加失败','error')); });
}
{% endif %}

function openClassModal() {
  // First check if teacher has a school
  fetch('/api/teacher/my-school').then(r=>r.json()).then(mySchool=>{
    if(mySchool.id){
      // Teacher has a school — create class directly
      const className = prompt('班级名称（如"高二3班"）：\n\n所属学校：' + mySchool.name);
      if(!className||!className.trim()) return;
      const grade = prompt('年级（如"高二"，可留空）：') || '';
      fetch('/api/teacher/create-class', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({school_id: mySchool.id, name: className.trim(), grade: grade.trim()||null})
      }).then(r=>{if(r.ok){toast('班级已创建');loadClassesPage();}else r.json().then(d=>toast(d.error||'创建失败','error'));});
    } else {
      // No school assigned — let teacher pick one
      fetch('/api/schools').then(r=>r.json()).then(schools=>{
        if(!schools.length){toast('请管理员先添加学校','error');return;}
        const schoolName = prompt('选择学校（输入学校名称）：\n\n可选：' + schools.map(s=>s.name).join('、'));
        if(!schoolName) return;
        const school = schools.find(s=>s.name.includes(schoolName.trim()));
        if(!school){toast('未找到该学校，请重新输入','error');return;}
        const className = prompt('班级名称（如"高二3班"）：');
        if(!className||!className.trim()) return;
        const grade = prompt('年级（如"高二"，可留空）：') || '';
        fetch('/api/teacher/create-class', {method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({school_id: school.id, name: className.trim(), grade: grade.trim()||null})
        }).then(r=>{if(r.ok){toast('班级已创建');loadClassesPage();}else r.json().then(d=>toast(d.error||'创建失败','error'));});
      });
    }
  });
}

// ── Admin ──
async function loadAdminPage() {
  const r = await fetch('/api/admin/users');
  if (!r.ok) { toast('加载失败', 'error'); return; }
  const users = await r.json();
  const tbody = document.querySelector('#admin-users-table tbody');
  tbody.innerHTML = '';
  users.forEach(u => {
    tbody.innerHTML += `<tr>
      <td><strong>${u.username}</strong></td>
      <td><span class="badge badge-${u.role}">${u.role==='admin'?'管理员':'老师'}</span></td>
      <td>${fmtDate(u.created_at)}</td>
      <td>
        <button class="btn btn-sm btn-outline" onclick="deleteAdminUser(${u.id}, '${u.username}')" style="color:var(--red);">删除</button>
      </td>
    </tr>`;
  });
}
function openAdminModal() {
  document.getElementById('admin-modal').classList.add('show');
  document.getElementById('admin-username').value='';
  document.getElementById('admin-password').value='';
  document.getElementById('admin-role').value='teacher';
}
function closeAdminModal() { document.getElementById('admin-modal').classList.remove('show'); }
async function saveAdminUser() {
  const data = {
    username: document.getElementById('admin-username').value.trim(),
    password: document.getElementById('admin-password').value,
    role: document.getElementById('admin-role').value,
  };
  if (!data.username || !data.password) return toast('用户名和密码必填', 'error');
  const r = await fetch('/api/admin/users', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
  if (r.ok) { toast('账号已创建'); closeAdminModal(); loadAdminPage(); }
  else { const d = await r.json(); toast(d.error || '创建失败', 'error'); }
}
async function deleteAdminUser(id, name) {
  if (!confirm(`确定删除账号 "${name}"？此操作不可恢复。`)) return;
  const r = await fetch('/api/admin/users/'+id, {method:'DELETE'});
  if (r.ok) { toast('已删除'); loadAdminPage(); }
  else toast('删除失败', 'error');
}

// ── Referrals ──
async function loadReferralsPage() {
  const r = await fetch('/api/referrals/stats');
  if (!r.ok) return;
  const s = await r.json();

  document.getElementById('referral-stats').innerHTML = `
    <div class="stat"><div class="num">${s.total_invites}</div><div class="label">总邀请码数</div></div>
    <div class="stat ok"><div class="num">${s.total_converted}</div><div class="label">已转化</div></div>
    <div class="stat info"><div class="num">${s.conversion_rate}%</div><div class="label">转化率</div></div>
    <div class="stat warn"><div class="num">${s.total_reward_weeks}</div><div class="label">累计奖励周数</div></div>
  `;

  const tbody = document.querySelector('#referral-top-table tbody');
  tbody.innerHTML = '';
  if (s.top_referrers.length === 0) {
    tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;color:var(--sub);">暂无邀请数据</td></tr>';
  } else {
    s.top_referrers.forEach((ref, i) => {
      tbody.innerHTML += `<tr>
        <td>${i+1}. ${ref.name}</td>
        <td>${ref.count}</td>
        <td>${ref.weeks}</td>
      </tr>`;
    });
  }

  // Load current setting
  try {
    const sr = await fetch('/api/budget');  // reuse budget endpoint just to avoid extra call; actually we don't have settings GET
    // no-op
  } catch(e) {}
}

async function saveReferralSettings() {
  const weeks = parseInt(document.getElementById('referral-reward-weeks').value);
  if (isNaN(weeks) || weeks < 0) return toast('奖励周数必须是非负整数', 'error');
  const r = await fetch('/api/referrals/settings', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({reward_weeks: weeks})
  });
  if (r.ok) { toast('设置已保存'); loadReferralsPage(); }
  else { const d = await r.json(); toast(d.error || '保存失败', 'error'); }
}

// ── Question Bank ──
async function loadBankPage() {
  await loadBankStats();
  await loadBank();
}

async function loadBankStats() {
  const r = await fetch('/api/questions/stats');
  if (!r.ok) return;
  const s = await r.json();
  document.getElementById('bank-stats').innerHTML = `
    <div class="stat"><div class="num">${s.total_questions}</div><div class="label">总题目</div></div>
    <div class="stat ok"><div class="num">${s.enabled_questions}</div><div class="label">已启用</div></div>
    <div class="stat info"><div class="num">${s.used_questions}</div><div class="label">被使用过</div></div>
    <div class="stat warn"><div class="num">${s.reuse_rate}%</div><div class="label">复用率</div></div>
    <div class="stat"><div class="num">${s.total_usage}</div><div class="label">总使用次数</div></div>
  `;
}

async function loadBank() {
  const search = document.getElementById('bank-search').value.trim();
  const url = search ? '/api/questions?knowledge_point=' + encodeURIComponent(search) : '/api/questions';
  const r = await fetch(url);
  if (!r.ok) return;
  const questions = await r.json();
  const tbody = document.querySelector('#questions-table tbody');
  tbody.innerHTML = '';
  if (questions.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--sub);">暂无题目</td></tr>';
    return;
  }
  questions.forEach(q => {
    const kps = (q.knowledge_points || []).map(kp => `<span class="badge badge-blue" style="margin-right:4px;">${kp}</span>`).join('');
    tbody.innerHTML += `<tr>
      <td style="max-width:300px;font-size:.85em;">${q.question_text || '-'}</td>
      <td>${q.question_type || '-'}</td>
      <td>${kps}</td>
      <td>${q.difficulty || 2}</td>
      <td>${q.usage_count || 0}</td>
      <td><span class="badge badge-${q.enabled ? 'green' : 'red'}">${q.enabled ? '启用' : '禁用'}</span></td>
      <td style="white-space:nowrap;">
        <button class="btn btn-sm btn-outline" onclick="editQuestion(${q.id})">编辑</button>
        <button class="btn btn-sm btn-outline" onclick="toggleQuestion(${q.id}, ${q.enabled ? 0 : 1})" style="color:${q.enabled ? 'var(--red)' : 'var(--green)'};">${q.enabled ? '禁用' : '启用'}</button>
      </td>
    </tr>`;
  });
}

function editQuestion(id) {
  fetch('/api/questions/' + id).then(r => r.json()).then(q => {
    document.getElementById('q-id').value = q.id;
    document.getElementById('q-text').value = q.question_text || '';
    document.getElementById('q-type').value = q.question_type || '';
    document.getElementById('q-answer').value = q.correct_answer || '';
    document.getElementById('q-explanation').value = q.explanation || '';
    document.getElementById('q-kp').value = (q.knowledge_points || []).join(', ');
    document.getElementById('q-difficulty').value = q.difficulty || 2;
    document.getElementById('q-modal').classList.add('show');
  });
}

function closeQModal() {
  document.getElementById('q-modal').classList.remove('show');
}

async function saveQuestion() {
  const id = document.getElementById('q-id').value;
  const data = {
    question_text: document.getElementById('q-text').value,
    question_type: document.getElementById('q-type').value,
    correct_answer: document.getElementById('q-answer').value,
    explanation: document.getElementById('q-explanation').value,
    knowledge_points: document.getElementById('q-kp').value.split(',').map(s => s.trim()).filter(Boolean),
    difficulty: parseInt(document.getElementById('q-difficulty').value) || 2,
  };
  const r = await fetch('/api/questions/' + id, {
    method: 'PUT', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data)
  });
  if (r.ok) { toast('题目已更新'); closeQModal(); loadBank(); }
  else { const d = await r.json(); toast(d.error || '保存失败', 'error'); }
}

async function toggleQuestion(id, enable) {
  const r = await fetch('/api/questions/' + id + '/toggle', {method: 'POST'});
  if (r.ok) { toast('状态已更新'); loadBank(); }
  else toast('操作失败', 'error');
}

async function saveBudget() {
  const total = parseFloat(document.getElementById('budget-total').value);
  const student = parseFloat(document.getElementById('budget-student').value);
  if (isNaN(total) || isNaN(student) || total < 0 || student < 0) {
    return toast('预算必须是非负数', 'error');
  }
  const r = await fetch('/api/budget', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({monthly_total_budget: total, monthly_student_budget: student})
  });
  if (r.ok) { toast('预算已保存'); loadDashboard(); }
  else { const d = await r.json(); toast(d.error || '保存失败', 'error'); }
}

// ── Quality Sampling ──
async function loadQualityPage() {
  await loadQualityStats();
  await loadQuality();
}

async function loadQualityStats() {
  const r = await fetch('/api/safety-checks/stats');
  if (!r.ok) return;
  const s = await r.json();
  document.getElementById('quality-stats').innerHTML = `
    <div class="stat"><div class="num">${s.total_checks}</div><div class="label">总抽检数</div></div>
    <div class="stat warn"><div class="num">${s.pending}</div><div class="label">待抽检</div></div>
    <div class="stat ok"><div class="num">${s.clean}</div><div class="label">合格</div></div>
    <div class="stat" style="background:var(--red-light);"><div class="num" style="color:var(--red);">${s.flagged}</div><div class="label">已标记问题</div></div>
  `;
}

async function loadQuality() {
  const r = await fetch('/api/safety-checks/pending');
  const list = document.getElementById('quality-pending-list');
  if (!r.ok) {
    list.innerHTML = '<div style="color:var(--sub);text-align:center;padding:24px;">加载失败</div>';
    return;
  }
  const checks = await r.json();
  list.innerHTML = '';
  if (checks.length === 0) {
    list.innerHTML = '<div style="color:var(--sub);text-align:center;padding:24px;">🎉 暂无待抽检内容</div>';
    return;
  }
  checks.forEach(c => {
    const typeLabel = c.content_type === 'mistake' ? '错题分析' : (c.content_type === 'feedback' ? '批改反馈' : c.content_type);
    const issueOptions = [
      {value: 'wrong_answer', label: '答案错误'},
      {value: 'wrong_explanation', label: '解析错误'},
      {value: 'wrong_knowledge_point', label: '知识点归类错误'},
      {value: 'wrong_grading', label: '批改判定错误'},
      {value: 'ocr_residual', label: 'OCR 残留/识别错'},
      {value: 'other', label: '其他'},
    ];
    const checkboxes = issueOptions.map(o =>
      `<label style="display:flex;align-items:center;gap:6px;font-size:.85em;color:var(--text);margin-right:12px;">
        <input type="checkbox" class="qc-issue-${c.id}" value="${o.value}" style="width:auto;"> ${o.label}
      </label>`
    ).join('');
    list.innerHTML += `
      <div class="card" style="border:1px solid var(--border);border-radius:8px;padding:16px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
          <div><strong>#${c.id} ${typeLabel}</strong> <span style="font-size:.8em;color:var(--sub);">${c.student_name || '未知学生'} · 任务 #${c.task_id}</span></div>
          <span style="font-size:.75em;color:var(--sub);">${fmtDate(c.created_at)}</span>
        </div>
        <div style="background:var(--bg);padding:12px;border-radius:6px;font-size:.9em;margin-bottom:12px;line-height:1.5;">${escapeHtml(c.content_snapshot || '（无摘要）')}</div>
        <div class="qc-actions-${c.id}" style="display:flex;flex-wrap:wrap;gap:10px;align-items:center;">
          <button class="btn btn-sm btn-green" onclick="reviewSafetyCheck(${c.id}, 'clean')">✅ 合格</button>
          <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;">
            ${checkboxes}
            <button class="btn btn-sm btn-outline" style="color:var(--red);" onclick="reviewSafetyCheck(${c.id}, 'flagged')">🚩 标记问题</button>
          </div>
        </div>
      </div>`;
  });
}

async function reviewSafetyCheck(checkId, status) {
  let issueFlags = [];
  if (status === 'flagged') {
    document.querySelectorAll(`.qc-issue-${checkId}:checked`).forEach(cb => issueFlags.push(cb.value));
    if (issueFlags.length === 0) return toast('请至少选择一个问题类型', 'error');
  }
  const r = await fetch('/api/safety-checks/' + checkId + '/review', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({safety_status: status, issue_flags: issueFlags})
  });
  if (r.ok) {
    toast(status === 'clean' ? '已标记为合格' : '已标记问题');
    loadQualityPage();
  } else {
    const d = await r.json();
    toast(d.error || '操作失败', 'error');
  }
}

// ── Observability ──
async function loadObservabilityPage() {
  await loadObservabilityAlerts('obs-alert-banner');
  await loadTaskFailureStats();
  await loadRecentFailures();
  await loadCostAlerts();
  await loadAuditLogActions();
  await loadAuditLogs();
  await loadBackups();
}

async function loadCompliance() {
  // Students without consent
  try {
    const r = await fetch('/api/compliance/students-without-consent');
    const students = r.ok ? await r.json() : [];
    document.getElementById('consent-pending-count').textContent = `待授权 ${students.length} 人`;
    const tbody = document.querySelector('#consent-table tbody');
    tbody.innerHTML = '';
    if (students.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--sub);">🎉 所有学生已完成家长授权</td></tr>';
    } else {
      students.forEach(s => {
        tbody.innerHTML += `
          <tr>
            <td><strong>${escapeHtml(s.name)}</strong></td>
            <td>${escapeHtml(s.grade || '')}</td>
            <td>${escapeHtml(s.parent_wechat || '')}</td>
            <td style="white-space:nowrap;">
              <button class="btn btn-sm btn-primary" onclick="openConsentModal(${s.id}, '${escapeHtml(s.name)}')">记录授权</button>
            </td>
          </tr>`;
      });
    }
  } catch(e) { console.error('Consent list load failed', e); }

  // Pending deletion requests
  try {
    const r = await fetch('/api/compliance/deletion-requests');
    const requests = r.ok ? await r.json() : [];
    document.getElementById('deletion-pending-count').textContent = `待处理 ${requests.length} 条`;
    const tbody = document.querySelector('#deletion-table tbody');
    tbody.innerHTML = '';
    if (requests.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--sub);">暂无待处理的数据删除申请</td></tr>';
    } else {
      requests.forEach(dr => {
        const isAdmin = window.CURRENT_USER_ROLE === 'admin';
        const processBtn = isAdmin
          ? `<button class="btn btn-sm btn-outline" style="color:var(--red);" onclick="processDeletion(${dr.id}, this)">执行删除</button>`
          : '<span style="font-size:.8em;color:var(--sub);">需管理员处理</span>';
        tbody.innerHTML += `
          <tr>
            <td><strong>${escapeHtml(dr.student_name)}</strong></td>
            <td>${escapeHtml(dr.requested_by)}</td>
            <td>${escapeHtml(dr.reason || '-')}</td>
            <td>${fmtDate(dr.created_at)}</td>
            <td style="white-space:nowrap;">${processBtn}</td>
          </tr>`;
      });
    }
  } catch(e) { console.error('Deletion requests load failed', e); }
}

async function openConsentModal(studentId, studentName) {
  const consentedBy = prompt(`记录 ${studentName} 的家长授权\n请输入家长姓名（必填）：`);
  if (!consentedBy || !consentedBy.trim()) return;
  const contact = prompt(`请输入家长联系方式（手机/微信，可选）：`) || '';
  const notes = prompt(`备注（可选）：`) || '';
  const r = await fetch('/api/compliance/consents', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({student_id: studentId, consented_by: consentedBy, contact, notes}),
  });
  if (r.ok) {
    toast('家长授权已记录');
    loadCompliance();
    loadDashboard();
  } else {
    toast('授权记录失败', 'error');
  }
}

async function processDeletion(reqId, btn) {
  if (!confirm('确定要执行删除吗？该学生将被软删除，公开页链接失效，相关数据保留在数据库中但标记为已删除。')) return;
  btn.disabled = true;
  const r = await fetch('/api/compliance/deletion-requests/' + reqId + '/process', {method: 'POST'});
  if (r.ok) {
    toast('删除申请已处理');
    loadCompliance();
    loadDashboard();
  } else {
    toast('处理失败', 'error');
    btn.disabled = false;
  }
}

async function loadTeacherProfilePage() {
  const r = await fetch('/api/teacher-profile');
  const p = r.ok ? await r.json() : {};
  document.getElementById('tp-institution').value = p.institution_name || '';
  document.getElementById('tp-teacher').value = p.teacher_name || '';
  document.getElementById('tp-years').value = p.teaching_years || '';
  document.getElementById('tp-specialty').value = p.specialty || '';
  document.getElementById('tp-philosophy').value = p.philosophy || '';
  document.getElementById('tp-contact').value = p.contact_info || '';
  const preview = document.getElementById('tp-avatar-preview');
  preview.textContent = p.avatar_url ? '当前头像：' + p.avatar_url : '未上传头像';
}

async function saveTeacherProfile() {
  const fileInput = document.getElementById('tp-avatar');
  let avatar_url = '';
  if (fileInput.files[0]) {
    const fd = new FormData();
    fd.append('file', fileInput.files[0]);
    const ur = await fetch('/api/teacher-profile/avatar', {method: 'POST', body: fd});
    if (!ur.ok) { toast('头像上传失败', 'error'); return; }
    const u = await ur.json();
    avatar_url = u.url;
  }
  const body = {
    institution_name: document.getElementById('tp-institution').value,
    teacher_name: document.getElementById('tp-teacher').value,
    teaching_years: document.getElementById('tp-years').value,
    specialty: document.getElementById('tp-specialty').value,
    philosophy: document.getElementById('tp-philosophy').value,
    contact_info: document.getElementById('tp-contact').value,
    avatar_url: avatar_url,
  };
  const r = await fetch('/api/teacher-profile', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  if (r.ok) {
    toast('机构介绍已保存');
    loadTeacherProfilePage();
  } else {
    toast('保存失败', 'error');
  }
}

async function loadObservabilityAlerts(containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const r = await fetch('/api/alerts');
  if (!r.ok) { container.innerHTML = ''; return; }
  const alerts = await r.json();
  if (!alerts.length) { container.innerHTML = ''; return; }
  container.innerHTML = alerts.map(a => `
    <div style="padding:10px 12px; border-radius:6px; margin-bottom:8px; font-size:.9em; display:flex; justify-content:space-between; align-items:center; ${a.level === 'critical' ? 'background:var(--red-light); color:var(--red);' : 'background:var(--accent-light); color:var(--accent);'}">
      <span>${a.level === 'critical' ? '🔴' : '⚠️'} ${escapeHtml(a.message)}</span>
      <button class="btn btn-sm btn-outline" onclick="dismissAlert(${a.id}, '${containerId}')" style="margin-left:12px;">忽略</button>
    </div>
  `).join('');
}

async function dismissAlert(alertId, containerId) {
  const r = await fetch('/api/alerts/' + alertId + '/dismiss', {method: 'POST'});
  if (r.ok) {
    toast('告警已忽略');
    await loadObservabilityAlerts(containerId);
    if (containerId !== 'obs-alert-banner') await loadObservabilityAlerts('obs-alert-banner');
  } else {
    toast('忽略失败', 'error');
  }
}

async function loadTaskFailureStats() {
  const r = await fetch('/api/tasks/failure-stats?days=7');
  if (!r.ok) return;
  const s = await r.json();
  document.getElementById('obs-task-stats').innerHTML = `
    <div class="stat"><div class="num">${s.total}</div><div class="label">总任务</div></div>
    <div class="stat warn"><div class="num">${s.failed}</div><div class="label">失败</div></div>
    <div class="stat" style="background:var(--accent-light);"><div class="num" style="color:var(--accent);">${s.rejected}</div><div class="label">驳回</div></div>
    <div class="stat" style="background:${s.failure_rate > 10 ? 'var(--red-light)' : 'var(--green-light)'};"><div class="num" style="color:${s.failure_rate > 10 ? 'var(--red)' : 'var(--green)'};">${s.failure_rate}%</div><div class="label">失败率</div></div>
  `;
  renderFailureTrend(s.daily_breakdown || []);
}

function renderFailureTrend(daily) {
  const container = document.getElementById('obs-failure-trend');
  if (!daily.length) {
    container.innerHTML = '<div style="color:var(--sub);text-align:center;padding-top:40px;">近7天无数据</div>';
    return;
  }
  const maxVal = Math.max(1, ...daily.map(d => Math.max(d.failed || 0, d.rejected || 0)));
  const bars = daily.slice().reverse().map(d => {
    const total = (d.failed || 0) + (d.rejected || 0);
    const fh = ((d.failed || 0) / maxVal * 100).toFixed(1);
    const rh = ((d.rejected || 0) / maxVal * 100).toFixed(1);
    return `
      <div style="display:flex;flex-direction:column;align-items:center;gap:4px;min-width:60px;">
        <div style="display:flex;align-items:flex-end;gap:2px;height:100px;">
          <div style="width:10px;height:${fh}%;background:var(--red);border-radius:2px;" title="失败 ${d.failed}"></div>
          <div style="width:10px;height:${rh}%;background:var(--accent);border-radius:2px;" title="驳回 ${d.rejected}"></div>
        </div>
        <div style="font-size:.7em;color:var(--sub);">${d.day.slice(5)}</div>
        <div style="font-size:.7em;color:var(--sub);">共${total}</div>
      </div>`;
  }).join('');
  container.innerHTML = `<div style="display:flex;align-items:flex-end;gap:12px;height:100%;">${bars}</div>
    <div style="margin-top:8px;font-size:.75em;color:var(--sub);">🟥 失败 🟧 驳回</div>`;
}

async function loadRecentFailures() {
  const r = await fetch('/api/tasks/recent-failures?limit=10');
  const tbody = document.querySelector('#obs-failure-table tbody');
  if (!r.ok) { tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--sub);">加载失败</td></tr>'; return; }
  const items = await r.json();
  tbody.innerHTML = '';
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--sub);">🎉 近期无失败任务</td></tr>';
    return;
  }
  items.forEach(t => {
    const statusLabel = t.status === 'failed' ? '<span style="color:var(--red);">失败</span>' : '<span style="color:var(--accent);">驳回</span>';
    const err = escapeHtml(t.error_message || '—');
    const shortErr = err.length > 80 ? err.slice(0, 80) + '...' : err;
    tbody.innerHTML += `
      <tr>
        <td>${t.student_name || '?'}</td>
        <td>${t.task_type === 'onboarding' ? '入学诊断' : '周度服务'}</td>
        <td>${statusLabel}</td>
        <td>${fmtDate(t.completed_at || t.created_at)}</td>
        <td>
          <span class="failure-msg-short">${shortErr}</span>
          ${err.length > 80 ? `<button class="btn btn-sm btn-outline" onclick="this.previousElementSibling.textContent='${err}';this.style.display='none';">展开</button>` : ''}
        </td>
      </tr>`;
  });
}

async function loadCostAlerts() {
  const r = await fetch('/api/cost/alerts');
  const panel = document.getElementById('obs-cost-panel');
  if (!r.ok) { panel.innerHTML = '加载失败'; return; }
  const d = await r.json();
  const thresholdEl = document.getElementById('obs-alert-threshold');
  if (thresholdEl) thresholdEl.value = d.threshold_pct;
  const pct = Math.min(d.monthly_pct, 100);
  const color = d.monthly_pct >= 100 ? 'var(--red)' : (d.monthly_pct >= d.threshold_pct ? 'var(--accent)' : 'var(--green)');
  let html = `
    <div style="margin-bottom:12px;">
      <div style="display:flex;justify-content:space-between;font-size:.85em;margin-bottom:4px;">
        <span>本月总成本 $${d.month_cost.toFixed(4)} / $${d.monthly_budget.toFixed(2)}</span>
        <span style="color:${color};font-weight:600;">${d.monthly_pct}%</span>
      </div>
      <div class="progress-bar" style="height:8px;"><div class="fill" style="width:${pct}%;background:${color};"></div></div>
    </div>
  `;
  if (d.alerts.length) {
    html += d.alerts.map(a => `
      <div style="padding:8px 10px; border-radius:6px; margin-bottom:6px; font-size:.85em; ${a.level === 'critical' ? 'background:var(--red-light); color:var(--red);' : 'background:var(--accent-light); color:var(--accent);'}">
        ${a.level === 'critical' ? '🔴' : '⚠️'} ${escapeHtml(a.message)}
      </div>
    `).join('');
  } else {
    html += '<div style="color:var(--green);font-size:.85em;">✅ 当前成本正常，未触发告警</div>';
  }
  panel.innerHTML = html;
}

async function saveAlertSettings() {
  const threshold = parseInt(document.getElementById('obs-alert-threshold').value);
  if (isNaN(threshold) || threshold < 0 || threshold > 100) {
    return toast('阈值必须是 0-100 的整数', 'error');
  }
  const r = await fetch('/api/admin/alert-settings', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({threshold_pct: threshold, enabled: true})
  });
  if (r.ok) { toast('告警阈值已保存'); loadCostAlerts(); }
  else { const d = await r.json(); toast(d.error || '保存失败', 'error'); }
}

async function loadAuditLogActions() {
  const r = await fetch('/api/audit-logs/actions');
  if (!r.ok) return;
  const actions = await r.json();
  const sel = document.getElementById('obs-audit-action');
  const current = sel.value;
  sel.innerHTML = '<option value="">全部</option>' + actions.map(a => `<option value="${a}">${a}</option>`).join('');
  sel.value = current || '';
}

async function loadAuditLogs() {
  const action = document.getElementById('obs-audit-action').value;
  const targetType = document.getElementById('obs-audit-target').value;
  const since = document.getElementById('obs-audit-since').value;
  const params = new URLSearchParams();
  if (action) params.append('action', action);
  if (targetType) params.append('target_type', targetType);
  if (since) params.append('since', since);
  params.append('limit', '100');

  const r = await fetch('/api/audit-logs?' + params.toString());
  const tbody = document.querySelector('#obs-audit-table tbody');
  if (!r.ok) { tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--sub);">加载失败</td></tr>'; return; }
  const logs = await r.json();
  tbody.innerHTML = '';
  if (!logs.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--sub);">暂无记录</td></tr>';
    return;
  }
  logs.forEach(l => {
    const details = JSON.stringify(l.details || {}, null, 2);
    tbody.innerHTML += `
      <tr>
        <td style="font-size:.8em;white-space:nowrap;">${fmtDate(l.created_at)} ${l.created_at ? l.created_at.slice(11,16) : ''}</td>
        <td>${l.actor_type || '-'}</td>
        <td>${l.action}</td>
        <td style="font-size:.8em;">${l.target_type || '-'} ${l.target_id || ''}</td>
        <td style="font-size:.8em;max-width:300px;overflow:hidden;text-overflow:ellipsis;"><pre style="margin:0;background:var(--bg);padding:6px;border-radius:4px;">${escapeHtml(details)}</pre></td>
      </tr>`;
  });
}

function formatBytes(bytes) {
  if (!bytes) return '-';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
}

async function loadBackups() {
  const tbody = document.querySelector('#obs-backup-table tbody');
  if (!tbody) return; // admin-only section, skip for teachers
  const r = await fetch('/api/backups');
  if (!r.ok) { tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--sub);">加载失败</td></tr>'; return; }
  const backups = await r.json();
  tbody.innerHTML = '';
  if (!backups.length) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--sub);">暂无备份</td></tr>';
    return;
  }
  backups.forEach(b => {
    tbody.innerHTML += `
      <tr>
        <td>${fmtDate(b.created_at)} ${b.created_at ? b.created_at.slice(11,16) : ''}</td>
        <td>${b.backup_type === 'daily' ? '每日' : (b.backup_type === 'weekly' ? '每周' : '手动')}</td>
        <td>${formatBytes(b.file_size)}</td>
        <td><a href="/api/backups/${b.id}/download" class="btn btn-sm btn-outline">下载</a></td>
      </tr>`;
  });
}

async function runManualBackup() {
  const btn = event.target;
  btn.disabled = true; btn.textContent = '备份中...';
  const r = await fetch('/api/backups/run', {method: 'POST'});
  btn.disabled = false; btn.textContent = '立即备份';
  if (r.ok) {
    toast('备份已完成');
    loadBackups();
  } else {
    toast('备份失败', 'error');
  }
}

// ── Learning Analytics ──
let _analyticsLoaded = false;
async function loadAnalyticsPage() {
  const sel = document.getElementById('analytics-student');
  if (_analyticsLoaded && sel && sel.options.length > 0) return;
  _analyticsLoaded = true;
  await loadClassAnalytics();
  // Load student selector
  const students = await (await fetch('/api/students')).json();
  const opts = students.map(s => `<option value="${s.id}">${s.name} (${s.grade})</option>`).join('');
  sel.innerHTML = opts;
  if (students.length > 0) {
    await loadStudentAnalytics(students[0].id);
  }
}

async function loadClassAnalytics() {
  const r = await fetch('/api/learning/class');
  if (!r.ok) return;
  const d = await r.json();

  document.getElementById('class-stats').innerHTML = `
    <div class="stat"><div class="num">${d.total_students}</div><div class="label">学生总数</div></div>
    <div class="stat info"><div class="num">${d.average_score||'-'}</div><div class="label">班级平均分</div></div>
    <div class="stat warn"><div class="num">${d.weak_knowledge_points.length}</div><div class="label">薄弱知识点</div></div>
  `;

  // Class trend chart
  document.getElementById('class-trend-chart').innerHTML = renderLineChart(
    d.score_trend.map(x => x.week_start.slice(5)),
    d.score_trend.map(x => x.avg_score),
    {height: 220, color: 'var(--accent)'}
  );

  // Weak knowledge points
  const kpDiv = document.getElementById('class-weak-kp');
  kpDiv.innerHTML = renderKnowledgeMastery(d.weak_knowledge_points, {compact: true});
}

async function loadStudentAnalytics(studentId) {
  if (!studentId) studentId = document.getElementById('analytics-student').value;
  if (!studentId) return;

  document.getElementById('score-student-id').value = studentId;
  const r = await fetch('/api/learning/student/' + studentId);
  if (!r.ok) return;
  const d = await r.json();

  document.getElementById('score-student-name').value = d.student ? d.student.name : '';

  document.getElementById('student-stats').innerHTML = `
    <div class="stat"><div class="num">${d.current_score||'-'}</div><div class="label">当前分数</div></div>
    <div class="stat info"><div class="num">${d.target_score||'-'}</div><div class="label">目标分数</div></div>
    <div class="stat ok"><div class="num">${d.practice_accuracy}%</div><div class="label">近期正确率</div></div>
    <div class="stat warn"><div class="num">${d.mistakes.total}</div><div class="label">总错题数</div></div>
  `;

  // Student trend chart
  const labels = d.scores.map(s => s.created_at.slice(5, 10));
  const values = d.scores.map(s => s.score);
  document.getElementById('student-trend-chart').innerHTML = values.length > 0
    ? renderLineChart(labels, values, {height: 220, color: 'var(--accent)', target: d.target_score})
    : '<p style="text-align:center;color:var(--sub);padding-top:80px;">暂无分数记录，可在周度批改后自动生成，或手动录入</p>';

  // Knowledge point heatmap
  const heatmapDiv = document.getElementById('student-kp-heatmap');
  heatmapDiv.innerHTML = renderKnowledgeMastery(d.knowledge_points, {showMastered: true});

  // Practice stats
  document.getElementById('student-practice-stats').innerHTML = `
    <p style="color:var(--sub);">近期练习 <strong>${d.practice_count_recent}</strong> 次，平均正确率 <strong>${d.practice_accuracy}%</strong>。</p>
  `;

  // Mistake stats
  const dueInfo = (d.mistakes.due_now > 0)
    ? `<span style="color:var(--red);"> ⚠️ <strong>${d.mistakes.due_now}</strong> 道待复习，<strong>${d.mistakes.upcoming_3d}</strong> 道3日内需复习</span>`
    : '';
  document.getElementById('student-mistake-stats').innerHTML = `
    <p style="color:var(--sub);">累计错题 <strong>${d.mistakes.total}</strong> 道，已掌握 <strong>${d.mistakes.mastered}</strong> 道，
       练习中 <strong>${d.mistakes.in_progress}</strong> 道，总复习次数 <strong>${d.mistakes.total_reviews}</strong>。${dueInfo}</p>
  `;

  // Learning path timeline (teacher view)
  renderTeacherTimeline(studentId);

  // Achievement wall (teacher view)
  renderTeacherAchievementWall(studentId);

  // Profile summary
  const profileDiv = document.getElementById('student-profile-summary');
  if (d.has_profile && d.profile) {
    const p = d.profile;
    const choices = p.plan_choices || {};
    const hasChoices = Object.keys(choices).some(k => choices[k]);
    const idCard = p.english_identity || '未填写';
    const idColor = { '敌人': 'var(--red)', '工具': 'var(--sub)', '朋友': 'var(--green)', '兴趣': 'var(--accent)' }[idCard] || 'var(--sub)';
    const tm = p.time_map || {};
    const slots = Array.isArray(tm.slots) ? tm.slots : [];
    const tmHtml = slots.length > 0 ? renderTimeMapVisualization(slots, tm.description) : '';
    const planLs = (d.learning_plan && d.learning_plan.diagnosis_report && d.learning_plan.diagnosis_report.learning_style) || null;
    const profileLs = p.learning_style_detail || null;
    const lsData = planLs || profileLs;
    const hasLsData = lsData && ['visual','auditory','kinesthetic','read_write'].some(k => Number(lsData[k]) > 0);
    const lsRadarHtml = hasLsData ? renderRadarChart(lsData, {size: 200}) : '';
    profileDiv.innerHTML = `
      ${lsRadarHtml ? `
      <div style="background:var(--card);border:1px solid var(--border);border-radius:6px;padding:12px;margin-bottom:10px;">
        <div style="font-size:.85em;color:var(--sub);margin-bottom:8px;">AI 学习风格画像（${lsData.dominant || p.learning_style || '未识别'}）</div>
        <div style="max-width:260px;">${lsRadarHtml}</div>
      </div>
      ` : ''}
      <div style="display:flex;flex-wrap:wrap;gap:8px;">
        <div style="flex:1 1 200px;background:var(--card);border:1px solid var(--border);border-radius:6px;padding:10px;">
          <div style="font-size:.75em;color:var(--sub);">学习类型 · 介质</div>
          <div style="font-size:.85em;font-weight:600;">${p.learning_style||'未填写'} · ${p.learning_medium||'未填写'}</div>
        </div>
        <div style="flex:1 1 200px;background:var(--card);border:1px solid var(--border);border-radius:6px;padding:10px;">
          <div style="font-size:.75em;color:var(--sub);">与英语的关系</div>
          <div style="font-size:.85em;font-weight:600;color:${idColor};">${idCard}</div>
        </div>
        <div style="flex:1 1 200px;background:var(--card);border:1px solid var(--border);border-radius:6px;padding:10px;">
          <div style="font-size:.75em;color:var(--sub);">词汇方向</div>
          <div style="font-size:.85em;font-weight:600;">${p.vocab_direction ? {'A':'匹配教材','B':'预习教材','C':'高考高频','D':'混合模式'}[p.vocab_direction] : '未填写'}</div>
        </div>
        <div style="flex:1 1 200px;background:var(--card);border:1px solid var(--border);border-radius:6px;padding:10px;">
          <div style="font-size:.75em;color:var(--sub);">1个月小目标</div>
          <div style="font-size:.85em;font-weight:600;">${p.one_month_goal||'未填写'}</div>
        </div>
        ${hasChoices ? `
        <div style="flex:1 1 200px;background:var(--accent-light);border:1px solid var(--accent);border-radius:6px;padding:10px;">
          <div style="font-size:.75em;color:var(--accent);">关键抉择</div>
          <div style="font-size:.85em;font-weight:600;">${choices.module_ratio||'-'} · ${choices.difficulty_start||'-'} · ${choices.daily_vocab||'-'}词/天</div>
        </div>
        ` : ''}
        ${p.plan_name ? `
        <div style="flex:1 1 200px;background:var(--green-light);border:1px solid var(--green);border-radius:6px;padding:10px;">
          <div style="font-size:.75em;color:var(--green);">专属计划</div>
          <div style="font-size:.85em;font-weight:600;">${p.plan_name}${p.plan_code_name ? ' · ' + p.plan_code_name : ''}</div>
        </div>
        ` : ''}
      </div>
      ${tmHtml}
    `;
  } else {
    profileDiv.innerHTML = `
      <div style="background:var(--bg);border:1px dashed var(--border);border-radius:6px;padding:16px;text-align:center;">
        <p style="color:var(--sub);font-size:.9em;">该学生尚未填写个性化画像</p>
        <button class="btn btn-sm btn-primary" onclick="editStudent(${studentId})" style="margin-top:8px;">去完善画像</button>
      </div>
    `;
  }

  // Diagnosis conclusion from latest plan
  const conclusionDiv = document.getElementById('student-diagnosis-conclusion');
  const plan = d.learning_plan || {};
  const diagnosis = plan.diagnosis_report;
  if (diagnosis && diagnosis.conclusion) {
    const c = diagnosis.conclusion;
    conclusionDiv.innerHTML = `
      <div style="background:var(--card);border:1px solid var(--border);border-radius:6px;padding:14px;">
        ${Array.isArray(c.core_findings) ? `
        <p style="font-size:.85em;color:var(--sub);margin-bottom:8px;"><strong>核心发现</strong></p>
        <ul style="margin:0 0 12px 18px;font-size:.85em;line-height:1.6;">${c.core_findings.map(f=>`<li>${f}</li>`).join('')}</ul>` : ''}
        <div style="display:flex;flex-wrap:wrap;gap:8px;">
          ${c.short_term ? `<div style="flex:1 1 200px;background:var(--bg);border-radius:6px;padding:10px;">
            <div style="font-size:.75em;color:var(--sub);">短期（1个月）</div>
            <div style="font-size:.82em;">${c.short_term}</div>
          </div>` : ''}
          ${c.medium_term ? `<div style="flex:1 1 200px;background:var(--bg);border-radius:6px;padding:10px;">
            <div style="font-size:.75em;color:var(--sub);">中期（1学期）</div>
            <div style="font-size:.82em;">${c.medium_term}</div>
          </div>` : ''}
          ${c.long_term ? `<div style="flex:1 1 200px;background:var(--bg);border-radius:6px;padding:10px;">
            <div style="font-size:.75em;color:var(--sub);">长期（1年）</div>
            <div style="font-size:.82em;">${c.long_term}</div>
          </div>` : ''}
        </div>
        ${c.warning ? `<p style="margin-top:12px;font-size:.82em;color:var(--red);">⚠️ ${c.warning}</p>` : ''}
      </div>
    `;
  } else {
    conclusionDiv.innerHTML = `<p style="color:var(--sub);font-size:.85em;">尚未生成基于画像的 AI 诊断结论。完成入学诊断后将在此展示。</p>`;
  }

  // Parent growth tasks
  const tasksDiv = document.getElementById('student-parent-tasks');
  const parentTasks = plan.parent_growth_tasks || [];
  const taskProgress = (d.profile && d.profile.parent_task_progress) || {};
  if (parentTasks.length > 0) {
    tasksDiv.innerHTML = `
      <div style="background:var(--card);border:1px solid var(--border);border-radius:6px;padding:14px;">
        <p style="font-size:.85em;color:var(--sub);margin-bottom:12px;">4 周渐进式家长脚手架，根据孩子画像和家庭支持情况生成。</p>
        <div style="display:flex;flex-direction:column;gap:10px;">
          ${parentTasks.map((t, idx) => {
            const weekKey = 'week' + t.week;
            const done = !!taskProgress[weekKey];
            return `
            <div style="display:flex;gap:10px;align-items:flex-start;background:var(--bg);border-radius:6px;padding:10px;${done ? 'opacity:.7;' : ''}">
              <input type="checkbox" ${done ? 'checked' : ''} onchange="toggleParentTask(${studentId}, '${weekKey}', this.checked)" style="margin-top:3px;width:auto;">
              <div style="flex:1;">
                <div style="font-size:.85em;font-weight:600;">第 ${t.week} 周 · ${t.theme} · ${t.title}</div>
                <div style="font-size:.82em;color:var(--text);margin-top:2px;">${t.task}</div>
                ${t.example ? `<div style="font-size:.8em;color:var(--sub);margin-top:4px;">示例：${t.example}</div>` : ''}
                ${t.goal ? `<div style="font-size:.78em;color:var(--accent);margin-top:4px;">目标：${t.goal}</div>` : ''}
              </div>
            </div>`;
          }).join('')}
        </div>
      </div>
    `;
  } else {
    tasksDiv.innerHTML = `<p style="color:var(--sub);font-size:.85em;">尚未生成家长成长任务包。完成入学诊断后将在此展示。</p>`;
  }

  // Motivation / Achievement cards
  const cardsDiv = document.getElementById('student-motivation-cards');
  const motivationCards = plan.motivation_cards || [];
  const achievements = d.achievements || [];
  const allCards = [
    ...motivationCards.map(c => ({...c, tag: 'AI'})),
    ...achievements.map(a => ({...a, tag: '数据'}))
  ];
  if (allCards.length > 0) {
    cardsDiv.innerHTML = `
      <div style="display:flex;flex-wrap:wrap;gap:10px;">
        ${allCards.map(c => `
          <div style="flex:1 1 200px;background:var(--card);border:1px solid var(--border);border-radius:6px;padding:12px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
              <span style="font-size:.8em;color:var(--accent);font-weight:600;">${c.title || '卡片'}</span>
              ${c.tag ? `<span style="font-size:.65em;background:var(--bg);color:var(--sub);padding:1px 6px;border-radius:4px;">${c.tag}</span>` : ''}
            </div>
            <div style="font-size:.85em;line-height:1.5;">${c.content || ''}</div>
          </div>
        `).join('')}
      </div>
    `;
  } else {
    cardsDiv.innerHTML = `<p style="color:var(--sub);font-size:.85em;">尚未生成卡片。完成入学诊断或产生练习记录后将自动生成。</p>`;
  }

  // Metacognitive review — now fetches student-submitted reviews
  const reviewDiv = document.getElementById('student-metacognitive-review');
  try {
    const revRes = await fetch('/api/students/' + studentId + '/reviews');
    if (revRes.ok) {
      const revData = await revRes.json();
      const current = revData.current || {};
      const history = revData.history || [];
      const submitted = history.filter(h => h.status === 'submitted');

      let revHtml = '';
      // Show current week review form status
      revHtml += `<div style="margin-bottom:12px;">
        <span style="font-weight:600;">📝 ${current.week_start || '本周'} 复盘</span>
        <span style="margin-left:8px;font-size:.8em;color:${current.status==='submitted'?'var(--green)':'var(--sub)'};">${current.status==='submitted' ? '✅ 已提交' : '⏳ 待填写'}</span>
        ${current.child_mood ? `<span style="margin-left:8px;font-size:.8em;">孩子心情：${'⭐'.repeat(current.child_mood)}</span>` : ''}
        ${current.parent_mood ? `<span style="margin-left:8px;font-size:.8em;">家长感受：${'⭐'.repeat(current.parent_mood)}</span>` : ''}
      </div>`;

      // Show latest submitted review details
      if (submitted.length > 0) {
        const latest = submitted[0];
        const childAns = latest.child_answers || {};
        const parentAns = latest.parent_answers || {};
        revHtml += `<div style="background:var(--card);border:1px solid var(--border);border-radius:6px;padding:12px;max-height:240px;overflow-y:auto;">`;
        revHtml += `<div style="font-size:.8em;color:var(--sub);margin-bottom:8px;">最近提交：${latest.week_start} 周 (${(latest.submitted_at||'').slice(0,10)})</div>`;
        if (Object.keys(childAns).length > 0) {
          revHtml += `<div style="font-size:.8em;font-weight:600;margin-bottom:4px;">🙋 孩子反思</div>`;
          Object.entries(childAns).forEach(([q, a]) => {
            revHtml += `<div style="font-size:.78em;color:var(--sub);margin-bottom:4px;"><strong>Q:</strong> ${q}</div>`;
            revHtml += `<div style="font-size:.78em;margin-bottom:8px;padding-left:8px;border-left:2px solid var(--accent);"><strong>A:</strong> ${a}</div>`;
          });
        }
        if (Object.keys(parentAns).length > 0) {
          revHtml += `<div style="font-size:.8em;font-weight:600;margin-bottom:4px;">👨‍👩‍👧 家长观察</div>`;
          Object.entries(parentAns).forEach(([q, a]) => {
            revHtml += `<div style="font-size:.78em;color:var(--sub);margin-bottom:4px;"><strong>Q:</strong> ${q}</div>`;
            revHtml += `<div style="font-size:.78em;margin-bottom:8px;padding-left:8px;border-left:2px solid var(--green);"><strong>A:</strong> ${a}</div>`;
          });
        }
        if (latest.child_note) revHtml += `<div style="font-size:.78em;color:var(--sub);">📝 孩子备注：${latest.child_note}</div>`;
        if (latest.parent_note) revHtml += `<div style="font-size:.78em;color:var(--sub);">📝 家长备注：${latest.parent_note}</div>`;
        revHtml += `</div>`;
      } else {
        revHtml += `<p style="color:var(--sub);font-size:.8em;">暂无已提交的复盘表。</p>`;
      }

      reviewDiv.innerHTML = revHtml;
    } else {
      reviewDiv.innerHTML = `<p style="color:var(--sub);font-size:.85em;">尚未生成元认知复盘表。</p>`;
    }
  } catch(e) {
    reviewDiv.innerHTML = `<p style="color:var(--sub);font-size:.85em;">加载复盘数据失败。</p>`;
  }

  // Plan adjustments
  const adjDiv = document.getElementById('student-plan-adjustments');
  const lastAdj = plan.last_adjustment || (d.learning_plan && d.learning_plan.plan_data && d.learning_plan.plan_data.last_adjustment);
  if (lastAdj) {
    adjDiv.innerHTML = `
      <div style="background:var(--card);border:1px solid var(--border);border-radius:6px;padding:12px;">
        <div style="font-size:.85em;color:var(--sub);margin-bottom:4px;">周 ${lastAdj.week_start || '-'} · 完成率 ${(lastAdj.completion_rate * 100).toFixed(0)}%</div>
        <div style="font-size:.85em;line-height:1.5;">${lastAdj.reason || ''}</div>
      </div>
    `;
  } else {
    adjDiv.innerHTML = `<p style="color:var(--sub);font-size:.85em;">暂无自适应调整记录。</p>`;
  }
}

async function toggleParentTask(studentId, weekKey, done) {
  const progress = {};
  progress[weekKey] = done;
  const r = await fetch('/api/students/' + studentId + '/profile/parent-tasks', {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({parent_task_progress: progress})
  });
  if (r.ok) {
    toast(done ? '已标记完成' : '已取消标记');
    loadStudentAnalytics(studentId);
  } else {
    toast('更新失败', 'error');
  }
}

function renderLineChart(labels, values, opts={}) {
  if (!values || values.length === 0) return '';
  const height = opts.height || 200;
  const width = 800;
  const padding = 40;
  const chartW = width - padding * 2;
  const chartH = height - padding * 2;
  const maxVal = Math.max(...values, opts.target || 0, 1);
  const minVal = Math.min(...values, 0);
  const range = maxVal - minVal || 1;

  const points = values.map((v, i) => {
    const x = padding + (i / (values.length - 1 || 1)) * chartW;
    const y = height - padding - ((v - minVal) / range) * chartH;
    return `${x},${y}`;
  }).join(' ');

  const dots = values.map((v, i) => {
    const x = padding + (i / (values.length - 1 || 1)) * chartW;
    const y = height - padding - ((v - minVal) / range) * chartH;
    return `<circle cx="${x}" cy="${y}" r="4" fill="${opts.color||'var(--accent)'}" stroke="#fff" stroke-width="2" />
            <text x="${x}" y="${y - 10}" text-anchor="middle" font-size="11" fill="var(--sub)">${v}</text>`;
  }).join('');

  const xLabels = labels.map((l, i) => {
    const x = padding + (i / (labels.length - 1 || 1)) * chartW;
    return `<text x="${x}" y="${height - padding + 18}" text-anchor="middle" font-size="11" fill="var(--sub)">${l}</text>`;
  }).join('');

  let targetLine = '';
  if (opts.target) {
    const y = height - padding - ((opts.target - minVal) / range) * chartH;
    targetLine = `<line x1="${padding}" y1="${y}" x2="${width - padding}" y2="${y}" stroke="var(--green)" stroke-dasharray="4,4" />
                  <text x="${width - padding}" y="${y - 5}" text-anchor="end" font-size="11" fill="var(--green)">目标 ${opts.target}</text>`;
  }

  return `<svg viewBox="0 0 ${width} ${height}" style="width:100%;height:${height}px;">
    <rect width="${width}" height="${height}" fill="var(--card)" />
    <line x1="${padding}" y1="${height - padding}" x2="${width - padding}" y2="${height - padding}" stroke="var(--border)" />
    <line x1="${padding}" y1="${padding}" x2="${padding}" y2="${height - padding}" stroke="var(--border)" />
    ${targetLine}
    <polyline fill="none" stroke="${opts.color||'var(--accent)'}" stroke-width="2.5" points="${points}" />
    ${dots}
    ${xLabels}
  </svg>`;
}

function renderRadarChart(data, opts={}) {
  if (!data) return '';
  const visual = Number(data.visual) || 0;
  const auditory = Number(data.auditory) || 0;
  const kinesthetic = Number(data.kinesthetic) || 0;
  const readWrite = Number(data.read_write) || 0;
  const dims = [
    {key:'visual', label:'视觉型', value:visual},
    {key:'auditory', label:'听觉型', value:auditory},
    {key:'kinesthetic', label:'动觉型', value:kinesthetic},
    {key:'read_write', label:'读写型', value:readWrite}
  ];
  if (dims.every(d => d.value === 0)) {
    return `<p style="color:var(--sub);text-align:center;padding:20px;">暂无学习风格测评数据</p>`;
  }
  const size = opts.size || 220;
  const center = size / 2;
  const radius = size * 0.36;
  const max = 10;
  const levels = [0.33, 0.66, 1.0];
  const angleFor = i => (Math.PI * 2 * i) / 4 - Math.PI / 2;
  const pointFor = (value, i) => {
    const r = (value / max) * radius;
    const a = angleFor(i);
    return `${center + r * Math.cos(a)},${center + r * Math.sin(a)}`;
  };
  const labelPosFor = (i, dist) => {
    const a = angleFor(i);
    return {x: center + dist * Math.cos(a), y: center + dist * Math.sin(a)};
  };
  const gridPolys = levels.map(lv => {
    const pts = dims.map((_, i) => pointFor(max * lv, i)).join(' ');
    return `<polygon points="${pts}" fill="none" stroke="var(--border)" stroke-width="1" stroke-dasharray="2,2"/>`;
  }).join('');
  const axes = dims.map((_, i) => {
    const end = labelPosFor(i, radius);
    return `<line x1="${center}" y1="${center}" x2="${end.x}" y2="${end.y}" stroke="var(--border)" stroke-width="1"/>`;
  }).join('');
  const dataPts = dims.map((d, i) => pointFor(d.value, i)).join(' ');
  const labels = dims.map((d, i) => {
    const pos = labelPosFor(i, radius + 22);
    const anchor = i === 0 ? 'middle' : (i === 1 ? 'start' : (i === 2 ? 'middle' : 'end'));
    return `<text x="${pos.x}" y="${pos.y + 4}" text-anchor="${anchor}" font-size="12" fill="var(--text)">${d.label}</text>
            <text x="${pos.x}" y="${pos.y + 17}" text-anchor="${anchor}" font-size="11" fill="var(--accent)">${d.value}</text>`;
  }).join('');
  const caption = [];
  if (data.dominant) caption.push(`<strong>${data.dominant}</strong>`);
  if (data.auxiliary) caption.push(`辅助：${data.auxiliary}`);
  if (data.interpretation) caption.push(data.interpretation);
  const captionHtml = caption.length ? `<div style="font-size:.8em;color:var(--sub);text-align:center;margin-top:8px;line-height:1.5;">${caption.join(' · ')}</div>` : '';
  return `<div style="max-width:${size}px;margin:0 auto;">
    <svg viewBox="0 0 ${size} ${size}" style="width:100%;height:${size}px;">
      <rect width="${size}" height="${size}" fill="var(--card)" rx="6"/>
      ${gridPolys}
      ${axes}
      <polygon points="${dataPts}" fill="var(--accent)" fill-opacity="0.25" stroke="var(--accent)" stroke-width="2"/>
      ${dims.map((d, i) => {
        const p = pointFor(d.value, i);
        return `<circle cx="${p.split(',')[0]}" cy="${p.split(',')[1]}" r="3" fill="var(--accent)"/>`;
      }).join('')}
      ${labels}
    </svg>
    ${captionHtml}
  </div>`;
}

async function renderTeacherTimeline(studentId) {
  const div = document.getElementById('student-timeline');
  if (!div || !studentId) return;
  try {
    const r = await fetch('/api/students/' + studentId + '/timeline');
    if (!r.ok) { div.innerHTML = '<p style="color:var(--sub);">暂无时间轴</p>'; return; }
    const data = await r.json();
    const milestones = data.milestones || [];
    if (milestones.length === 0) {
      div.innerHTML = '<p style="color:var(--sub);">🌱 学习旅程刚刚开始</p>';
      return;
    }
    let html = '<div class="timeline" style="max-height:400px;overflow-y:auto;">';
    for (const m of milestones) {
      html += `<div class="tl-item">
        <div class="tl-dot">${m.icon}</div>
        <div class="tl-date">${m.date}</div>
        <div class="tl-title">${m.icon} ${m.title}</div>
        <div class="tl-desc">${m.description}</div>
      </div>`;
    }
    html += '</div>';
    div.innerHTML = html;
  } catch(e) {
    div.innerHTML = '<p style="color:var(--sub);">加载失败</p>';
  }
}

async function renderTeacherAchievementWall(studentId) {
  const div = document.getElementById('student-achievements-wall');
  if (!div || !studentId) return;
  try {
    const r = await fetch('/api/students/' + studentId + '/achievements');
    if (!r.ok) { div.innerHTML = '<p style="color:var(--sub);">暂无成就数据</p>'; return; }
    const data = await r.json();
    if (!data.all || data.all.length === 0) {
      div.innerHTML = '<p style="color:var(--sub);">暂无成就定义</p>'; return;
    }
    let html = `<p style="color:var(--sub);margin-bottom:10px;">已解锁 <strong>${data.earned_count}</strong> / ${data.total_count} 项成就</p>`;
    html += '<div style="display:grid;grid-template-columns:repeat(auto-fill, minmax(130px, 1fr));gap:8px;">';
    for (const a of data.all) {
      const earnedClass = a.earned ? 'ach-earned' : 'ach-locked';
      const pct = a.progress_pct || 0;
      html += `<div class="ach-card ${earnedClass}" title="${a.description}">
        <div class="ach-icon">${a.icon}</div>
        <div class="ach-title">${a.title}</div>
        <div class="ach-desc">${a.description}</div>`;
      if (a.earned) {
        html += `<div class="ach-date">${(a.earned_at||'').slice(0,10)}</div>`;
      } else {
        html += `<div class="ach-progress"><div class="ach-progress-bar" style="width:${pct}%;"></div></div>
          <div class="ach-progress-text">${a.current}/${a.threshold}</div>`;
      }
      html += '</div>';
    }
    html += '</div>';
    div.innerHTML = html;
  } catch(e) {
    div.innerHTML = '<p style="color:var(--sub);">成就加载失败</p>';
  }
}

function renderKnowledgeMastery(items, opts={}) {
  if (!items || items.length === 0) {
    return `<p style="color:var(--sub);text-align:center;">暂无知识点数据</p>`;
  }
  const rows = items.map(kp => {
    const rate = Number(kp.mastery_rate) || 0;
    const total = kp.total || kp.total_mistakes || 0;
    const mastered = kp.mastered !== undefined ? kp.mastered : (total - (kp.unmastered || 0));
    const unmastered = kp.unmastered !== undefined ? kp.unmastered : (total - mastered);
    const color = rate < 30 ? 'var(--red)' : (rate < 60 ? 'var(--accent)' : 'var(--green)');
    const countText = total > 0 ? `${mastered}/${total} 已掌握` : '';
    return `<div style="${opts.compact ? 'margin-bottom:8px;' : 'flex:1 1 240px;background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:10px;margin-bottom:8px;'}">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
        <span style="font-size:.85em;font-weight:600;${opts.compact ? '' : 'color:' + color + ';'}">${kp.knowledge_point}</span>
        <span style="font-size:.8em;color:var(--sub);">掌握率 <strong style="color:${color};">${rate}%</strong> ${countText ? '· ' + countText : ''}</span>
      </div>
      <div class="progress-bar" style="height:6px;"><div class="fill" style="width:${rate}%;background:${color};"></div></div>
    </div>`;
  }).join('');
  return opts.compact ? rows : `<div style="display:flex;flex-wrap:wrap;gap:8px;">${rows}</div>`;
}

function openScoreModal() {
  const sid = document.getElementById('analytics-student').value;
  if (!sid) return toast('请先选择学生', 'error');
  document.getElementById('score-student-id').value = sid;
  const name = document.getElementById('analytics-student').selectedOptions[0].text.split(' ')[0];
  document.getElementById('score-student-name').value = name;
  document.getElementById('score-value').value = '';
  document.getElementById('score-date').value = new Date().toISOString().slice(0,10);
  document.getElementById('score-note').value = '';
  document.getElementById('score-modal').classList.add('show');
}
function closeScoreModal() { document.getElementById('score-modal').classList.remove('show'); }
async function saveScore() {
  const studentId = document.getElementById('score-student-id').value;
  const score = parseFloat(document.getElementById('score-value').value);
  const date = document.getElementById('score-date').value;
  const note = document.getElementById('score-note').value;
  if (!studentId || isNaN(score)) return toast('请输入学生分数', 'error');

  const r = await fetch('/api/learning/score', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({student_id: parseInt(studentId), score, week_start: date, note})
  });
  if (r.ok) {
    toast('分数已录入');
    closeScoreModal();
    loadStudentAnalytics(studentId);
  } else {
    const d = await r.json(); toast(d.error || '保存失败', 'error');
  }
}

// ── AI Correction ──
let correctionState = { taskId: null, items: [], originalItems: [] };

function closeCorrectionModal() {
  document.getElementById('correction-modal').classList.remove('show');
  correctionState = { taskId: null, items: [], originalItems: [] };
}

async function openCorrectionPanel(taskId) {
  correctionState.taskId = taskId;
  document.getElementById('correction-task-id').value = taskId;
  document.getElementById('correction-reason').value = '';
  document.getElementById('correction-status').textContent = '加载中...';
  document.getElementById('correction-modal').classList.add('show');

  const [taskR, corrR] = await Promise.all([
    fetch('/api/tasks/' + taskId),
    fetch('/api/tasks/' + taskId + '/corrections')
  ]);
  const task = taskR.ok ? await taskR.json() : {};
  const existingCorrections = corrR.ok ? await corrR.json() : [];

  const r = await fetch('/api/tasks/' + taskId + '/correctables');
  if (!r.ok) {
    document.getElementById('correction-status').textContent = '加载失败';
    return toast('加载可纠错内容失败', 'error');
  }
  const data = await r.json();
  correctionState.items = data.items || [];
  correctionState.originalItems = JSON.parse(JSON.stringify(correctionState.items));

  const taskTypeLabel = task.task_type === 'onboarding' ? '入学诊断' : '周度服务';
  document.getElementById('correction-task-info').textContent = `#${taskId} · ${taskTypeLabel} · ${data.items ? data.items.length + ' 条内容' : '0 条'}`;

  renderCorrectionItems(existingCorrections);
  document.getElementById('correction-status').textContent = existingCorrections.length > 0
    ? `该任务已有 ${existingCorrections.length} 条纠错记录，可继续补充`
    : '请修改有问题的字段，未修改的字段不会提交';
}

function renderCorrectionItems(existingCorrections) {
  const container = document.getElementById('correction-items');
  container.innerHTML = '';

  if (!correctionState.items.length) {
    container.innerHTML = '<div style="color:var(--sub); text-align:center; padding:24px;">暂无可纠错内容</div>';
    return;
  }

  correctionState.items.forEach((item, idx) => {
    const fields = [];
    const isGrading = item.content_type === 'grading';

    if (isGrading) {
      fields.push({ key: 'is_correct', label: '批改结果', type: 'select', options: [['1','✅ 对'], ['0','❌ 错']], val: item.is_correct ? '1' : '0' });
      fields.push({ key: 'feedback', label: '批改解析', type: 'textarea', val: item.feedback || '' });
      fields.push({ key: 'correct_answer', label: '正确答案（参考）', type: 'text', val: item.correct_answer || '', readonly: true, muted: true });
    } else {
      fields.push({ key: 'question', label: '题干', type: 'textarea', val: item.question || '' });
      fields.push({ key: 'correct_answer', label: '正确答案', type: 'text', val: item.correct_answer || '' });
      fields.push({ key: 'explanation', label: '解析', type: 'textarea', val: item.explanation || '' });
      fields.push({ key: 'knowledge_points', label: '知识点（用逗号分隔）', type: 'text', val: Array.isArray(item.knowledge_points) ? item.knowledge_points.join(', ') : (item.knowledge_points || '') });
      fields.push({ key: 'difficulty', label: '难度（1-5）', type: 'number', val: item.difficulty != null ? item.difficulty : 2 });
      fields.push({ key: 'question_type', label: '题型', type: 'text', val: item.question_type || '' });
    }

    // Show existing corrections for this target
    const targetCorrs = existingCorrections.filter(c => c.target_id === item.target_id);
    const corrTags = targetCorrs.map(c => {
      const fieldLabels = {
        question:'题干', correct_answer:'答案', explanation:'解析', knowledge_points:'知识点',
        difficulty:'难度', question_type:'题型', is_correct:'批改', feedback:'解析'
      };
      return `<span class="badge" style="background:var(--accent-light); color:var(--accent); font-size:.75em;">${fieldLabels[c.target_field] || c.target_field}</span>`;
    }).join(' ');

    let html = `<div class="card" style="border:1px solid var(--border); border-radius:8px; padding:16px;" data-idx="${idx}">`;
    html += `<div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:12px;">`;
    html += `<div><strong>#${idx + 1} ${isGrading ? '批改结果' : '错题'}</strong> ${corrTags}</div>`;
    if (item.knowledge_points && item.knowledge_points.length) {
      html += `<div style="font-size:.8em; color:var(--sub);">${Array.isArray(item.knowledge_points) ? item.knowledge_points.join(' · ') : item.knowledge_points}</div>`;
    }
    html += `</div>`;

    if (isGrading && item.question) {
      html += `<div style="background:var(--bg); padding:10px 12px; border-radius:6px; margin-bottom:12px; font-size:.9em; color:var(--text);"><strong>题目：</strong>${escapeHtml(item.question)}</div>`;
      html += `<div style="font-size:.85em; color:var(--sub); margin-bottom:12px;">学生答案：${escapeHtml(item.user_answer || '（未识别）')}</div>`;
    }

    fields.forEach(f => {
      const id = `corr-${idx}-${f.key}`;
      html += `<div class="form-group" style="margin-bottom:10px;">`;
      html += `<label style="font-size:.85em; color:var(--sub);">${f.label}</label>`;
      if (f.type === 'textarea') {
        html += `<textarea id="${id}" data-key="${f.key}" rows="2" ${f.readonly ? 'readonly style="background:#f5f2ec;"' : ''}>${escapeHtml(String(f.val || ''))}</textarea>`;
      } else if (f.type === 'select') {
        html += `<select id="${id}" data-key="${f.key}">${f.options.map(o => `<option value="${o[0]}" ${String(f.val) === o[0] ? 'selected' : ''}>${o[1]}</option>`).join('')}</select>`;
      } else {
        html += `<input id="${id}" type="${f.type}" data-key="${f.key}" value="${escapeHtml(String(f.val || ''))}" ${f.readonly ? 'readonly style="background:#f5f2ec;"' : ''} ${f.muted ? 'style="color:var(--sub);"' : ''}>`;
      }
      html += `</div>`;
    });

    html += `</div>`;
    container.innerHTML += html;
  });
}

function escapeHtml(text) {
  if (text == null) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

async function submitCorrections() {
  const taskId = correctionState.taskId;
  if (!taskId) return;

  const corrections = [];
  correctionState.items.forEach((item, idx) => {
    const original = correctionState.originalItems[idx];
    const isGrading = item.content_type === 'grading';
    const fieldKeys = isGrading
      ? ['is_correct', 'feedback']
      : ['question', 'correct_answer', 'explanation', 'knowledge_points', 'difficulty', 'question_type'];

    fieldKeys.forEach(key => {
      const el = document.getElementById(`corr-${idx}-${key}`);
      if (!el) return;
      let newVal = el.value;
      let oldVal = original[key];

      if (key === 'difficulty') {
        newVal = parseInt(newVal) || 2;
        oldVal = oldVal != null ? oldVal : 2;
      } else if (key === 'knowledge_points') {
        newVal = newVal.split(',').map(s => s.trim()).filter(Boolean);
        oldVal = Array.isArray(oldVal) ? oldVal : [];
      } else if (key === 'is_correct') {
        newVal = newVal === '1';
        oldVal = !!oldVal;
      }

      // Compare normalized values
      const changed = JSON.stringify(newVal) !== JSON.stringify(oldVal);
      if (changed) {
        corrections.push({
          content_type: item.content_type,
          target_id: item.target_id,
          target_field: key,
          original_value: oldVal,
          corrected_value: newVal,
        });
      }
    });
  });

  if (!corrections.length) {
    return toast('没有修改任何字段', 'error');
  }

  const reason = document.getElementById('correction-reason').value.trim();
  corrections.forEach(c => { c.reason = reason; });

  document.getElementById('correction-status').textContent = '提交中...';
  const r = await fetch('/api/tasks/' + taskId + '/corrections', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ corrections })
  });
  if (r.ok) {
    const d = await r.json();
    toast(`已提交 ${d.created} 条纠错`);
    closeCorrectionModal();
    loadDashboard();
  } else {
    const d = await r.json();
    document.getElementById('correction-status').textContent = d.error || '提交失败';
    toast(d.error || '提交失败', 'error');
  }
}

// ── Init ──
loadDashboard();
</script>
</body>
</html>'''

# ═══════════════════════════════════════════════════
# Student Auth Pages
# ═══════════════════════════════════════════════════

TEACHER_REGISTER_PAGE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>教师注册 · 拾阶而上</title>
<style>
:root{--bg:#f8f7f4;--card:#fff;--accent:#e07b4b;--accent-hover:#d06a3a;--accent-light:#fef3ed;--text:#1a1a1a;--sub:#6b6b6b;--border:#e8e6e1;--red:#d93a46;--shadow:0 1px 3px rgba(0,0,0,.06),0 2px 8px rgba(0,0,0,.02)}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.card{background:var(--card);border-radius:12px;padding:36px 32px;box-shadow:var(--shadow);width:100%;max-width:380px}
h1{font-size:1.3rem;color:var(--text);margin-bottom:6px;text-align:center}
.subtitle{text-align:center;color:var(--sub);font-size:.85rem;margin-bottom:24px}
label{display:block;font-size:.8rem;font-weight:600;color:var(--sub);margin-bottom:6px;margin-top:14px}
label:first-of-type{margin-top:0}
input{width:100%;border:1px solid var(--border);border-radius:8px;padding:10px 12px;font-size:.9rem;transition:border-color .15s,box-shadow .15s}
input:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-light);outline:none}
button{width:100%;background:var(--accent);color:#fff;border:none;border-radius:8px;padding:12px;font-size:.9rem;font-weight:600;cursor:pointer;transition:all .15s;margin-top:20px}
button:hover{background:var(--accent-hover);transform:translateY(-1px)}
button:disabled{opacity:.6;cursor:not-allowed;transform:none}
.error{color:var(--red);font-size:.8rem;margin-top:12px;display:none}
.links{text-align:center;margin-top:20px;font-size:.8rem;color:var(--sub)}
.links a{color:var(--accent);text-decoration:none}
.autocomplete{position:relative}
.ac-list{position:absolute;top:100%;left:0;right:0;background:var(--card);border:1px solid var(--border);border-radius:8px;box-shadow:var(--shadow);z-index:10;display:none;max-height:200px;overflow-y:auto}
.ac-item{padding:10px 12px;cursor:pointer;font-size:.85rem;border-bottom:1px solid var(--border)}
.ac-item:last-child{border-bottom:none}
.ac-item:hover{background:var(--accent-light)}
.ac-item .alias{color:var(--sub);font-size:.75rem}
</style>
</head>
<body>
<div class="card">
<h1>👩‍🏫 教师注册</h1>
<p class="subtitle">注册后即可管理班级和学生</p>
<div class="error" id="err"></div>
<label>姓名 / 昵称</label>
<input type="text" id="display-name" placeholder="如：王老师">
<label>学校</label>
<div class="autocomplete">
  <input type="text" id="school-input" placeholder="输入学校名称搜索..." autocomplete="off">
  <div class="ac-list" id="ac-list"></div>
</div>
<input type="hidden" id="school-id">
<label>用户名（登录用）</label>
<input type="text" id="username" placeholder="至少3位，仅英文和数字">
<label>手机号（可选，用于验证码登录）</label>
<input type="tel" id="phone" placeholder="11位手机号" maxlength="11">
<label>科目</label>
<select id="subject" style="width:100%;border:1px solid var(--border);border-radius:8px;padding:10px 12px;font-size:.9rem;">
  <option value="英语">英语</option>
  <option value="语文">语文</option>
  <option value="数学">数学</option>
  <option value="道法">道法</option>
  <option value="历史">历史</option>
  <option value="地理">地理</option>
  <option value="物理">物理</option>
  <option value="化学">化学</option>
  <option value="生物">生物</option>
  <option value="__custom__">自定义</option>
</select>
<div id="custom-subject-group" style="display:none;margin-top:8px;">
  <input type="text" id="custom-subject" placeholder="输入科目名称">
</div>
<label>密码</label>
<input type="password" id="pwd" placeholder="至少6位">
<label>确认密码</label>
<input type="password" id="pwd2" placeholder="再次输入密码">
<button id="btn" onclick="doRegister()">注 册</button>
<div class="links">已有账号？<a href="/login">去登录</a></div>
</div>
<script>
document.getElementById('subject').addEventListener('change', function(){
  document.getElementById('custom-subject-group').style.display = this.value === '__custom__' ? 'block' : 'none';
});

// School autocomplete
let acTimer=null;
const schoolInput=document.getElementById('school-input');
const acList=document.getElementById('ac-list');
schoolInput.addEventListener('input',function(){
  clearTimeout(acTimer);
  const q=this.value.trim();
  document.getElementById('school-id').value='';
  if(q.length<1){acList.style.display='none';return;}
  acTimer=setTimeout(async()=>{
    const r=await fetch('/api/schools/search?q='+encodeURIComponent(q));
    const schools=await r.json();
    if(!schools.length){acList.style.display='none';return;}
    acList.innerHTML=schools.map(s=>`<div class="ac-item" data-id="${s.id}" data-name="${s.name}">${s.name}${s.aliases&&s.aliases.length?'<span class="alias"> ('+s.aliases.join('/')+')</span>':''}</div>`).join('');
    acList.style.display='block';
  },250);
});
acList.addEventListener('click',function(e){
  const item=e.target.closest('.ac-item');if(!item)return;
  schoolInput.value=item.dataset.name;document.getElementById('school-id').value=item.dataset.id;
  acList.style.display='none';
});
document.addEventListener('click',e=>{if(!e.target.closest('.autocomplete'))acList.style.display='none';});

async function doRegister(){
  const err=document.getElementById('err');err.style.display='none';
  const displayName=document.getElementById('display-name').value.trim();
  const schoolId=parseInt(document.getElementById('school-id').value)||0;
  const username=document.getElementById('username').value.trim();
  const phone=document.getElementById('phone').value.trim();
  let subject = document.getElementById('subject').value;
  if(subject === '__custom__'){subject = document.getElementById('custom-subject').value.trim();}
  if(!subject){err.textContent='请选择或输入科目';err.style.display='block';return;}
  if(!schoolId){err.textContent='请选择学校';err.style.display='block';return;}
  const pwd=document.getElementById('pwd').value;
  const pwd2=document.getElementById('pwd2').value;
  if(!username){err.textContent='请输入用户名';err.style.display='block';return;}
  if(username.length<3){err.textContent='用户名至少3位';err.style.display='block';return;}
  if(!/^[a-zA-Z0-9]+$/.test(username)){err.textContent='用户名仅限英文和数字';err.style.display='block';return;}
  if(phone && (phone.length!==11 || !/^\d+$/.test(phone))){err.textContent='请输入有效的11位手机号';err.style.display='block';return;}
  if(!pwd||pwd.length<6){err.textContent='密码至少6位';err.style.display='block';return;}
  if(pwd!==pwd2){err.textContent='两次密码不一致';err.style.display='block';return;}
  const btn=document.getElementById('btn');btn.disabled=true;btn.textContent='注册中...';
  try{
    const r=await fetch('/api/teacher-register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password:pwd,display_name:displayName,phone:phone,subject:subject,school_id:schoolId})});
    const d=await r.json();
    if(r.ok){window.location.href=d.redirect||'/';}
    else{err.textContent=d.error||'注册失败';err.style.display='block';}
  }catch(e){err.textContent='网络错误';err.style.display='block';}
  btn.disabled=false;btn.textContent='注 册';
}
document.querySelectorAll('input').forEach(i=>i.addEventListener('keydown',e=>{if(e.key==='Enter')doRegister();}));
</script>
</body>
</html>'''

STUDENT_REGISTER_PAGE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>学生注册 · 拾阶而上</title>
<style>
:root{--bg:#f8f7f4;--card:#fff;--accent:#e07b4b;--accent-hover:#d06a3a;--accent-light:#fef3ed;--text:#1a1a1a;--sub:#6b6b6b;--border:#e8e6e1;--red:#d93a46;--green:#0f7b4e;--green-light:#effaf3;--shadow:0 1px 3px rgba(0,0,0,.06),0 2px 8px rgba(0,0,0,.02)}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.card{background:var(--card);border-radius:12px;padding:36px 32px;box-shadow:var(--shadow);width:100%;max-width:420px}
h1{font-size:1.3rem;color:var(--text);margin-bottom:6px;text-align:center}
.subtitle{text-align:center;color:var(--sub);font-size:.85rem;margin-bottom:24px}
label{display:block;font-size:.8rem;font-weight:600;color:var(--sub);margin-bottom:6px;margin-top:14px}
label:first-of-type{margin-top:0}
input,select{width:100%;border:1px solid var(--border);border-radius:8px;padding:10px 12px;font-size:.9rem;transition:border-color .15s,box-shadow .15s}
input:focus,select:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-light);outline:none}
button{width:100%;background:var(--accent);color:#fff;border:none;border-radius:8px;padding:12px;font-size:.9rem;font-weight:600;cursor:pointer;transition:all .15s;margin-top:20px}
button:hover{background:var(--accent-hover);transform:translateY(-1px)}
button:disabled{opacity:.6;cursor:not-allowed;transform:none}
.error{color:var(--red);font-size:.8rem;margin-top:12px;display:none}
.success{color:var(--green);font-size:.8rem;margin-top:8px;display:none}
.links{text-align:center;margin-top:20px;font-size:.8rem;color:var(--sub)}
.links a{color:var(--accent);text-decoration:none}
.autocomplete{position:relative}
.ac-list{position:absolute;top:100%;left:0;right:0;background:var(--card);border:1px solid var(--border);border-radius:8px;box-shadow:var(--shadow);z-index:10;display:none;max-height:200px;overflow-y:auto}
.ac-item{padding:10px 12px;cursor:pointer;font-size:.85rem;border-bottom:1px solid var(--border)}
.ac-item:last-child{border-bottom:none}
.ac-item:hover{background:var(--accent-light)}
.ac-item .alias{color:var(--sub);font-size:.75rem}
.code-ok{color:var(--green);font-size:.75rem;margin-top:4px;display:none}
</style>
</head>
<body>
<div class="card">
<h1>🎯 真正个性化的学习，从这里开始</h1>
<p class="subtitle">注册学生账号</p>
<div class="error" id="err"></div>

<label>姓名</label>
<input type="text" id="name" placeholder="你的姓名">

<label>手机号</label>
<input type="tel" id="phone" placeholder="11位手机号" maxlength="11">

<label>密码</label>
<input type="password" id="pwd" placeholder="至少6位">

{% if feature_school %}
<label>学校</label>
<div class="autocomplete">
  <input type="text" id="school-input" placeholder="输入学校名称搜索..." autocomplete="off">
  <div class="ac-list" id="ac-list"></div>
</div>
<input type="hidden" id="school-id">

<label>班级</label>
<select id="class-select" disabled><option value="">请先选择学校</option></select>

<label>班级码</label>
<input type="text" id="class-code" placeholder="老师提供的6位班级码" maxlength="6">
<div class="code-ok" id="code-ok">✓ 班级码验证通过</div>
{% endif %}

<button id="btn" onclick="doRegister()">注 册</button>
<div class="links">已有账号？<a href="/login">去登录</a></div>
</div>
<script>
const hasSchoolFields = !!document.getElementById('school-input');
let acTimer=null;

if (hasSchoolFields) {
  const schoolInput=document.getElementById('school-input');
  const acList=document.getElementById('ac-list');
  const classSelect=document.getElementById('class-select');
  const codeOk=document.getElementById('code-ok');

  schoolInput.addEventListener('input',function(){
    clearTimeout(acTimer);
    const q=this.value.trim();
    document.getElementById('school-id').value='';
    classSelect.disabled=true;classSelect.innerHTML='<option value="">请先选择学校</option>';
    if(q.length<1){acList.style.display='none';return;}
    acTimer=setTimeout(async()=>{
      const r=await fetch('/api/schools/search?q='+encodeURIComponent(q));
      const schools=await r.json();
      if(!schools.length){acList.style.display='none';return;}
      acList.innerHTML=schools.map(s=>`<div class="ac-item" data-id="${s.id}" data-name="${s.name}">${s.name}${s.aliases&&s.aliases.length?'<span class="alias"> ('+s.aliases.join('/')+')</span>':''}</div>`).join('');
      acList.style.display='block';
    },250);
  });

  acList.addEventListener('click',function(e){
    const item=e.target.closest('.ac-item');
    if(!item)return;
    schoolInput.value=item.dataset.name;
    document.getElementById('school-id').value=item.dataset.id;
    acList.style.display='none';
    loadClasses(item.dataset.id);
  });

  document.addEventListener('click',e=>{if(!e.target.closest('.autocomplete'))acList.style.display='none';});

  async function loadClasses(schoolId){
    const r=await fetch('/api/classes?school_id='+schoolId);
    const classes=await r.json();
    classSelect.disabled=false;
    classSelect.innerHTML='<option value="">请选择班级</option>'+classes.map(c=>`<option value="${c.id}">${c.name}${c.grade?' ('+c.grade+')':''}</option>`).join('');
  }

  document.getElementById('class-code').addEventListener('blur',async function(){
    const code=this.value.trim();
    codeOk.style.display='none';
    if(code.length!==6)return;
    const r=await fetch('/api/class/verify-code',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({class_code:code})});
    if(r.ok){codeOk.style.display='block';}
  });
}

async function doRegister(){
  const err=document.getElementById('err');err.style.display='none';
  const name=document.getElementById('name').value.trim();
  const phone=document.getElementById('phone').value.trim();
  const pwd=document.getElementById('pwd').value;
  const classCodeEl=document.getElementById('class-code');
  const classCode=classCodeEl?classCodeEl.value.trim():'';
  if(!name){err.textContent='请输入姓名';err.style.display='block';return;}
  if(!phone||phone.length!==11){err.textContent='请输入11位手机号';err.style.display='block';return;}
  if(!pwd||pwd.length<6){err.textContent='密码至少6位';err.style.display='block';return;}
  if(hasSchoolFields&&!classCode){err.textContent='请输入班级码';err.style.display='block';return;}
  const btn=document.getElementById('btn');btn.disabled=true;btn.textContent='注册中...';
  try{
    const body={name,phone,password:pwd};
    if(classCode)body.class_code=classCode;
    const r=await fetch('/api/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const d=await r.json();
    if(r.ok){window.location.href=d.redirect||'/student';}
    else{err.textContent=d.error||'注册失败';err.style.display='block';}
  }catch(e){err.textContent='网络错误';err.style.display='block';}
  btn.disabled=false;btn.textContent='注 册';
}
</script>
</body>
</html>'''

STUDENT_DASHBOARD_PAGE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>我的学习 · 拾阶而上</title>
<style>
:root{--bg:#f8f7f4;--bg-alt:#f1f0ec;--card:#fff;--accent:#e07b4b;--accent-hover:#d06a3a;--accent-light:#fef3ed;--text:#1a1a1a;--text-alt:#37352f;--sub:#6b6b6b;--mute:#9b9b9b;--border:#e8e6e1;--green:#0f7b4e;--green-light:#effaf3;--red:#d93a46;--red-light:#fef4f4;--blue:#4b8dc7;--blue-light:#eef5fb;--shadow:0 1px 3px rgba(0,0,0,.06),0 2px 8px rgba(0,0,0,.02);--shadow-lg:0 4px 24px rgba(0,0,0,.08)}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--text-alt);line-height:1.6;font-size:.875rem}
.container{max-width:700px;margin:0 auto;padding:20px 16px}
header{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px}
header h1{font-size:1.2rem;color:var(--text)}
header .meta{font-size:.75rem;color:var(--sub)}
.logout-btn{background:none;border:1px solid var(--border);border-radius:6px;padding:4px 12px;font-size:.75rem;color:var(--sub);cursor:pointer}
.logout-btn:hover{border-color:var(--accent);color:var(--accent)}
.tabs{display:flex;gap:0;border-bottom:1px solid var(--border);margin-bottom:20px}
.tab{padding:10px 16px;font-size:.85rem;color:var(--sub);cursor:pointer;border-bottom:2px solid transparent;transition:all .15s}
.tab.active{color:var(--accent);border-bottom-color:var(--accent);font-weight:600}
.page{display:none}.page.active{display:block}
.card{background:var(--card);border-radius:10px;padding:20px;box-shadow:var(--shadow);margin-bottom:16px}
.card h3{font-size:.95rem;color:var(--text);margin-bottom:12px}
.upload-zone{border:2px dashed var(--border);border-radius:10px;padding:40px 20px;text-align:center;cursor:pointer;transition:all .2s}
.upload-zone:hover{border-color:var(--accent);background:var(--accent-light)}
.upload-zone p{color:var(--sub);font-size:.85rem;margin-top:8px}
.upload-zone .icon{font-size:2rem}
.btn{background:var(--accent);color:#fff;border:none;border-radius:8px;padding:10px 20px;font-size:.85rem;font-weight:600;cursor:pointer;transition:all .15s}
.btn:hover{background:var(--accent-hover)}
.btn:disabled{opacity:.6;cursor:not-allowed}
.btn-sm{padding:6px 14px;font-size:.8rem}
.report-item{display:flex;justify-content:space-between;align-items:center;padding:12px 0;border-bottom:1px solid var(--border)}
.report-item:last-child{border-bottom:none}
.report-item .type{font-weight:600;font-size:.85rem}
.report-item .date{font-size:.75rem;color:var(--sub)}
.badge{display:inline-block;padding:2px 10px;border-radius:100px;font-size:.7rem;font-weight:600}
.badge-green{background:var(--green-light);color:var(--green)}
.badge-blue{background:var(--blue-light);color:var(--blue)}
.progress-bar{height:8px;background:var(--bg-alt);border-radius:4px;overflow:hidden;margin-top:8px}
.progress-bar .fill{height:100%;background:var(--accent);border-radius:4px;transition:width .3s}
.empty{text-align:center;color:var(--mute);padding:40px 0;font-size:.85rem}
.task-status{margin-top:12px;padding:12px;background:var(--blue-light);border-radius:8px;font-size:.8rem;color:var(--blue);display:none}
</style>
</head>
<body>
<div class="container">
<header>
  <div><h1>📚 我的学习</h1><div class="meta" id="student-meta"></div></div>
  <button class="logout-btn" onclick="doLogout()">退出</button>
</header>

<div class="tabs">
  <div class="tab active" onclick="switchTab('upload')">上传试卷</div>
  <div class="tab" onclick="switchTab('reports')">我的报告</div>
  <div class="tab" onclick="switchTab('progress')">学习进度</div>
</div>

<div class="page active" id="page-upload">
  <div class="card">
    <h3>📷 上传试卷照片</h3>
    <div class="upload-zone" id="upload-zone" onclick="document.getElementById('file-input').click()">
      <div class="icon">📄</div>
      <p>点击选择试卷照片（支持 jpg/png）</p>
    </div>
    <input type="file" id="file-input" accept="image/*" style="display:none" onchange="handleFile(this)">
    <div id="file-preview" style="margin-top:12px;display:none">
      <img id="preview-img" style="max-width:100%;border-radius:8px;border:1px solid var(--border)">
    </div>
    <div style="margin-top:16px;display:flex;gap:12px;align-items:center">
      <select id="task-type" style="border:1px solid var(--border);border-radius:8px;padding:8px 12px;font-size:.85rem">
        <option value="onboarding">入学诊断（首次使用）</option>
        <option value="weekly">每周练习（常规）</option>
      </select>
      <button class="btn" id="submit-btn" onclick="submitUpload()" disabled>提交分析</button>
    </div>
    <div class="task-status" id="task-status"></div>
  </div>
</div>

<div class="page" id="page-reports">
  <div class="card">
    <h3>📋 已审核报告</h3>
    <div id="reports-list"><div class="empty">暂无报告</div></div>
  </div>
</div>

<div class="page" id="page-progress">
  <div class="card">
    <h3>📈 学习进度</h3>
    <div id="progress-content"><div class="empty">暂无数据，上传试卷后开始追踪</div></div>
  </div>
</div>
</div>

<script>
let selectedFile=null;

function switchTab(name){
  document.querySelectorAll('.tab').forEach((t,i)=>{t.classList.toggle('active',['upload','reports','progress'][i]===name);});
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.getElementById('page-'+name).classList.add('active');
  if(name==='reports')loadReports();
  if(name==='progress')loadProgress();
}

function handleFile(input){
  if(!input.files.length)return;
  selectedFile=input.files[0];
  const reader=new FileReader();
  reader.onload=e=>{document.getElementById('preview-img').src=e.target.result;document.getElementById('file-preview').style.display='block';};
  reader.readAsDataURL(selectedFile);
  document.getElementById('submit-btn').disabled=false;
}

async function submitUpload(){
  if(!selectedFile)return;
  const btn=document.getElementById('submit-btn');btn.disabled=true;btn.textContent='提交中...';
  const fd=new FormData();
  fd.append('file',selectedFile);
  fd.append('task_type',document.getElementById('task-type').value);
  fd.append('stage','full');
  try{
    const r=await fetch('/api/student/upload',{method:'POST',body:fd});
    const d=await r.json();
    if(r.ok||r.status===202){
      const st=document.getElementById('task-status');
      st.style.display='block';st.textContent='✅ 提交成功！AI正在分析你的试卷，请稍后在「我的报告」中查看结果。';
      selectedFile=null;document.getElementById('file-preview').style.display='none';
      document.getElementById('file-input').value='';
    }else{alert(d.error||'提交失败');}
  }catch(e){alert('网络错误');}
  btn.disabled=false;btn.textContent='提交分析';
}

async function loadReports(){
  const r=await fetch('/api/student/reports');
  const reports=await r.json();
  const el=document.getElementById('reports-list');
  if(!reports.length){el.innerHTML='<div class="empty">暂无已审核报告</div>';return;}
  const typeMap={onboarding:'入学诊断',weekly:'每周练习'};
  el.innerHTML=reports.map(rp=>`<div class="report-item"><div><span class="type">${typeMap[rp.task_type]||rp.task_type}</span><div class="date">${rp.completed_at||''}</div></div>${rp.file_id?'<a href="/api/files/'+rp.file_id+'/download" class="btn btn-sm" target="_blank">查看</a>':'<span class="badge badge-blue">处理中</span>'}</div>`).join('');
}

async function loadProgress(){
  const r=await fetch('/api/student/progress');
  const d=await r.json();
  const el=document.getElementById('progress-content');
  const stats=d.stats||{};
  const mistakes=d.recent_mistakes||[];
  if(!mistakes.length){el.innerHTML='<div class="empty">暂无数据，上传试卷后开始追踪</div>';return;}
  const total=mistakes.length;
  const mastered=mistakes.filter(m=>m.mastery_level>=2).length;
  const pct=total?Math.round(mastered/total*100):0;
  el.innerHTML=`<p style="margin-bottom:8px">错题总数：<b>${total}</b>，已掌握：<b style="color:var(--green)">${mastered}</b></p><div class="progress-bar"><div class="fill" style="width:${pct}%"></div></div><p style="font-size:.75rem;color:var(--sub);margin-top:4px">掌握率 ${pct}%</p>`;
}

async function doLogout(){
  await fetch('/logout',{method:'POST'});
  window.location.href='/login';
}

(async function init(){
  const r=await fetch('/api/student/me');
  if(r.ok){const s=await r.json();document.getElementById('student-meta').textContent=`${s.name} · ${s.school_name||''} ${s.class_name||''}`;}
})();
</script>
</body>
</html>'''


# ═══════════════════════════════════════════════════
# Routes: Auth
# ═══════════════════════════════════════════════════

LOGIN_PAGE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>登录 · 拾阶而上</title>
<style>
:root {
  --bg: #f8f7f4; --card: #fff; --text: #1a1a1a; --text-alt: #37352f; --sub: #6b6b6b; --mute:#9b9b9b;
  --accent: #e07b4b; --accent-hover: #d06a3a; --accent-light: #fef3ed;
  --green:#0f7b4e; --green-light:#effaf3;
  --red: #d93a46; --border: #e8e6e1; --shadow: 0 1px 3px rgba(0,0,0,.06), 0 2px 8px rgba(0,0,0,.02);
  --shadow-lg: 0 4px 24px rgba(0,0,0,.08); --radius: 8px;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; background:var(--bg); color:var(--text-alt); display:flex; align-items:center; justify-content:center; min-height:100vh; font-size:.875rem; padding:20px; }
.login-card { background:var(--card); border:none; border-radius:12px; padding:36px 32px; width:100%; max-width:380px; box-shadow:var(--shadow-lg); }
.login-card h1 { font-size:1.3rem; color:var(--text); margin-bottom:6px; text-align:center; font-weight:700; }
.login-card .sub { text-align:center; color:var(--sub); font-size:.8rem; margin-bottom:24px; }
.role-tabs { display:flex; background:var(--bg); border-radius:10px; padding:4px; margin-bottom:24px; }
.role-tab { flex:1; text-align:center; padding:9px 0; border-radius:8px; font-size:.85rem; color:var(--sub); cursor:pointer; transition:all .18s; font-weight:500; }
.role-tab.active { background:var(--card); color:var(--accent); font-weight:600; box-shadow:var(--shadow); }
.form-group { margin-bottom:16px; }
.form-group label { display:block; font-size:.8rem; color:var(--sub); margin-bottom:5px; font-weight:600; }
.form-group input {
  width:100%; padding:10px 12px; border:1px solid var(--border); border-radius:var(--radius); font-size:.9rem;
  font-family:inherit; transition:border-color .15s, box-shadow .15s;
}
.form-group input:focus { border-color:var(--accent); box-shadow: 0 0 0 3px var(--accent-light); outline:none; }
.btn { width:100%; padding:11px; border:none; border-radius:var(--radius); cursor:pointer; font-size:.95rem; font-weight:600; transition:all .15s; }
.btn:hover { transform:translateY(-1px); box-shadow:var(--shadow); }
.btn:disabled { opacity:.6; cursor:not-allowed; transform:none; }
.btn-primary { background:var(--accent); color:#fff; }
.btn-primary:hover { background:var(--accent-hover); }
.error { color:var(--red); font-size:.8rem; margin-top:10px; text-align:center; display:none; }
.links { text-align:center; margin-top:18px; font-size:.8rem; color:var(--sub); }
.links a { color:var(--accent); text-decoration:none; font-weight:600; }
.pane { display:none; } .pane.active { display:block; animation:fadeIn .2s ease; }
@keyframes fadeIn { from{opacity:0;transform:translateY(4px);} to{opacity:1;transform:none;} }
.hint { font-size:.72rem; color:var(--mute); text-align:center; margin-top:14px; }
</style>
</head>
<body>
<div class="login-card">
  <h1>📚 拾阶而上</h1>
  <p class="sub">AI 个性化英语学习平台</p>

  <div class="role-tabs">
    <div class="role-tab active" id="tab-student" onclick="switchRole('student')">学生</div>
    <div class="role-tab" id="tab-staff" onclick="switchRole('staff')">教师 / 管理员</div>
  </div>

  <div class="pane active" id="pane-student">
    <div class="form-group"><label>手机号</label><input type="tel" id="s-phone" placeholder="注册时的11位手机号" maxlength="11"></div>
    <div class="form-group" id="s-pwd-group"><label>密码</label><input type="password" id="s-pwd" placeholder="请输入密码"></div>
    <div class="form-group" id="s-code-group" style="display:none;">
      <label>验证码</label>
      <div style="display:flex;gap:8px;">
        <input type="text" id="s-code" placeholder="6位验证码" maxlength="6" style="flex:1;">
        <button type="button" class="btn btn-outline" id="s-send-btn" onclick="sendSmsCode('student')" style="width:auto;padding:10px 16px;font-size:.8rem;white-space:nowrap;">获取验证码</button>
      </div>
    </div>
    <button class="btn btn-primary" id="s-btn" onclick="studentLogin()">登 录</button>
    <div class="error" id="s-err"></div>
    <div class="links">
      <a href="javascript:void(0)" onclick="toggleSmsLogin('student')" id="s-sms-toggle">验证码登录</a>
       · 
      <a href="/register">立即注册</a>
    </div>
  </div>

  <div class="pane" id="pane-staff">
    <div class="form-group"><label>用户名</label><input type="text" id="t-user" placeholder="请输入用户名"></div>
    <div class="form-group" id="t-pwd-group"><label>密码</label><input type="password" id="t-pwd" placeholder="请输入密码"></div>
    <div class="form-group" id="t-phone-group" style="display:none;"><label>手机号</label><input type="tel" id="t-phone" placeholder="绑定的手机号" maxlength="11"></div>
    <div class="form-group" id="t-code-group" style="display:none;">
      <label>验证码</label>
      <div style="display:flex;gap:8px;">
        <input type="text" id="t-code" placeholder="6位验证码" maxlength="6" style="flex:1;">
        <button type="button" class="btn btn-outline" id="t-send-btn" onclick="sendSmsCode('staff')" style="width:auto;padding:10px 16px;font-size:.8rem;white-space:nowrap;">获取验证码</button>
      </div>
    </div>
    <button class="btn btn-primary" id="t-btn" onclick="staffLogin()">登 录</button>
    <div class="error" id="t-err"></div>
    <div class="links">
      <a href="javascript:void(0)" onclick="toggleSmsLogin('staff')" id="t-sms-toggle">验证码登录</a>
       · 
      <a href="/teacher-register">注册教师账号</a>
    </div>
  </div>
</div>
<script>
let _smsMode = {student: false, staff: false};

function switchRole(role){
  document.getElementById('tab-student').classList.toggle('active', role==='student');
  document.getElementById('tab-staff').classList.toggle('active', role==='staff');
  document.getElementById('pane-student').classList.toggle('active', role==='student');
  document.getElementById('pane-staff').classList.toggle('active', role==='staff');
}
function showErr(id,msg){const e=document.getElementById(id);e.textContent=msg;e.style.display='block';}
function hideErr(id){document.getElementById(id).style.display='none';}

function toggleSmsLogin(pane){
  _smsMode[pane] = !_smsMode[pane];
  if(pane === 'student'){
    document.getElementById('s-pwd-group').style.display = _smsMode.student ? 'none' : 'block';
    document.getElementById('s-code-group').style.display = _smsMode.student ? 'block' : 'none';
    document.getElementById('s-sms-toggle').textContent = _smsMode.student ? '密码登录' : '验证码登录';
  } else {
    document.getElementById('t-pwd-group').style.display = _smsMode.staff ? 'none' : 'block';
    document.getElementById('t-phone-group').style.display = _smsMode.staff ? 'block' : 'none';
    document.getElementById('t-code-group').style.display = _smsMode.staff ? 'block' : 'none';
    document.getElementById('t-sms-toggle').textContent = _smsMode.staff ? '密码登录' : '验证码登录';
  }
}

async function sendSmsCode(pane){
  const errId = pane === 'student' ? 's-err' : 't-err';
  const btnId = pane === 'student' ? 's-send-btn' : 't-send-btn';
  const phone = pane === 'student'
    ? document.getElementById('s-phone').value.trim()
    : document.getElementById('t-phone').value.trim();
  hideErr(errId);
  if(!phone || phone.length !== 11){showErr(errId,'请输入11位手机号');return;}
  const btn = document.getElementById(btnId);
  btn.disabled = true;
  let countdown = 60;
  btn.textContent = countdown + 's';
  const timer = setInterval(()=>{countdown--;btn.textContent=countdown+'s';if(countdown<=0){clearInterval(timer);btn.disabled=false;btn.textContent='获取验证码';}},1000);
  try{
    const r = await fetch('/api/sms/send-code',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({phone,purpose:'login'})});
    const d = await r.json();
    if(!r.ok){showErr(errId,d.error||'发送失败');clearInterval(timer);btn.disabled=false;btn.textContent='获取验证码';}
  }catch(e){showErr(errId,'网络错误');clearInterval(timer);btn.disabled=false;btn.textContent='获取验证码';}
}

async function studentLogin(){
  hideErr('s-err');
  const phone=document.getElementById('s-phone').value.trim();
  const btn=document.getElementById('s-btn');

  if(_smsMode.student){
    const code=document.getElementById('s-code').value.trim();
    if(!phone||!code){showErr('s-err','请填写手机号和验证码');return;}
    btn.disabled=true;btn.textContent='登录中...';
    try{
      const r=await fetch('/api/sms/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({phone,code})});
      const d=await r.json();
      if(r.ok){window.location.href=d.redirect||'/student';}
      else{showErr('s-err',d.error||'登录失败');}
    }catch(e){showErr('s-err','网络错误');}
    btn.disabled=false;btn.textContent='登 录';
  } else {
    const pwd=document.getElementById('s-pwd').value;
    if(!phone||!pwd){showErr('s-err','请填写手机号和密码');return;}
    btn.disabled=true;btn.textContent='登录中...';
    try{
      const r=await fetch('/api/student-login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({phone,password:pwd})});
      const d=await r.json();
      if(r.ok){window.location.href=d.redirect||'/student';}
      else{showErr('s-err',d.error||'登录失败');}
    }catch(e){showErr('s-err','网络错误');}
    btn.disabled=false;btn.textContent='登 录';
  }
}

async function staffLogin(){
  hideErr('t-err');
  const btn=document.getElementById('t-btn');

  if(_smsMode.staff){
    const phone=document.getElementById('t-phone').value.trim();
    const code=document.getElementById('t-code').value.trim();
    if(!phone||!code){showErr('t-err','请填写手机号和验证码');return;}
    btn.disabled=true;btn.textContent='登录中...';
    try{
      const r=await fetch('/api/sms/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({phone,code})});
      const d=await r.json();
      if(r.ok){window.location.href=d.redirect||'/';}
      else{showErr('t-err',d.error||'登录失败');}
    }catch(e){showErr('t-err','网络错误');}
    btn.disabled=false;btn.textContent='登 录';
  } else {
    const user=document.getElementById('t-user').value.trim();
    const pwd=document.getElementById('t-pwd').value;
    if(!user||!pwd){showErr('t-err','请填写用户名和密码');return;}
    btn.disabled=true;btn.textContent='登录中...';
    const fd=new FormData();fd.append('username',user);fd.append('password',pwd);
    try{
      const r=await fetch('/login',{method:'POST',body:fd});
      if(r.redirected){window.location.href=r.url;}
      else{showErr('t-err','用户名或密码错误');}
    }catch(e){showErr('t-err','网络错误');}
    btn.disabled=false;btn.textContent='登 录';
  }
}

document.querySelectorAll('#pane-student input').forEach(i=>i.addEventListener('keydown',e=>{if(e.key==='Enter')studentLogin();}));
document.querySelectorAll('#pane-staff input').forEach(i=>i.addEventListener('keydown',e=>{if(e.key==='Enter')staffLogin();}));
</script>
</body>
</html>'''


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        if 'user_id' in session:
            return redirect('/')
        return render_template_string(LOGIN_PAGE, error=None)

    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')

    user = get_admin_user(username)
    if user and check_password_hash(user['password_hash'], password):
        session['user_id'] = user['id']
        session['user_name'] = user['username']
        session['user_role'] = user['role']
        session['user_subject'] = user.get('subject', '')
        return redirect('/')

    return render_template_string(LOGIN_PAGE, error='用户名或密码错误'), 401


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect('/login')


@app.route('/api/auth/me')
def api_auth_me():
    if 'user_id' in session:
        return jsonify({
            'logged_in': True,
            'user_id': session['user_id'],
            'username': session.get('user_name'),
            'role': session.get('user_role'),
        })
    return jsonify({'logged_in': False}), 401


# ═══════════════════════════════════════════════════
# Routes: Student Registration & Login
# ═══════════════════════════════════════════════════

@app.route('/api/schools/search')
@feature_required('feature_school_enabled')
def api_schools_search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    return jsonify(search_schools(q))


@app.route('/api/classes')
@feature_required('feature_school_enabled')
def api_classes_by_school():
    school_id = request.args.get('school_id', type=int)
    if not school_id:
        return jsonify({"error": "school_id required"}), 400
    return jsonify(get_classes_by_school(school_id))


@app.route('/api/class/verify-code', methods=['POST'])
@feature_required('feature_school_enabled')
def api_verify_class_code():
    data = request.get_json(force=True)
    code = (data.get('class_code') or '').strip()
    if not code:
        return jsonify({"error": "请输入班级码"}), 400
    cls = get_class_by_code(code)
    if not cls:
        return jsonify({"error": "班级码无效，请检查后重试"}), 404
    return jsonify({"valid": True, "class_id": cls["id"], "class_name": cls["name"],
                    "school_name": cls.get("school_name", "")})


@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json(force=True)
    phone = (data.get('phone') or '').strip()
    password = data.get('password') or ''
    name = (data.get('name') or '').strip()
    class_code = (data.get('class_code') or '').strip()

    if not phone or not password or not name:
        return jsonify({"error": "手机号、密码和姓名为必填项"}), 400
    if len(phone) != 11 or not phone.isdigit():
        return jsonify({"error": "请输入11位手机号"}), 400
    if len(password) < 6:
        return jsonify({"error": "密码至少6位"}), 400

    school_id = None
    class_id = None
    grade = None
    cls = None
    if class_code:
        cls = get_class_by_code(class_code)
        if not cls:
            return jsonify({"error": "班级码无效，请检查后重试"}), 404
        school_id = cls["school_id"]
        class_id = cls["id"]
        grade = cls.get("grade")

    try:
        student_id = register_student(
            phone=phone,
            password_hash=generate_password_hash(password),
            name=name,
            school_id=school_id,
            class_id=class_id,
            grade=grade,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 409

    session['user_id'] = student_id
    session['user_name'] = name
    session['user_role'] = 'student'
    session['student_id'] = student_id
    log_audit(session.get('user_id'), 'student_register', f"学生注册: {name} ({phone})",
              details=f"class_id={cls['id'] if cls else None}")
    return jsonify({"ok": True, "student_id": student_id, "redirect": "/student"})


@app.route('/api/student-login', methods=['POST'])
def api_student_login():
    data = request.get_json(force=True)
    phone = (data.get('phone') or '').strip()
    password = data.get('password') or ''

    if not phone or not password:
        return jsonify({"error": "请输入手机号和密码"}), 400

    student = get_student_by_phone(phone)
    if not student or not student.get('password_hash'):
        return jsonify({"error": "手机号或密码错误"}), 401
    if not check_password_hash(student['password_hash'], password):
        return jsonify({"error": "手机号或密码错误"}), 401

    session['user_id'] = student['id']
    session['user_name'] = student['name']
    session['user_role'] = 'student'
    session['student_id'] = student['id']
    return jsonify({"ok": True, "redirect": "/student"})


# ═══════════════════════════════════════════════════
# Routes: SMS Verification Code Login (backup method)
# ═══════════════════════════════════════════════════

@app.route('/api/sms/send-code', methods=['POST'])
def api_sms_send_code():
    """Send SMS verification code for login or password reset."""
    from sms import send_verification_code
    data = request.get_json(force=True)
    phone = (data.get('phone') or '').strip()
    purpose = data.get('purpose', 'login')  # 'login' or 'reset_password'

    if not phone or len(phone) != 11 or not phone.isdigit():
        return jsonify({"error": "请输入有效的11位手机号"}), 400

    if purpose == 'login':
        # For login, check if phone exists in admin_users or students
        from sms import get_admin_by_phone
        admin = get_admin_by_phone(phone)
        student = get_student_by_phone(phone)
        if not admin and not student:
            return jsonify({"error": "该手机号未注册"}), 404
    elif purpose == 'reset_password':
        # For password reset, check if phone exists
        from sms import get_admin_by_phone
        admin = get_admin_by_phone(phone)
        student = get_student_by_phone(phone)
        if not admin and not student:
            return jsonify({"error": "该手机号未注册"}), 404

    code = send_verification_code(phone, purpose)
    return jsonify({"ok": True, "message": "验证码已发送"})


@app.route('/api/sms/login', methods=['POST'])
def api_sms_login():
    """Login using phone + SMS verification code."""
    from sms import verify_code, get_admin_by_phone
    data = request.get_json(force=True)
    phone = (data.get('phone') or '').strip()
    code = (data.get('code') or '').strip()

    if not phone or not code:
        return jsonify({"error": "请输入手机号和验证码"}), 400

    if not verify_code(phone, code, 'login'):
        return jsonify({"error": "验证码无效或已过期"}), 401

    # Try admin/teacher login first
    admin = get_admin_by_phone(phone)
    if admin:
        session['user_id'] = admin['id']
        session['user_name'] = admin['username']
        session['user_role'] = admin['role']
        session['user_subject'] = admin.get('subject', '')
        return jsonify({"ok": True, "redirect": "/"})

    # Try student login
    student = get_student_by_phone(phone)
    if student:
        session['user_id'] = student['id']
        session['user_name'] = student['name']
        session['user_role'] = 'student'
        session['student_id'] = student['id']
        return jsonify({"ok": True, "redirect": "/student"})

    return jsonify({"error": "该手机号未注册"}), 404


@app.route('/api/sms/reset-password', methods=['POST'])
def api_sms_reset_password():
    """Reset password using phone + SMS verification code."""
    from sms import verify_code, get_admin_by_phone
    data = request.get_json(force=True)
    phone = (data.get('phone') or '').strip()
    code = (data.get('code') or '').strip()
    new_password = data.get('new_password') or ''

    if not phone or not code or not new_password:
        return jsonify({"error": "请填写完整信息"}), 400
    if len(new_password) < 6:
        return jsonify({"error": "密码至少6位"}), 400

    if not verify_code(phone, code, 'reset_password'):
        return jsonify({"error": "验证码无效或已过期"}), 401

    # Try admin/teacher password reset
    admin = get_admin_by_phone(phone)
    if admin:
        conn = get_connection()
        conn.execute("UPDATE admin_users SET password_hash = ? WHERE id = ?",
                     [generate_password_hash(new_password), admin['id']])
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "message": "密码已重置"})

    # Try student password reset
    student = get_student_by_phone(phone)
    if student:
        conn = get_connection()
        conn.execute("UPDATE students SET password_hash = ? WHERE id = ?",
                     [generate_password_hash(new_password), student['id']])
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "message": "密码已重置"})

    return jsonify({"error": "该手机号未注册"}), 404


@app.route('/student-login')
def student_login_page():
    return redirect('/login')


@app.route('/register')
def register_page():
    return render_template_string(STUDENT_REGISTER_PAGE,
        feature_school=is_feature_enabled('feature_school_enabled'))


@app.route('/teacher-register')
@feature_required('feature_teacher_enabled')
def teacher_register_page():
    return render_template_string(TEACHER_REGISTER_PAGE)


@app.route('/api/teacher-register', methods=['POST'])
@feature_required('feature_teacher_enabled')
def api_teacher_register():
    data = request.get_json(force=True)
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    display_name = (data.get('display_name') or '').strip()
    phone = (data.get('phone') or '').strip()
    subject = (data.get('subject') or '').strip()
    school_id = data.get('school_id') or None

    if not username or not password:
        return jsonify({"error": "用户名和密码为必填项"}), 400
    if len(username) < 3:
        return jsonify({"error": "用户名至少3位"}), 400
    if not all(c.isascii() and c.isalnum() for c in username):
        return jsonify({"error": "用户名仅限英文和数字"}), 400
    if len(password) < 6:
        return jsonify({"error": "密码至少6位"}), 400
    if phone and (len(phone) != 11 or not phone.isdigit()):
        return jsonify({"error": "请输入有效的11位手机号"}), 400
    if not subject:
        return jsonify({"error": "请选择科目"}), 400
    if not school_id:
        return jsonify({"error": "请选择学校"}), 400

    existing = get_admin_user(username)
    if existing:
        return jsonify({"error": "该用户名已被使用"}), 409

    # Check phone uniqueness if provided
    if phone:
        from sms import get_admin_by_phone
        if get_admin_by_phone(phone):
            return jsonify({"error": "该手机号已被使用"}), 409

    create_admin_user(username, generate_password_hash(password), 'teacher', subject=subject)
    user = get_admin_user(username)

    # Save phone + school_id if provided
    if phone or school_id:
        conn2 = get_connection()
        updates = []
        params = []
        if phone:
            updates.append("phone = ?"); params.append(phone)
        if school_id:
            updates.append("school_id = ?"); params.append(school_id)
        params.append(user['id'])
        conn2.execute(f"UPDATE admin_users SET {', '.join(updates)} WHERE id = ?", params)
        conn2.commit()
        conn2.close()

    session['user_id'] = user['id']
    session['user_name'] = display_name or username
    session['user_role'] = 'teacher'
    session['user_subject'] = (user.get('subject') or '')
    log_audit(user['id'], 'teacher_register', f"教师注册: {display_name or username}")
    return jsonify({"ok": True, "redirect": "/"})


# ═══════════════════════════════════════════════════
# Routes: Student Self-Service
# ═══════════════════════════════════════════════════

@app.route('/student')
@student_required
def student_dashboard():
    return render_template_string(STUDENT_DASHBOARD_PAGE,
        student_name=session.get('user_name', ''))


@app.route('/api/student/me')
@student_required
def api_student_me():
    student = get_student(session['student_id'])
    if not student:
        return jsonify({"error": "not found"}), 404
    conn = get_connection()
    row = conn.execute("""
        SELECT s.*, sc.name as school_name, cl.name as class_name
        FROM students s
        LEFT JOIN schools sc ON sc.id = s.school_id
        LEFT JOIN classes cl ON cl.id = s.class_id
        WHERE s.id = ?
    """, [session['student_id']]).fetchone()
    conn.close()
    d = dict(row) if row else dict(student)
    d.pop('password_hash', None)
    return jsonify(d)


@app.route('/api/student/reports')
@student_required
def api_student_reports():
    """Get approved reports for the logged-in student."""
    sid = session['student_id']
    conn = get_connection()
    rows = conn.execute("""
        SELECT t.id, t.task_type, t.output_data, t.completed_at, t.current_step
        FROM ai_tasks t
        WHERE t.student_id = ? AND t.status = 'done' AND t.needs_review = 0
        ORDER BY t.completed_at DESC
        LIMIT 50
    """, [sid]).fetchall()
    conn.close()
    reports = []
    for r in rows:
        d = dict(r)
        try:
            output = json.loads(d.get("output_data") or "{}")
        except (json.JSONDecodeError, TypeError):
            output = {}
        file_id = output.get("report_file_id") or output.get("exercise_file_id") or output.get("feedback_file_id")
        reports.append({
            "task_id": d["id"],
            "task_type": d["task_type"],
            "completed_at": d["completed_at"],
            "file_id": file_id,
            "stage": output.get("stage", ""),
        })
    return jsonify(reports)


@app.route('/api/student/upload', methods=['POST'])
@student_required
def api_student_upload():
    """Student uploads a test paper photo and triggers the pipeline."""
    sid = session['student_id']
    if 'file' not in request.files:
        return jsonify({"error": "请选择文件"}), 400
    f = request.files['file']
    if not f.filename:
        return jsonify({"error": "请选择文件"}), 400

    task_type = request.form.get('task_type', 'onboarding')
    stage = request.form.get('stage', 'full')

    ext = os.path.splitext(f.filename)[1].lower() or '.png'
    filename = f"{uuid.uuid4().hex}{ext}"
    file_type = 'test_paper'
    save_dir = os.path.join(UPLOAD_DIR, str(sid), file_type)
    os.makedirs(save_dir, exist_ok=True)
    f.save(os.path.join(save_dir, filename))

    file_id = add_file(sid, file_type, filename, f.filename,
                       week_start=get_week_start(), uploader_role='student')

    input_data = {"file_id": file_id}
    if task_type == 'weekly':
        input_data["stage"] = stage
    task_id = create_task(sid, task_type, input_data)
    enqueue_task(task_id)

    return jsonify({"ok": True, "task_id": task_id, "file_id": file_id}), 202


@app.route('/api/student/progress')
@student_required
def api_student_progress():
    """Get learning progress for the logged-in student."""
    sid = session['student_id']
    stats = get_student_learning_stats(sid)
    mistakes = get_student_mistake_book(sid, limit=100)
    return jsonify({"stats": stats, "recent_mistakes": mistakes})


# ═══════════════════════════════════════════════════
# Routes: Teacher Class Dashboard
# ═══════════════════════════════════════════════════

@app.route('/api/my-classes')
@feature_required('feature_school_enabled')
@login_required
def api_my_classes():
    """Get classes assigned to the current teacher."""
    if session.get('user_role') == 'admin':
        conn = get_connection()
        rows = conn.execute("""
            SELECT c.*, s.name as school_name
            FROM classes c JOIN schools s ON s.id = c.school_id
            ORDER BY s.name, c.name
        """).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    teacher_id = session['user_id']
    return jsonify(get_classes_by_teacher(teacher_id))


@app.route('/api/class/<int:class_id>/stats')
@feature_required('feature_school_enabled')
@login_required
def api_class_stats(class_id):
    return jsonify(get_class_stats(class_id))


@app.route('/api/class/<int:class_id>/students')
@feature_required('feature_school_enabled')
@login_required
def api_class_students(class_id):
    return jsonify(get_students_by_class(class_id))


# ═══════════════════════════════════════════════════
# Routes: Admin — School & Class Management
# ═══════════════════════════════════════════════════

@app.route('/api/schools', methods=['GET', 'POST'])
@feature_required('feature_school_enabled')
@admin_required
def api_schools():
    if request.method == 'POST':
        data = request.get_json(force=True)
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({"error": "学校名称必填"}), 400
        school_id = create_school(name, data.get('aliases'), data.get('region'))
        return jsonify({"ok": True, "id": school_id}), 201
    return jsonify(get_all_schools())


@app.route('/api/schools/<int:school_id>', methods=['PUT', 'DELETE'])
@feature_required('feature_school_enabled')
@admin_required
def api_school_detail(school_id):
    if request.method == 'DELETE':
        delete_school(school_id)
        return jsonify({"ok": True})
    data = request.get_json(force=True)
    update_school(school_id, data)
    return jsonify({"ok": True})


@app.route('/api/admin/classes', methods=['GET', 'POST'])
@feature_required('feature_school_enabled')
@admin_required
def api_admin_classes():
    if request.method == 'POST':
        data = request.get_json(force=True)
        school_id = data.get('school_id')
        name = (data.get('name') or '').strip()
        if not school_id or not name:
            return jsonify({"error": "学校和班级名称必填"}), 400
        cls = create_class(school_id, name, data.get('grade'), data.get('teacher_id'))
        return jsonify(cls), 201
    school_id = request.args.get('school_id', type=int)
    if school_id:
        return jsonify(get_classes_by_school(school_id))
    conn = get_connection()
    rows = conn.execute("""
        SELECT c.*, s.name as school_name, au.username as teacher_name
        FROM classes c
        JOIN schools s ON s.id = c.school_id
        LEFT JOIN admin_users au ON au.id = c.teacher_id
        ORDER BY s.name, c.name
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/admin/classes/<int:class_id>', methods=['PUT', 'DELETE'])
@feature_required('feature_school_enabled')
@admin_required
def api_admin_class_detail(class_id):
    if request.method == 'DELETE':
        delete_class(class_id)
        return jsonify({"ok": True})
    data = request.get_json(force=True)
    update_class(class_id, data)
    return jsonify({"ok": True})


@app.route('/api/teacher/create-class', methods=['POST'])
@feature_required('feature_school_enabled')
@login_required
def api_teacher_create_class():
    """Teacher creates a class (auto-assigned to themselves)."""
    data = request.get_json(force=True)
    school_id = data.get('school_id')
    name = (data.get('name') or '').strip()
    if not school_id or not name:
        return jsonify({"error": "学校和班级名称必填"}), 400
    cls = create_class(school_id, name, data.get('grade'), teacher_id=session['user_id'])
    return jsonify(cls), 201


@app.route('/api/teacher/my-school')
@feature_required('feature_teacher_enabled')
@login_required
def api_teacher_my_school():
    """Return the current teacher's school info, or empty object."""
    conn = get_connection()
    user = conn.execute("SELECT * FROM admin_users WHERE id = ?", [session['user_id']]).fetchone()
    conn.close()
    if user and user['school_id']:
        school = get_school(user['school_id'])
        return jsonify(dict(school) if school else {})
    return jsonify({})


# ═══════════════════════════════════════════════════
# Routes: Pages
# ═══════════════════════════════════════════════════

@app.route('/')
@login_required
def index():
    return render_template_string(MAIN_PAGE,
        user_role=session.get('user_role'),
        user_name=session.get('user_name', ''),
        user_subject=session.get('user_subject', ''),
        feature_school=is_feature_enabled('feature_school_enabled'),
        feature_teacher=is_feature_enabled('feature_teacher_enabled'))


# ═══════════════════════════════════════════════════
# Routes: Dashboard
# ═══════════════════════════════════════════════════

@app.route('/api/dashboard')
@login_required
def api_dashboard():
    stats = get_dashboard_stats()
    if session.get('user_role') != 'admin':
        teacher_students = get_students_by_teacher(session['user_id'])
        teacher_ids = {s['id'] for s in teacher_students}
        stats['total_students'] = len(teacher_students)
        stats['trial_count'] = 0
        pending_filtered = [r for r in stats.get('pending', []) if r.get('id') in teacher_ids]
        stats['pending'] = pending_filtered
        stats['pending_this_week'] = sum(1 for r in pending_filtered if not r.get('exercises_sent'))
        review_filtered = [r for r in stats.get('review_queue', []) if r.get('student_id') in teacher_ids]
        stats['review_queue'] = review_filtered
    return jsonify(stats)


@app.route('/api/cost')
@login_required
def api_cost():
    budgets = get_budgets()
    total_month = get_llm_cost_this_month()
    return jsonify({
        "today": get_llm_cost_today(),
        "month": total_month,
        "monthly_total_budget": budgets["monthly_total_budget"],
        "monthly_student_budget": budgets["monthly_student_budget"],
        "total_budget_used_pct": round(
            total_month / budgets["monthly_total_budget"] * 100, 2
        ) if budgets["monthly_total_budget"] > 0 else 0,
        "breakdown": get_llm_cost_breakdown("month"),
    })


@app.route('/api/status')
@login_required
def api_status():
    from llm import BACKEND, HAS_API_KEY, DEFAULT_MODEL, ANTHROPIC_BASE_URL, OCR_BACKEND, VISION_MODEL
    return jsonify({
        "backend": BACKEND,
        "has_api_key": HAS_API_KEY,
        "model": DEFAULT_MODEL,
        "base_url": ANTHROPIC_BASE_URL or "default",
        "demo_mode": not HAS_API_KEY,
        "ocr_backend": OCR_BACKEND,
        "vision_model": VISION_MODEL or DEFAULT_MODEL,
    })


# ═══════════════════════════════════════════════════
# Routes: Students CRUD
# ═══════════════════════════════════════════════════

@app.route('/api/students', methods=['GET'])
@login_required
def api_students_list():
    if session.get('user_role') == 'admin':
        students = get_all_students()
    else:
        students = get_students_by_teacher(session['user_id'])
    for s in students:
        s["has_consent"] = has_parent_consent(s["id"])
    return jsonify(students)


@app.route('/api/students/<int:id>', methods=['GET'])
@login_required
def api_student_get(id):
    row = get_student(id)
    if not row:
        return '', 404
    row["has_consent"] = has_parent_consent(id)
    return jsonify(row)


@app.route('/api/students', methods=['POST'])
@login_required
def api_student_create():
    data = request.get_json()
    if not data.get('name'):
        return jsonify({"error": "name required"}), 400
    sid = create_student(data)

    # Handle referral code if provided
    invite_code = data.get('invite_code', '').strip()
    if invite_code:
        record_referral(invite_code, sid)

    # Record parent consent if provided
    if data.get('parent_consent'):
        record_parent_consent(
            student_id=sid,
            consented_by=data.get('parent_name', 'unknown'),
            contact=data.get('parent_phone') or data.get('parent_wechat', ''),
            ip_address=request.remote_addr,
            notes='创建学生时获得家长授权',
        )

    # Audit log
    log_audit(
        actor_type='teacher',
        actor_id=str(session.get('user_id')),
        action='create_student',
        target_type='student',
        target_id=str(sid),
        details={"name": data.get('name')},
        ip_address=request.remote_addr,
    )

    return jsonify({"id": sid}), 201


@app.route('/api/students/<int:id>', methods=['PUT'])
@login_required
def api_student_update(id):
    data = request.get_json()
    if not data.get('name'):
        return jsonify({"error": "name required"}), 400
    update_student(id, data)

    # Record parent consent if newly provided
    if data.get('parent_consent') and not has_parent_consent(id):
        record_parent_consent(
            student_id=id,
            consented_by=data.get('parent_name', 'unknown'),
            contact=data.get('parent_phone') or data.get('parent_wechat', ''),
            ip_address=request.remote_addr,
            notes='更新学生信息时获得家长授权',
        )

    log_audit(
        actor_type='teacher',
        actor_id=str(session.get('user_id')),
        action='update_student',
        target_type='student',
        target_id=str(id),
        details={"name": data.get('name')},
        ip_address=request.remote_addr,
    )

    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════
# Routes: Student Profile (chat.md dimensions)
# ═══════════════════════════════════════════════════

@app.route('/api/students/<int:student_id>/profile', methods=['GET'])
@login_required
def api_student_profile_get(student_id):
    """Get student profile (chat.md dimensions)."""
    profile = get_student_profile(student_id)
    if not profile:
        return jsonify({}), 200
    return jsonify(profile)


@app.route('/api/students/<int:student_id>/profile', methods=['PUT'])
@login_required
def api_student_profile_update(student_id):
    """Create or update student profile."""
    data = request.get_json() or {}
    save_student_profile(student_id, data)

    # Sync frequently-queried fields to students table
    conn = get_connection()
    conn.execute("""
        UPDATE students SET gender = ?, textbook_version = ?, semester = ?
        WHERE id = ?
    """, [data.get("gender"), data.get("textbook_version"), data.get("semester"), student_id])
    conn.commit()
    conn.close()

    log_audit(
        actor_type='teacher',
        actor_id=str(session.get('user_id')),
        action='update_student_profile',
        target_type='student',
        target_id=str(student_id),
        details={"has_profile": True},
        ip_address=request.remote_addr,
    )
    return jsonify({"ok": True})


@app.route('/api/students/<int:student_id>/profile/parent-tasks', methods=['PUT'])
@login_required
def api_student_parent_tasks_update(student_id):
    """Update parent growth task completion progress."""
    data = request.get_json() or {}
    progress = data.get("parent_task_progress", {})
    profile = get_student_profile(student_id) or {}
    existing = profile.get("parent_task_progress") or {}
    if isinstance(existing, str):
        try:
            existing = json.loads(existing)
        except Exception:
            existing = {}
    existing.update(progress)
    save_student_profile(student_id, {"parent_task_progress": existing})

    log_audit(
        actor_type='teacher',
        actor_id=str(session.get('user_id')),
        action='update_parent_task_progress',
        target_type='student',
        target_id=str(student_id),
        details={"progress": existing},
        ip_address=request.remote_addr,
    )
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════
# Routes: Student Learning Loop (Mistake Book + Check-ins)
# ═══════════════════════════════════════════════════

@app.route('/api/students/<int:student_id>/mistakes', methods=['GET'])
@login_required
def api_student_mistakes(student_id):
    """Get mistake book for a student (backend view)."""
    mastered = request.args.get('mastered', 'false').lower() == 'true'
    return jsonify(get_student_mistake_book(student_id, mastered=mastered))


@app.route('/api/mistakes/<int:mistake_id>/master', methods=['POST'])
@login_required
def api_mark_mistake_mastered(mistake_id):
    """Mark a mistake as mastered."""
    success = mark_mistake_mastered(mistake_id)
    if not success:
        return jsonify({"error": "错题不存在"}), 404
    return jsonify({"ok": True})


@app.route('/api/students/<int:student_id>/due-reviews', methods=['GET'])
@login_required
def api_student_due_reviews(student_id):
    """Get mistakes due for spaced repetition review."""
    from db import get_due_reviews, get_review_stats
    return jsonify({
        "due_reviews": get_due_reviews(student_id),
        "stats": get_review_stats(student_id),
    })


# ═══════════════════════════════════════════════════
# Routes: Achievement Wall
# ═══════════════════════════════════════════════════

@app.route('/api/students/<int:student_id>/achievements', methods=['GET'])
@login_required
def api_student_achievements(student_id):
    """Get achievement wall for a student (teacher view)."""
    from db import get_student_achievements
    return jsonify(get_student_achievements(student_id))


@app.route('/api/public/<code>/achievements', methods=['GET'])
def api_public_achievements(code):
    """Public: get achievement wall by access code."""
    from db import get_connection, get_student_achievements
    conn = get_connection()
    student = conn.execute(
        "SELECT id FROM students WHERE access_code = ? AND status = 'active'", [code]
    ).fetchone()
    conn.close()
    if not student:
        return jsonify({"error": "invalid code"}), 404
    return jsonify(get_student_achievements(student["id"]))


# ═══════════════════════════════════════════════════
# Routes: Metacognitive Review (元认知复盘表)
# ═══════════════════════════════════════════════════

@app.route('/api/public/<code>/review', methods=['GET'])
def api_public_review(code):
    """Public: get metacognitive review for current week."""
    from db import get_connection, get_or_create_metacognitive_review, get_metacognitive_reviews
    conn = get_connection()
    student = conn.execute(
        "SELECT id FROM students WHERE access_code = ? AND status = 'active'", [code]
    ).fetchone()
    conn.close()
    if not student:
        return jsonify({"error": "invalid code"}), 404
    sid = student["id"]
    week = request.args.get("week", "")
    review = get_or_create_metacognitive_review(sid, week or None)
    history = get_metacognitive_reviews(sid, limit=8)
    return jsonify({"review": review, "history": history})


@app.route('/api/public/<code>/review', methods=['POST'])
def api_public_review_submit(code):
    """Public: submit metacognitive review for current week."""
    from db import get_connection, submit_metacognitive_review, get_week_start
    conn = get_connection()
    student = conn.execute(
        "SELECT id FROM students WHERE access_code = ? AND status = 'active'", [code]
    ).fetchone()
    conn.close()
    if not student:
        return jsonify({"error": "invalid code"}), 404
    sid = student["id"]
    data = request.get_json() or {}
    week = data.get("week_start", get_week_start())
    success = submit_metacognitive_review(
        student_id=sid,
        week_start=week,
        child_answers=data.get("child_answers"),
        parent_answers=data.get("parent_answers"),
        child_mood=data.get("child_mood"),
        parent_mood=data.get("parent_mood"),
        child_note=data.get("child_note"),
        parent_note=data.get("parent_note"),
    )
    if not success:
        return jsonify({"error": "提交失败"}), 500
    return jsonify({"ok": True})


@app.route('/api/students/<int:student_id>/reviews', methods=['GET'])
@login_required
def api_student_reviews(student_id):
    """Teacher: get all metacognitive reviews for a student."""
    from db import get_metacognitive_reviews, get_or_create_metacognitive_review
    current = get_or_create_metacognitive_review(student_id)
    history = get_metacognitive_reviews(student_id)
    return jsonify({"current": current, "history": history})


# ═══════════════════════════════════════════════════
# Routes: Learning Path Timeline
# ═══════════════════════════════════════════════════

@app.route('/api/students/<int:student_id>/timeline', methods=['GET'])
@login_required
def api_student_timeline(student_id):
    """Get learning path timeline for a student (teacher view)."""
    from db import get_student_timeline
    return jsonify({"milestones": get_student_timeline(student_id)})


@app.route('/api/public/<code>/timeline', methods=['GET'])
def api_public_timeline(code):
    """Public: get learning path timeline by access code."""
    from db import get_connection, get_student_timeline
    conn = get_connection()
    student = conn.execute(
        "SELECT id FROM students WHERE access_code = ? AND status = 'active'", [code]
    ).fetchone()
    conn.close()
    if not student:
        return jsonify({"error": "invalid code"}), 404
    return jsonify({"milestones": get_student_timeline(student["id"])})


@app.route('/api/mistakes/<int:mistake_id>/similar', methods=['GET'])
def api_get_similar_questions(mistake_id):
    """Get existing similar questions for a mistake."""
    from skills_bridge import get_similar_questions_for_mistake
    return jsonify({"questions": get_similar_questions_for_mistake(mistake_id)})


@app.route('/api/mistakes/<int:mistake_id>/similar', methods=['POST'])
def api_generate_similar_questions(mistake_id):
    """Generate similar questions for a mistake via AI.
    Public access allowed with valid access_code matching the mistake's student."""
    from db import get_mistake, get_connection
    from skills_bridge import generate_similar_questions as gen_similar, get_similar_questions_for_mistake
    mistake = get_mistake(mistake_id)
    if not mistake:
        return jsonify({"error": "错题不存在"}), 404
    # Validate access code
    data = request.get_json() or {}
    code = data.get("access_code", "")
    if code:
        conn = get_connection()
        student = conn.execute(
            "SELECT id FROM students WHERE access_code = ? AND status = 'active' AND id = ?",
            [code, mistake["student_id"]],
        ).fetchone()
        conn.close()
        if not student:
            return jsonify({"error": "无权限"}), 403
    count = int(data.get("count", 2))
    saved = gen_similar(mistake, count=count)
    return jsonify({"questions": saved})


@app.route('/api/students/<int:student_id>/batch-similar', methods=['POST'])
def api_batch_generate_similar(student_id):
    """Batch generate similar questions. Accepts access_code for public access."""
    from db import get_student_mistake_book, get_connection
    from skills_bridge import generate_similar_questions as gen_similar
    data = request.get_json() or {}
    # Validate access code
    code = data.get("access_code", "")
    if code:
        conn = get_connection()
        student = conn.execute(
            "SELECT id FROM students WHERE access_code = ? AND status = 'active' AND id = ?",
            [code, student_id],
        ).fetchone()
        conn.close()
        if not student:
            return jsonify({"error": "无权限"}), 403
    mistakes = get_student_mistake_book(student_id, mastered=False)
    limit = min(int(data.get("limit", 10)), 10)
    count_per = int(data.get("count_per", 2))
    results = []
    for m in mistakes[:limit]:
        # Skip if already has similar questions
        existing = get_similar_questions_for_mistake(m["id"])
        if len(existing) >= count_per:
            results.append({"mistake_id": m["id"], "questions": existing, "cached": True})
            continue
        saved = gen_similar(m, count=count_per)
        results.append({"mistake_id": m["id"], "questions": saved, "cached": False})
    return jsonify({"results": results})


@app.route('/api/students/<int:student_id>/checkins', methods=['GET'])
@login_required
def api_student_checkins(student_id):
    """Get check-in history for a student."""
    return jsonify(get_check_ins(student_id))


@app.route('/api/checkin', methods=['POST'])
def api_check_in():
    """Public check-in endpoint (no auth, validated by access_code)."""
    data = request.get_json() or {}
    code = data.get('access_code')
    if not code:
        return jsonify({"error": "access_code required"}), 400

    conn = get_connection()
    student = conn.execute(
        "SELECT id FROM students WHERE access_code = ? AND status = 'active'", [code]
    ).fetchone()
    conn.close()
    if not student:
        return jsonify({"error": "invalid access_code"}), 404

    record_check_in(
        student_id=student["id"],
        check_in_date=data.get('check_in_date'),
        content=data.get('content', ''),
        duration_minutes=data.get('duration_minutes', 0),
        source='manual',
    )
    return jsonify({"ok": True}), 201


@app.route('/api/public/<code>', methods=['GET'])
def api_public_summary(code):
    """Public summary for student page."""
    summary = get_student_public_summary(code)
    if not summary:
        return jsonify({"error": "invalid or expired code"}), 404
    summary["teacher"] = {}  # per-teacher profiles not exposed on public page
    return jsonify(summary)


# ═══════════════════════════════════════════════════
# Routes: Public Interactive Practice (P0)
# ═══════════════════════════════════════════════════

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


@app.route('/api/public/<code>/practice', methods=['GET'])
def api_public_practice(code):
    """Get interactive practice questions for a student (public, no login)."""
    student_id, err = _resolve_student_by_code(code)
    if err:
        return err

    conn = get_connection()
    # Get questions linked to this student's mistakes via source_mistake_id
    rows = conn.execute("""
        SELECT q.id, q.question_text, q.question_type, q.correct_answer,
               q.explanation, q.knowledge_points, q.difficulty, q.source_mistake_id
        FROM questions q
        JOIN mistakes m ON m.id = q.source_mistake_id
        WHERE m.student_id = ? AND q.enabled = 1 AND m.consecutive_correct < 2
        ORDER BY q.created_at DESC
        LIMIT 15
    """, [student_id]).fetchall()
    conn.close()

    # Fallback: if no linked questions, search by knowledge points from student's mistakes
    if not rows:
        conn = get_connection()
        unmastered_kps = conn.execute("""
            SELECT DISTINCT knowledge_points FROM mistakes
            WHERE student_id = ? AND consecutive_correct < 2
        """, [student_id]).fetchall()
        conn.close()
        all_kps = set()
        for r in unmastered_kps:
            kp_data = r["knowledge_points"]
            if isinstance(kp_data, str):
                try:
                    kp_data = json.loads(kp_data)
                except Exception:
                    kp_data = [kp_data]
            if isinstance(kp_data, list):
                all_kps.update(kp_data)
        if all_kps:
            from db import find_similar_questions
            raw = find_similar_questions(list(all_kps), limit=15)
            rows = [dict(r) if not isinstance(r, dict) else r for r in raw]

    questions = []
    for q in rows:
        kp = q["knowledge_points"]
        if isinstance(kp, str):
            try:
                kp = json.loads(kp)
            except Exception:
                kp = []
        questions.append({
            "id": q["id"],
            "question_text": q["question_text"],
            "question_type": q["question_type"] or "选择题",
            "options": _extract_options(q["question_text"]),
            "knowledge_points": kp if isinstance(kp, list) else [kp],
            "difficulty": q["difficulty"],
            "source_mistake_id": q["source_mistake_id"],
        })

    return jsonify({"questions": questions, "total": len(questions)})


def _extract_options(question_text):
    """Extract A/B/C/D options from question text if embedded."""
    import re
    options = re.findall(r'([A-D])\.\s*(.+?)(?=\s*[A-D]\.|$)', question_text)
    if len(options) >= 3:
        return [{"key": k, "text": v.strip()} for k, v in options]
    return []


@app.route('/api/public/<code>/practice/submit', methods=['POST'])
def api_public_practice_submit(code):
    """Submit a single answer, get instant feedback, update mastery."""
    student_id, err = _resolve_student_by_code(code)
    if err:
        return err

    data = request.get_json() or {}
    question_id = data.get("question_id")
    student_answer = data.get("answer", "").strip()

    if not question_id or not student_answer:
        return jsonify({"error": "question_id and answer required"}), 400

    conn = get_connection()
    q = conn.execute(
        "SELECT * FROM questions WHERE id = ? AND enabled = 1", [question_id]
    ).fetchone()
    conn.close()

    if not q:
        return jsonify({"error": "question not found"}), 404

    correct_answer = (q["correct_answer"] or "").strip()
    is_correct = student_answer.upper() == correct_answer.upper()

    # Update mastery via record_practice
    source_mistake_id = q["source_mistake_id"]
    if source_mistake_id:
        record_practice(
            mistake_id=source_mistake_id,
            user_answer=student_answer,
            is_correct=is_correct,
            feedback=q["explanation"] or "",
        )

    return jsonify({
        "is_correct": is_correct,
        "correct_answer": correct_answer,
        "explanation": q["explanation"] or "",
        "knowledge_points": json.loads(q["knowledge_points"]) if isinstance(q["knowledge_points"], str) else q["knowledge_points"],
    })


@app.route('/api/public/<code>/exercise-pdf', methods=['GET'])
def api_public_exercise_pdf(code):
    """Download practice exercises as a print-friendly PDF."""
    student_id, err = _resolve_student_by_code(code)
    if err:
        return err

    student = get_student(student_id)
    if not student:
        return jsonify({"error": "student not found"}), 404

    # Load questions (same logic as practice endpoint)
    conn = get_connection()
    rows = conn.execute("""
        SELECT q.question_text, q.question_type, q.correct_answer,
               q.explanation, q.knowledge_points, q.difficulty
        FROM questions q
        JOIN mistakes m ON m.id = q.source_mistake_id
        WHERE m.student_id = ? AND q.enabled = 1 AND m.consecutive_correct < 2
        ORDER BY q.created_at DESC
        LIMIT 15
    """, [student_id]).fetchall()
    conn.close()

    if not rows:
        return jsonify({"error": "暂无练习题，请先上传试卷"}), 404

    questions = []
    for q in rows:
        kp = q["knowledge_points"]
        if isinstance(kp, str):
            try:
                kp = json.loads(kp)
            except Exception:
                kp = []
        questions.append({
            "question_text": q["question_text"],
            "question_type": q["question_type"] or "选择题",
            "options": _extract_options(q["question_text"]),
            "knowledge_points": kp if isinstance(kp, list) else [kp],
            "difficulty": q["difficulty"],
        })

    # Format options for PDF renderer
    for q in questions:
        if q["options"]:
            q["options"] = [f"{o['key']}. {o['text']}" for o in q["options"]]

    from report_templates import render_exercise_pdf
    from io import BytesIO
    pdf_bytes = render_exercise_pdf(student["name"], questions, get_week_start())

    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"练习题-{student['name']}-{get_week_start()}.pdf",
    )


# ═══════════════════════════════════════════════════
# Routes: Public Parent Upload (P0)
# ═══════════════════════════════════════════════════

@app.route('/api/public/<code>/upload', methods=['POST'])
def api_public_upload(code):
    """Parent uploads test paper photo from public page. Auto-triggers pipeline."""
    student_id, err = _resolve_student_by_code(code)
    if err:
        return err

    if 'file' not in request.files:
        return jsonify({"error": "no file uploaded"}), 400

    files = request.files.getlist('file')
    if not files:
        return jsonify({"error": "no file uploaded"}), 400

    # Save files
    import uuid as _uuid
    week_start = get_week_start()
    file_ids = []
    for f in files:
        if not f or not f.filename:
            continue
        ext = os.path.splitext(f.filename)[1] or '.jpg'
        filename = f"{_uuid.uuid4().hex}{ext}"
        save_dir = os.path.join(UPLOAD_DIR, str(student_id), "test_paper")
        os.makedirs(save_dir, exist_ok=True)
        f.save(os.path.join(save_dir, filename))
        fid = add_file(
            student_id=student_id,
            uploader_role="parent",
            file_type="test_paper",
            filename=filename,
            original_filename=f.filename,
            week_start=week_start,
            file_size=os.path.getsize(os.path.join(save_dir, filename)),
            mime_type=f.content_type or "image/jpeg",
        )
        file_ids.append(fid)

    if not file_ids:
        return jsonify({"error": "no valid files"}), 400

    # Auto-trigger pipeline: grade_only (consumes 1 quota)
    sub = get_subscription(student_id)
    if not sub or sub.get("status") != "active":
        return jsonify({"error": "订阅已过期，请联系老师续费"}), 429
    has_quota, remaining = check_quota(student_id)
    if not has_quota:
        plan_label = PRICING.get(sub.get("plan", "trial"), {}).get("label", "体验")
        return jsonify({
            "error": f"本月 {plan_label} 额度已用完（剩余 {remaining} 次），请续费或升级套餐",
        }), 429
    if not consume_quota(student_id):
        return jsonify({"error": "额度扣减失败，请刷新后重试"}), 429

    task_id = create_task(
        student_id=student_id,
        task_type="weekly",
        input_data={"file_ids": file_ids, "stage": "grade_only"},
    )
    enqueue_task(task_id)

    return jsonify({"task_id": task_id, "file_ids": file_ids, "message": "试卷已上传，AI正在分析中"}), 202


@app.route('/api/public/<code>/task/<int:task_id>', methods=['GET'])
def api_public_task_status(code, task_id):
    """Public task progress polling (validated by access_code).
    If grade_only is done but a chained analysis_only is still running,
    report overall status as processing."""
    student_id, err = _resolve_student_by_code(code)
    if err:
        return err

    task = get_task(task_id)
    if not task or task["student_id"] != student_id:
        return jsonify({"error": "task not found"}), 404

    status = task["status"]
    current_step = task.get("current_step", "")
    progress = task.get("progress", 0)
    output = task.get("output_data")
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except Exception:
            output = None
    elif isinstance(output, dict):
        pass  # already parsed
    else:
        output = None

    # If grade_only is done, check for chained analysis_only task
    if status == "done":
        input_data = task.get("input_data") or "{}"
        if isinstance(input_data, str):
            try:
                input_data = json.loads(input_data)
            except Exception:
                input_data = {}
        if input_data.get("stage") == "grade_only":
            conn = get_connection()
            chained = conn.execute("""
                SELECT id, status, current_step, progress, output_data
                FROM ai_tasks
                WHERE student_id = ? AND task_type = 'weekly' AND id > ?
                  AND input_data LIKE '%analysis_only%'
                ORDER BY id DESC LIMIT 1
            """, [student_id, task_id]).fetchone()
            conn.close()
            if chained:
                if chained["status"] in ("pending", "processing"):
                    status = "processing"
                    current_step = chained["current_step"] or "生成练习题和报告..."
                    progress = 50 + (chained["progress"] or 0) // 2
                elif chained["status"] == "done":
                    chained_out = json.loads(chained["output_data"]) if chained["output_data"] else {}
                    if output:
                        output["questions_count"] = chained_out.get("questions_count", 0)
                        output["exercise_file_id"] = chained_out.get("exercise_file_id")
                        output["report_file_id"] = chained_out.get("report_file_id")

    return jsonify({
        "id": task["id"],
        "status": status,
        "current_step": current_step,
        "progress": progress,
        "error_message": task.get("error_message"),
        "output_data": output,
    })


# ═══════════════════════════════════════════════════
# Routes: Referral / Viral Growth
# ═══════════════════════════════════════════════════

@app.route('/api/referrals/my/<code>', methods=['GET'])
def api_my_referrals(code):
    """Public: get referral info for a student by access_code."""
    conn = get_connection()
    student = conn.execute(
        "SELECT id FROM students WHERE access_code = ? AND status = 'active'", [code]
    ).fetchone()
    conn.close()
    if not student:
        return jsonify({"error": "invalid code"}), 404

    # Ensure invite code exists
    invite_code = get_or_create_referral_code(student["id"])
    info = get_student_referrals(student["id"])
    info["invite_code"] = invite_code
    return jsonify(info)


@app.route('/api/referrals/validate/<invite_code>', methods=['GET'])
def api_validate_referral(invite_code):
    """Public: validate an invite code."""
    referrer = lookup_referrer_by_code(invite_code)
    if not referrer:
        return jsonify({"valid": False}), 404
    return jsonify({
        "valid": True,
        "referrer_name": referrer["name"],
        "reward_weeks": int(get_setting("referral_reward_weeks") or "1"),
    })


@app.route('/api/referrals/stats', methods=['GET'])
@login_required
def api_referral_stats():
    return jsonify(get_referral_stats())


@app.route('/api/referrals/settings', methods=['POST'])
@admin_required
def api_referral_settings():
    data = request.get_json() or {}
    try:
        weeks = int(data.get("reward_weeks", 1))
        if weeks < 0:
            raise ValueError
        set_setting("referral_reward_weeks", str(weeks))
    except (ValueError, TypeError):
        return jsonify({"error": "奖励周数必须是非负整数"}), 400
    return jsonify({"reward_weeks": weeks})


@app.route('/api/poster/<code>', methods=['GET'])
def api_generate_poster(code):
    """Generate shareable poster HTML for a student."""
    summary = get_student_public_summary(code)
    if not summary:
        return jsonify({"error": "invalid code"}), 404

    from report_templates import render_share_poster
    poster_html = render_share_poster(summary["student"], {
        "current_score": summary["student"].get("english_score"),
        "target_score": summary["student"].get("target_score"),
        "mastered_count": summary["mastered_count"],
        "mistakes_count": summary["mistakes_count"],
        "check_in_count": len(summary["check_ins"]),
    })

    # Save as file
    poster_dir = os.path.join(UPLOAD_DIR, str(summary["student"]["id"]), "posters")
    os.makedirs(poster_dir, exist_ok=True)
    filename = f"poster_{date.today().isoformat()}_{uuid.uuid4().hex[:8]}.html"
    filepath = os.path.join(poster_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(poster_html)

    file_id = add_file(
        student_id=summary["student"]["id"],
        uploader_role="system",
        file_type="poster",
        filename=filename,
        original_filename=f"{summary['student']['name']}的学习海报.html",
        file_size=os.path.getsize(filepath),
        mime_type="text/html",
    )
    return jsonify({"file_id": file_id, "path": filepath})


# ═══════════════════════════════════════════════════
# Routes: Question Bank
# ═══════════════════════════════════════════════════

@app.route('/api/questions', methods=['GET'])
@login_required
def api_questions_list():
    kp = request.args.get('knowledge_point')
    qtype = request.args.get('question_type')
    enabled_only = request.args.get('enabled_only', 'true').lower() == 'true'
    limit = request.args.get('limit', 100, type=int)
    return jsonify(get_questions(
        knowledge_point=kp,
        question_type=qtype,
        enabled_only=enabled_only,
        limit=limit,
    ))


@app.route('/api/questions/<int:question_id>', methods=['GET'])
@login_required
def api_question_get(question_id):
    q = get_question(question_id)
    return jsonify(q) if q else ('', 404)


@app.route('/api/questions/<int:question_id>', methods=['PUT'])
@login_required
def api_question_update(question_id):
    data = request.get_json() or {}
    success = update_question(question_id, data)
    if not success:
        return jsonify({"error": "题目不存在或无有效字段"}), 400
    return jsonify({"ok": True})


@app.route('/api/questions/<int:question_id>/toggle', methods=['POST'])
@login_required
def api_question_toggle(question_id):
    q = get_question(question_id)
    if not q:
        return jsonify({"error": "题目不存在"}), 404
    update_question(question_id, {"enabled": 0 if q.get("enabled") else 1})
    return jsonify({"ok": True, "enabled": not q.get("enabled")})


@app.route('/api/questions/stats', methods=['GET'])
@login_required
def api_question_stats():
    return jsonify(get_question_bank_stats())


# ═══════════════════════════════════════════════════
# Routes: Learning Analytics
# ═══════════════════════════════════════════════════

@app.route('/api/learning/class', methods=['GET'])
@login_required
def api_learning_class():
    return jsonify(get_class_learning_stats())


@app.route('/api/learning/student/<int:student_id>', methods=['GET'])
@login_required
def api_learning_student(student_id):
    stats = get_student_learning_stats(student_id)
    profile = get_student_profile(student_id)
    if profile:
        stats["profile"] = profile
        stats["has_profile"] = True
    else:
        stats["has_profile"] = False
    plan = get_learning_plan(student_id)
    if plan:
        stats["learning_plan"] = plan
    return jsonify(stats)


@app.route('/api/learning/score', methods=['POST'])
@login_required
def api_learning_record_score():
    data = request.get_json() or {}
    student_id = data.get('student_id')
    score = data.get('score')
    score_type = data.get('score_type', 'manual')
    note = data.get('note', '')
    week_start = data.get('week_start')

    if not student_id or score is None:
        return jsonify({"error": "student_id and score required"}), 400
    try:
        score = float(score)
    except (ValueError, TypeError):
        return jsonify({"error": "score must be a number"}), 400

    record_score(student_id, score, score_type=score_type, note=note,
                 week_start=week_start)
    return jsonify({"ok": True}), 201


@app.route('/api/budget', methods=['GET'])
@login_required
def api_budget_get():
    return jsonify(get_budgets())


@app.route('/api/budget', methods=['POST'])
@admin_required
def api_budget_set():
    data = request.get_json() or {}
    try:
        if "monthly_total_budget" in data:
            val = float(data["monthly_total_budget"])
            if val < 0:
                raise ValueError
            set_setting("monthly_total_budget", str(val))
        if "monthly_student_budget" in data:
            val = float(data["monthly_student_budget"])
            if val < 0:
                raise ValueError
            set_setting("monthly_student_budget", str(val))
    except (ValueError, TypeError):
        return jsonify({"error": "预算必须是大于等于0的数字"}), 400
    return jsonify(get_budgets())


# ═══════════════════════════════════════════════════
# Routes: Subscriptions
# ═══════════════════════════════════════════════════

@app.route('/api/subscriptions/<int:student_id>', methods=['GET'])
@login_required
def api_subscription_get(student_id):
    summary = get_subscription_summary(student_id)
    return jsonify(summary)


@app.route('/api/subscriptions', methods=['POST'])
@login_required
def api_subscription_save():
    data = request.get_json() or {}
    student_id = data.get('student_id')
    if not student_id:
        return jsonify({"error": "student_id required"}), 400

    # Only update plan; status is auto-managed by date
    sub = get_subscription(student_id)
    today = date.today().isoformat()
    if sub:
        # Preserve existing dates, update plan, price and quota
        plan = data.get('plan', sub.get('plan', 'trial'))
        from db import PRICING
        price = PRICING.get(plan, {}).get('price', 0)
        monthly_quota = PRICING.get(plan, {}).get('monthly_quota', 0)
        reset_month = date.today().strftime("%Y-%m")
        conn = get_connection()
        conn.execute("""
            UPDATE subscriptions SET plan = ?, price = ?, monthly_quota = ?, reset_month = ? WHERE student_id = ?
        """, [plan, price, monthly_quota, reset_month, student_id])
        conn.commit()
        conn.close()
    else:
        # Create new subscription
        plan = data.get('plan', 'trial')
        from db import PRICING
        price = PRICING.get(plan, {}).get('price', 0)
        save_subscription({
            "student_id": student_id,
            "plan": plan,
            "status": "active",
            "start_date": today,
            "end_date": None,
            "price": price,
        })
    return jsonify({"ok": True})


@app.route('/api/payments', methods=['POST'])
@login_required
def api_payment_create():
    data = request.get_json() or {}
    student_id = data.get('student_id')
    amount = data.get('amount')
    weeks = data.get('weeks', 1)
    note = data.get('note', '')

    if not student_id or amount is None:
        return jsonify({"error": "student_id and amount required"}), 400
    try:
        amount = float(amount)
        weeks = int(weeks)
    except (ValueError, TypeError):
        return jsonify({"error": "amount and weeks must be numbers"}), 400
    if amount < 0 or weeks <= 0:
        return jsonify({"error": "amount must be >= 0 and weeks > 0"}), 400

    payment_id = record_payment(student_id, amount, weeks, note)
    return jsonify({"payment_id": payment_id, "ok": True}), 201


@app.route('/api/payments/<int:student_id>', methods=['GET'])
@login_required
def api_payments_list(student_id):
    return jsonify(get_payments(student_id))


# ═══════════════════════════════════════════════════
# Routes: File Upload
# ═══════════════════════════════════════════════════

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


@app.route('/api/upload', methods=['POST'])
@login_required
def api_upload():
    student_id = request.form.get('student_id', type=int)
    file_type = request.form.get('file_type', 'test_paper')
    uploader_role = request.form.get('uploader_role', 'parent')

    # Support both single 'file' and multiple 'files'
    single_file = request.files.get('file')
    multiple_files = request.files.getlist('files')
    files = multiple_files if multiple_files else ([single_file] if single_file else [])

    if not files:
        return jsonify({"error": "no file"}), 400
    if len(files) > 15:
        return jsonify({"error": "一次最多上传 15 张图片"}), 400

    file_ids = [_save_uploaded_file(f, student_id, file_type, uploader_role) for f in files]

    if len(file_ids) == 1:
        return jsonify({"file_id": file_ids[0], "file_ids": file_ids}), 201
    return jsonify({"file_ids": file_ids}), 201


@app.route('/api/files/<int:file_id>/download')
@login_required
def api_file_download(file_id):
    f = get_file(file_id)
    if not f:
        return ('', 404)
    filepath = os.path.join(UPLOAD_DIR, str(f['student_id']),
                           f['file_type'], f['filename'])
    if not os.path.exists(filepath):
        return ('', 404)
    return send_file(filepath, download_name=f['original_filename'])


# ═══════════════════════════════════════════════════
# Routes: Teacher / Institution Profile
# ═══════════════════════════════════════════════════

@app.route('/api/teacher-profile', methods=['GET'])
@feature_required('feature_teacher_enabled')
@login_required
def api_teacher_profile_get():
    profile = get_teacher_profile(session['user_id'])
    # Auto-fill institution_name from teacher's school if blank
    if not profile.get('institution_name'):
        conn = get_connection()
        user = conn.execute("SELECT school_id FROM admin_users WHERE id = ?", [session['user_id']]).fetchone()
        conn.close()
        if user and user['school_id']:
            school = get_school(user['school_id'])
            if school:
                profile['institution_name'] = school['name']
    if profile.get('avatar_filename'):
        profile['avatar_url'] = f"/uploads/teacher/{profile['avatar_filename']}"
    else:
        profile['avatar_url'] = ''
    return jsonify(profile)


@app.route('/api/teacher-profile', methods=['POST'])
@feature_required('feature_teacher_enabled')
@login_required
def api_teacher_profile_save():
    data = request.get_json() or {}
    save_teacher_profile(session['user_id'], data)
    return jsonify({"ok": True})


@app.route('/api/teacher-profile/avatar', methods=['POST'])
@feature_required('feature_teacher_enabled')
@login_required
def api_teacher_profile_avatar():
    file = request.files.get('file')
    if not file:
        return jsonify({"error": "no file"}), 400
    ext = os.path.splitext(file.filename)[1] or '.jpg'
    stored_name = f"avatar{ext}"
    teacher_dir = os.path.join(UPLOAD_DIR, 'teacher')
    os.makedirs(teacher_dir, exist_ok=True)
    filepath = os.path.join(teacher_dir, stored_name)
    file.save(filepath)
    profile = get_teacher_profile()
    profile['avatar_filename'] = stored_name
    save_teacher_profile(profile)
    return jsonify({"url": f"/uploads/teacher/{stored_name}", "filename": stored_name}), 201


@app.route('/uploads/teacher/<path:filename>')
@feature_required('feature_teacher_enabled')
def teacher_uploads(filename):
    return send_from_directory(os.path.join(UPLOAD_DIR, 'teacher'), filename)


# ═══════════════════════════════════════════════════
# Routes: Pipeline
# ═══════════════════════════════════════════════════

@app.route('/api/pipeline/run', methods=['POST'])
@login_required
def api_pipeline_run():
    data = request.get_json()
    student_id = data['student_id']
    task_type = data['task_type']  # 'onboarding' | 'weekly'
    file_id = data.get('file_id')
    file_ids = data.get('file_ids')
    stage = data.get('stage', 'full')
    answer_file_id = data.get('answer_file_id')
    answer_file_ids = data.get('answer_file_ids')

    # Cost guard: check budget before creating task
    budget_check = check_cost_budget(student_id)
    if not budget_check["allowed"]:
        # Create a persistent cost alert so admins see it in the dashboard
        student = get_student(student_id)
        student_name = student["name"] if student else f"学生{student_id}"
        for reason in budget_check.get("reasons", []):
            create_alert(
                alert_type="cost_student" if "学生" in reason else "cost_total",
                level="critical",
                message=f"{student_name} 的任务被预算熔断阻止：{reason}",
                related_id=str(student_id),
                details={"reason": reason, "budget_check": budget_check},
            )
        return jsonify({
            "error": "预算已超支，无法启动新任务",
            "reasons": budget_check["reasons"],
            "budget": budget_check,
        }), 429

    # Quota check: subscription must be active and have remaining analyses
    # Only OCR-heavy stages consume quota; analysis_only/report_only are free
    sub = get_subscription(student_id)
    if not sub or sub.get("status") != "active":
        return jsonify({"error": "订阅已过期，请续费后重试"}), 429
    QUOTA_FREE_STAGES = ("analysis_only", "report_only")
    consumes_quota = stage not in QUOTA_FREE_STAGES
    if consumes_quota:
        has_quota, remaining = check_quota(student_id)
        if not has_quota:
            plan_label = PRICING.get(sub.get("plan", "trial"), {}).get("label", "体验")
            return jsonify({
                "error": f"本月 {plan_label} 额度已用完（剩余 {remaining} 次），请续费或升级套餐",
                "remaining_quota": remaining,
            }), 429
        if not consume_quota(student_id):
            return jsonify({"error": "额度扣减失败，请刷新后重试"}), 429

    input_data = {}
    if file_ids:
        input_data["file_ids"] = file_ids
    elif file_id:
        input_data["file_id"] = file_id
    if stage:
        input_data["stage"] = stage
    if answer_file_ids:
        input_data["answer_file_ids"] = answer_file_ids
    elif answer_file_id:
        input_data["answer_file_id"] = answer_file_id

    task_id = create_task(
        student_id=student_id,
        task_type=task_type,
        input_data=input_data,
    )
    enqueue_task(task_id)
    return jsonify({"task_id": task_id}), 202


@app.route('/api/tasks/<int:task_id>')
@login_required
def api_task_status(task_id):
    task = get_task(task_id)
    if not task:
        return ('', 404)
    return jsonify({
        "id": task["id"],
        "status": task["status"],
        "task_type": task["task_type"],
        "progress": task["progress"],
        "current_step": task["current_step"],
        "needs_review": bool(task["needs_review"]),
        "output_data": task["output_data"],
        "error_message": task["error_message"],
        "created_at": task["created_at"],
        "completed_at": task["completed_at"],
    })


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


@app.route('/api/tasks/<int:task_id>/approve', methods=['POST'])
@login_required
def api_task_approve(task_id):
    from db import update_task
    update_task(task_id, {"needs_review": 0})
    return jsonify({"ok": True})


@app.route('/api/tasks/<int:task_id>/reject', methods=['POST'])
@login_required
def api_task_reject(task_id):
    """Reject a task and re-run with teacher notes."""
    data = request.get_json() or {}
    teacher_notes = data.get('notes', '')

    from db import update_task, get_task, create_task

    old_task = get_task(task_id)
    if not old_task:
        return ('', 404)

    # Mark old task as rejected
    update_task(task_id, {"needs_review": 0, "status": "rejected"})

    # Create new task with teacher notes
    old_input = old_task.get('input_data', {}) or {}
    if isinstance(old_input, str):
        import json; old_input = json.loads(old_input)
    old_input['teacher_notes'] = teacher_notes
    old_input['retry_from'] = task_id

    new_task_id = create_task(
        student_id=old_task['student_id'],
        task_type=old_task['task_type'],
        input_data=old_input,
    )
    enqueue_task(new_task_id)
    return jsonify({"task_id": new_task_id}), 202


@app.route('/api/tasks', methods=['GET'])
@login_required
def api_tasks_list():
    conn = get_connection()
    rows = conn.execute("""
        SELECT t.*, s.name as student_name FROM ai_tasks t
        JOIN students s ON s.id = t.student_id
        ORDER BY t.created_at DESC LIMIT 50
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/tasks/batch/approve', methods=['POST'])
@login_required
def api_tasks_batch_approve():
    """Batch approve review tasks."""
    data = request.get_json() or {}
    task_ids = data.get('task_ids', [])
    if not task_ids:
        return jsonify({"error": "task_ids required"}), 400

    from db import update_task
    approved = 0
    for tid in task_ids:
        try:
            update_task(tid, {"needs_review": 0})
            approved += 1
        except Exception:
            pass
    return jsonify({"approved": approved})


@app.route('/api/tasks/batch/reject', methods=['POST'])
@login_required
def api_tasks_batch_reject():
    """Batch reject review tasks and re-run with shared teacher notes."""
    data = request.get_json() or {}
    task_ids = data.get('task_ids', [])
    teacher_notes = data.get('notes', '')
    if not task_ids:
        return jsonify({"error": "task_ids required"}), 400

    from db import update_task, get_task, create_task
    rejected = 0
    new_task_ids = []
    for tid in task_ids:
        try:
            old_task = get_task(tid)
            if not old_task:
                continue
            update_task(tid, {"needs_review": 0, "status": "rejected"})
            old_input = old_task.get('input_data', {}) or {}
            if isinstance(old_input, str):
                import json; old_input = json.loads(old_input)
            old_input['teacher_notes'] = teacher_notes
            old_input['retry_from'] = tid
            new_task_id = create_task(
                student_id=old_task['student_id'],
                task_type=old_task['task_type'],
                input_data=old_input,
            )
            enqueue_task(new_task_id)
            new_task_ids.append(new_task_id)
            rejected += 1
        except Exception:
            pass
    return jsonify({"rejected": rejected, "new_task_ids": new_task_ids}), 202


# ═══════════════════════════════════════════════════
# Routes: AI Content Corrections
# ═══════════════════════════════════════════════════

@app.route('/api/tasks/<int:task_id>/correctables', methods=['GET'])
@login_required
def api_task_correctables(task_id):
    """Return correctable items for a task: mistakes for onboarding/stage A,
    practice records for stage B grading.
    """
    task = get_task(task_id)
    if not task:
        return jsonify({"error": "task not found"}), 404

    output_data = task.get('output_data', {}) or {}
    if isinstance(output_data, str):
        try:
            output_data = json.loads(output_data)
        except Exception:
            output_data = {}

    input_data = task.get('input_data', {}) or {}
    if isinstance(input_data, str):
        try:
            input_data = json.loads(input_data)
        except Exception:
            input_data = {}

    stage = output_data.get('stage') or input_data.get('stage', 'full')
    result = {
        "task_id": task_id,
        "task_type": task['task_type'],
        "stage": stage,
        "student_id": task['student_id'],
        "items": [],
    }

    conn = get_connection()
    if stage == "grading_done":
        # Stage B: load practice records created by this task.
        # We approximate by practice_records created around task completion for this student.
        # A more precise way would be to store session/practice ids in output_data.
        completed_at = task.get('completed_at')
        rows = conn.execute("""
            SELECT pr.id, pr.mistake_id, pr.user_answer, pr.is_correct, pr.feedback,
                   m.question, m.correct_answer as mistake_answer,
                   m.question_type, m.knowledge_points, m.difficulty
            FROM practice_records pr
            JOIN mistakes m ON m.id = pr.mistake_id
            WHERE m.student_id = ?
            ORDER BY pr.created_at DESC
            LIMIT 20
        """, [task['student_id']]).fetchall()
        for r in rows:
            d = dict(r)
            try:
                d["knowledge_points"] = json.loads(d.get("knowledge_points", "[]"))
            except Exception:
                d["knowledge_points"] = []
            result["items"].append({
                "content_type": "grading",
                "target_id": d["id"],
                "mistake_id": d["mistake_id"],
                "question": d["question"],
                "user_answer": d["user_answer"],
                "is_correct": bool(d["is_correct"]),
                "feedback": d["feedback"],
                "correct_answer": d["mistake_answer"],
                "question_type": d["question_type"],
                "knowledge_points": d["knowledge_points"],
                "difficulty": d["difficulty"],
            })
    else:
        # Onboarding / Stage A: load mistakes from output_data.mistake_ids
        mistake_ids = output_data.get('mistake_ids', [])
        if mistake_ids:
            placeholders = ",".join("?" for _ in mistake_ids)
            rows = conn.execute(f"""
                SELECT id, question, question_type, correct_answer, user_answer,
                       explanation, knowledge_points, difficulty
                FROM mistakes
                WHERE id IN ({placeholders})
            """, list(mistake_ids)).fetchall()
            for r in rows:
                d = dict(r)
                try:
                    d["knowledge_points"] = json.loads(d.get("knowledge_points", "[]"))
                except Exception:
                    d["knowledge_points"] = []
                result["items"].append({
                    "content_type": "mistake",
                    "target_id": d["id"],
                    "question": d["question"],
                    "question_type": d["question_type"],
                    "correct_answer": d["correct_answer"],
                    "user_answer": d["user_answer"],
                    "explanation": d["explanation"],
                    "knowledge_points": d["knowledge_points"],
                    "difficulty": d["difficulty"],
                })
    conn.close()
    return jsonify(result)


@app.route('/api/tasks/<int:task_id>/corrections', methods=['GET'])
@login_required
def api_task_corrections_list(task_id):
    """List all corrections for a task."""
    task = get_task(task_id)
    if not task:
        return jsonify({"error": "task not found"}), 404
    return jsonify(get_task_corrections(task_id))


@app.route('/api/tasks/<int:task_id>/corrections', methods=['POST'])
@login_required
def api_task_corrections_create(task_id):
    """Create one or more corrections for a task and apply them to target records."""
    task = get_task(task_id)
    if not task:
        return jsonify({"error": "task not found"}), 404

    data = request.get_json() or {}
    items = data.get('corrections', [])
    if not isinstance(items, list):
        items = [data] if data else []

    created_ids = []
    valid_items = []
    username = session.get('user_id', 'unknown')

    for item in items:
        content_type = item.get('content_type')
        target_field = item.get('target_field')
        corrected_value = item.get('corrected_value')
        if not content_type or not target_field or corrected_value is None:
            continue

        target_id = item.get('target_id')
        original_value = item.get('original_value')
        reason = item.get('reason', '')

        cid = create_correction(
            task_id=task_id,
            student_id=task['student_id'],
            content_type=content_type,
            target_field=target_field,
            corrected_value=corrected_value,
            target_id=target_id,
            original_value=original_value,
            reason=reason,
            reviewed_by=username,
            apply=True,
        )
        created_ids.append(cid)
        valid_items.append(item)

        log_audit(
            actor_type='teacher',
            actor_id=username,
            action='correct',
            target_type='ai_task',
            target_id=str(task_id),
            details={
                'correction_id': cid,
                'content_type': content_type,
                'target_id': target_id,
                'target_field': target_field,
                'reason': reason,
            },
        )

    # Auto-trigger a rerun so AI can learn from the corrections immediately.
    # Only rerun if corrections were actually created and retry limit not reached.
    rerun_task_id = None
    if valid_items:
        try:
            rerun_task_id = _enqueue_correction_rerun(task, valid_items)
        except Exception:
            pass

    response = {"created": len(created_ids), "correction_ids": created_ids}
    if rerun_task_id:
        response["rerun_task_id"] = rerun_task_id
    return jsonify(response), 201


@app.route('/api/corrections/<int:correction_id>/revert', methods=['POST'])
@login_required
def api_correction_revert(correction_id):
    """Revert an applied correction."""
    ok = revert_correction(correction_id)
    if not ok:
        return jsonify({"error": "correction not found or already reverted"}), 400
    username = session.get('user_id', 'unknown')
    log_audit(
        actor_type='teacher',
        actor_id=username,
        action='revert_correction',
        target_type='ai_correction',
        target_id=str(correction_id),
    )
    return jsonify({"ok": True})


@app.route('/api/corrections/stats', methods=['GET'])
@login_required
def api_corrections_stats():
    """Return correction statistics for dashboard."""
    days = request.args.get('days', 7, type=int)
    return jsonify(get_correction_stats(days=days))


# ═══════════════════════════════════════════════════
# Routes: AIGC Safety Checks
# ═══════════════════════════════════════════════════

@app.route('/api/safety-checks/pending', methods=['GET'])
@login_required
def api_safety_checks_pending():
    """List pending AIGC safety checks."""
    return jsonify(get_pending_safety_checks())


@app.route('/api/safety-checks/stats', methods=['GET'])
@login_required
def api_safety_checks_stats():
    """Return AIGC safety check statistics."""
    return jsonify(get_safety_check_stats())


@app.route('/api/safety-checks/<int:check_id>/review', methods=['POST'])
@login_required
def api_safety_check_review(check_id):
    """Review a safety check: mark clean or flagged with issue flags."""
    data = request.get_json() or {}
    safety_status = data.get('safety_status')
    issue_flags = data.get('issue_flags', [])
    if safety_status not in ('clean', 'flagged'):
        return jsonify({"error": "safety_status must be 'clean' or 'flagged'"}), 400
    if safety_status == 'flagged' and not issue_flags:
        return jsonify({"error": "issue_flags required when flagged"}), 400

    username = session.get('user_id', 'unknown')
    ok = review_safety_check(check_id, safety_status, issue_flags, reviewed_by=username)
    if not ok:
        return jsonify({"error": "check not found"}), 404

    # If flagged, optionally create a correction record linking to the original task
    auto_correct = data.get('auto_correct', False)
    if safety_status == 'flagged' and auto_correct:
        # Frontend should provide correction details; this is a placeholder path.
        pass

    log_audit(
        actor_type='teacher',
        actor_id=username,
        action='review_safety_check',
        target_type='aigc_safety_check',
        target_id=str(check_id),
        details={"safety_status": safety_status, "issue_flags": issue_flags},
    )
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════
# Routes: Observability
# ═══════════════════════════════════════════════════

@app.route('/api/tasks/failure-stats', methods=['GET'])
@login_required
def api_task_failure_stats():
    """Return task failure/rejection statistics."""
    days = request.args.get('days', 7, type=int)
    return jsonify(get_task_failure_stats(days=days))


@app.route('/api/tasks/recent-failures', methods=['GET'])
@login_required
def api_recent_failed_tasks():
    """Return recent failed/rejected tasks with error messages."""
    limit = request.args.get('limit', 20, type=int)
    return jsonify(get_recent_failed_tasks(limit=limit))


@app.route('/api/alerts', methods=['GET'])
@login_required
def api_active_alerts():
    """Return active (non-dismissed) alerts."""
    return jsonify(get_active_alerts())


@app.route('/api/alerts/<int:alert_id>/dismiss', methods=['POST'])
@login_required
def api_dismiss_alert(alert_id):
    """Dismiss an active alert."""
    ok = dismiss_alert(alert_id)
    if not ok:
        return jsonify({"error": "alert not found or already dismissed"}), 404
    log_audit(
        actor_type='teacher',
        actor_id=str(session.get('user_id')),
        action='dismiss_alert',
        target_type='alert',
        target_id=str(alert_id),
    )
    return jsonify({"ok": True})


@app.route('/api/cost/alerts', methods=['GET'])
@login_required
def api_cost_alerts():
    """Return cost alert status."""
    return jsonify(get_cost_alert_status())


@app.route('/api/admin/alert-settings', methods=['POST'])
@admin_required
def api_alert_settings():
    """Update cost alert threshold."""
    data = request.get_json() or {}
    threshold = data.get('threshold_pct')
    enabled = data.get('enabled')
    if threshold is not None:
        try:
            t = int(threshold)
            if t < 0 or t > 100:
                raise ValueError
            set_setting('cost_alert_threshold_pct', str(t))
        except ValueError:
            return jsonify({"error": "threshold_pct must be 0-100"}), 400
    if enabled is not None:
        set_setting('cost_alert_enabled', '1' if enabled else '0')
    return jsonify({"ok": True})


@app.route('/api/audit-logs', methods=['GET'])
@login_required
def api_audit_logs():
    """Return audit logs with optional filters."""
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)
    actor_type = request.args.get('actor_type') or None
    action = request.args.get('action') or None
    target_type = request.args.get('target_type') or None
    since = request.args.get('since') or None
    return jsonify(get_audit_logs_filtered(
        limit=limit, offset=offset,
        actor_type=actor_type, action=action,
        target_type=target_type, since=since,
    ))


@app.route('/api/audit-logs/actions', methods=['GET'])
@login_required
def api_audit_log_actions():
    """Return distinct audit log actions for filter dropdown."""
    return jsonify(get_audit_log_actions())


@app.route('/api/backups', methods=['GET'])
@admin_required
def api_backups_list():
    """Return backup history."""
    return jsonify(get_backups())


@app.route('/api/backups/run', methods=['POST'])
@admin_required
def api_backup_run():
    """Manually trigger a database backup."""
    import backup as backup_module
    path = backup_module.run_backup('manual')
    log_audit(
        actor_type='admin',
        actor_id=str(session.get('user_id')),
        action='run_backup',
        target_type='backup',
        target_id='',
        details={"path": path},
    )
    return jsonify({"ok": True, "path": path})


@app.route('/api/backups/<int:backup_id>/download', methods=['GET'])
@admin_required
def api_backup_download(backup_id):
    """Download a backup file."""
    import backup as backup_module
    path = backup_module.get_backup_path(backup_id)
    if not path or not os.path.exists(path):
        return jsonify({"error": "backup not found"}), 404
    return send_file(path, as_attachment=True,
                     download_name=os.path.basename(path))


# ═══════════════════════════════════════════════════
# Routes: Weekly Records (read-only from AI)
# ═══════════════════════════════════════════════════

@app.route('/api/weekly', methods=['GET'])
@login_required
def api_weekly_list():
    week = request.args.get('week', get_week_start())
    if session.get('user_role') == 'admin':
        students = get_all_students()
    else:
        students = get_students_by_teacher(session['user_id'])
    result = []
    for s in students:
        wr = get_or_create_weekly_record(s['id'], week)
        result.append({
            "student_id": s["id"],
            "name": s["name"],
            "plan": s.get("plan", "trial"),
            "plan_label": s.get("plan_label", "试用"),
            "paper_submitted": wr["paper_submitted"],
            "paper_analyzed": wr["paper_analyzed"],
            "exercises_sent": wr["exercises_sent"],
            "exercises_completed": wr["exercises_completed"],
            "exercises_graded": wr["exercises_graded"],
            "report_sent": wr["report_sent"],
            "flashcard_sent": wr["flashcard_sent"],
            "notes": wr["notes"] or "",
            "week_start": week,
        })
    return jsonify(result)


# ═══════════════════════════════════════════════════
# Routes: Compliance (parent consent + data deletion)
# ═══════════════════════════════════════════════════

@app.route('/api/compliance/students-without-consent', methods=['GET'])
@login_required
def api_students_without_consent():
    return jsonify(get_students_without_consent())


@app.route('/api/compliance/consents', methods=['POST'])
@login_required
def api_record_parent_consent():
    data = request.get_json() or {}
    student_id = data.get('student_id')
    consented_by = (data.get('consented_by') or '').strip()
    contact = (data.get('contact') or '').strip()
    notes = (data.get('notes') or '').strip()

    if not student_id or not consented_by:
        return jsonify({"error": "student_id and consented_by are required"}), 400

    student = get_student(student_id)
    if not student:
        return jsonify({"error": "student not found"}), 404

    consent_id = record_parent_consent(
        student_id=student_id,
        consented_by=consented_by,
        contact=contact,
        ip_address=request.remote_addr or '',
        notes=notes,
    )
    log_audit(
        actor_type="teacher",
        actor_id=session.get("user_id"),
        action="record_parent_consent",
        target_type="student",
        target_id=student_id,
        details={"consent_id": consent_id, "consented_by": consented_by},
        ip_address=request.remote_addr or '',
    )
    return jsonify({"id": consent_id, "success": True})


@app.route('/api/compliance/deletion-requests', methods=['GET'])
@login_required
def api_deletion_requests():
    return jsonify(get_pending_deletion_requests())


@app.route('/api/compliance/deletion-requests', methods=['POST'])
@login_required
def api_create_deletion_request():
    data = request.get_json() or {}
    student_id = data.get('student_id')
    reason = (data.get('reason') or '').strip()
    requested_by = (data.get('requested_by') or '').strip() or session.get("user_name", "teacher")

    if not student_id:
        return jsonify({"error": "student_id is required"}), 400

    student = get_student(student_id)
    if not student:
        return jsonify({"error": "student not found"}), 404

    req_id = request_data_deletion(
        student_id=student_id,
        requested_by=requested_by,
        reason=reason,
    )
    log_audit(
        actor_type="teacher",
        actor_id=session.get("user_id"),
        action="request_data_deletion",
        target_type="student",
        target_id=student_id,
        details={"request_id": req_id, "reason": reason},
        ip_address=request.remote_addr or '',
    )
    return jsonify({"id": req_id, "success": True})


@app.route('/api/compliance/deletion-requests/<int:req_id>/process', methods=['POST'])
@admin_required
def api_process_deletion_request(req_id):
    success = process_data_deletion(req_id)
    if not success:
        return jsonify({"error": "deletion request not found"}), 404

    log_audit(
        actor_type="admin",
        actor_id=session.get("user_id"),
        action="process_data_deletion",
        target_type="deletion_request",
        target_id=req_id,
        details={},
        ip_address=request.remote_addr or '',
    )
    return jsonify({"success": True})


# ═══════════════════════════════════════════════════
# Routes: Admin Users (admin only)
# ═══════════════════════════════════════════════════

@app.route('/api/admin/users', methods=['GET'])
@admin_required
def api_admin_users_list():
    return jsonify(list_admin_users())


@app.route('/api/admin/users', methods=['POST'])
@admin_required
def api_admin_users_create():
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    role = data.get('role', 'teacher')

    if not username or not password:
        return jsonify({"error": "用户名和密码必填"}), 400
    if role not in ('admin', 'teacher'):
        return jsonify({"error": "角色必须是 admin 或 teacher"}), 400
    if len(password) < 4:
        return jsonify({"error": "密码至少4位"}), 400

    existing = get_admin_user(username)
    if existing:
        return jsonify({"error": "用户名已存在"}), 409

    user_id = create_admin_user(username, generate_password_hash(password), role)
    return jsonify({"id": user_id, "username": username, "role": role}), 201


@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@admin_required
def api_admin_users_delete(user_id):
    # Don't allow deleting yourself
    if user_id == session.get('user_id'):
        return jsonify({"error": "不能删除当前登录的账号"}), 400
    deleted = delete_admin_user(user_id)
    if not deleted:
        return jsonify({"error": "账号不存在"}), 404
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════
# Routes: Student Public View (no login)
# ═══════════════════════════════════════════════════

STUDENT_PAGE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>学生学习中心</title>
<style>
:root {
  --bg: #f8f7f4; --bg-alt: #f1f0ec; --card: #fff;
  --text: #1a1a1a; --text-alt: #33312c; --sub: #5a5a56; --mute: #8a8884;
  --accent: #e07b4b; --accent-hover: #d06a3a; --accent-light: #fef3ed;
  --green: #0f7b4e; --green-light: #effaf3;
  --blue: #4b8dc7; --blue-light: #eef5fb;
  --red: #d93a46; --red-light: #fef4f4;
  --border: #e8e6e1; --shadow-sm: 0 1px 2px rgba(0,0,0,.03);
  --shadow: 0 1px 3px rgba(0,0,0,.06), 0 2px 8px rgba(0,0,0,.02);
  --shadow-lg: 0 4px 24px rgba(0,0,0,.08);
  --radius: 10px;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; background:var(--bg); color:var(--text-alt); line-height:1.7; padding:16px; max-width:700px; margin:0 auto; font-size:1rem; }
.header { text-align:center; padding:28px 0 18px; border-bottom:2px solid var(--accent); margin-bottom:18px; }
.header h1 { font-size:1.55rem; color:var(--accent); font-weight:800; letter-spacing:.01em; }
.header .sub { color:var(--sub); font-size:.95rem; margin-top:6px; }
.summary { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-bottom:18px; }
.sum-item { background:var(--card); border:none; border-radius:12px; padding:16px 12px; text-align:center; box-shadow:var(--shadow); }
.sum-item .num { font-size:1.65rem; font-weight:800; color:var(--accent); }
.sum-item .label { font-size:.8rem; color:var(--sub); margin-top:2px; }
.tabs { display:flex; gap:4px; margin-bottom:18px; background:var(--card); padding:6px; border-radius:12px; box-shadow:var(--shadow); overflow-x:auto; -webkit-overflow-scrolling:touch; }
.tab { flex:1; padding:12px 10px; border:none; background:none; border-radius:8px; font-size:.92rem; font-weight:600; color:var(--sub); cursor:pointer; white-space:nowrap; transition:all .15s; border-bottom:2px solid transparent; }
.tab:hover { background:var(--bg-alt); color:var(--text); }
.tab.active { background:var(--accent-light); color:var(--accent); border-bottom-color:var(--accent); }
.page { display:none; }
.page.active { display:block; }
.card { background:var(--card); border:none; border-radius:12px; padding:22px; margin-bottom:14px; box-shadow:var(--shadow); }
.card h3 { font-size:1.12rem; margin-bottom:12px; font-weight:700; color:var(--text); }
.card .meta { color:var(--sub); font-size:.88rem; }
.btn { display:inline-block; padding:10px 20px; border:none; border-radius:var(--radius); cursor:pointer; font-size:.95rem; font-weight:600; text-decoration:none; transition:all .15s; min-height:44px; }
.btn:hover { transform:translateY(-1px); box-shadow:var(--shadow); }
.btn-primary { background:var(--accent); color:#fff; }
.btn-primary:hover { background:var(--accent-hover); }
.btn-green { background:var(--green); color:#fff; }
.btn-outline { background:var(--card); border:1px solid var(--border); color:var(--text); }
.btn-outline:hover { background:var(--bg-alt); }
.badge { display:inline-block; padding:4px 12px; border-radius:100px; font-size:.8rem; font-weight:600; }
.badge-green { background:var(--green-light); color:var(--green); }
.badge-red { background:var(--red-light); color:var(--red); }
.badge-blue { background:var(--blue-light); color:var(--blue); }
.empty { text-align:center; color:var(--sub); padding:44px 0; font-size:.95rem; }
.mistake-item { border-bottom:1px solid var(--border); padding:14px 0; }
.mistake-item:last-child { border-bottom:none; }
.mistake-q { font-weight:600; margin-bottom:8px; color:var(--text); font-size:1rem; line-height:1.6; }
.mistake-ans { font-size:.92rem; color:var(--sub); margin-bottom:6px; line-height:1.6; }
.calendar { display:grid; grid-template-columns:repeat(7,1fr); gap:6px; }
.cal-day { aspect-ratio:1; display:flex; align-items:center; justify-content:center; border-radius:8px; font-size:.85rem; background:var(--card); border:none; box-shadow:var(--shadow-sm); color:var(--sub); }
.cal-day.checked { background:var(--green-light); color:var(--green); font-weight:700; }
.cal-day.today { box-shadow:0 0 0 2px var(--accent); }
.week-row { display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid var(--border); font-size:.92rem; }
.week-row:last-child { border-bottom:none; }
.footer { text-align:center; color:var(--mute); font-size:.85rem; margin-top:36px; padding-top:18px; border-top:1px solid var(--border); }
.progress-bar { width:100%; height:10px; background:var(--border); border-radius:100px; overflow:hidden; margin:10px 0; }
.progress-bar .fill { height:100%; background:var(--accent); border-radius:100px; }
.kp-item { display:flex; justify-content:space-between; align-items:center; padding:10px 0; border-bottom:1px solid var(--border); font-size:.95rem; }
.kp-item:last-child { border-bottom:none; }
.toast { position:fixed; top:20px; left:50%; transform:translateX(-50%); padding:12px 24px; border-radius:var(--radius); color:#fff; font-size:.95rem; z-index:200; box-shadow:var(--shadow-lg); }
.toast-success { background:var(--green); }
/* Achievement Wall */
.ach-card { border-radius:10px; padding:12px 10px; text-align:center; transition:transform .2s; }
.ach-card:hover { transform:translateY(-2px); }
.ach-earned { background:linear-gradient(135deg,#fff9e6,#fef3c7); border:1.5px solid #f59e0b; }
.ach-locked { background:#f5f2ec; border:1.5px solid var(--border); opacity:.7; }
.ach-icon { font-size:1.8em; margin-bottom:4px; }
.ach-title { font-weight:700; font-size:.85em; margin-bottom:3px; color:var(--text); }
.ach-desc { font-size:.7em; color:var(--sub); line-height:1.3; margin-bottom:6px; }
.ach-date { font-size:.7em; color:var(--accent); margin-top:4px; }
.ach-progress { width:100%; height:5px; background:var(--border); border-radius:3px; overflow:hidden; margin-top:6px; }
.ach-progress-bar { height:100%; background:linear-gradient(90deg,var(--accent),var(--green)); border-radius:3px; transition:width .5s; }
.ach-progress-text { font-size:.65em; color:var(--sub); margin-top:2px; }
/* Learning Path Timeline */
.timeline { position:relative; padding-left:28px; }
.timeline::before { content:''; position:absolute; left:8px; top:0; bottom:0; width:3px; background:linear-gradient(to bottom, var(--accent), var(--green), var(--border)); border-radius:2px; }
.tl-item { position:relative; margin-bottom:20px; }
.tl-item:last-child { margin-bottom:0; }
.tl-dot { position:absolute; left:-24px; top:4px; width:16px; height:16px; border-radius:50%; background:var(--accent); border:3px solid #fff; box-shadow:0 1px 3px rgba(0,0,0,.2); z-index:1; display:flex; align-items:center; justify-content:center; font-size:.55em; }
.tl-date { font-size:.75em; color:var(--sub); margin-bottom:2px; }
.tl-title { font-weight:700; font-size:.9em; color:var(--text); }
.tl-desc { font-size:.8em; color:var(--sub); line-height:1.4; }
.tl-item.future .tl-dot { background:var(--border); border-color:#f5f2ec; }
.tl-item.future .tl-title { color:var(--sub); }
/* Metacognitive Review Form */
.review-input { width:100%; border:1px solid var(--border); border-radius:6px; padding:8px 10px; font-size:.85em; font-family:inherit; resize:vertical; box-sizing:border-box; }
.review-input:focus { outline:none; border-color:var(--accent); }
.mood-btn { width:40px; height:40px; border:1.5px solid var(--border); border-radius:50%; background:var(--card); font-size:1.1em; cursor:pointer; transition:all .2s; display:flex; align-items:center; justify-content:center; }
.mood-btn:hover { border-color:var(--accent); background:var(--accent-light); }
.mood-active { border-color:var(--accent); background:var(--accent); color:#fff; font-weight:700; }
</style>
</head>
<body>
<div class="header">
  <h1 id="stu-name">--</h1>
  <div class="sub" id="stu-info">--</div>
</div>

<div class="card" id="teacher-card" style="display:none;margin-bottom:16px;">
  <div style="display:flex;align-items:center;gap:14px;">
    <img id="teacher-avatar" src="" alt="" style="width:64px;height:64px;border-radius:50%;object-fit:cover;background:var(--border);display:none;">
    <div>
      <div style="font-weight:700;" id="teacher-name">--</div>
      <div style="font-size:.85em;color:var(--sub);" id="teacher-meta">--</div>
      <div style="font-size:.85em;color:var(--sub);margin-top:4px;" id="teacher-philosophy"></div>
      <div style="font-size:.85em;color:var(--accent);margin-top:4px;" id="teacher-contact"></div>
    </div>
  </div>
</div>

<div class="summary" id="summary">
  <div class="sum-item"><div class="num" id="sum-score">--</div><div class="label">当前分数</div></div>
  <div class="sum-item"><div class="num" id="sum-mistakes">--</div><div class="label">待攻克错题</div></div>
  <div class="sum-item"><div class="num" id="sum-due" style="color:var(--red);">--</div><div class="label">待复习</div></div>
  <div class="sum-item"><div class="num" id="sum-checkins">--</div><div class="label">本月打卡</div></div>
  <div class="sum-item"><div class="num" id="sum-achievements">--</div><div class="label">成就</div></div>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:16px;">
  <button class="btn btn-primary" onclick="openInviteModal()">🎁 邀请有礼</button>
  <button class="btn btn-green" onclick="generatePoster()">📸 生成海报</button>
</div>

<!-- Parent Upload Card -->
<div class="card" id="upload-card" style="margin-bottom:18px;border:2px dashed var(--border);text-align:center;cursor:pointer;transition:all .2s;" onclick="document.getElementById('parentFileInput').click()">
  <div style="font-size:3em;margin-bottom:10px;">📷</div>
  <div style="font-weight:800;font-size:1.15rem;margin-bottom:6px;">拍照上传试卷</div>
  <div style="font-size:.92rem;color:var(--sub);">拍一张孩子的英语试卷，AI自动分析错题</div>
  <div id="upload-progress" style="display:none;margin-top:14px;">
    <div class="progress-bar"><div class="fill" id="upload-fill" style="width:0%"></div></div>
    <div style="font-size:.9rem;color:var(--sub);margin-top:6px;" id="upload-status">上传中...</div>
  </div>
  <div id="upload-result" style="display:none;margin-top:14px;font-size:.95rem;color:var(--green);font-weight:700;line-height:1.6;"></div>
  <input type="file" id="parentFileInput" accept="image/*" capture="environment" multiple style="display:none;" onchange="handleParentUpload(this)">
</div>

<!-- Invite Modal -->
<div class="modal-overlay" id="invite-modal">
  <div class="modal" style="max-width:360px;">
    <h3>🎁 邀请好友一起学</h3>
    <p class="meta" style="margin-bottom:12px;">好友通过你的邀请码报名，双方各得 <strong id="reward-weeks">1</strong> 周免费学习时长</p>
    <div class="form-group">
      <label>你的邀请码</label>
      <input id="invite-code" readonly style="background:#f5f2ec;font-size:1.1em;text-align:center;font-weight:600;">
    </div>
    <div class="form-group">
      <label>已邀请成功</label>
      <input id="invite-count" readonly style="background:#f5f2ec;text-align:center;">
    </div>
    <button class="btn btn-primary" style="width:100%;" onclick="copyInviteCode()">📋 复制邀请码</button>
    <div class="btn-group" style="justify-content:flex-end;margin-top:12px;">
      <button class="btn btn-outline" onclick="closeInviteModal()">关闭</button>
    </div>
  </div>
</div>

<!-- Poster Modal -->
<div class="modal-overlay" id="poster-modal">
  <div class="modal" style="max-width:420px;">
    <h3>📸 学习成果海报</h3>
    <p class="meta" style="margin-bottom:12px;">已生成，可截图分享到朋友圈</p>
    <div id="poster-link" style="margin-bottom:16px;"></div>
    <div class="btn-group" style="justify-content:flex-end;">
      <button class="btn btn-outline" onclick="closePosterModal()">关闭</button>
    </div>
  </div>
</div>

<div class="tabs">
  <button class="tab active" onclick="switchTab('practice', event)">练习</button>
  <button class="tab" onclick="switchTab('reports', event)">报告</button>
  <button class="tab" onclick="switchTab('timeline', event)">时间轴</button>
  <button class="tab" onclick="switchTab('mistakes', event)">成长记录</button>
  <button class="tab" onclick="switchTab('achievements', event)">成就墙</button>
  <button class="tab" onclick="switchTab('review', event)">复盘</button>
  <button class="tab" onclick="switchTab('checkin', event)">坚持日记</button>
  <button class="tab" onclick="switchTab('progress', event)">进度</button>
</div>

<div id="page-practice" class="page active"></div>
<div id="page-reports" class="page"></div>
<div id="page-timeline" class="page"></div>
<div id="page-mistakes" class="page"></div>
<div id="page-achievements" class="page"></div>
<div id="page-review" class="page"></div>
<div id="page-checkin" class="page"></div>
<div id="page-progress" class="page"></div>

<div style="text-align:center;margin:24px 0;">
  <button class="btn btn-outline" onclick="requestDataDeletion()" style="font-size:.85em;">🗑️ 申请删除孩子学习数据</button>
  <p style="font-size:.75em;color:var(--sub);margin-top:8px;">依据个人信息保护法，家长可申请删除孩子数据，老师会尽快处理。</p>
</div>

<div class="footer">
  <p>拾阶而上 · AI 个性化学习</p>
</div>

<script>
const CODE = '{{code}}';
let STUDENT_ID = null;

function toast(msg) {
  const t = document.createElement('div'); t.className='toast toast-success'; t.textContent=msg;
  document.body.appendChild(t); setTimeout(()=>t.remove(), 2000);
}

async function requestDataDeletion() {
  const reason = prompt('申请删除孩子学习数据\n请输入删除原因（可选）：') || '';
  if (!confirm('确定要提交删除申请吗？老师会尽快处理。')) return;
  const r = await fetch('/api/public/' + CODE + '/request-deletion', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({reason, requested_by: '家长'}),
  });
  if (r.ok) {
    toast('删除申请已提交');
  } else {
    toast('提交失败，请稍后重试');
  }
}

function switchTab(name, evt) {
  document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  // Support both click events and programmatic calls
  if (evt && evt.target) {
    evt.target.classList.add('active');
  } else {
    // Programmatic: find tab button by onclick pattern
    const tabBtn = document.querySelector(`.tab[onclick*="'${name}'"]`);
    if (tabBtn) tabBtn.classList.add('active');
    // Fallback: find by text content
    if (!tabBtn) {
      const allTabs = document.querySelectorAll('.tab');
      const labelMap = {practice:'练习',reports:'报告',timeline:'时间轴',mistakes:'成长记录',achievements:'成就墙',review:'复盘',checkin:'坚持日记',progress:'进度'};
      const label = labelMap[name] || name;
      for (const t of allTabs) { if (t.textContent.trim() === label) { t.classList.add('active'); break; } }
    }
  }
  document.getElementById('page-'+name).classList.add('active');
}

async function loadData() {
  const r = await fetch('/api/public/' + CODE);
  if (!r.ok) { document.body.innerHTML = '<h2 style="text-align:center;margin-top:80px;">链接无效或已过期</h2>'; return; }
  const d = await r.json();
  const s = d.student;

  STUDENT_ID = s.id;
  document.getElementById('stu-name').textContent = s.name + ' 的学习中心';
  document.getElementById('stu-info').textContent = `${s.grade} · ${s.school_type} · 英语 ${s.english_score||'?'}分${s.target_score?' → 目标 '+s.target_score+'分':''}`;

  // Render teacher / institution profile
  if (d.teacher) {
    const t = d.teacher;
    const card = document.getElementById('teacher-card');
    card.style.display = 'block';
    const name = t.teacher_name || t.institution_name || '拾阶而上';
    document.getElementById('teacher-name').textContent = name;
    const metaParts = [];
    if (t.teaching_years) metaParts.push(t.teaching_years);
    if (t.specialty) metaParts.push(t.specialty);
    document.getElementById('teacher-meta').textContent = metaParts.join(' · ') || 'AI + 老师双师辅导';
    document.getElementById('teacher-philosophy').textContent = t.philosophy || '';
    document.getElementById('teacher-contact').textContent = t.contact_info || '';
    const avatar = document.getElementById('teacher-avatar');
    if (t.avatar_url) {
      avatar.src = t.avatar_url;
      avatar.style.display = 'block';
    }
  }
  document.getElementById('sum-score').textContent = s.english_score || '-';
  document.getElementById('sum-mistakes').textContent = d.mistakes_count;
  document.getElementById('sum-due').textContent = d.due_review_count || 0;
  document.getElementById('sum-checkins').textContent = d.check_ins.length;

  // Load achievement count async
  fetch('/api/public/' + CODE + '/achievements').then(r=>r.json()).then(data=>{
    document.getElementById('sum-achievements').textContent = (data.earned_count || 0);
  }).catch(()=>{});

  renderPractice();
  renderReports(d);
  renderTimeline();
  renderMistakes(d);
  renderAchievements();
  renderReview();
  renderCheckin(d);
  renderProgress(d);
}

async function openInviteModal() {
  const r = await fetch('/api/referrals/my/' + CODE);
  if (!r.ok) { toast('加载失败'); return; }
  const info = await r.json();
  document.getElementById('invite-code').value = info.invite_code;
  document.getElementById('invite-count').value = `${info.converted_count} 人（累计 ${info.total_reward_weeks} 周奖励）`;
  document.getElementById('reward-weeks').textContent = info.referrals.length > 0 ? (info.referrals[0].reward_weeks || 1) : 1;
  document.getElementById('invite-modal').classList.add('show');
}
function closeInviteModal() { document.getElementById('invite-modal').classList.remove('show'); }
async function copyInviteCode() {
  const code = document.getElementById('invite-code').value;
  try {
    await navigator.clipboard.writeText(code);
    toast('邀请码已复制');
  } catch(e) {
    // Fallback
    const input = document.getElementById('invite-code');
    input.select();
    document.execCommand('copy');
    toast('邀请码已复制');
  }
}

async function generatePoster() {
  const r = await fetch('/api/poster/' + CODE);
  if (!r.ok) { toast('海报生成失败'); return; }
  const d = await r.json();
  document.getElementById('poster-link').innerHTML = `
    <a href="/api/files/${d.file_id}/download" target="_blank" class="btn btn-primary" style="width:100%;">📸 查看/下载海报</a>
  `;
  document.getElementById('poster-modal').classList.add('show');
}
function closePosterModal() { document.getElementById('poster-modal').classList.remove('show'); }

// ═══ Interactive Practice (P0) ═══
let practiceQuestions = [];
let practiceIndex = 0;
let practiceCorrect = 0;

async function renderPractice() {
  const div = document.getElementById('page-practice');
  div.innerHTML = '<div class="card"><div class="empty">加载练习题中...</div></div>';
  try {
    const r = await fetch('/api/public/' + CODE + '/practice');
    const data = await r.json();
    practiceQuestions = data.questions || [];
    practiceIndex = 0;
    practiceCorrect = 0;
    if (practiceQuestions.length === 0) {
      div.innerHTML = `<div class="card"><div class="empty">
        <div style="font-size:2em;margin-bottom:8px;">🎉</div>
        <p>暂无待练习题</p>
        <p class="meta" style="margin-top:4px;">上传试卷后，AI会自动生成针对你薄弱点的专属练习</p>
      </div></div>`;
      return;
    }
    renderPracticeQuestion();
    // Add PDF download button below the question card
    const pdfBtn = document.createElement('div');
    pdfBtn.style.cssText = 'text-align:center;margin-top:12px;';
    pdfBtn.innerHTML = `<a href="/api/public/${CODE}/exercise-pdf" class="btn btn-outline" style="font-size:.85em;text-decoration:none;">🖨️ 下载打印版 PDF</a>`;
    div.appendChild(pdfBtn);
  } catch(e) {
    div.innerHTML = '<div class="card"><div class="empty">加载失败，请刷新重试</div></div>';
  }
}

function renderPracticeQuestion() {
  const div = document.getElementById('page-practice');
  if (practiceIndex >= practiceQuestions.length) {
    div.innerHTML = `<div class="card" style="text-align:center;padding:32px;">
      <div style="font-size:2.5em;margin-bottom:12px;">${practiceCorrect >= practiceQuestions.length/2 ? '🌟' : '💪'}</div>
      <h3>本轮练习完成！</h3>
      <p style="margin:12px 0;font-size:1.1em;font-weight:700;color:var(--accent);">${practiceCorrect} / ${practiceQuestions.length} 正确</p>
      <p class="meta">${practiceCorrect >= practiceQuestions.length/2 ? '太棒了，继续保持！' : '没关系，错题已加入复习计划，下次会更好'}</p>
      <button class="btn btn-primary" style="margin-top:16px;" onclick="renderPractice()">再来一轮</button>
    </div>`;
    return;
  }
  const q = practiceQuestions[practiceIndex];
  const kpTag = (q.knowledge_points||[]).map(k=>`<span class="badge badge-blue" style="margin-right:4px;">${k}</span>`).join('');
  const optionsHtml = q.options.length > 0
    ? q.options.map(o=>`
      <label class="practice-opt" data-key="${o.key}" onclick="selectOption(this,'${o.key}')" style="display:block;padding:14px 18px;margin:8px 0;border:1.5px solid var(--border);border-radius:10px;cursor:pointer;transition:all .15s;font-size:1rem;line-height:1.6;">
        <strong>${o.key}.</strong> ${o.text}
      </label>`).join('')
    : `<input type="text" id="practice-text-answer" placeholder="输入你的答案" style="width:100%;padding:12px 16px;border:1.5px solid var(--border);border-radius:10px;font-size:1rem;margin:10px 0;">`;

  div.innerHTML = `
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
        <span class="badge badge-green">第 ${practiceIndex+1}/${practiceQuestions.length} 题</span>
        <span style="font-size:.85em;color:var(--sub);">${q.question_type}</span>
      </div>
      <div style="margin-bottom:10px;">${kpTag}</div>
      <div style="font-weight:600;margin-bottom:16px;line-height:1.8;font-size:1.02rem;white-space:pre-wrap;">${q.question_text.replace(/[A-D]\.\s*.+?(?=\s*[A-D]\.|$)/g,'').trim()}</div>
      <div id="practice-options">${optionsHtml}</div>
      <button class="btn btn-primary" style="width:100%;margin-top:16px;" id="practice-submit-btn" onclick="submitPracticeAnswer()" disabled>提交答案</button>
      <div id="practice-feedback" style="display:none;margin-top:16px;"></div>
    </div>`;
}

let selectedAnswer = '';
function selectOption(el, key) {
  if (document.getElementById('practice-feedback').style.display !== 'none') return;
  document.querySelectorAll('.practice-opt').forEach(o=>{o.style.borderColor='var(--border)';o.style.background='';});
  el.style.borderColor = 'var(--accent)';
  el.style.background = 'var(--accent-light)';
  selectedAnswer = key;
  document.getElementById('practice-submit-btn').disabled = false;
}

async function submitPracticeAnswer() {
  const q = practiceQuestions[practiceIndex];
  const textInput = document.getElementById('practice-text-answer');
  const answer = selectedAnswer || (textInput ? textInput.value.trim() : '');
  if (!answer) return;

  document.getElementById('practice-submit-btn').disabled = true;
  document.getElementById('practice-submit-btn').textContent = '批改中...';

  try {
    const r = await fetch('/api/public/' + CODE + '/practice/submit', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question_id: q.id, answer: answer}),
    });
    const fb = await r.json();
    const fbDiv = document.getElementById('practice-feedback');
    fbDiv.style.display = 'block';

    if (fb.is_correct) {
      practiceCorrect++;
      fbDiv.innerHTML = `<div style="padding:16px;background:var(--green-light);border-radius:10px;border-left:4px solid var(--green);">
        <div style="font-weight:700;color:var(--green);margin-bottom:6px;font-size:1.05rem;">✅ 正确！</div>
        <div style="font-size:.95rem;color:var(--sub);line-height:1.7;">${fb.explanation||''}</div>
      </div>`;
      // Highlight correct option
      document.querySelectorAll('.practice-opt').forEach(o=>{
        if(o.dataset.key===fb.correct_answer){o.style.borderColor='var(--green)';o.style.background='var(--green-light)';}
      });
    } else {
      fbDiv.innerHTML = `<div style="padding:16px;background:var(--red-light);border-radius:10px;border-left:4px solid var(--red);">
        <div style="font-weight:700;color:var(--red);margin-bottom:6px;font-size:1.05rem;">❌ 不对哦</div>
        <div style="font-size:.95rem;margin-bottom:6px;"><strong>正确答案：${fb.correct_answer}</strong></div>
        <div style="font-size:.95rem;color:var(--sub);line-height:1.7;">${fb.explanation||''}</div>
      </div>`;
      document.querySelectorAll('.practice-opt').forEach(o=>{
        if(o.dataset.key===answer){o.style.borderColor='var(--red)';o.style.background='var(--red-light)';}
        if(o.dataset.key===fb.correct_answer){o.style.borderColor='var(--green)';o.style.background='var(--green-light)';}
      });
    }

    document.getElementById('practice-submit-btn').textContent = '下一题 →';
    document.getElementById('practice-submit-btn').disabled = false;
    document.getElementById('practice-submit-btn').onclick = ()=>{ practiceIndex++; selectedAnswer=''; renderPracticeQuestion(); };
  } catch(e) {
    toast('提交失败，请重试');
    document.getElementById('practice-submit-btn').disabled = false;
    document.getElementById('practice-submit-btn').textContent = '提交答案';
  }
}

// ═══ Parent Upload (P0) ═══
async function handleParentUpload(input) {
  const files = input.files;
  if (!files || files.length === 0) return;

  const progressDiv = document.getElementById('upload-progress');
  const resultDiv = document.getElementById('upload-result');
  const fillBar = document.getElementById('upload-fill');
  const statusText = document.getElementById('upload-status');
  progressDiv.style.display = 'block';
  resultDiv.style.display = 'none';
  fillBar.style.width = '30%';
  statusText.textContent = '上传中...';

  const formData = new FormData();
  for (let i = 0; i < files.length; i++) formData.append('file', files[i]);

  try {
    const r = await fetch('/api/public/' + CODE + '/upload', {method:'POST', body:formData});
    const data = await r.json();
    if (!r.ok) {
      statusText.textContent = data.error || '上传失败';
      fillBar.style.width = '0%';
      fillBar.style.background = 'var(--red)';
      return;
    }
    fillBar.style.width = '60%';
    statusText.textContent = 'AI正在分析错题...';
    pollTaskProgress(data.task_id);
  } catch(e) {
    statusText.textContent = '网络错误，请重试';
    fillBar.style.width = '0%';
  }
  input.value = '';
}

async function pollTaskProgress(taskId) {
  const fillBar = document.getElementById('upload-fill');
  const statusText = document.getElementById('upload-status');
  const resultDiv = document.getElementById('upload-result');
  let attempts = 0;
  const poll = async () => {
    attempts++;
    try {
      const r = await fetch('/api/public/' + CODE + '/task/' + taskId);
      const t = await r.json();
      if (t.status === 'done') {
        fillBar.style.width = '100%';
        statusText.textContent = '分析完成！';
        resultDiv.style.display = 'block';
        const out = t.output_data || {};
        const qCount = out.questions_count || 0;
        resultDiv.textContent = qCount > 0
          ? `✅ 已识别 ${out.mistakes_count||0} 道错题，生成 ${qCount} 道专属练习题，去「练习」tab 开始吧！`
          : `✅ 已识别 ${out.mistakes_count||0} 道错题，练习题生成中，稍后刷新「练习」tab`;
        renderPractice();
        return;
      } else if (t.status === 'failed') {
        statusText.textContent = '分析失败：' + (t.error_message||'未知错误').slice(0,60);
        fillBar.style.background = 'var(--red)';
        return;
      } else {
        fillBar.style.width = Math.min(60 + (t.progress||0)*0.35, 95) + '%';
        statusText.textContent = t.current_step || 'AI正在分析...';
        if (attempts < 60) setTimeout(poll, 3000);
      }
    } catch(e) {
      if (attempts < 60) setTimeout(poll, 5000);
    }
  };
  setTimeout(poll, 2000);
}

function renderReports(d) {
  const div = document.getElementById('page-reports');
  // Reports are loaded separately for backwards compatibility, or we can list approved tasks
  div.innerHTML = `
    <div class="card">
      <h3>📋 诊断报告</h3>
      <p class="meta">老师审核通过的报告会显示在这里</p>
      <div id="reports-list"></div>
    </div>
  `;
  fetch('/api/public/' + CODE + '/reports').then(r=>r.json()).then(reports=>{
    const list = document.getElementById('reports-list');
    if (!reports || reports.length === 0) {
      list.innerHTML = '<div class="empty"><p>📭 暂无已审核报告</p><p class="meta">老师正在处理中</p></div>';
      return;
    }
    list.innerHTML = reports.map(r=>`
      <div style="margin-top:12px;padding:12px;background:var(--bg);border-radius:6px;">
        <div class="meta">${r.created_at.slice(0,10)} · ${r.mistakes_count}道错题 · ${r.weak_points_count}个薄弱点</div>
        <a href="/api/files/${r.report_file_id}/download" target="_blank" class="btn btn-primary" style="margin-top:8px;">📄 查看报告</a>
      </div>
    `).join('');
  }).catch(()=>{});
}

function renderMistakes(d) {
  const div = document.getElementById('page-mistakes');
  const total = (d.mistakes_count || 0) + (d.mastered_count || 0);
  const mastered = d.mastered_count || 0;
  const remaining = d.mistakes_count || 0;

  if (total === 0) {
    div.innerHTML = '<div class="card"><div class="empty">🎉 暂无错题记录，上传试卷后自动生成</div></div>';
    return;
  }

  // Group mistakes by knowledge point
  const groups = {};
  (d.mistakes || []).forEach(m => {
    const kps = (m.knowledge_points || []);
    const kp = kps.length > 0 ? kps[0] : '其他';
    if (!groups[kp]) groups[kp] = [];
    groups[kp].push(m);
  });

  // Status helper
  const stageLabels = ['1小时', '1天', '2天', '4天', '7天', '15天', '30天', '60天'];
  function mistakeStatus(m) {
    const cc = m.consecutive_correct || 0;
    const stage = m.review_stage || 0;
    if (cc >= 2) return {icon: '🟢', label: '已掌握', color: 'var(--green)', bg: 'var(--green-light)'};
    if (stage >= 3) return {icon: '🟡', label: '在进步', color: 'var(--accent)', bg: 'var(--accent-light)'};
    return {icon: '🔴', label: '未攻克', color: 'var(--red)', bg: 'var(--red-light)'};
  }

  // Build grouped HTML
  let groupsHtml = '';
  for (const [kp, mistakes] of Object.entries(groups)) {
    const items = mistakes.map(m => {
      const st = mistakeStatus(m);
      const dueIds = new Set((d.due_reviews || []).map(r => r.id));
      const isDue = dueIds.has(m.id);
      return `
      <div class="mistake-item" style="border-left:3px solid ${st.color};padding-left:12px;margin:10px 0;">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
          <span>${st.icon}</span>
          <span class="badge" style="background:${st.bg};color:${st.color};">${st.label}</span>
          ${isDue ? '<span class="badge" style="background:#ffe0e0;color:var(--red);">🔔 待复习</span>' : ''}
        </div>
        <div class="mistake-q">${(m.question || '（题目未记录）').slice(0, 120)}</div>
        <div class="mistake-ans"><strong>答案：</strong>${m.correct_answer || '-'}</div>
        <button class="btn btn-green" style="margin-top:8px;font-size:.85rem;padding:6px 14px;min-height:38px;" onclick="masterMistake(${m.id})">✅ 已掌握</button>
        <button class="btn btn-outline" style="margin-top:8px;margin-left:6px;font-size:.85rem;padding:6px 14px;min-height:38px;" onclick="genSimilar(${m.id}, this)">🔍 类似题</button>
        <div class="similar-questions" id="similar-${m.id}" style="margin-top:8px;display:none;"></div>
      </div>`;
    }).join('');
    groupsHtml += `
      <div class="card" style="margin-bottom:12px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
          <h3 style="font-size:1.05rem;margin:0;">${kp}</h3>
          <span class="badge badge-blue">${mistakes.length} 道</span>
        </div>
        ${items}
      </div>`;
  }

  // Progress bar (thinning visual)
  const pct = total > 0 ? Math.round(mastered / total * 100) : 0;

  div.innerHTML = `
    <div class="card" style="text-align:center;margin-bottom:16px;padding:24px;">
      <div style="font-size:1.2rem;font-weight:800;margin-bottom:10px;line-height:1.6;">
        你已攻克 <span style="color:var(--green);">${mastered}</span> 道错题，还剩 <span style="color:var(--accent);">${remaining}</span> 道在路上
      </div>
      <div class="progress-bar" style="height:14px;margin:12px 0;">
        <div class="fill" style="width:${pct}%;background:linear-gradient(90deg,var(--green),var(--accent));border-radius:100px;"></div>
      </div>
      <div style="font-size:.9rem;color:var(--sub);">错题本完成度 ${pct}% · 越薄越厉害</div>
    </div>
    ${groupsHtml}
    <div style="margin-top:14px;text-align:center;">
      <button class="btn btn-primary" onclick="batchGenSimilar()">⚡ 一键生成全部类似题</button>
    </div>
  `;
}

async function genSimilar(mistakeId, btn) {
  const container = document.getElementById('similar-' + mistakeId);
  // Check if already loaded
  if (container.style.display === 'block' && container.children.length > 0) {
    container.style.display = 'none';
    btn.textContent = '🔍 生成类似题';
    return;
  }
  // Check cache first
  let r = await fetch('/api/mistakes/' + mistakeId + '/similar');
  let data = await r.json();
  if (data.questions && data.questions.length > 0) {
    renderSimilarQuestions(container, data.questions);
    btn.textContent = '🔍 隐藏类似题';
    return;
  }
  // Generate new
  btn.textContent = '⏳ 生成中...';
  btn.disabled = true;
  r = await fetch('/api/mistakes/' + mistakeId + '/similar', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({count:2, access_code: CODE})});
  data = await r.json();
  btn.textContent = '🔍 隐藏类似题';
  btn.disabled = false;
  if (data.questions && data.questions.length > 0) {
    renderSimilarQuestions(container, data.questions);
  } else {
    container.innerHTML = '<p class="meta">生成失败，请重试</p>';
    container.style.display = 'block';
  }
}

function renderSimilarQuestions(container, questions) {
  container.style.display = 'block';
  container.innerHTML = questions.map((q, i) => `
    <div style="background:#f8f6f0;border-radius:6px;padding:10px;margin-top:6px;">
      <div style="font-weight:600;margin-bottom:4px;">类似题${i+1}：${q.question_text}</div>
      <div style="font-size:.85em;color:var(--sub);">题型：${q.question_type || '-'} | 答案：${q.correct_answer || '-'}</div>
      <div style="font-size:.85em;color:var(--sub);">${q.explanation || ''}</div>
      ${(q.knowledge_points||[]).map(kp=>`<span class="badge badge-blue" style="margin-right:4px;font-size:.75em;">${kp}</span>`).join('')}
    </div>
  `).join('');
}

async function batchGenSimilar() {
  const btn = event.target;
  btn.textContent = '⏳ 批量生成中...';
  btn.disabled = true;
  const r = await fetch('/api/students/' + STUDENT_ID + '/batch-similar', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({limit:10,count_per:2, access_code: CODE})});
  const data = await r.json();
  btn.textContent = '⚡ 一键生成全部类似题';
  btn.disabled = false;
  let generated = 0, cached = 0;
  for (const result of data.results || []) {
    if (result.cached) cached++;
    else generated++;
    const container = document.getElementById('similar-' + result.mistake_id);
    if (container && result.questions.length > 0) {
      renderSimilarQuestions(container, result.questions);
      const btn = container.parentElement.querySelector('button[onclick*="genSimilar"]');
      if (btn) btn.textContent = '🔍 隐藏类似题';
    }
  }
  toast(`生成完成：新增 ${generated} 组，复用缓存 ${cached} 组`);
}

async function masterMistake(id) {
  const r = await fetch('/api/mistakes/' + id + '/master', {method:'POST'});
  if (r.ok) { toast('已标记掌握'); loadData(); }
  else toast('操作失败');
}

async function renderTimeline() {
  const div = document.getElementById('page-timeline');
  div.innerHTML = '<div class="card"><p style="text-align:center;color:var(--sub);">加载中...</p></div>';
  try {
    const r = await fetch('/api/public/' + CODE + '/timeline');
    if (!r.ok) { div.innerHTML = '<div class="card"><div class="empty">暂无时间轴数据</div></div>'; return; }
    const data = await r.json();
    const milestones = data.milestones || [];
    if (milestones.length === 0) {
      div.innerHTML = '<div class="card"><div class="empty">🌱 学习之旅刚刚开始，完成首次诊断后将出现第一条里程碑。</div></div>';
      return;
    }
    let html = '<div class="card"><h3>🛤️ 学习路径</h3><p class="meta" style="margin-bottom:16px;">每一步成长都值得被记录</p><div class="timeline">';
    for (const m of milestones) {
      html += `<div class="tl-item">
        <div class="tl-dot">${m.icon}</div>
        <div class="tl-date">${m.date}</div>
        <div class="tl-title">${m.icon} ${m.title}</div>
        <div class="tl-desc">${m.description}</div>
      </div>`;
    }
    html += '</div></div>';
    div.innerHTML = html;
  } catch(e) {
    div.innerHTML = '<div class="card"><div class="empty">时间轴加载失败</div></div>';
  }
}

let currentReview = null;

async function renderReview() {
  const div = document.getElementById('page-review');
  div.innerHTML = '<div class="card"><p style="text-align:center;color:var(--sub);">加载中...</p></div>';
  try {
    const r = await fetch('/api/public/' + CODE + '/review');
    if (!r.ok) { div.innerHTML = '<div class="card"><div class="empty">暂无复盘数据</div></div>'; return; }
    const data = await r.json();
    currentReview = data.review;
    const review = data.review || {};
    const tpl = review.template_questions || {};
    const childQs = tpl.child_reflection || [];
    const parentQs = tpl.parent_observation || [];
    const childAns = review.child_answers || {};
    const parentAns = review.parent_answers || {};
    const isSubmitted = review.status === 'submitted';

    let formHtml = '';

    // Child reflection section
    formHtml += `<div style="margin-bottom:16px;">
      <h4 style="margin-bottom:8px;">🙋 孩子反思区</h4>
      <p class="meta" style="margin-bottom:10px;">请孩子诚实回答以下问题：</p>`;
    childQs.forEach((q, i) => {
      const val = childAns[q] || '';
      formHtml += `<div class="form-group">
        <label>${i+1}. ${q}</label>
        <textarea class="review-input" data-child="${_escapeHtml(q)}" rows="2" placeholder="写下你的想法..." ${isSubmitted?'readonly':''} style="${isSubmitted?'background:#f5f2ec;':''}">${_escapeHtml(val)}</textarea>
      </div>`;
    });
    // Child mood
    formHtml += `<div class="form-group">
      <label>😊 这周学习心情（1-5分）</label>
      <div style="display:flex;gap:8px;">${[1,2,3,4,5].map(n =>
        `<button class="mood-btn ${review.child_mood===n?'mood-active':''}" onclick="setMood('child',${n})" ${isSubmitted?'disabled':''}>${n}</button>`
      ).join('')}</div>
    </div>`;
    // Child note
    formHtml += `<div class="form-group">
      <label>还有什么想说的话</label>
      <textarea class="review-input" id="child-note" rows="2" placeholder="自由发挥..." ${isSubmitted?'readonly':''} style="${isSubmitted?'background:#f5f2ec;':''}">${_escapeHtml(review.child_note||'')}</textarea>
    </div></div>`;

    // Parent observation section
    formHtml += `<div style="margin-bottom:16px;">
      <h4 style="margin-bottom:8px;">👨‍👩‍👧 家长观察区</h4>
      <p class="meta" style="margin-bottom:10px;">请家长从观察者角度回答：</p>`;
    parentQs.forEach((q, i) => {
      const val = parentAns[q] || '';
      formHtml += `<div class="form-group">
        <label>${i+1}. ${q}</label>
        <textarea class="review-input" data-parent="${_escapeHtml(q)}" rows="2" placeholder="写下你的观察..." ${isSubmitted?'readonly':''} style="${isSubmitted?'background:#f5f2ec;':''}">${_escapeHtml(val)}</textarea>
      </div>`;
    });
    formHtml += `<div class="form-group">
      <label>😊 家长感受（1-5分）</label>
      <div style="display:flex;gap:8px;">${[1,2,3,4,5].map(n =>
        `<button class="mood-btn ${review.parent_mood===n?'mood-active':''}" onclick="setMood('parent',${n})" ${isSubmitted?'disabled':''}>${n}</button>`
      ).join('')}</div>
    </div>`;
    formHtml += `<div class="form-group">
      <label>家长备注</label>
      <textarea class="review-input" id="parent-note" rows="2" placeholder="想对老师说的话..." ${isSubmitted?'readonly':''} style="${isSubmitted?'background:#f5f2ec;':''}">${_escapeHtml(review.parent_note||'')}</textarea>
    </div></div>`;

    // Submit button or submitted badge
    if (isSubmitted) {
      formHtml += `<div style="text-align:center;padding:12px;background:#e8f5e9;border-radius:8px;color:var(--green);font-weight:600;">✅ 本周复盘已提交 · ${(review.submitted_at||'').slice(0,10)}</div>`;
    } else {
      formHtml += `<button class="btn btn-primary" style="width:100%;" onclick="submitReview()">📝 提交本周复盘</button>`;
    }

    // History
    const history = data.history || [];
    let histHtml = '';
    if (history.length > 1) {
      histHtml = '<div style="margin-top:20px;"><h4 style="margin-bottom:10px;">📋 历史复盘</h4>';
      history.forEach(h => {
        if (h.week_start === review.week_start) return;
        histHtml += `<div style="background:var(--bg);border-radius:6px;padding:10px;margin-bottom:8px;">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <span style="font-weight:600;">📅 ${h.week_start} 周</span>
            <span style="font-size:.8em;color:${h.status==='submitted'?'var(--green)':'var(--sub)'};">${h.status==='submitted'?'已提交':'草稿'}</span>
          </div>`;
        if (h.child_mood) histHtml += `<span style="font-size:.8em;">孩子心情：${'⭐'.repeat(h.child_mood)}</span> `;
        if (h.parent_mood) histHtml += `<span style="font-size:.8em;">家长感受：${'⭐'.repeat(h.parent_mood)}</span>`;
        histHtml += '</div>';
      });
      histHtml += '</div>';
    }

    div.innerHTML = `<div class="card"><h3>🧠 每周元认知复盘</h3>
      <p class="meta" style="margin-bottom:16px;">${review.week_start} 周 · 反思让学习更深刻</p>
      ${formHtml}
      ${histHtml}
    </div>`;
  } catch(e) {
    div.innerHTML = '<div class="card"><div class="empty">复盘加载失败</div></div>';
  }
}

function setMood(type, value) {
  currentReview[type + '_mood'] = value;
  document.querySelectorAll('.mood-btn').forEach(b => b.classList.remove('mood-active'));
  event.target.classList.add('mood-active');
}

async function submitReview() {
  if (!currentReview) return;
  const childAns = {};
  document.querySelectorAll('[data-child]').forEach(el => {
    childAns[el.dataset.child] = el.value;
  });
  const parentAns = {};
  document.querySelectorAll('[data-parent]').forEach(el => {
    parentAns[el.dataset.parent] = el.value;
  });
  const body = {
    week_start: currentReview.week_start,
    child_answers: childAns,
    parent_answers: parentAns,
    child_mood: currentReview.child_mood,
    parent_mood: currentReview.parent_mood,
    child_note: document.getElementById('child-note')?.value || '',
    parent_note: document.getElementById('parent-note')?.value || '',
  };
  const r = await fetch('/api/public/' + CODE + '/review', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  if (r.ok) {
    toast('复盘已提交');
    renderReview();
  } else {
    toast('提交失败，请重试');
  }
}

function _escapeHtml(s) {
  if (!s) return '';
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

async function renderAchievements() {
  const div = document.getElementById('page-achievements');
  div.innerHTML = '<div class="card"><p style="text-align:center;color:var(--sub);">加载中...</p></div>';
  try {
    const r = await fetch('/api/public/' + CODE + '/achievements');
    if (!r.ok) { div.innerHTML = '<div class="card"><div class="empty">暂无成就数据</div></div>'; return; }
    const data = await r.json();
    const earned = data.earned_count || 0;
    const total = data.total_count || 0;

    let html = `<div class="card">
      <h3>🏆 成就墙 <span style="font-size:.7em;color:var(--sub);font-weight:normal;">${earned}/${total} 已解锁</span></h3>
      <div style="display:grid;grid-template-columns:repeat(auto-fill, minmax(140px, 1fr));gap:10px;margin-top:12px;">`;

    for (const a of data.all || []) {
      const earnedClass = a.earned ? 'ach-earned' : 'ach-locked';
      const pct = a.progress_pct || 0;
      html += `<div class="ach-card ${earnedClass}" title="${a.description}">
        <div class="ach-icon">${a.icon}</div>
        <div class="ach-title">${a.title}</div>
        <div class="ach-desc">${a.description}</div>`;
      if (a.earned) {
        html += `<div class="ach-date">${(a.earned_at||'').slice(0,10)}</div>`;
      } else {
        html += `<div class="ach-progress"><div class="ach-progress-bar" style="width:${pct}%;"></div></div>
          <div class="ach-progress-text">${a.current}/${a.threshold}</div>`;
      }
      html += `</div>`;
    }

    html += `</div></div>`;
    div.innerHTML = html;
  } catch(e) {
    div.innerHTML = '<div class="card"><div class="empty">成就加载失败</div></div>';
  }
}

function renderCheckin(d) {
  const div = document.getElementById('page-checkin');
  const today = new Date().toISOString().slice(0,10);
  const checkedToday = d.check_ins.includes(today);

  // Build 30-day calendar
  const days = [];
  for (let i = 29; i >= 0; i--) {
    const dt = new Date(); dt.setDate(dt.getDate() - i);
    days.push(dt.toISOString().slice(0,10));
  }

  div.innerHTML = `
    <div class="card">
      <h3>📅 本月打卡</h3>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
        <span class="meta">已打卡 ${d.check_ins.length} 天</span>
        <button class="btn ${checkedToday?'btn-outline':'btn-green'}" onclick="doCheckIn()" ${checkedToday?'disabled':''}>${checkedToday?'今日已打卡':'今日打卡'}</button>
      </div>
      <div class="calendar">
        ${days.map(day=>`
          <div class="cal-day ${d.check_ins.includes(day)?'checked':''} ${day===today?'today':''}" title="${day}">
            ${parseInt(day.slice(8))}
          </div>
        `).join('')}
      </div>
    </div>
  `;
}

async function doCheckIn() {
  const r = await fetch('/api/checkin', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({access_code: CODE, content: '今日学习打卡'})
  });
  if (r.ok) { toast('打卡成功'); loadData(); }
  else toast('打卡失败');
}

function renderProgress(d) {
  const div = document.getElementById('page-progress');

  // Score trend mini chart
  let chartHtml = '<p class="meta">暂无分数记录</p>';
  if (d.scores && d.scores.length > 0) {
    const values = d.scores.map(s=>s.score);
    const labels = d.scores.map(s=>s.created_at.slice(5,10));
    chartHtml = renderSvgChart(labels, values, d.student.target_score);
  }

  // Weak points
  const kpHtml = renderKnowledgeMastery(d.weak_points, {compact: true});

  // Weekly activity
  let weekHtml = '<p class="meta">暂无周度记录</p>';
  if (d.weekly_activity && d.weekly_activity.length > 0) {
    weekHtml = d.weekly_activity.map(w=>`
      <div class="week-row">
        <span>${w.week_start} 周</span>
        <span>${w.exercises_graded?'✅ 已完成':'⏳ 进行中'}</span>
      </div>
    `).join('');
  }

  // Learning style radar
  let lsHtml = '';
  if (d.learning_style) {
    lsHtml = `<div class="card">
      <h3>🧠 学习风格画像</h3>
      <div style="max-width:260px;margin:0 auto;">${renderRadarChart(d.learning_style, {size: 220})}</div>
    </div>`;
  }

  div.innerHTML = `
    ${lsHtml}
    <div class="card">
      <h3>📈 分数趋势</h3>
      ${chartHtml}
    </div>
    <div class="card">
      <h3>🔥 薄弱知识点</h3>
      ${kpHtml}
    </div>
    <div class="card">
      <h3>🗓️ 周度完成情况</h3>
      ${weekHtml}
    </div>
  `;
}

function renderSvgChart(labels, values, target) {
  const width = 600, height = 180, padding = 30;
  const chartW = width - padding * 2, chartH = height - padding * 2;
  const maxVal = Math.max(...values, target || 0, 1);
  const minVal = Math.min(...values, 0);
  const range = maxVal - minVal || 1;
  const points = values.map((v,i)=> {
    const x = padding + (i/(values.length-1||1))*chartW;
    const y = height - padding - ((v-minVal)/range)*chartH;
    return `${x},${y}`;
  }).join(' ');
  const dots = values.map((v,i)=> {
    const x = padding + (i/(values.length-1||1))*chartW;
    const y = height - padding - ((v-minVal)/range)*chartH;
    return `<circle cx="${x}" cy="${y}" r="4" fill="var(--accent)" stroke="#fff" stroke-width="2"/>
            <text x="${x}" y="${y-10}" text-anchor="middle" font-size="10" fill="var(--sub)">${v}</text>`;
  }).join('');
  const xlabs = labels.map((l,i)=> {
    const x = padding + (i/(labels.length-1||1))*chartW;
    return `<text x="${x}" y="${height-padding+16}" text-anchor="middle" font-size="10" fill="var(--sub)">${l}</text>`;
  }).join('');
  let targetLine = '';
  if (target) {
    const y = height - padding - ((target-minVal)/range)*chartH;
    targetLine = `<line x1="${padding}" y1="${y}" x2="${width-padding}" y2="${y}" stroke="var(--green)" stroke-dasharray="4,4"/>
                  <text x="${width-padding}" y="${y-5}" text-anchor="end" font-size="10" fill="var(--green)">目标 ${target}</text>`;
  }
  return `<svg viewBox="0 0 ${width} ${height}" style="width:100%;height:${height}px;">
    <rect width="${width}" height="${height}" fill="var(--card)"/>
    <line x1="${padding}" y1="${height-padding}" x2="${width-padding}" y2="${height-padding}" stroke="var(--border)"/>
    <line x1="${padding}" y1="${padding}" x2="${padding}" y2="${height-padding}" stroke="var(--border)"/>
    ${targetLine}
    <polyline fill="none" stroke="var(--accent)" stroke-width="2.5" points="${points}"/>
    ${dots}
    ${xlabs}
  </svg>`;
}

// Auto-switch to tab from URL hash (e.g. /s/xxx#mistakes)
if (window.location.hash) {
  const hashTab = window.location.hash.slice(1);
  const validTabs = ['practice','reports','timeline','mistakes','achievements','review','checkin','progress'];
  if (validTabs.includes(hashTab)) {
    setTimeout(() => switchTab(hashTab), 500);
  }
}
loadData();
</script>
</body>
</html>'''


@app.route('/s/<code>')
def student_view(code):
    """Public student view — no login required."""
    conn = get_connection()
    student = conn.execute(
        "SELECT id FROM students WHERE access_code = ? AND status = 'active'", [code]
    ).fetchone()
    conn.close()
    if not student:
        return '<h2 style="text-align:center;margin-top:80px;">链接无效或已过期</h2>', 404
    return render_template_string(STUDENT_PAGE, code=code)


# ═══════════════════════════════════════════════════
# Parent Mobile H5 — AI 学情体检
# ═══════════════════════════════════════════════════

PARENT_PAGE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>AI 学情体检</title>
<style>
  :root {
    --bg: #f8f7f4; --card: #ffffff; --text: #1a1a1a;
    --sub: #6b6b6b; --mute: #9b9b9b; --accent: #e07b4b;
    --accent-hover: #d06a3a; --accent-light: #fef3ed;
    --green: #0f7b4e; --green-light: #effaf3;
    --red: #d93a46; --red-light: #fef4f4;
    --blue: #4b8dc7; --blue-light: #eef5fb;
    --border: #e8e6e1;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    font-family: -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
    background: var(--bg); color: var(--text); line-height:1.6;
    min-height:100vh; padding-bottom:40px;
  }
  .container { max-width:480px; margin:0 auto; padding:16px; }

  /* Header */
  .header { text-align:center; padding:32px 0 20px; }
  .header .icon { font-size:48px; margin-bottom:12px; }
  .header h1 { font-size:1.5rem; font-weight:700; margin-bottom:4px; }
  .header p { font-size:.875rem; color:var(--sub); }

  /* Steps */
  .steps { display:flex; gap:8px; margin:0 0 24px; }
  .step {
    flex:1; text-align:center; padding:12px 8px; background:var(--card);
    border-radius:10px; box-shadow:0 1px 3px rgba(0,0,0,.06); font-size:.75rem;
    color:var(--mute); transition:all .3s;
  }
  .step .num {
    display:inline-block; width:24px; height:24px; line-height:24px;
    border-radius:50%; background:var(--bg); font-weight:700; font-size:.75rem;
    margin-bottom:4px;
  }
  .step.active { color:var(--accent); box-shadow:0 2px 8px rgba(224,123,75,.15); }
  .step.active .num { background:var(--accent); color:#fff; }
  .step.done { color:var(--green); }
  .step.done .num { background:var(--green); color:#fff; }

  /* Upload Zone */
  .upload-zone {
    background:var(--card); border:2px dashed var(--border); border-radius:16px;
    padding:40px 20px; text-align:center; cursor:pointer; transition:all .2s;
    margin-bottom:16px;
  }
  .upload-zone:hover, .upload-zone.dragover { border-color:var(--accent); background:var(--accent-light); }
  .upload-zone .icon { font-size:56px; display:block; margin-bottom:12px; }
  .upload-zone .title { font-size:1rem; font-weight:600; margin-bottom:4px; }
  .upload-zone .hint { font-size:.75rem; color:var(--mute); }
  .upload-zone .preview { max-width:100%; max-height:240px; border-radius:8px; display:none; margin:0 auto; }

  /* File input hidden */
  #fileInput { display:none; }

  /* Progress */
  .progress-card {
    background:var(--card); border-radius:16px; padding:32px 20px; text-align:center;
    box-shadow:0 2px 8px rgba(0,0,0,.06); display:none; margin-bottom:16px;
  }
  .spinner {
    display:inline-block; width:40px; height:40px; border:3px solid var(--border);
    border-top-color:var(--accent); border-radius:50%; animation:spin .8s linear infinite;
    margin-bottom:16px;
  }
  @keyframes spin { to { transform:rotate(360deg); } }
  .progress-card .status { font-size:.875rem; color:var(--sub); }
  .progress-card .step-name { font-size:.75rem; color:var(--mute); margin-top:4px; }

  /* Result Card */
  .result-card {
    background:var(--card); border-radius:16px; padding:24px 20px;
    box-shadow:0 2px 8px rgba(0,0,0,.06); display:none; margin-bottom:16px;
  }
  .result-card .title { font-size:1.15rem; font-weight:600; margin-bottom:16px; text-align:center; }
  .result-card .score-box {
    display:flex; align-items:center; justify-content:center; gap:16px;
    padding:16px; background:var(--accent-light); border-radius:12px; margin-bottom:20px;
  }
  .score-circle {
    width:72px; height:72px; border-radius:50%; display:flex; align-items:center;
    justify-content:center; font-size:1.5rem; font-weight:700; color:#fff;
  }
  .score-circle.high { background:var(--green); }
  .score-circle.mid { background:var(--accent); }
  .score-circle.low { background:var(--red); }
  .score-detail { font-size:.8rem; color:var(--sub); line-height:1.5; }
  .score-detail strong { color:var(--text); }

  .diagnosis-item {
    padding:12px 16px; border-radius:10px; margin-bottom:8px;
    display:flex; align-items:flex-start; gap:10px; font-size:.875rem;
  }
  .diagnosis-item .tag {
    display:inline-block; padding:2px 10px; border-radius:100px;
    font-size:.7rem; font-weight:600; white-space:nowrap;
  }
  .diagnosis-item.weak { background:var(--red-light); }
  .diagnosis-item.weak .tag { background:var(--red); color:#fff; }
  .diagnosis-item.ok { background:var(--green-light); }
  .diagnosis-item.ok .tag { background:var(--green); color:#fff; }
  .diagnosis-item.tip { background:var(--blue-light); }
  .diagnosis-item.tip .tag { background:var(--blue); color:#fff; }

  /* Buttons */
  .btn {
    display:block; width:100%; padding:14px; border:none; border-radius:12px;
    font-size:.95rem; font-weight:600; cursor:pointer; transition:all .15s;
    text-align:center; text-decoration:none;
  }
  .btn-primary { background:var(--accent); color:#fff; margin-bottom:8px; }
  .btn-primary:hover { background:var(--accent-hover); }
  .btn-secondary { background:var(--card); color:var(--accent); border:1.5px solid var(--accent); }
  .btn:disabled { opacity:.5; pointer-events:none; }

  /* Toast */
  .toast {
    position:fixed; top:20px; left:50%; transform:translateX(-50%); z-index:999;
    background:#1a1a1a; color:#fff; padding:10px 24px; border-radius:100px;
    font-size:.8rem; display:none;
  }

  /* Bottom CTA */
  .bottom-cta { text-align:center; padding:8px 0; }
  .bottom-cta p { font-size:.75rem; color:var(--mute); }
</style>
</head>
<body>
<div class="container">

  <!-- Header -->
  <div class="header">
    <div class="icon">🏠</div>
    <h1>AI 学情体检</h1>
    <p>不急着评价孩子，先学会看懂孩子</p>
  </div>

  <!-- Steps -->
  <div class="steps" id="steps">
    <div class="step active" id="step1"><div class="num">1</div>拍张试卷</div>
    <div class="step" id="step2"><div class="num">2</div>AI 看懂</div>
    <div class="step" id="step3"><div class="num">3</div>知道怎么办</div>
  </div>

  <!-- Upload -->
  <div class="upload-zone" id="uploadZone" onclick="document.getElementById('fileInput').click()">
    <span class="icon">📸</span>
    <div class="title">点这里，拍一张孩子的英语试卷</div>
    <div class="hint">拍得清楚一点，AI 看得更准哦</div>
    <img class="preview" id="previewImg" />
  </div>
  <input type="file" id="fileInput" accept="image/*" capture="environment" />

  <!-- Progress -->
  <div class="progress-card" id="progressCard">
    <div class="spinner"></div>
    <div class="status" id="progressStatus">正在识别试卷文字...</div>
    <div class="step-name" id="progressStep"></div>
  </div>

  <!-- Dashboard (returning users) -->
  <div class="dashboard" id="dashboard" style="display:none;">
    <!-- Stats row -->
    <div class="stats-row" id="statsRow"></div>
    <!-- Progress timeline -->
    <div class="result-card" id="timelineCard" style="margin-top:16px;">
      <div style="font-weight:600;font-size:.95rem;margin-bottom:12px;">📅 成长足迹</div>
      <div id="timelineList" style="font-size:.8rem;color:var(--sub);"></div>
    </div>
    <!-- Knowledge mastery -->
    <div class="result-card" id="masteryCard" style="margin-top:12px;">
      <div style="font-weight:600;font-size:.95rem;margin-bottom:12px;">🌱 成长进度</div>
      <div id="masteryBar"></div>
    </div>
    <!-- New test button -->
    <button class="btn btn-primary" onclick="startNewTest()" style="margin-top:16px;">📸 这周的试卷拍一张</button>
    <button class="btn btn-secondary" onclick="resetParent()" style="margin-top:8px;font-size:.8rem;">换个孩子看看</button>
  </div>

  <!-- Upload Zone (wrapped) -->
  <div id="uploadSection">
    <div class="upload-zone" id="uploadZone" onclick="document.getElementById('fileInput').click()">
      <span class="icon">📸</span>
      <div class="title">点击拍照或选择试卷照片</div>
      <div class="hint">支持 JPG/PNG，建议拍清晰</div>
      <img class="preview" id="previewImg" />
    </div>
    <input type="file" id="fileInput" accept="image/*" capture="environment" />
  </div>

  <!-- Progress -->
  <div class="progress-card" id="progressCard">
    <div class="spinner"></div>
    <div class="status" id="progressStatus">正在识别试卷文字...</div>
    <div class="step-name" id="progressStep"></div>
  </div>

  <!-- Result (one-time diagnosis) -->
  <div class="result-card" id="resultCard"></div>

  <!-- Bottom -->
  <div class="bottom-cta">
    <p>外面已经够卷了，家里别再变成第二个战场 💛</p>
  </div>
</div>

<!-- Toast -->
<div class="toast" id="toast"></div>

<script>
  const STORAGE_KEY = 'ai_parent_code';
  let savedCode = localStorage.getItem(STORAGE_KEY) || '';

  const fileInput = document.getElementById('fileInput');
  const uploadZone = document.getElementById('uploadZone');
  const uploadSection = document.getElementById('uploadSection');
  const previewImg = document.getElementById('previewImg');
  const progressCard = document.getElementById('progressCard');
  const resultCard = document.getElementById('resultCard');
  const dashboard = document.getElementById('dashboard');
  const progressStatus = document.getElementById('progressStatus');
  const progressStep = document.getElementById('progressStep');

  // Init: check for returning user
  (async function init() {
    if (savedCode) {
      const data = await loadProgress(savedCode);
      if (data && data.diagnoses && data.diagnoses.length > 0) {
        showDashboard(data);
        return;
      }
      // Code invalid, clear
      localStorage.removeItem(STORAGE_KEY);
      savedCode = '';
    }
    showUploadMode();
  })();

  fileInput.addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      previewImg.src = ev.target.result;
      previewImg.style.display = 'block';
      uploadZone.querySelector('.icon').style.display = 'none';
      uploadZone.querySelector('.title').textContent = '选好了，点这里重新拍';
      uploadZone.querySelector('.hint').textContent = file.name;
    };
    reader.readAsDataURL(file);
    await diagnose(file);
  });

  function showUploadMode() {
    uploadSection.style.display = 'block';
    dashboard.style.display = 'none';
    resultCard.style.display = 'none';
    progressCard.style.display = 'none';
    setStep(1);
  }

  function startNewTest() {
    uploadSection.style.display = 'block';
    resultCard.style.display = 'none';
    progressCard.style.display = 'none';
    previewImg.style.display = 'none';
    uploadZone.querySelector('.icon').style.display = 'block';
    uploadZone.querySelector('.title').textContent = '点这里，拍一张孩子的英语试卷';
    uploadZone.querySelector('.hint').textContent = '拍得清楚一点，AI 看得更准哦';
    setStep(1);
    window.scrollTo({top:0, behavior:'smooth'});
  }

  function resetParent() {
    localStorage.removeItem(STORAGE_KEY);
    savedCode = '';
    dashboard.style.display = 'none';
    document.getElementById('steps').style.display = 'flex';
    showUploadMode();
  }

  async function diagnose(file) {
    uploadSection.style.display = 'none';
    dashboard.style.display = 'none';
    progressCard.style.display = 'block';
    resultCard.style.display = 'none';
    setStep(2);

    const formData = new FormData();
    formData.append('file', file);
    if (savedCode) formData.append('access_code', savedCode);

    progressStatus.textContent = '正在上传，稍等一下...';
    progressStep.textContent = '';

    let res;
    try {
      res = await fetch('/api/parent/diagnose', { method:'POST', body:formData });
    } catch(e) {
      showError('网络不太稳定，请再试一次');
      return;
    }

    if (!res.ok) {
      const err = await res.json().catch(()=>({error:'出了点小问题'}));
      showError(err.error || '上传没成功，再试一次吧');
      return;
    }

    const { task_id, access_code } = await res.json();

    // Remember code for returning
    if (access_code) {
      savedCode = access_code;
      localStorage.setItem(STORAGE_KEY, access_code);
    }

    await pollTask(task_id);
  }

  async function pollTask(taskId) {
    const stepTexts = {
      'ocr': '正在读取试卷上的每一行字...',
      'analysis': '正在分析每道题错在哪里...',
      'plan': '正在为你定制下周的学习重点...',
      'report': '正在整理结果，马上就好...',
    };

    for (let i = 0; i < 120; i++) {
      await sleep(1500);
      let res;
      try { res = await fetch('/api/parent/task/' + taskId); } catch(e) { continue; }
      if (!res.ok) break;
      const data = await res.json();

      if (data.status === 'failed') {
        showError(data.error_message || '分析没成功，再试一次吧');
        return;
      }
      progressStatus.textContent = stepTexts[data.current_step] || '正在处理...';
      progressStep.textContent = data.progress ? '进度 ' + data.progress + '%' : '';
      if (data.status === 'done') {
        setStep(3);
        progressCard.style.display = 'none';
        // Reload dashboard with new data
        if (savedCode) {
          const prog = await loadProgress(savedCode);
          if (prog) { showDashboard(prog); return; }
        }
        showResult(data.output_data);
        return;
      }
    }
    showError('正在努力分析中，请稍后再看');
  }

  // ── Progress / Dashboard ──

  async function loadProgress(code) {
    try {
      const r = await fetch('/api/parent/progress/' + code);
      if (!r.ok) return null;
      return await r.json();
    } catch(e) { return null; }
  }

  function showDashboard(data) {
    dashboard.style.display = 'block';
    uploadSection.style.display = 'none';
    progressCard.style.display = 'none';
    resultCard.style.display = 'none';
    document.getElementById('steps').style.display = 'none';

    const d = data;
    const diagnoses = d.diagnoses || [];
    const latest = diagnoses[0] || {};
    const mistakes = d.mistakes || { total: 0, mastered: 0 };

    // Stats row — reframed positively
    let statsHtml = '<div style="display:flex;gap:8px;flex-wrap:wrap;">';
    statsHtml += statCard('🩺', diagnoses.length, '次体检');
    statsHtml += statCard('🌟', mistakes.mastered, '已稳住');
    statsHtml += statCard('🌱', mistakes.total - mistakes.mastered, '成长中');
    statsHtml += statCard('💪', d.checkin_days || 0, '坚持天');
    statsHtml += '</div>';
    document.getElementById('statsRow').innerHTML = statsHtml;

    // Timeline
    let tlHtml = '';
    if (diagnoses.length === 0) {
      tlHtml = '<div style="color:var(--mute);text-align:center;padding:20px;">还没有记录哦～ 上传第一份试卷，开启成长之旅吧</div>';
    }
    diagnoses.forEach((diag, idx) => {
      const icon = idx === 0 ? '🆕' : '📄';
      tlHtml += `<div style="display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid var(--border);">
        <span style="font-size:1.2rem;">${icon}</span>
        <div style="flex:1;">
          <div style="font-weight:600;">${escapeHtml(diag.date || '')}</div>
          <div style="font-size:.75rem;color:var(--sub);">发现 ${diag.mistakes_count} 个提升点 · 聚焦 ${diag.weak_points_count} 个知识块</div>
        </div>
        ${idx === 0 && diagnoses.length > 1 ? trendBadge(diagnoses) : ''}
      </div>`;
    });
    document.getElementById('timelineList').innerHTML = tlHtml || '<div style="color:var(--mute);">暂无记录</div>';

    // Mastery bar — growth journey framing
    const total = mistakes.total || 1;
    const pct = Math.round(mistakes.mastered / total * 100);
    document.getElementById('masteryBar').innerHTML = `
      <div style="display:flex;justify-content:space-between;font-size:.8rem;margin-bottom:6px;">
        <span>成长进度</span><span style="font-weight:600;">${pct}%</span>
      </div>
      <div style="height:10px;background:var(--border);border-radius:10px;overflow:hidden;">
        <div style="height:100%;width:${pct}%;background:var(--green);border-radius:10px;transition:width .5s;"></div>
      </div>
      <div style="font-size:.7rem;color:var(--mute);margin-top:4px;">
        ${mistakes.mastered} / ${mistakes.total} 个知识块已经稳住
        ${pct >= 60 ? '🎉 进步很大，继续保持这个节奏！' : pct >= 30 ? '💪 方向是对的，稳稳往前走' : '🌱 每一步都算数，孩子正在成长'}
      </div>`;
  }

  function statCard(icon, num, label) {
    return `<div style="flex:1;min-width:70px;background:var(--card);border-radius:10px;padding:12px 8px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.06);">
      <div style="font-size:1.3rem;">${icon}</div>
      <div style="font-size:1.3rem;font-weight:700;">${num}</div>
      <div style="font-size:.7rem;color:var(--mute);">${label}</div>
    </div>`;
  }

  function trendBadge(diagnoses) {
    if (diagnoses.length < 2) return '';
    const curr = diagnoses[0].mistakes_count || 0;
    const prev = diagnoses[1].mistakes_count || 0;
    if (curr < prev) return '<span style="color:var(--green);font-size:.75rem;font-weight:600;">↓ 提升点变少啦</span>';
    if (curr > prev) return '<span style="color:var(--red);font-size:.75rem;font-weight:600;">↑ 这周多关注下</span>';
    return '<span style="color:var(--mute);font-size:.75rem;">→ 保持稳定</span>';
  }

  // ── Result (one-time, no account) ──

  function showResult(data) {
    resultCard.style.display = 'block';

    let mc = data.mistakes_count || 0;
    let wp = data.weak_points_count || 0;
    let score = mc === 0 ? 100 : Math.max(30, 100 - mc * 12);
    let level = score >= 80 ? 'high' : score >= 50 ? 'mid' : 'low';
    let levelText = score >= 80 ? '基础挺扎实的 👍' : score >= 50 ? '有进步空间 💪' : '现在开始，就是最好的时候 🌱';
    let weaknesses = typeof data.weak_points === 'string'
      ? data.weak_points.split('\n').filter(Boolean)
      : (data.weak_points || []);

    let html = '<div class="title">🩺 孩子的英语学习体检单</div>';

    // Score
    html += `<div class="score-box">
      <div class="score-circle ${level}">${score}</div>
      <div class="score-detail">
        <div><strong>综合状态：${levelText}</strong></div>
        <div>发现了 ${mc} 个可以提升的地方</div>
        <div>聚焦 ${wp} 个知识点就能进步</div>
      </div>
    </div>`;

    // Weak points - reframed as "growth opportunities"
    if (weaknesses.length > 0) {
      html += '<div style="font-weight:600;font-size:.9rem;margin-bottom:8px;">🌱 接下来可以重点关注</div>';
      weaknesses.forEach(w => {
        html += `<div class="diagnosis-item weak">
          <span class="tag">成长点</span>
          <span>${escapeHtml(w)}</span>
        </div>`;
      });
    }

    // Strengths
    html += '<div style="font-weight:600;font-size:.9rem;margin:16px 0 8px;">🌟 已经做得很好的</div>';
    html += `<div class="diagnosis-item ok">
      <span class="tag">稳住了</span>
      <span>AI 识别出部分稳定掌握的知识点，这是孩子的基础盘</span>
    </div>`;

    // Suggestions - parent-friendly actions
    html += '<div style="font-weight:600;font-size:.9rem;margin:16px 0 8px;">💛 这周你可以试试</div>';
    html += `<div class="diagnosis-item tip">
      <span class="tag">小行动</span>
      <span>每周拍一张试卷，坚持 4 周就能看到变化轨迹</span>
    </div>`;
    html += `<div class="diagnosis-item tip">
      <span class="tag">这样说</span>
      <span>别问"怎么又错了"，试试"我们一起来看这道题卡在哪里"</span>
    </div>`;

    resultCard.innerHTML = html;

    // Action buttons
    resultCard.innerHTML += `
      <div style="margin-top:20px;">
        <p style="text-align:center;font-size:.8rem;color:var(--mute);margin-bottom:8px;">每次拍照都会记录下来，进步看得见 ✨</p>
        <button class="btn btn-primary" onclick="location.reload()">再拍一张试卷</button>
      </div>`;
  }

  function showError(msg) {
    progressCard.style.display = 'none';
    uploadZone.style.display = 'block';
    setStep(1);
    const toast = document.getElementById('toast');
    toast.textContent = msg;
    toast.style.display = 'block';
    setTimeout(() => { toast.style.display = 'none'; }, 3000);
  }

  function setStep(n) {
    [1,2,3].forEach(i => {
      const el = document.getElementById('step'+i);
      el.className = 'step' + (i < n ? ' done' : i === n ? ' active' : '');
    });
  }

  function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

  // Drag & drop
  uploadZone.addEventListener('dragover', (e) => { e.preventDefault(); uploadZone.classList.add('dragover'); });
  uploadZone.addEventListener('dragleave', () => { uploadZone.classList.remove('dragover'); });
  uploadZone.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadZone.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (file && file.type.startsWith('image/')) {
      fileInput.files = e.dataTransfer.files;
      fileInput.dispatchEvent(new Event('change'));
    }
  });
</script>
</body>
</html>'''


@app.route('/parent')
def parent_view():
    """Parent mobile H5 landing — AI learning health check."""
    return render_template_string(PARENT_PAGE)


@app.route('/api/parent/diagnose', methods=['POST'])
def api_parent_diagnose():
    """Parent uploads test paper → trigger diagnosis pipeline."""
    if 'file' not in request.files:
        return jsonify({"error": "请选择试卷照片"}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({"error": "请选择试卷照片"}), 400

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'png'
    grade = request.form.get('grade', '高中')
    existing_code = (request.form.get('access_code') or '').strip()

    conn = get_connection()
    import secrets

    # Returning user — reuse existing student
    if existing_code:
        student = conn.execute(
            "SELECT id, name, grade FROM students WHERE access_code = ? AND status = 'active'",
            [existing_code]
        ).fetchone()
        if student:
            sid = student["id"]
            access_code = existing_code
        else:
            conn.close()
            return jsonify({"error": "链接已过期，请重新开始"}), 404
    else:
        # New parent — create student
        access_code = secrets.token_urlsafe(8)
        student_name = f"家长用户_{access_code[:6]}"
        sid = create_student({
            "name": student_name,
            "grade": grade,
            "access_code": access_code,
        })
    conn.close()

    # Save uploaded file
    student_dir = os.path.join(UPLOAD_DIR, str(sid), "test_paper")
    os.makedirs(student_dir, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(student_dir, filename)
    file.save(filepath)
    file_size = os.path.getsize(filepath)

    file_id = add_file(sid, "parent", "test_paper",
                       filename=filename, original_filename=file.filename,
                       file_size=file_size, mime_type=file.content_type or "image/png")

    # Use weekly pipeline for returning users, onboarding for new
    task_type = "weekly" if existing_code else "onboarding"
    task_id = create_task(sid, task_type, {
        "file_id": file_id,
        "grade": grade,
        "subject": "英语",
    })
    enqueue_task(task_id)

    return jsonify({
        "task_id": task_id,
        "access_code": access_code,
        "message": "诊断已开始",
    }), 202


@app.route('/api/parent/task/<int:task_id>')
def api_parent_task(task_id):
    """Poll task status for parent diagnosis."""
    task = get_task(task_id)
    if not task:
        return jsonify({"error": "task not found"}), 404

    result = {
        "status": task["status"],
        "current_step": task.get("current_step", ""),
        "progress": task.get("progress", 0),
    }

    if task["status"] == "failed":
        result["error_message"] = task.get("error_message", "分析失败")

    if task["status"] == "done":
        try:
            result["output_data"] = json.loads(task["output_data"]) if task["output_data"] else {}
        except Exception:
            result["output_data"] = {}

    return jsonify(result)


@app.route('/api/parent/progress/<code>')
def api_parent_progress(code):
    """Get learning progress for a parent-linked student."""
    conn = get_connection()
    student = conn.execute(
        "SELECT * FROM students WHERE access_code = ? AND status = 'active'", [code]
    ).fetchone()
    if not student:
        conn.close()
        return jsonify({"error": "invalid code"}), 404

    sid = student["id"]

    # Diagnoses history (completed tasks)
    tasks = conn.execute("""
        SELECT output_data, created_at, task_type
        FROM ai_tasks
        WHERE student_id = ? AND status = 'done'
        ORDER BY created_at DESC LIMIT 20
    """, [sid]).fetchall()

    diagnoses = []
    for t in tasks:
        try:
            out = json.loads(t["output_data"]) if t["output_data"] else {}
        except Exception:
            out = {}
        diagnoses.append({
            "date": t["created_at"][:10],
            "mistakes_count": out.get("mistakes_count", 0),
            "weak_points_count": out.get("weak_points_count", 0),
            "accuracy": out.get("accuracy"),
            "correct_count": out.get("correct_count"),
            "total_count": out.get("total_count"),
        })

    # Mistake mastery stats
    total = conn.execute(
        "SELECT COUNT(*) as c FROM mistakes WHERE student_id = ?", [sid]
    ).fetchone()["c"]
    mastered = conn.execute(
        "SELECT COUNT(*) as c FROM mistakes WHERE student_id = ? AND consecutive_correct >= 2",
        [sid]
    ).fetchone()["c"]

    # Knowledge points summary
    kp_rows = conn.execute("""
        SELECT knowledge_points FROM mistakes WHERE student_id = ?
    """, [sid]).fetchall()
    kp_all = []
    for row in kp_rows:
        try:
            kps = json.loads(row["knowledge_points"] or "[]")
            kp_all.extend(kps)
        except Exception:
            pass
    from collections import Counter
    kp_counts = Counter(kp_all).most_common(8)

    # Check-in days
    checkins = conn.execute("""
        SELECT COUNT(DISTINCT check_in_date) as d FROM check_ins WHERE student_id = ?
    """, [sid]).fetchone()["d"]

    # Score history
    scores = conn.execute("""
        SELECT score, score_type, created_at FROM score_history
        WHERE student_id = ? ORDER BY created_at DESC LIMIT 10
    """, [sid]).fetchall()

    conn.close()

    return jsonify({
        "student": dict(student),
        "diagnoses": diagnoses,
        "mistakes": {"total": total, "mastered": mastered},
        "knowledge_points": [{"name": k, "count": c} for k, c in kp_counts],
        "checkin_days": checkins or 0,
        "scores": [{"score": s["score"], "subject": s["score_type"],
                     "date": s["created_at"][:10]} for s in scores],
    })


@app.route('/api/public/<code>/reports', methods=['GET'])
def api_public_reports(code):
    """Get approved reports for public student page."""
    conn = get_connection()
    student = conn.execute(
        "SELECT id FROM students WHERE access_code = ? AND status = 'active'", [code]
    ).fetchone()
    if not student:
        conn.close()
        return jsonify({"error": "invalid code"}), 404

    tasks = conn.execute("""
        SELECT output_data, created_at
        FROM ai_tasks
        WHERE student_id = ? AND task_type = 'onboarding'
          AND status = 'done' AND needs_review = 0
        ORDER BY created_at DESC LIMIT 10
    """, [student["id"]]).fetchall()
    conn.close()

    reports = []
    for t in tasks:
        try:
            out = json.loads(t["output_data"]) if t["output_data"] else {}
            if out.get("report_file_id"):
                reports.append({
                    "report_file_id": out["report_file_id"],
                    "mistakes_count": out.get("mistakes_count", "?"),
                    "weak_points_count": out.get("weak_points_count", "?"),
                    "created_at": t["created_at"],
                })
        except Exception:
            pass
    return jsonify(reports)


@app.route('/api/public/<code>/request-deletion', methods=['POST'])
def api_public_request_deletion(code):
    """Public endpoint for parents to request deletion of their child's data."""
    data = request.get_json() or {}
    reason = (data.get('reason') or '').strip()
    requested_by = (data.get('requested_by') or '家长').strip()

    conn = get_connection()
    student = conn.execute(
        "SELECT id FROM students WHERE access_code = ? AND status = 'active'", [code]
    ).fetchone()
    conn.close()
    if not student:
        return jsonify({"error": "invalid or expired code"}), 404

    req_id = request_data_deletion(
        student_id=student["id"],
        requested_by=requested_by,
        reason=reason,
    )
    log_audit(
        actor_type="parent",
        actor_id=None,
        action="public_request_data_deletion",
        target_type="student",
        target_id=student["id"],
        details={"request_id": req_id, "reason": reason},
        ip_address=request.remote_addr or '',
    )
    return jsonify({"id": req_id, "success": True, "message": "删除申请已提交，老师会尽快处理"})


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
    print(f"[OK] 保留: 管理员/教师账号、学校、班级数据")


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
    if len(sys.argv) > 1 and sys.argv[1] == 'clear-students':
        _cli_clear_students()
        sys.exit(0)

    init_db()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    print('=' * 50)
    print('  拾阶而上 · 管理系统')
    print(f'  http://localhost:5000')
    print(f'  数据库: {DB_PATH}')
    print(f'  上传目录: {UPLOAD_DIR}')
    print(f'  LLM 缓存: {"开启" if os.environ.get("LLM_CACHE_ENABLED") == "true" else "关闭"}')
    print('=' * 50)
    app.run(host='127.0.0.1', port=5000, debug=False)
