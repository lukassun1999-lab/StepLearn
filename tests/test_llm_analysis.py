# -*- coding: utf-8 -*-
"""长 OCR 分段分析回归测试（第 5 周提交）。

背景：MiniMax-M3（关闭思维链）对 2 万字符级整卷 OCR 返回空壳（0 错题），
中小文本正常。修复：按试卷题型分节切分，分块调用后合并，下游无感知。
"""

import pytest

import llm_analysis


@pytest.fixture(autouse=True)
def _no_hints(monkeypatch):
    """屏蔽 get_recent_correction_hints（查询的演示表在测试库不存在）。"""
    import db
    monkeypatch.setattr(db, "get_recent_correction_hints", lambda *a, **k: [])
    monkeypatch.setattr(db, "record_unmapped_kps", lambda *a, **k: None)


_SYNTHETIC_OCR = """【第一部分：试卷正文】
21. What color is the sky?
   A. Blue.    B. Green.
22. How many legs does a dog have?
   A. Two.    B. Four.
六、完形填空 阅读下面的短文，根据短文内容选择最佳选项。
The cat ___23___ the mouse in the garden.
23. A. chased    B. caught
【第二部分：学生作答】
21: B
22: B
23: A
"""


def test_chunk_by_section_splits_and_attaches_answers():
    """按节切分：每块含题目与对应作答行（作答行可集中列在别处）。"""
    chunks = llm_analysis.chunk_ocr_by_section(_SYNTHETIC_OCR)
    assert len(chunks) == 2, f"应切出 2 块: {len(chunks)}"
    c1, c2 = chunks
    # 块1：21-22 选择题 + 作答
    assert "21." in c1 and "22." in c1
    assert "21: B" in c1 and "22: B" in c1
    # 块2：完形填空 + 短文 + 作答（作答行在别处也要附上）
    assert "六、完形填空" in c2 and "23." in c2
    assert "23: A" in c2
    # 短文与题目不分离
    assert "The cat" in c2 and "23. A. chased" in c2


def test_chunk_page_markers_stripped():
    """页面标记剥离，不参与分块。"""
    ocr = "--- 第 1 页 ---\n1. A test?\n   A. Yes    B. No\n1: A\n--- 第 2 页 ---\n2. More?\n   A. Yes    B. No\n2: B"
    chunks = llm_analysis.chunk_ocr_by_section(ocr)
    assert len(chunks) == 1
    assert "--- 第" not in chunks[0]


def test_short_ocr_single_call(monkeypatch):
    """短文本走单次调用，不分块。"""
    calls = []
    class FakeClient:
        def call(self, **kw):
            calls.append(kw.get("call_type"))
            return {"mistakes": [], "summary": {}}
    fake = FakeClient()
    monkeypatch.setattr(llm_analysis, "_get_client", lambda: fake)
    llm_analysis.analyze_mistakes("1. What is it?\n   A. X    B. Y\n1: A")
    assert len(calls) == 1


def test_long_ocr_chunked_and_merged(monkeypatch):
    """长文本分块调用并合并结果：错题拼接、summary 聚合。"""
    calls = []
    chunk_results = [
        {"mistakes": [
            {"question_number": 21, "question_text": "Q21", "question_type": "单项选择",
             "correct_answer": "A. Blue", "user_answer": "B. Green",
             "error_cause": "careless", "knowledge_points": ["基础"]}],
         "summary": {"total_mistakes": 1, "by_type": {"单项选择": 1},
                     "top_weak_points": ["基础"], "overall_assessment": "A 块"}},
        {"mistakes": [
            {"question_number": 23, "question_text": "Q23", "question_type": "完形填空",
             "correct_answer": "caught", "user_answer": "chased",
             "error_cause": "vocab", "knowledge_points": ["动词"]}],
         "summary": {"total_mistakes": 1, "by_type": {"完形填空": 1},
                     "top_weak_points": ["动词"], "overall_assessment": "B 块"}},
    ]
    class FakeClient:
        def call(self, **kw):
            calls.append(kw)
            return chunk_results[len(calls) - 1]
    monkeypatch.setattr(llm_analysis, "_get_client", lambda: FakeClient())

    long_ocr = _SYNTHETIC_OCR + "\n" + "x" * (_llm_analysis_threshold())
    res = llm_analysis.analyze_mistakes(long_ocr)
    assert len(calls) == 2, f"应分块调用 2 次: {len(calls)}"
    assert len(res["mistakes"]) == 2
    s = res["summary"]
    assert s["total_mistakes"] == 2
    assert s["by_type"] == {"单项选择": 1, "完形填空": 1}
    assert "A 块" in s["overall_assessment"] and "B 块" in s["overall_assessment"]


def _llm_analysis_threshold():
    return llm_analysis._OCR_CHUNK_THRESHOLD


def test_chunked_merge_filters_false_mistakes(monkeypatch):
    """合并后统一过滤：备选答案命中（normal vs common/ordinary/normal）剔除。"""
    calls = []
    class FakeClient:
        def __init__(self):
            self.n = 0
        def call(self, **kw):
            calls.append(kw)
            self.n += 1
            if self.n == 1:
                return {"mistakes": [
                    {"question_number": 36, "question_text": "Q36", "question_type": "完成对话",
                     "correct_answer": "common/ordinary/normal", "user_answer": "normal",
                     "error_cause": "vocab", "knowledge_points": []},
                    {"question_number": 37, "question_text": "Q37", "question_type": "完成对话",
                     "correct_answer": "why", "user_answer": "what",
                     "error_cause": "grammar", "knowledge_points": []}],
                    "summary": {"total_mistakes": 2, "by_type": {"完成对话": 2},
                                "top_weak_points": [], "overall_assessment": ""}}
            return {"mistakes": [], "summary": {}}
    fake = FakeClient()
    monkeypatch.setattr(llm_analysis, "_get_client", lambda: fake)

    long_ocr = _SYNTHETIC_OCR + "\n" + "x" * (_llm_analysis_threshold())
    res = llm_analysis.analyze_mistakes(long_ocr)
    assert len(res["mistakes"]) == 1, "备选答案命中应被剔除"
    assert res["mistakes"][0]["question_number"] == 37
    assert res["summary"]["total_mistakes"] == 1


def test_chunked_fallback_when_no_sections(monkeypatch):
    """无节标题/无题号的异常格式 → 回退整卷单次调用。"""
    calls = []
    class FakeClient:
        def call(self, **kw):
            calls.append(kw)
            return {"mistakes": [], "summary": {}}
    fake = FakeClient()
    monkeypatch.setattr(llm_analysis, "_get_client", lambda: fake)
    llm_analysis.analyze_mistakes("纯文本无题号" * 3000)
    assert len(calls) == 1
