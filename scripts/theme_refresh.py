# -*- coding: utf-8 -*-
"""主题升级脚本：暖橙 → Duolingo 风明亮青绿（含圆角/阴影细化）。

设计目标（用户选定「柔和圆润 + 明亮活泼 + 适合学生/家长」）：
- 主色：暖橙 #e07b4b → 明亮青绿 #22B8A6（「拾阶而上」的成长感，活泼但不浮夸）
- 圆角：卡片 10px → 16px、按钮 8px → 12px（Duolingo 式大圆角）
- 阴影：更柔和、带轻微主色调，避免生硬

用法：python scripts/theme_refresh.py（幂等，可重复运行；只替换明确的旧值）
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 色值映射（旧 → 新）。只替换这些明确值，避免误伤其他颜色。
COLOR_MAP = {
    # 主色（暖橙 → 明亮青绿）
    "#e07b4b": "#22B8A6",
    "#d06a3a": "#189A8A",
    "#fef3ed": "#E6F8F4",
    # 背景轻微提亮，融入青色调，更清新
    "#f8f7f4": "#F6FAF9",
    "#f1f0ec": "#EEF5F3",
}

# 圆角规则（按字面替换）。卡片大圆角，按钮中圆角。
RADIUS_MAP = {
    "border-radius: 10px": "border-radius: 16px",
    "border-radius:10px": "border-radius:16px",
    "border-radius: 8px": "border-radius: 12px",
    "border-radius:8px": "border-radius:12px",
}

FILES = [
    "web/templates_family.py",
    "web/templates_admin.py",
    "web/templates_auth.py",
    "web/templates_shared.py",
    "web/shared.py",
    "report_templates.py",
    "static/css/shared.css",
]


def main():
    changed = 0
    for rel in FILES:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        out = src
        for old, new in COLOR_MAP.items():
            out = out.replace(old, new)
        for old, new in RADIUS_MAP.items():
            out = out.replace(old, new)
        if out != src:
            with open(path, "w", encoding="utf-8") as f:
                f.write(out)
            n_color = sum(src.count(k) for k in COLOR_MAP)
            n_radius = sum(src.count(k) for k in RADIUS_MAP)
            print(f"  更新 {rel}（色值 {n_color} 处，圆角 {n_radius} 处）")
            changed += 1
    print(f"完成：{changed} 个文件已更新")


if __name__ == "__main__":
    main()
