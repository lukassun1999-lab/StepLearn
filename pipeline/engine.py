#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""声明式链执行器：一条流水线，多个恢复点（见 核心链路架构设计.md §4）。

- 分析主链固定为 ocr → analyze → plan → analysis_report → exercises；
  weekly_report 为独立节点（手动补发 / 周六条件自动）。
- 外部 API 的 stage 参数（full/grade_only/analysis_only）映射为链的
  起始恢复点，链从该点一路执行到链尾——不再有「自动链第二个任务」。
- 断点续跑：僵尸任务复活时按 Cycle 状态跳到下一未完成节点；
  OCR 文本从 input_data._ocr_text 恢复，免重复识别。
"""

import db
from domain import cycle as cycle_mod
from pipeline import stages

# ── 链定义 ──
WEEKLY_CHAIN = ["ocr", "analyze", "plan", "analysis_report", "exercises"]
DIAGNOSTIC_CHAIN = ["ocr", "analyze", "plan", "analysis_report"]

NODE_FUNCS = {
    "ocr": stages.node_ocr,
    "analyze": stages.node_analyze,
    "plan": stages.node_plan,
    "analysis_report": stages.node_analysis_report,
    "exercises": stages.node_exercises,
    "weekly_report": stages.node_weekly_report,
}

# 节点 → 完成后 Cycle 到达的状态
NODE_DONE_STATE = {
    "ocr": "ocr_done",
    "analyze": "graded",
    "plan": "analyzed",
    "analysis_report": "report_ready",
    "exercises": "exercised",
    "weekly_report": "reported",
}

# 恢复点：外部 stage 参数 → 链起始节点
START_NODES = {
    "full": "ocr",
    "grade_only": "ocr",
    "analysis_only": "plan",
}

# 断点续跑：Cycle 状态 → 下一个可执行节点
_RESUME_NEXT = {
    "ocr_done": "analyze",
    "graded": "plan",
    "analyzed": "analysis_report",
    "report_ready": "exercises",
}

# 这些状态表示分析主链已跑完（避免僵尸复活时重复执行整条链）
_CHAIN_DONE_STATES = ("exercised", "reported")


def run_chain(task: dict, db_path: str, kind: str,
              start_param: str = "full") -> dict:
    """执行链并返回 output_data。

    Args:
        task: ai_tasks 行（含已解析的 input_data）。
        kind: cycle_mod.KIND_DIAGNOSTIC | KIND_WEEKLY。
        start_param: 恢复点参数（仅 weekly 有效）。
    """
    ctx = stages.Ctx(task, db_path)
    ctx.kind = kind

    if kind == cycle_mod.KIND_DIAGNOSTIC:
        chain, start_node = DIAGNOSTIC_CHAIN, "ocr"
    else:
        chain = WEEKLY_CHAIN
        start_node = START_NODES.get(start_param, "ocr")
    ctx.start_node = start_node

    ctx.student = db.get_student(ctx.student_id, db_path)
    if not ctx.student:
        raise ValueError(f"Student {ctx.student_id} not found")

    cycle = cycle_mod.get_or_create_cycle(
        ctx.student_id, ctx.week_start, kind, db_path)
    cycle_mod.attach_task(ctx.task_id, cycle["id"], db_path)
    if ctx.has_files():
        cycle_mod.advance_cycle(cycle["id"], "paper_received", db_path)

    # ── 断点续跑决策 ──
    stage_now = (cycle.get("stage") or "created")
    # 仅僵尸任务复活（_recover_tasks 标记 _auto_resumed）且链已跑完时，
    # 重建输出而不重复执行；用户主动重跑（新试卷/再次矩阵分析）照常执行。
    auto_resumed = bool(ctx.input_data.get("_auto_resumed"))
    chain_finished = (
        (kind == cycle_mod.KIND_WEEKLY and stage_now in _CHAIN_DONE_STATES)
        or (kind == cycle_mod.KIND_DIAGNOSTIC and stage_now == "report_ready")
    )
    if chain_finished and auto_resumed:
        return _reconstruct_output(ctx, kind)

    resume_node = _RESUME_NEXT.get(stage_now)
    if resume_node and resume_node in chain:
        if chain.index(resume_node) > chain.index(start_node):
            # analyze 节点需要 OCR 文本；丢失则退回从恢复点重跑
            if resume_node == "analyze" and not ctx.input_data.get("_ocr_text"):
                resume_node = None
            else:
                start_node = resume_node
                ctx.start_node = resume_node
                ctx.ocr_text = ctx.input_data.get("_ocr_text") or ctx.ocr_text

    # ── 顺序执行链节点，每节点落库一次 Cycle 状态 ──
    for node in chain[chain.index(start_node):]:
        NODE_FUNCS[node](ctx)
        cycle_mod.advance_cycle(cycle["id"], NODE_DONE_STATE[node], db_path)

    return ctx.build_output()


def run_weekly_report_node(task: dict, db_path: str) -> dict:
    """report_only：独立周报节点（手动补发 / 周六条件自动共用）。"""
    ctx = stages.Ctx(task, db_path)
    ctx.kind = cycle_mod.KIND_WEEKLY
    ctx.start_node = "weekly_report"
    ctx.student = db.get_student(ctx.student_id, db_path)
    if not ctx.student:
        raise ValueError(f"Student {ctx.student_id} not found")
    cycle = cycle_mod.get_or_create_cycle(
        ctx.student_id, ctx.week_start, cycle_mod.KIND_WEEKLY, db_path)
    cycle_mod.attach_task(ctx.task_id, cycle["id"], db_path)
    stages.node_weekly_report(ctx)
    cycle_mod.advance_cycle(cycle["id"], "reported", db_path)
    return {
        "needs_review": False,
        "student_id": ctx.student_id,
        "weekly_report_file_id": ctx.weekly_report_file_id,
        "stage": "report_done",
    }


def _reconstruct_output(ctx: stages.Ctx, kind: str) -> dict:
    """链已完成时的输出重建：从 files 表取本周产物（尽力而为）。"""
    conn = db.get_connection(ctx.db_path)

    def _latest(file_type):
        row = conn.execute("""
            SELECT id FROM files
            WHERE student_id = ? AND week_start = ? AND file_type = ?
            ORDER BY id DESC LIMIT 1
        """, [ctx.student_id, ctx.week_start, file_type]).fetchone()
        return row["id"] if row else None

    report_id = _latest("report_pdf")
    exercise_id = _latest("exercise_pdf")
    conn.close()

    if kind == cycle_mod.KIND_DIAGNOSTIC:
        return {
            "needs_review": False,
            "student_id": ctx.student_id,
            "report_file_id": report_id,
            "stage": "reconstructed",
        }
    return {
        "needs_review": False,
        "student_id": ctx.student_id,
        "report_file_id": report_id,
        "exercise_file_id": exercise_id,
        "stage": "exercises_ready",
        "reconstructed": True,
    }
