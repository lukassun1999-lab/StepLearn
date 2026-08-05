# -*- coding: utf-8 -*-
"""端到端验证：两周完整链路 → 周报"卡点变化"板块。

- 第一周：错题以词汇为主（4 vocab + 1 grammar）→ 画像 primary=vocab
- 第二周：错题以语法为主（1 vocab + 4 grammar）→ 画像 primary=grammar
- 周报应显示"上周的「词汇」补上来了，本周新卡点是「语法」"（卡点迁移叙事）

demo 模式运行，analyze_mistakes 打桩返回定制错题集（不产生真实 LLM 调用）。
"""

import os

import pytest

W1 = "2026-07-27"
W2 = "2026-08-03"


@pytest.fixture
def env(test_db_path, demo_mode, monkeypatch, tmp_path):
    """隔离 uploads 目录 + 打桩 analyze_mistakes，返回 (monkeypatch, upload_dir)。"""
    from pipeline import stages
    upload_dir = str(tmp_path / "uploads")
    monkeypatch.setattr(stages, "UPLOAD_DIR", upload_dir)
    return monkeypatch, upload_dir


def _make_student_and_file(upload_dir):
    import db
    sid = db.create_student({
        "name": "卡点验证", "grade": "高二", "school_type": "住校",
        "english_score": 100, "target_score": 120, "plan": "unlimited",
    })
    d = os.path.join(upload_dir, str(sid), "test_paper")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "fake.jpg"), "wb") as f:
        f.write(b"\xff\xd8\xff\xd9")
    file_id = db.add_file(
        student_id=sid, uploader_role="parent", file_type="test_paper",
        filename="fake.jpg", original_filename="fake.jpg",
        week_start=db.get_week_start(), file_size=4, mime_type="image/jpeg")
    return db, sid, file_id


def _mk_mistakes(cause_counts):
    """按 {cause: count} 构造错题集。"""
    mistakes = []
    for cause, n in cause_counts.items():
        for i in range(n):
            mistakes.append({
                "question_text": f"{cause} 错题 {i + 1}：What ___ you doing yesterday?",
                "question_type": "语法填空",
                "correct_answer": "were",
                "user_answer": "was",
                "explanation": f"考察{cause}相关规则",
                "knowledge_points": ["动词时态"],
                "difficulty": 2,
                "error_cause": cause,
                "cause_evidence": "模拟证据",
            })
    return mistakes


def _run_week(db, sid, file_id, week_start, mistakes, monkeypatch):
    """跑一周完整链路（grade_only），返回 output。"""
    from pipeline import cycle_pipeline, stages

    def fake_analyze(ocr_text, task_id=None):
        return {"mistakes": mistakes, "summary": {
            "total_mistakes": len(mistakes), "by_type": {},
            "top_weak_points": [], "overall_assessment": "test",
        }}

    monkeypatch.setattr(stages, "analyze_mistakes", fake_analyze)
    task_id = db.create_task(sid, "weekly", {
        "file_ids": [file_id], "stage": "grade_only", "quota_charged": True,
    }, week_start=week_start)
    task = db.get_task(task_id, db.DB_PATH)
    return cycle_pipeline.run_weekly(task, db.DB_PATH)


def test_weekly_report_cause_trend_e2e(env):
    monkeypatch, upload_dir = env
    db, sid, file_id = _make_student_and_file(upload_dir)

    # ── 第一周：词汇为主 ──
    out1 = _run_week(db, sid, file_id, W1, _mk_mistakes({"vocab": 4, "grammar": 1}),
                     monkeypatch)
    assert out1["mistakes_count"] == 5
    profile1 = db.get_cause_profile(sid)
    assert profile1 is not None and profile1["primary_cause"] == "vocab"
    hist1 = db.get_cause_profile_history(sid, week_start=W1)
    assert hist1 is not None and hist1["primary_cause"] == "vocab"
    assert hist1["total_count"] == 5

    # ── 第二周：语法为主（累积 v6:g7 使 primary 迁移到 grammar；
    #            本周 grammar 占 6/8=75% < 上周 vocab 80% → "补上来了"叙事）──
    out2 = _run_week(db, sid, file_id, W2, _mk_mistakes({"vocab": 2, "grammar": 6}),
                     monkeypatch)
    assert out2["mistakes_count"] == 8
    profile2 = db.get_cause_profile(sid)
    assert profile2["primary_cause"] == "grammar"
    hist2 = db.get_cause_profile_history(sid, week_start=W2)
    assert hist2["primary_cause"] == "grammar"

    # ── 周报：report_only 节点，只读历史生成"卡点变化" ──
    from pipeline import engine
    task_id = db.create_task(sid, "weekly", {"stage": "report_only"},
                             week_start=W2)
    task = db.get_task(task_id, db.DB_PATH)
    out = engine.run_weekly_report_node(task, db.DB_PATH)
    assert out["weekly_report_file_id"] is not None

    conn = db.get_connection(db.DB_PATH)
    frow = conn.execute(
        "SELECT * FROM files WHERE id = ?", [out["weekly_report_file_id"]]).fetchone()
    conn.close()
    html_path = os.path.join(upload_dir, str(sid), "weekly_pdf", frow["filename"])
    with open(html_path, encoding="utf-8") as f:
        html = f.read()

    # 卡点迁移叙事：上周词汇补上来了，本周新卡点是语法
    assert "卡点变化" in html
    assert "补上来了" in html
    assert "词汇" in html and "语法" in html
    assert "上周核心卡点" in html and "本周核心卡点" in html
