#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档解析层：PDF / docx 直接提取文本，不必走 vision OCR。

为什么需要这一层：
- 文本型 PDF/docx 直接提取文本 → **零 LLM 成本、100% 准确、更快**，
  而走 vision OCR 既花钱又可能识别错（手写/印刷混淆）。
- 扫描型 PDF（页面本质是图片，没有文本层）→ 渲染成图片回退 vision OCR。
- 老格式 .doc（Word 97-2003 二进制）Python 无法直接读，需 LibreOffice 转换；
  为保持服务器轻量不引入该依赖，遇到 .doc 明确提示用户另存为 .docx。

依赖（均为纯 pip，无系统级依赖）：
  PyMuPDF（import fitz）— PDF 文本提取 + 页面渲染
  python-docx            — docx 文本提取（含表格）
"""

import logging
import os

log = logging.getLogger(__name__)

# 判定为"文本型 PDF"的最少字符数：低于此值视为扫描件（无文本层）
_MIN_TEXT_PDF_CHARS = 50
# 扫描型 PDF 渲染上限（与图片上传 15 张对齐，防止超大 PDF 打爆内存）
_MAX_PDF_PAGES = 15
_PDF_RENDER_DPI = 200

DOC_EXTS = {".pdf", ".docx"}
# 明确不支持的老格式，用于给出可操作的提示
_LEGACY_DOC_EXT = ".doc"


def is_document(path: str) -> bool:
    """是否为本层可处理的文档格式（pdf/docx）。"""
    return os.path.splitext(path or "")[1].lower() in DOC_EXTS


def is_legacy_doc(path: str) -> bool:
    return os.path.splitext(path or "")[1].lower() == _LEGACY_DOC_EXT


def _import_fitz():
    """PyMuPDF ≥1.28 推荐 import pymupdf（import fitz 已标记废弃），
    旧版本只有 fitz。两者兼容，取可用的那个。"""
    try:
        import pymupdf
        return pymupdf
    except ImportError:
        pass
    try:
        import fitz  # PyMuPDF（旧导入名）
        return fitz
    except ImportError:
        log.warning("PyMuPDF 未安装，PDF 将无法直接提取文本（回退 vision OCR）")
        return None


def extract_text_from_pdf(path: str):
    """提取 PDF 文本。返回 (text, ok)。

    ok=False 表示无有效文本层（扫描件），调用方应渲染成图片走 vision。
    """
    fitz = _import_fitz()
    if fitz is None:
        return "", False
    try:
        with fitz.open(path) as doc:
            parts = [page.get_text() for page in doc]
        text = "\n".join(parts).strip()
    except Exception:
        log.warning("PDF 文本提取失败: %s", path, exc_info=True)
        return "", False
    if len(text) < _MIN_TEXT_PDF_CHARS:
        return "", False
    return text, True


def pdf_to_images(path: str, out_dir: str):
    """扫描型 PDF 渲染为 PNG，返回图片路径列表（按页序）。"""
    fitz = _import_fitz()
    if fitz is None:
        return []
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    try:
        with fitz.open(path) as doc:
            for i, page in enumerate(doc):
                if i >= _MAX_PDF_PAGES:
                    log.warning("PDF 超过 %s 页，仅渲染前 %s 页: %s",
                                _MAX_PDF_PAGES, _MAX_PDF_PAGES, path)
                    break
                pix = page.get_pixmap(dpi=_PDF_RENDER_DPI)
                p = os.path.join(out_dir, f"page_{i + 1}.png")
                pix.save(p)
                paths.append(p)
    except Exception:
        log.warning("PDF 渲染图片失败: %s", path, exc_info=True)
    return paths


def extract_text_from_docx(path: str) -> str:
    """提取 docx 文本（段落 + 表格）。表格常用于试卷排版，必须一并取。"""
    try:
        import docx
    except ImportError:
        log.warning("python-docx 未安装，docx 无法解析: %s", path)
        return ""
    try:
        d = docx.Document(path)
        parts = [p.text.strip() for p in d.paragraphs if p.text.strip()]
        for table in d.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells]
                if any(cells):
                    parts.append(" | ".join(cells))
        return "\n".join(parts).strip()
    except Exception:
        log.warning("docx 解析失败: %s", path, exc_info=True)
        return ""


def parse_document(path: str, out_dir: str = None):
    """解析单个文档。返回 (text, images)。

    - text:   提取到的文本；为空表示未能直接提取
    - images: 需回退 vision 的图片路径列表（扫描型 PDF 渲染产物）

    调用方逻辑：text 非空则直接用；否则把 images 交给 OCR。
    """
    ext = os.path.splitext(path or "")[1].lower()
    if ext == ".docx":
        return extract_text_from_docx(path), []
    if ext == ".pdf":
        text, ok = extract_text_from_pdf(path)
        if ok:
            return text, []
        # 扫描件：渲染成图片回退 vision
        if out_dir:
            return "", pdf_to_images(path, out_dir)
        return "", []
    return "", []
