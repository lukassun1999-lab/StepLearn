#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM 分析：错题提取、错因因果链、画像趋势（自 skills_bridge.py 拆出）。"""

import json
from typing import Any, Dict, List, Optional

from bridge_common import _get_client
from knowledge_base import (CAUSE_KEYS, CAUSE_LABELS, _filter_real_mistakes,
                            _is_unanswered, _normalize_error_cause,
                            _statistical_cause_profile, get_knowledge_framework,
                            normalize_knowledge_points)
from llm_prompts import CAUSE_CHAIN_PROMPT, MISTAKE_ANALYSIS_PROMPT



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

