# UI 优化（按系统特性）：微信手机家长端为核心 + 1-2 人运营桌面端（3 个提交）

系统特性定位：家长在**微信手机浏览器**拍照上传、学生在手机练习、增长靠海报分享、运营是 1-2 人桌面用。审计发现 6 个真缺陷（不止体验问题）。

## 提交 1：双端关键缺陷修复（外科手术式）

**家长端（templates_family.py）**：
- **PARENT_PAGE `CODE` 未定义 ReferenceError**（1674/1793）——分析完成后报告链接渲染崩溃，家长永久卡在进度页。接入轮询响应中保存的 access_code 变量
- 删除重复 ID（progressCard/progressStatus/progressStep 两套，1470 起为死标记）
- 移除 `user-scalable=no`（家长读报告需缩放）
- 触控目标：.cal-nav-btn 32→40px、.mood-btn 40→44px、内联 34px 按钮提至 44px
- 字号：8px（hol-name）→11px，0.65/0.7rem 一律 ≥0.75rem
- summary 5 瓦片 3 列栅格破行 → auto-fit 响应式

**管理端（templates_admin.py）**：
- **STEPS_MAP 前缀键不匹配**（pollTask 传 'onb'/'wk'，映射表键是 'onboarding'/'weekly'）——流水线步骤列表从未渲染。修正映射并改用后端 `current_step` 真实步骤名（API 已返回，UI 一直用百分比瞎猜）
- 补 `badge-pending/processing/done/failed` CSS（现状态渲染为无边框裸文本）
- onclick 插值 XSS 修补：manageSub 等按钮的学生名未转义（1593/1781/1553/1611/1768），改 data-* + 事件委托
- 宽表格（学生 11 列、仪表盘 9 列）包 .table-wrap 横向滚动

测试：test_pages_smoke 全绿；新增断言——家长页无 CODE 引用错误结构、状态徽章 CSS 存在。

## 提交 2：家长端微信场景优化（/parent + 上传链路）

- **首访多图上传**：input 加 `multiple`，预览列表支持增删；后端 `/api/parent/diagnose` 改 `getlist`（save_files 本就接受列表，改动极小）——多页试卷现在能传了
- **年级选择**：上传前加年级选择器（高一~高三+初中），默认高二；后端已支持 form 字段，仅补前端
- **客户端图片压缩**：canvas 降采样至长边 1600px、JPEG q0.8 再上传（现在几 MB 原图直传蜂窝网络）；双端（首访+学生页上传）共用同一工具函数
- **真上传进度**：fetch 改 XHR，接 `upload.onprogress` 字节级进度（现在是假进度条跳 30%→60%）
- **轮询预算对齐**：家长页 3 分钟上限 → 10 分钟（与分析实际 5-10 分钟一致）；超时不再死错误，改为展示 `/s/<code>` 链接卡片
- **微信海报保存修复**：a.download 在微信内无效——改为弹层内嵌 `<img>` + "长按保存到相册"引导（非微信环境保留下载按钮，UA 判断）
- **分享 meta**：/s/<code> 与 /parent 补 og:title/og:description（微信分享卡片不再是裸 URL）+ theme-color

测试：后端多图接受用例（/api/parent/diagnose 传 2 文件 → 202 + file_ids 2 条）；页面冒烟含 og meta。

## 提交 3：学生页底部导航重构 + 管理端运营效率

**底部导航（/s/<code>，移动优先 IA）**：
- 顶部 9 tab → 底部导航 5 项：**首页 / 练习 / 报告 / 成长 / 我的**
- 成长 = 时间轴 + 成就墙 + 成长记录（错题本）三子区（分段控件）；我的 = 复盘 + 坚持日记 + 进度 + 数据删除申请
- 现有各 tab 渲染函数不动，只改导航壳与分组容器——风险隔离
- hash 同步：切换写 `location.hash`，刷新/返回恢复位置

**管理端**：
- 仪表盘加「进行中任务」实时条：轮询 `/api/tasks` 过滤 processing/pending（10s，页面可见时），显示学生/类型/current_step/进度——不再手动 F5 盯任务；历史表补 onboarding 任务（现在只显示 weekly）
- consent 三连 `prompt()` 改现有 modal 组件

测试：页面冒烟（底部导航存在、5 项、hash 恢复脚本存在）；现有 249 用例全绿。

## 明确不做（说明）

- 深色模式：目标用户场景收益低，留待有真实需求
- 管理端 onboarding 表单与学生 modal 合并、词库外移：重构项非 UI 优化，下批次
- 微信 JS-SDK（自定义分享卡片/选图）：需公众号备案与域名，先 og meta 兜底

## 验收

每提交全量 pytest 全绿 + 应用启动冒烟；家长页核心流程（上传→轮询→报告链接）与管理端（上传→步骤列表→状态徽章）代码级复查。