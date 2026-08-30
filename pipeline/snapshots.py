#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立子链与快照任务：练习批改 / 周错题本（周一自动）/ 月度总结（每月 1 日自动）。

这些任务不在分析主链上，但都挂在 Cycle 上（核心链路架构设计.md §4.2）。
自 weekly_pipeline.py 移植，行为保持一致。
"""

import json
import logging
import os
import uuid
from datetime import date, timedelta

import db
from skills_bridge import (grade_answers, generate_monthly_analysis,
                           update_student_memory)
from report_templates import (
    render_feedback_report, render_weekly_mistake_book, render_monthly_report,
)
from pipeline import stages

log = logging.getLogger(__name__)


def _resolve_input(task: dict) -> dict:
    input_data = task.get("input_data") or {}
    if isinstance(input_data, str):
        try:
            input_data = json.loads(input_data)
        except Exception:
            input_data = {}
    return input_data


# ═══════════════════════════════════════════════════
# 练习批改：答案照片 → AI 批改 → 掌握度更新 → 反馈报告
# ═══════════════════════════════════════════════════

def run_grade_exercises(task: dict, db_path: str) -> dict:
    task_id = task["id"]
    student_id = task["student_id"]
    input_data = _resolve_input(task)
    file_ids = input_data.get("file_ids") or (
        [input_data["file_id"]] if input_data.get("file_id") else [])
    week_start = task.get("week_start") or db.get_week_start()

    def progress(step, pct):
        db.update_task_progress(task_id, step, pct, db_path)

    student = db.get_student(student_id, db_path)
    if not student:
        raise ValueError(f"Student {student_id} not found")
    if not file_ids:
        raise ValueError("No file_ids for exercise grading")

    # STEP 1: OCR student answer sheet
    progress("OCR识别答案", 15)
    ocr_text, _conf = stages.ocr_to_text(file_ids, student_id, task_id, db_path)
    if not ocr_text or not ocr_text.strip():
        raise ValueError("OCR未能识别学生答案，请检查图片质量")

    # STEP 2: Load recent exercise questions for this student
    # P3-14：取题逻辑收拢至 domain/questions.py。
    # unmastered_only=False：批改覆盖已发练习卷全集（含在线已练对的题）。
    progress("加载练习题", 30)
    from domain import questions as q_mod
    question_rows = q_mod.get_practice_questions(
        student_id, limit=20, with_fallback=True, unmastered_only=False,
        db_path=db_path)

    questions_for_grading = []
    for q in question_rows:
        questions_for_grading.append({
            "question_text": q["question_text"],
            "question_type": q["question_type"],
            "correct_answer": q["correct_answer"],
            "explanation": q["explanation"],
            "knowledge_points": q["knowledge_points"],
            "difficulty": q["difficulty"],
            "source_mistake_id": q["source_mistake_id"],
        })

    if not questions_for_grading:
        raise ValueError("未找到该学生的练习题记录，请先运行「矩阵分析」生成练习题")

    # STEP 3: AI grading
    progress("AI批改练习题", 55)
    student_answers = [{"raw_text": ocr_text}]
    grading_result = grade_answers(
        questions_for_grading, student_answers, task_id=task_id)
    results = grading_result.get("results", [])
    summary = grading_result.get("summary", {})

    # STEP 4: Update mastery via record_practice
    progress("更新掌握度", 75)
    for r in results:
        q_idx = r.get("question_index", -1)
        if 0 <= q_idx < len(questions_for_grading):
            source_mistake_id = questions_for_grading[q_idx].get("source_mistake_id")
            if source_mistake_id:
                db.record_practice(
                    mistake_id=source_mistake_id,
                    user_answer=r.get("student_answer", ""),
                    is_correct=bool(r.get("is_correct", False)),
                    feedback=r.get("explanation", ""),
                    db_path=db_path,
                )

    # STEP 5: Generate feedback report
    progress("生成批改反馈", 88)
    fb_html = render_feedback_report(
        student_name=student["name"],
        results=results,
        summary=summary,
        week_start=week_start,
    )
    fb_dir = os.path.join(stages.UPLOAD_DIR, str(student_id), "report_pdf")
    os.makedirs(fb_dir, exist_ok=True)
    fb_filename = f"feedback_{week_start}_{uuid.uuid4().hex[:8]}.html"
    fb_path = os.path.join(fb_dir, fb_filename)
    with open(fb_path, "w", encoding="utf-8") as f:
        f.write(fb_html)
    feedback_file_id = db.add_file(
        student_id=student_id, uploader_role="teacher",
        file_type="report_pdf", filename=fb_filename,
        original_filename=f"练习批改反馈-{student['name']}-{week_start}.html",
        week_start=week_start, file_size=os.path.getsize(fb_path),
        mime_type="text/html", db_path=db_path,
    )

    db.update_weekly_record(student_id, week_start, kind="weekly",
                            exercises_completed=1, exercises_graded=1,
                            db_path=db_path)

    accuracy = summary.get("accuracy")
    if accuracy is not None:
        db.record_score(student_id, score=accuracy * 100,
                        score_type="practice", source_task_id=task_id,
                        week_start=week_start, db_path=db_path)

    progress("完成", 100)
    return {
        "needs_review": False,
        "student_id": student_id,
        "feedback_file_id": feedback_file_id,
        "correct_count": summary.get("correct", 0),
        "total_count": summary.get("total", 0),
        "accuracy": summary.get("accuracy", 0),
        "stage": "exercise_graded",
    }


# ═══════════════════════════════════════════════════
# 周错题本快照（每周一自动，针对上一周）
# ═══════════════════════════════════════════════════

def run_weekly_mistake_book(task: dict, db_path: str) -> dict:
    task_id = task["id"]
    student_id = task["student_id"]
    week_start = task.get("week_start") or db.get_week_start()

    def progress(step, pct):
        db.update_task_progress(task_id, step, pct, db_path)

    student = db.get_student(student_id, db_path)
    if not student:
        raise ValueError(f"Student {student_id} not found")

    # week_start here = the Monday that triggered the task; we want LAST week's data
    ws_date = date.fromisoformat(week_start)
    prev_week_end = (ws_date - timedelta(days=1)).isoformat()
    prev_week_start = (ws_date - timedelta(days=7)).isoformat()

    conn = db.get_connection(db_path)
    mistake_rows = conn.execute("""
        SELECT question, question_type, correct_answer, user_answer,
               explanation, knowledge_points, difficulty, consecutive_correct
        FROM mistakes WHERE student_id = ?
          AND date(created_at, 'localtime') BETWEEN ? AND ?
        ORDER BY created_at
    """, [student_id, prev_week_start, prev_week_end]).fetchall()
    mastered_cnt = conn.execute("""
        SELECT COUNT(*) FROM mistakes WHERE student_id = ?
          AND consecutive_correct >= 2
          AND date(last_reviewed_at) BETWEEN ? AND ?
    """, [student_id, prev_week_start, prev_week_end]).fetchone()[0]
    conn.close()

    mistakes = []
    for m in mistake_rows:
        kp = m["knowledge_points"]
        if isinstance(kp, str):
            try:
                kp = json.loads(kp)
            except Exception:
                kp = []
        mistakes.append({
            "question_text": m["question"] or "",
            "question_type": m["question_type"] or "",
            "correct_answer": m["correct_answer"] or "",
            "user_answer": m["user_answer"] or "",
            "explanation": m["explanation"] or "",
            "knowledge_points": kp if isinstance(kp, list) else [kp],
            "difficulty": m["difficulty"] or 2,
        })

    progress("生成周错题本", 70)
    wb_html = render_weekly_mistake_book(
        student=student, mistakes=mistakes,
        week_start=prev_week_start, week_end=prev_week_end,
        mastered_count=mastered_cnt,
    )
    wb_dir = os.path.join(stages.UPLOAD_DIR, str(student_id), "report_pdf")
    os.makedirs(wb_dir, exist_ok=True)
    wb_filename = f"weekly_book_{prev_week_start}_{uuid.uuid4().hex[:8]}.html"
    wb_path = os.path.join(wb_dir, wb_filename)
    with open(wb_path, "w", encoding="utf-8") as f:
        f.write(wb_html)
    weekly_book_file_id = db.add_file(
        student_id=student_id, uploader_role="teacher",
        file_type="report_pdf", filename=wb_filename,
        original_filename=f"周错题本-{student['name']}-{prev_week_start}.html",
        week_start=prev_week_start, file_size=os.path.getsize(wb_path),
        mime_type="text/html", db_path=db_path,
    )

    progress("完成", 100)
    return {
        "needs_review": False,
        "student_id": student_id,
        "report_file_id": weekly_book_file_id,
        "mistakes_count": len(mistakes),
        "mastered_count": mastered_cnt,
        "stage": "weekly_book_done",
    }


# ═══════════════════════════════════════════════════
# 月度总结（每月 1 日自动，针对上个月）
# ═══════════════════════════════════════════════════

def _refresh_student_memory(student: dict, month_label: str, month_stats: dict,
                            kp_breakdown: str, score_history_str: str,
                            db_path: str, task_id: int = None) -> None:
    """把本月学情合并进 L3 长期记忆（memory_summary 为空则保留旧记忆）。"""
    student_id = student["id"]
    old_memory = db.get_student_memory(student_id, db_path=db_path)
    try:
        cause = db.get_cause_profile(student_id, db_path=db_path) or {}
    except Exception:
        cause = {}
    accuracy = month_stats.get("avg_accuracy")
    facts = "\n".join([
        f"- 本月错题 {month_stats.get('total_mistakes', 0)} 道，"
        f"累计攻克 {month_stats.get('mastered_count', 0)} 道，"
        f"练习 {month_stats.get('practice_count', 0)} 次，"
        f"平均正确率 {round(accuracy * 100)}%" if accuracy is not None else
        f"- 本月错题 {month_stats.get('total_mistakes', 0)} 道，"
        f"累计攻克 {month_stats.get('mastered_count', 0)} 道，"
        f"练习 {month_stats.get('practice_count', 0)} 次，无练习正确率数据",
        f"知识点错题分布:\n{kp_breakdown or '无'}",
        "最近错因画像: " + json.dumps(cause, ensure_ascii=False)[:600],
        f"分数变化:\n{score_history_str}",
    ])
    merged = update_student_memory(
        student_info={"name": student["name"], "grade": student["grade"]},
        month_label=month_label,
        old_memory=old_memory,
        month_facts=facts,
        task_id=task_id,
    )
    if not (merged or {}).get("memory_summary"):
        log.warning("长期记忆生成结果为空，保留旧记忆 student=%s", student_id)
        return
    db.save_student_memory(student_id, {
        "memory_summary": merged["memory_summary"],
        "learner_type": merged.get("learner_type", ""),
        "recurring_causes": merged.get("recurring_causes") or [],
        "effective_methods": merged.get("effective_methods") or [],
        "source_month": month_label,
    }, db_path=db_path)


def run_monthly_summary(task: dict, db_path: str) -> dict:
    task_id = task["id"]
    student_id = task["student_id"]
    week_start = task.get("week_start") or db.get_week_start()

    def progress(step, pct):
        db.update_task_progress(task_id, step, pct, db_path)

    student = db.get_student(student_id, db_path)
    if not student:
        raise ValueError(f"Student {student_id} not found")

    progress("加载上月数据", 15)
    ws_date = date.fromisoformat(week_start)
    first_of_month = date(ws_date.year, ws_date.month, 1)
    last_of_prev = first_of_month - timedelta(days=1)
    month_start = date(last_of_prev.year, last_of_prev.month, 1)
    month_end = last_of_prev
    month_label = f"{month_start.year}年{month_start.month}月"

    conn = db.get_connection(db_path)
    mistake_rows = conn.execute("""
        SELECT question, question_type, correct_answer, user_answer,
               explanation, knowledge_points, difficulty, consecutive_correct
        FROM mistakes WHERE student_id = ?
          AND date(created_at, 'localtime') BETWEEN ? AND ?
        ORDER BY created_at
    """, [student_id, month_start.isoformat(), month_end.isoformat()]).fetchall()

    mastered_cnt = conn.execute("""
        SELECT COUNT(*) FROM mistakes WHERE student_id = ?
          AND consecutive_correct >= 2
    """, [student_id]).fetchone()[0]

    practice_cnt = conn.execute("""
        SELECT COUNT(*) FROM practice_records pr
        JOIN mistakes m ON m.id = pr.mistake_id
        WHERE m.student_id = ?
          AND date(pr.created_at, 'localtime') BETWEEN ? AND ?
    """, [student_id, month_start.isoformat(), month_end.isoformat()]).fetchone()[0]

    avg_row = conn.execute("""
        SELECT AVG(CASE WHEN pr.is_correct THEN 100.0 ELSE 0.0 END) as avg_acc
        FROM practice_records pr
        JOIN mistakes m ON m.id = pr.mistake_id
        WHERE m.student_id = ?
          AND date(pr.created_at, 'localtime') BETWEEN ? AND ?
    """, [student_id, month_start.isoformat(), month_end.isoformat()]).fetchone()

    score_rows = conn.execute("""
        SELECT score, score_type, created_at FROM score_history
        WHERE student_id = ? AND date(created_at, 'localtime') BETWEEN ? AND ?
        ORDER BY created_at
    """, [student_id, month_start.isoformat(), month_end.isoformat()]).fetchall()
    conn.close()

    mistakes = []
    kp_stats = {}
    for m in mistake_rows:
        kp = m["knowledge_points"]
        if isinstance(kp, str):
            try:
                kp = json.loads(kp)
            except Exception:
                kp = []
        mistakes.append({
            "question_text": m["question"] or "",
            "question_type": m["question_type"] or "",
            "correct_answer": m["correct_answer"] or "",
            "user_answer": m["user_answer"] or "",
            "explanation": m["explanation"] or "",
            "knowledge_points": kp if isinstance(kp, list) else [kp],
            "difficulty": m["difficulty"] or 2,
        })
        for k in (kp or ["其他"]):
            kp_stats[k] = kp_stats.get(k, 0) + 1

    kp_breakdown = "\n".join(
        f"- {k}: {v} 道" for k, v in
        sorted(kp_stats.items(), key=lambda x: -x[1])[:10])
    score_history_str = "\n".join(
        f"- {r['created_at'][:10]} {r['score_type']}: {r['score']}分"
        for r in score_rows) or "本月无分数记录"

    month_stats = {
        "total_mistakes": len(mistakes),
        "mastered_count": mastered_cnt,
        "practice_count": practice_cnt,
        "avg_accuracy": avg_row["avg_acc"] / 100 if avg_row and avg_row["avg_acc"] else None,
    }

    progress("AI月度分析", 50)
    try:
        ai_analysis = generate_monthly_analysis(
            student_info={
                "name": student["name"],
                "grade": student["grade"],
                "english_score": student.get("english_score"),
            },
            month_label=month_label,
            month_stats=month_stats,
            kp_breakdown=kp_breakdown or "无错题记录",
            score_history=score_history_str,
            task_id=task_id,
        )
    except Exception:
        ai_analysis = {}

    # L3 长期记忆刷新（失败只告警，不影响月报本身）
    progress("更新长期记忆", 70)
    try:
        _refresh_student_memory(student, month_label, month_stats,
                                kp_breakdown, score_history_str,
                                db_path=db_path, task_id=task_id)
    except Exception:
        log.warning("L3 长期记忆刷新失败 student=%s", student_id, exc_info=True)

    progress("生成月度报告", 80)
    memory = db.get_student_memory(student_id, db_path=db_path)
    mr_html = render_monthly_report(
        student=student, mistakes=mistakes,
        month_label=month_label, month_stats=month_stats,
        ai_analysis=ai_analysis, memory=memory,
    )
    mr_dir = os.path.join(stages.UPLOAD_DIR, str(student_id), "report_pdf")
    os.makedirs(mr_dir, exist_ok=True)
    mr_filename = f"monthly_{month_start.isoformat()}_{uuid.uuid4().hex[:8]}.html"
    mr_path = os.path.join(mr_dir, mr_filename)
    with open(mr_path, "w", encoding="utf-8") as f:
        f.write(mr_html)
    monthly_file_id = db.add_file(
        student_id=student_id, uploader_role="teacher",
        file_type="report_pdf", filename=mr_filename,
        original_filename=f"月度报告-{student['name']}-{month_label}.html",
        week_start=month_start.isoformat(), file_size=os.path.getsize(mr_path),
        mime_type="text/html", db_path=db_path,
    )

    progress("完成", 100)
    return {
        "needs_review": False,
        "student_id": student_id,
        "report_file_id": monthly_file_id,
        "mistakes_count": len(mistakes),
        "mastered_count": mastered_cnt,
        "stage": "monthly_done",
    }
