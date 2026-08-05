# -*- coding: utf-8 -*-
"""P2 验收测试：家庭端入口合并 + 统一上传服务。

遵循 conftest 约定：db/domain 在测试函数内惰性导入。
"""

import io


def test_parent_page_renders_first_visit_mode(client):
    """/parent 渲染学情体检（首访模式），不再是死胡同跳转页。"""
    r = client.get("/parent")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "/api/parent/diagnose" in html
    assert "fileInput" in html


def test_student_route_removed(client, sample_student):
    """P3-13：/student 页已删除，学生端统一为 /s/<code>。"""
    with client.session_transaction() as sess:
        sess["user_id"] = sample_student
        sess["user_role"] = "student"
        sess["student_id"] = sample_student
    r = client.get("/student")
    assert r.status_code == 404


def test_public_upload_via_unified_service(client, sample_student, demo_mode,
                                           monkeypatch, tmp_path, test_db_path):
    """公开页上传走统一服务：202 + 扣额度 + 超额拒绝。"""
    import db
    from domain import upload as upload_mod

    monkeypatch.setattr(upload_mod, "UPLOAD_DIR", str(tmp_path / "uploads"))

    student = db.get_student(sample_student)
    code = student["access_code"]

    data = {"file": (io.BytesIO(b"\xff\xd8\xff\xd9"), "paper.jpg")}
    r = client.post(f"/api/public/{code}/upload", data=data,
                    content_type="multipart/form-data")
    assert r.status_code == 202
    body = r.get_json()
    assert body["task_id"] and body["file_ids"]

    # trial 注册即享 99 次/月，首次上传消耗 1 次
    has_quota, remaining = db.check_quota(sample_student, test_db_path)
    assert has_quota is True
    assert remaining == db.PRICING["trial"]["monthly_quota"] - 1

    # 第二次上传仍成功（额度充足）
    data2 = {"file": (io.BytesIO(b"\xff\xd8\xff\xd9"), "paper2.jpg")}
    r2 = client.post(f"/api/public/{code}/upload", data=data2,
                     content_type="multipart/form-data")
    assert r2.status_code == 202


def test_parent_diagnose_bootstrap_via_unified_service(client, demo_mode,
                                                       monkeypatch, tmp_path):
    """首访诊断：自动建档 + 统一上传服务 + 返回 access_code。"""
    from domain import upload as upload_mod

    monkeypatch.setattr(upload_mod, "UPLOAD_DIR", str(tmp_path / "uploads"))

    data = {
        "file": (io.BytesIO(b"\xff\xd8\xff\xd9"), "paper.jpg"),
        "grade": "高二",
    }
    r = client.post("/api/parent/diagnose", data=data,
                    content_type="multipart/form-data")
    assert r.status_code == 202
    body = r.get_json()
    assert body["task_id"] and body["access_code"]

    # 同 code 回访：走 weekly 链，再消耗 0 额度前需升级订阅 —— 这里只验证任务创建
    data2 = {
        "file": (io.BytesIO(b"\xff\xd8\xff\xd9"), "paper2.jpg"),
        "grade": "高二",
        "access_code": body["access_code"],
    }
    r2 = client.post("/api/parent/diagnose", data=data2,
                     content_type="multipart/form-data")
    # trial 有 99 次/月额度，回访第二次仍成功
    assert r2.status_code == 202


def test_master_mistake_public_access(client, test_db_path, sample_student):
    """成长记录'已掌握'：家庭端凭 access_code 公开操作（实测 401 修复）。"""
    import db
    mid = db.add_mistake(
        student_id=sample_student, source_exam="测试", question="q",
        question_type="语法填空", correct_answer="a", user_answer="b",
        db_path=test_db_path)
    code = db.get_student(sample_student)["access_code"]

    # 正确 access_code → 200
    r = client.post(f"/api/mistakes/{mid}/master", json={"access_code": code})
    assert r.status_code == 200
    # 错误 access_code → 403
    r = client.post(f"/api/mistakes/{mid}/master", json={"access_code": "WRONG"})
    assert r.status_code == 403
    # 无 access_code 且未登录 → 401
    r = client.post(f"/api/mistakes/{mid}/master", json={})
    assert r.status_code == 401
    # 错题不存在 → 404
    r = client.post("/api/mistakes/999999/master", json={"access_code": code})
    assert r.status_code == 404
