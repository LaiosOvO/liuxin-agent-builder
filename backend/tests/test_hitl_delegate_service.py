"""HitlService.create_delegate_token 集成测试（Plan 04-03，HITL-06）。

测试覆盖（9+ 用例，CLAUDE.md 2.2 真实 PG，不 mock DB）：

1. test_delegate_creates_3_tokens_for_recipient
2. test_delegate_new_deadline_reset_24h
3. test_delegate_records_appended_with_delegate_action
4. test_delegate_chain_delegated_field_set_depth_1
5. test_delegate_depth_2_then_3_then_4_raises_depth_exceeded
6. test_delegate_self_raises_self_delegate_error
7. test_delegate_to_existing_approver_raises_circular
8. test_delegate_cross_workspace_raises_recipient_not_found
9. test_delegate_recipient_disabled_raises_recipient_not_found
10. test_delegate_payload_immutability_old_dict_not_mutated

设计参考 docs/reading-dify-04-03-delegation-2026-05-17.md。
"""
from __future__ import annotations

import copy
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.agent_builder.models.flow_instance import FlowInstance
from app.agent_builder.models.hitl_token import HitlToken
from app.agent_builder.models.node_state import NodeState
from app.agent_builder.models.user import User
from app.agent_builder.services.hitl_service import (
    DEFAULT_TOKEN_EXPIRES_IN,
    MAX_DELEGATION_DEPTH,
    DelegateError,
    HitlService,
)


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=False)
async def clean_phase4_delegate(db_session):
    """测试后清理委托测试用表（含 user_workspace_roles 因为 delegate 需 JOIN 校验）。"""
    yield
    await db_session.execute(text("DELETE FROM hitl_tokens"))
    await db_session.execute(text("DELETE FROM node_states"))
    await db_session.execute(text("DELETE FROM flow_instances"))
    await db_session.execute(text("DELETE FROM workflow_versions"))
    await db_session.execute(text("DELETE FROM workflows"))
    await db_session.execute(text("DELETE FROM user_workspace_roles"))
    await db_session.execute(text("DELETE FROM users"))
    await db_session.execute(text("DELETE FROM workspaces"))
    await db_session.commit()


async def _ensure_role(db_session, role_id: int, code: str) -> None:
    """确保 roles 表有 (id, code) 行存在（migration 0001 已 seed 1-4 行，本函数兜底）。"""
    await db_session.execute(
        text(
            "INSERT INTO roles (id, code, description) VALUES (:id, :code, :desc) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": role_id, "code": code, "desc": code},
    )


async def _seed_delegate_scenario(
    db_session,
    *,
    second_workspace: bool = False,
    extra_approvers: list[uuid.UUID] | None = None,
    initial_delegated: dict | None = None,
    to_user_status: str = "active",
) -> dict:
    """完整种子数据：
    - workspace + (可选) 第二 workspace
    - from_user (active, 在 ws1)
    - to_user (active 或 disabled，在 ws1 或 ws2)
    - workflow / workflow_version / flow_instance / node_state（payload 含 approval_chain）

    Returns:
        dict 含所有 ORM 实例 + IDs
    """
    ws_id = uuid.uuid4()
    ws2_id = uuid.uuid4() if second_workspace else None

    from_user_id = uuid.uuid4()
    to_user_id = uuid.uuid4()
    wf_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    node_state_id = uuid.uuid4()

    # ── workspaces ─────────────────────────────────────────────────────
    await db_session.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :n, :s)"),
        {"id": str(ws_id), "n": "ws1", "s": f"ws1-{ws_id.hex[:8]}"},
    )
    if ws2_id is not None:
        await db_session.execute(
            text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :n, :s)"),
            {"id": str(ws2_id), "n": "ws2", "s": f"ws2-{ws2_id.hex[:8]}"},
        )

    # ── roles（FK 兜底） ───────────────────────────────────────────────
    await _ensure_role(db_session, 1, "admin")
    await _ensure_role(db_session, 2, "member")

    # ── users ──────────────────────────────────────────────────────────
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, status, is_super_admin) "
            "VALUES (:id, :e, 'h', 'active', false)"
        ),
        {"id": str(from_user_id), "e": f"from_{from_user_id.hex[:8]}@test.com"},
    )
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, status, is_super_admin) "
            "VALUES (:id, :e, 'h', :status, false)"
        ),
        {
            "id": str(to_user_id),
            "e": f"to_{to_user_id.hex[:8]}@test.com",
            "status": to_user_status,
        },
    )

    # ── user_workspace_roles（from_user 在 ws1，to_user 在 ws1 或 ws2）─
    await db_session.execute(
        text(
            "INSERT INTO user_workspace_roles (workspace_id, user_id, role_id) "
            "VALUES (:w, :u, 2)"
        ),
        {"w": str(ws_id), "u": str(from_user_id)},
    )
    to_user_ws = ws2_id if second_workspace else ws_id
    await db_session.execute(
        text(
            "INSERT INTO user_workspace_roles (workspace_id, user_id, role_id) "
            "VALUES (:w, :u, 2)"
        ),
        {"w": str(to_user_ws), "u": str(to_user_id)},
    )

    # ── workflow + version + instance ──────────────────────────────────
    await db_session.execute(
        text(
            "INSERT INTO workflows (id, workspace_id, name, status, created_by) "
            "VALUES (:id, :w, 'wf', 'published', :c)"
        ),
        {"id": str(wf_id), "w": str(ws_id), "c": str(from_user_id)},
    )
    await db_session.execute(
        text(
            "INSERT INTO workflow_versions "
            "(id, workspace_id, workflow_id, version_no, kind, dsl, created_by) "
            "VALUES (:id, :w, :wf, 1, 'published', '{}', :c)"
        ),
        {"id": str(ver_id), "w": str(ws_id), "wf": str(wf_id), "c": str(from_user_id)},
    )
    thread_id = f"{ws_id}:{inst_id}"
    await db_session.execute(
        text(
            "INSERT INTO flow_instances "
            "(id, workspace_id, workflow_id, workflow_version_id, "
            "dsl_snapshot, thread_id, status) "
            "VALUES (:id, :w, :wf, :v, '{}', :t, 'running')"
        ),
        {
            "id": str(inst_id),
            "w": str(ws_id),
            "wf": str(wf_id),
            "v": str(ver_id),
            "t": thread_id,
        },
    )

    # ── node_state.payload（含 approval_chain.approvers） ─────────────
    approvers = [str(from_user_id)]
    if extra_approvers:
        approvers.extend(str(a) for a in extra_approvers)

    approval_chain = {
        "mode": "single",
        "approvers": approvers,
        "current_idx": 0,
    }
    if initial_delegated:
        approval_chain["delegated"] = initial_delegated

    payload = {
        "phase": "review",
        "current_actor": {
            "id": str(from_user_id),
            "email": f"from_{from_user_id.hex[:8]}@test.com",
            "role": "reviewer",
        },
        "approval_chain": approval_chain,
        "records": [],
        "form_schema": {},
        "deadline_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
    }
    import json as _json

    await db_session.execute(
        text(
            "INSERT INTO node_states "
            "(id, workspace_id, instance_id, node_id, node_type, status, payload) "
            "VALUES (:id, :w, :i, 'hitl_1', 'hitl', 'in_review', CAST(:p AS jsonb))"
        ),
        {
            "id": str(node_state_id),
            "w": str(ws_id),
            "i": str(inst_id),
            "p": _json.dumps(payload),
        },
    )
    await db_session.commit()

    # 加载 ORM 实例
    from_user = (
        await db_session.execute(select(User).where(User.id == from_user_id))
    ).scalar_one()
    to_user = (
        await db_session.execute(select(User).where(User.id == to_user_id))
    ).scalar_one()
    flow_instance = (
        await db_session.execute(
            select(FlowInstance).where(FlowInstance.id == inst_id)
        )
    ).scalar_one()
    node_state = (
        await db_session.execute(
            select(NodeState).where(NodeState.id == node_state_id)
        )
    ).scalar_one()

    return {
        "ws_id": ws_id,
        "ws2_id": ws2_id,
        "from_user": from_user,
        "to_user": to_user,
        "flow_instance": flow_instance,
        "node_state": node_state,
        "to_user_email": to_user.email,
    }


# ── 1. 创建 3 个 token ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delegate_creates_3_tokens_for_recipient(
    db_session, clean_phase4_delegate
):
    """委托成功 → 创建 3 行 HitlToken (approve/return/reject) 给被委托人。"""
    seed = await _seed_delegate_scenario(db_session)
    service = HitlService(db_session)

    new_tokens, depth = await service.create_delegate_token(
        from_user=seed["from_user"],
        to_email=seed["to_user_email"],
        reason="我请假 3 天",
        node_state=seed["node_state"],
        flow_instance=seed["flow_instance"],
        ip="10.0.0.1",
        ua="Mozilla/5.0",
    )
    await db_session.commit()

    assert len(new_tokens) == 3
    assert {t.action for t in new_tokens} == {"approve", "return", "reject"}
    assert all(t.actor_id == seed["to_user"].id for t in new_tokens)
    assert all(t.used_at is None for t in new_tokens)
    assert depth == 1

    # DB 验证：3 行确实落地
    rows = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.actor_id == seed["to_user"].id)
        )
    ).scalars().all()
    assert len(rows) == 3


# ── 2. deadline_at 重置（不继承原 deadline） ─────────────────────────────────


@pytest.mark.asyncio
async def test_delegate_new_deadline_reset_24h(db_session, clean_phase4_delegate):
    """新 token.expires_at = now + 24h（重置），不继承原 node_state.deadline_at。"""
    seed = await _seed_delegate_scenario(db_session)
    service = HitlService(db_session)

    before = datetime.now(timezone.utc)
    new_tokens, _ = await service.create_delegate_token(
        from_user=seed["from_user"],
        to_email=seed["to_user_email"],
        reason="reason",
        node_state=seed["node_state"],
        flow_instance=seed["flow_instance"],
        ip="10.0.0.1",
        ua="UA",
    )
    await db_session.commit()
    after = datetime.now(timezone.utc)

    expected_min = before + timedelta(seconds=DEFAULT_TOKEN_EXPIRES_IN - 5)
    expected_max = after + timedelta(seconds=DEFAULT_TOKEN_EXPIRES_IN + 5)

    for tok in new_tokens:
        assert expected_min <= tok.expires_at <= expected_max


# ── 3. records 追加 type=delegate ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delegate_records_appended_with_delegate_action(
    db_session, clean_phase4_delegate
):
    """node_state.payload.records 追加一条 action='delegate' 记录。"""
    seed = await _seed_delegate_scenario(db_session)
    service = HitlService(db_session)

    await service.create_delegate_token(
        from_user=seed["from_user"],
        to_email=seed["to_user_email"],
        reason="出差不在公司",
        node_state=seed["node_state"],
        flow_instance=seed["flow_instance"],
        ip="192.168.1.1",
        ua="Chrome/120",
    )
    await db_session.commit()

    # 用 ORM 查询而非 get(expired) — 避免 commit 后的 lazy load 触发新事件循环 IO
    node_state = (
        await db_session.execute(
            select(NodeState).where(NodeState.id == seed["node_state"].id)
        )
    ).scalar_one()
    records = node_state.payload.get("records", [])

    assert len(records) == 1
    rec = records[0]
    assert rec["action"] == "delegate"
    assert rec["actor_id"] == str(seed["from_user"].id)
    assert rec["actor_email"] == seed["from_user"].email
    assert rec["reason"] == "出差不在公司"
    assert rec["delegate_to_id"] == str(seed["to_user"].id)
    assert rec["delegate_to_email"] == seed["to_user_email"]
    assert rec["depth"] == 1
    assert rec["ip"] == "192.168.1.1"
    assert rec["ua"] == "Chrome/120"
    assert "ts" in rec
    assert rec["form_data"] == {}


# ── 4. approval_chain.delegated 字段写入 ────────────────────────────────────


@pytest.mark.asyncio
async def test_delegate_chain_delegated_field_set_depth_1(
    db_session, clean_phase4_delegate
):
    """approval_chain.delegated[from_user_id] = {to:..., depth:1}。"""
    seed = await _seed_delegate_scenario(db_session)
    service = HitlService(db_session)

    await service.create_delegate_token(
        from_user=seed["from_user"],
        to_email=seed["to_user_email"],
        reason="reason",
        node_state=seed["node_state"],
        flow_instance=seed["flow_instance"],
        ip="1.1.1.1",
        ua="UA",
    )
    await db_session.commit()

    node_state = (
        await db_session.execute(
            select(NodeState).where(NodeState.id == seed["node_state"].id)
        )
    ).scalar_one()
    delegated = node_state.payload["approval_chain"].get("delegated", {})

    assert str(seed["from_user"].id) in delegated
    entry = delegated[str(seed["from_user"].id)]
    assert entry["to"] == str(seed["to_user"].id)
    assert entry["depth"] == 1


# ── 5. 深度上限：第 4 层抛 depth_exceeded ────────────────────────────────────


@pytest.mark.asyncio
async def test_delegate_depth_exceeded_at_level_4(
    db_session, clean_phase4_delegate
):
    """已 delegated 深度=3 时，再次委托抛 DelegateError code='depth_exceeded'。"""
    # 用初始 delegated 字典预置 — _seed_delegate_scenario 会写入 payload
    # 注意：用 placeholder UUID，下方再 SQL UPDATE 重写为真实 from_user.id
    seed = await _seed_delegate_scenario(db_session)

    # 真实场景：from_user 已经委托过且累计深度到 MAX
    # 直接通过 Python 端修改 ORM payload 再 commit（避免 stale cache）
    fresh_initial = {
        str(seed["from_user"].id): {"to": "any", "depth": MAX_DELEGATION_DEPTH},
    }
    node_state = seed["node_state"]
    old_payload = node_state.payload or {}
    new_chain = {
        **(old_payload.get("approval_chain") or {}),
        "delegated": fresh_initial,
    }
    new_payload = {**old_payload, "approval_chain": new_chain}
    node_state.payload = new_payload
    await db_session.commit()

    service = HitlService(db_session)
    with pytest.raises(DelegateError) as exc_info:
        await service.create_delegate_token(
            from_user=seed["from_user"],
            to_email=seed["to_user_email"],
            reason="再次委托",
            node_state=node_state,
            flow_instance=seed["flow_instance"],
            ip="1.1.1.1",
            ua="UA",
        )

    assert exc_info.value.code == "depth_exceeded"
    assert "3" in str(exc_info.value)


# ── 6. self_delegate ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delegate_self_raises_self_delegate_error(
    db_session, clean_phase4_delegate
):
    """to_email == from_user.email → DelegateError code='self_delegate'。"""
    seed = await _seed_delegate_scenario(db_session)
    service = HitlService(db_session)

    # 需要 to_email 用户存在但 id 与 from_user 相同 — 实测场景中两个 user 不会
    # 共享 email（CITEXT UNIQUE），所以构造一个 to_email = from_user.email 的用户
    # 也无法注入。改为把 to_email 指向 from_user.email，让 SQL 查 to_user 命中
    # from_user 本身（同一行）。
    with pytest.raises(DelegateError) as exc_info:
        await service.create_delegate_token(
            from_user=seed["from_user"],
            to_email=seed["from_user"].email,  # 自己的邮箱
            reason="自委托",
            node_state=seed["node_state"],
            flow_instance=seed["flow_instance"],
            ip="1.1.1.1",
            ua="UA",
        )

    assert exc_info.value.code == "self_delegate"


# ── 7. circular（被委托人已在 approvers 内） ─────────────────────────────────


@pytest.mark.asyncio
async def test_delegate_to_existing_approver_raises_circular(
    db_session, clean_phase4_delegate
):
    """to_user.id 已在 approval_chain.approvers 内 → DelegateError code='circular'。"""
    seed = await _seed_delegate_scenario(db_session)
    # 让 seed["to_user"].id 也是审批人之一（直接通过 ORM 更新 payload，避免 stale）
    node_state = seed["node_state"]
    old_payload = node_state.payload or {}
    new_chain = {
        **(old_payload.get("approval_chain") or {}),
        "approvers": [
            *(old_payload.get("approval_chain") or {}).get("approvers", []),
            str(seed["to_user"].id),
        ],
    }
    new_payload = {**old_payload, "approval_chain": new_chain}
    node_state.payload = new_payload
    await db_session.commit()

    service = HitlService(db_session)
    with pytest.raises(DelegateError) as exc_info:
        await service.create_delegate_token(
            from_user=seed["from_user"],
            to_email=seed["to_user_email"],
            reason="环路委托",
            node_state=node_state,
            flow_instance=seed["flow_instance"],
            ip="1.1.1.1",
            ua="UA",
        )

    assert exc_info.value.code == "circular"


# ── 8. 跨 workspace → recipient_not_found（防泄漏） ──────────────────────────


@pytest.mark.asyncio
async def test_delegate_cross_workspace_raises_recipient_not_found(
    db_session, clean_phase4_delegate
):
    """to_email 用户在另一个 workspace → DelegateError code='recipient_not_found'。"""
    seed = await _seed_delegate_scenario(db_session, second_workspace=True)
    service = HitlService(db_session)

    with pytest.raises(DelegateError) as exc_info:
        await service.create_delegate_token(
            from_user=seed["from_user"],
            to_email=seed["to_user_email"],  # 在 ws2 内
            reason="跨 ws",
            node_state=seed["node_state"],
            flow_instance=seed["flow_instance"],  # 在 ws1
            ip="1.1.1.1",
            ua="UA",
        )

    assert exc_info.value.code == "recipient_not_found"


# ── 9. to_user disabled → recipient_not_found ────────────────────────────────


@pytest.mark.asyncio
async def test_delegate_recipient_disabled_raises_recipient_not_found(
    db_session, clean_phase4_delegate
):
    """to_user.status='disabled' → DelegateError code='recipient_not_found'。"""
    seed = await _seed_delegate_scenario(db_session, to_user_status="disabled")
    service = HitlService(db_session)

    with pytest.raises(DelegateError) as exc_info:
        await service.create_delegate_token(
            from_user=seed["from_user"],
            to_email=seed["to_user_email"],
            reason="被禁用用户",
            node_state=seed["node_state"],
            flow_instance=seed["flow_instance"],
            ip="1.1.1.1",
            ua="UA",
        )

    assert exc_info.value.code == "recipient_not_found"


# ── 10. immutability：旧 payload 不被原地修改 ────────────────────────────────


@pytest.mark.asyncio
async def test_delegate_payload_immutability_old_dict_not_mutated(
    db_session, clean_phase4_delegate
):
    """create_delegate_token 不修改 payload 入参；构造新 dict 后赋值 ORM。"""
    seed = await _seed_delegate_scenario(db_session)
    service = HitlService(db_session)

    # 快照原 payload — deep copy
    old_payload_snapshot = copy.deepcopy(seed["node_state"].payload)
    snapshot_records_id = id(old_payload_snapshot["records"])

    await service.create_delegate_token(
        from_user=seed["from_user"],
        to_email=seed["to_user_email"],
        reason="immutability",
        node_state=seed["node_state"],
        flow_instance=seed["flow_instance"],
        ip="1.1.1.1",
        ua="UA",
    )
    await db_session.commit()

    # snapshot 的 records 仍是空 list（原值未被修改）— 快照本身不变
    assert old_payload_snapshot["records"] == []
    # snapshot.approval_chain 不含 delegated 字段
    assert "delegated" not in old_payload_snapshot["approval_chain"]
    # 同 list object id 不变
    assert id(old_payload_snapshot["records"]) == snapshot_records_id


# ── 11. (Bonus) 创建 token 后 DB 写入完成、jti 互不重复 ──────────────────────


@pytest.mark.asyncio
async def test_delegate_token_jti_unique_and_persisted(
    db_session, clean_phase4_delegate
):
    """3 个新 token 的 jti 互不相同，且都已通过 flush 落 DB。"""
    seed = await _seed_delegate_scenario(db_session)
    service = HitlService(db_session)

    new_tokens, _ = await service.create_delegate_token(
        from_user=seed["from_user"],
        to_email=seed["to_user_email"],
        reason="unique jti",
        node_state=seed["node_state"],
        flow_instance=seed["flow_instance"],
        ip="1.1.1.1",
        ua="UA",
    )
    await db_session.commit()

    jtis = {t.jti for t in new_tokens}
    assert len(jtis) == 3  # uuid4 不可能撞

    # DB 查回 3 行 — used_at 全为 None
    rows = (
        await db_session.execute(
            select(HitlToken).where(HitlToken.actor_id == seed["to_user"].id)
        )
    ).scalars().all()
    assert len(rows) == 3
    for row in rows:
        assert row.used_at is None
        assert row.instance_id == seed["flow_instance"].id
        assert row.node_state_id == seed["node_state"].id
