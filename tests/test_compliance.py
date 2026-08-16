import pytest


def login_client(client, user_id, role="admin", name="admin"):
    """Helper to set session for a logged-in user."""
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_role"] = role
        sess["user_name"] = name


def test_record_consent_and_reflected_in_student(client, sample_student, admin_user, test_db_path):
    login_client(client, admin_user, "admin")

    r = client.post("/api/compliance/consents", json={
        "student_id": sample_student,
        "consented_by": "张家长",
        "contact": "13800138000",
        "notes": "已签署纸质授权书",
    })
    assert r.status_code == 200
    data = r.get_json()
    assert data["success"] is True
    assert "id" in data

    # Direct DB check
    import db
    assert db.has_parent_consent(sample_student, db_path=test_db_path) is True

    # Student detail should reflect consent
    r2 = client.get(f"/api/students/{sample_student}")
    assert r2.status_code == 200
    assert r2.get_json()["has_consent"] is True

    # Student list should reflect consent
    r3 = client.get("/api/students")
    students = r3.get_json()
    assert any(s["id"] == sample_student and s["has_consent"] for s in students)


def test_consent_requires_fields(client, sample_student, admin_user):
    login_client(client, admin_user, "admin")

    r = client.post("/api/compliance/consents", json={
        "student_id": sample_student,
    })
    assert r.status_code == 400


def test_create_and_process_deletion_request(client, sample_student, admin_user, test_db_path):
    login_client(client, admin_user, "admin")

    r = client.post("/api/compliance/deletion-requests", json={
        "student_id": sample_student,
        "reason": "家长申请删除",
    })
    assert r.status_code == 200
    req_id = r.get_json()["id"]

    # Pending list contains the request
    r2 = client.get("/api/compliance/deletion-requests")
    pending = r2.get_json()
    assert any(x["id"] == req_id for x in pending)

    # Process the request
    r3 = client.post(f"/api/compliance/deletion-requests/{req_id}/process")
    assert r3.status_code == 200

    # Student should be soft-deleted
    import db
    student = db.get_student(sample_student, db_path=test_db_path)
    assert student["status"] == "deleted"
    assert student["access_code"] is None


def test_process_deletion_requires_admin(client, sample_student, admin_user, teacher_user):
    login_client(client, admin_user, "admin")
    r = client.post("/api/compliance/deletion-requests", json={
        "student_id": sample_student,
        "reason": "test",
    })
    req_id = r.get_json()["id"]

    # Teacher cannot process
    login_client(client, teacher_user, "teacher")
    r2 = client.post(f"/api/compliance/deletion-requests/{req_id}/process")
    assert r2.status_code == 403


def test_public_request_deletion(client, sample_student, test_db_path):
    import db
    student = db.get_student(sample_student, db_path=test_db_path)
    code = student["access_code"]

    r = client.post(f"/api/public/{code}/request-deletion", json={
        "reason": "测试删除",
        "requested_by": "家长",
    })
    assert r.status_code == 200
    data = r.get_json()
    assert data["success"] is True

    # A pending request should exist
    pending = db.get_pending_deletion_requests(db_path=test_db_path)
    assert any("测试删除" in (x.get("reason") or "") for x in pending)


def test_public_request_deletion_invalid_code(client):
    r = client.post("/api/public/invalid-code/request-deletion", json={"reason": "test"})
    assert r.status_code == 404


def test_dashboard_stats_include_compliance(client, sample_student, admin_user):
    login_client(client, admin_user, "admin")

    # Baseline counts before creating a deletion request
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    before = r.get_json()
    assert "students_without_consent" in before
    before_deletions = before["pending_deletions"]

    # After requesting deletion, pending_deletions should increase by 1
    client.post("/api/compliance/deletion-requests", json={
        "student_id": sample_student,
        "reason": "test stats",
    })
    r2 = client.get("/api/dashboard")
    after = r2.get_json()
    assert after["pending_deletions"] == before_deletions + 1
    assert after["students_without_consent"] >= before["students_without_consent"]


# ═════════════════════════════════════════════════════
# 2026-08 第 2 周提交 2：级联硬删 + 同意版本化/撤回 + 门禁
# ═════════════════════════════════════════════════════

import io
import os


def _build_full_graph(test_db_path, student_id):
    """为一名学生建立覆盖全部从属表的数据图，返回关键 id。"""
    import db
    p = dict(db_path=test_db_path)

    mid = db.add_mistake(student_id, question="q1", correct_answer="A",
                         source_exam="e", **p)
    conn = db.get_connection(test_db_path)
    conn.execute(
        "INSERT INTO questions (question_text, question_type, correct_answer, "
        "enabled, source_mistake_id) VALUES ('q1', '选择', 'A', 1, ?)", [mid])
    qid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO practice_records (mistake_id, user_answer, is_correct) "
        "VALUES (?, 'A', 1)", [mid])
    conn.execute(
        "INSERT INTO practice_sessions (student_id, exam_name, source_task_id) "
        "VALUES (?, 'e', NULL)", [student_id])
    tid = conn.execute(
        "INSERT INTO ai_tasks (student_id, task_type, input_data, week_start) "
        "VALUES (?, 'weekly', '{}', '2026-08-10')", [student_id]
    ).lastrowid
    conn.execute(
        "INSERT INTO llm_usage_log (task_id, call_type) VALUES (?, 'ocr')", [tid])
    conn.execute(
        "INSERT INTO aigc_safety_checks (task_id, content_type) VALUES (?, 'mistake')", [tid])
    conn.execute(
        "INSERT INTO ai_corrections (task_id, student_id, content_type, target_field, corrected_value) "
        "VALUES (?, ?, 'mistake', 'question', 'fixed')", [tid, student_id])
    conn.execute("INSERT INTO files (student_id, uploader_role, file_type, filename, original_filename) "
                 "VALUES (?, 'parent', 'test_paper', 'x.jpg', 'x.jpg')", [student_id])
    conn.execute("INSERT INTO weekly_records (student_id, week_start, kind) "
                 "VALUES (?, '2026-08-10', 'weekly')", [student_id])
    conn.execute("INSERT INTO score_history (student_id, score, week_start) "
                 "VALUES (?, 90, '2026-08-10')", [student_id])
    conn.execute("INSERT INTO audit_logs (actor_type, actor_id, action, target_type, target_id) "
                 "VALUES ('teacher', ?, 'view', 'student', ?)", [str(student_id), str(student_id)])
    conn.commit()
    conn.close()

    from datetime import date as _date
    db.save_subscription({"student_id": student_id, "plan": "monthly",
                          "status": "active",
                          "start_date": _date.today().isoformat()}, **p)
    db.record_payment(student_id, plan="monthly", amount=39, note="t", **p)
    db.record_parent_consent(student_id, consented_by="测试家长", **p)
    return mid, qid, tid


def _count(test_db_path, sql, params=()):
    import db
    conn = db.get_connection(test_db_path)
    n = conn.execute(sql, params).fetchone()[0]
    conn.close()
    return n


def test_deletion_cascade_hard_deletes_everything(sample_student, test_db_path):
    import db
    sid = sample_student
    mid, qid, tid = _build_full_graph(test_db_path, sid)

    # 磁盘上传目录（模拟一份已上传文件）
    from domain.upload import UPLOAD_DIR
    sdir = os.path.join(UPLOAD_DIR, str(sid), "test_paper")
    os.makedirs(sdir, exist_ok=True)
    disk_file = os.path.join(sdir, "photo.jpg")
    with open(disk_file, "wb") as f:
        f.write(b"\xff\xd8\xff\xd9")

    req_id = db.request_data_deletion(sid, requested_by="家长", reason="注销", db_path=test_db_path)
    assert db.process_data_deletion(req_id, db_path=test_db_path) is True

    # 从属数据全部清空
    assert _count(test_db_path, "SELECT COUNT(*) FROM mistakes WHERE student_id=?", (sid,)) == 0
    assert _count(test_db_path, "SELECT COUNT(*) FROM practice_sessions WHERE student_id=?", (sid,)) == 0
    assert _count(test_db_path, "SELECT COUNT(*) FROM ai_tasks WHERE student_id=?", (sid,)) == 0
    assert _count(test_db_path, "SELECT COUNT(*) FROM llm_usage_log WHERE task_id=?", (tid,)) == 0
    assert _count(test_db_path, "SELECT COUNT(*) FROM aigc_safety_checks WHERE task_id=?", (tid,)) == 0
    assert _count(test_db_path, "SELECT COUNT(*) FROM ai_corrections WHERE student_id=?", (sid,)) == 0
    assert _count(test_db_path, "SELECT COUNT(*) FROM files WHERE student_id=?", (sid,)) == 0
    assert _count(test_db_path, "SELECT COUNT(*) FROM weekly_records WHERE student_id=?", (sid,)) == 0
    assert _count(test_db_path, "SELECT COUNT(*) FROM score_history WHERE student_id=?", (sid,)) == 0
    assert _count(test_db_path, "SELECT COUNT(*) FROM subscriptions WHERE student_id=?", (sid,)) == 0
    assert _count(test_db_path, "SELECT COUNT(*) FROM parent_consents WHERE student_id=?", (sid,)) == 0
    assert _count(test_db_path, "SELECT COUNT(*) FROM practice_records WHERE mistake_id=?", (mid,)) == 0
    assert _count(test_db_path, "SELECT COUNT(*) FROM audit_logs WHERE actor_id=? OR target_id=?",
                  (str(sid), str(sid))) == 0

    # payments 保留（财务留档）
    assert _count(test_db_path, "SELECT COUNT(*) FROM payments WHERE student_id=?", (sid,)) == 1

    # 学生行 → 匿名存根：无 PII、无访问码、status=deleted
    stub = db.get_student(sid, db_path=test_db_path)
    assert stub["status"] == "deleted"
    assert stub["name"] == "已注销学生"
    assert stub["access_code"] is None
    assert stub["parent_access_code"] is None
    assert stub["parent_phone"] is None
    assert stub["notes"] is None

    # 题库题保留但引用置空
    assert _count(test_db_path, "SELECT COUNT(*) FROM questions WHERE id=?", (qid,)) == 1
    assert _count(test_db_path,
                  "SELECT COUNT(*) FROM questions WHERE id=? AND source_mistake_id IS NULL",
                  (qid,)) == 1

    # 磁盘目录已删
    assert not os.path.exists(disk_file)

    # 删除请求标记完成
    conn = db.get_connection(test_db_path)
    st = conn.execute("SELECT status FROM deletion_requests WHERE id=?",
                      [req_id]).fetchone()["status"]
    conn.close()
    assert st == "completed"


def test_deletion_unknown_request(test_db_path):
    import db
    assert db.process_data_deletion(999999, db_path=test_db_path) is False


def test_consent_version_recorded(test_db_path, sample_student):
    import db
    cid = db.record_parent_consent(sample_student, consented_by="家长乙",
                                   consent_version="v2", db_path=test_db_path)
    conn = db.get_connection(test_db_path)
    row = conn.execute("SELECT consent_version, withdrawn_at FROM parent_consents WHERE id=?",
                       [cid]).fetchone()
    conn.close()
    assert row["consent_version"] == "v2"
    assert row["withdrawn_at"] is None
    assert db.has_parent_consent(sample_student, db_path=test_db_path) is True


def test_consent_withdrawal(test_db_path, sample_student):
    import db
    db.record_parent_consent(sample_student, consented_by="家长甲", db_path=test_db_path)
    assert db.has_parent_consent(sample_student, db_path=test_db_path) is True

    withdrawn = db.withdraw_parent_consent(sample_student, withdrawn_by="家长甲",
                                           reason="不再使用", db_path=test_db_path)
    assert withdrawn is True
    # 撤回后视为无同意
    assert db.has_parent_consent(sample_student, db_path=test_db_path) is False
    # 历史轨迹保留（行未删，含撤回时间与原因）
    conn = db.get_connection(test_db_path)
    row = conn.execute(
        "SELECT withdrawn_at, notes FROM parent_consents WHERE student_id=?",
        [sample_student]).fetchone()
    conn.close()
    assert row["withdrawn_at"] is not None
    assert "不再使用" in row["notes"]
    # 无有效同意时再撤回 → False
    assert db.withdraw_parent_consent(sample_student, withdrawn_by="x",
                                      db_path=test_db_path) is False


def test_consent_gate_blocks_upload(client, sample_student, test_db_path, monkeypatch):
    monkeypatch.setenv("CONSENT_REQUIRED", "true")
    import db
    data = {"file": (io.BytesIO(b"\xff\xd8\xff\xd9"), "paper.jpg")}
    r = client.post("/api/parent/diagnose", data=data,
                    content_type="multipart/form-data")
    assert r.status_code == 403
    assert "监护人" in r.get_json()["error"]
    # 无任务产生
    assert _count(test_db_path, "SELECT COUNT(*) FROM ai_tasks WHERE student_id=?",
                  (sample_student,)) == 0


def test_consent_gate_allows_with_consent(client, sample_student, test_db_path, monkeypatch):
    monkeypatch.setenv("CONSENT_REQUIRED", "true")
    import db
    db.record_parent_consent(sample_student, consented_by="家长",
                             db_path=test_db_path)
    code = db.get_student(sample_student, db_path=test_db_path)["access_code"]
    data = {"file": (io.BytesIO(b"\xff\xd8\xff\xd9"), "paper.jpg"),
            "access_code": code}
    r = client.post("/api/parent/diagnose", data=data,
                    content_type="multipart/form-data")
    assert r.status_code == 202


def test_consent_gate_off_by_default(client, sample_student, test_db_path, monkeypatch):
    monkeypatch.delenv("CONSENT_REQUIRED", raising=False)
    import db
    code = db.get_student(sample_student, db_path=test_db_path)["access_code"]
    data = {"file": (io.BytesIO(b"\xff\xd8\xff\xd9"), "paper.jpg"),
            "access_code": code}
    r = client.post("/api/parent/diagnose", data=data,
                    content_type="multipart/form-data")
    assert r.status_code == 202


def test_withdraw_endpoint(client, teacher_user, sample_student, test_db_path):
    import db
    db.record_parent_consent(sample_student, consented_by="家长", db_path=test_db_path)
    login_client(client, teacher_user, "teacher", "t1")
    r = client.post("/api/compliance/consents/withdraw",
                    json={"student_id": sample_student, "reason": "测试撤回"})
    assert r.status_code == 200
    assert r.get_json()["had_active_consent"] is True
    assert db.has_parent_consent(sample_student, db_path=test_db_path) is False


def test_withdraw_endpoint_requires_staff(client, sample_student):
    r = client.post("/api/compliance/consents/withdraw",
                    json={"student_id": sample_student})
    assert r.status_code == 401
