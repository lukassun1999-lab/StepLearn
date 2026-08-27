# -*- coding: utf-8 -*-
"""家长转化漏斗回归测试（运营看板）。

覆盖：
- /api/funnel 五阶段口径（上传→分析→报告→练习→批改，本周去重学生数）
- 公开下载埋点：家长打开报告写 audit_logs(action=view_report)，驱动漏斗

注意：SQLite 写锁是全库级——本文件所有原生 SQL 都用"开连接→提交→立即关闭"
的短事务模式，绝不持有连接跨越库函数或 HTTP 调用。
"""

import pytest


@pytest.fixture
def staff_client(client, teacher_user):
    with client.session_transaction() as sess:
        sess["user_id"] = teacher_user
        sess["user_role"] = "teacher"
    return client


def _funnel_counts(client):
    r = client.get("/api/funnel")
    assert r.status_code == 200
    return r.get_json()


def test_funnel_stage_counts(client, staff_client, test_db_path):
    """每阶段灌入 1 名新学生的行为数据 → 对应阶段学生数恰好 +1。"""
    import db

    sid = db.create_student({"name": "漏斗学生", "grade": "高二"}, db_path=test_db_path)
    before = {s["key"]: s["students"] for s in _funnel_counts(staff_client)["stages"]}

    # 上传：建任务
    db.create_task(sid, "weekly", {"stage": "full"}, db_path=test_db_path)

    # 分析完成：置为 done（短事务）
    conn = db.get_connection(test_db_path)
    try:
        conn.execute(
            "UPDATE ai_tasks SET status='done' WHERE student_id=?", [sid])
        conn.commit()
    finally:
        conn.close()

    # 报告打开（埋点）
    db.log_audit(actor_type="parent", actor_id=str(sid), action="view_report",
                 target_type="report_pdf", target_id="999",
                 db_path=test_db_path)

    # 答题练习
    mid = db.add_mistake(student_id=sid, source_exam="t", question="Q",
                         question_type="单项选择", correct_answer="A",
                         user_answer="B", db_path=test_db_path)
    db.record_practice(mid, "A", True, "ok", db_path=test_db_path)

    # 批改回传
    from db.core import get_week_start
    db.update_weekly_record(sid, get_week_start(), kind="weekly",
                            exercises_graded=1, db_path=test_db_path)

    body = _funnel_counts(staff_client)
    after = {s["key"]: s["students"] for s in body["stages"]}
    assert [s["label"] for s in body["stages"]] == \
        ["上传试卷", "分析完成", "报告打开", "答题练习", "批改回传"]

    # 全套件语境下，此前测试遗留的 pending 任务可能被后台调度器在快照间隙
    # 翻转为 done，或其他学生新建任务——"上传/分析完成"是全局去重数，
    # 只做单调断言；其余三阶段本窗口内无其他写入方，保持精确 +1。
    for key in ("uploaded", "analyzed"):
        assert after[key] >= before[key] + 1, f"{key} 应至少 +1"
    for key in ("report_opened", "practiced", "graded"):
        assert after[key] == before[key] + 1, f"{key} 应恰好 +1"

    # 结构完整：周起始一致、每阶段占比为非负数值
    import db as _db
    from db.core import get_week_start as _gws
    assert body["week_start"] == _gws()
    for s in body["stages"]:
        assert isinstance(s["pct_of_upload"], (int, float)) \
            and s["pct_of_upload"] >= 0


def test_funnel_requires_staff(client):
    assert client.get("/api/funnel").status_code == 401


def test_public_download_writes_view_report(client, sample_student,
                                            test_db_path, monkeypatch, tmp_path):
    """公开下载报告 → audit_logs 记录 view_report（漏斗"报告打开"数据源）。"""
    import web.shared
    import db

    report_dir = tmp_path / str(sample_student) / "report_pdf"
    report_dir.mkdir(parents=True)
    (report_dir / "r.html").write_text("<html>ok</html>", encoding="utf-8")
    monkeypatch.setattr(web.shared, "UPLOAD_DIR", str(tmp_path))

    fid = db.add_file(student_id=sample_student, uploader_role="teacher",
                      file_type="report_pdf", filename="r.html",
                      original_filename="学情分析报告.html", file_size=11,
                      mime_type="text/html", db_path=test_db_path)
    code = db.get_student(sample_student, db_path=test_db_path)["access_code"]

    r = client.get(f"/api/public/{code}/files/{fid}/download")
    assert r.status_code == 200

    conn = db.get_connection(test_db_path)
    try:
        rows = conn.execute(
            "SELECT actor_type, actor_id FROM audit_logs "
            "WHERE action='view_report' AND target_id=?", [str(fid)]).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0]["actor_type"] == "parent"
    assert rows[0]["actor_id"] == str(sample_student)
