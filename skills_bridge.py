#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skill 调用封装层
Flask ↔ WorkBuddy Skills 的唯一桥梁。
Pipeline 代码只调这个模块，不直接操作 subprocess/LLM。
"""

import json
import os
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional

from llm import OCR_BACKEND, VISION_MODEL, LLMClient

# ═══════════════════════════════════════════════════
# Business Constants
# ═══════════════════════════════════════════════════

# 练习题数量策略（2026-08-04 调整）：每个错题生成 2 道同一知识点练习题，
# 不设总量上限（此前为 15 道封顶，已取消）。

# ═══════════════════════════════════════════════════
# Path Constants
# ═══════════════════════════════════════════════════

SKILLS_DIR = os.path.expanduser(r"~\.workbuddy\skills")
OCR_JS = os.path.join(SKILLS_DIR, "ocr-local", "scripts", "ocr.js")
# Our local wrapper with tessdata path configured
OCR_WRAPPER = os.path.join(os.path.dirname(__file__), "ocr_wrapper.js")
MISTAKE_ANALYZER_SCRIPTS = os.path.join(SKILLS_DIR, "english-mistake-analyzer", "scripts")
MISTAKE_ANALYZER_REFS = os.path.join(SKILLS_DIR, "english-mistake-analyzer", "references")
LEARNING_PLAN_REFS = os.path.join(SKILLS_DIR, "english-learning-plan", "references")

# Ensure skill scripts are importable
if MISTAKE_ANALYZER_SCRIPTS not in sys.path:
    sys.path.insert(0, MISTAKE_ANALYZER_SCRIPTS)


# ═══════════════════════════════════════════════════
# OCR (vision LLM primary, Tesseract fallback)
# ═══════════════════════════════════════════════════

VISION_OCR_PROMPT = """这是一张学生已作答的英语试卷图片。请仔细识别，并分两部分输出：

【第一部分：试卷正文】（按原文顺序）
- 逐题输出题号、题干、空格（用 ___题号___ 标注，如 ___36___）、选项（A/B/C/D 及其内容）。
- **重要：空格题号必须严格照抄试卷上印刷的数字，不得改写、重排或跳过。** 例如试卷上印的是 38，就写 ___38___，不要因为前面少识别了一个空格就写成 37。
- 每道题的选项按试卷原样列出。

【第二部分：学生作答】（重点，逐题识别）
学生通常在选项上打勾/画圈/填字母，或在横线上手写作答。请逐题列出学生的作答，格式为：
题号: 学生作答
例如：
26: B
27: even though
36: A
- 题号必须与试卷印刷题号一致。
- 若某题看不到学生作答痕迹，写"题号: 未作答"。
- 手写模糊无法辨认的，写"题号: [模糊]"，不要猜测具体内容。
- 特别注意：圈选标记旁边的选项字母、手写字母与题干粘连的情况（如把"B. full of"圈选后识别成"Bofull of"，应还原为 题号: B）。

直接输出内容，不要添加额外解释。"""


_MIN_OCR_TEXT_LENGTH = 1


def run_ocr_multimodal(image_path: str, task_id: int = None) -> Dict[str, Any]:
    """
    Run OCR using a vision-capable multimodal LLM.
    Returns: {"text": str, "confidence": float, "words": [], "backend": "vision"}
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    client = LLMClient(model=VISION_MODEL)
    result = client.call_vision(
        image_path=image_path,
        prompt=VISION_OCR_PROMPT,
        task_id=task_id,
        call_type="ocr",
    )

    # call_vision returns a parsed dict; raw text may be under _raw_text
    if isinstance(result, dict):
        text = result.get("text", result.get("_raw_text", ""))
    else:
        text = str(result)

    # Confidence heuristic: more [模糊] markers -> lower confidence
    fuzzy_count = text.count("[模糊]")
    total_chars = max(len(text), 1)
    confidence = max(0.5, 1.0 - (fuzzy_count / max(total_chars / 100, 1)))

    return {
        "text": text,
        "confidence": confidence,
        "words": [],
        "backend": "vision",
    }


def _run_tesseract_ocr(image_path: str, lang: str = "chi_sim+eng") -> Dict[str, Any]:
    """
    Original Tesseract.js OCR implementation.
    Returns: {"text": str, "confidence": float, "words": [...]}
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    # Set NODE_PATH + TESSDATA_PREFIX so Tesseract.js finds everything
    node_path = os.path.expanduser(r"~\.workbuddy\binaries\node\workspace\node_modules")
    tessdata_path = os.path.join(node_path, "tesseract.js-core", "tessdata")
    env = os.environ.copy()
    env["NODE_PATH"] = node_path
    env["TESSDATA_PREFIX"] = tessdata_path

    # Use our wrapper (has proper langPath) if tessdata exists; fall back to original
    tessdata_dir = os.path.join(os.path.dirname(__file__), "tessdata")
    ocr_script = OCR_WRAPPER if os.path.isdir(tessdata_dir) else OCR_JS

    result = subprocess.run(
        ["node", ocr_script, image_path, "--lang", lang, "--json"],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
        env=env,
    )
    if result.returncode != 0:
        stderr_msg = (result.stderr or "").strip() or result.stdout.strip() or "unknown error"
        raise RuntimeError(f"OCR failed (exit {result.returncode}): {stderr_msg[:200]}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        # If stdout isn't valid JSON, return raw text with default confidence
        return {"text": result.stdout, "confidence": 0.5, "words": []}

    text = data.get("text", "") if isinstance(data, dict) else result.stdout
    confidence = data.get("confidence", 0.5) if isinstance(data, dict) else 0.5
    words = data.get("words", []) if isinstance(data, dict) else []

    return {"text": text, "confidence": confidence, "words": words}


def run_ocr_parallel(image_paths, task_id=None, max_workers=4, progress=None):
    """OCR multiple images in parallel, preserving input order.

    Returns a list (same length/order as image_paths) of:
      {"text": str, "confidence": float, "ok": bool}

    Each page is OCR'd in its own thread (up to max_workers). DB writes use
    per-call connections (WAL + busy_timeout), so concurrent usage is safe.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    n = len(image_paths)
    if n == 0:
        return []

    def _one(i, path):
        try:
            r = run_ocr(path, task_id=task_id)
            return i, {"text": (r.get("text") or "").strip(),
                       "confidence": r.get("confidence", 0.0), "ok": True}
        except Exception:
            return i, {"text": "", "confidence": 0.0, "ok": False}

    results = [None] * n
    workers = max(1, min(max_workers, n))
    done_count = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_one, i, p): i for i, p in enumerate(image_paths)}
        for fut in as_completed(futs):
            i, res = fut.result()
            results[i] = res
            done_count += 1
            if progress and n:
                progress(f"OCR识别试卷 {done_count}/{n}", 15 + int(done_count / n * 10))
    return results


def run_ocr(image_path: str, lang: str = "chi_sim+eng",
            task_id: int = None) -> Dict[str, Any]:
    """
    Run OCR with automatic backend selection.
    Returns: {"text": str, "confidence": float, "words": [], "backend": str}
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    use_vision = OCR_BACKEND in ("auto", "vision")
    use_tesseract = OCR_BACKEND in ("auto", "tesseract")
    vision_error = None

    if use_vision:
        try:
            result = run_ocr_multimodal(image_path, task_id=task_id)
            if len(result.get("text", "").strip()) >= _MIN_OCR_TEXT_LENGTH:
                return result
            vision_error = "Vision OCR returned insufficient text"
        except Exception as e:
            vision_error = str(e)

    if use_tesseract:
        try:
            result = _run_tesseract_ocr(image_path, lang=lang)
            result["backend"] = "tesseract"
            if vision_error:
                result["vision_fallback_reason"] = vision_error
            return result
        except Exception as e:
            if vision_error:
                raise RuntimeError(
                    f"OCR failed: vision ({vision_error}), tesseract ({e})"
                )
            raise

    if vision_error:
        raise RuntimeError(
            f"Vision OCR failed and tesseract fallback disabled: {vision_error}"
        )

    raise RuntimeError("OCR backend configuration error")


# ═══════════════════════════════════════════════════
# Reference Reading (english-mistake-analyzer + english-learning-plan)
# ═══════════════════════════════════════════════════

def read_reference(skill: str, filename: str) -> str:
    """Read a reference file from a skill's references/ directory."""
    refs_dir = os.path.join(SKILLS_DIR, skill, "references")
    filepath = os.path.join(refs_dir, filename)
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Reference not found: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


def get_knowledge_framework() -> str:
    """Load the Gaokao English knowledge framework."""
    return read_reference("english-mistake-analyzer", "knowledge_framework.md")


def get_question_types() -> str:
    """Load the English exam question type taxonomy."""
    return read_reference("english-mistake-analyzer", "question_types.md")


def get_learning_plan_reference(stage: str) -> str:
    """Load a specific stage reference from english-learning-plan.
    stage: 'stage1' through 'stage6', or 'parent-growth-tasks'
    """
    filename = f"{stage}.md"
    return read_reference("english-learning-plan", filename)


# ═══════════════════════════════════════════════════
# Report Generation (import report_generator.py)
# ═══════════════════════════════════════════════════

def generate_weekly_report_html(week_start: str, week_end: str,
                                student_id: int = None) -> str:
    """
    Generate an HTML weekly report by calling report_generator.py.
    Returns the path to the generated HTML file.
    """
    from report_generator import weekly as gen_weekly  # may need adjustment
    # The report_generator.py CLI takes [YYYY-MM-DD] [YYYY-MM-DD]
    # We'll call it via subprocess for maximum compatibility
    result = subprocess.run(
        [sys.executable,
         os.path.join(MISTAKE_ANALYZER_SCRIPTS, "report_generator.py"),
         "weekly", week_start, week_end],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Report generation failed: {result.stderr.strip()}")

    # report_generator prints the output path
    output_path = result.stdout.strip().split("\n")[-1]
    return output_path


def generate_exam_html(questions: List[Dict], output_dir: str = None) -> str:
    """Generate a specialized practice exam HTML from questions list."""
    import tempfile
    if output_dir is None:
        output_dir = tempfile.mkdtemp()

    # Write questions to temp JSON
    qfile = os.path.join(output_dir, "questions.json")
    with open(qfile, "w", encoding="utf-8") as f:
        json.dump(questions, f, ensure_ascii=False, indent=2)

    result = subprocess.run(
        [sys.executable,
         os.path.join(MISTAKE_ANALYZER_SCRIPTS, "report_generator.py"),
         "exam", qfile],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Exam generation failed: {result.stderr.strip()}")

    output_path = result.stdout.strip().split("\n")[-1]
    return output_path


# ═══════════════════════════════════════════════════
# AI Analysis (LLM calls with SKILL.md prompt patterns)
# ═══════════════════════════════════════════════════

# ── Prompt Templates (extracted from english-mistake-analyzer SKILL.md) ──

MISTAKE_ANALYSIS_PROMPT = """分析以下英语试卷 OCR 文本，**只提取学生真正答错的题**，返回JSON（不要markdown代码块）:

{ocr_text}

【重要规则】
1. 只把"学生答案确实与正确答案不同"的题放进 mistakes。学生选对/填对的题一律不要放进来。
2. 比较时忽略选项字母前缀。例如学生答 "D. started a school"、正确答案 "started a school"，二者内容相同 → 学生答对了，**不要**算错题。同理 "A. cold"="cold"、"C, photographer"="photographer" 都算答对。
3. 注意 OCR 识别瑕疵：选项字母常与答案文字粘连，如 "Bofull of" 实为 "B. full of"、"A.cold" 实为 "A. cold"。需还原成真实作答再判断对错。
4. user_answer 与 correct_answer 必须用**同一格式**：
   - 有选项题型（单项选择/完形填空/多项选择等）：都写成「选项字母. 内容」（字母大写），如 "B. failed"、"A. until"，两者都带字母前缀；
   - 无选项题型（语法填空/选词填空/单句填空/翻译/写作等）：都只写答案内容（单词/短语/句子），不带字母。
5. question_text 必须包含该题**完整选项**：题干 + 换行 + 从 OCR 原样提取的选项列表（"A. xxx"、"B. xxx"...），不得省略选项。选项用于判对错（字母对应内容）与错题本展示。
6. 若无法判断学生真实作答或该题是否答错，则跳过该题，不要臆造错题。
   学生未作答/空白的题不要放进 mistakes（缺做不是"错"，无错因可归）。
7. 每道错题必须做错因分类，error_cause 五类取一：
   - vocab 单词不认识：生词、拼写、词义混淆、固定搭配不熟
   - grammar 语法规则没掌握：时态/语态/单复数/冠词/介词/非谓语/从句等规则错误
   - syntax 长句拆不开：句子结构、成分划分、语序理解失败
   - discourse 读不懂文章逻辑：主旨、推理、衔接、上下文理解失败
   - careless 看题不仔细：粗心、漏看、审题失误
   cause_evidence 用一句话给出判断依据（如"答案含未掌握生词 XXX"、"动词时态与时间状语不符"、"两个选项含义相近，属词义辨析"）。

返回格式:
{{"mistakes":[{{"question_number":1,"question_text":"完整题干（含全部选项）","question_type":"语法填空","correct_answer":"full of","user_answer":"fill of","error_cause":"vocab","cause_evidence":"拼写错误：full 写成 fill","explanation":"本题考查...","knowledge_points":["非谓语动词"],"difficulty":2}}],"summary":{{"total_mistakes":0,"by_type":{{"语法填空":2}},"top_weak_points":["非谓语动词"],"overall_assessment":"..."}}}}"""


CAUSE_CHAIN_PROMPT = """分析学生的错因因果链，返回JSON（不要markdown代码块）。

学生年级: {grade}
教材版本: {textbook_version}

错题清单（已按受控错因分类，含近期多次考试）:
{mistakes_json}

错因五类定义:
- vocab 单词不认识：生词、拼写、词义混淆、固定搭配不熟
- grammar 语法规则没掌握：时态/语态/单复数/冠词/介词/非谓语/从句等规则错误
- syntax 长句拆不开：句子结构、成分划分、语序理解失败
- discourse 读不懂文章逻辑：主旨、推理、衔接、上下文理解失败
- careless 看题不仔细：粗心、漏看、审题失误

判断要求（英语是累积性技能，词汇→句法→语篇层层传导）:
1. primary_cause 是"核心瓶颈"：不是错得最多的那类，而是"补上它，其他很多错题会跟着减少"的那类
2. cause_chain 列出核心瓶颈如何传导为其他错因（from→to + 一句说明）
3. priority_kps 按因果链给出 3 个聚焦知识点：先补根因，不是错误率最高的
4. plain_language 严格按模板填空（【】内填数据，不自由发挥话术）:
   "孩子这周真正卡住的是【核心瓶颈通俗名】——【证据一句话】，先补【第一聚焦点】。"

返回格式:
{{
  "primary_cause": "vocab|grammar|syntax|discourse|careless",
  "primary_evidence": "证据：基于错题的统计与判断",
  "cause_chain": [{{"from": "词汇", "to": "语法", "note": "词汇不足导致无法判断句子成分"}}],
  "secondary_causes": ["grammar"],
  "priority_kps": ["高频核心词汇", "现在完成时（受词汇连累，次生）", "长难句主干划分"],
  "plain_language": "孩子这周真正卡住的是【词汇量】——【语法错题里3道是被生词绊倒的】，先补【高频核心词汇】。"
}}"""


QUESTION_GENERATION_PROMPT = """根据错题生成同类练习题，返回JSON:

{mistakes_json}

题型规范: {question_types_ref}

硬性要求:
1. 每道题必须自包含：不得引用试卷原文、阅读材料、passage、上文/下文等外部上下文——学生看到题干就能独立作答
2. 答案格式必须与题型匹配：
   - 选择题/完形填空等有选项题型：把选项写进题干（如 "___1___ A. ...  B. ...  C. ...  D. ..."），correct_answer 写选项字母
   - 语法填空/选词填空/单句填空/翻译/写作等无选项题型：correct_answer **必须写单词/短语/句子本身**，严禁写字母（A/B/C/D）！
3. 题目难度与对应错题一致；每道题提供完整中文解析

返回格式:
{{"questions":[{{"source_mistake_id":1,"question_type":"语法填空","question_text":"完整题干（含选项，如为有选项题型）","options":["A","B","C","D"],"correct_answer":"按题型规则填字母或答案内容","explanation":"中文解析","knowledge_points":["非谓语动词"],"difficulty":2}}]}}"""


GRADING_PROMPT = """批改学生练习题答案，返回JSON:

练习题: {questions_json}
学生答案: {student_answers_json}

返回格式:
{{"results":[{{"question_index":0,"is_correct":true,"student_answer":"B","correct_answer":"B","explanation":"解析","knowledge_point_feedback":"掌握情况"}}],"summary":{{"total":10,"correct":7,"accuracy":0.7,"mastered_points":["定语从句"],"still_weak_points":["非谓语动词"],"overall_feedback":"总结"}}}}"""


LEARNING_PLAN_PROMPT = """为学生生成个性化学习方案，返回JSON（不要markdown代码块）。

学生基础信息:
- 姓名: {name}
- 年级: {grade}
- 当前分数: {score}
- 住校/走读: {school_type}
- 目标分数: {target_score}

错题与薄弱点诊断:
{diagnosis_json}

个性化画像（参考 chat.md 六大部分）:
{profile_json}

错因因果链画像（diagnosis_json 中的 cause_profile 字段，可能缺失）:
- 它给出孩子当前的核心瓶颈（primary_cause，如 vocab=词汇量不足）与传导链（cause_chain，如 词汇→语法）
- 若存在，weak_point_priority 必须遵守：**根因优先，不是错误率优先**
  1. 把因果链根因对应的知识点排在最前（即使它当前不是错误率最高的）
  2. "错得最多但属次生表现"的知识点应降级（如语法错题是词汇不足的下游症状时，语法类知识点排后）
  3. 每项 reason 必须引用因果链判断（如"词汇量是核心瓶颈，语法错题为次生表现"），不能只写"X道错题"
- 若 cause_profile 缺失或为空，按薄弱点矩阵常规排序

请基于以上画像做真正个性化的诊断和方案设计，返回格式:
{{
  "diagnosis_report": {{
    "learning_style": {{
      "visual": 0-10,
      "auditory": 0-10,
      "kinesthetic": 0-10,
      "read_write": 0-10,
      "dominant": "视觉型/听觉型/动觉型/读写型",
      "auxiliary": "...",
      "interpretation": "简短解读"
    }},
    "time_efficiency": {{
      "total_hours": "一周可用总时长",
      "peak_coverage": "高峰时段被英语学习覆盖的比例",
      "fragment_utilization": "碎片时间利用率评估",
      "conflict_risk": "时间冲突风险"
    }},
    "weak_point_matrix": [
      {{"point": "薄弱点", "loss_rate": "失分率", "potential": "提升潜力", "difficulty": "训练难度", "priority": "🥇/🥈/🥉"}}
    ],
    "psychological_motivation": {{
      "identity": "与英语的关系描述",
      "drive": "内驱力 1-5",
      "resilience": "抗挫力 1-5",
      "autonomy": "自主性 1-5"
    }},
    "conclusion": {{
      "core_findings": ["核心发现1", "核心发现2", "核心发现3"],
      "short_term": "短期建议（1个月）",
      "medium_term": "中期建议（1学期）",
      "long_term": "长期建议（1年）",
      "warning": "需要警惕的风险"
    }}
  }},
  "plan_design_logic": {{
    "time_allocation": "时间分配逻辑",
    "psychological_design": "心理动机设计",
    "cognitive_design": "认知规律设计",
    "precision_design": "精准提分设计",
    "anti_abandonment": "防放弃设计"
  }},
  "weekly_schedule": {{"saturday_afternoon": "完成练习题30分钟"}},
  "modules": [{{"name": "词汇", "priority": 1, "weekly_time_minutes": 120, "focus": "高考高频词汇", "daily_word_count": 8}}],
  "weak_point_priority": [{{"knowledge_point": "非谓语动词", "severity": "高", "reason": "2道错题"}}],
  "minimum_standard": {{"boarding": "每日词汇+1篇阅读", "day_student": "每晚词汇+听力"}},
  "motivation_message": "鼓励话，可结合孩子的1个月小目标和英语变厉害后想做什么",
  "parent_guide": "家长建议，结合家长陪学时间、监督需求、孩子心声",
  "parent_growth_tasks": [
    {{"week": 1, "theme": "观察者", "title": "情绪标注练习", "task": "连续3天，在孩子学英语时观察并记录情绪，不做评判", "example": "'我注意到你做阅读时皱了眉'", "goal": "帮助孩子被看见，降低焦虑"}},
    {{"week": 2, "theme": "倾听者", "title": "5分钟无评判倾听", "task": "每天留5分钟，只听孩子说说学英语的感受", "example": "'今天英语哪个部分最费劲？'", "goal": "建立安全表达通道"}},
    {{"week": 3, "theme": "提问者", "title": "错题分析会", "task": "陪孩子看错题，只提问不讲解", "example": "'这道题你当时怎么想的？'", "goal": "培养元认知和自主纠错"}},
    {{"week": 4, "theme": "肯定者", "title": "具体行为+影响反馈", "task": "每天反馈一个具体进步行为及其影响", "example": "'你今天主动复习了单词，这让我觉得你在为自己负责'", "goal": "强化内驱力和身份认同"}}
  ],
  "motivation_cards": [
    {{"title": "启动卡", "content": "一句针对孩子心声和目标的启动鼓励语"}},
    {{"title": "成就卡", "content": "可视化本周/本月进展的成就总结"}},
    {{"title": "抗挫卡", "content": "遇到错题或想放弃时可以读的一句话"}}
  ],
  "metacognitive_review": {{
    "child_reflection": [
      "这周学英语时，我最投入的是哪一刻？",
      "哪类题让我最有挫败感？我当时想到了什么？",
 "下周我想先攻克哪个小目标？"
    ],
    "parent_observation": [
      "这周孩子主动提到英语几次？",
      "孩子执行计划时，松紧程度如何？"
    ],
    "error_categories": ["语法混淆", "词汇不熟", "阅读理解", "听力", "写作表达", "粗心"],
    "adjustment_rules": "根据下周完成率自动调整：≥80% 提升10%难度；50-80% 维持；<50% 降低20%"
  }}
}}"""


PLAN_UPDATE_PROMPT = """更新学习方案，基于本周完成率和画像生成AI诊所建议与下周调整，返回JSON:

学生{student_id}, 周{week_start}
薄弱点: {weak_point_matrix}
新错题: {new_mistakes_json}
已掌握: {mastered_mistakes_json}
统计: 新{new_count} 掌握{mastered_count}

本周综合完成率: {completion_rate}%（学生活动权重60% + 家长参与权重40%）
家长任务包进度: {parent_task_progress_json}
家长任务包详情: {parent_tasks_json}
关键抉择（来自画像）: {plan_choices_json}
当前模块设置: {current_modules_json}

调整规则（必须遵守）:
- 综合完成率 ≥ 80%: 下周难度/任务量提升约 10%（可在现有 daily_word_count 上 +1~2，或增加 1 个薄弱模块练习）
- 综合完成率 50%-80%: 下周维持当前难度，优化时间安排或降低摩擦。若家长任务完成率低于学生活跃度，应在 parent_guide 中鼓励家长更多参与。
- 综合完成率 < 50%: 下周难度/任务量降低约 20%，并加入防放弃设计。需分析是学生端还是家长端掉队，给出针对性建议。

返回格式:
{{
  "updated_weak_points": [],
  "ai_clinic": "给老师的诊所建议",
  "next_week_focus": ["重点1", "重点2"],
  "plan_adjustments": "具体调整说明（含家长参与度分析）",
  "adjusted_modules": [{{"name": "词汇", "weekly_time_minutes": 120, "daily_word_count": 8, "focus": "..."}}],
  "motivation_message": "给孩子下周的鼓励语",
  "parent_guide": "给家长的建议（如果家长参与度低，提供降低门槛的建议）"
}}"""


# ── LLM-based functions ──

def _get_client():
    from llm import get_client
    return get_client()


def _normalize_answer(ans) -> str:
    """归一化答案用于比对：去选项字母前缀、去引号、统一小写、压缩空白。"""
    if ans is None:
        return ''
    s = str(ans).strip()
    # 去掉开头的选项字母前缀：A. / B) / C, / D、 / A： 等
    s = re.sub(r'^[A-Da-d]\s*[.)、,，:：]\s*', '', s)
    # 去掉首尾引号（中英文）
    s = s.strip('"\'“”‘’')
    # 压缩空白
    s = re.sub(r'\s+', ' ', s).strip()
    return s.lower()


def _answer_option_content(ans: str, question_text: str) -> str:
    """若 ans 为纯字母 A-D，尝试从题干内嵌选项解析对应内容；否则原样返回。

    解决「学生作答只记字母、正确答案记内容」的格式错位：
    - user_answer='a'、题干含 "A. until ... B. unless" → 解析为 'until'
    - 无选项可解析 → 返回原字母（保持可比较性）
    """
    import re as _re
    s = str(ans or "").strip()
    if not _re.fullmatch(r"[A-Da-d]", s):
        return s
    opts = _re.findall(
        r'([A-Da-d])[.、)）:：]\s*(.+?)(?=\s*[A-Da-d][.、)）:：]|$)', question_text or "")
    mapping = {k.upper(): v.strip() for k, v in opts}
    return mapping.get(s.upper(), s)


# ── 错因五类（受控枚举 + 关键词兜底映射）──────────
CAUSE_KEYS = ("vocab", "grammar", "syntax", "discourse", "careless")
CAUSE_LABELS = {"vocab": "词汇", "grammar": "语法", "syntax": "句法",
                "discourse": "语篇", "careless": "审题"}
_CAUSE_KEYWORDS = {
    "vocab": ["拼写", "单词", "词汇", "生词", "词义", "词形", "搭配", "不认识",
              "辨析", "固定表达", "情景交际"],
    "grammar": ["时态", "语态", "单复数", "冠词", "介词", "非谓语", "从句",
                "主谓一致", "语法", "词性", "规则", "连词", "虚拟", "最高级",
                "比较级", "情态", "复数", "谓语", "代词", "成分"],
    "syntax": ["长难句", "句子结构", "成分", "语序", "句式", "主干", "拆分"],
    "discourse": ["主旨", "推理", "逻辑", "上下文", "衔接", "语篇", "篇章",
                  "细节理解", "态度", "情感"],
    "careless": ["粗心", "漏看", "审题", "抄错", "笔误", "没看清"],
}
_CAUSE_DEFAULT = "grammar"
_UNANSWERED_MARKERS = ("未作答", "未完成", "空白", "未填写", "没有作答",
                       "no answer", "blank", "学生未答")

# ── 受控知识点词表（knowledge_points.json，归一化映射）──
_KP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "knowledge_points.json")
_KP_TABLE = None       # [{"id","c","a","l","g"}, ...]
_KP_INDEX = None       # alias/canonical(去空白) → canonical


def _load_knowledge_base() -> None:
    """加载受控知识点词表（进程内缓存）。缺失时降级为空词表（不阻断主链路）。"""
    global _KP_TABLE, _KP_INDEX
    if _KP_TABLE is not None:
        return
    try:
        with open(_KP_FILE, encoding="utf-8") as f:
            data = json.load(f)
        _KP_TABLE = data.get("points") or []
        _KP_INDEX = {}
        for p in _KP_TABLE:
            c = (p.get("c") or "").strip()
            if not c:
                continue
            _KP_INDEX[c.replace(" ", "")] = c
            for a in p.get("a") or []:
                a = (a or "").strip()
                if a:
                    _KP_INDEX[a.replace(" ", "")] = c
    except Exception:
        _KP_TABLE = []
        _KP_INDEX = {}


def normalize_knowledge_points(raw_labels) -> tuple:
    """受控词表归一化：自由标签 → canonical 列表。

    匹配策略（按优先级）：
    1. 精确匹配（canonical 或 alias，忽略空白）
    2. 标签更细：canonical 是标签的子串（"现在完成时的用法"→"现在完成时"），取最长
    3. 标签更粗：标签是 canonical 的子串，仅当唯一匹配时映射（歧义 → 进未识别池）
    返回 (canonical 去重列表, 未识别标签去重列表)。
    """
    _load_knowledge_base()
    canonicals, unmapped = [], []
    for raw in raw_labels or []:
        label = str(raw or "").strip()
        if not label:
            continue
        key = label.replace(" ", "")
        matched = _KP_INDEX.get(key) if _KP_INDEX else None
        if not matched and _KP_TABLE:
            # 标签更细：canonical 是标签子串
            finer = [p["c"] for p in _KP_TABLE if p["c"].replace(" ", "") in key]
            if finer:
                matched = max(finer, key=len)
            else:
                # 标签更粗：仅唯一 canonical 包含标签才映射
                coarser = [p["c"] for p in _KP_TABLE
                           if key in p["c"].replace(" ", "")]
                if len(coarser) == 1:
                    matched = coarser[0]
        if matched:
            if matched not in canonicals:
                canonicals.append(matched)
        else:
            if label not in unmapped:
                unmapped.append(label)
    return canonicals, unmapped


def _is_unanswered(m: Dict) -> bool:
    """未作答/缺做题没有认知层面的错因，不应参与错因统计。
    以解析文本中的标记为准；user_answer 缺失不算（可能是 LLM 漏输出）。"""
    reason = " ".join(filter(None, [
        m.get("error_reason", ""), m.get("cause_evidence", ""),
        m.get("explanation", ""),
    ]))
    if any(k in reason for k in _UNANSWERED_MARKERS):
        return True
    user_ans = str(m.get("user_answer") or "").strip()
    return bool(user_ans) and user_ans in ("-", "—", "？", "?", "/")


def _normalize_error_cause(m: Dict) -> Optional[str]:
    """兜底：LLM 未输出受控错因时，按题型加权 + 关键词映射到五类之一。
    未作答/缺做返回 None（不进错因统计）。"""
    cause = (m.get("error_cause") or "").strip()
    if cause in CAUSE_KEYS:
        return cause
    if _is_unanswered(m):
        return None
    reason = " ".join(filter(None, [
        m.get("error_reason", ""), m.get("cause_evidence", ""),
        m.get("explanation", "")[:80], m.get("question_type", ""),
    ]))
    qtype = m.get("question_type") or ""
    # 题型加权（先于关键词）：阅读/匹配/任务型 → 语篇；情景交际 → 表达积累
    if any(k in qtype for k in ("阅读", "匹配", "任务型", "信息")):
        return "discourse"
    if any(k in qtype for k in ("补全对话", "情景", "交际")):
        return "vocab"
    # 完形填空以词义/语境选择为主，除非明确涉及语法规则
    if "完形" in qtype:
        if any(k in reason for k in _CAUSE_KEYWORDS["grammar"]):
            return "grammar"
        return "vocab"
    for key in CAUSE_KEYS:
        if any(k in reason for k in _CAUSE_KEYWORDS[key]):
            return key
    return _CAUSE_DEFAULT


def _statistical_cause_profile(mistakes: List[Dict]) -> Optional[Dict[str, Any]]:
    """纯统计兜底画像：LLM 不可用时的错因分布 + 简单传导链（不依赖大模型）。"""
    counts = {k: 0 for k in CAUSE_KEYS}
    by_cause = {k: [] for k in CAUSE_KEYS}
    for m in mistakes:
        c = _normalize_error_cause(m)
        if c is None:  # 未作答/缺做：无认知错因，跳过
            continue
        counts[c] += 1
        by_cause[c].append(m)
    if not mistakes or sum(counts.values()) == 0:
        return None
    primary = max(counts, key=counts.get)
    secondary = [k for k in CAUSE_KEYS if k != primary and counts[k] > 0]

    chain = []
    cascade = {"vocab": ["grammar", "syntax", "discourse"],
               "grammar": ["syntax", "discourse"], "syntax": ["discourse"]}
    for to in cascade.get(primary, []):
        if counts.get(to, 0) > 0:
            note = {"vocab": "生词阻断句意理解", "grammar": "规则不牢导致长句分析失败",
                    "syntax": "长句拆不开导致篇章理解受阻"}.get(to, "层层传导")
            chain.append({"from": CAUSE_LABELS[primary], "to": CAUSE_LABELS[to], "note": note})

    kp_counter = {}
    for m in by_cause[primary]:
        for kp in (m.get("knowledge_points") or [])[:2]:
            kp_counter[kp] = kp_counter.get(kp, 0) + 1
    priority_kps = [kp for kp, _ in sorted(kp_counter.items(), key=lambda x: -x[1])][:3]

    label = CAUSE_LABELS[primary]
    evidence = f"共 {counts[primary]} 道错题集中在这一环节" + (
        f"，另有 {counts[secondary[0]]} 道属于{CAUSE_LABELS[secondary[0]]}（次生）"
        if secondary else "")
    plain = f"孩子这周真正卡住的是【{label}】——【{evidence}】，先补【{priority_kps[0] if priority_kps else '基础'}】。"
    return {
        "primary_cause": primary,
        "primary_evidence": evidence,
        "cause_chain": chain,
        "secondary_causes": secondary,
        "priority_kps": priority_kps,
        "plain_language": plain,
    }


def _filter_real_mistakes(mistakes: List[Dict]) -> List[Dict]:
    """
    兜底过滤：把"学生答案与正确答案实质相同"的条目剔除（不算错题）。
    同时把 user_answer / correct_answer 归一化为不带选项字母的纯答案内容。
    """
    import re as _re
    real = []
    for m in mistakes:
        raw_u = m.get('user_answer')
        raw_c = m.get('correct_answer')
        nu = _normalize_answer(raw_u)
        nc = _normalize_answer(raw_c)
        user_display = None  # 展示用（保留「字母. 内容」格式）
        # 纯字母作答（如 'a'）：从题干选项解析内容后再比较（'a' → 'until'）
        if raw_u and _re.fullmatch(r"[A-Da-d]", str(raw_u).strip()):
            content = _answer_option_content(raw_u, m.get('question_text', ''))
            if content != str(raw_u).strip():
                nu = _normalize_answer(content)
                user_display = f"{str(raw_u).strip().upper()}. {content}"
        # 二者都有内容且实质相同 → 学生答对了，剔除
        if nu and nc and nu == nc:
            continue
        # 归一化写回：字母解析过的保留「字母. 内容」，其余去字母前缀
        if raw_u:
            m['user_answer'] = user_display or (_normalize_answer(raw_u) or raw_u)
        if raw_c:
            m['correct_answer'] = _normalize_answer(raw_c) or raw_c
        real.append(m)
    return real


def analyze_mistakes(ocr_text: str, task_id: int = None) -> Dict[str, Any]:
    """
    Run mistake analysis via LLM (english-mistake-analyzer STEP 2).
    Returns: {"mistakes": [...], "summary": {...}}
    """
    from db import get_recent_correction_hints
    hints = get_recent_correction_hints([], content_type="mistake", limit=5)
    prompt = MISTAKE_ANALYSIS_PROMPT.format(ocr_text=ocr_text)
    if hints:
        prompt = f"{prompt}\n\n{hints}"
    schema = {
        "mistakes": {"type": "array", "required": True},
        "summary": {"type": "object", "required": True},
    }
    result = _get_client().call(
        prompt=prompt, schema=schema, task_id=task_id, call_type="analyze"
    )
    # 兜底：剔除"答对却被当成错题"的条目，并归一化答案格式
    if isinstance(result, dict) and isinstance(result.get('mistakes'), list):
        before = len(result['mistakes'])
        result['mistakes'] = _filter_real_mistakes(result['mistakes'])
        dropped = before - len(result['mistakes'])
        # 错因归一化：LLM 未输出受控 error_cause 时按题型加权+关键词兜底映射
        # （未作答/缺做 → 空串，不进错因统计）
        for m in result['mistakes']:
            if not (m.get("error_cause") or "").strip():
                m["error_cause"] = _normalize_error_cause(m) or ""
        # 知识点归一化：自由标签 → 受控词表 canonical；未识别进池（带频次统计）
        unmapped_all = []
        for m in result['mistakes']:
            kps = m.get("knowledge_points") or []
            if isinstance(kps, str):
                try:
                    kps = json.loads(kps)
                except Exception:
                    kps = []
            if kps:
                canon, unmapped = normalize_knowledge_points(kps)
                # 一律写回 canonical（即使为空）——入库的永远是受控标签，未识别进池
                m["knowledge_points"] = canon
                unmapped_all.extend(unmapped)
        if unmapped_all:
            from db import record_unmapped_kps
            record_unmapped_kps(list(dict.fromkeys(unmapped_all)))
        if isinstance(result.get('summary'), dict):
            summary = result['summary']
            if dropped:
                summary.setdefault('overall_assessment', '')
                summary['overall_assessment'] = (
                    f"(已自动剔除 {dropped} 道误判为错题的答对题目) " +
                    (summary.get('overall_assessment') or '')
                )
            # 同步 summary 统计，避免与过滤后的 mistakes 不一致
            kept = result['mistakes']
            summary['total_mistakes'] = len(kept)
            by_type = {}
            for m in kept:
                qt = m.get('question_type') or '其他'
                by_type[qt] = by_type.get(qt, 0) + 1
            if by_type:
                summary['by_type'] = by_type
    return result


def analyze_cause_chain(student: Dict, mistakes: List[Dict],
                        task_id: int = None) -> Optional[Dict[str, Any]]:
    """
    错因因果链分析（差异化支柱核心）：
    找出核心瓶颈（primary_cause）、传导链、根因优先的聚焦知识点与家长一句话。
    LLM 不可用时回退到纯统计画像（_statistical_cause_profile），保证主链路稳定。
    """
    from db import get_unmastered_mistakes
    payload = [m for m in mistakes if m.get("error_cause") or m.get("error_reason")]
    try:
        recent = get_unmastered_mistakes(student["id"]) or []
    except Exception:
        recent = []
    for m in recent:
        if isinstance(m, dict) and m.get("question"):
            payload.append({
                "question_type": m.get("question_type", ""),
                "question_text": m.get("question", "")[:120],
                "error_cause": m.get("error_cause") or "",
                "error_reason": (m.get("explanation") or "")[:80],
                "knowledge_points": m.get("knowledge_points", []),
            })
    # 按题干去重（本次与近期可能重复）
    seen, dedup = set(), []
    for m in payload:
        q = (m.get("question_text") or "").strip()
        if q and q in seen:
            continue
        seen.add(q)
        # 知识点归一化到受控词表（本次为新标签，近期为存量自由标签，统一处理）
        kps = m.get("knowledge_points") or []
        if isinstance(kps, str):
            try:
                kps = json.loads(kps)
            except Exception:
                kps = []
        canon, _ = normalize_knowledge_points(kps)
        m["knowledge_points"] = canon
        dedup.append(m)
    if not dedup:
        return None

    prompt = CAUSE_CHAIN_PROMPT.format(
        grade=student.get("grade", "高二"),
        textbook_version=student.get("textbook_version") or "未选择",
        mistakes_json=json.dumps(dedup[:30], ensure_ascii=False),
    )
    schema = {
        "primary_cause": {"type": "string", "required": True},
        "primary_evidence": {"type": "string", "required": True},
        "cause_chain": {"type": "array", "required": False},
        "secondary_causes": {"type": "array", "required": False},
        "priority_kps": {"type": "array", "required": True},
        "plain_language": {"type": "string", "required": False},
    }
    try:
        result = _get_client().call(
            prompt=prompt, schema=schema, task_id=task_id, call_type="cause_chain")
    except Exception:
        result = {}
    if not isinstance(result, dict) or result.get("primary_cause") not in CAUSE_KEYS:
        # LLM 不可用 / 输出无效 → 统计兜底画像
        return _statistical_cause_profile(dedup)

    profile = {
        "primary_cause": result["primary_cause"],
        "primary_evidence": result.get("primary_evidence") or "",
        "cause_chain": result.get("cause_chain") or [],
        "secondary_causes": [c for c in (result.get("secondary_causes") or [])
                             if c in CAUSE_KEYS],
        "priority_kps": (result.get("priority_kps") or [])[:3],
        "plain_language": result.get("plain_language") or "",
    }
    if not profile["plain_language"]:
        fallback = _statistical_cause_profile(dedup)
        profile["plain_language"] = (fallback or {}).get("plain_language", "")
    return profile


def build_cause_trend(current: Dict, previous: Dict) -> Optional[Dict[str, Any]]:
    """跨周错因对比 → 进步叙事（模板生成，不依赖 LLM）。
    current/previous 为 cause_profile_history 记录（含 cause_counts 五类分布）。
    返回 {"narrative", 本周/上周 label 与占比} 或 None（数据不足）。
    """
    cur_cause = current.get("primary_cause") or ""
    prev_cause = previous.get("primary_cause") or ""
    if cur_cause not in CAUSE_KEYS or prev_cause not in CAUSE_KEYS:
        return None
    cur_counts = current.get("cause_counts") or {}
    prev_counts = previous.get("cause_counts") or {}
    cur_total = sum(cur_counts.values()) or 1
    prev_total = sum(prev_counts.values()) or 1
    cur_pct = round(cur_counts.get(cur_cause, 0) * 100 / cur_total)
    prev_pct = round(prev_counts.get(prev_cause, 0) * 100 / prev_total)
    cur_label = CAUSE_LABELS[cur_cause]
    prev_label = CAUSE_LABELS[prev_cause]

    if cur_cause == prev_cause:
        if cur_pct < prev_pct:
            narrative = (f"「{cur_label}」问题在缓解——占错题比例从 {prev_pct}% 降到 {cur_pct}%，"
                         f"练习见效了，坚持就是胜利。")
        elif cur_pct > prev_pct:
            narrative = (f"「{cur_label}」仍是本周的主要卡点（{prev_pct}% → {cur_pct}%），"
                         f"需要集中火力继续攻。")
        else:
            narrative = (f"「{cur_label}」依旧是最需要攻克的部分（约 {cur_pct}% 的错题），"
                         f"这周继续聚焦。")
    else:
        if prev_pct >= cur_pct:
            narrative = (f"上周的「{prev_label}」（{prev_pct}%）补上来了，"
                         f"本周新卡点是「{cur_label}」——说明在往前走了。")
        else:
            narrative = (f"核心卡点从「{prev_label}」转向「{cur_label}」"
                         f"（{prev_pct}% → {cur_pct}%），进入新阶段，注意新问题。")

    return {
        "narrative": narrative,
        "current_primary": cur_cause,
        "previous_primary": prev_cause,
        "current_primary_label": cur_label,
        "previous_primary_label": prev_label,
        "current_pct": cur_pct,
        "previous_pct": prev_pct,
    }


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

    # 主观题型（阅读/任务型/写作等）不进逐题练习：不生成练习题，
    # 其错题整理由错题本内容提炼（周报/月度总结素材）
    mistakes = [m for m in mistakes
                if m.get("question_type") not in _SUBJECTIVE_TYPES]

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
        # 跳过有选项题型但题干未内嵌选项的历史坏题（前端无法渲染）
        if (str(q.get("question_type") or "") in _OPTION_TYPES
                and not _options_embedded(q.get("question_text", ""))):
            continue
        selected_from_bank.append({
            "question_text": q["question_text"],
            "question_type": q["question_type"],
            "correct_answer": q["correct_answer"],
            "explanation": q["explanation"],
            "knowledge_points": q["knowledge_points"],
            "difficulty": q["difficulty"],
            "from_bank": True,
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
        for i, q in enumerate(generated_questions):
            mistake = mistakes[i] if i < len(mistakes) else mistakes[-1] if mistakes else {}
            source_mistake_id = mistake.get("id")
            # P3 质量硬化：填空类题型答案若被写成裸字母，回退源错题答案
            _fix_generated_answer_format(q, source_answer=mistake.get("correct_answer", ""))
            # 有选项题型：确保选项内嵌题干；无法拼装则标记坏题（不入库不下发）
            _ensure_options_embedded(q)
            try:
                q_text = q.get("question_text", "").strip()
                if (q.get("question_type") or "") in _OPTION_TYPES and not _options_embedded(q_text):
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
                pass

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


SIMILAR_QUESTION_PROMPT = """你是一位经验丰富的英语老师。学生做错了下面这道题，请生成{count}道考察**同一知识点**但题干完全不同的类似题，帮助学生巩固。

原错题:
- 题目: {question}
- 题型: {question_type}
- 正确答案: {correct_answer}
- 学生答案: {user_answer}
- 解析: {explanation}
- 知识点: {knowledge_points}

硬性要求:
1. 每道类似题考察相同的知识点，但必须更换场景、人物、语境、词汇——不得仅替换一两个词
2. 严禁生成与原题题干相同或高度相似的题目（如仅换了人名/动词）
3. 每道题的场景必须互不相同（比如一道关于学校、一道关于家庭、一道关于社会）
4. 题目难度与原题一致
5. 每道题提供完整中文解析
6. **题目必须自包含**：不得引用试卷原文、阅读材料、passage、上文/下文等外部上下文——学生看到题干就能独立作答
7. **答案格式必须与题型匹配**：
   - 选择题/完形填空（有选项的题型）：把选项写进题干（如 "___1___ A. ...  B. ...  C. ...  D. ..."），correct_answer 写选项字母
   - 语法填空/选词填空/单句填空/翻译/写作（无选项题型）：correct_answer **必须写单词/短语/句子本身**，严禁写字母（A/B/C/D）！

返回JSON格式:
{{"questions":[{{"question_text":"完整题干（含选项，如为有选项题型）","question_type":"{question_type}","options":["A","B","C","D"],"correct_answer":"按题型规则填字母或答案内容","explanation":"中文解析","knowledge_points":["知识点"],"difficulty":{difficulty}}}]}}"""


# 无选项题型：答案必须为单词/短语/句子本身（禁止裸字母）
_FILL_BLANK_TYPES = ("语法填空", "选词填空", "单词拼写", "单句填空", "短文填空",
                     "翻译", "完成句子", "写作", "书面表达")
# 有选项题型：选项必须内嵌在题干中（前端/打印版均从题干解析选项）
_OPTION_TYPES = ("单项选择", "多项选择", "选择题", "完形填空")
# 主观题型：不生成逐题练习（无标准判分），错题整理由错题本内容提炼
_SUBJECTIVE_TYPES = ("任务型阅读", "阅读理解", "写作", "书面表达")
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
        pass

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
            pass

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
    return results


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
    return _get_client().call(
        prompt=prompt, schema=schema, task_id=task_id, call_type="plan"
    )


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


# ═══════════════════════════════════════════════════
# Monthly Analysis
# ═══════════════════════════════════════════════════

MONTHLY_ANALYSIS_PROMPT = """你是学生的英语学习顾问，请基于以下月度数据生成分月总结分析，返回JSON（不要markdown代码块）。

学生: {name}, 年级: {grade}, 当前分数: {score}
月份: {month_label}

月度数据:
- 总错题数: {total_mistakes}
- 已攻克数: {mastered_count}
- 练习次数: {practice_count}
- 平均正确率: {accuracy}

知识点错题分布:
{kp_breakdown}

分数变化:
{score_history}

请从以下维度分析:
1. 进步亮点: 哪些知识点有明显进步？哪些错误类型在减少？
2. 需要关注: 哪些知识点反复出错？有没有退步的趋势？
3. 下月建议: 针对性地给出2-3条下月学习重点建议

返回格式:
{{"progress_points":["进步1","进步2"],"regression_points":["关注1"],"next_month_suggestions":["建议1","建议2"],"overall_assessment":"一句话总结本月表现和趋势"}}"""


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


# ═══════════════════════════════════════════════════
# Test
# ═══════════════════════════════════════════════════

if __name__ == "__main__":
    # Test file existence
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
