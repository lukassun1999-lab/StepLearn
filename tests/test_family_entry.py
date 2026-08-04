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

    # trial 额度 1 次被消耗
    has_quota, remaining = db.check_quota(sample_student, test_db_path)
    assert has_quota is False and remaining == 0

    # 第二次上传被额度闸门拒绝
    data2 = {"file": (io.BytesIO(b"\xff\xd8\xff\xd9"), "paper2.jpg")}
    r2 = client.post(f"/api/public/{code}/upload", data=data2,
                     content_type="multipart/form-data")
    assert r2.status_code == 429
    assert "额度" in r2.get_json()["error"]


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
    # trial 额度仅 1 次，第二次应被闸门拒绝
    assert r2.status_code == 429
