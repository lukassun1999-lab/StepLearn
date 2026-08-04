#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B 端封存层：学校/班级/教师机构相关路由（P3-15 自 ops_api/pages 隔离）。

这些路由全部受 feature flag 守卫（feature_school_enabled /
feature_teacher_enabled，默认关闭）。C 端最小闭环模式下整体不可见；
恢复方式见 FEATURE_FLAGS.md（打开 flag 即生效，无需改代码）。
"""

import os

from flask import (Blueprint, jsonify, render_template_string, request,
                   send_from_directory, session)
from werkzeug.security import generate_password_hash

from db import *  # noqa: F401,F403
from web.shared import (UPLOAD_DIR, admin_required, feature_required,
                        login_required)
from web.templates_auth import TEACHER_REGISTER_PAGE

b_end_bp = Blueprint("b_end", __name__)

@b_end_bp.route('/api/schools/search')
@feature_required('feature_school_enabled')
def api_schools_search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    return jsonify(search_schools(q))


@b_end_bp.route('/api/classes')
@feature_required('feature_school_enabled')
def api_classes_by_school():
    school_id = request.args.get('school_id', type=int)
    if not school_id:
        return jsonify({"error": "school_id required"}), 400
    return jsonify(get_classes_by_school(school_id))


@b_end_bp.route('/api/class/verify-code', methods=['POST'])
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


@b_end_bp.route('/api/teacher-register', methods=['POST'])
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


@b_end_bp.route('/api/my-classes')
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


@b_end_bp.route('/api/class/<int:class_id>/stats')
@feature_required('feature_school_enabled')
@login_required
def api_class_stats(class_id):
    return jsonify(get_class_stats(class_id))


@b_end_bp.route('/api/class/<int:class_id>/students')
@feature_required('feature_school_enabled')
@login_required
def api_class_students(class_id):
    return jsonify(get_students_by_class(class_id))


@b_end_bp.route('/api/schools', methods=['GET', 'POST'])
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


@b_end_bp.route('/api/schools/<int:school_id>', methods=['PUT', 'DELETE'])
@feature_required('feature_school_enabled')
@admin_required
def api_school_detail(school_id):
    if request.method == 'DELETE':
        delete_school(school_id)
        return jsonify({"ok": True})
    data = request.get_json(force=True)
    update_school(school_id, data)
    return jsonify({"ok": True})


@b_end_bp.route('/api/admin/classes', methods=['GET', 'POST'])
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


@b_end_bp.route('/api/admin/classes/<int:class_id>', methods=['PUT', 'DELETE'])
@feature_required('feature_school_enabled')
@admin_required
def api_admin_class_detail(class_id):
    if request.method == 'DELETE':
        delete_class(class_id)
        return jsonify({"ok": True})
    data = request.get_json(force=True)
    update_class(class_id, data)
    return jsonify({"ok": True})


@b_end_bp.route('/api/teacher/create-class', methods=['POST'])
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


@b_end_bp.route('/api/teacher/my-school')
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


@b_end_bp.route('/api/teacher-profile', methods=['GET'])
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


@b_end_bp.route('/api/teacher-profile', methods=['POST'])
@feature_required('feature_teacher_enabled')
@login_required
def api_teacher_profile_save():
    data = request.get_json() or {}
    save_teacher_profile(session['user_id'], data)
    return jsonify({"ok": True})


@b_end_bp.route('/api/teacher-profile/avatar', methods=['POST'])
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


@b_end_bp.route('/teacher-register')
@feature_required('feature_teacher_enabled')
def teacher_register_page():
    return render_template_string(TEACHER_REGISTER_PAGE)


@b_end_bp.route('/uploads/teacher/<path:filename>')
@feature_required('feature_teacher_enabled')
def teacher_uploads(filename):
    return send_from_directory(os.path.join(UPLOAD_DIR, 'teacher'), filename)
