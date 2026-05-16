"""ExecutionEngine 集成测试。

测试 ExecutionEngine 的关键行为：
1. start_instance：创建 FlowInstance DB 行 + enqueue
2. 跨工作区权限拒绝
3. abort_instance：标记 status='aborted'
4. thread_id 格式校验
5. restart_pending_instances_on_startup：重新 enqueue

约定（CLAUDE.md 2.2）：
- 需要真实 Postgres（conftest.py db_session fixture）
- arq_pool 用 Mock 对象（避免需要真实 Redis 任务队列）
- Redis 用 fakeredis
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def fake_redis_instance():
    """独立 fakeredis 实例。"""
    r = await fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def mock_arq_pool():
    """Mock arq pool：仅 assert enqueue_job 被调用。"""
    pool = MagicMock()
    pool.enqueue_job = AsyncMock()
    return pool


@pytest_asyncio.fixture
async def workspace_and_workflow(db_session):
    """创建测试用 workspace + workflow + workflow_version。

    返回 (workspace, workflow_version, workspace_b)
    """
    from app.agent_builder.models.user import User, UserStatus
    from app.agent_builder.models.workflow import Workflow
    from app.agent_builder.models.workflow_version import WorkflowVersion
    from app.agent_builder.models.workspace import Workspace
    from app.services.password import hash_password

    # 创建用户
    user = User(
        id=uuid.uuid4(),
        email=f"runner_test_{uuid.uuid4().hex[:6]}@test.example.com",
        password_hash=hash_password("TestPassword1"),
        display_name="TestRunner",
        status=UserStatus.active.value,
        is_super_admin=False,
    )
    db_session.add(user)

    # 工作区 A
    ws_a = Workspace(id=uuid.uuid4(), name="工作区A", slug=f"ws-a-{uuid.uuid4().hex[:6]}")
    db_session.add(ws_a)

    # 工作区 B（用于跨 workspace 测试）
    ws_b = Workspace(id=uuid.uuid4(), name="工作区B", slug=f"ws-b-{uuid.uuid4().hex[:6]}")
    db_session.add(ws_b)

    await db_session.flush()

    # 创建 workflow（属于 ws_a）
    wf = Workflow(
        id=uuid.uuid4(),
        workspace_id=ws_a.id,
        name="测试工作流",
        status="published",
        created_by=user.id,
    )
    db_session.add(wf)
    await db_session.flush()

    # 创建 workflow_version
    simple_dsl = {
        "version": "1.0",
        "state_schema": {"result": "str"},
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [{"source": "start", "target": "end"}],
    }
    wv = WorkflowVersion(
        id=uuid.uuid4(),
        workspace_id=ws_a.id,
        workflow_id=wf.id,
        version_no=1,
        kind="published",
        dsl=simple_dsl,
        created_by=user.id,
    )
    db_session.add(wv)
    await db_session.commit()

    return user, ws_a, ws_b, wv


# ── 测试 1：start_instance 创建 FlowInstance 行 ───────────────────────────────────

@pytest.mark.asyncio
async def test_start_instance_creates_row(db_session, fake_redis_instance, mock_arq_pool, workspace_and_workflow):
    """start_instance 应在 flow_instances 表创建一行，status='pending'。"""
    from app.agent_builder.models.flow_instance import FlowInstance
    from app.agent_builder.workflow.execution_engine import ExecutionEngine

    user, ws_a, ws_b, wv = workspace_and_workflow
    engine = ExecutionEngine(db=db_session, redis=fake_redis_instance, arq_pool=mock_arq_pool)

    instance = await engine.start_instance(
        workflow_version_id=wv.id,
        initial_input={"name": "测试"},
        user_id=user.id,
        workspace_id=ws_a.id,
    )

    # 验证 DB 中存在该实例
    result = await db_session.execute(
        select(FlowInstance).where(FlowInstance.id == instance.id)
    )
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.status == "pending"
    assert row.workspace_id == ws_a.id
    assert row.workflow_version_id == wv.id
    assert row.initial_input == {"name": "测试"}


# ── 测试 2：start_instance 调用 arq enqueue ──────────────────────────────────────

@pytest.mark.asyncio
async def test_start_instance_enqueues_arq(db_session, fake_redis_instance, mock_arq_pool, workspace_and_workflow):
    """start_instance 应调用 arq_pool.enqueue_job('run_instance_arq', ...)。"""
    from app.agent_builder.workflow.execution_engine import ExecutionEngine

    user, ws_a, ws_b, wv = workspace_and_workflow
    engine = ExecutionEngine(db=db_session, redis=fake_redis_instance, arq_pool=mock_arq_pool)

    instance = await engine.start_instance(
        workflow_version_id=wv.id,
        initial_input={},
        user_id=user.id,
        workspace_id=ws_a.id,
    )

    # 验证 arq enqueue 被调用
    mock_arq_pool.enqueue_job.assert_called_once_with(
        "run_instance_arq", str(instance.id)
    )


# ── 测试 3：跨 workspace 权限拒绝 ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_instance_cross_workspace_denied(db_session, fake_redis_instance, mock_arq_pool, workspace_and_workflow):
    """用户在 ws_a，传 workflow_version 属于 ws_b → PermissionError。"""
    from app.agent_builder.workflow.execution_engine import ExecutionEngine

    user, ws_a, ws_b, wv = workspace_and_workflow

    # wv 属于 ws_a，但传入 ws_b 调用
    engine = ExecutionEngine(db=db_session, redis=fake_redis_instance, arq_pool=mock_arq_pool)

    with pytest.raises(PermissionError, match="workspace mismatch"):
        await engine.start_instance(
            workflow_version_id=wv.id,
            initial_input={},
            user_id=user.id,
            workspace_id=ws_b.id,  # 错误 workspace
        )


# ── 测试 4：abort_instance 标记 status='aborted' ──────────────────────────────────

@pytest.mark.asyncio
async def test_abort_instance_marks_status(db_session, fake_redis_instance, mock_arq_pool, workspace_and_workflow):
    """abort_instance 后，DB 中 status 应为 'aborted'。"""
    from app.agent_builder.models.flow_instance import FlowInstance
    from app.agent_builder.workflow.execution_engine import ExecutionEngine

    user, ws_a, ws_b, wv = workspace_and_workflow
    engine = ExecutionEngine(db=db_session, redis=fake_redis_instance, arq_pool=mock_arq_pool)

    # 先创建实例
    instance = await engine.start_instance(
        workflow_version_id=wv.id,
        initial_input={},
        user_id=user.id,
        workspace_id=ws_a.id,
    )

    # 中止
    await engine.abort_instance(
        instance.id,
        user_id=user.id,
        workspace_id=ws_a.id,
    )

    # 验证 DB 状态
    await db_session.refresh(instance)
    result = await db_session.execute(
        select(FlowInstance).where(FlowInstance.id == instance.id)
    )
    row = result.scalar_one()
    assert row.status == "aborted"
    assert row.completed_at is not None


# ── 测试 5：thread_id 格式 ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_thread_id_format(db_session, fake_redis_instance, mock_arq_pool, workspace_and_workflow):
    """thread_id 应为 '{workspace_id}:{instance_id}' 格式（防 Pitfall 13）。"""
    from app.agent_builder.workflow.execution_engine import ExecutionEngine

    user, ws_a, ws_b, wv = workspace_and_workflow
    engine = ExecutionEngine(db=db_session, redis=fake_redis_instance, arq_pool=mock_arq_pool)

    instance = await engine.start_instance(
        workflow_version_id=wv.id,
        initial_input={},
        user_id=user.id,
        workspace_id=ws_a.id,
    )

    expected_thread_id = f"{ws_a.id}:{instance.id}"
    assert instance.thread_id == expected_thread_id
