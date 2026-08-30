# -*- coding: utf-8 -*-
"""doctor 运行体检冒烟测试（demo 模式，不发起真实 API 调用）。"""

import pytest

import llm


def test_doctor_smoke(monkeypatch, test_db_path, capsys):
    import app
    monkeypatch.setattr(llm, "BACKEND", "demo")  # 跳过 LLM 连通性探测

    rc = app._cli_doctor()
    out = capsys.readouterr().out

    assert rc in (0, 1)
    assert "拾阶而上" in out
    assert "体检完成" in out
    # 关键体检板块齐全
    for section in ("▶ LLM", "▶ OCR", "▶ 数据库", "▶ 备份", "▶ 磁盘与目录",
                    "▶ 生产配置"):
        assert section in out
    assert "[FAIL]" in out or "[OK]" in out  # 至少有结论输出
