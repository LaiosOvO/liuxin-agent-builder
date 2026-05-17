"""TriggerCapability + ToolCapability v1.1 骨架单测 — runtime_checkable + async generator 静态断言 + JSON Schema dict 透传。

测试范围（v1.1 仅验证 Protocol 骨架契约 — 实现留 Phase 5.D+）：
1. runtime_checkable isinstance 路径（Mock plugin 鸭子类型）
2. TriggerEvent / ToolSpec / ToolInvocationResult dataclass frozen=True
3. ToolSpec.input_schema dict 透传（不强类型化）
4. ToolInvocationResult success / error envelope 互斥语义
5. **isasyncgenfunction 静态断言**（High 5 防 `if False: yield ...` 模式被误写）

直接子模块 import + 从 capabilities/__init__.py re-export 双路径都测试。
"""
from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.agent_builder.platforms.capabilities.tool import (
    ToolCapability,
    ToolInvocationResult,
    ToolSpec,
)
from app.agent_builder.platforms.capabilities.trigger import (
    TriggerCapability,
    TriggerEvent,
)


# ── Mock Trigger plugin ────────────────────────────────────────────────────────


class _MockTrigger:
    """Trigger 能力 mock — 实现 async generator subscribe_events + verify_event_signature。"""

    name = "mock_trigger"

    async def subscribe_events(
        self, event_types: list[str]
    ) -> AsyncIterator[TriggerEvent]:
        """模拟 push 2 个 event。"""
        for et in event_types[:2]:  # 取前 2 个 event type
            yield TriggerEvent(
                event_type=et,
                payload={"data": f"payload-{et}"},
                occurred_at="2026-05-17T12:00:00Z",
            )

    async def verify_event_signature(
        self, headers: dict[str, str], body: bytes
    ) -> bool:
        """模拟签名校验 — 仅验 X-Mock-Signature header 存在。"""
        return "X-Mock-Signature" in headers


# ── Mock Tool plugin ───────────────────────────────────────────────────────────


class _MockTool:
    """Tool 能力 mock — 实现 list_tools + invoke_tool。"""

    name = "mock_tool"

    async def list_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="echo",
                description="Echo back the input text",
                input_schema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
                output_schema={"type": "object", "properties": {"text": {"type": "string"}}},
            ),
            ToolSpec(
                name="add",
                description="Add two numbers",
                input_schema={
                    "type": "object",
                    "properties": {
                        "a": {"type": "number"},
                        "b": {"type": "number"},
                    },
                    "required": ["a", "b"],
                },
            ),
        ]

    async def invoke_tool(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolInvocationResult:
        if tool_name == "echo":
            return ToolInvocationResult(
                tool_name="echo",
                success=True,
                result={"text": arguments.get("text", "")},
            )
        if tool_name == "add":
            return ToolInvocationResult(
                tool_name="add",
                success=True,
                result={"sum": arguments["a"] + arguments["b"]},
            )
        return ToolInvocationResult(
            tool_name=tool_name,
            success=False,
            error_message=f"Tool {tool_name} not found",
        )


# ── Tests: TriggerCapability ───────────────────────────────────────────────────


def test_trigger_capability_isinstance():
    """runtime_checkable 鸭子类型 — Mock 无需继承也 pass isinstance。"""
    plugin = _MockTrigger()
    assert isinstance(plugin, TriggerCapability)


def test_trigger_event_frozen():
    """TriggerEvent dataclass frozen=True — 不可变。"""
    event = TriggerEvent(
        event_type="message.new",
        payload={"text": "hello"},
        occurred_at="2026-05-17T12:00:00Z",
    )
    with pytest.raises((AttributeError, Exception)):
        event.event_type = "modified"  # type: ignore[misc]


def test_trigger_event_source_extras_default():
    """TriggerEvent.source_extras 默认空 dict（default_factory）。"""
    event = TriggerEvent(
        event_type="x",
        payload={},
        occurred_at="2026-05-17T12:00:00Z",
    )
    assert event.source_extras == {}


def test_subscribe_events_is_async_generator_function():
    """**High 5 静态断言**: subscribe_events 必须是 async generator function（含 yield）。

    Trigger capability 的 subscribe_events 是 pull 模式核心 — 必须是 asyncgenfunction
    才能 `async for event in cap.subscribe_events(...)`。
    """
    assert inspect.isasyncgenfunction(_MockTrigger.subscribe_events), (
        "TriggerCapability.subscribe_events 必须是 async generator function（含 yield）。"
        " 若实现 stub 时即使不真 yield 也要写 `if False: yield TriggerEvent(...)`。"
    )


def test_subscribe_events_yields_trigger_events():
    """subscribe_events 真实 yield TriggerEvent。"""

    async def go():
        plugin = _MockTrigger()
        events = []
        async for event in plugin.subscribe_events(["msg.new", "msg.updated"]):
            events.append(event)
        assert len(events) == 2
        assert events[0].event_type == "msg.new"
        assert events[0].payload == {"data": "payload-msg.new"}
        assert events[1].event_type == "msg.updated"

    asyncio.run(go())


def test_verify_event_signature_returns_bool():
    """verify_event_signature 返回 bool — Mock 校验 X-Mock-Signature。"""

    async def go():
        plugin = _MockTrigger()
        ok = await plugin.verify_event_signature(
            {"X-Mock-Signature": "abc"}, b"body"
        )
        assert ok is True
        fail = await plugin.verify_event_signature({}, b"body")
        assert fail is False

    asyncio.run(go())


# ── Tests: ToolCapability ──────────────────────────────────────────────────────


def test_tool_capability_isinstance():
    """runtime_checkable 鸭子类型 — Mock 无需继承也 pass isinstance。"""
    plugin = _MockTool()
    assert isinstance(plugin, ToolCapability)


def test_tool_spec_frozen():
    """ToolSpec dataclass frozen=True — 不可变。"""
    spec = ToolSpec(
        name="search",
        description="Search the database",
        input_schema={"type": "object"},
    )
    with pytest.raises((AttributeError, Exception)):
        spec.name = "modified"  # type: ignore[misc]


def test_tool_spec_carries_json_schema_dict():
    """ToolSpec.input_schema 是 dict（不强类型化 — 借鉴 Dify ToolEntity 模式）。"""
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["query"],
    }
    spec = ToolSpec(name="search", description="Search", input_schema=schema)
    assert isinstance(spec.input_schema, dict)
    assert spec.input_schema == schema  # 透传
    assert spec.input_schema["properties"]["query"]["type"] == "string"


def test_tool_spec_output_schema_optional():
    """ToolSpec.output_schema 可空 — 部分 tool 不严格定义 output。"""
    spec = ToolSpec(
        name="trigger_action",
        description="Trigger an action",
        input_schema={"type": "object"},
    )
    assert spec.output_schema is None


def test_tool_invocation_result_success_envelope():
    """ToolInvocationResult success=True 时 result 有值，error_message=None。"""
    r = ToolInvocationResult(
        tool_name="echo",
        success=True,
        result={"text": "hello"},
    )
    assert r.success is True
    assert r.result == {"text": "hello"}
    assert r.error_message is None


def test_tool_invocation_result_error_envelope():
    """ToolInvocationResult success=False 时 error_message 有值，result=None。"""
    r = ToolInvocationResult(
        tool_name="unknown",
        success=False,
        error_message="Tool unknown not found",
    )
    assert r.success is False
    assert r.result is None
    assert r.error_message == "Tool unknown not found"


def test_tool_invocation_result_frozen():
    """ToolInvocationResult dataclass frozen=True。"""
    r = ToolInvocationResult(tool_name="x", success=True)
    with pytest.raises((AttributeError, Exception)):
        r.success = False  # type: ignore[misc]


def test_list_tools_returns_list_of_specs():
    """list_tools 返回 list[ToolSpec]。"""

    async def go():
        plugin = _MockTool()
        tools = await plugin.list_tools()
        assert isinstance(tools, list)
        assert all(isinstance(t, ToolSpec) for t in tools)
        assert len(tools) == 2
        assert tools[0].name == "echo"
        assert tools[1].name == "add"

    asyncio.run(go())


def test_invoke_tool_success_path():
    """invoke_tool 成功路径 — success=True + result 有值。"""

    async def go():
        plugin = _MockTool()
        result = await plugin.invoke_tool(
            tool_name="add", arguments={"a": 2, "b": 3}
        )
        assert result.success is True
        assert result.result == {"sum": 5}
        assert result.error_message is None

    asyncio.run(go())


def test_invoke_tool_unknown_name_returns_error():
    """invoke_tool 未知 tool_name 返回 error envelope（不 raise — plugin 自行 catch）。"""

    async def go():
        plugin = _MockTool()
        result = await plugin.invoke_tool(
            tool_name="nonexistent", arguments={}
        )
        assert result.success is False
        assert result.error_message == "Tool nonexistent not found"
        assert result.result is None

    asyncio.run(go())


# ── Tests: Re-export from capabilities/__init__.py ─────────────────────────────


def test_capabilities_package_reexports_all_8():
    """capabilities/__init__.py re-export 6 capability + 值对象（IM/Doc 来自 Plan 02 + 4 新）。

    验证 __all__ 含至少 14 字段（4 新 capability + 值对象，IM/Doc 可选）。
    """
    from app.agent_builder.platforms import capabilities

    # Plan 03 必须的 capability
    assert "HRCapability" in capabilities.__all__
    assert "IdentityCapability" in capabilities.__all__
    assert "TriggerCapability" in capabilities.__all__
    assert "ToolCapability" in capabilities.__all__

    # Plan 03 值对象
    assert "Employee" in capabilities.__all__
    assert "EmployeeRef" in capabilities.__all__
    assert "UserPrincipal" in capabilities.__all__
    assert "TriggerEvent" in capabilities.__all__
    assert "ToolSpec" in capabilities.__all__
    assert "ToolInvocationResult" in capabilities.__all__

    # 直接 import 验证
    from app.agent_builder.platforms.capabilities import (  # noqa: F401
        HRCapability,
        IdentityCapability,
        ToolCapability,
        TriggerCapability,
    )
