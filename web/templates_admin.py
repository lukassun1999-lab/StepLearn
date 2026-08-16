# -*- coding: utf-8 -*-
"""运营后台页面模板（P2-12 自 app.py 拆出）。"""

MAIN_PAGE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>拾阶而上 · 管理系统</title>
<link rel="icon" href="data:,">
<style>
:root {
  --bg: #f8f7f4; --bg-alt: #f1f0ec; --card: #fff;
  --text: #1a1a1a; --text-alt: #37352f; --sub: #6b6b6b; --mute: #9b9b9b;
  --accent: #e07b4b; --accent-hover: #d06a3a; --accent-light: #fef3ed;
  --green: #0f7b4e; --green-light: #effaf3;
  --red: #d93a46; --red-light: #fef4f4;
  --blue: #4b8dc7; --blue-light: #eef5fb;
  --border: #e8e6e1; --shadow-sm: 0 1px 2px rgba(0,0,0,.03);
  --shadow: 0 1px 3px rgba(0,0,0,.06), 0 2px 8px rgba(0,0,0,.02);
  --shadow-lg: 0 4px 24px rgba(0,0,0,.08);
  --radius: 8px;
}
* { margin:0; padding:0; box-sizing:border-box; }
@keyframes spin { to { transform:rotate(360deg); } }
body { font-family: ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; background:var(--bg); color:var(--text-alt); line-height:1.6; font-size:.875rem; }
.header { background:var(--card); border-bottom:1px solid var(--border); padding:0 20px; display:flex; align-items:center; height:56px; }
.header h1 { font-size:1.1rem; color:var(--accent); margin-right:auto; font-weight:700; }
.nav { display:flex; gap:2px; overflow-x:auto; -webkit-overflow-scrolling:touch; flex:1; margin:0 12px; }
.nav button { padding:8px 14px; border:none; background:none; border-radius:6px; cursor:pointer; font-size:.8rem; color:var(--sub); white-space:nowrap; transition:all .15s; }
.nav button:hover { background:var(--bg-alt); color:var(--text); }
.nav button.active { background:var(--accent-light); color:var(--accent); font-weight:600; }
.main { max-width:1200px; margin:0 auto; padding:24px 20px; }
.page { display:none; }
.page.active { display:block; }
h2 { font-size:1.15rem; font-weight:600; line-height:1.4; margin-bottom:16px; border-left:3px solid var(--accent); padding-left:12px; color:var(--text); }
.stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:16px; margin-bottom:24px; }
.stat { background:var(--card); border:none; border-radius:10px; padding:20px; box-shadow:var(--shadow); transition:box-shadow .2s; }
.stat:hover { box-shadow:var(--shadow-lg); }
.stat .num { font-size:1.6rem; font-weight:700; color:var(--text); }
.stat .label { font-size:.75rem; color:var(--sub); margin-top:4px; }
.stat.warn .num { color:var(--red); }
.stat.ok .num { color:var(--green); }
.stat.info .num { color:var(--blue); }
table { width:100%; border-collapse:collapse; background:var(--card); border-radius:10px; overflow:hidden; box-shadow:var(--shadow); }
th { background:var(--bg-alt); padding:10px 14px; text-align:left; font-size:.8rem; color:var(--sub); font-weight:600; }
td { padding:10px 14px; border-bottom:1px solid var(--border); font-size:.85rem; color:var(--text-alt); }
tr:last-child td { border-bottom:none; }
.badge { display:inline-block; padding:3px 10px; border-radius:100px; font-size:.75rem; font-weight:600; }
.badge-trial { background:var(--blue-light); color:var(--blue); }
.badge-monthly { background:var(--green-light); color:var(--green); }
.badge-yearly { background:var(--accent-light); color:var(--accent); }
.badge-unlimited { background:#2a2438; color:#ffd700; }
.badge-active { background:var(--green-light); color:var(--green); }
.badge-expired { background:var(--red-light); color:var(--red); }
.badge-paused { background:var(--bg-alt); color:var(--sub); }
.badge-expiring { background:var(--accent-light); color:var(--accent); }
/* 任务状态（历史表 badge-${t.status} 此前无定义，渲染为无边框裸文本） */
.badge-pending { background:var(--bg-alt); color:var(--sub); }
.badge-processing { background:var(--blue-light); color:var(--blue); }
.badge-done { background:var(--green-light); color:var(--green); }
.badge-failed { background:var(--red-light); color:var(--red); }
.badge-cancelled { background:var(--bg-alt); color:var(--sub); }
.form-group { margin-bottom:16px; }
.form-group label { display:block; font-size:.8rem; color:var(--sub); margin-bottom:4px; font-weight:600; }
.form-group input, .form-group select, .form-group textarea {
  width:100%; padding:8px 12px; border:1px solid var(--border); border-radius:var(--radius); font-size:.875rem;
  font-family:inherit; background:var(--card); transition:border-color .15s, box-shadow .15s; line-height:1.5;
}
.form-group input:focus, .form-group select:focus, .form-group textarea:focus {
  border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-light); outline:none;
}
.form-group textarea { resize:vertical; min-height:60px; }
.form-row { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
@media (max-width:640px) { .form-row { grid-template-columns:1fr; } }
.btn { padding:8px 20px; border:none; border-radius:var(--radius); cursor:pointer; font-size:.875rem; font-weight:600; transition:all .15s ease; min-height:36px; }
.btn:hover { transform:translateY(-1px); box-shadow:var(--shadow); }
.btn-primary { background:var(--accent); color:#fff; }
.btn-primary:hover { background:var(--accent-hover); }
.btn-green { background:var(--green); color:#fff; }
.btn-outline { background:var(--card); border:1px solid var(--border); color:var(--text); }
.btn-outline:hover { background:var(--bg-alt); border-color:var(--accent); }
.btn-sm { padding:4px 12px; font-size:.8rem; }
.btn-group { display:flex; gap:8px; margin-top:16px; }
.modal-overlay { display:none; position:fixed; top:0;left:0;right:0;bottom:0; background:rgba(0,0,0,.25); backdrop-filter:blur(4px); -webkit-backdrop-filter:blur(4px); z-index:100; align-items:center; justify-content:center; animation:fadeIn .2s ease; }
.modal-overlay.show { display:flex; }
.modal { background:var(--card); border-radius:12px; padding:28px; max-width:560px; width:90%; max-height:80vh; overflow-y:auto; box-shadow:var(--shadow-lg); animation:modalEnter .25s ease; }
.modal h3 { margin-bottom:16px; }
.progress-bar { width:100%; height:8px; background:var(--border); border-radius:100px; overflow:hidden; margin:12px 0; }
.progress-bar .fill { height:100%; background:var(--accent); border-radius:100px; transition:width .3s ease; }
.step-list { margin:12px 0; }
.step-item { padding:8px 12px; margin:4px 0; border-radius:var(--radius); font-size:.85rem; display:flex; align-items:center; gap:8px; }
.step-item.done { background:var(--green-light); color:var(--green); }
.step-item.current { background:var(--accent-light); color:var(--accent); font-weight:600; }
.step-item.pending { background:var(--bg); color:var(--sub); }
.spinner { display:inline-block; width:16px; height:16px; border:2px solid var(--border); border-top:2px solid var(--accent); border-radius:50%; animation:spin 1s linear infinite; }
@keyframes spin { to { transform:rotate(360deg); } }
@keyframes fadeIn { from{opacity:0;} to{opacity:1;} }
@keyframes modalEnter { from{opacity:0;transform:scale(.95) translateY(8px);} to{opacity:1;transform:scale(1) translateY(0);} }
.toast { position:fixed; top:20px; right:20px; padding:12px 20px; border-radius:var(--radius); color:#fff; font-size:.875rem; z-index:200; box-shadow:var(--shadow-lg); animation:fadeIn .3s ease; }
.toast-success { background:var(--green); }
.toast-error { background:var(--red); }
.card { background:var(--card); border:none; border-radius:10px; padding:20px; box-shadow:var(--shadow); margin-bottom:16px; }
.table-wrap { overflow-x:auto; -webkit-overflow-scrolling:touch; }
</style>
</head>
<body>

<div class="header">
  <h1>🏠 拾阶而上</h1>
  <div class="nav">
    <button onclick="switchPage('dashboard')" class="active" data-page="dashboard">概览</button>
    <button onclick="switchPage('students')" data-page="students">学生</button>
    {% if feature_school %}
    <button onclick="switchPage('classes')" data-page="classes">班级管理</button>
    {% endif %}
    <button onclick="switchPage('onboard')" data-page="onboard">入学诊断</button>
    <button onclick="switchPage('weekly')" data-page="weekly">周度服务</button>
    <button onclick="switchPage('analytics')" data-page="analytics">学情看板</button>
    <button onclick="switchPage('bank')" data-page="bank">题库</button>
    <button onclick="switchPage('quality')" data-page="quality">质量抽检</button>
    <button onclick="switchPage('referrals')" data-page="referrals">邀请统计</button>
    <button onclick="switchPage('compliance')" data-page="compliance">合规</button>
    {% if feature_teacher %}
    <button onclick="switchPage('teacher-profile')" data-page="teacher-profile">机构介绍</button>
    {% endif %}
    {% if user_role == 'admin' %}
    <button onclick="switchPage('admin')" data-page="admin">账号管理</button>
    <button onclick="switchPage('observability')" data-page="observability">系统监控</button>
    {% endif %}
  </div>
  <div style="display:flex;align-items:center;gap:12px;margin-left:auto;">
    <span style="font-size:.85em;color:var(--sub);">
      <span style="background:var(--accent-light);color:var(--accent);padding:2px 8px;border-radius:10px;font-size:.75em;font-weight:600;">{% if user_role == 'admin' %}管理员{% else %}老师{% endif %}</span>
      <span id="user-name">{{user_name}}</span>
      {% if user_subject %}<span style="color:var(--blue);font-size:.8em;font-weight:600;margin-left:2px;">{{user_subject}}</span>{% endif %}
    </span>
    <form method="POST" action="/logout" style="display:inline;">
      <button type="submit" class="btn btn-sm btn-outline">退出</button>
    </form>
  </div>
</div>

<script>window.CURRENT_USER_ROLE = "{{user_role}}";</script>

<div class="main">

<!-- ══════ DASHBOARD ══════ -->
<div id="page-dashboard" class="page active">
  <div class="stats" id="stats-bar"></div>

  <!-- Active alerts banner -->
  <div id="dashboard-alert-banner" style="margin-bottom:16px;"></div>

  <!-- Recent failures quick tip -->
  <div id="dashboard-failure-tip" style="margin-bottom:16px; display:none;">
    <div style="background:var(--red-light);color:var(--red);padding:10px 12px;border-radius:6px;font-size:.9em;display:flex;justify-content:space-between;align-items:center;">
      <span id="dashboard-failure-text"></span>
      <button class="btn btn-sm btn-outline" onclick="switchPage('observability')" style="margin-left:12px;">查看详情</button>
    </div>
  </div>

  <!-- Compliance alerts -->
  <div id="dashboard-compliance-banner" style="margin-bottom:16px;"></div>

  <!-- P3-13：审核队列已移除（D1 决策）。AI 结果直通家长，质量由抽检+纠错回路保障。 -->

  {% if feature_school %}
  <h2>👩‍🏫 老师工作台</h2>
  <div class="stats" id="teacher-workload" style="margin-bottom:16px;"></div>

  <h3 style="font-size:1em;margin:16px 0 8px;">⏳ 待上传试卷学生</h3>
  <div class="table-wrap"><table id="pending-paper-table" style="margin-bottom:24px;">
    <thead><tr><th>学生</th><th>年级</th><th>操作</th></tr></thead>
    <tbody></tbody>
  </table></div>
  {% endif %}

  <h2>🧠 AI 纠错趋势（近7天）</h2>
  <div class="stats" id="correction-trend" style="margin-bottom:24px;">
    <div class="stat"><div class="num">-</div><div class="label">纠错总数</div></div>
  </div>

  <h2>⚠️ 订阅/续费提醒</h2>
  <table id="expiring-table" style="margin-bottom:24px;">
    <thead><tr><th>学生</th><th>年级</th><th>套餐</th><th>到期日</th><th>剩余天数</th><th>操作</th></tr></thead>
    <tbody></tbody>
  </table>

  <h2>本周状态</h2>
  <table id="pending-table">
    <thead><tr>
      <th>学生</th><th>年级</th><th>套餐</th><th>试卷提交</th><th>分析完成</th><th>练习题</th><th>批改</th><th>周报</th><th>链路状态</th>
    </tr></thead>
    <tbody></tbody>
  </table>
  <p style="margin-top:12px;color:var(--sub);font-size:.85em;" id="week-label"></p>

  {% if user_role == 'admin' %}
  <h2 style="margin-top:24px;">💰 API 成本与预算</h2>
  <div class="card" style="margin-bottom:16px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
      <span style="font-size:.85em;color:var(--sub);">本月总成本 / 月度预算</span>
      <span style="font-size:.85em;font-weight:600;" id="budget-text">-</span>
    </div>
    <div class="progress-bar" style="margin:8px 0;"><div class="fill" id="budget-bar" style="width:0%;background:var(--green);"></div></div>
    <p style="font-size:.85em;color:var(--sub);">今日: $<span id="cost-today">-</span> | 本月: $<span id="cost-month">-</span> | 单人月度预算: $<span id="student-budget">-</span></p>
    <div class="form-row" style="margin-top:12px;">
      <div class="form-group" style="margin-bottom:0;"><label style="font-size:.8em;">月度总预算 (USD)</label><input id="budget-total" type="number" step="1" placeholder="100"></div>
      <div class="form-group" style="margin-bottom:0;"><label style="font-size:.8em;">单人月度预算 (USD)</label><input id="budget-student" type="number" step="1" placeholder="20"></div>
    </div>
    <button class="btn btn-sm btn-primary" style="margin-top:8px;" onclick="saveBudget()">保存预算设置</button>
  </div>

  <table id="cost-breakdown-table" style="margin-bottom:24px;">
    <thead><tr><th>学生</th><th>本月调用次数</th><th>本月成本 (USD)</th><th>占单人预算</th></tr></thead>
    <tbody></tbody>
  </table>
  {% endif %}

  <h2 style="margin-top:24px;">🔧 系统状态</h2>
  <div class="card" id="system-status-card" style="margin-bottom:16px;">
    <p style="font-size:.85em;color:var(--sub);">加载中...</p>
  </div>
</div>

<!-- ══════ STUDENTS ══════ -->
<div id="page-students" class="page">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
    <h2 style="margin:0;">学生列表</h2>
    <button class="btn btn-primary" onclick="openStudentModal()">+ 添加学生</button>
  </div>
  <div style="display:flex;gap:12px;align-items:center;margin-bottom:12px;flex-wrap:wrap;">
    <select id="filter-plan" onchange="loadStudents()" style="padding:6px 10px;border-radius:6px;border:1px solid var(--border);font-size:.85em;background:#fff;">
      <option value="">全部套餐</option>
      <option value="trial">体验（3次）</option>
      <option value="monthly">包月</option>
      <option value="yearly">包年</option><option value="unlimited">超级账号</option>
    </select>
    <select id="filter-status" onchange="loadStudents()" style="padding:6px 10px;border-radius:6px;border:1px solid var(--border);font-size:.85em;background:#fff;">
      <option value="">全部状态</option>
      <option value="active">有效</option>
      <option value="expired">已过期</option>
      <option value="soon">即将到期（7天内）</option>
    </select>
    <select id="sort-by" onchange="loadStudents()" style="padding:6px 10px;border-radius:6px;border:1px solid var(--border);font-size:.85em;background:#fff;">
      <option value="name">按姓名排序</option>
      <option value="days_remaining">按到期时间排序</option>
      <option value="plan">按套餐排序</option>
    </select>
  </div>
  <div class="table-wrap"><table id="students-table">
    <thead><tr>
      <th>姓名</th><th>年级</th><th>类型</th><th>英语分</th><th>目标分</th><th>套餐</th><th>有效期</th><th>状态</th><th>授权</th><th>本月AI成本</th><th>操作</th>
    </tr></thead>
    <tbody></tbody>
  </table></div>
</div>

<!-- ══════ ONBOARDING ══════ -->
<div id="page-onboard" class="page">
  <h2>新学生入学诊断</h2>
  <p style="color:var(--sub);margin-bottom:16px;">上传学生首张英语试卷 + 基本信息，AI 自动生成首次诊断报告和学习方案。</p>
  <div class="card" style="margin-bottom:24px;">
    <h3>第一步：填写基本信息</h3>
    <div class="form-row">
      <div class="form-group"><label>姓名 *</label><input id="onb-name"></div>
      <div class="form-group"><label>年级</label><select id="onb-grade"><option>高一</option><option selected>高二</option><option>高三</option></select></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>性别</label><select id="onb-gender"><option value="">请选择</option><option>男</option><option>女</option></select></div>
      <div class="form-group"><label>住校/走读</label><select id="onb-school-type"><option selected>住校</option><option>走读</option></select></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>最近英语分数</label><input id="onb-score" type="number" step="0.5"></div>
      <div class="form-group"><label>目标分数</label><input id="onb-target" type="number" step="0.5"></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>套餐</label><select id="onb-plan"><option value="trial" selected>体验（免费·3次）</option><option value="monthly">包月 ¥39/月</option><option value="yearly">包年 ¥399/年</option><option value="unlimited">超级账号（不限次）</option></select></div>
      <div class="form-group"><label>家长电话</label><input id="onb-parent-phone"></div>
    </div>
    <div class="form-group" style="display:flex;align-items:center;gap:8px;">
      <input type="checkbox" id="onb-parent-consent" style="width:auto;">
      <label for="onb-parent-consent" style="margin-bottom:0;font-weight:400;">家长已同意收集和使用学生学习数据</label>
    </div>
  </div>
  <div class="card" style="margin-bottom:24px;">
    <h3>🎯 第二步：真正个性化的学习，从这里开始</h3>
    <p style="color:var(--accent);margin-bottom:16px;font-size:.92em;line-height:1.8;">
      ⚡️ 花 3 分钟填一填，AI 出的每道题都会「长在」孩子的薄弱点上——比闷头刷 30 道题管用多了
    </p>
    <div style="display:flex;gap:4px;margin-bottom:16px;border-bottom:1px solid var(--border);flex-wrap:wrap;">
      <button class="onb-profile-tab active" data-tab="english" onclick="switchOnbProfileTab('english')" style="padding:8px 16px;border:none;background:none;border-bottom:2px solid var(--accent);font-weight:600;color:var(--text);">📝 英语学情</button>
      <button class="onb-profile-tab" data-tab="traits" onclick="switchOnbProfileTab('traits')" style="padding:8px 16px;border:none;background:none;color:var(--sub);">🧠 学习特质</button>
      <button class="onb-profile-tab" data-tab="goals" onclick="switchOnbProfileTab('goals')" style="padding:8px 16px;border:none;background:none;color:var(--sub);">🎯 目标与支持</button>
    </div>

    <!-- English Tab -->
    <div id="onb-tab-english" class="onb-profile-tab-content" style="display:block;">
      <div class="form-row">
        <div class="form-group"><label>最近3-5次分数范围</label><input id="onb-recent-scores" placeholder="如：85,92,88 或 85-95"></div>
        <div class="form-group"><label>最有挑战的方面</label><input id="onb-weak-areas" placeholder="如：阅读理解长难句"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>失分主要原因</label><input id="onb-score-loss-reason" placeholder="如：知识点不熟练 / 做题方法 / 粗心"></div>
        <div class="form-group"><label>优先提升题型（逗号分隔）</label><input id="onb-weak-question-types" placeholder="完形填空,阅读理解,作文,听力"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>容易混淆的语法点</label><input id="onb-confused-grammar" placeholder="如：定语从句关系词"></div>
        <div class="form-group"><label>已有学习资源</label><input id="onb-existing-resources" placeholder="如：高考词汇书、真题册"></div>
      </div>
      <div class="form-group"><label>词汇方向</label>
        <select id="onb-vocab-direction">
          <option value="">请选择</option>
          <option value="A">A. 匹配教材</option>
          <option value="B">B. 预习教材</option>
          <option value="C">C. 高考高频词汇</option>
          <option value="D">D. 混合模式</option>
        </select>
      </div>
      <div class="form-group"><label>时间全景图（按周安排）</label>
        <div style="border:1px solid var(--border);border-radius:6px;padding:12px;background:var(--bg);">
          <table style="width:100%;font-size:.85em;">
            <thead>
              <tr style="color:var(--sub);">
                <th style="text-align:left;padding:4px;">星期</th>
                <th style="text-align:left;padding:4px;">开始</th>
                <th style="text-align:left;padding:4px;">结束</th>
                <th style="text-align:left;padding:4px;">内容</th>
                <th style="text-align:left;padding:4px;">性质</th>
                <th style="text-align:left;padding:4px;">精力</th>
                <th style="width:30px;"></th>
              </tr>
            </thead>
            <tbody id="onb-time-map-slots"></tbody>
          </table>
          <button class="btn btn-sm btn-outline" onclick="addOnbTimeSlot()" style="margin-top:8px;">+ 添加时段</button>
          <div style="margin-top:10px;">
            <label style="font-size:.8em;color:var(--sub);">补充说明</label>
            <textarea id="onb-time-map-desc" rows="2" placeholder="如：考试周会取消周六上午时段..." style="margin-top:4px;"></textarea>
          </div>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>一周可用学习时长（小时）</label><input id="onb-weekly-available-hours" type="number" step="0.5"></div>
        <div class="form-group"><label>孩子自愿承诺的英语时间（分钟/周）</label><input id="onb-committed-english-minutes" type="number"></div>
      </div>
    </div>

    <!-- Traits Tab -->
    <div id="onb-tab-traits" class="onb-profile-tab-content" style="display:none;">
      <div class="form-row">
        <div class="form-group"><label>学习类型</label>
          <select id="onb-learning-style">
            <option value="">请选择</option>
            <option value="视觉型">视觉型（爱看、爱画、记笔记）</option>
            <option value="听觉型">听觉型（爱听、爱读、跟读）</option>
            <option value="动觉型">动觉型（动笔、拆解、做题）</option>
            <option value="读写型">读写型（阅读+写作）</option>
          </select>
        </div>
        <div class="form-group"><label>学习介质偏好</label>
          <select id="onb-learning-medium">
            <option value="">请选择</option>
            <option value="纸质">纸质资料</option>
            <option value="电子">电子资料</option>
            <option value="混合">混合</option>
          </select>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>背单词习惯</label><input id="onb-vocab-habit" placeholder="如：反复抄写 / 读出声"></div>
        <div class="form-group"><label>容易分心的环节</label><input id="onb-attention-weakness" placeholder="如：做阅读时容易走神"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>过往有效方法</label><input id="onb-effective-methods" placeholder="如：用思维导图记语法"></div>
        <div class="form-group"><label>过往无效方法</label><input id="onb-ineffective-methods" placeholder="如：单纯抄单词"></div>
      </div>
      <div class="form-group"><label>与英语的关系</label>
        <select id="onb-english-identity">
          <option value="">请选择</option>
          <option value="敌人">敌人 / 负担</option>
          <option value="工具">工具 / 任务</option>
          <option value="朋友">朋友 / 技能</option>
          <option value="兴趣">兴趣 / 爱好</option>
        </select>
      </div>
      <hr style="margin:16px 0;border:none;border-top:1px solid var(--border);">
      <p style="font-size:.85em;color:var(--sub);margin-bottom:12px;">小测评结果（可选填）</p>
      <div class="form-row">
        <div class="form-group"><label>注意力极限时长（分钟）</label><input id="onb-attention-minutes" type="number" placeholder="如：25"></div>
        <div class="form-group"><label>词汇量自测等级</label>
          <div style="display:flex;gap:8px;align-items:flex-end;">
            <select id="onb-vocab-level" style="flex:1;">
              <option value="">未测评</option>
              <option value="基础偏弱">基础偏弱</option>
              <option value="基础尚可">基础尚可</option>
              <option value="中上水平">中上水平</option>
              <option value="词汇较强">词汇较强</option>
            </select>
            <button class="btn btn-sm btn-outline" onclick="startVocabTest('onb')" style="white-space:nowrap;padding:6px 14px;">📝 在线测评</button>
          </div>
        </div>
      </div>
      <div class="form-group"><label>学习场景偏好</label>
        <select id="onb-scene-preference">
          <option value="">未测评</option>
          <option value="视觉助记">视觉助记（看+写）</option>
          <option value="音频跟读">音频跟读（听+读）</option>
          <option value="语境句子">语境句子（上下文理解）</option>
        </select>
      </div>
    </div>

    <!-- Goals Tab -->
    <div id="onb-tab-goals" class="onb-profile-tab-content" style="display:none;">
      <div class="form-row">
        <div class="form-group"><label>升学目标</label><input id="onb-academic-goal" placeholder="如：稳住不下滑 / 冲刺130分"></div>
        <div class="form-group"><label>选科情况</label><select id="onb-subject-choice"><option value="">请选择</option><option>文科</option><option>理科</option><option>未分科</option></select></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>教材版本</label><input id="onb-textbook-version" placeholder="如：人教版必修2"></div>
        <div class="form-group"><label>学期</label><select id="onb-semester"><option value="">请选择</option><option>上学期</option><option>下学期</option></select></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>期望进步时间</label><input id="onb-target-timeline" placeholder="如：3个月"></div>
        <div class="form-group"><label>1个月小目标</label><input id="onb-one-month-goal" placeholder="如：阅读理解正确率提升到70%"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>家长每周陪学时间</label><input id="onb-parent-availability" placeholder="如：周末1-2小时"></div>
        <div class="form-group"><label>需要监督吗</label>
          <select id="onb-supervision-needed">
            <option value="0">主要靠孩子自主</option>
            <option value="1">需要每天检查</option>
          </select>
        </div>
      </div>
      <div class="form-group"><label>学习环境</label><input id="onb-study-environment" placeholder="如：独立书房 / 客厅"></div>
      <hr style="margin:16px 0;border:none;border-top:1px solid var(--border);">
      <p style="font-size:.85em;color:var(--sub);margin-bottom:12px;">孩子的心声</p>
      <div class="form-row">
        <div class="form-group"><label>最不想做的事</label><input id="onb-least-favorite-task" placeholder="如：背单词"></div>
        <div class="form-group"><label>期望强度</label>
          <select id="onb-preferred-intensity">
            <option value="">请选择</option>
            <option value="轻松">轻松一点</option>
            <option value="中等">中等</option>
            <option value="上强度">可以上点强度</option>
          </select>
        </div>
      </div>
      <div class="form-group"><label>英语变厉害后想做什么</label><input id="onb-aspirational-use" placeholder="如：看美剧不用字幕"></div>
      <hr style="margin:16px 0;border:none;border-top:1px solid var(--border);">
      <p style="font-size:.85em;color:var(--sub);margin-bottom:12px;">关键抉择</p>
      <div class="form-row">
        <div class="form-group"><label>模块配比</label>
          <select id="onb-module-ratio">
            <option value="">请选择</option>
            <option value="主攻突破">主攻突破型（薄弱模块70%）</option>
            <option value="稳步推进">稳步推进型（词汇50%）</option>
          </select>
        </div>
        <div class="form-group"><label>难度起点</label>
          <select id="onb-difficulty-start">
            <option value="">请选择</option>
            <option value="基础巩固">基础巩固起步</option>
            <option value="中等直入">中等难度直入</option>
          </select>
        </div>
      </div>
      <div class="form-group"><label>每日词汇量</label>
        <select id="onb-daily-vocab">
          <option value="">请选择</option>
          <option value="5">每天5个（轻松）</option>
          <option value="8">每天8个（性价比最高）</option>
          <option value="10">每天10个（挑战）</option>
        </select>
      </div>
      <div class="form-row">
        <div class="form-group"><label>专属计划名称</label><input id="onb-plan-name" placeholder="如：火箭计划"></div>
        <div class="form-group"><label>专属代号</label><input id="onb-plan-code-name" placeholder="如：Rocket-2024"></div>
      </div>
    </div>
  </div>
  <div class="card">
    <h3>第三步：上传试卷照片</h3>
    <div class="form-group"><label>试卷照片（支持 JPG/PNG，最多 15 张）</label><input type="file" id="onb-file" accept="image/*" multiple style="padding:8px;"></div>
    <button class="btn btn-primary" onclick="startOnboarding()">🚀 开始诊断</button>
  </div>
  <div id="onb-progress" style="display:none;margin-top:16px;">
    <div class="progress-bar"><div class="fill" id="onb-bar" style="width:0%"></div></div>
    <div class="step-list" id="onb-steps"></div>
    <p id="onb-result" style="margin-top:12px;"></p>
  </div>
</div>

<!-- ══════ WEEKLY ══════ -->
<div id="page-weekly" class="page">
  <h2>周度服务</h2>
  <div class="card" style="margin-bottom:16px;">
    <div class="form-row">
      <div class="form-group" style="flex:1;"><label>选择学生</label><select id="wk-student"></select></div>
      <div class="form-group" style="flex:1;"><label>试卷照片（最多 15 张）</label><input type="file" id="wk-file" accept="image/*" multiple onchange="onFileSelected()"></div>
    </div>
    <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:8px;">
      <button class="btn btn-primary" onclick="startWeekly('grade_only')">✅ 批改试卷</button>
      <button class="btn btn-outline" onclick="startWeekly('analysis_only')" style="border-color:var(--accent);color:var(--accent);">📋 矩阵分析</button>
      <button class="btn btn-green" onclick="startWeekly('report_only')">📊 生成周报</button>
    </div>
  </div>

  <div id="wk-progress" style="display:none;">
    <div class="progress-bar"><div class="fill" id="wk-bar" style="width:0%"></div></div>
    <div class="step-list" id="wk-steps"></div>
    <p id="wk-result" style="margin-top:12px;"></p>
  </div>
  <h2 style="margin-top:32px;">历史任务</h2>
  <table id="tasks-table">
    <thead><tr><th>学生</th><th>类型</th><th>状态</th><th>结果</th><th>时间</th><th>操作</th></tr></thead>
    <tbody></tbody>
  </table>
</div>

<!-- ══════ ANALYTICS ══════ -->
<div id="page-analytics" class="page">
  <h2>📊 班级学情概览</h2>
  <div class="stats" id="class-stats"></div>

  <div class="card" style="margin-bottom:24px;">
    <h3 style="margin-bottom:16px;">班级平均分趋势</h3>
    <div id="class-trend-chart" style="width:100%;height:240px;"></div>
  </div>

  <div class="form-row" style="margin-bottom:16px;">
    <div class="card" style="width:100%;">
      <h3 style="margin-bottom:16px;">班级薄弱知识点 TOP10</h3>
      <div id="class-weak-kp"></div>
    </div>
  </div>

  <h2 style="margin-top:32px;">👤 个人学情</h2>
  <div class="form-row" style="margin-bottom:16px;">
    <div class="form-group" style="margin-bottom:0;">
      <label>选择学生</label>
      <select id="analytics-student" onchange="loadStudentAnalytics()"></select>
    </div>
    <div class="form-group" style="margin-bottom:0;">
      <label></label>
      <button class="btn btn-primary" style="margin-top:20px;" onclick="openScoreModal()">+ 录入分数</button>
    </div>
  </div>

  <div id="student-analytics">
    <div class="stats" id="student-stats"></div>

    <div class="card" style="margin-bottom:24px;">
      <h3 style="margin-bottom:16px;">分数趋势</h3>
      <div id="student-trend-chart" style="width:100%;height:220px;">
        <p style="text-align:center;color:var(--sub);padding-top:80px;">请选择学生查看</p>
      </div>
    </div>

    <div class="form-row" style="margin-bottom:24px;">
      <div class="card" style="width:100%;">
        <h3 style="margin-bottom:16px;">知识点掌握热力图</h3>
        <div id="student-kp-heatmap"></div>
      </div>
    </div>

    <h3>近期练习表现</h3>
    <div id="student-practice-stats" style="margin-bottom:24px;"></div>

    <h3>错题统计</h3>
    <div id="student-mistake-stats" style="margin-bottom:24px;"></div>

    <h3>🛤️ 学习路径时间轴</h3>
    <div id="student-timeline" style="margin-bottom:24px;"></div>

    <h3>🏆 成就墙</h3>
    <div id="student-achievements-wall" style="margin-bottom:24px;"></div>

    <h3>个性化画像</h3>
    <div id="student-profile-summary" style="margin-bottom:24px;"></div>

    <h3>诊断结论</h3>
    <div id="student-diagnosis-conclusion" style="margin-bottom:24px;"></div>

    <h3>动机卡片</h3>
    <div id="student-motivation-cards" style="margin-bottom:24px;"></div>

    <h3>元认知复盘表</h3>
    <div id="student-metacognitive-review" style="margin-bottom:24px;"></div>

    <h3>自适应调整记录</h3>
    <div id="student-plan-adjustments"></div>
  </div>
</div>

<!-- ══════ QUESTION BANK ══════ -->
<div id="page-bank" class="page">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
    <h2 style="margin:0;">🗂️ 题库管理</h2>
    <div class="btn-group" style="margin:0;">
      <input type="text" id="bank-search" placeholder="搜索知识点" style="padding:6px 10px;border:1px solid var(--border);border-radius:6px;font-size:.85em;">
      <button class="btn btn-primary" onclick="loadBank()">搜索</button>
    </div>
  </div>

  <div class="stats" id="bank-stats" style="margin-bottom:16px;"></div>

  <table id="questions-table">
    <thead><tr><th>题目</th><th>题型</th><th>知识点</th><th>难度</th><th>使用次数</th><th>状态</th><th>操作</th></tr></thead>
    <tbody></tbody>
  </table>

  <!-- Question Edit Modal -->
  <div class="modal-overlay" id="q-modal">
    <div class="modal" style="max-width:560px;">
      <h3>编辑题目</h3>
      <input type="hidden" id="q-id">
      <div class="form-group"><label>题干</label><textarea id="q-text" rows="3"></textarea></div>
      <div class="form-row">
        <div class="form-group"><label>题型</label><input id="q-type"></div>
        <div class="form-group"><label>正确答案</label><input id="q-answer"></div>
      </div>
      <div class="form-group"><label>解析</label><textarea id="q-explanation" rows="2"></textarea></div>
      <div class="form-row">
        <div class="form-group"><label>知识点（逗号分隔）</label><input id="q-kp"></div>
        <div class="form-group"><label>难度（1-5）</label><input id="q-difficulty" type="number" min="1" max="5"></div>
      </div>
      <div class="btn-group" style="justify-content:flex-end;">
        <button class="btn btn-outline" onclick="closeQModal()">取消</button>
        <button class="btn btn-primary" onclick="saveQuestion()">保存</button>
      </div>
    </div>
  </div>
</div>

</div>

<!-- ══════ QUALITY SAMPLING ══════ -->
<div id="page-quality" class="page">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
    <h2 style="margin:0;">🔍 AI 内容质量抽检</h2>
    <button class="btn btn-primary" onclick="loadQuality()">刷新</button>
  </div>

  <div class="stats" id="quality-stats" style="margin-bottom:16px;"></div>

  <h3 style="font-size:1em;margin:16px 0 8px;">待抽检</h3>
  <div id="quality-pending-list" style="display:flex;flex-direction:column;gap:12px;">
    <div style="color:var(--sub);text-align:center;padding:24px;">加载中...</div>
  </div>
</div>

<!-- ══════ REFERRALS ══════ -->
<div id="page-referrals" class="page">
  <h2>🎁 邀请统计</h2>
  <div class="stats" id="referral-stats" style="margin-bottom:16px;"></div>

  <div class="card" style="margin-bottom:24px;">
    <h3 style="margin-bottom:12px;">奖励规则配置</h3>
    <div class="form-row">
      <div class="form-group" style="margin-bottom:0;">
        <label>邀请成功奖励周数</label>
        <input id="referral-reward-weeks" type="number" min="0" value="1">
      </div>
    </div>
    <button class="btn btn-primary" style="margin-top:8px;" onclick="saveReferralSettings()">保存设置</button>
  </div>

  <h3 style="font-size:1em;margin:16px 0 8px;">🏆 邀请榜 TOP10</h3>
  <table id="referral-top-table">
    <thead><tr><th>学生</th><th>邀请人数</th><th>累计奖励周数</th></tr></thead>
    <tbody></tbody>
  </table>
</div>

<!-- ══════ CLASSES ══════ -->
{% if feature_school %}
<div id="page-classes" class="page">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
    <h2 style="margin:0;">班级管理</h2>
    <div style="display:flex;gap:8px;">
      {% if user_role == 'admin' %}<button class="btn btn-outline btn-sm" onclick="openSchoolModal()">+ 添加学校</button>{% endif %}
      <button class="btn btn-primary btn-sm" onclick="openClassModal()">+ 创建班级</button>
    </div>
  </div>
  <div id="classes-list"></div>
  <div id="class-detail" style="display:none;">
    <div style="margin-bottom:16px;"><button class="btn btn-outline btn-sm" onclick="backToClasses()">← 返回班级列表</button></div>
    <div id="class-stats-cards" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:16px;"></div>
    <div class="card">
      <h3 style="font-size:.95em;margin-bottom:12px;">全班薄弱知识点 TOP5</h3>
      <div id="class-weak-points"></div>
    </div>
    <div class="card">
      <h3 style="font-size:.95em;margin-bottom:12px;">学生列表</h3>
      <div class="table-wrap">
        <table id="class-students-table">
          <thead><tr><th>姓名</th><th>年级</th><th>手机号</th><th>操作</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>
  </div>
</div>
{% endif %}

{% if user_role == 'admin' %}
<!-- ══════ ADMIN ══════ -->
<div id="page-admin" class="page">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
    <h2 style="margin:0;">账号管理</h2>
    <button class="btn btn-primary" onclick="openAdminModal()">+ 添加账号</button>
  </div>
  <table id="admin-users-table">
    <thead><tr><th>用户名</th><th>角色</th><th>创建时间</th><th>操作</th></tr></thead>
    <tbody></tbody>
  </table>
</div>
<div class="modal-overlay" id="admin-modal">
  <div class="modal">
    <h3 id="admin-modal-title">添加账号</h3>
    <div class="form-group"><label>用户名 *</label><input id="admin-username"></div>
    <div class="form-group"><label>密码 *</label><input type="password" id="admin-password"></div>
    <div class="form-group"><label>角色</label><select id="admin-role"><option value="teacher" selected>老师</option><option value="admin">管理员</option></select></div>
    <div class="btn-group" style="justify-content:flex-end;">
      <button class="btn btn-outline" onclick="closeAdminModal()">取消</button>
      <button class="btn btn-primary" onclick="saveAdminUser()">保存</button>
    </div>
  </div>
</div>

<!-- ══════ OBSERVABILITY ══════ -->
<div id="page-observability" class="page">
  <h2>📊 系统监控</h2>

  <!-- Active Alerts Banner -->
  <div id="obs-alert-banner" style="margin-bottom:16px;"></div>

  <!-- Task Health -->
  <div class="card" style="margin-bottom:24px;">
    <h3 style="margin-bottom:12px;">🩺 任务健康</h3>
    <div class="stats" id="obs-task-stats" style="margin-bottom:16px;"></div>
    <div style="margin-bottom:12px;">
      <strong style="font-size:.9em;">近7天每日失败/驳回趋势</strong>
      <div id="obs-failure-trend" style="height:140px; background:var(--bg); border-radius:6px; padding:12px; margin-top:8px; overflow-x:auto;"></div>
    </div>
    <h4 style="font-size:.9em; margin:16px 0 8px;">最近失败任务</h4>
    <table id="obs-failure-table">
      <thead><tr><th>学生</th><th>任务</th><th>状态</th><th>时间</th><th>错误信息</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <!-- Cost Alerts -->
  <div class="card" style="margin-bottom:24px;">
    <h3 style="margin-bottom:12px;">💰 成本告警</h3>
    <div id="obs-cost-panel"></div>
    {% if user_role == 'admin' %}
    <div class="form-row" style="margin-top:12px;">
      <div class="form-group" style="margin-bottom:0;">
        <label style="font-size:.8em;">告警阈值 (%)</label>
        <input id="obs-alert-threshold" type="number" min="0" max="100" value="80" style="width:80px;">
      </div>
      <div class="form-group" style="margin-bottom:0; align-self:flex-end;">
        <button class="btn btn-sm btn-primary" onclick="saveAlertSettings()">保存阈值</button>
      </div>
    </div>
    {% endif %}
  </div>

  <!-- Audit Logs -->
  <div class="card" style="margin-bottom:24px;">
    <h3 style="margin-bottom:12px;">📋 审计日志</h3>
    <div class="form-row" style="margin-bottom:12px;">
      <div class="form-group" style="margin-bottom:0;">
        <label style="font-size:.8em;">操作类型</label>
        <select id="obs-audit-action"><option value="">全部</option></select>
      </div>
      <div class="form-group" style="margin-bottom:0;">
        <label style="font-size:.8em;">目标类型</label>
        <input id="obs-audit-target" placeholder="如 student">
      </div>
      <div class="form-group" style="margin-bottom:0;">
        <label style="font-size:.8em;">开始日期</label>
        <input id="obs-audit-since" type="date">
      </div>
      <div class="form-group" style="margin-bottom:0; align-self:flex-end;">
        <button class="btn btn-sm btn-primary" onclick="loadAuditLogs()">查询</button>
      </div>
    </div>
    <table id="obs-audit-table">
      <thead><tr><th>时间</th><th>操作者</th><th>动作</th><th>目标</th><th>详情</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <!-- Backups -->
  <div class="card" style="margin-bottom:24px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
      <h3 style="margin:0;">💾 自动备份</h3>
      <button class="btn btn-sm btn-primary" onclick="runManualBackup()">立即备份</button>
    </div>
    <p style="font-size:.85em;color:var(--sub);margin-bottom:12px;">保留策略：最近 7 个 daily 备份 + 最近 4 个 weekly 备份。每天/每周凌晨 3 点自动执行。</p>
    <table id="obs-backup-table">
      <thead><tr><th>时间</th><th>类型</th><th>文件大小</th><th>操作</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>
</div>
{% endif %}

<!-- ══════ COMPLIANCE ══════ -->
<div id="page-compliance" class="page">
  <h2>👨‍👩‍👧 数据合规</h2>

  <!-- Consent Section -->
  <div class="card" style="margin-bottom:24px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
      <h3 style="margin:0;">📝 待家长授权学生</h3>
      <span style="font-size:.85em;color:var(--sub);" id="consent-pending-count">-</span>
    </div>
    <table id="consent-table" style="margin-bottom:12px;">
      <thead><tr><th>学生</th><th>年级</th><th>家长联系方式</th><th>操作</th></tr></thead>
      <tbody></tbody>
    </table>
    <p style="font-size:.85em;color:var(--sub);">在学生详情页也可补录家长授权。授权记录会写入审计日志。</p>
  </div>

  <!-- Deletion Requests Section -->
  <div class="card" style="margin-bottom:24px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
      <h3 style="margin:0;">🗑️ 待处理数据删除申请</h3>
      <span style="font-size:.85em;color:var(--sub);" id="deletion-pending-count">-</span>
    </div>
    <table id="deletion-table">
      <thead><tr><th>学生</th><th>申请人</th><th>原因</th><th>申请时间</th><th>操作</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>
</div>

<!-- Teacher / Institution Profile Page -->
{% if feature_teacher %}
<div id="page-teacher-profile" class="page">
  <h2>🏫 机构与老师介绍</h2>
  <div class="card" style="max-width:640px;">
    <div class="form-row">
      <div class="form-group"><label>机构名称</label><input id="tp-institution" placeholder="拾阶而上"></div>
      <div class="form-group"><label>老师姓名</label><input id="tp-teacher" placeholder="王老师"></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>教龄</label><input id="tp-years" placeholder="8 年高考英语教学经验"></div>
      <div class="form-group"><label>擅长方向</label><input id="tp-specialty" placeholder="阅读理解提分 / 写作冲刺"></div>
    </div>
    <div class="form-group"><label>教学理念</label><input id="tp-philosophy" placeholder="错题不过夜，弱项逐个破"></div>
    <div class="form-group"><label>联系方式（仅对付费家长显示）</label><input id="tp-contact" placeholder="微信：xxx"></div>
    <div class="form-group">
      <label>老师头像</label>
      <input type="file" id="tp-avatar" accept="image/*" style="padding:8px;">
      <p id="tp-avatar-preview" style="font-size:.85em;color:var(--sub);margin-top:6px;"></p>
    </div>
    <button class="btn btn-primary" onclick="saveTeacherProfile()">💾 保存</button>
  </div>
</div>
{% endif %}

<!-- Subscription Modal -->
<div class="modal-overlay" id="sub-modal">
  <div class="modal" style="max-width:520px;">
    <h3 id="sub-modal-title">订阅管理</h3>
    <input type="hidden" id="sub-student-id">

    <div class="form-row">
      <div class="form-group"><label>套餐</label>
        <select id="sub-plan" onchange="updateSubPrice()">
          <option value="trial">体验（免费·3次）</option>
          <option value="monthly">包月 ¥39/月（40次/月，月底清零）</option>
          <option value="yearly">包年 ¥399/年（600次/年）</option><option value="unlimited">超级账号（不限次）</option>
        </select>
      </div>
      <div class="form-group"><label>当前状态</label><input id="sub-status" readonly style="background:#f5f2ec;"></div>
    </div>

    <div class="form-row">
      <div class="form-group"><label>有效期至</label><input id="sub-end-date" type="date"></div>
      <div class="form-group"><label>累计缴费</label><input id="sub-total-paid" readonly style="background:#f5f2ec;"></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>本月额度</label><input id="sub-quota" readonly style="background:#f5f2ec;"></div>
      <div class="form-group"><label>本月已用</label><input id="sub-used" readonly style="background:#f5f2ec;"></div>
    </div>

    <div class="btn-group" style="justify-content:flex-end;">
      <button class="btn btn-outline" onclick="closeSubModal()">关闭</button>
      <button class="btn btn-primary" onclick="saveSubPlan()">保存套餐</button>
    </div>

    <hr style="border:none;border-top:1px solid var(--border);margin:24px 0;">

    <h4 style="margin-bottom:12px;">收款记录</h4>
    <div class="form-row">
      <div class="form-group"><label>收款套餐</label>
        <select id="pay-plan" onchange="updatePayAmount()">
          <option value="monthly">包月 ¥39/月</option>
          <option value="yearly">包年 ¥399/年</option>
        </select>
      </div>
      <div class="form-group"><label>收款金额（元）</label><input id="pay-amount" type="number" step="0.01" placeholder="0.00"></div>
    </div>
    <div class="form-group"><label>备注</label><input id="pay-note" placeholder="如：微信转账、现金"></div>
    <button class="btn btn-green" style="width:100%;" onclick="recordPayment()">💰 记录收款并续费</button>

    <h4 style="margin:20px 0 8px;">历史记录</h4>
    <table id="payments-table" style="font-size:.85em;">
      <thead><tr><th>日期</th><th>金额</th><th>套餐</th><th>备注</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>
</div>

<!-- Score Modal -->
<div class="modal-overlay" id="score-modal">
  <div class="modal" style="max-width:400px;">
    <h3>录入考试分数</h3>
    <input type="hidden" id="score-student-id">
    <div class="form-group"><label>学生</label><input id="score-student-name" readonly style="background:#f5f2ec;"></div>
    <div class="form-row">
      <div class="form-group"><label>分数 *</label><input id="score-value" type="number" step="0.5" placeholder="0-150"></div>
      <div class="form-group"><label>日期</label><input id="score-date" type="date"></div>
    </div>
    <div class="form-group"><label>备注</label><input id="score-note" placeholder="如：月考、期中"></div>
    <div class="btn-group" style="justify-content:flex-end;">
      <button class="btn btn-outline" onclick="closeScoreModal()">取消</button>
      <button class="btn btn-primary" onclick="saveScore()">保存</button>
    </div>
  </div>
</div>

<!-- ══════ MODAL: AI Correction ══════ -->
<div class="modal-overlay" id="correction-modal">
  <div class="modal" style="max-width:760px; padding:0; display:flex; flex-direction:column; max-height:85vh;">
    <div style="padding:20px 24px; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center;">
      <h3 style="margin:0;">📝 AI 内容纠错 <span id="correction-task-info" style="font-size:.7em; color:var(--sub); font-weight:400;"></span></h3>
      <button class="btn btn-sm btn-outline" onclick="closeCorrectionModal()">关闭</button>
    </div>
    <div style="padding:20px 24px; overflow-y:auto; flex:1;">
      <input type="hidden" id="correction-task-id">
      <div id="correction-items" style="display:flex; flex-direction:column; gap:16px;"></div>
      <div class="form-group" style="margin-top:16px;">
        <label>纠错原因（可选，会记入审计日志）</label>
        <input id="correction-reason" placeholder="如：OCR 把答案识别错了 / 知识点应归类为定语从句">
      </div>
    </div>
    <div style="padding:16px 24px; border-top:1px solid var(--border); display:flex; justify-content:space-between; align-items:center;">
      <span id="correction-status" style="font-size:.85em; color:var(--sub);"></span>
      <div class="btn-group" style="gap:8px;">
        <button class="btn btn-outline" onclick="closeCorrectionModal()">取消</button>
        <button class="btn btn-primary" onclick="submitCorrections()">提交纠错</button>
      </div>
    </div>
  </div>
</div>

<!-- ══════ MODAL: Student ══════ -->
<div class="modal-overlay" id="student-modal">
  <div class="modal" style="max-width:720px;">
    <h3 id="student-modal-title">添加学生</h3>

    <!-- Tab navigation -->
    <div style="display:flex;gap:4px;margin-bottom:16px;border-bottom:1px solid var(--border);flex-wrap:wrap;">
      <button class="profile-tab active" data-tab="basic" onclick="switchProfileTab('basic')" style="padding:8px 16px;border:none;background:none;border-bottom:2px solid var(--accent);font-weight:600;color:var(--text);">基本信息</button>
      <button class="profile-tab" data-tab="english" onclick="switchProfileTab('english')" style="padding:8px 16px;border:none;background:none;color:var(--sub);">英语学情</button>
      <button class="profile-tab" data-tab="traits" onclick="switchProfileTab('traits')" style="padding:8px 16px;border:none;background:none;color:var(--sub);">学习特质</button>
      <button class="profile-tab" data-tab="goals" onclick="switchProfileTab('goals')" style="padding:8px 16px;border:none;background:none;color:var(--sub);">目标与支持</button>
    </div>

    <!-- Basic Info Tab -->
    <div id="tab-basic" class="profile-tab-content" style="display:block;">
      <div class="form-row">
        <div class="form-group"><label>姓名 *</label><input id="f-name"></div>
        <div class="form-group"><label>年级</label><select id="f-grade"><option>高一</option><option selected>高二</option><option>高三</option></select></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>性别</label><select id="f-gender"><option value="">请选择</option><option>男</option><option>女</option></select></div>
        <div class="form-group"><label>学期</label><select id="f-semester"><option value="">请选择</option><option>上学期</option><option>下学期</option></select></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>住校/走读</label><select id="f-school-type"><option selected>住校</option><option>走读</option></select></div>
        <div class="form-group"><label>套餐</label><select id="f-plan"><option value="trial">体验（3次）</option><option value="monthly">包月</option><option value="yearly">包年</option><option value="unlimited">超级账号</option></select></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>英语成绩</label><input id="f-english-score" type="number" step="0.5"></div>
        <div class="form-group"><label>目标分数</label><input id="f-target-score" type="number" step="0.5"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>升学目标</label><input id="f-academic-goal" placeholder="如：稳住不下滑 / 冲刺130分"></div>
        <div class="form-group"><label>选科情况</label><select id="f-subject-choice"><option value="">请选择</option><option>文科</option><option>理科</option><option>未分科</option></select></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>教材版本</label><input id="f-textbook-version" placeholder="如：人教版必修2"></div>
        <div class="form-group"><label>家长姓名</label><input id="f-parent-name"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>家长微信</label><input id="f-parent-wechat"></div>
        <div class="form-group"><label>家长电话</label><input id="f-parent-phone"></div>
      </div>
      <div class="form-group" style="display:flex;align-items:center;gap:8px;">
        <input type="checkbox" id="f-parent-consent" style="width:auto;">
        <label for="f-parent-consent" style="margin-bottom:0;font-weight:400;">家长已同意收集和使用学生学习数据（未成年人合规授权）</label>
      </div>
      <div class="form-group"><label>备注</label><textarea id="f-notes"></textarea></div>
    </div>

    <!-- English Situation Tab -->
    <div id="tab-english" class="profile-tab-content" style="display:none;">
      <div class="form-row">
        <div class="form-group"><label>最近3-5次分数范围</label><input id="f-recent-scores" placeholder="如：85,92,88 或 85-95"></div>
        <div class="form-group"><label>最有挑战的方面</label><input id="f-weak-areas" placeholder="如：阅读理解长难句"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>失分主要原因</label><input id="f-score-loss-reason" placeholder="如：知识点不熟练 / 做题方法 / 粗心"></div>
        <div class="form-group"><label>优先提升题型（逗号分隔）</label><input id="f-weak-question-types" placeholder="完形填空,阅读理解,作文,听力"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>容易混淆的语法点</label><input id="f-confused-grammar" placeholder="如：定语从句关系词"></div>
        <div class="form-group"><label>已有学习资源</label><input id="f-existing-resources" placeholder="如：高考词汇书、真题册"></div>
      </div>
      <div class="form-group"><label>词汇方向</label>
        <select id="f-vocab-direction">
          <option value="">请选择</option>
          <option value="A">A. 匹配教材</option>
          <option value="B">B. 预习教材</option>
          <option value="C">C. 高考高频词汇</option>
          <option value="D">D. 混合模式</option>
        </select>
      </div>
      <div class="form-group"><label>时间全景图（按周安排）</label>
        <div id="time-map-editor" style="border:1px solid var(--border);border-radius:6px;padding:12px;background:var(--bg);">
          <table style="width:100%;font-size:.85em;">
            <thead>
              <tr style="color:var(--sub);">
                <th style="text-align:left;padding:4px;">星期</th>
                <th style="text-align:left;padding:4px;">开始</th>
                <th style="text-align:left;padding:4px;">结束</th>
                <th style="text-align:left;padding:4px;">内容</th>
                <th style="text-align:left;padding:4px;">性质</th>
                <th style="text-align:left;padding:4px;">精力</th>
                <th style="width:30px;"></th>
              </tr>
            </thead>
            <tbody id="time-map-slots"></tbody>
          </table>
          <button class="btn btn-sm btn-outline" onclick="addTimeSlot()" style="margin-top:8px;">+ 添加时段</button>
          <div style="margin-top:10px;">
            <label style="font-size:.8em;color:var(--sub);">补充说明</label>
            <textarea id="f-time-map-desc" rows="2" placeholder="如：考试周会取消周六上午时段..." style="margin-top:4px;"></textarea>
          </div>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>一周可用学习时长（小时）</label><input id="f-weekly-available-hours" type="number" step="0.5"></div>
        <div class="form-group"><label>孩子自愿承诺的英语时间（分钟/周）</label><input id="f-committed-english-minutes" type="number"></div>
      </div>
    </div>

    <!-- Learning Traits Tab -->
    <div id="tab-traits" class="profile-tab-content" style="display:none;">
      <div class="form-row">
        <div class="form-group"><label>学习类型</label>
          <select id="f-learning-style">
            <option value="">请选择</option>
            <option value="视觉型">视觉型（爱看、爱画、记笔记）</option>
            <option value="听觉型">听觉型（爱听、爱读、跟读）</option>
            <option value="动觉型">动觉型（动笔、拆解、做题）</option>
            <option value="读写型">读写型（阅读+写作）</option>
          </select>
        </div>
        <div class="form-group"><label>AI 学习风格测评</label>
          <div id="learning-style-radar" style="border:1px solid var(--border);border-radius:6px;padding:10px;background:var(--bg);">
            <p style="color:var(--sub);text-align:center;margin:20px 0;">完成首次 AI 诊断后将展示 4 维学习风格雷达图</p>
          </div>
        </div>
        <div class="form-group"><label>学习介质偏好</label>
          <select id="f-learning-medium">
            <option value="">请选择</option>
            <option value="纸质">纸质资料</option>
            <option value="电子">电子资料</option>
            <option value="混合">混合</option>
          </select>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>背单词习惯</label><input id="f-vocab-habit" placeholder="如：反复抄写 / 读出声"></div>
        <div class="form-group"><label>容易分心的环节</label><input id="f-attention-weakness" placeholder="如：做阅读时容易走神"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>过往有效方法</label><input id="f-effective-methods" placeholder="如：用思维导图记语法"></div>
        <div class="form-group"><label>过往无效方法</label><input id="f-ineffective-methods" placeholder="如：单纯抄单词"></div>
      </div>
      <div class="form-group"><label>与英语的关系</label>
        <select id="f-english-identity">
          <option value="">请选择</option>
          <option value="敌人">敌人 / 负担</option>
          <option value="工具">工具 / 任务</option>
          <option value="朋友">朋友 / 技能</option>
          <option value="兴趣">兴趣 / 爱好</option>
        </select>
      </div>
      <hr style="margin:16px 0;border:none;border-top:1px solid var(--border);">
      <p style="font-size:.85em;color:var(--sub);margin-bottom:12px;">小测评结果（可选填）</p>
      <div class="form-row">
        <div class="form-group"><label>注意力极限时长（分钟）</label><input id="f-attention-minutes" type="number" placeholder="如：25"></div>
        <div class="form-group"><label>词汇量自测等级</label>
          <div style="display:flex;gap:8px;align-items:flex-end;">
            <select id="f-vocab-level" style="flex:1;">
              <option value="">未测评</option>
              <option value="基础偏弱">基础偏弱</option>
              <option value="基础尚可">基础尚可</option>
              <option value="中上水平">中上水平</option>
              <option value="词汇较强">词汇较强</option>
            </select>
            <button class="btn btn-sm btn-outline" onclick="startVocabTest('f')" style="white-space:nowrap;padding:6px 14px;">📝 在线测评</button>
          </div>
        </div>
      </div>
      <div class="form-group"><label>学习场景偏好</label>
        <select id="f-scene-preference">
          <option value="">未测评</option>
          <option value="视觉助记">视觉助记（看+写）</option>
          <option value="音频跟读">音频跟读（听+读）</option>
          <option value="语境句子">语境句子（上下文理解）</option>
        </select>
      </div>
    </div>

    <!-- Goals Tab -->
    <div id="tab-goals" class="profile-tab-content" style="display:none;">
      <div class="form-row">
        <div class="form-group"><label>期望进步时间</label><input id="f-target-timeline" placeholder="如：3个月"></div>
        <div class="form-group"><label>1个月小目标</label><input id="f-one-month-goal" placeholder="如：阅读理解正确率提升到70%"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>家长每周陪学时间</label><input id="f-parent-availability" placeholder="如：周末1-2小时"></div>
        <div class="form-group"><label>需要监督吗</label>
          <select id="f-supervision-needed">
            <option value="0">主要靠孩子自主</option>
            <option value="1">需要每天检查</option>
          </select>
        </div>
      </div>
      <div class="form-group"><label>学习环境</label><input id="f-study-environment" placeholder="如：独立书房 / 客厅"></div>
      <hr style="margin:16px 0;border:none;border-top:1px solid var(--border);">
      <p style="font-size:.85em;color:var(--sub);margin-bottom:12px;">孩子的心声</p>
      <div class="form-row">
        <div class="form-group"><label>最不想做的事</label><input id="f-least-favorite-task" placeholder="如：背单词"></div>
        <div class="form-group"><label>期望强度</label>
          <select id="f-preferred-intensity">
            <option value="">请选择</option>
            <option value="轻松">轻松一点</option>
            <option value="中等">中等</option>
            <option value="上强度">可以上点强度</option>
          </select>
        </div>
      </div>
      <div class="form-group"><label>英语变厉害后想做什么</label><input id="f-aspirational-use" placeholder="如：看美剧不用字幕"></div>
      <hr style="margin:16px 0;border:none;border-top:1px solid var(--border);">
      <p style="font-size:.85em;color:var(--sub);margin-bottom:12px;">关键抉择</p>
      <div class="form-row">
        <div class="form-group"><label>模块配比</label>
          <select id="f-module-ratio">
            <option value="">请选择</option>
            <option value="主攻突破">主攻突破型（薄弱模块70%）</option>
            <option value="稳步推进">稳步推进型（词汇50%）</option>
          </select>
        </div>
        <div class="form-group"><label>难度起点</label>
          <select id="f-difficulty-start">
            <option value="">请选择</option>
            <option value="基础巩固">基础巩固起步</option>
            <option value="中等直入">中等难度直入</option>
          </select>
        </div>
      </div>
      <div class="form-group"><label>每日词汇量</label>
        <select id="f-daily-vocab">
          <option value="">请选择</option>
          <option value="5">每天5个（轻松）</option>
          <option value="8">每天8个（性价比最高）</option>
          <option value="10">每天10个（挑战）</option>
        </select>
      </div>
      <div class="form-row">
        <div class="form-group"><label>专属计划名称</label><input id="f-plan-name" placeholder="如：火箭计划"></div>
        <div class="form-group"><label>专属代号</label><input id="f-plan-code-name" placeholder="如：Rocket-2024"></div>
      </div>
    </div>

    <input type="hidden" id="f-student-id">
    <div class="btn-group" style="justify-content:flex-end;margin-top:16px;">
      <button class="btn btn-outline" onclick="closeStudentModal()">取消</button>
      <button class="btn btn-primary" onclick="saveStudent()">保存</button>
    </div>
  </div>
</div>

<!-- ══════ VOCAB TEST MODAL ══════ -->
<div class="modal-overlay" id="vocab-test-modal">
  <div class="modal" style="max-width:480px;text-align:center;">
    <div id="vt-intro">
      <h3 id="vt-title" style="margin-bottom:8px;">📝 词汇量快测</h3>
      <p id="vt-grade-hint" style="color:var(--sub);font-size:.9em;margin-bottom:20px;"></p>
      <div style="background:var(--bg);border-radius:10px;padding:20px;margin-bottom:20px;text-align:left;font-size:.9em;line-height:1.8;">
        <p style="margin-bottom:8px;">📋 <b>测试说明</b></p>
        <p>• 共 <b id="vt-total-q">60</b> 个单词，约 3 分钟</p>
        <p>• 看到单词，诚实判断<b>是否认识</b></p>
        <p>• 题目根据<b id="vt-grade-label">年级</b>要求自动匹配难度</p>
        <p>• 测试结束自动给出词汇量估算</p>
      </div>
      <button class="btn btn-primary" onclick="beginVocabTest()" style="font-size:1.1em;padding:12px 40px;">开始测评 🚀</button>
      <br><button class="btn btn-sm" onclick="closeVocabTest()" style="margin-top:12px;color:var(--sub);">跳过，手动选择</button>
    </div>
    <div id="vt-testing" style="display:none;">
      <div style="margin-bottom:8px;color:var(--sub);font-size:.85em;">
        进度 <span id="vt-progress-text">1/30</span>
        <span id="vt-band-hint" style="margin-left:12px;color:var(--accent);"></span>
      </div>
      <div class="progress-bar" style="margin-bottom:24px;"><div class="fill" id="vt-bar" style="width:0%"></div></div>
      <div style="font-size:2.2em;font-weight:700;margin:32px 0 12px;letter-spacing:1px;" id="vt-word"></div>
      <p style="color:var(--sub);font-size:.85em;margin-bottom:28px;">你认识这个词吗？</p>
      <div style="display:flex;gap:12px;justify-content:center;">
        <button class="btn btn-green" onclick="answerVocab(true)" style="font-size:1.1em;padding:12px 36px;min-width:120px;">✅ 认识</button>
        <button class="btn btn-outline" onclick="answerVocab(false)" style="font-size:1.1em;padding:12px 36px;min-width:120px;">❌ 不认识</button>
      </div>
    </div>
    <div id="vt-result" style="display:none;">
      <h3 style="margin-bottom:16px;">📊 测评结果</h3>
      <div style="background:var(--bg);border-radius:10px;padding:20px;margin-bottom:20px;">
        <div style="font-size:2.5em;font-weight:700;color:var(--accent);" id="vt-est-vocab">0</div>
        <div style="color:var(--sub);font-size:.9em;">估算词汇量</div>
        <div id="vt-level-badge" style="margin-top:12px;"></div>
        <div id="vt-band-detail" style="margin-top:16px;text-align:left;font-size:.85em;"></div>
      </div>
      <button class="btn btn-primary" onclick="applyVocabResult()" style="font-size:1.05em;padding:10px 32px;">✅ 应用结果</button>
      <br><button class="btn btn-sm" onclick="closeVocabTest()" style="margin-top:8px;color:var(--sub);">放弃，不保存</button>
    </div>
  </div>
</div>

<script>
// ── Helpers ──
function toast(msg, type='success') {
  const t = document.createElement('div'); t.className='toast toast-'+type; t.textContent=msg;
  document.body.appendChild(t); setTimeout(()=>t.remove(), 2500);
}
function fmtDate(d) { return d ? d.slice(0,10) : '-'; }
function icon(v) { return v ? '✅' : ''; }

async function viewStudentAnalytics(studentId) {
  switchPage('analytics');
  await loadAnalyticsPage();
  const sel = document.getElementById('analytics-student');
  if (sel && studentId) {
    sel.value = studentId;
    sel.dispatchEvent(new Event('change'));
  }
  window.scrollTo({top: 0, behavior: 'smooth'});
}

async function viewStudentMistakes(studentId) {
  // Look up student access_code and open public page at 成长记录 tab
  try {
    const r = await fetch('/api/students/' + studentId);
    const s = await r.json();
    if (s && s.access_code) {
      window.open('/s/' + s.access_code + '#mistakes', '_blank');
    } else {
      toast('无法获取学生链接');
    }
  } catch(e) {
    toast('获取学生信息失败');
  }
}

// Upload files with progress bar
function uploadFilesWithProgress(fileInput, studentId, fileType, uploaderRole) {
  return new Promise((resolve, reject) => {
    const fd = new FormData();
    for (const f of fileInput.files) fd.append('files', f);
    fd.append('student_id', studentId);
    fd.append('file_type', fileType);
    fd.append('uploader_role', uploaderRole);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/upload');

    // Show progress overlay
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.4);z-index:9999;display:flex;align-items:center;justify-content:center;';
    overlay.innerHTML = '<div style="background:#fff;border-radius:12px;padding:32px 40px;min-width:280px;text-align:center;box-shadow:0 4px 20px rgba(0,0,0,0.15);"><div style="font-size:1rem;font-weight:600;margin-bottom:16px;color:#1a1a1a;">上传中...</div><div style="background:#e8e6e1;border-radius:8px;height:8px;overflow:hidden;"><div id="upload-progress-bar" style="background:var(--accent, #e07b4b);height:100%;width:0%;transition:width 0.2s;"></div></div><div id="upload-progress-text" style="margin-top:10px;font-size:0.85rem;color:#6b6b6b;">0%</div></div>';
    document.body.appendChild(overlay);

    xhr.upload.onprogress = function(e) {
      if (e.lengthComputable) {
        const pct = Math.round((e.loaded / e.total) * 100);
        const bar = document.getElementById('upload-progress-bar');
        const text = document.getElementById('upload-progress-text');
        if (bar) bar.style.width = pct + '%';
        if (text) text.textContent = pct + '%';
      }
    };

    xhr.onload = function() {
      overlay.remove();
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        reject(new Error('Upload failed'));
      }
    };
    xhr.onerror = function() {
      overlay.remove();
      reject(new Error('Network error'));
    };
    xhr.send(fd);
  });
}

// ── Vocab Test ──
const VOCAB_BANKS = {
  '中考核心': {
    min: 0, max: 1600, words: [
      'accident','achieve','active','advantage','afford','announce','apologize','appreciate','attend','attitude','balance','barrier','belong','benefit','bitter','blame','border','bother','brave','breathe','calm','celebrate','challenge','character','charity','climate','communicate','community','compare','complete','concentrate','confident','congratulate','connect','consider','continue','convenient','courage','create','curious','damage','dangerous','decision','decline','defend','deliver','demand','depend','describe','deserve','design','destroy','determine','develop','devote','disappear','discover','distance','disturb','divide','eager','educate','effect','effort','embarrass','emerge','employ','enable','encourage','energy','enormous','enter','environment','escape','especially','eventually','evidence','examine','example','excellent','exchange','exercise','exist','expect','experience','experiment','explain','explore','express','extreme','familiar','favorite','fierce','figure','finance','fluent','forbid','force','fortunate','freedom','frequent','friendship','generous','genuine','global','gradual','grateful','guarantee','guard','handle','hesitate','honest','humorous','identify','ignore','illegal','imagine','immediate','import','impress','improve','include','increase','independent','indicate','influence','inform','innocent','insist','inspire','instruct','intelligent','intend','interview','introduce','invent','investigate','involve','issue','journey','judge','justice','knowledge','laughter','liberal','liberty','lonely','loyal','manage','manner','material','measure','mention','mercy','mild','minority','misunderstand','monitor','moral','motivate','mysterious','narrow','necessary','negotiate','nervous','normal','notice','numerous','observe','obstacle','obvious','operate','opinion','oppose','ordinary','organize','original','overcome','participate','particular','partner','passenger','patience','perfect','perform','permit','persuade','phenomenon','physical','pleasure','poison','polish','political','popular','population','portion','possess','potential','poverty','practical','precious','predict','prefer','prepare','preserve','pretend','prevent','principle','private','probable','proceed','produce','profit','progress','prohibit','promise','promote','proper','protect','protest','proud','provide','publish','punctual','punish','purpose','pursue','qualify','quality','quantity','rapid','rare','realize','reasonable','recognize','recommend','recover','reduce','refer','reflect','regular','reject','relate','relative','relax','relevant','reliable','relief','remain','remark','remarkable','remove','replace','reputation','request','require','research','reserve','resign','resist','resolve','respect','respond','responsible','restore','result','reveal','review','reward','ridiculous','risk','satisfy','scare','schedule','secure','select','sensitive','separate','serious','service','settle','severe','shadow','shallow','shelter','signal','significance','similar','simple','slight','social','somehow','sorrow','source','specific','spiritual','stable','standard','starve','struggle','stubborn','succeed','suffer','sufficient','suggest','suitable','supply','support','suppose','surprise','surround','survive','suspect','symbol','sympathy','system','talent','temperature','temporary','tend','thorough','threaten','tolerate','tough','tradition','transform','tremble','trend','trial','trick','typical','undergo','unique','universal','urban','urge','value','various','victim','violence','virtue','visual','voluntary','volunteer','wander','welfare','widespread','willing','wisdom','witness','worthwhile',
    ]
  },
  '高考基础': {
    min: 1600, max: 2800, words: [
      'abandon','abolish','abroad','abrupt','absence','absolute','absorb','abstract','absurd','abundant','academic','accelerate','accessible','accommodate','accompany','accomplish','accountant','accumulate','accurate','acknowledge','acquire','adapt','adequate','adjust','administration','adopt','aggressive','allocate','alternative','amateur','ambition','analyze','ancestor','anniversary','annual','anticipate','anxiety','apparent','appeal','appetite','applaud','applicant','appoint','approach','appropriate','approve','architecture','arise','arrange','artificial','assess','assign','associate','assume','atmosphere','attach','attempt','authentic','authority','automatic','available','avenue','average','aware','awkward','bargain','barrier','behalf','behave','beneficial','betray','billion','biography','blanket','boundary','budget','burden','calculate','campaign','candidate','capable','capacity','capture','career','catalog','category','caution','ceremony','certificate','champion','characteristic','circumstance','civilization','clarify','classic','classify','collapse','colleague','commercial','commission','commit','committee','companion','compensate','competence','complaint','complex','component','compose','comprehension','compromise','concentrate','concept','concrete','condition','conduct','confidential','confirm','conflict','conscience','conscious','consequence','conservative','considerate','consistent','constant','constitution','construct','consumption','contemporary','contradict','controversial','convenience','conventional','convince','cooperate','correspond','council','criterion','criticize','crucial','cultivate','curiosity','curriculum','deadline','declaration','dedicate','definitely','definition','delegate','deliberate','delicate','democratic','demonstrate','deposit','depression','derive','desperate','destination','dignity','dilemma','dimension','diploma','disability','discipline','discrimination','dismiss','distinction','distinguish','distribute','diverse','domestic','dominate','donation','dramatic','duration','efficient','elaborate','election','elegant','eliminate','embassy','emerge','emergency','emphasis','encounter','endeavor','enforce','enormous','enterprise','enthusiasm','essential','establish','evaluate','evolution','exaggerate','exceed','exception','execute','exhibition','expansion','expense','exploit','extension','extraordinary','facility','faith','fascinating','fatal','flexible','forecast','foundation','fragile','framework','friction','fulfill','fundamental','generate','genuine','govern','graceful','gradual','grateful','guarantee','guidance','harmony','highlight','horizon','household','identical','identity','illustrate','immigrant','impact','implement','implication','impose','incident','incorporate','infect','inflation','ingredient','initiative','innovation','input','inspection','institute','instrument','insurance','integrate','integrity','intellectual','intense','interact','interpret','interrupt','investigation','investment','isolate','jealous','justice','justify','landscape','launch','legislation','liberty','limitation','literature','logical','magnificent','maintain','manufacture','mature','maximum','mechanism','memorial','minimum','moderate','monument','motivation','negotiate','nightmare','nutrition','objective','obligation','occupation','opponent','opportunity','optimistic','origin','outcome','outstanding','overlook','ownership','parliament','passion','patent','patience','patriotic','pension','perceive','permanent','perspective','phenomenon','philosophy','pile','platform','pledge','portion','portrait','possess','potential','precaution','precise','prejudice','premier','prescribe','preserve','primitive','principle','priority','procedure','profession','prohibit','prominent','proportion','prospect','prosperity','psychology','publication','purchase','qualification','radiation','random','reception','reckon','recognition','recommend','recreation','registration','regulate','relevant','reputation','resemble','resolution','restore','restriction','reveal','revenue','revolution','routine','sacrifice','satellite','satisfaction','scholarship','senator','sensitive','sequence','significance','sketch','souvenir','specialist','specify','splendid','sponsor','statistics','status','stimulate','strategy','subjective','submit','subscribe','substitute','sufficient','summarize','superior','supplement','surrender','suspect','suspicion','sustainable','symbol','sympathy','tackle','temporary','tendency','territory','testify','therapy','tolerate','tournament','tragedy','transform','transition','transparent','tremendous','triumph','ultimate','undergo','undertake','unemployment','unique','universal','urban','utilize','valid','verify','version','vessel','veteran','violate','vivid','voluntary','vulnerable','widespread','withdraw','witness','worthwhile',
    ]
  },
  '高考进阶': {
    min: 2800, max: 3800, words: [
      'abolish','abortion','abrupt','absorb','abstract','absurd','abundance','accessory','accommodate','accountability','accumulate','acquaintance','acupuncture','addictive','adolescent','adverse','advocate','aesthetic','aggregate','agony','allege','alleviate','allocate','ambiguous','amend','analogy','anonymous','apparatus','appraisal','aptitude','array','articulate','ascend','ascribe','assassinate','assault','assert','assimilate','astronomy','athletic','atlas','attorney','audit','authentic','authorize','aviation','bankruptcy','barren','bearing','bibliography','bilateral','biochemistry','bishop','bizarre','blaze','blessing','blossom','boycott','breakdown','brewery','brochure','bronze','browse','bruise','brutal','bureaucracy','calorie','cardinal','casualty','catastrophe','cater','cathedral','Catholic','caution','census','champagne','chant','cherish','cholesterol','chronic','chunk','circulation','cite','civic','clamp','clan','clarity','clash','clasp','cloak','clockwise','cluster','coalition','cognitive','coherent','coincide','collaborate','collision','colonial','comet','commemorate','commence','commend','commentary','commitment','commodity','commonplace','commute','compact','compatible','compel','compensate','compilation','complement','complication','comply','compulsory','concede','conceive','conception','concise','condemn','condense','confer','confidential','configuration','conform','confront','congress','conquest','conscientious','consecutive','consensus','console','consolidate','conspicuous','constituent','constrain','contaminate','contemplate','contempt','contend','continuity','contradiction','contrive','convene','conversion','convict','cooperative','cordial','corporate','corpse','correlate','corrode','corrupt','cosmetic','counsel','counterpart','courtesy','cradle','credential','cripple','crisp','criterion','crucial','cruise','culminate','cumulative','curb','cynical','dazzle','deadline','decree','dedicate','deduce','deduct','default','defendant','defiance','deficiency','defy','delegate','deliberate','demographic','denial','denounce','depict','deploy','depreciate','depress','deprive','designate','destined','detach','detain','deteriorate','diagnose','differentiate','diffuse','dignity','dilemma','diligent','dilute','diminish','diploma','directory','disable','disastrous','discern','discharge','disclose','discourse','discrepancy','discrete','discriminate','disperse','displace','disposition','disregard','disrupt','dissipate','distil','distort','diversion','dividend','divine','dock','doctrine','domain','dome','drainage','drastic','drawback','drought','dubious','duplicate','dwarf','dwell','ecological','ecosystem','eject','elapse','elevate','elicit','eligible','elite','eloquent','embark','embed','embody','emigrate','emission','empirical','enact','enclose','endanger','endow','enforcement','enlighten','enrich','enrol','ensemble','entail','entrepreneur','envisage','epidemic','epoch','equator','equivalent','erosion','erroneous','erupt','escort','essence','esteem','eternal','evacuate','evaporate','evoke','exceedingly','excerpt','exempt','exile','exotic','expedition','expenditure','expertise','expire','explicit','exposition','exquisite','extinct','extinguish','extract','extravagant','fabricate','facet','facilitate','feminine','ferry','finite','fiscal','fixture','flaw','foam','foil','foremost','formidable','formulate','foster','fracture','friction','fringe','furious','fusion','futile','galaxy','gasp','gauge','gender','genetic','gigantic','glacier','glamour','gland','gleam','glitter','gloom','gorgeous','gossip','grant','graphic','graze','grieve','grim','grin','groan','guerrilla','gymnasium','habitat','hail','hamper','handicap','harassment','harsh','haul','haunt','hazard','heed','hemisphere','henceforth','herb','heritage','hierarchy','hike','hinder','hitherto','hoist','homogeneous','hospitality','hostage','hover','huddle','humanity','humidity','hurl','hurricane','hypothesis','ideology','idiot','ignite','illuminate','illusion','immerse','immune','impair','impart','imperative','imperial','impetus','implement','implicit','impulse','inaugurate','incentive','incidence','inclination','inclusive','incorporate','incur','indefinite','indicative','indignant','indispensable','induce','indulge','inertia','infectious','inflict','ingenious','inherent','inhibit','initiate','inject','inlet','innovation','innumerable','insane','instantaneous','intact','integral','integrity','intellect','intelligible','intensify','interim','intermittent','intersection','intervene','intimidate','intricate','intrinsic','intuition','invalid','invaluable','invariably','inventory','invert','irony','irrespective','irrigation','irritate','ivory','jeopardize','judicial','junction','jurisdiction','juvenile','kidnap','kit','knit','knob','lace','lame','latitude','layman','leaflet','legacy','legend','legislation','legitimate','lever','levy','liability','likelihood','limb','linear','linger','literacy','locomotive','longitude','loom','lounge','lubricate','luminous','lunar','magnify','manifest','manipulate','manoeuvre','manuscript','marginal','marsh','marshal','masculine','massacre','masterpiece','meadow','mechanism','mediate','medieval','melody','memorandum','menace','merge','metaphor','metropolitan','midst','migrant','militant','mingle','miniature','minimize','misery','missionary','mob','mobilize','mock','momentum','monetary','monopoly','monster','mortal','mortgage','murmur','muscular','mute','mutter','naive','narrative','nasty','necessitate','negligible','negotiate','nominal','nominate','nonetheless','norm','notable','notorious','notwithstanding','nourish','novelty','nurture','oath','obedient','obligation','obscene','obscure','odor','offset','olive','opaque','ordeal','orient','oriental','orientation','originate','ornament','orthodox','outbreak','outfit','outrage','overflow','overhear','overlap','overt','overthrow','overturn','overwhelm','oxide','pamphlet','paradise','paradox','parameter','parasite','pastime','pasture','pathetic','patrol','patron','pedestrian','penalty','pendulum','penetrate','perfection','perfume','periodic','perish','permeate','permissible','perpetual','perplex','persistent','petition','petty','pharmacy','physiological','pilgrim','pirate','plea','plead','plight','plumber','plunge','poke','polar','ponder','porcelain','portray','posterity','posture','practitioner','preach','precede','precedent','precision','predominant','premier','premise','premium','prescription','preside','prestige','presume','pretext','prevalent','prey','probe','proceeding','proclaim','productive','proficiency','profound','progressive','prolong','promising','prone','propaganda','propel','prophet','proposition','prosecute','prospective','prototype','provocative','provoke','proximity','prune','psychiatrist','pumpkin','purify','pursuit','qualitative','quantify','quantitative','quest','quota','radiant','rally','rating','reap','reassure','recede','recipient','reciprocal','recite','reckless','reclaim','reconcile','rectify','recur','redundant','referee','refrain','refuge','refund','refute','regime','rein','rejoice','relay','relentless','remainder','renaissance','repay','repel','repertoire','repression','reproach','resemblance','resent','reside','residential','resonance','restrain','resultant','retain','retort','retrieve','retrospect','revelation','revenge','revive','rhetoric','rigorous','rim','rip','ritual','robust','rot','sacred','safeguard','salute','savage','scandal','scramble','scrap','scrutiny','sculpture','seam','segment','segregate','sentiment','sergeant','serial','shabby','shatter','shepherd','shove','shrewd','shuttle','siege','sieve','signify','silicon','simulate','simultaneously','sip','skeleton','skeptical','skip','slash','slaughter','slot','smuggle','snatch','soar','sociology','solemn','solidarity','solo','sovereign','spacious','sparkle','speciality','specification','spectacle','spectator','spectrum','spice','spiral','splash','spokesman','spontaneous','stabilize','stagger','stalk','stall','stance','staple','statesman','stationary','stereo','stereotype','stern','steward','stitch','straightforward','strand','stray','streamline','stride','strive','stroll','stumble','sturdy','submarine','subordinate','substantial','subtle','successor','sue','suffice','suite','summit','summon','superb','superficial','superintendent','supersonic','surge','susceptible','suspension','suspicious','swamp','symmetry','symphony','symposium','syndrome','synthesis','tablet','tactics','tangle','tariff','tease','tedious','temperament','tempt','tenant','tentative','terrain','testify','testimony','texture','thereafter','thermal','threshold','thrill','throne','tick','tile','tilt','token','toll','torment','toss','toxic','trait','transaction','transcend','transient','transit','traverse','trench','tribe','tribute','trifle','trigger','triple','tropical','tuck','tug','tuition','tumble','turbulent','turnover','ultraviolet','unanimous','underestimate','underlying','undermine','unfold','unify','update','upgrade','uphold','utilize','utmost','vacuum','validity','valve','vegetation','vein','velocity','velvet','ventilate','venture','verdict','verge','versatile','verse','veto','vicious','vocal','vocational','void','vulgar','vulnerable','wardrobe','warehouse','warfare','warrant','watertight','weary','weird','whereby','whirl','wholesale','wither','wreck','yell','zeal',
    ]
  },
  '大学四级': {
    min: 3800, max: 5500, words: [
      'aberration','abrogate','accolade','acquiesce','acrimony','admonish','aesthetic','affable','aggrandize','alacrity','amalgamate','ambidextrous','ameliorate','anachronism','anathema','antediluvian','antithesis','apathetic','aplomb','approbation','arbitrary','arduous','articulate','asperity','assiduous','attenuate','auspicious','avarice','bellicose','belligerent','benevolent','bequeath','besmirch','bifurcate','bilious','blandishment','blasphemy','boisterous','bombastic','brevity','bucolic','cacophony','callous','calumny','candor','capitulate','capricious','castigate','catalyst','caustic','chagrin','charlatan','chicanery','circumlocution','circumspect','clamor','clandestine','clemency','coercion','cogent','commensurate','complacent','complaisant','conciliatory','concomitant','condescend','confound','congenial','conjecture','connoisseur','consternation','contentious','contrite','conundrum','copious','corroborate','credulous','culpable','cursory','dauntless','debacle','decorum','deference','delineate','demagogue','demure','denigrate','deprecate','derelict','desiccate','despondent','destitute','diaphanous','diatribe','dichotomy','diffident','dilatory','diminution','disaffected','discomfit','discursive','disparage','disseminate','dissolution','docile','dogmatic','draconian','dubiety','ebullient','edify','effervescent','efficacious','egregious','elegy','elucidate','emaciated','embellish','emollient','empirical','encomium','endemic','enervate','engender','ephemeral','equanimity','equivocate','erudite','esoteric','ethereal','euphemism','evanescent','exacerbate','excoriate','execrable','exigent','exonerate','expatriate','expeditious','extol','facetious','fallacious','fastidious','fatuous','fecund','felicitous','fervent','flippant','florid','forbearance','fortuitous','fractious','frivolous','fulsome','garrulous','gauche','germane','grandiloquent','gregarious','hackneyed','hapless','harangue','hedonism','hegemony','hermetic','hubris','iconoclast','idiosyncratic','ignominious','imbroglio','immutable','impartial','impecunious','imperious','impertinent','impervious','impetuous','implacable','impudent','impugn','inchoate','incipient','incorrigible','indolent','ineffable','ineluctable','inexorable','ingenuous','inimical','innocuous','inscrutable','insidious','insolvent','intransigent','intrepid','inundate','inveterate','irascible','irreverent','itinerant','juxtapose','kudos','laconic','lambaste','languid','largesse','lassitude','lethargic','levity','litigious','loquacious','lugubrious','magnanimous','malfeasance','malinger','mendacious','mercurial','meretricious','metamorphosis','meticulous','misanthrope','mitigate','mollify','moribund','munificent','myopic','nebulous','nefarious','neophyte','nexus','nonchalant','noxious','obdurate','obfuscate','oblique','obsequious','obsolete','obstinate','officious','omnipotent','omniscient','onerous','opprobrious','ostentatious','palliative','panacea','paradigm','paragon','pariah','parsimonious','partisan','paucity','pedantic','pejorative','penchant','penurious','perennial','perfidious','perfunctory','peripatetic','pernicious','perspicacious','pertinacious','petulant','philanthropic','phlegmatic','placate','platitude','plethora','polemic','pragmatic','precarious','precipitous','preclude','precocious','predilection','preponderance','prescient','presumptuous','prevaricate','primordial','proclivity','prodigious','profligate','prognosticate','proletariat','promulgate','propensity','propitious','prosaic','proscribe','protean','protuberant','provincial','pugnacious','punctilious','pundit','quagmire','quandary','querulous','quintessential','quixotic','quotidian','rancor','rapacious','rarefied','recalcitrant','recant','recondite','redoubtable','refractory','relegate','remonstrate','renascent','repartee','replete','reprobate','reprove','repudiate','requisite','rescind','resilient','resplendent','restive','resurgent','reticent','retrograde','revile','ribald','rife','ruminate','rustic','sagacious','salient','sanctimonious','sanguine','sardonic','savant','scintillate','scrupulous','sedentary','seminal','serendipity','servile','sibilant','solicitous','somnolent','sophistry','specious','sporadic','spurious','squalid','stolid','stringent','strident','subjugate','subliminal','subterfuge','succinct','suffrage','sundry','supercilious','supine','supplicate','surfeit','surreptitious','sycophant','taciturn','tangible','tantamount','temerity','tempestuous','tenacious','tendentious','terse','torpid','tractable','transgress','transitory','trenchant','trepidation','truculent','turgid','ubiquitous','umbrage','unctuous','unequivocal','unprecedented','unscrupulous','upbraid','urbane','usurp','vacillate','vapid','vehement','venal','venerable','verbose','verdant','verisimilitude','vicarious','vicissitude','vigilant','vilify','vindicate','virtuoso','viscous','vitriolic','vituperate','vivacious','vociferous','volatile','voracious','wanton','winsome','wizened','xenophobia','zealous','zenith',
    ]
  }
};

// Grade → bands mapping for test composition
const GRADE_VOCAB_PLAN = {
  '高一': { label: '高一（目标~2000词，高考基础起步）', bands: [
    { name: '中考核心', count: 20, weight: 0.25 },
    { name: '高考基础', count: 24, weight: 0.45 },
    { name: '高考进阶', count: 16, weight: 0.30 },
  ]},
  '高二': { label: '高二（目标~2800词，高考进阶为主）', bands: [
    { name: '中考核心', count: 10, weight: 0.15 },
    { name: '高考基础', count: 20, weight: 0.35 },
    { name: '高考进阶', count: 24, weight: 0.40 },
    { name: '大学四级', count: 6, weight: 0.10 },
  ]},
  '高三': { label: '高三（目标~3500词，冲刺高考）', bands: [
    { name: '高考基础', count: 16, weight: 0.25 },
    { name: '高考进阶', count: 30, weight: 0.55 },
    { name: '大学四级', count: 14, weight: 0.20 },
  ]},
};

let _vtState = null;

function startVocabTest(prefix) {
  // Determine grade: onboarding uses onb-grade, student modal uses f-grade
  const gradeEl = document.getElementById(prefix === 'onb' ? 'onb-grade' : 'f-grade');
  const grade = gradeEl ? gradeEl.value : '高二';
  const plan = GRADE_VOCAB_PLAN[grade] || GRADE_VOCAB_PLAN['高二'];

  // Build test words
  const words = [];
  plan.bands.forEach(band => {
    const pool = VOCAB_BANKS[band.name];
    if (!pool) return;
    const shuffled = [...pool.words].sort(() => Math.random() - 0.5);
    for (let i = 0; i < Math.min(band.count, shuffled.length); i++) {
      words.push({ word: shuffled[i], band: band.name });
    }
  });
  // Shuffle the test order
  words.sort(() => Math.random() - 0.5);

  _vtState = {
    prefix,
    grade,
    plan,
    words,
    currentIdx: 0,
    answers: [],       // {word, band, known: bool}
    total: words.length,
  };

  // Setup intro screen
  document.getElementById('vt-title').textContent = '📝 词汇量快测';
  document.getElementById('vt-grade-hint').textContent = plan.label;
  document.getElementById('vt-total-q').textContent = words.length;
  document.getElementById('vt-grade-label').textContent = grade;
  document.getElementById('vt-intro').style.display = 'block';
  document.getElementById('vt-testing').style.display = 'none';
  document.getElementById('vt-result').style.display = 'none';
  document.getElementById('vocab-test-modal').classList.add('show');
}

function beginVocabTest() {
  document.getElementById('vt-intro').style.display = 'none';
  document.getElementById('vt-testing').style.display = 'block';
  showVocabWord();
}

function showVocabWord() {
  const st = _vtState;
  if (st.currentIdx >= st.total) { finishVocabTest(); return; }
  const item = st.words[st.currentIdx];
  document.getElementById('vt-word').textContent = item.word;
  document.getElementById('vt-progress-text').textContent = `${st.currentIdx + 1}/${st.total}`;
  document.getElementById('vt-bar').style.width = `${((st.currentIdx) / st.total) * 100}%`;
  document.getElementById('vt-band-hint').textContent = '';
}

function answerVocab(known) {
  const st = _vtState;
  const item = st.words[st.currentIdx];
  st.answers.push({ word: item.word, band: item.band, known });
  st.currentIdx++;
  if (st.currentIdx >= st.total) {
    finishVocabTest();
  } else {
    showVocabWord();
  }
}

function finishVocabTest() {
  document.getElementById('vt-testing').style.display = 'none';
  document.getElementById('vt-result').style.display = 'block';

  const st = _vtState;
  // Calculate per-band stats
  const bandStats = {};
  st.answers.forEach(a => {
    if (!bandStats[a.band]) bandStats[a.band] = { total: 0, known: 0 };
    bandStats[a.band].total++;
    if (a.known) bandStats[a.band].known++;
  });

  // Estimate vocab size: weighted sum of band midpoints * recognition rate
  let estVocab = 0;
  let totalWeight = 0;
  Object.entries(bandStats).forEach(([bandName, stats]) => {
    const band = VOCAB_BANKS[bandName];
    if (!band) return;
    const rate = stats.known / stats.total;
    const mid = (band.min + band.max) / 2;
    const weight = stats.total;
    estVocab += mid * rate * weight;
    totalWeight += weight;
  });
  estVocab = Math.round(estVocab / Math.max(totalWeight, 1));

  // Map to level
  let level, levelColor;
  if (estVocab < 1600) { level = '基础偏弱'; levelColor = 'var(--red)'; }
  else if (estVocab < 2500) { level = '基础尚可'; levelColor = 'var(--accent)'; }
  else if (estVocab < 3300) { level = '中上水平'; levelColor = 'var(--blue)'; }
  else { level = '词汇较强'; levelColor = 'var(--green)'; }

  document.getElementById('vt-est-vocab').textContent = estVocab;
  document.getElementById('vt-level-badge').innerHTML = `<span style="display:inline-block;padding:4px 16px;border-radius:16px;font-weight:600;background:${levelColor}20;color:${levelColor};">${level}</span>`;

  // Per-band detail
  const bandOrder = ['中考核心','高考基础','高考进阶','大学四级'];
  document.getElementById('vt-band-detail').innerHTML = bandOrder.filter(b => bandStats[b]).map(b => {
    const s = bandStats[b];
    const rate = Math.round(s.known / s.total * 100);
    const barColor = rate >= 80 ? 'var(--green)' : rate >= 50 ? 'var(--accent)' : 'var(--red)';
    return `<div style="margin-bottom:8px;">
      <div style="display:flex;justify-content:space-between;font-size:.85em;"><span>${b}</span><span>${s.known}/${s.total} (${rate}%)</span></div>
      <div class="progress-bar" style="height:6px;margin-top:2px;"><div class="fill" style="width:${rate}%;background:${barColor};"></div></div>
    </div>`;
  }).join('');

  _vtState.estVocab = estVocab;
  _vtState.level = level;
}

function applyVocabResult() {
  const prefix = _vtState.prefix;
  const selId = prefix === 'onb' ? 'onb-vocab-level' : 'f-vocab-level';
  const sel = document.getElementById(selId);
  if (sel) sel.value = _vtState.level;
  closeVocabTest();
  toast(`词汇测评完成：估算 ${_vtState.estVocab} 词，等级「${_vtState.level}」`);
}

function closeVocabTest() {
  document.getElementById('vocab-test-modal').classList.remove('show');
}

// ── Navigation ──
function switchPage(name) {
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.nav button').forEach(b=>b.classList.remove('active'));
  document.getElementById('page-'+name).classList.add('active');
  const navBtn = document.querySelector(`.nav button[data-page="${name}"]`);
  if (navBtn) navBtn.classList.add('active');
  if (name==='dashboard') loadDashboard();
  if (name==='students') loadStudents();
  if (name==='weekly') loadWeeklyPage();
  if (name==='analytics') loadAnalyticsPage();
  if (name==='bank') loadBankPage();
  if (name==='quality') loadQualityPage();
  if (name==='referrals') loadReferralsPage();
  if (name==='classes') loadClassesPage();
  if (name==='admin') loadAdminPage();
  if (name==='observability') loadObservabilityPage();
  if (name==='compliance') loadCompliance();
  if (name==='teacher-profile') loadTeacherProfilePage();
}

// ── Dashboard ──
async function loadDashboard() {
  const r = await fetch('/api/dashboard'); const d = await r.json();
  document.getElementById('stats-bar').innerHTML = `
    <div class="stat"><div class="num">${d.total_students}</div><div class="label">总学生数</div></div>
    <div class="stat ok"><div class="num">${d.active_subscriptions}</div><div class="label">有效订阅</div></div>
    <div class="stat info"><div class="num">${d.trial_count}</div><div class="label">试用中</div></div>
    <div class="stat warn"><div class="num">${d.pending_this_week}</div><div class="label">本周待处理</div></div>
    <div class="stat" style="background:var(--blue-light);"><div class="num" style="color:var(--blue);">${d.question_bank ? d.question_bank.total_questions : 0}</div><div class="label">题库题目</div></div>
  `;
  document.getElementById('week-label').textContent = '周期：' + d.week_start + ' 起';

  // P3-13：审核队列已移除。逐条纠错入口见「周度服务 → 任务历史」。

  // Teacher workload
  const tw = d.teacher_workload || {};
  const pendingPaperCount = tw.pending_paper_uploads ? tw.pending_paper_uploads.length : 0;
  document.getElementById('teacher-workload').innerHTML = `
    <div class="stat warn"><div class="num">${pendingPaperCount}</div><div class="label">本周待上传试卷</div></div>
  `;

  // Pending paper uploads
  const pptbody = document.querySelector('#pending-paper-table tbody');
  pptbody.innerHTML = '';
  if (tw.pending_paper_uploads && tw.pending_paper_uploads.length > 0) {
    tw.pending_paper_uploads.forEach(s => {
      pptbody.innerHTML += `<tr>
        <td><strong>${escapeHtml(s.name)}</strong></td>
        <td>${s.grade || ''}</td>
        <td><button class="btn btn-sm btn-primary" onclick="runWeeklyForStudent(${s.id})">去上传</button></td>
      </tr>`;
    });
  } else {
    pptbody.innerHTML = '<tr><td colspan="3" style="text-align:center;color:var(--sub);">🎉 所有学生本周已上传试卷</td></tr>';
  }

  // AI correction trend
  try {
    const cr = await fetch('/api/corrections/stats?days=7');
    const cs = await cr.json();
    const topPoints = (cs.top_knowledge_points || []).map(p =>
      `<span class="badge badge-blue" style="margin-right:6px;">${p.point} (${p.count})</span>`
    ).join('') || '<span style="color:var(--sub);">暂无</span>';
    document.getElementById('correction-trend').innerHTML = `
      <div class="stat"><div class="num">${cs.total || 0}</div><div class="label">纠错总数</div></div>
      <div class="stat ok"><div class="num">${cs.effective || 0}</div><div class="label">有效纠错</div></div>
      <div class="stat warn"><div class="num">${(cs.repeat_ratio * 100).toFixed(0)}%</div><div class="label">问题重复率</div></div>
      <div class="stat" style="flex:2; min-width:220px;"><div style="font-size:.9em;font-weight:600;margin-bottom:4px;">Top3 易错知识点</div><div>${topPoints}</div></div>
    `;
  } catch(e) { console.error('Correction stats load failed', e); }

  // P3-13：审核复选框（select-all/selected-count）已随审核队列删除

  // Subscription alerts
  const etbody = document.querySelector('#expiring-table tbody');
  etbody.innerHTML = '';
  if (d.expiring_subscriptions && d.expiring_subscriptions.length > 0) {
    d.expiring_subscriptions.forEach(s => {
      const days = s.days_remaining;
      const daysText = days === null ? '-' : (days < 0 ? `已过期 ${-days} 天` : (days === 0 ? '今天到期' : `剩余 ${days} 天`));
      const daysClass = days === null ? '' : (days < 3 ? 'color:var(--red);font-weight:600;' : (days < 7 ? 'color:var(--accent);' : 'color:var(--sub);'));
      etbody.innerHTML += `<tr>
        <td><strong>${escapeHtml(s.name)}</strong></td>
        <td>${s.grade||''}</td>
        <td><span class="badge badge-${s.plan||'trial'}">${s.plan_label||'试用'}</span></td>
        <td>${s.end_date||'-'}</td>
        <td style="${daysClass}">${daysText}</td>
        <td><button class="btn btn-sm btn-primary" data-name="${escapeHtml(s.name)}" onclick="manageSub(${s.id}, this.dataset.name)">续费</button></td>
      </tr>`;
    });
  } else {
    etbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--sub);">暂无到期提醒（7天内到期或已过期）</td></tr>';
  }

  // Pending
  const tbody = document.querySelector('#pending-table tbody');
  tbody.innerHTML = '';
  (d.pending||[]).forEach(s => {
    // P2-11：链路状态列 —— 周期状态机当前态，中间态停留超 48h 标红告警
    const stageBadge = s.stuck
      ? `<span class="badge" style="background:var(--red-light);color:var(--red);" title="中间态停留超过48小时，请检查任务或重新触发">⚠ ${s.stage_label}·卡住</span>`
      : `<span class="badge" style="background:var(--blue-light);color:var(--blue);">${s.stage_label}</span>`;
    tbody.innerHTML += `<tr>
      <td><strong>${escapeHtml(s.name)}</strong></td><td>${s.grade}</td>
      <td><span class="badge badge-${s.plan||'trial'}">${s.plan_label||'试用'}</span></td>
      <td>${icon(s.paper_submitted)}</td><td>${icon(s.paper_analyzed)}</td>
      <td>${icon(s.exercises_sent)}</td><td>${icon(s.exercises_graded)}</td>
      <td>${icon(s.report_sent)}</td>
      <td>${stageBadge}</td>
    </tr>`;
  });

  // Cost and budget
  try {
    const cr = await fetch('/api/cost'); const cd = await cr.json();
    document.getElementById('cost-today').textContent = cd.today.toFixed(4);
    document.getElementById('cost-month').textContent = cd.month.toFixed(4);
    document.getElementById('student-budget').textContent = cd.monthly_student_budget.toFixed(2);
    document.getElementById('budget-text').textContent = `$${cd.month.toFixed(2)} / $${cd.monthly_total_budget.toFixed(2)} (${cd.total_budget_used_pct}%)`;

    const bar = document.getElementById('budget-bar');
    bar.style.width = Math.min(cd.total_budget_used_pct, 100) + '%';
    bar.style.background = cd.total_budget_used_pct >= 100 ? 'var(--red)' : (cd.total_budget_used_pct >= 80 ? 'var(--accent)' : 'var(--green)');

    if (document.getElementById('budget-total')) document.getElementById('budget-total').value = cd.monthly_total_budget;
    if (document.getElementById('budget-student')) document.getElementById('budget-student').value = cd.monthly_student_budget;

    const ctbody = document.querySelector('#cost-breakdown-table tbody');
    ctbody.innerHTML = '';
    if (cd.breakdown && cd.breakdown.length > 0) {
      cd.breakdown.forEach(stu => {
        const pct = cd.monthly_student_budget > 0 ? (stu.cost / cd.monthly_student_budget * 100).toFixed(1) : 0;
        const costColor = stu.cost >= cd.monthly_student_budget ? 'color:var(--red);font-weight:600;' : 'color:var(--sub);';
        if (stu.cost > 0 || stu.calls > 0) {
          ctbody.innerHTML += `<tr>
            <td>${stu.name}</td>
            <td>${stu.calls}</td>
            <td style="${costColor}">$${stu.cost.toFixed(4)}</td>
            <td>${pct}%</td>
          </tr>`;
        }
      });
      if (ctbody.innerHTML === '') {
        ctbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--sub);">本月暂无 LLM 调用记录</td></tr>';
      }
    } else {
      ctbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--sub);">本月暂无 LLM 调用记录</td></tr>';
    }
  } catch(e) { console.error('Cost load failed', e); }

  // Active alerts banner
  try {
    await loadObservabilityAlerts('dashboard-alert-banner');
  } catch(e) { console.error('Alerts load failed', e); }

  // Recent failures quick tip
  try {
    const fr = await fetch('/api/tasks/recent-failures?limit=5');
    if (fr.ok) {
      const failures = await fr.json();
      const tip = document.getElementById('dashboard-failure-tip');
      if (failures.length > 0) {
        tip.style.display = 'block';
        document.getElementById('dashboard-failure-text').textContent =
          `⚠️ 近24小时有 ${failures.length} 个任务失败，点击查看详情`;
      } else {
        tip.style.display = 'none';
      }
    }
  } catch(e) { console.error('Failure tip load failed', e); }

  // Compliance alerts
  try {
    const banner = document.getElementById('dashboard-compliance-banner');
    const consentCount = d.students_without_consent || 0;
    const deletionCount = d.pending_deletions || 0;
    if (consentCount === 0 && deletionCount === 0) {
      banner.innerHTML = '';
    } else {
      const items = [];
      if (consentCount > 0) items.push(`⚠️ ${consentCount} 名学生未获得家长数据授权`);
      if (deletionCount > 0) items.push(`🗑️ ${deletionCount} 条数据删除申请待处理`);
      banner.innerHTML = `
        <div style="background:var(--accent-light);color:var(--accent);padding:10px 12px;border-radius:6px;font-size:.9em;display:flex;justify-content:space-between;align-items:center;">
          <span>${items.join(' · ')}</span>
          <button class="btn btn-sm btn-outline" onclick="switchPage('compliance')" style="margin-left:12px;">去处理</button>
        </div>`;
    }
  } catch(e) { console.error('Compliance banner load failed', e); }

  // System status
  try {
    const sr = await fetch('/api/status');
    if (sr.ok) {
      const sd = await sr.json();
      const demoBadge = sd.demo_mode
        ? '<span style="background:var(--accent-light);color:var(--accent);padding:2px 8px;border-radius:4px;font-size:.8em;margin-left:8px;">Demo 模式</span>'
        : '';
      const backendColor = sd.backend === 'demo' ? 'var(--accent)' : 'var(--green)';
      document.getElementById('system-status-card').innerHTML = `
        <div style="display:flex;flex-wrap:wrap;gap:16px;font-size:.9em;">
          <div><span style="color:var(--sub);">LLM 后端：</span><strong style="color:${backendColor};">${sd.backend}</strong>${demoBadge}</div>
          <div><span style="color:var(--sub);">默认模型：</span><strong>${sd.model}</strong></div>
          <div><span style="color:var(--sub);">OCR 后端：</span><strong>${sd.ocr_backend}</strong></div>
          <div><span style="color:var(--sub);">Vision 模型：</span><strong>${sd.vision_model}</strong></div>
        </div>
      `;
    }
  } catch(e) { console.error('Status load failed', e); }
}

// ── Students ──
async function loadStudents() {
  const r = await fetch('/api/students'); const students = await r.json();
  const tbody = document.querySelector('#students-table tbody');

  // Filter controls
  const filterPlan = document.getElementById('filter-plan')?.value || '';
  const filterStatus = document.getElementById('filter-status')?.value || '';
  const sortBy = document.getElementById('sort-by')?.value || 'name';

  let filtered = students;
  if (filterPlan) filtered = filtered.filter(s => (s.plan || 'trial') === filterPlan);
  if (filterStatus === 'active') filtered = filtered.filter(s => s.sub_status === 'active');
  if (filterStatus === 'expired') filtered = filtered.filter(s => s.sub_status === 'expired');
  if (filterStatus === 'soon') filtered = filtered.filter(s => s.days_remaining !== null && s.days_remaining >= 0 && s.days_remaining <= 7);

  filtered.sort((a, b) => {
    if (sortBy === 'name') return a.name.localeCompare(b.name, 'zh');
    if (sortBy === 'plan') return (a.plan || 'trial').localeCompare(b.plan || 'trial');
    if (sortBy === 'days_remaining') {
      const da = a.days_remaining === null ? 99999 : a.days_remaining;
      const db = b.days_remaining === null ? 99999 : b.days_remaining;
      return da - db;
    }
    return 0;
  });

  tbody.innerHTML = '';
  if (filtered.length === 0) {
    tbody.innerHTML = '<tr><td colspan="11" style="text-align:center;color:var(--sub);padding:40px 0;">没有符合条件的学生</td></tr>';
    return;
  }

  filtered.forEach(s => {
    const viewUrl = s.access_code ? `/s/${s.access_code}` : '';
    const validText = s.sub_end_date ? s.sub_end_date.slice(0,10) : (s.sub_status==='expired' ? '已过期' : '未设置');
    const days = s.days_remaining;
    const daysText = days === null ? '-' : (days < 0 ? `已过期 ${-days} 天` : (days === 0 ? '今天到期' : `剩余 ${days} 天`));
    const daysClass = days === null ? '' : (days < 3 ? 'color:var(--red);font-weight:600;' : (days < 7 ? 'color:var(--accent);' : 'color:var(--green);'));
    const rowStyle = days !== null && days < 3 ? 'background:rgba(255,59,48,0.05);' : (days !== null && days < 7 ? 'background:rgba(232,129,59,0.04);' : '');
    const statusText = s.sub_status==='active' ? '有效' : (s.sub_status==='paused' ? '暂停' : '过期');
    let statusBadgeClass = s.sub_status || 'active';
    if (s.sub_status !== 'expired' && days !== null && days >= 0 && days <= 7) statusBadgeClass = 'expiring';
    const costText = s.month_cost ? `$${s.month_cost.toFixed(4)}` : '-';
    const consentBadge = s.has_consent
      ? '<span style="color:var(--green);font-size:.85em;">✅ 已授权</span>'
      : '<span style="color:var(--accent);font-size:.85em;">⚠️ 待授权</span>';
    const consentBtn = s.has_consent
      ? ''
      : `<button class="btn btn-sm btn-outline" onclick="recordConsentFromStudent(${s.id}, '${escapeHtml(s.name)}')" style="margin-top:4px;">补授权</button>`;
    tbody.innerHTML += `<tr style="${rowStyle}">
      <td><strong>${escapeHtml(s.name)}</strong>${viewUrl ? `<br><a href="${viewUrl}" target="_blank" style="font-size:.75em;color:var(--blue);">📎 学生页</a>` : ''}</td>
      <td>${s.grade}</td><td>${s.school_type}</td>
      <td>${s.english_score||'-'}</td><td>${s.target_score||'-'}</td>
      <td><span class="badge badge-${s.plan||'trial'}">${s.plan_label||'试用'}</span></td>
      <td style="font-size:.85em;">
        <div>${validText}</div>
        <div style="${daysClass}font-size:.78em;margin-top:2px;">${daysText}</div>
      </td>
      <td><span class="badge badge-${statusBadgeClass}">${statusText}</span></td>
      <td>${consentBadge}<br>${consentBtn}</td>
      <td style="font-size:.85em;color:var(--sub);">${costText}</td>
      <td>
        <button class="btn btn-sm btn-outline" onclick="editStudent(${s.id})">编辑</button>
        <button class="btn btn-sm btn-outline" data-name="${escapeHtml(s.name)}" onclick="manageSub(${s.id}, this.dataset.name)">订阅</button>
        <button class="btn btn-sm btn-outline" onclick="requestDeletion(${s.id}, '${escapeHtml(s.name)}')" style="color:var(--red);">删除申请</button>
      </td>
    </tr>`;
  });
}

async function recordConsentFromStudent(studentId, studentName) {
  const consentedBy = prompt(`补录 ${studentName} 的家长授权\n请输入家长姓名（必填）：`);
  if (!consentedBy || !consentedBy.trim()) return;
  const contact = prompt(`请输入家长联系方式（手机/微信，可选）：`) || '';
  const notes = prompt(`备注（可选）：`) || '';
  const r = await fetch('/api/compliance/consents', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({student_id: studentId, consented_by: consentedBy, contact, notes}),
  });
  if (r.ok) {
    toast('家长授权已记录');
    loadStudents();
    loadDashboard();
  } else {
    toast('授权记录失败', 'error');
  }
}

async function requestDeletion(studentId, studentName) {
  const reason = prompt(`申请删除 ${studentName} 的学习数据\n请输入删除原因（可选）：`) || '';
  if (!confirm('确定要提交数据删除申请吗？提交后需管理员审核执行。')) return;
  const r = await fetch('/api/compliance/deletion-requests', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({student_id: studentId, reason}),
  });
  if (r.ok) {
    toast('删除申请已提交');
    loadCompliance();
    loadDashboard();
  } else {
    toast('提交失败', 'error');
  }
}

// ── Time Map Editor ──
let timeMapSlots = [];

function renderTimeMapSlots() {
  const tbody = document.getElementById('time-map-slots');
  if (!tbody) return;
  const natureColors = { immovable: 'var(--red-light)', hobby: 'var(--green-light)', available: 'var(--accent-light)', fragment: 'var(--blue-light)' };
  const natureLabels = { immovable: '🔴 不可动', hobby: '🟢 爱好', available: '⭐ 可用', fragment: '🔵 碎片' };
  tbody.innerHTML = timeMapSlots.map((slot, idx) => `
    <tr data-idx="${idx}" style="border-bottom:1px solid var(--border);">
      <td style="padding:4px;">
        <select class="tm-day" style="width:72px;font-size:.85em;">
          ${['周一','周二','周三','周四','周五','周六','周日'].map(d => `<option value="${d}" ${slot.day===d?'selected':''}>${d}</option>`).join('')}
        </select>
      </td>
      <td style="padding:4px;"><input class="tm-start" type="time" value="${slot.start||''}" style="width:100px;font-size:.85em;"></td>
      <td style="padding:4px;"><input class="tm-end" type="time" value="${slot.end||''}" style="width:100px;font-size:.85em;"></td>
      <td style="padding:4px;"><input class="tm-content" value="${escapeHtml(slot.content||'')}" placeholder="如：晚自习" style="width:120px;font-size:.85em;"></td>
      <td style="padding:4px;">
        <select class="tm-nature" style="width:88px;font-size:.85em;background:${natureColors[slot.nature||'available']};">
          ${Object.entries(natureLabels).map(([k,l]) => `<option value="${k}" ${slot.nature===k?'selected':''}>${l}</option>`).join('')}
        </select>
      </td>
      <td style="padding:4px;">
        <select class="tm-energy" style="width:80px;font-size:.85em;">
          <option value="peak" ${slot.energy==='peak'?'selected':''}>高峰</option>
          <option value="okay" ${slot.energy==='okay'?'selected':''}>尚可</option>
          <option value="normal" ${slot.energy==='normal'?'selected':''}>一般</option>
        </select>
      </td>
      <td style="padding:4px;text-align:center;">
        <button class="btn btn-sm" onclick="removeTimeSlot(${idx})" style="color:var(--red);font-size:.8em;" title="删除">×</button>
      </td>
    </tr>
  `).join('');
  tbody.querySelectorAll('.tm-nature').forEach(sel => {
    sel.addEventListener('change', function() {
      const colors = { immovable: 'var(--red-light)', hobby: 'var(--green-light)', available: 'var(--accent-light)', fragment: 'var(--blue-light)' };
      this.style.background = colors[this.value] || '';
    });
  });
}

function addTimeSlot() {
  timeMapSlots.push({ day: '周一', start: '', end: '', content: '', nature: 'available', energy: 'normal' });
  renderTimeMapSlots();
}

function removeTimeSlot(idx) {
  timeMapSlots.splice(idx, 1);
  renderTimeMapSlots();
}

function collectTimeMap() {
  const rows = document.querySelectorAll('#time-map-slots tr');
  const slots = [];
  rows.forEach(row => {
    slots.push({
      day: row.querySelector('.tm-day').value,
      start: row.querySelector('.tm-start').value,
      end: row.querySelector('.tm-end').value,
      content: row.querySelector('.tm-content').value.trim(),
      nature: row.querySelector('.tm-nature').value,
      energy: row.querySelector('.tm-energy').value,
    });
  });
  return {
    description: document.getElementById('f-time-map-desc').value.trim(),
    slots: slots,
  };
}

// ── Onboarding Time Map ──
let onbTimeMapSlots = [];

function renderOnbTimeMapSlots() {
  const tbody = document.getElementById('onb-time-map-slots');
  if (!tbody) return;
  const natureColors = { immovable: 'var(--red-light)', hobby: 'var(--green-light)', available: 'var(--accent-light)', fragment: 'var(--blue-light)' };
  const natureLabels = { immovable: '🔴 不可动', hobby: '🟢 爱好', available: '⭐ 可用', fragment: '🔵 碎片' };
  tbody.innerHTML = onbTimeMapSlots.map((slot, idx) => `
    <tr data-idx="${idx}" style="border-bottom:1px solid var(--border);">
      <td style="padding:4px;">
        <select class="onb-tm-day" style="width:72px;font-size:.85em;">
          ${['周一','周二','周三','周四','周五','周六','周日'].map(d => `<option value="${d}" ${slot.day===d?'selected':''}>${d}</option>`).join('')}
        </select>
      </td>
      <td style="padding:4px;"><input class="onb-tm-start" type="time" value="${slot.start||''}" style="width:100px;font-size:.85em;"></td>
      <td style="padding:4px;"><input class="onb-tm-end" type="time" value="${slot.end||''}" style="width:100px;font-size:.85em;"></td>
      <td style="padding:4px;"><input class="onb-tm-content" value="${escapeHtml(slot.content||'')}" placeholder="如：晚自习" style="width:120px;font-size:.85em;"></td>
      <td style="padding:4px;">
        <select class="onb-tm-nature" style="width:88px;font-size:.85em;background:${natureColors[slot.nature||'available']};">
          ${Object.entries(natureLabels).map(([k,l]) => `<option value="${k}" ${slot.nature===k?'selected':''}>${l}</option>`).join('')}
        </select>
      </td>
      <td style="padding:4px;">
        <select class="onb-tm-energy" style="width:80px;font-size:.85em;">
          <option value="peak" ${slot.energy==='peak'?'selected':''}>高峰</option>
          <option value="okay" ${slot.energy==='okay'?'selected':''}>尚可</option>
          <option value="normal" ${slot.energy==='normal'?'selected':''}>一般</option>
        </select>
      </td>
      <td style="padding:4px;text-align:center;">
        <button class="btn btn-sm" onclick="removeOnbTimeSlot(${idx})" style="color:var(--red);font-size:.8em;" title="删除">×</button>
      </td>
    </tr>
  `).join('');
  tbody.querySelectorAll('.onb-tm-nature').forEach(sel => {
    sel.addEventListener('change', function() {
      const colors = { immovable: 'var(--red-light)', hobby: 'var(--green-light)', available: 'var(--accent-light)', fragment: 'var(--blue-light)' };
      this.style.background = colors[this.value] || '';
    });
  });
}

function addOnbTimeSlot() {
  onbTimeMapSlots.push({ day: '周一', start: '', end: '', content: '', nature: 'available', energy: 'normal' });
  renderOnbTimeMapSlots();
}

function removeOnbTimeSlot(idx) {
  onbTimeMapSlots.splice(idx, 1);
  renderOnbTimeMapSlots();
}

function collectOnbTimeMap() {
  const rows = document.querySelectorAll('#onb-time-map-slots tr');
  const slots = [];
  rows.forEach(row => {
    slots.push({
      day: row.querySelector('.onb-tm-day').value,
      start: row.querySelector('.onb-tm-start').value,
      end: row.querySelector('.onb-tm-end').value,
      content: row.querySelector('.onb-tm-content').value.trim(),
      nature: row.querySelector('.onb-tm-nature').value,
      energy: row.querySelector('.onb-tm-energy').value,
    });
  });
  return {
    description: document.getElementById('onb-time-map-desc').value.trim(),
    slots: slots,
  };
}

function renderTimeMapVisualization(slots, description) {
  const days = ['周一','周二','周三','周四','周五','周六','周日'];
  const natureStyles = {
    immovable: {bg:'var(--red-light)', border:'var(--red)', label:'不可动'},
    hobby: {bg:'var(--green-light)', border:'var(--green)', label:'爱好'},
    available: {bg:'var(--accent-light)', border:'var(--accent)', label:'可用'},
    fragment: {bg:'var(--blue-light)', border:'var(--blue)', label:'碎片'},
  };
  const energyLabels = {peak:'🔥高峰', okay:'✅尚可', normal:'➖一般'};
  const byDay = {};
  days.forEach(d => byDay[d] = []);
  slots.forEach(s => { if (byDay[s.day]) byDay[s.day].push(s); });
  return `
    <div style="margin-top:12px;background:var(--card);border:1px solid var(--border);border-radius:6px;padding:12px;">
      <div style="font-size:.85em;font-weight:600;margin-bottom:8px;">时间全景图</div>
      <div style="display:grid;grid-template-columns:repeat(7, 1fr);gap:6px;">
        ${days.map(d => `
          <div style="background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:6px;min-height:80px;">
            <div style="font-size:.75em;color:var(--sub);font-weight:600;margin-bottom:4px;text-align:center;">${d}</div>
            ${byDay[d].length === 0 ? '<div style="font-size:.7em;color:var(--sub);text-align:center;">—</div>' : byDay[d].map(s => {
              const st = natureStyles[s.nature] || natureStyles.available;
              return `<div style="background:${st.bg};border-left:3px solid ${st.border};border-radius:4px;padding:4px 6px;margin-bottom:4px;font-size:.72em;line-height:1.4;">
                <div style="font-weight:600;">${s.start||'?'} - ${s.end||'?'}</div>
                <div style="color:var(--sub);">${escapeHtml(s.content||'')}</div>
                <div style="display:flex;justify-content:space-between;margin-top:2px;">
                  <span>${st.label}</span>
                  <span>${energyLabels[s.energy]||''}</span>
                </div>
              </div>`;
            }).join('')}
          </div>
        `).join('')}
      </div>
      ${description ? `<p style="margin-top:8px;font-size:.8em;color:var(--sub);">备注：${escapeHtml(description)}</p>` : ''}
    </div>
  `;
}

function escapeHtml(text) {
  if (!text) return '';
  return text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function openStudentModal() {
  document.getElementById('student-modal').classList.add('show');
  document.getElementById('student-modal-title').textContent = '添加学生';
  ['name','english-score','target-score','parent-name','parent-wechat','parent-phone','notes','academic-goal','textbook-version','recent-scores','weak-areas','score-loss-reason','weak-question-types','confused-grammar','existing-resources','weekly-available-hours','committed-english-minutes','vocab-habit','attention-weakness','effective-methods','ineffective-methods','target-timeline','one-month-goal','parent-availability','study-environment','least-favorite-task','aspirational-use','plan-name','plan-code-name','time-map-desc'].forEach(f=>document.getElementById('f-'+f).value='');
  document.getElementById('f-grade').value = '高二';
  document.getElementById('f-school-type').value = '住校';
  document.getElementById('f-plan').value = 'trial';
  ['gender','semester','subject-choice','vocab-direction','learning-style','learning-medium','english-identity','vocab-level','scene-preference','supervision-needed','preferred-intensity','module-ratio','difficulty-start','daily-vocab'].forEach(f=>document.getElementById('f-'+f).value='');
  timeMapSlots = [];
  renderTimeMapSlots();
  document.getElementById('f-student-id').value='';
  document.getElementById('f-parent-consent').checked = false;
  switchProfileTab('basic');
}
function closeStudentModal() { document.getElementById('student-modal').classList.remove('show'); }

// ── Profile Tab Navigation ──
function switchProfileTab(tabName) {
  document.querySelectorAll('.profile-tab').forEach(t => {
    t.classList.remove('active');
    t.style.borderBottom = 'none';
    t.style.color = 'var(--sub)';
    t.style.fontWeight = '400';
  });
  document.querySelectorAll('.profile-tab-content').forEach(c => c.style.display = 'none');

  const activeTab = document.querySelector(`.profile-tab[data-tab="${tabName}"]`);
  if (activeTab) {
    activeTab.classList.add('active');
    activeTab.style.borderBottom = '2px solid var(--accent)';
    activeTab.style.color = 'var(--text)';
    activeTab.style.fontWeight = '600';
  }
  const activeContent = document.getElementById('tab-' + tabName);
  if (activeContent) activeContent.style.display = 'block';
}

function switchOnbProfileTab(tabName) {
  document.querySelectorAll('.onb-profile-tab').forEach(t => {
    t.classList.remove('active');
    t.style.borderBottom = 'none';
    t.style.color = 'var(--sub)';
    t.style.fontWeight = '400';
  });
  document.querySelectorAll('.onb-profile-tab-content').forEach(c => c.style.display = 'none');

  const activeTab = document.querySelector(`.onb-profile-tab[data-tab="${tabName}"]`);
  if (activeTab) {
    activeTab.classList.add('active');
    activeTab.style.borderBottom = '2px solid var(--accent)';
    activeTab.style.color = 'var(--text)';
    activeTab.style.fontWeight = '600';
  }
  const activeContent = document.getElementById('onb-tab-' + tabName);
  if (activeContent) activeContent.style.display = 'block';
}

async function editStudent(id) {
  const [r, pr] = await Promise.all([
    fetch('/api/students/' + id),
    fetch('/api/students/' + id + '/profile')
  ]);
  const s = await r.json();
  const profile = pr.ok ? await pr.json() : {};

  document.getElementById('f-student-id').value = s.id;
  document.getElementById('f-name').value = s.name||'';
  document.getElementById('f-grade').value = s.grade||'高二';
  document.getElementById('f-gender').value = s.gender||profile.gender||'';
  document.getElementById('f-semester').value = s.semester||profile.semester||'';
  document.getElementById('f-school-type').value = s.school_type||'住校';
  document.getElementById('f-plan').value = s.plan||'trial';
  document.getElementById('f-english-score').value = s.english_score||'';
  document.getElementById('f-target-score').value = s.target_score||'';
  document.getElementById('f-academic-goal').value = profile.academic_goal||'';
  document.getElementById('f-subject-choice').value = profile.subject_choice||'';
  document.getElementById('f-textbook-version').value = s.textbook_version||profile.textbook_version||'';
  document.getElementById('f-parent-name').value = s.parent_name||'';
  document.getElementById('f-parent-wechat').value = s.parent_wechat||'';
  document.getElementById('f-parent-phone').value = s.parent_phone||'';
  document.getElementById('f-notes').value = s.notes||'';
  document.getElementById('f-parent-consent').checked = !!s.has_consent;

  // English situation
  document.getElementById('f-recent-scores').value = Array.isArray(profile.recent_scores) ? profile.recent_scores.join(',') : (profile.recent_scores||'');
  document.getElementById('f-weak-areas').value = profile.weak_areas||'';
  document.getElementById('f-score-loss-reason').value = profile.score_loss_reason||'';
  document.getElementById('f-weak-question-types').value = Array.isArray(profile.weak_question_types) ? profile.weak_question_types.join(',') : (profile.weak_question_types||'');
  document.getElementById('f-confused-grammar').value = profile.confused_grammar||'';
  document.getElementById('f-existing-resources').value = profile.existing_resources||'';
  document.getElementById('f-vocab-direction').value = profile.vocab_direction||'';
  const tm = (profile.time_map && typeof profile.time_map === 'object') ? profile.time_map : {};
  timeMapSlots = Array.isArray(tm.slots) ? tm.slots : [];
  document.getElementById('f-time-map-desc').value = tm.description || '';
  renderTimeMapSlots();
  document.getElementById('f-weekly-available-hours').value = profile.weekly_available_hours||'';
  document.getElementById('f-committed-english-minutes').value = profile.committed_english_minutes||'';

  // Traits
  document.getElementById('f-learning-style').value = profile.learning_style||'';
  const lsDetail = profile.learning_style_detail || {};
  const hasLsDetail = ['visual','auditory','kinesthetic','read_write'].some(k => Number(lsDetail[k]) > 0);
  document.getElementById('learning-style-radar').innerHTML = hasLsDetail
    ? renderRadarChart(lsDetail, {size: 220})
    : `<p style="color:var(--sub);text-align:center;margin:20px 0;">完成首次 AI 诊断后将展示 4 维学习风格雷达图</p>`;
  document.getElementById('f-learning-medium').value = profile.learning_medium||'';
  document.getElementById('f-vocab-habit').value = profile.vocab_habit||'';
  document.getElementById('f-attention-weakness').value = profile.attention_weakness||'';
  document.getElementById('f-effective-methods').value = profile.effective_methods||'';
  document.getElementById('f-ineffective-methods').value = profile.ineffective_methods||'';
  document.getElementById('f-english-identity').value = profile.english_identity||'';

  const assessments = profile.assessments||{};
  document.getElementById('f-attention-minutes').value = assessments.attention_minutes||'';
  document.getElementById('f-vocab-level').value = assessments.vocab_level||'';
  document.getElementById('f-scene-preference').value = assessments.scene_preference||'';

  // Goals
  document.getElementById('f-target-timeline').value = profile.target_timeline||'';
  document.getElementById('f-one-month-goal').value = profile.one_month_goal||'';
  document.getElementById('f-parent-availability').value = profile.parent_availability||'';
  document.getElementById('f-supervision-needed').value = profile.supervision_needed ? '1' : '0';
  document.getElementById('f-study-environment').value = profile.study_environment||'';
  document.getElementById('f-least-favorite-task').value = profile.least_favorite_task||'';
  document.getElementById('f-preferred-intensity').value = profile.preferred_intensity||'';
  document.getElementById('f-aspirational-use').value = profile.aspirational_use||'';

  const choices = profile.plan_choices||{};
  document.getElementById('f-module-ratio').value = choices.module_ratio||'';
  document.getElementById('f-difficulty-start').value = choices.difficulty_start||'';
  document.getElementById('f-daily-vocab').value = choices.daily_vocab||'';
  document.getElementById('f-plan-name').value = profile.plan_name||'';
  document.getElementById('f-plan-code-name').value = profile.plan_code_name||'';

  switchProfileTab('basic');
  document.getElementById('student-modal-title').textContent = '编辑学生';
  document.getElementById('student-modal').classList.add('show');
}

async function saveStudent() {
  const id = document.getElementById('f-student-id').value;
  const basicData = {
    name: document.getElementById('f-name').value,
    grade: document.getElementById('f-grade').value,
    school_type: document.getElementById('f-school-type').value,
    gender: document.getElementById('f-gender').value,
    semester: document.getElementById('f-semester').value,
    english_score: document.getElementById('f-english-score').value||null,
    target_score: document.getElementById('f-target-score').value||null,
    academic_goal: document.getElementById('f-academic-goal').value,
    subject_choice: document.getElementById('f-subject-choice').value,
    textbook_version: document.getElementById('f-textbook-version').value,
    parent_name: document.getElementById('f-parent-name').value,
    parent_wechat: document.getElementById('f-parent-wechat').value,
    parent_phone: document.getElementById('f-parent-phone').value,
    notes: document.getElementById('f-notes').value,
    plan: document.getElementById('f-plan').value,
    parent_consent: document.getElementById('f-parent-consent').checked,
  };

  const profileData = {
    gender: basicData.gender,
    semester: basicData.semester,
    academic_goal: basicData.academic_goal,
    subject_choice: basicData.subject_choice,
    textbook_version: basicData.textbook_version,
    time_map: collectTimeMap(),
    weekly_available_hours: parseFloat(document.getElementById('f-weekly-available-hours').value)||null,
    committed_english_minutes: parseInt(document.getElementById('f-committed-english-minutes').value)||null,
    recent_scores: document.getElementById('f-recent-scores').value.split(',').map(s=>s.trim()).filter(Boolean),
    weak_areas: document.getElementById('f-weak-areas').value,
    weak_question_types: document.getElementById('f-weak-question-types').value.split(',').map(s=>s.trim()).filter(Boolean),
    score_loss_reason: document.getElementById('f-score-loss-reason').value,
    confused_grammar: document.getElementById('f-confused-grammar').value,
    existing_resources: document.getElementById('f-existing-resources').value,
    vocab_direction: document.getElementById('f-vocab-direction').value,
    learning_style: document.getElementById('f-learning-style').value,
    learning_medium: document.getElementById('f-learning-medium').value,
    vocab_habit: document.getElementById('f-vocab-habit').value,
    attention_weakness: document.getElementById('f-attention-weakness').value,
    effective_methods: document.getElementById('f-effective-methods').value,
    ineffective_methods: document.getElementById('f-ineffective-methods').value,
    english_identity: document.getElementById('f-english-identity').value,
    assessments: {
      attention_minutes: parseInt(document.getElementById('f-attention-minutes').value)||null,
      vocab_level: document.getElementById('f-vocab-level').value,
      scene_preference: document.getElementById('f-scene-preference').value,
    },
    target_timeline: document.getElementById('f-target-timeline').value,
    one_month_goal: document.getElementById('f-one-month-goal').value,
    parent_availability: document.getElementById('f-parent-availability').value,
    supervision_needed: parseInt(document.getElementById('f-supervision-needed').value)||0,
    study_environment: document.getElementById('f-study-environment').value,
    least_favorite_task: document.getElementById('f-least-favorite-task').value,
    preferred_intensity: document.getElementById('f-preferred-intensity').value,
    aspirational_use: document.getElementById('f-aspirational-use').value,
    plan_choices: {
      module_ratio: document.getElementById('f-module-ratio').value,
      difficulty_start: document.getElementById('f-difficulty-start').value,
      daily_vocab: document.getElementById('f-daily-vocab').value,
    },
    plan_name: document.getElementById('f-plan-name').value,
    plan_code_name: document.getElementById('f-plan-code-name').value,
  };

  if (!basicData.name) return toast('姓名必填','error');

  const url = id ? '/api/students/'+id : '/api/students';
  const method = id ? 'PUT' : 'POST';
  const r = await fetch(url, {method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(basicData)});
  if (!r.ok) { toast('保存基本信息失败','error'); return; }
  const student = await r.json();
  const studentId = id || student.id;

  const pr = await fetch('/api/students/' + studentId + '/profile', {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(profileData)
  });
  if (!pr.ok) { toast('保存画像失败','error'); return; }

  toast(id?'已更新':'已添加');
  closeStudentModal();
  loadStudents();
}
async function manageSub(studentId, name) {
  document.getElementById('sub-student-id').value = studentId;
  document.getElementById('sub-modal-title').textContent = name + ' 的订阅管理';
  const r = await fetch('/api/subscriptions/' + studentId);
  let data = {student_id: studentId, plan: 'trial', status_label: '有效', end_date: '', total_paid: 0, payments: []};
  if (r.ok) { data = await r.json(); }

  document.getElementById('sub-plan').value = data.plan || 'trial';
  document.getElementById('sub-status').value = data.status_label || '有效';
  document.getElementById('sub-end-date').value = data.end_date || '';
  document.getElementById('sub-total-paid').value = '¥' + (data.total_paid || 0).toFixed(2);
  const isUnlimited = data.plan === 'unlimited';
  document.getElementById('sub-quota').value = isUnlimited ? '不限次数' : (data.monthly_quota || 0) + ' 次';
  document.getElementById('sub-used').value = isUnlimited ? '超级账号'
    : (data.used_count || 0) + ' 次（剩余 ' + (data.remaining_quota || 0) + ' 次）';
  document.getElementById('pay-plan').value = 'monthly';
  document.getElementById('pay-amount').value = '';
  document.getElementById('pay-note').value = '';

  // Render payments
  const ptbody = document.querySelector('#payments-table tbody');
  ptbody.innerHTML = '';
  if (data.payments && data.payments.length > 0) {
    data.payments.forEach(p => {
      const planLabel = (p.weeks || 1) >= 12 ? '包年' : '包月';
      ptbody.innerHTML += `<tr>
        <td>${fmtDate(p.paid_at)}</td>
        <td>¥${(p.amount||0).toFixed(2)}</td>
        <td>${planLabel}</td>
        <td>${p.note||'-'}</td>
      </tr>`;
    });
  } else {
    ptbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--sub);">暂无收款记录</td></tr>';
  }

  document.getElementById('sub-modal').classList.add('show');
}
function closeSubModal() { document.getElementById('sub-modal').classList.remove('show'); }
function updateSubPrice() {
  // Reserved for future auto-fill
}
function updatePayAmount() {
  const prices = {monthly: 39, yearly: 399};
  const plan = document.getElementById('pay-plan').value;
  document.getElementById('pay-amount').value = prices[plan] || '';
}
async function saveSubPlan() {
  const studentId = document.getElementById('sub-student-id').value;
  const plan = document.getElementById('sub-plan').value;
  const endDate = document.getElementById('sub-end-date').value || null;
  const r = await fetch('/api/subscriptions', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({student_id: parseInt(studentId), plan, end_date: endDate})
  });
  if (r.ok) { toast('套餐已更新'); loadStudents(); }
  else { const d = await r.json(); toast(d.error || '保存失败', 'error'); }
}
async function recordPayment() {
  const studentId = document.getElementById('sub-student-id').value;
  const plan = document.getElementById('pay-plan').value;
  const amount = parseFloat(document.getElementById('pay-amount').value);
  const note = document.getElementById('pay-note').value;
  if (!amount || amount <= 0) return toast('请输入收款金额', 'error');

  const r = await fetch('/api/payments', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({student_id: parseInt(studentId), plan, amount, note})
  });
  if (r.ok) {
    toast(plan === 'yearly' ? '收款已记录，包年套餐已生效（600 次额度）' : '收款已记录，包月套餐已生效');
    manageSub(studentId, document.getElementById('sub-modal-title').textContent.replace(' 的订阅管理',''));
    loadStudents();
  } else {
    const d = await r.json(); toast(d.error || '记录失败', 'error');
  }
}

// ── Onboarding Pipeline ──
async function startOnboarding() {
  const name = document.getElementById('onb-name').value.trim();
  if (!name) return toast('请填写学生姓名', 'error');
  const fileInput = document.getElementById('onb-file');
  if (!fileInput.files.length) return toast('请上传试卷照片', 'error');
  if (fileInput.files.length > 6) return toast('一次最多上传 6 张图片', 'error');

  // Create student first
  const studentData = {
    name, grade: document.getElementById('onb-grade').value,
    school_type: document.getElementById('onb-school-type').value,
    gender: document.getElementById('onb-gender').value,
    english_score: document.getElementById('onb-score').value||null,
    target_score: document.getElementById('onb-target').value||null,
    plan: document.getElementById('onb-plan').value,
    parent_phone: document.getElementById('onb-parent-phone').value,
    parent_consent: document.getElementById('onb-parent-consent').checked,
  };
  const sr = await fetch('/api/students', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(studentData)});
  if (!sr.ok) { toast('创建学生失败', 'error'); return; }
  const student = await sr.json();

  // Save personalized profile
  const profileData = {
    gender: studentData.gender,
    semester: document.getElementById('onb-semester').value,
    academic_goal: document.getElementById('onb-academic-goal').value,
    subject_choice: document.getElementById('onb-subject-choice').value,
    textbook_version: document.getElementById('onb-textbook-version').value,
    time_map: collectOnbTimeMap(),
    weekly_available_hours: parseFloat(document.getElementById('onb-weekly-available-hours').value)||null,
    committed_english_minutes: parseInt(document.getElementById('onb-committed-english-minutes').value)||null,
    recent_scores: document.getElementById('onb-recent-scores').value.split(',').map(s=>s.trim()).filter(Boolean),
    weak_areas: document.getElementById('onb-weak-areas').value,
    weak_question_types: document.getElementById('onb-weak-question-types').value.split(',').map(s=>s.trim()).filter(Boolean),
    score_loss_reason: document.getElementById('onb-score-loss-reason').value,
    confused_grammar: document.getElementById('onb-confused-grammar').value,
    existing_resources: document.getElementById('onb-existing-resources').value,
    vocab_direction: document.getElementById('onb-vocab-direction').value,
    learning_style: document.getElementById('onb-learning-style').value,
    learning_medium: document.getElementById('onb-learning-medium').value,
    vocab_habit: document.getElementById('onb-vocab-habit').value,
    attention_weakness: document.getElementById('onb-attention-weakness').value,
    effective_methods: document.getElementById('onb-effective-methods').value,
    ineffective_methods: document.getElementById('onb-ineffective-methods').value,
    english_identity: document.getElementById('onb-english-identity').value,
    assessments: {
      attention_minutes: parseInt(document.getElementById('onb-attention-minutes').value)||null,
      vocab_level: document.getElementById('onb-vocab-level').value,
      scene_preference: document.getElementById('onb-scene-preference').value,
    },
    target_timeline: document.getElementById('onb-target-timeline').value,
    one_month_goal: document.getElementById('onb-one-month-goal').value,
    parent_availability: document.getElementById('onb-parent-availability').value,
    supervision_needed: parseInt(document.getElementById('onb-supervision-needed').value)||0,
    study_environment: document.getElementById('onb-study-environment').value,
    least_favorite_task: document.getElementById('onb-least-favorite-task').value,
    preferred_intensity: document.getElementById('onb-preferred-intensity').value,
    aspirational_use: document.getElementById('onb-aspirational-use').value,
    plan_choices: {
      module_ratio: document.getElementById('onb-module-ratio').value,
      difficulty_start: document.getElementById('onb-difficulty-start').value,
      daily_vocab: document.getElementById('onb-daily-vocab').value,
    },
    plan_name: document.getElementById('onb-plan-name').value,
    plan_code_name: document.getElementById('onb-plan-code-name').value,
  };
  try {
    await fetch('/api/students/' + student.id + '/profile', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(profileData)
    });
  } catch(e) { console.error('Failed to save onboarding profile', e); }

  // Upload files with progress
  let upload;
  try {
    upload = await uploadFilesWithProgress(fileInput, student.id, 'test_paper', 'parent');
  } catch(e) {
    toast('上传没成功，再试一次吧', 'error');
    return;
  }

  // Trigger pipeline
  const pr = await fetch('/api/pipeline/run', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({student_id: student.id, task_type: 'onboarding', file_ids: upload.file_ids})
  });
  if (!pr.ok) { toast('启动失败', 'error'); return; }
  const task = await pr.json();

  // Show progress + reset personalized form
  onbTimeMapSlots = [];
  renderOnbTimeMapSlots();
  document.getElementById('onb-progress').style.display = 'block';
  pollTask(task.task_id, 'onb');
}

// ── Weekly Pipeline ──
async function loadWeeklyPage() {
  const students = await (await fetch('/api/students')).json();
  const opts = students.map(s => `<option value="${s.id}">${escapeHtml(s.name)} (${escapeHtml(s.grade)})</option>`).join('');
  document.getElementById('wk-student').innerHTML = opts;
  // Load history
  const tr = await fetch('/api/tasks');
  const tasks = await tr.json();
  const tbody = document.querySelector('#tasks-table tbody');
  tbody.innerHTML = '';
  tasks.filter(t=>t.task_type==='weekly').slice(0,20).forEach(t => {
    let out = {};
    try { out = JSON.parse(t.output_data || '{}'); } catch(e) {}
    const stage = out.stage || '';
    // 兼容历史任务：早期 grading_done 任务输出无 correct_count（那时是批改试卷产出错题）
    const info = stage==='exercises_ready' ? `${out.questions_count||'?'}题` :
                 stage==='grading_done' ? (out.total_count != null
                   ? `正确${out.correct_count}/${out.total_count}`
                   : `${out.mistakes_count||0}道错题`) : '';
    // P3-13：审核入口移除后，逐条纠错 + 报告下载迁移到这里
    const rid = out.report_file_id || out.exercise_file_id || '';
    const corrBtn = (t.status==='done' && (out.mistakes_count>0 || out.report_file_id))
      ? `<button class="btn btn-sm btn-outline" onclick="openCorrectionPanel(${t.id})" title="逐条纠错">📝 纠错</button> ` : '';
    const reportBtn = rid
      ? `<a href="/api/files/${rid}/download" target="_blank" class="btn btn-sm btn-outline" style="text-decoration:none;" title="查看AI生成的报告">📄 报告</a>` : '';
    tbody.innerHTML += `<tr>
      <td>${t.student_name||'?'}</td>
      <td>${stage==='exercises_ready'?'生成练习题':stage==='grading_done'?'批改完成':t.status}</td>
      <td><span class="badge badge-${t.status}">${t.status}</span></td>
      <td>${info}</td>
      <td>${fmtDate(t.created_at)}</td>
      <td style="white-space:nowrap;">${corrBtn}${reportBtn}</td>
    </tr>`;
  });
}
async function runWeeklyForStudent(sid) {
  switchPage('weekly');
  document.getElementById('wk-student').value = sid;
}
// Auto-upload when files are selected (stores file_ids for later use)
let pendingFileIds = [];
async function onFileSelected() {
  const fileInput = document.getElementById('wk-file');
  const sid = document.getElementById('wk-student').value;
  if (!sid) { toast('请先选择学生', 'error'); fileInput.value = ''; return; }
  if (!fileInput.files.length) return;
  if (fileInput.files.length > 15) { toast('一次最多上传 15 张图片', 'error'); fileInput.value = ''; return; }

  // Show file names immediately
  const fileNames = Array.from(fileInput.files).map(f => f.name);
  showFileList(fileNames, fileInput.files.length);

  try {
    const upload = await uploadFilesWithProgress(fileInput, sid, 'test_paper', 'parent');
    pendingFileIds = upload.file_ids;
    showFileList(fileNames, fileInput.files.length, true);
  } catch(e) {
    showFileList(fileNames, fileInput.files.length, false);
  }
}

function showFileList(fileNames, total, success) {
  let el = document.getElementById('wk-file-list');
  if (!el) {
    el = document.createElement('div');
    el.id = 'wk-file-list';
    el.style.cssText = 'margin-top:10px;font-size:0.85rem;color:#6b6b6b;';
    document.getElementById('wk-file').parentElement.appendChild(el);
  }
  if (success === undefined) {
    el.innerHTML = `<div>📎 待上传：${fileNames.join('、')}</div>`;
  } else if (success) {
    el.innerHTML = `<div style="color:#0f7b4e;">✅ 已成功上传 ${total} 个文件</div><div style="margin-top:4px;">${fileNames.map(n => '· ' + n).join('<br>')}</div>`;
  } else {
    el.innerHTML = `<div style="color:#d93a46;">❌ 上传失败，请重试</div>`;
  }
}

async function startWeekly(stage) {
  const sid = document.getElementById('wk-student').value;
  if (!sid) return toast('请选择学生', 'error');

  // analysis_only / report_only: no file upload needed
  if (stage === 'analysis_only' || stage === 'report_only') {
    const inputData = {student_id: parseInt(sid), task_type: 'weekly', stage: stage};
    const pr = await fetch('/api/pipeline/run', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(inputData)
    });
    if (!pr.ok) { toast('启动失败', 'error'); return; }
    const task = await pr.json();
    document.getElementById('wk-progress').style.display = 'block';
    pollTask(task.task_id, 'wk');
    return;
  }

  // Use pendingFileIds from auto-upload, or upload now if needed
  let fileIds = pendingFileIds;
  if (!fileIds || !fileIds.length) {
    const fileInput = document.getElementById('wk-file');
    if (!fileInput.files.length) return toast('请先上传照片', 'error');
    if (fileInput.files.length > 15) return toast('一次最多上传 15 张图片', 'error');
    try {
      const upload = await uploadFilesWithProgress(fileInput, sid, 'test_paper', 'parent');
      fileIds = upload.file_ids;
    } catch(e) {
      toast('上传没成功，再试一次吧', 'error');
      return;
    }
  }
  pendingFileIds = []; // clear after use

  const inputData = {student_id: parseInt(sid), task_type: 'weekly', file_ids: fileIds, stage: stage};

  const pr = await fetch('/api/pipeline/run', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(inputData)
  });
  if (!pr.ok) { toast('启动失败', 'error'); return; }
  const task = await pr.json();
  document.getElementById('wk-progress').style.display = 'block';
  pollTask(task.task_id, 'wk');
}

// ─ Task Polling ──
const STEPS_MAP = {
  onboarding: ['初始化', 'OCR识别试卷', '分析错题', '生成薄弱点矩阵', '生成学习方案', '生成诊断报告'],
  weekly: ['初始化', 'OCR识别试卷', '分析错题', '生成薄弱点矩阵', '生成学习方案', '生成分析报告', '生成练习题', '等待学生答案', '批改练习', '生成周报', '更新学习方案'],
  grade_only: ['初始化', 'OCR识别试卷', '分析错题', '保存错题', '完成'],
  analysis_only: ['初始化', '加载学情数据', '生成薄弱点矩阵', '生成学习方案', '生成分析报告', '完成'],
  report_only: ['初始化', '加载学情数据', '生成周报', '完成'],
};

function pollTask(taskId, prefix) {
  const bar = document.getElementById(prefix+'-bar');
  const steps = document.getElementById(prefix+'-steps');
  const result = document.getElementById(prefix+'-result');
  // 步骤列表按任务自身类型解析（原实现用 DOM 前缀 'onb'/'wk' 查表，
  // 与 STEPS_MAP 键 'onboarding'/'weekly' 永不匹配 → 列表从未渲染）
  let stepNames = [];

  const timer = setInterval(async () => {
    try {
      const r = await fetch('/api/tasks/'+taskId);
      const t = await r.json();

      if (!stepNames.length) stepNames = STEPS_MAP[t.task_type] || [];
      const pct = t.progress || 0;
      bar.style.width = pct+'%';

      // 优先用后端 current_step 真实步骤名定位（API 已返回，此前被忽略）
      const curIdx = t.current_step
        ? stepNames.findIndex(n => n === t.current_step
            || n.includes(t.current_step) || t.current_step.includes(n))
        : -1;
      const stepPct = stepNames.length ? Math.round(100 / stepNames.length) : 100;
      steps.innerHTML = stepNames.map((name, i) => {
        let cls = 'pending';
        if (curIdx >= 0) {
          if (i < curIdx) cls = 'done';
          else if (i === curIdx) cls = 'current';
          else if (pct >= (i+1)*stepPct) cls = 'done';
        } else {
          if (pct >= (i+1)*stepPct) cls = 'done';
          else if (pct >= i*stepPct) cls = 'current';
        }
        return `<div class="step-item ${cls}">
          ${cls==='current'?'<span class="spinner"></span>':(cls==='done'?'✅':'○')}
          ${name}
        </div>`;
      }).join('') + (t.current_step && t.status === 'processing'
        ? `<div style="font-size:.75rem;color:var(--sub);margin-top:6px;">当前：${t.current_step}</div>` : '');

      if (t.status === 'done') {
        clearInterval(timer);
        bar.style.width = '100%';
        const od = t.output_data || {};
        const rid = od.report_file_id;
        const mc = od.mistakes_count;
        const sid = od.student_id;
        result.innerHTML = '<span style="color:var(--accent);">✅ 处理完成</span>';
        if (mc) result.innerHTML += `<br>📝 AI 发现 <strong>${mc}</strong> 道错题` + (sid ? ` <a href="javascript:void(0)" onclick="viewStudentMistakes(${sid})" style="color:var(--accent);font-size:.85em;">→ 查看错题详情</a>` : '');
        if (rid) {
          result.innerHTML += `<br>📄 <a href="/api/files/${rid}/download" target="_blank" class="btn btn-sm btn-green" style="margin-top:8px;text-decoration:none;">📥 下载分析报告</a>`;
          result.innerHTML += `<br><span style="color:var(--sub);font-size:.8em;">报告已生成，点击上方按钮在新窗口查看</span>`;
          // Auto-open report in new tab
          window.open('/api/files/' + rid + '/download', '_blank');
        } else if (!rid && od.stage === 'grading_done') {
          result.innerHTML += `<br><span style="color:var(--sub);font-size:.85em;">💡 请点击「📋 矩阵分析」生成分析报告，或点击「📊 生成周报」出周报</span>`;
        } else {
          result.innerHTML += `<br><span style="color:var(--sub);font-size:.85em;">💡 可在「周度服务 → 历史任务」中查看报告或逐条纠错</span>`;
        }
        loadDashboard();
      } else if (t.status === 'failed') {
        clearInterval(timer);
        result.innerHTML = `<span style="color:var(--red);">❌ 处理失败: ${t.error_message||'出了点小问题'}</span>`;
        if (t.error_message && t.error_message.includes('OCR')) {
          result.innerHTML += '<br><span style="color:var(--sub);">💡 可能是图片质量问题，请确认照片清晰无反光，重新上传试试</span>';
        }
      }
    } catch(e) { clearInterval(timer); }
  }, 2000);
}

// ── P3-13：审核（approve/reject/batch）JS 已删除，质量由抽检+纠错回路承担 ──

// ── Classes ──
let _currentClassId = null;
async function loadClassesPage() {
  const r = await fetch('/api/my-classes');
  if (!r.ok) { toast('加载班级失败', 'error'); return; }
  const classes = await r.json();
  const el = document.getElementById('classes-list');
  document.getElementById('class-detail').style.display = 'none';
  el.style.display = 'block';
  if (!classes.length) {
    el.innerHTML = '<div class="card" style="text-align:center;color:var(--mute);padding:40px;">暂无班级。{% if user_role == "admin" %}请点击右上角「创建班级」。{% else %}请联系管理员分配班级。{% endif %}</div>';
    return;
  }
  el.innerHTML = classes.map(c => `
    <div class="card" style="cursor:pointer;transition:all .15s;" onmouseover="this.style.transform='translateY(-1px)';this.style.boxShadow='var(--shadow-lg)'" onmouseout="this.style.transform='';this.style.boxShadow='var(--shadow)'" onclick="openClassDetail(${c.id})">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <div>
          <strong style="font-size:.95em;">${c.name}</strong>
          <span style="font-size:.75em;color:var(--sub);margin-left:8px;">${c.school_name||''}</span>
          ${c.grade?'<span class="badge badge-blue" style="margin-left:8px;">'+c.grade+'</span>':''}
        </div>
        <div style="text-align:right;">
          <div style="font-size:.75em;color:var(--sub);">班级码</div>
          <div style="font-size:1.1em;font-weight:700;color:var(--accent);letter-spacing:2px;">${c.class_code||'-'}</div>
        </div>
      </div>
    </div>
  `).join('');
}

async function openClassDetail(classId) {
  _currentClassId = classId;
  document.getElementById('classes-list').style.display = 'none';
  document.getElementById('class-detail').style.display = 'block';
  const [statsR, studentsR] = await Promise.all([
    fetch('/api/class/'+classId+'/stats'),
    fetch('/api/class/'+classId+'/students'),
  ]);
  const stats = await statsR.json();
  const students = await studentsR.json();
  document.getElementById('class-stats-cards').innerHTML = `
    <div class="card" style="text-align:center;"><div style="font-size:1.5em;font-weight:700;color:var(--text);">${stats.student_count}</div><div style="font-size:.75em;color:var(--sub);">班级人数</div></div>
    <div class="card" style="text-align:center;"><div style="font-size:1.5em;font-weight:700;color:var(--green);">${stats.active_this_week}</div><div style="font-size:.75em;color:var(--sub);">本周活跃</div></div>
    <div class="card" style="text-align:center;"><div style="font-size:1.5em;font-weight:700;color:var(--accent);">${stats.avg_mastery_rate}%</div><div style="font-size:.75em;color:var(--sub);">平均掌握率</div></div>
    <div class="card" style="text-align:center;"><div style="font-size:1.5em;font-weight:700;color:var(--blue);">${stats.total_mistakes}</div><div style="font-size:.75em;color:var(--sub);">累计错题</div></div>
  `;
  const wp = stats.weak_points_top5 || [];
  document.getElementById('class-weak-points').innerHTML = wp.length
    ? wp.map((w,i) => `<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border);">
        <span style="font-size:.75em;color:var(--mute);width:20px;">${i+1}.</span>
        <span style="flex:1;font-size:.85em;">${w.knowledge_point}</span>
        <span style="font-size:.8em;color:var(--red);font-weight:600;">错误率 ${Math.round(w.error_rate*100)}%</span>
      </div>`).join('')
    : '<div style="color:var(--mute);font-size:.85em;padding:12px 0;">暂无数据</div>';
  const tbody = document.querySelector('#class-students-table tbody');
  tbody.innerHTML = students.map(s => `<tr>
    <td><strong>${escapeHtml(s.name)}</strong></td>
    <td>${s.grade||'-'}</td>
    <td>${s.phone||'-'}</td>
    <td><button class="btn btn-sm btn-outline" onclick="switchPage('students')">查看学情</button></td>
  </tr>`).join('') || '<tr><td colspan="4" style="text-align:center;color:var(--mute);">暂无学生</td></tr>';
}

function backToClasses() {
  document.getElementById('class-detail').style.display = 'none';
  document.getElementById('classes-list').style.display = 'block';
}

{% if user_role == 'admin' %}
function openSchoolModal() {
  const name = prompt('请输入学校名称：');
  if (!name || !name.trim()) return;
  const aliases = prompt('别名/简称（多个用逗号分隔，可留空）：') || '';
  fetch('/api/schools', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name: name.trim(), aliases: aliases.split(/[,，]/).map(s=>s.trim()).filter(Boolean)})
  }).then(r => { if(r.ok){toast('学校已添加');loadClassesPage();} else r.json().then(d=>toast(d.error||'添加失败','error')); });
}
{% endif %}

function openClassModal() {
  // First check if teacher has a school
  fetch('/api/teacher/my-school').then(r=>r.json()).then(mySchool=>{
    if(mySchool.id){
      // Teacher has a school — create class directly
      const className = prompt('班级名称（如"高二3班"）：\n\n所属学校：' + mySchool.name);
      if(!className||!className.trim()) return;
      const grade = prompt('年级（如"高二"，可留空）：') || '';
      fetch('/api/teacher/create-class', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({school_id: mySchool.id, name: className.trim(), grade: grade.trim()||null})
      }).then(r=>{if(r.ok){toast('班级已创建');loadClassesPage();}else r.json().then(d=>toast(d.error||'创建失败','error'));});
    } else {
      // No school assigned — let teacher pick one
      fetch('/api/schools').then(r=>r.json()).then(schools=>{
        if(!schools.length){toast('请管理员先添加学校','error');return;}
        const schoolName = prompt('选择学校（输入学校名称）：\n\n可选：' + schools.map(s=>s.name).join('、'));
        if(!schoolName) return;
        const school = schools.find(s=>s.name.includes(schoolName.trim()));
        if(!school){toast('未找到该学校，请重新输入','error');return;}
        const className = prompt('班级名称（如"高二3班"）：');
        if(!className||!className.trim()) return;
        const grade = prompt('年级（如"高二"，可留空）：') || '';
        fetch('/api/teacher/create-class', {method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({school_id: school.id, name: className.trim(), grade: grade.trim()||null})
        }).then(r=>{if(r.ok){toast('班级已创建');loadClassesPage();}else r.json().then(d=>toast(d.error||'创建失败','error'));});
      });
    }
  });
}

// ── Admin ──
async function loadAdminPage() {
  const r = await fetch('/api/admin/users');
  if (!r.ok) { toast('加载失败', 'error'); return; }
  const users = await r.json();
  const tbody = document.querySelector('#admin-users-table tbody');
  tbody.innerHTML = '';
  users.forEach(u => {
    tbody.innerHTML += `<tr>
      <td><strong>${u.username}</strong></td>
      <td><span class="badge badge-${u.role}">${u.role==='admin'?'管理员':'老师'}</span></td>
      <td>${fmtDate(u.created_at)}</td>
      <td>
        <button class="btn btn-sm btn-outline" onclick="deleteAdminUser(${u.id}, '${u.username}')" style="color:var(--red);">删除</button>
      </td>
    </tr>`;
  });
}
function openAdminModal() {
  document.getElementById('admin-modal').classList.add('show');
  document.getElementById('admin-username').value='';
  document.getElementById('admin-password').value='';
  document.getElementById('admin-role').value='teacher';
}
function closeAdminModal() { document.getElementById('admin-modal').classList.remove('show'); }
async function saveAdminUser() {
  const data = {
    username: document.getElementById('admin-username').value.trim(),
    password: document.getElementById('admin-password').value,
    role: document.getElementById('admin-role').value,
  };
  if (!data.username || !data.password) return toast('用户名和密码必填', 'error');
  const r = await fetch('/api/admin/users', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
  if (r.ok) { toast('账号已创建'); closeAdminModal(); loadAdminPage(); }
  else { const d = await r.json(); toast(d.error || '创建失败', 'error'); }
}
async function deleteAdminUser(id, name) {
  if (!confirm(`确定删除账号 "${name}"？此操作不可恢复。`)) return;
  const r = await fetch('/api/admin/users/'+id, {method:'DELETE'});
  if (r.ok) { toast('已删除'); loadAdminPage(); }
  else toast('删除失败', 'error');
}

// ── Referrals ──
async function loadReferralsPage() {
  const r = await fetch('/api/referrals/stats');
  if (!r.ok) return;
  const s = await r.json();

  document.getElementById('referral-stats').innerHTML = `
    <div class="stat"><div class="num">${s.total_invites}</div><div class="label">总邀请码数</div></div>
    <div class="stat ok"><div class="num">${s.total_converted}</div><div class="label">已转化</div></div>
    <div class="stat info"><div class="num">${s.conversion_rate}%</div><div class="label">转化率</div></div>
    <div class="stat warn"><div class="num">${s.total_reward_weeks}</div><div class="label">累计奖励周数</div></div>
  `;

  const tbody = document.querySelector('#referral-top-table tbody');
  tbody.innerHTML = '';
  if (s.top_referrers.length === 0) {
    tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;color:var(--sub);">暂无邀请数据</td></tr>';
  } else {
    s.top_referrers.forEach((ref, i) => {
      tbody.innerHTML += `<tr>
        <td>${i+1}. ${ref.name}</td>
        <td>${ref.count}</td>
        <td>${ref.weeks}</td>
      </tr>`;
    });
  }

  // Load current setting
  try {
    const sr = await fetch('/api/budget');  // reuse budget endpoint just to avoid extra call; actually we don't have settings GET
    // no-op
  } catch(e) {}
}

async function saveReferralSettings() {
  const weeks = parseInt(document.getElementById('referral-reward-weeks').value);
  if (isNaN(weeks) || weeks < 0) return toast('奖励周数必须是非负整数', 'error');
  const r = await fetch('/api/referrals/settings', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({reward_weeks: weeks})
  });
  if (r.ok) { toast('设置已保存'); loadReferralsPage(); }
  else { const d = await r.json(); toast(d.error || '保存失败', 'error'); }
}

// ── Question Bank ──
async function loadBankPage() {
  await loadBankStats();
  await loadBank();
}

async function loadBankStats() {
  const r = await fetch('/api/questions/stats');
  if (!r.ok) return;
  const s = await r.json();
  document.getElementById('bank-stats').innerHTML = `
    <div class="stat"><div class="num">${s.total_questions}</div><div class="label">总题目</div></div>
    <div class="stat ok"><div class="num">${s.enabled_questions}</div><div class="label">已启用</div></div>
    <div class="stat info"><div class="num">${s.used_questions}</div><div class="label">被使用过</div></div>
    <div class="stat warn"><div class="num">${s.reuse_rate}%</div><div class="label">复用率</div></div>
    <div class="stat"><div class="num">${s.total_usage}</div><div class="label">总使用次数</div></div>
  `;
}

async function loadBank() {
  const search = document.getElementById('bank-search').value.trim();
  const url = search ? '/api/questions?knowledge_point=' + encodeURIComponent(search) : '/api/questions';
  const r = await fetch(url);
  if (!r.ok) return;
  const questions = await r.json();
  const tbody = document.querySelector('#questions-table tbody');
  tbody.innerHTML = '';
  if (questions.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--sub);">暂无题目</td></tr>';
    return;
  }
  questions.forEach(q => {
    const kps = (q.knowledge_points || []).map(kp => `<span class="badge badge-blue" style="margin-right:4px;">${kp}</span>`).join('');
    tbody.innerHTML += `<tr>
      <td style="max-width:300px;font-size:.85em;">${q.question_text || '-'}</td>
      <td>${q.question_type || '-'}</td>
      <td>${kps}</td>
      <td>${q.difficulty || 2}</td>
      <td>${q.usage_count || 0}</td>
      <td><span class="badge badge-${q.enabled ? 'green' : 'red'}">${q.enabled ? '启用' : '禁用'}</span></td>
      <td style="white-space:nowrap;">
        <button class="btn btn-sm btn-outline" onclick="editQuestion(${q.id})">编辑</button>
        <button class="btn btn-sm btn-outline" onclick="toggleQuestion(${q.id}, ${q.enabled ? 0 : 1})" style="color:${q.enabled ? 'var(--red)' : 'var(--green)'};">${q.enabled ? '禁用' : '启用'}</button>
      </td>
    </tr>`;
  });
}

function editQuestion(id) {
  fetch('/api/questions/' + id).then(r => r.json()).then(q => {
    document.getElementById('q-id').value = q.id;
    document.getElementById('q-text').value = q.question_text || '';
    document.getElementById('q-type').value = q.question_type || '';
    document.getElementById('q-answer').value = q.correct_answer || '';
    document.getElementById('q-explanation').value = q.explanation || '';
    document.getElementById('q-kp').value = (q.knowledge_points || []).join(', ');
    document.getElementById('q-difficulty').value = q.difficulty || 2;
    document.getElementById('q-modal').classList.add('show');
  });
}

function closeQModal() {
  document.getElementById('q-modal').classList.remove('show');
}

async function saveQuestion() {
  const id = document.getElementById('q-id').value;
  const data = {
    question_text: document.getElementById('q-text').value,
    question_type: document.getElementById('q-type').value,
    correct_answer: document.getElementById('q-answer').value,
    explanation: document.getElementById('q-explanation').value,
    knowledge_points: document.getElementById('q-kp').value.split(',').map(s => s.trim()).filter(Boolean),
    difficulty: parseInt(document.getElementById('q-difficulty').value) || 2,
  };
  const r = await fetch('/api/questions/' + id, {
    method: 'PUT', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data)
  });
  if (r.ok) { toast('题目已更新'); closeQModal(); loadBank(); }
  else { const d = await r.json(); toast(d.error || '保存失败', 'error'); }
}

async function toggleQuestion(id, enable) {
  const r = await fetch('/api/questions/' + id + '/toggle', {method: 'POST'});
  if (r.ok) { toast('状态已更新'); loadBank(); }
  else toast('操作失败', 'error');
}

async function saveBudget() {
  const total = parseFloat(document.getElementById('budget-total').value);
  const student = parseFloat(document.getElementById('budget-student').value);
  if (isNaN(total) || isNaN(student) || total < 0 || student < 0) {
    return toast('预算必须是非负数', 'error');
  }
  const r = await fetch('/api/budget', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({monthly_total_budget: total, monthly_student_budget: student})
  });
  if (r.ok) { toast('预算已保存'); loadDashboard(); }
  else { const d = await r.json(); toast(d.error || '保存失败', 'error'); }
}

// ── Quality Sampling ──
async function loadQualityPage() {
  await loadQualityStats();
  await loadQuality();
}

async function loadQualityStats() {
  const r = await fetch('/api/safety-checks/stats');
  if (!r.ok) return;
  const s = await r.json();
  document.getElementById('quality-stats').innerHTML = `
    <div class="stat"><div class="num">${s.total_checks}</div><div class="label">总抽检数</div></div>
    <div class="stat warn"><div class="num">${s.pending}</div><div class="label">待抽检</div></div>
    <div class="stat ok"><div class="num">${s.clean}</div><div class="label">合格</div></div>
    <div class="stat" style="background:var(--red-light);"><div class="num" style="color:var(--red);">${s.flagged}</div><div class="label">已标记问题</div></div>
  `;
}

async function loadQuality() {
  const r = await fetch('/api/safety-checks/pending');
  const list = document.getElementById('quality-pending-list');
  if (!r.ok) {
    list.innerHTML = '<div style="color:var(--sub);text-align:center;padding:24px;">加载失败</div>';
    return;
  }
  const checks = await r.json();
  list.innerHTML = '';
  if (checks.length === 0) {
    list.innerHTML = '<div style="color:var(--sub);text-align:center;padding:24px;">🎉 暂无待抽检内容</div>';
    return;
  }
  checks.forEach(c => {
    const typeLabel = c.content_type === 'mistake' ? '错题分析' : (c.content_type === 'feedback' ? '批改反馈' : c.content_type);
    const issueOptions = [
      {value: 'wrong_answer', label: '答案错误'},
      {value: 'wrong_explanation', label: '解析错误'},
      {value: 'wrong_knowledge_point', label: '知识点归类错误'},
      {value: 'wrong_grading', label: '批改判定错误'},
      {value: 'ocr_residual', label: 'OCR 残留/识别错'},
      {value: 'other', label: '其他'},
    ];
    const checkboxes = issueOptions.map(o =>
      `<label style="display:flex;align-items:center;gap:6px;font-size:.85em;color:var(--text);margin-right:12px;">
        <input type="checkbox" class="qc-issue-${c.id}" value="${o.value}" style="width:auto;"> ${o.label}
      </label>`
    ).join('');
    list.innerHTML += `
      <div class="card" style="border:1px solid var(--border);border-radius:8px;padding:16px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
          <div><strong>#${c.id} ${typeLabel}</strong> <span style="font-size:.8em;color:var(--sub);">${c.student_name || '未知学生'} · 任务 #${c.task_id}</span></div>
          <span style="font-size:.75em;color:var(--sub);">${fmtDate(c.created_at)}</span>
        </div>
        <div style="background:var(--bg);padding:12px;border-radius:6px;font-size:.9em;margin-bottom:12px;line-height:1.5;">${escapeHtml(c.content_snapshot || '（无摘要）')}</div>
        <div class="qc-actions-${c.id}" style="display:flex;flex-wrap:wrap;gap:10px;align-items:center;">
          <button class="btn btn-sm btn-green" onclick="reviewSafetyCheck(${c.id}, 'clean')">✅ 合格</button>
          <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;">
            ${checkboxes}
            <button class="btn btn-sm btn-outline" style="color:var(--red);" onclick="reviewSafetyCheck(${c.id}, 'flagged')">🚩 标记问题</button>
          </div>
        </div>
      </div>`;
  });
}

async function reviewSafetyCheck(checkId, status) {
  let issueFlags = [];
  if (status === 'flagged') {
    document.querySelectorAll(`.qc-issue-${checkId}:checked`).forEach(cb => issueFlags.push(cb.value));
    if (issueFlags.length === 0) return toast('请至少选择一个问题类型', 'error');
  }
  const r = await fetch('/api/safety-checks/' + checkId + '/review', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({safety_status: status, issue_flags: issueFlags})
  });
  if (r.ok) {
    toast(status === 'clean' ? '已标记为合格' : '已标记问题');
    loadQualityPage();
  } else {
    const d = await r.json();
    toast(d.error || '操作失败', 'error');
  }
}

// ── Observability ──
async function loadObservabilityPage() {
  await loadObservabilityAlerts('obs-alert-banner');
  await loadTaskFailureStats();
  await loadRecentFailures();
  await loadCostAlerts();
  await loadAuditLogActions();
  await loadAuditLogs();
  await loadBackups();
}

async function loadCompliance() {
  // Students without consent
  try {
    const r = await fetch('/api/compliance/students-without-consent');
    const students = r.ok ? await r.json() : [];
    document.getElementById('consent-pending-count').textContent = `待授权 ${students.length} 人`;
    const tbody = document.querySelector('#consent-table tbody');
    tbody.innerHTML = '';
    if (students.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--sub);">🎉 所有学生已完成家长授权</td></tr>';
    } else {
      students.forEach(s => {
        tbody.innerHTML += `
          <tr>
            <td><strong>${escapeHtml(s.name)}</strong></td>
            <td>${escapeHtml(s.grade || '')}</td>
            <td>${escapeHtml(s.parent_wechat || '')}</td>
            <td style="white-space:nowrap;">
              <button class="btn btn-sm btn-primary" onclick="openConsentModal(${s.id}, '${escapeHtml(s.name)}')">记录授权</button>
            </td>
          </tr>`;
      });
    }
  } catch(e) { console.error('Consent list load failed', e); }

  // Pending deletion requests
  try {
    const r = await fetch('/api/compliance/deletion-requests');
    const requests = r.ok ? await r.json() : [];
    document.getElementById('deletion-pending-count').textContent = `待处理 ${requests.length} 条`;
    const tbody = document.querySelector('#deletion-table tbody');
    tbody.innerHTML = '';
    if (requests.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--sub);">暂无待处理的数据删除申请</td></tr>';
    } else {
      requests.forEach(dr => {
        const isAdmin = window.CURRENT_USER_ROLE === 'admin';
        const processBtn = isAdmin
          ? `<button class="btn btn-sm btn-outline" style="color:var(--red);" onclick="processDeletion(${dr.id}, this)">执行删除</button>`
          : '<span style="font-size:.8em;color:var(--sub);">需管理员处理</span>';
        tbody.innerHTML += `
          <tr>
            <td><strong>${escapeHtml(dr.student_name)}</strong></td>
            <td>${escapeHtml(dr.requested_by)}</td>
            <td>${escapeHtml(dr.reason || '-')}</td>
            <td>${fmtDate(dr.created_at)}</td>
            <td style="white-space:nowrap;">${processBtn}</td>
          </tr>`;
      });
    }
  } catch(e) { console.error('Deletion requests load failed', e); }
}

async function openConsentModal(studentId, studentName) {
  const consentedBy = prompt(`记录 ${studentName} 的家长授权\n请输入家长姓名（必填）：`);
  if (!consentedBy || !consentedBy.trim()) return;
  const contact = prompt(`请输入家长联系方式（手机/微信，可选）：`) || '';
  const notes = prompt(`备注（可选）：`) || '';
  const r = await fetch('/api/compliance/consents', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({student_id: studentId, consented_by: consentedBy, contact, notes}),
  });
  if (r.ok) {
    toast('家长授权已记录');
    loadCompliance();
    loadDashboard();
  } else {
    toast('授权记录失败', 'error');
  }
}

async function processDeletion(reqId, btn) {
  if (!confirm('确定要执行删除吗？该学生将被软删除，公开页链接失效，相关数据保留在数据库中但标记为已删除。')) return;
  btn.disabled = true;
  const r = await fetch('/api/compliance/deletion-requests/' + reqId + '/process', {method: 'POST'});
  if (r.ok) {
    toast('删除申请已处理');
    loadCompliance();
    loadDashboard();
  } else {
    toast('处理失败', 'error');
    btn.disabled = false;
  }
}

async function loadTeacherProfilePage() {
  const r = await fetch('/api/teacher-profile');
  const p = r.ok ? await r.json() : {};
  document.getElementById('tp-institution').value = p.institution_name || '';
  document.getElementById('tp-teacher').value = p.teacher_name || '';
  document.getElementById('tp-years').value = p.teaching_years || '';
  document.getElementById('tp-specialty').value = p.specialty || '';
  document.getElementById('tp-philosophy').value = p.philosophy || '';
  document.getElementById('tp-contact').value = p.contact_info || '';
  const preview = document.getElementById('tp-avatar-preview');
  preview.textContent = p.avatar_url ? '当前头像：' + p.avatar_url : '未上传头像';
}

async function saveTeacherProfile() {
  const fileInput = document.getElementById('tp-avatar');
  let avatar_url = '';
  if (fileInput.files[0]) {
    const fd = new FormData();
    fd.append('file', fileInput.files[0]);
    const ur = await fetch('/api/teacher-profile/avatar', {method: 'POST', body: fd});
    if (!ur.ok) { toast('头像上传失败', 'error'); return; }
    const u = await ur.json();
    avatar_url = u.url;
  }
  const body = {
    institution_name: document.getElementById('tp-institution').value,
    teacher_name: document.getElementById('tp-teacher').value,
    teaching_years: document.getElementById('tp-years').value,
    specialty: document.getElementById('tp-specialty').value,
    philosophy: document.getElementById('tp-philosophy').value,
    contact_info: document.getElementById('tp-contact').value,
    avatar_url: avatar_url,
  };
  const r = await fetch('/api/teacher-profile', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  if (r.ok) {
    toast('机构介绍已保存');
    loadTeacherProfilePage();
  } else {
    toast('保存失败', 'error');
  }
}

async function loadObservabilityAlerts(containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const r = await fetch('/api/alerts');
  if (!r.ok) { container.innerHTML = ''; return; }
  const alerts = await r.json();
  if (!alerts.length) { container.innerHTML = ''; return; }
  container.innerHTML = alerts.map(a => `
    <div style="padding:10px 12px; border-radius:6px; margin-bottom:8px; font-size:.9em; display:flex; justify-content:space-between; align-items:center; ${a.level === 'critical' ? 'background:var(--red-light); color:var(--red);' : 'background:var(--accent-light); color:var(--accent);'}">
      <span>${a.level === 'critical' ? '🔴' : '⚠️'} ${escapeHtml(a.message)}</span>
      <button class="btn btn-sm btn-outline" onclick="dismissAlert(${a.id}, '${containerId}')" style="margin-left:12px;">忽略</button>
    </div>
  `).join('');
}

async function dismissAlert(alertId, containerId) {
  const r = await fetch('/api/alerts/' + alertId + '/dismiss', {method: 'POST'});
  if (r.ok) {
    toast('告警已忽略');
    await loadObservabilityAlerts(containerId);
    if (containerId !== 'obs-alert-banner') await loadObservabilityAlerts('obs-alert-banner');
  } else {
    toast('忽略失败', 'error');
  }
}

async function loadTaskFailureStats() {
  const r = await fetch('/api/tasks/failure-stats?days=7');
  if (!r.ok) return;
  const s = await r.json();
  document.getElementById('obs-task-stats').innerHTML = `
    <div class="stat"><div class="num">${s.total}</div><div class="label">总任务</div></div>
    <div class="stat warn"><div class="num">${s.failed}</div><div class="label">失败</div></div>
    <div class="stat" style="background:var(--accent-light);"><div class="num" style="color:var(--accent);">${s.rejected}</div><div class="label">驳回</div></div>
    <div class="stat" style="background:${s.failure_rate > 10 ? 'var(--red-light)' : 'var(--green-light)'};"><div class="num" style="color:${s.failure_rate > 10 ? 'var(--red)' : 'var(--green)'};">${s.failure_rate}%</div><div class="label">失败率</div></div>
  `;
  renderFailureTrend(s.daily_breakdown || []);
}

function renderFailureTrend(daily) {
  const container = document.getElementById('obs-failure-trend');
  if (!daily.length) {
    container.innerHTML = '<div style="color:var(--sub);text-align:center;padding-top:40px;">近7天无数据</div>';
    return;
  }
  const maxVal = Math.max(1, ...daily.map(d => Math.max(d.failed || 0, d.rejected || 0)));
  const bars = daily.slice().reverse().map(d => {
    const total = (d.failed || 0) + (d.rejected || 0);
    const fh = ((d.failed || 0) / maxVal * 100).toFixed(1);
    const rh = ((d.rejected || 0) / maxVal * 100).toFixed(1);
    return `
      <div style="display:flex;flex-direction:column;align-items:center;gap:4px;min-width:60px;">
        <div style="display:flex;align-items:flex-end;gap:2px;height:100px;">
          <div style="width:10px;height:${fh}%;background:var(--red);border-radius:2px;" title="失败 ${d.failed}"></div>
          <div style="width:10px;height:${rh}%;background:var(--accent);border-radius:2px;" title="驳回 ${d.rejected}"></div>
        </div>
        <div style="font-size:.7em;color:var(--sub);">${d.day.slice(5)}</div>
        <div style="font-size:.7em;color:var(--sub);">共${total}</div>
      </div>`;
  }).join('');
  container.innerHTML = `<div style="display:flex;align-items:flex-end;gap:12px;height:100%;">${bars}</div>
    <div style="margin-top:8px;font-size:.75em;color:var(--sub);">🟥 失败 🟧 驳回</div>`;
}

async function loadRecentFailures() {
  const r = await fetch('/api/tasks/recent-failures?limit=10');
  const tbody = document.querySelector('#obs-failure-table tbody');
  if (!r.ok) { tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--sub);">加载失败</td></tr>'; return; }
  const items = await r.json();
  tbody.innerHTML = '';
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--sub);">🎉 近期无失败任务</td></tr>';
    return;
  }
  items.forEach(t => {
    const statusLabel = t.status === 'failed' ? '<span style="color:var(--red);">失败</span>' : '<span style="color:var(--accent);">驳回</span>';
    const err = escapeHtml(t.error_message || '—');
    const shortErr = err.length > 80 ? err.slice(0, 80) + '...' : err;
    tbody.innerHTML += `
      <tr>
        <td>${t.student_name || '?'}</td>
        <td>${t.task_type === 'onboarding' ? '入学诊断' : '周度服务'}</td>
        <td>${statusLabel}</td>
        <td>${fmtDate(t.completed_at || t.created_at)}</td>
        <td>
          <span class="failure-msg-short">${shortErr}</span>
          ${err.length > 80 ? `<button class="btn btn-sm btn-outline" onclick="this.previousElementSibling.textContent='${err}';this.style.display='none';">展开</button>` : ''}
        </td>
      </tr>`;
  });
}

async function loadCostAlerts() {
  const r = await fetch('/api/cost/alerts');
  const panel = document.getElementById('obs-cost-panel');
  if (!r.ok) { panel.innerHTML = '加载失败'; return; }
  const d = await r.json();
  const thresholdEl = document.getElementById('obs-alert-threshold');
  if (thresholdEl) thresholdEl.value = d.threshold_pct;
  const pct = Math.min(d.monthly_pct, 100);
  const color = d.monthly_pct >= 100 ? 'var(--red)' : (d.monthly_pct >= d.threshold_pct ? 'var(--accent)' : 'var(--green)');
  let html = `
    <div style="margin-bottom:12px;">
      <div style="display:flex;justify-content:space-between;font-size:.85em;margin-bottom:4px;">
        <span>本月总成本 $${d.month_cost.toFixed(4)} / $${d.monthly_budget.toFixed(2)}</span>
        <span style="color:${color};font-weight:600;">${d.monthly_pct}%</span>
      </div>
      <div class="progress-bar" style="height:8px;"><div class="fill" style="width:${pct}%;background:${color};"></div></div>
    </div>
  `;
  if (d.alerts.length) {
    html += d.alerts.map(a => `
      <div style="padding:8px 10px; border-radius:6px; margin-bottom:6px; font-size:.85em; ${a.level === 'critical' ? 'background:var(--red-light); color:var(--red);' : 'background:var(--accent-light); color:var(--accent);'}">
        ${a.level === 'critical' ? '🔴' : '⚠️'} ${escapeHtml(a.message)}
      </div>
    `).join('');
  } else {
    html += '<div style="color:var(--green);font-size:.85em;">✅ 当前成本正常，未触发告警</div>';
  }
  panel.innerHTML = html;
}

async function saveAlertSettings() {
  const threshold = parseInt(document.getElementById('obs-alert-threshold').value);
  if (isNaN(threshold) || threshold < 0 || threshold > 100) {
    return toast('阈值必须是 0-100 的整数', 'error');
  }
  const r = await fetch('/api/admin/alert-settings', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({threshold_pct: threshold, enabled: true})
  });
  if (r.ok) { toast('告警阈值已保存'); loadCostAlerts(); }
  else { const d = await r.json(); toast(d.error || '保存失败', 'error'); }
}

async function loadAuditLogActions() {
  const r = await fetch('/api/audit-logs/actions');
  if (!r.ok) return;
  const actions = await r.json();
  const sel = document.getElementById('obs-audit-action');
  const current = sel.value;
  sel.innerHTML = '<option value="">全部</option>' + actions.map(a => `<option value="${a}">${a}</option>`).join('');
  sel.value = current || '';
}

async function loadAuditLogs() {
  const action = document.getElementById('obs-audit-action').value;
  const targetType = document.getElementById('obs-audit-target').value;
  const since = document.getElementById('obs-audit-since').value;
  const params = new URLSearchParams();
  if (action) params.append('action', action);
  if (targetType) params.append('target_type', targetType);
  if (since) params.append('since', since);
  params.append('limit', '100');

  const r = await fetch('/api/audit-logs?' + params.toString());
  const tbody = document.querySelector('#obs-audit-table tbody');
  if (!r.ok) { tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--sub);">加载失败</td></tr>'; return; }
  const logs = await r.json();
  tbody.innerHTML = '';
  if (!logs.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--sub);">暂无记录</td></tr>';
    return;
  }
  logs.forEach(l => {
    const details = JSON.stringify(l.details || {}, null, 2);
    tbody.innerHTML += `
      <tr>
        <td style="font-size:.8em;white-space:nowrap;">${fmtDate(l.created_at)} ${l.created_at ? l.created_at.slice(11,16) : ''}</td>
        <td>${l.actor_type || '-'}</td>
        <td>${l.action}</td>
        <td style="font-size:.8em;">${l.target_type || '-'} ${l.target_id || ''}</td>
        <td style="font-size:.8em;max-width:300px;overflow:hidden;text-overflow:ellipsis;"><pre style="margin:0;background:var(--bg);padding:6px;border-radius:4px;">${escapeHtml(details)}</pre></td>
      </tr>`;
  });
}

function formatBytes(bytes) {
  if (!bytes) return '-';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
}

async function loadBackups() {
  const tbody = document.querySelector('#obs-backup-table tbody');
  if (!tbody) return; // admin-only section, skip for teachers
  const r = await fetch('/api/backups');
  if (!r.ok) { tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--sub);">加载失败</td></tr>'; return; }
  const backups = await r.json();
  tbody.innerHTML = '';
  if (!backups.length) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--sub);">暂无备份</td></tr>';
    return;
  }
  backups.forEach(b => {
    tbody.innerHTML += `
      <tr>
        <td>${fmtDate(b.created_at)} ${b.created_at ? b.created_at.slice(11,16) : ''}</td>
        <td>${b.backup_type === 'daily' ? '每日' : (b.backup_type === 'weekly' ? '每周' : '手动')}</td>
        <td>${formatBytes(b.file_size)}</td>
        <td><a href="/api/backups/${b.id}/download" class="btn btn-sm btn-outline">下载</a></td>
      </tr>`;
  });
}

async function runManualBackup() {
  const btn = event.target;
  btn.disabled = true; btn.textContent = '备份中...';
  const r = await fetch('/api/backups/run', {method: 'POST'});
  btn.disabled = false; btn.textContent = '立即备份';
  if (r.ok) {
    toast('备份已完成');
    loadBackups();
  } else {
    toast('备份失败', 'error');
  }
}

// ── Learning Analytics ──
let _analyticsLoaded = false;
async function loadAnalyticsPage() {
  const sel = document.getElementById('analytics-student');
  if (_analyticsLoaded && sel && sel.options.length > 0) return;
  _analyticsLoaded = true;
  await loadClassAnalytics();
  // Load student selector
  const students = await (await fetch('/api/students')).json();
  const opts = students.map(s => `<option value="${s.id}">${escapeHtml(s.name)} (${escapeHtml(s.grade)})</option>`).join('');
  sel.innerHTML = opts;
  if (students.length > 0) {
    await loadStudentAnalytics(students[0].id);
  }
}

async function loadClassAnalytics() {
  const r = await fetch('/api/learning/class');
  if (!r.ok) return;
  const d = await r.json();

  document.getElementById('class-stats').innerHTML = `
    <div class="stat"><div class="num">${d.total_students}</div><div class="label">学生总数</div></div>
    <div class="stat info"><div class="num">${d.average_score||'-'}</div><div class="label">班级平均分</div></div>
    <div class="stat warn"><div class="num">${d.weak_knowledge_points.length}</div><div class="label">薄弱知识点</div></div>
  `;

  // Class trend chart
  document.getElementById('class-trend-chart').innerHTML = renderLineChart(
    d.score_trend.map(x => x.week_start.slice(5)),
    d.score_trend.map(x => x.avg_score),
    {height: 220, color: 'var(--accent)'}
  );

  // Weak knowledge points
  const kpDiv = document.getElementById('class-weak-kp');
  kpDiv.innerHTML = renderKnowledgeMastery(d.weak_knowledge_points, {compact: true});
}

async function loadStudentAnalytics(studentId) {
  if (!studentId) studentId = document.getElementById('analytics-student').value;
  if (!studentId) return;

  document.getElementById('score-student-id').value = studentId;
  const r = await fetch('/api/learning/student/' + studentId);
  if (!r.ok) return;
  const d = await r.json();

  document.getElementById('score-student-name').value = d.student ? d.student.name : '';

  document.getElementById('student-stats').innerHTML = `
    <div class="stat"><div class="num">${d.current_score||'-'}</div><div class="label">当前分数</div></div>
    <div class="stat info"><div class="num">${d.target_score||'-'}</div><div class="label">目标分数</div></div>
    <div class="stat ok"><div class="num">${d.practice_accuracy}%</div><div class="label">近期正确率</div></div>
    <div class="stat warn"><div class="num">${d.mistakes.total}</div><div class="label">总错题数</div></div>
  `;

  // Student trend chart
  const labels = d.scores.map(s => s.created_at.slice(5, 10));
  const values = d.scores.map(s => s.score);
  document.getElementById('student-trend-chart').innerHTML = values.length > 0
    ? renderLineChart(labels, values, {height: 220, color: 'var(--accent)', target: d.target_score})
    : '<p style="text-align:center;color:var(--sub);padding-top:80px;">暂无分数记录，可在周度批改后自动生成，或手动录入</p>';

  // Knowledge point heatmap
  const heatmapDiv = document.getElementById('student-kp-heatmap');
  heatmapDiv.innerHTML = renderKnowledgeMastery(d.knowledge_points, {showMastered: true});

  // Practice stats
  document.getElementById('student-practice-stats').innerHTML = `
    <p style="color:var(--sub);">近期练习 <strong>${d.practice_count_recent}</strong> 次，平均正确率 <strong>${d.practice_accuracy}%</strong>。</p>
  `;

  // Mistake stats
  const dueInfo = (d.mistakes.due_now > 0)
    ? `<span style="color:var(--red);"> ⚠️ <strong>${d.mistakes.due_now}</strong> 道待复习，<strong>${d.mistakes.upcoming_3d}</strong> 道3日内需复习</span>`
    : '';
  document.getElementById('student-mistake-stats').innerHTML = `
    <p style="color:var(--sub);">累计错题 <strong>${d.mistakes.total}</strong> 道，已掌握 <strong>${d.mistakes.mastered}</strong> 道，
       练习中 <strong>${d.mistakes.in_progress}</strong> 道，总复习次数 <strong>${d.mistakes.total_reviews}</strong>。${dueInfo}</p>
  `;

  // Learning path timeline (teacher view)
  renderTeacherTimeline(studentId);

  // Achievement wall (teacher view)
  renderTeacherAchievementWall(studentId);

  // Profile summary
  const profileDiv = document.getElementById('student-profile-summary');
  if (d.has_profile && d.profile) {
    const p = d.profile;
    const choices = p.plan_choices || {};
    const hasChoices = Object.keys(choices).some(k => choices[k]);
    const idCard = p.english_identity || '未填写';
    const idColor = { '敌人': 'var(--red)', '工具': 'var(--sub)', '朋友': 'var(--green)', '兴趣': 'var(--accent)' }[idCard] || 'var(--sub)';
    const tm = p.time_map || {};
    const slots = Array.isArray(tm.slots) ? tm.slots : [];
    const tmHtml = slots.length > 0 ? renderTimeMapVisualization(slots, tm.description) : '';
    const planLs = (d.learning_plan && d.learning_plan.diagnosis_report && d.learning_plan.diagnosis_report.learning_style) || null;
    const profileLs = p.learning_style_detail || null;
    const lsData = planLs || profileLs;
    const hasLsData = lsData && ['visual','auditory','kinesthetic','read_write'].some(k => Number(lsData[k]) > 0);
    const lsRadarHtml = hasLsData ? renderRadarChart(lsData, {size: 200}) : '';
    profileDiv.innerHTML = `
      ${lsRadarHtml ? `
      <div style="background:var(--card);border:1px solid var(--border);border-radius:6px;padding:12px;margin-bottom:10px;">
        <div style="font-size:.85em;color:var(--sub);margin-bottom:8px;">AI 学习风格画像（${lsData.dominant || p.learning_style || '未识别'}）</div>
        <div style="max-width:260px;">${lsRadarHtml}</div>
      </div>
      ` : ''}
      <div style="display:flex;flex-wrap:wrap;gap:8px;">
        <div style="flex:1 1 200px;background:var(--card);border:1px solid var(--border);border-radius:6px;padding:10px;">
          <div style="font-size:.75em;color:var(--sub);">学习类型 · 介质</div>
          <div style="font-size:.85em;font-weight:600;">${p.learning_style||'未填写'} · ${p.learning_medium||'未填写'}</div>
        </div>
        <div style="flex:1 1 200px;background:var(--card);border:1px solid var(--border);border-radius:6px;padding:10px;">
          <div style="font-size:.75em;color:var(--sub);">与英语的关系</div>
          <div style="font-size:.85em;font-weight:600;color:${idColor};">${idCard}</div>
        </div>
        <div style="flex:1 1 200px;background:var(--card);border:1px solid var(--border);border-radius:6px;padding:10px;">
          <div style="font-size:.75em;color:var(--sub);">词汇方向</div>
          <div style="font-size:.85em;font-weight:600;">${p.vocab_direction ? {'A':'匹配教材','B':'预习教材','C':'高考高频','D':'混合模式'}[p.vocab_direction] : '未填写'}</div>
        </div>
        <div style="flex:1 1 200px;background:var(--card);border:1px solid var(--border);border-radius:6px;padding:10px;">
          <div style="font-size:.75em;color:var(--sub);">1个月小目标</div>
          <div style="font-size:.85em;font-weight:600;">${p.one_month_goal||'未填写'}</div>
        </div>
        ${hasChoices ? `
        <div style="flex:1 1 200px;background:var(--accent-light);border:1px solid var(--accent);border-radius:6px;padding:10px;">
          <div style="font-size:.75em;color:var(--accent);">关键抉择</div>
          <div style="font-size:.85em;font-weight:600;">${choices.module_ratio||'-'} · ${choices.difficulty_start||'-'} · ${choices.daily_vocab||'-'}词/天</div>
        </div>
        ` : ''}
        ${p.plan_name ? `
        <div style="flex:1 1 200px;background:var(--green-light);border:1px solid var(--green);border-radius:6px;padding:10px;">
          <div style="font-size:.75em;color:var(--green);">专属计划</div>
          <div style="font-size:.85em;font-weight:600;">${p.plan_name}${p.plan_code_name ? ' · ' + p.plan_code_name : ''}</div>
        </div>
        ` : ''}
      </div>
      ${tmHtml}
    `;
  } else {
    profileDiv.innerHTML = `
      <div style="background:var(--bg);border:1px dashed var(--border);border-radius:6px;padding:16px;text-align:center;">
        <p style="color:var(--sub);font-size:.9em;">该学生尚未填写个性化画像</p>
        <button class="btn btn-sm btn-primary" onclick="editStudent(${studentId})" style="margin-top:8px;">去完善画像</button>
      </div>
    `;
  }

  // Diagnosis conclusion from latest plan
  const conclusionDiv = document.getElementById('student-diagnosis-conclusion');
  const plan = d.learning_plan || {};
  const diagnosis = plan.diagnosis_report;
  if (diagnosis && diagnosis.conclusion) {
    const c = diagnosis.conclusion;
    conclusionDiv.innerHTML = `
      <div style="background:var(--card);border:1px solid var(--border);border-radius:6px;padding:14px;">
        ${Array.isArray(c.core_findings) ? `
        <p style="font-size:.85em;color:var(--sub);margin-bottom:8px;"><strong>核心发现</strong></p>
        <ul style="margin:0 0 12px 18px;font-size:.85em;line-height:1.6;">${c.core_findings.map(f=>`<li>${f}</li>`).join('')}</ul>` : ''}
        <div style="display:flex;flex-wrap:wrap;gap:8px;">
          ${c.short_term ? `<div style="flex:1 1 200px;background:var(--bg);border-radius:6px;padding:10px;">
            <div style="font-size:.75em;color:var(--sub);">短期（1个月）</div>
            <div style="font-size:.82em;">${c.short_term}</div>
          </div>` : ''}
          ${c.medium_term ? `<div style="flex:1 1 200px;background:var(--bg);border-radius:6px;padding:10px;">
            <div style="font-size:.75em;color:var(--sub);">中期（1学期）</div>
            <div style="font-size:.82em;">${c.medium_term}</div>
          </div>` : ''}
          ${c.long_term ? `<div style="flex:1 1 200px;background:var(--bg);border-radius:6px;padding:10px;">
            <div style="font-size:.75em;color:var(--sub);">长期（1年）</div>
            <div style="font-size:.82em;">${c.long_term}</div>
          </div>` : ''}
        </div>
        ${c.warning ? `<p style="margin-top:12px;font-size:.82em;color:var(--red);">⚠️ ${c.warning}</p>` : ''}
      </div>
    `;
  } else {
    conclusionDiv.innerHTML = `<p style="color:var(--sub);font-size:.85em;">尚未生成基于画像的 AI 诊断结论。完成入学诊断后将在此展示。</p>`;
  }

  // Parent growth tasks
  const tasksDiv = document.getElementById('student-parent-tasks');
  const parentTasks = plan.parent_growth_tasks || [];
  const taskProgress = (d.profile && d.profile.parent_task_progress) || {};
  if (parentTasks.length > 0) {
    tasksDiv.innerHTML = `
      <div style="background:var(--card);border:1px solid var(--border);border-radius:6px;padding:14px;">
        <p style="font-size:.85em;color:var(--sub);margin-bottom:12px;">4 周渐进式家长脚手架，根据孩子画像和家庭支持情况生成。</p>
        <div style="display:flex;flex-direction:column;gap:10px;">
          ${parentTasks.map((t, idx) => {
            const weekKey = 'week' + t.week;
            const done = !!taskProgress[weekKey];
            return `
            <div style="display:flex;gap:10px;align-items:flex-start;background:var(--bg);border-radius:6px;padding:10px;${done ? 'opacity:.7;' : ''}">
              <input type="checkbox" ${done ? 'checked' : ''} onchange="toggleParentTask(${studentId}, '${weekKey}', this.checked)" style="margin-top:3px;width:auto;">
              <div style="flex:1;">
                <div style="font-size:.85em;font-weight:600;">第 ${t.week} 周 · ${t.theme} · ${t.title}</div>
                <div style="font-size:.82em;color:var(--text);margin-top:2px;">${t.task}</div>
                ${t.example ? `<div style="font-size:.8em;color:var(--sub);margin-top:4px;">示例：${t.example}</div>` : ''}
                ${t.goal ? `<div style="font-size:.78em;color:var(--accent);margin-top:4px;">目标：${t.goal}</div>` : ''}
              </div>
            </div>`;
          }).join('')}
        </div>
      </div>
    `;
  } else {
    tasksDiv.innerHTML = `<p style="color:var(--sub);font-size:.85em;">尚未生成家长成长任务包。完成入学诊断后将在此展示。</p>`;
  }

  // Motivation / Achievement cards
  const cardsDiv = document.getElementById('student-motivation-cards');
  const motivationCards = plan.motivation_cards || [];
  const achievements = d.achievements || [];
  const allCards = [
    ...motivationCards.map(c => ({...c, tag: 'AI'})),
    ...achievements.map(a => ({...a, tag: '数据'}))
  ];
  if (allCards.length > 0) {
    cardsDiv.innerHTML = `
      <div style="display:flex;flex-wrap:wrap;gap:10px;">
        ${allCards.map(c => `
          <div style="flex:1 1 200px;background:var(--card);border:1px solid var(--border);border-radius:6px;padding:12px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
              <span style="font-size:.8em;color:var(--accent);font-weight:600;">${c.title || '卡片'}</span>
              ${c.tag ? `<span style="font-size:.65em;background:var(--bg);color:var(--sub);padding:1px 6px;border-radius:4px;">${c.tag}</span>` : ''}
            </div>
            <div style="font-size:.85em;line-height:1.5;">${c.content || ''}</div>
          </div>
        `).join('')}
      </div>
    `;
  } else {
    cardsDiv.innerHTML = `<p style="color:var(--sub);font-size:.85em;">尚未生成卡片。完成入学诊断或产生练习记录后将自动生成。</p>`;
  }

  // Metacognitive review — now fetches student-submitted reviews
  const reviewDiv = document.getElementById('student-metacognitive-review');
  try {
    const revRes = await fetch('/api/students/' + studentId + '/reviews');
    if (revRes.ok) {
      const revData = await revRes.json();
      const current = revData.current || {};
      const history = revData.history || [];
      const submitted = history.filter(h => h.status === 'submitted');

      let revHtml = '';
      // Show current week review form status
      revHtml += `<div style="margin-bottom:12px;">
        <span style="font-weight:600;">📝 ${current.week_start || '本周'} 复盘</span>
        <span style="margin-left:8px;font-size:.8em;color:${current.status==='submitted'?'var(--green)':'var(--sub)'};">${current.status==='submitted' ? '✅ 已提交' : '⏳ 待填写'}</span>
        ${current.child_mood ? `<span style="margin-left:8px;font-size:.8em;">孩子心情：${'⭐'.repeat(current.child_mood)}</span>` : ''}
        ${current.parent_mood ? `<span style="margin-left:8px;font-size:.8em;">家长感受：${'⭐'.repeat(current.parent_mood)}</span>` : ''}
      </div>`;

      // Show latest submitted review details
      if (submitted.length > 0) {
        const latest = submitted[0];
        const childAns = latest.child_answers || {};
        const parentAns = latest.parent_answers || {};
        revHtml += `<div style="background:var(--card);border:1px solid var(--border);border-radius:6px;padding:12px;max-height:240px;overflow-y:auto;">`;
        revHtml += `<div style="font-size:.8em;color:var(--sub);margin-bottom:8px;">最近提交：${latest.week_start} 周 (${(latest.submitted_at||'').slice(0,10)})</div>`;
        if (Object.keys(childAns).length > 0) {
          revHtml += `<div style="font-size:.8em;font-weight:600;margin-bottom:4px;">🙋 孩子反思</div>`;
          Object.entries(childAns).forEach(([q, a]) => {
            revHtml += `<div style="font-size:.78em;color:var(--sub);margin-bottom:4px;"><strong>Q:</strong> ${q}</div>`;
            revHtml += `<div style="font-size:.78em;margin-bottom:8px;padding-left:8px;border-left:2px solid var(--accent);"><strong>A:</strong> ${a}</div>`;
          });
        }
        if (Object.keys(parentAns).length > 0) {
          revHtml += `<div style="font-size:.8em;font-weight:600;margin-bottom:4px;">👨‍👩‍👧 家长观察</div>`;
          Object.entries(parentAns).forEach(([q, a]) => {
            revHtml += `<div style="font-size:.78em;color:var(--sub);margin-bottom:4px;"><strong>Q:</strong> ${q}</div>`;
            revHtml += `<div style="font-size:.78em;margin-bottom:8px;padding-left:8px;border-left:2px solid var(--green);"><strong>A:</strong> ${a}</div>`;
          });
        }
        if (latest.child_note) revHtml += `<div style="font-size:.78em;color:var(--sub);">📝 孩子备注：${latest.child_note}</div>`;
        if (latest.parent_note) revHtml += `<div style="font-size:.78em;color:var(--sub);">📝 家长备注：${latest.parent_note}</div>`;
        revHtml += `</div>`;
      } else {
        revHtml += `<p style="color:var(--sub);font-size:.8em;">暂无已提交的复盘表。</p>`;
      }

      reviewDiv.innerHTML = revHtml;
    } else {
      reviewDiv.innerHTML = `<p style="color:var(--sub);font-size:.85em;">尚未生成元认知复盘表。</p>`;
    }
  } catch(e) {
    reviewDiv.innerHTML = `<p style="color:var(--sub);font-size:.85em;">加载复盘数据失败。</p>`;
  }

  // Plan adjustments
  const adjDiv = document.getElementById('student-plan-adjustments');
  const lastAdj = plan.last_adjustment || (d.learning_plan && d.learning_plan.plan_data && d.learning_plan.plan_data.last_adjustment);
  if (lastAdj) {
    adjDiv.innerHTML = `
      <div style="background:var(--card);border:1px solid var(--border);border-radius:6px;padding:12px;">
        <div style="font-size:.85em;color:var(--sub);margin-bottom:4px;">周 ${lastAdj.week_start || '-'} · 完成率 ${(lastAdj.completion_rate * 100).toFixed(0)}%</div>
        <div style="font-size:.85em;line-height:1.5;">${lastAdj.reason || ''}</div>
      </div>
    `;
  } else {
    adjDiv.innerHTML = `<p style="color:var(--sub);font-size:.85em;">暂无自适应调整记录。</p>`;
  }
}

async function toggleParentTask(studentId, weekKey, done) {
  const progress = {};
  progress[weekKey] = done;
  const r = await fetch('/api/students/' + studentId + '/profile/parent-tasks', {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({parent_task_progress: progress})
  });
  if (r.ok) {
    toast(done ? '已标记完成' : '已取消标记');
    loadStudentAnalytics(studentId);
  } else {
    toast('更新失败', 'error');
  }
}

function renderLineChart(labels, values, opts={}) {
  if (!values || values.length === 0) return '';
  const height = opts.height || 200;
  const width = 800;
  const padding = 40;
  const chartW = width - padding * 2;
  const chartH = height - padding * 2;
  const maxVal = Math.max(...values, opts.target || 0, 1);
  const minVal = Math.min(...values, 0);
  const range = maxVal - minVal || 1;

  const points = values.map((v, i) => {
    const x = padding + (i / (values.length - 1 || 1)) * chartW;
    const y = height - padding - ((v - minVal) / range) * chartH;
    return `${x},${y}`;
  }).join(' ');

  const dots = values.map((v, i) => {
    const x = padding + (i / (values.length - 1 || 1)) * chartW;
    const y = height - padding - ((v - minVal) / range) * chartH;
    return `<circle cx="${x}" cy="${y}" r="4" fill="${opts.color||'var(--accent)'}" stroke="#fff" stroke-width="2" />
            <text x="${x}" y="${y - 10}" text-anchor="middle" font-size="11" fill="var(--sub)">${v}</text>`;
  }).join('');

  const xLabels = labels.map((l, i) => {
    const x = padding + (i / (labels.length - 1 || 1)) * chartW;
    return `<text x="${x}" y="${height - padding + 18}" text-anchor="middle" font-size="11" fill="var(--sub)">${l}</text>`;
  }).join('');

  let targetLine = '';
  if (opts.target) {
    const y = height - padding - ((opts.target - minVal) / range) * chartH;
    targetLine = `<line x1="${padding}" y1="${y}" x2="${width - padding}" y2="${y}" stroke="var(--green)" stroke-dasharray="4,4" />
                  <text x="${width - padding}" y="${y - 5}" text-anchor="end" font-size="11" fill="var(--green)">目标 ${opts.target}</text>`;
  }

  return `<svg viewBox="0 0 ${width} ${height}" style="width:100%;height:${height}px;">
    <rect width="${width}" height="${height}" fill="var(--card)" />
    <line x1="${padding}" y1="${height - padding}" x2="${width - padding}" y2="${height - padding}" stroke="var(--border)" />
    <line x1="${padding}" y1="${padding}" x2="${padding}" y2="${height - padding}" stroke="var(--border)" />
    ${targetLine}
    <polyline fill="none" stroke="${opts.color||'var(--accent)'}" stroke-width="2.5" points="${points}" />
    ${dots}
    ${xLabels}
  </svg>`;
}

function renderRadarChart(data, opts={}) {
  if (!data) return '';
  const visual = Number(data.visual) || 0;
  const auditory = Number(data.auditory) || 0;
  const kinesthetic = Number(data.kinesthetic) || 0;
  const readWrite = Number(data.read_write) || 0;
  const dims = [
    {key:'visual', label:'视觉型', value:visual},
    {key:'auditory', label:'听觉型', value:auditory},
    {key:'kinesthetic', label:'动觉型', value:kinesthetic},
    {key:'read_write', label:'读写型', value:readWrite}
  ];
  if (dims.every(d => d.value === 0)) {
    return `<p style="color:var(--sub);text-align:center;padding:20px;">暂无学习风格测评数据</p>`;
  }
  const size = opts.size || 220;
  const center = size / 2;
  const radius = size * 0.36;
  const max = 10;
  const levels = [0.33, 0.66, 1.0];
  const angleFor = i => (Math.PI * 2 * i) / 4 - Math.PI / 2;
  const pointFor = (value, i) => {
    const r = (value / max) * radius;
    const a = angleFor(i);
    return `${center + r * Math.cos(a)},${center + r * Math.sin(a)}`;
  };
  const labelPosFor = (i, dist) => {
    const a = angleFor(i);
    return {x: center + dist * Math.cos(a), y: center + dist * Math.sin(a)};
  };
  const gridPolys = levels.map(lv => {
    const pts = dims.map((_, i) => pointFor(max * lv, i)).join(' ');
    return `<polygon points="${pts}" fill="none" stroke="var(--border)" stroke-width="1" stroke-dasharray="2,2"/>`;
  }).join('');
  const axes = dims.map((_, i) => {
    const end = labelPosFor(i, radius);
    return `<line x1="${center}" y1="${center}" x2="${end.x}" y2="${end.y}" stroke="var(--border)" stroke-width="1"/>`;
  }).join('');
  const dataPts = dims.map((d, i) => pointFor(d.value, i)).join(' ');
  const labels = dims.map((d, i) => {
    const pos = labelPosFor(i, radius + 22);
    const anchor = i === 0 ? 'middle' : (i === 1 ? 'start' : (i === 2 ? 'middle' : 'end'));
    return `<text x="${pos.x}" y="${pos.y + 4}" text-anchor="${anchor}" font-size="12" fill="var(--text)">${d.label}</text>
            <text x="${pos.x}" y="${pos.y + 17}" text-anchor="${anchor}" font-size="11" fill="var(--accent)">${d.value}</text>`;
  }).join('');
  const caption = [];
  if (data.dominant) caption.push(`<strong>${data.dominant}</strong>`);
  if (data.auxiliary) caption.push(`辅助：${data.auxiliary}`);
  if (data.interpretation) caption.push(data.interpretation);
  const captionHtml = caption.length ? `<div style="font-size:.8em;color:var(--sub);text-align:center;margin-top:8px;line-height:1.5;">${caption.join(' · ')}</div>` : '';
  return `<div style="max-width:${size}px;margin:0 auto;">
    <svg viewBox="0 0 ${size} ${size}" style="width:100%;height:${size}px;">
      <rect width="${size}" height="${size}" fill="var(--card)" rx="6"/>
      ${gridPolys}
      ${axes}
      <polygon points="${dataPts}" fill="var(--accent)" fill-opacity="0.25" stroke="var(--accent)" stroke-width="2"/>
      ${dims.map((d, i) => {
        const p = pointFor(d.value, i);
        return `<circle cx="${p.split(',')[0]}" cy="${p.split(',')[1]}" r="3" fill="var(--accent)"/>`;
      }).join('')}
      ${labels}
    </svg>
    ${captionHtml}
  </div>`;
}

async function renderTeacherTimeline(studentId) {
  const div = document.getElementById('student-timeline');
  if (!div || !studentId) return;
  try {
    const r = await fetch('/api/students/' + studentId + '/timeline');
    if (!r.ok) { div.innerHTML = '<p style="color:var(--sub);">暂无时间轴</p>'; return; }
    const data = await r.json();
    const milestones = data.milestones || [];
    if (milestones.length === 0) {
      div.innerHTML = '<p style="color:var(--sub);">🌱 学习旅程刚刚开始</p>';
      return;
    }
    let html = '<div class="timeline" style="max-height:400px;overflow-y:auto;">';
    for (const m of milestones) {
      html += `<div class="tl-item">
        <div class="tl-dot">${m.icon}</div>
        <div class="tl-date">${m.date}</div>
        <div class="tl-title">${m.icon} ${m.title}</div>
        <div class="tl-desc">${m.description}</div>
      </div>`;
    }
    html += '</div>';
    div.innerHTML = html;
  } catch(e) {
    div.innerHTML = '<p style="color:var(--sub);">加载失败</p>';
  }
}

async function renderTeacherAchievementWall(studentId) {
  const div = document.getElementById('student-achievements-wall');
  if (!div || !studentId) return;
  try {
    const r = await fetch('/api/students/' + studentId + '/achievements');
    if (!r.ok) { div.innerHTML = '<p style="color:var(--sub);">暂无成就数据</p>'; return; }
    const data = await r.json();
    if (!data.all || data.all.length === 0) {
      div.innerHTML = '<p style="color:var(--sub);">暂无成就定义</p>'; return;
    }
    let html = `<p style="color:var(--sub);margin-bottom:10px;">已解锁 <strong>${data.earned_count}</strong> / ${data.total_count} 项成就</p>`;
    html += '<div style="display:grid;grid-template-columns:repeat(auto-fill, minmax(130px, 1fr));gap:8px;">';
    for (const a of data.all) {
      const earnedClass = a.earned ? 'ach-earned' : 'ach-locked';
      const pct = a.progress_pct || 0;
      html += `<div class="ach-card ${earnedClass}" title="${a.description}">
        <div class="ach-icon">${a.icon}</div>
        <div class="ach-title">${a.title}</div>
        <div class="ach-desc">${a.description}</div>`;
      if (a.earned) {
        html += `<div class="ach-date">${(a.earned_at||'').slice(0,10)}</div>`;
      } else {
        html += `<div class="ach-progress"><div class="ach-progress-bar" style="width:${pct}%;"></div></div>
          <div class="ach-progress-text">${a.current}/${a.threshold}</div>`;
      }
      html += '</div>';
    }
    html += '</div>';
    div.innerHTML = html;
  } catch(e) {
    div.innerHTML = '<p style="color:var(--sub);">成就加载失败</p>';
  }
}

function renderKnowledgeMastery(items, opts={}) {
  if (!items || items.length === 0) {
    return `<p style="color:var(--sub);text-align:center;">暂无知识点数据</p>`;
  }
  const rows = items.map(kp => {
    const rate = Number(kp.mastery_rate) || 0;
    const total = kp.total || kp.total_mistakes || 0;
    const mastered = kp.mastered !== undefined ? kp.mastered : (total - (kp.unmastered || 0));
    const unmastered = kp.unmastered !== undefined ? kp.unmastered : (total - mastered);
    const color = rate < 30 ? 'var(--red)' : (rate < 60 ? 'var(--accent)' : 'var(--green)');
    const countText = total > 0 ? `${mastered}/${total} 已掌握` : '';
    return `<div style="${opts.compact ? 'margin-bottom:8px;' : 'flex:1 1 240px;background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:10px;margin-bottom:8px;'}">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
        <span style="font-size:.85em;font-weight:600;${opts.compact ? '' : 'color:' + color + ';'}">${kp.knowledge_point}</span>
        <span style="font-size:.8em;color:var(--sub);">掌握率 <strong style="color:${color};">${rate}%</strong> ${countText ? '· ' + countText : ''}</span>
      </div>
      <div class="progress-bar" style="height:6px;"><div class="fill" style="width:${rate}%;background:${color};"></div></div>
    </div>`;
  }).join('');
  return opts.compact ? rows : `<div style="display:flex;flex-wrap:wrap;gap:8px;">${rows}</div>`;
}

function openScoreModal() {
  const sid = document.getElementById('analytics-student').value;
  if (!sid) return toast('请先选择学生', 'error');
  document.getElementById('score-student-id').value = sid;
  const name = document.getElementById('analytics-student').selectedOptions[0].text.split(' ')[0];
  document.getElementById('score-student-name').value = name;
  document.getElementById('score-value').value = '';
  document.getElementById('score-date').value = new Date().toISOString().slice(0,10);
  document.getElementById('score-note').value = '';
  document.getElementById('score-modal').classList.add('show');
}
function closeScoreModal() { document.getElementById('score-modal').classList.remove('show'); }
async function saveScore() {
  const studentId = document.getElementById('score-student-id').value;
  const score = parseFloat(document.getElementById('score-value').value);
  const date = document.getElementById('score-date').value;
  const note = document.getElementById('score-note').value;
  if (!studentId || isNaN(score)) return toast('请输入学生分数', 'error');

  const r = await fetch('/api/learning/score', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({student_id: parseInt(studentId), score, week_start: date, note})
  });
  if (r.ok) {
    toast('分数已录入');
    closeScoreModal();
    loadStudentAnalytics(studentId);
  } else {
    const d = await r.json(); toast(d.error || '保存失败', 'error');
  }
}

// ── AI Correction ──
let correctionState = { taskId: null, items: [], originalItems: [] };

function closeCorrectionModal() {
  document.getElementById('correction-modal').classList.remove('show');
  correctionState = { taskId: null, items: [], originalItems: [] };
}

async function openCorrectionPanel(taskId) {
  correctionState.taskId = taskId;
  document.getElementById('correction-task-id').value = taskId;
  document.getElementById('correction-reason').value = '';
  document.getElementById('correction-status').textContent = '加载中...';
  document.getElementById('correction-modal').classList.add('show');

  const [taskR, corrR] = await Promise.all([
    fetch('/api/tasks/' + taskId),
    fetch('/api/tasks/' + taskId + '/corrections')
  ]);
  const task = taskR.ok ? await taskR.json() : {};
  const existingCorrections = corrR.ok ? await corrR.json() : [];

  const r = await fetch('/api/tasks/' + taskId + '/correctables');
  if (!r.ok) {
    document.getElementById('correction-status').textContent = '加载失败';
    return toast('加载可纠错内容失败', 'error');
  }
  const data = await r.json();
  correctionState.items = data.items || [];
  correctionState.originalItems = JSON.parse(JSON.stringify(correctionState.items));

  const taskTypeLabel = task.task_type === 'onboarding' ? '入学诊断' : '周度服务';
  document.getElementById('correction-task-info').textContent = `#${taskId} · ${taskTypeLabel} · ${data.items ? data.items.length + ' 条内容' : '0 条'}`;

  renderCorrectionItems(existingCorrections);
  document.getElementById('correction-status').textContent = existingCorrections.length > 0
    ? `该任务已有 ${existingCorrections.length} 条纠错记录，可继续补充`
    : '请修改有问题的字段，未修改的字段不会提交';
}

function renderCorrectionItems(existingCorrections) {
  const container = document.getElementById('correction-items');
  container.innerHTML = '';

  if (!correctionState.items.length) {
    container.innerHTML = '<div style="color:var(--sub); text-align:center; padding:24px;">暂无可纠错内容</div>';
    return;
  }

  correctionState.items.forEach((item, idx) => {
    const fields = [];
    const isGrading = item.content_type === 'grading';

    if (isGrading) {
      fields.push({ key: 'is_correct', label: '批改结果', type: 'select', options: [['1','✅ 对'], ['0','❌ 错']], val: item.is_correct ? '1' : '0' });
      fields.push({ key: 'feedback', label: '批改解析', type: 'textarea', val: item.feedback || '' });
      fields.push({ key: 'correct_answer', label: '正确答案（参考）', type: 'text', val: item.correct_answer || '', readonly: true, muted: true });
    } else {
      fields.push({ key: 'question', label: '题干', type: 'textarea', val: item.question || '' });
      fields.push({ key: 'correct_answer', label: '正确答案', type: 'text', val: item.correct_answer || '' });
      fields.push({ key: 'explanation', label: '解析', type: 'textarea', val: item.explanation || '' });
      fields.push({ key: 'knowledge_points', label: '知识点（用逗号分隔）', type: 'text', val: Array.isArray(item.knowledge_points) ? item.knowledge_points.join(', ') : (item.knowledge_points || '') });
      fields.push({ key: 'difficulty', label: '难度（1-5）', type: 'number', val: item.difficulty != null ? item.difficulty : 2 });
      fields.push({ key: 'question_type', label: '题型', type: 'text', val: item.question_type || '' });
    }

    // Show existing corrections for this target
    const targetCorrs = existingCorrections.filter(c => c.target_id === item.target_id);
    const corrTags = targetCorrs.map(c => {
      const fieldLabels = {
        question:'题干', correct_answer:'答案', explanation:'解析', knowledge_points:'知识点',
        difficulty:'难度', question_type:'题型', is_correct:'批改', feedback:'解析'
      };
      return `<span class="badge" style="background:var(--accent-light); color:var(--accent); font-size:.75em;">${fieldLabels[c.target_field] || c.target_field}</span>`;
    }).join(' ');

    let html = `<div class="card" style="border:1px solid var(--border); border-radius:8px; padding:16px;" data-idx="${idx}">`;
    html += `<div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:12px;">`;
    html += `<div><strong>#${idx + 1} ${isGrading ? '批改结果' : '错题'}</strong> ${corrTags}</div>`;
    if (item.knowledge_points && item.knowledge_points.length) {
      html += `<div style="font-size:.8em; color:var(--sub);">${Array.isArray(item.knowledge_points) ? item.knowledge_points.join(' · ') : item.knowledge_points}</div>`;
    }
    html += `</div>`;

    if (isGrading && item.question) {
      html += `<div style="background:var(--bg); padding:10px 12px; border-radius:6px; margin-bottom:12px; font-size:.9em; color:var(--text);"><strong>题目：</strong>${escapeHtml(item.question)}</div>`;
      html += `<div style="font-size:.85em; color:var(--sub); margin-bottom:12px;">学生答案：${escapeHtml(item.user_answer || '（未识别）')}</div>`;
    }

    fields.forEach(f => {
      const id = `corr-${idx}-${f.key}`;
      html += `<div class="form-group" style="margin-bottom:10px;">`;
      html += `<label style="font-size:.85em; color:var(--sub);">${f.label}</label>`;
      if (f.type === 'textarea') {
        html += `<textarea id="${id}" data-key="${f.key}" rows="2" ${f.readonly ? 'readonly style="background:#f5f2ec;"' : ''}>${escapeHtml(String(f.val || ''))}</textarea>`;
      } else if (f.type === 'select') {
        html += `<select id="${id}" data-key="${f.key}">${f.options.map(o => `<option value="${o[0]}" ${String(f.val) === o[0] ? 'selected' : ''}>${o[1]}</option>`).join('')}</select>`;
      } else {
        html += `<input id="${id}" type="${f.type}" data-key="${f.key}" value="${escapeHtml(String(f.val || ''))}" ${f.readonly ? 'readonly style="background:#f5f2ec;"' : ''} ${f.muted ? 'style="color:var(--sub);"' : ''}>`;
      }
      html += `</div>`;
    });

    html += `</div>`;
    container.innerHTML += html;
  });
}

function escapeHtml(text) {
  if (text == null) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

async function submitCorrections() {
  const taskId = correctionState.taskId;
  if (!taskId) return;

  const corrections = [];
  correctionState.items.forEach((item, idx) => {
    const original = correctionState.originalItems[idx];
    const isGrading = item.content_type === 'grading';
    const fieldKeys = isGrading
      ? ['is_correct', 'feedback']
      : ['question', 'correct_answer', 'explanation', 'knowledge_points', 'difficulty', 'question_type'];

    fieldKeys.forEach(key => {
      const el = document.getElementById(`corr-${idx}-${key}`);
      if (!el) return;
      let newVal = el.value;
      let oldVal = original[key];

      if (key === 'difficulty') {
        newVal = parseInt(newVal) || 2;
        oldVal = oldVal != null ? oldVal : 2;
      } else if (key === 'knowledge_points') {
        newVal = newVal.split(',').map(s => s.trim()).filter(Boolean);
        oldVal = Array.isArray(oldVal) ? oldVal : [];
      } else if (key === 'is_correct') {
        newVal = newVal === '1';
        oldVal = !!oldVal;
      }

      // Compare normalized values
      const changed = JSON.stringify(newVal) !== JSON.stringify(oldVal);
      if (changed) {
        corrections.push({
          content_type: item.content_type,
          target_id: item.target_id,
          target_field: key,
          original_value: oldVal,
          corrected_value: newVal,
        });
      }
    });
  });

  if (!corrections.length) {
    return toast('没有修改任何字段', 'error');
  }

  const reason = document.getElementById('correction-reason').value.trim();
  corrections.forEach(c => { c.reason = reason; });

  document.getElementById('correction-status').textContent = '提交中...';
  const r = await fetch('/api/tasks/' + taskId + '/corrections', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ corrections })
  });
  if (r.ok) {
    const d = await r.json();
    toast(`已提交 ${d.created} 条纠错`);
    closeCorrectionModal();
    loadDashboard();
  } else {
    const d = await r.json();
    document.getElementById('correction-status').textContent = d.error || '提交失败';
    toast(d.error || '提交失败', 'error');
  }
}

// ── Init ──
loadDashboard();
</script>
</body>
</html>'''

