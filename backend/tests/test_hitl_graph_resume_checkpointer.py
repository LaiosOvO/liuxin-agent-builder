"""HITL graph resume — checkpointer 注入回归测试（Phase 3 03-VERIFICATION gap closure）.

Verifier 报告：原 _default_graph_loader 调用 compiler.compile(dsl) 时未传
checkpointer，导致 LangGraph 的 interrupt 永远找不到 thread state，无法 resume，
流程被静默卡住（node_state.payload 更新成功但 graph 不推进）。

本测试组用 mock 拦截 DSLCompiler.compile + graph.ainvoke，验证：
1. _default_graph_resumer 把 checkpointer 注入 compile()
2. compile() 在 `async with get_checkpointer()` 内被调用（checkpointer 仍 active）
3. ainvoke(Command(resume=...)) 收到正确 thread_id + resume_args
4. workflow_version 缺失 / DSL 空时返回 False 且不抛异常

不依赖真实 Postgres 容器（compile/ainvoke 全 mock），可在 CI 内跑。
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
def fake_flow_instance():
    """fake flow_instance（不入 DB）— 仅用于 _default_graph_resumer 入参。"""
    inst = MagicMock()
    inst.id = uuid.uuid4()
    inst.workspace_id = uuid.uuid4()
    inst.workflow_version_id = uuid.uuid4()
    return inst


@pytest.fixture
def fake_workflow_version():
    """fake workflow_version with non-empty DSL."""
    wv = MagicMock()
    wv.dsl = {
        "version": "1.0",
        "state_schema": {},
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [{"source": "start", "target": "end"}],
    }
    return wv


async def test_resumer_returns_false_when_workflow_version_missing(
    fake_flow_instance,
):
    """workflow_version 不存在时 resumer 返回 False，不抛异常。"""
    from app.agent_builder.api.hitl import _default_graph_resumer

    db = MagicMock()
    db.get = AsyncMock(return_value=None)
    redis = MagicMock()

    result = await _default_graph_resumer(
        fake_flow_instance,
        db,
        redis,
        resume_args={"action": "approve", "reason": ""},
        thread_id="ws/inst",
    )
    assert result is False


async def test_resumer_returns_false_when_dsl_empty(fake_flow_instance):
    """workflow_version.dsl 空时 resumer 返回 False。"""
    from app.agent_builder.api.hitl import _default_graph_resumer

    wv = MagicMock()
    wv.dsl = None
    db = MagicMock()
    db.get = AsyncMock(return_value=wv)
    redis = MagicMock()

    result = await _default_graph_resumer(
        fake_flow_instance,
        db,
        redis,
        resume_args={"action": "approve"},
        thread_id="ws/inst",
    )
    assert result is False


async def test_resumer_passes_checkpointer_to_compile(
    fake_flow_instance, fake_workflow_version
):
    """P0 回归：resumer 必须把 checkpointer 作为 kwarg 传给 compile()。

    这是 03-VERIFICATION gap 的根因 — 原 _default_graph_loader 丢了 checkpointer。
    """
    from app.agent_builder.api.hitl import _default_graph_resumer

    db = MagicMock()
    db.get = AsyncMock(return_value=fake_workflow_version)
    redis = MagicMock()

    fake_checkpointer = MagicMock(name="AsyncPostgresSaver")
    fake_graph = MagicMock()
    fake_graph.ainvoke = AsyncMock(return_value={"end": "done"})
    fake_compiled = MagicMock()
    fake_compiled.graph = fake_graph

    compile_calls: list[dict] = []

    def _compile_spy(dsl, **kwargs):
        compile_calls.append({"dsl": dsl, "kwargs": kwargs})
        return fake_compiled

    @patch("app.agent_builder.workflow.checkpoint.get_checkpointer")
    @patch("app.agent_builder.workflow.compiler.DSLCompiler")
    async def _run(mock_compiler_cls, mock_get_cp):
        # async context manager 模拟
        cp_cm = MagicMock()
        cp_cm.__aenter__ = AsyncMock(return_value=fake_checkpointer)
        cp_cm.__aexit__ = AsyncMock(return_value=None)
        mock_get_cp.return_value = cp_cm

        mock_compiler_instance = MagicMock()
        mock_compiler_instance.compile = MagicMock(side_effect=_compile_spy)
        mock_compiler_cls.return_value = mock_compiler_instance

        return await _default_graph_resumer(
            fake_flow_instance,
            db,
            redis,
            resume_args={
                "action": "approve",
                "reason": "ok",
                "form_data": {},
                "actor_id": str(uuid.uuid4()),
                "ip": "10.0.0.1",
                "ua": "UA",
                "jti": str(uuid.uuid4()),
            },
            thread_id=f"{fake_flow_instance.workspace_id}/{fake_flow_instance.id}",
        )

    result = await _run()

    # 关键断言：compile 收到 checkpointer kwarg（root-cause fix 验证）
    assert result is True, "resumer 应在 ainvoke 成功时返回 True"
    assert len(compile_calls) == 1, "compile 应被调用一次"
    assert "checkpointer" in compile_calls[0]["kwargs"], (
        "checkpointer kwarg 缺失 — 这是 03-VERIFICATION gap 的根因"
    )
    assert compile_calls[0]["kwargs"]["checkpointer"] is fake_checkpointer

    # ainvoke 应收到 Command(resume=...) + thread_id config
    fake_graph.ainvoke.assert_awaited_once()
    call_args = fake_graph.ainvoke.await_args
    cmd_arg = call_args.args[0]
    # langgraph.types.Command 是 frozen dataclass，有 resume 字段
    assert hasattr(cmd_arg, "resume"), "ainvoke 应收到 Command 对象"
    assert cmd_arg.resume["action"] == "approve"
    config = call_args.kwargs["config"]
    assert config["configurable"]["thread_id"] == (
        f"{fake_flow_instance.workspace_id}/{fake_flow_instance.id}"
    )


async def test_resumer_swallows_exception_and_returns_false(
    fake_flow_instance, fake_workflow_version
):
    """compile 或 ainvoke 异常时 resumer 返回 False，不阻塞 node_state 写入。"""
    from app.agent_builder.api.hitl import _default_graph_resumer

    db = MagicMock()
    db.get = AsyncMock(return_value=fake_workflow_version)
    redis = MagicMock()

    with patch(
        "app.agent_builder.workflow.checkpoint.get_checkpointer"
    ) as mock_get_cp:
        cp_cm = MagicMock()
        cp_cm.__aenter__ = AsyncMock(
            side_effect=RuntimeError("checkpointer 连接失败")
        )
        cp_cm.__aexit__ = AsyncMock(return_value=None)
        mock_get_cp.return_value = cp_cm

        result = await _default_graph_resumer(
            fake_flow_instance,
            db,
            redis,
            resume_args={"action": "approve"},
            thread_id="ws/inst",
        )

    assert result is False, "异常应被捕获并返回 False（不阻塞 node_state 写入）"
