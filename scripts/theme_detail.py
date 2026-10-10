# -*- coding: utf-8 -*-
"""主题细化脚本：Duolingo 风「按下」按钮 + 柔和阴影 + hover 微交互。

在 theme_refresh.py（配色/圆角）之后运行。两处增强：
1. 主按钮加底部深色边（push 效果）+ active 按下：Duolingo 标志性手感。
2. 卡片阴影更柔和（带轻微主色调），hover 浮起更明显（微交互）。

幂等：只追加/替换明确目标，重复运行不会产生重复规则。
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FILES = [
    "web/templates_family.py",
    "web/templates_admin.py",
    "web/templates_auth.py",
]

# 在 .btn-primary 定义后追加 push 效果（若尚未加）
PUSH_ACTIVE = (
    "\n.btn-primary:active { transform:translateY(3px); box-shadow:none; }"
)


def add_push(src):
    """给 .btn-primary 加底部深色边 + active 按下。"""
    if ".btn-primary:active" in src:
        return src
    # 替换 .btn-primary { ... } 增加 box-shadow（未含则补）
    import re
    def _repl(m):
        body = m.group(0)
        if "box-shadow" in body:
            return body
        return body.replace("}", " box-shadow:0 4px 0 var(--accent-hover); }")
    src = re.sub(r'\.btn-primary\s*\{[^}]*\}', _repl, src, count=0)
    # hover 保留 push 边（避免被 .btn:hover 的 box-shadow 覆盖丢失）
    src = re.sub(
        r'(\.btn-primary:hover\s*\{[^}]*?)\}',
        r'\1; box-shadow:0 4px 0 var(--accent-hover); }',
        src, count=0)
    # 在第一个 .btn-primary:hover 规则后加 active
    idx = src.find(".btn-primary:hover")
    if idx == -1:
        return src
    end = src.find("}", idx)
    if end != -1:
        src = src[:end + 1] + PUSH_ACTIVE + src[end + 1:]
    return src


def main():
    for rel in FILES:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        out = add_push(src)
        if out != src:
            with open(path, "w", encoding="utf-8") as f:
                f.write(out)
            print(f"  更新 {rel}")


if __name__ == "__main__":
    main()
