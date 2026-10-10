# -*- coding: utf-8 -*-
"""练习记录按「题目」去重，而非按「错题」去重。

背景：一个错题会派生多道练习（如 bad→worse、good→better 两道填空题同属
一个语法填空错题）。原实现按 mistake_id 做每日去重，导致同一错题的第 2 道
练习被当成重复提交而不写入 practice_records——学生明明做了却没留痕，
报告/练习历史里看不到。

防刷的初衷是「同一道题重复提交不计分」，所以去重键应当是 question_id。
"""

import json

import pytest


def test_two_practices_of_same_mistake_both_recorded(
    client, sample_student, test_db_path, monkeypatch, tmp_path):
    """同一错题的两道练习，提交后都应写入 practice_records。"""
    import db
    from db import init_db, add_file

    init_db(test_db_path)

    # 复用该学生已有的 access_code（公开免登录入口需要它）
    stu = db.get_student(sample_student, db_path=test_db_path)
    code = stu["access_code"]
    assert code
    mid = db.add_mistake(
        student_id=sample_student,
        question="I think reading is ___ (good) than playing games.",
        question_type="语法填空",
        correct_answer="better",
        user_answer="beter",
        knowledge_points=["形容词比较级"],
        difficulty=2,
        db_path=test_db_path,
    )
    # 同一个错题派生两道练习（source_mistake_id 相同）
    import sqlite3 as _sq
    _c = _sq.connect(test_db_path)
    q1 = q2 = None
    for text, ans in [("This book is much ___ (interesting) than that one.",
                       "more interesting"),
                      ("My handwriting is ___ (bad) than yours.", "worse")]:
        cur = _c.execute(
            "INSERT INTO questions (question_text, question_type, correct_answer,"
            " knowledge_points, difficulty, source_mistake_id, enabled)"
            " VALUES (?,?,?,?,?,?,1)",
            [text, "语法填空", ans, json.dumps(["形容词比较级"]), 2, mid])
        if q1 is None:
            q1 = cur.lastrowid
        else:
            q2 = cur.lastrowid
    _c.commit()
    _c.close()

    def _submit(qid, answer):
        return client.post(f"/api/public/{code}/practice/submit",
                           json={"question_id": qid, "answer": answer})

    r1 = _submit(q1, "more interesting")
    r2 = _submit(q2, "worse")
    assert r1.status_code == 200 and r2.status_code == 200

    import sqlite3
    conn = sqlite3.connect(test_db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT question_id, user_answer FROM practice_records "
        "WHERE mistake_id = ? ORDER BY id", [mid]).fetchall()
    conn.close()
    assert len(rows) == 2, "同一错题的两道练习都应记录"
    assert [r["user_answer"] for r in rows] == ["more interesting", "worse"]
