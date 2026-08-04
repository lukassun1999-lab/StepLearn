# -*- coding: utf-8 -*-
"""Cycle 状态机单测（P1-2，核心链路架构设计.md §3）。

注意：遵循 conftest 约定，db / domain 模块必须在测试函数内惰性导入，
否则 DB_PATH 会在 WEEKEND_ENGLISH_DB 设置前绑定到生产 data.db。
"""

import pytest


def test_states_linear_order(test_db_path):
    # 依赖 test_db_path 确保 domain/db 首次导入发生在测试库环境就绪后
    from domain import cycle

    assert cycle.STATES[0] == "created"
    assert cycle.STATES[-1] == "reported"
    assert cycle.state_index("graded") < cycle.state_index("exercised")
    assert cycle.state_index(None) == 0
    assert cycle.state_index("bogus-state") == 0


def test_get_or_create_cycle_idempotent(test_db_path, sample_student):
    from domain import cycle

    c1 = cycle.get_or_create_cycle(sample_student, "2026-08-03", db_path=test_db_path)
    c2 = cycle.get_or_create_cycle(sample_student, "2026-08-03", db_path=test_db_path)
    assert c1["id"] == c2["id"]
    assert c1["kind"] == cycle.KIND_WEEKLY
    assert c1["stage"] == "created"


def test_diagnostic_and_weekly_coexist_same_week(test_db_path, sample_student):
    from domain import cycle

    wk = cycle.get_or_create_cycle(
        sample_student, "2026-08-03", cycle.KIND_WEEKLY, test_db_path)
    dg = cycle.get_or_create_cycle(
        sample_student, "2026-08-03", cycle.KIND_DIAGNOSTIC, test_db_path)
    assert wk["id"] != dg["id"]
    found = cycle.get_cycle(
        sample_student, "2026-08-03", cycle.KIND_DIAGNOSTIC, test_db_path)
    assert found is not None and found["id"] == dg["id"]


def test_get_cycle_missing_returns_none(test_db_path, sample_student):
    from domain import cycle

    assert cycle.get_cycle(sample_student, "2030-01-07", db_path=test_db_path) is None


def test_advance_monotonic_and_idempotent(test_db_path, sample_student):
    from domain import cycle

    c = cycle.get_or_create_cycle(sample_student, "2026-08-03", db_path=test_db_path)
    # 前进
    assert cycle.advance_cycle(c["id"], "graded", db_path=test_db_path) == "graded"
    # 回退是幂等 no-op，不报错
    assert cycle.advance_cycle(c["id"], "ocr_done", db_path=test_db_path) == "graded"
    # 重复是幂等 no-op
    assert cycle.advance_cycle(c["id"], "graded", db_path=test_db_path) == "graded"
    # 跨级前进
    assert cycle.advance_cycle(c["id"], "reported", db_path=test_db_path) == "reported"
    got = cycle.get_cycle_by_id(c["id"], test_db_path)
    assert got["stage"] == "reported"
    assert got["updated_at"]
    assert cycle.reached(got, "graded") is True
    assert cycle.reached(got, "created") is True


def test_advance_unknown_stage_raises(test_db_path, sample_student):
    from domain import cycle

    c = cycle.get_or_create_cycle(sample_student, "2026-08-03", db_path=test_db_path)
    with pytest.raises(ValueError):
        cycle.advance_cycle(c["id"], "not-a-stage", db_path=test_db_path)


def test_advance_missing_cycle_raises(test_db_path):
    from domain import cycle

    with pytest.raises(ValueError):
        cycle.advance_cycle(999999, "graded", db_path=test_db_path)


def test_attach_task_links_cycle(test_db_path, sample_student):
    import db
    from domain import cycle

    c = cycle.get_or_create_cycle(sample_student, "2026-08-03", db_path=test_db_path)
    tid = db.create_task(sample_student, "weekly", {"stage": "grade_only"},
                         db_path=test_db_path)
    cycle.attach_task(tid, c["id"], db_path=test_db_path)
    task = db.get_task(tid, test_db_path)
    assert task["cycle_id"] == c["id"]


def test_stage_labels():
    from domain import cycle

    assert cycle.stage_label(None) == "未开始"
    assert cycle.stage_label("created") == "未开始"
    assert cycle.stage_label("graded") == "错题入库"
    assert cycle.stage_label("exercised") == "练习就绪"
    assert cycle.stage_label("reported") == "周报已发"
    # 未知状态原样返回（不崩溃）
    assert cycle.stage_label("weird") == "weird"


def test_stuck_detection():
    from datetime import datetime
    from domain import cycle

    old = "2020-01-01 00:00:00"
    now = datetime.now().isoformat(sep=" ")
    # 稳态（created/exercised/reported）永不判卡住
    assert cycle.is_stuck({"stage": "created", "updated_at": old}) is False
    assert cycle.is_stuck({"stage": "exercised", "updated_at": old}) is False
    assert cycle.is_stuck({"stage": "reported", "updated_at": old}) is False
    # 中间态 + 久远时间 → 卡住
    assert cycle.is_stuck({"stage": "graded", "updated_at": old}) is True
    assert cycle.is_stuck({"stage": "paper_received", "updated_at": old}) is True
    # 中间态 + 刚更新 → 未卡住
    assert cycle.is_stuck({"stage": "graded", "updated_at": now}) is False
    # 缺 updated_at → 不判
    assert cycle.is_stuck({"stage": "graded"}) is False
    assert cycle.is_stuck(None) is False
