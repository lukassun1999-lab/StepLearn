# -*- coding: utf-8 -*-
"""页面冒烟测试：所有 HTML 入口可达且渲染正常。

P2-12 拆蓝图前建立的基线安全网：拆分前后本文件必须全绿。
"""


def _login_admin(client, admin_user):
    with client.session_transaction() as sess:
        sess["user_id"] = admin_user
        sess["user_role"] = "admin"
        sess["user_name"] = "admin"


def test_login_page(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert "密码" in r.get_data(as_text=True)


def test_index_requires_login(client):
    r = client.get("/")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_index_renders_admin_console(client, admin_user):
    _login_admin(client, admin_user)
    r = client.get("/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "学生" in html and "dashboard" in html.lower()


def test_register_pages(client):
    r = client.get("/register")
    assert r.status_code == 200
    assert "注册" in r.get_data(as_text=True)
    # 教师注册被 feature flag 关闭 → 404
    r2 = client.get("/teacher-register")
    assert r2.status_code == 404
    # 学生登录页重定向到统一登录
    r3 = client.get("/student-login")
    assert r3.status_code == 302


def test_student_page_renders_family_center(client, sample_student):
    import db

    student = db.get_student(sample_student)
    code = student["access_code"]
    r = client.get(f"/s/{code}")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    # 学习中心 9 tab 的关键标记
    assert "练习" in html and "报告" in html and "成长记录" in html

    r2 = client.get("/s/invalid-code-xyz")
    assert r2.status_code == 404


def test_parent_page_first_visit(client):
    r = client.get("/parent")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "/api/parent/diagnose" in html


def test_public_reports_endpoint(client, sample_student):
    """/api/public/<code>/reports 可访问（无报告时为空结构）。"""
    import db

    student = db.get_student(sample_student)
    code = student["access_code"]
    r = client.get(f"/api/public/{code}/reports")
    assert r.status_code == 200
