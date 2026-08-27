# -*- coding: utf-8 -*-
"""公开访问码暴力枚举防护回归测试。

背景：/api/public/<code>/* 端点全部经 _resolve_student_by_code 校验，
此前无效 code 只返回 404，可被无限枚举猜测有效 access_code。
防护：同一 IP 15 分钟窗口内失败达阈值 → 临时封禁（仍返回与 404 一致的
响应，不泄露 code 是否有效）。按 IP 聚合计数。
"""


def test_invalid_codes_eventually_blocked(client, sample_student, test_db_path):
    """连续无效 code 达阈值后，即使改用正确 code 也被拒（枚举被拦）。"""
    import db
    code = db.get_student(sample_student, db_path=test_db_path)["access_code"]

    # 先确认正确 code 正常
    assert client.get(f"/api/public/{code}").status_code == 200

    # 连续无效 code（换着试，模拟枚举）
    for _ in range(6):
        assert client.get("/api/public/nonexist1").status_code == 404

    # 封禁后：正确 code 也被拒（不泄露其有效性），且响应体与 404 一致
    r = client.get(f"/api/public/{code}")
    assert r.status_code == 404
    assert r.get_json()["error"] == "invalid or expired code"


def test_valid_request_clears_failures(client, sample_student, test_db_path):
    """偶发输错后成功 → 计数清零，不会误锁正常用户。"""
    import db
    code = db.get_student(sample_student, db_path=test_db_path)["access_code"]

    # 3 次失败（未达阈值）后成功 → 清零
    for _ in range(3):
        assert client.get("/api/public/nonexist").status_code == 404
    assert client.get(f"/api/public/{code}").status_code == 200

    # 再失败 5 次仍未达阈值（6 次才锁）——证明已被清零
    for _ in range(5):
        assert client.get("/api/public/nonexist").status_code == 404
    assert client.get(f"/api/public/{code}").status_code == 200


def test_different_ips_independent(client, sample_student, test_db_path):
    """限流按 IP 隔离：一个 IP 被封，不影响另一个 IP 的正常访问。"""
    import db
    code = db.get_student(sample_student, db_path=test_db_path)["access_code"]

    # IP A 连续 6 次失败 → 达到阈值被封禁
    for _ in range(6):
        client.get("/api/public/nonexist", environ_overrides={"REMOTE_ADDR": "10.0.0.1"})
    # 被封后，IP A 即使拿正确 code 也被拒（仍返回与 404 一致的响应）
    r_blocked = client.get(
        f"/api/public/{code}", environ_overrides={"REMOTE_ADDR": "10.0.0.1"})
    assert r_blocked.status_code == 404
    assert r_blocked.get_json()["error"] == "invalid or expired code"

    # IP B 独立计数，从未失败，正确 code 仍可访问
    r_ok = client.get(
        f"/api/public/{code}", environ_overrides={"REMOTE_ADDR": "10.0.0.2"})
    assert r_ok.status_code == 200


def test_all_public_code_endpoints_share_limiter(client, sample_student, test_db_path):
    """所有 code 作用域的公开端点都走限流，无侧门绕过。"""
    import db
    code = db.get_student(sample_student, db_path=test_db_path)["access_code"]

    # 未达阈值（每个端点各错 1 次，共 5 次 → 仍达不到 6，正确 code 可访问）
    side_doors = [
        "/api/public/nonexist",
        "/api/public/nonexist/achievements",
        "/api/public/nonexist/review",
        "/api/public/nonexist/timeline",
        "/api/public/nonexist/reports",
    ]
    for path in side_doors:
        assert client.get(path).status_code == 404

    # 第 6 次失败（换一个侧门）→ 达到阈值，此后正确 code 也被拒
    assert client.get("/api/public/nonexist2/practice").status_code == 404
    r = client.get(f"/api/public/{code}")
    assert r.status_code == 404
    assert r.get_json()["error"] == "invalid or expired code"


def test_proxy_trusted_production_path():
    """TRUST_PROXY_HEADERS=true（生产反代配置）下应用可启动，且限流按
    X-Forwarded-For 里的真实客户端 IP 聚合。

    回归：此前 app.py 用了 ProxyFix 但漏了 import，TRUST_PROXY_HEADERS=true
    时启动即 NameError——默认测试环境不设该变量，分支不执行，全绿掩盖了崩溃。
    """
    import os
    import subprocess
    import sys
    import tempfile

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ,
               WEEKEND_ENGLISH_DB=os.path.join(tempfile.mkdtemp(), "t.db"),
               TRUST_PROXY_HEADERS="true")
    script = (
        "from db import init_db\n"
        "init_db()\n"
        "import app\n"
        "with app.app.test_client() as c:\n"
        "    c.get('/api/public/nonexist', headers={'X-Forwarded-For': '10.9.8.7'})\n"
        "import web.shared as ws\n"
        "assert ws._code_limit.get('10.9.8.7'), ws._code_limit\n"
    )
    r = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True,
        timeout=60, env=env, cwd=project_root)
    assert r.returncode == 0, f"生产路径失败:\n{r.stderr}\n{r.stdout}"
