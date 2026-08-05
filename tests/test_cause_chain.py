"""错因因果链（Phase 1）测试：受控错因、统计兜底画像、因果链分析、报告板块。"""


def _mk_mistake(question, error_reason="", error_cause="", kps=None,
                question_type="语法填空", explanation=""):
    m = {"question_text": question, "question_type": question_type,
         "user_answer": "x", "correct_answer": "y",
         "explanation": explanation,
         "knowledge_points": kps or ["非谓语动词"], "difficulty": 2}
    if error_reason:
        m["error_reason"] = error_reason
    if error_cause:
        m["error_cause"] = error_cause
    return m


# ── 错因归一化 ────────────────────────────────────

def test_normalize_error_cause_respects_explicit_value():
    from skills_bridge import _normalize_error_cause
    assert _normalize_error_cause({"error_cause": "vocab"}) == "vocab"


def test_normalize_error_cause_keyword_mapping():
    from skills_bridge import _normalize_error_cause
    assert _normalize_error_cause({"error_reason": "拼写错误"}) == "vocab"
    assert _normalize_error_cause({"error_reason": "时态错误"}) == "grammar"
    assert _normalize_error_cause({"error_reason": "长难句结构不清"}) == "syntax"
    assert _normalize_error_cause({"error_reason": "主旨理解偏差"}) == "discourse"
    assert _normalize_error_cause({"error_reason": "粗心看错"}) == "careless"


def test_normalize_error_cause_default_when_unknown():
    from skills_bridge import _normalize_error_cause
    assert _normalize_error_cause({"explanation": "完全未知的原因"}) == "grammar"


# ── 校准修正：未作答 / 题型加权 / 关键词补齐 ─────

def test_normalize_error_cause_unanswered_returns_none():
    from skills_bridge import _normalize_error_cause
    assert _normalize_error_cause({"user_answer": "", "explanation": "完全未作答"}) is None
    assert _normalize_error_cause({"user_answer": "-", "explanation": "xx"}) is None
    assert _normalize_error_cause({"explanation": "该题学生未作答"}) is None


def test_normalize_error_cause_question_type_weighting():
    from skills_bridge import _normalize_error_cause
    # 阅读理解 → 语篇（即使解析里没有关键词）
    assert _normalize_error_cause({"question_type": "阅读理解",
                                   "explanation": "根据原文选C"}) == "discourse"
    # 补全对话/情景交际 → 表达积累（vocab）
    assert _normalize_error_cause({"question_type": "补全对话",
                                   "explanation": "情景交际判断"}) == "vocab"
    # 完形填空默认词汇（词义辨析），除非明确涉及语法
    assert _normalize_error_cause({"question_type": "完形填空",
                                   "explanation": "名词辨析，上下文理解"}) == "vocab"
    assert _normalize_error_cause({"question_type": "完形填空",
                                   "explanation": "动词时态与上下文不符"}) == "grammar"


def test_normalize_error_cause_grammar_keywords_expanded():
    from skills_bridge import _normalize_error_cause
    assert _normalize_error_cause({"explanation": "连词用法错误"}) == "grammar"
    assert _normalize_error_cause({"explanation": "形容词最高级应用"}) == "grammar"
    assert _normalize_error_cause({"explanation": "情态动词 can't 的用法"}) == "grammar"
    assert _normalize_error_cause({"explanation": "并列谓语"}) == "grammar"


def test_statistical_profile_skips_unanswered():
    from skills_bridge import _statistical_cause_profile
    mistakes = [
        _mk_mistake("Q1", error_cause="vocab", kps=["高频词汇"]),
        _mk_mistake("Q2", explanation="学生未作答", kps=["阅读理解"]),
    ]
    p = _statistical_cause_profile(mistakes)
    assert p is not None
    assert p["primary_cause"] == "vocab"
    assert "未作答" not in p["plain_language"]


# ── 统计兜底画像 ──────────────────────────────────

def test_statistical_cause_profile_primary_and_chain():
    from skills_bridge import _statistical_cause_profile
    mistakes = [
        _mk_mistake("Q1", error_cause="vocab", kps=["高频词汇"]),
        _mk_mistake("Q2", error_cause="vocab", kps=["高频词汇"]),
        _mk_mistake("Q3", error_cause="grammar", kps=["现在完成时"]),
    ]
    p = _statistical_cause_profile(mistakes)
    assert p["primary_cause"] == "vocab"
    assert "现在完成时" not in (p["priority_kps"] or [])
    assert "高频词汇" in (p["priority_kps"] or [])
    # 词汇为根因时，应传导到存在次生错因的类
    assert any(link["from"] == "词汇" and link["to"] == "语法"
               for link in p["cause_chain"])
    assert "grammar" in (p["secondary_causes"] or [])
    assert "孩子这周真正卡住的是" in p["plain_language"]


def test_statistical_cause_profile_empty_returns_none():
    from skills_bridge import _statistical_cause_profile
    assert _statistical_cause_profile([]) is None


# ── 因果链分析（demo 模式走统计兜底）──────────────

def test_analyze_cause_chain_demo_falls_back_to_stats(demo_mode, test_db_path):
    import db
    from skills_bridge import analyze_cause_chain
    sid = db.create_student({"name": "因果链测试", "grade": "初二"},
                            db_path=test_db_path)
    student = db.get_student(sid)
    mistakes = [
        _mk_mistake("Q1 不认识生词", error_cause="vocab", kps=["高频词汇"]),
        _mk_mistake("Q2 时态错误", error_cause="grammar", kps=["现在完成时"]),
    ]
    p = analyze_cause_chain(student, mistakes)
    assert p is not None
    assert p["primary_cause"] in ("vocab", "grammar", "syntax", "discourse", "careless")
    assert p["plain_language"]


def test_analyze_cause_chain_no_mistakes_returns_none(demo_mode, test_db_path):
    import db
    from skills_bridge import analyze_cause_chain
    sid = db.create_student({"name": "无错题", "grade": "高二"}, db_path=test_db_path)
    student = db.get_student(sid)
    assert analyze_cause_chain(student, []) is None


# ── db 存取 ───────────────────────────────────────

def test_save_get_cause_profile_roundtrip(test_db_path):
    import db
    sid = db.create_student({"name": "画像学生"}, db_path=test_db_path)
    profile = {
        "primary_cause": "vocab",
        "primary_evidence": "8道错题中5道含生词",
        "cause_chain": [{"from": "词汇", "to": "语法", "note": "生词阻断"}],
        "secondary_causes": ["grammar"],
        "priority_kps": ["高频词汇", "现在完成时"],
        "plain_language": "孩子这周真正卡住的是【词汇】——先补【高频词汇】。",
    }
    db.save_cause_profile(sid, profile, db_path=test_db_path)
    got = db.get_cause_profile(sid, db_path=test_db_path)
    assert got["primary_cause"] == "vocab"
    assert got["cause_chain"] == [{"from": "词汇", "to": "语法", "note": "生词阻断"}]
    assert got["priority_kps"] == ["高频词汇", "现在完成时"]
    # upsert：再次保存覆盖
    profile["primary_cause"] = "grammar"
    db.save_cause_profile(sid, profile, db_path=test_db_path)
    assert db.get_cause_profile(sid, db_path=test_db_path)["primary_cause"] == "grammar"


def test_add_mistake_saves_error_cause(test_db_path):
    import db
    sid = db.create_student({"name": "错因学生"}, db_path=test_db_path)
    mid = db.add_mistake(
        student_id=sid, source_exam="测试",
        question="What ___ you doing?",
        question_type="语法填空",
        correct_answer="were", user_answer="was",
        explanation="时态错误",
        knowledge_points=["过去进行时"],
        error_cause="grammar",
        cause_evidence="动词时态与时间状语不符",
        db_path=test_db_path,
    )
    m = db.get_mistake(mid, db_path=test_db_path)
    assert m["error_cause"] == "grammar"
    assert m["cause_evidence"] == "动词时态与时间状语不符"


# ── 报告板块 ─────────────────────────────────────

def _sample_student():
    return {"name": "小明", "grade": "初二", "english_score": 90}


def test_report_contains_cause_section_with_profile():
    from report_templates import render_diagnostic_report
    cause_profile = {
        "primary_cause": "vocab",
        "primary_evidence": "8道错题中5道含生词",
        "cause_chain": [{"from": "词汇", "to": "语法", "note": "生词阻断"}],
        "secondary_causes": ["grammar"],
        "priority_kps": ["高频词汇"],
        "plain_language": "孩子这周真正卡住的是【词汇量】——先补【高频词汇】。",
    }
    html = render_diagnostic_report(
        student=_sample_student(),
        ocr_confidence=0.9,
        mistakes=[_mk_mistake("Q1", error_cause="vocab")],
        weak_points=[{"knowledge_point": "非谓语动词", "severity": "高"}],
        learning_plan={},
        cause_profile=cause_profile,
    )
    assert "错因画像" in html
    assert "核心卡点：单词不认识" in html
    assert "孩子这周真正卡住的是【词汇量】" in html
    assert "高频词汇" in html


def test_report_without_profile_has_no_cause_section():
    from report_templates import render_diagnostic_report
    html = render_diagnostic_report(
        student=_sample_student(),
        ocr_confidence=0.9,
        mistakes=[],
        weak_points=[],
        learning_plan={},
    )
    assert "错因画像" not in html


# ── 方案重排：因果链根因优先 ──────────────────────

def test_reorder_priority_by_cause_puts_root_first():
    from pipeline.stages import _reorder_priority_by_cause
    plan = {
        "weak_point_priority": [
            {"knowledge_point": "现在完成时", "severity": "中", "reason": "2道错题"},
            {"knowledge_point": "高频词汇", "severity": "中", "reason": "1道错题"},
            {"knowledge_point": "定语从句", "severity": "低", "reason": "1道错题"},
        ]
    }
    cause_profile = {"priority_kps": ["高频词汇", "现在完成时（受词汇连累，次生）"]}
    out = _reorder_priority_by_cause(plan, cause_profile)
    kps = [it["knowledge_point"] for it in out["weak_point_priority"]]
    assert kps == ["高频词汇", "现在完成时", "定语从句"]
    assert out["weak_point_priority"][0]["severity"] == "高"
    # 括号标注的知识点也能匹配并提升优先级
    assert out["weak_point_priority"][1]["severity"] == "高"
    assert out["weak_point_priority"][1]["reason"] == "2道错题"  # 已有 reason 不覆盖


def test_reorder_priority_by_cause_no_match_keeps_order():
    from pipeline.stages import _reorder_priority_by_cause
    plan = {"weak_point_priority": [
        {"knowledge_point": "非谓语动词", "severity": "高", "reason": "2道错题"}]}
    out = _reorder_priority_by_cause(plan, {"priority_kps": ["高频词汇"]})
    assert out["weak_point_priority"][0]["knowledge_point"] == "非谓语动词"
    assert out["weak_point_priority"][0]["severity"] == "高"


def test_reorder_priority_by_cause_handles_bad_input():
    from pipeline.stages import _reorder_priority_by_cause
    assert _reorder_priority_by_cause(None, {}) is None
    assert _reorder_priority_by_cause({}, {}) == {}
    plan = {"weak_point_priority": "not-a-list"}
    assert _reorder_priority_by_cause(plan, {"priority_kps": ["高频词汇"]}) is plan


# ── Phase 2：跨周对比叙事 ────────────────────────

def test_cause_history_roundtrip_and_before(test_db_path):
    import db
    sid = db.create_student({"name": "历史学生"}, db_path=test_db_path)
    profile = {"primary_cause": "vocab", "plain_language": "x"}
    db.save_cause_profile_history(sid, "2026-08-03", profile,
                                  cause_counts={"vocab": 5, "grammar": 3},
                                  db_path=test_db_path)
    db.save_cause_profile_history(sid, "2026-08-10", profile,
                                  cause_counts={"vocab": 2, "grammar": 2},
                                  db_path=test_db_path)
    cur = db.get_cause_profile_history(sid, week_start="2026-08-10",
                                       db_path=test_db_path)
    assert cur["cause_counts"] == {"vocab": 2, "grammar": 2}
    assert cur["total_count"] == 4
    prev = db.get_cause_profile_history(sid, before="2026-08-10", db_path=test_db_path)
    assert prev["week_start"] == "2026-08-03"
    assert db.get_cause_profile_history(sid, db_path=test_db_path)["week_start"] == "2026-08-10"
    sid2 = db.create_student({"name": "无历史"}, db_path=test_db_path)
    assert db.get_cause_profile_history(sid2, db_path=test_db_path) is None


def test_cause_history_upsert_same_week(test_db_path):
    import db
    sid = db.create_student({"name": "覆盖学生"}, db_path=test_db_path)
    db.save_cause_profile_history(sid, "2026-08-10", {"primary_cause": "vocab"},
                                  cause_counts={"vocab": 3}, db_path=test_db_path)
    db.save_cause_profile_history(sid, "2026-08-10", {"primary_cause": "grammar"},
                                  cause_counts={"grammar": 4}, db_path=test_db_path)
    cur = db.get_cause_profile_history(sid, week_start="2026-08-10", db_path=test_db_path)
    assert cur["primary_cause"] == "grammar"
    assert cur["total_count"] == 4


def test_build_cause_trend_same_cause_declining():
    from skills_bridge import build_cause_trend
    cur = {"primary_cause": "vocab", "cause_counts": {"vocab": 2, "grammar": 2}}
    prev = {"primary_cause": "vocab", "cause_counts": {"vocab": 5, "grammar": 1}}
    t = build_cause_trend(cur, prev)
    assert "缓解" in t["narrative"]
    assert t["current_primary_label"] == "词汇"
    assert t["previous_pct"] == 83 and t["current_pct"] == 50


def test_build_cause_trend_same_cause_increasing():
    from skills_bridge import build_cause_trend
    cur = {"primary_cause": "vocab", "cause_counts": {"vocab": 6, "grammar": 1}}
    prev = {"primary_cause": "vocab", "cause_counts": {"vocab": 3, "grammar": 3}}
    t = build_cause_trend(cur, prev)
    assert "主要卡点" in t["narrative"]


def test_build_cause_trend_cause_shift():
    from skills_bridge import build_cause_trend
    cur = {"primary_cause": "grammar", "cause_counts": {"vocab": 1, "grammar": 4}}
    prev = {"primary_cause": "vocab", "cause_counts": {"vocab": 5, "grammar": 1}}
    t = build_cause_trend(cur, prev)
    assert "补上来了" in t["narrative"]
    assert "新卡点" in t["narrative"]


def test_build_cause_trend_invalid_returns_none():
    from skills_bridge import build_cause_trend
    assert build_cause_trend({"primary_cause": "xx", "cause_counts": {}},
                             {"primary_cause": "vocab", "cause_counts": {}}) is None


def test_weekly_report_cause_trend_section():
    from report_templates import render_weekly_report
    cause_trend = {
        "narrative": "上周的「词汇」（80%）补上来了，本周新卡点是「语法」——说明在往前走了。",
        "current_primary": "grammar", "previous_primary": "vocab",
        "current_primary_label": "语法", "previous_primary_label": "词汇",
        "current_pct": 60, "previous_pct": 80,
    }
    html = render_weekly_report(
        student_name="小明", week_start="2026-08-10", week_end="2026-08-16",
        new_mistakes=5, mastered_count=2, weak_areas=[],
        cause_trend=cause_trend,
    )
    assert "卡点变化" in html
    assert "补上来了" in html
    assert "语法" in html


def test_weekly_report_without_cause_trend():
    from report_templates import render_weekly_report
    html = render_weekly_report(
        student_name="小明", week_start="2026-08-10", week_end="2026-08-16",
        new_mistakes=0, mastered_count=0, weak_areas=[],
    )
    assert "卡点变化" not in html


# ── 报告文本兜底：LLM 把 parent_guide 返回成 dict 的防御（实测发现）──

def test_plan_text_normalization():
    from report_templates import _plan_text
    # 字符串原样
    assert _plan_text("简单建议") == "简单建议"
    # dict 转可读文本（键名映射中文标签）
    out = _plan_text({"boarding_advice": "周六陪读", "emotional_support": "多安慰"})
    assert "住校：周六陪读" in out
    assert "情绪支持：多安慰" in out
    assert "<br>" in out
    # 空 dict / None → fallback
    assert _plan_text({}, "默认") == "默认"
    assert _plan_text(None, "默认") == "默认"
    assert _plan_text([], "默认") == "默认"


def test_report_with_dict_parent_guide_no_repr():
    from report_templates import render_diagnostic_report
    guide = {"boarding_advice": "孩子住校，周末陪伴", "emotional_support": "考后安慰"}
    html = render_diagnostic_report(
        student=_sample_student(),
        ocr_confidence=0.9,
        mistakes=[],
        weak_points=[],
        learning_plan={
            "parent_guide": guide,
            "motivation_message": {"title": "鼓励"},
        },
    )
    # 不再出现 Python repr（dict 字面量）
    assert "boarding_advice'" not in html
    assert "{" not in html[html.index("你可以试试这样做"):html.index("你可以试试这样做") + 500]
    # 渲染的是格式化后的可读文本
    assert "住校：孩子住校，周末陪伴" in html
    assert "情绪支持：考后安慰" in html
    assert "title：鼓励" in html  # 无中文映射的键用原键名


def test_normalize_plan_text_field():
    from skills_bridge import _normalize_plan_text_field
    assert _normalize_plan_text_field("纯文本") == "纯文本"
    out = _normalize_plan_text_field({"boarding_advice": "周末陪读", "monitoring": "每周跟进"})
    assert "boarding_advice：周末陪读" in out
    assert "；" in out
    assert _normalize_plan_text_field(None) == ""


# ── 答案括号格式归一化（OCR 输出 "b (false)" 等，实测导致答对误判）──

def test_filter_real_mistakes_paren_format():
    from skills_bridge import _filter_real_mistakes
    # 学生答 b、正确 "b (false)" → 字母相同，答对剔除（实测误判案例）
    assert _filter_real_mistakes([
        {"user_answer": "b", "correct_answer": "b (false)", "question_text": "q"}]) == []
    # 学生答 b、正确 "a (true)" → 字母不同，保留（确实答错）
    kept = _filter_real_mistakes([
        {"user_answer": "b", "correct_answer": "a (true)", "question_text": "q"}])
    assert len(kept) == 1
    # 学生答 "c (so that)"、正确 "so that" → 内容相同，答对剔除
    assert _filter_real_mistakes([
        {"user_answer": "c (so that)", "correct_answer": "so that",
         "question_text": "q"}]) == []
    # 学生答 "a (high)"、正确 "highest" → 内容不同，保留（确实答错）
    kept = _filter_real_mistakes([
        {"user_answer": "a (high)", "correct_answer": "highest",
         "question_text": "q"}])
    assert len(kept) == 1
    # 双方括号格式、内容不同 → 保留
    kept = _filter_real_mistakes([
        {"user_answer": "a (high)", "correct_answer": "b (highest)",
         "question_text": "q"}])
    assert len(kept) == 1
    # 括号格式 + 显示保留「字母. 内容」
    kept = _filter_real_mistakes([
        {"user_answer": "a (high)", "correct_answer": "higher",
         "question_text": "q"}])
    assert kept[0]["user_answer"] == "A. high"


# ── 阅读类题型不进逐题练习（实测生成无选项残题）──

def test_reading_types_excluded_from_practice():
    from skills_bridge import _SUBJECTIVE_TYPES as sb_types
    from domain.questions import _SUBJECTIVE_TYPES as dom_types
    for t in ("阅读选择", "阅读判断", "阅读匹配", "信息匹配"):
        assert t in sb_types and t in dom_types


def test_generate_questions_skips_reading_mistakes(demo_mode, test_db_path):
    """阅读类错题不生成练习题（无法自包含出题）。"""
    from skills_bridge import generate_questions
    mistakes = [{
        "question_text": "What is David worried about?",
        "question_type": "阅读选择", "correct_answer": "B", "user_answer": "A",
        "knowledge_points": ["阅读细节理解"], "difficulty": 2,
    }, {
        "question_text": "Tom's grandmother has been in hospital.",
        "question_type": "阅读判断", "correct_answer": "B", "user_answer": "A",
        "knowledge_points": ["阅读细节理解"], "difficulty": 2,
    }]
    result = generate_questions(mistakes, task_id=None)
    assert result["questions"] == []  # 全部被过滤，不调 LLM 不产出
