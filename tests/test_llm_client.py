# -*- coding: utf-8 -*-
"""LLM 客户端回归测试（提交 4：推理模型文本路径修复）。

背景：MiniMax-M3 是推理模型，文本路径未关闭思维链时会把全部输出预算
耗在 <think> 思考上（实测 4095/4096 token），JSON 被截断 → 流水线
校验报 "Required field 'mistakes' missing from LLM output"，任务失败。
视觉路径早已修复（extra_body thinking disabled），文本路径此前漏了。
"""

import types


def _fake_openai_factory(raw_text: str, captures: list):
    """构造 fake openai.OpenAI：记录 create() 的 kwargs，返回固定文本。"""
    class FakeCompletions:
        def create(self, **kwargs):
            captures.append(kwargs)
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(
                    message=types.SimpleNamespace(content=raw_text))],
                usage=types.SimpleNamespace(prompt_tokens=10, completion_tokens=20),
            )

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, *args, **kwargs):
            self.chat = FakeChat()

    return FakeOpenAI


def _call_text(monkeypatch, raw_text):
    """用 fake OpenAI 驱动 _call_openai_compatible，返回 (result, kwargs)。"""
    import openai
    import llm as llm_mod
    captures = []
    fake = _fake_openai_factory(raw_text, captures)
    monkeypatch.setattr(openai, "OpenAI", fake)
    c = llm_mod.get_client()
    result, _, _ = c._call_openai_compatible("test prompt")
    return result, captures[0]


def test_text_call_disables_thinking(monkeypatch):
    """文本路径必须关闭思维链（extra_body thinking disabled），与视觉路径一致。"""
    result, kwargs = _call_text(monkeypatch, '{"ok": true}')
    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}, \
        "推理模型会耗尽输出预算在 <think> 上，结构化任务必须关闭思维链"
    assert result == {"ok": True}


def test_text_call_has_large_output_budget(monkeypatch):
    """输出预算足够大：长试卷的错题 JSON + 解释可能远超 4096 token。"""
    _, kwargs = _call_text(monkeypatch, '{"ok": true}')
    assert kwargs["max_tokens"] >= 8192, f"max_tokens={kwargs['max_tokens']} 会被推理/长 JSON 截断"
