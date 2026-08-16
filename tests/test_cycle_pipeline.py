# -*- coding: utf-8 -*-
"""P1 验收测试：声明式链 / 恢复点 / 断点续跑 / 条件周报 / 额度闸门。

全部在 demo 模式下运行（不产生真实 LLM 调用）。
遵循 conftest 约定：db/domain/pipeline 均在测试函数内惰性导入。
"""

import os

import pytest


@pytest.fixture
def env(test_db_path, demo_mode, monkeypatch, tmp_path):
    """隔离 uploads 目录（不污染项目 uploads/），返回临时上传根目录。"""
    from pipeline import stages
    upload_dir = str(tmp_path / "uploads")
    monkeypatch.setattr(stages, "UPLOAD_DIR", upload_dir)
    return upload_dir


def _make_student_and_file(upload_dir, plan="unlimited"):
    """建学生（自动订阅）+ 占位试卷文件，返回 (db, sid, file_id, week_start)。"""
    import db
    sid = db.create_student({
        "name": "链路测试", "grade": "高二", "school_type": "住校",
        "english_score": 100, "target_score": 120, "plan": plan,
    })
    week_start = db.get_week_start()
    d = os.path.join(upload_dir, str(sid), "test_paper")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "fake.jpg"), "wb") as f:
        f.write(b"\xff\xd8\xff\xd9")  # demo 模式不读取图片内容
    file_id = db.add_file(
        student_id=sid, uploader_role="parent", file_type="test_paper",
        filename="fake.jpg", original_filename="fake.jpg",
        week_start=week_start, file_size=4, mime_type="image/jpeg")
    return db, sid, file_id, week_start


# ═══════════════════════════════════════════════════
# 1. 家长核心链路：grade_only 一次任务跑完整条分析主链（P1-5 验收）
# ═══════════════════════════════════════════════════

def test_grade_only_runs_full_chain_in_one_task(env):
    db, sid, file_id, week_start = _make_student_and_file(env)
    from domain import cycle as cycle_mod
    from pipeline import cycle_pipeline

    task_id = db.create_task(sid, "weekly", {
        "file_ids": [file_id], "stage": "grade_only", "quota_charged": True})
    task = db.get_task(task_id, db.DB_PATH)
    output = cycle_pipeline.run_weekly(task, db.DB_PATH)

    # 一次任务产出全部：错题 + 分析报告 + 练习题
    assert output["mistakes_count"] == 5          # demo 数据 5 道错题
    assert output["report_file_id"] is not None
    assert output["exercise_file_id"] is not None
    assert output["questions_count"] > 0
    assert output["stage"] == "exercises_ready"
    assert output["needs_review"] is False        # D1：审核闸门移除

    # Cycle 状态推进到 exercised
    cyc = cycle_mod.get_cycle(sid, week_start, cycle_mod.KIND_WEEKLY)
    assert cyc is not None and cyc["stage"] == "exercised"

    # 没有「自动链的第二个任务」：本学生仅 1 个任务
    conn = db.get_connection(db.DB_PATH)
    n = conn.execute("SELECT COUNT(*) FROM ai_tasks WHERE student_id=?", [sid]).fetchone()[0]
    conn.close()
    assert n == 1


def test_onboarding_diagnostic_chain(env):
    db, sid, file_id, week_start = _make_student_and_file(env)
    from domain import cycle as cycle_mod
    from pipeline import cycle_pipeline

    task_id = db.create_task(sid, "onboarding", {"file_ids": [file_id]})
    task = db.get_task(task_id, db.DB_PATH)
    output = cycle_pipeline.run_onboarding(task, db.DB_PATH)

    assert output["report_file_id"] is not None
    assert output["mistakes_count"] == 5
    assert output["weak_points_count"] >= 0
    assert output["needs_review"] is False

    # diagnostic 周期独立于 weekly 周期存在
    cyc = cycle_mod.get_cycle(sid, week_start, cycle_mod.KIND_DIAGNOSTIC)
    assert cyc is not None and cyc["stage"] == "report_ready"
    assert cycle_mod.get_cycle(sid, week_start, cycle_mod.KIND_WEEKLY) is None


# ═══════════════════════════════════════════════════
# 2. 恢复点与断点续跑
# ═══════════════════════════════════════════════════

def test_analysis_only_recovery_point(env):
    db, sid, file_id, week_start = _make_student_and_file(env)
    from pipeline import cycle_pipeline

    # 先跑批改（grade_only）
    t1 = db.create_task(sid, "weekly", {"file_ids": [file_id], "stage": "grade_only"})
    cycle_pipeline.run_weekly(db.get_task(t1, db.DB_PATH), db.DB_PATH)

    # analysis_only 恢复点：不上传文件，从 plan 节点继续
    t2 = db.create_task(sid, "weekly", {"stage": "analysis_only"})
    output = cycle_pipeline.run_weekly(db.get_task(t2, db.DB_PATH), db.DB_PATH)
    assert output["stage"] == "analysis_done"
    assert output["report_file_id"] is not None


def test_completed_cycle_reconstructs_instead_of_rerun(env):
    db, sid, file_id, week_start = _make_student_and_file(env)
    from pipeline import cycle_pipeline

    t1 = db.create_task(sid, "weekly", {"file_ids": [file_id], "stage": "grade_only"})
    out1 = cycle_pipeline.run_weekly(db.get_task(t1, db.DB_PATH), db.DB_PATH)

    # 僵尸复活场景（_recover_tasks 会写入 _auto_resumed 标记）：
    # 链已完成（exercised），不应重复执行
    t2 = db.create_task(sid, "weekly", {
        "file_ids": [file_id], "stage": "grade_only", "_auto_resumed": 1})
    out2 = cycle_pipeline.run_weekly(db.get_task(t2, db.DB_PATH), db.DB_PATH)
    assert out2.get("reconstructed") is True
    assert out2["report_file_id"] == out1["report_file_id"]

    # 错题没有被重复入库（仍为 demo 的 5 道）
    conn = db.get_connection(db.DB_PATH)
    n = conn.execute("SELECT COUNT(*) FROM mistakes WHERE student_id=?", [sid]).fetchone()[0]
    conn.close()
    assert n == 5

    # 对照：用户主动重跑（无 _auto_resumed）照常执行，错题会新增
    t3 = db.create_task(sid, "weekly", {"file_ids": [file_id], "stage": "grade_only"})
    out3 = cycle_pipeline.run_weekly(db.get_task(t3, db.DB_PATH), db.DB_PATH)
    assert out3["mistakes_count"] == 5
    conn = db.get_connection(db.DB_PATH)
    n2 = conn.execute("SELECT COUNT(*) FROM mistakes WHERE student_id=?", [sid]).fetchone()[0]
    conn.close()
    assert n2 == 10


def test_start_node_mapping_and_resume_table():
    from pipeline import engine
    assert engine.START_NODES == {"full": "ocr", "grade_only": "ocr",
                                  "analysis_only": "plan"}
    # 恢复表必须指向链内节点，且状态顺序递增
    from domain import cycle as cycle_mod
    prev = -1
    for state, node in engine._RESUME_NEXT.items():
        assert node in engine.WEEKLY_CHAIN
        idx = cycle_mod.state_index(state)
        assert idx > prev
        prev = idx


# ═══════════════════════════════════════════════════
# 2.5 analyze 幂等：同任务重放不翻倍（2026-08 第 2 周提交 3）
# ═══════════════════════════════════════════════════

def test_analyze_replay_same_task_no_duplicates(env):
    """崩溃窗口 [错题已入库, advance_cycle('graded') 未落] 内僵尸复活：
    同一任务重放 analyze，先清理上次残留再重建——错题数不变。"""
    db, sid, file_id, week_start = _make_student_and_file(env)
    from domain import cycle as cycle_mod
    from pipeline import cycle_pipeline

    t1 = db.create_task(sid, "weekly", {"file_ids": [file_id], "stage": "grade_only"})
    task = db.get_task(t1, db.DB_PATH)
    cycle_pipeline.run_weekly(task, db.DB_PATH)

    # 模拟崩溃：回退 Cycle 状态到 ocr_done（analyze 完成但 graded 未落），
    # 任务回到 pending 后由恢复逻辑重跑（_ocr_text 已持久化，免重识别）
    conn = db.get_connection(db.DB_PATH)
    conn.execute("UPDATE weekly_records SET stage='ocr_done' WHERE student_id=? AND week_start=?",
                 [sid, week_start])
    conn.close()
    db.update_task(t1, {"status": "pending"}, db.DB_PATH)

    output = cycle_pipeline.run_weekly(db.get_task(t1, db.DB_PATH), db.DB_PATH)

    # 错题不翻倍：仍是 demo 的 5 道（同任务重放已清理重建）
    conn = db.get_connection(db.DB_PATH)
    n = conn.execute("SELECT COUNT(*) FROM mistakes WHERE student_id=?", [sid]).fetchone()[0]
    sessions = conn.execute(
        "SELECT COUNT(*) FROM practice_sessions WHERE student_id=?", [sid]).fetchone()[0]
    conn.close()
    assert n == 5
    assert sessions == 1
    assert output["mistakes_count"] == 5


def test_purge_task_mistakes_cleans_children(test_db_path, sample_student):
    """purge_task_mistakes：删错题连带练习记录、置空题库引用、删场次。"""
    import db
    sid = sample_student
    p = dict(db_path=db.DB_PATH)

    tid = db.create_task(sid, "weekly", {"stage": "grade_only"})
    mid = db.add_mistake(sid, question="q", correct_answer="A",
                         source_task_id=tid, **p)
    conn = db.get_connection(db.DB_PATH)
    conn.execute("INSERT INTO practice_records (mistake_id, user_answer, is_correct) "
                 "VALUES (?, 'A', 1)", [mid])
    conn.execute("INSERT INTO questions (question_text, correct_answer, enabled, source_mistake_id) "
                 "VALUES ('q', 'A', 1, ?)", [mid])
    qid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute("INSERT INTO practice_sessions (student_id, exam_name, source_task_id) "
                 "VALUES (?, 'e', ?)", [sid, tid])
    conn.commit()
    conn.close()

    deleted = db.purge_task_mistakes(tid, db_path=db.DB_PATH)
    assert deleted == 1

    conn = db.get_connection(db.DB_PATH)
    assert conn.execute("SELECT COUNT(*) FROM mistakes WHERE id=?", [mid]).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM practice_records WHERE mistake_id=?",
                        [mid]).fetchone()[0] == 0
    # 题库题保留但引用置空
    assert conn.execute("SELECT COUNT(*) FROM questions WHERE id=? AND source_mistake_id IS NULL",
                        [qid]).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM practice_sessions WHERE source_task_id=?",
                        [tid]).fetchone()[0] == 0
    conn.close()


def test_analyze_failure_purges_partial_inserts(env, monkeypatch):
    """插入中途异常：不留半成品错题（清理后重抛，任务标记失败）。"""
    db, sid, file_id, week_start = _make_student_and_file(env)
    from pipeline import cycle_pipeline

    t1 = db.create_task(sid, "weekly", {"file_ids": [file_id], "stage": "grade_only"})

    real_add = db.add_mistake
    calls = {"n": 0}

    def flaky_add(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:  # 第 3 条插入时崩溃
            raise sqlite3.OperationalError("disk I/O error (simulated)")
        return real_add(*args, **kwargs)

    import sqlite3
    monkeypatch.setattr(db, "add_mistake", flaky_add)

    import pytest
    with pytest.raises(sqlite3.OperationalError):
        cycle_pipeline.run_weekly(db.get_task(t1, db.DB_PATH), db.DB_PATH)

    # 半成品已清理：0 条错题、0 个场次
    conn = db.get_connection(db.DB_PATH)
    n = conn.execute("SELECT COUNT(*) FROM mistakes WHERE student_id=?", [sid]).fetchone()[0]
    s = conn.execute("SELECT COUNT(*) FROM practice_sessions WHERE student_id=?", [sid]).fetchone()[0]
    conn.close()
    assert n == 0
    assert s == 0


# ═══════════════════════════════════════════════════
# 3. 周报独立节点 + 周六条件式触发（D3 / P1-7）
# ═══════════════════════════════════════════════════

def test_report_only_generates_weekly_report(env):
    db, sid, file_id, week_start = _make_student_and_file(env)
    from domain import cycle as cycle_mod
    from pipeline import cycle_pipeline

    # 先有分析数据
    t1 = db.create_task(sid, "weekly", {"file_ids": [file_id], "stage": "grade_only"})
    cycle_pipeline.run_weekly(db.get_task(t1, db.DB_PATH), db.DB_PATH)

    # report_only
    t2 = db.create_task(sid, "weekly", {"stage": "report_only"})
    output = cycle_pipeline.run_weekly(db.get_task(t2, db.DB_PATH), db.DB_PATH)
    assert output["stage"] == "report_done"
    assert output["weekly_report_file_id"] is not None

    cyc = cycle_mod.get_cycle(sid, week_start, cycle_mod.KIND_WEEKLY)
    assert cyc["stage"] == "reported"


def test_saturday_weekly_report_conditional(env, monkeypatch):
    # 注意：test_db_path 为会话级共享库，其他测试的学生也会命中触发条件，
    # 因此断言只针对本测试学生的 report_only 任务数量变化。
    db, sid, file_id, week_start = _make_student_and_file(env)
    from pipeline import cycle_pipeline, scheduler

    monkeypatch.setattr(scheduler, "_enqueue_fn", lambda task_id, dbp: None)

    def _report_task_count():
        conn = db.get_connection(db.DB_PATH)
        n = conn.execute(
            "SELECT COUNT(*) FROM ai_tasks WHERE student_id=? AND task_type='weekly' "
            "AND input_data LIKE '%report_only%' AND status NOT IN ('failed','cancelled')",
            [sid]).fetchone()[0]
        conn.close()
        return n

    # 无分析数据 → 不为本学生触发
    scheduler._trigger_weekly_reports(db.DB_PATH)
    assert _report_task_count() == 0

    # 跑一次批改 → paper_analyzed=1 → 触发 1 个周报任务
    t1 = db.create_task(sid, "weekly", {"file_ids": [file_id], "stage": "grade_only"})
    cycle_pipeline.run_weekly(db.get_task(t1, db.DB_PATH), db.DB_PATH)
    scheduler._trigger_weekly_reports(db.DB_PATH)
    assert _report_task_count() == 1

    # 当日去重：已有非失败的 report_only 任务 → 不再重复创建
    scheduler._trigger_weekly_reports(db.DB_PATH)
    assert _report_task_count() == 1


# ═══════════════════════════════════════════════════
# 5. worker 处理路径：单任务闭环（P1-5：确认自动链 hack 已移除）
# ═══════════════════════════════════════════════════

def test_worker_process_task_single_task_no_chain(env):
    db, sid, file_id, week_start = _make_student_and_file(env)
    import pipeline_worker

    # 注册真实 handler（测试隔离：用后恢复）
    original = dict(pipeline_worker._PIPELINE_HANDLERS)
    try:
        from pipeline import cycle_pipeline
        cycle_pipeline.register()

        task_id = db.create_task(sid, "weekly", {
            "file_ids": [file_id], "stage": "grade_only", "quota_charged": True})
        task = db.get_task(task_id, db.DB_PATH)
        pipeline_worker._process_task(task, db.DB_PATH)

        done = db.get_task(task_id, db.DB_PATH)
        assert done["status"] == "done"
        assert done["needs_review"] == 0
        assert done["output_data"]["exercise_file_id"] is not None
        assert done["output_data"]["report_file_id"] is not None
        assert done["output_data"]["questions_count"] > 0

        # 关键验收：没有自动链出的第二个任务
        conn = db.get_connection(db.DB_PATH)
        n = conn.execute(
            "SELECT COUNT(*) FROM ai_tasks WHERE student_id=?", [sid]).fetchone()[0]
        conn.close()
        assert n == 1
    finally:
        pipeline_worker._PIPELINE_HANDLERS.clear()
        pipeline_worker._PIPELINE_HANDLERS.update(original)


# ═══════════════════════════════════════════════════
# 4. 统一额度闸门（P1-8）
# ═══════════════════════════════════════════════════

def test_quota_gate(test_db_path):
    import db
    from domain import quota

    # 无订阅 → 拒绝
    sid_none = db.create_student({"name": "无订阅", "grade": "高二"})
    conn = db.get_connection(test_db_path)
    conn.execute("DELETE FROM subscriptions WHERE student_id=?", [sid_none])
    conn.commit()
    conn.close()
    ok, err = quota.charge_analysis(sid_none, db_path=test_db_path)
    assert ok is False and "订阅" in err

    # trial：注册赠送 3 次一次性额度，前 3 次成功、第 4 次拒绝
    sid_trial = db.create_student({"name": "体验", "grade": "高二", "plan": "trial"})
    trial_quota = db.PRICING["trial"]["monthly_quota"]
    for _ in range(trial_quota):
        ok, err = quota.charge_analysis(sid_trial, db_path=test_db_path)
        assert ok is True, err
    ok, err = quota.charge_analysis(sid_trial, db_path=test_db_path)
    assert ok is False and "额度" in err

    # staff 豁免
    ok, _ = quota.charge_analysis(sid_trial, is_staff=True, db_path=test_db_path)
    assert ok is True

    # unlimited 不限次
    sid_unl = db.create_student({"name": "无限", "grade": "高二", "plan": "unlimited"})
    for _ in range(3):
        ok, _ = quota.charge_analysis(sid_unl, db_path=test_db_path)
        assert ok is True
