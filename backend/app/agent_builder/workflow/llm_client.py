"""LLM 客户端工厂模块。

提供：
- LLMClientError 基类 + 各子类异常（Auth/RateLimit/Server/Timeout/BadRequest/ContextTooLong）
- _map_provider_error()：将各 provider 原生异常归一化为 LLMClientError 子类
- call_llm()：使用 LangChain init_chat_model 调用 LLM，带 tenacity 重试
- check_llm_provider_envs()：检查已配置的 LLM provider 列表，供启动校验调用

设计决策（CONTEXT.md 2026-05-16 锁定）：
- 使用 LangChain init_chat_model("provider:model") 字符串格式，直接原生调用
- 异常归一化在本层统一处理，上层节点不需了解各 provider 的原生异常类型
- tenacity 重试仅覆盖可重试异常（RateLimit / Server / Timeout），Auth 等不重试
- 默认重试 3 次，指数退避 1s/2s/4s，可被节点 config.retry_count 覆盖

支持的 provider（v1）：
- openai       — langchain-openai，OPENAI_API_KEY
- anthropic    — langchain-anthropic，ANTHROPIC_API_KEY
- zhipuai      — langchain-community (ChatZhipuAI)，ZHIPUAI_API_KEY
- deepseek     — langchain-deepseek，DEEPSEEK_API_KEY
- ollama       — langchain-ollama，OLLAMA_BASE_URL（默认 http://localhost:11434）
- google_genai — langchain-google-genai，GOOGLE_API_KEY
"""
from __future__ import annotations

import logging
import os
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# 异常类层次
# ─────────────────────────────────────────────────────────────────────────────


class LLMClientError(Exception):
    """LLM 客户端异常基类。所有 provider 异常均归一化为此类的子类。"""


class LLMAuthError(LLMClientError):
    """认证失败（API Key 无效 / 未配置）。不可重试。"""


class LLMRateLimitError(LLMClientError):
    """触发速率限制（429）。可重试。"""


class LLMServerError(LLMClientError):
    """Provider 服务端错误（5xx）。可重试。"""


class LLMTimeoutError(LLMClientError):
    """请求超时。可重试。"""


class LLMBadRequestError(LLMClientError):
    """请求参数错误（400 / 422）。不可重试。"""


class LLMContextTooLongError(LLMClientError):
    """输入 token 超出上下文窗口。不可重试。"""


# ─────────────────────────────────────────────────────────────────────────────
# 异常归一化
# ─────────────────────────────────────────────────────────────────────────────

# 可重试异常类型元组（供 tenacity retry_if_exception_type 使用）
_RETRYABLE_ERRORS = (LLMRateLimitError, LLMServerError, LLMTimeoutError)


def _map_provider_error(exc: Exception) -> LLMClientError:
    """将各 provider 原生异常映射为统一的 LLMClientError 子类。

    按异常类的模块路径 + 名称做字符串匹配，避免硬依赖各 provider 包的导入。
    这样即使某 provider 包未安装，映射逻辑也不会 ImportError。

    Args:
        exc: 原始异常

    Returns:
        对应的 LLMClientError 子类实例
    """
    # 获取异常类型的完整模块路径，用于模式匹配
    exc_type = type(exc)
    module = getattr(exc_type, "__module__", "") or ""
    class_name = exc_type.__name__

    # 认证错误（不重试）
    if class_name in ("AuthenticationError",):
        return LLMAuthError(f"认证失败: {exc}") from exc

    # 速率限制（可重试）
    if class_name in ("RateLimitError",):
        return LLMRateLimitError(f"速率限制: {exc}") from exc

    # 超时（可重试）
    if "timeout" in class_name.lower() or "TimeoutException" in class_name:
        return LLMTimeoutError(f"请求超时: {exc}") from exc
    # httpx 超时
    if "httpx" in module and "timeout" in class_name.lower():
        return LLMTimeoutError(f"请求超时（httpx）: {exc}") from exc

    # 上下文过长（不重试）
    if "ContextLength" in class_name or "context_length" in str(exc).lower():
        return LLMContextTooLongError(f"上下文超出窗口: {exc}") from exc

    # 坏请求（不重试）
    if class_name in ("BadRequestError", "UnprocessableEntityError", "InvalidRequestError"):
        return LLMBadRequestError(f"请求参数错误: {exc}") from exc

    # 服务端错误（5xx 状态码，可重试）
    status_code: int | None = getattr(exc, "status_code", None)
    if status_code is not None and status_code >= 500:
        return LLMServerError(f"服务端错误 ({status_code}): {exc}") from exc

    # APIStatusError 兜底：按状态码分类
    if "APIStatusError" in class_name or "APIError" in class_name:
        if status_code == 401:
            return LLMAuthError(f"认证失败 (401): {exc}") from exc
        if status_code == 429:
            return LLMRateLimitError(f"速率限制 (429): {exc}") from exc
        if status_code is not None and status_code >= 500:
            return LLMServerError(f"服务端错误 ({status_code}): {exc}") from exc
        return LLMBadRequestError(f"API 错误: {exc}") from exc

    # 兜底：包装为 LLMServerError（触发重试比静默失败更安全）
    log.warning(
        "未识别的 LLM 异常类型 %s.%s，将作为 LLMServerError 处理: %s",
        module,
        class_name,
        exc,
    )
    return LLMServerError(f"未知 LLM 错误: {exc}") from exc


# ─────────────────────────────────────────────────────────────────────────────
# 日志：重试时打印告警
# ─────────────────────────────────────────────────────────────────────────────


def _log_retry(retry_state: RetryCallState) -> None:
    """tenacity 重试回调：记录每次重试的警告日志。"""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    log.warning(
        "LLM 调用第 %d 次重试（异常: %s）",
        retry_state.attempt_number,
        exc,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 核心调用接口
# ─────────────────────────────────────────────────────────────────────────────


async def call_llm(
    model_str: str,
    messages: list[dict[str, Any]],
    *,
    retry_count: int = 3,
    **kwargs: Any,
) -> AIMessage:
    """使用 LangChain init_chat_model 异步调用 LLM。

    内置 tenacity 指数退避重试（仅覆盖可重试异常）。
    所有 provider 异常均通过 _map_provider_error 归一化后抛出。

    Args:
        model_str: LangChain model 字符串，格式 "provider:model_name"
            例：
            - "openai:gpt-4o-mini"
            - "anthropic:claude-sonnet-4-5"
            - "zhipuai:glm-4.6"
            - "deepseek:deepseek-chat"
            - "ollama:llama3"
            - "google_genai:gemini-pro"
        messages: OpenAI 格式消息列表，如：
            [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
        retry_count: 最大重试次数（默认 3，含第一次调用则最多执行 retry_count 次）
        **kwargs: 透传给 init_chat_model 的参数，如：
            - temperature: float（默认 0.7）
            - max_tokens: int
            - timeout: int（秒）
            - api_base: str（自定义 base URL）
            - api_key: str（覆盖 env 中的 key）

    Returns:
        AIMessage：LangChain 统一响应格式
            - .content: str — LLM 响应文本
            - .usage_metadata: dict — token 用量
            - .response_metadata: dict — provider 原始元数据

    Raises:
        LLMAuthError: 认证失败（不重试）
        LLMRateLimitError: 速率限制（重试后仍失败）
        LLMServerError: 服务端错误（重试后仍失败）
        LLMTimeoutError: 超时（重试后仍失败）
        LLMBadRequestError: 请求参数错误（不重试）
        LLMContextTooLongError: 上下文过长（不重试）
    """
    # 构造 tenacity 装饰后的调用器（动态 retry_count）
    @retry(
        retry=retry_if_exception_type(_RETRYABLE_ERRORS),
        stop=stop_after_attempt(max(1, retry_count)),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        before_sleep=_log_retry,
        reraise=True,
    )
    async def _invoke_with_retry() -> AIMessage:
        try:
            chat = init_chat_model(model_str, **kwargs)
            result = await chat.ainvoke(messages)
            # init_chat_model 返回 BaseMessage，强制类型为 AIMessage
            if not isinstance(result, AIMessage):
                # 将非 AIMessage 包装成 AIMessage（兼容不同 provider）
                return AIMessage(
                    content=str(result.content),
                    response_metadata=getattr(result, "response_metadata", {}),
                    usage_metadata=getattr(result, "usage_metadata", None),
                )
            return result
        except LLMClientError:
            # 已是归一化异常，直接再抛（避免双重包装）
            raise
        except Exception as exc:
            mapped = _map_provider_error(exc)
            raise mapped from exc

    return await _invoke_with_retry()


# ─────────────────────────────────────────────────────────────────────────────
# 启动校验辅助
# ─────────────────────────────────────────────────────────────────────────────

# 各 provider 对应的 env var 名称
_PROVIDER_ENV_MAP: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "zhipuai": "ZHIPUAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "google_genai": "GOOGLE_API_KEY",
    "ollama": "OLLAMA_BASE_URL",
}


def check_llm_provider_envs() -> list[str]:
    """检查已配置的 LLM provider 列表。

    遍历 _PROVIDER_ENV_MAP，返回已配置（env var 非空）的 provider 名称列表。
    供 startup_checks.run_startup_checks() 调用，无 provider 时发出 WARNING。

    Returns:
        已配置 provider 名称列表，如 ["openai", "zhipuai"]
        若无任何 provider 配置，返回空列表。
    """
    configured: list[str] = [
        provider
        for provider, env_var in _PROVIDER_ENV_MAP.items()
        if os.environ.get(env_var)
    ]
    return configured
