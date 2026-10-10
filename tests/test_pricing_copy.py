# -*- coding: utf-8 -*-
"""对外计费表述与实际计价一致性（P0-7 回归锁）。

背景：2026-10-10 竞品核验时发现报告页脚写着"按周付费，随时可停"，但
`PRICING`（db/core.py）只有 免费体验 / ¥39 月 / ¥399 年，**没有周套餐** ——
等于对外承诺了不存在的计费方式（合规瑕疵）。

产品决定：**不新增周套餐，改文案对齐实际计价**。本文件锁住这条，防止
文案再漂移回未兑现的承诺。

按 DEVELOPMENT.md 约定，db / report_templates 在函数内惰性导入
（render_diagnostic_report 会经 get_teacher_profile 访问数据库）。
"""


def test_pricing_has_no_weekly_plan(test_db_path):
    """前置事实：PRICING 确实没有周套餐。

    若将来真的新增周套餐，本测试会失败 —— 那是好事：提醒同步更新文案，
    并在此处显式解除对"周付费"的限制。
    """
    import db

    plans = {str(k).lower() for k in db.PRICING}
    assert not any("week" in name for name in plans), \
        f"PRICING 出现了周套餐，请同步更新对外文案与 P0-7 测试：{plans}"
    assert {"trial", "monthly", "yearly"} <= plans


def test_no_weekly_billing_claim_in_report_templates():
    """模板源码里不得残留"按周付费"。

    报告模板有多个渲染面（诊断报告/周报/月度/海报等），逐面渲染成本高且
    容易漏，因此直接对源码设卡：任何一处写回这个承诺都会被抓到。
    """
    import pathlib

    import report_templates

    src = pathlib.Path(report_templates.__file__).read_text(encoding="utf-8")
    assert "按周付费" not in src
    assert "按月/按年付费" in src, "对外计费口径应写明 按月/按年"


def test_diagnostic_report_footer_matches_pricing(test_db_path):
    """诊断报告页脚：计价口径与 PRICING 一致。"""
    from report_templates import render_diagnostic_report

    html = render_diagnostic_report(
        student={"name": "小明", "grade": "初二"},
        ocr_confidence=0.95,
        mistakes=[], weak_points=[], learning_plan={},
    )
    assert "按周付费" not in html
    assert "按月/按年付费" in html
    assert "随时可停" in html


def test_share_poster_footer_matches_pricing(test_db_path):
    """学习海报页脚：计价口径与 PRICING 一致。"""
    from report_templates import render_share_poster

    html = render_share_poster({"name": "小明", "grade": "初二"}, {})
    assert "按周付费" not in html
    assert "按月/按年付费" in html
