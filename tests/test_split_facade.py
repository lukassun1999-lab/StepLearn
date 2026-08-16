# -*- coding: utf-8 -*-
"""拆分门面完整性测试（第 3 周提交 4/5）。

skills_bridge 与 db 均为再导出门面：大量调用方与测试直接引用其符号
（含私有名）。拆分后必须保证全部符号仍可从原路径导入。
"""

import pytest


@pytest.mark.parametrize("name", [
    # 公共函数（pipeline/ops/tests 消费）
    "run_ocr", "run_ocr_parallel", "run_ocr_multimodal",
    "analyze_mistakes", "analyze_cause_chain", "build_cause_trend",
    "generate_questions", "generate_similar_questions",
    "get_similar_questions_for_mistake",
    "grade_answers", "review_essay",
    "generate_learning_plan", "generate_plan_update",
    "generate_monthly_analysis",
    "normalize_knowledge_points", "read_reference",
    "get_knowledge_framework", "get_question_types",
    "get_learning_plan_reference",
    "generate_weekly_report_html", "generate_exam_html",
    # 常量
    "SKILLS_DIR", "OCR_JS", "OCR_WRAPPER",
    "MISTAKE_ANALYZER_SCRIPTS", "MISTAKE_ANALYZER_REFS", "LEARNING_PLAN_REFS",
    "CAUSE_KEYS", "CAUSE_LABELS",
    "VISION_OCR_PROMPT", "MISTAKE_ANALYSIS_PROMPT", "CAUSE_CHAIN_PROMPT",
    "QUESTION_GENERATION_PROMPT", "ESSAY_REVIEW_PROMPT", "GRADING_PROMPT",
    "LEARNING_PLAN_PROMPT", "PLAN_UPDATE_PROMPT", "SIMILAR_QUESTION_PROMPT",
    "MONTHLY_ANALYSIS_PROMPT",
    # 测试引用的私有名
    "_get_client", "_normalize_answer", "_answer_option_content",
    "_inflection_missing_hint", "_is_excluded_type", "_OPTION_TYPES",
    "_fix_generated_answer_format", "_normalize_error_cause",
    "_statistical_cause_profile", "_normalize_plan_text_field",
    "_filter_real_mistakes", "_READING_TYPES", "_SUBJECTIVE_TYPES",
    "_load_knowledge_base",
])
def test_skills_bridge_facade_exports(name):
    import skills_bridge
    assert hasattr(skills_bridge, name), f"门面缺失符号: {name}"


def test_skills_bridge_impl_modules_exist():
    import bridge_common, llm_prompts, ocr_service
    import knowledge_base, llm_analysis, question_gen, llm_plans
    for mod in (bridge_common, llm_prompts, ocr_service,
                knowledge_base, llm_analysis, question_gen, llm_plans):
        assert mod.__name__
