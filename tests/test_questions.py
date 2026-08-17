# -*- coding: utf-8 -*-
"""P3-14：取题服务 domain/questions.py 单测。"""


def _make_mistake_and_question(db, sid, test_db_path, mastered=False):
    mid = db.add_mistake(
        student_id=sid, source_exam="单测卷",
        question="2+2=? A.3 B.4 C.5 D.6", question_type="选择题",
        correct_answer="B", user_answer="A",
        explanation="2+2=4", knowledge_points=["四则运算"],
        difficulty=2, db_path=test_db_path)
    qid = db.save_question({
        "question_text": "3+3=? A.5 B.6 C.7 D.8",
        "question_type": "选择题",
        "correct_answer": "B",
        "explanation": "3+3=6",
        "knowledge_points": ["四则运算"],
        "difficulty": 2,
        "source": "llm",
        "source_mistake_id": mid,
    }, db_path=test_db_path)
    if mastered:
        conn = db.get_connection(test_db_path)
        conn.execute("UPDATE mistakes SET consecutive_correct = 2 WHERE id = ?", [mid])
        conn.commit()
        conn.close()
    return mid, qid


def test_primary_path_returns_linked_questions(test_db_path, sample_student):
    import db
    from domain import questions as q_mod

    mid, qid = _make_mistake_and_question(db, sample_student, test_db_path)

    qs = q_mod.get_practice_questions(sample_student, db_path=test_db_path)
    assert len(qs) == 1
    assert qs[0]["id"] == qid
    # 主路径保留来源关联（批改/练习后回写掌握度用）
    assert qs[0]["source_mistake_id"] == mid
    assert qs[0]["knowledge_points"] == ["四则运算"]


def test_mastered_mistake_filtered_by_default(test_db_path, sample_student):
    import db
    from domain import questions as q_mod

    _make_mistake_and_question(db, sample_student, test_db_path, mastered=True)

    # 在线练习/练习卷口径：已掌握不再出
    assert q_mod.get_practice_questions(sample_student, db_path=test_db_path) == []
    # 批改口径（unmastered_only=False）：覆盖已发练习卷全集
    qs = q_mod.get_practice_questions(
        sample_student, unmastered_only=False, db_path=test_db_path)
    assert len(qs) == 1


def test_fallback_strips_source_link(test_db_path, sample_student):
    import db
    from domain import questions as q_mod

    # 唯一知识点名，避免会话级共享库中其他测试题目的 LIKE 污染
    kp = "定语从句-单测专用知识点"

    # 未掌握错题（无关联题）
    db.add_mistake(
        student_id=sample_student, source_exam="单测卷",
        question="The book ___ I bought is great.",
        question_type="语法填空", correct_answer="which", user_answer="what",
        explanation="定语从句", knowledge_points=[kp],
        difficulty=2, db_path=test_db_path)
    # 题库里的同知识点题（无 source_mistake_id）
    db.save_question({
        "question_text": "The movie ___ we watched was boring.",
        "question_type": "语法填空",
        "correct_answer": "which",
        "explanation": "定语从句",
        "knowledge_points": [kp],
        "difficulty": 2,
        "source": "llm",
        "source_mistake_id": None,
    }, db_path=test_db_path)

    qs = q_mod.get_practice_questions(sample_student, db_path=test_db_path)
    assert len(qs) == 1
    # 兜底题必须切断来源关联，防止掌握度跨学生污染
    assert qs[0]["source_mistake_id"] is None

    # 关闭兜底则返回空
    assert q_mod.get_practice_questions(
        sample_student, with_fallback=False, db_path=test_db_path) == []


def test_empty_student_returns_empty(test_db_path, sample_student):
    from domain import questions as q_mod

    assert q_mod.get_practice_questions(sample_student, db_path=test_db_path) == []


def test_inflection_missing_hint():
    """词形转换题缺括号提示词检测（实测：highest 无 high 提示，学生无法作答）。"""
    from skills_bridge import _inflection_missing_hint
    # 最高级无提示词 → 坏题
    assert _inflection_missing_hint({
        "question_type": "语法填空", "correct_answer": "highest",
        "question_text": "Mount Tai is the ___ mountain in Shandong."}) is True
    # 带括号提示词 → 正常
    assert _inflection_missing_hint({
        "question_type": "语法填空", "correct_answer": "highest",
        "question_text": "Mount Tai is the ___ (high) mountain in Shandong."}) is False
    # 虚词答案（连词）→ 正常，无需提示词
    assert _inflection_missing_hint({
        "question_type": "语法填空", "correct_answer": "so that",
        "question_text": "She studied hard ___ she could pass."}) is False
    # 复数词形无提示词 → 坏题
    assert _inflection_missing_hint({
        "question_type": "单句填空", "correct_answer": "experiences",
        "question_text": "My ___ in China were happy."}) is True
    # 多词答案（代词指代 the ones）→ 非词形转换，正常
    assert _inflection_missing_hint({
        "question_type": "语法填空", "correct_answer": "the ones",
        "question_text": "These athletes are ___ who broke the records."}) is False
    # 有选项题型不适用该校验
    assert _inflection_missing_hint({
        "question_type": "单项选择", "correct_answer": "B",
        "question_text": "___ is the best.\nA. high\nB. highest"}) is False
    # 非 dict / 非填空类 → False
    assert _inflection_missing_hint(None) is False
    assert _inflection_missing_hint({"question_type": "完形填空",
                                     "correct_answer": "highest",
                                     "question_text": "q"}) is False


def test_is_excluded_type():
    """无法自包含题型排除：听力/对话/填空/写作（含模糊匹配）；阅读类由 passage 单独判断。"""
    from skills_bridge import _is_excluded_type
    # 排除
    for t in ("补全对话", "听力填空", "听力选择", "听力判断", "听短文填空", "听短文选择",
              "填空题", "情景交际", "书面表达"):
        assert _is_excluded_type(t), t
    # 模糊匹配：新出现的听力/对话标签变体
    assert _is_excluded_type("听力匹配题") is True
    assert _is_excluded_type("听短文回答问题") is True
    assert _is_excluded_type("补全对话七选五") is True
    # 阅读类不再一刀切排除（generate_questions 按 passage 有无判断）
    for t in ("阅读理解", "阅读选择", "阅读判断", "阅读匹配", "阅读表达填空",
              "任务型阅读", "信息匹配", "匹配题"):
        assert _is_excluded_type(t) is False, t
    # 保留（可自包含）
    for t in ("语法填空", "选词填空", "单项选择", "单项选择题", "完形填空",
              "词汇拼写", "单句填空"):
        assert _is_excluded_type(t) is False, t


def test_option_types_include_variants():
    """选项题型标签变体（单项选择题）应被识别为有选项题型。"""
    from skills_bridge import _OPTION_TYPES
    assert "单项选择题" in _OPTION_TYPES
    assert "单项选择" in _OPTION_TYPES


# ── 阅读带原文练习（passage）──

def test_add_mistake_saves_passage(test_db_path):
    import db
    sid = db.create_student({"name": "短文学生"}, db_path=test_db_path)
    mid = db.add_mistake(
        student_id=sid, source_exam="t", question="Q1?",
        question_type="阅读选择", correct_answer="B", user_answer="A",
        passage="Tom's grandmother has been in hospital for three months.",
        db_path=test_db_path)
    assert db.get_mistake(mid, db_path=test_db_path)["passage"].startswith("Tom's")


def test_generate_questions_reading_with_passage(demo_mode, test_db_path):
    """阅读类错题带短文 → 生成带原文的练习。"""
    from skills_bridge import generate_questions
    passage = ("Tom's grandmother has been in hospital for three months. "
               "She needs daily care from the family.")
    mistakes = [{
        "id": 1001,
        "question_text": "Tom's grandmother has been in hospital for three months.",
        "question_type": "阅读判断", "correct_answer": "B", "user_answer": "A",
        "knowledge_points": ["阅读细节理解"], "difficulty": 2, "passage": passage,
    }]
    result = generate_questions(mistakes, task_id=None)
    assert result["questions"], "带短文的阅读错题应生成练习"
    for q in result["questions"]:
        assert q.get("passage") == passage  # 生成题附带短文原文


def test_generate_questions_reading_without_passage(demo_mode, test_db_path):
    """阅读类错题无短文 → 无法自包含，排除。"""
    from skills_bridge import generate_questions
    mistakes = [{
        "id": 1002,
        "question_text": "Tom's grandmother has been in hospital.",
        "question_type": "阅读判断", "correct_answer": "B", "user_answer": "A",
        "knowledge_points": ["阅读细节理解"], "difficulty": 2,
    }]
    result = generate_questions(mistakes, task_id=None)
    assert result["questions"] == []


def test_practice_api_returns_passage(demo_mode, test_db_path):
    """取题：阅读题带短文才返回，且返回短文原文。"""
    import db
    from domain import questions as q_mod
    sid = db.create_student({"name": "阅读练习"}, db_path=test_db_path)
    mid = db.add_mistake(
        student_id=sid, source_exam="t", question="Q",
        question_type="阅读选择", correct_answer="B", user_answer="A",
        passage="Trees are important for the environment.",
        db_path=test_db_path)
    db.save_question({
        "question_text": "What is the passage about?\nA. trees\nB. water",
        "question_type": "阅读选择", "correct_answer": "A",
        "explanation": "x", "knowledge_points": ["主旨大意"],
        "difficulty": 2, "source_mistake_id": mid,
    }, db_path=test_db_path)
    qs = q_mod.get_practice_questions(sid, db_path=test_db_path)
    assert len(qs) == 1
    assert qs[0]["passage"] == "Trees are important for the environment."

    # 阅读类无短文 → 不返回（无法作答）
    mid2 = db.add_mistake(
        student_id=sid, source_exam="t", question="Q2",
        question_type="阅读判断", correct_answer="B", user_answer="A",
        db_path=test_db_path)
    db.save_question({
        "question_text": "Q2 判断题", "question_type": "阅读判断",
        "correct_answer": "B", "explanation": "x",
        "knowledge_points": ["阅读细节理解"], "difficulty": 2,
        "source_mistake_id": mid2,
    }, db_path=test_db_path)
    qs = q_mod.get_practice_questions(sid, db_path=test_db_path)
    assert len(qs) == 1  # 无短文的阅读题被过滤


def test_exercise_sheet_renders_passage():
    """练习卷渲染短文。"""
    from report_templates import render_exercise_sheet
    html = render_exercise_sheet("小明", [{
        "question_text": "What is the passage about?",
        "question_type": "阅读选择", "correct_answer": "A",
        "knowledge_points": ["主旨大意"], "difficulty": 2,
        "options": ["A. trees", "B. water"],
        "passage": "Trees are important for the environment.",
    }])
    assert "阅读短文" in html
    assert "Trees are important" in html


def test_exercise_sheet_no_duplicated_options():
    """练习卷选项不重复：题干已内嵌选项时不再渲染选项区（含 LLM 裸字母脏数据）。"""
    from report_templates import render_exercise_sheet
    html = render_exercise_sheet("小明", [{
        "question_text": "What is the passage about?\n   A. Trees help the soil.\n"
                        "   B. Water is important.\n   C. Birds need trees.\n"
                        "   D. Forests are large.",
        "question_type": "阅读选择", "correct_answer": "A",
        "knowledge_points": ["主旨大意"], "difficulty": 2,
        "options": ["A", "B", "C", "D"],   # LLM 可能返回裸字母选项
        "passage": "Trees are important.",
    }])
    # 选项全文只出现一次（内嵌在题干里），不重复渲染
    assert html.count("Trees help the soil.") == 1
    assert html.count("Water is important.") == 1
    # 裸字母选项块被丢弃，不出现 ">A</div>" 之类的空壳
    assert ">A</div>" not in html and ">B</div>" not in html


def test_exercise_sheet_renders_options_when_not_embedded():
    """题干未内嵌选项时，选项区正常渲染（dict 形状）。"""
    from report_templates import render_exercise_sheet
    html = render_exercise_sheet("小明", [{
        "question_text": "Choose the best word.",
        "question_type": "选择题", "correct_answer": "A",
        "knowledge_points": [], "difficulty": 2,
        "options": [{"key": "A", "text": "trees"}, {"key": "B", "text": "water"},
                    {"key": "C", "text": "soil"}, {"key": "D", "text": "forest"}],
    }])
    assert "A. trees" in html and "D. forest" in html


def test_fix_generated_answer_format():
    """P3 质量硬化：填空类题型答案格式校验（禁止裸字母）。"""
    from skills_bridge import _fix_generated_answer_format

    # 填空类 + 裸字母 → 回退源错题答案
    q = {"question_type": "语法填空", "correct_answer": "A"}
    out = _fix_generated_answer_format(q, source_answer="one of them")
    assert out["correct_answer"] == "one of them"

    # 源答案带选项字母前缀 → 去除前缀
    q = {"question_type": "语法填空", "correct_answer": "B"}
    out = _fix_generated_answer_format(q, source_answer="B. full of")
    assert out["correct_answer"] == "full of"

    # 填空类 + 已是答案内容 → 不动
    q = {"question_type": "语法填空", "correct_answer": "full of"}
    out = _fix_generated_answer_format(q, source_answer="full of")
    assert out["correct_answer"] == "full of"

    # 选择题 + 字母答案 → 保留字母
    q = {"question_type": "选择题", "correct_answer": "B"}
    out = _fix_generated_answer_format(q, source_answer="full of")
    assert out["correct_answer"] == "B"

    # 填空类 + 无源答案 → 保持原样不崩溃
    q = {"question_type": "语法填空", "correct_answer": "A"}
    out = _fix_generated_answer_format(q, source_answer="")
    assert out["correct_answer"] == "A"
