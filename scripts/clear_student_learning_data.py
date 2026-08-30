#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""清空指定学生的错题本与周报（重新上传试卷前归零，如 simon 重新分析）。

范围（"错题本 + 周报"及其直接衍生）：
  - mistakes 错题 + practice_records 练习记录 + questions 关联练习题
  - cause_profiles / cause_profile_history 错因画像
  - weekly_pdf 周报文件 + 周错题本文件（files 表 + 磁盘）
  - weekly_records 周期记录（重传需开新周期；ai_tasks.cycle_id 引用先置空，
    任务历史保留）

不在范围（保留）：learning_plans 学习方案、诊断/练习卷 PDF、ai_tasks 历史、
check_ins / metacognitive_reviews / score_history / achievements。

默认 DRY RUN；确认后执行: python scripts/clear_student_learning_data.py --student 1 --apply
"""

import csv
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.shared import UPLOAD_DIR  # noqa: E402

_APPLY = "--apply" in sys.argv


def _resolve_student(conn):
    if "--student" not in sys.argv:
        print("用法: python scripts/clear_student_learning_data.py --student <id或名> [--apply]")
        sys.exit(1)
    key = sys.argv[sys.argv.index("--student") + 1]
    row = conn.execute(
        "SELECT id, name FROM students WHERE id = ? OR name = ?",
        [int(key) if key.isdigit() else -1, key]).fetchone()
    if not row:
        print(f"错误: 未找到学生 '{key}'")
        sys.exit(1)
    return row["id"], row["name"]


def main():
    import sqlite3
    from datetime import datetime

    conn = sqlite3.connect(DB_PATH := "data.db")
    conn.row_factory = sqlite3.Row
    sid, name = _resolve_student(conn)

    scope = {
        "mistakes(错题)": f"SELECT COUNT(*) FROM mistakes WHERE student_id={sid}",
        "practice_records(练习记录)": (
            f"SELECT COUNT(*) FROM practice_records pr JOIN mistakes m "
            f"ON m.id=pr.mistake_id WHERE m.student_id={sid}"),
        "questions(关联练习题)": (
            f"SELECT COUNT(*) FROM questions q JOIN mistakes m "
            f"ON m.id=q.source_mistake_id WHERE m.student_id={sid}"),
        "cause_profiles(错因画像)": f"SELECT COUNT(*) FROM cause_profiles WHERE student_id={sid}",
        "cause_profile_history(画像历史)": f"SELECT COUNT(*) FROM cause_profile_history WHERE student_id={sid}",
        "weekly_records(周期记录)": f"SELECT COUNT(*) FROM weekly_records WHERE student_id={sid}",
        "files(周报+周错题本)": (
            f"SELECT COUNT(*) FROM files WHERE student_id={sid} AND "
            f"(file_type='weekly_pdf' OR original_filename LIKE '周错题本-%')"),
    }
    print(f"学生 {name} (id={sid}) 清除范围 —— 模式: "
          f"{'APPLY（将删除）' if _APPLY else 'DRY RUN（只统计不删除）'}")
    for label, sql in scope.items():
        print(f"  {label}: {conn.execute(sql).fetchone()[0]}")

    file_rows = conn.execute(
        f"SELECT id, file_type, filename, original_filename FROM files "
        f"WHERE student_id={sid} AND (file_type='weekly_pdf' "
        f"OR original_filename LIKE '周错题本-%')").fetchall()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_csv = f"备份_学生{name}学习数据_{stamp}.csv"
    with open(backup_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        for label, sql, prefix in [
            ("mistakes", f"SELECT * FROM mistakes WHERE student_id={sid}", "mistake"),
            ("weekly_records", f"SELECT * FROM weekly_records WHERE student_id={sid}", "cycle"),
            ("files", f"SELECT * FROM files WHERE student_id={sid} AND "
                      f"(file_type='weekly_pdf' OR original_filename LIKE '周错题本-%')", "file"),
        ]:
            rows = conn.execute(sql).fetchall()
            if rows:
                w.writerow([f"== {label} =="] + list(rows[0].keys()))
                for r in rows:
                    w.writerow([prefix] + [r[k] for k in r.keys()])
                w.writerow([])
    print(f"备份已导出: {backup_csv}")

    if not _APPLY:
        print("\nDRY RUN 结束。确认后执行: "
              f"python scripts/clear_student_learning_data.py --student {sid} --apply")
        conn.close()
        return

    # 磁盘：周报 + 周错题本文件
    deleted_files = 0
    for f in file_rows:
        for d in (f["file_type"], f["file_type"] + "s"):
            p = os.path.join(UPLOAD_DIR, str(sid), d, f["filename"])
            if os.path.exists(p):
                os.remove(p)
                deleted_files += 1
                break

    cur = conn.execute(
        "DELETE FROM practice_records WHERE mistake_id IN "
        "(SELECT id FROM mistakes WHERE student_id=?)", [sid])
    n_pr = cur.rowcount
    cur = conn.execute(
        "DELETE FROM questions WHERE source_mistake_id IN "
        "(SELECT id FROM mistakes WHERE student_id=?)", [sid])
    n_q = cur.rowcount
    n_m = conn.execute("DELETE FROM mistakes WHERE student_id=?", [sid]).rowcount
    n_cp = conn.execute("DELETE FROM cause_profiles WHERE student_id=?", [sid]).rowcount
    n_ch = conn.execute("DELETE FROM cause_profile_history WHERE student_id=?", [sid]).rowcount
    # 周期记录被 ai_tasks.cycle_id 引用：先置空保留任务历史
    n_null = conn.execute(
        "UPDATE ai_tasks SET cycle_id=NULL WHERE student_id=?", [sid]).rowcount
    n_wr = conn.execute("DELETE FROM weekly_records WHERE student_id=?", [sid]).rowcount
    n_f = conn.execute(
        "DELETE FROM files WHERE student_id=? AND (file_type='weekly_pdf' "
        "OR original_filename LIKE '周错题本-%')", [sid]).rowcount
    conn.commit()
    conn.close()
    print(f"\n已删除: 错题 {n_m}, 练习记录 {n_pr}, 关联练习题 {n_q}, "
          f"错因画像 {n_cp}/{n_ch}, 周期记录 {n_wr}（任务历史 {n_null} 条已解绑保留）, "
          f"周报/周错题本文件 {deleted_files} 个（DB {n_f} 条）")
    print("保留: 学习方案、诊断/练习卷 PDF、任务历史、打卡/复盘/成绩。")


if __name__ == "__main__":
    main()
