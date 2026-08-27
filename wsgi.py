#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WSGI 入口（gunicorn / uwsgi 使用）。

⚠️ 单进程约束：任务队列（queue.Queue）、流水线 worker 线程、调度器
均为进程内存态，gunicorn 必须只起 1 个 worker（多 worker 会导致
任务重复消费与调度重复触发）。并发靠线程：

    gunicorn --workers 1 --threads 8 --timeout 120 \
        --bind 127.0.0.1:8000 wsgi:app

导入 app 即触发 init_db 迁移 + worker/调度器启动（与 python app.py 一致）。
"""

from app import app
from db import init_db

# 通过 gunicorn 启动时 __name__ != "__main__，init_db() 不会在 app.py 的
# __main__ 分支执行，这里显式调用以幂等创建所有表（IF NOT EXISTS 安全）。
init_db()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000)
