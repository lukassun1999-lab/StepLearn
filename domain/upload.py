#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一上传服务：存文件 → 额度闸门 → 建任务 的唯一实现（P2-10）。

调用方：
- /api/public/<code>/upload  （家庭端公开页，家长拍照）
- /api/student/upload        （学生登录态上传）
- /api/parent/diagnose       （首访 bootstrap：建档后走本服务）

运营端 /api/upload 仅存文件不触发流水线，不走本服务。
"""

import os
import uuid

import db

UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")

QUOTA_FREE_STAGES = ("analysis_only", "report_only")


class UploadError(Exception):
    """上传/闸门失败；status 为应返回前端的 HTTP 状态码。"""

    def __init__(self, message: str, status: int = 429):
        super().__init__(message)
        self.message = message
        self.status = status


def save_files(student_id, files, file_type: str = "test_paper",
               uploader_role: str = "parent", week_start: str = None,
               db_path: str = None):
    """保存上传文件集并登记 files 表。返回 file_ids（跳过空文件）。

    安全校验：扩展名白名单 + 单文件 20MB 上限（试卷照片/答题卡）。
    """
    from web.shared import _sanitize_file_type, _validate_upload
    db_path = db_path or db.DB_PATH
    week_start = week_start or db.get_week_start()
    file_type = _sanitize_file_type(file_type)
    file_ids = []
    for f in files:
        if not f or not getattr(f, "filename", None):
            continue
        err = _validate_upload(f)
        if err:
            raise UploadError(err, 400)
        ext = os.path.splitext(f.filename)[1].lower() or ".jpg"
        filename = f"{uuid.uuid4().hex}{ext}"
        save_dir = os.path.join(UPLOAD_DIR, str(student_id), file_type)
        os.makedirs(save_dir, exist_ok=True)
        filepath = os.path.join(save_dir, filename)
        f.save(filepath)
        if os.path.getsize(filepath) > 20 * 1024 * 1024:
            os.remove(filepath)
            raise UploadError("文件超过 20MB 限制", 400)
        fid = db.add_file(
            student_id=student_id, uploader_role=uploader_role,
            file_type=file_type, filename=filename,
            original_filename=f.filename, week_start=week_start,
            file_size=os.path.getsize(filepath),
            mime_type=getattr(f, "content_type", None) or "image/jpeg",
            db_path=db_path,
        )
        file_ids.append(fid)
    return file_ids


def family_upload(student_id, files, *, uploader_role: str = "parent",
                  task_type: str = "weekly", stage: str = "grade_only",
                  is_staff: bool = False, extra_input: dict = None,
                  db_path: str = None):
    """家庭端统一上传：存文件 → 额度闸门 → 建任务入队。

    Returns:
        (task_id, file_ids)
    Raises:
        UploadError: 无有效文件(400) / 额度或订阅问题(429)
    """
    db_path = db_path or db.DB_PATH

    # PIPL 门禁：CONSENT_REQUIRED=true 时，无有效监护人同意不得处理学生数据。
    # 默认关闭（个人使用不打断）；商用上线置 true 强制合规。
    if (os.environ.get("CONSENT_REQUIRED") == "true"
            and not db.has_parent_consent(student_id, db_path=db_path)):
        raise UploadError("尚未获得监护人数据处理同意，请联系老师完成同意登记后再上传", 403)

    file_ids = save_files(student_id, files, uploader_role=uploader_role,
                          db_path=db_path)
    if not file_ids:
        raise UploadError("没有有效的文件", 400)

    input_data = {"file_ids": file_ids}
    if task_type == "weekly":
        input_data["stage"] = stage
    if extra_input:
        input_data.update(extra_input)

    # 统一额度闸门（domain/quota.py 单一收口）
    if stage not in QUOTA_FREE_STAGES:
        from domain import quota as quota_mod
        ok, err = quota_mod.charge_analysis(
            student_id, is_staff=is_staff, db_path=db_path)
        if not ok:
            raise UploadError(err, 429)
        if not is_staff:
            input_data["quota_charged"] = True

    task_id = db.create_task(student_id, task_type, input_data, db_path=db_path)
    from pipeline_worker import enqueue_task
    enqueue_task(task_id, db_path)
    return task_id, file_ids
