# -*- coding: utf-8 -*-
"""家长上报 → 运营采纳 → 进模式池（P0-1 + P0-3）。

P0-1：家庭端「这题有问题」上报入口，落 status='pending'。
P0-3：采纳后才写 ai_feedback_patterns，并被 get_recent_correction_hints
      取到注入批改 prompt —— 未采纳的上报不得污染提示词池。

隔离约定：feedback pattern 是**全局**表（跨学生），因此按 DEVELOPMENT.md
的测试约定用唯一知识点名隔离断言。
"""

import uuid


def _setup(db_path, knowledge_points=None):
    """建学生 + 任务 + 错题，返回 (student_id, task_id, mistake_id)。"""
    import db

    sid = db.create_student({"name": "上报测试", "grade": "初二",
                             "plan": "trial"}, db_path=db_path)
    tid = db.create_task(sid, "weekly", {"stage": "report_only"},
                         week_start=db.get_week_start(), db_path=db_path)
    mid = db.add_mistake(
        student_id=sid, source_exam="t", question="Q",
        question_type="单项选择", correct_answer="A", user_answer="B",
        knowledge_points=knowledge_points, source_task_id=tid, db_path=db_path)
    return sid, tid, mid


def _kp():
    """每次调用返回唯一知识点，避免全局 pattern 表跨测试串味。"""
    return [f"KP_{uuid.uuid4().hex[:8]}"]


# ── P0-1 上报 ───────────────────────────────────────

def test_report_creates_pending_without_touching_data(test_db_path):
    """上报只落 pending：错题数据不变、模式池不进。"""
    import db

    kp = _kp()
    sid, _, mid = _setup(test_db_path, knowledge_points=kp)
    before = db.get_mistake(mid, db_path=test_db_path)

    r = db.create_parent_report(sid, mid, "wrong_answer",
                                note="老师说答案是 C",
                                suggested_value="C", db_path=test_db_path)
    assert r["ok"] and r["report_id"] and not r["duplicate"]

    after = db.get_mistake(mid, db_path=test_db_path)
    assert after["correct_answer"] == before["correct_answer"], "上报不得直接改数据"

    row = db.get_correction(r["report_id"], db_path=test_db_path)
    assert row["status"] == "pending"
    assert row["content_type"] == "mistake"
    assert row["target_field"] == "correct_answer"
    assert row["corrected_value"] == "C"
    assert row["original_value"] == "A"
    assert row["reason"] == "老师说答案是 C"

    # 未采纳 → 不进提示词池
    assert db.get_recent_correction_hints(kp, "mistake", db_path=test_db_path) == ""


def test_report_is_idempotent_per_field(test_db_path):
    """同一 (错题, 字段) 重复上报返回同一记录；换字段则新建。"""
    import db

    sid, _, mid = _setup(test_db_path)
    a = db.create_parent_report(sid, mid, "wrong_answer", db_path=test_db_path)
    b = db.create_parent_report(sid, mid, "wrong_answer", db_path=test_db_path)
    assert b["duplicate"] is True
    assert b["report_id"] == a["report_id"]

    c = db.create_parent_report(sid, mid, "wrong_explanation", db_path=test_db_path)
    assert c["duplicate"] is False
    assert c["report_id"] != a["report_id"]


def test_report_rejects_other_students_mistake(test_db_path):
    """不能上报别人的错题（家庭端免登录，必须服务端校验归属）。"""
    import db

    sid, _, mid = _setup(test_db_path)
    other = db.create_student({"name": "别人", "grade": "初二", "plan": "trial"},
                              db_path=test_db_path)
    r = db.create_parent_report(other, mid, "wrong_answer", db_path=test_db_path)
    assert r["ok"] is False and r["error"] == "mistake_not_found"


def test_report_rejects_unknown_issue(test_db_path):
    import db

    sid, _, mid = _setup(test_db_path)
    r = db.create_parent_report(sid, mid, "not_a_real_issue", db_path=test_db_path)
    assert r["ok"] is False and r["error"] == "unknown_issue"


def test_report_daily_cap(test_db_path):
    """每学生每日上报上限（防刷）。"""
    import db
    from db.operations import PARENT_REPORT_DAILY_CAP

    sid, tid, _ = _setup(test_db_path)
    made = 0
    for i in range(PARENT_REPORT_DAILY_CAP + 3):
        mid = db.add_mistake(student_id=sid, source_exam="t", question=f"Q{i}",
                             question_type="单项选择", correct_answer="A",
                             user_answer="B", source_task_id=tid,
                             db_path=test_db_path)
        r = db.create_parent_report(sid, mid, "wrong_answer", db_path=test_db_path)
        if r["ok"]:
            made += 1
    assert made == PARENT_REPORT_DAILY_CAP

    mid = db.add_mistake(student_id=sid, source_exam="t", question="Qx",
                         question_type="单项选择", correct_answer="A",
                         user_answer="B", source_task_id=tid, db_path=test_db_path)
    r = db.create_parent_report(sid, mid, "wrong_answer", db_path=test_db_path)
    assert r["error"] == "rate_limited"


# ── P0-3 采纳 → 模式池 → prompt ──────────────────────

def test_adopt_applies_value_and_feeds_pattern_pool(test_db_path):
    """采纳：覆盖目标字段 + 写 pattern + 可被 prompt 提示串取到。"""
    import db

    kp = _kp()
    sid, _, mid = _setup(test_db_path, knowledge_points=kp)
    r = db.create_parent_report(sid, mid, "wrong_answer",
                                suggested_value="C", db_path=test_db_path)

    assert db.adopt_parent_report(r["report_id"], reviewed_by="admin",
                                  db_path=test_db_path) is True

    assert db.get_mistake(mid, db_path=test_db_path)["correct_answer"] == "C"
    assert db.get_correction(r["report_id"], db_path=test_db_path)["status"] == "applied"

    hints = db.get_recent_correction_hints(kp, "mistake", db_path=test_db_path)
    assert "老师纠错参考" in hints
    assert "答案错误" in hints and "C" in hints


def test_adopt_can_override_parent_value(test_db_path):
    """运营可在采纳时改写家长给的答案（家长可能给错）。"""
    import db

    sid, _, mid = _setup(test_db_path)
    r = db.create_parent_report(sid, mid, "wrong_answer",
                                suggested_value="家长猜的", db_path=test_db_path)
    db.adopt_parent_report(r["report_id"], corrected_value="D",
                           db_path=test_db_path)
    assert db.get_mistake(mid, db_path=test_db_path)["correct_answer"] == "D"


def test_adopt_wrong_grading_retracts_mistake(test_db_path):
    """「孩子其实做对了」采纳后撤销该错题：判定为已掌握，离开复习队列。"""
    import db

    kp = _kp()
    sid, _, mid = _setup(test_db_path, knowledge_points=kp)
    r = db.create_parent_report(sid, mid, "wrong_grading",
                                note="孩子选的就是 A", db_path=test_db_path)
    assert db.adopt_parent_report(r["report_id"], db_path=test_db_path) is True

    m = db.get_mistake(mid, db_path=test_db_path)
    assert m["consecutive_correct"] == 2 and m["mastery_level"] == 100

    progress = db.get_review_progress(sid, db_path=test_db_path)
    assert progress["mastered"] == 1 and progress["active"] == 0

    hints = db.get_recent_correction_hints(kp, "mistake", db_path=test_db_path)
    assert "批改判定错误" in hints


def test_reject_keeps_data_and_pool_clean(test_db_path):
    """驳回：不改数据、不进模式池。"""
    import db

    kp = _kp()
    sid, _, mid = _setup(test_db_path, knowledge_points=kp)
    r = db.create_parent_report(sid, mid, "wrong_answer",
                                suggested_value="Z", db_path=test_db_path)

    assert db.reject_parent_report(r["report_id"], reviewed_by="admin",
                                   reason="核对后答案无误",
                                   db_path=test_db_path) is True
    assert db.get_mistake(mid, db_path=test_db_path)["correct_answer"] == "A"
    row = db.get_correction(r["report_id"], db_path=test_db_path)
    assert row["status"] == "rejected"
    assert row["reason"] == "核对后答案无误"
    assert db.get_recent_correction_hints(kp, "mistake", db_path=test_db_path) == ""


def test_adopt_requires_pending_status(test_db_path):
    """已采纳/已驳回的记录不能重复处理（保证采纳与驳回互斥）。"""
    import db

    sid, _, mid = _setup(test_db_path)
    r = db.create_parent_report(sid, mid, "wrong_answer", db_path=test_db_path)
    assert db.adopt_parent_report(r["report_id"], db_path=test_db_path) is True
    assert db.adopt_parent_report(r["report_id"], db_path=test_db_path) is False
    assert db.reject_parent_report(r["report_id"], db_path=test_db_path) is False


def test_reject_then_report_again_is_allowed(test_db_path):
    """驳回后同一字段可再次上报（pending 已消费，不触发幂等短路）。"""
    import db

    sid, _, mid = _setup(test_db_path)
    a = db.create_parent_report(sid, mid, "wrong_answer", db_path=test_db_path)
    db.reject_parent_report(a["report_id"], db_path=test_db_path)
    b = db.create_parent_report(sid, mid, "wrong_answer", db_path=test_db_path)
    assert b["ok"] and not b["duplicate"] and b["report_id"] != a["report_id"]


# ── 运营端待处理列表 ────────────────────────────────

def test_pending_list_and_count(test_db_path):
    import db

    sid, _, mid = _setup(test_db_path)
    before = db.get_pending_report_count(db_path=test_db_path)
    r = db.create_parent_report(sid, mid, "wrong_answer", note="求解",
                                db_path=test_db_path)

    assert db.get_pending_report_count(db_path=test_db_path) == before + 1
    rows = db.get_pending_reports(db_path=test_db_path)
    mine = [x for x in rows if x["id"] == r["report_id"]]
    assert len(mine) == 1
    assert mine[0]["student_name"] == "上报测试"
    assert mine[0]["question"] == "Q"

    db.adopt_parent_report(r["report_id"], db_path=test_db_path)
    assert db.get_pending_report_count(db_path=test_db_path) == before
