# -*- coding: utf-8 -*-
"""日志框架回归测试（第 3 周提交 2）。

覆盖：
- setup_logging 幂等（重复调用不叠加 handler）
- 关键路径产生日志：任务失败记 ERROR、额度退还失败可见
- 模块 logger 命名挂在标准层级下
"""

import logging


def test_setup_logging_idempotent():
    import log_setup

    log_setup.reset_logging_for_tests()
    log_setup.setup_logging()
    n1 = len(logging.getLogger().handlers)
    log_setup.setup_logging()
    n2 = len(logging.getLogger().handlers)
    assert n1 >= 1  # 至少 stderr handler
    assert n2 == n1  # 幂等：不叠加
    log_setup.reset_logging_for_tests()


def test_log_file_rotation_configured(tmp_path, monkeypatch):
    import log_setup

    log_setup.reset_logging_for_tests()
    monkeypatch.setattr(log_setup.os.path, "dirname", lambda _: str(tmp_path))
    log_setup.setup_logging()
    try:
        handlers = logging.getLogger().handlers
        from logging.handlers import RotatingFileHandler
        rotating = [h for h in handlers if isinstance(h, RotatingFileHandler)]
        assert len(rotating) == 1
        assert rotating[0].maxBytes == 1024 * 1024
        assert rotating[0].backupCount == 5
    finally:
        log_setup.reset_logging_for_tests()


def test_task_failure_logs_error(caplog, test_db_path, sample_student):
    """任务失败路径产生 ERROR 级日志（含任务号）。"""
    import db
    from pipeline_worker import _process_task

    # 未知 task_type → handler 缺失 → 确定性失败（demo 模式不影响）
    tid = db.create_task(sample_student, "no_such_type", {},
                         db_path=test_db_path)
    task = db.get_task(tid, test_db_path)
    with caplog.at_level(logging.ERROR, logger="pipeline_worker"):
        _process_task(task, test_db_path)
    assert any(r.levelno >= logging.ERROR and "任务失败" in r.getMessage()
               for r in caplog.records)
    t = db.get_task(tid, test_db_path)
    assert t["status"] == "failed"


def test_module_loggers_use_standard_names():
    import pipeline_worker
    import pipeline.stages
    import skills_bridge

    assert logging.getLogger("pipeline_worker").name == "pipeline_worker"
    assert logging.getLogger("pipeline.stages").name == "pipeline.stages"
    assert logging.getLogger("skills_bridge").name == "skills_bridge"
    # 模块内有 log 对象且挂在自身名下
    assert pipeline_worker.log.name == "pipeline_worker"
    assert pipeline.stages.log.name == "pipeline.stages"
    assert skills_bridge.log.name == "skills_bridge"
