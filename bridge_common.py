#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""skill 桥接共享件：路径常量、sys.path 副作用、惰性 LLM client。

从 skills_bridge.py 拆出（2026-08 第 3 周提交 4）；skills_bridge 门面
继续对外提供全部符号，调用方零改动。
"""

import os
import sys

SKILLS_DIR = os.path.expanduser(r"~\.workbuddy\skills")
OCR_JS = os.path.join(SKILLS_DIR, "ocr-local", "scripts", "ocr.js")
# Our local wrapper with tessdata path configured
OCR_WRAPPER = os.path.join(os.path.dirname(__file__), "ocr_wrapper.js")
MISTAKE_ANALYZER_SCRIPTS = os.path.join(SKILLS_DIR, "english-mistake-analyzer", "scripts")
MISTAKE_ANALYZER_REFS = os.path.join(SKILLS_DIR, "english-mistake-analyzer", "references")
LEARNING_PLAN_REFS = os.path.join(SKILLS_DIR, "english-learning-plan", "references")

# Ensure skill scripts are importable
if MISTAKE_ANALYZER_SCRIPTS not in sys.path:
    sys.path.insert(0, MISTAKE_ANALYZER_SCRIPTS)


def _get_client():
    from llm import get_client
    return get_client()
