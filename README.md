# 拾阶而上 · StepLearn

家长驱动的 AI 个性化学习系统。家长拍一张试卷照片，系统自动完成 OCR、错题分析、针对性练习生成与周报，让家长看见孩子的成长，让孩子减少盲目刷题。

> **核心价值链**：家长拍照 → AI 自动分析 → 家长看到进步、肯定成长 → 孩子拿到针对性练习 → 错题本越读越薄。
>
> **错因因果链**（2026-08-05）：诊断从"哪里不会"升级为"为什么不会、先补什么"。每道错题归因到受控五类（词汇/语法/句法/语篇/审题），聚合出核心瓶颈与传导链；方案与周报按"根因优先、非错误率优先"聚焦，跨周对比生成"卡点变化"进步叙事。
>
> 架构模式：**单租户自营**（非多租户 SaaS）。当前为 C 端最小闭环模式，学校/教师功能由 feature flag 封存（见 `FEATURE_FLAGS.md`）。

---

## 核心链路

```
建档 → 入学诊断(周期0) → 周循环(周期1..N) → 月度总结
                          │
                          ▼
              ocr → analyze → plan → analysis_report → exercises
                          │
                          ▼
              【错题本】核心资产（连对 2 次即掌握，越读越薄）
                          │
                          ▼
              周报（周六条件自动）· 周错题本（周一）· 月度总结（每月 1 日）
```

- **Cycle 状态机**：每个「学生 × 周 × 类型（diagnostic/weekly）」是一个学习周期，状态线性推进：`created → paper_received → ocr_done → graded → analyzed → report_ready → exercised → reported`。
- **声明式流水线**：一条链、多个恢复点。运营端三按钮（批改试卷 / 矩阵分析 / 生成周报）= 链上三个恢复点；家长上传 = 从 `ocr` 一次跑完。
- **质量回路**（替代已删除的审核闸门）：AI 结果直通家长；随机抽检（safety-checks）+ 老师逐条纠错（corrections，纠错模式自动回流到后续 prompt）。

---

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3 + Flask（app.py 仅装配层，路由拆分为蓝图） |
| 数据库 | SQLite（WAL 模式），单文件 `data.db` |
| 异步任务 | `threading` + `queue.Queue`（3 worker + 按学生串行锁 + 僵尸任务自愈） |
| LLM | Anthropic / OpenAI 兼容 API（当前接 Kimi/MiniMax） |
| OCR | 多模态 vision LLM + Tesseract.js 自动降级 |
| 前端 | 原生 HTML/CSS/JS（模板位于 `web/templates_*.py`） |

---

## 快速开始

### 1. 安装依赖

```powershell
pip install -r requirements.txt
```

### 2. 配置环境变量

```powershell
copy .env.example .env
# 编辑 .env，填入 API key
```

示例配置（Kimi）：

```text
ANTHROPIC_BASE_URL=https://api.kimi.com/coding/
ANTHROPIC_API_KEY=sk-...
LLM_MODEL=kimi-k2.6
VISION_MODEL=kimi-k2.6
OCR_BACKEND=auto
```

### 3. 初始化管理员并启动

```powershell
python app.py create-admin admin 你的密码 admin
python app.py
```

访问 http://127.0.0.1:5000 登录运营后台。首次启动自动执行数据库建表与迁移（幂等）。

---

## 常用命令

| 命令 | 说明 |
|------|------|
| `python app.py` | 启动 Flask 服务 |
| `python app.py create-admin <用户名> <密码> <role>` | 创建账号（role: `admin` / `teacher`） |
| `python app.py list-admins` | 列出所有账号 |
| `python app.py reset-password <用户名> <新密码>` | 重置密码 |
| `python -m pytest tests/ -v` | 运行测试 |

---

## 项目结构

```
StepLearn/
├── app.py                  # 装配层：Flask 实例 + 蓝图注册 + 流水线注册 + CLI（~240 行）
├── web/                    # 页面与共享层
│   ├── pages.py            #   页面蓝图（登录/注册/运营后台/家庭端）
│   ├── shared.py           #   装饰器、共享辅助、UPLOAD_DIR/VERSION
│   └── templates_*.py      #   内联 HTML 模板（admin/auth/family）
├── api/                    # API 蓝图
│   ├── family_api.py       #   家庭端：上传/练习/报告/转介绍/公开页
│   └── ops_api.py          #   运营端：学生/任务/质量/成本/合规/运维
├── b_end/                  # B 端封存层（feature flag 守卫，默认关闭）
│   └── routes.py           #   学校/班级/教师机构路由
├── domain/                 # 领域服务（不碰 HTTP，可单测）
│   ├── cycle.py            #   ★ Cycle 状态机
│   ├── upload.py           #   统一上传服务（存文件→额度闸门→建任务）
│   ├── quota.py            #   订阅额度统一闸门
│   └── questions.py        #   取题服务（收拢三处重复逻辑）
├── pipeline/               # AI 流水线
│   ├── engine.py           #   ★ 声明式链执行器（恢复点 + 断点续跑）
│   ├── stages.py           #   链节点：ocr/analyze/plan/analysis_report/exercises/weekly_report
│   ├── snapshots.py        #   快照任务：练习批改/周错题本/月度总结
│   ├── cycle_pipeline.py   #   统一 handler（onboarding + weekly）
│   └── scheduler.py        #   调度器：周六条件周报/周一错题本/月度总结
├── pipeline_worker.py      # 任务队列 + worker 池（僵尸恢复/退额度/抽检）
├── db.py                   # SQLite 数据层（唯一数据源，35 表，含 cause_profiles 错因画像）
├── llm.py                  # LLM 抽象：重试/schema 校验/缓存/成本计费/demo 模式
├── skills_bridge.py        # OCR + LLM 业务封装（prompt 库 + 错因因果链分析）
├── report_templates.py     # HTML/PDF 报告渲染（含错因画像/卡点变化板块）
├── ocr_wrapper.js          # Tesseract.js 包装脚本
├── tessdata/               # OCR 语言包（.traineddata.gz）
├── tests/                  # pytest 测试（90 用例）
├── uploads/<student_id>/   # 学生上传文件与产出报告
├── backups/                # 自动备份（每日 03:00）
├── archive/                # 归档：历史测试产物与备份
└── scripts/archive/        # 归档：一次性数据修复脚本
```

---

## 三个界面

| 界面 | 入口 | 说明 |
|------|------|------|
| 运营后台 | `/`（需登录） | 学生管理、流水线触发、质量回路（抽检+纠错）、成本与合规 |
| 家庭端学习中心 | `/s/<access_code>`（免登录） | 报告、在线练习、错题本、周报、成就墙、复盘、打卡 |
| 学情体检（首访） | `/parent` | 家长首次拍照 → 自动建档 → 诊断 → 获得专属链接 |

学生注册/登录后也统一进入 `/s/<access_code>`。

---

## 订阅与额度

| 套餐 | 价格 | 月额度 | 说明 |
|------|------|--------|------|
| trial 体验 | ¥0 | 1 | 1 次入学诊断 |
| basic 基础版 | ¥99/月 | 8 | 每周 1 套卷完整循环 |
| premium 托管版 | ¥299/月 | 16 | 每周 2 套卷 + 即时结果 |

- 仅 OCR 重阶段（批改试卷）消耗额度；矩阵分析/周报免费；运营账号豁免。
- 任务失败自动退还额度（quota_charged 标记）。

---

## 配置说明

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `ANTHROPIC_API_KEY` | 无 | Anthropic 或 Kimi 兼容接口的 API key |
| `ANTHROPIC_BASE_URL` | 无 | 自定义 Anthropic 端点（Kimi：`https://api.kimi.com/coding/`） |
| `LLM_API_KEY` / `LLM_BASE_URL` | 无 | OpenAI 兼容接口（DeepSeek/Qwen/GLM 等） |
| `LLM_MODEL` | `deepseek-chat` | 默认文本模型 |
| `VISION_MODEL` | `LLM_MODEL` | OCR 视觉模型，生产建议显式设置 |
| `OCR_BACKEND` | `auto` | `auto`=先 vision 后 Tesseract；`vision`/`tesseract` 强制 |
| `LLM_CACHE_ENABLED` | `false` | 开发缓存开关 |
| `FLASK_SECRET_KEY` | 内置 dev key | 生产环境必须替换 |
| `WEEKEND_ENGLISH_DB` | `data.db` | SQLite 路径（测试用于指定临时库） |

无任何 API key 时自动进入 demo 模式（返回占位数据，可跑通全流程）。

---

## 数据合规

- **家长授权**：`parent_consents` 记录；未授权学生在合规页与仪表盘提醒。
- **数据删除**：家长可通过公开页提交删除申请；管理员执行软删除。
- 所有授权/删除/敏感操作写入 `audit_logs`。

---

## 详细文档

- [`核心链路架构设计.md`](核心链路架构设计.md)：顶层设计、决策记录、P1-P3 实施记录
- [`功能模块与核心流程梳理.md`](功能模块与核心流程梳理.md)：现状全景梳理
- [`DEVELOPMENT.md`](DEVELOPMENT.md)：数据模型、API 概览、开发约定
- [`FEATURE_FLAGS.md`](FEATURE_FLAGS.md)：B 端功能封存与恢复方式
- [`错因因果链实施方案.md`](错因因果链实施方案.md)：受控错因分类 + 因果链画像的设计与实施记录
- [`错因校准报告.md`](错因校准报告.md)：首轮运营校准（83 条真实错题回测）

---

## 注意事项

- `.env` 不要提交到版本控制。
- worker 池按学生串行、跨学生并行；同学生任务排队执行。
- OCR 成本按 token 估算计入 `llm_usage_log`，建议定期与真实账单校准。
- 数据库迁移在 `init_db()` 中幂等执行；重大变更前先手动备份 `data.db`。
