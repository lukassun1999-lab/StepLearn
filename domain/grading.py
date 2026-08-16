#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在线练习判分归一化。

此前提交端点用裸 `a.upper() == b.upper()` 精确匹配，以下场景全部误判错：
- 全角字母/数字（Ａ vs A，手机输入法常见）
- 多选答案顺序（"BA" vs "AB"、"A,B" vs "AB"）
- 分隔符差异（中文逗号/顿号/分号/空格混用）
- 首尾标点（句号、引号）

normalize_answer 统一清洗后比较；is_answer_correct 为唯一判分入口。
"""

import re
import unicodedata

# 答案中常见的分隔符（全/半角）
_SEPARATORS = re.compile(r"[,，、;；/\\\s]+")
# 首尾标点（含中英文句号、引号、括号）
_EDGE_PUNCT = "。.,，;；:：!！?？\"'“”‘’()（）[]【】"


def normalize_answer(text, multiselect: bool = None) -> str:
    """归一化答案文本用于比较。

    - None → 空串
    - NFKC 归一化（全角→半角：Ａ→A、１→1）、大写、弯撇号统一
    - 多选（multiselect=True 或答案含分隔符的 A-F 字母组合）：
      去分隔符后排序，顺序无关
    - 其余答案：分隔符折叠为单空格、去首尾标点（内部标点保留）

    自动识别要求「含分隔符」（如 A,B）——单词间不会出现逗号顿号，
    以此区分多选与 DAB/BAD 类 A-F 内单词；无分隔符的 "BA"/"AB"
    由题型标志（question_type 含「多选」）判定。
    """
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", str(text)).upper()
    s = s.replace("\u2019", "'")  # 弯撇号（don't / Tom's）统一为直撇号

    compact = _SEPARATORS.sub("", s)
    if multiselect is None:
        multiselect = (_SEPARATORS.search(s) is not None
                       and re.fullmatch(r"[A-F]+", compact) is not None)
    if multiselect:
        return "".join(sorted(compact))

    s = _SEPARATORS.sub(" ", s).strip(_EDGE_PUNCT + " \t")
    return re.sub(r"\s+", " ", s)


def is_answer_correct(student_answer, correct_answer, multiselect: bool = None) -> bool:
    """判分：双侧归一化后比较。空答案一律判错。"""
    a = normalize_answer(student_answer, multiselect)
    b = normalize_answer(correct_answer, multiselect)
    if not a or not b:
        return False
    return a == b
