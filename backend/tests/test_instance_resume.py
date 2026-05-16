"""实例重启恢复测试。

测试 ExecutionEngine.restart_pending_instances_on_startup 的行为：
1. 预置 pending + running 实例，验证全部重新 enqueue
2. completed 实例不重新 enqueue

约定：
- 需要真实 Postgres
- arq_pool 用 Mock
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
    r = await fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def mock_arq_pool():
    pool = MagicMock()
    pool.enqueue_job = AsyncMock()
    return pool


@pytest_asyncio.fixture
async def setup_instances(db_session):
    """创建测试用 workspace + workflow + 多个实例。

    返回 (ws_a, user, wv, instances_dict)
    """
    from app.agent_builder.models.flow_instance import FlowInstance
    from app.agent_builder.models.user import User, UserStatus
    from app.agent_builder.models.workflow import Workflow
    from app.agent_builder.models.workflow_version import WorkflowVersion
    from app.agent_builder.models.workspace import Workspace
    from app.agent_builder.workflow.checkpoint import build_thread_id
    from app.services.password import hash_password

    user = User(
        id=uuid.uuid4(),
        email=f"resume_test_{uuid.uuid4().hex[:6]}@test.example.com",
        password_hash=hash_password("TestPass1"),
        display_name="ResumeTester",
        status=UserStatus.active.value,
        is_super_admin=False,
    )
    db_session.add(user)

    ws = Workspace(id=uuid.uuid4(), name="ResumeWS", slug=f"resume-ws-{uuid.uuid4().hex[:6]}")
    db_session.add(ws)
    await db_session.flush()

    wf = Workflow(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        name="ResumeWF",
        status="published",
        created_by=user.id,
    )
    db_session.add(wf)
    await db_session.flush()

    simple_dsl = {
        "version": "1.0",
        "state_schema": {},
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [{"source": "start", "target": "end"}],
    }
    wv = WorkflowVersion(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        workflow_id=wf.id,
        version_no=1,
        kind="published",
        dsl=simple_dsl,
        created_by=user.id,
    )
    db_session.add(wv)
    await db_session.flush()

    def make_inst(status: str) -> FlowInstance:
        inst_id = uuid.uuid4()
        return FlowInstance(
            id=inst_id,
            workspace_id=ws.id,
            workflow_id=wf.id,
            workflow_version_id=wv.id,
            dsl_snapshot=simple_dsl,
            thread_id=build_thread_id(ws.id, inst_id),
            status=status,
            initial_input={},
            created_by=user.id,
        )

    inst_pending_1 = make_inst("pending")
    inst_pending_2 = make_inst("pending")
    inst_running = make_inst("running")
    inst_completed = make_inst("completed")
    inst_aborted = make_inst("aborted")

    for inst in [inst_pending_1, inst_pending_2, inst_running, inst_completed, inst_aborted]:
        db_session.add(inst)
    await db_session.commit()

    return ws, user, wv, {
        "pending_1": inst_pending_1,
        "pending_2": inst_pending_2,
        "running": inst_running,
        "completed": inst_completed,
        "aborted": inst_aborted,
    }


# ── 测试 1：restart_pending_instances_count ────────────────────────────────────────

@pytest.mark.asyncio
async def test_restart_pending_instances_count(
    db_session, fake_redis_instance, mock_arq_pool, setup_instances
):
    """DB 中 2 个 pending + 1 个 running → restart 重 enqueue 至少 3 个（含本 fixture 创建的实例）。"""
    from app.agent_builder.workflow.execution_engine import ExecutionEngine

    ws, user, wv, instances = setup_instances
    engine = ExecutionEngine(db=db_session, redis=fake_redis_instance, arq_pool=mock_arq_pool)

    count = await engine.restart_pending_instances_on_startup()

    # 本 fixture 创建 2 pending + 1 running = 3 个应被 enqueue
    # DB 中可能还有其他测试留下的 pending/running，所以 count >= 3
    assert count >= 3, f"期望至少 3 个实例重新 enqueue，实际 {count}"
    assert mock_arq_pool.enqueue_job.call_count >= 3

    # 验证本 fixture 的 3 个目标实例的 ID 都被 enqueue 了
    enqueued_ids = {
        call.args[1]  # enqueue_job("run_instance_arq", str(instance_id))
        for call in mock_arq_pool.enqueue_job.call_args_list
    }
    for key in ["pending_1", "pending_2", "running"]:
        assert str(instances[key].id) in enqueued_ids, f"实例 {key} 应被 enqueue"


# ── 测试 2：只有 completed 实例时，count=0 ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_restart_no_pending_instances(db_session, fake_redis_instance, mock_arq_pool, setup_instances):
    """只有 completed/aborted 实例时，restart 应返回 0。"""
    from app.agent_builder.models.flow_instance import FlowInstance
    from app.agent_builder.workflow.execution_engine import ExecutionEngine
    from sqlalchemy import update

    ws, user, wv, instances = setup_instances

    # 先把所有 pending/running 标为 completed
    await db_session.execute(
        update(FlowInstance)
        .where(FlowInstance.status.in_(["pending", "running"]))
        .values(status="completed")
    )
    await db_session.commit()

    # 新建一个独立的 mock_pool 避免计数被污染
    fresh_pool = MagicMock()
    fresh_pool.enqueue_job = AsyncMock()
    engine = ExecutionEngine(db=db_session, redis=fake_redis_instance, arq_pool=fresh_pool)

    count = await engine.restart_pending_instances_on_startup()
    assert count == 0
    fresh_pool.enqueue_job.assert_not_called()


# ── 测试 3：abort 实例不影响其他实例的 enqueue ────────────────────────────────────

@pytest.mark.asyncio
async def test_abort_does_not_affect_other_instances(
    db_session, fake_redis_instance, mock_arq_pool, setup_instances
):
    """abort 一个实例后，restart_pending_instances_on_startup 仍能正确统计其他 pending/running。"""
    from app.agent_builder.models.flow_instance import FlowInstance
    from app.agent_builder.workflow.execution_engine import ExecutionEngine
    from sqlalchemy import update

    ws, user, wv, instances = setup_instances

    # abort 一个 pending 实例
    await db_session.execute(
        update(FlowInstance)
        .where(FlowInstance.id == instances["pending_1"].id)
        .values(status="aborted")
    )
    await db_session.commit()

    fresh_pool = MagicMock()
    fresh_pool.enqueue_job = AsyncMock()
    engine = ExecutionEngine(db=db_session, redis=fake_redis_instance, arq_pool=fresh_pool)

    count = await engine.restart_pending_instances_on_startup()
    # 剩余 1 pending + 1 running = 2
    assert count == 2
    assert fresh_pool.enqueue_job.call_count == 2


# ── 测试 4：start_instance + abort 序列验证 ──────────────────────────────────────

@pytest.mark.asyncio
async def test_start_then_abort_instance(
    db_session, fake_redis_instance, mock_arq_pool, setup_instances
):
    """start_instance 然后 abort_instance，最终 status 应为 aborted。"""
    from app.agent_builder.models.flow_instance import FlowInstance
    from app.agent_builder.workflow.execution_engine import ExecutionEngine

    ws, user, wv, instances = setup_instances
    engine = ExecutionEngine(db=db_session, redis=fake_redis_instance, arq_pool=mock_arq_pool)

    # 创建新实例
    inst = await engine.start_instance(
        workflow_version_id=wv.id,
        initial_input={},
        user_id=user.id,
        workspace_id=ws.id,
    )
    assert inst.status == "pending"

    # 中止
    await engine.abort_instance(inst.id, user_id=user.id, workspace_id=ws.id)

    # 验证
    result = await db_session.execute(
        select(FlowInstance).where(FlowInstance.id == inst.id)
    )
    row = result.scalar_one()
    assert row.status == "aborted"
    assert row.completed_at is not None
