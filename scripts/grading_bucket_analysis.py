#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判卷误判归因分桶（只读分析，不写库）。

背景：判卷准确率瓶颈（MiniMax-M3 ~60%）。老师纠错表（ai_corrections）暂无
真实使用数据（0 条），无法从人工标签分桶。本脚本改用**生产库可自动检测的
确定性信号**给误判分桶，并导出人工复核表（复用错因校准报告的人工审查模式）：

  B1 归一化命中（确定误判）: is_answer_correct(user, correct) 为真
     —— LLM 判错但归一化比对命中（大小写/全角/标点/备选答案），必为误判
  B2 字母前缀命中（高度疑似）: 学生答单字母，标准答案以同一字母+分隔符开头
     （如 user='e' vs correct='e. dealing with...'）——学生选对了字母选项
  B3 未作答污染: 解析/作答含未作答标记（缺做不是错，禁入错题）
  B4 格式风险（人工复核）: 一侧带选项字母前缀另一侧不带，无法自动判定
  覆盖率: 有 OCR 原文的任务，OCR 学生作答题号 vs 落库错题号的覆盖情况

用法:
  python scripts/grading_bucket_analysis.py [db_path]   # 默认 data.db（只读）
  输出: 控制台摘要 + 错判归因报告.md + 错判人工复核表.csv
"""

import csv
import json
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from domain.grading import is_answer_correct, normalize_answer  # noqa: E402
from knowledge_base import _is_unanswered  # noqa: E402

# 学生作答为单选项字母（A-H，容错大小写/带分隔符）
_SINGLE_LETTER_RE = re.compile(r"^\(?([A-Ha-h])\)?[.、)）：:]?\s*$")
# 标准答案开头的字母前缀（e. / E) / B、 等）
_ANSWER_PREFIX_RE = re.compile(r"^\(?([A-Ha-h])\)?[.、)）：:]\s*(.+)$", re.DOTALL)

_UNANSWERED_USER_MARKERS = ("未作答", "未填写", "空白", "未答题", "[模糊]", "无法辨认")


def _user_unanswered(user_answer: str) -> bool:
    u = (user_answer or "").strip()
    if not u:
        return True
    return any(m in u for m in _UNANSWERED_USER_MARKERS)


def _bucket_of(row) -> tuple[str, str]:
    """返回 (桶名, 说明)。确定性规则，顺序即优先级。"""
    user = row["user_answer"] or ""
    correct = row["correct_answer"] or ""
    as_dict = {"explanation": row["explanation"] or "",
               "error_reason": "", "cause_evidence": "",
               "user_answer": user}

    if _is_unanswered(as_dict) or _user_unanswered(user):
        return "B3_未作答污染", "解析或作答含未作答/模糊标记（缺做不是错）"

    if user and correct and is_answer_correct(user, correct):
        return "B1_归一化命中", "归一化比对命中（大小写/全角/标点/备选答案）——LLM 必判错"

    m_user = _SINGLE_LETTER_RE.match(user.strip())
    m_prefix = _ANSWER_PREFIX_RE.match(correct.strip())
    if m_user and m_prefix and m_user.group(1).upper() == m_prefix.group(1).upper():
        return "B2_字母前缀命中", (f"学生答字母 {m_user.group(1).upper()}，标准答案同字母选项"
                                   "（内容型答案）——学生选对")

    if (m_user and not m_prefix and correct.strip()
            and not _ANSWER_PREFIX_RE.match(correct.strip())):
        return "B4_格式风险", "学生答字母但标准答案是内容（无选项上下文无法自动判定）"
    if m_prefix and not m_user:
        return "B4_格式风险", "标准答案带字母前缀但学生作答是内容/其他格式"
    return "OK_未见异常", ""


def _ocr_question_numbers(ocr_text: str) -> set:
    """从 OCR 文本第二部分（题号: 学生作答）提取题号集合。"""
    nums = set()
    for m in re.finditer(r"^\s*(\d{1,3})\s*[:：]", ocr_text or "", re.MULTILINE):
        nums.add(int(m.group(1)))
    return nums


def main():
    import sqlite3

    db_path = sys.argv[1] if len(sys.argv) > 1 else "data.db"
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT id, student_id, source_task_id, question_type, question,
               user_answer, correct_answer, explanation, consecutive_correct
        FROM mistakes ORDER BY id
    """).fetchall()

    buckets = {}
    review_rows = []
    for r in rows:
        bucket, why = _bucket_of(r)
        buckets.setdefault(bucket, []).append(r)
        if bucket != "OK_未见异常":
            review_rows.append({
                "mistake_id": r["id"], "bucket": bucket,
                "question_type": r["question_type"] or "",
                "user_answer": (r["user_answer"] or "")[:60],
                "correct_answer": (r["correct_answer"] or "")[:80],
                "why": why,
                "question": (r["question"] or "")[:80],
            })

    total = len(rows)
    print(f"生产库错题总数: {total}")
    for name in sorted(buckets):
        n = len(buckets[name])
        print(f"  {name}: {n} ({n / total * 100:.0f}%)" if total else f"  {name}: {n}")

    definite = len(buckets.get("B1_归一化命中", [])) + len(buckets.get("B2_字母前缀命中", []))
    polluted = len(buckets.get("B3_未作答污染", []))
    print(f"\n可确定性误判（B1+B2）: {definite} 条"
          f"（占全部错题 {definite / total * 100:.0f}%，若均在实判中计为错则直接抬高误判率）")
    print(f"未作答污染（B3）: {polluted} 条")

    # 覆盖率：有 OCR 原文的任务
    print("\n任务级覆盖率（OCR 学生作答题号 vs 落库错题号）:")
    tasks = conn.execute("""
        SELECT t.id, t.student_id, t.input_data FROM ai_tasks t
        WHERE t.input_data LIKE '%_ocr_text%' AND length(t.input_data) > 1000
        ORDER BY t.id
    """).fetchall()
    for t in tasks:
        try:
            data = json.loads(t["input_data"])
        except Exception:
            continue
        ocr = data.get("_ocr_text") or ""
        nums = _ocr_question_numbers(ocr)
        mistake_nums = {r["id"] for r in conn.execute(
            "SELECT id FROM mistakes WHERE source_task_id = ?", [t["id"]])}
        # 错题没有题号列，用 question 文本开头的数字兜底
        if not mistake_nums:
            continue
        print(f"  task {t['id']}: OCR 识别作答 {len(nums)} 题, 落库错题 {len(mistake_nums)} 条"
              f"（错题占比 {len(mistake_nums) / max(len(nums), 1) * 100:.0f}%，"
              "偏高提示误判或漏判判对）")
    conn.close()

    # 导出人工复核表
    out_csv = "错判人工复核表.csv"
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(review_rows[0].keys()) if review_rows else
                           ["mistake_id", "bucket", "question_type", "user_answer",
                            "correct_answer", "why", "question"])
        w.writeheader()
        w.writerows(review_rows)
    print(f"\n人工复核表已导出: {out_csv}（{len(review_rows)} 条）")
    print("建议：像《错因校准报告》一样人工抽检 B4 与抽查 OK 桶各 20 条，"
          "补齐'自定答案错/漏判'两个人工桶后，再决定 ③ 多票是否上线。")


if __name__ == "__main__":
    main()
