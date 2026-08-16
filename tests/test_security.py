# -*- coding: utf-8 -*-
"""安全加固回归测试（2026-08 第 1 周止血清单）。

覆盖：
- 学生登录态被 ops 端点拦截（staff_required）
- similar 端点反向鉴权修复（access_code 必填）
- /api/parent/task IDOR 修复（?code= 必填且归属匹配）
- 公开摘要字段白名单（不泄漏 phone/password_hash/家长联系方式）
- access_code 加密随机（不再 6 位数字）
- 上传类型白名单
"""


def _login(client, user_id, role, name="user"):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_role"] = role
        sess["user_name"] = name


def _login_student(client, student_id):
    # 与 api/family_api.py 学生登录写入的 session 字段一致
    with client.session_transaction() as sess:
        sess["user_id"] = student_id
        sess["user_role"] = "student"
        sess["student_id"] = student_id
        sess["user_name"] = "student"


# ── 学生登录态不能访问运营端 ────────────────────────

def test_student_session_blocked_from_ops_endpoints(client, sample_student):
    _login_student(client, sample_student)
    blocked = [
        "/api/dashboard", "/api/students", "/api/status",
        f"/api/students/{sample_student}",
        "/api/tasks", "/api/questions", "/api/weekly",
        "/api/audit-logs", "/api/subscriptions/" + str(sample_student),
        "/api/payments/" + str(sample_student),
    ]
    for path in blocked:
        r = client.get(path)
        assert r.status_code == 403, f"{path} 应拦截学生登录态，实际 {r.status_code}"
    # 状态变更类
    r = client.post("/api/subscriptions",
                    json={"student_id": sample_student, "plan": "unlimited"})
    assert r.status_code == 403
    r = client.post("/api/payments",
                    json={"student_id": sample_student, "plan": "monthly", "amount": 39})
    assert r.status_code == 403
    r = client.post("/api/pipeline/run",
                    json={"student_id": sample_student, "stage": "grade_only"})
    assert r.status_code == 403


def test_teacher_session_allowed_on_ops(client, teacher_user):
    _login(client, teacher_user, "teacher", "teacher1")
    r = client.get("/api/students")
    assert r.status_code == 200


def test_anonymous_blocked_from_ops(client):
    r = client.get("/api/students")
    assert r.status_code == 401


# ── similar 端点：access_code 必填 ──────────────────

def test_similar_requires_access_code(client, sample_student, test_db_path):
    import db
    mid = db.add_mistake(
        sample_student, question="I ___ to school yesterday.",
        user_answer="go", correct_answer="went",
        question_type="单项选择", db_path=test_db_path)
    # 不带 code → 401（原漏洞：if code 不传即放行）
    r = client.post(f"/api/mistakes/{mid}/similar", json={})
    assert r.status_code == 401
    # 错 code → 403
    r = client.post(f"/api/mistakes/{mid}/similar",
                    json={"access_code": "wrong-code"})
    assert r.status_code == 403
    r = client.get(f"/api/mistakes/{mid}/similar")
    assert r.status_code == 401


# ── 家长任务轮询 IDOR ───────────────────────────────

def test_parent_task_requires_matching_code(client, sample_student, test_db_path):
    import db
    task_id = db.create_task(sample_student, "diagnostic", {"stage": "grade_only"},
                             db_path=test_db_path)
    # 无 code → 401
    r = client.get(f"/api/parent/task/{task_id}")
    assert r.status_code == 401
    # 错 code → 403
    r = client.get(f"/api/parent/task/{task_id}?code=nope")
    assert r.status_code == 403


def test_parent_task_with_valid_code(client, sample_student, test_db_path):
    import db
    code = db.get_student(sample_student)["access_code"]
    task_id = db.create_task(sample_student, "diagnostic", {"stage": "grade_only"},
                             db_path=test_db_path)
    r = client.get(f"/api/parent/task/{task_id}?code={code}")
    assert r.status_code == 200


# ── 公开摘要字段白名单 ──────────────────────────────

def test_public_summary_does_not_leak_pii(client, test_db_path):
    import db
    sid = db.create_student({
        "name": "白名单", "grade": "高二",
        "parent_phone": "13800000000", "parent_wechat": "wxid_secret",
        "parent_name": "家长", "notes": "内部备注",
    }, db_path=test_db_path)
    conn = db.get_connection(test_db_path)
    conn.execute("UPDATE students SET phone = ? WHERE id = ?",
                 ["13900000000", sid])
    conn.commit()
    conn.close()
    code = db.get_student(sid)["access_code"]
    r = client.get(f"/api/public/{code}")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    for secret in ("13800000000", "13900000000", "wxid_secret", "password_hash",
                   "内部备注"):
        assert secret not in body, f"公开接口泄漏了 {secret}"


# ── access_code 加密随机 ────────────────────────────

def test_new_access_codes_are_crypto_random(test_db_path):
    import db
    sid = db.create_student({"name": "随机码"}, db_path=test_db_path)
    s = db.get_student(sid)
    # token_urlsafe(8) ≈ 11 位、含字母；不再纯 6 位数字
    assert len(s["access_code"]) >= 10
    assert not s["access_code"].isdigit()


# ── 上传类型白名单 ──────────────────────────────────

def test_upload_rejects_html_file(client, sample_student, test_db_path):
    from io import BytesIO
    code = None
    import db
    code = db.get_student(sample_student)["access_code"]
    data = {"file": (BytesIO(b"<script>alert(1)</script>"), "evil.html")}
    r = client.post(f"/api/public/{code}/upload", data=data,
                    content_type="multipart/form-data")
    assert r.status_code in (400, 413, 422), r.get_data(as_text=True)
