# -*- coding: utf-8 -*-
"""L3 学生长期记忆测试：DB 读写、记忆合并 prompt、月度总结刷新与方案消费。"""

import json
import os
import uuid

import pytest

import db
import llm_plans
import pipeline.snapshots as snapshots
import pipeline.stages as stages
from pipeline.snapshots import _refresh_student_memory, run_monthly_summary


# ── DB 读写 ─────────────────────────────────────────

def test_memory_roundtrip(test_db_path, sample_student):
    assert db.get_student_memory(sample_student, db_path=test_db_path) is None

    db.save_student_memory(sample_student, {
        "memory_summary": "词汇量是核心瓶颈，例句记忆法对其有效",
        "learner_type": "视觉型、需要正反馈驱动",
        "recurring_causes": ["词汇"],
        "effective_methods": ["例句记忆法"],
        "source_month": "2026年8月",
    }, db_path=test_db_path)

    m = db.get_student_memory(sample_student, db_path=test_db_path)
    assert m["memory_summary"] == "词汇量是核心瓶颈，例句记忆法对其有效"
    assert m["learner_type"] == "视觉型、需要正反馈驱动"
    assert m["recurring_causes"] == ["词汇"]
    assert m["effective_methods"] == ["例句记忆法"]
    assert m["source_month"] == "2026年8月"

    # 覆盖写（upsert）
    db.save_student_memory(sample_student, {
        "memory_summary": "更新后的画像",
        "source_month": "2026年9月",
    }, db_path=test_db_path)
    m = db.get_student_memory(sample_student, db_path=test_db_path)
    assert m["memory_summary"] == "更新后的画像"
    assert m["recurring_causes"] == []


def test_memory_survives_corrupt_json(test_db_path, sample_student):
    db.save_student_memory(sample_student, {
        "memory_summary": "ok", "recurring_causes": ["词汇"],
    }, db_path=test_db_path)
    conn = db.get_connection(test_db_path)
    conn.execute("UPDATE student_memory SET recurring_causes = 'not-json' "
                 "WHERE student_id = ?", [sample_student])
    conn.commit()
    conn.close()
    assert db.get_student_memory(sample_student, db_path=test_db_path)["recurring_causes"] == []


# ── 记忆合并 LLM 函数 ───────────────────────────────

class _FakeMemoryClient:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def call(self, **kw):
        self.calls.append(kw)
        return self.result


def test_update_student_memory_merges_old_memory(monkeypatch):
    fake = _FakeMemoryClient({
        "memory_summary": "合并后画像",
        "learner_type": "视觉型",
        "recurring_causes": ["词汇"],
        "effective_methods": ["例句记忆法"],
    })
    monkeypatch.setattr(llm_plans, "_get_client", lambda: fake)

    result = llm_plans.update_student_memory(
        student_info={"name": "小明", "grade": "高二"},
        month_label="2026年8月",
        old_memory={"memory_summary": "旧画像", "recurring_causes": ["词汇"]},
        month_facts="- 本月错题 5 道",
    )

    assert result["memory_summary"] == "合并后画像"
    prompt = fake.calls[0]["prompt"]
    assert "旧画像" in prompt          # 旧记忆进入 prompt
    assert "本月错题 5 道" in prompt    # 本月学情进入 prompt
    assert "2026年8月" in prompt
    assert fake.calls[0]["schema"]["memory_summary"]["required"] is True


# ── 方案生成消费记忆 ────────────────────────────────

def test_generate_learning_plan_injects_memory(monkeypatch):
    fake = _FakeMemoryClient({"weak_point_priority": [], "modules": []})
    monkeypatch.setattr(llm_plans, "_get_client", lambda: fake)

    llm_plans.generate_learning_plan(
        student_info={"name": "小明", "grade": "高二"},
        diagnosis={},
        memory={
            "learner_type": "视觉型",
            "memory_summary": "词汇量是瓶颈",
            "recurring_causes": ["词汇", "审题"],
            "effective_methods": ["例句记忆法"],
        },
    )

    prompt = fake.calls[0]["prompt"]
    assert "学习者类型：视觉型" in prompt
    assert "词汇量是瓶颈" in prompt
    assert "词汇、审题" in prompt
    assert "例句记忆法" in prompt


def test_generate_learning_plan_without_memory(monkeypatch):
    fake = _FakeMemoryClient({"weak_point_priority": [], "modules": []})
    monkeypatch.setattr(llm_plans, "_get_client", lambda: fake)
    llm_plans.generate_learning_plan(student_info={"name": "小明"}, diagnosis={})
    assert "（暂无）" in fake.calls[0]["prompt"]


def test_generate_plan_update_injects_memory(monkeypatch):
    fake = _FakeMemoryClient({})
    monkeypatch.setattr(llm_plans, "_get_client", lambda: fake)
    llm_plans.generate_plan_update(
        student_id=1, week_start="2026-08-31",
        memory_summary="视觉型；反复错因：词汇",
    )
    assert "反复错因：词汇" in fake.calls[0]["prompt"]


def test_memory_digest(test_db_path, sample_student):
    assert stages._memory_digest(None) == ""
    assert stages._memory_digest({"memory_summary": ""}) == ""
    digest = stages._memory_digest({
        "learner_type": "视觉型",
        "memory_summary": "词汇是瓶颈",
        "recurring_causes": ["词汇"],
    })
    assert "视觉型" in digest and "词汇是瓶颈" in digest and "反复错因：词汇" in digest


# ── 月度总结刷新记忆 ────────────────────────────────

def _make_student_with_month_data(test_db_path):
    sid = db.create_student({
        "name": "记忆学生", "grade": "高二", "school_type": "住校",
        "english_score": 100, "plan": "trial",
    }, db_path=test_db_path)
    mid = db.add_mistake(
        student_id=sid, question="Q", question_type="单项选择",
        correct_answer="A", user_answer="B",
        knowledge_points=["强调句型"], db_path=test_db_path)
    # 错题落在 2026-08（run_monthly_summary 分析上个月）
    conn = db.get_connection(test_db_path)
    conn.execute("UPDATE mistakes SET created_at = '2026-08-20 10:00:00' "
                 "WHERE id = ?", [mid])
    conn.commit()
    conn.close()
    return sid


def test_monthly_summary_refreshes_memory(monkeypatch, test_db_path, tmp_path):
    monkeypatch.setattr(stages, "UPLOAD_DIR", str(tmp_path / "uploads"))
    sid = _make_student_with_month_data(test_db_path)
    db.save_student_memory(sid, {"memory_summary": "旧画像"},
                           db_path=test_db_path)
    task_id = db.create_task(sid, "monthly", {}, week_start="2026-09-07",
                             db_path=test_db_path)
    task = db.get_task(task_id, db_path=test_db_path)

    seen = {}

    def fake_update(student_info, month_label, old_memory, month_facts,
                    task_id=None):
        seen["old"] = old_memory
        seen["label"] = month_label
        seen["facts"] = month_facts
        return {"memory_summary": "新画像：词汇反复出现，例句法有效",
                "learner_type": "视觉型",
                "recurring_causes": ["词汇"],
                "effective_methods": ["例句法"]}

    monkeypatch.setattr(snapshots, "update_student_memory", fake_update)
    monkeypatch.setattr(snapshots, "generate_monthly_analysis",
                        lambda **kw: {"overall_assessment": "ok"})

    run_monthly_summary(task, test_db_path)

    assert seen["old"]["memory_summary"] == "旧画像"
    assert seen["label"] == "2026年8月"
    m = db.get_student_memory(sid, db_path=test_db_path)
    assert m["memory_summary"] == "新画像：词汇反复出现，例句法有效"
    assert m["source_month"] == "2026年8月"
    # 月报 HTML 已生成
    report_dir = os.path.join(str(tmp_path / "uploads"), str(sid), "report_pdf")
    assert any(f.startswith("monthly_") for f in os.listdir(report_dir))


def test_monthly_summary_keeps_old_memory_on_empty_result(
        monkeypatch, test_db_path, tmp_path):
    monkeypatch.setattr(stages, "UPLOAD_DIR", str(tmp_path / "uploads"))
    sid = _make_student_with_month_data(test_db_path)
    db.save_student_memory(sid, {"memory_summary": "旧画像"},
                           db_path=test_db_path)
    task_id = db.create_task(sid, "monthly", {}, week_start="2026-09-07",
                             db_path=test_db_path)
    task = db.get_task(task_id, db_path=test_db_path)

    monkeypatch.setattr(snapshots, "update_student_memory",
                        lambda **kw: {"memory_summary": ""})
    monkeypatch.setattr(snapshots, "generate_monthly_analysis",
                        lambda **kw: {})

    run_monthly_summary(task, test_db_path)

    m = db.get_student_memory(sid, db_path=test_db_path)
    assert m["memory_summary"] == "旧画像"


def test_refresh_student_memory_includes_cause_profile(monkeypatch, test_db_path):
    sid = _make_student_with_month_data(test_db_path)
    db.save_cause_profile(sid, {
        "primary_cause": "vocab", "cause_chain": ["vocab", "grammar"],
    }, db_path=test_db_path)

    seen = {}

    def fake_update(**kw):
        seen["facts"] = kw["month_facts"]
        return {"memory_summary": "ok"}

    monkeypatch.setattr(snapshots, "update_student_memory", fake_update)
    _refresh_student_memory(
        {"id": sid, "name": "记忆学生", "grade": "高二"},
        "2026年8月", {"total_mistakes": 3, "mastered_count": 1,
                      "practice_count": 10, "avg_accuracy": 0.8},
        "- 强调句型: 3 道", "- 2026-08-20 月考: 95分",
        db_path=test_db_path)

    assert "强调句型" in seen["facts"]
    assert "vocab" in seen["facts"]       # 错因画像进入事实
    assert "95分" in seen["facts"]
