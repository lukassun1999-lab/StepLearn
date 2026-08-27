#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""链节点：每个节点是一个函数 node(ctx)（见 核心链路架构设计.md §4）。

分析主链（声明顺序即执行顺序）:
    ocr → analyze → plan → analysis_report → exercises
weekly_report 为独立节点（手动补发 / 周六条件自动）。

节点产物双落库（DB + 文件），支持断点续跑；ocr 文本持久化到
ai_tasks.input_data._ocr_text，僵尸任务复活时免重识别。
"""

import json
import logging
import os
import uuid
from datetime import date, timedelta

log = logging.getLogger(__name__)

import db
from skills_bridge import (
    analyze_mistakes, generate_questions, generate_plan_update,
    generate_learning_plan, analyze_cause_chain, build_cause_trend,
    CAUSE_KEYS,
)
from report_templates import (
    render_diagnostic_report, render_exercise_sheet, render_weekly_report,
)

# pipeline/ 在项目根下一层，uploads 在项目根（可被测试 monkeypatch）
UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")


class Ctx:
    """一次链运行的上下文：中间产物 + 产物。"""

    def __init__(self, task: dict, db_path: str):
        self.task = task
        self.task_id = task["id"]
        self.student_id = task["student_id"]
        self.db_path = db_path
        self.input_data = task.get("input_data") or {}
        if isinstance(self.input_data, str):
            try:
                self.input_data = json.loads(self.input_data)
            except Exception:
                self.input_data = {}
        self.week_start = task.get("week_start") or db.get_week_start()
        self.kind = "weekly"          # 由 engine 设置
        self.start_node = "ocr"       # 由 engine 设置
        # ── 中间产物 ──
        self.student = None
        self.file_ids = []
        self.ocr_text = ""
        self.ocr_confidence = 0.8
        self.analysis = None          # analyze_mistakes 原始返回
        self.mistakes = []            # 本次分析产出的错题（dict 形态）
        self.chunk_stats = None       # 分段分析执行情况 {total, ok, failed}（非分段为 None）
        self.session_id = None
        self.saved_mistake_ids = []
        self.weak_points = []
        self.cause_profile = None    # 错因因果链画像（analyze_cause_chain 产物）
        self.plan = None
        self.questions_data = []
        # ── 产物（files 表 id）──
        self.report_file_id = None
        self.exercise_file_id = None
        self.weekly_report_file_id = None
        self.essay_review_file_id = None   # 作文批改报告（写作类错题触发）

    def progress(self, step: str, pct: int):
        db.update_task_progress(self.task_id, step, pct, self.db_path)

    def has_files(self) -> bool:
        return bool(self.input_data.get("file_ids") or self.input_data.get("file_id"))

    def resolve_file_ids(self):
        return self.input_data.get("file_ids") or (
            [self.input_data["file_id"]] if self.input_data.get("file_id") else [])

    def build_output(self) -> dict:
        """按 kind 构造任务 output_data。"""
        from domain import cycle as cycle_mod
        if self.kind == cycle_mod.KIND_DIAGNOSTIC:
            out = {
                "needs_review": False,
                "student_id": self.student_id,
                "report_file_id": self.report_file_id,
                "mistakes_count": len(self.mistakes),
                "weak_points_count": len(self.weak_points),
                "ocr_confidence": self.ocr_confidence,
                "session_id": self.session_id,
                "mistake_ids": self.saved_mistake_ids,
            }
            if self.chunk_stats:
                out["chunk_stats"] = self.chunk_stats
            return out
        out = {
            "needs_review": False,
            "student_id": self.student_id,
            "exercise_file_id": self.exercise_file_id,
            "report_file_id": self.report_file_id,
            "essay_review_file_id": self.essay_review_file_id,
            "mistakes_count": len(self.mistakes),
            "questions_count": len(self.questions_data),
            "session_id": self.session_id,
            "mistake_ids": self.saved_mistake_ids,
            # stage 标记保留前端兼容：ocr 起点=完整批改分析；plan 起点=矩阵分析
            "stage": "exercises_ready" if self.start_node == "ocr" else "analysis_done",
        }
        if self.file_ids:
            out["file_ids"] = self.file_ids
        if self.chunk_stats:
            out["chunk_stats"] = self.chunk_stats
        return out


# ═══════════════════════════════════════════════════
# OCR 辅助
# ═══════════════════════════════════════════════════

def get_image_path(student_id: int, file_id: int, db_path: str) -> str:
    finfo = db.get_file(file_id, db_path)
    if not finfo:
        raise ValueError(f"File {file_id} not found")
    path = os.path.join(UPLOAD_DIR, str(student_id), finfo["file_type"], finfo["filename"])
    if not os.path.exists(path):
        raise FileNotFoundError(f"Image not found: {path}")
    return path


def ocr_to_text(file_ids, student_id, task_id, db_path):
    """并行 OCR 全部页并按页序拼接。返回 (text, avg_confidence)。

    缺页/识别失败不中断，以占位提示替代（与历史行为一致）。
    """
    from skills_bridge import run_ocr_parallel
    jobs = []
    for idx, fid in enumerate(file_ids):
        try:
            jobs.append((idx, get_image_path(student_id, fid, db_path)))
        except Exception:
            log.warning("试卷图片缺失跳过 file_id=%s", fid, exc_info=True)
    results = run_ocr_parallel([p for _, p in jobs], task_id=task_id)
    parts = [None] * len(file_ids)
    conf_sum, conf_n = 0.0, 0
    for (idx, _), r in zip(jobs, results):
        if r["ok"] and r["text"]:
            parts[idx] = f"--- 第 {idx + 1} 页 ---\n{r['text']}"
            conf_sum += r.get("confidence", 0.0) or 0.0
            conf_n += 1
        else:
            parts[idx] = f"--- 第 {idx + 1} 页 ---\n[系统提示] OCR未能识别该页"
    for i in range(len(file_ids)):
        if parts[i] is None:
            parts[i] = f"--- 第 {i + 1} 页 ---\n[系统提示] OCR未能识别该页"
    confidence = conf_sum / conf_n if conf_n else 0.3
    return "\n\n".join(parts), confidence


_OCR_EMPTY_PLACEHOLDER = (
    "[系统提示] 此试卷图片未能通过OCR自动提取文字。请基于学生基本信息"
    "（年级/分数）给出通用诊断。")


# ═══════════════════════════════════════════════════
# 链节点
# ═══════════════════════════════════════════════════

def node_ocr(ctx: Ctx):
    file_ids = ctx.resolve_file_ids()
    if not file_ids:
        raise ValueError("缺少试卷照片（file_id/file_ids）")
    ctx.progress("OCR识别试卷", 15)
    text, confidence = ocr_to_text(file_ids, ctx.student_id, ctx.task_id, ctx.db_path)
    if not text.strip() or len(text.strip()) < 50:
        text = _OCR_EMPTY_PLACEHOLDER
        confidence = confidence or 0.3
    ctx.file_ids = file_ids
    ctx.ocr_text = text
    ctx.ocr_confidence = confidence
    # 持久化 OCR 中间产物，供断点续跑（免重复识别）
    persisted = dict(ctx.input_data)
    persisted["_ocr_text"] = text
    db.update_task(ctx.task_id, {
        "input_data": json.dumps(persisted, ensure_ascii=False),
    }, ctx.db_path)


def node_analyze(ctx: Ctx):
    from domain import cycle as cycle_mod
    ctx.progress("AI分析错题", 35)
    # 幂等清理：僵尸任务断点续跑重放本节点时，先删掉本任务上一次尝试
    # 写入的错题/场次（崩溃窗口 [错题入库, advance_cycle 未落] 内复活，
    # 不清理会造成错题翻倍）。清掉后按本次分析结果重建。
    db.purge_task_mistakes(ctx.task_id, db_path=ctx.db_path)
    ocr_text = ctx.ocr_text
    teacher_notes = ctx.input_data.get("teacher_notes", "")
    if teacher_notes:
        ocr_text = f"{ocr_text}\n\n[老师意见]: {teacher_notes}"
    analysis = analyze_mistakes(ocr_text, task_id=ctx.task_id)
    mistakes = analysis.get("mistakes", [])
    ctx.chunk_stats = (analysis.get("summary") or {}).get("chunk_stats")

    if ctx.kind == cycle_mod.KIND_DIAGNOSTIC:
        exam_name = f"{ctx.student['name']}首次诊断"
    else:
        exam_name = f"{ctx.student['name']}周测-{ctx.week_start}"
    try:
        ctx.session_id = db.create_session(
            ctx.student_id, exam_name=exam_name,
            source_task_id=ctx.task_id, db_path=ctx.db_path)
        for m in mistakes:
            mid = db.add_mistake(
                student_id=ctx.student_id,
                source_exam=exam_name,
                question=m.get("question_text", ""),
                question_type=m.get("question_type", ""),
                correct_answer=m.get("correct_answer", ""),
                user_answer=m.get("user_answer", ""),
                explanation=m.get("explanation", "")[:500],
                knowledge_points=m.get("knowledge_points", []),
                difficulty=m.get("difficulty", 2),
                error_cause=m.get("error_cause", ""),
                cause_evidence=m.get("cause_evidence", ""),
                passage=m.get("passage", ""),
                source_task_id=ctx.task_id,
                db_path=ctx.db_path,
            )
            ctx.saved_mistake_ids.append(mid)
            db.add_mistake_to_session(ctx.session_id, mid, db_path=ctx.db_path)
    except Exception:
        # 插入中途失败：清掉本任务半成品，不留孤儿错题（下次重跑重建）
        db.purge_task_mistakes(ctx.task_id, db_path=ctx.db_path)
        raise

    db.update_weekly_record(ctx.student_id, ctx.week_start, kind=ctx.kind,
                            paper_submitted=1, paper_analyzed=1,
                            db_path=ctx.db_path)
    ctx.analysis = analysis
    ctx.mistakes = mistakes
    # 试卷内嵌作文批改（写作类错题触发；失败不阻断主链路）
    node_essay_review(ctx)


_WRITING_TYPES = ("书面表达", "写作", "英语写作", "英语表达")


def node_essay_review(ctx: Ctx):
    """作文批改：本次错题含写作类且学生有作文内容时，生成批改报告。
    独立于主链状态机（由 node_analyze 末尾调用），失败静默。"""
    if not ctx.mistakes:
        return
    essay_mistake = None
    for m in ctx.mistakes:
        if (m.get("question_type") or "") in _WRITING_TYPES:
            essay = str(m.get("user_answer") or "").strip()
            if essay and essay not in ("未作答", "未填写", "无", "-"):
                essay_mistake = m
                break
    if not essay_mistake:
        return
    ctx.progress("批改作文", 42)
    try:
        from skills_bridge import review_essay
        review = review_essay(
            question=essay_mistake.get("question_text", "") or "英语作文",
            essay=str(essay_mistake.get("user_answer", "")),
            grade=(ctx.student or {}).get("grade", ""),
            task_id=ctx.task_id,
        )
        if not isinstance(review, dict) or not review.get("errors"):
            return
        from report_templates import render_essay_review
        html = render_essay_review(ctx.student, essay_mistake, review)
        essay_dir = os.path.join(UPLOAD_DIR, str(ctx.student_id), "essay_review")
        os.makedirs(essay_dir, exist_ok=True)
        fname = f"essay_{ctx.week_start}_{uuid.uuid4().hex[:8]}.html"
        with open(os.path.join(essay_dir, fname), "w", encoding="utf-8") as f:
            f.write(html)
        ctx.essay_review_file_id = db.add_file(
            student_id=ctx.student_id, uploader_role="teacher",
            file_type="essay_review", filename=fname,
            original_filename=f"作文批改-{(ctx.student or {}).get('name', '同学')}.html",
            week_start=ctx.week_start, file_size=os.path.getsize(
                os.path.join(essay_dir, fname)),
            mime_type="text/html", db_path=ctx.db_path,
        )
    except Exception:
        ctx.essay_review_file_id = None


def _build_diagnosis(ctx: Ctx) -> dict:
    """构造方案生成输入：本次运行有分析结果则用之；断点续跑时从 DB 重建。"""
    cause_profile = db.get_cause_profile(ctx.student_id, db_path=ctx.db_path)
    if ctx.analysis:
        return {
            "mistakes_summary": ctx.analysis.get("summary", {}),
            "mistakes_count": len(ctx.mistakes),
            "weak_points": ctx.weak_points,
            "cause_profile": cause_profile,
            "ocr_confidence": ctx.ocr_confidence,
        }
    conn = db.get_connection(ctx.db_path)
    rows = conn.execute("""
        SELECT question, knowledge_points FROM mistakes
        WHERE student_id = ? ORDER BY created_at DESC LIMIT 20
    """, [ctx.student_id]).fetchall()
    conn.close()
    diag_mistakes = []
    for m in rows:
        kp = m["knowledge_points"]
        if isinstance(kp, str):
            try:
                kp = json.loads(kp)
            except Exception:
                kp = []
        diag_mistakes.append({
            "question_text": m["question"] or "",
            "knowledge_points": kp if isinstance(kp, list) else [kp],
        })
    return {
        "mistakes_summary": {},
        "mistakes_count": len(diag_mistakes),
        "weak_points": ctx.weak_points,
        "cause_profile": cause_profile,
        "ocr_confidence": 0.8,
    }


def _reorder_priority_by_cause(plan: dict, cause_profile: dict) -> dict:
    """确定性保障：把因果链根因知识点排到 weak_point_priority 最前。
    prompt 只是引导 LLM，这里保证结果——不依赖 LLM 自觉。"""
    if not isinstance(plan, dict):
        return plan
    priority_kps = [k.split("（")[0].strip()
                    for k in (cause_profile.get("priority_kps") or [])
                    if k and k.split("（")[0].strip()]
    items = plan.get("weak_point_priority")
    if not priority_kps or not isinstance(items, list) or not items:
        return plan
    # 根因知识点按 priority_kps 顺序排最前（不是按 plan 原顺序）
    matched = []
    for rk in priority_kps:
        for it in items:
            kp = it.get("knowledge_point", "")
            if rk and (rk in kp or kp in rk) and it not in matched:
                it["severity"] = "高"
                if not it.get("reason"):
                    it["reason"] = "因果链根因优先"
                matched.append(it)
    rest = [it for it in items if it not in matched]
    plan["weak_point_priority"] = matched + rest
    return plan


def node_plan(ctx: Ctx):
    """薄弱点矩阵 + 学习方案（已有方案 → 增量更新；无 → 全新生成）。"""
    ctx.progress("生成薄弱点矩阵", 45)
    weak_points = db.get_weak_knowledge_points(
        student_id=ctx.student_id, top_n=8, db_path=ctx.db_path)
    for wp in weak_points:
        mastery = wp.get("mastery_rate", 50)
        wp["severity"] = "高" if mastery < 30 else ("中" if mastery < 60 else "低")
    ctx.weak_points = weak_points

    # 错因因果链画像（独立于方案路径，每次分析都刷新；失败不阻断主链路）
    try:
        ctx.cause_profile = analyze_cause_chain(
            student=ctx.student,
            mistakes=ctx.mistakes or _recent_mistakes_from_db(ctx, limit=20),
            task_id=ctx.task_id,
        )
        if ctx.cause_profile:
            db.save_cause_profile(ctx.student_id, ctx.cause_profile, db_path=ctx.db_path)
            # 写入跨周历史（周报"卡点变化"叙事的数据源）
            counts = {}
            for m in (ctx.mistakes or _recent_mistakes_from_db(ctx, limit=20)):
                c = m.get("error_cause") or ""
                if c in CAUSE_KEYS:
                    counts[c] = counts.get(c, 0) + 1
            db.save_cause_profile_history(
                ctx.student_id, ctx.week_start,
                profile=ctx.cause_profile, cause_counts=counts,
                db_path=ctx.db_path,
            )
    except Exception:
        ctx.cause_profile = None

    plan_row = db.get_learning_plan(ctx.student_id, db_path=ctx.db_path) or {}
    existing_plan = plan_row.get("plan_data") or {}
    profile = db.get_student_profile(ctx.student_id, db_path=ctx.db_path)

    if existing_plan.get("modules"):
        # 已有方案 → 增量更新（AI 诊所，按完成率自适应调整）
        ctx.progress("更新学习方案", 55)
        unmastered = db.get_unmastered_mistakes(
            student_id=ctx.student_id, db_path=ctx.db_path)
        new_mistakes_json = json.dumps(
            [{"question": m.get("question", "")[:100],
              "knowledge_points": m.get("knowledge_points", [])}
             for m in unmastered[:10]], ensure_ascii=False)
        completion_rate = db.get_weekly_completion_rate(
            ctx.student_id, ctx.week_start, db_path=ctx.db_path)
        parent_task_progress = (profile or {}).get("parent_task_progress") or {}
        plan_choices = (profile or {}).get("plan_choices") or {}
        plan_update = generate_plan_update(
            student_id=ctx.student_id,
            week_start=ctx.week_start,
            weak_point_matrix=weak_points,
            new_mistakes_json=new_mistakes_json,
            mastered_mistakes_json="[]",
            new_count=len(unmastered),
            mastered_count=0,
            completion_rate=completion_rate,
            parent_task_progress_json=json.dumps(parent_task_progress, ensure_ascii=False),
            parent_tasks_json=json.dumps(
                existing_plan.get("parent_growth_tasks", []), ensure_ascii=False),
            plan_choices_json=json.dumps(plan_choices, ensure_ascii=False),
            current_modules_json=json.dumps(
                existing_plan.get("modules", []), ensure_ascii=False),
            task_id=ctx.task_id,
        )
        if plan_update.get("adjusted_modules"):
            existing_plan["modules"] = plan_update["adjusted_modules"]
        if plan_update.get("motivation_message"):
            existing_plan["motivation_message"] = plan_update["motivation_message"]
        if plan_update.get("parent_guide"):
            existing_plan["parent_guide"] = plan_update["parent_guide"]
        db.save_learning_plan(ctx.student_id, existing_plan, weak_points, ctx.db_path)
        db.add_plan_update(ctx.student_id, ctx.week_start,
                           json.dumps(plan_update, ensure_ascii=False),
                           db_path=ctx.db_path)
        ctx.plan = existing_plan
    else:
        # 无方案 → 全新生成（入学诊断 / 首次周循环）
        ctx.progress("AI生成学习方案", 55)
        plan = generate_learning_plan(
            student_info={
                "name": ctx.student["name"],
                "grade": ctx.student["grade"],
                "english_score": ctx.student.get("english_score"),
                "school_type": ctx.student["school_type"],
                "target_score": ctx.student.get("target_score"),
            },
            diagnosis=_build_diagnosis(ctx),
            profile=profile,
            task_id=ctx.task_id,
        )
        # 因果链根因优先（确定性重排，prompt 引导之外的兜底保障）
        if ctx.cause_profile:
            plan = _reorder_priority_by_cause(plan, ctx.cause_profile)
        # AI 评估的学习风格回写画像
        learning_style_detail = (
            plan.get("diagnosis_report", {}).get("learning_style")
            if isinstance(plan, dict) else None)
        if learning_style_detail:
            db.save_student_profile(ctx.student_id, {
                "learning_style_detail": learning_style_detail,
                "learning_style": learning_style_detail.get("dominant", ""),
            }, db_path=ctx.db_path)
        db.save_learning_plan(ctx.student_id, plan, weak_points, ctx.db_path)
        ctx.plan = plan


def _recent_mistakes_from_db(ctx: Ctx, limit: int = 20):
    """从 DB 读取最近错题（报告展示用，断点续跑/无本次分析时的数据来源）。"""
    conn = db.get_connection(ctx.db_path)
    rows = conn.execute("""
        SELECT question, question_type, correct_answer, user_answer,
               explanation, knowledge_points, difficulty
        FROM mistakes WHERE student_id = ?
        ORDER BY created_at DESC LIMIT ?
    """, [ctx.student_id, limit]).fetchall()
    conn.close()
    out = []
    for m in rows:
        kp = m["knowledge_points"]
        if isinstance(kp, str):
            try:
                kp = json.loads(kp)
            except Exception:
                kp = []
        out.append({
            "question_text": m["question"] or "",
            "question_type": m["question_type"] or "",
            "correct_answer": m["correct_answer"] or "",
            "user_answer": m["user_answer"] or "",
            "explanation": m["explanation"] or "",
            "error_reason": (m["explanation"] or "")[:200],
            "knowledge_points": kp if isinstance(kp, list) else [kp],
            "difficulty": m["difficulty"] or 2,
        })
    return out


def node_analysis_report(ctx: Ctx):
    from domain import cycle as cycle_mod
    ctx.progress("生成分析报告", 65)
    mistakes = ctx.mistakes or _recent_mistakes_from_db(ctx)
    if ctx.kind == cycle_mod.KIND_DIAGNOSTIC:
        prefix = "diagnostic"
        label = f"首次诊断报告-{ctx.student['name']}-{ctx.week_start}"
    else:
        prefix = "analysis"
        label = f"学情分析报告-{ctx.student['name']}-{ctx.week_start}"
    report_html = render_diagnostic_report(
        student=ctx.student,
        ocr_confidence=ctx.ocr_confidence,
        mistakes=mistakes,
        weak_points=ctx.weak_points,
        learning_plan=ctx.plan,
        cause_profile=(ctx.cause_profile
                       or db.get_cause_profile(ctx.student_id, db_path=ctx.db_path)),
    )
    report_dir = os.path.join(UPLOAD_DIR, str(ctx.student_id), "report_pdf")
    os.makedirs(report_dir, exist_ok=True)
    report_filename = f"{prefix}_{ctx.week_start}_{uuid.uuid4().hex[:8]}.html"
    report_path = os.path.join(report_dir, report_filename)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_html)
    ctx.report_file_id = db.add_file(
        student_id=ctx.student_id, uploader_role="teacher",
        file_type="report_pdf", filename=report_filename,
        original_filename=f"{label}.html",
        week_start=ctx.week_start, file_size=os.path.getsize(report_path),
        mime_type="text/html", db_path=ctx.db_path,
    )
    db.update_weekly_record(ctx.student_id, ctx.week_start, kind=ctx.kind,
                            report_sent=1, db_path=ctx.db_path)


def node_exercises(ctx: Ctx):
    """生成针对性练习（题库复用优先 + LLM 兜底），渲染练习卷。"""
    ctx.progress("AI生成练习题", 75)
    unmastered = db.get_unmastered_mistakes(
        student_id=ctx.student_id, db_path=ctx.db_path)
    questions_data = []
    if unmastered:
        qresult = generate_questions(unmastered, task_id=ctx.task_id)
        questions_data = qresult.get("questions", [])
    ctx.questions_data = questions_data

    if questions_data:
        ctx.progress("生成练习题卷", 85)
        ex_html = render_exercise_sheet(
            student_name=ctx.student["name"],
            questions=questions_data,
            week_start=ctx.week_start,
        )
        ex_dir = os.path.join(UPLOAD_DIR, str(ctx.student_id), "exercise_pdf")
        os.makedirs(ex_dir, exist_ok=True)
        ex_filename = f"exercise_{ctx.week_start}_{uuid.uuid4().hex[:8]}.html"
        ex_path = os.path.join(ex_dir, ex_filename)
        with open(ex_path, "w", encoding="utf-8") as f:
            f.write(ex_html)
        ctx.exercise_file_id = db.add_file(
            student_id=ctx.student_id, uploader_role="teacher",
            file_type="exercise_pdf", filename=ex_filename,
            original_filename=f"练习题-{ctx.student['name']}-{ctx.week_start}.html",
            week_start=ctx.week_start, file_size=os.path.getsize(ex_path),
            mime_type="text/html", db_path=ctx.db_path,
        )
    db.update_weekly_record(ctx.student_id, ctx.week_start, kind=ctx.kind,
                            exercises_sent=1 if questions_data else 0,
                            db_path=ctx.db_path)


def node_weekly_report(ctx: Ctx):
    """家长周报（成长叙事 + 三方行动方案）。手动补发/周六自动共用。"""
    ctx.progress("加载学情数据", 20)
    week_end = (date.fromisoformat(ctx.week_start) + timedelta(days=6)).isoformat()
    weekly_stats = db.get_weekly_stats(
        ctx.student_id, ctx.week_start, week_end, db_path=ctx.db_path)
    comparison = db.get_weekly_comparison(
        ctx.student_id, ctx.week_start, weeks=4, db_path=ctx.db_path)
    profile = db.get_student_profile(ctx.student_id, db_path=ctx.db_path)
    learning_style_detail = (profile or {}).get("learning_style_detail") or None

    weak_areas = weekly_stats.get("weak_areas") or []
    top_weak = weak_areas[0].get("knowledge_point", "") if weak_areas else ""
    second_weak = weak_areas[1].get("knowledge_point", "") if len(weak_areas) > 1 else ""
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

    ctx.progress("生成周报", 60)
    # 错因跨周对比（"卡点变化"叙事；report_only 重跑时只读历史，不重新分析）
    cause_trend = None
    try:
        cur_cause = db.get_cause_profile_history(
            ctx.student_id, week_start=ctx.week_start, db_path=ctx.db_path)
        prev_cause = db.get_cause_profile_history(
            ctx.student_id, before=ctx.week_start, db_path=ctx.db_path)
        if cur_cause and prev_cause:
            cause_trend = build_cause_trend(cur_cause, prev_cause)
    except Exception:
        cause_trend = None

    wr_html = render_weekly_report(
        student_name=ctx.student["name"],
        week_start=ctx.week_start,
        week_end=week_end,
        new_mistakes=weekly_stats.get("new_mistakes_count", 0),
        mastered_count=weekly_stats.get("mastered_count", 0),
        weak_areas=weak_areas,
        ai_clinic="",
        comparison=comparison,
        learning_style_detail=learning_style_detail,
        action_plan=action_plan,
        cause_trend=cause_trend,
    )
    wr_dir = os.path.join(UPLOAD_DIR, str(ctx.student_id), "weekly_pdf")
    os.makedirs(wr_dir, exist_ok=True)
    wr_filename = f"weekly_{ctx.week_start}_{uuid.uuid4().hex[:8]}.html"
    wr_path = os.path.join(wr_dir, wr_filename)
    with open(wr_path, "w", encoding="utf-8") as f:
        f.write(wr_html)
    ctx.weekly_report_file_id = db.add_file(
        student_id=ctx.student_id, uploader_role="teacher",
        file_type="weekly_pdf", filename=wr_filename,
        original_filename=f"家长周报-{ctx.student['name']}-{ctx.week_start}.html",
        week_start=ctx.week_start, file_size=os.path.getsize(wr_path),
        mime_type="text/html", db_path=ctx.db_path,
    )
    db.update_weekly_record(ctx.student_id, ctx.week_start, kind=ctx.kind,
                            report_sent=1, db_path=ctx.db_path)
    try:
        db.record_check_in(ctx.student_id, check_in_date=ctx.week_start,
                           content="生成周度学习报告",
                           duration_minutes=5, source="auto",
                           db_path=ctx.db_path)
    except Exception:
        log.warning("周报打卡记录失败 student=%s", ctx.student_id, exc_info=True)
