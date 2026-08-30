# -*- coding: utf-8 -*-
"""SM-2 间隔重复调度测试（Ebbinghaus 阶梯 × 个人难度系数）。

掌握判定仍是"连对 2 次"（consecutive_correct >= 2），SM-2 只影响排程：
答对 ease +0.05（上限 3.0）→ 间隔拉长；答错 ease -0.20（下限 1.3）→ 间隔缩短。
"""

from datetime import datetime

import pytest

import db
from db.learning import (
    _EBBINGHAUS_INTERVALS,
    _EASE_DEFAULT,
    _EASE_MAX,
    _EASE_MIN,
    _MAX_REVIEW_STAGE,
    _next_review_at,
    record_practice,
)


def _add(db_path, sid):
    return db.add_mistake(
        student_id=sid, source_exam="t", question="Q",
        question_type="单项选择", correct_answer="A", user_answer="B",
        db_path=db_path)


def test_correct_advances_stage_and_raises_ease(test_db_path, sample_student):
    mid = _add(test_db_path, sample_student)
    assert record_practice(mid, "A", True, db_path=test_db_path)

    m = db.get_mistake(mid, db_path=test_db_path)
    assert m["review_stage"] == 1
    assert m["consecutive_correct"] == 1
    assert m["ease_factor"] == pytest.approx(_EASE_DEFAULT + 0.05)
    # 间隔 = 基础间隔 × ease/2.5（答对后略长于固定阶梯）
    assert m["review_interval_hours"] == pytest.approx(
        _EBBINGHAUS_INTERVALS[1] * m["ease_factor"] / _EASE_DEFAULT)


def test_wrong_lowers_ease_and_resets_stage(test_db_path, sample_student):
    mid = _add(test_db_path, sample_student)
    record_practice(mid, "A", True, db_path=test_db_path)
    record_practice(mid, "B", False, db_path=test_db_path)

    m = db.get_mistake(mid, db_path=test_db_path)
    assert m["consecutive_correct"] == 0
    assert m["review_stage"] == 1  # 答错部分回退，不清零
    assert m["ease_factor"] == pytest.approx(_EASE_DEFAULT + 0.05 - 0.20)
    assert m["review_interval_hours"] == pytest.approx(
        _EBBINGHAUS_INTERVALS[1] * m["ease_factor"] / _EASE_DEFAULT)


def test_ease_floor_on_repeated_wrong(test_db_path, sample_student):
    mid = _add(test_db_path, sample_student)
    for _ in range(10):
        record_practice(mid, "B", False, db_path=test_db_path)
    m = db.get_mistake(mid, db_path=test_db_path)
    assert m["ease_factor"] == pytest.approx(_EASE_MIN)


def test_ease_cap_on_repeated_correct(test_db_path, sample_student):
    mid = _add(test_db_path, sample_student)
    for _ in range(12):
        record_practice(mid, "A", True, db_path=test_db_path)
    m = db.get_mistake(mid, db_path=test_db_path)
    assert m["ease_factor"] == pytest.approx(_EASE_MAX)
    assert m["review_stage"] == _MAX_REVIEW_STAGE
    assert m["consecutive_correct"] >= 2  # 早已判定掌握
    assert m["mastery_level"] == 100


def test_next_review_at_stretches_with_ease():
    long = datetime.fromisoformat(
        _next_review_at(3, ease_factor=_EASE_MAX))
    short = datetime.fromisoformat(
        _next_review_at(3, ease_factor=_EASE_MIN))
    assert long > short


def test_next_review_at_falls_back_on_bad_ease():
    base = datetime.fromisoformat(_next_review_at(2, ease_factor=_EASE_DEFAULT))
    bad = datetime.fromisoformat(_next_review_at(2, ease_factor=0))
    assert bad == base
