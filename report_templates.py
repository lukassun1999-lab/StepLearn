#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报告 HTML 模板
生成首次诊断报告、专属练习题、批改反馈、家长周报。
所有报告均为手机友好的独立 HTML 文件。
"""

import os
import re
from datetime import date

from db import get_teacher_profile


# ═══════════════════════════════════════════════════
# 题干内嵌选项判断（与 question_gen._options_embedded 同规则，避免跨模块耦合）
# ═══════════════════════════════════════════════════
_OPTION_INLINE_RE = re.compile(r"[A-Da-d][.、)）:：]\s*\S")


def _text_has_inline_options(text: str) -> bool:
    """题干是否已内嵌 ≥2 个 A-D 选项（要求 ≥2 处匹配，避免 'tired.' 之类误报）。"""
    return len(_OPTION_INLINE_RE.findall(text or "")) >= 2


# ═══════════════════════════════════════════════════
# CJK font for xhtml2pdf (PDF export only)
# xhtml2pdf renders every Chinese glyph as a black box (tofu) unless a CJK
# font is registered with reportlab's pdfmetrics. We register one up front
# and reference it by name in CSS — this avoids xhtml2pdf's @font-face URL
# fetch (which copies to a temp file and can fail on permission/sandbox).
# ═══════════════════════════════════════════════════

_CJK_FONT_CANDIDATES = [
    "simhei.ttf",   # 黑体 — clean single TTF, renders well
    "Deng.ttf",     # 等线 — Windows 10/11 default
    "simkai.ttf",   # 楷体
    "simfang.ttf",  # 仿宋
    "STSONG.TTF",   # 华文宋体
    "msyh.ttc",     # 微软雅黑 (collection)
    "simsun.ttc",   # 宋体 (collection, fallback)
]

_CJK_REGISTERED = False


def _ensure_cjk_font() -> str:
    """Register a CJK font with reportlab. Returns the family name to use in
    CSS ('CJK'), or '' if no CJK font could be registered (best-effort tofu)."""
    global _CJK_REGISTERED
    if _CJK_REGISTERED:
        return "CJK"
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        if "CJK" in pdfmetrics.getRegisteredFontNames():
            _CJK_REGISTERED = True
            return "CJK"
        fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        for name in _CJK_FONT_CANDIDATES:
            path = os.path.join(fonts_dir, name)
            if os.path.exists(path):
                try:
                    pdfmetrics.registerFont(TTFont("CJK", path))
                    _CJK_REGISTERED = True
                    return "CJK"
                except Exception:
                    continue
    except Exception:
        pass
    return ""


def _base_html(title: str, body: str, css_extra: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
:root {{
  --bg: #f8f7f4; --bg-alt: #f1f0ec; --card: #fff;
  --text: #1a1a1a; --text-alt: #37352f; --sub: #6b6b6b; --mute: #9b9b9b;
  --accent: #e07b4b; --accent-light: #fef3ed;
  --green: #0f7b4e; --green-light: #effaf3;
  --red: #d93a46; --red-light: #fef4f4;
  --blue: #4b8dc7; --blue-light: #eef5fb;
  --border: #e8e6e1; --shadow-sm: 0 1px 2px rgba(0,0,0,.03);
  --shadow: 0 1px 3px rgba(0,0,0,.06), 0 2px 8px rgba(0,0,0,.02);
  --shadow-lg: 0 4px 24px rgba(0,0,0,.08);
  --radius: 8px;
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  font-family: ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  background:var(--bg); color:var(--text-alt); line-height:1.6;
  padding:24px 16px; max-width:800px; margin:0 auto; font-size:.875rem;
}}
.header {{
  text-align:center; padding:40px 0 32px;
  border-bottom:2px solid var(--accent); margin-bottom:32px;
}}
.header h1 {{ font-size:1.5rem; color:var(--accent); margin-bottom:8px; font-weight:700; }}
.header .sub {{ color:var(--sub); font-size:.9rem; }}
.section {{ margin:28px 0; }}
.section h2 {{
  font-size:1.1rem; border-left:4px solid var(--accent);
  padding-left:12px; margin-bottom:14px; font-weight:600; color:var(--text);
}}
.card {{
  background:var(--card); border:none;
  border-radius:10px; padding:20px; margin-bottom:14px;
  box-shadow:var(--shadow);
}}
.card h3 {{ font-size:1rem; margin-bottom:8px; font-weight:600; color:var(--text); }}
.card p {{ color:var(--sub); font-size:.85rem; margin-bottom:6px; }}
table {{ width:100%; border-collapse:collapse; font-size:.85rem; margin:12px 0; }}
th {{ background:var(--bg-alt); color:var(--sub); padding:8px 12px; text-align:left; font-weight:600; }}
td {{ padding:8px 12px; border-bottom:1px solid var(--border); color:var(--text-alt); }}
.badge {{ display:inline-block; padding:3px 10px; border-radius:100px; font-size:.75rem; font-weight:600; }}
.badge-high {{ background:var(--red-light); color:var(--red); }}
.badge-mid {{ background:var(--accent-light); color:var(--accent); }}
.badge-low {{ background:var(--green-light); color:var(--green); }}
.badge-mastered {{ background:var(--green-light); color:var(--green); }}
.badge-practicing {{ background:var(--accent-light); color:var(--accent); }}
.priority-list {{ list-style:none; padding:0; }}
.priority-list li {{
  padding:10px 14px; margin:6px 0; background:var(--card);
  border:none; border-radius:8px; box-shadow:var(--shadow-sm);
  display:flex; justify-content:space-between; align-items:center;
}}
.module-card {{
  background:var(--card); border:none;
  border-radius:10px; padding:18px; margin-bottom:10px; box-shadow:var(--shadow-sm);
}}
.module-card h4 {{ color:var(--accent); margin-bottom:6px; }}
.module-card .meta {{ color:var(--sub); font-size:.8rem; }}
.schedule-table td:first-child {{ font-weight:600; white-space:nowrap; color:var(--accent); }}
.quote-box {{
  background:var(--blue-light); border-left:3px solid var(--blue);
  padding:16px 20px; border-radius:6px; margin:16px 0;
  font-style:italic; color:var(--text);
}}
.cta-box {{
  background:var(--accent-light); border-left:3px solid var(--accent);
  padding:16px 20px; border-radius:6px; margin:16px 0;
}}
.highlight-num {{ font-size:2rem; font-weight:700; color:var(--accent); }}
.footer {{
  text-align:center; color:var(--mute); font-size:.75rem;
  margin-top:48px; padding-top:24px; border-top:1px solid var(--border);
}}
@media print {{
  body {{ background:#fff; padding:0; }}
  .card {{ box-shadow:none; break-inside:avoid; }}
}}
{css_extra}
</style>
</head>
<body>
{body}
</body>
</html>"""


# ═══════════════════════════════════════════════════
# 首次诊断报告
# ═══════════════════════════════════════════════════

def _plan_text(value, fallback=""):
    """报告文本字段兜底：LLM 可能返回 dict（实测 parent_guide 返回了结构化对象），
    统一转可读多行文本，避免 Python repr 直接渲染到页面。"""
    if isinstance(value, str):
        return value or fallback
    if isinstance(value, dict):
        labels = {"boarding_advice": "住校", "day_student_advice": "走读",
                  "time_investment": "时间投入", "monitoring": "效果跟进",
                  "emotional_support": "情绪支持"}
        lines = []
        for k, v in value.items():
            if isinstance(v, (str, int, float)):
                lines.append(f"{labels.get(k, k)}：{v}".replace("\n", " "))
        text = "<br>".join(lines) if lines else ""
        return text or fallback
    return fallback


def render_diagnostic_report(
    student: dict,
    ocr_confidence: float,
    mistakes: list,
    weak_points: list,
    learning_plan: dict,
    cause_profile: dict = None,
) -> str:
    """Generate the first diagnostic report HTML."""

    teacher = get_teacher_profile()
    teacher_name = teacher.get("teacher_name") or teacher.get("institution_name") or "拾阶而上"
    teacher_meta = " · ".join(filter(None, [teacher.get("teaching_years", ""), teacher.get("specialty", "")]))
    teacher_html = f"""
    <div class="section" style="background:var(--accent-light);border-radius:10px;padding:14px;margin-bottom:18px;">
      <div style="display:flex;align-items:center;gap:12px;">
        <div style="flex:1;">
          <div style="font-weight:700;color:var(--accent);">{teacher_name}</div>
          <div style="font-size:.85em;color:var(--sub);">{teacher_meta or 'AI + 老师双师辅导'}</div>
          {f'<div style="font-size:.85em;color:var(--sub);margin-top:4px;">{teacher.get("philosophy", "")}</div>' if teacher.get("philosophy") else ''}
        </div>
      </div>
    </div>
    """
    # Weak point severity bars
    wp_rows = ""
    for i, wp in enumerate(weak_points):
        severity = wp.get("severity", "中")
        badge_cls = {"高": "badge-high", "中": "badge-mid", "低": "badge-low"}.get(severity, "badge-mid")
        wp_rows += f"""
        <li>
          <span>{i+1}. {wp.get('knowledge_point', '?')}</span>
          <span class="badge {badge_cls}">{severity}优先级</span>
        </li>"""

    # Mistake detail cards — full question + wrong/correct answers + explanation
    mistake_cards = ""
    for i, m in enumerate(mistakes[:20]):
        kps = m.get("knowledge_points", [])
        if isinstance(kps, str):
            try:
                import json as _json
                kps = _json.loads(kps)
            except Exception:
                kps = [kps] if kps else []
        kp_tags = "".join(
            f'<span style="display:inline-block;background:var(--bg);color:var(--sub);border-radius:100px;padding:2px 10px;font-size:.7rem;margin-right:4px;margin-bottom:4px;">{kp}</span>'
            for kp in kps[:4]
        )
        question = m.get('question_text', '') or m.get('question', '') or ''
        user_ans = m.get('user_answer', '') or '未识别'
        correct_ans = m.get('correct_answer', '') or ''
        explanation = m.get('explanation', '') or m.get('error_reason', '') or ''
        qtype = m.get('question_type', '')
        difficulty = m.get('difficulty', '')
        error_reason = m.get('error_reason', '')

        mistake_cards += f"""
        <div style="background:var(--card);border-radius:12px;padding:16px;margin-bottom:14px;border:1px solid var(--border);">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
            <div style="font-weight:700;font-size:.95rem;">第 {i+1} 题</div>
            <div style="display:flex;gap:6px;">
              {f'<span style="background:var(--bg);color:var(--sub);border-radius:100px;padding:2px 10px;font-size:.7rem;">{qtype}</span>' if qtype else ''}
              {f'<span style="background:var(--bg);color:var(--sub);border-radius:100px;padding:2px 10px;font-size:.7rem;">难度 {difficulty}</span>' if difficulty else ''}
            </div>
          </div>
          <div style="background:var(--bg);border-radius:8px;padding:12px;margin-bottom:10px;white-space:pre-wrap;font-size:.9rem;line-height:1.7;color:var(--text);">{question}</div>
          <div style="display:flex;gap:10px;margin-bottom:10px;">
            <div style="flex:1;background:#fef4f4;border-radius:8px;padding:8px 12px;">
              <div style="font-size:.72rem;color:#d93a46;font-weight:600;margin-bottom:2px;">✗ 你的答案</div>
              <div style="font-size:.9rem;color:#d93a46;font-weight:600;">{user_ans}</div>
            </div>
            <div style="flex:1;background:#effaf3;border-radius:8px;padding:8px 12px;">
              <div style="font-size:.72rem;color:#0f7b4e;font-weight:600;margin-bottom:2px;">✓ 正确答案</div>
              <div style="font-size:.9rem;color:#0f7b4e;font-weight:600;">{correct_ans}</div>
            </div>
          </div>
          {f'''<div style="background:var(--accent-light);border-radius:8px;padding:12px;margin-bottom:10px;">
            <div style="font-size:.72rem;color:var(--accent);font-weight:600;margin-bottom:4px;">📖 解析</div>
            <div style="font-size:.85rem;line-height:1.7;color:var(--text);">{explanation}</div>
          </div>''' if explanation else ''}
          <div style="display:flex;gap:4px;flex-wrap:wrap;align-items:center;">
            {kp_tags}
            {f'<span style="display:inline-block;background:#fef4f4;color:#d93a46;border-radius:100px;padding:2px 10px;font-size:.7rem;">{error_reason}</span>' if error_reason else ''}
          </div>
        </div>"""

    # Learning modules
    module_cards = ""
    for mod in learning_plan.get("modules", []):
        module_cards += f"""
        <div class="module-card">
          <h4>📚 {mod.get('name', '?')}</h4>
          <div class="meta">
            每周 {mod.get('weekly_time_minutes', '?')} 分钟 |
            每日词汇 {mod.get('daily_word_count', 0)} 个 |
            重点：{mod.get('focus', '待定')}
          </div>
        </div>"""

    # Weekly schedule
    schedule = learning_plan.get("weekly_schedule", {})
    schedule_rows = ""
    for slot, desc in schedule.items():
        label = {"weekday_morning": "周一至周五 早间", "weekday_evening": "周一至周五 晚间",
                 "saturday_morning": "周六上午", "saturday_afternoon": "周六下午",
                 "sunday": "周日"}.get(slot, slot)
        schedule_rows += f"<tr><td>{label}</td><td>{desc}</td></tr>"

    # Diagnosis report
    diagnosis = learning_plan.get("diagnosis_report", {})
    diagnosis_html = ""
    if diagnosis and diagnosis.get("conclusion"):
        c = diagnosis["conclusion"]
        findings = "\n".join(
            f"<li>{f}</li>" for f in c.get("core_findings", [])
        )
        diagnosis_html = f"""
        <div class="section">
          <h2>🔬 AI 个性化诊断</h2>
          <div class="card">
            {"<h3>核心发现</h3><ul>" + findings + "</ul>" if findings else ""}
            <div style="display:flex; flex-wrap:wrap; gap:12px; margin-top:12px;">
              {f'<div style="flex:1; min-width:180px; background:var(--bg); border-radius:8px; padding:12px;"><div style="font-size:.8em; color:var(--sub);">短期（1个月）</div><div style="font-size:.9em;">{c.get("short_term", "")}</div></div>' if c.get("short_term") else ""}
              {f'<div style="flex:1; min-width:180px; background:var(--bg); border-radius:8px; padding:12px;"><div style="font-size:.8em; color:var(--sub);">中期（1学期）</div><div style="font-size:.9em;">{c.get("medium_term", "")}</div></div>' if c.get("medium_term") else ""}
              {f'<div style="flex:1; min-width:180px; background:var(--bg); border-radius:8px; padding:12px;"><div style="font-size:.8em; color:var(--sub);">长期（1年）</div><div style="font-size:.9em;">{c.get("long_term", "")}</div></div>' if c.get("long_term") else ""}
            </div>
            {f'<p style="margin-top:12px; color:var(--red); font-size:.9em;">⚠️ {c.get("warning")}</p>' if c.get("warning") else ""}
          </div>
        </div>
        """

    # Parent growth tasks
    parent_tasks = learning_plan.get("parent_growth_tasks", [])
    parent_tasks_html = ""
    if parent_tasks:
        task_cards = "\n".join(
            f"""
            <div class="card" style="border-left:4px solid var(--accent);">
              <h3>第 {t.get('week', '?')} 周 · {t.get('theme', '?')} · {t.get('title', '?')}</h3>
              <p><strong>任务：</strong>{t.get('task', '')}</p>
              <p><strong>示例：</strong>{t.get('example', '')}</p>
              <p><strong>目标：</strong>{t.get('goal', '')}</p>
            </div>
            """
            for t in parent_tasks
        )
        parent_tasks_html = f"""
        <div class="section">
          <h2>👨‍👩‍👧 家长成长任务包（4 周）</h2>
          <p style="color:var(--sub); font-size:.9em; margin-bottom:12px;">
            你不是监工，你是孩子最好的脚手架。每周一个微练习，逐步从“观察者”成长为“肯定者”。
          </p>
          {task_cards}
        </div>
        """

    # Motivation cards (AI generated + data-driven achievements)
    motivation_cards = learning_plan.get("motivation_cards", [])
    mastered_count = sum(1 for m in mistakes if m.get("consecutive_correct", 0) >= 2)
    mastered_kps = set()
    for m in mistakes:
        if m.get("consecutive_correct", 0) >= 2:
            for kp in m.get("knowledge_points", []):
                mastered_kps.add(kp)
    data_achievements = []
    if mastered_kps:
        kp_list_str = ", ".join(sorted(mastered_kps)[:5])
        more = f"等 {len(mastered_kps)} 个" if len(mastered_kps) > 5 else ""
        data_achievements.append({
            "title": "🎯 知识点突破",
            "content": f"已稳住 {len(mastered_kps)} 个知识点：{kp_list_str}{more}。"
        })
    if mastered_count > 0:
        data_achievements.append({
            "title": "✅ 错题攻克",
            "content": f"累计 {mastered_count} 道错题已被连续答对 2 次，正式移出薄弱清单。"
        })

    all_cards = motivation_cards + data_achievements
    motivation_html = ""
    if all_cards:
        cards = "\n".join(
            f"""
            <div class="card" style="border-left:4px solid var(--green);">
              <h3>{c.get('title', '激励卡')}</h3>
              <p>{c.get('content', '')}</p>
            </div>
            """
            for c in all_cards
        )
        motivation_html = f"""
        <div class="section">
          <h2>💌 动机卡片与成就</h2>
          {cards}
        </div>
        """

    # Metacognitive review
    review = learning_plan.get("metacognitive_review", {})
    review_html = ""
    if review:
        child_q = "\n".join(f"<li>{q}</li>" for q in review.get("child_reflection", []))
        parent_q = "\n".join(f"<li>{q}</li>" for q in review.get("parent_observation", []))
        error_cats = " ".join(
            f"<span class='badge' style='background:var(--bg);color:var(--sub);margin-right:6px;'>{cat}</span>"
            for cat in review.get("error_categories", [])
        )
        review_html = f"""
        <div class="section">
          <h2>🧠 元认知复盘表</h2>
          <div class="card">
            {f'<h3>孩子反思区</h3><ul>{child_q}</ul>' if child_q else ''}
            {f'<h3 style="margin-top:12px;">家长观察区</h3><ul>{parent_q}</ul>' if parent_q else ''}
            {f'<h3 style="margin-top:12px;">错误类型统计</h3><p>{error_cats}</p>' if error_cats else ''}
            {f'<p style="margin-top:12px; color:var(--accent); font-size:.9em;">📌 {review.get("adjustment_rules", "")}</p>' if review.get("adjustment_rules") else ''}
          </div>
        </div>
        """

    # 错因画像（错因因果链：核心卡点 + 家长一句话 + 因果链 + 根因聚焦）
    cause_html = ""
    if cause_profile and cause_profile.get("primary_cause"):
        cause_labels = {"vocab": "单词不认识", "grammar": "语法规则没掌握",
                        "syntax": "长句拆不开", "discourse": "读不懂文章逻辑",
                        "careless": "看题不仔细"}
        primary = cause_profile.get("primary_cause", "")
        primary_label = cause_labels.get(primary, primary)
        plain = cause_profile.get("plain_language") or ""
        chain = cause_profile.get("cause_chain") or []
        chain_html = ""
        if chain:
            chain_parts = []
            for link in chain[:4]:
                chain_parts.append(
                    f'<span style="background:var(--accent-light);color:var(--accent-hover);'
                    f'border-radius:100px;padding:3px 10px;font-size:.75rem;">{link.get("from", "?")}</span>'
                    f'<span style="color:var(--accent);margin:0 4px;">→</span>'
                    f'<span style="background:var(--bg);color:var(--sub);border-radius:100px;'
                    f'padding:3px 10px;font-size:.75rem;">{link.get("to", "?")}</span>'
                )
            chain_html = (f'<div style="margin-top:12px;display:flex;align-items:center;'
                          f'flex-wrap:wrap;gap:2px;">{"".join(chain_parts)}</div>')
        kps = cause_profile.get("priority_kps") or []
        kp_tags = "".join(
            f'<span style="display:inline-block;background:var(--bg);color:var(--text);'
            f'border:1px solid var(--border);border-radius:100px;padding:3px 12px;'
            f'font-size:.8rem;margin-right:6px;margin-bottom:6px;">🎯 {kp}</span>'
            for kp in kps[:3]
        )
        cause_html = f"""
        <div class="section">
          <h2>🔍 错因画像</h2>
          <div class="card" style="border-left:4px solid var(--accent);">
            {f'<p style="font-size:.95rem;font-weight:700;color:var(--text);margin-bottom:8px;">核心卡点：{primary_label}</p>' if primary_label else ''}
            {f'<p style="font-size:.9rem;line-height:1.8;color:var(--text-alt);margin-bottom:8px;">{plain}</p>' if plain else ''}
            {chain_html}
            {f'<div style="margin-top:14px;"><div style="font-size:.78rem;color:var(--sub);margin-bottom:6px;">本周按因果链聚焦（先补根因，次生问题会自己松动）：</div>{kp_tags}</div>' if kp_tags else ''}
          </div>
        </div>
        """

    body = f"""
<div class="header">
  <h1>📋 首次诊断报告</h1>
  <div class="sub">{student.get('name', '同学')} · {student.get('grade', '')} · {date.today().isoformat()}</div>
</div>

{teacher_html}

<div class="section">
  <h2>📊 诊断概况</h2>
  <div class="card" style="display:flex; justify-content:space-around; text-align:center; flex-wrap:wrap; gap:16px;">
    <div><div class="highlight-num">{len(mistakes)}</div><div style="color:var(--sub);">发现提升点</div></div>
    <div><div class="highlight-num">{len(weak_points)}</div><div style="color:var(--sub);">重点成长区</div></div>
    <div><div class="highlight-num">{ocr_confidence:.0%}</div><div style="color:var(--sub);">OCR 准确率</div></div>
    <div><div class="highlight-num">{student.get('english_score', '-')}</div><div style="color:var(--sub);">当前分数</div></div>
  </div>
</div>

{cause_html}

{diagnosis_html}

<!-- Learning Style Radar -->
{(
    '<div class="section"><h2>🧠 学习风格画像</h2>'
    f'<div class="card" style="text-align:center;">{_render_learning_style_radar(learning_plan.get("diagnosis_report", {}).get("learning_style", {}))}</div>'
    '<p style="color:var(--sub);font-size:.85em;margin-top:8px;">此画像由 AI 基于错题分析和学生问卷生成，用于定制学习方案。</p>'
    '</div>'
) if learning_plan.get("diagnosis_report", {}).get("learning_style") else ''}

<div class="section">
  <h2>📝 错题详解</h2>
  <p style="color:var(--sub); font-size:.85em; margin-bottom:12px;">每道错题都附有你的答案、正确答案和详细解析</p>
  {mistake_cards}
</div>

{motivation_html}

{review_html}

<div class="section">
  <h2>🌱 接下来重点关注</h2>
  <ul class="priority-list">{wp_rows}</ul>
</div>

<div class="section">
  <h2>🎯 个性化学习方案</h2>

  <h3 style="margin-top:16px;">每周时间安排</h3>
  <table class="schedule-table">
    {schedule_rows}
  </table>

  <h3 style="margin-top:16px;">学习模块</h3>
  {module_cards}

  <div class="card">
    <h3>📌 每天一小步，效果看得见</h3>
    <p><strong>住校：</strong>{learning_plan.get('minimum_standard', {}).get('boarding', '每日词汇+1篇阅读')}</p>
    <p><strong>走读：</strong>{learning_plan.get('minimum_standard', {}).get('day_student', '每晚词汇+听力训练')}</p>
  </div>
</div>

<div class="section">
  <h2>💬 想对孩子说的话</h2>
  <div class="quote-box">
    <p>{_plan_text(learning_plan.get('motivation_message'), '每一份试卷都是一次成长的机会。孩子已经在路上了，我们一起陪他走下去。')}</p>
  </div>
</div>

{parent_tasks_html}

<div class="section">
  <h2>💛 你可以试试这样做</h2>
  <div class="cta-box">
    <p>{_plan_text(learning_plan.get('parent_guide'), '请每周六上午拍照发一张孩子最近做过的英语卷子，剩下的交给我们。')}</p>
  </div>
</div>

<div class="footer">
  <p>拾阶而上 · AI 驱动个性化学习 · 按周付费，随时可停</p>
  <p>报告生成时间：{date.today().isoformat()}</p>
</div>"""

    return _base_html(f"首次诊断报告 - {student.get('name', '同学')}", body)


# ═══════════════════════════════════════════════════
# 专属练习题
# ═══════════════════════════════════════════════════

def render_exercise_sheet(student_name: str, questions: list, week_start: str = "") -> str:
    """Generate practice exercise HTML."""

    q_blocks = ""
    for i, q in enumerate(questions):
        opts_html = ""
        # P3 质量硬化后题干已内嵌选项（A. xx B. xx ...）→ 不再重复渲染选项区，
        # 否则选项出现两次。仅当题干未内嵌且 options 有实质内容时才补渲染；
        # 裸字母（A/B/C/D 无文本）是 LLM 脏数据，直接跳过。
        if not _text_has_inline_options(str(q.get("question_text") or "")):
            for opt in (q.get("options") or []):
                if isinstance(opt, dict):
                    label = str(opt.get("key") or "").strip()
                    text = str(opt.get("text") or "").strip()
                else:
                    label, text = "", str(opt).strip()
                if not text or re.fullmatch(r"[A-Da-d]", text):
                    continue
                shown = f"{label}. {text}" if label else text
                opts_html += f"<div style='padding:6px 12px; margin:4px 0; background:var(--bg); border-radius:6px;'>{shown}</div>"

        kps = ", ".join(q.get("knowledge_points") or [])
        passage_html = ""
        if q.get("passage"):
            passage_html = f"""
            <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:12px 14px;margin:12px 0;white-space:pre-wrap;line-height:1.8;">
              <div style="font-size:.72rem;color:var(--sub);font-weight:600;margin-bottom:4px;">📄 阅读短文</div>
              {q.get("passage")}
            </div>"""
        q_blocks += f"""
        <div class="card">
          <h3>第 {i+1} 题 <span style="font-weight:400;color:var(--sub);font-size:.85em;">{q.get('question_type', '')} · {kps}</span></h3>
          {passage_html}
          <div style="white-space:pre-wrap; margin:12px 0; line-height:1.9;">{q.get('question_text', '')}</div>
          {opts_html}
        </div>"""

    body = f"""
<div class="header">
  <h1>📝 专属练习题</h1>
  <div class="sub">{student_name} · {week_start or date.today().isoformat()} 起</div>
</div>

<div class="cta-box" style="margin-bottom:24px;">
  <p>这些题目是 AI 根据你<b>最近的试卷</b>为你定制的——只练最需要的地方，不浪费时间。共 {len(questions)} 题，约 30-40 分钟完成。</p>
</div>

{q_blocks}

<div class="footer">
  <p>做完后拍个照就行，AI 会帮你批改，还会告诉你哪里进步了。</p>
</div>"""

    return _base_html(f"专属练习题 - {student_name}", body)


# ═══════════════════════════════════════════════════
# 作文批改报告
# ═══════════════════════════════════════════════════

def render_essay_review(student: dict, mistake: dict, review: dict) -> str:
    """渲染作文批改报告 HTML：逐句错误标注 + 四维评价 + 评分建议 + 优点 + 建议。"""
    errors = review.get("errors") or []
    error_rows = ""
    for i, e in enumerate(errors[:12]):
        etype = e.get("type", "")
        error_rows += f"""
        <div style="background:var(--card);border:1px solid var(--border);border-radius:10px;padding:12px 14px;margin-bottom:10px;">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
            <span style="background:var(--red-light);color:var(--red);border-radius:100px;padding:2px 10px;font-size:.7rem;font-weight:600;">{i + 1}. {etype}</span>
          </div>
          <div style="background:#fef4f4;border-radius:6px;padding:6px 10px;font-size:.9rem;margin-bottom:6px;white-space:pre-wrap;"><span style="color:var(--red);font-weight:600;">✗ </span>{e.get('quote', '')}</div>
          <div style="background:#effaf3;border-radius:6px;padding:6px 10px;font-size:.9rem;white-space:pre-wrap;"><span style="color:var(--green);font-weight:600;">✓ </span>{e.get('suggestion', '')}</div>
          <div style="font-size:.8rem;color:var(--sub);margin-top:6px;">{e.get('issue', '')}</div>
        </div>"""
    if not error_rows:
        error_rows = '<div class="card"><p style="color:var(--green);">这篇作文没有发现明显错误，继续保持！</p></div>'

    ev = review.get("evaluation") or {}
    ev_rows = "".join(
        f"""<div style="flex:1;min-width:150px;background:var(--bg);border-radius:8px;padding:10px 12px;">
          <div style="font-size:.75rem;color:var(--sub);font-weight:600;margin-bottom:4px;">{label}</div>
          <div style="font-size:.85rem;line-height:1.6;">{value}</div>
        </div>"""
        for label, value in (("内容完整性", ev.get("content")), ("结构逻辑", ev.get("structure")),
                             ("语言准确性", ev.get("language")), ("词汇丰富度", ev.get("vocabulary")))
        if value)
    score = review.get("score_suggestion") or {}
    strengths = "".join(f"<li>{s}</li>" for s in (review.get("strengths") or [])[:3])
    advices = "".join(f"<li>{a}</li>" for a in (review.get("advice") or [])[:3])

    body = f"""
<div class="header">
  <h1>📝 英语作文批改</h1>
  <div class="sub">{(student or {}).get('name', '同学')} · {(student or {}).get('grade', '')} · {date.today().isoformat()}</div>
</div>

<div class="section">
  <h2>📋 作文题目</h2>
  <div class="card" style="white-space:pre-wrap;line-height:1.8;">{mistake.get('question_text') or mistake.get('question') or '英语作文'}</div>
</div>

<div class="section">
  <h2>✍️ 学生作文</h2>
  <div class="card" style="white-space:pre-wrap;line-height:1.9;">{mistake.get('user_answer') or ''}</div>
</div>

<div class="section">
  <h2>🔍 逐句批注（{len(errors[:12])} 处）</h2>
  {error_rows}
</div>

<div class="section">
  <h2>📊 整体评价</h2>
  <div class="card">
    <div style="display:flex;gap:10px;flex-wrap:wrap;">{ev_rows}</div>
    {f'''<div style="margin-top:14px;background:var(--accent-light);border-radius:8px;padding:12px 14px;">
      <div style="font-size:.8rem;color:var(--sub);font-weight:600;margin-bottom:4px;">评分建议</div>
      <div style="font-size:1.05rem;font-weight:700;color:var(--accent-hover);">{score.get('band', '')}</div>
      <div style="font-size:.85rem;color:var(--text-alt);margin-top:4px;">{score.get('basis', '')}</div>
    </div>''' if score.get('band') else ''}
  </div>
</div>

{f'''
<div class="section">
  <h2>💛 值得肯定的地方</h2>
  <div class="card"><ul style="margin:0;padding-left:1.2em;line-height:2;">{strengths}</ul></div>
</div>

<div class="section">
  <h2>🎯 下次可以这样改</h2>
  <div class="card" style="border-left:4px solid var(--green);"><ul style="margin:0;padding-left:1.2em;line-height:2;">{advices}</ul></div>
</div>
''' if strengths or advices else ''}

<div class="footer">
  <p>拾阶而上 · AI 作文批改 · 修改示例供参考</p>
</div>"""
    return _base_html("英语作文批改", body)


# ═══════════════════════════════════════════════════
# 批改反馈
# ═══════════════════════════════════════════════════

def render_feedback_report(student_name: str, results: list, summary: dict,
                            week_start: str = "") -> str:
    """Generate grading feedback HTML."""

    total = summary.get("total", 0)
    correct = summary.get("correct", 0)
    accuracy = summary.get("accuracy", 0)

    result_rows = ""
    for i, r in enumerate(results):
        icon = "✅" if r.get("is_correct") else "❌"
        bg = "var(--green-light)" if r.get("is_correct") else "var(--red-light)"
        result_rows += f"""
        <div class="card" style="border-left:4px solid {'var(--green)' if r.get('is_correct') else 'var(--red)'};">
          <h3>{icon} 第 {i+1} 题</h3>
          <p><strong>你的答案：</strong>{r.get('student_answer', '?')}</p>
          <p><strong>正确答案：</strong>{r.get('correct_answer', '?')}</p>
          <p style="margin-top:8px;">{r.get('explanation', '')}</p>
          <p style="color:var(--sub); font-size:.85em;">{r.get('knowledge_point_feedback', '')}</p>
        </div>"""

    mastered = ", ".join(summary.get("mastered_points", [])) or "暂无"
    weak = ", ".join(summary.get("still_weak_points", [])) or "暂无"

    body = f"""
<div class="header">
  <h1>✅ 批改反馈</h1>
  <div class="sub">{student_name} · {week_start or date.today().isoformat()}</div>
</div>

<div class="section">
  <div class="card" style="display:flex; justify-content:space-around; text-align:center; flex-wrap:wrap; gap:16px;">
    <div><div class="highlight-num" style="color:{'var(--green)' if accuracy >= 0.8 else 'var(--accent)' if accuracy >= 0.6 else 'var(--red)'};">{accuracy:.0%}</div><div style="color:var(--sub);">正确率</div></div>
    <div><div class="highlight-num" style="color:var(--green);">{correct}</div><div style="color:var(--sub);">答对</div></div>
    <div><div class="highlight-num" style="color:var(--red);">{total - correct}</div><div style="color:var(--sub);">需巩固</div></div>
  </div>
</div>

<div class="section">
  <h2>📋 逐题反馈</h2>
  {result_rows}
</div>

<div class="section">
  <h2>📊 知识点掌握情况</h2>
  <div class="card">
    <p><strong>🌟 已经稳住了：</strong>{mastered}</p>
    <p><strong>🌱 再练一练：</strong>{weak}</p>
  </div>
  <div class="cta-box">
    <p><strong>这次的表现：</strong>{summary.get('overall_feedback', '每一步都算数，继续往前走！')}</p>
  </div>
</div>

<div class="footer">
  <p>下次练习时，系统会继续针对"还需练习"的知识点出题。</p>
</div>"""

    return _base_html(f"批改反馈 - {student_name}", body)


# ═══════════════════════════════════════════════════
# 家长周报
# ═══════════════════════════════════════════════════

def _render_accuracy_chart(accuracy: list, weeks: list) -> str:
    """Generate a responsive SVG line chart for accuracy trend."""
    if not accuracy or all(a is None for a in accuracy):
        return ""

    # Chart dimensions
    W, H = 600, 240
    pad_l, pad_r, pad_t, pad_b = 50, 30, 30, 50
    gw = W - pad_l - pad_r
    gh = H - pad_t - pad_b

    # Filter valid points and compute min/max for y-axis
    valid = [(i, a) for i, a in enumerate(accuracy) if a is not None]
    if not valid:
        return ""

    y_min, y_max = 0, 100
    n = len(accuracy)

    def x_of(i: int) -> float:
        return pad_l + (i / max(n - 1, 1)) * gw

    def y_of(v: float) -> float:
        return pad_t + gh - ((v - y_min) / (y_max - y_min)) * gh

    # Grid lines (0, 25, 50, 75, 100)
    grid_lines = ""
    y_labels = ""
    for pct in [0, 25, 50, 75, 100]:
        y = y_of(pct)
        grid_lines += f'<line x1="{pad_l}" y1="{y}" x2="{W - pad_r}" y2="{y}" stroke="#e8e3dc" stroke-width="1" stroke-dasharray="4,4"/>'
        y_labels += f'<text x="{pad_l - 10}" y="{y + 4}" text-anchor="end" font-size="12" fill="#6b6b6b">{pct}%</text>'

    # X-axis labels (week dates, shortened)
    x_labels = ""
    for i, ws in enumerate(weeks):
        label = ws[5:] if len(ws) >= 10 else ws  # MM-DD
        x = x_of(i)
        x_labels += f'<text x="{x:.1f}" y="{H - pad_b + 18}" text-anchor="middle" font-size="12" fill="#6b6b6b">{label}</text>'

    # Line path through valid points
    path_d = ""
    for idx, (i, a) in enumerate(valid):
        cmd = "M" if idx == 0 else "L"
        path_d += f"{cmd}{x_of(i):.1f},{y_of(a):.1f} "

    # Data points
    points = ""
    for i, a in valid:
        x, y = x_of(i), y_of(a)
        points += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#e8813b" stroke="#fff" stroke-width="2"/>'
        points += f'<text x="{x:.1f}" y="{y - 10:.1f}" text-anchor="middle" font-size="12" fill="#2d2d2d" font-weight="600">{a:.0f}%</text>'

    return f"""
    <div class="card" style="text-align:center; padding:16px;">
      <svg viewBox="0 0 {W} {H}" style="width:100%; max-width:600px; height:auto;">
        {grid_lines}
        <line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{H - pad_b}" stroke="#6b6b6b" stroke-width="1"/>
        <line x1="{pad_l}" y1="{H - pad_b}" x2="{W - pad_r}" y2="{H - pad_b}" stroke="#6b6b6b" stroke-width="1"/>
        <path d="{path_d}" fill="none" stroke="#e8813b" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
        {points}
        {y_labels}
        {x_labels}
      </svg>
    </div>
    """


def _render_kp_mastery_chart(kp_trends: dict, weeks: list) -> str:
    """Generate a responsive SVG multi-line chart for knowledge point mastery trends."""
    if not kp_trends:
        return ""

    kp_trends = {kp: rates for kp, rates in kp_trends.items() if rates}
    if not kp_trends:
        return ""

    W, H = 600, 280
    pad_l, pad_r, pad_t, pad_b = 50, 30, 30, 70
    gw = W - pad_l - pad_r
    gh = H - pad_t - pad_b
    n_weeks = len(weeks)
    y_min, y_max = 0, 100

    def x_of(i: int) -> float:
        return pad_l + (i / max(n_weeks - 1, 1)) * gw

    def y_of(v: float) -> float:
        return pad_t + gh - ((v - y_min) / (y_max - y_min)) * gh

    # Grid lines and Y-axis labels
    grid_lines = ""
    y_labels = ""
    for pct in [0, 25, 50, 75, 100]:
        y = y_of(pct)
        grid_lines += f'<line x1="{pad_l}" y1="{y}" x2="{W - pad_r}" y2="{y}" stroke="#e8e3dc" stroke-width="1" stroke-dasharray="4,4"/>'
        y_labels += f'<text x="{pad_l - 10}" y="{y + 4}" text-anchor="end" font-size="12" fill="#6b6b6b">{pct}%</text>'

    # X-axis labels
    x_labels = ""
    for i, ws in enumerate(weeks):
        label = ws[5:] if len(ws) >= 10 else ws
        x = x_of(i)
        x_labels += f'<text x="{x:.1f}" y="{H - pad_b + 18}" text-anchor="middle" font-size="12" fill="#6b6b6b">{label}</text>'

    colors = ["#e8813b", "#22a06b", "#3b82c4", "#d14343", "#8b5cf6"]

    paths = ""
    points = ""
    value_labels = ""
    legend_items = []

    for idx, (kp, rates) in enumerate(kp_trends.items()):
        color = colors[idx % len(colors)]

        path_d = ""
        for i, rate in enumerate(rates):
            x, y = x_of(i), y_of(rate)
            cmd = "M" if i == 0 else "L"
            path_d += f"{cmd}{x:.1f},{y:.1f} "
        paths += f'<path d="{path_d}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>'

        for i, rate in enumerate(rates):
            x, y = x_of(i), y_of(rate)
            points += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}" stroke="#fff" stroke-width="2"/>'

        if rates:
            last_x, last_y = x_of(len(rates) - 1), y_of(rates[-1])
            value_labels += f'<text x="{last_x + 8:.1f}" y="{last_y + 4:.1f}" font-size="11" fill="{color}" font-weight="600">{rates[-1]:.0f}%</text>'

        legend_items.append((kp, color, rates[-1] if rates else 0))

    legend_html = ""
    for kp, color, current in legend_items:
        legend_html += f'''
        <span style="display:inline-flex;align-items:center;gap:4px;margin:4px 8px;font-size:.82em;color:#4a4a4a;">
            <span style="width:14px;height:3px;background:{color};border-radius:1px;display:inline-block;"></span>
            {kp} <strong style="color:{color};">{current:.0f}%</strong>
        </span>'''

    return f"""
    <div class="card" style="text-align:center; padding:16px 12px;">
      <svg viewBox="0 0 {W} {H}" style="width:100%; max-width:600px; height:auto;">
        {grid_lines}
        <line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{H - pad_b}" stroke="#6b6b6b" stroke-width="1"/>
        <line x1="{pad_l}" y1="{H - pad_b}" x2="{W - pad_r}" y2="{H - pad_b}" stroke="#6b6b6b" stroke-width="1"/>
        {paths}
        {points}
        {value_labels}
        {y_labels}
        {x_labels}
      </svg>
      <div style="margin-top:4px; display:flex; flex-wrap:wrap; justify-content:center;">
        {legend_html}
      </div>
    </div>
    """


def _render_learning_style_radar(learning_style: dict, size: int = 220) -> str:
    """Generate an SVG radar chart for the 4-dimension learning style assessment."""

    dims = [
        {"key": "visual", "label": "视觉型", "value": float(learning_style.get("visual") or 0)},
        {"key": "auditory", "label": "听觉型", "value": float(learning_style.get("auditory") or 0)},
        {"key": "kinesthetic", "label": "动觉型", "value": float(learning_style.get("kinesthetic") or 0)},
        {"key": "read_write", "label": "读写型", "value": float(learning_style.get("read_write") or 0)},
    ]

    if all(d["value"] == 0 for d in dims):
        return ""

    import math
    center = size / 2.0
    radius = size * 0.36
    max_val = 10.0
    levels = [0.33, 0.66, 1.0]

    def angle_for(i: int) -> float:
        return (math.pi * 2.0 * i) / 4.0 - math.pi / 2.0

    def point_for(value: float, i: int) -> str:
        r = (value / max_val) * radius
        a = angle_for(i)
        return f"{center + r * math.cos(a):.1f},{center + r * math.sin(a):.1f}"

    def label_pos_for(i: int, dist: float) -> tuple:
        a = angle_for(i)
        return (center + dist * math.cos(a), center + dist * math.sin(a))

    # Grid polygons
    grid_polys = ""
    for lv in levels:
        pts = " ".join(point_for(max_val * lv, i) for i in range(4))
        grid_polys += (
            f'<polygon points="{pts}" fill="none" stroke="#e8e3dc" '
            f'stroke-width="1" stroke-dasharray="2,2"/>'
        )

    # Axes
    axes = ""
    for i in range(4):
        ex, ey = label_pos_for(i, radius)
        axes += (
            f'<line x1="{center:.0f}" y1="{center:.0f}" '
            f'x2="{ex:.1f}" y2="{ey:.1f}" stroke="#e8e3dc" stroke-width="1"/>'
        )

    # Data polygon
    data_pts = " ".join(point_for(d["value"], i) for i, d in enumerate(dims))
    data_poly = (
        f'<polygon points="{data_pts}" fill="#e8813b" fill-opacity="0.25" '
        f'stroke="#e8813b" stroke-width="2"/>'
    )

    # Data dots
    dots = ""
    for i, d in enumerate(dims):
        pt = point_for(d["value"], i)
        x, y = pt.split(",")
        dots += f'<circle cx="{x}" cy="{y}" r="3" fill="#e8813b"/>'

    # Labels
    labels = ""
    for i, d in enumerate(dims):
        lx, ly = label_pos_for(i, radius + 22)
        anchor = ["middle", "start", "middle", "end"][i]
        labels += (
            f'<text x="{lx:.1f}" y="{ly + 4:.1f}" text-anchor="{anchor}" '
            f'font-size="12" fill="#2d2d2d">{d["label"]}</text>'
            f'<text x="{lx:.1f}" y="{ly + 18:.1f}" text-anchor="{anchor}" '
            f'font-size="11" fill="#e8813b">{d["value"]:.0f}</text>'
        )

    # Caption
    caption = []
    if learning_style.get("dominant"):
        caption.append(f'<strong>{learning_style["dominant"]}</strong>')
    if learning_style.get("auxiliary"):
        caption.append(f'辅助：{learning_style["auxiliary"]}')
    if learning_style.get("interpretation"):
        caption.append(learning_style["interpretation"])
    caption_html = ""
    if caption:
        caption_html = (
            f'<div style="font-size:.85em;color:#6b6b6b;text-align:center;'
            f'margin-top:8px;line-height:1.5;">{" · ".join(caption)}</div>'
        )

    return f"""
    <div style="max-width:{size}px;margin:0 auto;">
      <!-- viewBox 四周留白 35px：四向维度标签（radius+22 处）超出图表边界会被裁剪 -->
      <svg viewBox="-35 -35 {size + 70} {size + 70}" style="width:100%;height:{size}px;display:block;">
        {grid_polys}
        {axes}
        {data_poly}
        {dots}
        {labels}
      </svg>
      {caption_html}
    </div>
    """


def _render_action_plan(action_plan: dict, weak_areas: list, mastered_count: int,
                        student_name: str) -> str:
    """Render the 'next step action plan' section for the weekly report."""
    if action_plan:
        system_items = action_plan.get("system_will", [])
        student_items = action_plan.get("student_should", [])
        parent_items = action_plan.get("parent_can", [])
    else:
        top_weak = weak_areas[0].get("knowledge_point", "") if weak_areas else ""
        second_weak = weak_areas[1].get("knowledge_point", "") if len(weak_areas) > 1 else ""
        system_items = [f"下周针对「{top_weak}」出专项练习"] if top_weak else ["下周继续根据薄弱点生成专项练习"]
        if second_weak:
            system_items.append(f"同步关注「{second_weak}」的掌握情况")
        student_items = ["完成本周专属练习题（约30分钟）", "每天花5分钟过一遍错题本"]
        parent_items = ["周六前拍一张最近的英语试卷发过来", "孩子做完练习后，问一句'今天练了什么'就够了"]

    if not system_items and not student_items and not parent_items:
        return ""

    sys_rows = "\n".join(f"<li>· {item}</li>" for item in system_items)
    stu_rows = "\n".join(f"<li>· {item}</li>" for item in student_items)
    par_rows = "\n".join(f"<li>· {item}</li>" for item in parent_items)

    return f"""
<div class="section">
  <h2>📋 下一步行动计划</h2>
  <div class="card" style="border-left:4px solid var(--blue);">
    <h3 style="color:var(--blue);">🤖 我们这边会做的</h3>
    <ul style="margin:8px 0 0 0;padding-left:1.2em;color:var(--text-alt);">{sys_rows}</ul>
  </div>
  <div class="card" style="border-left:4px solid var(--green);">
    <h3 style="color:var(--green);">📱 {student_name}要做的</h3>
    <ul style="margin:8px 0 0 0;padding-left:1.2em;color:var(--text-alt);">{stu_rows}</ul>
  </div>
  <div class="card" style="border-left:4px solid var(--accent);">
    <h3 style="color:var(--accent);">👨‍👩‍👧 家长可以做的</h3>
    <ul style="margin:8px 0 0 0;padding-left:1.2em;color:var(--text-alt);">{par_rows}</ul>
  </div>
</div>"""


def render_weekly_report(student_name: str, week_start: str, week_end: str,
                         new_mistakes: int, mastered_count: int,
                         weak_areas: list, ai_clinic: str = "",
                         comparison: dict = None,
                         learning_style_detail: dict = None,
                         action_plan: dict = None,
                         cause_trend: dict = None) -> str:
    """Generate parent weekly report as a growth narrative (成长叙事)."""

    # ── Derive narrative data ──
    # Mastered knowledge points (from comparison or weak_areas with high mastery)
    mastered_kps = []
    climbing_kps = []
    if comparison:
        for kp, counts in comparison.get("knowledge_point_trends", {}).items():
            if len(counts) >= 2 and counts[-1] == 0 and counts[-2] > 0:
                mastered_kps.append(kp)
            elif counts and counts[-1] > 0:
                climbing_kps.append({"name": kp, "count": counts[-1],
                                     "prev": counts[-2] if len(counts) >= 2 else counts[-1]})
    # Fallback from weak_areas
    if not climbing_kps and weak_areas:
        for wa in weak_areas[:3]:
            rate = wa.get("mastery_rate", 0)
            climbing_kps.append({
                "name": wa.get("knowledge_point", "?"),
                "count": wa.get("unmastered", 0),
                "prev": wa.get("unmastered", 0),
                "rate": rate,
            })

    # ── Praise script: specific thing parent can say ──
    if mastered_kps:
        praise = f"你这周把「{mastered_kps[0]}」彻底搞懂了，比上个月强太多了！"
    elif mastered_count > 0:
        praise = f"这周你稳住了{mastered_count}道错题，说明之前的练习真的有用。"
    elif new_mistakes == 0:
        praise = "这周没有新错题，说明你现在的状态很稳，继续保持。"
    else:
        praise = "这周虽然发现了新错题，但能发现问题本身就是进步——怕的是错了还不知道。"

    # ── One thing for next week ──
    if climbing_kps:
        one_thing = f"完成5道「{climbing_kps[0]['name']}」专项练习（约15分钟）"
    else:
        one_thing = "每天花5分钟翻一遍错题本，保持手感"

    # ── Trajectory section ──
    trajectory_html = ""
    if comparison:
        weeks = comparison.get("weeks", [])
        new_mist_trend = comparison.get("new_mistakes", [])
        mastered_trend = comparison.get("mastered_count", [])
        if len(weeks) >= 2:
            first_mistakes = new_mist_trend[0] if new_mist_trend else 0
            last_mistakes = new_mist_trend[-1] if new_mist_trend else 0
            total_mastered = sum(mastered_trend)
            if last_mistakes < first_mistakes:
                trajectory_text = f"第1周发现{first_mistakes}道错题 → 第{len(weeks)}周只有{last_mistakes}道"
                trajectory_emoji = "📉"
                trajectory_note = "错题在变少，说明薄弱点正在被逐个攻克"
            elif last_mistakes > first_mistakes:
                trajectory_text = f"第1周{first_mistakes}道 → 第{len(weeks)}周{last_mistakes}道"
                trajectory_emoji = "📊"
                trajectory_note = "新错题增多不代表退步——可能是接触了更难的题型"
            else:
                trajectory_text = f"连续{len(weeks)}周稳定在{last_mistakes}道左右"
                trajectory_emoji = "➡️"
                trajectory_note = "稳定本身就是一种能力，接下来可以挑战更高难度"
            trajectory_html = f"""
            <div class="card" style="text-align:center;padding:20px;">
              <div style="font-size:1.8em;margin-bottom:8px;">{trajectory_emoji}</div>
              <div style="font-size:1.05em;font-weight:700;margin-bottom:6px;">{trajectory_text}</div>
              <div style="font-size:.85em;color:var(--sub);">{trajectory_note}</div>
              <div style="margin-top:12px;font-size:.85em;color:var(--green);font-weight:600;">
                累计攻克 {total_mastered} 道错题 · 错题本在变薄
              </div>
            </div>"""

    # ── Mastered steps (台阶) ──
    mastered_steps_html = ""
    if mastered_kps:
        items = "".join(f'<div style="padding:10px 14px;margin:6px 0;background:var(--green-light);border-radius:8px;display:flex;align-items:center;gap:8px;"><span>✅</span><span style="font-weight:600;">{kp}</span><span style="margin-left:auto;font-size:.8em;color:var(--green);">已攻克</span></div>' for kp in mastered_kps[:5])
        mastered_steps_html = f"""
        <div class="section">
          <h2>🪨 新踩实的台阶</h2>
          <p style="color:var(--sub);font-size:.85em;margin-bottom:12px;">这些知识点，孩子已经能稳定做对了：</p>
          {items}
        </div>"""
    elif mastered_count > 0:
        mastered_steps_html = f"""
        <div class="section">
          <h2>🪨 新踩实的台阶</h2>
          <div class="card" style="text-align:center;">
            <div style="font-size:1.5em;font-weight:700;color:var(--green);">{mastered_count} 道</div>
            <div style="font-size:.85em;color:var(--sub);">错题这周被稳住了，说明练习有效</div>
          </div>
        </div>"""

    # ── Climbing steps ──
    climbing_html = ""
    if climbing_kps:
        items = ""
        for kp in climbing_kps[:4]:
            rate = kp.get("rate", 0)
            prev = kp.get("prev", kp.get("count", 0))
            cur = kp.get("count", 0)
            if cur < prev:
                trend_text = f"比上周少{prev - cur}道"
                trend_color = "var(--green)"
            elif cur > prev:
                trend_text = f"比上周多{cur - prev}道"
                trend_color = "var(--red)"
            else:
                trend_text = "和上周持平"
                trend_color = "var(--sub)"
            bar_width = min(rate, 100) if rate else max(10, 100 - cur * 15)
            items += f"""
            <div style="padding:12px 14px;margin:6px 0;background:var(--bg);border-radius:8px;">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                <span style="font-weight:600;">🔄 {kp['name']}</span>
                <span style="font-size:.8em;color:{trend_color};">{trend_text}</span>
              </div>
              <div class="progress-bar"><div class="fill" style="width:{bar_width}%;background:{'var(--green)' if bar_width > 60 else 'var(--accent)'};"></div></div>
            </div>"""
        climbing_html = f"""
        <div class="section">
          <h2>🪨 还在爬的台阶</h2>
          <p style="color:var(--sub);font-size:.85em;margin-bottom:12px;">这些知识点正在进步中，再练几轮就能踩实：</p>
          {items}
        </div>"""

    # ── New mistakes (neutral framing) ──
    new_mistakes_html = ""
    if new_mistakes > 0:
        new_mistakes_html = f"""
        <div class="section">
          <div class="card" style="border-left:4px solid var(--blue);padding:14px 16px;">
            <span style="font-size:.9em;">📝 本周新发现 <strong>{new_mistakes}</strong> 道错题</span>
            <span style="font-size:.8em;color:var(--sub);margin-left:8px;">已自动生成针对性练习</span>
          </div>
        </div>"""

    # ── 卡点变化（错因跨周对比叙事）──
    cause_html = ""
    if cause_trend and cause_trend.get("narrative"):
        prev_label = cause_trend.get("previous_primary_label", "?")
        cur_label = cause_trend.get("current_primary_label", "?")
        prev_pct = cause_trend.get("previous_pct", 0)
        cur_pct = cause_trend.get("current_pct", 0)
        same = cause_trend.get("current_primary") == cause_trend.get("previous_primary")
        arrow_color = "var(--green)" if same and cur_pct <= prev_pct else "var(--accent)"
        cause_html = f"""
        <div class="section">
          <h2>🧭 卡点变化</h2>
          <div class="card" style="border-left:4px solid var(--accent);">
            <p style="font-size:.95rem;line-height:1.8;margin-bottom:12px;">{cause_trend["narrative"]}</p>
            <div style="display:flex;gap:20px;flex-wrap:wrap;align-items:center;">
              <div style="background:var(--bg);border-radius:8px;padding:10px 14px;min-width:130px;">
                <div style="font-size:.72rem;color:var(--sub);">上周核心卡点</div>
                <div style="font-weight:700;font-size:.95rem;">{prev_label}</div>
                <div style="font-size:.78rem;color:var(--sub);">占错题 {prev_pct}%</div>
              </div>
              <div style="color:{arrow_color};font-size:1.2rem;font-weight:700;">→</div>
              <div style="background:var(--accent-light);border-radius:8px;padding:10px 14px;min-width:130px;">
                <div style="font-size:.72rem;color:var(--sub);">本周核心卡点</div>
                <div style="font-weight:700;font-size:.95rem;color:var(--accent-hover);">{cur_label}</div>
                <div style="font-size:.78rem;color:var(--sub);">占错题 {cur_pct}%</div>
              </div>
            </div>
          </div>
        </div>"""

    body = f"""
<div class="header">
  <h1>📈 本周拾阶而上</h1>
  <div class="sub">{student_name} · {week_start} ~ {week_end}</div>
</div>

{mastered_steps_html}

{climbing_html}

{new_mistakes_html}

{cause_html}

<div class="section">
  <h2>📊 成长轨迹</h2>
  {trajectory_html or '<div class="card"><p style="color:var(--sub);text-align:center;">积累更多数据后，这里会显示进步曲线</p></div>'}
</div>

<div class="section">
  <h2>💬 这周可以夸孩子</h2>
  <div class="card" style="border-left:4px solid var(--accent);padding:16px;">
    <p style="font-size:1em;line-height:1.7;font-style:italic;">"{praise}"</p>
    <p style="font-size:.8em;color:var(--sub);margin-top:8px;">💡 具体的肯定比"你真棒"有效10倍</p>
  </div>
</div>

<div class="section">
  <h2>🎯 下周只需做一件事</h2>
  <div class="card" style="text-align:center;padding:20px;">
    <div style="font-size:1.05em;font-weight:700;color:var(--accent);">{one_thing}</div>
    <p style="font-size:.8em;color:var(--sub);margin-top:8px;">不用多，做到这一件就够了</p>
  </div>
</div>

<div class="footer">
  <p>拾阶而上 · 步步有痕，拾阶可见</p>
</div>"""
    return _base_html(f"本周拾阶而上 - {student_name}", body)


def render_share_poster(student: dict, stats: dict) -> str:
    """Generate a shareable achievement poster HTML for parents."""
    name = student.get("name", "同学")
    grade = student.get("grade", "")
    current = student.get("english_score") or stats.get("current_score") or None
    target = student.get("target_score") or stats.get("target_score") or None
    mastered = stats.get("mastered_count", 0)
    mistakes = stats.get("mistakes_count", 0)
    checkins = stats.get("check_in_count", 0)

    # 分数回退：档案未填 → 取最近一次分数（score_history 按时间升序，末位最新）
    if not current:
        scores = stats.get("scores") or []
        if scores:
            current = scores[-1].get("score") or None

    # Encouraging message based on progress
    messages = [
        "每天进步一点点，英语提升看得见！",
        "坚持练习，薄弱点逐个击破！",
        "用对方法，英语学习事半功倍！",
        "错题不过夜，进步不停歇！",
    ]
    message = messages[(student.get("id", 0) + mastered) % len(messages)]

    # 主数字区：有分数显示分数；无分数用错题掌握进度（错题本越读越薄）
    if current:
        score_label = "当前英语成绩"
        score_text = f"{current}分"
        score_sub = ""
        if target:
            score_text += f"<span style='font-size:.5em;color:var(--sub);'> / 目标 {target}分</span>"
    else:
        score_label = "已稳住错题"
        score_text = f"{mastered}"
        score_sub = (f"<div style='font-size:.75em;color:var(--sub);margin-top:6px;'>"
                     f"共 {mastered + mistakes} 道错题 · 稳住 {mastered} 道，错题本越读越薄</div>")

    import xml.sax.saxutils as _su
    _safe_name = _su.escape(str(name or ""))
    _safe_grade = _su.escape(str(grade or ""))
    body = f"""
<div style="background:linear-gradient(135deg, #e8813b 0%, #f5a56a 100%); min-height:100vh; padding:32px 20px; text-align:center; color:#fff; font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;">
  <div style="max-width:380px; margin:0 auto; background:rgba(255,255,255,.12); border-radius:20px; padding:32px 24px; backdrop-filter:blur(10px); border:1px solid rgba(255,255,255,.3);">
    <div style="font-size:.9em; opacity:.9; margin-bottom:8px;">拾阶而上</div>
    <h1 style="font-size:1.6em; margin-bottom:8px;">{_safe_name} 的学习海报</h1>
    <div style="font-size:.85em; opacity:.85; margin-bottom:28px;">{_safe_grade} · AI 个性化英语学习</div>

    <div style="background:#fff; border-radius:16px; padding:24px; color:var(--text); margin-bottom:20px;">
      <div style="font-size:.85em; color:var(--sub); margin-bottom:8px;">{score_label}</div>
      <div style="font-size:3em; font-weight:700; color:var(--accent); line-height:1;">{score_text}</div>
      {score_sub}

      <div style="display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-top:24px;">
        <div style="background:var(--green-light); border-radius:10px; padding:12px 4px;">
          <div style="font-size:1.5em; font-weight:700; color:var(--green);">{mastered}</div>
          <div style="font-size:.7em; color:var(--sub);">已稳住错题</div>
        </div>
        <div style="background:var(--accent-light); border-radius:10px; padding:12px 4px;">
          <div style="font-size:1.5em; font-weight:700; color:var(--accent);">{mistakes}</div>
          <div style="font-size:.7em; color:var(--sub);">待攻克错题</div>
        </div>
        <div style="background:var(--blue-light); border-radius:10px; padding:12px 4px;">
          <div style="font-size:1.5em; font-weight:700; color:var(--blue);">{checkins}</div>
          <div style="font-size:.7em; color:var(--sub);">本月打卡</div>
        </div>
      </div>
    </div>

    <div style="background:rgba(255,255,255,.2); border-radius:12px; padding:16px; margin-bottom:24px;">
      <p style="font-size:1.05em; line-height:1.6; margin:0;">"{message}"</p>
    </div>
  </div>

  <div style="margin-top:24px; font-size:.75em; opacity:.7;">
    <p>拾阶而上 · AI 驱动个性化学习</p>
    <p>按周付费 · 随时可停 · invite好友一起学</p>
  </div>
</div>"""

    return _base_html(f"{name} 的学习海报", body, css_extra="""
      :root {{ --accent: #e07b4b; --green: #0f7b4e; --blue: #4b8dc7; --sub: #6b6b6b; }}
    """)


# ═══════════════════════════════════════════════════
# PDF 生成（打印友好）
# ═══════════════════════════════════════════════════

def render_exercise_pdf(student_name: str, questions: list, week_start: str = "") -> bytes:
    """Generate a print-friendly PDF of practice exercises using reportlab platypus.
    xhtml2pdf is bypassed because it cannot reliably embed CJK fonts."""
    from io import BytesIO
    import xml.sax.saxutils as _su
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib import colors

    cjk = _ensure_cjk_font()
    font = cjk or "Helvetica"

    def esc(text):
        """Escape XML for reportlab Paragraph and convert newlines to <br/>."""
        return _su.escape(str(text or "")).replace("\n", "<br/>")

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            topMargin=2 * cm, bottomMargin=2 * cm,
                            leftMargin=2 * cm, rightMargin=2 * cm)

    title_st = ParagraphStyle("T", fontName=font, fontSize=18, alignment=TA_CENTER,
                              spaceAfter=4, leading=24)
    sub_st = ParagraphStyle("S", fontName=font, fontSize=10, alignment=TA_CENTER,
                            textColor=colors.HexColor("#666666"), spaceAfter=2)
    qhead_st = ParagraphStyle("QH", fontName=font, fontSize=12, spaceBefore=14,
                              spaceAfter=4, leading=16)
    body_st = ParagraphStyle("B", fontName=font, fontSize=10, leading=16, spaceAfter=4)
    opt_st = ParagraphStyle("O", fontName=font, fontSize=10, leading=14,
                            leftIndent=14, spaceAfter=2)
    ans_st = ParagraphStyle("A", fontName=font, fontSize=9, textColor=colors.grey,
                            spaceBefore=6, spaceAfter=10)
    footer_st = ParagraphStyle("F", fontName=font, fontSize=9, alignment=TA_CENTER,
                               textColor=colors.grey, spaceBefore=20)

    story = [
        Paragraph("专属练习题", title_st),
        Paragraph(f"{esc(student_name)} · {week_start or date.today().isoformat()} · 共 {len(questions)} 题", sub_st),
        Paragraph("这些题目根据你最近的试卷错题定制，只练最需要的地方", sub_st),
        Spacer(1, 16),
    ]

    for i, q in enumerate(questions):
        kps = ", ".join(q.get("knowledge_points", []))
        qtype = q.get("question_type", "")
        head = f"第 {i + 1} 题"
        if qtype or kps:
            head += f'  <font size="9" color="#888888">{esc(qtype)} · {esc(kps)}</font>'
        story.append(Paragraph(head, qhead_st))
        if q.get("passage"):
            story.append(Paragraph(
                f'<font size="8" color="#888888">📄 阅读短文</font><br/>{esc(q["passage"])}',
                body_st))
        story.append(Paragraph(esc(q.get("question_text", "")), body_st))
        for opt in q.get("options", []):
            story.append(Paragraph(esc(opt), opt_st))
        story.append(Paragraph("我的答案：________________", ans_st))

    story.append(Spacer(1, 20))
    story.append(Paragraph("拾阶而上 · 做完后拍照上传，AI 自动批改", footer_st))

    doc.build(story)
    return buffer.getvalue()


# ═══════════════════════════════════════════════════
# 周错题本 & 月度总结报告
# ═══════════════════════════════════════════════════

def render_weekly_mistake_book(
    student: dict,
    mistakes: list,
    week_start: str,
    week_end: str,
    mastered_count: int = 0,
) -> str:
    """Generate a weekly mistake book HTML — one per student per week."""

    total = len(mistakes)
    remaining = total - mastered_count

    # Knowledge point breakdown
    kp_stats: dict = {}
    for m in mistakes:
        kps = m.get("knowledge_points", [])
        if isinstance(kps, str):
            import json as _j
            try: kps = _j.loads(kps)
            except Exception: kps = [kps]
        for kp in (kps or ["其他"]):
            kp_stats[kp] = kp_stats.get(kp, 0) + 1
    kp_sorted = sorted(kp_stats.items(), key=lambda x: -x[1])[:8]
    kp_tags = "".join(
        f'<span style="display:inline-block;background:var(--bg);border-radius:100px;'
        f'padding:4px 12px;font-size:.8rem;margin:2px;">{kp} ×{cnt}</span>'
        for kp, cnt in kp_sorted
    )

    # Mistake cards (reuse diagnostic report style)
    cards = ""
    for i, m in enumerate(mistakes):
        kps = m.get("knowledge_points", [])
        if isinstance(kps, str):
            import json as _j
            try: kps = _j.loads(kps)
            except Exception: kps = []
        question = m.get("question_text", "") or m.get("question", "") or ""
        user_ans = m.get("user_answer", "") or "未识别"
        correct_ans = m.get("correct_answer", "") or ""
        explanation = m.get("explanation", "") or m.get("error_reason", "") or ""
        qtype = m.get("question_type", "")

        cards += f"""
        <div style="background:var(--card);border-radius:12px;padding:16px;margin-bottom:14px;box-shadow:var(--shadow);">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
            <span style="font-weight:700;">第 {i+1} 题</span>
            {f'<span style="background:var(--bg);border-radius:100px;padding:2px 10px;font-size:.7rem;color:var(--sub);">{qtype}</span>' if qtype else ''}
          </div>
          <div style="background:var(--bg);border-radius:8px;padding:12px;margin-bottom:10px;white-space:pre-wrap;font-size:.9rem;line-height:1.7;">{question}</div>
          <div style="display:flex;gap:10px;margin-bottom:10px;">
            <div style="flex:1;background:var(--red-light);border-radius:8px;padding:8px 12px;">
              <div style="font-size:.72rem;color:var(--red);font-weight:600;">✗ 你的答案</div>
              <div style="font-size:.9rem;color:var(--red);font-weight:600;">{user_ans}</div>
            </div>
            <div style="flex:1;background:var(--green-light);border-radius:8px;padding:8px 12px;">
              <div style="font-size:.72rem;color:var(--green);font-weight:600;">✓ 正确答案</div>
              <div style="font-size:.9rem;color:var(--green);font-weight:600;">{correct_ans}</div>
            </div>
          </div>
          {f'<div style="background:var(--accent-light);border-radius:8px;padding:12px;"><div style="font-size:.72rem;color:var(--accent);font-weight:600;margin-bottom:4px;">📖 解析</div><div style="font-size:.85rem;line-height:1.7;">{explanation}</div></div>' if explanation else ''}
        </div>"""

    body = f"""
<div class="header">
  <h1>📒 周错题本</h1>
  <div class="sub">{student.get('name','同学')} · {week_start} ~ {week_end}</div>
</div>

<div class="card" style="display:flex;justify-content:space-around;text-align:center;flex-wrap:wrap;gap:12px;">
  <div><div style="font-size:1.8rem;font-weight:700;color:var(--accent);">{total}</div><div style="color:var(--sub);font-size:.8rem;">本周错题</div></div>
  <div><div style="font-size:1.8rem;font-weight:700;color:var(--green);">{mastered_count}</div><div style="color:var(--sub);font-size:.8rem;">已攻克</div></div>
  <div><div style="font-size:1.8rem;font-weight:700;color:var(--red);">{remaining}</div><div style="color:var(--sub);font-size:.8rem;">仍在攻克</div></div>
</div>

<div class="section">
  <h2>🏷️ 知识点分布</h2>
  <div style="line-height:2.4;">{kp_tags or '<span style="color:var(--sub);">暂无</span>'}</div>
</div>

<div class="section">
  <h2>📝 错题详解</h2>
  {cards or '<div class="card"><p>本周无错题记录，继续保持！</p></div>'}
</div>

<div style="text-align:center;color:var(--mute);font-size:.75rem;margin-top:24px;">
  拾阶而上 · 每周自动生成 · 坚持复盘就是最好的进步
</div>
"""
    return _base_html(f"{student.get('name','')} 周错题本 {week_start}", body)


def render_monthly_report(
    student: dict,
    mistakes: list,
    month_label: str,
    month_stats: dict,
    ai_analysis: dict,
) -> str:
    """Generate a monthly summary report HTML."""

    total = month_stats.get("total_mistakes", len(mistakes))
    mastered = month_stats.get("mastered_count", 0)
    practice_count = month_stats.get("practice_count", 0)
    avg_accuracy = month_stats.get("avg_accuracy")

    # Knowledge point trends
    kp_stats: dict = {}
    for m in mistakes:
        kps = m.get("knowledge_points", [])
        if isinstance(kps, str):
            import json as _j
            try: kps = _j.loads(kps)
            except Exception: kps = []
        for kp in (kps or ["其他"]):
            kp_stats[kp] = kp_stats.get(kp, 0) + 1
    kp_sorted = sorted(kp_stats.items(), key=lambda x: -x[1])[:10]

    kp_bars = ""
    max_count = max((c for _, c in kp_sorted), default=1)
    for kp, cnt in kp_sorted:
        pct = int(cnt / max_count * 100)
        kp_bars += f"""
        <div style="margin-bottom:8px;">
          <div style="display:flex;justify-content:space-between;font-size:.8rem;margin-bottom:2px;">
            <span>{kp}</span><span style="color:var(--sub);">{cnt} 道</span>
          </div>
          <div style="height:6px;background:var(--bg);border-radius:6px;overflow:hidden;">
            <div style="height:100%;width:{pct}%;background:var(--accent);border-radius:6px;"></div>
          </div>
        </div>"""

    # AI analysis sections
    ai = ai_analysis or {}
    progress = ai.get("progress_points", [])
    regression = ai.get("regression_points", [])
    suggestions = ai.get("next_month_suggestions", [])
    assessment = ai.get("overall_assessment", "")

    progress_html = "".join(f"<li style='color:var(--green);'>{p}</li>" for p in progress)
    regression_html = "".join(f"<li style='color:var(--red);'>{p}</li>" for p in regression)
    suggestions_html = "".join(f"<li>{s}</li>" for s in suggestions)

    # Condensed mistake list (grouped by knowledge point)
    mistake_list = ""
    for i, m in enumerate(mistakes[:30]):
        question = (m.get("question_text", "") or m.get("question", ""))[:80]
        correct = m.get("correct_answer", "")
        mistake_list += f"""
        <div style="padding:8px 12px;border-bottom:1px solid var(--border);font-size:.85rem;">
          <span style="color:var(--sub);">{i+1}.</span> {question}{'...' if len(question)==80 else ''}
          <span style="color:var(--green);font-weight:600;margin-left:8px;">→ {correct}</span>
        </div>"""

    accuracy_display = f"{avg_accuracy:.0%}" if isinstance(avg_accuracy, (int, float)) else "—"

    body = f"""
<div class="header">
  <h1>📊 月度总结报告</h1>
  <div class="sub">{student.get('name','同学')} · {month_label}</div>
</div>

<div class="card" style="display:flex;justify-content:space-around;text-align:center;flex-wrap:wrap;gap:12px;">
  <div><div style="font-size:1.8rem;font-weight:700;color:var(--accent);">{total}</div><div style="color:var(--sub);font-size:.8rem;">月度错题</div></div>
  <div><div style="font-size:1.8rem;font-weight:700;color:var(--green);">{mastered}</div><div style="color:var(--sub);font-size:.8rem;">已攻克</div></div>
  <div><div style="font-size:1.8rem;font-weight:700;color:var(--blue);">{practice_count}</div><div style="color:var(--sub);font-size:.8rem;">练习次数</div></div>
  <div><div style="font-size:1.8rem;font-weight:700;color:var(--accent);">{accuracy_display}</div><div style="color:var(--sub);font-size:.8rem;">平均正确率</div></div>
</div>

<div class="section">
  <h2>📈 知识点错题分布</h2>
  <div class="card">{kp_bars or '<p style="color:var(--sub);">本月无错题记录</p>'}</div>
</div>

{f'''<div class="section">
  <h2>🤖 AI 月度诊断</h2>
  <div class="card">
    {f'<p style="margin-bottom:12px;">{assessment}</p>' if assessment else ''}
    {f'<h3 style="color:var(--green);margin-bottom:6px;">进步亮点</h3><ul style="margin-bottom:12px;">{progress_html}</ul>' if progress else ''}
    {f'<h3 style="color:var(--red);margin-bottom:6px;">需要关注</h3><ul style="margin-bottom:12px;">{regression_html}</ul>' if regression else ''}
    {f'<h3 style="margin-bottom:6px;">下月建议</h3><ul>{suggestions_html}</ul>' if suggestions else ''}
  </div>
</div>''' if ai else ''}

<div class="section">
  <h2>📒 月度错题清单</h2>
  <div class="card" style="padding:0;overflow:hidden;">
    {mistake_list or '<p style="padding:16px;color:var(--sub);">本月无错题记录</p>'}
  </div>
</div>

<div style="text-align:center;color:var(--mute);font-size:.75rem;margin-top:24px;">
  拾阶而上 · 每月1日自动生成 · 坚持是最有力的成长
</div>
"""
    return _base_html(f"{student.get('name','')} 月度报告 {month_label}", body)


# ═══════════════════════════════════════════════════
# Test
# ═══════════════════════════════════════════════════

if __name__ == "__main__":
    # Quick smoke test
    html = render_diagnostic_report(
        student={"name": "测试", "grade": "高二", "english_score": 115},
        ocr_confidence=0.85,
        mistakes=[
            {"question_type": "语法填空", "knowledge_points": ["非谓语动词"], "error_reason": "语法误解"},
        ],
        weak_points=[
            {"knowledge_point": "非谓语动词", "severity": "高"},
            {"knowledge_point": "定语从句", "severity": "中"},
        ],
        learning_plan={
            "weekly_schedule": {"saturday_afternoon": "完成专属练习题 30-40 分钟"},
            "modules": [
                {"name": "词汇", "weekly_time_minutes": 120, "daily_word_count": 8, "focus": "高考高频词汇"},
            ],
            "minimum_standard": {"boarding": "每日词汇+1篇阅读", "day_student": "每晚词汇+听力"},
            "motivation_message": "你的基础不错，找到薄弱点刻意练习，进步会很明显的！",
            "parent_guide": "每周六拍照发卷子，剩下的交给我们。",
        },
    )
    out_path = os.path.join(os.path.dirname(__file__), "test_report.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Test report written to: {out_path}")
    print("report_templates.py OK")
