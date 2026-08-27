# -*- coding: utf-8 -*-
"""UI 关键缺陷修复回归测试（第 4 批提交 1）。

覆盖：
- 家长页 PARENT_PAGE 不再引用未定义的 CODE（ReportError 卡死分析完成流程）
- 页面无重复 DOM id（progressCard 等曾定义两次）
- viewport 允许缩放（家长读报告）
- 管理端任务状态徽章 CSS 存在
- pollTask 按任务类型解析步骤（不再用 DOM 前缀查表）
- onclick 不再字符串插值学生名（XSS）
"""

import re


def _page_src(name):
    import web.templates_family as tf
    import web.templates_admin as ta
    return {"family": tf.STUDENT_PAGE, "parent": tf.PARENT_PAGE,
            "admin": ta.MAIN_PAGE}[name]


def test_parent_page_no_undefined_code():
    src = _page_src("parent")
    # PARENT_PAGE 全文里不允许出现裸 CODE（savedCode 之外的）
    for m in re.finditer(r'CODE', src):
        ctx = src[max(0, m.start()-10):m.start()+6]
        assert 'savedCode' in ctx or 'STORAGE' in ctx or 'ACCESS' in ctx, \
            f"PARENT_PAGE 存在未定义 CODE 引用: ...{ctx!r}"


def test_no_duplicate_dom_ids():
    for page in ("family", "parent", "admin"):
        src = _page_src(page)
        # 排除 JS 模板字面量动态 id（${...}）
        ids = [i for i in re.findall(r'id="([^"]+)"', src)
               if "${" not in i]
        dups = {i for i in ids if ids.count(i) > 1}
        assert not dups, f"{page} 页重复 id: {dups}"


def test_parent_viewport_allows_zoom():
    src = _page_src("parent")
    assert "user-scalable=no" not in src
    assert "maximum-scale=1" not in src


def test_admin_task_status_badges_css():
    src = _page_src("admin")
    for status in ("pending", "processing", "done", "failed"):
        assert f".badge-{status}" in src, f"缺少 .badge-{status} 样式"


def test_admin_poll_task_uses_task_type():
    src = _page_src("admin")
    # 步骤列表应从任务响应的 task_type 解析，而非 DOM 前缀
    assert "STEPS_MAP[t.task_type]" in src
    # 后端真实步骤名接入
    assert "current_step" in src


def test_admin_no_raw_name_in_onclick():
    src = _page_src("admin")
    # onclick 内不允许直接插值字符串学生名（引号逃逸 → XSS）
    assert "manageSub(${s.id},'${s.name}')" not in src
    assert "manageSub(${s.id}, this.dataset.name)" in src


def test_family_touch_targets():
    src = _page_src("family")
    # 触控目标下限（原 32px 日历按钮 / 40px 心情按钮）
    assert "width:32px; height:32px;" not in src
    assert "width:32px;height:32px;" not in src


def test_family_min_font_sizes():
    src = _page_src("family")
    assert "font-size:.5rem" not in src   # 原 8px
    assert "font-size:.65em" not in src


# ═══ 提交 2：微信场景优化回归 ═══

def test_student_upload_uses_xhr():
    """学生页上传使用 XHR（upload.onprogress）获取真字节进度，而非 fetch 假进度。"""
    src = _page_src("family")
    assert "XMLHttpRequest" in src
    assert "upload.onprogress" in src or "xhr.upload" in src
    # 不应再用 fetch 上传（上传函数内）
    lines = src.split('\n')
    in_upload_fn = False
    for line in lines:
        if 'async function handleParentUpload' in line:
            in_upload_fn = True
        if in_upload_fn and 'async function ' in line and 'handleParentUpload' not in line:
            break
        if in_upload_fn and "'/api/public/" in line and 'fetch(' in line:
            assert False, "学生页上传函数内仍用 fetch 上传，应改 XHR"


def test_student_upload_has_compressImage():
    """学生页含 compressImage 工具函数（客户端压缩后再上传）。"""
    src = _page_src("family")
    assert "function compressImage" in src
    # 压缩逻辑：canvas 长边缩放 + JPEG q0.8
    assert "maxEdge" in src or "max_edge" in src
    assert "image/jpeg" in src


def test_parent_has_multi_photo_ui():
    """家长页含多图预览 UI（previewList）和年级选择器（gradePick）。"""
    src = _page_src("parent")
    assert "id=\"previewList\"" in src or "id='previewList'" in src
    assert "pickedFiles" in src
    assert "pickedGrade" in src


def test_parent_page_og_meta():
    """家长页与学情主页均有 og:title/og:description 用于微信分享卡片。"""
    for page in ("family", "parent"):
        src = _page_src(page)
        assert "og:title" in src, f"{page} 缺 og:title"
        assert "og:description" in src, f"{page} 缺 og:description"


def test_student_wechat_poster_fix():
    """学情主页海报保存针对微信内置浏览器 UA 做了适配。"""
    src = _page_src("family")
    assert "MicroMessenger" in src
    assert "showPosterSaveOverlay" in src


def test_public_upload_accepts_multi():
    """公开上传端点使用 getlist('file') 接受多文件。"""
    import api.family_api as fa
    src = open(fa.__file__, encoding='utf-8').read()
    assert "getlist('file')" in src


# ═══ 提交 3：底部导航重构 + 管理端运营效率 ═══

def test_student_bottom_nav_five_items():
    """学生页顶部 9 tab 收敛为底部导航 5 项（首页/练习/报告/成长/我的）。"""
    src = _page_src("family")
    assert "bottom-nav" in src
    for tab in ('home', 'practice', 'reports', 'growth', 'me'):
        assert f'data-tab="{tab}"' in src, f"底部导航缺 {tab} 项"
    # 旧的 9 tab 顶栏按钮已移除
    assert 'onclick="switchTab(\'timeline\', event)"' in src  # 转为分段按钮
    assert "class=\"tabs\"" not in src


def test_student_growth_me_groups():
    """成长（时间轴/成就墙/成长记录）与我的（复盘/坚持日记/进度）分组容器。"""
    src = _page_src("family")
    assert 'id="page-growth"' in src
    assert 'id="page-me"' in src
    # 子区用 sub-page（与 .page 主容器区分，switchTab 不会误伤）
    assert 'id="page-timeline" class="sub-page' in src
    assert 'id="page-mistakes" class="sub-page' in src
    assert 'id="page-progress" class="sub-page' in src
    # 旧 tab 名映射到分组
    assert "SUB_GROUPS" in src
    assert "mistakes:'growth'" in src
    assert "progress:'me'" in src


def test_student_hash_sync():
    """底部导航切换写 hash，刷新/返回可恢复位置。"""
    src = _page_src("family")
    assert "window.location.hash = name" in src or "location.hash = name" in src
    assert "hashchange" in src
    assert "VALID_TABS" in src


def test_admin_live_tasks_strip():
    """仪表盘含进行中任务实时条（10s 轮询 /api/tasks 过滤 processing/pending）。"""
    src = _page_src("admin")
    assert "live-tasks-wrap" in src
    assert "loadLiveTasks" in src
    assert "setInterval(loadLiveTasks, 10000)" in src
    assert "t.status === 'processing' || t.status === 'pending'" in src


def test_admin_history_has_onboarding():
    """历史任务表补 onboarding 任务（此前只显示 weekly）。"""
    src = _page_src("admin")
    assert "t.task_type==='weekly' || t.task_type==='onboarding'" in src


def test_admin_consent_uses_modal():
    """consent 三连 prompt() 改为 modal 表单。"""
    src = _page_src("admin")
    assert 'id="consent-modal"' in src
    assert "consent-name" in src
    assert "saveConsent" in src
    # 两个 consent 函数均不再使用 prompt
    assert "consentedBy = prompt" not in src


# ═══ 提交 5：报告合并方案（报告=诊断总结+错题明细，完成提示直达，空壳过滤）═══

def test_student_done_card_has_report_entry():
    """分析完成卡片直接给「查看报告」「去练习」入口（不再只提示去练习 tab）。"""
    src = _page_src("family")
    assert "查看报告" in src
    assert "switchTab('reports', null)" in src
    # 完成态卡片是带按钮的 HTML 而非纯文本
    assert "resultDiv.innerHTML" in src


def test_student_reports_inline_preview():
    """报告列表卡片内联预览（iframe srcdoc 拉取报告 HTML，免下载打开）。"""
    src = _page_src("family")
    assert "toggleReportPreview" in src
    assert "frame.srcdoc = html" in src
    assert "report-preview-" in src
    # 最新报告默认展开
    assert "toggleReportPreview(0, reports[0].report_file_id)" in src
    # 预览底部有去练习入口
    assert "switchTab('practice', null)" in src


def test_reports_api_filters_empty_shells(client, sample_student, test_db_path):
    """报告列表过滤空壳：0 错题的周错题本/月度总结不再展示，有数据的保留。"""
    import db
    import json

    student = db.get_student(sample_student)
    code = student["access_code"]

    # 制造两类任务：空壳周错题本 + 有错题的分析任务
    db.create_task(sample_student, "weekly", {"stage": "grade_only"}, db_path=test_db_path)
    db.create_task(sample_student, "weekly", {"stage": "grade_only"}, db_path=test_db_path)
    conn = db.get_connection(test_db_path)
    tasks = conn.execute(
        "SELECT id FROM ai_tasks WHERE student_id = ? ORDER BY id DESC LIMIT 2",
        [sample_student]).fetchall()
    shell_id, real_id = tasks[0]["id"], tasks[1]["id"]
    conn.execute(
        "UPDATE ai_tasks SET status='done', needs_review=0, output_data=? WHERE id=?",
        [json.dumps({"stage": "weekly_book_done", "mistakes_count": 0,
                     "weekly_report_file_id": 1}), shell_id])
    conn.execute(
        "UPDATE ai_tasks SET status='done', needs_review=0, output_data=? WHERE id=?",
        [json.dumps({"stage": "exercises_ready", "mistakes_count": 5,
                     "report_file_id": 2}), real_id])
    conn.commit()
    conn.close()

    r = client.get(f"/api/public/{code}/reports")
    assert r.status_code == 200
    reports = r.get_json()
    titles = [x["title"] for x in reports]
    assert "学情分析报告" in titles, f"有数据的报告应保留: {titles}"
    assert "周错题本" not in titles, f"0 错题空壳应被过滤: {titles}"


def test_practice_options_data_driven():
    """交互答题按数据渲染选项（不依赖题型白名单），阅读选择/阅读补全短文也有选项。"""
    src = _page_src("family")
    # 选项渲染改为数据驱动：有选项就显示
    assert "opts.length > 0" in src
    # 阅读类题型补进白名单（选项缺失时走跳过分支而非填空输入框）
    assert "阅读选择" in src and "阅读补全短文" in src
    assert "escapeHtml(o.text)" in src


def test_failure_presentation_reliable():
    """失败/进度可靠呈现（任务 1 优化）：

    - 学生页：分析失败为常驻错误卡片（完整原因 + 重置按钮），不再是一行会被
      下一次状态覆盖的小字；超时给报告入口；部分成功明示 chunk_stats.failed
    - 家长页：showError 改常驻卡片（可手动关闭），不再 3 秒自动消失
    """
    student = _page_src("family")
    # 常驻错误卡片 + 重试引导
    assert "resetUploadAfterFailure" in student
    assert "❌ 分析没成功" in student
    assert "重新上传试卷照片" in student
    # 部分成功提示（分段分析块失败）
    assert "chunk_stats" in student and "个章节分析未成功" in student
    # 超时/网络异常给报告入口而非裸文本
    assert "分析还在进行中" in student

    parent = _page_src("parent")
    assert 'id="parent-error-card"' in parent
    assert "dismissParentError" in parent
    # showError 不再走自动消失的 toast
    assert "setTimeout(() => { toast.style.display = 'none'; }, 3000);" not in parent


def test_shared_css_common_layer():
    """模板公共层：四端共享样式抽取到 static/css/shared.css。

    - shared.css 必须存在且含公共组件规则（modal/page/btn/spin）
    - 四个内联模板均注入 <link>，且位于各页 <style> 之前（本地覆盖优先）
    - 被抽取的规则不得残留在模板中（重复声明即回退）
    """
    import os
    import web.templates_family as tf
    import web.templates_admin as ta
    import web.templates_auth as th

    css_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'css', 'shared.css')
    assert os.path.exists(css_path), "static/css/shared.css 不存在"
    css = open(css_path, encoding='utf-8').read()
    for sel in ('.page.active', '.modal-overlay.show', '.btn-outline',
                '.form-group', '@keyframes spin', '@keyframes modalEnter'):
        assert sel in css, f"shared.css 缺 {sel}"

    auth_tpl = getattr(th, [a for a in dir(th) if a.isupper() and 'PAGE' in a][0])
    for name, tpl in [('student', tf.STUDENT_PAGE), ('parent', tf.PARENT_PAGE),
                      ('admin', ta.MAIN_PAGE), ('auth', auth_tpl)]:
        link_pos = tpl.find('shared.css')
        style_pos = tpl.find('<style>')
        assert link_pos > 0, f"{name} 未引入 shared.css"
        assert link_pos < style_pos, f"{name} 的 link 必须在本地 <style> 之前"
        for leftover in ('.toast-success {', '@keyframes spin'):
            assert leftover not in tpl, f"{name} 残留已抽取规则: {leftover}"
