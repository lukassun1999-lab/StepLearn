#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""题目生成：错题练习题、类似题、题库匹配（自 skills_bridge.py 拆出）。"""

import json
import logging
import re
from typing import Any, Dict, List

from bridge_common import _get_client
from knowledge_base import (get_question_types, normalize_knowledge_points)
from llm_prompts import QUESTION_GENERATION_PROMPT, SIMILAR_QUESTION_PROMPT

log = logging.getLogger(__name__)

_INFLECTION_HINT_TYPES = ("语法填空", "单句填空", "选词填空", "词汇拼写")
# 词形变化标记（规则变化）：最高级/比较级/时态/复数/词性后缀
_INFLECTION_MARKS = ("est", "ier", "iest", "ed", "es", "ies", "ly", "tion", "ment", "ing")


def _inflection_missing_hint(q: Dict) -> bool:
    """无选项题型的词形转换题是否缺括号提示词（实测：highest 无 high 提示，学生无法作答）。
    纯虚词空（连词/介词/冠词等）无需提示词，不算坏题。"""
    if not isinstance(q, dict):
        return False
    if (q.get("question_type") or "") not in _INFLECTION_HINT_TYPES:
        return False
    text = q.get("question_text") or ""
    if re.search(r"[（(]\s*[a-zA-Z]+", text):
        return False  # 已有括号提示词
    ans = str(q.get("correct_answer") or "").strip().lower()
    if not ans or " " in ans:
        return False  # 多词答案（the ones / so that 等）通常是虚词或指代，非词形转换
    return any(ans.endswith(m) for m in _INFLECTION_MARKS if len(ans) > len(m) + 1)


def generate_questions(mistakes: List[Dict], task_id: int = None,
                       target_count: int = None) -> Dict[str, Any]:
    """
    Generate practice questions. First try to reuse from question bank,
    then fall back to LLM for the rest. New LLM-generated questions are
    saved to the bank for future reuse.

    数量策略（2026-08-04 调整）：每个错题生成 2 道同一知识点练习题，
    不设总量上限（取消 15 道封顶）。

    Args:
        mistakes: list of mistake dicts to generate questions for
        task_id: optional AI task id for progress tracking
        target_count: 兼容参数，已忽略（固定为 len(mistakes) * 2）

    Returns: {"questions": [...], "from_bank": int, "generated": int}
    """
    from db import find_similar_questions, save_question, increment_question_usage

    # 过滤：听力/对话/写作等一律排除；阅读类仅在有短文（passage）时保留
    # （无短文无法自包含出题——此前会生成"引用 passage 但没给文章"的残题）
    kept = []
    for m in mistakes:
        qt = m.get("question_type", "")
        if qt in _READING_TYPES:
            if (m.get("passage") or "").strip():
                kept.append(m)  # 有短文 → 生成带原文的练习
            continue
        if not _is_excluded_type(qt):
            kept.append(m)
    mistakes = kept

    # 每错题 2 题，不设总量上限
    target_count = len(mistakes) * 2
    if target_count == 0:
        return {"questions": [], "from_bank": 0, "generated": 0}

    # Collect knowledge points from all mistakes
    all_kps = set()
    for m in mistakes:
        kps = m.get("knowledge_points", [])
        if isinstance(kps, str):
            kps = json.loads(kps)
        for kp in kps:
            all_kps.add(kp)

    # Try to find questions from bank
    bank_questions = find_similar_questions(
        knowledge_points=list(all_kps),
        limit=target_count,
    )

    selected_from_bank = []
    used_ids = []
    for q in bank_questions:
        # 跳过主观/无法自包含题型的历史坏题（听力/对话等）；阅读类题库题无短文信息，不可做
        if _is_excluded_type(str(q.get("question_type") or "")):
            continue
        if str(q.get("question_type") or "") in _READING_TYPES:
            continue
        # 跳过有选项题型但题干未内嵌选项的历史坏题（前端无法渲染）
        if (str(q.get("question_type") or "") in _OPTION_TYPES
                and not _options_embedded(q.get("question_text", ""))):
            continue
        # 跳过缺提示词的词形转换题（历史坏题，学生无法作答）
        if _inflection_missing_hint(q):
            continue
        selected_from_bank.append({
            "question_text": q["question_text"],
            "question_type": q["question_type"],
            "correct_answer": q["correct_answer"],
            "explanation": q["explanation"],
            "knowledge_points": q["knowledge_points"],
            "difficulty": q["difficulty"],
            "from_bank": True,
            "passage": "",
        })
        used_ids.append(q["id"])

    remaining = target_count - len(selected_from_bank)
    generated_questions = []
    bad_indexes = set()

    if remaining > 0:
        # Ask LLM to generate only for mistakes not covered by bank
        question_types_ref = get_question_types()
        from db import get_recent_correction_hints
        hints = get_recent_correction_hints(list(all_kps), content_type="question", limit=5)
        prompt = QUESTION_GENERATION_PROMPT.format(
            mistakes_json=json.dumps(mistakes, ensure_ascii=False, indent=2),
            question_types_ref=question_types_ref,
        )
        if hints:
            prompt = f"{prompt}\n\n{hints}"
        schema = {"questions": {"type": "array", "required": True}}
        result = _get_client().call(
            prompt=prompt, schema=schema, task_id=task_id, call_type="generate"
        )
        generated_questions = result.get("questions", [])[:remaining]

        # Save new questions to bank (linked to source mistake for tracking)
        mistake_by_id = {m.get("id"): m for m in mistakes}
        for i, q in enumerate(generated_questions):
            mistake = mistakes[i] if i < len(mistakes) else mistakes[-1] if mistakes else {}
            source_mistake_id = mistake.get("id")
            # 阅读类：生成题附带源错题的短文原文（渲染时随题展示，学生可依据短文答题）
            src = mistake_by_id.get(q.get("source_mistake_id")) or mistake
            q["passage"] = (src.get("passage") or "")
            # P3 质量硬化：填空类题型答案若被写成裸字母，回退源错题答案
            _fix_generated_answer_format(q, source_answer=mistake.get("correct_answer", ""))
            # 有选项题型：确保选项内嵌题干；无法拼装则标记坏题（不入库不下发）
            _ensure_options_embedded(q)
            try:
                q_text = q.get("question_text", "").strip()
                if (q.get("question_type") or "") in _OPTION_TYPES and not _options_embedded(q_text):
                    bad_indexes.add(i)
                    continue
                # 无选项词形转换题缺括号提示词 → 坏题（学生无法作答）
                if _inflection_missing_hint(q):
                    bad_indexes.add(i)
                    continue
                # Skip if too similar to an existing question in the bank
                existing = find_similar_questions(
                    knowledge_points=q.get("knowledge_points", []),
                    limit=10,
                )
                dup = False
                for ex in existing:
                    if _text_similarity(q_text, ex.get("question_text", "")) > 0.7:
                        dup = True
                        break
                if dup:
                    continue
                save_question({
                    "question_text": q_text,
                    "question_type": q.get("question_type", ""),
                    "correct_answer": q.get("correct_answer", ""),
                    "explanation": q.get("explanation", ""),
                    "knowledge_points": q.get("knowledge_points", []),
                    "difficulty": q.get("difficulty", 2),
                    "source": "llm",
                    "source_mistake_id": source_mistake_id,
                })
            except Exception:
                log.warning("题目入库失败（来源 llm）", exc_info=True)

    # Mark bank questions as used
    if used_ids:
        increment_question_usage(used_ids)

    # Normalize LLM-generated questions: options/knowledge_points must be lists
    # (LLM may emit null, which crashes renderers iterating over them)
    for q in generated_questions:
        if not isinstance(q, dict):
            continue
        if q.get("options") is None:
            q["options"] = []
        elif not isinstance(q["options"], list):
            q["options"] = [q["options"]]
        if q.get("knowledge_points") is None:
            q["knowledge_points"] = []
        elif not isinstance(q["knowledge_points"], list):
            q["knowledge_points"] = [q["knowledge_points"]]

    # 剔除选项缺失的坏题（有选项题型但题干无内嵌选项）
    if bad_indexes:
        generated_questions = [q for j, q in enumerate(generated_questions)
                               if j not in bad_indexes]

    final_questions = selected_from_bank + [
        {**q, "from_bank": False} for q in generated_questions
    ]

    return {
        "questions": final_questions,
        "from_bank": len(selected_from_bank),
        "generated": len(generated_questions),
    }


# ── 类似题生成 ──────────────────────────────────────

_FILL_BLANK_TYPES = ("语法填空", "选词填空", "单词拼写", "单句填空", "短文填空",
                     "翻译", "完成句子", "写作", "书面表达")
# 有选项题型：选项必须内嵌在题干中（前端/打印版均从题干解析选项）
_OPTION_TYPES = ("单项选择", "单项选择题", "多项选择", "选择题", "完形填空")
# 主观题型：不生成逐题练习（无标准判分），错题整理由错题本内容提炼
_SUBJECTIVE_TYPES = ("任务型阅读", "阅读理解", "阅读选择", "阅读判断", "阅读匹配",
                     "阅读表达", "阅读表达填空", "阅读表达问答", "信息匹配", "匹配题",
                     "补全对话", "情景交际", "填空题", "书面表达", "写作", "英语写作",
                     "听力填空", "听力选择", "听力判断", "听力匹配", "听短文填空", "听短文选择")


# 阅读类题型：有短文（passage）时可生成带原文的练习；无短文则无法自包含
_READING_TYPES = ("阅读理解", "阅读选择", "阅读判断", "阅读匹配", "阅读表达",
                  "阅读表达填空", "阅读表达问答", "任务型阅读", "信息匹配", "匹配题")


def _is_excluded_type(question_type: str) -> bool:
    """是否排除出逐题练习：主观/无法自包含/需特殊资源（听力类、对话类、无短文阅读类）。"""
    qt = question_type or ""
    if qt in _SUBJECTIVE_TYPES and qt not in _READING_TYPES:
        return True  # 阅读类单独按 passage 判断
    if "听力" in qt or "听短文" in qt or "补全对话" in qt:
        return True
    return False
_OPTION_INLINE_RE = None  # 懒加载


def _options_embedded(text: str) -> bool:
    """题干是否已内嵌 ≥2 个 A-D 选项（要求 ≥2 处匹配，避免 'tired.' 之类误报）。"""
    global _OPTION_INLINE_RE
    import re as _re
    if _OPTION_INLINE_RE is None:
        _OPTION_INLINE_RE = _re.compile(r"[A-Da-d][.、)）:：]\s*\S")
    return len(_OPTION_INLINE_RE.findall(text or "")) >= 2


def _ensure_options_embedded(q: Dict[str, Any]) -> bool:
    """有选项题型必须把选项内嵌进题干（P3 质量硬化）：
    - 题干已内嵌选项 → 直接通过
    - 否则用 LLM 返回的 options 字段拼装进题干
    - 无法拼装 → 返回 False，调用方应丢弃该题（坏题不入库不下发）
    无选项题型恒返回 True。
    """
    import re as _re
    qtype = str(q.get("question_type") or "")
    if qtype not in _OPTION_TYPES:
        return True
    text = str(q.get("question_text") or "").strip()
    if _options_embedded(text):
        return True
    opts = q.get("options")
    letters = ["A", "B", "C", "D", "E", "F"]
    lines = []
    if isinstance(opts, list):
        for i, o in enumerate(opts[:4]):
            if isinstance(o, dict):
                key = str(o.get("key") or letters[i])
                lines.append(f"{key}. {str(o.get('text', '')).strip()}".rstrip())
            else:
                o = str(o).strip()
                if _re.fullmatch(r"[A-Da-d]", o):
                    return False  # 纯字母无内容，无法拼装
                if _re.fullmatch(r"[A-Da-d][.、)）:：].*", o):
                    lines.append(o)
                else:
                    lines.append(f"{letters[i]}. {o}")
    if len(lines) >= 3 and all(l.split(". ", 1)[-1].strip() for l in lines):
        q["question_text"] = text + "\n" + "\n".join(lines)
        return True
    return False


def _fix_generated_answer_format(q: Dict[str, Any],
                                 source_answer: str = "") -> Dict[str, Any]:
    """生成题答案格式后置校验（P3 质量硬化）：
    - 无选项题型若答案被写成裸字母（A/B/C/D），回退为源错题的答案内容
    - 有选项题型：答案保留字母（由前端从题干解析选项）
    """
    import re as _re
    qtype = str(q.get("question_type") or "")
    answer = str(q.get("correct_answer") or "").strip()
    if qtype in _FILL_BLANK_TYPES and answer and _re.fullmatch(r"[A-Da-d]", answer):
        fallback = str(source_answer or "").strip()
        # 去掉源答案的选项字母前缀（如 "A. xxx" → "xxx"）
        fallback = _re.sub(r"^[A-Da-d][.、)）:：]\s*", "", fallback)
        if fallback:
            q["correct_answer"] = fallback
    return q


def _text_similarity(a: str, b: str) -> float:
    """Simple word-overlap similarity between two question texts. Returns 0.0–1.0."""
    import re
    def tokenize(s):
        return set(re.findall(r'[a-zA-Z一-鿿]+', str(s).lower()))
    ta, tb = tokenize(a), tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def generate_similar_questions(mistake: Dict, count: int = 2,
                                task_id: int = None) -> List[Dict[str, Any]]:
    """
    Generate similar questions for a single mistake via LLM.
    Saves generated questions to the bank with source_mistake_id link.
    Deduplicates: skips questions too similar to the original or to each other.
    Returns list of saved question dicts.
    """
    from db import save_question, get_question, get_connection
    import re as _re

    kps = mistake.get("knowledge_points", [])
    if isinstance(kps, str):
        try:
            kps = json.loads(kps)
        except Exception:
            kps = []

    # Fetch already-saved questions for this mistake (for dedup)
    existing_texts = []
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT question_text FROM questions WHERE source_mistake_id = ? AND enabled = 1",
            [mistake.get("id")],
        ).fetchall()
        conn.close()
        existing_texts = [r[0] for r in rows if r[0]]
    except Exception:
        log.warning("题库已有题目查询失败", exc_info=True)

    original_text = mistake.get("question", "")
    original_text_clean = _re.sub(r'[A-D]\.\s*\S+', '', original_text).strip()

    prompt = SIMILAR_QUESTION_PROMPT.format(
        count=min(count, 5),
        question=mistake.get("question", ""),
        question_type=mistake.get("question_type", "选择题"),
        correct_answer=mistake.get("correct_answer", ""),
        user_answer=mistake.get("user_answer", ""),
        explanation=mistake.get("explanation", ""),
        knowledge_points=", ".join(kps) if kps else "未知",
        difficulty=mistake.get("difficulty", 2),
    )

    schema = {"questions": {"type": "array", "required": True}}
    result = _get_client().call(
        prompt=prompt, schema=schema, task_id=task_id, call_type="generate"
    )

    questions = result.get("questions", [])
    saved = []
    seen_texts = list(existing_texts)  # track within this batch too
    for q in questions:
        if len(saved) >= count:
            break
        q_text = q.get("question_text", "").strip()
        if not q_text:
            continue
        # Skip if too similar to original mistake
        if _text_similarity(q_text, original_text_clean) > 0.7:
            continue
        # Skip if too similar to any already-saved or just-generated question
        dup = False
        for et in seen_texts:
            if _text_similarity(q_text, et) > 0.65:
                dup = True
                break
        if dup:
            continue
        # P3 质量硬化：填空类题型答案若被写成裸字母，回退源错题答案
        _fix_generated_answer_format(q, source_answer=mistake.get("correct_answer", ""))
        try:
            q_data = {
                "question_text": q_text,
                "question_type": q.get("question_type", mistake.get("question_type", "")),
                "correct_answer": q.get("correct_answer", ""),
                "explanation": q.get("explanation", ""),
                "knowledge_points": q.get("knowledge_points", kps),
                "difficulty": q.get("difficulty", mistake.get("difficulty", 2)),
                "source": "similar",
                "source_mistake_id": mistake.get("id"),
            }
            qid = save_question(q_data)
            saved.append(get_question(qid))
            seen_texts.append(q_text)
        except Exception:
            log.warning("相似题入库失败（来源 similar）", exc_info=True)

    return saved


def get_similar_questions_for_mistake(mistake_id: int) -> List[Dict[str, Any]]:
    """Get existing similar questions generated for a mistake."""
    from db import get_connection
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM questions WHERE source_mistake_id = ? AND enabled = 1 ORDER BY created_at DESC",
        [mistake_id],
    ).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["knowledge_points"] = json.loads(d.get("knowledge_points", "[]"))
        results.append(d)
