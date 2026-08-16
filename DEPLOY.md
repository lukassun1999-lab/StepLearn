# 生产部署指南

> 适用场景：单台 Linux 服务器（2C4G 起步）自托管。整个系统单进程运行，
> 无外部消息队列/缓存依赖，SQLite + 线程池即全部基础设施。

## 架构约束（必读）

**必须单进程。** 任务队列（`queue.Queue`）、3 个流水线 worker 线程、
定时调度器（周报/备份）全部住在进程内存里。多进程（gunicorn 多 worker
或多实例）会导致：任务重复消费、额度重复扣减、周报重复发送。

并发能力靠线程：gunicorn `--workers 1 --threads 8` + 应用内
3 个 pipeline worker 线程。当前用户规模（百人级）足够。

## 1. 环境准备

```bash
# Ubuntu 22.04 为例
sudo apt update && sudo apt install -y python3-venv python3-pip
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt gunicorn
```

**服务器时区必须是 Asia/Shanghai**（业务周/月边界按本地时间统计）：

```bash
sudo timedatectl set-timezone Asia/Shanghai
```

## 2. 数据迁移清单

从开发机搬到服务器，共 4 项：

| 项 | 说明 |
|----|------|
| `data.db` | 主数据库（含订阅/额度/错题全部业务数据） |
| `uploads/` | 学生试卷照片（PIPL 敏感数据，传输走加密通道） |
| `tessdata/` | OCR 语言包（也可服务器重新下载） |
| `.env` | 密钥与 API key（**不要进 git**，服务器上 `chmod 600`） |

首次在服务器启动会自动执行 schema 迁移（幂等 ALTER TABLE，无手工操作）。

## 3. .env 生产配置

```ini
# 必改：强随机密钥（python -c "import secrets; print(secrets.token_hex(32))"）
FLASK_SECRET_KEY=<64位随机串>

# LLM（真实 key）
LLM_MODEL=kimi-k2.6
VISION_MODEL=kimi-k2.6

# HTTPS（经反向代理终结 TLS 后置 true，启用 Secure cookie）
HTTPS_ENABLED=true

# 商用收学生后开启（无监护人同意禁止上传）
# CONSENT_REQUIRED=true
```

## 4. systemd 服务

`/etc/systemd/system/steplearn.service`：

```ini
[Unit]
Description=StepLearn English
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/opt/steplearn
Environment="PATH=/opt/steplearn/venv/bin"
ExecStart=/opt/steplearn/venv/bin/gunicorn \
    --workers 1 --threads 8 --timeout 120 \
    --bind 127.0.0.1:8000 wsgi:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo chown -R www-data:www-data /opt/steplearn
sudo systemctl daemon-reload
sudo systemctl enable --now steplearn
```

注意 `--workers 1` 是硬约束（见「架构约束」）。重启即触发僵尸任务
恢复（24h 内自动续跑，超时退额度）。

## 5. HTTPS（推荐 Caddy，自动证书）

`/etc/caddy/Caddyfile`：

```
your-domain.com {
    reverse_proxy 127.0.0.1:8000
}
```

```bash
sudo apt install -y caddy
sudo systemctl reload caddy
```

证书自动申请续期，无需手工操作。nginx + certbot 方案亦可，
关键是 TLS 必须在反代层终结（gunicorn 自身不配 TLS）。

## 6. 日常运维

```bash
# 日志
sudo journalctl -u steplearn -f

# 数据库备份（backups/ 目录，调度器每日 03:00 后自动跑 + 保留策略）
# 手动备份：
python backup.py

# 创建管理账号 / 超级学生账号
python app.py create-admin <user> <pass> admin
python app.py set-super <access_code>

# 重置密码
python app.py reset-password <user> <new_pass>
```

## 7. 升级发布

```bash
cd /opt/steplearn
git pull
source venv/bin/activate
pip install -r requirements.txt
python -m pytest -q          # 有测试环境的话先跑回归
sudo systemctl restart steplearn
```

启动时自动完成 schema 迁移与僵尸任务恢复，无需停机脚本。

## 8. 安全检查清单

- [ ] `FLASK_SECRET_KEY` 已换为强随机值（.env 不进 git、chmod 600）
- [ ] `HTTPS_ENABLED=true`（Secure cookie 生效）
- [ ] gunicorn 绑定 127.0.0.1（只经反代对外）
- [ ] `.env` / `data.db` / `uploads/` 权限仅服务用户可读
- [ ] 商用阶段：`CONSENT_REQUIRED=true` + 运营端完成监护人同意登记
- [ ] 服务器防火墙仅开放 80/443（8000 不对公网）
