#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""取题服务：从未掌握错题取针对性练习题的唯一实现（P3-14）。

收拢此前重复三处的取题逻辑：
- /api/public/<code>/practice      （在线练习）
- /api/public/<code>/exercise-pdf  （可打印练习卷）
- grade_exercises 快照任务          （答案批改）

规则：
- 主路径：未掌握错题关联题（questions.source_mistake_id），保留关联以便
  批改后回写掌握度（record_practice）。
- 兜底路径：按知识点匹配题库（find_similar_questions）。题库题可能源自
  其他学生的错题，一律切断 source_mistake_id 关联，防止掌握度跨学生污染。
"""

import json

import db

# 主观/无法自包含题型：不进逐题练习（无标准判分或需原文上下文），
# 其错题整理由错题本内容提炼（周报/月度总结素材）。
# 阅读选择/判断/匹配等虽为客观题，但脱离原文无法自包含出题（会生成无选项残题），一并排除。
_SUBJECTIVE_TYPES = ("任务型阅读", "阅读理解", "阅读选择", "阅读判断", "阅读匹配",
                     "阅读表达", "信息匹配", "写作", "书面表达")


def _parse_kp(raw):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = []
    return raw if isinstance(raw, list) else [raw]


def get_practice_questions(student_id: int, limit: int = 15,
                           with_fallback: bool = True,
                           unmastered_only: bool = True,
                           db_path: str = None):
    """取学生针对性练习题。

    Args:
        student_id: 学生 ID。
        limit: 题目上限。
        with_fallback: 无关联题时是否按知识点从题库兜底。
        unmastered_only: 是否仅取未掌握错题的关联题
            （在线练习/练习卷用 True；答案批改用 False，以覆盖已发练习卷全集）。

    Returns:
        题目 dict 列表（knowledge_points 已解析；兜底题 source_mistake_id 为 None）。
    """
    db_path = db_path or db.DB_PATH
    mastery_clause = "AND m.consecutive_correct < 2" if unmastered_only else ""
    # 按题目自身题型过滤主观题（源错题题型可能与题目不一致，如任务型阅读题源自选词填空错题）
    subject_clause = ("AND q.question_type NOT IN ("
                      + ",".join("?" * len(_SUBJECTIVE_TYPES)) + ")")
    conn = db.get_connection(db_path)
    rows = conn.execute(f"""
        SELECT q.id, q.question_text, q.question_type, q.correct_answer,
               q.explanation, q.knowledge_points, q.difficulty, q.source_mistake_id
        FROM questions q
        JOIN mistakes m ON m.id = q.source_mistake_id
        WHERE m.student_id = ? AND q.enabled = 1 {mastery_clause} {subject_clause}
        ORDER BY q.created_at DESC
        LIMIT ?
    """, [student_id, *_SUBJECTIVE_TYPES, limit]).fetchall()
    conn.close()

    questions = []
    for q in rows:
        questions.append({
            "id": q["id"],
            "question_text": q["question_text"] or "",
            "question_type": q["question_type"] or "",
            "correct_answer": q["correct_answer"] or "",
            "explanation": q["explanation"] or "",
            "knowledge_points": _parse_kp(q["knowledge_points"]),
            "difficulty": q["difficulty"] or 2,
            "source_mistake_id": q["source_mistake_id"],
        })
    if questions or not with_fallback:
        return questions

    # 兜底：按知识点匹配题库题（切断来源关联，禁止回写掌握度）
    unmastered = db.get_unmastered_mistakes(student_id=student_id, db_path=db_path)
    all_kps = set()
    for m in unmastered:
        all_kps.update(_parse_kp(m.get("knowledge_points", [])))
    if not all_kps:
        return []
    bank = db.find_similar_questions(list(all_kps), limit=limit)
    for r in bank:
        r = dict(r) if not isinstance(r, dict) else r
        if r.get("question_type") in _SUBJECTIVE_TYPES:
            continue  # 主观题型不进逐题练习
        questions.append({
            "id": r.get("id"),
            "question_text": r.get("question_text", ""),
            "question_type": r.get("question_type", ""),
            "correct_answer": r.get("correct_answer", ""),
            "explanation": r.get("explanation", ""),
            "knowledge_points": _parse_kp(r.get("knowledge_points", [])),
            "difficulty": r.get("difficulty", 2),
            "source_mistake_id": None,
        })
    return questions
