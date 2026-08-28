#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识库与归一化：skill 参考文件读取、受控词表映射、错因五类、
答案归一化、真错题过滤（自 skills_bridge.py 拆出）。
"""

import json
import os
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional

from bridge_common import (MISTAKE_ANALYZER_REFS, MISTAKE_ANALYZER_SCRIPTS,
                           LEARNING_PLAN_REFS, SKILLS_DIR)

# ═══════════════════════════════════════════════════
# Reference Reading (english-mistake-analyzer + english-learning-plan)
# ═══════════════════════════════════════════════════

def _project_references_dir() -> str:
    """项目内 references/ 目录（与 SKILLS_DIR 行为互补）。

    服务器（Linux/容器）通常没有 ~/.workbuddy/skills，因此把 skill 参考文件
    随仓库分发在 references/ 下，避免运行时 FileNotFoundError。
    """
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "references")


def read_reference(skill: str, filename: str) -> str:
    """Read a reference file from a skill's references/ directory.

    查找顺序：
      1. 项目内 <project>/references/<skill>/references/<filename>（部署自带）
      2. SKILLS_DIR（~/.workbuddy/skills/...，本地开发可跟随 skill 更新）
    """
    project_refs = os.path.join(_project_references_dir(), skill, "references", filename)
    if os.path.exists(project_refs):
        with open(project_refs, "r", encoding="utf-8") as f:
            return f.read()

    refs_dir = os.path.join(SKILLS_DIR, skill, "references")
    filepath = os.path.normpath(os.path.join(refs_dir, filename))
    if not os.path.exists(filepath):
        raise FileNotFoundError(
            f"Reference not found: tried {project_refs} and {filepath}"
        )
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
# 题型前缀：归一化前剥离（"阅读理解-细节理解" → "细节理解"）
_KP_TYPE_PREFIXES = ("阅读理解", "阅读", "完形填空", "完形", "语法填空",
                     "选词填空", "任务型阅读", "信息匹配", "单项选择")
# 题型词忽略列表：LLM 常把题型当知识点输出，直接忽略（不进词表、不刷未识别池）
_KP_IGNORE = frozenset({
    "阅读理解", "阅读", "阅读匹配", "阅读表达", "阅读表达填空", "阅读表达问答",
    "语法填空", "完形填空", "选词填空", "单项选择", "填空题", "匹配题",
    "任务型阅读", "任务型", "书面表达", "写作", "英语写作", "英语表达",
    "补全对话", "问答", "综合", "细节填空", "词形变化", "历史知识",
})


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
    0. 忽略列表中的题型词直接丢弃；剥离题型前缀（"阅读理解-细节理解"）
    1. 精确匹配（canonical 或 alias，忽略空白）
    2. 标签更细：canonical 是标签的子串（"现在完成时的用法"→"现在完成时"），取最长
    3. 标签更粗：标签是 canonical 的子串，仅当唯一匹配时映射（歧义 → 进未识别池）
    返回 (canonical 去重列表, 未识别标签去重列表)。
    """
    _load_knowledge_base()
    canonicals, unmapped = [], []

    def _match(key):
        m = _KP_INDEX.get(key) if _KP_INDEX else None
        if not m and _KP_TABLE:
            finer = [p["c"] for p in _KP_TABLE if p["c"].replace(" ", "") in key]
            if finer:
                m = max(finer, key=len)
            else:
                coarser = [p["c"] for p in _KP_TABLE
                           if key in p["c"].replace(" ", "")]
                if len(coarser) == 1:
                    m = coarser[0]
        return m

    for raw in raw_labels or []:
        label = str(raw or "").strip()
        if not label:
            continue
        key = label.replace(" ", "")
        matched = _match(key)
        if not matched:
            # 题型前缀剥离后重试（"阅读理解-细节理解" → "细节理解"）
            for prefix in _KP_TYPE_PREFIXES:
                if key.startswith(prefix + "-"):
                    stripped = key[len(prefix) + 1:]
                    matched = _match(stripped)
                    key = stripped
                    break
        if matched:
            if matched not in canonicals:
                canonicals.append(matched)
        elif (key in _KP_IGNORE or label in _KP_IGNORE
              or any(label.startswith(ig + "（") or label.startswith(ig + "(")
                     for ig in _KP_IGNORE)):
            # 题型词/带括号说明的题型词直接丢弃（"历史知识（工业革命前的睡眠习惯）"）
            continue
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
    from domain.grading import is_answer_correct
    real = []
    for m in mistakes:
        raw_u = m.get('user_answer')
        raw_c = m.get('correct_answer')
        # 统一判分语义先行（与在线练习/批改同源）：备选答案任一命中
        # （common/ordinary/normal → normal 即对）、首尾标点/大小写/全角
        # 差异（nature. vs nature）→ 学生其实答对了，不构成错题。
        # 仅在两侧都有内容时生效，纯字母/括号格式等复杂形态交给下方兜底。
        if is_answer_correct(raw_u, raw_c):
            continue
        nu = _normalize_answer(raw_u)
        nc = _normalize_answer(raw_c)
        user_display = None
        # 括号格式（OCR/LLM 常见）："b (false)"、"a (high)"、"c(so that)"
        # → 提取 (字母, 内容)；支持纯字母作答与括号格式答案的字母比对
        up = _re.match(r'^([A-Da-d])\s*[（(]\s*(.+?)\s*[）)]$', str(raw_u or '').strip())
        cp = _re.match(r'^([A-Da-d])\s*[（(]\s*(.+?)\s*[）)]$', str(raw_c or '').strip())
        up = (up.group(1).upper(), up.group(2).strip()) if up else None
        cp = (cp.group(1).upper(), cp.group(2).strip()) if cp else None

        if up and cp:
            # 双方都是"字母(内容)"：字母相同或内容相同 → 答对
            if up[0] == cp[0] or up[1] == cp[1]:
                continue
            nu, nc = up[1], cp[1]
        elif up and not cp:
            # 学生答案"字母(内容)"、正确无字母 → 比较内容
            nu = up[1]
            user_display = f"{up[0]}. {up[1]}"
        elif cp and not up and _re.fullmatch(r"[A-Da-d]", str(raw_u or '').strip()):
            # 学生纯字母、正确"字母(内容)"：字母相同 → 答对（如 阅读判断 b vs "b (false)"）
            if str(raw_u).strip().upper() == cp[0]:
                continue
            # 字母不同：若题干无选项可解析 → 无法确认学生选择的内容 → 存疑跳过（不冤枉）
            content = _answer_option_content(raw_u, m.get('question_text', ''))
            if content == str(raw_u).strip():
                continue
            nu = cp[1]

        # 纯字母作答（如 'a'）：从题干选项解析内容后再比较（'a' → 'until'）
        if raw_u and not up and not cp and _re.fullmatch(r"[A-Da-d]", str(raw_u).strip()):
            content = _answer_option_content(raw_u, m.get('question_text', ''))
            if content != str(raw_u).strip():
                nu = _normalize_answer(content)
                user_display = f"{str(raw_u).strip().upper()}. {content}"
            else:
                # 题干无选项、作答为纯字母 → 无法判断对错 → 存疑跳过（不冤枉学生）
                continue
        # 正确答案为纯字母（如 'B'）时，从题干解析其内容再比较
        if nc and _re.fullmatch(r"[A-Da-d]", nc.strip()) and raw_c:
            cc = _answer_option_content(raw_c, m.get('question_text', ''))
            if cc != str(raw_c).strip():
                nc = _normalize_answer(cc)
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
