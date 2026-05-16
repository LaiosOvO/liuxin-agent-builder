"""llm_client.py 单元测试。

覆盖：
1. call_llm 路由到不同 provider（mock init_chat_model）
2. 异常归一化（RateLimit / Auth）
3. tenacity 重试行为
4. check_llm_provider_envs 环境变量检测

所有测试 mock init_chat_model，不发真实 API 请求。
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from langchain_core.messages import AIMessage

from app.agent_builder.workflow.llm_client import (
    LLMAuthError,
    LLMBadRequestError,
    LLMRateLimitError,
    LLMServerError,
    LLMTimeoutError,
    _map_provider_error,
    call_llm,
    check_llm_provider_envs,
)

# ─────────────────────────────────────────────────────────────────────────────
# 工具函数：构造 fake AIMessage
# ─────────────────────────────────────────────────────────────────────────────


def _make_ai_message(content: str = "hello", model: str = "gpt-4o-mini") -> AIMessage:
    return AIMessage(
        content=content,
        response_metadata={"model_name": model},
        usage_metadata={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
    )


def _make_fake_chat(response: AIMessage) -> MagicMock:
    """构造 fake chat model（ainvoke 返回 response）。"""
    chat = MagicMock()
    chat.ainvoke = AsyncMock(return_value=response)
    return chat


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: call_llm 路由到 zhipuai
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_call_llm_routes_zhipuai():
    """call_llm('zhipuai:glm-4.6', ...) 应正确透传参数给 init_chat_model。"""
    fake_response = _make_ai_message("GLM 响应", "glm-4.6")
    fake_chat = _make_fake_chat(fake_response)

    with patch(
        "app.agent_builder.workflow.llm_client.init_chat_model",
        return_value=fake_chat,
    ) as mock_init:
        result = await call_llm(
            model_str="zhipuai:glm-4.6",
            messages=[{"role": "user", "content": "你好"}],
            temperature=0.5,
        )

    # init_chat_model 应被调用一次，model_str 和 temperature 正确透传
    mock_init.assert_called_once_with("zhipuai:glm-4.6", temperature=0.5)
    # ainvoke 应被调用，传入 messages
    fake_chat.ainvoke.assert_called_once_with([{"role": "user", "content": "你好"}])
    # 返回值应是 AIMessage
    assert isinstance(result, AIMessage)
    assert result.content == "GLM 响应"


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: call_llm 路由到 openai
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_call_llm_routes_openai():
    """call_llm('openai:gpt-4o', ...) 应正确路由。"""
    fake_response = _make_ai_message("OpenAI 响应", "gpt-4o")
    fake_chat = _make_fake_chat(fake_response)

    with patch(
        "app.agent_builder.workflow.llm_client.init_chat_model",
        return_value=fake_chat,
    ) as mock_init:
        result = await call_llm(
            model_str="openai:gpt-4o",
            messages=[{"role": "user", "content": "Hello"}],
            temperature=0.7,
            max_tokens=1024,
        )

    mock_init.assert_called_once_with("openai:gpt-4o", temperature=0.7, max_tokens=1024)
    assert result.content == "OpenAI 响应"


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: 速率限制异常映射
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_call_llm_maps_rate_limit_error():
    """mock ainvoke 抛出 RateLimitError 类名异常 → 归一化为 LLMRateLimitError。"""

    class FakeRateLimitError(Exception):
        """模拟 openai.RateLimitError。"""

        pass

    FakeRateLimitError.__name__ = "RateLimitError"

    fake_chat = MagicMock()
    fake_chat.ainvoke = AsyncMock(side_effect=FakeRateLimitError("rate limited"))

    # 禁用重试（retry_count=1 实际上发 1 次），只验证异常映射
    with patch(
        "app.agent_builder.workflow.llm_client.init_chat_model",
        return_value=fake_chat,
    ):
        with pytest.raises(LLMRateLimitError):
            await call_llm(
                model_str="openai:gpt-4o-mini",
                messages=[{"role": "user", "content": "test"}],
                retry_count=1,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: tenacity 重试成功
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_call_llm_retries_on_rate_limit():
    """第 1 次 RateLimitError，第 2 次成功 → 最终返回正常结果。"""

    class FakeRateLimitError(Exception):
        pass

    FakeRateLimitError.__name__ = "RateLimitError"

    fake_response = _make_ai_message("重试成功")
    call_count = 0

    async def side_effect(messages):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise FakeRateLimitError("rate limited")
        return fake_response

    fake_chat = MagicMock()
    fake_chat.ainvoke = AsyncMock(side_effect=side_effect)

    with patch(
        "app.agent_builder.workflow.llm_client.init_chat_model",
        return_value=fake_chat,
    ):
        # 使用非常短的等待（通过 wait_exponential min=0）来加速测试
        with patch("app.agent_builder.workflow.llm_client.wait_exponential") as mock_wait:
            mock_wait.return_value = MagicMock(return_value=0)  # 等待 0 秒
            result = await call_llm(
                model_str="openai:gpt-4o-mini",
                messages=[{"role": "user", "content": "test"}],
                retry_count=3,
            )

    assert call_count == 2  # 第 1 次失败，第 2 次成功
    assert result.content == "重试成功"


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: Auth 错误不重试
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_call_llm_no_retry_on_auth_error():
    """AuthenticationError 应立即抛出 LLMAuthError，不进行重试。"""

    class FakeAuthError(Exception):
        pass

    FakeAuthError.__name__ = "AuthenticationError"

    call_count = 0

    async def side_effect(messages):
        nonlocal call_count
        call_count += 1
        raise FakeAuthError("invalid api key")

    fake_chat = MagicMock()
    fake_chat.ainvoke = AsyncMock(side_effect=side_effect)

    with patch(
        "app.agent_builder.workflow.llm_client.init_chat_model",
        return_value=fake_chat,
    ):
        with pytest.raises(LLMAuthError):
            await call_llm(
                model_str="openai:gpt-4o",
                messages=[{"role": "user", "content": "test"}],
                retry_count=3,  # 即使设置 3 次，Auth 错误不重试
            )

    # Auth 错误不可重试，应只调用 1 次
    assert call_count == 1


# ─────────────────────────────────────────────────────────────────────────────
# Test 6+: _map_provider_error 直接测试
# ─────────────────────────────────────────────────────────────────────────────


def test_map_provider_error_auth():
    """AuthenticationError → LLMAuthError。"""

    class FakeAuthError(Exception):
        pass

    FakeAuthError.__name__ = "AuthenticationError"
    result = _map_provider_error(FakeAuthError("bad key"))
    assert isinstance(result, LLMAuthError)


def test_map_provider_error_rate_limit():
    """RateLimitError → LLMRateLimitError。"""

    class FakeRateLimit(Exception):
        pass

    FakeRateLimit.__name__ = "RateLimitError"
    result = _map_provider_error(FakeRateLimit("429"))
    assert isinstance(result, LLMRateLimitError)


def test_map_provider_error_timeout():
    """TimeoutException → LLMTimeoutError。"""

    class FakeTimeout(Exception):
        pass

    FakeTimeout.__name__ = "TimeoutException"
    result = _map_provider_error(FakeTimeout("timed out"))
    assert isinstance(result, LLMTimeoutError)


def test_map_provider_error_server_500():
    """APIStatusError with status_code=500 → LLMServerError。"""

    class FakeAPIStatusError(Exception):
        pass

    FakeAPIStatusError.__name__ = "APIStatusError"
    exc = FakeAPIStatusError("internal server error")
    exc.status_code = 500
    result = _map_provider_error(exc)
    assert isinstance(result, LLMServerError)


def test_map_provider_error_bad_request():
    """BadRequestError → LLMBadRequestError。"""

    class FakeBadRequest(Exception):
        pass

    FakeBadRequest.__name__ = "BadRequestError"
    result = _map_provider_error(FakeBadRequest("invalid param"))
    assert isinstance(result, LLMBadRequestError)


# ─────────────────────────────────────────────────────────────────────────────
# Test: check_llm_provider_envs
# ─────────────────────────────────────────────────────────────────────────────


def test_check_llm_provider_envs_returns_configured(monkeypatch):
    """设置 OPENAI_API_KEY 和 ZHIPUAI_API_KEY → 返回 ['openai', 'zhipuai']。"""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai")
    monkeypatch.setenv("ZHIPUAI_API_KEY", "sk-test-zhipuai")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)

    result = check_llm_provider_envs()
    assert "openai" in result
    assert "zhipuai" in result
    assert "anthropic" not in result


def test_check_llm_provider_envs_empty(monkeypatch):
    """不设置任何 provider env → 返回空列表。"""
    for key in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ZHIPUAI_API_KEY",
                "DEEPSEEK_API_KEY", "GOOGLE_API_KEY", "OLLAMA_BASE_URL"]:
        monkeypatch.delenv(key, raising=False)

    result = check_llm_provider_envs()
    assert result == []
