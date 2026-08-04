# 功能开关 (Feature Flags)

## 快速恢复学校/教师功能

```bash
cd C:\Users\29095\WorkBuddy\2026-06-07-22-05-26\StepLearn
python -c "from db import set_setting; set_setting('feature_school_enabled','true'); set_setting('feature_teacher_enabled','true')"
```

## 单独控制

```bash
# 只恢复学校/班级
python -c "from db import set_setting; set_setting('feature_school_enabled','true')"

# 只恢复教师
python -c "from db import set_setting; set_setting('feature_teacher_enabled','true')"
```

## 关闭

```bash
python -c "from db import set_setting; set_setting('feature_school_enabled','false'); set_setting('feature_teacher_enabled','false')"
```

## 查看当前状态

```bash
python -c "from db import is_feature_enabled; print('school:', is_feature_enabled('feature_school_enabled')); print('teacher:', is_feature_enabled('feature_teacher_enabled'))"
```

## 开关说明

| 开关 | 默认值 | 控制范围 |
|------|--------|----------|
| `feature_school_enabled` | false | 学校CRUD、班级CRUD、班级码验证、学生注册的学校/班级/班级码字段、导航栏"班级管理"、概览页"老师工作台" |
| `feature_teacher_enabled` | false | 教师注册页、教师档案API、教师头像上传、导航栏"机构介绍" |

## 实现机制

- 存储：SQLite `settings` 表（key-value），通过 `db.py` 的 `get_setting()` / `set_setting()` 读写
- 默认值：`db.py` 中 `FEATURE_FLAGS` 字典，数据库无记录时使用默认值
- 后端守卫：`web/shared.py` 的 `@feature_required('flag_name')` 装饰器，关闭时API返回404
- 前端渲染：Jinja `{% if feature_school %}` / `{% if feature_teacher %}` 条件控制导航按钮和页面区块
- 学生注册：班级码改为可选，`feature_school_enabled=false` 时注册只需姓名+手机号+密码

## 代码位置（P3-15）

自 2026-08-04 起，全部 18 个 B 端路由已从 `api/ops_api.py` / `web/pages.py` 隔离到独立的
**`b_end/routes.py`（`b_end_bp` 蓝图）**。C 端最小闭环主链路不再包含任何学校/班级/教师代码；
打开上方 flag 即整体恢复，无需改代码。

## 涉及路由（共18个）

**feature_school_enabled 控制（11个）：**
- GET `/api/schools/search`
- GET `/api/classes`
- POST `/api/class/verify-code`
- GET `/api/my-classes`
- GET `/api/class/<id>/stats`
- GET `/api/class/<id>/students`
- GET|POST `/api/schools`
- PUT|DELETE `/api/schools/<id>`
- GET|POST `/api/admin/classes`
- PUT|DELETE `/api/admin/classes/<id>`
- POST `/api/teacher/create-class`

**feature_teacher_enabled 控制（7个）：**
- GET `/teacher-register`
- POST `/api/teacher-register`
- GET `/api/teacher/my-school`
- GET `/api/teacher-profile`
- POST `/api/teacher-profile`
- POST `/api/teacher-profile/avatar`
- GET `/uploads/teacher/<path>`

## 改动日期

2026-07-23 — 根据凯哥建议，先不碰学校端，只从学生和家长端入手
