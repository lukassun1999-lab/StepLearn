# -*- coding: utf-8 -*-
"""年龄识别 + 不满十四周岁「单独同意」（P0-6，PIPL 第28/31条）。

背景：受众为初一～高三，**初一普遍 12–13 岁**，大量用户属"不满十四周岁"——
其个人信息为敏感个人信息，须监护人**单独同意**（独立、具体、不与一般条款捆绑）。

设计要点：
- 只收集**出生年份**（最小必要），取"最小可能年龄"判定（偏保守：可能已满14也算未满）。
- 单独同意作为**独立同意类型**（`children_sensitive_info`）单独落库，与一般同意分开可举证。
- 缺单独同意时，上传门禁（CONSENT_REQUIRED=true）给出可操作提示而非笼统拒绝。
"""

import io
from datetime import date

import pytest

import db
from db.compliance import (CONSENT_TYPE_CHILDREN, CONSENT_TYPE_DATA,
                           age_from_birth_year)

_THIS_YEAR = date.today().year
UNDER_14_YEAR = _THIS_YEAR - 12   # 明确不满 14
OVER_14_YEAR = _THIS_YEAR - 16    # 明确已满 14


def _login(client, user_id, role="admin", name="admin"):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_role"] = role
        sess["user_name"] = name


def _payload(**over):
    import uuid
    p = {
        "name": "年龄测试",
        "phone": "13" + str(uuid.uuid4().int)[:9],
        "password": "secret123",
        "grade": "初一",
        "textbook_version": "人教版",
        "consent_agreed": True,
        "birth_year": UNDER_14_YEAR,
        "children_consent_agreed": True,
    }
    p.update(over)
    return p


def _consent_types(test_db_path, student_id):
    conn = db.get_connection(test_db_path)
    rows = conn.execute(
        "SELECT consent_type, notes, consent_version FROM parent_consents "
        "WHERE student_id = ? AND withdrawn_at IS NULL ORDER BY id", [student_id]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── 年龄判定 ────────────────────────────────────────

def test_age_from_birth_year():
    assert age_from_birth_year(UNDER_14_YEAR) == 12
    assert age_from_birth_year(str(OVER_14_YEAR)) == 16
    for bad in (None, "", "abc", 1800, _THIS_YEAR + 1):
        assert age_from_birth_year(bad) is None, bad


def test_needs_children_consent_only_for_under_14(test_db_path, sample_student):
    # 无出生年份 → 不臆测
    assert db.needs_children_consent(sample_student, db_path=test_db_path) is False

    db.set_student_birth_year(sample_student, UNDER_14_YEAR, db_path=test_db_path)
    assert db.needs_children_consent(sample_student, db_path=test_db_path) is True
    assert db.required_consent_types(sample_student, db_path=test_db_path) == [
        CONSENT_TYPE_DATA, CONSENT_TYPE_CHILDREN]

    db.set_student_birth_year(sample_student, OVER_14_YEAR, db_path=test_db_path)
    assert db.needs_children_consent(sample_student, db_path=test_db_path) is False
    assert db.required_consent_types(sample_student, db_path=test_db_path) == [
        CONSENT_TYPE_DATA]


def test_missing_types_distinguishes_general_vs_children(test_db_path, sample_student):
    db.set_student_birth_year(sample_student, UNDER_14_YEAR, db_path=test_db_path)
    assert db.missing_consent_types(sample_student, db_path=test_db_path) == [
        CONSENT_TYPE_DATA, CONSENT_TYPE_CHILDREN]

    db.record_parent_consent(sample_student, consented_by="家长",
                            db_path=test_db_path)  # 默认一般同意
    assert db.has_parent_consent(sample_student, db_path=test_db_path) is True
    # 关键：一般同意不算满足单独同意
    assert db.missing_consent_types(sample_student, db_path=test_db_path) == [
        CONSENT_TYPE_CHILDREN]
    assert db.has_parent_consent(sample_student, db_path=test_db_path,
                                consent_type=CONSENT_TYPE_CHILDREN) is False

    db.record_parent_consent(sample_student, consented_by="家长",
                            consent_type=CONSENT_TYPE_CHILDREN,
                            db_path=test_db_path)
    assert db.missing_consent_types(sample_student, db_path=test_db_path) == []


def test_set_birth_year_does_not_touch_other_fields(test_db_path, sample_student):
    before = db.get_student(sample_student, db_path=test_db_path)
    db.set_student_birth_year(sample_student, UNDER_14_YEAR, db_path=test_db_path)
    after = db.get_student(sample_student, db_path=test_db_path)
    assert after["birth_year"] == UNDER_14_YEAR
    for f in ("name", "grade", "english_score", "target_score"):
        assert after[f] == before[f]


def test_get_students_without_consent_reports_missing_types(test_db_path):
    sid = db.create_student({"name": "缺同意", "grade": "初一"}, db_path=test_db_path)
    db.set_student_birth_year(sid, UNDER_14_YEAR, db_path=test_db_path)
    db.record_parent_consent(sid, consented_by="家长", db_path=test_db_path)

    rows = {r["id"]: r for r in db.get_students_without_consent(db_path=test_db_path)}
    assert sid in rows, "只缺儿童单独同意的学生也要出现在待授权列表"
    assert rows[sid]["missing_consents"] == [CONSENT_TYPE_CHILDREN]
    assert rows[sid]["needs_children_consent"] is True


# ── 注册：年龄 + 单独同意 ────────────────────────────

def test_register_requires_birth_year(client, test_db_path):
    r = client.post("/api/register", json=_payload(birth_year=""))
    assert r.status_code == 400
    assert "出生年份" in r.get_json()["error"]


def test_register_under_14_requires_separate_consent(client, test_db_path):
    """不满14周岁未勾选单独同意 → 拒绝，并给出可识别错误码。"""
    r = client.post("/api/register",
                    json=_payload(children_consent_agreed=False))
    assert r.status_code == 400
    body = r.get_json()
    assert body["code"] == "children_consent_required"
    assert "单独同意" in body["error"]


def test_register_under_14_records_both_consents(client, test_db_path):
    r = client.post("/api/register", json=_payload())
    assert r.status_code == 200
    sid = r.get_json()["student_id"]
    assert db.get_student(sid, db_path=test_db_path)["birth_year"] == UNDER_14_YEAR
    types = [c["consent_type"] for c in _consent_types(test_db_path, sid)]
    assert types == [CONSENT_TYPE_DATA, CONSENT_TYPE_CHILDREN]
    assert db.missing_consent_types(sid, db_path=test_db_path) == []


def test_register_over_14_records_general_only(client, test_db_path):
    r = client.post("/api/register",
                    json=_payload(birth_year=OVER_14_YEAR,
                                  children_consent_agreed=False))
    assert r.status_code == 200
    sid = r.get_json()["student_id"]
    types = [c["consent_type"] for c in _consent_types(test_db_path, sid)]
    assert types == [CONSENT_TYPE_DATA]


# ── 学习中心自助同意 ────────────────────────────────

def _code(test_db_path, student_id):
    return db.get_student(student_id, db_path=test_db_path)["access_code"]


def test_consent_get_exposes_age_status(client, sample_student, test_db_path):
    db.set_student_birth_year(sample_student, UNDER_14_YEAR, db_path=test_db_path)
    code = _code(test_db_path, sample_student)
    d = client.get(f"/api/public/{code}/consent").get_json()
    assert d["birth_year"] == UNDER_14_YEAR and d["age"] == 12
    assert d["needs_children_consent"] is True
    assert d["missing_types"] == [CONSENT_TYPE_DATA, CONSENT_TYPE_CHILDREN]


def test_consent_post_under_14_needs_separate_flag(client, sample_student,
                                                   test_db_path):
    db.set_student_birth_year(sample_student, UNDER_14_YEAR, db_path=test_db_path)
    code = _code(test_db_path, sample_student)
    r = client.post(f"/api/public/{code}/consent", json={"agreed": True})
    assert r.status_code == 400
    assert r.get_json()["code"] == "children_consent_required"
    # 校验不通过不得留下半截同意
    assert _consent_types(test_db_path, sample_student) == []


def test_consent_post_under_14_records_both(client, sample_student, test_db_path):
    db.set_student_birth_year(sample_student, UNDER_14_YEAR, db_path=test_db_path)
    code = _code(test_db_path, sample_student)
    r = client.post(f"/api/public/{code}/consent",
                    json={"agreed": True, "children_agreed": True})
    assert r.status_code == 201
    assert set(r.get_json()["recorded_types"]) == {CONSENT_TYPE_DATA,
                                                  CONSENT_TYPE_CHILDREN}
    assert r.get_json()["missing_types"] == []
    assert "单独同意" in _consent_types(test_db_path, sample_student)[1]["notes"]


def test_consent_post_can_supply_birth_year(client, sample_student, test_db_path):
    """档案缺出生年份时，家长在同意卡片里补录 → 立即触发单独同意要求。"""
    code = _code(test_db_path, sample_student)
    r = client.post(f"/api/public/{code}/consent",
                    json={"agreed": True, "birth_year": UNDER_14_YEAR})
    assert r.status_code == 400, "补录后判定为不满14周岁，必须单独同意"
    assert r.get_json()["code"] == "children_consent_required"
    assert db.get_student(sample_student, db_path=test_db_path)["birth_year"] == UNDER_14_YEAR


# ── 首访建档 ────────────────────────────────────────

@pytest.fixture
def _isolated_upload(tmp_path, monkeypatch):
    from domain import upload as upload_mod
    import pipeline_worker
    monkeypatch.setattr(upload_mod, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(pipeline_worker, "enqueue_task", lambda *a, **k: None)
    return tmp_path


def _diagnose(client, **form):
    data = {"file": (io.BytesIO(b"\xff\xd8\xff\xd9"), "p.jpg")}
    data.update(form)
    return client.post("/api/parent/diagnose", data=data,
                       content_type="multipart/form-data")


def _student_count(test_db_path):
    conn = db.get_connection(test_db_path)
    n = conn.execute("SELECT COUNT(*) AS c FROM students").fetchone()["c"]
    conn.close()
    return n


def test_first_visit_under_14_without_separate_consent_blocks_archive(
        client, test_db_path, monkeypatch, _isolated_upload):
    monkeypatch.setenv("CONSENT_REQUIRED", "true")
    before = _student_count(test_db_path)
    r = _diagnose(client, grade="初一", consent_agreed="true",
                  birth_year=str(UNDER_14_YEAR), children_consent_agreed="false")
    assert r.status_code == 403
    assert r.get_json()["code"] == "children_consent_required"
    assert _student_count(test_db_path) == before, "未取得单独同意不得建档"


def test_first_visit_under_14_with_separate_consent_records_both(
        client, test_db_path, monkeypatch, _isolated_upload):
    monkeypatch.setenv("CONSENT_REQUIRED", "true")
    r = _diagnose(client, grade="初一", consent_agreed="true",
                  birth_year=str(UNDER_14_YEAR), children_consent_agreed="true")
    assert r.status_code == 202
    conn = db.get_connection(test_db_path)
    sid = conn.execute("SELECT id FROM students WHERE access_code = ?",
                       [r.get_json()["access_code"]]).fetchone()["id"]
    conn.close()
    assert db.get_student(sid, db_path=test_db_path)["birth_year"] == UNDER_14_YEAR
    types = [c["consent_type"] for c in _consent_types(test_db_path, sid)]
    assert types == [CONSENT_TYPE_DATA, CONSENT_TYPE_CHILDREN]


def test_first_visit_missing_birth_year_rejected_when_gate_on(
        client, test_db_path, monkeypatch, _isolated_upload):
    monkeypatch.setenv("CONSENT_REQUIRED", "true")
    before = _student_count(test_db_path)
    r = _diagnose(client, grade="初一", consent_agreed="true")
    assert r.status_code == 400
    assert "出生年份" in r.get_json()["error"]
    assert _student_count(test_db_path) == before


# ── 上传门禁：缺单独同意的分支 ──────────────────────

def test_gate_blocks_when_only_children_consent_missing(client, sample_student,
                                                        test_db_path, monkeypatch,
                                                        _isolated_upload):
    """有一般同意但缺儿童单独同意 → 门禁给出"单独同意"提示（不是笼统拒绝）。"""
    monkeypatch.setenv("CONSENT_REQUIRED", "true")
    db.set_student_birth_year(sample_student, UNDER_14_YEAR, db_path=test_db_path)
    db.record_parent_consent(sample_student, consented_by="家长", db_path=test_db_path)
    code = _code(test_db_path, sample_student)

    r = client.post(f"/api/public/{code}/upload",
                    data={"file": (io.BytesIO(b"\xff\xd8\xff\xd9"), "p.jpg")},
                    content_type="multipart/form-data")
    assert r.status_code == 403
    assert "单独同意" in r.get_json()["error"]


def test_gate_allows_after_children_consent(client, sample_student, test_db_path,
                                            monkeypatch, _isolated_upload):
    monkeypatch.setenv("CONSENT_REQUIRED", "true")
    db.set_student_birth_year(sample_student, UNDER_14_YEAR, db_path=test_db_path)
    db.record_parent_consent(sample_student, consented_by="家长", db_path=test_db_path)
    db.record_parent_consent(sample_student, consented_by="家长",
                            consent_type=CONSENT_TYPE_CHILDREN, db_path=test_db_path)
    code = _code(test_db_path, sample_student)

    r = client.post(f"/api/public/{code}/upload",
                    data={"file": (io.BytesIO(b"\xff\xd8\xff\xd9"), "p.jpg")},
                    content_type="multipart/form-data")
    assert r.status_code == 202


# ── 三处界面的年龄交互 ──────────────────────────────

def test_register_page_has_birth_year_and_separate_consent(client):
    html = client.get("/register").get_data(as_text=True)
    assert 'id="birth-year"' in html
    assert 'id="children-consent"' in html
    assert "单独同意" in html
    assert "未成年人个人信息专门章节" in html
    # 不默认勾选
    assert 'id="children-consent" checked' not in html


def test_parent_page_has_birth_year_and_separate_consent(client):
    html = client.get("/parent").get_data(as_text=True)
    assert 'id="birth-year-parent"' in html
    assert 'id="children-consent-parent"' in html
    assert "children_consent_agreed" in html


def test_family_center_gate_has_birth_year_and_separate_consent(client,
                                                               sample_student,
                                                               test_db_path):
    html = client.get(f"/s/{_code(test_db_path, sample_student)}").get_data(as_text=True)
    assert 'id="birth-year-center"' in html
    assert 'id="children-consent-center"' in html
    assert "updateChildrenConsentCenter" in html
