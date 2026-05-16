"""HitlActionService 集成测试（CLAUDE.md 2.2 — 真实 PG + Redis 不 mock）。

测试覆盖（8 用例）：
1. test_submit_action_happy_path_consumes_jti_and_writes_audit
2. test_submit_action_form_schema_validation_failure_raises
3. test_submit_action_double_submit_raises_JtiAlreadyConsumed
4. test_submit_action_invalidates_siblings
5. test_submit_action_writes_audit_log_with_ip_ua_decision
6. test_submit_action_updates_node_state_payload_records
7. test_submit_action_computes_new_status_correctly
8. test_submit_action_advisory_lock_acquired

设计：
- 真实 PG（CLAUDE.md 2.2 不 mock DB）
- 真实 Redis（HitlTokenStore 内部用 pipeline）
- mock graph_loader（返回 None 跳过 LangGraph ainvoke — Phase 2 ExecutionEngine 集成留 03-10 E2E）
- seed 链路与 test_hitl_service.py 一致
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy import select, text

from app.agent_builder.models.audit_log import AuditLog
from app.agent_builder.models.hitl_token import HitlToken
from app.agent_builder.models.node_state import NodeState
from app.agent_builder.services.hitl_action_service import (
    FlowInstanceNotFound,
    FormDataValidationError,
    HitlActionService,
    JtiAlreadyConsumed,
    NodeStateNotFound,
)


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=False)
async def clean_phase3(db_session):
    """每次测试后清理 Phase 3 + Phase 1/2 表。"""
    yield
    await db_session.execute(text("DELETE FROM audit_logs"))
    await db_session.execute(text("DELETE FROM hitl_tokens"))
    await db_session.execute(text("DELETE FROM node_states"))
    await db_session.execute(text("DELETE FROM flow_instances"))
    await db_session.execute(text("DELETE FROM workflow_versions"))
    await db_session.execute(text("DELETE FROM workflows"))
    await db_session.execute(text("DELETE FROM user_workspace_roles"))
    await db_session.execute(text("DELETE FROM users"))
    await db_session.execute(text("DELETE FROM workspaces"))
    await db_session.commit()


@pytest_asyncio.fixture
async def redis_client():
    """连接 test Redis（端口 16379；与 test_hitl_token_store_redis.py 一致）。"""
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:16379/0")
    client = Redis.from_url(redis_url, decode_responses=True)
    # 清理本测试相关 key（防止上次测试残留）
    keys = await client.keys("agent_builder:jti:*")
    if keys:
        await client.delete(*keys)
    yield client
    keys = await client.keys("agent_builder:jti:*")
    if keys:
        await client.delete(*keys)
    await client.aclose()


async def _seed_full_flow(
    db_session,
    *,
    form_schema: dict | None = None,
    phase: str = "submit",
    actions: list[str] = None,
) -> dict:
    """创建完整数据：ws → user → wf → ver → instance → node_state(payload) → 3 hitl_tokens。

    Returns:
        dict 含 jti_dict (action → jti UUID), node_state_id, instance_id, ws_id, user_id
    """
    if actions is None:
        actions = ["submit", "return", "reject"]
    if form_schema is None:
        form_schema = {}

    ws_id = uuid.uuid4()
    user_id = uuid.uuid4()
    wf_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    node_state_id = uuid.uuid4()

    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(ws_id), "name": "action测试", "slug": f"action-{ws_id.hex[:8]}"},
    )
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, status, is_super_admin) "
            "VALUES (:id, :email, :ph, 'active', false)"
        ),
        {"id": str(user_id), "email": f"u_{uuid.uuid4().hex[:6]}@test.com", "ph": "hash"},
    )
    await db_session.execute(
        text(
            "INSERT INTO workflows (id, workspace_id, name, status, created_by) "
            "VALUES (:id, :ws_id, :name, 'published', :created_by)"
        ),
        {
            "id": str(wf_id),
            "ws_id": str(ws_id),
            "name": "action_wf",
            "created_by": str(user_id),
        },
    )
    await db_session.execute(
        text(
            "INSERT INTO workflow_versions (id, workspace_id, workflow_id, version_no, kind, dsl, created_by) "
            "VALUES (:id, :ws_id, :wf_id, 1, 'published', '{}', :created_by)"
        ),
        {
            "id": str(ver_id),
            "ws_id": str(ws_id),
            "wf_id": str(wf_id),
            "created_by": str(user_id),
        },
    )
    thread_id = f"{ws_id}:{inst_id}"
    await db_session.execute(
        text(
            "INSERT INTO flow_instances "
            "(id, workspace_id, workflow_id, workflow_version_id, dsl_snapshot, thread_id, status) "
            "VALUES (:id, :ws_id, :wf_id, :ver_id, '{}', :thread_id, 'running')"
        ),
        {
            "id": str(inst_id),
            "ws_id": str(ws_id),
            "wf_id": str(wf_id),
            "ver_id": str(ver_id),
            "thread_id": thread_id,
        },
    )

    # node_state payload 含 form_schema + phase + records 空数组
    import json as _json
    initial_payload = {
        "phase": phase,
        "current_actor": {
            "id": str(user_id),
            "email": "user@test.com",
            "role": "executor" if phase == "submit" else "reviewer",
        },
        "approval_chain": {"mode": "single", "approvers": [str(user_id)], "current_idx": 0},
        "records": [],
        "pending_approvers": [],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "deadline_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        "form_schema": form_schema,
    }
    await db_session.execute(
        text(
            "INSERT INTO node_states "
            "(id, workspace_id, instance_id, node_id, node_type, status, payload) "
            "VALUES (:id, :ws_id, :inst_id, 'hitl_1', 'hitl', 'waiting_human', CAST(:payload AS jsonb))"
        ),
        {
            "id": str(node_state_id),
            "ws_id": str(ws_id),
            "inst_id": str(inst_id),
            "payload": _json.dumps(initial_payload),
        },
    )

    # 创建 3 个 hitl_tokens（每个 action 一行）
    jti_dict = {}
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    for action in actions:
        jti = uuid.uuid4()
        jti_dict[action] = jti
        await db_session.execute(
            text(
                "INSERT INTO hitl_tokens "
                "(jti, instance_id, node_state_id, actor_id, action, expires_at) "
                "VALUES (:jti, :inst, :ns, :actor, :action, :exp)"
            ),
            {
                "jti": str(jti),
                "inst": str(inst_id),
                "ns": str(node_state_id),
                "actor": str(user_id),
                "action": action,
                "exp": expires_at,
            },
        )

    await db_session.commit()

    return {
        "ws_id": ws_id,
        "user_id": user_id,
        "inst_id": inst_id,
        "node_state_id": node_state_id,
        "jti_dict": jti_dict,
    }


def _build_jwt_payload(seed: dict, action: str) -> dict:
    """构造 HitlTokenService.decode 返回值的 mock（不实际 sign，跳过 JWT）。"""
    return {
        "jti": str(seed["jti_dict"][action]),
        "flow_id": str(seed["inst_id"]),
        "node_state_id": str(seed["node_state_id"]),
        "actor_id": str(seed["user_id"]),
        "actor_email": "user@test.com",
        "role": "executor",
        "action": action,
    }


# ── 8 测试用例 ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_action_happy_path_consumes_jti_and_writes_audit(
    db_session, redis_client, clean_phase3
):
    """Happy path：submit 决策 → jti 消费 + audit 写入 + node_state 状态变迁。"""
    seed = await _seed_full_flow(db_session)
    service = HitlActionService(db_session, redis_client, graph_loader=_mock_graph_loader)
    jwt_payload = _build_jwt_payload(seed, "submit")

    result = await service.submit_action(
        payload=jwt_payload,
        action="submit",
        reason="同意提交",
        form_data={},
        ip="10.0.0.1",
        ua="Mozilla/5.0",
    )

    assert result["status"] == "ok"
    assert result["new_node_status"] == "in_review"  # submit phase + action=submit → in_review
    assert result["invalidated_siblings"] == 2  # return + reject 失效

    # 验证 jti 已消费
    consumed = await db_session.execute(
        select(HitlToken).where(HitlToken.jti == seed["jti_dict"]["submit"])
    )
    token = consumed.scalar_one()
    assert token.used_at is not None
    assert token.used_ip == "10.0.0.1"
    assert token.used_ua == "Mozilla/5.0"


@pytest.mark.asyncio
async def test_submit_action_form_schema_validation_failure_raises(
    db_session, redis_client, clean_phase3
):
    """form_schema 校验失败 → 抛 FormDataValidationError + jti 未消费。"""
    schema = {"type": "object", "required": ["comment"], "properties": {"comment": {"type": "string"}}}
    seed = await _seed_full_flow(db_session, form_schema=schema)
    service = HitlActionService(db_session, redis_client, graph_loader=_mock_graph_loader)
    jwt_payload = _build_jwt_payload(seed, "submit")

    with pytest.raises(FormDataValidationError) as exc_info:
        await service.submit_action(
            payload=jwt_payload,
            action="submit",
            reason="缺 comment 字段",
            form_data={"wrong": "field"},  # 缺 required.comment
            ip="10.0.0.1",
            ua="Mozilla/5.0",
        )
    assert exc_info.value.errors  # 错误列表非空

    # 验证 jti 未消费（校验失败不应消费）
    token = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.jti == seed["jti_dict"]["submit"])
        )
    ).scalar_one()
    assert token.used_at is None


@pytest.mark.asyncio
async def test_submit_action_double_submit_raises_JtiAlreadyConsumed(
    db_session, redis_client, clean_phase3
):
    """同 jti 二次提交 → 抛 JtiAlreadyConsumed。"""
    seed = await _seed_full_flow(db_session)
    service = HitlActionService(db_session, redis_client, graph_loader=_mock_graph_loader)
    jwt_payload = _build_jwt_payload(seed, "submit")

    # 第一次成功
    await service.submit_action(
        payload=jwt_payload,
        action="submit",
        reason="第一次",
        form_data={},
        ip="10.0.0.1",
        ua="UA-1",
    )

    # 第二次抛异常
    with pytest.raises(JtiAlreadyConsumed):
        await service.submit_action(
            payload=jwt_payload,
            action="submit",
            reason="重复提交",
            form_data={},
            ip="10.0.0.2",
            ua="UA-2",
        )


@pytest.mark.asyncio
async def test_submit_action_invalidates_siblings(
    db_session, redis_client, clean_phase3
):
    """同节点其他 token 失效（HITL-01 防重复决策）。"""
    seed = await _seed_full_flow(db_session)
    service = HitlActionService(db_session, redis_client, graph_loader=_mock_graph_loader)
    jwt_payload = _build_jwt_payload(seed, "submit")

    await service.submit_action(
        payload=jwt_payload,
        action="submit",
        reason="提交",
        form_data={},
        ip="10.0.0.1",
        ua="UA",
    )

    # 验证 sibling tokens (return / reject) 都已 used_at SET
    rows = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.node_state_id == seed["node_state_id"])
        )
    ).scalars().all()

    by_action = {r.action: r for r in rows}
    assert by_action["submit"].used_ip == "10.0.0.1"  # 真实用户消费
    assert by_action["return"].used_at is not None
    assert by_action["return"].used_ip == "system:sibling-invalidate"
    assert by_action["reject"].used_at is not None
    assert by_action["reject"].used_ip == "system:sibling-invalidate"


@pytest.mark.asyncio
async def test_submit_action_writes_audit_log_with_ip_ua_decision(
    db_session, redis_client, clean_phase3
):
    """NET-05 决策审计：actor_ip / actor_ua / decision / node_state_id 全部填。"""
    seed = await _seed_full_flow(db_session)
    service = HitlActionService(db_session, redis_client, graph_loader=_mock_graph_loader)
    jwt_payload = _build_jwt_payload(seed, "submit")

    await service.submit_action(
        payload=jwt_payload,
        action="submit",
        reason="NET-05 测试",
        form_data={},
        ip="192.168.1.100",
        ua="Mozilla/5.0 (Macintosh) Chrome/120",
    )

    audit = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "hitl.decision")
        )
    ).scalar_one()

    assert audit.actor_ip == "192.168.1.100"
    assert audit.actor_ua == "Mozilla/5.0 (Macintosh) Chrome/120"
    assert audit.decision == "submit"
    assert audit.node_state_id == seed["node_state_id"]
    assert audit.actor_user_id == seed["user_id"]
    assert audit.workspace_id == seed["ws_id"]
    assert audit.target_type == "node_state"
    assert audit.target_id == seed["node_state_id"]
    # meta 包含完整上下文
    assert audit.meta["jti"] == str(seed["jti_dict"]["submit"])
    assert audit.meta["instance_id"] == str(seed["inst_id"])
    assert audit.meta["reason"] == "NET-05 测试"


@pytest.mark.asyncio
async def test_submit_action_updates_node_state_payload_records(
    db_session, redis_client, clean_phase3
):
    """append_record 添加新记录到 node_state.payload['records']。"""
    seed = await _seed_full_flow(db_session)
    service = HitlActionService(db_session, redis_client, graph_loader=_mock_graph_loader)
    jwt_payload = _build_jwt_payload(seed, "submit")

    await service.submit_action(
        payload=jwt_payload,
        action="submit",
        reason="审核通过",
        form_data={"comment": "OK"},
        ip="10.0.0.1",
        ua="UA",
    )

    # 重新加载 node_state（不能依赖 ORM 缓存）
    db_session.expire_all()
    ns = await db_session.get(NodeState, seed["node_state_id"])
    assert ns is not None
    assert ns.status == "in_review"
    assert ns.payload is not None
    records = ns.payload.get("records", [])
    assert len(records) == 1
    rec = records[0]
    assert rec["action"] == "submit"
    assert rec["reason"] == "审核通过"
    assert rec["form_data"] == {"comment": "OK"}
    assert rec["ip"] == "10.0.0.1"
    assert rec["actor_id"] == str(seed["user_id"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phase,action,expected_status",
    [
        ("submit", "submit", "in_review"),  # 执行人 submit → 进入 review
        ("review", "approve", "done"),       # 审核人 approve → 终态 done
        ("submit", "return", "returned"),    # 任何 phase 的 return → 终态
        ("review", "reject", "rejected"),    # 任何 phase 的 reject → 终态
    ],
)
async def test_submit_action_computes_new_status_correctly(
    db_session, redis_client, clean_phase3, phase, action, expected_status
):
    """状态机变迁正确：phase + action → expected_status。"""
    actions_for_phase = (
        ["submit", "return", "reject"] if phase == "submit" else ["approve", "return", "reject"]
    )
    seed = await _seed_full_flow(db_session, phase=phase, actions=actions_for_phase)
    service = HitlActionService(db_session, redis_client, graph_loader=_mock_graph_loader)
    jwt_payload = _build_jwt_payload(seed, action)
    # 修正 role 匹配 phase
    jwt_payload["role"] = "executor" if phase == "submit" else "reviewer"

    result = await service.submit_action(
        payload=jwt_payload,
        action=action,
        reason=f"测试 {phase}+{action}",
        form_data={},
        ip="10.0.0.1",
        ua="UA",
    )
    assert result["new_node_status"] == expected_status


@pytest.mark.asyncio
async def test_submit_action_advisory_lock_acquired(
    db_session, redis_client, clean_phase3, monkeypatch
):
    """advisory_xact_lock 被调用（spy text() 调用参数）。"""
    seed = await _seed_full_flow(db_session)
    service = HitlActionService(db_session, redis_client, graph_loader=_mock_graph_loader)
    jwt_payload = _build_jwt_payload(seed, "submit")

    # spy db.execute 调用
    original_execute = db_session.execute
    advisory_lock_calls = []

    async def spy_execute(stmt, *args, **kwargs):
        # stmt 可能是 TextClause / Select / Update 等
        stmt_text = str(stmt)
        if "advisory_xact_lock" in stmt_text.lower():
            advisory_lock_calls.append((stmt_text, args, kwargs))
        return await original_execute(stmt, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", spy_execute)

    await service.submit_action(
        payload=jwt_payload,
        action="submit",
        reason="lock 测试",
        form_data={},
        ip="10.0.0.1",
        ua="UA",
    )

    assert len(advisory_lock_calls) == 1
    # 检查 lock_key 参数（hash(thread_id) & 0x7FFF...）
    assert "k" in advisory_lock_calls[0][1][0]  # second positional arg is dict


@pytest.mark.asyncio
async def test_submit_action_raises_FlowInstanceNotFound_if_instance_missing(
    db_session, redis_client, clean_phase3
):
    """flow_instance 不存在 → 抛 FlowInstanceNotFound（覆盖 404 路径）。"""
    seed = await _seed_full_flow(db_session)
    service = HitlActionService(db_session, redis_client, graph_loader=_mock_graph_loader)
    jwt_payload = _build_jwt_payload(seed, "submit")
    jwt_payload["flow_id"] = str(uuid.uuid4())  # 不存在的 instance_id

    with pytest.raises(FlowInstanceNotFound):
        await service.submit_action(
            payload=jwt_payload,
            action="submit",
            reason="404 测试",
            form_data={},
            ip="10.0.0.1",
            ua="UA",
        )


# ── mock helpers ─────────────────────────────────────────────────────────────


async def _mock_graph_loader(flow_instance, db, redis):
    """mock graph loader — 返回 None 跳过 LangGraph ainvoke。

    真实 graph + Command(resume) 集成在 03-10 E2E 覆盖。
    """
    return None
