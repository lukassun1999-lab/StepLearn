#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""存量误判错题清洗（对照《错判归因报告》分桶）。

背景：08-28 批改修复提交之前的存量错题中，有一批违反现行产品规则的记录
仍在错题本/错因画像/周报里发酵（实测 180 条中 69 条问题、52 条可确定性清除）：
  B1 归一化命中 / B2 字母前缀命中 —— 学生其实答对，不该是错题
  B3 未作答污染 —— 缺做不是错（prompt 规则 7 / 提交 67a0d82 的既定产品规则）
B4 格式风险**不在自动清洗范围**（无法自动判定，走人工复核 CSV）。

默认 DRY RUN：只报告与导出备份，不写库。
确认无误后执行: python scripts/cleanup_legacy_misjudged.py --apply

删除前自动导出全量备份 CSV（可回查）；同时清理这些错题的 practice_records。
"""

import csv
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.grading_bucket_analysis import _bucket_of  # noqa: E402

_APPLY = "--apply" in sys.argv
DB_PATH = "data.db"


def main():
    import sqlite3
    from datetime import datetime

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, student_id, source_task_id, question_type, question,
               user_answer, correct_answer, explanation, consecutive_correct
        FROM mistakes ORDER BY id
    """).fetchall()

    to_delete = []
    for r in rows:
        bucket, _why = _bucket_of(r)
        if bucket in ("B1_归一化命中", "B2_字母前缀命中", "B3_未作答污染"):
            to_delete.append((r, bucket))

    mode = "APPLY（将删除）" if _APPLY else "DRY RUN（只报告不删除）"
    print(f"存量错题 {len(rows)} 条，确定性可清洗 {len(to_delete)} 条 —— 模式: {mode}")
    for r, bucket in to_delete:
        preview = (r["question"] or "")[:40].replace("\n", " ")
        print(f"  [{bucket}] mistake {r['id']} student={r['student_id']} "
              f"type={r['question_type']} | {preview}")

    if not to_delete:
        print("无可清洗条目。")
        conn.close()
        return

    # 删除前备份（dry-run 也导出，供人工核对）
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_csv = f"备份_误判错题_{stamp}.csv"
    fields = ["id", "student_id", "source_task_id", "question_type", "question",
              "user_answer", "correct_answer", "explanation", "error_cause",
              "cause_evidence", "knowledge_points", "difficulty", "mastery_level",
              "review_count", "consecutive_correct", "created_at", "_bucket"]
    with open(backup_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(fields)
        for r, bucket in to_delete:
            full = conn.execute("SELECT * FROM mistakes WHERE id = ?",
                                [r["id"]]).fetchone()
            w.writerow([full[k] for k in fields[:-1]] + [bucket])
    print(f"\n备份已导出: {backup_csv}")

    if not _APPLY:
        print("\nDRY RUN 结束。确认以上清单无误后执行:")
        print("  python scripts/cleanup_legacy_misjudged.py --apply")
        conn.close()
        return

    ids = [r["id"] for r, _ in to_delete]
    ph = ",".join("?" for _ in ids)
    cur = conn.execute(f"DELETE FROM practice_records WHERE mistake_id IN ({ph})", ids)
    print(f"已删除关联练习记录 {cur.rowcount} 条")
    cur = conn.execute(f"DELETE FROM mistakes WHERE id IN ({ph})", ids)
    print(f"已删除误判错题 {cur.rowcount} 条")
    conn.commit()
    conn.close()
    print("完成。周报/错因画像/错题本将从下次任务开始基于干净数据统计。")


if __name__ == "__main__":
    main()
