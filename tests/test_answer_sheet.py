# -*- coding: utf-8 -*-
"""试卷+答题卡双输入判题回归测试。

背景：学生考试多使用答题卡作答、试卷本身无书写。此前只传试卷时，
LLM 看不到学生作答 → 漏报/虚报，判题准确率受损。
方案：上传时试卷与答题卡分组存储，OCR 分组拼接段落标注，
判题 LLM 从试卷读题目、从答题卡读学生作答（llm_prompts 双输入模式）。
"""

import os

import pytest


@pytest.fixture
def env(test_db_path, demo_mode, monkeypatch, tmp_path):
    """隔离 uploads 目录（不污染项目 uploads/）。"""
    from pipeline import stages
    upload_dir = str(tmp_path / "uploads")
    monkeypatch.setattr(stages, "UPLOAD_DIR", upload_dir)
    return upload_dir


def _fake_ocr(paths, task_id=None):
    """Mock run_ocr_parallel：按路径序号返回确定性文本。"""
    return [{"ok": True, "text": f"OCR_TEXT_{i}", "confidence": 0.9}
            for i in range(len(paths))]


def _save_upload_files(student_id, names, file_type, upload_dir):
    """直接写占位图片并登记 files 表（模拟 save_files 后的落盘状态）。"""
    import db
    d = os.path.join(upload_dir, str(student_id), file_type)
    os.makedirs(d, exist_ok=True)
    ids = []
    for name in names:
        with open(os.path.join(d, name), "wb") as f:
            f.write(b"\xff\xd8\xff\xd9")
        ids.append(db.add_file(
            student_id=student_id, uploader_role="parent",
            file_type=file_type, filename=name, original_filename=name,
            week_start=db.get_week_start(), file_size=4,
            mime_type="image/jpeg"))
    return ids


def test_ocr_to_text_groups_paper_and_sheet(env, sample_student, test_db_path,
                                            monkeypatch):
    """试卷与答题卡分组拼接，段落标注（答题卡），顺序试卷在前。"""
    import db
    from pipeline import stages
    import skills_bridge
    monkeypatch.setattr(skills_bridge, "run_ocr_parallel", _fake_ocr)

    paper_ids = _save_upload_files(sample_student, ["p1.jpg", "p2.jpg"],
                                   "test_paper", env)
    sheet_ids = _save_upload_files(sample_student, ["s1.jpg"],
                                   "answer_sheet", env)

    text, conf = stages.ocr_to_text(
        paper_ids, sample_student, task_id=1, db_path=test_db_path,
        answer_sheet_file_ids=sheet_ids)

    assert "--- 第 1 页 ---" in text
    assert "--- 第 2 页 ---" in text
    assert "--- 第 1 页 （答题卡）---" in text
    # 试卷在前、答题卡在后
    assert text.index("--- 第 2 页 ---") < text.index("--- 第 1 页 （答题卡）---")
    assert conf == pytest.approx(0.9)


def test_ocr_to_text_without_sheet_backwards_compatible(env, sample_student,
                                                        test_db_path,
                                                        monkeypatch):
    """只传试卷（无答题卡）→ 段落无（答题卡）标注，走原逻辑。"""
    from pipeline import stages
    import skills_bridge
    monkeypatch.setattr(skills_bridge, "run_ocr_parallel", _fake_ocr)

    paper_ids = _save_upload_files(sample_student, ["p1.jpg"],
                                   "test_paper", env)
    text, conf = stages.ocr_to_text(
        paper_ids, sample_student, task_id=1, db_path=test_db_path)

    assert "--- 第 1 页 ---" in text
    assert "答题卡" not in text
    assert conf == pytest.approx(0.9)


def test_family_upload_stores_sheet_separately(env, sample_student,
                                               test_db_path, monkeypatch,
                                               tmp_path):
    """family_upload 双传：试卷存 test_paper、答题卡存 answer_sheet，
    input_data 记录两组 file_ids；只传试卷时无 answer_sheet_file_ids。"""
    import db
    from domain import upload as upload_mod
    monkeypatch.setattr(upload_mod, "UPLOAD_DIR", str(tmp_path / "uploads"))

    class _F:
        def __init__(self, name):
            self.filename = name
            self.content_type = "image/jpeg"
            self.content_length = 4

        def save(self, path):
            with open(path, "wb") as f:
                f.write(b"\xff\xd8\xff\xd9")

    paper = [_F("p1.jpg"), _F("p2.jpg")]
    sheet = [_F("s1.jpg")]

    task_id, ids = upload_mod.family_upload(
        sample_student, paper, answer_sheet_files=sheet,
        uploader_role="parent", task_type="weekly", stage="grade_only",
        db_path=test_db_path)
    assert len(ids) == 2

    task = db.get_task(task_id, db_path=test_db_path)
    inp = task["input_data"]
    if isinstance(inp, str):
        import json
        inp = json.loads(inp)
    assert len(inp["file_ids"]) == 2
    assert len(inp["answer_sheet_file_ids"]) == 1

    # 落盘目录按类型分开
    base = os.path.join(str(tmp_path / "uploads"), str(sample_student))
    assert os.path.exists(os.path.join(base, "test_paper"))
    assert os.path.exists(os.path.join(base, "answer_sheet"))

    # 只传试卷：不产生 answer_sheet_file_ids
    task2_id, _ = upload_mod.family_upload(
        sample_student, [_F("p3.jpg")], uploader_role="parent",
        task_type="weekly", stage="grade_only", db_path=test_db_path)
    task2 = db.get_task(task2_id, db_path=test_db_path)
    inp2 = task2["input_data"]
    if isinstance(inp2, str):
        import json
        inp2 = json.loads(inp2)
    assert "answer_sheet_file_ids" not in inp2


def test_public_upload_accepts_answer_sheet(client, sample_student,
                                            test_db_path, monkeypatch,
                                            tmp_path):
    """/api/public/<code>/upload 接收 answer_sheet 字段并分组入库。"""
    import db
    from domain import upload as upload_mod
    import pipeline_worker
    monkeypatch.setattr(upload_mod, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(pipeline_worker, "enqueue_task", lambda *a, **k: None)

    code = db.get_student(sample_student, db_path=test_db_path)["access_code"]
    data = {
        "file": (__import__("io").BytesIO(b"\xff\xd8\xff\xd9"), "paper.jpg"),
        "answer_sheet": (__import__("io").BytesIO(b"\xff\xd8\xff\xd9"), "sheet.jpg"),
    }
    r = client.post(f"/api/public/{code}/upload", data=data,
                    content_type="multipart/form-data")
    assert r.status_code == 202
    assert len(r.get_json()["file_ids"]) == 1

    # 任务 input_data 两组 id 齐备，答题卡类型入库正确
    task = db.get_task(r.get_json()["task_id"], db_path=test_db_path)
    inp = task["input_data"]
    if isinstance(inp, str):
        import json
        inp = json.loads(inp)
    assert len(inp["file_ids"]) == 1
    assert len(inp["answer_sheet_file_ids"]) == 1
    f = db.get_file(inp["answer_sheet_file_ids"][0], db_path=test_db_path)
    assert f["file_type"] == "answer_sheet"
