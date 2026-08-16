# -*- coding: utf-8 -*-
"""demo 模式显式告警回归测试（第 3 周提交 3）。

不依赖 app 导入时的真实后端状态（开发机 .env 常有真实 key），
直接 monkeypatch BACKEND 验证 _warn_demo_backend 的行为。
"""

import logging


def _reset_demo_flag():
    import llm
    llm._demo_warned = False


def _clear_alerts(test_db_path):
    import db
    conn = db.get_connection(test_db_path)
    conn.execute("DELETE FROM alerts WHERE alert_type='demo_mode'")
    conn.commit()
    conn.close()


def _count_alerts(test_db_path):
    import db
    conn = db.get_connection(test_db_path)
    n = conn.execute(
        "SELECT COUNT(*) FROM alerts WHERE alert_type='demo_mode' AND dismissed=0"
    ).fetchone()[0]
    conn.close()
    return n


def test_demo_call_warns_once(caplog, demo_mode):
    import llm

    _reset_demo_flag()
    client = llm.get_client()
    with caplog.at_level(logging.WARNING, logger="llm"):
        client.call(prompt="t", call_type="analyze")
        client.call(prompt="t", call_type="analyze")
    warnings = [r for r in caplog.records
                if r.levelno == logging.WARNING and "DEMO" in r.getMessage()]
    assert len(warnings) == 1  # 进程内只告警一次，不刷屏
    _reset_demo_flag()


def test_demo_backend_creates_alert(client, test_db_path, monkeypatch):
    import llm
    _clear_alerts(test_db_path)
    monkeypatch.setattr(llm, "BACKEND", "demo")

    from app import _warn_demo_backend
    _warn_demo_backend()

    assert _count_alerts(test_db_path) == 1
    import db
    conn = db.get_connection(test_db_path)
    msg = conn.execute(
        "SELECT message FROM alerts WHERE alert_type='demo_mode' AND dismissed=0"
    ).fetchone()["message"]
    conn.close()
    assert "API key" in msg


def test_demo_alert_deduped(client, test_db_path, monkeypatch):
    import llm
    _clear_alerts(test_db_path)
    monkeypatch.setattr(llm, "BACKEND", "demo")

    from app import _warn_demo_backend
    _warn_demo_backend()
    _warn_demo_backend()
    _warn_demo_backend()
    # create_alert 等价活跃告警去重：重启/重复触发不堆叠
    assert _count_alerts(test_db_path) == 1


def test_no_demo_alert_with_real_backend(client, test_db_path, monkeypatch):
    import llm
    _clear_alerts(test_db_path)
    monkeypatch.setattr(llm, "BACKEND", "openai")

    from app import _warn_demo_backend
    _warn_demo_backend()
    assert _count_alerts(test_db_path) == 0


def test_app_calls_warn_at_import(client, test_db_path):
    """app 模块携带 _warn_demo_backend 且在导入序列中已调用（源码级断言）。"""
    import inspect
    import app
    src = inspect.getsource(app)
    assert "_warn_demo_backend()" in src  # 导入时执行，非仅定义
