# -*- coding: utf-8 -*-
"""防臆造校验测试：题干在试卷中查不到的错题标记为 unverified。

场景：试卷常不完整（如缺听力、只有 21-60 题），而答案含全部题号。
LLM 会凭短文内容编出题号和选项（如"43 题 noisy vs comfortable"）。

设计取舍：**只标记不删除**。实测直接删除会误杀真实错题（语法填空等题干
形态特殊，归一化后匹配不到就被删），而"漏报孩子真错的题"比"多报可疑题"
更隐蔽、更危险——前者家长完全不知情，后者家长可自行核对。
"""

from llm_analysis import _mark_unverified, _extract_paper_text

PAPER = (
    "第二部分 阅读理解\n"
    "23. Where are the speakers probably?\n"
    "A. In a library.  B. In a hospital.  C. In a restaurant.\n"
    "第三部分 语言知识运用\n"
    "57. My favorite is 57 (read) books every day.\n"
)


def test_real_question_verified():
    """题干能在试卷中找到 → verified=True。"""
    ms = [{"question_number": 57, "question_text": "My favorite is 57 (read) books every day."}]
    out = _mark_unverified(ms, PAPER)
    assert len(out) == 1
    assert out[0]["question_verified"] is True


def test_fabricated_question_flagged_not_deleted():
    """题干编造 → 标记 unverified=False，但不删除（避免误杀真错题）。"""
    ms = [{"question_number": 43, "question_text": "He was very 43 and invited us to his house."}]
    out = _mark_unverified(ms, PAPER)
    assert len(out) == 1, "可疑项应保留并标记，不应被删除"
    assert out[0]["question_verified"] is False


def test_mixed_flags_each():
    ms = [
        {"question_number": 57, "question_text": "My favorite is 57 (read) books every day."},
        {"question_number": 52, "question_text": "I promised to 52 him again someday."},
    ]
    out = _mark_unverified(ms, PAPER)
    assert len(out) == 2
    flags = {m["question_number"]: m["question_verified"] for m in out}
    assert flags[57] is True
    assert flags[52] is False


def test_short_question_text_unknown():
    """题干过短无法可靠校验 → None（未知），不误判为编造。"""
    ms = [{"question_number": 1, "question_text": "Q21"}]
    out = _mark_unverified(ms, PAPER)
    assert out[0]["question_verified"] is None


def test_whitespace_and_punctuation_tolerated():
    """空格/标点差异不影响匹配。"""
    ms = [{"question_number": 23,
           "question_text": "Where are the speakers probably?  A. In a library."}]
    assert _mark_unverified(ms, PAPER)[0]["question_verified"] is True


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
