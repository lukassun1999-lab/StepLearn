#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OCR 服务（vision LLM 为主、Tesseract 兜底），自 skills_bridge.py 拆出。"""

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from llm import OCR_BACKEND, VISION_MODEL, LLMClient
from bridge_common import OCR_JS, OCR_WRAPPER
from llm_prompts import VISION_OCR_PROMPT

_MIN_OCR_TEXT_LENGTH = 1


def run_ocr_multimodal(image_path: str, task_id: int = None) -> Dict[str, Any]:
    """
    Run OCR using a vision-capable multimodal LLM.
    Returns: {"text": str, "confidence": float, "words": [], "backend": "vision"}
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    client = LLMClient(model=VISION_MODEL)
    result = client.call_vision(
        image_path=image_path,
        prompt=VISION_OCR_PROMPT,
        task_id=task_id,
        call_type="ocr",
    )

    # call_vision returns a parsed dict; raw text may be under _raw_text
    if isinstance(result, dict):
        text = result.get("text", result.get("_raw_text", ""))
    else:
        text = str(result)

    # Confidence heuristic: more [模糊] markers -> lower confidence
    fuzzy_count = text.count("[模糊]")
    total_chars = max(len(text), 1)
    confidence = max(0.5, 1.0 - (fuzzy_count / max(total_chars / 100, 1)))

    return {
        "text": text,
        "confidence": confidence,
        "words": [],
        "backend": "vision",
    }


def _run_tesseract_ocr(image_path: str, lang: str = "chi_sim+eng") -> Dict[str, Any]:
    """
    Original Tesseract.js OCR implementation.
    Returns: {"text": str, "confidence": float, "words": [...]}
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    # Set NODE_PATH + TESSDATA_PREFIX so Tesseract.js finds everything
    node_path = os.path.expanduser(r"~\.workbuddy\binaries\node\workspace\node_modules")
    tessdata_path = os.path.join(node_path, "tesseract.js-core", "tessdata")
    env = os.environ.copy()
    env["NODE_PATH"] = node_path
    env["TESSDATA_PREFIX"] = tessdata_path

    # Use our wrapper (has proper langPath) if tessdata exists; fall back to original
    tessdata_dir = os.path.join(os.path.dirname(__file__), "tessdata")
    ocr_script = OCR_WRAPPER if os.path.isdir(tessdata_dir) else OCR_JS

    result = subprocess.run(
        ["node", ocr_script, image_path, "--lang", lang, "--json"],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
        env=env,
    )
    if result.returncode != 0:
        stderr_msg = (result.stderr or "").strip() or result.stdout.strip() or "unknown error"
        raise RuntimeError(f"OCR failed (exit {result.returncode}): {stderr_msg[:200]}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        # If stdout isn't valid JSON, return raw text with default confidence
        return {"text": result.stdout, "confidence": 0.5, "words": []}

    text = data.get("text", "") if isinstance(data, dict) else result.stdout
    confidence = data.get("confidence", 0.5) if isinstance(data, dict) else 0.5
    words = data.get("words", []) if isinstance(data, dict) else []

    return {"text": text, "confidence": confidence, "words": words}


def run_ocr_parallel(image_paths, task_id=None, max_workers=4, progress=None):
    """OCR multiple images in parallel, preserving input order.

    Returns a list (same length/order as image_paths) of:
      {"text": str, "confidence": float, "ok": bool}

    Each page is OCR'd in its own thread (up to max_workers). DB writes use
    per-call connections (WAL + busy_timeout), so concurrent usage is safe.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    n = len(image_paths)
    if n == 0:
        return []

    def _one(i, path):
        try:
            r = run_ocr(path, task_id=task_id)
            return i, {"text": (r.get("text") or "").strip(),
                       "confidence": r.get("confidence", 0.0), "ok": True}
        except Exception:
            return i, {"text": "", "confidence": 0.0, "ok": False}

    results = [None] * n
    workers = max(1, min(max_workers, n))
    done_count = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_one, i, p): i for i, p in enumerate(image_paths)}
        for fut in as_completed(futs):
            i, res = fut.result()
            results[i] = res
            done_count += 1
            if progress and n:
                progress(f"OCR识别试卷 {done_count}/{n}", 15 + int(done_count / n * 10))
    return results


def run_ocr(image_path: str, lang: str = "chi_sim+eng",
            task_id: int = None) -> Dict[str, Any]:
    """
    Run OCR with automatic backend selection.
    Returns: {"text": str, "confidence": float, "words": [], "backend": str}
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    use_vision = OCR_BACKEND in ("auto", "vision")
    use_tesseract = OCR_BACKEND in ("auto", "tesseract")
    vision_error = None

    if use_vision:
        try:
            result = run_ocr_multimodal(image_path, task_id=task_id)
            if len(result.get("text", "").strip()) >= _MIN_OCR_TEXT_LENGTH:
                return result
            vision_error = "Vision OCR returned insufficient text"
        except Exception as e:
            vision_error = str(e)

    if use_tesseract:
        try:
            result = _run_tesseract_ocr(image_path, lang=lang)
            result["backend"] = "tesseract"
            if vision_error:
                result["vision_fallback_reason"] = vision_error
            return result
        except Exception as e:
            if vision_error:
                raise RuntimeError(
                    f"OCR failed: vision ({vision_error}), tesseract ({e})"
                )
            raise

    if vision_error:
        raise RuntimeError(
            f"Vision OCR failed and tesseract fallback disabled: {vision_error}"
        )

    raise RuntimeError("OCR backend configuration error")

