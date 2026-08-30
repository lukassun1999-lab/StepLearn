# -*- coding: utf-8 -*-
"""判卷准确性改进回归测试（《错判归因报告》①④②）。

- ④ 判定类调用 temperature=0（见 test_llm_client.py）
- ① 印刷参考答案直读：覆盖自定答案 + 学生命中答案键的"错题"自动剔除
- ② B2 字母前缀比对：学生答单字母 vs 标准答案同字母"字母. 内容" → 剔除
"""

import json

import pytest

import llm_analysis
from knowledge_base import _filter_real_mistakes


# ── ② B2 字母前缀比对 ──────────────────────────────

def test_b2_letter_prefix_match_dropped():
    """实测案例（mistake 562）：user='e' vs correct='e. dealing with...' 被误判错。"""
    mistakes = [{
        "question_number": 62,
        "question_text": "___62___ dealing with such feelings",
        "question_type": "阅读补全短文",
        "user_answer": "e",
        "correct_answer": "e. dealing with such feelings doesn't come easy.",
        "explanation": "学生选错选项",
        "knowledge_points": ["非谓语动词"],
    }]
    assert _filter_real_mistakes(mistakes) == []


def test_b2_prefix_stripped_for_content_answer():
    """学生答内容、标准答案带字母前缀：剥前缀后内容相同 → 剔除。"""
    mistakes = [{
        "question_number": 1,
        "question_text": "It was ___ difficult.",
        "question_type": "选词填空",
        "user_answer": "dealing with such feelings",
        "correct_answer": "e. dealing with such feelings",
        "explanation": "词义辨析",
        "knowledge_points": ["非谓语动词"],
    }]
    assert _filter_real_mistakes(mistakes) == []


def test_b2_different_letter_kept():
    """学生字母与标准答案字母不同 → 仍是错题（不冤枉剔除）。"""
    m = {
        "question_number": 2,
        "question_text": "___62___ dealing with such feelings",
        "question_type": "阅读补全短文",
        "user_answer": "f",
        "correct_answer": "e. dealing with such feelings doesn't come easy.",
        "explanation": "学生选错选项",
        "knowledge_points": ["非谓语动词"],
    }
    assert _filter_real_mistakes([m]) == [m]


# ── ① 印刷参考答案直读 ──────────────────────────────

def _wrap(mistakes, summary_extra=None):
    summary = {"total_mistakes": len(mistakes), "overall_assessment": "ok"}
    summary.update(summary_extra or {})
    return {"mistakes": json.loads(json.dumps(mistakes)), "summary": summary}


def test_printed_key_overrides_and_drops_matching_student(test_db_path):
    """学生作答命中印刷答案键 → 模型的"错题"判定被代码推翻剔除。"""
    result = _wrap(
        [
            # 学生答 gone、键是 gone、模型自定答案 went 判学生错 → 应剔除
            {"question_number": 3, "question_text": "He has ___ (go) home.", "question_type": "语法填空",
             "user_answer": "gone", "correct_answer": "went",
             "explanation": "时态错误", "knowledge_points": ["非谓语动词"]},
            # 键里没有的题 → 保留，不受影响
            {"question_number": 9, "question_text": "They ___ here yesterday.", "question_type": "语法填空",
             "user_answer": "go", "correct_answer": "went",
             "explanation": "时态错误", "knowledge_points": ["非谓语动词"]},
        ],
        {"printed_answer_key": {"3": "gone"}},
    )
    llm_analysis._postprocess_mistakes(result)
    assert len(result["mistakes"]) == 1
    assert result["mistakes"][0]["question_number"] == 9
    assert result["summary"]["printed_key_applied"] == 1  # 只有键内的 qn3 被覆盖


def test_printed_key_overrides_correct_answer_on_real_mistakes(test_db_path):
    """确实错的题：correct_answer 被印刷键覆盖，来源标记 printed_key。"""
    result = _wrap(
        [{"question_number": 5, "question_text": "She ___ here yesterday.", "question_type": "语法填空",
          "user_answer": "go", "correct_answer": "ai_guessed",
          "explanation": "介词误用", "knowledge_points": ["非谓语动词"]}],
        {"printed_answer_key": {"5": "went"}},
    )
    llm_analysis._postprocess_mistakes(result)
    assert len(result["mistakes"]) == 1
    m = result["mistakes"][0]
    assert m["correct_answer"] == "went"
    assert m["answer_source"] == "printed_key"
    assert result["summary"]["printed_key_applied"] == 1


def test_printed_key_bad_shapes_ignored(test_db_path):
    """范围形式/非数字题号/空值：安全跳过，不抛错。"""
    result = _wrap(
        [{"question_number": 1, "question_text": "Q", "question_type": "单项选择",
          "user_answer": "A", "correct_answer": "B",
          "explanation": "x", "knowledge_points": ["非谓语动词"]}],
        {"printed_answer_key": {"1-5": "BCADC", "abc": "X", "2": None, "": "Y"}},
    )
    llm_analysis._postprocess_mistakes(result)  # 不抛错
    assert result["summary"]["printed_answer_key"] == {}
    assert "printed_key_applied" not in result["summary"]


def test_answered_count_normalized(test_db_path):
    result = _wrap([], {"answered_count": "45"})
    llm_analysis._postprocess_mistakes(result)
    assert result["summary"]["answered_count"] == 45

    result = _wrap([], {"answered_count": "很多"})
    llm_analysis._postprocess_mistakes(result)
    assert result["summary"]["answered_count"] is None


# ── 分块合并保留新字段 ──────────────────────────────

def test_chunk_merge_keeps_printed_key_and_answered_count():
    merged = llm_analysis._merge_chunk_results([
        {"mistakes": [], "summary": {"printed_answer_key": {"1": "A"},
                                     "answered_count": 10}},
        {"mistakes": [], "summary": {"printed_answer_key": {"2": "B"},
                                     "answered_count": 8}},
    ])
    assert merged["summary"]["printed_answer_key"] == {"1": "A", "2": "B"}
    assert merged["summary"]["answered_count"] == 18


# ── ④ temperature（判定类 0 / 生成类 0.3）──────────
# 见 tests/test_llm_client.py::test_judgment_calls_use_zero_temperature 等


@pytest.mark.parametrize("call_type,expected", [
    ("analyze", 0.0), ("grade", 0.0), ("cause_chain", 0.0), ("ocr", 0.0),
    ("generate", 0.3), ("plan", 0.3), ("essay_review", 0.3), ("", 0.3),
])
def test_temperature_routing(call_type, expected):
    import llm
    assert llm._temperature_for(call_type) == expected
