"""ToolCapability — plugin 提供 RPC tools 给 LLM 节点调用（v1.1 骨架）。

设计要点（ADR-001 §3.5 + Dify reading doc 借鉴点 #2/#4）：

- **Phase 5.A 仅定 Protocol 骨架** — 真实接入留 Phase 5.D+
- **list_tools + invoke_tool 双 API 分离** — Declaration vs Invocation（借鉴 Dify
  PluginToolProviderEntity 三段式：provider + declaration + invocation manager）
- **input_schema / output_schema 用 dict[str, Any]** — 不强类型化（借鉴 Dify
  ToolEntity.output_schema: Mapping[str, object]），让 plugin 自由选 OpenAPI / JSON
  Schema / 自定义格式
- **ToolInvocationResult success/error envelope** — 借鉴 Dify PluginDaemonBasicResponse
  错误码模式（code != 0 = error），但简化为 success: bool + error_message: str | None

为什么 v1.1 仅骨架：用户 CONTEXT.md §Deferred Ideas 明确：
- TriggerCapability / ToolCapability / WorkflowCapability 完整接口（v1.1 仅留 Protocol
  骨架，真实接入留 Phase 5.D+）

Reference (Dify reading doc `docs/reading-dify-05a-03-hr-identity-trigger-tool-2026-05-17.md`)：
- 借鉴 Dify PluginToolProviderEntity (api/core/plugin/entities/plugin_daemon.py:43-46) 的
  declaration + plugin_id 分离 — 但简化无 plugin_unique_identifier 字段
- 借鉴 Dify ToolEntity.parameters (api/core/tools/entities/tool_entities.py:411-419) 的
  dict 直传 — input_schema: dict 不强类型化
- 借鉴 Dify PluginDaemonBasicResponse (api/core/plugin/entities/plugin_daemon.py:23-29) 的
  envelope 模式 — ToolInvocationResult.success/error_message 字段
- License: Dify AGPL-3.0 vs 本项目 Apache-2.0 — 严格不拷源代码

CLAUDE.md immutability：ToolSpec / ToolInvocationResult dataclass frozen=True。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


# ── 值对象（Value Objects）─────────────────────────────────────────────────────


@dataclass(frozen=True)
class ToolSpec:
    """Tool 声明 — plugin 暴露给 LLM 节点的 tool 元信息。

    input_schema / output_schema 用 dict[str, Any] 直传 JSON Schema —
    不在主进程强校验 schema 合法性（plugin 自行保证），让 plugin 自由选格式。

    LLM 节点（Phase 5.D 起）直接把 input_schema 喂给 OpenAI / Anthropic function calling
    格式（这两家都吃 JSON Schema）。
    """

    name: str  # tool 名 — 在 plugin 内唯一（如 "search_employees" / "create_ticket"）
    description: str  # LLM 看的 tool 用途说明
    input_schema: dict[str, Any]  # JSON Schema for parameters（plugin 自定义）
    output_schema: dict[str, Any] | None = None  # 可空 — 部分 tool 不严格定义 output
    extras: dict[str, str] = field(default_factory=dict)  # plugin-specific metadata


@dataclass(frozen=True)
class ToolInvocationResult:
    """Tool 调用结果 — success / error envelope。

    设计借鉴 Dify PluginDaemonBasicResponse 但简化：
    - success=True 时 result 有值；
    - success=False 时 error_message 有值；
    - 永不同时有值（互斥）。

    比 Dify 简化的点：不用 generic 泛型（YAGNI v1）；不用 code 字段（plugin 自行 log）。
    """

    tool_name: str  # 回显 — 方便调用方按 tool 分流
    success: bool
    result: dict[str, Any] | None = None  # success=True 时有值
    error_message: str | None = None  # success=False 时有值


# ── Capability Protocol ────────────────────────────────────────────────────────


@runtime_checkable
class ToolCapability(Protocol):
    """LLM Tool 能力 — 让 LLM 节点能调 plugin 暴露的 RPC tools（v1.1 骨架）。

    Phase 5.A 仅定义 Protocol；具体 plugin 实现留 Phase 5.D+（LLM Tool 节点真实接入）。

    runtime_checkable 让 `isinstance(plugin, ToolCapability)` 走鸭子类型校验。

    Phase 5.D 起 LLM 节点调用方流程：
        1. tools = await tool_cap.list_tools()
        2. tool_schemas = [{"name": t.name, "description": t.description,
                            "parameters": t.input_schema} for t in tools]
        3. llm_response = await llm.invoke_with_tools(messages, tools=tool_schemas)
        4. if llm_response.tool_call:
               result = await tool_cap.invoke_tool(
                   tool_name=llm_response.tool_call.name,
                   arguments=llm_response.tool_call.arguments
               )
        5. messages.append({"role": "tool", "content": result.result, ...})
    """

    name: str  # plugin 名 — Registry 路由用

    async def list_tools(self) -> list[ToolSpec]:
        """列出 plugin 提供的所有 tools — LLM 节点 startup 调用。

        Returns:
            list[ToolSpec]: 该 plugin 暴露的全部 tool。空 list 表示 plugin 实现了
                ToolCapability 但当前没有可用 tool（如凭据未配置）。

        Phase 5.D 起 plugin 实现细节：
            - 静态 tool list（如 HR plugin 固定 5 个 tool）直接 return 常量
            - 动态 tool list（如 OpenAPI plugin 从 spec 文件读取）按需懒加载
        """
        ...

    async def invoke_tool(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolInvocationResult:
        """调用 plugin 提供的 tool — LLM 节点每次 function call 调用一次。

        Args:
            tool_name: list_tools 返回的 ToolSpec.name 之一
            arguments: 符合 ToolSpec.input_schema 的参数 dict（LLM 生成）

        Returns:
            ToolInvocationResult: success=True 时 result 是 tool 输出；
                success=False 时 error_message 是错误说明（plugin 友好文本，可喂回 LLM）。

        Phase 5.D 起 plugin 实现细节：
            - 未知 tool_name → return ToolInvocationResult(success=False,
                error_message=f"Tool {tool_name} not found")
            - arguments 不符合 schema → plugin 自行校验，return error
            - tool 内部异常 → plugin 自行 catch，return error（不向主进程 raise，避免
              单个 tool fail 影响整个 LLM 流程）
        """
        ...
