#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报告 HTML 模板
生成首次诊断报告、专属练习题、批改反馈、家长周报。
所有报告均为手机友好的独立 HTML 文件。
"""

import os
from datetime import date

from db import get_teacher_profile


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

def render_diagnostic_report(
    student: dict,
    ocr_confidence: float,
    mistakes: list,
    weak_points: list,
    learning_plan: dict,
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

    # Mistake summary
    mistake_rows = ""
    for m in mistakes[:10]:  # top 10
        kps = ", ".join(m.get("knowledge_points", [])[:3])
        question = m.get('question_text', '') or ''
        # Truncate long questions
        if len(question) > 100:
            question = question[:100] + '...'
        mistake_rows += f"""
        <tr>
          <td>{question}</td>
          <td>{m.get('question_type', '?')}</td>
          <td>{kps}</td>
          <td>{m.get('error_reason', '?')}</td>
        </tr>"""

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

{diagnosis_html}

<!-- Learning Style Radar -->
{(
    '<div class="section"><h2>🧠 学习风格画像</h2>'
    f'<div class="card" style="text-align:center;">{_render_learning_style_radar(learning_plan.get("diagnosis_report", {}).get("learning_style", {}))}</div>'
    '<p style="color:var(--sub);font-size:.85em;margin-top:8px;">此画像由 AI 基于错题分析和学生问卷生成，用于定制学习方案。</p>'
    '</div>'
) if learning_plan.get("diagnosis_report", {}).get("learning_style") else ''}

{motivation_html}

{review_html}

<div class="section">
  <h2>🌱 接下来重点关注</h2>
  <ul class="priority-list">{wp_rows}</ul>
</div>

<div class="section">
  <h2>📝 每道题背后的原因</h2>
  <div style="overflow-x:auto;">
    <table>
      <tr><th>题目</th><th>题型</th><th>考查知识点</th><th>错误原因</th></tr>
      {mistake_rows}
    </table>
  </div>
  <p style="color:var(--sub); font-size:.85em; margin-top:8px;">（仅展示前 10 道错题，完整列表见系统）</p>
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
    <p>{learning_plan.get('motivation_message', '每一份试卷都是一次成长的机会。孩子已经在路上了，我们一起陪他走下去。')}</p>
  </div>
</div>

{parent_tasks_html}

<div class="section">
  <h2>💛 你可以试试这样做</h2>
  <div class="cta-box">
    <p>{learning_plan.get('parent_guide', '请每周六上午拍照发一张孩子最近做过的英语卷子，剩下的交给我们。')}</p>
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
        for opt in q.get("options", []):
            opts_html += f"<div style='padding:6px 12px; margin:4px 0; background:var(--bg); border-radius:6px;'>{opt}</div>"

        kps = ", ".join(q.get("knowledge_points", []))
        q_blocks += f"""
        <div class="card">
          <h3>第 {i+1} 题 <span style="font-weight:400;color:var(--sub);font-size:.85em;">{q.get('question_type', '')} · {kps}</span></h3>
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
      <svg viewBox="0 0 {size} {size}" style="width:100%;height:{size}px;display:block;">
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
                         action_plan: dict = None) -> str:
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

    body = f"""
<div class="header">
  <h1>📈 本周拾阶而上</h1>
  <div class="sub">{student_name} · {week_start} ~ {week_end}</div>
</div>

{mastered_steps_html}

{climbing_html}

{new_mistakes_html}

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
    current = student.get("english_score") or stats.get("current_score", "?")
    target = student.get("target_score") or stats.get("target_score", "")
    mastered = stats.get("mastered_count", 0)
    mistakes = stats.get("mistakes_count", 0)
    checkins = stats.get("check_in_count", 0)

    # Encouraging message based on progress
    messages = [
        "每天进步一点点，英语提升看得见！",
        "坚持练习，薄弱点逐个击破！",
        "用对方法，英语学习事半功倍！",
        "错题不过夜，进步不停歇！",
    ]
    message = messages[(student.get("id", 0) + mastered) % len(messages)]

    # Score improvement display
    score_text = f"{current}分"
    if target:
        score_text += f"<span style='font-size:.5em;color:var(--sub);'> / 目标 {target}分</span>"

    body = f"""
<div style="background:linear-gradient(135deg, #e8813b 0%, #f5a56a 100%); min-height:100vh; padding:32px 20px; text-align:center; color:#fff; font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;">
  <div style="max-width:380px; margin:0 auto; background:rgba(255,255,255,.12); border-radius:20px; padding:32px 24px; backdrop-filter:blur(10px); border:1px solid rgba(255,255,255,.3);">
    <div style="font-size:.9em; opacity:.9; margin-bottom:8px;">拾阶而上</div>
    <h1 style="font-size:1.6em; margin-bottom:8px;">{name} 的学习海报</h1>
    <div style="font-size:.85em; opacity:.85; margin-bottom:28px;">{grade} · AI 个性化英语学习</div>

    <div style="background:#fff; border-radius:16px; padding:24px; color:var(--text); margin-bottom:20px;">
      <div style="font-size:.85em; color:var(--sub); margin-bottom:8px;">当前英语成绩</div>
      <div style="font-size:3em; font-weight:700; color:var(--accent); line-height:1;">{score_text}</div>

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

    <div style="border-top:1px dashed rgba(255,255,255,.4); padding-top:20px;">
      <p style="font-size:.8em; opacity:.85; margin-bottom:8px;">扫码查看完整学习报告</p>
      <div style="width:120px; height:120px; background:#fff; border-radius:10px; margin:0 auto; display:flex; align-items:center; justify-content:center; color:var(--sub); font-size:.7em;">
        [二维码区域]
      </div>
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
    """Generate a print-friendly PDF of practice exercises. Returns PDF bytes."""
    from io import BytesIO
    from xhtml2pdf import pisa

    q_blocks = ""
    for i, q in enumerate(questions):
        opts_html = ""
        options = q.get("options", [])
        if options:
            for opt in options:
                opts_html += f"<div style='padding:4px 10px;margin:3px 0;background:#f5f5f5;border-radius:4px;font-size:13px;'>{opt}</div>"
        kps = ", ".join(q.get("knowledge_points", []))
        q_blocks += f"""
        <div style="margin-bottom:18px;padding-bottom:14px;border-bottom:1px solid #e0e0e0;">
          <div style="font-weight:bold;font-size:14px;margin-bottom:6px;">
            第 {i+1} 题 <span style="font-weight:normal;color:#666;font-size:12px;">{q.get('question_type','')} · {kps}</span>
          </div>
          <div style="white-space:pre-wrap;line-height:1.8;font-size:13px;margin-bottom:8px;">{q.get('question_text','')}</div>
          {opts_html}
          <div style="margin-top:8px;color:#999;font-size:11px;">我的答案：________</div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  @page {{ size: A4; margin: 2cm; }}
  body {{ font-family: "Microsoft YaHei","PingFang SC",sans-serif; color: #1a1a1a; }}
</style></head><body>
<div style="text-align:center;margin-bottom:24px;">
  <h1 style="font-size:20px;margin-bottom:4px;">📝 专属练习题</h1>
  <p style="color:#666;font-size:13px;">{student_name} · {week_start or date.today().isoformat()} · 共 {len(questions)} 题</p>
  <p style="color:#999;font-size:11px;">这些题目根据你最近的试卷错题定制，只练最需要的地方</p>
</div>
{q_blocks}
<div style="text-align:center;margin-top:24px;color:#999;font-size:11px;border-top:1px solid #e0e0e0;padding-top:12px;">
  拾阶而上 · 做完后拍照上传，AI 自动批改
</div>
</body></html>"""

    buffer = BytesIO()
    pisa.CreatePDF(html, dest=buffer)
    return buffer.getvalue()


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
