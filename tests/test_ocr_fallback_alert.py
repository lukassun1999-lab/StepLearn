# -*- coding: utf-8 -*-
"""OCR 降级显式告警（静默劣化修复）。

背景：`OCR_BACKEND=auto` 下，视觉模型识别失败（模型不支持图片、端点错误、额度不足等）
会**静默退回 Tesseract.js**，只在结果里塞一个 `vision_fallback_reason` 字段，
上层（`run_ocr_parallel` → `ocr_to_text` → 任务产出 → 家长端）一路丢弃。

后果：家长只会看到"识别结果变差"，没人知道降级发生了 —— 换模型/改端点后这类
配置错误尤其容易悄悄发生。

修复：原因字段一路上提 → 日志 + 任务进度文案 + `output_data.ocr_warning` → 家长端显式提示。
"""

import pytest


def test_run_ocr_parallel_propagates_fallback_reason(monkeypatch):
    """服务层：退回本地识别的原因必须带出 run_ocr_parallel。"""
    import ocr_service

    monkeypatch.setattr(ocr_service, "run_ocr", lambda path, task_id=None: {
        "text": "识别文本", "confidence": 0.5, "backend": "tesseract",
        "vision_fallback_reason": "model does not support images",
    })
    out = ocr_service.run_ocr_parallel(["/nonexistent/a.jpg"])
    assert out[0]["ok"] is True
    assert out[0]["vision_fallback_reason"] == "model does not support images"


def test_run_ocr_parallel_propagates_total_failure(monkeypatch):
    """彻底失败也要带出错误信息（原实现只给 ok=False）。"""
    import ocr_service

    def _boom(path, task_id=None):
        raise RuntimeError("OCR failed: vision (400 bad request), tesseract (node missing)")

    monkeypatch.setattr(ocr_service, "run_ocr", _boom)
    out = ocr_service.run_ocr_parallel(["/nonexistent/a.jpg"])
    assert out[0]["ok"] is False
    assert "tesseract" in out[0]["error"]


def test_group_helper_collects_fallback_warning(monkeypatch):
    """链层：分组 OCR 时把降级页数收集成告警文案。"""
    import skills_bridge
    from pipeline import stages

    monkeypatch.setattr(stages, "get_image_path", lambda sid, fid, db: "/tmp/x.jpg")
    monkeypatch.setattr(skills_bridge, "run_ocr_parallel", lambda paths, task_id=None: [
        {"ok": True, "text": "T1", "confidence": 0.4,
         "vision_fallback_reason": "vision failed"},
        {"ok": True, "text": "T2", "confidence": 0.4},
    ])

    warnings = []
    parts, _conf, n = stages._ocr_group_to_text(
        [1, 2], "", 1, 1, None, warnings=warnings)
    assert n == 2 and all(parts)
    assert len(warnings) == 1
    assert "1 页视觉识别失败" in warnings[0]
    assert "试卷" in warnings[0]


def test_group_helper_collects_total_failure_warning(monkeypatch):
    import skills_bridge
    from pipeline import stages

    monkeypatch.setattr(stages, "get_image_path", lambda sid, fid, db: "/tmp/x.jpg")
    monkeypatch.setattr(skills_bridge, "run_ocr_parallel", lambda paths, task_id=None: [
        {"ok": False, "text": "", "confidence": 0.0, "error": "boom"},
    ])

    warnings = []
    stages._ocr_group_to_text([1], "", 1, 1, None, warnings=warnings)
    assert warnings and "两种 OCR 均未识别成功" in warnings[0]


def test_no_warning_when_vision_succeeds(monkeypatch):
    """正常路径不产生任何告警（回归保护）。"""
    import skills_bridge
    from pipeline import stages

    monkeypatch.setattr(stages, "get_image_path", lambda sid, fid, db: "/tmp/x.jpg")
    monkeypatch.setattr(skills_bridge, "run_ocr_parallel", lambda paths, task_id=None: [
        {"ok": True, "text": "T", "confidence": 0.9},
    ])

    warnings = []
    stages._ocr_group_to_text([1], "", 1, 1, None, warnings=warnings)
    assert warnings == []


# ── 任务产出：告警必须能从 output_data 读到 ────────────

@pytest.fixture
def env(test_db_path, demo_mode, monkeypatch, tmp_path):
    from pipeline import stages
    upload_dir = str(tmp_path / "uploads")
    monkeypatch.setattr(stages, "UPLOAD_DIR", upload_dir)
    return upload_dir


def test_node_ocr_sets_warning_and_build_output(env, sample_student, test_db_path,
                                                monkeypatch):
    """node_ocr 收集告警 → Ctx.ocr_warning + 日志 + 进度文案 + output_data。"""
    import db
    from pipeline import stages

    task_id = db.create_task(sample_student, "weekly", {
        "file_ids": [1], "stage": "grade_only",
    }, db_path=test_db_path)
    task = db.get_task(task_id, db_path=test_db_path)
    ctx = stages.Ctx(task, test_db_path)
    ctx.student = db.get_student(sample_student, db_path=test_db_path)

    steps = []
    monkeypatch.setattr(ctx, "progress", lambda step, pct: steps.append(step))

    def fake_ocr_to_text(*a, **kw):
        kw["warnings"].append("试卷有 1 页视觉识别失败，已退回本地 OCR，"
                              "识别准确率可能下降（建议重新上传更清晰的照片）")
        return "试卷正文。" * 20, 0.5

    monkeypatch.setattr(stages, "ocr_to_text", fake_ocr_to_text)
    stages.node_ocr(ctx)

    assert "视觉识别失败" in ctx.ocr_warning
    assert any("视觉识别失败" in s for s in steps), "进度文案要带上告警"
    assert ctx.build_output()["ocr_warning"] == ctx.ocr_warning


def test_build_output_omits_warning_when_clean(env, sample_student, test_db_path,
                                               monkeypatch):
    """无降级时 output_data 不含该字段（不制造噪音）。"""
    import db
    from pipeline import stages

    task_id = db.create_task(sample_student, "weekly", {
        "file_ids": [1], "stage": "grade_only",
    }, db_path=test_db_path)
    ctx = stages.Ctx(db.get_task(task_id, db_path=test_db_path), test_db_path)
    ctx.student = db.get_student(sample_student, db_path=test_db_path)
    monkeypatch.setattr(ctx, "progress", lambda step, pct: None)
    monkeypatch.setattr(stages, "ocr_to_text", lambda *a, **k: ("试卷正文。" * 20, 0.9))
    stages.node_ocr(ctx)

    assert ctx.ocr_warning == ""
    assert "ocr_warning" not in ctx.build_output()


# ── 家长端可见 ──────────────────────────────────────

def test_family_pages_render_ocr_warning_notice(client, sample_student,
                                                test_db_path):
    """两个家庭端页面都要渲染该告警（否则仍是"静默"）。"""
    import db
    code = db.get_student(sample_student, db_path=test_db_path)["access_code"]

    center = client.get(f"/s/{code}").get_data(as_text=True)
    assert "out.ocr_warning" in center and "escapeHtml(out.ocr_warning)" in center

    parent = client.get("/parent").get_data(as_text=True)
    assert "data.ocr_warning" in parent
