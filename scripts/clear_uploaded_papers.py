#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""清除历史上传的学生试卷与答题卡（AI 生成的报告/练习/周报/海报不受影响）。

范围（"上传的学生试卷" = 学生拍照上传的原始作答材料）：
  - files 表 file_type IN ('test_paper', 'answer_sheet') 的记录
  - uploads/<student_id>/test_paper/ 与 answer_sheet/ 目录下的全部磁盘文件
    （含失败任务遗留的无 DB 记录孤儿文件）

不在范围：report_pdf / exercise_pdf / weekly_pdf / poster（AI 产出，保留）；
错题/任务/周期等派生数据（用户未要求清除，保留）。

注意：清除后家长端无法再回看/下载原始试卷照片；2 个引用试卷文件的失败任务
（209、212）如需重跑需家长重新上传。

默认 DRY RUN：只统计与导出清单，不删任何东西。
确认后执行: python scripts/clear_uploaded_papers.py --apply
"""

import csv
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.shared import UPLOAD_DIR  # noqa: E402

_FILE_TYPES = ("test_paper", "answer_sheet")
_APPLY = "--apply" in sys.argv
DB_PATH = "data.db"


def main():
    import sqlite3
    from datetime import datetime

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"SELECT * FROM files WHERE file_type IN ({','.join('?' * len(_FILE_TYPES))}) "
        "ORDER BY student_id, id", list(_FILE_TYPES)).fetchall()

    # 磁盘扫描（含无 DB 记录的孤儿文件）
    disk_files = []
    if os.path.isdir(UPLOAD_DIR):
        for sid in sorted(os.listdir(UPLOAD_DIR)):
            for ftype in _FILE_TYPES:
                d = os.path.join(UPLOAD_DIR, sid, ftype)
                if not os.path.isdir(d):
                    continue
                for name in sorted(os.listdir(d)):
                    p = os.path.join(d, name)
                    if os.path.isfile(p):
                        disk_files.append((int(sid), ftype, p, os.path.getsize(p)))

    db_paths = set()
    manifest_rows = []
    total_bytes = 0
    for f in rows:
        path = None
        for d in (f["file_type"], f["file_type"] + "s"):
            p = os.path.join(UPLOAD_DIR, str(f["student_id"]), d, f["filename"])
            if os.path.exists(p):
                path = p
                break
        if path:
            db_paths.add(os.path.normcase(os.path.abspath(path)))
            size = os.path.getsize(path)
        else:
            size = f["file_size"] or 0  # 文件已不在磁盘（仅删记录）
        total_bytes += size
        manifest_rows.append({
            "source": "db", "file_id": f["id"], "student_id": f["student_id"],
            "file_type": f["file_type"], "path": path or "(磁盘上已不存在)",
            "original_filename": f["original_filename"], "size_bytes": size,
            "created_at": f["created_at"],
        })
    disk_only = 0
    for sid, ftype, p, size in disk_files:
        if os.path.normcase(os.path.abspath(p)) in db_paths:
            continue
        disk_only += 1
        total_bytes += size
        manifest_rows.append({
            "source": "disk_orphan", "file_id": "", "student_id": sid,
            "file_type": ftype, "path": p, "original_filename": os.path.basename(p),
            "size_bytes": size, "created_at": "",
        })

    mode = "APPLY（将删除）" if _APPLY else "DRY RUN（只统计不删除）"
    print(f"上传试卷/答题卡: DB 记录 {len(rows)} 条, 磁盘文件 {len(disk_files)} 个"
          f"（其中无记录孤儿 {disk_only} 个）, 共 {total_bytes / 1048576:.1f} MB —— 模式: {mode}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest_csv = f"备份_已清除试卷清单_{stamp}.csv"
    with open(manifest_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(manifest_rows[0].keys()))
        w.writeheader()
        w.writerows(manifest_rows)
    print(f"删除清单已导出: {manifest_csv}")

    if not _APPLY:
        print("\nDRY RUN 结束。确认后执行: python scripts/clear_uploaded_papers.py --apply")
        conn.close()
        return

    deleted_files = 0
    for sid, ftype, p, _size in disk_files:
        try:
            os.remove(p)
            deleted_files += 1
        except FileNotFoundError:
            pass
    # 清空后的空目录一并移除
    for sid, ftype, _p, _s in disk_files:
        d = os.path.join(UPLOAD_DIR, str(sid), ftype)
        try:
            os.rmdir(d)
        except OSError:
            pass
    cur = conn.execute(
        f"DELETE FROM files WHERE file_type IN ({','.join('?' * len(_FILE_TYPES))})",
        list(_FILE_TYPES))
    removed_rows = cur.rowcount
    conn.commit()
    conn.close()
    print(f"\n已删除磁盘文件 {deleted_files} 个, DB 记录 {removed_rows} 条")
    print("保留: AI 生成的报告/练习/周报/海报与全部错题、任务数据。")


if __name__ == "__main__":
    main()
