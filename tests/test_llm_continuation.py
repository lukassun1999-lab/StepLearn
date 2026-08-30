# -*- coding: utf-8 -*-
"""LLM 截断自动续写测试（_continue_anthropic / _continue_openai）。

输出被 max_tokens 截断时用预填充/追加消息请求续写，拼接后一次性解析；
单轮续写失败按已收到的截断文本继续（尽力而为，不拖垮整次调用）。
"""

import types

import llm


# ── Fake 响应构造 ───────────────────────────────────

def _anthropic_resp(text, stop_reason, prompt_tokens=10, output_tokens=5):
    return types.SimpleNamespace(
        stop_reason=stop_reason,
        content=[types.SimpleNamespace(text=text)],
        usage=types.SimpleNamespace(input_tokens=prompt_tokens,
                                    output_tokens=output_tokens),
    )


def _openai_resp(text, finish_reason, prompt_tokens=10, output_tokens=5):
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(
            message=types.SimpleNamespace(content=text),
            finish_reason=finish_reason,
        )],
        usage=types.SimpleNamespace(prompt_tokens=prompt_tokens,
                                    completion_tokens=output_tokens),
    )


# ── Anthropic 路径 ─────────────────────────────────

def test_anthropic_continuation_joins_and_sums_tokens():
    calls = []

    class FakeMessages:
        def create(self, **kw):
            calls.append(kw)
            return _anthropic_resp('LLO"}', "end_turn")

    client = types.SimpleNamespace(messages=FakeMessages())
    first = _anthropic_resp('{"a": "HE', "max_tokens")

    text, pt, ot = llm.LLMClient()._continue_anthropic(
        client, "p", first.content[0].text, first, 10, 5)

    assert text == '{"a": "HELLO"}'
    assert llm.LLMClient()._parse_response(text) == {"a": "HELLO"}
    assert (pt, ot) == (20, 10)  # 续写轮的 token 累加
    assert len(calls) == 1
    # 预填充：原始 user 消息 + assistant 已有文本
    assert calls[0]["messages"][0]["content"] == "p"
    assert calls[0]["messages"][1]["content"] == '{"a": "HE'


def test_anthropic_vision_continuation_keeps_image_blocks():
    calls = []

    class FakeMessages:
        def create(self, **kw):
            calls.append(kw)
            return _anthropic_resp("…续", "end_turn")

    client = types.SimpleNamespace(messages=FakeMessages())
    image_content = [{"type": "image", "source": {"type": "base64",
                                                  "media_type": "image/png",
                                                  "data": "xxx"}},
                     {"type": "text", "text": "OCR"}]
    first = _anthropic_resp("识别到一半的", "max_tokens")
    llm.LLMClient()._continue_anthropic(
        client, image_content, first.content[0].text, first, 10, 5,
        model="vision-model")

    # 续写请求必须原样带上图片内容块，且用视觉模型
    assert calls[0]["messages"][0]["content"] == image_content
    assert calls[0]["model"] == "vision-model"


def test_anthropic_no_continuation_when_complete():
    calls = []

    class FakeMessages:
        def create(self, **kw):
            calls.append(kw)
            raise AssertionError("未截断不应发起续写")

    client = types.SimpleNamespace(messages=FakeMessages())
    first = _anthropic_resp('{"a": 1}', "end_turn")
    text, pt, ot = llm.LLMClient()._continue_anthropic(
        client, "p", first.content[0].text, first, 10, 5)
    assert text == '{"a": 1}' and (pt, ot) == (10, 5) and not calls


def test_anthropic_continuation_error_keeps_partial():
    class FakeMessages:
        def create(self, **kw):
            raise RuntimeError("endpoint down")

    client = types.SimpleNamespace(messages=FakeMessages())
    first = _anthropic_resp('{"a": "HE', "max_tokens")
    text, pt, ot = llm.LLMClient()._continue_anthropic(
        client, "p", first.content[0].text, first, 10, 5)
    assert text == '{"a": "HE'  # 退回原行为：按截断文本继续
    assert (pt, ot) == (10, 5)


def test_anthropic_continuation_respects_cap(monkeypatch):
    monkeypatch.setattr(llm, "MAX_CONTINUATIONS", 2)
    calls = []

    class FakeMessages:
        def create(self, **kw):
            calls.append(kw)
            return _anthropic_resp("x", "max_tokens")  # 永远截断

    client = types.SimpleNamespace(messages=FakeMessages())
    first = _anthropic_resp("y", "max_tokens")
    llm.LLMClient()._continue_anthropic(
        client, "p", first.content[0].text, first, 0, 0)
    assert len(calls) == 2  # 续写最多 MAX_CONTINUATIONS 轮


# ── OpenAI 兼容路径 ────────────────────────────────

def test_openai_continuation_joins_and_appends_messages():
    calls = []

    class FakeCompletions:
        def create(self, **kw):
            calls.append(kw)
            return _openai_resp(' 1}', "stop")

    client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=FakeCompletions()))
    create_kwargs = {"model": "m"}
    messages = [{"role": "user", "content": "p"}]
    first = _openai_resp('{"a":', "length")

    text, pt, ot = llm.LLMClient()._continue_openai(
        client, create_kwargs, messages, first.choices[0].message.content,
        first, 10, 5)

    assert text == '{"a": 1}'
    assert llm.LLMClient()._parse_response(text) == {"a": 1}
    assert (pt, ot) == (20, 10)
    assert len(calls) == 1
    sent = calls[0]["messages"]
    assert sent[0] == {"role": "user", "content": "p"}
    assert sent[1] == {"role": "assistant", "content": '{"a":'}
    assert "截断" in sent[2]["content"]  # 续写指令
    assert calls[0]["model"] == "m"


def test_openai_no_continuation_when_complete():
    class FakeCompletions:
        def create(self, **kw):
            raise AssertionError("未截断不应发起续写")

    client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=FakeCompletions()))
    first = _openai_resp('{"a": 1}', "stop")
    text, pt, ot = llm.LLMClient()._continue_openai(
        client, {"model": "m"}, [{"role": "user", "content": "p"}],
        first.choices[0].message.content, first, 10, 5)
    assert text == '{"a": 1}' and (pt, ot) == (10, 5)


def test_openai_continuation_error_keeps_partial():
    class FakeCompletions:
        def create(self, **kw):
            raise RuntimeError("timeout")

    client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=FakeCompletions()))
    first = _openai_resp('{"a":', "length")
    text, _, _ = llm.LLMClient()._continue_openai(
        client, {"model": "m"}, [{"role": "user", "content": "p"}],
        first.choices[0].message.content, first, 10, 5)
    assert text == '{"a":'
