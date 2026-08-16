#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批改与方案：练习批改、作文批改、学习方案、AI 诊所、月度总结
（自 skills_bridge.py 拆出）。
"""

import json
from typing import Any, Dict, List, Optional

from bridge_common import _get_client
from llm_prompts import (ESSAY_REVIEW_PROMPT, GRADING_PROMPT,
                         LEARNING_PLAN_PROMPT, MONTHLY_ANALYSIS_PROMPT,
                         PLAN_UPDATE_PROMPT)

def grade_answers(questions: List[Dict], student_answers: List[Dict],
                  task_id: int = None) -> Dict[str, Any]:
    """
    Grade student answers via LLM (english-mistake-analyzer STEP 4).
    Returns: {"results": [...], "summary": {...}}
    """
    all_kps = set()
    for q in questions:
        kps = q.get("knowledge_points", [])
        if isinstance(kps, str):
            try:
                kps = json.loads(kps)
            except Exception:
                kps = []
        for kp in kps:
            all_kps.add(kp)

    from db import get_recent_correction_hints
    hints = get_recent_correction_hints(list(all_kps), content_type="grading", limit=5)
    prompt = GRADING_PROMPT.format(
        questions_json=json.dumps(questions, ensure_ascii=False, indent=2),
        student_answers_json=json.dumps(student_answers, ensure_ascii=False, indent=2),
    )
    if hints:
        prompt = f"{prompt}\n\n{hints}"
    schema = {
        "results": {"type": "array", "required": True},
        "summary": {"type": "object", "required": True},
    }
    return _get_client().call(
        prompt=prompt, schema=schema, task_id=task_id, call_type="grade"
    )


def _normalize_plan_text_field(value) -> str:
    """方案自由文本字段规范化：LLM 可能返回 dict（实测 parent_guide 返回结构化对象），
    统一转字符串后再入库，保证各消费方拿到一致文本。"""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            if isinstance(v, (str, int, float)):
                parts.append(f"{k}：{str(v).replace(chr(10), ' ')}")
        return "；".join(parts)
    return ""


def review_essay(question: str, essay: str, grade: str = "",
                 task_id: int = None) -> Dict[str, Any]:
    """批改学生英语作文：逐句错误标注 + 四维评价 + 评分建议 + 优点 + 建议。
    内容管控：只输出局部修改示例，不整篇改写。"""
    prompt = ESSAY_REVIEW_PROMPT.format(grade=grade, question=question, essay=essay)
    schema = {
        "errors": {"type": "array", "required": True},
        "evaluation": {"type": "object", "required": True},
        "score_suggestion": {"type": "object", "required": True},
        "strengths": {"type": "array", "required": False},
        "advice": {"type": "array", "required": False},
    }
    return _get_client().call(
        prompt=prompt, schema=schema, task_id=task_id, call_type="essay_review")


def generate_learning_plan(student_info: Dict, diagnosis: Dict,
                           profile: Dict = None, task_id: int = None) -> Dict[str, Any]:
    """
    Generate personalized learning plan via LLM, incorporating student profile
    (chat.md six-part dimensions) when available.
    """
    profile_json = json.dumps(profile or {}, ensure_ascii=False, indent=2)
    prompt = LEARNING_PLAN_PROMPT.format(
        name=student_info.get("name", ""),
        grade=student_info.get("grade", "高二"),
        score=student_info.get("english_score", "未知"),
        school_type=student_info.get("school_type", "住校"),
        target_score=student_info.get("target_score", "未设定"),
        diagnosis_json=json.dumps(diagnosis, ensure_ascii=False, indent=2),
        profile_json=profile_json,
    )
    schema = {
        "diagnosis_report": {"type": "object", "required": False},
        "weak_point_priority": {"type": "array", "required": True},
        "modules": {"type": "array", "required": True},
    }
    result = _get_client().call(
        prompt=prompt, schema=schema, task_id=task_id, call_type="plan"
    )
    # 自由文本字段规范化：LLM 可能把 parent_guide 等返回成 dict，统一转字符串
    for key in ("parent_guide", "motivation_message"):
        if isinstance(result.get(key), dict):
            result[key] = _normalize_plan_text_field(result[key])
    return result


def generate_plan_update(student_id: int, week_start: str,
                         weak_point_matrix=None,
                         new_mistakes_json: str = "[]",
                         mastered_mistakes_json: str = "[]",
                         new_count: int = 0,
                         mastered_count: int = 0,
                         completion_rate: float = 0.0,
                         parent_task_progress_json: str = "{}",
                         parent_tasks_json: str = "[]",
                         plan_choices_json: str = "{}",
                         current_modules_json: str = "[]",
                         task_id: int = None) -> Dict[str, Any]:
    """
    Generate AI Clinic content to update learning plan, incorporating
    weekly completion rate, student profile, and parent task engagement
    for adaptive difficulty.

    All matrix/list inputs arrive pre-serialized by the caller
    (weekly_pipeline analysis_only stage) to avoid re-fetching from DB.
    completion_rate may be 0-1 fraction or 0-100 percent; normalized here.
    """
    if not isinstance(weak_point_matrix, str):
        weak_point_matrix = json.dumps(weak_point_matrix or [], ensure_ascii=False)

    rate = completion_rate * 100 if completion_rate <= 1 else completion_rate

    prompt = PLAN_UPDATE_PROMPT.format(
        student_id=student_id,
        week_start=week_start,
        weak_point_matrix=weak_point_matrix,
        new_mistakes_json=new_mistakes_json,
        mastered_mistakes_json=mastered_mistakes_json,
        new_count=new_count,
        mastered_count=mastered_count,
        completion_rate=round(rate, 1),
        parent_task_progress_json=parent_task_progress_json,
        parent_tasks_json=parent_tasks_json,
        plan_choices_json=plan_choices_json,
        current_modules_json=current_modules_json,
    )
    schema = {
        "ai_clinic": {"type": "string", "required": False},
        "next_week_focus": {"type": "array", "required": False},
        "plan_adjustments": {"type": "string", "required": False},
        "adjusted_modules": {"type": "array", "required": False},
        "motivation_message": {"type": "string", "required": False},
        "parent_guide": {"type": "string", "required": False},
    }
    return _get_client().call(
        prompt=prompt, schema=schema, task_id=task_id, call_type="plan"
    )


def generate_monthly_analysis(
    student_info: Dict,
    month_label: str,
    month_stats: Dict,
    kp_breakdown: str,
    score_history: str,
    task_id: int = None,
) -> Dict[str, Any]:
    """Generate AI monthly analysis via LLM."""
    prompt = MONTHLY_ANALYSIS_PROMPT.format(
        name=student_info.get("name", ""),
        grade=student_info.get("grade", ""),
        score=student_info.get("english_score", "未知"),
        month_label=month_label,
        total_mistakes=month_stats.get("total_mistakes", 0),
        mastered_count=month_stats.get("mastered_count", 0),
        practice_count=month_stats.get("practice_count", 0),
        accuracy=month_stats.get("avg_accuracy", "—"),
        kp_breakdown=kp_breakdown,
        score_history=score_history,
    )
    schema = {
        "progress_points": {"type": "array", "required": False},
        "regression_points": {"type": "array", "required": False},
        "next_month_suggestions": {"type": "array", "required": False},
        "overall_assessment": {"type": "string", "required": False},
    }
    return _get_client().call(
        prompt=prompt, schema=schema, task_id=task_id, call_type="plan"
    )

