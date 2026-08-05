#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 调用抽象层
- 支持 Anthropic API 和 OpenAI 兼容 API（DeepSeek/通义千问/GLM/Moonshot 等）
- 指数退避重试 (429/5xx)
- JSON Schema 输出校验
- 开发模式缓存 (LLM_CACHE_ENABLED=true)
- Token 用量 + 成本追踪

使用方法:
  # Anthropic
  set ANTHROPIC_API_KEY=sk-ant-...
  set LLM_MODEL=claude-sonnet-4-6

  # DeepSeek (推荐，便宜且中文好)
  set LLM_API_KEY=sk-...
  set LLM_BASE_URL=https://api.deepseek.com
  set LLM_MODEL=deepseek-chat

  # 通义千问
  set LLM_API_KEY=sk-...
  set LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
  set LLM_MODEL=qwen-plus

  # 智谱 GLM
  set LLM_API_KEY=...
  set LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
  set LLM_MODEL=glm-4-flash

  # 无 API key → 自动 demo 模式
"""

import json
import os
import time
import hashlib
import base64
import threading
from datetime import datetime

# Lock for atomic cache writes across worker threads
_cache_lock = threading.Lock()

# ═══════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════

DEFAULT_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")
CACHE_ENABLED = os.environ.get("LLM_CACHE_ENABLED", "false").lower() == "true"
MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "3"))
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "120"))  # seconds per API attempt
CACHE_DIR = os.path.join(os.path.dirname(__file__), ".llm_cache")

# Which backend to use
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "")  # Custom Anthropic endpoint (Kimi, etc.)
HAS_API_KEY = bool(ANTHROPIC_KEY or LLM_API_KEY)
BACKEND = "anthropic" if (ANTHROPIC_KEY) else ("openai" if LLM_API_KEY else "demo")

# Vision / OCR configuration
OCR_BACKEND = os.environ.get("OCR_BACKEND", "auto").lower()  # auto | vision | tesseract
VISION_MODEL = os.environ.get("VISION_MODEL", "") or DEFAULT_MODEL
VISION_MAX_IMAGE_SIZE = int(os.environ.get("VISION_MAX_IMAGE_SIZE", "2097152"))

# Pricing per 1M tokens (USD)
PRICING = {
    # Anthropic
    "claude-sonnet-4-6":     {"input": 3.00, "output": 15.00},
    "claude-opus-4-8":       {"input": 15.00, "output": 75.00},
    "claude-haiku-4-5":      {"input": 0.80, "output": 4.00},
    # DeepSeek
    "deepseek-chat":         {"input": 0.27, "output": 1.10},
    "deepseek-reasoner":     {"input": 0.55, "output": 2.19},
    # Qwen
    "qwen-plus":             {"input": 0.80, "output": 2.00},
    "qwen-max":              {"input": 2.40, "output": 9.60},
    # GLM
    "glm-4-flash":           {"input": 0.00, "output": 0.00},  # 智谱有免费额度
    # Moonshot / Kimi
    "moonshot-v1-8k":        {"input": 0.60, "output": 0.60},
    "kimi-k2.6":             {"input": 0.60, "output": 0.60},
    # Vision-capable models (best-effort pricing; calibrate against real bills)
    "qwen-vl-plus":          {"input": 2.00, "output": 6.00},
    "qwen-vl-max":           {"input": 4.00, "output": 12.00},
    "glm-4v":                {"input": 2.00, "output": 2.00},
    # Generic fallback
    "default":               {"input": 0.50, "output": 1.50},
}


class LLMError(Exception):
    pass


class LLMValidationError(LLMError):
    pass


class LLMRetryExhausted(LLMError):
    pass


# ═══════════════════════════════════════════════════
# Client
# ═══════════════════════════════════════════════════

class LLMClient:
    def __init__(self, model: str = None, db_path: str = None):
        self.model = model or DEFAULT_MODEL
        self._db_path = db_path  # lazy import to avoid circular dependency

    @property
    def db_path(self):
        if self._db_path is None:
            from db import DB_PATH
            self._db_path = DB_PATH
        return self._db_path

    def _get_cache_key(self, prompt: str, schema: dict = None) -> str:
        raw = f"{self.model}:{prompt}:{json.dumps(schema or {}, sort_keys=True)}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _cache_get(self, key: str) -> dict | None:
        if not CACHE_ENABLED:
            return None
        cache_file = os.path.join(CACHE_DIR, f"{key}.json")
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def _cache_set(self, key: str, result: dict) -> None:
        if not CACHE_ENABLED:
            return
        os.makedirs(CACHE_DIR, exist_ok=True)
        cache_file = os.path.join(CACHE_DIR, f"{key}.json")
        tmp_file = f"{cache_file}.tmp.{threading.current_thread().ident}"
        with _cache_lock:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False)
            os.replace(tmp_file, cache_file)

    def _calculate_cost(self, prompt_tokens: int, output_tokens: int, model: str = None) -> float:
        prices = PRICING.get(model or self.model, PRICING["default"])
        return (prompt_tokens / 1_000_000) * prices["input"] + \
               (output_tokens / 1_000_000) * prices["output"]

    def _validate_output(self, result: dict, schema: dict) -> None:
        """Basic JSON Schema subset validation. Raises LLMValidationError."""
        if schema is None:
            return
        for key, spec in schema.items():
            if spec.get("required") and key not in result:
                raise LLMValidationError(f"Required field '{key}' missing from LLM output")
            if key in result:
                expected_type = spec.get("type")
                if expected_type == "array" and not isinstance(result[key], list):
                    raise LLMValidationError(
                        f"Field '{key}' expected array, got {type(result[key]).__name__}"
                    )
                if expected_type == "string" and not isinstance(result[key], str):
                    raise LLMValidationError(
                        f"Field '{key}' expected string, got {type(result[key]).__name__}"
                    )
                if expected_type == "integer" and not isinstance(result[key], int):
                    raise LLMValidationError(
                        f"Field '{key}' expected int, got {type(result[key]).__name__}"
                    )
                if expected_type == "number" and not isinstance(result[key], (int, float)):
                    raise LLMValidationError(
                        f"Field '{key}' expected number, got {type(result[key]).__name__}"
                    )

    # ── Demo Data ──────────────────────────────────

    DEMO_DATA = {
        "analyze": {
            "mistakes": [
                {
                    "question_number": 1,
                    "question_text": "The manager, ___ his factory's products were poor in quality, decided to give the workers further training.\nA. knowing  B. known  C. to know  D. being known",
                    "question_type": "语法填空",
                    "correct_answer": "A",
                    "user_answer": "B",
                    "error_reason": "非谓语动词误用",
                    "explanation": "本题考查非谓语动词作状语。主语The manager与know之间是主动关系，应用现在分词knowing作状语，表示'知道'。known表示被动，意为'被知道'，不符合语境。",
                    "knowledge_points": ["非谓语动词", "现在分词作状语"],
                    "difficulty": 3,
                },
                {
                    "question_number": 2,
                    "question_text": "A cook will be immediately fired if he is found ___ in the kitchen.\nA. smoke  B. smoking  C. to smoke  D. smoked",
                    "question_type": "语法填空",
                    "correct_answer": "B",
                    "user_answer": "C",
                    "error_reason": "find复合结构误用",
                    "explanation": "find sb. doing sth. 表示'发现某人正在做某事'。这里是被动语态 he is found smoking，意为'他被发现在抽烟'。to smoke表示不定式，一般不用于find的复合结构中。",
                    "knowledge_points": ["非谓语动词", "find复合结构"],
                    "difficulty": 2,
                },
                {
                    "question_number": 3,
                    "question_text": "It was in the small house ___ was built with stones by his father ___ he spent his childhood.\nA. which; that  B. that; where  C. which; which  D. that; which",
                    "question_type": "语法填空",
                    "correct_answer": "A",
                    "user_answer": "B",
                    "error_reason": "定语从句与强调句混淆",
                    "explanation": "第一空考查定语从句，先行词house在从句中作主语，用which引导；第二空考查强调句型It was...that...，强调地点状语in the small house。",
                    "knowledge_points": ["定语从句", "强调句型"],
                    "difficulty": 4,
                },
                {
                    "question_number": 4,
                    "question_text": "The number of people who ___ killed in the accident ___ still unknown.\nA. was; was  B. were; were  C. were; was  D. was; were",
                    "question_type": "语法填空",
                    "correct_answer": "C",
                    "user_answer": "D",
                    "error_reason": "主谓一致混淆",
                    "explanation": "第一空：who指代people，谓语用复数were；第二空：主语是The number（单数），谓语用was。the number of + 复数名词作主语时，谓语用单数。",
                    "knowledge_points": ["主谓一致", "the number of"],
                    "difficulty": 2,
                },
                {
                    "question_number": 5,
                    "question_text": "Only when he reached the tea house ___ it was the same place he'd been in last year.\nA. he realized  B. he did realize  C. realized he  D. did he realize",
                    "question_type": "语法填空",
                    "correct_answer": "D",
                    "user_answer": "A",
                    "error_reason": "倒装句规则遗忘",
                    "explanation": "Only + 状语从句置于句首时，主句要用部分倒装。正常语序是he realized，倒装后变为did he realize。",
                    "knowledge_points": ["倒装句", "only的倒装"],
                    "difficulty": 3,
                },
            ],
            "summary": {
                "total_mistakes": 5,
                "by_type": {"语法填空": 5},
                "top_weak_points": ["非谓语动词", "定语从句", "倒装句"],
                "overall_assessment": "学生在非谓语动词和特殊句型（倒装、强调句）方面薄弱，主谓一致也有漏洞。建议重点突破非谓语动词板块，同时巩固三大从句和特殊句型。",
            },
        },
        "generate": {
            "questions": [
                {
                    "source_mistake_id": 1,
                    "question_type": "语法填空",
                    "question_text": "___ (see) from the top of the mountain, the city looks beautiful.\nA. Seeing  B. Seen  C. To see  D. Having seen",
                    "options": ["A. Seeing", "B. Seen", "C. To see", "D. Having seen"],
                    "correct_answer": "B",
                    "explanation": "本题考查过去分词作状语。主语the city与see之间是被动关系（城市被看），应用过去分词Seen作状语。",
                    "knowledge_points": ["非谓语动词", "过去分词作状语"],
                    "difficulty": 2,
                },
                {
                    "source_mistake_id": 2,
                    "question_type": "语法填空",
                    "question_text": "When I came in, I found him ___ (lie) on the sofa, reading a novel.",
                    "options": [],
                    "correct_answer": "lying",
                    "explanation": "find sb. doing sth. 发现某人正在做某事。lie的现在分词是lying。",
                    "knowledge_points": ["非谓语动词", "find复合结构"],
                    "difficulty": 2,
                },
                {
                    "source_mistake_id": 3,
                    "question_type": "语法填空",
                    "question_text": "It was at the airport ___ I met my old friend for the first time.\nA. where  B. that  C. which  D. when",
                    "options": ["A. where", "B. that", "C. which", "D. when"],
                    "correct_answer": "B",
                    "explanation": "本题考查强调句型 It was...that...，强调地点状语 at the airport。注意区分定语从句：如果去掉It was...that后句子完整，则为强调句型。",
                    "knowledge_points": ["强调句型", "定语从句辨析"],
                    "difficulty": 3,
                },
                {
                    "source_mistake_id": 4,
                    "question_type": "语法填空",
                    "question_text": "A number of students ___ (be) waiting outside the office now.",
                    "options": [],
                    "correct_answer": "are",
                    "explanation": "a number of + 复数名词作主语时，谓语用复数。注意区分：the number of + 复数名词作主语时，谓语用单数。",
                    "knowledge_points": ["主谓一致", "a number of vs the number of"],
                    "difficulty": 2,
                },
                {
                    "source_mistake_id": 5,
                    "question_type": "语法填空",
                    "question_text": "Not until he left his home ___ (do) he begin to know how important the family was for him.",
                    "options": [],
                    "correct_answer": "did",
                    "explanation": "Not until...置于句首时，主句用部分倒装。正常语序为he began，倒装后变为did he begin。",
                    "knowledge_points": ["倒装句", "not until倒装"],
                    "difficulty": 3,
                },
            ],
        },
        "grade": {
            "results": [
                {"question_index": 0, "is_correct": True, "student_answer": "B", "correct_answer": "B",
                 "explanation": "回答正确！过去分词作状语表示被动，你已经掌握了。",
                 "knowledge_point_feedback": "非谓语动词-过去分词：已掌握"},
                {"question_index": 1, "is_correct": True, "student_answer": "lying", "correct_answer": "lying",
                 "explanation": "正确！find sb. doing 是固定搭配。",
                 "knowledge_point_feedback": "find复合结构：已掌握"},
                {"question_index": 2, "is_correct": False, "student_answer": "A", "correct_answer": "B",
                 "explanation": "误选where是因为把它当定语从句了。it was at the airport...是强调句型，应该用that。",
                 "knowledge_point_feedback": "强调句型 vs 定语从句：还需练习"},
                {"question_index": 3, "is_correct": True, "student_answer": "are", "correct_answer": "are",
                 "explanation": "正确！a number of + 复数名词 + 复数谓语。",
                 "knowledge_point_feedback": "主谓一致：已掌握"},
                {"question_index": 4, "is_correct": True, "student_answer": "did", "correct_answer": "did",
                 "explanation": "正确！not until倒装已经掌握。",
                 "knowledge_point_feedback": "倒装句：已掌握"},
            ],
            "summary": {
                "total": 5, "correct": 4, "accuracy": 0.8,
                "mastered_points": ["过去分词作状语", "find复合结构", "主谓一致", "倒装句"],
                "still_weak_points": ["强调句型与定语从句辨析"],
                "overall_feedback": "表现不错！5题答对4题，正确率80%。强调句型与定语从句的辨析还需要再练，其他知识点掌握得很好。",
            },
        },
        "plan": {
            "weekly_schedule": {
                "weekday_morning": "晨读15分钟：复习前一天的高频词汇",
                "weekday_evening": "完成1篇阅读理解 + 5道语法填空（住校自主安排）",
                "saturday_morning": "家长拍照上传本周试卷",
                "saturday_afternoon": "完成专属练习题 30-40 分钟",
                "sunday": "整理错题笔记 + 预习下周词汇",
            },
            "modules": [
                {"name": "词汇", "priority": 1, "weekly_time_minutes": 100, "focus": "高考高频词汇 + 试卷生词", "daily_word_count": 8},
                {"name": "语法", "priority": 2, "weekly_time_minutes": 90, "focus": "非谓语动词 + 从句 + 特殊句型", "daily_word_count": 0},
                {"name": "阅读", "priority": 3, "weekly_time_minutes": 60, "focus": "每日1篇阅读理解 + 长难句分析", "daily_word_count": 0},
            ],
            "weak_point_priority": [
                {"knowledge_point": "非谓语动词", "severity": "高", "reason": "2道错题，错误率100%"},
                {"knowledge_point": "定语从句", "severity": "高", "reason": "与强调句型混淆"},
                {"knowledge_point": "倒装句", "severity": "中", "reason": "only倒装规则遗忘"},
                {"knowledge_point": "主谓一致", "severity": "中", "reason": "a number of vs the number of 混淆"},
                {"knowledge_point": "强调句型", "severity": "中", "reason": "与定语从句辨析不清"},
            ],
            "minimum_standard": {
                "boarding": "每天完成：词汇复习10分钟 + 1篇阅读理解 + 5道语法题。周六回家完成专属练习题。",
                "day_student": "每晚完成：词汇复习15分钟 + 听力训练10分钟 + 1篇阅读理解。",
            },
            "motivation_message": "嘿，我看了你的卷子。你的语法基础其实不错，主要就是几个具体的地方在坑你——非谓语动词到底用doing还是done、强调句和定语从句怎么区分、什么时候该倒装。找到了这几块短板，咱们就集中练，不刷整套卷子。搞定了这些，下次考试至少找回5-8分。怎么样？",
            "parent_guide": "家长只需要做三件事：①每周六上午拍照发一张孩子最近做过的英语卷子；②收到PDF后打印出来放孩子桌上；③孩子做完后拍照发回来。全程不超过15分钟。系统会自动分析、出题、批改、追踪。",
        },
        "essay_review": {
            "errors": [
                {"quote": "I go to school by foot every day.",
                 "type": "用词", "issue": "by foot 应为 on foot", "suggestion": "I go to school on foot every day."},
                {"quote": "She don't like math.",
                 "type": "语法", "issue": "第三人称单数否定应为 doesn't", "suggestion": "She doesn't like math."}
            ],
            "evaluation": {
                "content": "内容切题，覆盖了题目要求的要点，但细节展开不足。",
                "structure": "有基本结构，缺少衔接词，段落之间过渡生硬。",
                "language": "语法基本正确，存在少量主谓一致和固定搭配错误。",
                "vocabulary": "词汇基础可，可尝试更多高级表达（如 instead of, as a result）。"
            },
            "score_suggestion": {"band": "二档（13-15/20）", "basis": "内容完整、语言基本准确，结构与词汇有提升空间"},
            "strengths": ["能完整表达题目要点", "句式尝试多样", "书写规范"],
            "advice": ["多使用连接词（however/therefore/firstly）增强连贯", "背诵并运用 5 个高分句型", "写完后自查主谓一致"]
        },
    }

    # ── Public API ──────────────────────────────────

    def call(self, prompt: str, schema: dict = None, max_retries: int = None,
             task_id: int = None, call_type: str = "") -> dict:
        """
        Call LLM with automatic retry, validation, caching, and cost logging.

        Args:
            prompt: The LLM prompt (system + user combined as a single message)
            schema: Optional dict mapping field names to {"type": "...", "required": bool}
            max_retries: Override default retry count
            task_id: Associated ai_task ID for logging
            call_type: Category for cost tracking ('analyze'|'generate'|'grade'|'report'|'plan')

        Returns:
            Parsed dict from LLM JSON response.

        Raises:
            LLMValidationError: Output failed schema validation after all retries
            LLMRetryExhausted: All retries exhausted due to API errors
        """
        retries = max_retries if max_retries is not None else MAX_RETRIES

        # Demo mode: return demo data when no API key is configured
        if not HAS_API_KEY:
            demo = self.DEMO_DATA.get(call_type)
            if demo:
                self._log_usage(task_id, call_type, 0, 0, 0, 0, 0, cached=True)
                return demo.copy()
            return {}

        # Check cache
        cache_key = self._get_cache_key(prompt, schema)
        cached = self._cache_get(cache_key)
        if cached:
            self._log_usage(task_id, call_type, 0, 0, 0, 0, 0, cached=True)
            return cached

        last_error = None
        for attempt in range(retries + 1):
            try:
                start_ms = int(time.time() * 1000)
                result, prompt_tokens, output_tokens = self._call_api(prompt)
                duration_ms = int(time.time() * 1000) - start_ms

                # Validate output
                try:
                    self._validate_output(result, schema)
                except LLMValidationError:
                    if attempt < retries:
                        prompt = self._add_validation_fix_prompt(prompt, result, schema)
                        continue
                    raise  # will be caught below and wrapped

                # Success — cache + log
                self._cache_set(cache_key, result)
                self._log_usage(task_id, call_type, prompt_tokens, output_tokens,
                                self._calculate_cost(prompt_tokens, output_tokens),
                                duration_ms, attempt, cached=False)
                return result

            except LLMValidationError as e:
                last_error = e
            except Exception as e:
                last_error = e
                if attempt < retries:
                    wait = 2 ** attempt
                    time.sleep(wait)
                    continue

        if isinstance(last_error, LLMValidationError):
            raise last_error
        raise LLMRetryExhausted(
            f"LLM call failed after {retries} retries. Last error: {last_error}"
        )

    def call_vision(self, image_path: str, prompt: str, schema: dict = None,
                    max_retries: int = None, task_id: int = None,
                    call_type: str = "ocr") -> dict:
        """Call a vision-capable LLM with an image + text prompt.

        Returns parsed dict (same shape as call()). In demo mode, returns
        placeholder text. Falls back to _raw_text wrapping if the response
        is not valid JSON.
        """
        retries = max_retries if max_retries is not None else MAX_RETRIES
        model = VISION_MODEL or self.model

        # Demo mode
        if not HAS_API_KEY:
            demo_text = "[DEMO] 图片内容模拟识别：这是一张用于演示的图片，系统未配置真实 API key，因此返回占位文本供流程测试使用。"
            self._log_usage(task_id, call_type, 0, 0, 0, 0, 0, cached=True, model=model)
            return {"_raw_text": demo_text, "confidence": 0.95}

        # Cache key includes file mtime so replacing the image invalidates cache
        cache_key = self._get_cache_key(
            f"vision:{image_path}:{os.path.getmtime(image_path)}:{prompt}", schema
        )
        cached = self._cache_get(cache_key)
        if cached:
            self._log_usage(task_id, call_type, 0, 0, 0, 0, 0, cached=True, model=model)
            return cached

        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image not found: {image_path}")

        # Resize if necessary; if Pillow is unavailable, send as-is
        prepared_path = self._prepare_image(image_path)
        try:
            with open(prepared_path, "rb") as f:
                image_bytes = f.read()
        finally:
            if prepared_path != image_path and os.path.exists(prepared_path):
                try:
                    os.remove(prepared_path)
                except Exception:
                    pass

        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        mime_type = self._detect_mime_type(image_path)
        estimated_image_tokens = self._estimate_image_tokens(image_bytes)

        last_error = None
        for attempt in range(retries + 1):
            try:
                start_ms = int(time.time() * 1000)
                result, prompt_tokens, output_tokens = self._call_vision_api(
                    image_b64=image_b64, mime_type=mime_type,
                    prompt=prompt, model=model,
                )
                duration_ms = int(time.time() * 1000) - start_ms

                total_prompt_tokens = prompt_tokens + estimated_image_tokens

                try:
                    self._validate_output(result, schema)
                except LLMValidationError:
                    if attempt < retries:
                        prompt = self._add_validation_fix_prompt(prompt, result, schema)
                        continue
                    raise

                self._cache_set(cache_key, result)
                self._log_usage(
                    task_id, call_type, total_prompt_tokens, output_tokens,
                    self._calculate_cost(total_prompt_tokens, output_tokens, model=model),
                    duration_ms, attempt, cached=False, model=model,
                )
                return result

            except LLMValidationError as e:
                last_error = e
            except Exception as e:
                last_error = e
                if attempt < retries:
                    wait = 2 ** attempt
                    time.sleep(wait)
                    continue

        if isinstance(last_error, LLMValidationError):
            raise last_error
        raise LLMRetryExhausted(
            f"Vision LLM call failed after {retries} retries. Last error: {last_error}"
        )

    def _call_api(self, prompt: str) -> tuple[dict, int, int]:
        """Make the actual API call. Returns (parsed_result, prompt_tokens, output_tokens)."""
        if BACKEND == "anthropic":
            return self._call_anthropic(prompt)
        else:
            return self._call_openai_compatible(prompt)

    def _call_anthropic(self, prompt: str) -> tuple[dict, int, int]:
        """Call Anthropic API (supports custom base URL for Kimi etc.)."""
        import anthropic

        kwargs = dict(api_key=ANTHROPIC_KEY)
        if ANTHROPIC_BASE_URL:
            kwargs["base_url"] = ANTHROPIC_BASE_URL

        client = anthropic.Anthropic(**kwargs)
        response = client.messages.create(
            model=self.model,
            max_tokens=4096,
            timeout=120,  # 2-minute timeout
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
        prompt_tokens = getattr(response.usage, "input_tokens", 0) if hasattr(response, "usage") else 0
        output_tokens = getattr(response.usage, "output_tokens", 0) if hasattr(response, "usage") else 0
        return self._parse_response(text), prompt_tokens, output_tokens

    def _call_openai_compatible(self, prompt: str) -> tuple[dict, int, int]:
        """Call OpenAI-compatible API (DeepSeek, Qwen, GLM, Moonshot, etc.)."""
        from openai import OpenAI
        # max_retries=0: our own backoff loop in call() governs retries
        client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL or None,
                        timeout=LLM_TIMEOUT, max_retries=0)
        response = client.chat.completions.create(
            model=self.model,
            max_tokens=4096,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.choices[0].message.content or ""
        prompt_tokens = getattr(response.usage, "prompt_tokens", 0) if response.usage else 0
        output_tokens = getattr(response.usage, "completion_tokens", 0) if response.usage else 0
        return self._parse_response(text), prompt_tokens, output_tokens

    def _call_vision_api(self, image_b64: str, mime_type: str, prompt: str,
                         model: str) -> tuple[dict, int, int]:
        """Dispatch vision call to the configured backend."""
        if BACKEND == "anthropic":
            return self._call_anthropic_vision(image_b64, mime_type, prompt, model)
        else:
            return self._call_openai_vision(image_b64, mime_type, prompt, model)

    def _call_anthropic_vision(self, image_b64: str, mime_type: str, prompt: str,
                               model: str) -> tuple[dict, int, int]:
        """Call Anthropic Messages API with an image (supports Kimi-compatible endpoints)."""
        import anthropic

        kwargs = dict(api_key=ANTHROPIC_KEY)
        if ANTHROPIC_BASE_URL:
            kwargs["base_url"] = ANTHROPIC_BASE_URL

        client = anthropic.Anthropic(**kwargs)
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            timeout=120,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": image_b64,
                    }},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        text = response.content[0].text
        prompt_tokens = getattr(response.usage, "input_tokens", 0) if hasattr(response, "usage") else 0
        output_tokens = getattr(response.usage, "output_tokens", 0) if hasattr(response, "usage") else 0
        return self._parse_response(text), prompt_tokens, output_tokens

    def _call_openai_vision(self, image_b64: str, mime_type: str, prompt: str,
                            model: str) -> tuple[dict, int, int]:
        """Call OpenAI-compatible vision API (DeepSeek, Qwen, GLM, etc.)."""
        from openai import OpenAI

        client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL or None,
                        timeout=LLM_TIMEOUT, max_retries=0)
        response = client.chat.completions.create(
            model=model,
            max_tokens=8192,  # OCR text can be long; 4096 may truncate reasoning models
            temperature=0.3,
            # Disable chain-of-thought for OCR: MiniMax-M3 etc. emit <think> blocks that
            # waste tokens and can be truncated. OCR needs direct text output.
            extra_body={"thinking": {"type": "disabled"}},
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {
                        "url": f"data:{mime_type};base64,{image_b64}",
                    }},
                ],
            }],
        )
        text = response.choices[0].message.content or ""
        prompt_tokens = getattr(response.usage, "prompt_tokens", 0) if response.usage else 0
        output_tokens = getattr(response.usage, "completion_tokens", 0) if response.usage else 0
        return self._parse_response(text), prompt_tokens, output_tokens

    def _parse_response(self, text: str) -> dict:
        """Parse LLM response text into dict (handles JSON + markdown + lenient formats)."""
        import re
        if not isinstance(text, str):
            text = str(text)
        text = text.strip()
        # Strip reasoning/think blocks (reasoning models like MiniMax-M2.5 emit <think>...</think>)
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<reasoning>.*?</reasoning>', '', text, flags=re.DOTALL | re.IGNORECASE)
        # Strip markdown fences
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
            text = text.strip()
        # Try standard JSON first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try json5 (handles unquoted keys, trailing commas, single quotes)
        try:
            import json5
            return json5.loads(text)
        except Exception:
            pass
        # Fix unquoted string values (Kimi quirk: {key: value} where value should be "value")
        # Pattern: colon+space followed by a bare word (not number/true/false/null/quote/brace)
        try:
            fixed = re.sub(
                r'(:\s*)([a-zA-Z_一-鿿][a-zA-Z0-9_一-鿿]*(?:\s+[a-zA-Z_一-鿿][a-zA-Z0-9_一-鿿]*)*)(\s*[,}\]])',
                r'\1"\2"\3', text
            )
            import json5
            return json5.loads(fixed)
        except Exception:
            pass
        # Last resort: find the first balanced {...} JSON block and parse it
        # (handles reasoning models that prefix/suffix prose around the JSON)
        try:
            start = text.find('{')
            while start != -1:
                depth = 0
                for i in range(start, len(text)):
                    ch = text[i]
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            cand = text[start:i + 1]
                            try:
                                return json.loads(cand)
                            except json.JSONDecodeError:
                                break  # try the next '{'
                start = text.find('{', start + 1)
        except Exception:
            pass
        # Wrap raw text
        return {"_raw_text": text}

    def _add_validation_fix_prompt(self, original_prompt: str, failed_result: dict,
                                   schema: dict) -> str:
        """Add validation error context for retry."""
        return (
            f"{original_prompt}\n\n"
            f"YOUR PREVIOUS RESPONSE FAILED VALIDATION. Expected schema:\n"
            f"{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
            f"Your response:\n{json.dumps(failed_result, ensure_ascii=False)}\n\n"
            f"Please fix and return ONLY valid JSON matching the expected schema."
        )

    def _prepare_image(self, image_path: str) -> str:
        """Resize image if it exceeds VISION_MAX_IMAGE_SIZE. Returns original or temp path."""
        try:
            from PIL import Image
        except Exception:
            return image_path

        size = os.path.getsize(image_path)
        if size <= VISION_MAX_IMAGE_SIZE:
            return image_path

        img = Image.open(image_path)
        fmt = img.format or "JPEG"
        # Reduce dimensions iteratively until the in-memory file is under the limit
        while True:
            import io
            buf = io.BytesIO()
            save_kwargs = {"format": fmt}
            if fmt == "JPEG":
                save_kwargs["quality"] = 85
            img.save(buf, **save_kwargs)
            if buf.tell() <= VISION_MAX_IMAGE_SIZE:
                break
            w, h = img.size
            img = img.resize((w // 2, h // 2), Image.LANCZOS)

        import tempfile
        fd, tmp_path = tempfile.mkstemp(suffix=os.path.splitext(image_path)[1] or ".jpg")
        os.close(fd)
        img.save(tmp_path, **save_kwargs)
        return tmp_path

    def _detect_mime_type(self, image_path: str) -> str:
        ext = os.path.splitext(image_path)[1].lower()
        mapping = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
        }
        return mapping.get(ext, "image/jpeg")

    def _estimate_image_tokens(self, image_bytes: bytes) -> int:
        """Best-effort image token estimate. Conservative heuristic: 1 KB ≈ 10 tokens."""
        kb = len(image_bytes) / 1024
        return int(kb * 10)

    def _log_usage(self, task_id: int, call_type: str, prompt_tokens: int,
                   output_tokens: int, estimated_cost: float, duration_ms: int,
                   retry_count: int, cached: bool, model: str = None) -> None:
        """Write usage to llm_usage_log via db.py."""
        try:
            from db import log_llm_usage
            log_llm_usage(
                task_id=task_id, call_type=call_type, model=model or self.model,
                prompt_tokens=prompt_tokens, output_tokens=output_tokens,
                estimated_cost=estimated_cost, duration_ms=duration_ms,
                retry_count=retry_count, cached=int(cached),
                db_path=self.db_path,
            )
        except Exception:
            pass  # never let logging failure break the pipeline

    # ── Cost queries ────────────────────────────────

    def cost_today(self) -> float:
        from db import get_llm_cost_today
        return get_llm_cost_today(self.db_path)

    def cost_this_month(self) -> float:
        from db import get_llm_cost_this_month
        return get_llm_cost_this_month(self.db_path)


# ═══════════════════════════════════════════════════
# Client Factory (per-model cache, thread-safe)
# ═══════════════════════════════════════════════════

_client_cache: dict = {}
_client_lock = threading.Lock()


def get_client(model: str = None) -> LLMClient:
    key = model or DEFAULT_MODEL
    client = _client_cache.get(key)
    if client is not None:
        return client
    with _client_lock:
        client = _client_cache.get(key)
        if client is None:
            client = LLMClient(model=key)
            _client_cache[key] = client
        return client


# ═══════════════════════════════════════════════════
# Test
# ═══════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(__file__))

    print(f"Backend:    {BACKEND}")
    print(f"Model:      {DEFAULT_MODEL}")
    print(f"Has API key: {HAS_API_KEY}")
    print(f"Cache:      {'ON' if CACHE_ENABLED else 'OFF'}")
    print(f"Max retries: {MAX_RETRIES}")
    if LLM_BASE_URL:
        print(f"Base URL:   {LLM_BASE_URL}")

    if not HAS_API_KEY:
        print("\nNo API key configured. Running in DEMO mode.")
        print("To use a real LLM, set one of:")
        print("  Anthropic:  $env:ANTHROPIC_API_KEY = 'sk-ant-...'")
        print("  DeepSeek:   $env:LLM_API_KEY = 'sk-...'; $env:LLM_BASE_URL = 'https://api.deepseek.com'; $env:LLM_MODEL = 'deepseek-chat'")
        print("  Qwen:       $env:LLM_API_KEY = 'sk-...'; $env:LLM_BASE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1'; $env:LLM_MODEL = 'qwen-plus'")
        print("  GLM:        $env:LLM_API_KEY = '...'; $env:LLM_BASE_URL = 'https://open.bigmodel.cn/api/paas/v4'; $env:LLM_MODEL = 'glm-4-flash'")
        print("\nTesting demo mode...")
        client = LLMClient()
        result = client.call(prompt="test", call_type="analyze")
        print(f"Demo mistakes: {len(result.get('mistakes', []))}")
        print("llm.py OK (demo mode)")
    else:
        print("\nllm.py OK (ready for API calls)")
