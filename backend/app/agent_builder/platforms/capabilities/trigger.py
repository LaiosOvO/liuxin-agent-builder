"""TriggerCapability — 平台 push event 触发 workflow（v1.1 骨架）。

设计要点（ADR-001 §3.5 + Dify reading doc 借鉴点 #3）：

- **Phase 5.A 仅定 Protocol 骨架** — 真实接入留 Phase 5.D+
- **subscribe_events 用 async generator** — pull 模式（比 Dify webhook 注册简化一层
  Flask route）；调用方 `async for event in cap.subscribe_events(["message.new"])`
- **verify_event_signature** — webhook / WS 模式下校验事件来源真实性（防伪造）

为什么 v1.1 仅骨架：用户 CONTEXT.md §Deferred Ideas 明确：
- TriggerCapability / ToolCapability / WorkflowCapability 完整接口（v1.1 仅留 Protocol
  骨架，真实接入留 Phase 5.D+）

Reference (Dify reading doc `docs/reading-dify-05a-03-hr-identity-trigger-tool-2026-05-17.md`)：
- 借鉴 Dify TriggerProviderEntity (api/core/trigger/entities/entities.py:138) 的
  subscription_schema + events[] 概念 — 但简化为 async generator pull
- 借鉴 Dify EndpointDeclaration (api/core/plugin/entities/endpoint.py:12-23) 的 path + method
  概念 — 但 v1.1 不实现 Flask route 注册
- License: Dify AGPL-3.0 vs 本项目 Apache-2.0 — 严格不拷源代码

CLAUDE.md immutability：TriggerEvent dataclass frozen=True，payload dict 由 plugin
自行保证不可变（Python convention）。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


# ── 值对象（Value Objects）─────────────────────────────────────────────────────


@dataclass(frozen=True)
class TriggerEvent:
    """订阅触发的事件 — plugin push 给主进程。

    event_type 是 plugin-defined 字符串（不强类型化 — 不同 plugin 用自己的语义）：
    - IM plugin: "message.new" / "message.updated" / "user.joined_channel"
    - Doc plugin: "doc.updated" / "comment.added"
    - HR plugin: "leave_request.created" / "employee.onboarded"

    payload 是 raw event data（dict[str, Any]） — 主进程 dispatch 到 workflow 节点时
    透传给 Trigger 节点的 output（不解析）。

    source_extras 装 plugin-specific 元数据（如 webhook delivery_id / WS connection_id）
    用于 Phase 7 Run Viewer 钩子 + audit log。
    """

    event_type: str
    payload: dict[str, Any]
    occurred_at: str  # ISO 8601 timestamp（plugin 自带 — 不用主进程当前时间）
    source_extras: dict[str, str] = field(default_factory=dict)


# ── Capability Protocol ────────────────────────────────────────────────────────


@runtime_checkable
class TriggerCapability(Protocol):
    """事件订阅能力 — plugin 主动推 event 到主进程（v1.1 骨架）。

    Phase 5.A 仅定义 Protocol；具体 plugin 实现留 Phase 5.D+（IM bot 入站 / Doc 变更
    订阅 / HR 离职流水线触发）。

    runtime_checkable 让 `isinstance(plugin, TriggerCapability)` 走鸭子类型校验。

    **重要 — async generator 模式**：subscribe_events 必须是 async generator function
    （含 `yield`），否则 Python isasyncgenfunction 返回 False，调用方 `async for` 失败。
    实现 stub 时即使没真实事件也要写 `if False: yield TriggerEvent(...)`，让 Python
    标记为 asyncgenfunction。
    """

    name: str  # plugin 名 — Registry 路由用

    def subscribe_events(
        self,
        event_types: list[str],
    ) -> AsyncIterator[TriggerEvent]:
        """长连接订阅事件 — async generator yield TriggerEvent。

        Args:
            event_types: 关心的 event_type 白名单（plugin 自己理解语义）。
                空 list 表示订阅所有事件。

        Yields:
            TriggerEvent: plugin push 的事件。
                调用方按 event_type 分流到对应 workflow Trigger 节点。

        用法（Phase 5.D Trigger 节点 runner）：
            async for event in trigger_cap.subscribe_events(["leave_request.created"]):
                await dispatch_to_workflow(event)

        实现细节（Phase 5.D 起 plugin 自实现）：
            - 长连接方式 plugin 自选（WebSocket / HTTP long-polling / Redis Stream）
            - 主进程负责消费速率控制（async for 自然 backpressure）
            - 重连 / 心跳 由 plugin 自行管理（fail-fast 后调用方决定是否 retry）
        """
        ...

    async def verify_event_signature(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> bool:
        """webhook / WS 模式下校验事件来源真实性。

        Args:
            headers: HTTP headers（如 X-Hub-Signature-256 / X-Lark-Signature）
            body: raw request body bytes

        Returns:
            bool: True 表示签名通过，False 表示伪造

        Phase 5.D 起 plugin 实现 — IM bot 入站 webhook 必校验防伪。
        """
        ...
