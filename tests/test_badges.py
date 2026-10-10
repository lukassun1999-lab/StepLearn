# -*- coding: utf-8 -*-
"""徽章 / 成就解锁 / 学习用具兑换（P0-2：接口就位，规则暂不定）。

规则配置区（`db/learning.py` 的 BADGE_MILESTONES / REWARD_CATALOG）默认**为空**，
此时系统只做记数：徽章累计但不解锁成就，兑换申请被拒且**不产生单据**。
本文件用 monkeypatch 临时填入规则，验证"规则一旦填上，整条接口就通"。

同时覆盖采纳家长上报 → 记徽章的接线（P0-1 → P0-2）。
"""

import db
from db import learning as db_learning


def _setup(db_path):
    """建学生 + 任务 + 错题，返回 (student_id, task_id, mistake_id)。"""
    sid = db.create_student({"name": "徽章测试", "grade": "初二", "plan": "trial"},
                            db_path=db_path)
    tid = db.create_task(sid, "weekly", {"stage": "report_only"},
                         week_start=db.get_week_start(), db_path=db_path)
    mid = db.add_mistake(student_id=sid, source_exam="t", question="Q",
                         question_type="单项选择", correct_answer="A",
                         user_answer="B", source_task_id=tid, db_path=db_path)
    return sid, tid, mid


# ── 徽章计数与展示 ─────────────────────────────────

def test_award_accumulates_and_uses_catalog(test_db_path, sample_student):
    assert db.award_badge(sample_student, "parent_report_adopted",
                          db_path=test_db_path)["count"] == 1
    assert db.award_badge(sample_student, "parent_report_adopted",
                          db_path=test_db_path)["count"] == 2

    data = db.get_badges(sample_student, db_path=test_db_path)
    assert data["total_count"] == 2 and data["kinds"] == 1
    b = data["badges"][0]
    assert b["title"] == "火眼金睛" and b["icon"] == "🔍"
    assert b["description"]
    # 规则未配置 → 无里程碑进度可展示
    assert data["milestones_configured"] == 0 and b["next_milestone"] is None


def test_unknown_badge_key_still_counts_and_falls_back(test_db_path, sample_student):
    """未登记的 key 也允许记数（先埋点后定规则），展示回退用 key 本身。"""
    r = db.award_badge(sample_student, "some_future_badge", db_path=test_db_path)
    assert r["count"] == 1
    b = db.get_badges(sample_student, db_path=test_db_path)["badges"][0]
    assert b["badge_key"] == "some_future_badge" and b["title"] == "some_future_badge"


def test_milestone_unlocks_achievement_once(test_db_path, sample_student, monkeypatch):
    """规则填上后：徽章达标 → 解锁成就；重复达成不重复解锁。"""
    monkeypatch.setattr(db_learning, "BADGE_MILESTONES", [{
        "badge_key": "parent_report_adopted", "count": 2,
        "achievement_key": "badge_precision_2", "title": "明察秋毫",
        "description": "累计 2 次反馈被采纳", "icon": "🏅", "tier": 1,
    }])

    first = db.award_badge(sample_student, "parent_report_adopted",
                           db_path=test_db_path)
    assert first["unlocked"] == [], "未达阈值不解锁"

    second = db.award_badge(sample_student, "parent_report_adopted",
                            db_path=test_db_path)
    assert [u["achievement_key"] for u in second["unlocked"]] == ["badge_precision_2"]

    third = db.award_badge(sample_student, "parent_report_adopted",
                           db_path=test_db_path)
    assert third["unlocked"] == [], "已解锁不重复插入"

    earned = {a["achievement_key"] for a in
              db.get_student_achievements(sample_student, db_path=test_db_path)["earned"]}
    assert "badge_precision_2" in earned

    data = db.get_badges(sample_student, db_path=test_db_path)
    assert data["milestones_configured"] == 1
    assert data["badges"][0]["next_milestone"] is None, "已达成的里程碑不再出现在进度里"


def test_milestone_progress_when_not_reached(test_db_path, sample_student, monkeypatch):
    """未达阈值时展示距解锁还差多少枚。"""
    monkeypatch.setattr(db_learning, "BADGE_MILESTONES", [{
        "badge_key": "parent_report_adopted", "count": 5,
        "achievement_key": "badge_precision_5", "title": "明察秋毫",
    }])
    db.award_badge(sample_student, "parent_report_adopted", db_path=test_db_path)
    nxt = db.get_badges(sample_student, db_path=test_db_path)["badges"][0]["next_milestone"]
    assert nxt["count"] == 5 and nxt["remaining"] == 4
    assert nxt["achievement_key"] == "badge_precision_5"


# ── 兑换学习用具 ───────────────────────────────────

def test_redemption_rejected_when_rules_absent(test_db_path, sample_student):
    """规则未配置 → 拒绝且不产生单据（FAIL-SAFE，不产脏数据）。"""
    r = db.request_reward_redemption(sample_student, "mistake_slayer_5",
                                     db_path=test_db_path)
    assert r["ok"] is False and r["error"] == "reward_not_configured"
    assert db.list_reward_redemptions(db_path=test_db_path) == []


def test_redemption_full_flow_with_rules(test_db_path, sample_student, monkeypatch):
    conn = db.get_connection(test_db_path)
    conn.execute("INSERT INTO achievements (student_id, achievement_key, title) "
                 "VALUES (?, ?, ?)",
                 [sample_student, "mistake_slayer_5", "错题克星 5道"])
    conn.commit()
    conn.close()
    monkeypatch.setattr(db_learning, "REWARD_CATALOG", {
        "mistake_slayer_5": {"reward_key": "notebook", "title": "错题本笔记本"},
    })

    # 未获得的成就不能兑换
    other = db.create_student({"name": "无成就", "grade": "初二", "plan": "trial"},
                              db_path=test_db_path)
    assert db.request_reward_redemption(other, "mistake_slayer_5",
                                        db_path=test_db_path)["error"] == "achievement_not_earned"

    r = db.request_reward_redemption(sample_student, "mistake_slayer_5",
                                    note="想要一本", db_path=test_db_path)
    assert r["ok"] and r["redemption_id"]

    # 同一成就重复申请被拒
    assert db.request_reward_redemption(sample_student, "mistake_slayer_5",
                                        db_path=test_db_path)["error"] == "already_requested"

    rows = db.list_reward_redemptions(status="requested", db_path=test_db_path)
    assert len(rows) == 1
    assert rows[0]["reward_title"] == "错题本笔记本" and rows[0]["note"] == "想要一本"
    assert rows[0]["student_name"] == "测试学生"

    # 履约
    assert db.update_redemption_status(r["redemption_id"], "fulfilled",
                                       handled_by="admin", db_path=test_db_path) is True
    assert db.update_redemption_status(r["redemption_id"], "cancelled",
                                       db_path=test_db_path) is False, "已处理的不可重复处理"
    assert db.update_redemption_status(r["redemption_id"], "bogus",
                                       db_path=test_db_path) is False, "非法状态拒绝"
    assert db.list_reward_redemptions(status="requested", db_path=test_db_path) == []
    done = db.list_reward_redemptions(status="fulfilled", db_path=test_db_path)
    assert [d["id"] for d in done] == [r["redemption_id"]]


# ── P0-1 → P0-2 接线 ───────────────────────────────

def test_adopt_parent_report_awards_badge_once(test_db_path):
    """采纳上报 → 记一枚徽章；重复采纳（已处理）不再记。"""
    sid, _tid, mid = _setup(test_db_path)
    rep = db.create_parent_report(sid, mid, "wrong_answer", db_path=test_db_path)

    assert db.adopt_parent_report(rep["report_id"], db_path=test_db_path) is True
    data = db.get_badges(sid, db_path=test_db_path)
    assert data["total_count"] == 1
    assert data["badges"][0]["badge_key"] == "parent_report_adopted"

    assert db.adopt_parent_report(rep["report_id"], db_path=test_db_path) is False
    assert db.get_badges(sid, db_path=test_db_path)["total_count"] == 1


def test_reject_does_not_award_badge(test_db_path):
    sid, _tid, mid = _setup(test_db_path)
    rep = db.create_parent_report(sid, mid, "wrong_answer", db_path=test_db_path)
    db.reject_parent_report(rep["report_id"], db_path=test_db_path)
    assert db.get_badges(sid, db_path=test_db_path)["total_count"] == 0


# ── API ────────────────────────────────────────────

def test_public_badges_endpoint(client, test_db_path):
    sid, _tid, _mid = _setup(test_db_path)
    code = db.get_student(sid, db_path=test_db_path)["access_code"]
    db.award_badge(sid, "parent_report_adopted", db_path=test_db_path)

    r = client.get(f"/api/public/{code}/badges")
    assert r.status_code == 200
    body = r.get_json()
    assert body["badges"]["total_count"] == 1
    assert body["badges"]["milestones_configured"] == 0
    assert body["achievements"]["earned_count"] == 0


def test_redemptions_endpoints(client, admin_user, test_db_path):
    assert client.get("/api/redemptions").status_code == 401
    with client.session_transaction() as sess:
        sess["user_id"] = admin_user
        sess["user_role"] = "admin"
        sess["user_name"] = "admin"

    r = client.get("/api/redemptions")
    assert r.status_code == 200
    body = r.get_json()
    # 注意：会话共享测试库，其它用例可能已产生兑换单 → 只断言形状与规则计数，
    # 不断言全局为空（那会随用例执行顺序而碎）
    assert isinstance(body["redemptions"], list)
    assert body["rewards_configured"] == 0, "REWARD_CATALOG 默认未配置"

    filtered = client.get("/api/redemptions?status=fulfilled")
    assert filtered.status_code == 200
    assert isinstance(filtered.get_json()["redemptions"], list)
    assert client.get("/api/redemptions?status=bogus").status_code == 400
    assert client.post("/api/redemptions/999/status",
                       json={"status": "fulfilled"}).status_code == 400
    assert client.post("/api/redemptions/999/status",
                       json={"status": "nope"}).status_code == 400


def test_family_achievement_page_mentions_badges(client, test_db_path):
    """成就墙页面代码里带徽章渲染（规则未配置时提示"完善中"）。"""
    sid, _tid, _mid = _setup(test_db_path)
    code = db.get_student(sid, db_path=test_db_path)["access_code"]
    r = client.get(f"/s/{code}")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "徽章" in html and "兑换规则正在完善中" in html
