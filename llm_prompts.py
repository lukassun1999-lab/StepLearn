#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM Prompt 模板（纯常量，自 skills_bridge.py 拆出）。

VISION_OCR 用于视觉识别；分析/生成/批改/方案各模板对应
english-mistake-analyzer 等 skill 的提示词（见各自注释）。
"""

VISION_OCR_PROMPT = """这是一张学生已作答的英语试卷图片。请仔细识别，并分两部分输出：

【第一部分：试卷正文】（按原文顺序）
- 逐题输出题号、题干、空格（用 ___题号___ 标注，如 ___36___）、选项（A/B/C/D 及其内容）。
- **重要：空格题号必须严格照抄试卷上印刷的数字，不得改写、重排或跳过。** 例如试卷上印的是 38，就写 ___38___，不要因为前面少识别了一个空格就写成 37。
- 每道题的选项按试卷原样列出。

【第二部分：学生作答】（重点，逐题识别）
学生通常在选项上打勾/画圈/填字母，或在横线上手写作答。请逐题列出学生的作答，格式为：
题号: 学生作答
例如：
26: B
27: even though
36: A
- 题号必须与试卷印刷题号一致。
- 若某题看不到学生作答痕迹，写"题号: 未作答"。
- 手写模糊无法辨认的，写"题号: [模糊]"，不要猜测具体内容。
- 特别注意：圈选标记旁边的选项字母、手写字母与题干粘连的情况（如把"B. full of"圈选后识别成"Bofull of"，应还原为 题号: B）。

直接输出内容，不要添加额外解释。"""



# ── Prompt Templates (extracted from english-mistake-analyzer SKILL.md) ──

MISTAKE_ANALYSIS_PROMPT = """分析以下英语试卷 OCR 文本，**只提取学生真正答错的题**，返回JSON（不要markdown代码块）:

{ocr_text}

【核心前提：自动批改模式】
本系统的使用场景是「学生在家完成作业后拍照上传」，因此试卷**通常没有老师批改痕迹，也不提供标准答案**。你必须承担「自动批改」职责：
- 逐题根据题干、选项和英语语法/词汇/篇章知识，**自行判定该题的正确答案**（correct_answer）；
- 再把「你判定的正确答案」与「学生实际作答」对比，不同的即为错题；
- 若 OCR 文本中已给出标准答案或批改痕迹（红叉/红勾/分数），则以卷面答案为准，你无需重复判定。
- 判定正确答案时务必严谨：只在有充分把握时给出；若题目信息残缺到无法判定正确答案（如题干被截断、选项不全），按规则 6 跳过该题。

【双输入模式：试卷 + 答题卡】
若 OCR 文本中包含「（答题卡）」段落，说明学生是在**答题卡上作答**、试卷本身没有书写。此时：
- 学生作答一律从**答题卡段落**读取（涂黑选项如 "3. B"、"5. A C" 或多选涂黑项；手写填空内容），**不要**从试卷段落找学生答案；
- 题目与选项从**试卷段落**读取；
- 把答题卡上的题号作答与试卷题目逐题配对后判定对错；答题卡上未涂/未填的题视为未作答，按规则 7 处理（不得放入 mistakes）；
- 试卷段落里印刷的示例答案、参考答案标注（如 "Key: 1-5 BCADC"）**不是学生作答**，一律忽略；
- 若 OCR 文本中没有「（答题卡）」段落，则默认学生答案直接书写在试卷上，按下方规则从试卷文本中识别学生作答。

【印刷参考答案（最高优先级答案源）】
若 OCR 文本中包含试卷印刷的参考答案（如 "参考答案"、"Key:"、"答案：1-5 BCADC"、逐题标注的答案）：
- 这些是该题**权威的正确答案**，逐题展开后直接采用为 correct_answer，**不要**自己重新判定该题答案；
- 它们是答案不是学生作答——学生作答仍从答题卡/试卷书写处读取（遵守上方规则）；
- 采用印刷答案的错题输出 answer_source 为 "printed_key"；自行判定答案的错题输出 "ai_inferred"；
- summary.printed_answer_key 逐题输出你采用到的印刷答案（如 {{"3":"B","5":"C"}}），**禁止**输出 "1-5 BCADC" 之类的范围形式；卷面没有印刷答案则输出空对象 {{}}。

【重要规则】
1. 只把"学生答案确实与正确答案不同"的题放进 mistakes。学生选对/填对的题一律不要放进来。
2. 比较时忽略选项字母前缀。例如学生答 "D. started a school"、正确答案 "started a school"，二者内容相同 → 学生答对了，**不要**算错题。同理 "A. cold"="cold"、"C, photographer"="photographer" 都算答对。
3. 注意 OCR 识别瑕疵：选项字母常与答案文字粘连，如 "Bofull of" 实为 "B. full of"、"A.cold" 实为 "A. cold"。需还原成真实作答再判断对错。
4. user_answer 与 correct_answer 必须用**同一格式**：
   - 有选项题型（单项选择/完形填空/多项选择等）：都写成「选项字母. 内容」（字母大写），如 "B. failed"、"A. until"，两者都带字母前缀；
   - 无选项题型（语法填空/选词填空/单句填空/翻译/写作等）：都只写答案内容（单词/短语/句子），不带字母。
5. question_text 必须包含该题**完整选项**：题干 + 换行 + 从 OCR 原样提取的选项列表（"A. xxx"、"B. xxx"...），不得省略选项。选项用于判对错（字母对应内容）与错题本展示。
6. 仅在「学生作答无法辨认」或「题目信息残缺到无法判定正确答案」时跳过该题，不要臆造错题。
   **注意：卷面没有批改痕迹、没有标准答案，不属于"无法判断"——此时应按【核心前提：自动批改模式】自行判定正确答案。**
7. 【最高优先级·绝对禁止】学生**未作答/空白/看不清**的题，**一律不得放进 mistakes**——缺做不是"错"，无错因可归。
   判断题时必须先确认"学生确实写了答案"，再比对对错。把"未作答"当错题是本系统最严重的错误，会直接误导家长。
8. 【逐题覆盖·禁止遗漏】对 OCR 文本中**每一道有学生作答的题目**都要逐一判定，不得只抽查部分题目。
   自动批改模式下，请在内部按「题号 → 学生答案 → 你判定的正确答案 → 是否一致」逐题过一遍，只把"一致=否"的题输出。
9. 每道错题必须做错因分类，error_cause 五类取一：
   - vocab 单词不认识：生词、拼写、词义混淆、固定搭配不熟
   - grammar 语法规则没掌握：时态/语态/单复数/冠词/介词/非谓语/从句等规则错误
   - syntax 长句拆不开：句子结构、成分划分、语序理解失败
   - discourse 读不懂文章逻辑：主旨、推理、衔接、上下文理解失败
   - careless 看题不仔细：粗心、漏看、审题失误
   cause_evidence 用一句话给出判断依据（如"答案含未掌握生词 XXX"、"动词时态与时间状语不符"、"两个选项含义相近，属词义辨析"）。
10. 每道错题输出 passage 字段：该题所属**阅读短文/对话的完整原文**（从 OCR 文本中原样提取，保留段落与题号不混入；若题目本身无短文——如语法填空/单项选择/单句完形——passage 必须为空字符串 ""）。

返回格式:
{{"mistakes":[{{"question_number":1,"question_text":"完整题干（含全部选项）","question_type":"语法填空","correct_answer":"full of","user_answer":"fill of","answer_source":"printed_key","error_cause":"vocab","cause_evidence":"拼写错误：full 写成 fill","passage":"","explanation":"本题考查...","knowledge_points":["非谓语动词"],"difficulty":2}}],"summary":{{"total_mistakes":0,"by_type":{{"语法填空":2}},"top_weak_points":["非谓语动词"],"overall_assessment":"...","printed_answer_key":{{}},"answered_count":0}}}}

summary 字段说明: printed_answer_key=卷面印刷参考答案（无则空对象）；answered_count=学生实际作答的题数（判对+判错都算，未作答不算）——用于覆盖率统计。"""


CAUSE_CHAIN_PROMPT = """分析学生的错因因果链，返回JSON（不要markdown代码块）。

学生年级: {grade}
教材版本: {textbook_version}

错题清单（已按受控错因分类，含近期多次考试）:
{mistakes_json}

错因五类定义:
- vocab 单词不认识：生词、拼写、词义混淆、固定搭配不熟
- grammar 语法规则没掌握：时态/语态/单复数/冠词/介词/非谓语/从句等规则错误
- syntax 长句拆不开：句子结构、成分划分、语序理解失败
- discourse 读不懂文章逻辑：主旨、推理、衔接、上下文理解失败
- careless 看题不仔细：粗心、漏看、审题失误

判断要求（英语是累积性技能，词汇→句法→语篇层层传导）:
1. primary_cause 是"核心瓶颈"：不是错得最多的那类，而是"补上它，其他很多错题会跟着减少"的那类
2. cause_chain 列出核心瓶颈如何传导为其他错因（from→to + 一句说明）
3. priority_kps 按因果链给出 3 个聚焦知识点：先补根因，不是错误率最高的
4. plain_language 严格按模板填空（【】内填数据，不自由发挥话术）:
   "孩子这周真正卡住的是【核心瓶颈通俗名】——【证据一句话】，先补【第一聚焦点】。"

返回格式:
{{
  "primary_cause": "vocab|grammar|syntax|discourse|careless",
  "primary_evidence": "证据：基于错题的统计与判断",
  "cause_chain": [{{"from": "词汇", "to": "语法", "note": "词汇不足导致无法判断句子成分"}}],
  "secondary_causes": ["grammar"],
  "priority_kps": ["高频核心词汇", "现在完成时（受词汇连累，次生）", "长难句主干划分"],
  "plain_language": "孩子这周真正卡住的是【词汇量】——【语法错题里3道是被生词绊倒的】，先补【高频核心词汇】。"
}}"""


QUESTION_GENERATION_PROMPT = """根据错题生成同类练习题，返回JSON:

{mistakes_json}

题型规范: {question_types_ref}

硬性要求:
1. 每道题必须自包含：不得引用试卷原文、阅读材料、passage、上文/下文等外部上下文——学生看到题干就能独立作答
2. 答案格式必须与题型匹配：
   - 选择题/完形填空等有选项题型：把选项写进题干（如 "___1___ A. ...  B. ...  C. ...  D. ..."），correct_answer 写选项字母
   - 语法填空/选词填空/单句填空/翻译/写作等无选项题型：correct_answer **必须写单词/短语/句子本身**，严禁写字母（A/B/C/D）！
3. 题目难度与对应错题一致；每道题提供完整中文解析
4. 语法填空/单句填空等无选项题型，若正确填答是某词的**词形变化**（比较级/最高级/时态/语态/名词复数/词性转换等），题干必须在空处用括号给出原词，例如 "The mountain is the ___ (high) mountain in Shandong"；否则学生没有词根线索无法作答。纯虚词空（连词/介词/冠词/代词等）无需提示词。
   判断方法：correct_answer 与空处直接填的词若不同形（如 highest 是 high 的变形），就必须带提示词。
5. 选词填空必须提供**候选词框**：在题干末尾列出 6-8 个候选词（含正确答案与干扰词），如 "候选词：although, though, because, since, unless, whether"；没有词库学生无法作答。
   若错题本身带词库，优先沿用原词库。
6. 若错题含 **passage 字段**（阅读类），新题必须基于该短文出题：
   - 短文**原样**放入返回的 passage 字段（不得改写、缩写或省略）
   - 题目从短文内容出（事实细节/主旨/推理/词义猜测等），带 4 个选项，题干自包含不引用外部材料
   - 题干中不得出现"根据上文/原文/文章"这类依赖未提供材料的表述

返回格式:
{{"questions":[{{"source_mistake_id":1,"question_type":"语法填空","question_text":"完整题干（含选项，如为有选项题型）","options":["A","B","C","D"],"correct_answer":"按题型规则填字母或答案内容","explanation":"中文解析","knowledge_points":["非谓语动词"],"difficulty":2,"passage":"短文原文（错题有 passage 时原样保留，否则空字符串）"}}]}}"""


ESSAY_REVIEW_PROMPT = """批改学生英语作文，返回JSON（不要markdown代码块）。

学生年级: {grade}
作文题目/要求:
{question}

学生作文:
{essay}

批改要求:
1. errors：逐处标出语法/拼写/用词/标点错误——引用原文片段（quote）、给出类型（type: 语法|拼写|用词|标点）、一句话问题说明（issue）、**局部修改示例**（suggestion，只改该处，不重写整句以上）；错误超过 8 处取最典型的 8 处
2. evaluation：内容完整性（content）/结构逻辑（structure）/语言准确性（language）/词汇丰富度（vocabulary）四维评价，每维 1-2 句
3. score_suggestion：按中高考作文评分口径给分数段（band，如"二档（13-15/20）"）+ 一句依据（basis）
4. strengths：2-3 条具体优点（尽量引用作文中的证据）
5. advice：给学生的改进建议 2-3 条，具体可执行（如"把 if 条件句改用 unless"、"多使用连接词 however/therefore"），不用空话

内容管控：**不得整篇改写学生作文**；suggestion 仅给局部修改示例；advice 用可执行行动建议。

返回格式:
{{
  "errors": [{{"quote": "原文片段", "type": "语法|拼写|用词|标点", "issue": "问题说明", "suggestion": "局部修改示例"}}],
  "evaluation": {{"content": "", "structure": "", "language": "", "vocabulary": ""}},
  "score_suggestion": {{"band": "", "basis": ""}},
  "strengths": ["", ""],
  "advice": ["", ""]
}}"""


GRADING_PROMPT = """批改学生练习题答案，返回JSON:

练习题: {questions_json}
学生答案: {student_answers_json}

返回格式:
{{"results":[{{"question_index":0,"is_correct":true,"student_answer":"B","correct_answer":"B","explanation":"解析","knowledge_point_feedback":"掌握情况"}}],"summary":{{"total":10,"correct":7,"accuracy":0.7,"mastered_points":["定语从句"],"still_weak_points":["非谓语动词"],"overall_feedback":"总结"}}}}"""


LEARNING_PLAN_PROMPT = """为学生生成个性化学习方案，返回JSON（不要markdown代码块）。

学生基础信息:
- 姓名: {name}
- 年级: {grade}
- 当前分数: {score}
- 住校/走读: {school_type}
- 目标分数: {target_score}

错题与薄弱点诊断:
{diagnosis_json}

个性化画像（参考 chat.md 六大部分）:
{profile_json}

长期学习记忆（跨月沉淀的学生画像，可能为空）:
{memory_section}
- 若非空，方案设计必须与之呼应：recurring_causes 里的错因要用与之前不同的新讲法再攻；
  effective_methods 里验证有效的做法应延续
- 若为空（"（暂无）"），忽略本节

错因因果链画像（diagnosis_json 中的 cause_profile 字段，可能缺失）:
- 它给出孩子当前的核心瓶颈（primary_cause，如 vocab=词汇量不足）与传导链（cause_chain，如 词汇→语法）
- 若存在，weak_point_priority 必须遵守：**根因优先，不是错误率优先**
  1. 把因果链根因对应的知识点排在最前（即使它当前不是错误率最高的）
  2. "错得最多但属次生表现"的知识点应降级（如语法错题是词汇不足的下游症状时，语法类知识点排后）
  3. 每项 reason 必须引用因果链判断（如"词汇量是核心瓶颈，语法错题为次生表现"），不能只写"X道错题"
- 若 cause_profile 缺失或为空，按薄弱点矩阵常规排序

请基于以上画像做真正个性化的诊断和方案设计，返回格式:
{{
  "diagnosis_report": {{
    "learning_style": {{
      "visual": 0-10,
      "auditory": 0-10,
      "kinesthetic": 0-10,
      "read_write": 0-10,
      "dominant": "视觉型/听觉型/动觉型/读写型",
      "auxiliary": "...",
      "interpretation": "简短解读"
    }},
    "time_efficiency": {{
      "total_hours": "一周可用总时长",
      "peak_coverage": "高峰时段被英语学习覆盖的比例",
      "fragment_utilization": "碎片时间利用率评估",
      "conflict_risk": "时间冲突风险"
    }},
    "weak_point_matrix": [
      {{"point": "薄弱点", "loss_rate": "失分率", "potential": "提升潜力", "difficulty": "训练难度", "priority": "🥇/🥈/🥉"}}
    ],
    "psychological_motivation": {{
      "identity": "与英语的关系描述",
      "drive": "内驱力 1-5",
      "resilience": "抗挫力 1-5",
      "autonomy": "自主性 1-5"
    }},
    "conclusion": {{
      "core_findings": ["核心发现1", "核心发现2", "核心发现3"],
      "short_term": "短期建议（1个月）",
      "medium_term": "中期建议（1学期）",
      "long_term": "长期建议（1年）",
      "warning": "需要警惕的风险"
    }}
  }},
  "plan_design_logic": {{
    "time_allocation": "时间分配逻辑",
    "psychological_design": "心理动机设计",
    "cognitive_design": "认知规律设计",
    "precision_design": "精准提分设计",
    "anti_abandonment": "防放弃设计"
  }},
  "weekly_schedule": {{"saturday_afternoon": "完成练习题30分钟"}},
  "modules": [{{"name": "词汇", "priority": 1, "weekly_time_minutes": 120, "focus": "高考高频词汇", "daily_word_count": 8}}],
  "weak_point_priority": [{{"knowledge_point": "非谓语动词", "severity": "高", "reason": "2道错题"}}],
  "minimum_standard": {{"boarding": "每日词汇+1篇阅读", "day_student": "每晚词汇+听力"}},
  "motivation_message": "鼓励话，可结合孩子的1个月小目标和英语变厉害后想做什么（必须为纯文本字符串，不得返回 JSON 对象）",
  "parent_guide": "家长建议，结合家长陪学时间、监督需求、孩子心声（必须为纯文本字符串，不得返回 JSON 对象）",
  "parent_growth_tasks": [
    {{"week": 1, "theme": "观察者", "title": "情绪标注练习", "task": "连续3天，在孩子学英语时观察并记录情绪，不做评判", "example": "'我注意到你做阅读时皱了眉'", "goal": "帮助孩子被看见，降低焦虑"}},
    {{"week": 2, "theme": "倾听者", "title": "5分钟无评判倾听", "task": "每天留5分钟，只听孩子说说学英语的感受", "example": "'今天英语哪个部分最费劲？'", "goal": "建立安全表达通道"}},
    {{"week": 3, "theme": "提问者", "title": "错题分析会", "task": "陪孩子看错题，只提问不讲解", "example": "'这道题你当时怎么想的？'", "goal": "培养元认知和自主纠错"}},
    {{"week": 4, "theme": "肯定者", "title": "具体行为+影响反馈", "task": "每天反馈一个具体进步行为及其影响", "example": "'你今天主动复习了单词，这让我觉得你在为自己负责'", "goal": "强化内驱力和身份认同"}}
  ],
  "motivation_cards": [
    {{"title": "启动卡", "content": "一句针对孩子心声和目标的启动鼓励语"}},
    {{"title": "成就卡", "content": "可视化本周/本月进展的成就总结"}},
    {{"title": "抗挫卡", "content": "遇到错题或想放弃时可以读的一句话"}}
  ],
  "metacognitive_review": {{
    "child_reflection": [
      "这周学英语时，我最投入的是哪一刻？",
      "哪类题让我最有挫败感？我当时想到了什么？",
 "下周我想先攻克哪个小目标？"
    ],
    "parent_observation": [
      "这周孩子主动提到英语几次？",
      "孩子执行计划时，松紧程度如何？"
    ],
    "error_categories": ["语法混淆", "词汇不熟", "阅读理解", "听力", "写作表达", "粗心"],
    "adjustment_rules": "根据下周完成率自动调整：≥80% 提升10%难度；50-80% 维持；<50% 降低20%"
  }}
}}"""


PLAN_UPDATE_PROMPT = """更新学习方案，基于本周完成率和画像生成AI诊所建议与下周调整，返回JSON:

学生{student_id}, 周{week_start}
薄弱点: {weak_point_matrix}
新错题: {new_mistakes_json}
已掌握: {mastered_mistakes_json}
统计: 新{new_count} 掌握{mastered_count}

本周综合完成率: {completion_rate}%（学生活动权重60% + 家长参与权重40%）
家长任务包进度: {parent_task_progress_json}
家长任务包详情: {parent_tasks_json}
关键抉择（来自画像）: {plan_choices_json}
当前模块设置: {current_modules_json}
长期学习记忆（跨月沉淀，"（暂无）"则忽略）: {memory_summary}
- recurring_causes 中的错因若仍在新错题里出现，next_week_focus 必须点名并换讲法

调整规则（必须遵守）:
- 综合完成率 ≥ 80%: 下周难度/任务量提升约 10%（可在现有 daily_word_count 上 +1~2，或增加 1 个薄弱模块练习）
- 综合完成率 50%-80%: 下周维持当前难度，优化时间安排或降低摩擦。若家长任务完成率低于学生活跃度，应在 parent_guide 中鼓励家长更多参与。
- 综合完成率 < 50%: 下周难度/任务量降低约 20%，并加入防放弃设计。需分析是学生端还是家长端掉队，给出针对性建议。

返回格式:
{{
  "updated_weak_points": [],
  "ai_clinic": "给老师的诊所建议",
  "next_week_focus": ["重点1", "重点2"],
  "plan_adjustments": "具体调整说明（含家长参与度分析）",
  "adjusted_modules": [{{"name": "词汇", "weekly_time_minutes": 120, "daily_word_count": 8, "focus": "..."}}],
  "motivation_message": "给孩子下周的鼓励语",
  "parent_guide": "给家长的建议（如果家长参与度低，提供降低门槛的建议）"
}}"""


SIMILAR_QUESTION_PROMPT = """你是一位经验丰富的英语老师。学生做错了下面这道题，请生成{count}道考察**同一知识点**但题干完全不同的类似题，帮助学生巩固。

原错题:
- 题目: {question}
- 题型: {question_type}
- 正确答案: {correct_answer}
- 学生答案: {user_answer}
- 解析: {explanation}
- 知识点: {knowledge_points}

硬性要求:
1. 每道类似题考察相同的知识点，但必须更换场景、人物、语境、词汇——不得仅替换一两个词
2. 严禁生成与原题题干相同或高度相似的题目（如仅换了人名/动词）
3. 每道题的场景必须互不相同（比如一道关于学校、一道关于家庭、一道关于社会）
4. 题目难度与原题一致
5. 每道题提供完整中文解析
6. **题目必须自包含**：不得引用试卷原文、阅读材料、passage、上文/下文等外部上下文——学生看到题干就能独立作答
7. **答案格式必须与题型匹配**：
   - 选择题/完形填空（有选项的题型）：把选项写进题干（如 "___1___ A. ...  B. ...  C. ...  D. ..."），correct_answer 写选项字母
   - 语法填空/选词填空/单句填空/翻译/写作（无选项题型）：correct_answer **必须写单词/短语/句子本身**，严禁写字母（A/B/C/D）！

返回JSON格式:
{{"questions":[{{"question_text":"完整题干（含选项，如为有选项题型）","question_type":"{question_type}","options":["A","B","C","D"],"correct_answer":"按题型规则填字母或答案内容","explanation":"中文解析","knowledge_points":["知识点"],"difficulty":{difficulty}}}]}}"""




MONTHLY_ANALYSIS_PROMPT = """你是学生的英语学习顾问，请基于以下月度数据生成分月总结分析，返回JSON（不要markdown代码块）。

学生: {name}, 年级: {grade}, 当前分数: {score}
月份: {month_label}

月度数据:
- 总错题数: {total_mistakes}
- 已攻克数: {mastered_count}
- 练习次数: {practice_count}
- 平均正确率: {accuracy}

知识点错题分布:
{kp_breakdown}

分数变化:
{score_history}

请从以下维度分析:
1. 进步亮点: 哪些知识点有明显进步？哪些错误类型在减少？
2. 需要关注: 哪些知识点反复出错？有没有退步的趋势？
3. 下月建议: 针对性地给出2-3条下月学习重点建议

返回格式:
{{"progress_points":["进步1","进步2"],"regression_points":["关注1"],"next_month_suggestions":["建议1","建议2"],"overall_assessment":"一句话总结本月表现和趋势"}}"""


STUDENT_MEMORY_PROMPT = """你是学生的学习档案管理员。请把"本月学情"合并进该学生的长期记忆，返回JSON（不要markdown代码块）。

长期记忆只保留跨周稳定、对制定后续学习方案有用的信息：这个孩子是什么类型的学习者、哪类错因反复出现、哪种讲法/练习方式对他确实有效、哪种无效。一次性的、本月特有的细节请丢弃。

学生: {name}, 年级: {grade}
数据月份: {month_label}

已有长期记忆（可能为空）:
{old_memory_json}

本月学情:
{month_facts}

合并规则:
1. memory_summary：不超过 150 字的连贯中文描述（画像 + 有效/无效方法），信息密度优先
2. recurring_causes：本月错因与旧记忆重复、或本月内多次出现的错因才保留
3. effective_methods：本月数据显示进步明显处对应的做法，或旧记忆中仍有效的做法
4. 与旧记忆冲突时，以本月数据为准

返回格式:
{{"memory_summary":"...","learner_type":"一句话学习者类型","recurring_causes":["错因1"],"effective_methods":["有效做法1"]}}"""

