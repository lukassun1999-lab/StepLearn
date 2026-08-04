# -*- coding: utf-8 -*-
"""登录/注册页面模板（P2-12 自 app.py 拆出）。"""

LOGIN_PAGE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>登录 · 拾阶而上</title>
<link rel="icon" href="data:,">
<style>
:root {
  --bg: #f8f7f4; --card: #fff; --text: #1a1a1a; --text-alt: #37352f; --sub: #6b6b6b; --mute:#9b9b9b;
  --accent: #e07b4b; --accent-hover: #d06a3a; --accent-light: #fef3ed;
  --green:#0f7b4e; --green-light:#effaf3;
  --red: #d93a46; --border: #e8e6e1; --shadow: 0 1px 3px rgba(0,0,0,.06), 0 2px 8px rgba(0,0,0,.02);
  --shadow-lg: 0 4px 24px rgba(0,0,0,.08); --radius: 8px;
}
* { margin:0; padding:0; box-sizing:border-box; }
@keyframes spin { to { transform:rotate(360deg); } }
body { font-family: ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; background:var(--bg); color:var(--text-alt); display:flex; align-items:center; justify-content:center; min-height:100vh; font-size:.875rem; padding:20px; }
.login-card { background:var(--card); border:none; border-radius:12px; padding:36px 32px; width:100%; max-width:380px; box-shadow:var(--shadow-lg); }
.login-card h1 { font-size:1.3rem; color:var(--text); margin-bottom:6px; text-align:center; font-weight:700; }
.login-card .sub { text-align:center; color:var(--sub); font-size:.8rem; margin-bottom:24px; }
.role-tabs { display:flex; background:var(--bg); border-radius:10px; padding:4px; margin-bottom:24px; }
.role-tab { flex:1; text-align:center; padding:9px 0; border-radius:8px; font-size:.85rem; color:var(--sub); cursor:pointer; transition:all .18s; font-weight:500; }
.role-tab.active { background:var(--card); color:var(--accent); font-weight:600; box-shadow:var(--shadow); }
.form-group { margin-bottom:16px; }
.form-group label { display:block; font-size:.8rem; color:var(--sub); margin-bottom:5px; font-weight:600; }
.form-group input {
  width:100%; padding:10px 12px; border:1px solid var(--border); border-radius:var(--radius); font-size:.9rem;
  font-family:inherit; transition:border-color .15s, box-shadow .15s;
}
.form-group input:focus { border-color:var(--accent); box-shadow: 0 0 0 3px var(--accent-light); outline:none; }
.btn { width:100%; padding:11px; border:none; border-radius:var(--radius); cursor:pointer; font-size:.95rem; font-weight:600; transition:all .15s; }
.btn:hover { transform:translateY(-1px); box-shadow:var(--shadow); }
.btn:disabled { opacity:.6; cursor:not-allowed; transform:none; }
.btn-primary { background:var(--accent); color:#fff; }
.btn-primary:hover { background:var(--accent-hover); }
.error { color:var(--red); font-size:.8rem; margin-top:10px; text-align:center; display:none; }
.links { text-align:center; margin-top:18px; font-size:.8rem; color:var(--sub); }
.links a { color:var(--accent); text-decoration:none; font-weight:600; }
.pane { display:none; } .pane.active { display:block; animation:fadeIn .2s ease; }
@keyframes fadeIn { from{opacity:0;transform:translateY(4px);} to{opacity:1;transform:none;} }
.hint { font-size:.72rem; color:var(--mute); text-align:center; margin-top:14px; }
</style>
</head>
<body>
<div class="login-card">
  <h1>📚 拾阶而上</h1>
  <p class="sub">AI 个性化英语学习平台</p>

  <div class="role-tabs">
    <div class="role-tab active" id="tab-student" onclick="switchRole('student')">学生</div>
    <div class="role-tab" id="tab-staff" onclick="switchRole('staff')">教师 / 管理员</div>
  </div>

  <div class="pane active" id="pane-student">
    <div class="form-group"><label>账号</label><input type="text" id="s-phone" placeholder="手机号即为账号" maxlength="20"></div>
    <div class="form-group" id="s-pwd-group"><label>密码</label><input type="password" id="s-pwd" placeholder="请输入密码"></div>
    <div class="form-group" id="s-code-group" style="display:none;">
      <label>手机号</label>
      <input type="tel" id="s-sms-phone" placeholder="注册时的11位手机号" maxlength="11" style="margin-bottom:8px;">
      <div style="display:flex;gap:8px;">
        <input type="text" id="s-code" placeholder="6位验证码" maxlength="6" style="flex:1;">
        <button type="button" class="btn btn-outline" id="s-send-btn" onclick="sendSmsCode('student')" style="width:auto;padding:10px 16px;font-size:.8rem;white-space:nowrap;">获取验证码</button>
      </div>
    </div>
    <button class="btn btn-primary" id="s-btn" onclick="studentLogin()">登 录</button>
    <div class="error" id="s-err"></div>
    <div class="links">
      <a href="javascript:void(0)" onclick="toggleSmsLogin('student')" id="s-sms-toggle">忘记密码？</a>
       ·
      <a href="/register">立即注册</a>
    </div>
  </div>

  <div class="pane" id="pane-staff">
    <div class="form-group"><label>用户名</label><input type="text" id="t-user" placeholder="请输入用户名"></div>
    <div class="form-group" id="t-pwd-group"><label>密码</label><input type="password" id="t-pwd" placeholder="请输入密码"></div>
    <div class="form-group" id="t-phone-group" style="display:none;"><label>手机号</label><input type="tel" id="t-phone" placeholder="绑定的手机号" maxlength="11"></div>
    <div class="form-group" id="t-code-group" style="display:none;">
      <label>验证码</label>
      <div style="display:flex;gap:8px;">
        <input type="text" id="t-code" placeholder="6位验证码" maxlength="6" style="flex:1;">
        <button type="button" class="btn btn-outline" id="t-send-btn" onclick="sendSmsCode('staff')" style="width:auto;padding:10px 16px;font-size:.8rem;white-space:nowrap;">获取验证码</button>
      </div>
    </div>
    <button class="btn btn-primary" id="t-btn" onclick="staffLogin()">登 录</button>
    <div class="error" id="t-err"></div>
    <div class="links">
      <a href="javascript:void(0)" onclick="toggleSmsLogin('staff')" id="t-sms-toggle">验证码登录</a>
       · 
      <a href="/teacher-register">注册教师账号</a>
    </div>
  </div>
</div>
<script>
let _smsMode = {student: false, staff: false};

function switchRole(role){
  document.getElementById('tab-student').classList.toggle('active', role==='student');
  document.getElementById('tab-staff').classList.toggle('active', role==='staff');
  document.getElementById('pane-student').classList.toggle('active', role==='student');
  document.getElementById('pane-staff').classList.toggle('active', role==='staff');
}
function showErr(id,msg){const e=document.getElementById(id);e.textContent=msg;e.style.display='block';}
function hideErr(id){document.getElementById(id).style.display='none';}

function toggleSmsLogin(pane){
  _smsMode[pane] = !_smsMode[pane];
  if(pane === 'student'){
    document.getElementById('s-phone').parentElement.style.display = _smsMode.student ? 'none' : 'block';
    document.getElementById('s-pwd-group').style.display = _smsMode.student ? 'none' : 'block';
    document.getElementById('s-code-group').style.display = _smsMode.student ? 'block' : 'none';
    document.getElementById('s-sms-toggle').textContent = _smsMode.student ? '返回密码登录' : '忘记密码？';
  } else {
    document.getElementById('t-pwd-group').style.display = _smsMode.staff ? 'none' : 'block';
    document.getElementById('t-phone-group').style.display = _smsMode.staff ? 'block' : 'none';
    document.getElementById('t-code-group').style.display = _smsMode.staff ? 'block' : 'none';
    document.getElementById('t-sms-toggle').textContent = _smsMode.staff ? '密码登录' : '验证码登录';
  }
}

async function sendSmsCode(pane){
  const errId = pane === 'student' ? 's-err' : 't-err';
  const btnId = pane === 'student' ? 's-send-btn' : 't-send-btn';
  const phone = pane === 'student'
    ? document.getElementById('s-sms-phone').value.trim()
    : document.getElementById('t-phone').value.trim();
  hideErr(errId);
  if(!phone || phone.length !== 11){showErr(errId,'请输入11位手机号');return;}
  const btn = document.getElementById(btnId);
  btn.disabled = true;
  let countdown = 60;
  btn.textContent = countdown + 's';
  const timer = setInterval(()=>{countdown--;btn.textContent=countdown+'s';if(countdown<=0){clearInterval(timer);btn.disabled=false;btn.textContent='获取验证码';}},1000);
  try{
    const r = await fetch('/api/sms/send-code',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({phone,purpose:'login'})});
    const d = await r.json();
    if(!r.ok){showErr(errId,d.error||'发送失败');clearInterval(timer);btn.disabled=false;btn.textContent='获取验证码';}
  }catch(e){showErr(errId,'网络错误');clearInterval(timer);btn.disabled=false;btn.textContent='获取验证码';}
}

async function studentLogin(){
  hideErr('s-err');
  const btn=document.getElementById('s-btn');

  if(_smsMode.student){
    const phone=document.getElementById('s-sms-phone').value.trim();
    const code=document.getElementById('s-code').value.trim();
    if(!phone||!code){showErr('s-err','请填写手机号和验证码');return;}
    btn.disabled=true;btn.textContent='登录中...';
    try{
      const r=await fetch('/api/sms/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({phone,code})});
      const d=await r.json();
      if(r.ok){window.location.href=d.redirect||'/parent';}
      else{showErr('s-err',d.error||'登录失败');}
    }catch(e){showErr('s-err','网络错误');}
    btn.disabled=false;btn.textContent='登 录';
  } else {
    const account=document.getElementById('s-phone').value.trim();
    const pwd=document.getElementById('s-pwd').value;
    if(!account||!pwd){showErr('s-err','请填写账号和密码');return;}
    btn.disabled=true;btn.textContent='登录中...';
    try{
      const r=await fetch('/api/student-login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({account,password:pwd})});
      const d=await r.json();
      if(r.ok){window.location.href=d.redirect||'/parent';}
      else{showErr('s-err',d.error||'登录失败');}
    }catch(e){showErr('s-err','网络错误');}
    btn.disabled=false;btn.textContent='登 录';
  }
}

async function staffLogin(){
  hideErr('t-err');
  const btn=document.getElementById('t-btn');

  if(_smsMode.staff){
    const phone=document.getElementById('t-phone').value.trim();
    const code=document.getElementById('t-code').value.trim();
    if(!phone||!code){showErr('t-err','请填写手机号和验证码');return;}
    btn.disabled=true;btn.textContent='登录中...';
    try{
      const r=await fetch('/api/sms/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({phone,code})});
      const d=await r.json();
      if(r.ok){window.location.href=d.redirect||'/';}
      else{showErr('t-err',d.error||'登录失败');}
    }catch(e){showErr('t-err','网络错误');}
    btn.disabled=false;btn.textContent='登 录';
  } else {
    const user=document.getElementById('t-user').value.trim();
    const pwd=document.getElementById('t-pwd').value;
    if(!user||!pwd){showErr('t-err','请填写用户名和密码');return;}
    btn.disabled=true;btn.textContent='登录中...';
    const fd=new FormData();fd.append('username',user);fd.append('password',pwd);
    try{
      const r=await fetch('/login',{method:'POST',body:fd});
      if(r.redirected){window.location.href=r.url;}
      else{showErr('t-err','用户名或密码错误');}
    }catch(e){showErr('t-err','网络错误');}
    btn.disabled=false;btn.textContent='登 录';
  }
}

document.querySelectorAll('#pane-student input').forEach(i=>i.addEventListener('keydown',e=>{if(e.key==='Enter')studentLogin();}));
document.querySelectorAll('#pane-staff input').forEach(i=>i.addEventListener('keydown',e=>{if(e.key==='Enter')staffLogin();}));
</script>
</body>
</html>'''


STUDENT_REGISTER_PAGE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>学生注册 · 拾阶而上</title>
<link rel="icon" href="data:,">
<style>
:root{--bg:#f8f7f4;--card:#fff;--accent:#e07b4b;--accent-hover:#d06a3a;--accent-light:#fef3ed;--text:#1a1a1a;--sub:#6b6b6b;--border:#e8e6e1;--red:#d93a46;--green:#0f7b4e;--green-light:#effaf3;--shadow:0 1px 3px rgba(0,0,0,.06),0 2px 8px rgba(0,0,0,.02)}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.card{background:var(--card);border-radius:12px;padding:36px 32px;box-shadow:var(--shadow);width:100%;max-width:420px}
h1{font-size:1.3rem;color:var(--text);margin-bottom:6px;text-align:center}
.subtitle{text-align:center;color:var(--sub);font-size:.85rem;margin-bottom:24px}
label{display:block;font-size:.8rem;font-weight:600;color:var(--sub);margin-bottom:6px;margin-top:14px}
label:first-of-type{margin-top:0}
input,select{width:100%;border:1px solid var(--border);border-radius:8px;padding:10px 12px;font-size:.9rem;transition:border-color .15s,box-shadow .15s}
input:focus,select:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-light);outline:none}
button{width:100%;background:var(--accent);color:#fff;border:none;border-radius:8px;padding:12px;font-size:.9rem;font-weight:600;cursor:pointer;transition:all .15s;margin-top:20px}
button:hover{background:var(--accent-hover);transform:translateY(-1px)}
button:disabled{opacity:.6;cursor:not-allowed;transform:none}
.error{color:var(--red);font-size:.8rem;margin-top:12px;display:none}
.success{color:var(--green);font-size:.8rem;margin-top:8px;display:none}
.links{text-align:center;margin-top:20px;font-size:.8rem;color:var(--sub)}
.links a{color:var(--accent);text-decoration:none}
.autocomplete{position:relative}
.ac-list{position:absolute;top:100%;left:0;right:0;background:var(--card);border:1px solid var(--border);border-radius:8px;box-shadow:var(--shadow);z-index:10;display:none;max-height:200px;overflow-y:auto}
.ac-item{padding:10px 12px;cursor:pointer;font-size:.85rem;border-bottom:1px solid var(--border)}
.ac-item:last-child{border-bottom:none}
.ac-item:hover{background:var(--accent-light)}
.ac-item .alias{color:var(--sub);font-size:.75rem}
.code-ok{color:var(--green);font-size:.75rem;margin-top:4px;display:none}
</style>
</head>
<body>
<div class="card">
<h1>🎯 真正个性化的学习，从这里开始</h1>
<p class="subtitle">注册学生账号</p>
<div class="error" id="err"></div>

<label>姓名</label>
<input type="text" id="name" placeholder="你的姓名">

<label>手机号</label>
<input type="tel" id="phone" placeholder="11位手机号" maxlength="11">

<label>密码</label>
<input type="password" id="pwd" placeholder="至少6位">

{% if feature_school %}
<label>学校</label>
<div class="autocomplete">
  <input type="text" id="school-input" placeholder="输入学校名称搜索..." autocomplete="off">
  <div class="ac-list" id="ac-list"></div>
</div>
<input type="hidden" id="school-id">

<label>班级</label>
<select id="class-select" disabled><option value="">请先选择学校</option></select>

<label>班级码</label>
<input type="text" id="class-code" placeholder="老师提供的6位班级码" maxlength="6">
<div class="code-ok" id="code-ok">✓ 班级码验证通过</div>
{% endif %}

<button id="btn" onclick="doRegister()">注 册</button>
<div class="links">已有账号？<a href="/login">去登录</a></div>
</div>
<script>
const hasSchoolFields = !!document.getElementById('school-input');
let acTimer=null;

if (hasSchoolFields) {
  const schoolInput=document.getElementById('school-input');
  const acList=document.getElementById('ac-list');
  const classSelect=document.getElementById('class-select');
  const codeOk=document.getElementById('code-ok');

  schoolInput.addEventListener('input',function(){
    clearTimeout(acTimer);
    const q=this.value.trim();
    document.getElementById('school-id').value='';
    classSelect.disabled=true;classSelect.innerHTML='<option value="">请先选择学校</option>';
    if(q.length<1){acList.style.display='none';return;}
    acTimer=setTimeout(async()=>{
      const r=await fetch('/api/schools/search?q='+encodeURIComponent(q));
      const schools=await r.json();
      if(!schools.length){acList.style.display='none';return;}
      acList.innerHTML=schools.map(s=>`<div class="ac-item" data-id="${s.id}" data-name="${s.name}">${s.name}${s.aliases&&s.aliases.length?'<span class="alias"> ('+s.aliases.join('/')+')</span>':''}</div>`).join('');
      acList.style.display='block';
    },250);
  });

  acList.addEventListener('click',function(e){
    const item=e.target.closest('.ac-item');
    if(!item)return;
    schoolInput.value=item.dataset.name;
    document.getElementById('school-id').value=item.dataset.id;
    acList.style.display='none';
    loadClasses(item.dataset.id);
  });

  document.addEventListener('click',e=>{if(!e.target.closest('.autocomplete'))acList.style.display='none';});

  async function loadClasses(schoolId){
    const r=await fetch('/api/classes?school_id='+schoolId);
    const classes=await r.json();
    classSelect.disabled=false;
    classSelect.innerHTML='<option value="">请选择班级</option>'+classes.map(c=>`<option value="${c.id}">${c.name}${c.grade?' ('+c.grade+')':''}</option>`).join('');
  }

  document.getElementById('class-code').addEventListener('blur',async function(){
    const code=this.value.trim();
    codeOk.style.display='none';
    if(code.length!==6)return;
    const r=await fetch('/api/class/verify-code',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({class_code:code})});
    if(r.ok){codeOk.style.display='block';}
  });
}

async function doRegister(){
  const err=document.getElementById('err');err.style.display='none';
  const name=document.getElementById('name').value.trim();
  const phone=document.getElementById('phone').value.trim();
  const pwd=document.getElementById('pwd').value;
  const classCodeEl=document.getElementById('class-code');
  const classCode=classCodeEl?classCodeEl.value.trim():'';
  if(!name){err.textContent='请输入姓名';err.style.display='block';return;}
  if(!phone||phone.length!==11){err.textContent='请输入11位手机号';err.style.display='block';return;}
  if(!pwd||pwd.length<6){err.textContent='密码至少6位';err.style.display='block';return;}
  if(hasSchoolFields&&!classCode){err.textContent='请输入班级码';err.style.display='block';return;}
  const btn=document.getElementById('btn');btn.disabled=true;btn.textContent='注册中...';
  try{
    const body={name,phone,password:pwd};
    if(classCode)body.class_code=classCode;
    const r=await fetch('/api/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const d=await r.json();
    if(r.ok){window.location.href=d.redirect||'/parent';}
    else{err.textContent=d.error||'注册失败';err.style.display='block';}
  }catch(e){err.textContent='网络错误';err.style.display='block';}
  btn.disabled=false;btn.textContent='注 册';
}
</script>
</body>
</html>'''


TEACHER_REGISTER_PAGE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>教师注册 · 拾阶而上</title>
<link rel="icon" href="data:,">
<style>
:root{--bg:#f8f7f4;--card:#fff;--accent:#e07b4b;--accent-hover:#d06a3a;--accent-light:#fef3ed;--text:#1a1a1a;--sub:#6b6b6b;--border:#e8e6e1;--red:#d93a46;--shadow:0 1px 3px rgba(0,0,0,.06),0 2px 8px rgba(0,0,0,.02)}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.card{background:var(--card);border-radius:12px;padding:36px 32px;box-shadow:var(--shadow);width:100%;max-width:380px}
h1{font-size:1.3rem;color:var(--text);margin-bottom:6px;text-align:center}
.subtitle{text-align:center;color:var(--sub);font-size:.85rem;margin-bottom:24px}
label{display:block;font-size:.8rem;font-weight:600;color:var(--sub);margin-bottom:6px;margin-top:14px}
label:first-of-type{margin-top:0}
input{width:100%;border:1px solid var(--border);border-radius:8px;padding:10px 12px;font-size:.9rem;transition:border-color .15s,box-shadow .15s}
input:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-light);outline:none}
button{width:100%;background:var(--accent);color:#fff;border:none;border-radius:8px;padding:12px;font-size:.9rem;font-weight:600;cursor:pointer;transition:all .15s;margin-top:20px}
button:hover{background:var(--accent-hover);transform:translateY(-1px)}
button:disabled{opacity:.6;cursor:not-allowed;transform:none}
.error{color:var(--red);font-size:.8rem;margin-top:12px;display:none}
.links{text-align:center;margin-top:20px;font-size:.8rem;color:var(--sub)}
.links a{color:var(--accent);text-decoration:none}
.autocomplete{position:relative}
.ac-list{position:absolute;top:100%;left:0;right:0;background:var(--card);border:1px solid var(--border);border-radius:8px;box-shadow:var(--shadow);z-index:10;display:none;max-height:200px;overflow-y:auto}
.ac-item{padding:10px 12px;cursor:pointer;font-size:.85rem;border-bottom:1px solid var(--border)}
.ac-item:last-child{border-bottom:none}
.ac-item:hover{background:var(--accent-light)}
.ac-item .alias{color:var(--sub);font-size:.75rem}
</style>
</head>
<body>
<div class="card">
<h1>👩‍🏫 教师注册</h1>
<p class="subtitle">注册后即可管理班级和学生</p>
<div class="error" id="err"></div>
<label>姓名 / 昵称</label>
<input type="text" id="display-name" placeholder="如：王老师">
<label>学校</label>
<div class="autocomplete">
  <input type="text" id="school-input" placeholder="输入学校名称搜索..." autocomplete="off">
  <div class="ac-list" id="ac-list"></div>
</div>
<input type="hidden" id="school-id">
<label>用户名（登录用）</label>
<input type="text" id="username" placeholder="至少3位，仅英文和数字">
<label>手机号（可选，用于验证码登录）</label>
<input type="tel" id="phone" placeholder="11位手机号" maxlength="11">
<label>科目</label>
<select id="subject" style="width:100%;border:1px solid var(--border);border-radius:8px;padding:10px 12px;font-size:.9rem;">
  <option value="英语">英语</option>
  <option value="语文">语文</option>
  <option value="数学">数学</option>
  <option value="道法">道法</option>
  <option value="历史">历史</option>
  <option value="地理">地理</option>
  <option value="物理">物理</option>
  <option value="化学">化学</option>
  <option value="生物">生物</option>
  <option value="__custom__">自定义</option>
</select>
<div id="custom-subject-group" style="display:none;margin-top:8px;">
  <input type="text" id="custom-subject" placeholder="输入科目名称">
</div>
<label>密码</label>
<input type="password" id="pwd" placeholder="至少6位">
<label>确认密码</label>
<input type="password" id="pwd2" placeholder="再次输入密码">
<button id="btn" onclick="doRegister()">注 册</button>
<div class="links">已有账号？<a href="/login">去登录</a></div>
</div>
<script>
document.getElementById('subject').addEventListener('change', function(){
  document.getElementById('custom-subject-group').style.display = this.value === '__custom__' ? 'block' : 'none';
});

// School autocomplete
let acTimer=null;
const schoolInput=document.getElementById('school-input');
const acList=document.getElementById('ac-list');
schoolInput.addEventListener('input',function(){
  clearTimeout(acTimer);
  const q=this.value.trim();
  document.getElementById('school-id').value='';
  if(q.length<1){acList.style.display='none';return;}
  acTimer=setTimeout(async()=>{
    const r=await fetch('/api/schools/search?q='+encodeURIComponent(q));
    const schools=await r.json();
    if(!schools.length){acList.style.display='none';return;}
    acList.innerHTML=schools.map(s=>`<div class="ac-item" data-id="${s.id}" data-name="${s.name}">${s.name}${s.aliases&&s.aliases.length?'<span class="alias"> ('+s.aliases.join('/')+')</span>':''}</div>`).join('');
    acList.style.display='block';
  },250);
});
acList.addEventListener('click',function(e){
  const item=e.target.closest('.ac-item');if(!item)return;
  schoolInput.value=item.dataset.name;document.getElementById('school-id').value=item.dataset.id;
  acList.style.display='none';
});
document.addEventListener('click',e=>{if(!e.target.closest('.autocomplete'))acList.style.display='none';});

async function doRegister(){
  const err=document.getElementById('err');err.style.display='none';
  const displayName=document.getElementById('display-name').value.trim();
  const schoolId=parseInt(document.getElementById('school-id').value)||0;
  const username=document.getElementById('username').value.trim();
  const phone=document.getElementById('phone').value.trim();
  let subject = document.getElementById('subject').value;
  if(subject === '__custom__'){subject = document.getElementById('custom-subject').value.trim();}
  if(!subject){err.textContent='请选择或输入科目';err.style.display='block';return;}
  if(!schoolId){err.textContent='请选择学校';err.style.display='block';return;}
  const pwd=document.getElementById('pwd').value;
  const pwd2=document.getElementById('pwd2').value;
  if(!username){err.textContent='请输入用户名';err.style.display='block';return;}
  if(username.length<3){err.textContent='用户名至少3位';err.style.display='block';return;}
  if(!/^[a-zA-Z0-9]+$/.test(username)){err.textContent='用户名仅限英文和数字';err.style.display='block';return;}
  if(phone && (phone.length!==11 || !/^\d+$/.test(phone))){err.textContent='请输入有效的11位手机号';err.style.display='block';return;}
  if(!pwd||pwd.length<6){err.textContent='密码至少6位';err.style.display='block';return;}
  if(pwd!==pwd2){err.textContent='两次密码不一致';err.style.display='block';return;}
  const btn=document.getElementById('btn');btn.disabled=true;btn.textContent='注册中...';
  try{
    const r=await fetch('/api/teacher-register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password:pwd,display_name:displayName,phone:phone,subject:subject,school_id:schoolId})});
    const d=await r.json();
    if(r.ok){window.location.href=d.redirect||'/';}
    else{err.textContent=d.error||'注册失败';err.style.display='block';}
  }catch(e){err.textContent='网络错误';err.style.display='block';}
  btn.disabled=false;btn.textContent='注 册';
}
document.querySelectorAll('input').forEach(i=>i.addEventListener('keydown',e=>{if(e.key==='Enter')doRegister();}));
</script>
</body>
</html>'''

