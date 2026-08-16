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
