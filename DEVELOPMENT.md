# 拾阶而上 · StepLearn — 开发文档

> 家长驱动的 AI 个性化学习系统。家长拍照 → AI 自动分析 → 家长看见成长 → 孩子针对性练习 → 错题本越读越薄。

**最后更新：** 2026-08-04（P1-P3 收敛重构后）
**架构模式：** 单租户自营（非多租户 SaaS）
**产品形态：** C 端最小闭环（学校/教师功能由 feature flag 封存，见 `FEATURE_FLAGS.md`）

---

## 1. 产品定位

| 维度 | 说明 |
|------|------|
| 目标用户 | 高中生家庭（自营，单租户） |
| 付费方 | 家长（trial 3 次 → ¥39/月 monthly 40 次 → ¥399/年 yearly 600 次） |
| 使用方 | 家长（拍照/看报告/陪学）、学生（在线练习/看错题本）、运营者（后台保障链路运转） |
| 核心价值 | 家长看见并肯定孩子的成长；孩子减少盲目刷题 |
| 关键决策 | 老师/学校**不是**核心角色；审核闸门已移除，AI 结果直通家长，质量由抽检+纠错回路保障 |

---

## 2. 技术栈

| 层 | 选型 | 说明 |
|----|------|------|
| 后端 | Python 3 + Flask | app.py 仅装配层（~240 行），路由拆分为蓝图 |
| 数据库 | SQLite（WAL + busy_timeout=15000） | 单文件 `data.db`，35 张表，`db.py` 唯一数据源 |
| 异步任务 | `threading` + `queue.Queue` | 3 worker + 按学生串行锁 + 僵尸任务自愈 + 失败退额度 |
| LLM | Anthropic / OpenAI 兼容 API | 当前接 Kimi/MiniMax；无 key 自动 demo 模式 |
| OCR | 多模态 vision LLM + Tesseract.js 降级 | 手写试卷专用 prompt；`ocr_wrapper.js` 封装 Tesseract |
| 前端 | 原生 HTML/CSS/JS | 模板位于 `web/templates_*.py`（内联字符串），无构建步骤 |
| 报告 | 服务端渲染 HTML | 练习卷另有 PDF 导出（report_templates.render_exercise_pdf） |

**外部依赖：** `flask`、`anthropic`（或 `openai`）、`Pillow`、Node + `tesseract.js`。见 `requirements.txt`。

---

## 3. 系统架构

```
┌────────────────────────────────────────────────────────────┐
│ app.py — 装配层：Flask 实例 + 蓝图注册 + CLI + 备份调度      │
└──────────────────────────┬─────────────────────────────────┘
        ┌──────────────┬───┴────────┬──────────────┐
┌───────▼──────┐ ┌──────▼─────┐ ┌────▼─────┐ ┌─────▼─────┐
│ web/pages.py │ │api/family_ │ │api/ops_  │ │b_end/     │
│ 页面蓝图      │ │api.py      │ │api.py    │ │routes.py  │
│ (登录/后台/  │ │ 家庭端 API  │ │ 运营端API │ │ B端封存层  │
│  家庭端页面) │ │             │ │          │ │(flag 守卫)│
└──────────────┘ └──────┬─────┘ └────┬─────┘ └───────────┘
                        │  domain/   │
              ┌─────────▼─────────────▼─────────┐
              │ domain/ — 领域服务（不碰 HTTP）   │
              │  cycle(状态机) upload quota      │
              │  questions                       │
              └─────────┬───────────────────────┘
                        │ enqueue_task()
              ┌─────────▼───────────────────────┐
              │ pipeline_worker.py               │
              │  队列+3worker+按学生锁+僵尸恢复   │
              │  +失败退额度+完成抽检             │
              └─────────┬───────────────────────┘
                        │ handler(cycle_pipeline.register)
              ┌─────────▼───────────────────────┐
              │ pipeline/                        │
              │  engine(声明式链+恢复点+续跑)    │
              │  stages(6节点) snapshots(3快照)  │
              │  scheduler(周六周报/周一/月度)   │
              └─────────┬───────────────────────┘
              ┌─────────▼───────────┐  ┌──────────────────┐
              │ skills_bridge.py    │  │ report_templates │
              │ (OCR+LLM 业务封装)  │  │ (报告渲染)       │
              └─────────┬───────────┘  └──────────────────┘
              ┌─────────▼───────────┐  ┌──────────────────┐
              │ llm.py              │  │ db.py            │
              │ (重试/校验/缓存/计费)│  │ (唯一数据源)     │
              └─────────────────────┘  └──────────────────┘
```

**设计要点：**
- **Cycle 状态机**（`domain/cycle.py`）：`(student_id, week_start, kind)` 唯一；kind=diagnostic|weekly；状态线性推进、只进不退、advance 幂等。物理存储于 `weekly_records`（P1 迁移加 kind/stage 列）。
- **声明式流水线**（`pipeline/engine.py`）：链 `ocr → analyze → plan → analysis_report → exercises`；weekly_report 独立节点。外部 stage 参数（full/grade_only/analysis_only）映射为链起点；僵尸复活按 cycle.stage 断点续跑。
- **统一闸门**：上传走 `domain/upload.py`（存文件→额度→建任务），额度走 `domain/quota.py`，取题走 `domain/questions.py`。
- LLM 无 key → demo 模式（占位数据跑通全流程，测试依赖此特性）。

---

## 4. 数据模型（35 张表）

**核心实体**
- `students` — 学生档案（姓名/年级/教材版本 textbook_version/access_code/parent_access_code/手机号密码；注册时采集年级与教材版本）
- `student_profiles` — 40+ 字段个性化画像（六大部分 + 测评 + 方案抉择 + 家长任务进度）

**周期与流程**
- `weekly_records` — **Cycle 表**：(student_id, week_start, kind) 唯一；stage 状态机 + 兼容布尔标记（paper_submitted/paper_analyzed/exercises_sent/exercises_completed/exercises_graded/report_sent）
- `ai_tasks` — AI 任务（类型/状态/进度/输入输出/cycle_id/错误信息；needs_review 列保留但恒 0）
- `files` — 文件元数据（uploads/<student_id>/<file_type>/ 组织）

**教学（错题本是核心资产）**
- `mistakes` — 错题（题干/答案/知识点/难度/consecutive_correct；连对 2 次即掌握；**error_cause/cause_evidence** 受控五类错因归因，未作答不进统计）
- `practice_records` — 作答记录；`practice_sessions` — 考试会话
- `questions` — 题库（source_mistake_id 溯源；usage_count 复用计数）
- `learning_plans` — 方案+薄弱矩阵；`plan_updates` — 方案更新史（AI 诊所）
- `score_history` — 分数趋势；`check_ins` — 打卡
- `cause_profiles` — **错因因果链画像**（每学生一条：核心瓶颈/传导链/根因聚焦知识点/家长一句话，LLM+统计兜底）
- `cause_profile_history` — 画像周历史（student_id+week_start 唯一，跨周"卡点变化"叙事数据源）

**商业**
- `subscriptions`（套餐/月额度/used_count/reset_month）、`payments`、`referrals`

**质量回路**
- `aigc_safety_checks` — 抽检；`ai_corrections` — 纠错；`ai_feedback_patterns` — 纠错模式沉淀（回流 prompt）

**合规与可观测**
- `parent_consents`、`deletion_requests`、`audit_logs`、`alerts`、`backups`、`llm_usage_log`

**账号与设置**
- `admin_users`（role: admin/teacher）、`sms_codes`、`settings`（KV：预算/feature flag 等）

**B 端封存**
- `schools`、`classes`、`teacher_profile`（feature flag 关闭时不使用）

关键关系：`students` 1→N 几乎所有表；`ai_tasks.cycle_id` → `weekly_records`；`questions.source_mistake_id` → `mistakes`（掌握度回写链路）；`ai_tasks` 1→N `llm_usage_log`（成本归集）。

---

## 5. 核心流程

### 家长核心链路（产品生命线）
```
拍照上传(/api/public/<code>/upload) → 额度闸门 → grade_only 任务
  → [worker] ocr → analyze → plan → analysis_report → exercises（一次任务跑完）
  → 家长轮询 /api/public/<code>/task/<id> → 学习中心呈现报告+练习+错题本
```
首访家长走 `/parent`（学情体检）：自动建档（trial 1 次额度）→ onboarding 诊断 → 获得 access_code。

### 运营端三按钮（= 链上恢复点）
- 批改试卷 `grade_only`：ocr 起点（需照片，消耗额度）
- 矩阵分析 `analysis_only`：plan 起点（免费）
- 生成周报 `report_only`：weekly_report 独立节点（免费；周六调度器条件自动）

### 练习闭环
- 在线：练习 tab 取未掌握错题关联题（domain/questions）→ 即时判对错 → record_practice → 连对 2 次掌握
- 纸面：`grade_exercises` 快照任务（OCR 答案 → AI 批改 → 掌握度回写 → 反馈报告 + 成绩记录）

### 自动化调度（pipeline/scheduler.py）
- 周一 08:00 后：全体活跃学生周错题本（DB 级当日去重）
- 每月 1 日 08:00 后：月度总结
- 周六 08:00 后：**条件式周报** —— 本周有分析数据才出，避免空报
- 每日 03:00：数据库自动备份（app.py 备份调度线程）

### 质量回路（替代审核闸门）
```
任务完成 → 随机抽检 2 条入 aigc_safety_checks → 老师过审
老师纠错（运营后台「周度服务 → 历史任务 → 纠错」）→ ai_corrections
         → ai_feedback_patterns 沉淀 → 后续 prompt 自动注入纠错提示
```

---

## 6. Pipeline 输入/输出结构

`POST /api/pipeline/run`（运营端）或统一上传服务（家庭端）创建任务；前端轮询 `GET /api/tasks/<id>` / `/api/public/<code>/task/<id>`。

### 触发请求体（/api/pipeline/run）
```jsonc
{
  "student_id": 14,
  "task_type": "onboarding" | "weekly",
  "file_ids": [26],                  // 试卷照片（ocr 起点需要）
  "stage": "full" | "grade_only" | "analysis_only" | "report_only"
           | "grade_exercises" | "weekly_mistake_book" | "monthly_summary"
}
// 返回: { "task_id": 20 }  HTTP 202
```

### 分析链输出（ocr 起点：full / grade_only）
```jsonc
{
  "needs_review": false,        // 恒 false（审核闸门已移除）
  "student_id": 14,
  "exercise_file_id": 27,       // 练习卷 HTML file_id（无题为 null）
  "report_file_id": 31,         // 分析报告 HTML file_id
  "mistakes_count": 10,
  "questions_count": 12,        // 每错题 2 题，不设总量上限（2026-08-04 起）
  "session_id": 8,
  "mistake_ids": [201, 202],
  "stage": "exercises_ready"    // plan 起点时为 "analysis_done"
}
```

### grade_exercises 输出
```jsonc
{
  "needs_review": false,
  "student_id": 14,
  "feedback_file_id": 32,
  "correct_count": 6, "total_count": 10, "accuracy": 0.6,
  "stage": "exercise_graded"
}
```

### weekly_report / 快照输出
```jsonc
{ "needs_review": false, "student_id": 14,
  "weekly_report_file_id": 40, "stage": "report_done" }
```

> 任务失败：`status="failed"`，error_message 含 traceback 前 5 帧；quota_charged 任务失败自动退额度。

---

## 7. API 概览（按蓝图）

**页面（web/pages）**：`/`（运营后台）、`/login`、`/register`、`/student-login`、`/s/<code>`（家庭端）、`/parent`（学情体检）

**家庭端（api/family_api）**：
- 认证：`/api/register`（body: name/phone/password/grade/textbook_version，班级码存在时年级以班级为准）、`/api/student-login`、`/api/sms/*`
- 公开页（code 作用域）：`/api/public/<code>/*` — upload / task / reports / practice(+submit) / exercise-pdf / review / timeline / achievements / checkins / progress / request-deletion
- 家长：`/api/parent/diagnose`、`/api/parent/task/<id>`、`/api/parent/progress/<code>`
- 转介绍：`/api/referrals/*`、`/api/poster/<code>`

**运营端（api/ops_api）**：
- 仪表盘/成本/状态：`/api/dashboard`、`/api/cost`、`/api/status`
- 学生管理：`/api/students*`、`/api/students/<id>/profile|mistakes|analytics|reviews`
- 流水线/任务：`/api/pipeline/run`、`/api/tasks*`、`/api/weekly`
- 质量回路：`/api/tasks/<id>/correctables|corrections`、`/api/corrections/*`、`/api/safety-checks/*`
- 商业：`/api/subscriptions*`、`/api/payments`、`/api/budget`
- 题库：`/api/questions*`；学情：`/api/learning/*`
- 运维：`/api/alerts*`、`/api/admin/alert-settings`、`/api/audit-logs*`、`/api/backups*`
- 合规：`/api/compliance/*`；文件：`/api/upload`、`/api/files/<id>/download`

**B 端封存（b_end/routes，flag 守卫）**：学校/班级 CRUD、班级码、教师注册与档案（18 条路由，见 FEATURE_FLAGS.md）

---

## 8. 开发约定

### 测试
- `python -m pytest tests/`（55 用例）；fixture 见 `tests/conftest.py`
- **conftest 关键约定**：`test_db_path` 在 fixture 内设置 `WEEKEND_ENGLISH_DB` 后才 import db。**所有测试必须在函数内惰性导入 db/domain/pipeline 模块**，模块顶层导入会让 DB_PATH 绑定到生产库（曾造成测试数据污染事故）。
- demo 模式测试用 `demo_mode` fixture；会话级共享测试库，注意测试间数据隔离（唯一知识点名等）。

### 代码组织
- 新领域逻辑 → `domain/`（不碰 HTTP，可单测）；新路由 → 对应蓝图
- db_path 参数默认惰性解析（`db_path or db.DB_PATH`），不在模块顶层冻结
- 模板是 `web/templates_*.py` 中的字符串常量（含 Jinja 条件），render_template_string 渲染

### 迁移
- schema 变更走 `db.py::_migrate_db`（幂等）；建表语句在 `init_db`
- weekly_records 表结构变更需谨慎：它是 Cycle 状态机本体

---

## 9. 已知技术债

| 优先级 | 问题 | 影响 |
|--------|------|------|
| 🟡 中 | `llm.py::_default_client` 全局单例 | 多 worker 竞态（历史遗留） |
| 🟡 中 | 报告为 HTML（仅练习卷有 PDF） | 家长手机端体验一般 |
| 🟡 中 | `sms.py` 为 mock（验证码打印控制台） | 上线家长手机号体系前必须接真实服务商 |
| 🟢 低 | 模板内联 JS 巨大（templates_admin ~4000 行） | 前端改动需小心；暂无组件化计划 |
| 🟢 低 | b_end/routes.py 内个别休眠 bug（如 avatar 上传参数） | flag 开启时才会暴露 |

---

## 10. 重构历史

| 日期 | 里程碑 | 说明 |
|------|--------|------|
| 2026-06-21 前 | Phase 1-5 | 老师主导的完整系统（审核流/班级/看板/合规/可观测） |
| 2026-07-23 | C 端转型 | 凯哥建议：跳过学校渠道；feature flag 封存 B 端 |
| 2026-07-24 | 产品再定位 | 家长驱动链路确认（拍照→报告→练习→错题本） |
| 2026-08-04 | **P1 收敛后端** | Cycle 状态机、声明式链、自动链 hack 移除、审核闸门移除、统一额度闸门、周六条件周报 |
| 2026-08-04 | **P2 收敛界面** | 家庭端合并（/parent 首访 + /s/<code> 学习中心）、统一上传服务、链路状态可见、app.py 拆蓝图（9949→237 行） |
| 2026-08-04 | **P3 清理固化** | 审核队列代码删除、取题收拢 domain/questions、B 端隔离 b_end/、_migrate_db 重复修复、杂物归档、文档重写 |

详见 `核心链路架构设计.md`（决策记录与实施细节）。
