#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运营端 API 蓝图：管理后台全部管理与运维接口（P2-12 自 app.py 拆出）。"""

import json
import os
from datetime import date

from flask import Blueprint, jsonify, request, send_file, session
from werkzeug.security import generate_password_hash

from db import *  # noqa: F401,F403
from pipeline_worker import enqueue_task
from web.shared import (UPLOAD_DIR, _enqueue_correction_rerun, _resolve_file_path,
                        _save_uploaded_file, admin_required,
                        login_required)

ops_api_bp = Blueprint("ops_api", __name__)


@ops_api_bp.route('/api/auth/me')
def api_auth_me():
    if 'user_id' in session:
        return jsonify({
            'logged_in': True,
            'user_id': session['user_id'],
            'username': session.get('user_name'),
            'role': session.get('user_role'),
        })
    return jsonify({'logged_in': False}), 401














@ops_api_bp.route('/api/dashboard')
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
    return jsonify(stats)

@ops_api_bp.route('/api/cost')
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

@ops_api_bp.route('/api/status')
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

@ops_api_bp.route('/api/students', methods=['GET'])
@login_required
def api_students_list():
    if session.get('user_role') == 'admin':
        students = get_all_students()
    else:
        students = get_students_by_teacher(session['user_id'])
    for s in students:
        s["has_consent"] = has_parent_consent(s["id"])
    return jsonify(students)

@ops_api_bp.route('/api/students/<int:id>', methods=['GET'])
@login_required
def api_student_get(id):
    row = get_student(id)
    if not row:
        return '', 404
    row["has_consent"] = has_parent_consent(id)
    return jsonify(row)

@ops_api_bp.route('/api/students', methods=['POST'])
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

@ops_api_bp.route('/api/students/<int:id>', methods=['PUT'])
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

@ops_api_bp.route('/api/students/<int:student_id>/profile', methods=['GET'])
@login_required
def api_student_profile_get(student_id):
    """Get student profile (chat.md dimensions)."""
    profile = get_student_profile(student_id)
    if not profile:
        return jsonify({}), 200
    return jsonify(profile)

@ops_api_bp.route('/api/students/<int:student_id>/profile', methods=['PUT'])
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

@ops_api_bp.route('/api/students/<int:student_id>/profile/parent-tasks', methods=['PUT'])
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

@ops_api_bp.route('/api/students/<int:student_id>/mistakes', methods=['GET'])
@login_required
def api_student_mistakes(student_id):
    """Get mistake book for a student (backend view)."""
    mastered = request.args.get('mastered', 'false').lower() == 'true'
    return jsonify(get_student_mistake_book(student_id, mastered=mastered))

@ops_api_bp.route('/api/mistakes/<int:mistake_id>/master', methods=['POST'])
@login_required
def api_mark_mistake_mastered(mistake_id):
    """Mark a mistake as mastered."""
    success = mark_mistake_mastered(mistake_id)
    if not success:
        return jsonify({"error": "错题不存在"}), 404
    return jsonify({"ok": True})

@ops_api_bp.route('/api/students/<int:student_id>/due-reviews', methods=['GET'])
@login_required
def api_student_due_reviews(student_id):
    """Get mistakes due for spaced repetition review."""
    from db import get_due_reviews, get_review_stats
    return jsonify({
        "due_reviews": get_due_reviews(student_id),
        "stats": get_review_stats(student_id),
    })

@ops_api_bp.route('/api/students/<int:student_id>/achievements', methods=['GET'])
@login_required
def api_student_achievements(student_id):
    """Get achievement wall for a student (teacher view)."""
    from db import get_student_achievements
    return jsonify(get_student_achievements(student_id))

@ops_api_bp.route('/api/students/<int:student_id>/reviews', methods=['GET'])
@login_required
def api_student_reviews(student_id):
    """Teacher: get all metacognitive reviews for a student."""
    from db import get_metacognitive_reviews, get_or_create_metacognitive_review
    current = get_or_create_metacognitive_review(student_id)
    history = get_metacognitive_reviews(student_id)
    return jsonify({"current": current, "history": history})

@ops_api_bp.route('/api/students/<int:student_id>/timeline', methods=['GET'])
@login_required
def api_student_timeline(student_id):
    """Get learning path timeline for a student (teacher view)."""
    from db import get_student_timeline
    return jsonify({"milestones": get_student_timeline(student_id)})

@ops_api_bp.route('/api/mistakes/<int:mistake_id>/similar', methods=['GET'])
def api_get_similar_questions(mistake_id):
    """Get existing similar questions for a mistake."""
    from skills_bridge import get_similar_questions_for_mistake
    return jsonify({"questions": get_similar_questions_for_mistake(mistake_id)})

@ops_api_bp.route('/api/mistakes/<int:mistake_id>/similar', methods=['POST'])
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

@ops_api_bp.route('/api/students/<int:student_id>/batch-similar', methods=['POST'])
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

@ops_api_bp.route('/api/students/<int:student_id>/checkins', methods=['GET'])
@login_required
def api_student_checkins(student_id):
    """Get check-in history for a student."""
    return jsonify(get_check_ins(student_id))

@ops_api_bp.route('/api/checkin', methods=['POST'])
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

@ops_api_bp.route('/api/questions', methods=['GET'])
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

@ops_api_bp.route('/api/questions/<int:question_id>', methods=['GET'])
@login_required
def api_question_get(question_id):
    q = get_question(question_id)
    return jsonify(q) if q else ('', 404)

@ops_api_bp.route('/api/questions/<int:question_id>', methods=['PUT'])
@login_required
def api_question_update(question_id):
    data = request.get_json() or {}
    success = update_question(question_id, data)
    if not success:
        return jsonify({"error": "题目不存在或无有效字段"}), 400
    return jsonify({"ok": True})

@ops_api_bp.route('/api/questions/<int:question_id>/toggle', methods=['POST'])
@login_required
def api_question_toggle(question_id):
    q = get_question(question_id)
    if not q:
        return jsonify({"error": "题目不存在"}), 404
    update_question(question_id, {"enabled": 0 if q.get("enabled") else 1})
    return jsonify({"ok": True, "enabled": not q.get("enabled")})

@ops_api_bp.route('/api/questions/stats', methods=['GET'])
@login_required
def api_question_stats():
    return jsonify(get_question_bank_stats())

@ops_api_bp.route('/api/learning/class', methods=['GET'])
@login_required
def api_learning_class():
    return jsonify(get_class_learning_stats())

@ops_api_bp.route('/api/learning/student/<int:student_id>', methods=['GET'])
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

@ops_api_bp.route('/api/learning/score', methods=['POST'])
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

@ops_api_bp.route('/api/budget', methods=['GET'])
@login_required
def api_budget_get():
    return jsonify(get_budgets())

@ops_api_bp.route('/api/budget', methods=['POST'])
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

@ops_api_bp.route('/api/subscriptions/<int:student_id>', methods=['GET'])
@login_required
def api_subscription_get(student_id):
    summary = get_subscription_summary(student_id)
    return jsonify(summary)

@ops_api_bp.route('/api/subscriptions', methods=['POST'])
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

@ops_api_bp.route('/api/payments', methods=['POST'])
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

@ops_api_bp.route('/api/payments/<int:student_id>', methods=['GET'])
@login_required
def api_payments_list(student_id):
    return jsonify(get_payments(student_id))

@ops_api_bp.route('/api/upload', methods=['POST'])
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

@ops_api_bp.route('/api/files/<int:file_id>/download')
@login_required
def api_file_download(file_id):
    f = get_file(file_id)
    if not f:
        return ('', 404)
    filepath = _resolve_file_path(f)
    if not filepath:
        return ('', 404)
    return send_file(filepath, download_name=f['original_filename'])




@ops_api_bp.route('/api/pipeline/run', methods=['POST'])
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

    # Quota gate (domain/quota.py 统一收口):
    # 仅 OCR 重阶段消耗额度；analysis_only/report_only 免费；staff 豁免
    is_staff = session.get("user_role") in ("teacher", "admin")
    QUOTA_FREE_STAGES = ("analysis_only", "report_only")
    quota_charged = False
    if stage not in QUOTA_FREE_STAGES:
        from domain import quota as quota_mod
        ok, err = quota_mod.charge_analysis(student_id, is_staff=is_staff)
        if not ok:
            return jsonify({"error": err}), 429
        quota_charged = not is_staff

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
    if quota_charged:
        input_data["quota_charged"] = True

    task_id = create_task(
        student_id=student_id,
        task_type=task_type,
        input_data=input_data,
    )
    enqueue_task(task_id)
    return jsonify({"task_id": task_id}), 202

@ops_api_bp.route('/api/tasks/<int:task_id>')
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
        "output_data": task["output_data"],
        "error_message": task["error_message"],
        "created_at": task["created_at"],
        "completed_at": task["completed_at"],
    })

# P3-13：审核端点（approve/reject/batch）已删除。
# 质量控制由抽检（safety-checks）与纠错（corrections）回路承担。

@ops_api_bp.route('/api/tasks', methods=['GET'])
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

@ops_api_bp.route('/api/tasks/<int:task_id>/correctables', methods=['GET'])
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

@ops_api_bp.route('/api/tasks/<int:task_id>/corrections', methods=['GET'])
@login_required
def api_task_corrections_list(task_id):
    """List all corrections for a task."""
    task = get_task(task_id)
    if not task:
        return jsonify({"error": "task not found"}), 404
    return jsonify(get_task_corrections(task_id))

@ops_api_bp.route('/api/tasks/<int:task_id>/corrections', methods=['POST'])
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

@ops_api_bp.route('/api/corrections/<int:correction_id>/revert', methods=['POST'])
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

@ops_api_bp.route('/api/corrections/stats', methods=['GET'])
@login_required
def api_corrections_stats():
    """Return correction statistics for dashboard."""
    days = request.args.get('days', 7, type=int)
    return jsonify(get_correction_stats(days=days))

@ops_api_bp.route('/api/safety-checks/pending', methods=['GET'])
@login_required
def api_safety_checks_pending():
    """List pending AIGC safety checks."""
    return jsonify(get_pending_safety_checks())

@ops_api_bp.route('/api/safety-checks/stats', methods=['GET'])
@login_required
def api_safety_checks_stats():
    """Return AIGC safety check statistics."""
    return jsonify(get_safety_check_stats())

@ops_api_bp.route('/api/safety-checks/<int:check_id>/review', methods=['POST'])
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

@ops_api_bp.route('/api/tasks/failure-stats', methods=['GET'])
@login_required
def api_task_failure_stats():
    """Return task failure/rejection statistics."""
    days = request.args.get('days', 7, type=int)
    return jsonify(get_task_failure_stats(days=days))

@ops_api_bp.route('/api/tasks/recent-failures', methods=['GET'])
@login_required
def api_recent_failed_tasks():
    """Return recent failed/rejected tasks with error messages."""
    limit = request.args.get('limit', 20, type=int)
    return jsonify(get_recent_failed_tasks(limit=limit))

@ops_api_bp.route('/api/alerts', methods=['GET'])
@login_required
def api_active_alerts():
    """Return active (non-dismissed) alerts."""
    return jsonify(get_active_alerts())

@ops_api_bp.route('/api/alerts/<int:alert_id>/dismiss', methods=['POST'])
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

@ops_api_bp.route('/api/cost/alerts', methods=['GET'])
@login_required
def api_cost_alerts():
    """Return cost alert status."""
    return jsonify(get_cost_alert_status())

@ops_api_bp.route('/api/admin/alert-settings', methods=['POST'])
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

@ops_api_bp.route('/api/audit-logs', methods=['GET'])
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

@ops_api_bp.route('/api/audit-logs/actions', methods=['GET'])
@login_required
def api_audit_log_actions():
    """Return distinct audit log actions for filter dropdown."""
    return jsonify(get_audit_log_actions())

@ops_api_bp.route('/api/backups', methods=['GET'])
@admin_required
def api_backups_list():
    """Return backup history."""
    return jsonify(get_backups())

@ops_api_bp.route('/api/backups/run', methods=['POST'])
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

@ops_api_bp.route('/api/backups/<int:backup_id>/download', methods=['GET'])
@admin_required
def api_backup_download(backup_id):
    """Download a backup file."""
    import backup as backup_module
    path = backup_module.get_backup_path(backup_id)
    if not path or not os.path.exists(path):
        return jsonify({"error": "backup not found"}), 404
    return send_file(path, as_attachment=True,
                     download_name=os.path.basename(path))

@ops_api_bp.route('/api/weekly', methods=['GET'])
@login_required
def api_weekly_list():
    week = request.args.get('week', get_week_start())
    if session.get('user_role') == 'admin':
        students = get_all_students()
    else:
        students = get_students_by_teacher(session['user_id'])
    from domain import cycle as cycle_mod
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
            # P2-11：链路视角 —— 周期状态机当前态 + 卡住标记
            "stage": wr.get("stage") or "created",
            "stage_label": cycle_mod.stage_label(wr.get("stage")),
            "stuck": cycle_mod.is_stuck(wr),
        })
    return jsonify(result)

@ops_api_bp.route('/api/compliance/students-without-consent', methods=['GET'])
@login_required
def api_students_without_consent():
    return jsonify(get_students_without_consent())

@ops_api_bp.route('/api/compliance/consents', methods=['POST'])
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

@ops_api_bp.route('/api/compliance/deletion-requests', methods=['GET'])
@login_required
def api_deletion_requests():
    return jsonify(get_pending_deletion_requests())

@ops_api_bp.route('/api/compliance/deletion-requests', methods=['POST'])
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

@ops_api_bp.route('/api/compliance/deletion-requests/<int:req_id>/process', methods=['POST'])
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

@ops_api_bp.route('/api/admin/users', methods=['GET'])
@admin_required
def api_admin_users_list():
    return jsonify(list_admin_users())

@ops_api_bp.route('/api/admin/users', methods=['POST'])
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

@ops_api_bp.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@admin_required
def api_admin_users_delete(user_id):
    # Don't allow deleting yourself
    if user_id == session.get('user_id'):
        return jsonify({"error": "不能删除当前登录的账号"}), 400
    deleted = delete_admin_user(user_id)
    if not deleted:
        return jsonify({"error": "账号不存在"}), 404
    return jsonify({"ok": True})

