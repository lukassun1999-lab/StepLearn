# -*- coding: utf-8 -*-
"""运营端建档/编辑的年龄识别与儿童单独同意（P0-6）。

背景：运营端代建档曾是**唯一漏掉年龄的路径** —— 表单没有出生年份 → 判定
"不需要单独同意" → 不满 14 周岁的孩子整条链路都绕过单独同意。
规则：**既然代登记家长同意，就必须说明年龄**；不满 14 周岁还须单独确认儿童授权；
编辑既有学生时，已登记的单独同意仍然有效，不要求重复勾选。
"""

from datetime import date

import pytest

import db
from db.compliance import CONSENT_TYPE_CHILDREN, CONSENT_TYPE_DATA
from api.ops_api import _valid_birth_year

_THIS_YEAR = date.today().year
UNDER_14_YEAR = _THIS_YEAR - 12
OVER_14_YEAR = _THIS_YEAR - 16


def login_client(client, user_id, role="admin", name="admin"):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_role"] = role
        sess["user_name"] = name


def _types(test_db_path, student_id):
    conn = db.get_connection(test_db_path)
    rows = conn.execute(
        "SELECT consent_type, notes FROM parent_consents WHERE student_id = ? "
        "AND withdrawn_at IS NULL ORDER BY id", [student_id]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _create(client, **over):
    payload = {"name": "运营建档", "grade": "初一", "parent_consent": True,
               "birth_year": OVER_14_YEAR}
    payload.update(over)
    return client.post("/api/students", json=payload)


# ── 年份校验 ────────────────────────────────────────

def test_valid_birth_year_helper():
    assert _valid_birth_year(str(UNDER_14_YEAR)) == UNDER_14_YEAR
    assert _valid_birth_year(OVER_14_YEAR) == OVER_14_YEAR
    for bad in (None, "", "  ", "abc", 1800, _THIS_YEAR + 5):
        assert _valid_birth_year(bad) is None, bad


# ── 建档 ────────────────────────────────────────────

def test_create_with_consent_requires_birth_year(client, admin_user):
    login_client(client, admin_user)
    r = _create(client, birth_year=None)
    assert r.status_code == 400
    assert "出生年份" in r.get_json()["error"]


def test_create_under_14_requires_separate_consent(client, admin_user,
                                                   test_db_path):
    login_client(client, admin_user)
    r = _create(client, birth_year=UNDER_14_YEAR, children_consent=False)
    assert r.status_code == 400
    assert r.get_json()["code"] == "children_consent_required"

    # 失败不得留下学生或半截同意
    conn = db.get_connection(test_db_path)
    n = conn.execute("SELECT COUNT(*) AS c FROM students WHERE name = ?",
                     ["运营建档"]).fetchone()["c"]
    conn.close()
    assert n == 0


def test_create_under_14_with_separate_consent_records_both(client, admin_user,
                                                            test_db_path):
    login_client(client, admin_user)
    r = _create(client, birth_year=UNDER_14_YEAR, children_consent=True,
                parent_name="张家长")
    assert r.status_code == 201
    sid = r.get_json()["id"]
    assert db.get_student(sid, db_path=test_db_path)["birth_year"] == UNDER_14_YEAR
    rows = _types(test_db_path, sid)
    assert [c["consent_type"] for c in rows] == [CONSENT_TYPE_DATA,
                                                CONSENT_TYPE_CHILDREN]
    assert "单独" in rows[1]["notes"]
    assert db.missing_consent_types(sid, db_path=test_db_path) == []


def test_create_over_14_records_general_only(client, admin_user, test_db_path):
    login_client(client, admin_user)
    r = _create(client, birth_year=OVER_14_YEAR, children_consent=False)
    assert r.status_code == 201
    sid = r.get_json()["id"]
    assert [c["consent_type"] for c in _types(test_db_path, sid)] == [
        CONSENT_TYPE_DATA]


def test_create_without_consent_needs_no_birth_year(client, admin_user,
                                                    test_db_path):
    """未代登记同意时不强制年龄（后续可由家长自助补），但年份填了就要存下来。"""
    login_client(client, admin_user)
    r = _create(client, parent_consent=False, birth_year=UNDER_14_YEAR)
    assert r.status_code == 201
    sid = r.get_json()["id"]
    assert db.get_student(sid, db_path=test_db_path)["birth_year"] == UNDER_14_YEAR
    assert _types(test_db_path, sid) == []
    # 未同意 → 待授权（含儿童单独同意）
    assert db.missing_consent_types(sid, db_path=test_db_path) == [
        CONSENT_TYPE_DATA, CONSENT_TYPE_CHILDREN]


# ── 编辑 ────────────────────────────────────────────

def test_update_with_consent_requires_birth_year(client, admin_user,
                                                 sample_student):
    login_client(client, admin_user)
    r = client.put(f"/api/students/{sample_student}",
                   json={"name": "改名", "parent_consent": True, "birth_year": ""})
    assert r.status_code == 400
    assert "出生年份" in r.get_json()["error"]


def test_update_under_14_requires_separate_consent_once(client, admin_user,
                                                        sample_student,
                                                        test_db_path):
    login_client(client, admin_user)
    payload = {"name": "初一学生", "parent_consent": True,
               "birth_year": UNDER_14_YEAR}

    r = client.put(f"/api/students/{sample_student}", json=payload)
    assert r.status_code == 400
    assert r.get_json()["code"] == "children_consent_required"

    # 单独勾选后通过，并落一条独立同意
    r = client.put(f"/api/students/{sample_student}",
                   json={**payload, "children_consent": True})
    assert r.status_code == 200
    types = [c["consent_type"] for c in _types(test_db_path, sample_student)]
    assert CONSENT_TYPE_CHILDREN in types

    # 已登记的单独同意仍然有效 → 再次编辑不要求重复勾选（UX 回归保护）
    r = client.put(f"/api/students/{sample_student}",
                   json={**payload, "children_consent": False})
    assert r.status_code == 200
    types2 = [c["consent_type"] for c in _types(test_db_path, sample_student)]
    assert types2.count(CONSENT_TYPE_CHILDREN) == 1, "不应重复记录单独同意"


def test_update_birth_year_persisted_without_touching_other_fields(
        client, admin_user, sample_student, test_db_path):
    login_client(client, admin_user)
    before = db.get_student(sample_student, db_path=test_db_path)
    r = client.put(f"/api/students/{sample_student}",
                   json={"name": before["name"], "grade": before["grade"],
                         "parent_consent": False, "birth_year": OVER_14_YEAR})
    assert r.status_code == 200
    after = db.get_student(sample_student, db_path=test_db_path)
    assert after["birth_year"] == OVER_14_YEAR
    assert after["name"] == before["name"] and after["grade"] == before["grade"]


# ── 运营端可见性 ────────────────────────────────────

def test_student_list_and_detail_expose_missing_consents(client, admin_user,
                                                        sample_student,
                                                        test_db_path):
    login_client(client, admin_user)
    db.set_student_birth_year(sample_student, UNDER_14_YEAR, db_path=test_db_path)
    db.record_parent_consent(sample_student, consented_by="家长",
                            db_path=test_db_path)

    detail = client.get(f"/api/students/{sample_student}").get_json()
    assert detail["has_consent"] is True
    assert detail["missing_consents"] == [CONSENT_TYPE_CHILDREN]
    assert detail["has_children_consent"] is False
    assert detail["birth_year"] == UNDER_14_YEAR

    row = next(s for s in client.get("/api/students").get_json()
               if s["id"] == sample_student)
    assert row["missing_consents"] == [CONSENT_TYPE_CHILDREN]
    assert row["has_children_consent"] is False


def test_compliance_page_lists_student_missing_only_children_consent(
        client, admin_user, sample_student, test_db_path):
    login_client(client, admin_user)
    db.set_student_birth_year(sample_student, UNDER_14_YEAR, db_path=test_db_path)
    db.record_parent_consent(sample_student, consented_by="家长",
                            db_path=test_db_path)
    rows = client.get("/api/compliance/students-without-consent").get_json()
    row = next(r for r in rows if r["id"] == sample_student)
    assert row["missing_consents"] == [CONSENT_TYPE_CHILDREN]
    assert row["needs_children_consent"] is True


# ── 界面真的有这些字段 ──────────────────────────────

def test_admin_page_has_birth_year_and_children_consent(client, admin_user):
    login_client(client, admin_user)
    html = client.get("/").get_data(as_text=True)
    # 建档表单
    assert 'id="onb-birth-year"' in html
    assert 'id="onb-children-consent"' in html
    # 编辑表单
    assert 'id="f-birth-year"' in html
    assert 'id="f-children-consent"' in html
    # 显隐逻辑与三态徽章
    assert "updateOpsChildrenConsent" in html
    assert "缺儿童单独同意" in html
    # 不默认勾选
    assert 'id="onb-children-consent" checked' not in html
    assert 'id="f-children-consent" checked' not in html
