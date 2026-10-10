# -*- coding: utf-8 -*-
"""家长上报 API + 运营端采纳/驳回端点（P0-1 → P0-3）。

覆盖：免登录上报的归属校验与幂等、运营端鉴权、采纳后数据生效并回流模式池、
驳回不动数据、已处理记录不可重复处理。
"""

import uuid

import db


def _login(client, user_id, role="admin", name="admin"):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_role"] = role
        sess["user_name"] = name


def _seed(test_db_path, kp=None):
    """建学生 + 任务 + 错题，返回 (student_id, mistake_id, access_code)。"""
    sid = db.create_student({"name": "API上报", "grade": "初二", "plan": "trial"},
                            db_path=test_db_path)
    tid = db.create_task(sid, "weekly", {"stage": "report_only"},
                         week_start=db.get_week_start(), db_path=test_db_path)
    mid = db.add_mistake(student_id=sid, source_exam="t", question="API题",
                         question_type="单项选择", correct_answer="A",
                         user_answer="B", knowledge_points=kp,
                         source_task_id=tid, db_path=test_db_path)
    code = db.get_student(sid, db_path=test_db_path)["access_code"]
    return sid, mid, code


# ── 家庭端（免登录，按 access_code）─────────────────

def test_family_report_creates_pending(client, test_db_path):
    _sid, mid, code = _seed(test_db_path)
    r = client.post(f"/api/public/{code}/report",
                    json={"mistake_id": mid, "issue": "wrong_answer",
                          "suggested_answer": "C", "note": "老师说是 C"})
    assert r.status_code == 201
    body = r.get_json()
    assert body["ok"] and body["report_id"] and not body["duplicate"]

    row = db.get_correction(body["report_id"], db_path=test_db_path)
    assert row["status"] == "pending"
    assert row["target_field"] == "correct_answer"
    assert row["corrected_value"] == "C"
    # 未采纳 → 错题数据不变
    assert db.get_mistake(mid, db_path=test_db_path)["correct_answer"] == "A"


def test_family_report_duplicate_is_idempotent(client, test_db_path):
    _sid, mid, code = _seed(test_db_path)
    first = client.post(f"/api/public/{code}/report",
                        json={"mistake_id": mid, "issue": "wrong_answer"}).get_json()
    second = client.post(f"/api/public/{code}/report",
                         json={"mistake_id": mid, "issue": "wrong_answer"}).get_json()
    assert second["duplicate"] is True
    assert second["report_id"] == first["report_id"]


def test_family_report_validation(client, test_db_path):
    _sid, mid, code = _seed(test_db_path)
    assert client.post(f"/api/public/{code}/report",
                       json={"mistake_id": mid, "issue": "nope"}).status_code == 400
    assert client.post(f"/api/public/{code}/report",
                       json={"issue": "wrong_answer"}).status_code == 400
    assert client.post(f"/api/public/{code}/report",
                       json={"mistake_id": 999999,
                             "issue": "wrong_answer"}).status_code == 404


def test_family_report_cannot_touch_other_student(client, test_db_path):
    _sid_a, mid_a, _code_a = _seed(test_db_path)
    _sid_b, _mid_b, code_b = _seed(test_db_path)
    r = client.post(f"/api/public/{code_b}/report",
                    json={"mistake_id": mid_a, "issue": "wrong_answer"})
    assert r.status_code == 404


def test_family_report_rejects_bad_code(client, test_db_path):
    _seed(test_db_path)
    r = client.post("/api/public/NO-SUCH-CODE/report",
                    json={"mistake_id": 1, "issue": "wrong_answer"})
    assert r.status_code in (401, 404)


# ── 运营端（staff 鉴权）────────────────────────────

def test_ops_reports_requires_staff(client, test_db_path):
    assert client.get("/api/reports/pending").status_code == 401
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_role"] = "student"
    assert client.get("/api/reports/pending").status_code == 403


def test_ops_pending_list_and_adopt(client, admin_user, test_db_path):
    kp = [f"KP_{uuid.uuid4().hex[:8]}"]
    _sid, mid, code = _seed(test_db_path, kp=kp)
    rid = client.post(f"/api/public/{code}/report",
                      json={"mistake_id": mid, "issue": "wrong_answer",
                            "suggested_answer": "C"}).get_json()["report_id"]

    _login(client, admin_user)
    body = client.get("/api/reports/pending").get_json()
    assert any(x["id"] == rid for x in body["reports"])
    assert body["count"] >= 1
    mine = [x for x in body["reports"] if x["id"] == rid][0]
    assert mine["target_field"] == "correct_answer"
    assert mine["original_value"] == "A"

    r = client.post(f"/api/reports/{rid}/adopt", json={"corrected_value": "D"})
    assert r.status_code == 200
    assert db.get_mistake(mid, db_path=test_db_path)["correct_answer"] == "D"
    # P0-3：采纳后进入提示词池
    assert db.get_recent_correction_hints(kp, "mistake", db_path=test_db_path) != ""
    # 采纳后离开待处理队列
    after = client.get("/api/reports/pending").get_json()
    assert all(x["id"] != rid for x in after["reports"])


def test_ops_reject_keeps_data_and_pool_clean(client, admin_user, test_db_path):
    kp = [f"KP_{uuid.uuid4().hex[:8]}"]
    _sid, mid, code = _seed(test_db_path, kp=kp)
    rid = client.post(f"/api/public/{code}/report",
                      json={"mistake_id": mid,
                            "issue": "wrong_explanation"}).get_json()["report_id"]

    _login(client, admin_user)
    r = client.post(f"/api/reports/{rid}/reject", json={"reason": "核对后无误"})
    assert r.status_code == 200

    m = db.get_mistake(mid, db_path=test_db_path)
    assert (m["explanation"] or "") == ""
    row = db.get_correction(rid, db_path=test_db_path)
    assert row["status"] == "rejected" and row["reason"] == "核对后无误"
    assert db.get_recent_correction_hints(kp, "mistake", db_path=test_db_path) == ""

    # 已处理 → 不可再采纳
    assert client.post(f"/api/reports/{rid}/adopt", json={}).status_code == 400


def test_ops_adopt_wrong_grading_retracts_mistake(client, admin_user, test_db_path):
    sid, mid, code = _seed(test_db_path)
    rid = client.post(f"/api/public/{code}/report",
                      json={"mistake_id": mid, "issue": "wrong_grading",
                            "note": "孩子选的就是 A"}).get_json()["report_id"]

    _login(client, admin_user)
    assert client.post(f"/api/reports/{rid}/adopt", json={}).status_code == 200

    assert db.get_mistake(mid, db_path=test_db_path)["consecutive_correct"] == 2
    assert db.get_review_progress(sid, db_path=test_db_path)["active"] == 0


# ── 页面渲染（确保两端界面真的被服务出来）──────────

def test_quality_page_renders_parent_report_block(client, admin_user):
    _login(client, admin_user)
    r = client.get("/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "家长上报" in html
    assert "adoptReport" in html and "rejectReport" in html


def test_family_mistake_card_renders_report_entry(client, test_db_path):
    _sid, _mid, code = _seed(test_db_path)
    r = client.get(f"/s/{code}")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "这题有问题" in html
    assert "submitReport" in html and "wrong_grading" in html
