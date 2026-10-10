# -*- coding: utf-8 -*-
"""家庭端同意交互（P0-6）：注册勾选 / 首访门禁 / 学习中心自助同意 / 条款页面。

对应文本：
- 《用户服务协议》§1.2：注册时主动勾选 + 首访点"同意并继续"，不默认勾选
- 《隐私政策》§5.2：监护人单独同意、版本化记录
落地：写 `parent_consents`（consent_version = web.legal.CONSENT_VERSION），
`CONSENT_REQUIRED=true` 时未同意禁止上传（domain/upload.py 门禁）。
"""

import io
import uuid
from datetime import date

import pytest

import db
from web.legal import CONSENT_VERSION, render_markdown


def _login(client, user_id, role="admin", name="admin"):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_role"] = role
        sess["user_name"] = name


def _register_payload(**over):
    p = {
        "name": "同意测试",
        "phone": "13" + str(uuid.uuid4().int)[:9],
        "password": "secret123",
        "grade": "初二",
        "textbook_version": "人教版",
        "consent_agreed": True,
        # 已满14周岁：本节只验证一般同意交互，年龄相关用例见 test_age_consent.py
        "birth_year": date.today().year - 16,
    }
    p.update(over)
    return p


def _consents(test_db_path, student_id):
    conn = db.get_connection(test_db_path)
    rows = conn.execute(
        "SELECT * FROM parent_consents WHERE student_id = ?", [student_id]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── 注册页勾选 ──────────────────────────────────────

def test_register_requires_consent_checkbox(client, test_db_path):
    """未勾选同意不得注册（服务端强制，不依赖前端）。"""
    r = client.post("/api/register", json=_register_payload(consent_agreed=False))
    assert r.status_code == 400
    assert "同意" in r.get_json()["error"]
    # 也覆盖缺字段的情况（不默认勾选）
    payload = _register_payload()
    payload.pop("consent_agreed")
    assert client.post("/api/register", json=payload).status_code == 400


def test_register_records_versioned_consent(client, test_db_path):
    r = client.post("/api/register", json=_register_payload())
    assert r.status_code == 200
    sid = r.get_json()["student_id"]

    rows = _consents(test_db_path, sid)
    assert len(rows) == 1
    assert rows[0]["consent_version"] == CONSENT_VERSION
    assert "注册页" in (rows[0]["notes"] or "")
    assert db.has_parent_consent(sid, db_path=test_db_path) is True


# ── 学习中心：状态查询 + 自助同意 ────────────────────

def test_public_consent_get_status(client, sample_student, test_db_path):
    code = db.get_student(sample_student, db_path=test_db_path)["access_code"]
    d = client.get(f"/api/public/{code}/consent").get_json()
    assert d["has_consent"] is False
    assert d["required"] is False          # 默认关闭（自用不打断）
    assert d["version"] == CONSENT_VERSION
    urls = {x["url"] for x in d["documents"]}
    assert {"/terms", "/privacy", "/ai-disclaimer"} <= urls


def test_public_consent_post_requires_explicit_agreement(client, sample_student,
                                                         test_db_path):
    code = db.get_student(sample_student, db_path=test_db_path)["access_code"]
    for body in ({}, {"agreed": False}, {"agreed": "true"}):
        r = client.post(f"/api/public/{code}/consent", json=body)
        assert r.status_code == 400, body
    assert _consents(test_db_path, sample_student) == []


def test_public_consent_post_records_and_reflects(client, sample_student,
                                                 test_db_path):
    code = db.get_student(sample_student, db_path=test_db_path)["access_code"]
    r = client.post(f"/api/public/{code}/consent", json={"agreed": True})
    assert r.status_code == 201
    assert r.get_json()["version"] == CONSENT_VERSION

    assert db.has_parent_consent(sample_student, db_path=test_db_path) is True
    assert client.get(f"/api/public/{code}/consent").get_json()["has_consent"] is True
    rows = _consents(test_db_path, sample_student)
    assert rows[0]["consent_version"] == CONSENT_VERSION
    assert "自助" in (rows[0]["notes"] or "")


# ── 首访门禁（CONSENT_REQUIRED） ─────────────────────

def _upload_diagnose(client, **form):
    data = {"file": (io.BytesIO(b"\xff\xd8\xff\xd9"), "p.jpg")}
    data.update(form)
    return client.post("/api/parent/diagnose", data=data,
                       content_type="multipart/form-data")


@pytest.fixture
def _isolated_upload(tmp_path, monkeypatch):
    from domain import upload as upload_mod
    import pipeline_worker
    monkeypatch.setattr(upload_mod, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(pipeline_worker, "enqueue_task", lambda *a, **k: None)
    return tmp_path


def test_required_blocks_first_visit_without_consent(client, test_db_path,
                                                     monkeypatch, _isolated_upload):
    monkeypatch.setenv("CONSENT_REQUIRED", "true")
    conn = db.get_connection(test_db_path)
    before = conn.execute("SELECT COUNT(*) AS c FROM students").fetchone()["c"]
    conn.close()

    r = _upload_diagnose(client, grade="初二")
    assert r.status_code == 403
    assert "同意" in r.get_json()["error"]

    conn = db.get_connection(test_db_path)
    after = conn.execute("SELECT COUNT(*) AS c FROM students").fetchone()["c"]
    conn.close()
    assert after == before, "未同意不得建档（避免产生无同意的孤儿档案）"


def test_required_allows_with_consent_and_records(client, test_db_path,
                                                  monkeypatch, _isolated_upload):
    monkeypatch.setenv("CONSENT_REQUIRED", "true")
    r = _upload_diagnose(client, grade="初二", consent_agreed="true",
                         birth_year=str(date.today().year - 16))
    assert r.status_code == 202
    body = r.get_json()

    sid = db.get_student_by_access_code_probe = None  # noqa: F841 (占位，避免误用)
    conn = db.get_connection(test_db_path)
    sid = conn.execute("SELECT id FROM students WHERE access_code = ?",
                       [body["access_code"]]).fetchone()["id"]
    conn.close()
    assert db.has_parent_consent(sid, db_path=test_db_path) is True
    assert _consents(test_db_path, sid)[0]["consent_version"] == CONSENT_VERSION


def test_consent_recorded_even_when_gate_off(client, test_db_path,
                                             _isolated_upload):
    """门禁默认关闭（自用），但用户勾选了就要记录 —— 协议 §1.2 的同意不能丢。"""
    r = _upload_diagnose(client, grade="初二", consent_agreed="true")
    assert r.status_code == 202
    conn = db.get_connection(test_db_path)
    sid = conn.execute("SELECT id FROM students WHERE access_code = ?",
                       [r.get_json()["access_code"]]).fetchone()["id"]
    conn.close()
    assert len(_consents(test_db_path, sid)) == 1


# ── 条款页面 ────────────────────────────────────────

@pytest.mark.parametrize("path,keyword,has_table", [
    ("/terms", "用户服务协议", True),
    ("/privacy", "隐私政策", True),
    ("/ai-disclaimer", "AI 生成内容免责声明", False),
])
def test_legal_pages_render(client, path, keyword, has_table):
    r = client.get(path)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert keyword in html
    if has_table:
        assert "<table>" in html, "条款表格必须被渲染（不是原样输出 markdown）"
    body = html.split("<body>")[1]
    assert "<h1>" in body or "<h2>" in body, "标题必须被渲染为标签"


def test_legal_page_unknown_slug_404s():
    from web.legal import render_legal_page
    assert render_legal_page("nope") is None


def test_markdown_renderer_subset():
    md = ("# 标题\n\n段落 **加粗** 与 `代码`。\n\n"
          "- 项目一\n- 项目二\n\n1. 第一\n2. 第二\n\n"
          "> 引用\n\n---\n\n"
          "| 列A | 列B |\n|---|---|\n| a1 | b1 |\n\n"
          "[链接](https://example.com)\n\n<script>alert(1)</script>\n")
    html = render_markdown(md)
    assert "<h1>标题</h1>" in html
    assert "<strong>加粗</strong>" in html and "<code>代码</code>" in html
    assert "<ul>" in html and "<li>项目一</li>" in html
    assert "<ol>" in html and "<li>第一</li>" in html
    assert "<blockquote>引用</blockquote>" in html, "引用符号不能被转义掉"
    assert "<hr>" in html
    assert "<th>列A</th>" in html and "<td>a1</td>" in html
    assert '<a href="https://example.com"' in html
    assert "&lt;script&gt;" in html, "原始 HTML 必须转义"


def test_javascript_link_is_not_rendered_as_anchor():
    html = render_markdown("[点我](javascript:alert(1))")
    assert "<a" not in html and "点我" in html


# ── 三处界面都真的有同意交互 ─────────────────────────

def test_register_page_has_consent_checkbox(client):
    html = client.get("/register").get_data(as_text=True)
    assert "consent-agree" in html
    assert "/terms" in html and "/privacy" in html
    assert "监护人" in html
    # 不默认勾选
    assert "consent-agree\" checked" not in html


def test_parent_page_has_consent_gate(client):
    html = client.get("/parent").get_data(as_text=True)
    assert "consent-agree-parent" in html
    assert "consent_agreed" in html, "首访上传必须把同意随表单提交"
    assert "/terms" in html and "/privacy" in html


def test_family_center_has_consent_gate(client, sample_student, test_db_path):
    code = db.get_student(sample_student, db_path=test_db_path)["access_code"]
    html = client.get(f"/s/{code}").get_data(as_text=True)
    assert "consent-gate" in html and "agreeConsent" in html
    assert "/api/public/" in html and "/consent" in html
