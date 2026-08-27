#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""页面路由蓝图：运营后台 + 登录注册 + 家庭端页面（P2-12 自 app.py 拆出）。"""

from flask import (Blueprint, make_response, redirect,
                   render_template_string, request, session)
from werkzeug.security import check_password_hash

from db import *  # noqa: F401,F403
from web.shared import VERSION, _resolve_student_by_code, login_required
from web.templates_admin import MAIN_PAGE
from web.templates_auth import LOGIN_PAGE, STUDENT_REGISTER_PAGE
from web.templates_family import PARENT_PAGE, STUDENT_PAGE

pages_bp = Blueprint("pages", __name__)


@pages_bp.route('/login', methods=['GET', 'POST'])
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

@pages_bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect('/login')

@pages_bp.route('/student-login')
def student_login_page():
    return redirect('/login')

@pages_bp.route('/register')
def register_page():
    return render_template_string(STUDENT_REGISTER_PAGE,
        feature_school=is_feature_enabled('feature_school_enabled'))


# P3-13：/student 页已删除。学生端并入家庭端，登录/注册后直接进 /s/<code>。

@pages_bp.route('/')
@login_required
def index():
    return render_template_string(MAIN_PAGE,
        user_role=session.get('user_role'),
        user_name=session.get('user_name', ''),
        user_subject=session.get('user_subject', ''),
        feature_school=is_feature_enabled('feature_school_enabled'),
        feature_teacher=is_feature_enabled('feature_teacher_enabled'))


@pages_bp.route('/s/<code>')
def student_view(code):
    """Public student view — no login required."""
    _, err = _resolve_student_by_code(code)
    if err:
        return '<h2 style="text-align:center;margin-top:80px;">链接无效或已过期</h2>', 404
    resp = make_response(render_template_string(STUDENT_PAGE, code=code, version=VERSION))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return resp

@pages_bp.route('/parent')
def parent_view():
    """家庭端统一入口（P2-9）：首访模式 = AI 学情体检（PARENT_PAGE）。

    - 首访家长：拍照 → 自动建档 → 诊断 → 获得 access_code
    - 回访家长（localStorage 有有效 code）：页面 JS 直接跳转 /s/<code> 学习中心
    """
    resp = make_response(render_template_string(PARENT_PAGE, version=VERSION))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return resp

