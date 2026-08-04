#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""入学诊断 + 周循环统一流水线入口。

P1 起替代 onboarding_pipeline.py 与 weekly_pipeline.py：
两者共用同一条声明式链（pipeline/engine.py），按 Cycle 类型与
恢复点参数路由（核心链路架构设计.md §4）。
"""

import json

from domain import cycle as cycle_mod
from pipeline import engine, snapshots


def _stage_of(task: dict) -> str:
    input_data = task.get("input_data") or {}
    if isinstance(input_data, str):
        try:
            input_data = json.loads(input_data)
        except Exception:
            input_data = {}
    return input_data.get("stage", "full")


def run_onboarding(task: dict, db_path: str) -> dict:
    """入学诊断 = diagnostic 周期，完整分析链。"""
    return engine.run_chain(task, db_path, kind=cycle_mod.KIND_DIAGNOSTIC)


def run_weekly(task: dict, db_path: str) -> dict:
    """周循环：stage 参数路由到链恢复点 / 独立子链 / 快照任务。"""
    stage = _stage_of(task)

    if stage == "grade_exercises":
        return snapshots.run_grade_exercises(task, db_path)
    if stage == "weekly_mistake_book":
        return snapshots.run_weekly_mistake_book(task, db_path)
    if stage == "monthly_summary":
        return snapshots.run_monthly_summary(task, db_path)
    if stage == "report_only":
        return engine.run_weekly_report_node(task, db_path)
    if stage in engine.START_NODES:
        return engine.run_chain(
            task, db_path, kind=cycle_mod.KIND_WEEKLY, start_param=stage)
    raise ValueError(f"Unknown weekly stage: {stage}")


def register():
    from pipeline_worker import register_handler
    register_handler("onboarding", run_onboarding)
    register_handler("weekly", run_weekly)


if __name__ == "__main__":
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    print("cycle_pipeline.py OK (run via app.py)")
