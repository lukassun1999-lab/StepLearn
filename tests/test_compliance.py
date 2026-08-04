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
