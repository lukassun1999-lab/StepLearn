#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cycle（学习周期）状态机 —— 核心链路的主干。

见 核心链路架构设计.md §3。

一个 Cycle 实例 = 一个学生 × 一个周期起点 × 一种类型：
  kind = 'diagnostic'  入学诊断（周期 0）
  kind = 'weekly'      周循环

状态线性推进，只进不退；advance 对回退/重复状态幂等（no-op），
以支持流水线节点重跑与断点续跑。

物理存储：weekly_records 表（P1 迁移后增加 kind/stage 列）。
"""

from datetime import datetime
from typing import Any, Dict, Optional

import db

KIND_WEEKLY = "weekly"
KIND_DIAGNOSTIC = "diagnostic"

# 状态机全部状态（线性顺序即推进顺序）
STATES = [
    "created",          # 周期已建，无照片
    "paper_received",   # 已收到试卷照片
    "ocr_done",         # OCR 完成
    "graded",           # 错题已入库（错题本资产更新点）
    "analyzed",         # 薄弱矩阵 + 学习方案已更新
    "report_ready",     # 分析报告已产出
    "exercised",        # 针对性练习已就绪
    "reported",         # 周报已产出（周循环终态）
]
_STATE_INDEX = {s: i for i, s in enumerate(STATES)}


def state_index(state: Optional[str]) -> int:
    """状态在状态机中的序号；未知状态按 created(0) 处理。"""
    return _STATE_INDEX.get(state or "created", 0)


def _resolve_db_path(db_path: Optional[str]) -> str:
    """惰性解析 DB 路径：不在模块导入期冻结 DB_PATH（测试环境依赖此行为）。"""
    return db_path or db.DB_PATH


def get_or_create_cycle(student_id: int, week_start: str = None,
                        kind: str = KIND_WEEKLY,
                        db_path: str = None) -> Dict[str, Any]:
    """获取或创建 Cycle（幂等）。"""
    if week_start is None:
        week_start = db.get_week_start()
    return db.get_or_create_weekly_record(
        student_id, week_start, kind, _resolve_db_path(db_path))


def get_cycle(student_id: int, week_start: str, kind: str = KIND_WEEKLY,
              db_path: str = None) -> Optional[Dict[str, Any]]:
    """查询 Cycle，不存在返回 None。"""
    conn = db.get_connection(_resolve_db_path(db_path))
    row = conn.execute("""
        SELECT * FROM weekly_records
        WHERE student_id = ? AND week_start = ? AND kind = ?
    """, [student_id, week_start, kind]).fetchone()
    conn.close()
    return dict(row) if row else None


def get_cycle_by_id(cycle_id: int,
                    db_path: str = None) -> Optional[Dict[str, Any]]:
    conn = db.get_connection(_resolve_db_path(db_path))
    row = conn.execute(
        "SELECT * FROM weekly_records WHERE id = ?", [cycle_id]
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def advance_cycle(cycle_id: int, new_stage: str,
                  db_path: str = None) -> str:
    """推进状态机。只进不退：new_stage 不高于当前状态时为幂等 no-op。

    Returns:
        推进后的实际状态。
    """
    if new_stage not in _STATE_INDEX:
        raise ValueError(f"Unknown cycle stage: {new_stage}")
    conn = db.get_connection(_resolve_db_path(db_path))
    try:
        row = conn.execute(
            "SELECT stage FROM weekly_records WHERE id = ?", [cycle_id]
        ).fetchone()
        if row is None:
            raise ValueError(f"Cycle {cycle_id} not found")
        current = row["stage"] or "created"
        if _STATE_INDEX[new_stage] <= _STATE_INDEX[current]:
            return current
        conn.execute(
            "UPDATE weekly_records SET stage = ?, updated_at = ? WHERE id = ?",
            [new_stage, db._now_iso(), cycle_id],
        )
        conn.commit()
        return new_stage
    finally:
        conn.close()


def attach_task(task_id: int, cycle_id: int, db_path: str = None) -> None:
    """把 AI 任务挂到 Cycle 上（不再有孤儿任务）。"""
    conn = db.get_connection(_resolve_db_path(db_path))
    conn.execute(
        "UPDATE ai_tasks SET cycle_id = ? WHERE id = ?", [cycle_id, task_id]
    )
    conn.commit()
    conn.close()


def reached(cycle: Dict[str, Any], state: str) -> bool:
    """Cycle 是否已达到（不低于）某状态。"""
    return state_index(cycle.get("stage")) >= state_index(state)


# ═══════════════════════════════════════════════════
# 运营端展示辅助（P2-11 链路视角）
# ═══════════════════════════════════════════════════

STAGE_LABELS = {
    "created": "未开始",
    "paper_received": "已收卷",
    "ocr_done": "OCR完成",
    "graded": "错题入库",
    "analyzed": "方案更新",
    "report_ready": "报告就绪",
    "exercised": "练习就绪",
    "reported": "周报已发",
}

# 中间态：链已启动但未到稳态。P1 起一次任务跑完整链，
# 这些状态正常只存在几分钟；长时间停留即视为卡住。
_INTERMEDIATE_STATES = (
    "paper_received", "ocr_done", "graded", "analyzed", "report_ready")


def stage_label(stage: Optional[str]) -> str:
    """状态机当前态的中文标签。"""
    return STAGE_LABELS.get(stage or "created", stage or "created")


def is_stuck(cycle: Optional[Dict[str, Any]], stuck_hours: float = 48.0) -> bool:
    """Cycle 是否卡住：处于中间态且超过 stuck_hours 无任何推进。"""
    stage = (cycle or {}).get("stage") or "created"
    if stage not in _INTERMEDIATE_STATES:
        return False
    updated = (cycle or {}).get("updated_at")
    if not updated:
        return False
    try:
        ts = datetime.fromisoformat(str(updated).replace(" ", "T")[:19])
    except (ValueError, TypeError):
        return False
    return (datetime.now() - ts).total_seconds() > stuck_hours * 3600
