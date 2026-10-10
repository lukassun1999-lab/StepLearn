# -*- coding: utf-8 -*-
"""标准答案入口（老师的「原题 + 标准答案」场景）。

背景：实践发现老师在周末常把学校试卷**原题 + 标准答案**发给家长，让孩子改错并
总结错题原因。此前标准答案只有"印在卷面上"这一条路（vision 提取 printed_answer_key），
家长手里的独立答案文件无从输入 → 判对错只能靠模型自判（已知准确率瓶颈）。

方案：新增第三组上传「标准答案」（file_type=answer_key），**独立解析**成
{题号: 答案} 再注入 `summary.printed_answer_key`，复用既有权威通道
（`_apply_printed_answer_key` + `_filter_real_mistakes`）。

关键设计：标准答案**不并入 OCR 正文** —— 否则会污染 `_extract_paper_text`
的防臆造校验（答案文件里也含题号）。
"""

import io
import json
import os

import pytest

import db
import llm_analysis


@pytest.fixture
def env(test_db_path, demo_mode, monkeypatch, tmp_path):
    """隔离 uploads 目录（不污染项目 uploads/）。"""
    from pipeline import stages
    upload_dir = str(tmp_path / "uploads")
    monkeypatch.setattr(stages, "UPLOAD_DIR", upload_dir)
    return upload_dir


class _F:
    """极简 FileStorage 替身。"""

    def __init__(self, name):
        self.filename = name
        self.content_type = "image/jpeg"
        self.content_length = 4

    def save(self, path):
        with open(path, "wb") as f:
            f.write(b"\xff\xd8\xff\xd9")


def _task_input(task):
    inp = task["input_data"]
    return json.loads(inp) if isinstance(inp, str) else inp


def _fake_client(analyze_result, key_result):
    """按 call_type 分派的假 LLM 客户端。"""
    class FakeClient:
        def call(self, **kw):
            return key_result if kw.get("call_type") == "answer_key" else analyze_result
    return FakeClient()


# ── 上传：三组输入分开存储 ─────────────────────────

def test_family_upload_stores_answer_key_separately(env, sample_student,
                                                    test_db_path, monkeypatch,
                                                    tmp_path):
    """试卷 / 答题卡 / 标准答案 三组分别落 test_paper / answer_sheet / answer_key。"""
    from domain import upload as upload_mod
    monkeypatch.setattr(upload_mod, "UPLOAD_DIR", str(tmp_path / "uploads"))

    task_id, ids = upload_mod.family_upload(
        sample_student, [_F("p1.jpg"), _F("p2.jpg")],
        answer_sheet_files=[_F("s1.jpg")],
        answer_key_files=[_F("k1.jpg")],
        uploader_role="parent", task_type="weekly", stage="grade_only",
        db_path=test_db_path)
    assert len(ids) == 2

    inp = _task_input(db.get_task(task_id, db_path=test_db_path))
    assert len(inp["file_ids"]) == 2
    assert len(inp["answer_sheet_file_ids"]) == 1
    assert len(inp["answer_key_file_ids"]) == 1

    base = os.path.join(str(tmp_path / "uploads"), str(sample_student))
    assert os.path.exists(os.path.join(base, "test_paper"))
    assert os.path.exists(os.path.join(base, "answer_sheet"))
    assert os.path.exists(os.path.join(base, "answer_key"))

    # 不带标准答案时不产生该键（回归保护）
    task2_id, _ = upload_mod.family_upload(
        sample_student, [_F("p3.jpg")], uploader_role="parent",
        task_type="weekly", stage="grade_only", db_path=test_db_path)
    assert "answer_key_file_ids" not in _task_input(
        db.get_task(task2_id, db_path=test_db_path))


def test_public_upload_accepts_answer_key(client, sample_student, test_db_path,
                                          monkeypatch, tmp_path):
    """/api/public/<code>/upload 接收 answer_key 字段并按类型入库。"""
    from domain import upload as upload_mod
    import pipeline_worker
    monkeypatch.setattr(upload_mod, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(pipeline_worker, "enqueue_task", lambda *a, **k: None)

    code = db.get_student(sample_student, db_path=test_db_path)["access_code"]
    r = client.post(f"/api/public/{code}/upload", data={
        "file": (io.BytesIO(b"\xff\xd8\xff\xd9"), "paper.jpg"),
        "answer_key": (io.BytesIO(b"\xff\xd8\xff\xd9"), "key.jpg"),
    }, content_type="multipart/form-data")
    assert r.status_code == 202

    inp = _task_input(db.get_task(r.get_json()["task_id"], db_path=test_db_path))
    assert len(inp["answer_key_file_ids"]) == 1
    f = db.get_file(inp["answer_key_file_ids"][0], db_path=test_db_path)
    assert f["file_type"] == "answer_key"


# ── 解析：文本 → 逐题答案键 ────────────────────────

def test_parse_answer_key_normalizes(monkeypatch):
    monkeypatch.setattr(llm_analysis, "_get_client", lambda: _fake_client(
        {}, {"answers": {"1": "B", "22": "full of", " 3 ": "C",
                         "x": "非法题号", "4": "  ", "5": None}}))
    parsed = llm_analysis.parse_answer_key("标准答案文本")
    assert parsed == {1: "B", 22: "full of", 3: "C"}, "非法题号/空答案应跳过"


def test_parse_answer_key_empty_or_failure(monkeypatch):
    assert llm_analysis.parse_answer_key("") == {}
    assert llm_analysis.parse_answer_key("   ") == {}

    class Boom:
        def call(self, **kw):
            raise RuntimeError("API 挂了")
    monkeypatch.setattr(llm_analysis, "_get_client", lambda: Boom())
    assert llm_analysis.parse_answer_key("1: A") == {}, "异常按无标准答案处理"


def test_extract_answer_key_text_labels_notes_and_expands(monkeypatch):
    """标准答案段落有独立标注 + 显式声明权威性，并对范围答案做展开。"""
    from pipeline import stages
    captured = {}

    def fake_group(ids, label, student_id, task_id, db_path, note=""):
        captured["label"], captured["note"] = label, note
        return ([f"--- 第 1 页 {label}---\n{note}1-3: ABC"], 0.9, 1)

    monkeypatch.setattr(stages, "_ocr_group_to_text", fake_group)
    text, conf = stages.extract_answer_key_text([1], 1, 1, None)

    assert captured["label"] == "（标准答案）"
    assert "权威答案来源" in captured["note"]
    # 范围答案展开为逐题（显著提升后续提取可靠性）
    assert "1: A" in text and "2: B" in text and "3: C" in text
    assert conf == pytest.approx(0.9)

    assert stages.extract_answer_key_text([], 1, 1, None) == ("", 0.0)


# ── 核心收益：权威覆盖 + 误判剔除 ──────────────────

def _analyze_result():
    """两条 语法填空 错题（内容型答案，避开纯字母的"存疑跳过"分支）。

    注意：纯字母作答 + 题干无选项时 `_filter_real_mistakes` 会存疑跳过
    （不冤枉学生，见 knowledge_base.py:416），因此测试用内容型答案。
    """
    return {
        "mistakes": [
            # 模型判错、实为答对：学生 'full of'，模型自判 'full in' → 答案键 'full of'
            {"question_number": 1, "question_text": "The bottle is ___ water.",
             "question_type": "语法填空", "correct_answer": "full in",
             "user_answer": "full of", "error_cause": "grammar",
             "knowledge_points": ["固定搭配"]},
            # 真错：学生 'fill of'，答案键 'full of'
            {"question_number": 2, "question_text": "The box is ___ toys.",
             "question_type": "语法填空", "correct_answer": "full in",
             "user_answer": "fill of", "error_cause": "vocab",
             "knowledge_points": ["固定搭配"]},
        ],
        "summary": {"total_mistakes": 2, "by_type": {"语法填空": 2},
                    "top_weak_points": [], "overall_assessment": ""},
    }


def test_answer_key_overrides_and_drops_misjudged(monkeypatch, demo_mode):
    """标准答案 → correct_answer 权威覆盖 + 答对却被判错的题被剔除。"""
    monkeypatch.setattr(llm_analysis, "_get_client", lambda: _fake_client(
        _analyze_result(), {"answers": {"1": "full of", "2": "full of"}}))

    res = llm_analysis.analyze_mistakes(
        "1. The bottle is ___ water.\n1: full of",
        answer_key_text="1: full of\n2: full of")

    assert len(res["mistakes"]) == 1, "答对却被判错的题应被剔除"
    m = res["mistakes"][0]
    assert m["question_number"] == 2
    assert m["correct_answer"] == "full of", "标准答案必须覆盖模型自判答案"
    assert m["answer_source"] == "answer_key", "来源应标记为 answer_key"
    assert res["summary"]["printed_key_applied"] == 2
    assert res["summary"]["answer_key_file_questions"] == [1, 2]


def test_no_answer_key_behavior_unchanged(monkeypatch, demo_mode):
    """不传标准答案时行为与历史一致（回归保护）。"""
    monkeypatch.setattr(llm_analysis, "_get_client", lambda: _fake_client(
        _analyze_result(), {}))

    res = llm_analysis.analyze_mistakes("1. The bottle is ___ water.\n1: full of")

    assert len(res["mistakes"]) == 2, "无标准答案时不剔除"
    for m in res["mistakes"]:
        assert m.get("answer_source") != "answer_key"
        assert m["correct_answer"] == "full in", "模型自判答案不被改动"
    assert "answer_key_file_questions" not in res["summary"]


def test_printed_key_takes_lower_precedence_than_file(monkeypatch, demo_mode):
    """卷面印刷答案与标准答案文件都有时，以文件为准（显式上传=更明确意图）。"""
    result = _analyze_result()
    result["summary"]["printed_answer_key"] = {"2": "打印的答案"}
    monkeypatch.setattr(llm_analysis, "_get_client", lambda: _fake_client(
        result, {"answers": {"2": "文件答案"}}))

    res = llm_analysis.analyze_mistakes("1. The bottle is ___ water.\n1: full of",
                                       answer_key_text="2: 文件答案")
    m2 = [m for m in res["mistakes"] if m["question_number"] == 2][0]
    assert m2["correct_answer"] == "文件答案"
    assert m2["answer_source"] == "answer_key"


# ── 链路级：node_ocr 提取 → 持久化 → node_analyze 收到 ──

def test_pipeline_extracts_persists_and_passes_answer_key(env, sample_student,
                                                          test_db_path, monkeypatch):
    """标准答案走完整链路：node_ocr 独立提取并持久化，node_analyze 拿到它。"""
    from pipeline import stages

    task_id = db.create_task(sample_student, "weekly", {
        "file_ids": [1], "answer_key_file_ids": [2], "stage": "grade_only",
    }, db_path=test_db_path)
    task = db.get_task(task_id, db_path=test_db_path)
    ctx = stages.Ctx(task, test_db_path)
    ctx.student = db.get_student(sample_student, db_path=test_db_path)

    monkeypatch.setattr(stages, "ocr_to_text",
                        lambda *a, **k: ("试卷正文。" * 20, 0.9))
    monkeypatch.setattr(stages, "extract_answer_key_text",
                        lambda ids, *a, **k: ("1: B\n2: C", 0.9))
    stages.node_ocr(ctx)
    assert ctx.answer_key_text == "1: B\n2: C"
    assert ctx.answer_key_file_ids == [2]

    # 断点续跑用：已持久化到 input_data._answer_key_text
    persisted = _task_input(db.get_task(task_id, db_path=test_db_path))
    assert persisted["_answer_key_text"] == "1: B\n2: C"

    # node_analyze 把标准答案传给判题
    seen = {}

    def fake_analyze(ocr_text, task_id=None, answer_key_text=None):
        seen["key"] = answer_key_text
        return {"mistakes": [], "summary": {}}

    monkeypatch.setattr(stages, "analyze_mistakes", fake_analyze)
    stages.node_analyze(ctx)
    assert seen["key"] == "1: B\n2: C"


def test_ocr_text_excludes_answer_key(env, sample_student, test_db_path,
                                      monkeypatch):
    """设计不变量：标准答案**不进** ocr_text（避免污染防臆造校验）。"""
    from pipeline import stages

    task_id = db.create_task(sample_student, "weekly", {
        "file_ids": [1], "answer_key_file_ids": [2], "stage": "grade_only",
    }, db_path=test_db_path)
    task = db.get_task(task_id, db_path=test_db_path)
    ctx = stages.Ctx(task, test_db_path)

    captured = {}

    def fake_ocr_to_text(file_ids, student_id, task_id, db_path,
                         answer_sheet_file_ids=None, warnings=None):
        captured["file_ids"] = file_ids
        captured["sheet_ids"] = answer_sheet_file_ids
        return ("试卷正文。" * 20, 0.9)

    monkeypatch.setattr(stages, "ocr_to_text", fake_ocr_to_text)
    monkeypatch.setattr(stages, "extract_answer_key_text",
                        lambda *a, **k: ("标准答案正文", 0.9))
    stages.node_ocr(ctx)

    assert captured["file_ids"] == [1], "标准答案不得混入试卷文件组"
    assert captured["sheet_ids"] == []
    assert "标准答案正文" not in ctx.ocr_text
    assert ctx.answer_key_text == "标准答案正文"


# ── 两个上传界面都真的有这个入口 ─────────────────────

def test_both_upload_pages_expose_answer_key_input(client, sample_student,
                                                   test_db_path):
    """`/parent` 首访页与 `/s/<code>` 学习中心都要有标准答案入口（含提交字段）。"""
    code = db.get_student(sample_student, db_path=test_db_path)["access_code"]

    parent_html = client.get("/parent").get_data(as_text=True)
    assert "标准答案" in parent_html
    assert "keyInput" in parent_html
    assert "pickedKeys" in parent_html
    assert "formData.append('answer_key'" in parent_html

    center_html = client.get(f"/s/{code}").get_data(as_text=True)
    assert "标准答案" in center_html
    assert "parentKeyInput" in center_html
    assert "handleParentKeyUpload" in center_html
    assert "formData.append('answer_key'" in center_html
