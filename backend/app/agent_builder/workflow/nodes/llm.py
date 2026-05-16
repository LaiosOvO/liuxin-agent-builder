"""LLM 节点执行器模块。

提供：
- LLMNodeExecutor：使用 LangChain init_chat_model 实现多 provider LLM 调用

支持的 prompt 模式：
1. 三段 prompt 模式 (system_prompt / user_prompt / assistant_examples)
2. raw_prompt 模式（直接传 messages JSON 数组）

两种模式互斥：存在 raw_prompt 时，三段 prompt 字段被忽略。

所有 prompt 字段均支持 Jinja2 变量插值（通过 BaseNodeExecutor._render_config）。

节点输出 5 字段（与 LangChain AIMessage 对齐）：
- content: str               — LLM 响应文本
- role: str                  — 固定为 "assistant"
- usage_metadata: dict | None — token 用量（prompt_tokens/completion_tokens/total_tokens）
- model: str                 — 实际使用的模型名（来自 response_metadata 或回退到 config["model"]）
- response_metadata: dict    — provider 原始元数据

设计参考（docs/reading-dify-02-05-llm-node-2026-05-16.md）：
- 三段 prompt + raw 互斥模式：沿用 Dify LLM 节点设计
- 适配层隔离：LLMNodeExecutor 依赖 call_llm 接口，不直接调 init_chat_model
- assistant_examples 插入顺序：system → examples(user/assistant交替) → user
- model 字段兜底：response_metadata.get("model_name", config["model"])
- api_base 覆盖：Ollama / 私有网关场景通过 config.api_base 覆盖

绝对约束（CONTEXT.md 锁定）：
- 仅使用 LangChain init_chat_model，不使用 lite/llm 包
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.agent_builder.workflow.llm_client import (
    LLMRateLimitError,
    LLMServerError,
    LLMTimeoutError,
    call_llm,
)
from app.agent_builder.workflow.nodes.base import BaseNodeExecutor

log = logging.getLogger(__name__)


class LLMNodeExecutor(BaseNodeExecutor):
    """LLM 节点执行器。

    基于 LangChain init_chat_model 实现跨 provider LLM 调用。

    节点配置字段（config 中）：
        model (str, 必须): LangChain model 字符串，如 "openai:gpt-4o-mini"
        system_prompt (str, 可选): 系统提示，支持 Jinja2 插值
        user_prompt (str, 三段模式必须): 用户提示，支持 Jinja2 插值
        assistant_examples (list[dict], 可选): few-shot 示例，每项含 "user"/"assistant" 字段
        raw_prompt (str, 可选): 直接传 messages JSON 数组（与三段模式互斥）
        temperature (float, 可选): 采样温度，默认 0.7
        max_tokens (int, 可选): 最大输出 token 数
        api_base (str, 可选): 覆盖 provider 默认 base URL（Ollama / 私有网关）
        api_key (str, 可选): 覆盖环境变量中的 API Key
        timeout_sec (int, 可选): 请求超时秒数，默认 30
        retry_count (int, 可选): 最大重试次数，默认 3
    """

    def _default_retry_count(self) -> int:
        """默认重试 3 次（LLM 调用比普通节点更需要重试）。"""
        return 3

    def _default_timeout(self) -> int:
        """默认 30 秒超时。"""
        return 30

    def _retryable_exceptions(self) -> tuple[type[Exception], ...]:
        """可触发基类重试的异常。

        注意：llm_client.call_llm 内部已有 tenacity 重试；
        此处定义的是节点层的外层重试，供 BaseNodeExecutor 使用。
        通常 LLM 节点不需要双层重试，但保留接口兼容性。
        """
        return (LLMRateLimitError, LLMServerError, LLMTimeoutError)

    async def execute(self, config: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        """执行 LLM 调用，返回 5 字段结构化输出。

        Args:
            config: 经 Jinja2 渲染后的节点配置（BaseNodeExecutor._render_config 产出）
            state: 当前 LangGraph state dict

        Returns:
            含 5 字段的 dict：
            - content: LLM 响应文本
            - role: "assistant"
            - usage_metadata: token 用量（可能为 None）
            - model: 实际模型名
            - response_metadata: provider 原始元数据

        Raises:
            NodeExecutionError: 通过 BaseNodeExecutor.__call__ 包装后抛出
            LLMAuthError: 认证失败（不重试）
            LLMBadRequestError: 参数错误（不重试）
        """
        messages = self._render_messages(config, state)

        # 构造 call_llm 的 kwargs（过滤 None 值，避免各 provider 拒绝 None 参数）
        call_kwargs: dict[str, Any] = {
            "temperature": config.get("temperature", 0.7),
            "retry_count": config.get("retry_count", self._default_retry_count()),
        }

        # 可选参数：仅在 config 中明确设置时传入
        if config.get("max_tokens") is not None:
            call_kwargs["max_tokens"] = config["max_tokens"]
        if config.get("api_base"):
            call_kwargs["api_base"] = config["api_base"]
        if config.get("api_key"):
            call_kwargs["api_key"] = config["api_key"]
        if config.get("timeout_sec") is not None:
            call_kwargs["timeout"] = config["timeout_sec"]

        model_str: str = config["model"]
        log.info("LLM 节点 [%s] 调用 model=%s, messages=%d 条", self.node_id, model_str, len(messages))

        ai_msg = await call_llm(
            model_str=model_str,
            messages=messages,
            **call_kwargs,
        )

        # 提取 model 名：优先从 response_metadata 取，兜底用 config["model"]
        response_meta: dict = getattr(ai_msg, "response_metadata", {}) or {}
        model_name: str = response_meta.get("model_name", model_str) or model_str

        return {
            "content": ai_msg.content,
            "role": "assistant",
            "usage_metadata": getattr(ai_msg, "usage_metadata", None),
            "model": model_name,
            "response_metadata": response_meta,
        }

    def _render_messages(
        self,
        config: dict[str, Any],
        state: dict[str, Any],
    ) -> list[dict[str, str]]:
        """将 config 中的 prompt 配置渲染为 messages 列表。

        模式 A — raw_prompt（优先）：
            config["raw_prompt"] 已被 BaseNodeExecutor._render_config 渲染过 Jinja2 变量；
            此处再做 JSON 解析，得到 messages 列表。

        模式 B — 三段 prompt：
            1. system_prompt（可选） → {"role": "system", "content": ...}
            2. assistant_examples（可选）→ user/assistant 交替插入
            3. user_prompt（必须）→ {"role": "user", "content": ...}

        注意：_render_config 已将 config 中所有 str 字段递归用 Jinja2 渲染，
        此处无需再次渲染，直接使用 config 中的已渲染值。

        Args:
            config: 已经过 Jinja2 渲染的节点配置
            state: 当前 state（此处不直接使用，渲染由基类完成）

        Returns:
            OpenAI-compatible messages 列表
        """
        # raw_prompt 模式（优先于三段 prompt）
        if "raw_prompt" in config and config["raw_prompt"]:
            raw_str: str = config["raw_prompt"]
            try:
                parsed = json.loads(raw_str)
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"[{self.node_id}] raw_prompt 不是合法 JSON: {e}"
                ) from e
            if not isinstance(parsed, list):
                raise ValueError(
                    f"[{self.node_id}] raw_prompt 必须是 JSON 数组（messages 列表）"
                )
            return parsed

        # 三段 prompt 模式
        messages: list[dict[str, str]] = []

        # 1. system_prompt（可选）
        if system_p := config.get("system_prompt"):
            messages.append({"role": "system", "content": system_p})

        # 2. assistant_examples（可选）：user/assistant 交替
        for example in config.get("assistant_examples") or []:
            messages.append({"role": "user", "content": example["user"]})
            messages.append({"role": "assistant", "content": example["assistant"]})

        # 3. user_prompt（必须）
        user_p = config.get("user_prompt")
        if not user_p:
            raise ValueError(
                f"[{self.node_id}] LLM 节点三段 prompt 模式需要 user_prompt，"
                "或者使用 raw_prompt 模式"
            )
        messages.append({"role": "user", "content": user_p})

        return messages
