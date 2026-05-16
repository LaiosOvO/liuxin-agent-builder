"""LLMNodeExecutor 单元测试。

覆盖：
1. 三段 prompt 模式（system + user → messages 组装）
2. assistant_examples 注入
3. raw_prompt 模式
4. Jinja2 变量插值
5. 节点输出 5 字段
6. 超时异常传播
7. api_base 覆盖参数透传
8. temperature / max_tokens 透传
9. Jinja2 sandbox 阻止不安全模板
10. 默认 retry_count

所有测试 mock call_llm + init_chat_model，不发真实 API 请求。
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from app.agent_builder.workflow.llm_client import LLMTimeoutError
from app.agent_builder.workflow.nodes.base import NodeExecutionError
from app.agent_builder.workflow.nodes.llm import LLMNodeExecutor

# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────


def _make_node_def(config: dict) -> dict:
    """构造最小化节点定义 dict。"""
    return {
        "id": "llm_node_1",
        "type": "llm",
        "config": config,
    }


def _make_ai_message(
    content: str = "AI 响应",
    model: str = "openai:gpt-4o-mini",
    input_tokens: int = 10,
    output_tokens: int = 20,
) -> AIMessage:
    return AIMessage(
        content=content,
        response_metadata={"model_name": model},
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: 三段 prompt — system + user → messages 数量 2
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_node_three_phase_prompt():
    """三段 prompt 模式：system_prompt + user_prompt → messages 含 2 条（无 examples）。"""
    node_def = _make_node_def({
        "model": "openai:gpt-4o-mini",
        "system_prompt": "你是助手",
        "user_prompt": "你好",
    })
    executor = LLMNodeExecutor(node_def)

    captured_messages = []

    async def fake_call_llm(model_str, messages, **kwargs):
        captured_messages.extend(messages)
        return _make_ai_message()

    with patch("app.agent_builder.workflow.nodes.llm.call_llm", side_effect=fake_call_llm):
        result = await executor(state={})

    assert len(captured_messages) == 2
    assert captured_messages[0] == {"role": "system", "content": "你是助手"}
    assert captured_messages[1] == {"role": "user", "content": "你好"}


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: assistant_examples 注入
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_node_with_examples():
    """assistant_examples 注入：1 system + 2N example + 1 user。"""
    examples = [
        {"user": "例1用户", "assistant": "例1助手"},
        {"user": "例2用户", "assistant": "例2助手"},
    ]
    node_def = _make_node_def({
        "model": "zhipuai:glm-4.6",
        "system_prompt": "系统提示",
        "user_prompt": "正式问题",
        "assistant_examples": examples,
    })
    executor = LLMNodeExecutor(node_def)

    captured_messages = []

    async def fake_call_llm(model_str, messages, **kwargs):
        captured_messages.extend(messages)
        return _make_ai_message()

    with patch("app.agent_builder.workflow.nodes.llm.call_llm", side_effect=fake_call_llm):
        result = await executor(state={})

    # 期望：1 system + 4 examples (2*2) + 1 user = 6 条
    assert len(captured_messages) == 6
    assert captured_messages[0]["role"] == "system"
    assert captured_messages[1] == {"role": "user", "content": "例1用户"}
    assert captured_messages[2] == {"role": "assistant", "content": "例1助手"}
    assert captured_messages[3] == {"role": "user", "content": "例2用户"}
    assert captured_messages[4] == {"role": "assistant", "content": "例2助手"}
    assert captured_messages[5]["role"] == "user"


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: raw_prompt 模式
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_node_raw_prompt():
    """raw_prompt JSON → messages 直接使用。"""
    raw_messages = [
        {"role": "system", "content": "原始系统提示"},
        {"role": "user", "content": "原始用户提示"},
        {"role": "assistant", "content": "历史回复"},
        {"role": "user", "content": "跟进问题"},
    ]
    node_def = _make_node_def({
        "model": "anthropic:claude-sonnet-4-5",
        "raw_prompt": json.dumps(raw_messages),
    })
    executor = LLMNodeExecutor(node_def)

    captured_messages = []

    async def fake_call_llm(model_str, messages, **kwargs):
        captured_messages.extend(messages)
        return _make_ai_message()

    with patch("app.agent_builder.workflow.nodes.llm.call_llm", side_effect=fake_call_llm):
        await executor(state={})

    # raw_prompt 应直接作为 messages 传入，不做任何转换
    assert captured_messages == raw_messages


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: Jinja2 变量插值
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_node_jinja_interpolation():
    """{{ start.user_input }} 应从 state 中替换为实际值。"""
    node_def = _make_node_def({
        "model": "openai:gpt-4o-mini",
        "system_prompt": "你叫 {{ start.name }}",
        "user_prompt": "用户说：{{ start.user_input }}",
    })
    executor = LLMNodeExecutor(node_def)

    state = {
        "start": {
            "name": "Alice",
            "user_input": "你好世界",
        }
    }

    captured_messages = []

    async def fake_call_llm(model_str, messages, **kwargs):
        captured_messages.extend(messages)
        return _make_ai_message()

    with patch("app.agent_builder.workflow.nodes.llm.call_llm", side_effect=fake_call_llm):
        await executor(state=state)

    assert captured_messages[0]["content"] == "你叫 Alice"
    assert captured_messages[1]["content"] == "用户说：你好世界"


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: 节点输出 5 字段齐全
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_node_returns_output_fields():
    """节点输出应包含 content/role/usage_metadata/model/response_metadata 5 字段。"""
    node_def = _make_node_def({
        "model": "openai:gpt-4o-mini",
        "user_prompt": "测试",
    })
    executor = LLMNodeExecutor(node_def)

    fake_ai_msg = _make_ai_message("这是响应", "gpt-4o-mini", 5, 10)

    async def fake_call_llm(model_str, messages, **kwargs):
        return fake_ai_msg

    with patch("app.agent_builder.workflow.nodes.llm.call_llm", side_effect=fake_call_llm):
        state_update = await executor(state={})

    # executor.__call__ 返回 {node_id: result}
    result = state_update["llm_node_1"]
    assert "content" in result
    assert "role" in result
    assert "usage_metadata" in result
    assert "model" in result
    assert "response_metadata" in result

    assert result["content"] == "这是响应"
    assert result["role"] == "assistant"
    assert result["model"] == "gpt-4o-mini"
    assert result["usage_metadata"]["total_tokens"] == 15


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: 超时异常传播
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_node_timeout_propagates():
    """LLMTimeoutError 应通过 BaseNodeExecutor 包装为 NodeExecutionError 抛出。"""
    node_def = _make_node_def({
        "model": "openai:gpt-4o-mini",
        "user_prompt": "测试",
        "timeout_sec": 1,
        "retry_count": 1,  # 仅 1 次，快速失败
    })
    executor = LLMNodeExecutor(node_def)

    async def fake_call_llm(model_str, messages, **kwargs):
        raise LLMTimeoutError("请求超时")

    with patch("app.agent_builder.workflow.nodes.llm.call_llm", side_effect=fake_call_llm):
        with pytest.raises(NodeExecutionError) as exc_info:
            await executor(state={})

    assert exc_info.value.node_id == "llm_node_1"


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: api_base 覆盖透传
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_node_api_base_override():
    """config.api_base 应透传给 call_llm 的 api_base 参数。"""
    node_def = _make_node_def({
        "model": "openai:gpt-4o-mini",
        "user_prompt": "测试",
        "api_base": "http://ollama.local:11434/v1",
        "api_key": "ollama-dummy",
    })
    executor = LLMNodeExecutor(node_def)

    captured_kwargs: dict = {}

    async def fake_call_llm(model_str, messages, **kwargs):
        captured_kwargs.update(kwargs)
        return _make_ai_message()

    with patch("app.agent_builder.workflow.nodes.llm.call_llm", side_effect=fake_call_llm):
        await executor(state={})

    assert captured_kwargs.get("api_base") == "http://ollama.local:11434/v1"
    assert captured_kwargs.get("api_key") == "ollama-dummy"


# ─────────────────────────────────────────────────────────────────────────────
# Test 8: temperature / max_tokens 透传
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_node_temperature_max_tokens():
    """temperature 和 max_tokens 应正确透传给 call_llm。"""
    node_def = _make_node_def({
        "model": "zhipuai:glm-4.6",
        "user_prompt": "测试",
        "temperature": 0.3,
        "max_tokens": 512,
    })
    executor = LLMNodeExecutor(node_def)

    captured_kwargs: dict = {}

    async def fake_call_llm(model_str, messages, **kwargs):
        captured_kwargs.update(kwargs)
        return _make_ai_message()

    with patch("app.agent_builder.workflow.nodes.llm.call_llm", side_effect=fake_call_llm):
        await executor(state={})

    assert captured_kwargs.get("temperature") == 0.3
    assert captured_kwargs.get("max_tokens") == 512


# ─────────────────────────────────────────────────────────────────────────────
# Test 9: Jinja2 sandbox 阻止不安全模板
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_node_jinja_sandbox_blocks_unsafe():
    """{{ ''.__class__.__mro__ }} 应被 sandbox 拒绝。"""
    node_def = _make_node_def({
        "model": "openai:gpt-4o-mini",
        "user_prompt": "{{ ''.__class__.__mro__ }}",  # 尝试访问私有属性
    })
    executor = LLMNodeExecutor(node_def)

    # SandboxedEnvironment 阻止访问双下划线属性，抛出 SecurityError 或 UndefinedError
    with patch("app.agent_builder.workflow.nodes.llm.call_llm"):
        with pytest.raises((NodeExecutionError, Exception)):
            await executor(state={})


# ─────────────────────────────────────────────────────────────────────────────
# Test 10: 默认 retry_count 为 3
# ─────────────────────────────────────────────────────────────────────────────


def test_llm_node_default_retry_count():
    """LLMNodeExecutor 默认 retry_count 应为 3。"""
    node_def = _make_node_def({
        "model": "openai:gpt-4o-mini",
        "user_prompt": "test",
    })
    executor = LLMNodeExecutor(node_def)
    assert executor._default_retry_count() == 3


# ─────────────────────────────────────────────────────────────────────────────
# Test 11: 无 user_prompt 时三段模式抛 ValueError
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_node_missing_user_prompt_raises():
    """三段 prompt 模式缺少 user_prompt 应抛出包含 ValueError 的 NodeExecutionError。"""
    node_def = _make_node_def({
        "model": "openai:gpt-4o-mini",
        "system_prompt": "系统提示",
        # 故意缺少 user_prompt
    })
    executor = LLMNodeExecutor(node_def)

    with patch("app.agent_builder.workflow.nodes.llm.call_llm"):
        with pytest.raises(NodeExecutionError):
            await executor(state={})


# ─────────────────────────────────────────────────────────────────────────────
# Test 12: raw_prompt 模式优先于三段 prompt
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_node_raw_prompt_takes_precedence():
    """同时设置 raw_prompt 和三段 prompt 时，raw_prompt 优先。"""
    raw_messages = [{"role": "user", "content": "raw message"}]
    node_def = _make_node_def({
        "model": "openai:gpt-4o-mini",
        "system_prompt": "三段系统提示（应被忽略）",
        "user_prompt": "三段用户提示（应被忽略）",
        "raw_prompt": json.dumps(raw_messages),
    })
    executor = LLMNodeExecutor(node_def)

    captured_messages = []

    async def fake_call_llm(model_str, messages, **kwargs):
        captured_messages.extend(messages)
        return _make_ai_message()

    with patch("app.agent_builder.workflow.nodes.llm.call_llm", side_effect=fake_call_llm):
        await executor(state={})

    # 只有 raw_prompt 中的 1 条 message
    assert len(captured_messages) == 1
    assert captured_messages[0]["content"] == "raw message"


# ─────────────────────────────────────────────────────────────────────────────
# Test 13: model 字段兜底（provider 不返回 model_name 时）
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_node_model_fallback():
    """response_metadata 不含 model_name 时，model 字段回退到 config['model']。"""
    node_def = _make_node_def({
        "model": "deepseek:deepseek-chat",
        "user_prompt": "测试",
    })
    executor = LLMNodeExecutor(node_def)

    # 返回不含 model_name 的 AIMessage
    fake_msg = AIMessage(
        content="response",
        response_metadata={},  # 没有 model_name
        usage_metadata=None,
    )

    async def fake_call_llm(model_str, messages, **kwargs):
        return fake_msg

    with patch("app.agent_builder.workflow.nodes.llm.call_llm", side_effect=fake_call_llm):
        state_update = await executor(state={})

    result = state_update["llm_node_1"]
    assert result["model"] == "deepseek:deepseek-chat"  # 回退到 config["model"]


# ─────────────────────────────────────────────────────────────────────────────
# Test 14: LLMNodeExecutor 注册在 NODE_EXECUTORS 中
# ─────────────────────────────────────────────────────────────────────────────


def test_llm_node_registered_in_node_executors():
    """LLMNodeExecutor 应已注册到 NODE_EXECUTORS['llm']。"""
    from app.agent_builder.workflow.nodes import NODE_EXECUTORS

    assert "llm" in NODE_EXECUTORS
    assert NODE_EXECUTORS["llm"] is LLMNodeExecutor


# ─────────────────────────────────────────────────────────────────────────────
# Test 15: raw_prompt 非法 JSON 抛 NodeExecutionError
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_node_raw_prompt_invalid_json():
    """raw_prompt 包含非法 JSON → 应抛出 NodeExecutionError。"""
    node_def = _make_node_def({
        "model": "openai:gpt-4o-mini",
        "raw_prompt": "not valid json {{",
    })
    executor = LLMNodeExecutor(node_def)

    with patch("app.agent_builder.workflow.nodes.llm.call_llm"):
        with pytest.raises((NodeExecutionError, Exception)):
            await executor(state={})


# ─────────────────────────────────────────────────────────────────────────────
# Test 16: 无 system_prompt 时 messages 只含 user
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_node_no_system_prompt():
    """无 system_prompt 时，messages 应只包含 user message（1 条）。"""
    node_def = _make_node_def({
        "model": "ollama:llama3",
        "user_prompt": "你好",
        # 没有 system_prompt
    })
    executor = LLMNodeExecutor(node_def)

    captured_messages = []

    async def fake_call_llm(model_str, messages, **kwargs):
        captured_messages.extend(messages)
        return _make_ai_message()

    with patch("app.agent_builder.workflow.nodes.llm.call_llm", side_effect=fake_call_llm):
        await executor(state={})

    assert len(captured_messages) == 1
    assert captured_messages[0]["role"] == "user"
    assert captured_messages[0]["content"] == "你好"
