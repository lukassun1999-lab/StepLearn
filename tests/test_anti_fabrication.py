# -*- coding: utf-8 -*-
"""防臆造校验测试：题干在试卷中查不到的错题必须剔除。

场景：试卷常不完整（如缺听力、只有 21-60 题），而答案含全部题号。
LLM 会凭短文内容编出题号和选项（如"43 题 noisy vs comfortable"），
这类虚假错题会直接误导家长，必须在代码层剔除。
"""

from llm_analysis import _filter_fabricated, _extract_paper_text

PAPER = (
    "第二部分 阅读理解\n"
    "23. Where are the speakers probably?\n"
    "A. In a library.  B. In a hospital.  C. In a restaurant.\n"
    "第三部分 语言知识运用\n"
    "57. My favorite is 57 (read) books every day.\n"
)


def test_real_question_kept():
    """题干能在试卷中找到 → 保留。"""
    ms = [{"question_number": 57, "question_text": "My favorite is 57 (read) books every day."}]
    assert len(_filter_fabricated(ms, PAPER)) == 1


def test_fabricated_question_dropped():
    """题干是编造的（试卷中查不到）→ 剔除。"""
    ms = [{"question_number": 43, "question_text": "He was very 43 and invited us to his house."}]
    assert _filter_fabricated(ms, PAPER) == []


def test_mixed_keeps_only_real():
    ms = [
        {"question_number": 57, "question_text": "My favorite is 57 (read) books every day."},
        {"question_number": 52, "question_text": "I promised to 52 him again someday."},
    ]
    out = _filter_fabricated(ms, PAPER)
    assert len(out) == 1 and out[0]["question_number"] == 57


def test_empty_question_text_kept():
    """无题干无法校验，保留交给其他规则（不误杀）。"""
    ms = [{"question_number": 1, "question_text": ""}]
    assert len(_filter_fabricated(ms, PAPER)) == 1


def test_whitespace_and_punctuation_tolerated():
    """空格/标点差异不影响匹配。"""
    ms = [{"question_number": 23,
           "question_text": "Where are the speakers probably?  A. In a library."}]
    assert len(_filter_fabricated(ms, PAPER)) == 1


def test_extract_paper_text_strips_answer_sheet():
    """试卷正文应去掉答题卡段落（用答题卡独有的标记 STU_SHEET_MARK 验证）。"""
    full = (PAPER + "\n\n--- 第 1 页 （答题卡）---\n"
            "【说明：学生作答】\nSTU_SHEET_MARK\n57: rea\n")
    paper = _extract_paper_text(full)
    assert "（答题卡）" not in paper
    assert "STU_SHEET_MARK" not in paper
    assert "Where are the speakers" in paper


def test_extract_paper_text_no_sheet():
    """没有答题卡段落时返回全文。"""
    assert _extract_paper_text(PAPER) == PAPER
