# -*- coding: utf-8 -*-
"""受控知识点词表：归一化映射 + 未识别池。"""


def test_normalize_exact_and_alias():
    from skills_bridge import normalize_knowledge_points
    # canonical 精确匹配
    assert normalize_knowledge_points(["现在完成时"]) == (["现在完成时"], [])
    # alias 精确匹配（忽略空白）
    assert normalize_knowledge_points(["have done"]) == (["现在完成时"], [])
    assert normalize_knowledge_points([" 现在完成时 "]) == (["现在完成时"], [])


def test_normalize_finer_label_substring():
    from skills_bridge import normalize_knowledge_points
    # 标签更细：canonical 是标签子串 → 最长匹配
    assert normalize_knowledge_points(["现在完成时的用法"]) == (["现在完成时"], [])
    assert normalize_knowledge_points(["宾语从句语序"]) == (["宾语从句"], [])


def test_normalize_generic_alias_single_match():
    from skills_bridge import normalize_knowledge_points
    # 笼统标签 → alias 映射（无歧义）
    assert normalize_knowledge_points(["定语从句"]) == (["定语从句 · 关系代词"], [])
    assert normalize_knowledge_points(["主谓一致"]) == (["主谓一致 · 语法一致"], [])
    assert normalize_knowledge_points(["强调句型"]) == (["强调句"], [])


def test_normalize_ambiguous_and_unknown_go_unmapped():
    from skills_bridge import normalize_knowledge_points
    # 歧义（匹配多个 canonical）→ 未识别池
    assert normalize_knowledge_points(["非谓语动词"]) == ([], ["非谓语动词"])
    # 完全未知 → 未识别池
    assert normalize_knowledge_points(["时态填空"]) == ([], ["时态填空"])
    assert normalize_knowledge_points(["completely unknown"]) == ([], ["completely unknown"])


def test_normalize_dedup_and_empty():
    from skills_bridge import normalize_knowledge_points
    assert normalize_knowledge_points(
        ["现在完成时", "现在完成时", "have done"]) == (["现在完成时"], [])
    assert normalize_knowledge_points([]) == ([], [])
    assert normalize_knowledge_points(None) == ([], [])


# ── 补词后新增：前缀剥离 / 忽略列表 / 能力类映射 ──

def test_normalize_strips_question_type_prefix():
    from skills_bridge import normalize_knowledge_points
    assert normalize_knowledge_points(["阅读理解-细节理解"]) == (["细节理解"], [])
    assert normalize_knowledge_points(["阅读理解-推理判断"]) == (["推理判断"], [])
    assert normalize_knowledge_points(["阅读理解-主旨大意"]) == (["主旨大意"], [])


def test_normalize_ignores_question_type_words():
    from skills_bridge import normalize_knowledge_points
    # 题型词直接丢弃：既不是 canonical 也不进未识别池
    assert normalize_knowledge_points(["阅读理解", "语法填空", "完形填空",
                                       "英语写作"]) == ([], [])
    # 忽略词与真实知识点混合时只保留后者
    assert normalize_knowledge_points(["阅读理解", "现在完成时"]) == (["现在完成时"], [])
    # 带括号说明的题型词同样忽略（真实 LLM 输出风格）
    assert normalize_knowledge_points(["历史知识（工业革命前的睡眠习惯）"]) == ([], [])


def test_normalize_discourse_capability_aliases():
    from skills_bridge import normalize_knowledge_points
    assert normalize_knowledge_points(["主旨归纳"]) == (["主旨大意"], [])
    assert normalize_knowledge_points(["上下文理解"]) == (["语境理解与推断"], [])
    assert normalize_knowledge_points(["语义理解"]) == (["语境理解与推断"], [])


def test_normalize_vocab_discrimination_aliases():
    from skills_bridge import normalize_knowledge_points
    assert normalize_knowledge_points(["名词辨析"]) == (["词义辨析（易混词）"], [])
    assert normalize_knowledge_points(["动词辨析"]) == (["词义辨析（易混词）"], [])
    assert normalize_knowledge_points(["形容词辨析"]) == (["词义辨析（易混词）"], [])


def test_normalize_new_aliases():
    from skills_bridge import normalize_knowledge_points
    assert normalize_knowledge_points(["并列谓语"]) == (["并列句"], [])
    assert normalize_knowledge_points(["介词短语"]) == (["介词固定搭配"], [])
    assert normalize_knowledge_points(["词性变换"]) == (["词性转换"], [])
    assert normalize_knowledge_points(["情态动词 can't 的用法"]) == (
        ["情态动词表推测"], [])
    assert normalize_knowledge_points(["信息匹配"]) == (["文章结构"], [])


def test_record_and_get_unmapped_kps(test_db_path):
    import db
    # 用独特标签避免与其他测试（demo 分析记录"非谓语动词"等）共享 session DB 冲突
    label_a, label_b = "unmapped-test-a", "unmapped-test-b"
    db.record_unmapped_kps([label_a, label_b], db_path=test_db_path)
    db.record_unmapped_kps([label_a], db_path=test_db_path)  # 重复 → 计数累加
    rows = db.get_unmapped_kps(db_path=test_db_path)
    counts = {r["label"]: r["count"] for r in rows}
    assert counts[label_a] == 2
    assert counts[label_b] == 1
    # 空输入不报错
    db.record_unmapped_kps([], db_path=test_db_path)
    db.record_unmapped_kps(None, db_path=test_db_path)


def test_analyze_mistakes_normalizes_kps(demo_mode, test_db_path):
    """集成：analyze_mistakes 将自由标签归一化并记录未识别词。"""
    import json
    import os
    from skills_bridge import analyze_mistakes
    result = analyze_mistakes("fake ocr text")
    mistakes = result.get("mistakes", [])
    assert mistakes  # demo 数据
    kb_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "knowledge_points.json")
    canonicals = {p["c"] for p in json.load(open(kb_path, encoding="utf-8"))["points"]}
    for m in mistakes:
        kps = m.get("knowledge_points") or []
        for kp in kps:
            assert kp in canonicals, f"标签未归一化: {kp}"
