# -*- coding: utf-8 -*-
"""作文批改：review_essay / node_essay_review / 报告渲染。"""


def test_review_essay_demo_structure(demo_mode):
    from skills_bridge import review_essay
    r = review_essay("Write about your weekend",
                     "I go to school by foot every day.")
    assert isinstance(r, dict)
    assert isinstance(r.get("errors"), list)
    assert r["errors"], "demo 数据应有错误标注"
    assert "suggestion" in r["errors"][0]
    assert isinstance(r.get("evaluation"), dict)
    assert r.get("score_suggestion", {}).get("band")


def test_render_essay_review():
    from report_templates import render_essay_review
    review = {
        "errors": [{"quote": "She don't like math.", "type": "语法",
                    "issue": "第三人称单数", "suggestion": "She doesn't like math."}],
        "evaluation": {"content": "内容切题", "structure": "结构完整",
                       "language": "基本准确", "vocabulary": "基础可"},
        "score_suggestion": {"band": "二档（13-15/20）", "basis": "内容完整"},
        "strengths": ["要点覆盖完整"],
        "advice": ["多用连接词"],
    }
    html = render_essay_review({"name": "小明", "grade": "初二"},
                               {"question_text": "Write about your weekend",
                                "user_answer": "She don't like math."}, review)
    assert "作文批改" in html
    assert "逐句批注" in html
    assert "She doesn't like math." in html
    assert "二档（13-15/20）" in html
    assert "值得肯定" in html


def test_node_essay_review_triggers(demo_mode, test_db_path, monkeypatch, tmp_path):
    """写作类错题触发批改并生成报告文件；非写作类不触发。"""
    import db
    from pipeline import stages
    monkeypatch.setattr(stages, "UPLOAD_DIR", str(tmp_path / "uploads"))
    sid = db.create_student({"name": "作文学生", "grade": "高二"}, db_path=test_db_path)
    ctx = stages.Ctx({"id": 900001, "student_id": sid, "input_data": {},
                      "week_start": "2026-08-10"}, test_db_path)
    ctx.student = db.get_student(sid)
    ctx.mistakes = [{
        "question_text": "Write about your weekend",
        "question_type": "书面表达",
        "user_answer": "I go to school by foot every day. She don't like math.",
    }]
    stages.node_essay_review(ctx)
    assert ctx.essay_review_file_id is not None
    f = db.get_file(ctx.essay_review_file_id, db_path=test_db_path)
    assert f["file_type"] == "essay_review"

    # 非写作类错题 → 不触发
    ctx2 = stages.Ctx({"id": 900002, "student_id": sid, "input_data": {},
                       "week_start": "2026-08-10"}, test_db_path)
    ctx2.student = db.get_student(sid)
    ctx2.mistakes = [{"question_text": "What ___ you doing?",
                      "question_type": "语法填空", "user_answer": "was"}]
    stages.node_essay_review(ctx2)
    assert ctx2.essay_review_file_id is None


def test_node_essay_review_skips_unanswered(demo_mode, test_db_path, monkeypatch, tmp_path):
    """写作类但未作答 → 不触发批改。"""
    import db
    from pipeline import stages
    monkeypatch.setattr(stages, "UPLOAD_DIR", str(tmp_path / "uploads2"))
    sid = db.create_student({"name": "未答作文"}, db_path=test_db_path)
    ctx = stages.Ctx({"id": 900003, "student_id": sid, "input_data": {},
                      "week_start": "2026-08-10"}, test_db_path)
    ctx.student = db.get_student(sid)
    ctx.mistakes = [{"question_text": "Write about your weekend",
                     "question_type": "书面表达", "user_answer": "未作答"}]
    stages.node_essay_review(ctx)
    assert ctx.essay_review_file_id is None
