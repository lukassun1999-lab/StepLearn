#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日志初始化（2026-08 第 3 周提交 2）：标准库 logging，零新依赖。

约定：
- 各模块 `log = logging.getLogger(__name__)`，层级挂在根 logger 下。
- setup_logging() 在 app 导入时调用一次（幂等，重复调用无副作用）。
- 输出：stderr（gunicorn/systemd 采集）+ logs/app.log 轮转文件
  （1MB × 5 份）。LOG_LEVEL 环境变量控制级别，默认 INFO。
- logs/ 目录在 .gitignore；创建失败（只读卷等）不阻断启动。
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup_logging() -> None:
    """配置根 logger（幂等）。测试环境重复 import app 不会叠加 handler。"""
    global _configured
    if _configured:
        return
    _configured = True

    level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(),
                    logging.INFO)
    formatter = logging.Formatter(_LOG_FORMAT, _DATE_FORMAT)

    root = logging.getLogger()
    root.setLevel(level)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    root.addHandler(console)

    # 轮转文件（尽力而为：目录不可写则跳过，仅控制台输出）
    try:
        log_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "logs")
        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, "app.log"),
            maxBytes=1024 * 1024, backupCount=5, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        root.warning("logs/ 目录不可写，仅输出到 stderr", exc_info=True)

    # 三方库降噪：werkzeug 每请求两条 INFO 太吵
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


def reset_logging_for_tests() -> None:
    """测试辅助：清空根 handler，恢复未配置状态。"""
    global _configured
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    _configured = False
