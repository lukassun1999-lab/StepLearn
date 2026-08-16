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
