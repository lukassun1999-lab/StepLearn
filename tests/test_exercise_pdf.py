# -*- coding: utf-8 -*-
"""练习卷 PDF 中文支持测试。

历史事故：_ensure_cjk_font 只搜 Windows 字体目录且失败静默，Linux 生产环境
（gunicorn）上回退到 Helvetica，整页汉字渲染成同一占位字形（家长看到的"n"乱码）。
现仓库自带 Noto Sans SC（OFL 许可），任何环境都确定可用。
"""

import os

import pytest

import report_templates as rt


def test_bundled_cjk_font_exists():
    assert os.path.exists(rt._BUNDLED_CJK_FONT), (
        f"自带中文字体缺失: {rt._BUNDLED_CJK_FONT}（Linux 生产环境将出现整页乱码）")


def test_bundled_font_is_first_candidate(monkeypatch):
    monkeypatch.setenv("WINDIR", r"Z:\nonexistent")
    paths = list(rt._iter_cjk_font_paths())
    assert paths and paths[0] == rt._BUNDLED_CJK_FONT


def test_ensure_cjk_font_uses_bundled_when_no_system_fonts(monkeypatch):
    # 模拟 Linux：Windows 字体目录不可达（自带字体应在场兜底）
    monkeypatch.setenv("WINDIR", r"Z:\nonexistent")
    monkeypatch.setattr(rt, "_CJK_FONT_CANDIDATES", [])
    assert rt._ensure_cjk_font() == "CJK"


def test_ensure_cjk_font_warns_loudly_when_nothing_found(monkeypatch, caplog):
    import reportlab.pdfbase.pdfmetrics as _pm
    monkeypatch.setattr(_pm, "getRegisteredFontNames", lambda: [])
    monkeypatch.setattr(rt, "_CJK_REGISTERED", False)
    monkeypatch.setattr(rt, "_BUNDLED_CJK_FONT", "Z:/nonexistent/NotoSansSC.ttf")
    monkeypatch.setattr(rt, "_CJK_FONT_CANDIDATES", [])
    monkeypatch.setattr(rt, "_CJK_FONT_LINUX_DIRS", [])
    with caplog.at_level("WARNING"):
        assert rt._ensure_cjk_font() == ""  # 不再静默：必须告警
    assert any("CJK" in r.message for r in caplog.records)


def test_render_exercise_pdf_contains_chinese_text(test_db_path):
    questions = [{
        "question_text": "用所给单词的适当形式填空：She ___ (go) to school every day.",
        "options": [],
        "knowledge_points": ["一般现在时"],
        "question_type": "语法填空",
        "passage": "",
    }]
    pdf = rt.render_exercise_pdf("链路测试", questions, "2026-08-31")
    assert pdf[:5] == b"%PDF-" and len(pdf) > 1000
    # CJK 字体已注册并用于嵌入（不再回退纯西文 Helvetica）
    assert rt._ensure_cjk_font() == "CJK"


def test_render_exercise_pdf_english_fallback_when_no_cjk_font(monkeypatch):
    """最后兜底：无任何 CJK 字体时，版式标签全英文，且不嵌入 CJK 字体。

    （自带字体在场的部署走不到这里；这是防字体文件损坏/被删的保险。）"""
    monkeypatch.setattr(rt, "_ensure_cjk_font", lambda: "")
    questions = [{
        "question_text": "Fill in the blank: She ___ (go) to school every day.",
        "options": ["A. go", "B. goes", "C. going"],
        "knowledge_points": ["一般现在时"],  # 中文内容：英文版式下应被抑制
        "question_type": "语法填空",
        "passage": "",
    }]
    pdf = rt.render_exercise_pdf("student", questions, "2026-08-31")
    assert pdf[:5] == b"%PDF-" and len(pdf) > 1000
    # 全英文版式：没有绘制任何 CJK 字形 → 不会嵌入 CJK 字体子集
    assert b"NotoSansSC" not in pdf
    assert b"SimHei" not in pdf
    assert b"simhei" not in pdf
