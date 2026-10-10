#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""法律文本（用户服务协议 / 隐私政策 / AI 内容免责声明）的加载与渲染。

背景：家庭端同意交互必须能打开条款正文，否则"点击同意"没有依据。
文本源文件放在项目根 `legal/` 目录（与仓库一起部署），版本号与文件名中的版本对应。

- 零依赖：项目未引入 markdown 库，这里用一个小渲染器覆盖法律文本用到的子集
  （标题 / 无序列表 / 有序列表 / 引用 / 水平线 / 粗体 / 行内代码 / 表格 / 链接 / 段落）。
- 先解析结构、再对行内内容做 HTML 转义，避免把 `>` 引用符号转义掉。
"""

import html as _html
import os
import re
from typing import Dict, Optional, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEGAL_DIR = os.path.join(_ROOT, "legal")

# 同意书版本号：与 legal/ 下文本文件名中的版本一致（改动文本时必须同步，
# 否则 parent_consents.consent_version 记录的"同意的是哪一版"会失真）。
CONSENT_VERSION = "v1.0"

# slug → (文件名, 页面标题)
LEGAL_DOCS: Dict[str, Tuple[str, str]] = {
    "terms": ("01_用户服务协议_v1.0.md", "用户服务协议"),
    "privacy": ("02_隐私政策_v1.0.md", "隐私政策"),
    "ai-disclaimer": ("03_AI生成内容免责声明_v1.0.md", "AI 生成内容免责声明"),
}

# 同意时必须一并勾选确认的文档（顺序即展示顺序）
CONSENT_DOC_SLUGS = ("terms", "privacy")


def _inline(text: str) -> str:
    """行内元素：先转义，再做粗体/代码/链接（链接仅放行 http/https）。"""
    text = _html.escape(text, quote=False)

    def _link(m):
        label, url = m.group(1), m.group(2)
        if not re.match(r"^https?://", url):
            return label
        return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{label}</a>'

    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", _link, text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text


def render_markdown(md: str) -> str:
    """把法律文本 Markdown 渲染为 HTML（覆盖项目实际用到的子集）。"""
    if not md:
        return ""
    lines = md.replace("\r\n", "\n").split("\n")
    out = []
    para = []
    list_tag: Optional[str] = None
    i = 0

    def flush_para():
        if para:
            out.append("<p>" + _inline(" ".join(para)) + "</p>")
            para.clear()

    def close_list():
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None

    def open_list(tag):
        nonlocal list_tag
        if list_tag != tag:
            close_list()
            out.append(f"<{tag}>")
            list_tag = tag

    while i < len(lines):
        raw = lines[i]
        s = raw.strip()

        # 表格：当前行是表头且下一行是分隔行
        if (s.startswith("|") and i + 1 < len(lines)
                and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip())):
            flush_para()
            close_list()
            header = [c.strip() for c in s.strip("|").split("|")]
            out.append("<table><thead><tr>"
                       + "".join(f"<th>{_inline(c)}</th>" for c in header)
                       + "</tr></thead><tbody>")
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells)
                           + "</tr>")
                i += 1
            out.append("</tbody></table>")
            continue

        if s.startswith("#"):
            flush_para()
            close_list()
            level = min(len(s) - len(s.lstrip("#")), 4)
            out.append(f"<h{level}>{_inline(s[level:].strip())}</h{level}>")
        elif s in ("---", "***", "___"):
            flush_para()
            close_list()
            out.append("<hr>")
        elif s.startswith(">"):
            flush_para()
            close_list()
            out.append(f"<blockquote>{_inline(s.lstrip('>').strip())}</blockquote>")
        elif re.match(r"^[-*]\s+", s):
            flush_para()
            open_list("ul")
            out.append("<li>" + _inline(re.sub(r"^[-*]\s+", "", s)) + "</li>")
        elif re.match(r"^\d+[.)]\s+", s):
            flush_para()
            open_list("ol")
            out.append("<li>" + _inline(re.sub(r"^\d+[.)]\s+", "", s)) + "</li>")
        elif not s:
            flush_para()
            close_list()
        else:
            close_list()
            para.append(s)
        i += 1

    flush_para()
    close_list()
    return "\n".join(out)


def load_legal_doc(slug: str) -> Optional[Tuple[str, str]]:
    """按 slug 读取并渲染。返回 (标题, HTML) 或 None（未知 slug / 文件缺失）。"""
    doc = LEGAL_DOCS.get(slug)
    if not doc:
        return None
    filename, title = doc
    path = os.path.join(LEGAL_DIR, filename)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return title, render_markdown(f.read())


_LEGAL_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} · 拾阶而上</title>
<style>
 :root {{ --text:#1a1a1a; --sub:#6b6b6b; --accent:#22B8A6; --border:#e8e6e1; }}
 * {{ box-sizing:border-box; }}
 body {{ margin:0; padding:20px 16px 60px; background:#F6FAF9; color:var(--text);
        font-family:ui-sans-serif,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
        line-height:1.75; font-size:15px; }}
 .wrap {{ max-width:760px; margin:0 auto; background:#fff; border-radius:16px;
          padding:24px 20px 40px; box-shadow:0 1px 3px rgba(0,0,0,.06); }}
 h1 {{ font-size:1.3rem; margin:0 0 6px; }}
 h2 {{ font-size:1.08rem; margin:26px 0 10px; padding-left:10px;
       border-left:4px solid var(--accent); }}
 h3 {{ font-size:1rem; margin:20px 0 8px; }}
 h4 {{ font-size:.95rem; margin:16px 0 6px; color:var(--sub); }}
 p {{ margin:10px 0; }}
 ul, ol {{ padding-left:22px; margin:10px 0; }}
 li {{ margin:5px 0; }}
 hr {{ border:none; border-top:1px solid var(--border); margin:22px 0; }}
 blockquote {{ margin:12px 0; padding:10px 14px; background:#E6F8F4;
               border-radius:10px; color:#0f6b60; font-size:.92rem; }}
 table {{ width:100%; border-collapse:collapse; margin:14px 0; font-size:.9rem; }}
 th {{ background:#EEF5F3; text-align:left; padding:8px 10px; font-weight:600; }}
 td {{ padding:8px 10px; border-top:1px solid var(--border); vertical-align:top; }}
 code {{ background:#EEF5F3; padding:1px 5px; border-radius:5px; font-size:.9em; }}
 a {{ color:var(--accent); }}
 .top {{ display:flex; justify-content:space-between; align-items:center;
         margin-bottom:14px; gap:10px; flex-wrap:wrap; }}
 .top a {{ font-size:.85rem; text-decoration:none; }}
 .ver {{ font-size:.8rem; color:var(--sub); }}
 .empty {{ color:var(--sub); text-align:center; padding:40px 0; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <a href="/parent">← 返回</a>
    <span class="ver">拾阶而上 · {title} · {version}</span>
  </div>
  {body}
</div>
</body>
</html>"""


def render_legal_page(slug: str, version: str = None) -> Optional[str]:
    """渲染完整页面 HTML；未知 slug 或文本缺失返回 None（由路由给 404）。"""
    doc = load_legal_doc(slug)
    if not doc:
        return None
    title, body = doc
    return _LEGAL_PAGE.format(title=title, body=body,
                              version=version or CONSENT_VERSION)
