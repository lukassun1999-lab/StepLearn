#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""家庭端 API 蓝图：学生/家长/公开页（P2-12 自 app.py 拆出）。"""

import json
import os
import uuid
from datetime import date

from flask import Blueprint, jsonify, request, send_file, session
from werkzeug.security import check_password_hash, generate_password_hash

from db import *  # noqa: F401,F403
from domain.grading import is_answer_correct
from web.shared import (UPLOAD_DIR, _extract_options, _resolve_file_path,
                        _resolve_student_by_code, admin_required,
                        login_required)

family_api_bp = Blueprint("family_api", __name__)

# 家长端免登录可下载的文件类型白名单（防枚举：仅 AI 产出的可见成果）
_PUBLIC_DOWNLOAD_TYPES = ("poster", "report_pdf", "exercise_pdf", "essay_review")


_VALID_GRADES = {"初一", "初二", "初三", "高一", "高二", "高三"}
_VALID_TEXTBOOKS = {"人教版", "外研社版", "北师大版", "暂不确定"}


@family_api_bp.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json(force=True)
    phone = (data.get('phone') or '').strip()
    password = data.get('password') or ''
    name = (data.get('name') or '').strip()
    class_code = (data.get('class_code') or '').strip()
    grade = (data.get('grade') or '').strip()
    textbook_version = (data.get('textbook_version') or '').strip()

    if not phone or not password or not name:
        return jsonify({"error": "手机号、密码和姓名为必填项"}), 400
    if len(phone) != 11 or not phone.isdigit():
        return jsonify({"error": "请输入11位手机号"}), 400
    if len(password) < 6:
        return jsonify({"error": "密码至少6位"}), 400
    if grade not in _VALID_GRADES:
        return jsonify({"error": "请选择年级"}), 400
    if textbook_version not in _VALID_TEXTBOOKS:
        return jsonify({"error": "请选择教材版本"}), 400

    school_id = None
    class_id = None
    cls = None
    if class_code:
        cls = get_class_by_code(class_code)
        if not cls:
            return jsonify({"error": "班级码无效，请检查后重试"}), 404
        school_id = cls["school_id"]
        class_id = cls["id"]
        # 学校场景下年级以班级为准，避免与班级信息冲突
        if cls.get("grade"):
            grade = cls["grade"]

    try:
        student_id = register_student(
            phone=phone,
            password_hash=generate_password_hash(password),
            name=name,
            school_id=school_id,
            class_id=class_id,
            grade=grade,
            textbook_version=textbook_version,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 409

    session['user_id'] = student_id
    session['user_name'] = name
    session['user_role'] = 'student'
    session['student_id'] = student_id
    log_audit(session.get('user_id'), 'student_register', f"学生注册: {name} ({phone})",
              details=f"class_id={cls['id'] if cls else None}")
    # P2-9：注册后直接进入家庭端学习中心
    new_student = get_student(student_id)
    access_code = (new_student or {}).get('access_code') or ''
    return jsonify({"ok": True, "student_id": student_id,
                    "redirect": "/s/" + access_code if access_code else "/student"})

@family_api_bp.route('/api/student-login', methods=['POST'])
def api_student_login():
    data = request.get_json(force=True)
    account = (data.get('account') or data.get('phone') or '').strip()
    password = data.get('password') or ''

    if not account or not password:
        return jsonify({"error": "请输入账号和密码"}), 400

    # Try phone first, then name, then access_code
    student = get_student_by_phone(account)
    if not student:
        conn = get_connection()
        student = conn.execute(
            "SELECT * FROM students WHERE name = ? AND status = 'active' AND password_hash IS NOT NULL",
            [account]
        ).fetchone()
        if not student:
            student = conn.execute(
                "SELECT * FROM students WHERE access_code = ? AND status = 'active' AND password_hash IS NOT NULL",
                [account]
            ).fetchone()
        conn.close()
        if student:
            student = dict(student)

    if not student or not student.get('password_hash'):
        return jsonify({"error": "账号或密码错误"}), 401
    if not check_password_hash(student['password_hash'], password):
        return jsonify({"error": "账号或密码错误"}), 401

    session['user_id'] = student['id']
    session['user_name'] = student['name']
    session['user_role'] = 'student'
    session['student_id'] = student['id']
    return jsonify({"ok": True, "redirect": "/s/" + (student.get('access_code') or '')})

@family_api_bp.route('/api/sms/send-code', methods=['POST'])
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

    try:
        send_verification_code(phone, purpose)
    except ValueError as e:
        return jsonify({"error": str(e)}), 429
    return jsonify({"ok": True, "message": "验证码已发送"})

@family_api_bp.route('/api/sms/login', methods=['POST'])
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
        return jsonify({"ok": True, "redirect": "/s/" + (student.get('access_code') or '')})

    return jsonify({"error": "该手机号未注册"}), 404

@family_api_bp.route('/api/sms/reset-password', methods=['POST'])
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

# P3-13：session 态学生端点（/api/student/me|reports|upload|progress）已删除。
# 学生端并入家庭端后，统一走 code 作用域的 /api/public/<code>/* 端点。

@family_api_bp.route('/api/public/<code>/achievements', methods=['GET'])
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

@family_api_bp.route('/api/public/<code>/review', methods=['GET'])
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

@family_api_bp.route('/api/public/<code>/review', methods=['POST'])
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

@family_api_bp.route('/api/public/<code>/timeline', methods=['GET'])
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

@family_api_bp.route('/api/public/<code>', methods=['GET'])
def api_public_summary(code):
    """Public summary for student page."""
    summary = get_student_public_summary(code)
    if not summary:
        return jsonify({"error": "invalid or expired code"}), 404
    summary["teacher"] = {}  # per-teacher profiles not exposed on public page
    return jsonify(summary)

@family_api_bp.route('/api/public/<code>/practice', methods=['GET'])
def api_public_practice(code):
    """Get interactive practice questions for a student (public, no login).

    P3-14：取题逻辑收拢至 domain/questions.py。
    """
    student_id, err = _resolve_student_by_code(code)
    if err:
        return err

    from domain import questions as q_mod
    rows = q_mod.get_practice_questions(student_id, limit=15)

    questions = []
    for q in rows:
        questions.append({
            "id": q["id"],
            "question_text": q["question_text"],
            "question_type": q["question_type"] or "选择题",
            "options": _extract_options(q["question_text"]),
            "knowledge_points": q["knowledge_points"],
            "difficulty": q["difficulty"],
            "source_mistake_id": q["source_mistake_id"],
        })

    return jsonify({"questions": questions, "total": len(questions)})

@family_api_bp.route('/api/public/<code>/practice/submit', methods=['POST'])
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
    # 题型含「多选」→ 字母集合比较（顺序无关）；否则自动识别 A-F 组合
    multiselect = "多选" in (q["question_type"] or "")
    is_correct = is_answer_correct(student_answer, correct_answer, multiselect)

    # Update mastery via record_practice — but only when the source mistake
    # actually belongs to THIS student. Bank-reused questions may carry a
    # source_mistake_id pointing at another student's mistake; recording
    # against it would corrupt that student's mastery data.
    #
    # 防刷（P0-4）：每题每天只计首次提交——答错后接口会返回正确答案，
    # 若每次提交都计分，马上重交一次即可刷「连续答对」。当日后续提交
    # 只返回反馈不改掌握度；隔天可再计分（兼容 ≥1 天的间隔复习节奏）。
    source_mistake_id = q["source_mistake_id"]
    mastery_info = None  # 本次提交计入掌握度且答对 → 前端即时攻克反馈
    if source_mistake_id:
        conn = get_connection()
        owner = conn.execute(
            "SELECT student_id FROM mistakes WHERE id = ?", [source_mistake_id]
        ).fetchone()
        if owner and owner["student_id"] == student_id:
            too_soon = conn.execute("""
                SELECT 1 FROM practice_records
                WHERE mistake_id = ? AND created_at > datetime('now', '-30 seconds')
                LIMIT 1
            """, [source_mistake_id]).fetchone()
            counted_today = conn.execute("""
                SELECT 1 FROM practice_records
                WHERE mistake_id = ? AND date(created_at, 'localtime') = date('now', 'localtime')
                LIMIT 1
            """, [source_mistake_id]).fetchone()
            if not too_soon and not counted_today:
                record_practice(
                    mistake_id=source_mistake_id,
                    user_answer=student_answer,
                    is_correct=is_correct,
                    feedback=q["explanation"] or "",
                )
                if is_correct:
                    # 攻克 = 连续答对达 2 次（与错题本徽标/统计同口径）。
                    # 即时庆祝是练习激励回路的核心：学生当场知道"这道题拿下了"。
                    row = conn.execute(
                        "SELECT consecutive_correct FROM mistakes WHERE id = ?",
                        [source_mistake_id]).fetchone()
                    new_cc = (row["consecutive_correct"] or 0) if row else 0
                    mastered_total = conn.execute("""
                        SELECT COUNT(*) AS c FROM mistakes
                        WHERE student_id = ? AND consecutive_correct >= 2
                    """, [student_id]).fetchone()["c"]
                    mastery_info = {"just_mastered": new_cc >= 2,
                                    "mastered_count": mastered_total}
        conn.close()

    resp = {
        "is_correct": is_correct,
        "correct_answer": correct_answer,
        "explanation": q["explanation"] or "",
        "knowledge_points": json.loads(q["knowledge_points"]) if isinstance(q["knowledge_points"], str) else q["knowledge_points"],
    }
    if mastery_info:
        resp["mastery"] = mastery_info
    return jsonify(resp)

@family_api_bp.route('/api/public/<code>/mistake-books', methods=['GET'])
def api_public_mistake_books(code):
    """按分析日期分组的错题本：如「20260804错题本」。

    每次试卷分析入库的错题按 created_at 的日期分组（倒序，最新在前），
    每组含该次全部错题的题目/学生作答/正确答案/解析，供学生先看后练。
    """
    student_id, err = _resolve_student_by_code(code)
    if err:
        return err
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM mistakes WHERE student_id = ?
        ORDER BY created_at DESC, id ASC
    """, [student_id]).fetchall()
    conn.close()

    books = []
    current = None
    for r in rows:
        d = dict(r)
        day = (d.get("created_at") or "")[:10].replace("-", "")  # 2026-08-04 → 20260804
        if not current or current["date"] != day:
            current = {"date": day, "label": f"{day}错题本",
                       "count": 0, "mistakes": []}
            books.append(current)
        try:
            d["knowledge_points"] = json.loads(d.get("knowledge_points") or "[]")
        except Exception:
            d["knowledge_points"] = []
        d["is_mastered"] = d.get("consecutive_correct", 0) >= 2
        current["mistakes"].append(d)
        current["count"] += 1
    return jsonify({"books": books, "total": sum(b["count"] for b in books)})


@family_api_bp.route('/api/public/<code>/files/<int:file_id>/download', methods=['GET'])
def api_public_file_download(code, file_id):
    """免登录下载家长端可见产物（海报/报告/练习卷），校验归属学生与类型白名单。

    运营端下载仍走 /api/files/<id>/download（login_required）；
    家长端（免登录）用本路由，防止任意文件被枚举。
    """
    student_id, err = _resolve_student_by_code(code)
    if err:
        return err
    f = get_file(file_id)
    if not f or f["student_id"] != student_id \
            or f["file_type"] not in _PUBLIC_DOWNLOAD_TYPES:
        return ('', 404)
    filepath = _resolve_file_path(f)
    if not filepath:
        return ('', 404)
    return send_file(filepath, download_name=f["original_filename"])


@family_api_bp.route('/api/public/<code>/exercise-pdf', methods=['GET'])
def api_public_exercise_pdf(code):
    """Download practice exercises as a print-friendly PDF."""
    student_id, err = _resolve_student_by_code(code)
    if err:
        return err

    student = get_student(student_id)
    if not student:
        return jsonify({"error": "student not found"}), 404

    # P3-14：取题逻辑收拢至 domain/questions.py（与练习 tab 同源）
    from domain import questions as q_mod
    rows = q_mod.get_practice_questions(student_id, limit=15)

    if not rows:
        return jsonify({"error": "暂无练习题，请先上传试卷"}), 404

    questions = []
    for q in rows:
        questions.append({
            "question_text": q["question_text"],
            "question_type": q["question_type"] or "选择题",
            "options": _extract_options(q["question_text"]),
            "knowledge_points": q["knowledge_points"],
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

@family_api_bp.route('/api/public/<code>/upload', methods=['POST'])
def api_public_upload(code):
    """Parent uploads test paper photo from public page. Auto-triggers pipeline.

    P2-10：接入统一上传服务 domain/upload.py（存文件+闸门+触发单一实现）。
    """
    student_id, err = _resolve_student_by_code(code)
    if err:
        return err

    if 'file' not in request.files:
        return jsonify({"error": "no file uploaded"}), 400
    files = request.files.getlist('file')
    if not files:
        return jsonify({"error": "no file uploaded"}), 400

    from domain import upload as upload_mod
    try:
        task_id, file_ids = upload_mod.family_upload(
            student_id, files, uploader_role="parent",
            task_type="weekly", stage="grade_only")
    except upload_mod.UploadError as e:
        return jsonify({"error": e.message}), e.status

    return jsonify({"task_id": task_id, "file_ids": file_ids, "message": "试卷已上传，AI正在分析中"}), 202

@family_api_bp.route('/api/public/<code>/task/<int:task_id>', methods=['GET'])
def api_public_task_status(code, task_id):
    """Public task progress polling (validated by access_code).

    P1：grade_only 现在一次任务跑完分析主链（错题+方案+报告+练习），
    不再有「缝合的第二个任务」，轮询直接返回本任务状态。
    """
    student_id, err = _resolve_student_by_code(code)
    if err:
        return err

    task = get_task(task_id)
    if not task or task["student_id"] != student_id:
        return jsonify({"error": "task not found"}), 404

    output = task.get("output_data")
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except Exception:
            output = None

    return jsonify({
        "id": task["id"],
        "status": task["status"],
        "current_step": task.get("current_step", ""),
        "progress": task.get("progress", 0),
        "error_message": task.get("error_message"),
        "output_data": output,
    })

@family_api_bp.route('/api/referrals/my/<code>', methods=['GET'])
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

@family_api_bp.route('/api/referrals/validate/<invite_code>', methods=['GET'])
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

@family_api_bp.route('/api/referrals/stats', methods=['GET'])
@login_required
def api_referral_stats():
    return jsonify(get_referral_stats())

@family_api_bp.route('/api/referrals/settings', methods=['POST'])
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

@family_api_bp.route('/api/poster/<code>', methods=['GET'])
def api_generate_poster(code):
    """Generate shareable poster HTML for a student."""
    summary = get_student_public_summary(code)
    if not summary:
        return jsonify({"error": "invalid code"}), 404

    # 无学习数据不生成海报（新学生：无错题/无打卡）
    if (summary["mistakes_count"] or 0) + (summary["mastered_count"] or 0) \
            + len(summary["check_ins"] or []) == 0:
        return jsonify({"error": "暂无学习数据，先上传试卷或完成练习后再生成海报吧"}), 400

    from report_templates import render_share_poster
    poster_html = render_share_poster(summary["student"], {
        "current_score": summary["student"].get("english_score"),
        "target_score": summary["student"].get("target_score"),
        "mastered_count": summary["mastered_count"],
        "mistakes_count": summary["mistakes_count"],
        "check_in_count": len(summary["check_ins"]),
        "scores": summary.get("scores") or [],
    })

    # Save as file（目录与 file_type 一致：poster；历史 posters 目录由 _resolve_file_path 兼容）
    poster_dir = os.path.join(UPLOAD_DIR, str(summary["student"]["id"]), "poster")
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
    # html 随接口返回，前端用 iframe srcdoc 内嵌预览（附件下载头/登录态不影响预览）
    return jsonify({"file_id": file_id, "path": filepath, "html": poster_html})

@family_api_bp.route('/api/parent/diagnose', methods=['POST'])
def api_parent_diagnose():
    """Parent uploads test paper → trigger diagnosis pipeline."""
    if 'file' not in request.files:
        return jsonify({"error": "请选择试卷照片"}), 400

    # 多页试卷支持：接收多张照片（多图时第一张必须有文件名）
    files = [f for f in request.files.getlist('file') if f and f.filename]
    if not files:
        return jsonify({"error": "请选择试卷照片"}), 400

    grade = (request.form.get('grade') or '').strip() or '高二'
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

    # P2-10：统一上传服务（存文件 → 额度闸门 → 建任务）。
    # 新用户建档时已自动获得 trial 订阅 1 次额度，闸门在此统一执行。
    from domain import upload as upload_mod
    task_type = "weekly" if existing_code else "onboarding"
    try:
        task_id, _file_ids = upload_mod.family_upload(
            sid, files, uploader_role="parent",
            task_type=task_type, stage="full",
            extra_input={"grade": grade, "subject": "英语"})
    except upload_mod.UploadError as e:
        return jsonify({"error": e.message}), e.status

    return jsonify({
        "task_id": task_id,
        "access_code": access_code,
        "message": "诊断已开始",
    }), 202

@family_api_bp.route('/api/parent/task/<int:task_id>')
def api_parent_task(task_id):
    """Poll task status for parent diagnosis.

    凭自增 task_id 即可读任意学生诊断结果的 IDOR 已修：必须携带
    ?code=<access_code> 且与任务归属学生匹配。
    """
    task = get_task(task_id)
    if not task:
        return jsonify({"error": "task not found"}), 404

    code = (request.args.get("code") or "").strip()
    if not code:
        return jsonify({"error": "missing code"}), 401
    student_id, err = _resolve_student_by_code(code)
    if err or student_id != task.get("student_id"):
        return jsonify({"error": "forbidden"}), 403

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

@family_api_bp.route('/api/parent/progress/<code>')
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
            "report_file_id": out.get("report_file_id")
                or out.get("weekly_report_file_id")
                or out.get("feedback_file_id"),
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

@family_api_bp.route('/api/public/<code>/reports', methods=['GET'])
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
        SELECT output_data, created_at, task_type
        FROM ai_tasks
        WHERE student_id = ? AND task_type IN ('onboarding', 'weekly')
          AND status = 'done' AND needs_review = 0
        ORDER BY created_at DESC LIMIT 10
    """, [student["id"]]).fetchall()
    conn.close()

    # Each pipeline stage stores its downloadable artifact under a different key
    _REPORT_KINDS = [
        ("report_file_id", "学情分析报告"),
        ("weekly_report_file_id", "家长周报"),
        ("feedback_file_id", "练习批改反馈"),
        ("essay_review_file_id", "作文批改"),
    ]
    _STAGE_TITLES = {
        "weekly_book_done": "周错题本",
        "monthly_done": "月度总结报告",
    }
    reports = []
    for t in tasks:
        try:
            out = json.loads(t["output_data"]) if t["output_data"] else {}
            stage = out.get("stage", "")
            title = _STAGE_TITLES.get(stage)
            if not title:
                for key, label in _REPORT_KINDS:
                    if out.get(key):
                        title = label
                        break
            if title and (out.get("report_file_id") or out.get("weekly_report_file_id")
                          or out.get("feedback_file_id") or out.get("essay_review_file_id")):
                # 空壳过滤：定时任务在学生无数据时生成的周错题本/月度总结是
                # 0 错题占位文档，对家长无信息量且易被误读为"报告为空"，不展示
                if (out.get("mistakes_count", 0) == 0
                        and stage in ("weekly_book_done", "monthly_done")):
                    continue
                fid = (out.get("report_file_id") or out.get("weekly_report_file_id")
                       or out.get("feedback_file_id") or out.get("essay_review_file_id"))
                reports.append({
                    "report_file_id": fid,
                    "title": title,
                    "mistakes_count": out.get("mistakes_count", "—"),
                    "weak_points_count": out.get("weak_points_count", "—"),
                    "created_at": t["created_at"],
                })
        except Exception:
            pass
    return jsonify(reports)

@family_api_bp.route('/api/public/<code>/request-deletion', methods=['POST'])
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

