# -*- coding: utf-8 -*-
"""范围形式作答展开测试（如 "41-45: ABBAC" → "41: A" …）。

背景：答题卡/答案常以范围形式给出。判题 LLM 若不展开就无法与学生题号配对，
实测会臆造学生作答 → 产生大量虚假错题（如 43 题编造 noisy vs comfortable）。
展开是确定性规则，放在代码层比依赖 LLM 可靠。
"""

from pipeline.stages import expand_range_answers


def test_expand_continuous_letters():
    out = expand_range_answers("41-45: ABBAC")
    assert "41: A" in out
    assert "42: B" in out
    assert "45: C" in out
    assert "41-45" not in out


def test_expand_with_spaces():
    """字母间有空格也要正确展开。"""
    out = expand_range_answers("1-5: C B B B A")
    assert "1: C" in out and "5: A" in out


def test_expand_multiple_ranges():
    out = expand_range_answers("1-5: CBBBA\n6-10: CBAAA")
    assert "1: C" in out and "10: A" in out


def test_single_answer_untouched():
    """单题作答（56. in）不是范围形式，保持原样。"""
    src = "56. in\n57. rea"
    assert expand_range_answers(src) == src


def test_mismatched_count_untouched():
    """题数与字母数对不上时保持原样，交给 LLM 判断，不强行展开。"""
    src = "41-45: ABC"
    assert expand_range_answers(src) == src


def test_non_answer_text_untouched():
    src = "第一部分　听力\nWhat time is it now?"
    assert expand_range_answers(src) == src
