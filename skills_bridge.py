#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Skill 调用封装层（门面）— Flask ↔ WorkBuddy Skills 的唯一桥梁。

2026-08 第 3 周提交 4 拆分：实现移至六个模块，本文件只做再导出，
保持全部符号（含测试引用的私有名）从 skills_bridge 可导入，
调用方与测试零改动：

- bridge_common.py   路径常量、sys.path 副作用、惰性 LLM client
- llm_prompts.py     全部 prompt 模板（纯常量）
- ocr_service.py     OCR（vision 主 / Tesseract 兜底）
- knowledge_base.py  参考文件读取、知识点/错因归一、真错题过滤
- llm_analysis.py    错题提取、错因因果链、画像趋势
- question_gen.py    练习题生成、类似题、题库匹配
- llm_plans.py       练习批改、作文批改、学习方案、月度总结

Pipeline 代码只调这个模块，不直接操作 subprocess/LLM。
"""

import logging

# 路径常量 + sys.path 副作用 + _get_client
from bridge_common import (LEARNING_PLAN_REFS, MISTAKE_ANALYZER_REFS,
                           MISTAKE_ANALYZER_SCRIPTS, OCR_JS, OCR_WRAPPER,
                           SKILLS_DIR, _get_client)
# Prompt 模板
from llm_prompts import (CAUSE_CHAIN_PROMPT, ESSAY_REVIEW_PROMPT,
                         GRADING_PROMPT, LEARNING_PLAN_PROMPT,
                         MISTAKE_ANALYSIS_PROMPT, MONTHLY_ANALYSIS_PROMPT,
                         PLAN_UPDATE_PROMPT, QUESTION_GENERATION_PROMPT,
                         SIMILAR_QUESTION_PROMPT, STUDENT_MEMORY_PROMPT,
                         VISION_OCR_PROMPT)
# OCR
from ocr_service import (_MIN_OCR_TEXT_LENGTH, _run_tesseract_ocr,
                         run_ocr, run_ocr_multimodal, run_ocr_parallel)
# 知识库 / 归一化
from knowledge_base import (_CAUSE_DEFAULT, _CAUSE_KEYWORDS, _KP_FILE,
                            _KP_IGNORE, _KP_INDEX, _KP_TABLE,
                            _KP_TYPE_PREFIXES, _UNANSWERED_MARKERS,
                            CAUSE_KEYS, CAUSE_LABELS, _answer_option_content,
                            _filter_real_mistakes, _is_unanswered,
                            _load_knowledge_base, _normalize_answer,
                            _normalize_error_cause, _statistical_cause_profile,
                            generate_exam_html, generate_weekly_report_html,
                            get_knowledge_framework, get_learning_plan_reference,
                            get_question_types, normalize_knowledge_points,
                            read_reference)
# LLM 分析
from llm_analysis import (analyze_cause_chain, analyze_mistakes,
                          build_cause_trend)
# 题目生成
from question_gen import (_FILL_BLANK_TYPES, _INFLECTION_HINT_TYPES,
                          _INFLECTION_MARKS, _OPTION_INLINE_RE, _OPTION_TYPES,
                          _READING_TYPES, _SUBJECTIVE_TYPES,
                          _ensure_options_embedded, _fix_generated_answer_format,
                          _inflection_missing_hint, _is_excluded_type,
                          _options_embedded, _text_similarity,
                          generate_questions, generate_similar_questions,
                          get_similar_questions_for_mistake)
# 批改与方案
from llm_plans import (_normalize_plan_text_field, generate_learning_plan,
                       generate_monthly_analysis, generate_plan_update,
                       grade_answers, review_essay, update_student_memory)

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════
# Test / self-check
# ═══════════════════════════════════════════════════

if __name__ == "__main__":
    import os
    checks = [
        ("OCR script", OCR_JS),
        ("Mistake analyzer scripts", MISTAKE_ANALYZER_SCRIPTS),
        ("  - knowledge_framework.md", os.path.join(MISTAKE_ANALYZER_REFS, "knowledge_framework.md")),
        ("  - question_types.md", os.path.join(MISTAKE_ANALYZER_REFS, "question_types.md")),
        ("Learning plan refs", LEARNING_PLAN_REFS),
    ]
    for label, path in checks:
        status = "OK" if os.path.exists(path) else "MISSING"
        print(f"  [{status}] {label}: {path}")

    # Test reference reading
    kf = get_knowledge_framework()
    print(f"\nKnowledge framework: {len(kf)} chars")
    qt = get_question_types()
    print(f"Question types: {len(qt)} chars")
    print(f"Learning plan stage1 ref: {len(get_learning_plan_reference('stage1-opening-and-basics'))} chars")

    print("\nskills_bridge.py OK")
