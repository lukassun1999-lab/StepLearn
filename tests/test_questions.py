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
