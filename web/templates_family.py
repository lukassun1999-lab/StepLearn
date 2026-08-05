# -*- coding: utf-8 -*-
"""家庭端页面模板（P2-12 自 app.py 拆出）。"""

STUDENT_PAGE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>学生学习中心</title>
<link rel="icon" href="data:,">
<style>
:root {
  --bg: #f8f7f4; --bg-alt: #f1f0ec; --card: #fff;
  --text: #1a1a1a; --text-alt: #33312c; --sub: #5a5a56; --mute: #8a8884;
  --accent: #e07b4b; --accent-hover: #d06a3a; --accent-light: #fef3ed;
  --green: #0f7b4e; --green-light: #effaf3;
  --blue: #4b8dc7; --blue-light: #eef5fb;
  --red: #d93a46; --red-light: #fef4f4;
  --border: #e8e6e1; --shadow-sm: 0 1px 2px rgba(0,0,0,.03);
  --shadow: 0 1px 3px rgba(0,0,0,.06), 0 2px 8px rgba(0,0,0,.02);
  --shadow-lg: 0 4px 24px rgba(0,0,0,.08);
  --radius: 10px;
}
* { margin:0; padding:0; box-sizing:border-box; }
@keyframes spin { to { transform:rotate(360deg); } }
body { font-family: ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; background:var(--bg); color:var(--text-alt); line-height:1.7; padding:16px; max-width:700px; margin:0 auto; font-size:1rem; }
.header { text-align:center; padding:28px 0 18px; border-bottom:2px solid var(--accent); margin-bottom:18px; }
.header h1 { font-size:1.55rem; color:var(--accent); font-weight:800; letter-spacing:.01em; }
.header .sub { color:var(--sub); font-size:.95rem; margin-top:6px; }
.summary { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-bottom:18px; }
.sum-item { background:var(--card); border:none; border-radius:12px; padding:16px 12px; text-align:center; box-shadow:var(--shadow); }
.sum-item .num { font-size:1.65rem; font-weight:800; color:var(--accent); }
.sum-item .label { font-size:.8rem; color:var(--sub); margin-top:2px; }
.tabs { display:flex; gap:4px; margin-bottom:18px; background:var(--card); padding:6px; border-radius:12px; box-shadow:var(--shadow); overflow-x:auto; -webkit-overflow-scrolling:touch; }
.tab { flex:1; padding:12px 10px; border:none; background:none; border-radius:8px; font-size:.92rem; font-weight:600; color:var(--sub); cursor:pointer; white-space:nowrap; transition:all .15s; border-bottom:2px solid transparent; }
.tab:hover { background:var(--bg-alt); color:var(--text); }
.tab.active { background:var(--accent-light); color:var(--accent); border-bottom-color:var(--accent); }
.page { display:none; }
.page.active { display:block; }
.card { background:var(--card); border:none; border-radius:12px; padding:22px; margin-bottom:14px; box-shadow:var(--shadow); }
.card h3 { font-size:1.12rem; margin-bottom:12px; font-weight:700; color:var(--text); }
.card .meta { color:var(--sub); font-size:.88rem; }
.btn { display:inline-block; padding:10px 20px; border:none; border-radius:var(--radius); cursor:pointer; font-size:.95rem; font-weight:600; text-decoration:none; transition:all .15s; min-height:44px; }
.btn:hover { transform:translateY(-1px); box-shadow:var(--shadow); }
.btn-primary { background:var(--accent); color:#fff; }
.btn-primary:hover { background:var(--accent-hover); }
.btn-green { background:var(--green); color:#fff; }
.btn-outline { background:var(--card); border:1px solid var(--border); color:var(--text); }
.btn-outline:hover { background:var(--bg-alt); }
.badge { display:inline-block; padding:4px 12px; border-radius:100px; font-size:.8rem; font-weight:600; }
.badge-green { background:var(--green-light); color:var(--green); }
.badge-red { background:var(--red-light); color:var(--red); }
.badge-blue { background:var(--blue-light); color:var(--blue); }
.empty { text-align:center; color:var(--sub); padding:44px 0; font-size:.95rem; }
.mistake-item { border-bottom:1px solid var(--border); padding:14px 0; }
.mistake-item:last-child { border-bottom:none; }
.mistake-q { font-weight:600; margin-bottom:8px; color:var(--text); font-size:1rem; line-height:1.6; }
.mistake-ans { font-size:.92rem; color:var(--sub); margin-bottom:6px; line-height:1.6; }
.calendar { display:grid; grid-template-columns:repeat(7,1fr); gap:6px; }
.cal-dow { text-align:center; font-size:.75rem; color:var(--mute); font-weight:600; padding:2px 0 4px; }
.cal-dow.sun, .cal-dow.sat { color:var(--red); }
.cal-nav { display:flex; align-items:center; justify-content:space-between; margin-bottom:10px; }
.cal-nav-btn { background:var(--card); border:1px solid var(--border); border-radius:8px; width:32px; height:32px; font-size:1rem; cursor:pointer; color:var(--sub); display:flex; align-items:center; justify-content:center; transition:all .2s; }
.cal-nav-btn:hover { border-color:var(--accent); color:var(--accent); }
.cal-nav-title { font-size:1.05rem; font-weight:700; }
.cal-day { position:relative; aspect-ratio:1; display:flex; flex-direction:column; align-items:center; justify-content:center; border-radius:8px; font-size:.85rem; background:var(--card); border:none; box-shadow:var(--shadow-sm); color:var(--sub); cursor:default; }
.cal-day.weekend { color:var(--red); }
.cal-day.holiday { color:var(--red); font-weight:700; background:var(--red-light); }
.cal-day.checked { background:var(--green-light); color:var(--green); font-weight:700; }
.cal-day.checked::after { content:''; position:absolute; bottom:3px; width:5px; height:5px; border-radius:50%; background:var(--green); }
.cal-day.today { box-shadow:0 0 0 2px var(--accent); }
.cal-day.other { opacity:.25; }
.cal-day .hol-name { position:absolute; bottom:1px; left:0; right:0; font-size:.5rem; color:var(--red); font-weight:600; line-height:1; white-space:nowrap; overflow:hidden; }
.week-row { display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid var(--border); font-size:.92rem; }
.week-row:last-child { border-bottom:none; }
.footer { text-align:center; color:var(--mute); font-size:.85rem; margin-top:36px; padding-top:18px; border-top:1px solid var(--border); }
.progress-bar { width:100%; height:10px; background:var(--border); border-radius:100px; overflow:hidden; margin:10px 0; }
.progress-bar .fill { height:100%; background:var(--accent); border-radius:100px; }
.kp-item { display:flex; justify-content:space-between; align-items:center; padding:10px 0; border-bottom:1px solid var(--border); font-size:.95rem; }
.kp-item:last-child { border-bottom:none; }
.toast { position:fixed; top:20px; left:50%; transform:translateX(-50%); padding:12px 24px; border-radius:var(--radius); color:#fff; font-size:.95rem; z-index:200; box-shadow:var(--shadow-lg); }
.toast-success { background:var(--green); }
/* Modal（修复：此前模板缺失弹窗 CSS，导致弹窗常驻页面） */
.modal-overlay { display:none; position:fixed; top:0;left:0;right:0;bottom:0; background:rgba(0,0,0,.25); backdrop-filter:blur(4px); -webkit-backdrop-filter:blur(4px); z-index:100; align-items:center; justify-content:center; animation:fadeIn .2s ease; }
.modal-overlay.show { display:flex; }
.modal { background:var(--card); border-radius:12px; padding:28px; max-width:560px; width:90%; max-height:80vh; overflow-y:auto; box-shadow:var(--shadow-lg); animation:modalEnter .25s ease; }
@keyframes modalEnter { from{opacity:0;transform:scale(.95) translateY(8px);} to{opacity:1;transform:scale(1) translateY(0);} }
/* Achievement Wall */
.ach-card { border-radius:10px; padding:12px 10px; text-align:center; transition:transform .2s; }
.ach-card:hover { transform:translateY(-2px); }
.ach-earned { background:linear-gradient(135deg,#fff9e6,#fef3c7); border:1.5px solid #f59e0b; }
.ach-locked { background:#f5f2ec; border:1.5px solid var(--border); opacity:.7; }
.ach-icon { font-size:1.8em; margin-bottom:4px; }
.ach-title { font-weight:700; font-size:.85em; margin-bottom:3px; color:var(--text); }
.ach-desc { font-size:.7em; color:var(--sub); line-height:1.3; margin-bottom:6px; }
.ach-date { font-size:.7em; color:var(--accent); margin-top:4px; }
.ach-progress { width:100%; height:5px; background:var(--border); border-radius:3px; overflow:hidden; margin-top:6px; }
.ach-progress-bar { height:100%; background:linear-gradient(90deg,var(--accent),var(--green)); border-radius:3px; transition:width .5s; }
.ach-progress-text { font-size:.65em; color:var(--sub); margin-top:2px; }
/* Learning Path Timeline */
.timeline { position:relative; padding-left:28px; }
.timeline::before { content:''; position:absolute; left:8px; top:0; bottom:0; width:3px; background:linear-gradient(to bottom, var(--accent), var(--green), var(--border)); border-radius:2px; }
.tl-item { position:relative; margin-bottom:20px; }
.tl-item:last-child { margin-bottom:0; }
.tl-dot { position:absolute; left:-24px; top:4px; width:16px; height:16px; border-radius:50%; background:var(--accent); border:3px solid #fff; box-shadow:0 1px 3px rgba(0,0,0,.2); z-index:1; display:flex; align-items:center; justify-content:center; font-size:.55em; }
.tl-date { font-size:.75em; color:var(--sub); margin-bottom:2px; }
.tl-title { font-weight:700; font-size:.9em; color:var(--text); }
.tl-desc { font-size:.8em; color:var(--sub); line-height:1.4; }
.tl-item.future .tl-dot { background:var(--border); border-color:#f5f2ec; }
.tl-item.future .tl-title { color:var(--sub); }
/* Metacognitive Review Form */
.review-input { width:100%; border:1px solid var(--border); border-radius:6px; padding:8px 10px; font-size:.85em; font-family:inherit; resize:vertical; box-sizing:border-box; }
.review-input:focus { outline:none; border-color:var(--accent); }
.mood-btn { width:40px; height:40px; border:1.5px solid var(--border); border-radius:50%; background:var(--card); font-size:1.1em; cursor:pointer; transition:all .2s; display:flex; align-items:center; justify-content:center; }
.mood-btn:hover { border-color:var(--accent); background:var(--accent-light); }
.mood-active { border-color:var(--accent); background:var(--accent); color:#fff; font-weight:700; }
</style>
</head>
<body>
<div class="header">
  <h1 id="stu-name">--</h1>
  <div class="sub" id="stu-info">--</div>
</div>

<div class="card" id="teacher-card" style="display:none;margin-bottom:16px;">
  <div style="display:flex;align-items:center;gap:14px;">
    <img id="teacher-avatar" src="" alt="" style="width:64px;height:64px;border-radius:50%;object-fit:cover;background:var(--border);display:none;">
    <div>
      <div style="font-weight:700;" id="teacher-name">--</div>
      <div style="font-size:.85em;color:var(--sub);" id="teacher-meta">--</div>
      <div style="font-size:.85em;color:var(--sub);margin-top:4px;" id="teacher-philosophy"></div>
      <div style="font-size:.85em;color:var(--accent);margin-top:4px;" id="teacher-contact"></div>
    </div>
  </div>
</div>

<div class="summary" id="summary">
  <div class="sum-item"><div class="num" id="sum-score">--</div><div class="label">当前分数</div></div>
  <div class="sum-item"><div class="num" id="sum-mistakes">--</div><div class="label">待攻克错题</div></div>
  <div class="sum-item"><div class="num" id="sum-due" style="color:var(--red);">--</div><div class="label">待复习</div></div>
  <div class="sum-item"><div class="num" id="sum-checkins">--</div><div class="label">本月打卡</div></div>
  <div class="sum-item"><div class="num" id="sum-achievements">--</div><div class="label">成就</div></div>
</div>

<div id="poster-btn-wrap" style="display:none;margin-bottom:16px;">
  <!-- 2026-08-04: referral entry removed from family home -->
  <!-- 海报按钮初始隐藏，仅在有学习数据时由 renderHome 显示 -->
  <button class="btn btn-green" style="width:100%;" onclick="generatePoster()">📸 生成海报</button>
</div>

<!-- Parent Upload Card -->
<div class="card" id="upload-card" style="margin-bottom:18px;border:2px dashed var(--border);text-align:center;cursor:pointer;transition:all .2s;" onclick="document.getElementById('parentFileInput').click()">
  <div style="font-size:3em;margin-bottom:10px;">📷</div>
  <div style="font-weight:800;font-size:1.15rem;margin-bottom:6px;">拍照上传试卷</div>
  <div style="font-size:.92rem;color:var(--sub);">拍一张孩子的英语试卷，AI自动分析错题</div>
  <div id="upload-progress" style="display:none;margin-top:14px;">
    <div class="progress-bar"><div class="fill" id="upload-fill" style="width:0%"></div></div>
    <div style="font-size:.9rem;color:var(--sub);margin-top:6px;" id="upload-status">上传中...</div>
  </div>
  <div id="upload-result" style="display:none;margin-top:14px;font-size:.95rem;color:var(--green);font-weight:700;line-height:1.6;"></div>
  <input type="file" id="parentFileInput" accept="image/*" capture="environment" multiple style="display:none;" onchange="handleParentUpload(this)">
</div>

<!-- Poster Modal -->
<div class="modal-overlay" id="poster-modal">
  <div class="modal" style="max-width:420px;">
    <h3>📸 学习成果海报</h3>
    <p class="meta" style="margin-bottom:12px;">已生成，保存图片即可分享到朋友圈</p>
    <iframe id="poster-frame" title="学习成果海报" style="width:100%;height:520px;border:1px solid var(--border);border-radius:10px;background:#fff;"></iframe>
    <div id="poster-link" style="margin:12px 0 16px;text-align:center;"></div>
    <div class="btn-group" style="justify-content:flex-end;">
      <button class="btn btn-primary" onclick="savePosterImage()">💾 另存为图片</button>
      <button class="btn btn-outline" onclick="closePosterModal()">关闭</button>
    </div>
  </div>
</div>

<div class="tabs">
  <button class="tab active" onclick="switchTab('home', event)">首页</button>
  <button class="tab" onclick="switchTab('practice', event)">练习</button>
  <button class="tab" onclick="switchTab('reports', event)">报告</button>
  <button class="tab" onclick="switchTab('timeline', event)">时间轴</button>
  <button class="tab" onclick="switchTab('mistakes', event)">成长记录</button>
  <button class="tab" onclick="switchTab('achievements', event)">成就墙</button>
  <button class="tab" onclick="switchTab('review', event)">复盘</button>
  <button class="tab" onclick="switchTab('checkin', event)">坚持日记</button>
  <button class="tab" onclick="switchTab('progress', event)">进度</button>
</div>

<div id="page-home" class="page active">
  <div id="home-stats" style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px;"></div>
  <!-- 2026-08-04: 首页重复上传入口已移除，顶部 upload-card 为唯一拍照上传入口 -->
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:16px;">
    <div onclick="switchTab('practice',null)" style="background:var(--card);border-radius:12px;padding:16px;text-align:center;cursor:pointer;">
      <div style="font-size:1.5rem;">📝</div><div style="font-size:.85rem;font-weight:600;margin-top:4px;">练习题</div>
    </div>
    <div onclick="switchTab('reports',null)" style="background:var(--card);border-radius:12px;padding:16px;text-align:center;cursor:pointer;">
      <div style="font-size:1.5rem;">📋</div><div style="font-size:.85rem;font-weight:600;margin-top:4px;">分析报告</div>
    </div>
    <div onclick="switchTab('mistakes',null)" style="background:var(--card);border-radius:12px;padding:16px;text-align:center;cursor:pointer;">
      <div style="font-size:1.5rem;">🌱</div><div style="font-size:.85rem;font-weight:600;margin-top:4px;">错题本</div>
    </div>
    <div onclick="switchTab('progress',null)" style="background:var(--card);border-radius:12px;padding:16px;text-align:center;cursor:pointer;">
      <div style="font-size:1.5rem;">📊</div><div style="font-size:.85rem;font-weight:600;margin-top:4px;">学习进度</div>
    </div>
  </div>
</div>

<div id="page-practice" class="page"></div>
<div id="page-reports" class="page"></div>
<div id="page-timeline" class="page"></div>
<div id="page-mistakes" class="page"></div>
<div id="page-achievements" class="page"></div>
<div id="page-review" class="page"></div>
<div id="page-checkin" class="page"></div>
<div id="page-progress" class="page"></div>

<div style="text-align:center;margin:24px 0;">
  <button class="btn btn-outline" onclick="requestDataDeletion()" style="font-size:.85em;">🗑️ 申请删除孩子学习数据</button>
  <p style="font-size:.75em;color:var(--sub);margin-top:8px;">依据个人信息保护法，家长可申请删除孩子数据，老师会尽快处理。</p>
</div>

<div class="footer">
  <p>拾阶而上 · AI 个性化学习 <span style="color:var(--mute);">v.{{version}}</span></p>
</div>

<script>
const CODE = '{{code}}';
let STUDENT_ID = null;

function toast(msg) {
  const t = document.createElement('div'); t.className='toast toast-success'; t.textContent=msg;
  document.body.appendChild(t); setTimeout(()=>t.remove(), 2000);
}

async function requestDataDeletion() {
  const reason = prompt('申请删除孩子学习数据\n请输入删除原因（可选）：') || '';
  if (!confirm('确定要提交删除申请吗？老师会尽快处理。')) return;
  const r = await fetch('/api/public/' + CODE + '/request-deletion', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({reason, requested_by: '家长'}),
  });
  if (r.ok) {
    toast('删除申请已提交');
  } else {
    toast('提交失败，请稍后重试');
  }
}

function switchTab(name, evt) {
  document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  // Support both click events and programmatic calls
  if (evt && evt.target) {
    evt.target.classList.add('active');
  } else {
    // Programmatic: find tab button by onclick pattern
    const tabBtn = document.querySelector(`.tab[onclick*="'${name}'"]`);
    if (tabBtn) tabBtn.classList.add('active');
    // Fallback: find by text content
    if (!tabBtn) {
      const allTabs = document.querySelectorAll('.tab');
      const labelMap = {home:'首页',practice:'练习',reports:'报告',timeline:'时间轴',mistakes:'成长记录',achievements:'成就墙',review:'复盘',checkin:'坚持日记',progress:'进度'};
      const label = labelMap[name] || name;
      for (const t of allTabs) { if (t.textContent.trim() === label) { t.classList.add('active'); break; } }
    }
  }
  document.getElementById('page-'+name).classList.add('active');
}

async function loadData() {
  const r = await fetch('/api/public/' + CODE);
  if (!r.ok) { document.body.innerHTML = '<h2 style="text-align:center;margin-top:80px;">链接无效或已过期</h2>'; return; }
  const d = await r.json();
  const s = d.student;

  STUDENT_ID = s.id;
  document.getElementById('stu-name').textContent = s.name + ' 的学习中心';
  document.getElementById('stu-info').textContent = `${s.grade} · ${s.school_type} · 英语 ${s.english_score||'?'}分${s.target_score?' → 目标 '+s.target_score+'分':''}`;

  // Render teacher / institution profile
  if (d.teacher && (d.teacher.teacher_name || d.teacher.institution_name)) {
    const t = d.teacher;
    const card = document.getElementById('teacher-card');
    card.style.display = 'block';
    const name = t.teacher_name || t.institution_name || '拾阶而上';
    document.getElementById('teacher-name').textContent = name;
    const metaParts = [];
    if (t.teaching_years) metaParts.push(t.teaching_years);
    if (t.specialty) metaParts.push(t.specialty);
    document.getElementById('teacher-meta').textContent = metaParts.join(' · ') || 'AI + 老师双师辅导';
    document.getElementById('teacher-philosophy').textContent = t.philosophy || '';
    document.getElementById('teacher-contact').textContent = t.contact_info || '';
    const avatar = document.getElementById('teacher-avatar');
    if (t.avatar_url) {
      avatar.src = t.avatar_url;
      avatar.style.display = 'block';
    }
  }
  document.getElementById('sum-score').textContent = s.english_score || '-';
  document.getElementById('sum-mistakes').textContent = d.mistakes_count;
  document.getElementById('sum-due').textContent = d.due_review_count || 0;
  // 本月打卡数（check_ins 是全量，需按当月过滤）
  const _t = new Date();
  const _ymPrefix = _t.getFullYear() + '-' + String(_t.getMonth()+1).padStart(2,'0');
  document.getElementById('sum-checkins').textContent = (d.check_ins||[]).filter(x=>x.startsWith(_ymPrefix)).length;

  // Load achievement count async
  fetch('/api/public/' + CODE + '/achievements').then(r=>r.json()).then(data=>{
    document.getElementById('sum-achievements').textContent = (data.earned_count || 0);
  }).catch(()=>{});

  renderHome(d);
  renderPractice();
  renderReports(d);
  renderTimeline();
  renderMistakes(d);
  renderAchievements();
  renderReview();
  renderCheckin(d);
  renderProgress(d);
}

// ── Home tab: dashboard summary + upload ──

function renderHome(d) {
  const remaining = d.mistakes_count || 0;
  const mastered = d.mastered_count || 0;
  const total = remaining + mastered;
  const checkins = (d.check_ins || []).length;
  const pct = total > 0 ? Math.round(mastered / total * 100) : 0;

  // 海报需学习数据支撑：新学生（无错题/无打卡/无报告）不展示首页海报按钮
  const hasLearningData = remaining + mastered + checkins + (d.reports ? d.reports.length : 0) > 0;
  const posterWrap = document.getElementById('poster-btn-wrap');
  if (posterWrap) posterWrap.style.display = hasLearningData ? 'block' : 'none';

  function statCard(icon, num, label) {
    return `<div style="flex:1;min-width:70px;background:var(--card);border-radius:10px;padding:12px 8px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.06);">
      <div style="font-size:1.3rem;">${icon}</div>
      <div style="font-size:1.3rem;font-weight:700;">${num}</div>
      <div style="font-size:.7rem;color:var(--sub);">${label}</div>
    </div>`;
  }

  let html = '<div style="display:flex;gap:8px;flex-wrap:wrap;">';
  html += statCard('🌱', remaining, '成长中');
  html += statCard('🌟', mastered, '已稳住');
  html += statCard('💪', checkins, '坚持天');
  html += '</div>';

  // Mastery bar
  if (total > 0) {
    html += `<div style="margin-top:12px;background:var(--card);border-radius:10px;padding:12px;">
      <div style="display:flex;justify-content:space-between;font-size:.8rem;margin-bottom:6px;">
        <span>成长进度</span><span style="font-weight:600;">${pct}%</span>
      </div>
      <div style="height:8px;background:var(--bg);border-radius:8px;overflow:hidden;">
        <div style="height:100%;width:${pct}%;background:var(--success,#0f7b4e);border-radius:8px;transition:width .5s;"></div>
      </div>
    </div>`;
  }

  document.getElementById('home-stats').innerHTML = html;
}

async function generatePoster() {
  const r = await fetch('/api/poster/' + CODE);
  if (!r.ok) { toast('海报生成失败'); return; }
  const d = await r.json();
  // 内嵌预览（srcdoc 直接渲染海报 HTML，无需登录态/下载头）
  document.getElementById('poster-frame').srcdoc = d.html || '';
  document.getElementById('poster-link').innerHTML = `
    <a href="/api/public/${CODE}/files/${d.file_id}/download" target="_blank" class="btn btn-outline" style="text-decoration:none;">↗ 打开完整海报</a>
  `;
  document.getElementById('poster-modal').classList.add('show');
}
function closePosterModal() { document.getElementById('poster-modal').classList.remove('show'); }

// 海报另存为图片：iframe(srcdoc 同源) → SVG foreignObject → canvas → PNG 下载
async function savePosterImage() {
  const frame = document.getElementById('poster-frame');
  const doc = frame.contentDocument || frame.contentWindow.document;
  if (!doc || !doc.body) { toast('海报尚未生成'); return; }
  try {
    // 等待内嵌图片加载完成
    await Promise.all(Array.from(doc.querySelectorAll('img')).map(img =>
      img.complete ? Promise.resolve() : new Promise(r => { img.onload = r; img.onerror = r; })
    ));
    const width = doc.body.scrollWidth;
    const height = doc.body.scrollHeight;
    if (!width || !height) { toast('海报内容为空'); return; }
    const styleHtml = Array.from(doc.head.querySelectorAll('style')).map(s => s.textContent).join('');
    const bodyHtml = new XMLSerializer().serializeToString(doc.body);
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">` +
      `<foreignObject width="100%" height="100%"><div xmlns="http://www.w3.org/1999/xhtml">` +
      `<style>${styleHtml}</style>${bodyHtml}</div></foreignObject></svg>`;
    const url = URL.createObjectURL(new Blob([svg], {type: 'image/svg+xml;charset=utf-8'}));
    const img = new Image();
    img.onload = () => {
      const scale = 2; // 2x 高清导出
      const canvas = document.createElement('canvas');
      canvas.width = width * scale;
      canvas.height = height * scale;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      const a = document.createElement('a');
      a.href = canvas.toDataURL('image/png');
      a.download = '学习海报.png';
      a.click();
      toast('海报已保存');
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      toast('图片生成失败，可点「打开完整海报」查看');
    };
    img.src = url;
  } catch(e) {
    toast('图片生成失败，可点「打开完整海报」查看');
  }
}

// ═══ Interactive Practice (P0) ═══
let practiceQuestions = [];
let practiceIndex = 0;
let practiceCorrect = 0;

async function renderPractice() {
  const div = document.getElementById('page-practice');
  div.innerHTML = '<div class="card"><div class="empty">加载练习题中...</div></div>';
  try {
    const r = await fetch('/api/public/' + CODE + '/practice');
    const data = await r.json();
    practiceQuestions = data.questions || [];
    practiceIndex = 0;
    practiceCorrect = 0;
    if (practiceQuestions.length === 0) {
      div.innerHTML = `<div class="card"><div class="empty">
        <div style="font-size:2em;margin-bottom:8px;">🎉</div>
        <p>暂无待练习题</p>
        <p class="meta" style="margin-top:4px;">上传试卷后，AI会自动生成针对你薄弱点的专属练习</p>
      </div></div>`;
      return;
    }
    renderPracticeQuestion();
    // Add PDF download button below the question card
    const pdfBtn = document.createElement('div');
    pdfBtn.style.cssText = 'text-align:center;margin-top:12px;';
    pdfBtn.innerHTML = `<a href="/api/public/${CODE}/exercise-pdf" class="btn btn-outline" style="font-size:.85em;text-decoration:none;">🖨️ 下载打印版 PDF</a>`;
    div.appendChild(pdfBtn);
  } catch(e) {
    div.innerHTML = '<div class="card"><div class="empty">加载失败，请刷新重试</div></div>';
  }
}

function renderPracticeQuestion() {
  const div = document.getElementById('page-practice');
  if (practiceIndex >= practiceQuestions.length) {
    div.innerHTML = `<div class="card" style="text-align:center;padding:32px;">
      <div style="font-size:2.5em;margin-bottom:12px;">${practiceCorrect >= practiceQuestions.length/2 ? '🌟' : '💪'}</div>
      <h3>本轮练习完成！</h3>
      <p style="margin:12px 0;font-size:1.1em;font-weight:700;color:var(--accent);">${practiceCorrect} / ${practiceQuestions.length} 正确</p>
      <p class="meta">${practiceCorrect >= practiceQuestions.length/2 ? '太棒了，继续保持！' : '没关系，错题已加入复习计划，下次会更好'}</p>
      <button class="btn btn-green" style="margin-top:16px;width:100%;" onclick="generatePoster()">📸 生成学习海报，分享这份进步</button>
      <button class="btn btn-primary" style="margin-top:10px;width:100%;" onclick="renderPractice()">再来一轮</button>
    </div>`;
    return;
  }
  const q = practiceQuestions[practiceIndex];
  const kpTag = (q.knowledge_points||[]).map(k=>`<span class="badge badge-blue" style="margin-right:4px;">${k}</span>`).join('');
  const OPTION_TYPES = ['单项选择','多项选择','选择题','完形填空'];
  const isOptionType = OPTION_TYPES.includes(q.question_type);
  const opts = q.options || [];
  let optionsHtml, submitLabel = '提交答案', submitAction = 'submitPracticeAnswer()';
  if (isOptionType && opts.length === 0) {
    // 有选项题型但选项缺失：提示 + 跳过，避免误渲染成填空输入框
    optionsHtml = `<div style="padding:14px 16px;margin:10px 0;background:var(--red-light);border-radius:10px;color:var(--red);font-size:.9rem;text-align:center;">⚠️ 本题选项加载失败，先跳过，继续练习</div>`;
    submitLabel = '跳过这道 →';
    submitAction = 'skipPracticeQuestion()';
  } else if (isOptionType) {
    optionsHtml = opts.map(o=>`
      <label class="practice-opt" data-key="${o.key}" onclick="selectOption(this,'${o.key}')" style="display:block;padding:14px 18px;margin:8px 0;border:1.5px solid var(--border);border-radius:10px;cursor:pointer;transition:all .15s;font-size:1rem;line-height:1.6;">
        <strong>${o.key}.</strong> ${o.text}
      </label>`).join('');
  } else {
    optionsHtml = `<input type="text" id="practice-text-answer" placeholder="输入你的答案" oninput="document.getElementById('practice-submit-btn').disabled = this.value.trim()===''" style="width:100%;padding:12px 16px;border:1.5px solid var(--border);border-radius:10px;font-size:1rem;margin:10px 0;">`;
  }

  div.innerHTML = `
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
        <span class="badge badge-green">第 ${practiceIndex+1}/${practiceQuestions.length} 题</span>
        <span style="font-size:.85em;color:var(--sub);">${q.question_type}</span>
      </div>
      <div style="margin-bottom:10px;">${kpTag}</div>
      <div style="font-weight:600;margin-bottom:16px;line-height:1.8;font-size:1.02rem;white-space:pre-wrap;">${q.question_text.replace(/[A-D]\.\s*.+?(?=\s*[A-D]\.|$)/g,'').trim()}</div>
      <div id="practice-options">${optionsHtml}</div>
      <button class="btn btn-primary" style="width:100%;margin-top:16px;" id="practice-submit-btn" onclick="${submitAction}" ${isOptionType && opts.length === 0 ? '' : 'disabled'}>${submitLabel}</button>
      <div id="practice-feedback" style="display:none;margin-top:16px;"></div>
    </div>`;
}

function skipPracticeQuestion() {
  practiceIndex++;
  selectedAnswer = '';
  renderPracticeQuestion();
}

let selectedAnswer = '';
function selectOption(el, key) {
  if (document.getElementById('practice-feedback').style.display !== 'none') return;
  document.querySelectorAll('.practice-opt').forEach(o=>{o.style.borderColor='var(--border)';o.style.background='';});
  el.style.borderColor = 'var(--accent)';
  el.style.background = 'var(--accent-light)';
  selectedAnswer = key;
  document.getElementById('practice-submit-btn').disabled = false;
}

async function submitPracticeAnswer() {
  const q = practiceQuestions[practiceIndex];
  const textInput = document.getElementById('practice-text-answer');
  const answer = selectedAnswer || (textInput ? textInput.value.trim() : '');
  if (!answer) { toast('请先作答再提交'); return; }

  document.getElementById('practice-submit-btn').disabled = true;
  document.getElementById('practice-submit-btn').textContent = '批改中...';

  try {
    const r = await fetch('/api/public/' + CODE + '/practice/submit', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question_id: q.id, answer: answer}),
    });
    const fb = await r.json();
    const fbDiv = document.getElementById('practice-feedback');
    fbDiv.style.display = 'block';

    if (fb.is_correct) {
      practiceCorrect++;
      fbDiv.innerHTML = `<div style="padding:16px;background:var(--green-light);border-radius:10px;border-left:4px solid var(--green);">
        <div style="font-weight:700;color:var(--green);margin-bottom:6px;font-size:1.05rem;">✅ 正确！</div>
        <div style="font-size:.95rem;color:var(--sub);line-height:1.7;">${fb.explanation||''}</div>
      </div>`;
      // Highlight correct option
      document.querySelectorAll('.practice-opt').forEach(o=>{
        if(o.dataset.key===fb.correct_answer){o.style.borderColor='var(--green)';o.style.background='var(--green-light)';}
      });
    } else {
      fbDiv.innerHTML = `<div style="padding:16px;background:var(--red-light);border-radius:10px;border-left:4px solid var(--red);">
        <div style="font-weight:700;color:var(--red);margin-bottom:6px;font-size:1.05rem;">❌ 不对哦</div>
        <div style="font-size:.95rem;margin-bottom:6px;"><strong>正确答案：${fb.correct_answer}</strong></div>
        <div style="font-size:.95rem;color:var(--sub);line-height:1.7;">${fb.explanation||''}</div>
      </div>`;
      document.querySelectorAll('.practice-opt').forEach(o=>{
        if(o.dataset.key===answer){o.style.borderColor='var(--red)';o.style.background='var(--red-light)';}
        if(o.dataset.key===fb.correct_answer){o.style.borderColor='var(--green)';o.style.background='var(--green-light)';}
      });
    }

    document.getElementById('practice-submit-btn').textContent = '下一题 →';
    document.getElementById('practice-submit-btn').disabled = false;
    document.getElementById('practice-submit-btn').onclick = ()=>{ practiceIndex++; selectedAnswer=''; renderPracticeQuestion(); };
  } catch(e) {
    toast('提交失败，请重试');
    document.getElementById('practice-submit-btn').disabled = false;
    document.getElementById('practice-submit-btn').textContent = '提交答案';
  }
}

// ═══ Parent Upload (P0) ═══
async function handleParentUpload(input) {
  const files = input.files;
  if (!files || files.length === 0) return;

  const progressDiv = document.getElementById('upload-progress');
  const resultDiv = document.getElementById('upload-result');
  const fillBar = document.getElementById('upload-fill');
  const statusText = document.getElementById('upload-status');
  progressDiv.style.display = 'block';
  resultDiv.style.display = 'none';
  fillBar.style.width = '30%';
  statusText.textContent = '上传中...';

  const formData = new FormData();
  for (let i = 0; i < files.length; i++) formData.append('file', files[i]);

  try {
    const r = await fetch('/api/public/' + CODE + '/upload', {method:'POST', body:formData});
    const data = await r.json();
    if (!r.ok) {
      statusText.textContent = data.error || '上传失败';
      fillBar.style.width = '0%';
      fillBar.style.background = 'var(--red)';
      return;
    }
    fillBar.style.width = '60%';
    statusText.textContent = 'AI正在分析错题...';
    pollTaskProgress(data.task_id);
  } catch(e) {
    statusText.textContent = '网络错误，请重试';
    fillBar.style.width = '0%';
  }
  input.value = '';
}

async function pollTaskProgress(taskId) {
  const fillBar = document.getElementById('upload-fill');
  const statusText = document.getElementById('upload-status');
  const resultDiv = document.getElementById('upload-result');
  let attempts = 0;
  const poll = async () => {
    attempts++;
    try {
      const r = await fetch('/api/public/' + CODE + '/task/' + taskId);
      const t = await r.json();
      if (t.status === 'done') {
        fillBar.style.width = '100%';
        statusText.textContent = '分析完成！';
        resultDiv.style.display = 'block';
        const out = t.output_data || {};
        const qCount = out.questions_count || 0;
        const mCount = out.mistakes_count || 0;
        if (mCount === 0) {
          resultDiv.textContent = '🎉 这份卷子没有识别到错题，掌握得不错！如需更多练习请联系老师';
        } else {
          resultDiv.textContent = qCount > 0
            ? `✅ 已识别 ${mCount} 道错题，生成 ${qCount} 道专属练习题，去「练习」tab 开始吧！`
            : `✅ 已识别 ${mCount} 道错题，练习题生成中，稍后刷新「练习」tab`;
        }
        renderPractice();
        return;
      } else if (t.status === 'failed') {
        statusText.textContent = '分析失败：' + (t.error_message||'未知错误').slice(0,60);
        fillBar.style.background = 'var(--red)';
        return;
      } else {
        fillBar.style.width = Math.min(60 + (t.progress||0)*0.35, 95) + '%';
        statusText.textContent = t.current_step || 'AI正在分析...';
        if (attempts < 600) {
          setTimeout(poll, 3000);
        } else {
          statusText.textContent = '仍在处理中，可稍后刷新页面查看结果（通常 5-10 分钟完成）';
        }
      }
    } catch(e) {
      if (attempts < 600) {
        setTimeout(poll, 5000);
      } else {
        statusText.textContent = '网络不稳定，结果会更新在「报告」和「练习」tab，可稍后再来看';
      }
    }
  };
  setTimeout(poll, 2000);
}

function renderReports(d) {
  const div = document.getElementById('page-reports');
  // Reports are loaded separately for backwards compatibility, or we can list approved tasks
  div.innerHTML = `
    <div class="card">
      <h3>📋 诊断报告</h3>
      <p class="meta">每次分析的报告都会保存在这里</p>
      <div id="reports-list"></div>
    </div>
  `;
  fetch('/api/public/' + CODE + '/reports').then(r=>r.json()).then(reports=>{
    const list = document.getElementById('reports-list');
    if (!reports || reports.length === 0) {
      list.innerHTML = '<div class="empty"><p>📭 暂无报告</p><p class="meta">上传试卷后自动生成</p></div>';
      return;
    }
    list.innerHTML = reports.map(r=>`
      <div style="margin-top:12px;padding:12px;background:var(--bg);border-radius:6px;">
        <div style="font-weight:600;font-size:.9rem;">${r.title || '学情分析报告'}</div>
        <div class="meta">${r.created_at.slice(0,10)} · ${r.mistakes_count}道错题 · ${r.weak_points_count}个薄弱点</div>
        <a href="/api/public/${CODE}/files/${r.report_file_id}/download" target="_blank" class="btn btn-primary" style="margin-top:8px;">📄 查看报告</a>
      </div>
    `).join('');
  }).catch(()=>{});
}

// 掌握状态助手（全局，供错题本/展开项共用）
function mistakeStatus(m) {
  const cc = m.consecutive_correct || 0;
  const stage = m.review_stage || 0;
  if (cc >= 2) return {icon: '🟢', label: '已掌握', color: 'var(--green)', bg: 'var(--green-light)'};
  if (stage >= 3) return {icon: '🟡', label: '在进步', color: 'var(--accent)', bg: 'var(--accent-light)'};
  return {icon: '🔴', label: '未攻克', color: 'var(--red)', bg: 'var(--red-light)'};
}

function renderMistakes(d) {
  const div = document.getElementById('page-mistakes');
  const total = (d.mistakes_count || 0) + (d.mastered_count || 0);
  const mastered = d.mastered_count || 0;
  const remaining = d.mistakes_count || 0;

  if (total === 0) {
    div.innerHTML = '<div class="card"><div class="empty">🎉 暂无错题记录，上传试卷后自动生成</div></div>';
    return;
  }

  // Progress bar (thinning visual)
  const pct = total > 0 ? Math.round(mastered / total * 100) : 0;
  div.innerHTML = `
    <div class="card" style="text-align:center;margin-bottom:16px;padding:24px;">
      <div style="font-size:1.2rem;font-weight:800;margin-bottom:10px;line-height:1.6;">
        你已攻克 <span style="color:var(--green);">${mastered}</span> 道错题，还剩 <span style="color:var(--accent);">${remaining}</span> 道在路上
      </div>
      <div class="progress-bar" style="height:14px;margin:12px 0;">
        <div class="fill" style="width:${pct}%;background:linear-gradient(90deg,var(--green),var(--accent));border-radius:100px;"></div>
      </div>
      <div style="font-size:.9rem;color:var(--sub);">错题本完成度 ${pct}% · 越薄越厉害</div>
    </div>
    <div id="mistake-books"><div class="card"><div class="empty">加载错题本中...</div></div></div>
  `;

  // 按分析日期分组的错题本（如「20260804错题本」），最新一次默认展开
  fetch('/api/public/' + CODE + '/mistake-books').then(r=>r.json()).then(data=>{
    const books = data.books || [];
    const booksDiv = document.getElementById('mistake-books');
    if (!booksDiv) return;
    if (books.length === 0) {
      booksDiv.innerHTML = '<div class="card"><div class="empty">🎉 暂无错题记录</div></div>';
      return;
    }
    const firstDate = books[0].date;
    booksDiv.innerHTML = books.map(book=>`
      <div class="card" style="margin-bottom:12px;padding:0;overflow:hidden;">
        <div style="display:flex;justify-content:space-between;align-items:center;padding:14px 16px;cursor:pointer;background:var(--bg);" onclick="toggleMistakeBook('${book.date}', this)">
          <h3 style="font-size:1.02rem;margin:0;">📚 ${book.label}</h3>
          <div>
            <span class="badge badge-blue" style="margin-right:6px;">${book.count} 道</span>
            <span class="book-arrow" style="font-size:.8em;color:var(--sub);">${book.date === firstDate ? '▼' : '▶'}</span>
          </div>
        </div>
        <div id="book-${book.date}" style="display:${book.date === firstDate ? 'block' : 'none'};padding:12px 16px;">
          ${book.mistakes.map(m=>mistakeItemHtml(m)).join('')}
        </div>
      </div>
    `).join('');
  }).catch(()=>{
    const booksDiv = document.getElementById('mistake-books');
    if (booksDiv) booksDiv.innerHTML = '<div class="card"><div class="empty">加载失败，请刷新重试</div></div>';
  });

  div.innerHTML += `
    <div style="margin-top:14px;text-align:center;">
      <button class="btn btn-primary" style="width:100%;" onclick="switchTab('practice', event)">🚀 开始练习</button>
    </div>
  `;
}

// 单个错题卡片：题目 + 学生作答 + 正确答案 + 解析（原封不动展示）
function mistakeItemHtml(m) {
  const st = mistakeStatus(m);
  const qtype = m.question_type ? `<span class="badge" style="background:var(--bg);color:var(--sub);">${m.question_type}</span>` : '';
  return `
    <div class="mistake-item" style="border-left:3px solid ${st.color};padding-left:12px;margin:12px 0;">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap;">
        <span>${st.icon}</span>
        <span class="badge" style="background:${st.bg};color:${st.color};">${st.label}</span>
        ${qtype}
      </div>
      <div style="font-weight:600;line-height:1.7;white-space:pre-wrap;">${m.question || '（题目未记录）'}</div>
      <div style="margin-top:8px;">
        <div style="background:var(--red-light);border-radius:8px;padding:8px 12px;margin-bottom:6px;">
          <span style="font-size:.72rem;color:var(--red);font-weight:600;">✗ 你的作答：</span>
          <span style="font-size:.9rem;">${m.user_answer || '（未作答）'}</span>
        </div>
        <div style="background:var(--green-light);border-radius:8px;padding:8px 12px;">
          <span style="font-size:.72rem;color:var(--green);font-weight:600;">✓ 正确答案：</span>
          <span style="font-size:.9rem;font-weight:600;">${m.correct_answer || '-'}</span>
        </div>
        ${m.explanation ? `<div style="background:var(--accent-light);border-radius:8px;padding:8px 12px;margin-top:6px;font-size:.85rem;line-height:1.7;">📖 ${m.explanation}</div>` : ''}
      </div>
      <div style="margin-top:8px;">
        <button class="btn btn-green" style="font-size:.8rem;padding:6px 12px;min-height:34px;" onclick="masterMistake(${m.id})">✅ 已掌握</button>
        <button class="btn btn-primary" style="font-size:.8rem;padding:6px 12px;min-height:34px;margin-left:6px;" onclick="goPractice()">📝 去练习</button>
      </div>
    </div>`;
}

// 展开/收起某日错题本
function toggleMistakeBook(bookDate, el) {
  const body = document.getElementById('book-' + bookDate);
  if (!body) return;
  const open = body.style.display !== 'none';
  body.style.display = open ? 'none' : 'block';
  const arrow = el.querySelector('.book-arrow');
  if (arrow) arrow.textContent = open ? '▶' : '▼';
}

// 去练习：跳转练习 tab（练习题基于未掌握错题生成，即时反馈并更新掌握度）
function goPractice() {
  switchTab('practice', null);
  setTimeout(() => toast('已进入练习——做完即时反馈，连续答对 2 次即掌握'), 500);
}

async function masterMistake(id) {
  const r = await fetch('/api/mistakes/' + id + '/master', {method:'POST'});
  if (r.ok) { toast('已标记掌握'); loadData(); }
  else toast('操作失败');
}

async function renderTimeline() {
  const div = document.getElementById('page-timeline');
  div.innerHTML = '<div class="card"><p style="text-align:center;color:var(--sub);">加载中...</p></div>';
  try {
    const r = await fetch('/api/public/' + CODE + '/timeline');
    if (!r.ok) { div.innerHTML = '<div class="card"><div class="empty">暂无时间轴数据</div></div>'; return; }
    const data = await r.json();
    const milestones = data.milestones || [];
    if (milestones.length === 0) {
      div.innerHTML = '<div class="card"><div class="empty">🌱 学习之旅刚刚开始，完成首次诊断后将出现第一条里程碑。</div></div>';
      return;
    }
    let html = '<div class="card"><h3>🛤️ 学习路径</h3><p class="meta" style="margin-bottom:16px;">每一步成长都值得被记录</p><div class="timeline">';
    for (const m of milestones) {
      html += `<div class="tl-item">
        <div class="tl-dot">${m.icon}</div>
        <div class="tl-date">${m.date}</div>
        <div class="tl-title">${m.icon} ${m.title}</div>
        <div class="tl-desc">${m.description}</div>
      </div>`;
    }
    html += '</div></div>';
    div.innerHTML = html;
  } catch(e) {
    div.innerHTML = '<div class="card"><div class="empty">时间轴加载失败</div></div>';
  }
}

let currentReview = null;

async function renderReview() {
  const div = document.getElementById('page-review');
  div.innerHTML = '<div class="card"><p style="text-align:center;color:var(--sub);">加载中...</p></div>';
  try {
    const r = await fetch('/api/public/' + CODE + '/review');
    if (!r.ok) { div.innerHTML = '<div class="card"><div class="empty">暂无复盘数据</div></div>'; return; }
    const data = await r.json();
    currentReview = data.review;
    const review = data.review || {};
    const tpl = review.template_questions || {};
    const childQs = tpl.child_reflection || [];
    const parentQs = tpl.parent_observation || [];
    const childAns = review.child_answers || {};
    const parentAns = review.parent_answers || {};
    const isSubmitted = review.status === 'submitted';

    let formHtml = '';

    // Child reflection section
    formHtml += `<div style="margin-bottom:16px;">
      <h4 style="margin-bottom:8px;">🙋 孩子反思区</h4>
      <p class="meta" style="margin-bottom:10px;">请孩子诚实回答以下问题：</p>`;
    childQs.forEach((q, i) => {
      const val = childAns[q] || '';
      formHtml += `<div class="form-group">
        <label>${i+1}. ${q}</label>
        <textarea class="review-input" data-child="${_escapeHtml(q)}" rows="2" placeholder="写下你的想法..." ${isSubmitted?'readonly':''} style="${isSubmitted?'background:#f5f2ec;':''}">${_escapeHtml(val)}</textarea>
      </div>`;
    });
    // Child mood
    formHtml += `<div class="form-group">
      <label>😊 这周学习心情（1-5分）</label>
      <div style="display:flex;gap:8px;">${[1,2,3,4,5].map(n =>
        `<button class="mood-btn ${review.child_mood===n?'mood-active':''}" onclick="setMood('child',${n})" ${isSubmitted?'disabled':''}>${n}</button>`
      ).join('')}</div>
    </div>`;
    // Child note
    formHtml += `<div class="form-group">
      <label>还有什么想说的话</label>
      <textarea class="review-input" id="child-note" rows="2" placeholder="自由发挥..." ${isSubmitted?'readonly':''} style="${isSubmitted?'background:#f5f2ec;':''}">${_escapeHtml(review.child_note||'')}</textarea>
    </div></div>`;

    // Parent observation section
    formHtml += `<div style="margin-bottom:16px;">
      <h4 style="margin-bottom:8px;">👨‍👩‍👧 家长观察区</h4>
      <p class="meta" style="margin-bottom:10px;">请家长从观察者角度回答：</p>`;
    parentQs.forEach((q, i) => {
      const val = parentAns[q] || '';
      formHtml += `<div class="form-group">
        <label>${i+1}. ${q}</label>
        <textarea class="review-input" data-parent="${_escapeHtml(q)}" rows="2" placeholder="写下你的观察..." ${isSubmitted?'readonly':''} style="${isSubmitted?'background:#f5f2ec;':''}">${_escapeHtml(val)}</textarea>
      </div>`;
    });
    formHtml += `<div class="form-group">
      <label>😊 家长感受（1-5分）</label>
      <div style="display:flex;gap:8px;">${[1,2,3,4,5].map(n =>
        `<button class="mood-btn ${review.parent_mood===n?'mood-active':''}" onclick="setMood('parent',${n})" ${isSubmitted?'disabled':''}>${n}</button>`
      ).join('')}</div>
    </div>`;
    formHtml += `<div class="form-group">
      <label>家长备注</label>
      <textarea class="review-input" id="parent-note" rows="2" placeholder="想对老师说的话..." ${isSubmitted?'readonly':''} style="${isSubmitted?'background:#f5f2ec;':''}">${_escapeHtml(review.parent_note||'')}</textarea>
    </div></div>`;

    // Submit button or submitted badge
    if (isSubmitted) {
      formHtml += `<div style="text-align:center;padding:12px;background:#e8f5e9;border-radius:8px;color:var(--green);font-weight:600;">✅ 本周复盘已提交 · ${(review.submitted_at||'').slice(0,10)}</div>`;
    } else {
      formHtml += `<button class="btn btn-primary" style="width:100%;" onclick="submitReview()">📝 提交本周复盘</button>`;
    }

    // History
    const history = data.history || [];
    let histHtml = '';
    if (history.length > 1) {
      histHtml = '<div style="margin-top:20px;"><h4 style="margin-bottom:10px;">📋 历史复盘</h4>';
      history.forEach(h => {
        if (h.week_start === review.week_start) return;
        histHtml += `<div style="background:var(--bg);border-radius:6px;padding:10px;margin-bottom:8px;">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <span style="font-weight:600;">📅 ${h.week_start} 周</span>
            <span style="font-size:.8em;color:${h.status==='submitted'?'var(--green)':'var(--sub)'};">${h.status==='submitted'?'已提交':'草稿'}</span>
          </div>`;
        if (h.child_mood) histHtml += `<span style="font-size:.8em;">孩子心情：${'⭐'.repeat(h.child_mood)}</span> `;
        if (h.parent_mood) histHtml += `<span style="font-size:.8em;">家长感受：${'⭐'.repeat(h.parent_mood)}</span>`;
        histHtml += '</div>';
      });
      histHtml += '</div>';
    }

    div.innerHTML = `<div class="card"><h3>🧠 每周元认知复盘</h3>
      <p class="meta" style="margin-bottom:16px;">${review.week_start} 周 · 反思让学习更深刻</p>
      ${formHtml}
      ${histHtml}
    </div>`;
  } catch(e) {
    div.innerHTML = '<div class="card"><div class="empty">复盘加载失败</div></div>';
  }
}

function setMood(type, value) {
  currentReview[type + '_mood'] = value;
  document.querySelectorAll('.mood-btn').forEach(b => b.classList.remove('mood-active'));
  event.target.classList.add('mood-active');
}

async function submitReview() {
  if (!currentReview) return;
  const childAns = {};
  document.querySelectorAll('[data-child]').forEach(el => {
    childAns[el.dataset.child] = el.value;
  });
  const parentAns = {};
  document.querySelectorAll('[data-parent]').forEach(el => {
    parentAns[el.dataset.parent] = el.value;
  });
  const body = {
    week_start: currentReview.week_start,
    child_answers: childAns,
    parent_answers: parentAns,
    child_mood: currentReview.child_mood,
    parent_mood: currentReview.parent_mood,
    child_note: document.getElementById('child-note')?.value || '',
    parent_note: document.getElementById('parent-note')?.value || '',
  };
  const r = await fetch('/api/public/' + CODE + '/review', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  if (r.ok) {
    toast('复盘已提交');
    renderReview();
  } else {
    toast('提交失败，请重试');
  }
}

function _escapeHtml(s) {
  if (!s) return '';
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

async function renderAchievements() {
  const div = document.getElementById('page-achievements');
  div.innerHTML = '<div class="card"><p style="text-align:center;color:var(--sub);">加载中...</p></div>';
  try {
    const r = await fetch('/api/public/' + CODE + '/achievements');
    if (!r.ok) { div.innerHTML = '<div class="card"><div class="empty">暂无成就数据</div></div>'; return; }
    const data = await r.json();
    const earned = data.earned_count || 0;
    const total = data.total_count || 0;

    let html = `<div class="card">
      <h3>🏆 成就墙 <span style="font-size:.7em;color:var(--sub);font-weight:normal;">${earned}/${total} 已解锁</span></h3>
      <div style="display:grid;grid-template-columns:repeat(auto-fill, minmax(140px, 1fr));gap:10px;margin-top:12px;">`;

    for (const a of data.all || []) {
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
      html += `</div>`;
    }

    html += `</div></div>`;
    div.innerHTML = html;
  } catch(e) {
    div.innerHTML = '<div class="card"><div class="empty">成就加载失败</div></div>';
  }
}

// 2026 年法定节假日（国务院办公厅通知）
const HOLIDAY_RANGES = [
  ['2026-01-01','2026-01-03','元旦'],
  ['2026-02-15','2026-02-23','春节'],
  ['2026-04-04','2026-04-06','清明'],
  ['2026-05-01','2026-05-05','劳动节'],
  ['2026-06-19','2026-06-21','端午'],
  ['2026-09-25','2026-09-27','中秋'],
  ['2026-10-01','2026-10-07','国庆'],
];
const HOLIDAY_MAP = (()=>{
  const m = {};
  for (const [s,e,n] of HOLIDAY_RANGES){
    const d = new Date(s+'T00:00:00'), end = new Date(e+'T00:00:00');
    while (d <= end){ m[d.toISOString().slice(0,10)] = n; d.setDate(d.getDate()+1); }
  }
  return m;
})();

let checkinYM = null;          // 当前展示的年月 {y,m}，null=本月
let CHECKIN_DATA = null;       // 打卡数据缓存，供月份切换时渲染

function _pad2(n){ return String(n).padStart(2,'0'); }
function _fmtYMD(y,m,d){ return y + '-' + _pad2(m) + '-' + _pad2(d); }
function _localToday(){ const t=new Date(); return _fmtYMD(t.getFullYear(), t.getMonth()+1, t.getDate()); }

function renderCheckin(d) {
  CHECKIN_DATA = d;
  const div = document.getElementById('page-checkin');
  const today = new Date();
  const ty = today.getFullYear(), tm = today.getMonth()+1;
  const y = checkinYM ? checkinYM.y : ty;
  const m = checkinYM ? checkinYM.m : tm;
  const checkedSet = new Set(d.check_ins || []);
  const todayStr = _localToday();

  const ymPrefix = y + '-' + _pad2(m);
  const monthChecked = (d.check_ins||[]).filter(x=>x.startsWith(ymPrefix)).length;

  // 周一起始：getDay() 日0~六6 → (getDay()+6)%7 = 周一0~周日6
  const firstDow = (new Date(y, m-1, 1).getDay() + 6) % 7;
  const daysInMonth = new Date(y, m, 0).getDate();

  const dowHtml = ['一','二','三','四','五','六','日']
    .map((n,i)=>`<div class="cal-dow ${i>=5?'sun':''}">${n}</div>`).join('');

  const cells = [];
  for (let i=0;i<firstDow;i++) cells.push('<div class="cal-day other"></div>');
  for (let day=1; day<=daysInMonth; day++){
    const dateStr = _fmtYMD(y,m,day);
    const hol = HOLIDAY_MAP[dateStr] || '';
    const dow = (new Date(y, m-1, day).getDay() + 6) % 7;
    const isChecked = checkedSet.has(dateStr);
    const cls = ['cal-day',
      isChecked?'checked':'',
      dow>=5?'weekend':'',
      hol?'holiday':'',
      dateStr===todayStr?'today':''
    ].filter(Boolean).join(' ');
    const holLabel = hol ? `<div class="hol-name">${hol}</div>` : '';
    cells.push(`<div class="${cls}" title="${dateStr}${hol?' · '+hol:''}${isChecked?' · 已打卡':''}">${day}${holLabel}</div>`);
  }

  const canNext = !(y===ty && m===tm);
  div.innerHTML = `
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <h3>📅 打卡日历</h3>
        <span class="meta">本月打卡 <strong>${monthChecked}</strong> 天</span>
      </div>
      <div class="cal-nav" style="margin-top:10px;">
        <button class="cal-nav-btn" onclick="shiftCheckinMonth(-1)" title="上个月">◀</button>
        <div class="cal-nav-title">${y}年${m}月</div>
        <button class="cal-nav-btn" onclick="shiftCheckinMonth(1)" title="下个月" ${canNext?'':'disabled'} style="${canNext?'':'opacity:.3;cursor:default;'}">▶</button>
      </div>
      <div class="calendar">
        ${dowHtml}
        ${cells.join('')}
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;">
        <span style="font-size:.78rem;color:var(--mute);">🟢 已打卡 · 🔴 节假日</span>
        <button class="btn ${checkedSet.has(todayStr)?'btn-outline':'btn-green'}" onclick="doCheckIn()" ${checkedSet.has(todayStr)?'disabled':''}>${checkedSet.has(todayStr)?'今日已打卡':'今日打卡'}</button>
      </div>
    </div>
  `;
}

function shiftCheckinMonth(delta) {
  const today = new Date();
  const ty = today.getFullYear(), tm = today.getMonth()+1;
  const y = checkinYM ? checkinYM.y : ty;
  const m = checkinYM ? checkinYM.m : tm;
  let ny = y, nm = m + delta;
  if (nm < 1){ nm = 12; ny--; }
  if (nm > 12){ nm = 1; ny++; }
  // 不允许切到未来月份
  if (ny > ty || (ny === ty && nm > tm)) return;
  checkinYM = {y: ny, m: nm};
  if (CHECKIN_DATA) renderCheckin(CHECKIN_DATA);
}

async function doCheckIn() {
  const r = await fetch('/api/checkin', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({access_code: CODE, content: '今日学习打卡'})
  });
  if (r.ok) { toast('打卡成功'); loadData(); }
  else toast('打卡失败');
}

function renderProgress(d) {
  const div = document.getElementById('page-progress');

  // Score trend mini chart
  let chartHtml = '<p class="meta">暂无分数记录</p>';
  if (d.scores && d.scores.length > 0) {
    const values = d.scores.map(s=>s.score);
    const labels = d.scores.map(s=>s.created_at.slice(5,10));
    chartHtml = renderSvgChart(labels, values, d.student.target_score);
  }

  // Weak points
  const kpHtml = renderKnowledgeMastery(d.weak_points, {compact: true});

  // Weekly activity
  let weekHtml = '<p class="meta">暂无周度记录</p>';
  if (d.weekly_activity && d.weekly_activity.length > 0) {
    weekHtml = d.weekly_activity.map(w=>`
      <div class="week-row">
        <span>${w.week_start} 周</span>
        <span>${w.exercises_graded?'✅ 已完成':'⏳ 进行中'}</span>
      </div>
    `).join('');
  }

  // Learning style radar
  let lsHtml = '';
  if (d.learning_style) {
    lsHtml = `<div class="card">
      <h3>🧠 学习风格画像</h3>
      <div style="max-width:260px;margin:0 auto;">${renderRadarChart(d.learning_style, {size: 220})}</div>
    </div>`;
  }

  div.innerHTML = `
    ${lsHtml}
    <div class="card">
      <h3>📈 分数趋势</h3>
      ${chartHtml}
    </div>
    <div class="card">
      <h3>🔥 薄弱知识点</h3>
      ${kpHtml}
    </div>
    <div class="card">
      <h3>🗓️ 周度完成情况</h3>
      ${weekHtml}
    </div>
  `;
}

function renderKnowledgeMastery(weakPoints, opts) {
  // 薄弱知识点掌握度条（compact 模式，进度 tab 使用）
  if (!weakPoints || weakPoints.length === 0) return '<p class="meta">暂无薄弱点数据</p>';
  return weakPoints.map(w => {
    const m = Number(w.mastery_rate) || 0;
    const color = m < 30 ? 'var(--red)' : (m < 60 ? '#e6a23c' : 'var(--green)');
    return `<div style="margin-bottom:10px;">
      <div style="display:flex;justify-content:space-between;font-size:.9rem;margin-bottom:4px;">
        <span>${w.knowledge_point || '未知知识点'}</span><span style="color:var(--sub);">${Math.round(m)}%</span>
      </div>
      <div style="height:8px;background:var(--bg);border-radius:6px;overflow:hidden;">
        <div style="height:100%;width:${Math.min(100, Math.max(0, m))}%;background:${color};border-radius:6px;"></div>
      </div>
    </div>`;
  }).join('');
}

function renderRadarChart(ls, opts) {
  // 学习风格四维雷达图（visual/auditory/kinesthetic/read_write，0-10）
  const size = (opts && opts.size) || 220;
  const R = size / 2 - 26, cx = size / 2, cy = size / 2;
  const dims = ['visual', 'auditory', 'kinesthetic', 'read_write'];
  const labels = ['视觉', '听觉', '动觉', '读写'];
  const angles = [0, 90, 180, 270].map(a => a * Math.PI / 180);
  const pts = dims.map((k, i) => {
    const v = Math.max(0, Math.min(10, Number(ls[k]) || 0)) / 10;
    return [cx + Math.sin(angles[i]) * R * v, cy - Math.cos(angles[i]) * R * v];
  });
  const polygon = pts.map(p => p.join(',')).join(' ');
  const axisLines = angles.map((a, i) =>
    `<line x1="${cx}" y1="${cy}" x2="${cx + Math.sin(a) * R}" y2="${cy - Math.cos(a) * R}" stroke="#e5e0d5" stroke-width="1"/>`
  ).join('');
  const labelHtml = labels.map((l, i) =>
    `<text x="${cx + Math.sin(angles[i]) * (R + 20)}" y="${cy - Math.cos(angles[i]) * (R + 20)}" text-anchor="middle" font-size="12" fill="#6b6b6b">${l}</text>`
  ).join('');
  return `<svg viewBox="0 0 ${size} ${size}" style="width:100%;max-width:${size}px;height:auto;">
    ${axisLines}
    <polygon points="${polygon}" fill="rgba(224,123,75,.25)" stroke="#e07b4b" stroke-width="2"/>
    ${labelHtml}
  </svg>`;
}

function renderSvgChart(labels, values, target) {
  const width = 600, height = 180, padding = 30;
  const chartW = width - padding * 2, chartH = height - padding * 2;
  const maxVal = Math.max(...values, target || 0, 1);
  const minVal = Math.min(...values, 0);
  const range = maxVal - minVal || 1;
  const points = values.map((v,i)=> {
    const x = padding + (i/(values.length-1||1))*chartW;
    const y = height - padding - ((v-minVal)/range)*chartH;
    return `${x},${y}`;
  }).join(' ');
  const dots = values.map((v,i)=> {
    const x = padding + (i/(values.length-1||1))*chartW;
    const y = height - padding - ((v-minVal)/range)*chartH;
    return `<circle cx="${x}" cy="${y}" r="4" fill="var(--accent)" stroke="#fff" stroke-width="2"/>
            <text x="${x}" y="${y-10}" text-anchor="middle" font-size="10" fill="var(--sub)">${v}</text>`;
  }).join('');
  const xlabs = labels.map((l,i)=> {
    const x = padding + (i/(labels.length-1||1))*chartW;
    return `<text x="${x}" y="${height-padding+16}" text-anchor="middle" font-size="10" fill="var(--sub)">${l}</text>`;
  }).join('');
  let targetLine = '';
  if (target) {
    const y = height - padding - ((target-minVal)/range)*chartH;
    targetLine = `<line x1="${padding}" y1="${y}" x2="${width-padding}" y2="${y}" stroke="var(--green)" stroke-dasharray="4,4"/>
                  <text x="${width-padding}" y="${y-5}" text-anchor="end" font-size="10" fill="var(--green)">目标 ${target}</text>`;
  }
  return `<svg viewBox="0 0 ${width} ${height}" style="width:100%;height:${height}px;">
    <rect width="${width}" height="${height}" fill="var(--card)"/>
    <line x1="${padding}" y1="${height-padding}" x2="${width-padding}" y2="${height-padding}" stroke="var(--border)"/>
    <line x1="${padding}" y1="${padding}" x2="${padding}" y2="${height-padding}" stroke="var(--border)"/>
    ${targetLine}
    <polyline fill="none" stroke="var(--accent)" stroke-width="2.5" points="${points}"/>
    ${dots}
    ${xlabs}
  </svg>`;
}

// Auto-switch to tab from URL hash (e.g. /s/xxx#mistakes)
if (window.location.hash) {
  const hashTab = window.location.hash.slice(1);
  const validTabs = ['home','practice','reports','timeline','mistakes','achievements','review','checkin','progress'];
  if (validTabs.includes(hashTab)) {
    setTimeout(() => switchTab(hashTab), 500);
  }
}
loadData();
</script>
</body>
</html>'''


PARENT_PAGE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>AI 学情体检</title>
<link rel="icon" href="data:,">
<style>
  :root {
    --bg: #f8f7f4; --card: #ffffff; --text: #1a1a1a;
    --sub: #6b6b6b; --mute: #9b9b9b; --accent: #e07b4b;
    --accent-hover: #d06a3a; --accent-light: #fef3ed;
    --green: #0f7b4e; --green-light: #effaf3;
    --red: #d93a46; --red-light: #fef4f4;
    --blue: #4b8dc7; --blue-light: #eef5fb;
    --border: #e8e6e1;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
@keyframes spin { to { transform:rotate(360deg); } }
  body {
    font-family: -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
    background: var(--bg); color: var(--text); line-height:1.6;
    min-height:100vh; padding-bottom:40px;
  }
  .container { max-width:480px; margin:0 auto; padding:16px; }

  /* Header */
  .header { text-align:center; padding:32px 0 20px; }
  .header .icon { font-size:48px; margin-bottom:12px; }
  .header h1 { font-size:1.5rem; font-weight:700; margin-bottom:4px; }
  .header p { font-size:.875rem; color:var(--sub); }

  /* Steps */
  .steps { display:flex; gap:8px; margin:0 0 24px; }
  .step {
    flex:1; text-align:center; padding:12px 8px; background:var(--card);
    border-radius:10px; box-shadow:0 1px 3px rgba(0,0,0,.06); font-size:.75rem;
    color:var(--mute); transition:all .3s;
  }
  .step .num {
    display:inline-block; width:24px; height:24px; line-height:24px;
    border-radius:50%; background:var(--bg); font-weight:700; font-size:.75rem;
    margin-bottom:4px;
  }
  .step.active { color:var(--accent); box-shadow:0 2px 8px rgba(224,123,75,.15); }
  .step.active .num { background:var(--accent); color:#fff; }
  .step.done { color:var(--green); }
  .step.done .num { background:var(--green); color:#fff; }

  /* Upload Zone */
  .upload-zone {
    background:var(--card); border:2px dashed var(--border); border-radius:16px;
    padding:40px 20px; text-align:center; cursor:pointer; transition:all .2s;
    margin-bottom:16px;
  }
  .upload-zone:hover, .upload-zone.dragover { border-color:var(--accent); background:var(--accent-light); }
  .upload-zone .icon { font-size:56px; display:block; margin-bottom:12px; }
  .upload-zone .title { font-size:1rem; font-weight:600; margin-bottom:4px; }
  .upload-zone .hint { font-size:.75rem; color:var(--mute); }
  .upload-zone .preview { max-width:100%; max-height:240px; border-radius:8px; display:none; margin:0 auto; }

  /* File input hidden */
  #fileInput { display:none; }

  /* Progress */
  .progress-card {
    background:var(--card); border-radius:16px; padding:32px 20px; text-align:center;
    box-shadow:0 2px 8px rgba(0,0,0,.06); display:none; margin-bottom:16px;
  }
  .spinner {
    display:inline-block; width:40px; height:40px; border:3px solid var(--border);
    border-top-color:var(--accent); border-radius:50%; animation:spin .8s linear infinite;
    margin-bottom:16px;
  }
  @keyframes spin { to { transform:rotate(360deg); } }
  .progress-card .status { font-size:.875rem; color:var(--sub); }
  .progress-card .step-name { font-size:.75rem; color:var(--mute); margin-top:4px; }

  /* Result Card */
  .result-card {
    background:var(--card); border-radius:16px; padding:24px 20px;
    box-shadow:0 2px 8px rgba(0,0,0,.06); display:none; margin-bottom:16px;
  }
  .result-card .title { font-size:1.15rem; font-weight:600; margin-bottom:16px; text-align:center; }
  .result-card .score-box {
    display:flex; align-items:center; justify-content:center; gap:16px;
    padding:16px; background:var(--accent-light); border-radius:12px; margin-bottom:20px;
  }
  .score-circle {
    width:72px; height:72px; border-radius:50%; display:flex; align-items:center;
    justify-content:center; font-size:1.5rem; font-weight:700; color:#fff;
  }
  .score-circle.high { background:var(--green); }
  .score-circle.mid { background:var(--accent); }
  .score-circle.low { background:var(--red); }
  .score-detail { font-size:.8rem; color:var(--sub); line-height:1.5; }
  .score-detail strong { color:var(--text); }

  .diagnosis-item {
    padding:12px 16px; border-radius:10px; margin-bottom:8px;
    display:flex; align-items:flex-start; gap:10px; font-size:.875rem;
  }
  .diagnosis-item .tag {
    display:inline-block; padding:2px 10px; border-radius:100px;
    font-size:.7rem; font-weight:600; white-space:nowrap;
  }
  .diagnosis-item.weak { background:var(--red-light); }
  .diagnosis-item.weak .tag { background:var(--red); color:#fff; }
  .diagnosis-item.ok { background:var(--green-light); }
  .diagnosis-item.ok .tag { background:var(--green); color:#fff; }
  .diagnosis-item.tip { background:var(--blue-light); }
  .diagnosis-item.tip .tag { background:var(--blue); color:#fff; }

  /* Buttons */
  .btn {
    display:block; width:100%; padding:14px; border:none; border-radius:12px;
    font-size:.95rem; font-weight:600; cursor:pointer; transition:all .15s;
    text-align:center; text-decoration:none;
  }
  .btn-primary { background:var(--accent); color:#fff; margin-bottom:8px; }
  .btn-primary:hover { background:var(--accent-hover); }
  .btn-secondary { background:var(--card); color:var(--accent); border:1.5px solid var(--accent); }
  .btn:disabled { opacity:.5; pointer-events:none; }

  /* Toast */
  .toast {
    position:fixed; top:20px; left:50%; transform:translateX(-50%); z-index:999;
    background:#1a1a1a; color:#fff; padding:10px 24px; border-radius:100px;
    font-size:.8rem; display:none;
  }

  /* Bottom CTA */
  .bottom-cta { text-align:center; padding:8px 0; }
  .bottom-cta p { font-size:.75rem; color:var(--mute); }
</style>
</head>
<body>
<div class="container">

  <!-- Header -->
  <div class="header">
    <div class="icon">🏠</div>
    <h1>AI 学情体检</h1>
    <p>不急着评价孩子，先学会看懂孩子</p>
  </div>

  <!-- Steps -->
  <div class="steps" id="steps">
    <div class="step active" id="step1"><div class="num">1</div>拍张试卷</div>
    <div class="step" id="step2"><div class="num">2</div>AI 看懂</div>
    <div class="step" id="step3"><div class="num">3</div>知道怎么办</div>
  </div>

  <!-- Progress -->
  <div class="progress-card" id="progressCard">
    <div class="spinner"></div>
    <div class="status" id="progressStatus">正在识别试卷文字...</div>
    <div class="step-name" id="progressStep"></div>
  </div>

  <!-- Dashboard (returning users) -->
  <div class="dashboard" id="dashboard" style="display:none;">
    <!-- Stats row -->
    <div class="stats-row" id="statsRow"></div>
    <!-- Progress timeline -->
    <div class="result-card" id="timelineCard" style="margin-top:16px;">
      <div style="font-weight:600;font-size:.95rem;margin-bottom:12px;">📅 成长足迹</div>
      <div id="timelineList" style="font-size:.8rem;color:var(--sub);"></div>
    </div>
    <!-- Knowledge mastery -->
    <div class="result-card" id="masteryCard" style="margin-top:12px;">
      <div style="font-weight:600;font-size:.95rem;margin-bottom:12px;">🌱 成长进度</div>
      <div id="masteryBar"></div>
    </div>
    <!-- New test button -->
    <button class="btn btn-primary" onclick="startNewTest()" style="margin-top:16px;">📸 这周的试卷拍一张</button>
    <button class="btn btn-secondary" onclick="resetParent()" style="margin-top:8px;font-size:.8rem;">换个孩子看看</button>
  </div>

  <!-- Upload Zone (wrapped) -->
  <div id="uploadSection">
    <div class="upload-zone" id="uploadZone" onclick="document.getElementById('fileInput').click()">
      <span class="icon">📸</span>
      <div class="title">点击拍照或选择试卷照片</div>
      <div class="hint">支持 JPG/PNG，建议拍清晰</div>
      <img class="preview" id="previewImg" />
    </div>
    <input type="file" id="fileInput" accept="image/*" capture="environment" />
  </div>

  <!-- Progress -->
  <div class="progress-card" id="progressCard">
    <div class="spinner"></div>
    <div class="status" id="progressStatus">正在识别试卷文字...</div>
    <div class="step-name" id="progressStep"></div>
  </div>

  <!-- Result (one-time diagnosis) -->
  <div class="result-card" id="resultCard"></div>

  <!-- Bottom -->
  <div class="bottom-cta">
    <p>外面已经够卷了，家里别再变成第二个战场 💛</p>
  </div>
</div>

<!-- Toast -->
<div class="toast" id="toast"></div>

<script>
  const STORAGE_KEY = 'ai_parent_code';
  let savedCode = localStorage.getItem(STORAGE_KEY) || '';

  const fileInput = document.getElementById('fileInput');
  const uploadZone = document.getElementById('uploadZone');
  const uploadSection = document.getElementById('uploadSection');
  const previewImg = document.getElementById('previewImg');
  const progressCard = document.getElementById('progressCard');
  const resultCard = document.getElementById('resultCard');
  const dashboard = document.getElementById('dashboard');
  const progressStatus = document.getElementById('progressStatus');
  const progressStep = document.getElementById('progressStep');

  // Init: 回访家长（有有效 code）直接进入完整学习中心（P2-9 家庭端合并）
  (async function init() {
    if (savedCode) {
      const data = await loadProgress(savedCode);
      if (data && data.diagnoses && data.diagnoses.length > 0) {
        location.href = '/s/' + savedCode;
        return;
      }
      // Code invalid, clear
      localStorage.removeItem(STORAGE_KEY);
      savedCode = '';
    }
    showUploadMode();
  })();

  fileInput.addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      previewImg.src = ev.target.result;
      previewImg.style.display = 'block';
      uploadZone.querySelector('.icon').style.display = 'none';
      uploadZone.querySelector('.title').textContent = '选好了，点这里重新拍';
      uploadZone.querySelector('.hint').textContent = file.name;
    };
    reader.readAsDataURL(file);
    await diagnose(file);
  });

  function showUploadMode() {
    uploadSection.style.display = 'block';
    dashboard.style.display = 'none';
    resultCard.style.display = 'none';
    progressCard.style.display = 'none';
    setStep(1);
  }

  function startNewTest() {
    uploadSection.style.display = 'block';
    resultCard.style.display = 'none';
    progressCard.style.display = 'none';
    previewImg.style.display = 'none';
    uploadZone.querySelector('.icon').style.display = 'block';
    uploadZone.querySelector('.title').textContent = '点这里，拍一张孩子的英语试卷';
    uploadZone.querySelector('.hint').textContent = '拍得清楚一点，AI 看得更准哦';
    setStep(1);
    window.scrollTo({top:0, behavior:'smooth'});
  }

  function resetParent() {
    localStorage.removeItem(STORAGE_KEY);
    savedCode = '';
    dashboard.style.display = 'none';
    document.getElementById('steps').style.display = 'flex';
    showUploadMode();
  }

  async function diagnose(file) {
    uploadSection.style.display = 'none';
    dashboard.style.display = 'none';
    progressCard.style.display = 'block';
    resultCard.style.display = 'none';
    setStep(2);

    const formData = new FormData();
    formData.append('file', file);
    if (savedCode) formData.append('access_code', savedCode);

    progressStatus.textContent = '正在上传，稍等一下...';
    progressStep.textContent = '';

    let res;
    try {
      res = await fetch('/api/parent/diagnose', { method:'POST', body:formData });
    } catch(e) {
      showError('网络不太稳定，请再试一次');
      return;
    }

    if (!res.ok) {
      const err = await res.json().catch(()=>({error:'出了点小问题'}));
      showError(err.error || '上传没成功，再试一次吧');
      return;
    }

    const { task_id, access_code } = await res.json();

    // Remember code for returning
    if (access_code) {
      savedCode = access_code;
      localStorage.setItem(STORAGE_KEY, access_code);
    }

    await pollTask(task_id);
  }

  async function pollTask(taskId) {
    const stepTexts = {
      'ocr': '正在读取试卷上的每一行字...',
      'analysis': '正在分析每道题错在哪里...',
      'plan': '正在为你定制下周的学习重点...',
      'report': '正在整理结果，马上就好...',
    };

    for (let i = 0; i < 120; i++) {
      await sleep(1500);
      let res;
      try { res = await fetch('/api/parent/task/' + taskId); } catch(e) { continue; }
      if (!res.ok) break;
      const data = await res.json();

      if (data.status === 'failed') {
        showError(data.error_message || '分析没成功，再试一次吧');
        return;
      }
      progressStatus.textContent = stepTexts[data.current_step] || '正在处理...';
      progressStep.textContent = data.progress ? '进度 ' + data.progress + '%' : '';
      if (data.status === 'done') {
        setStep(3);
        progressCard.style.display = 'none';
        // Reload dashboard with new data
        if (savedCode) {
          const prog = await loadProgress(savedCode);
          if (prog) { showDashboard(prog); return; }
        }
        showResult(data.output_data);
        return;
      }
    }
    showError('正在努力分析中，请稍后再看');
  }

  // ── Progress / Dashboard ──

  async function loadProgress(code) {
    try {
      const r = await fetch('/api/parent/progress/' + code);
      if (!r.ok) return null;
      return await r.json();
    } catch(e) { return null; }
  }

  function showDashboard(data) {
    dashboard.style.display = 'block';
    uploadSection.style.display = 'none';
    progressCard.style.display = 'none';
    resultCard.style.display = 'none';
    document.getElementById('steps').style.display = 'none';

    const d = data;
    const diagnoses = d.diagnoses || [];
    const latest = diagnoses[0] || {};
    const mistakes = d.mistakes || { total: 0, mastered: 0 };

    // Stats row — reframed positively
    let statsHtml = '<div style="display:flex;gap:8px;flex-wrap:wrap;">';
    statsHtml += statCard('🩺', diagnoses.length, '次体检');
    statsHtml += statCard('🌟', mistakes.mastered, '已稳住');
    statsHtml += statCard('🌱', mistakes.total - mistakes.mastered, '成长中');
    statsHtml += statCard('💪', d.checkin_days || 0, '坚持天');
    statsHtml += '</div>';
    document.getElementById('statsRow').innerHTML = statsHtml;

    // Timeline
    let tlHtml = '';
    if (diagnoses.length === 0) {
      tlHtml = '<div style="color:var(--mute);text-align:center;padding:20px;">还没有记录哦～ 上传第一份试卷，开启成长之旅吧</div>';
    }
    diagnoses.forEach((diag, idx) => {
      const icon = idx === 0 ? '🆕' : '📄';
      const reportLink = diag.report_file_id
        ? `<a href="/api/public/${CODE}/files/${diag.report_file_id}/download" target="_blank" rel="noopener" style="font-size:.7rem;color:var(--accent);text-decoration:none;white-space:nowrap;">查看报告 →</a>`
        : '';
      tlHtml += `<div style="display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid var(--border);">
        <span style="font-size:1.2rem;">${icon}</span>
        <div style="flex:1;">
          <div style="font-weight:600;">${escapeHtml(diag.date || '')}</div>
          <div style="font-size:.75rem;color:var(--sub);">发现 ${diag.mistakes_count} 个提升点 · 聚焦 ${diag.weak_points_count} 个知识块</div>
        </div>
        ${reportLink}
        ${idx === 0 && diagnoses.length > 1 ? trendBadge(diagnoses) : ''}
      </div>`;
    });
    document.getElementById('timelineList').innerHTML = tlHtml || '<div style="color:var(--mute);">暂无记录</div>';

    // Mastery bar — growth journey framing
    const total = mistakes.total || 1;
    const pct = Math.round(mistakes.mastered / total * 100);
    document.getElementById('masteryBar').innerHTML = `
      <div style="display:flex;justify-content:space-between;font-size:.8rem;margin-bottom:6px;">
        <span>成长进度</span><span style="font-weight:600;">${pct}%</span>
      </div>
      <div style="height:10px;background:var(--border);border-radius:10px;overflow:hidden;">
        <div style="height:100%;width:${pct}%;background:var(--green);border-radius:10px;transition:width .5s;"></div>
      </div>
      <div style="font-size:.7rem;color:var(--mute);margin-top:4px;">
        ${mistakes.mastered} / ${mistakes.total} 个知识块已经稳住
        ${pct >= 60 ? '🎉 进步很大，继续保持这个节奏！' : pct >= 30 ? '💪 方向是对的，稳稳往前走' : '🌱 每一步都算数，孩子正在成长'}
      </div>`;

    // Entry to full student page (reports / practice / mistakes / progress tabs)
    if (savedCode) {
      let entry = document.getElementById('studentPageEntry');
      if (!entry) {
        entry = document.createElement('div');
        entry.id = 'studentPageEntry';
        entry.style.cssText = 'margin-top:16px;text-align:center;';
        masteryCard.parentNode.insertBefore(entry, masteryCard.nextSibling);
      }
      entry.innerHTML = `<a href="/s/${savedCode}" style="display:block;padding:14px;background:var(--accent);color:#fff;border-radius:12px;font-weight:600;font-size:.95rem;text-decoration:none;box-shadow:0 2px 8px rgba(224,123,75,.2);">📋 查看完整学情 · 报告/练习/错题</a>`;
    }
  }

  function statCard(icon, num, label) {
    return `<div style="flex:1;min-width:70px;background:var(--card);border-radius:10px;padding:12px 8px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.06);">
      <div style="font-size:1.3rem;">${icon}</div>
      <div style="font-size:1.3rem;font-weight:700;">${num}</div>
      <div style="font-size:.7rem;color:var(--mute);">${label}</div>
    </div>`;
  }

  function trendBadge(diagnoses) {
    if (diagnoses.length < 2) return '';
    const curr = diagnoses[0].mistakes_count || 0;
    const prev = diagnoses[1].mistakes_count || 0;
    if (curr < prev) return '<span style="color:var(--green);font-size:.75rem;font-weight:600;">↓ 提升点变少啦</span>';
    if (curr > prev) return '<span style="color:var(--red);font-size:.75rem;font-weight:600;">↑ 这周多关注下</span>';
    return '<span style="color:var(--mute);font-size:.75rem;">→ 保持稳定</span>';
  }

  // ── Result (one-time, no account) ──

  function showResult(data) {
    resultCard.style.display = 'block';

    let mc = data.mistakes_count || 0;
    let wp = data.weak_points_count || 0;
    let score = mc === 0 ? 100 : Math.max(30, 100 - mc * 12);
    let level = score >= 80 ? 'high' : score >= 50 ? 'mid' : 'low';
    let levelText = score >= 80 ? '基础挺扎实的 👍' : score >= 50 ? '有进步空间 💪' : '现在开始，就是最好的时候 🌱';
    let weaknesses = typeof data.weak_points === 'string'
      ? data.weak_points.split('\n').filter(Boolean)
      : (data.weak_points || []);

    let html = '<div class="title">🩺 孩子的英语学习体检单</div>';

    // Score
    html += `<div class="score-box">
      <div class="score-circle ${level}">${score}</div>
      <div class="score-detail">
        <div><strong>综合状态：${levelText}</strong></div>
        <div>发现了 ${mc} 个可以提升的地方</div>
        <div>聚焦 ${wp} 个知识点就能进步</div>
      </div>
    </div>`;

    // Weak points - reframed as "growth opportunities"
    if (weaknesses.length > 0) {
      html += '<div style="font-weight:600;font-size:.9rem;margin-bottom:8px;">🌱 接下来可以重点关注</div>';
      weaknesses.forEach(w => {
        html += `<div class="diagnosis-item weak">
          <span class="tag">成长点</span>
          <span>${escapeHtml(w)}</span>
        </div>`;
      });
    }

    // Strengths
    html += '<div style="font-weight:600;font-size:.9rem;margin:16px 0 8px;">🌟 已经做得很好的</div>';
    html += `<div class="diagnosis-item ok">
      <span class="tag">稳住了</span>
      <span>AI 识别出部分稳定掌握的知识点，这是孩子的基础盘</span>
    </div>`;

    // Suggestions - parent-friendly actions
    html += '<div style="font-weight:600;font-size:.9rem;margin:16px 0 8px;">💛 这周你可以试试</div>';
    html += `<div class="diagnosis-item tip">
      <span class="tag">小行动</span>
      <span>每周拍一张试卷，坚持 4 周就能看到变化轨迹</span>
    </div>`;
    html += `<div class="diagnosis-item tip">
      <span class="tag">这样说</span>
      <span>别问"怎么又错了"，试试"我们一起来看这道题卡在哪里"</span>
    </div>`;

    resultCard.innerHTML = html;

    // Action buttons
    let reportBtn = '';
    if (data.report_file_id) {
      reportBtn = `<a href="/api/public/${CODE}/files/${data.report_file_id}/download" target="_blank" rel="noopener" style="display:block;padding:14px;background:var(--accent);color:#fff;border-radius:12px;font-weight:600;font-size:.95rem;text-decoration:none;text-align:center;margin-bottom:10px;">📄 查看详细分析报告</a>`;
    }
    resultCard.innerHTML += `
      <div style="margin-top:20px;">
        ${reportBtn}
        ${savedCode ? `<a href="/s/${savedCode}" style="display:block;padding:12px;background:var(--card);color:var(--accent);border-radius:12px;font-weight:600;font-size:.9rem;text-decoration:none;text-align:center;margin-bottom:10px;border:1px solid var(--accent);">📋 进入完整学情主页</a>` : ''}
        <p style="text-align:center;font-size:.8rem;color:var(--mute);margin-bottom:8px;">每次拍照都会记录下来，进步看得见 ✨</p>
        <button class="btn btn-primary" onclick="location.reload()">再拍一张试卷</button>
      </div>`;
  }

  function showError(msg) {
    progressCard.style.display = 'none';
    uploadZone.style.display = 'block';
    setStep(1);
    const toast = document.getElementById('toast');
    toast.textContent = msg;
    toast.style.display = 'block';
    setTimeout(() => { toast.style.display = 'none'; }, 3000);
  }

  function setStep(n) {
    [1,2,3].forEach(i => {
      const el = document.getElementById('step'+i);
      el.className = 'step' + (i < n ? ' done' : i === n ? ' active' : '');
    });
  }

  function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

  // Drag & drop
  uploadZone.addEventListener('dragover', (e) => { e.preventDefault(); uploadZone.classList.add('dragover'); });
  uploadZone.addEventListener('dragleave', () => { uploadZone.classList.remove('dragover'); });
  uploadZone.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadZone.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (file && file.type.startsWith('image/')) {
      fileInput.files = e.dataTransfer.files;
      fileInput.dispatchEvent(new Event('change'));
    }
  });
</script>
</body>
</html>'''

