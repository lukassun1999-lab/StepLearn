#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM 分析：错题提取、错因因果链、画像趋势（自 skills_bridge.py 拆出）。"""

import json
import re
from typing import Any, Dict, List, Optional

from bridge_common import _get_client
from knowledge_base import (CAUSE_KEYS, CAUSE_LABELS, _filter_real_mistakes,
                            _is_unanswered, _normalize_error_cause,
                            _statistical_cause_profile, get_knowledge_framework,
                            normalize_knowledge_points)
from llm_prompts import CAUSE_CHAIN_PROMPT, MISTAKE_ANALYSIS_PROMPT


# ═══════════════════════════════════════════════════
# 长 OCR 分段分析
# ═══════════════════════════════════════════════════
# 实测 MiniMax-M3（关闭思维链）对 2 万字符级整卷 OCR 会返回空壳（0 错题），
# 而中小文本正常。试卷天然按题型分节（选择/阅读/完型/作文），按节切分后
# 每块调一次分析：阅读/完型"短文+题目"保持同一块不被切断；各块错题合并，
# 下游（报告/练习/方案）无感知。
_OCR_CHUNK_THRESHOLD = 12000  # 超过该长度按题型分节分析

# 节起始行：五、六、**七、完形填空** / **B. 补全对话** / A. 补全短文 / B卷
_SECTION_RE = re.compile(r'^\s*\*{0,2}[一二三四五六七八九十]+[、.．]\s*\S')
_SUB_SECTION_RE = re.compile(r'^\s*\*{0,2}[A-Z][.、）)]\s*[\u4e00-\u9fff]')
_VOLUME_RE = re.compile(r'^[AB]卷')
# 题号行：22. / **A 36.**（排除 3.3 这类小数：数字后不能再跟数字）
_QUESTION_RE = re.compile(r'^\s*\*{0,2}[A-Z]?\s*\d{1,3}[.、．](?!\d)')
# 作答行：22: xxx / 空格4: xxx
_ANSWER_RE = re.compile(r'^\s*(?:空格)?\d{1,3}\s*:')
_PAGE_MARK_RE = re.compile(r'^\s*-{2,}\s*第\s*\d+\s*页\s*-{2,}\s*$')


def chunk_ocr_by_section(ocr_text: str) -> List[str]:
    """按试卷题型分节切分 OCR 文本。

    - 节边界：中文序号节标题 / 字母子节（补全对话/补全短文等）/ B卷
      （无条件切分——过切无害，各块独立分析；欠切才是问题）
    - 无题号的纯段落（短文续页、学生作答块）并入前一块
    - 每块按其题号附上整卷中对应的作答行（学生作答常集中列在页尾，
      或与题目隔页；已在块内的作答行不重复附加）
    - 页面标记（--- 第 N 页 ---）剥离
    """
    lines = [l for l in (ocr_text or "").split("\n") if not _PAGE_MARK_RE.match(l)]
    if not lines:
        return []

    chunks: List[List[str]] = []
    for line in lines:
        is_boundary = bool(
            _SECTION_RE.match(line) or _SUB_SECTION_RE.match(line)
            or _VOLUME_RE.match(line))
        if is_boundary and chunks:
            chunks.append([line])
        else:
            if not chunks:
                chunks.append([])
            chunks[-1].append(line)

    # 合并无题号的块（短文续页/作答块）到前一块
    merged: List[List[str]] = []
    for c in chunks:
        if _has_questions(c) or not merged:
            merged.append(c)
        else:
            merged[-1].extend(c)
    chunks = merged

    # 每块附上对应题号的作答行（按整卷作答行全集匹配，保证配对）
    all_answers = [l for l in lines if _ANSWER_RE.match(l)]
    out = []
    for c in chunks:
        if not _has_questions(c):
            continue
        ctext = "\n".join(c)
        nums = {_question_num(m.group(0)) for l in c
                for m in _QUESTION_RE.finditer(l)}
        inline = {l.strip() for l in ctext.split("\n")}
        attached = [a for a in all_answers
                    if _question_num(a.split(":", 1)[0]) in nums
                    and a.strip() not in inline]
        text = ctext.strip()
        if attached:
            text += "\n\n【学生作答】\n" + "\n".join(attached)
        out.append(text)
    return out


def _question_num(token: str) -> str:
    """题号标记归一：'22.' / '22、' / '22:' / '空格4:' → '22'。"""
    return re.sub(r"[^0-9]", "", token)


def _has_questions(lines: List[str]) -> bool:
    return any(_QUESTION_RE.match(l) for l in lines)


def _merge_chunk_results(results: List[Dict]) -> Dict[str, Any]:
    """合并各分块的 mistakes 与 summary。"""
    mistakes: List[Dict] = []
    by_type: Dict[str, int] = {}
    weak_counter: Dict[str, int] = {}
    assessments = []
    for r in results:
        if not isinstance(r, dict):
            continue
        mistakes.extend(r.get("mistakes") or [])
        s = r.get("summary") or {}
        for qt, n in (s.get("by_type") or {}).items():
            by_type[qt] = by_type.get(qt, 0) + int(n or 0)
        for kp in (s.get("top_weak_points") or []):
            weak_counter[kp] = weak_counter.get(kp, 0) + 1
        if s.get("overall_assessment"):
            assessments.append(str(s["overall_assessment"]).strip())
    summary = {
        "total_mistakes": len(mistakes),
        "by_type": by_type,
        "top_weak_points": [k for k, _ in sorted(
            weak_counter.items(), key=lambda x: -x[1])][:5],
        "overall_assessment": "；".join(assessments)[:500],
    }
    return {"mistakes": mistakes, "summary": summary}


_ANALYZE_SCHEMA = {
    "mistakes": {"type": "array", "required": True},
    "summary": {"type": "object", "required": True},
}


def analyze_mistakes(ocr_text: str, task_id: int = None) -> Dict[str, Any]:
    """
    Run mistake analysis via LLM (english-mistake-analyzer STEP 2).
    Returns: {"mistakes": [...], "summary": {...}}
    长文本自动按题型分节多次调用后合并，避免整卷超长导致模型返回空壳。
    """
    from db import get_recent_correction_hints
    hints = get_recent_correction_hints([], content_type="mistake", limit=5)
    if len(ocr_text or "") > _OCR_CHUNK_THRESHOLD:
        result = _analyze_chunked(ocr_text, hints, task_id)
    else:
        prompt = MISTAKE_ANALYSIS_PROMPT.format(ocr_text=ocr_text)
        if hints:
            prompt = f"{prompt}\n\n{hints}"
        result = _get_client().call(
            prompt=prompt, schema=_ANALYZE_SCHEMA, task_id=task_id,
            call_type="analyze"
        )
    _postprocess_mistakes(result)
    return result


def _analyze_chunked(ocr_text: str, hints: str, task_id: int = None) -> Dict[str, Any]:
    """按题型分节逐块分析，合并结果。单块失败不阻断整卷（该块按 0 错题计）。"""
    chunks = chunk_ocr_by_section(ocr_text)
    if not chunks:
        # 分节失败（无题号/无节标题的异常格式）→ 回退整卷单次调用
        prompt = MISTAKE_ANALYSIS_PROMPT.format(ocr_text=ocr_text)
        if hints:
            prompt = f"{prompt}\n\n{hints}"
        return _get_client().call(
            prompt=prompt, schema=_ANALYZE_SCHEMA, task_id=task_id,
            call_type="analyze")

    results = []
    for i, chunk in enumerate(chunks):
        try:
            prompt = MISTAKE_ANALYSIS_PROMPT.format(ocr_text=chunk)
            if hints:
                prompt = f"{prompt}\n\n{hints}"
            results.append(_get_client().call(
                prompt=prompt, schema=_ANALYZE_SCHEMA, task_id=task_id,
                call_type="analyze"))
        except Exception:
            # 单块失败：跳过该块继续，保证整卷不因一块异常而失败
            continue
    if not results:
        return {"mistakes": [], "summary": {}}
    return _merge_chunk_results(results)


def _postprocess_mistakes(result: Dict) -> None:
    """兜底：剔除"答对却被当成错题"的条目，并归一化答案/错因/知识点。

    与 summary 统计同步，保证与过滤后的 mistakes 一致。
    """
    if not isinstance(result, dict) or not isinstance(result.get('mistakes'), list):
        return
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

