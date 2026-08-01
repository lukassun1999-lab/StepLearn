#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每周循环流水线
OCR 试卷 → 错题分析 → 同类题生成 → 练习题 HTML → 批改 → 周报 → 更新方案
"""

import json
import os
import uuid
from datetime import date, timedelta

from db import (
    get_student, get_student_profile, get_file, add_file, get_or_create_weekly_record,
    update_weekly_record, update_task_progress, get_week_start,
    add_mistake as db_add_mistake, create_session, add_mistake_to_session,
    get_unmastered_mistakes, get_weak_knowledge_points,
    get_learning_plan, save_learning_plan, add_plan_update, record_score,
    record_check_in, get_plan_needs_review, get_weekly_comparison,
    get_weekly_completion_rate, get_weekly_stats, record_practice,
)
from skills_bridge import (
    run_ocr, analyze_mistakes, generate_questions, grade_answers,
    generate_plan_update, generate_learning_plan, WEEKLY_QUESTION_TARGET,
)
from report_templates import (
    render_diagnostic_report, render_exercise_sheet,
    render_feedback_report, render_weekly_report,
)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")


def _get_image_path(student_id: int, file_id: int, db_path: str) -> str:
    finfo = get_file(file_id, db_path)
    path = os.path.join(UPLOAD_DIR, str(student_id), finfo["file_type"], finfo["filename"])
    if not os.path.exists(path):
        raise FileNotFoundError(f"Image not found: {path}")
    return path


def _ocr_multiple(file_ids: list, student_id: int, task_id: int, db_path: str) -> str:
    """OCR one or more images and concatenate text with page separators."""
    if not file_ids:
        return ""
    parts = []
    for idx, fid in enumerate(file_ids):
        try:
            path = _get_image_path(student_id, fid, db_path)
            result = run_ocr(path, task_id=task_id)
            text = result.get("text", "").strip()
            if text:
                parts.append(f"--- 第 {idx + 1} 页 ---\n{text}")
        except Exception:
            parts.append(f"--- 第 {idx + 1} 页 ---\n[系统提示] OCR未能识别该页")
    return "\n\n".join(parts)


def run_weekly(task: dict, db_path: str) -> dict:
    """Execute the weekly pipeline. Called by pipeline_worker as registered handler."""
    task_id = task["id"]
    student_id = task["student_id"]
    input_data = task.get("input_data", {}) or {}
    file_id = input_data.get("file_id")
    file_ids = input_data.get("file_ids") or ([file_id] if file_id else [])
    answer_file_id = input_data.get("answer_file_id")
    answer_file_ids = input_data.get("answer_file_ids") or ([answer_file_id] if answer_file_id else [])
    pipeline_stage = input_data.get("stage", "full")  # 'full' | 'grade_only'

    def progress(step: str, pct: int):
        update_task_progress(task_id, step, pct, db_path)

    # ── Load data ──
    progress("加载数据", 5)
    student = get_student(student_id, db_path)
    if not student:
        raise ValueError(f"Student {student_id} not found")

    week_start = task.get("week_start") or get_week_start()

    # ── STAGE A: Paper → Exercises ──
    if pipeline_stage in ("full",):
        if not file_ids:
            raise ValueError("No file_id or file_ids for weekly pipeline")

        # STEP 1: OCR
        progress("OCR识别试卷", 15)
        ocr_text = _ocr_multiple(file_ids, student_id, task_id, db_path)
        if not ocr_text:
            ocr_text = "[系统提示] OCR未能完整识别，请基于学生基本信息分析"

        # STEP 2: Analyze mistakes
        progress("AI分析错题", 35)
        teacher_notes = input_data.get("teacher_notes", "")
        if teacher_notes:
            ocr_text = f"{ocr_text}\n\n[老师意见]: {teacher_notes}"
        analysis = analyze_mistakes(ocr_text, task_id=task_id)
        mistakes = analysis.get("mistakes", [])

        # Save new mistakes
        session_id = create_session(student_id,
                                     exam_name=f"{student['name']}周测-{week_start}",
                                     db_path=db_path)
        saved_mistake_ids = []
        for m in mistakes:
            mid = db_add_mistake(
                student_id=student_id,
                source_exam=f"{student['name']}周测-{week_start}",
                question=m.get("question_text", ""),
                question_type=m.get("question_type", ""),
                correct_answer=m.get("correct_answer", ""),
                user_answer=m.get("user_answer", ""),
                explanation=m.get("explanation", "")[:500],
                knowledge_points=m.get("knowledge_points", []),
                difficulty=m.get("difficulty", 2),
                db_path=db_path,
            )
            saved_mistake_ids.append(mid)
            add_mistake_to_session(session_id, mid, db_path)

        # STEP 3: Weak point matrix
        progress("生成薄弱点矩阵", 45)
        weak_points = get_weak_knowledge_points(student_id=student_id, top_n=8, db_path=db_path)
        severity_map = {"高": 0, "中": 1, "低": 2}
        for wp in weak_points:
            mastery = wp.get("mastery_rate", 50)
            if mastery < 30:
                wp["severity"] = "高"
            elif mastery < 60:
                wp["severity"] = "中"
            else:
                wp["severity"] = "低"

        # STEP 4: Generate learning plan
        progress("AI生成学习方案", 55)
        summary = analysis.get("summary", {})
        ocr_confidence = analysis.get("ocr_confidence", 0.8)
        diagnosis = {
            "mistakes_summary": summary,
            "mistakes_count": len(mistakes),
            "weak_points": weak_points,
            "ocr_confidence": ocr_confidence,
        }
        profile = get_student_profile(student_id, db_path=db_path)
        plan = generate_learning_plan(
            student_info={
                "name": student["name"],
                "grade": student["grade"],
                "english_score": student.get("english_score"),
                "school_type": student["school_type"],
                "target_score": student.get("target_score"),
            },
            diagnosis=diagnosis,
            profile=profile,
            task_id=task_id,
        )
        save_learning_plan(student_id, plan, weak_points, db_path)

        # STEP 5: Generate analysis report HTML
        progress("生成分析报告", 65)
        report_html = render_diagnostic_report(
            student=student,
            ocr_confidence=ocr_confidence,
            mistakes=mistakes,
            weak_points=weak_points,
            learning_plan=plan,
        )
        report_dir = os.path.join(UPLOAD_DIR, str(student_id), "report_pdf")
        os.makedirs(report_dir, exist_ok=True)
        report_filename = f"weekly_analysis_{week_start}_{uuid.uuid4().hex[:8]}.html"
        report_path = os.path.join(report_dir, report_filename)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_html)
        report_file_id = add_file(
            student_id=student_id, uploader_role="teacher",
            file_type="report_pdf", filename=report_filename,
            original_filename=f"周测分析报告-{student['name']}-{week_start}.html",
            week_start=week_start, file_size=os.path.getsize(report_path),
            mime_type="text/html", db_path=db_path,
        )

        # STEP 6: Generate similar questions (target: 15 per week)
        progress("AI生成练习题", 75)
        unmastered = get_unmastered_mistakes(student_id=student_id, db_path=db_path)
        questions_data = []
        if unmastered:
            # Pass all unmastered mistakes; generate_questions caps at WEEKLY_QUESTION_TARGET
            qresult = generate_questions(unmastered, task_id=task_id)  # target 15 by default
            questions_data = qresult.get("questions", [])

        # STEP 7: Generate exercise HTML
        progress("生成练习题", 85)
        ex_html = render_exercise_sheet(
            student_name=student["name"],
            questions=questions_data,
            week_start=week_start,
        )
        ex_dir = os.path.join(UPLOAD_DIR, str(student_id), "exercise_pdf")
        os.makedirs(ex_dir, exist_ok=True)
        ex_filename = f"exercise_{week_start}_{uuid.uuid4().hex[:8]}.html"
        ex_path = os.path.join(ex_dir, ex_filename)
        with open(ex_path, "w", encoding="utf-8") as f:
            f.write(ex_html)
        exercise_file_id = add_file(
            student_id=student_id, uploader_role="teacher",
            file_type="exercise_pdf", filename=ex_filename,
            original_filename=f"练习题-{student['name']}-{week_start}.html",
            week_start=week_start, file_size=os.path.getsize(ex_path),
            mime_type="text/html", db_path=db_path,
        )

        # Update weekly records
        update_weekly_record(student_id, week_start,
                             paper_submitted=1, paper_analyzed=1,
                             exercises_sent=1, report_sent=1, db_path=db_path)

        progress("完成", 95)

        return {
            "needs_review": get_plan_needs_review(student_id, db_path),
            "student_id": student_id,
            "exercise_file_id": exercise_file_id,
            "report_file_id": report_file_id,
            "mistakes_count": len(mistakes),
            "questions_count": len(questions_data),
            "session_id": session_id,
            "mistake_ids": saved_mistake_ids,
            "stage": "exercises_ready",
        }

    # ── STAGE B: Grade Only (OCR + analyze, save mistakes) ──
    if pipeline_stage in ("grade_only",):
        if not file_ids:
            raise ValueError("No file_ids for grading")

        # STEP 1: OCR
        progress("OCR识别试卷", 20)
        ocr_text = _ocr_multiple(file_ids, student_id, task_id, db_path)
        if not ocr_text:
            ocr_text = "[系统提示] OCR未能完整识别"

        # STEP 2: Analyze mistakes
        progress("AI分析错题", 60)
        teacher_notes = input_data.get("teacher_notes", "")
        if teacher_notes:
            ocr_text = f"{ocr_text}\n\n[老师意见]: {teacher_notes}"
        analysis = analyze_mistakes(ocr_text, task_id=task_id)
        mistakes = analysis.get("mistakes", [])

        # Save mistakes
        session_id = create_session(student_id,
                                     exam_name=f"{student['name']}周测-{week_start}",
                                     db_path=db_path)
        saved_mistake_ids = []
        for m in mistakes:
            mid = db_add_mistake(
                student_id=student_id,
                source_exam=f"{student['name']}周测-{week_start}",
                question=m.get("question_text", ""),
                question_type=m.get("question_type", ""),
                correct_answer=m.get("correct_answer", ""),
                user_answer=m.get("user_answer", ""),
                explanation=m.get("explanation", "")[:500],
                knowledge_points=m.get("knowledge_points", []),
                difficulty=m.get("difficulty", 2),
                db_path=db_path,
            )
            saved_mistake_ids.append(mid)
            add_mistake_to_session(session_id, mid, db_path)

        # Update weekly records
        update_weekly_record(student_id, week_start,
                             paper_submitted=1, paper_analyzed=1, db_path=db_path)

        progress("完成", 100)
        return {
            "needs_review": get_plan_needs_review(student_id, db_path),
            "student_id": student_id,
            "file_ids": file_ids,
            "mistakes_count": len(mistakes),
            "session_id": session_id,
            "mistake_ids": saved_mistake_ids,
            "stage": "grading_done",
        }

    # ─ STAGE C: Analysis Only (weak points + plan + exercises + report) ──
    if pipeline_stage in ("analysis_only",):
        progress("加载学情数据", 10)
        weak_points = get_weak_knowledge_points(student_id=student_id, top_n=8, db_path=db_path)
        for wp in weak_points:
            mastery = wp.get("mastery_rate", 50)
            if mastery < 30:
                wp["severity"] = "高"
            elif mastery < 60:
                wp["severity"] = "中"
            else:
                wp["severity"] = "低"

        # Incremental plan update (don't overwrite from scratch if plan exists)
        progress("更新学习方案", 25)
        existing_plan = get_learning_plan(student_id, db_path=db_path) or {}
        profile = get_student_profile(student_id, db_path=db_path)
        learning_style_detail = (profile or {}).get("learning_style_detail") or None

        if existing_plan.get("modules"):
            # Plan exists → incremental update via plan_update prompt
            unmastered = get_unmastered_mistakes(student_id=student_id, db_path=db_path)
            new_mistakes_json = json.dumps(
                [{"question": m.get("question", "")[:100], "knowledge_points": m.get("knowledge_points", [])}
                 for m in unmastered[:10]], ensure_ascii=False)
            mastered_json = "[]"
            completion_rate = get_weekly_completion_rate(student_id, week_start, db_path=db_path)
            parent_task_progress = (profile or {}).get("parent_task_progress") or {}
            plan_choices = (profile or {}).get("plan_choices") or {}
            current_modules = existing_plan.get("modules") or []

            plan_update = generate_plan_update(
                student_id=student_id,
                week_start=week_start,
                weak_point_matrix=weak_points,
                new_mistakes_json=new_mistakes_json,
                mastered_mistakes_json=mastered_json,
                new_count=len(unmastered),
                mastered_count=0,
                completion_rate=completion_rate,
                parent_task_progress_json=json.dumps(parent_task_progress, ensure_ascii=False),
                parent_tasks_json=json.dumps(existing_plan.get("parent_growth_tasks", []), ensure_ascii=False),
                plan_choices_json=json.dumps(plan_choices, ensure_ascii=False),
                current_modules_json=json.dumps(current_modules, ensure_ascii=False),
                task_id=task_id,
            )
            # Merge adjustments into existing plan
            if plan_update.get("adjusted_modules"):
                existing_plan["modules"] = plan_update["adjusted_modules"]
            if plan_update.get("motivation_message"):
                existing_plan["motivation_message"] = plan_update["motivation_message"]
            if plan_update.get("parent_guide"):
                existing_plan["parent_guide"] = plan_update["parent_guide"]
            save_learning_plan(student_id, existing_plan, weak_points, db_path)
            add_plan_update(student_id, week_start,
                            json.dumps(plan_update, ensure_ascii=False), db_path=db_path)
            plan = existing_plan
        else:
            # No existing plan → generate from scratch
            from db import get_connection as _get_conn
            _conn = _get_conn(db_path)
            _mistake_rows = _conn.execute("""
                SELECT question, question_type, correct_answer, user_answer,
                       explanation, knowledge_points, difficulty
                FROM mistakes WHERE student_id = ?
                ORDER BY created_at DESC LIMIT 20
            """, [student_id]).fetchall()
            _conn.close()
            _diagnosis_mistakes = []
            for m in _mistake_rows:
                kp = m["knowledge_points"]
                if isinstance(kp, str):
                    try:
                        kp = json.loads(kp)
                    except Exception:
                        kp = []
                _diagnosis_mistakes.append({
                    "question_text": m["question"] or "",
                    "knowledge_points": kp if isinstance(kp, list) else [kp],
                })
            diagnosis = {
                "mistakes_summary": {},
                "mistakes_count": len(_diagnosis_mistakes),
                "weak_points": weak_points,
                "ocr_confidence": 0.8,
            }
            plan = generate_learning_plan(
                student_info={
                    "name": student["name"],
                    "grade": student["grade"],
                    "english_score": student.get("english_score"),
                    "school_type": student["school_type"],
                    "target_score": student.get("target_score"),
                },
                diagnosis=diagnosis,
                profile=profile,
                task_id=task_id,
            )
            save_learning_plan(student_id, plan, weak_points, db_path)

        # Fetch recent mistakes from DB for report display
        from db import get_connection
        conn = get_connection(db_path)
        mistake_rows = conn.execute("""
            SELECT question, question_type, correct_answer, user_answer,
                   explanation, knowledge_points, difficulty, created_at
            FROM mistakes
            WHERE student_id = ?
            ORDER BY created_at DESC
            LIMIT 20
        """, [student_id]).fetchall()
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
                "error_reason": (m["explanation"] or "")[:200],
                "knowledge_points": kp if isinstance(kp, list) else [kp],
                "difficulty": m["difficulty"] or 2,
            })

        # Generate analysis report HTML
        progress("生成分析报告", 50)
        report_html = render_diagnostic_report(
            student=student,
            ocr_confidence=0.8,
            mistakes=mistakes,
            weak_points=weak_points,
            learning_plan=plan,
        )
        report_dir = os.path.join(UPLOAD_DIR, str(student_id), "report_pdf")
        os.makedirs(report_dir, exist_ok=True)
        report_filename = f"analysis_{week_start}_{uuid.uuid4().hex[:8]}.html"
        report_path = os.path.join(report_dir, report_filename)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_html)
        report_file_id = add_file(
            student_id=student_id, uploader_role="teacher",
            file_type="report_pdf", filename=report_filename,
            original_filename=f"矩阵分析报告-{student['name']}-{week_start}.html",
            week_start=week_start, file_size=os.path.getsize(report_path),
            mime_type="text/html", db_path=db_path,
        )

        # Generate practice questions from unmastered mistakes
        progress("AI生成练习题", 70)
        unmastered = get_unmastered_mistakes(student_id=student_id, db_path=db_path)
        questions_data = []
        exercise_file_id = None
        if unmastered:
            qresult = generate_questions(unmastered, task_id=task_id)
            questions_data = qresult.get("questions", [])

        if questions_data:
            progress("生成练习题卷", 85)
            ex_html = render_exercise_sheet(
                student_name=student["name"],
                questions=questions_data,
                week_start=week_start,
            )
            ex_dir = os.path.join(UPLOAD_DIR, str(student_id), "exercise_pdf")
            os.makedirs(ex_dir, exist_ok=True)
            ex_filename = f"exercise_{week_start}_{uuid.uuid4().hex[:8]}.html"
            ex_path = os.path.join(ex_dir, ex_filename)
            with open(ex_path, "w", encoding="utf-8") as f:
                f.write(ex_html)
            exercise_file_id = add_file(
                student_id=student_id, uploader_role="teacher",
                file_type="exercise_pdf", filename=ex_filename,
                original_filename=f"练习题-{student['name']}-{week_start}.html",
                week_start=week_start, file_size=os.path.getsize(ex_path),
                mime_type="text/html", db_path=db_path,
            )

        # Update weekly records
        update_weekly_record(student_id, week_start,
                             exercises_sent=1 if questions_data else 0,
                             report_sent=1, db_path=db_path)

        progress("完成", 100)
        return {
            "needs_review": get_plan_needs_review(student_id, db_path),
            "student_id": student_id,
            "report_file_id": report_file_id,
            "exercise_file_id": exercise_file_id,
            "questions_count": len(questions_data),
            "stage": "analysis_done",
        }

    # ── STAGE C: Generate Weekly Report (no answer upload needed) ─
    if pipeline_stage in ("report_only",):
        # Generate weekly parent report based on existing data from Stage A
        progress("加载学情数据", 20)
        week_end = (date.fromisoformat(week_start) + timedelta(days=6)).isoformat()
        weekly_stats = get_weekly_stats(student_id, week_start, week_end, db_path=db_path)
        comparison = get_weekly_comparison(student_id, week_start, weeks=4, db_path=db_path)
        profile = get_student_profile(student_id, db_path=db_path)
        learning_style_detail = (profile or {}).get("learning_style_detail") or None

        # Build action plan from weekly data
        top_weak = weekly_stats.get("weak_areas", [{}])[0].get("knowledge_point", "") if weekly_stats.get("weak_areas") else ""
        second_weak = weekly_stats.get("weak_areas", [{}])[1].get("knowledge_point", "") if len(weekly_stats.get("weak_areas", [])) > 1 else ""
        system_will = []
        if top_weak:
            system_will.append(f"下周针对「{top_weak}」出专项练习")
        if second_weak:
            system_will.append(f"同步关注「{second_weak}」的掌握情况")
        if not system_will:
            system_will.append("下周继续根据薄弱点生成专项练习")
        system_will.append("预计周四前生成新的专属练习题")
        action_plan = {
            "system_will": system_will,
            "student_should": [
                "完成本周专属练习题（约30分钟）",
                "每天花5分钟过一遍错题本",
            ],
            "parent_can": [
                "周六前拍一张最近的英语试卷发过来",
                "孩子做完练习后，问一句'今天练了什么'就够了",
            ],
        }

        # Generate weekly report HTML
        progress("生成周报", 60)
        wr_html = render_weekly_report(
            student_name=student["name"],
            week_start=week_start,
            week_end=week_end,
            new_mistakes=weekly_stats.get("new_mistakes_count", 0),
            mastered_count=weekly_stats.get("mastered_count", 0),
            weak_areas=weekly_stats.get("weak_areas", []),
            ai_clinic="",
            comparison=comparison,
            learning_style_detail=learning_style_detail,
            action_plan=action_plan,
        )
        wr_dir = os.path.join(UPLOAD_DIR, str(student_id), "weekly_pdf")
        os.makedirs(wr_dir, exist_ok=True)
        wr_filename = f"weekly_{week_start}_{uuid.uuid4().hex[:8]}.html"
        wr_path = os.path.join(wr_dir, wr_filename)
        with open(wr_path, "w", encoding="utf-8") as f:
            f.write(wr_html)
        weekly_report_file_id = add_file(
            student_id=student_id, uploader_role="teacher",
            file_type="weekly_pdf", filename=wr_filename,
            original_filename=f"家长周报-{student['name']}-{week_start}.html",
            week_start=week_start, file_size=os.path.getsize(wr_path),
            mime_type="text/html", db_path=db_path,
        )

        # Update weekly records
        update_weekly_record(student_id, week_start,
                             report_sent=1, db_path=db_path)

        # Auto check-in
        try:
            record_check_in(student_id, check_in_date=week_start,
                            content="生成周度学习报告",
                            duration_minutes=5,
                            source="auto",
                            db_path=db_path)
        except Exception:
            pass

        progress("完成", 100)

        return {
            "needs_review": get_plan_needs_review(student_id, db_path),
            "student_id": student_id,
            "weekly_report_file_id": weekly_report_file_id,
            "stage": "report_done",
        }

    # ── STAGE E: Grade Exercises (OCR answers → grade → update mastery) ──
    if pipeline_stage in ("grade_exercises",):
        if not file_ids:
            raise ValueError("No file_ids for exercise grading")

        # STEP 1: OCR student answer sheet
        progress("OCR识别答案", 15)
        ocr_text = _ocr_multiple(file_ids, student_id, task_id, db_path)
        if not ocr_text:
            raise ValueError("OCR未能识别学生答案，请检查图片质量")

        # STEP 2: Load recent exercise questions for this student
        progress("加载练习题", 30)
        from db import get_connection
        conn = get_connection(db_path)
        # Get questions generated this week for this student (via source_mistake_id link)
        question_rows = conn.execute("""
            SELECT q.id, q.question_text, q.question_type, q.correct_answer,
                   q.explanation, q.knowledge_points, q.difficulty, q.source_mistake_id
            FROM questions q
            JOIN mistakes m ON m.id = q.source_mistake_id
            WHERE m.student_id = ? AND q.enabled = 1
            ORDER BY q.created_at DESC
            LIMIT 20
        """, [student_id]).fetchall()
        conn.close()

        if not question_rows:
            # Fallback: get questions by knowledge points matching student's mistakes
            unmastered = get_unmastered_mistakes(student_id=student_id, db_path=db_path)
            all_kps = set()
            for m in unmastered:
                kps = m.get("knowledge_points", [])
                if isinstance(kps, str):
                    try:
                        kps = json.loads(kps)
                    except Exception:
                        kps = []
                all_kps.update(kps)
            from db import find_similar_questions
            question_rows_raw = find_similar_questions(list(all_kps), limit=20)
            question_rows = [dict(r) if not isinstance(r, dict) else r for r in question_rows_raw]

        questions_for_grading = []
        for q in question_rows:
            kp = q.get("knowledge_points", "[]")
            if isinstance(kp, str):
                try:
                    kp = json.loads(kp)
                except Exception:
                    kp = []
            questions_for_grading.append({
                "question_text": q.get("question_text", ""),
                "question_type": q.get("question_type", ""),
                "correct_answer": q.get("correct_answer", ""),
                "explanation": q.get("explanation", ""),
                "knowledge_points": kp if isinstance(kp, list) else [kp],
                "difficulty": q.get("difficulty", 2),
                "source_mistake_id": q.get("source_mistake_id"),
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
                    record_practice(
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
        fb_dir = os.path.join(UPLOAD_DIR, str(student_id), "report_pdf")
        os.makedirs(fb_dir, exist_ok=True)
        fb_filename = f"feedback_{week_start}_{uuid.uuid4().hex[:8]}.html"
        fb_path = os.path.join(fb_dir, fb_filename)
        with open(fb_path, "w", encoding="utf-8") as f:
            f.write(fb_html)
        feedback_file_id = add_file(
            student_id=student_id, uploader_role="teacher",
            file_type="report_pdf", filename=fb_filename,
            original_filename=f"练习批改反馈-{student['name']}-{week_start}.html",
            week_start=week_start, file_size=os.path.getsize(fb_path),
            mime_type="text/html", db_path=db_path,
        )

        # Update weekly records
        update_weekly_record(student_id, week_start,
                             exercises_completed=1, exercises_graded=1, db_path=db_path)

        # Record score if accuracy available
        accuracy = summary.get("accuracy")
        if accuracy is not None:
            record_score(student_id, score=accuracy * 100,
                         score_type="practice", source_task_id=task_id,
                         week_start=week_start, db_path=db_path)

        progress("完成", 100)
        return {
            "needs_review": get_plan_needs_review(student_id, db_path),
            "student_id": student_id,
            "feedback_file_id": feedback_file_id,
            "correct_count": summary.get("correct", 0),
            "total_count": summary.get("total", 0),
            "accuracy": summary.get("accuracy", 0),
            "stage": "exercise_graded",
        }



# ═══════════════════════════════════════════════════
# Register
# ═══════════════════════════════════════════════════

def register():
    from pipeline_worker import register_handler
    register_handler("weekly", run_weekly)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    print("weekly_pipeline.py OK (run via app.py)")
