"""HITL-07 申请人追踪页 API 集成测试（10 用例）。

测试用例：
1.  test_applicant_can_view_own_instance_tracking — 申请人本人 200
2.  test_non_applicant_403 — B 用户访问 A 的实例（同 workspace）→ 403
3.  test_admin_can_view_anyone — admin 绕过 applicant 检查
4.  test_admin_sees_ip_and_ua_in_records — admin records 含 IP/UA
5.  test_applicant_does_not_see_ip_or_ua — 申请人 records 中 ip/ua 为 None
6.  test_cross_workspace_returns_404 — ws_b 用户访问 ws_a 实例 → 404
7.  test_current_node_includes_deadline_for_active_hitl — active HITL 节点暴露 deadline
8.  test_completed_instance_has_no_current_node — 终态实例 current_node 为 None
9.  test_unauthenticated_returns_401 — 未登录访问 → 401
10. test_records_sorted_by_ts_ascending — records 按 ts ASC 排序（聚合跨节点）

使用真实 Postgres，禁止 mock DB（CLAUDE.md 2.2）。

注意（与 03-06 一致的 event loop 隔离规则）：
  直接 INSERT node_states 时不能复用 db_session（其 engine 与 async_client
  的 get_db 共享 pool，跨 API 调用会触发 "attached to a different loop"）。
  应每次使用 async_session_maker() 重新构造 session 写入并立即 commit / close。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from sqlalchemy import text

pytestmark = pytest.mark.asyncio


# ── 公共 DSL（与 test_instances_api 一致）─────────────────────────────────────

VALID_DSL = {
    "version": "1.0",
    "name": "测试工作流",
    "state_schema": {},
    "nodes": [
        {"id": "start", "type": "start", "position": {"x": 0, "y": 0}, "config": {}},
        {"id": "end", "type": "end", "position": {"x": 300, "y": 0}, "config": {}},
    ],
    "edges": [{"id": "e1", "source": "start", "target": "end"}],
}


# ── 清理 ────────────────────────────────────────────────────────────────────────


async def _cleanup(db_session):
    """删除工作流/实例相关表中的测试数据。

    委托给 _cleanup_independent —— 用独立 session 避免与 async_client 的
    连接池事件循环冲突（与 03-06 模式一致）。
    """
    await _cleanup_independent()


# 注意：跨测试事件循环隔离已经在 conftest.db_session fixture 中通过
# `await engine.dispose()` 实现；不需要本文件再加 autouse fixture，否则与
# conftest 的隔离重叠会导致 race condition（test_instances_api 同样模式
# 验证过 9 个用例稳定）。


# ── 辅助：创建并发布工作流 ────────────────────────────────────────────────────


async def _create_and_publish_workflow(async_client, cookie: str) -> str:
    """创建工作流 + 保存 DSL + 发布，返回 workflow_id。"""
    create_r = await async_client.post(
        "/api/agent_builder/v1/workflows",
        json={"name": "追踪测试工作流"},
        cookies={"session": cookie},
    )
    assert create_r.status_code == 201, create_r.text
    wf_id = create_r.json()["id"]

    save_r = await async_client.put(
        f"/api/agent_builder/v1/workflows/{wf_id}/draft",
        json={"dsl": VALID_DSL},
        cookies={"session": cookie},
    )
    assert save_r.status_code == 200, save_r.text

    pub_r = await async_client.post(
        f"/api/agent_builder/v1/workflows/{wf_id}/publish",
        cookies={"session": cookie},
    )
    assert pub_r.status_code == 200, pub_r.text

    return wf_id


async def _create_instance(async_client, cookie: str, wf_id: str) -> str:
    """创建实例（applicant 即 cookie 对应用户）。"""
    r = await async_client.post(
        f"/api/agent_builder/v1/workflows/{wf_id}/instances",
        json={"initial_input": {"k": "v"}},
        cookies={"session": cookie},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _insert_hitl_node_state(
    *,
    workspace_id: uuid.UUID,
    instance_id: str,
    node_id: str = "hitl_review_1",
    status: str = "waiting_human",
    records: list[dict] | None = None,
    deadline_at: str = "2026-05-18T12:00:00Z",
    actor_email: str = "approver@test.example.com",
    actor_name: str = "审批人甲",
) -> str:
    """直接 INSERT node_state（含 payload.records / payload.current_actor）。

    用独立 session 避免污染 async_client 的连接池事件循环（参考 03-06 模式）。
    返回 node_state UUID（str）。
    """
    if records is None:
        records = []
    payload = {
        "phase": "review",
        "current_actor": {"email": actor_email, "name": actor_name, "id": str(uuid.uuid4())},
        "deadline_at": deadline_at,
        "title": "审批节点",
        "records": records,
    }
    ns_id = uuid.uuid4()

    from app.agent_builder.db.engine import async_session_maker

    async with async_session_maker() as session:
        await session.execute(
            text(
                """
                INSERT INTO node_states (
                  id, workspace_id, instance_id, node_id, node_type, status,
                  started_at, payload, retries
                ) VALUES (
                  :id, :ws_id, :inst_id, :node_id, 'hitl', :status,
                  NOW(), CAST(:payload AS JSONB), 0
                )
                """
            ),
            {
                "id": ns_id,
                "ws_id": workspace_id,
                "inst_id": instance_id,
                "node_id": node_id,
                "status": status,
                "payload": json.dumps(payload),
            },
        )
        await session.commit()
    return str(ns_id)


async def _update_instance_status(instance_id: str, status: str) -> None:
    """直接 UPDATE flow_instance.status（绕过 service 中止逻辑限制）。

    用独立 session 与 async_client 隔离。
    """
    from app.agent_builder.db.engine import async_session_maker

    # 终态时 completed_at 同步写入；asyncpg 不支持同一参数复用于不同推断类型，
    # 因此根据 status 分两条 SQL。
    is_terminal = status in ("completed", "failed", "aborted")
    sql = (
        """
        UPDATE flow_instances
           SET status = :status,
               completed_at = NOW()
         WHERE id = :inst_id
        """
        if is_terminal
        else """
        UPDATE flow_instances
           SET status = :status
         WHERE id = :inst_id
        """
    )
    async with async_session_maker() as session:
        await session.execute(text(sql), {"status": status, "inst_id": instance_id})
        await session.commit()


async def _cleanup_independent() -> None:
    """通过独立 session 清理（事件循环隔离）。"""
    from app.agent_builder.db.engine import async_session_maker

    async with async_session_maker() as session:
        await session.execute(text("DELETE FROM node_states"))
        await session.execute(text("DELETE FROM flow_instances"))
        await session.execute(text("DELETE FROM workflow_versions"))
        await session.execute(text("DELETE FROM workflows"))
        await session.commit()


# ── Test 1: 申请人本人可访问 ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_applicant_can_view_own_instance_tracking(
    async_client, two_workspaces, db_session
):
    """申请人本人访问自己创建的实例 → 200，返回追踪信息。"""
    try:
        applicant, cookie = two_workspaces["ws_a_editor"]
        wf_id = await _create_and_publish_workflow(async_client, cookie)
        inst_id = await _create_instance(async_client, cookie, wf_id)

        r = await async_client.get(
            f"/api/agent_builder/v1/instances/{inst_id}/tracking",
            cookies={"session": cookie},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["instance_id"] == inst_id
        assert data["applicant"]["id"] == str(applicant.id)
        assert data["status"] == "pending"
        assert isinstance(data["records"], list)
        # 新实例无节点 → current_node 应为 None
        assert data["current_node"] is None
    finally:
        await _cleanup(db_session)


# ── Test 2: 非申请人 403 ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_non_applicant_403(async_client, two_workspaces, db_session):
    """B 用户（同 workspace，非 admin）访问 A 创建的实例 → 403。"""
    try:
        _, applicant_cookie = two_workspaces["ws_a_editor"]
        _, other_cookie = two_workspaces["ws_a_viewer"]

        wf_id = await _create_and_publish_workflow(async_client, applicant_cookie)
        inst_id = await _create_instance(async_client, applicant_cookie, wf_id)

        r = await async_client.get(
            f"/api/agent_builder/v1/instances/{inst_id}/tracking",
            cookies={"session": other_cookie},
        )
        assert r.status_code == 403, r.text
    finally:
        await _cleanup(db_session)


# ── Test 3: admin 绕过 applicant 检查 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_can_view_anyone(async_client, two_workspaces, db_session):
    """admin 访问他人创建的实例 → 200。"""
    try:
        _, applicant_cookie = two_workspaces["ws_a_editor"]
        _, admin_cookie = two_workspaces["ws_a_admin"]

        wf_id = await _create_and_publish_workflow(async_client, applicant_cookie)
        inst_id = await _create_instance(async_client, applicant_cookie, wf_id)

        r = await async_client.get(
            f"/api/agent_builder/v1/instances/{inst_id}/tracking",
            cookies={"session": admin_cookie},
        )
        assert r.status_code == 200, r.text
    finally:
        await _cleanup(db_session)


# ── Test 4: admin 看到完整 IP/UA ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_sees_ip_and_ua_in_records(
    async_client, two_workspaces, db_session
):
    """admin records 中 ip/ua 字段非 None。"""
    try:
        applicant, applicant_cookie = two_workspaces["ws_a_editor"]
        _, admin_cookie = two_workspaces["ws_a_admin"]

        wf_id = await _create_and_publish_workflow(async_client, applicant_cookie)
        inst_id = await _create_instance(async_client, applicant_cookie, wf_id)

        # 插入含 IP/UA 的 records 到 node_state.payload
        records = [
            {
                "actor_email": "approver@test.example.com",
                "actor_name": "审批人甲",
                "action": "approve",
                "reason": "看起来合规",
                "ts": "2026-05-17T09:30:00Z",
                "ip": "192.168.1.50",
                "ua": "Mozilla/5.0 Test",
            }
        ]
        await _insert_hitl_node_state(
            workspace_id=two_workspaces["ws_a"].id,
            instance_id=inst_id,
            records=records,
        )

        r = await async_client.get(
            f"/api/agent_builder/v1/instances/{inst_id}/tracking",
            cookies={"session": admin_cookie},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert len(data["records"]) == 1
        rec = data["records"][0]
        assert rec["ip"] == "192.168.1.50"
        assert rec["ua"] == "Mozilla/5.0 Test"
        assert rec["actor_email"] == "approver@test.example.com"
        assert rec["action"] == "approve"
        assert rec["reason"] == "看起来合规"
    finally:
        await _cleanup(db_session)


# ── Test 5: 申请人脱敏 IP/UA ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_applicant_does_not_see_ip_or_ua(
    async_client, two_workspaces, db_session
):
    """申请人本人（非 admin）records 中 ip/ua 字段为 None。"""
    try:
        applicant, applicant_cookie = two_workspaces["ws_a_editor"]

        wf_id = await _create_and_publish_workflow(async_client, applicant_cookie)
        inst_id = await _create_instance(async_client, applicant_cookie, wf_id)

        records = [
            {
                "actor_email": "approver@test.example.com",
                "actor_name": "审批人甲",
                "action": "approve",
                "reason": "ok",
                "ts": "2026-05-17T09:30:00Z",
                "ip": "192.168.1.50",
                "ua": "Mozilla/5.0 Test",
            }
        ]
        await _insert_hitl_node_state(
            workspace_id=two_workspaces["ws_a"].id,
            instance_id=inst_id,
            records=records,
        )

        r = await async_client.get(
            f"/api/agent_builder/v1/instances/{inst_id}/tracking",
            cookies={"session": applicant_cookie},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert len(data["records"]) == 1
        rec = data["records"][0]
        # 隐私字段脱敏
        assert rec["ip"] is None
        assert rec["ua"] is None
        # 业务字段保留
        assert rec["actor_email"] == "approver@test.example.com"
        assert rec["action"] == "approve"
        assert rec["actor_name"] == "审批人甲"
    finally:
        await _cleanup(db_session)


# ── Test 6: 跨 workspace 404 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_workspace_returns_404(
    async_client, two_workspaces, db_session
):
    """ws_b 用户访问 ws_a 中的实例 → 404（WorkspaceScopedQuery 过滤）。"""
    try:
        _, cookie_a = two_workspaces["ws_a_editor"]
        _, cookie_b = two_workspaces["ws_b_editor"]

        wf_id = await _create_and_publish_workflow(async_client, cookie_a)
        inst_id = await _create_instance(async_client, cookie_a, wf_id)

        r = await async_client.get(
            f"/api/agent_builder/v1/instances/{inst_id}/tracking",
            cookies={"session": cookie_b},
        )
        assert r.status_code == 404, r.text
    finally:
        await _cleanup(db_session)


# ── Test 7: active HITL 节点 deadline ──────────────────────────────────────


@pytest.mark.asyncio
async def test_current_node_includes_deadline_for_active_hitl(
    async_client, two_workspaces, db_session
):
    """active HITL 节点 → current_node.deadline_at + actor + status + node_type。"""
    try:
        _, cookie = two_workspaces["ws_a_editor"]

        wf_id = await _create_and_publish_workflow(async_client, cookie)
        inst_id = await _create_instance(async_client, cookie, wf_id)

        await _insert_hitl_node_state(
            workspace_id=two_workspaces["ws_a"].id,
            instance_id=inst_id,
            status="waiting_human",
            deadline_at="2026-05-18T12:00:00Z",
            actor_email="approver@test.example.com",
            actor_name="审批人甲",
        )

        r = await async_client.get(
            f"/api/agent_builder/v1/instances/{inst_id}/tracking",
            cookies={"session": cookie},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        cn = data["current_node"]
        assert cn is not None
        assert cn["status"] == "waiting_human"
        assert cn["node_type"] == "hitl"
        assert cn["deadline_at"] == "2026-05-18T12:00:00Z"
        assert cn["actor"]["email"] == "approver@test.example.com"
        assert cn["actor"]["name"] == "审批人甲"
        # title 来自 payload.title
        assert cn["title"] == "审批节点"
    finally:
        await _cleanup(db_session)


# ── Test 8: 终态实例无 current_node ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_completed_instance_has_no_current_node(
    async_client, two_workspaces, db_session
):
    """实例 status=completed 且所有节点终态 → current_node 为 None。"""
    try:
        _, cookie = two_workspaces["ws_a_editor"]

        wf_id = await _create_and_publish_workflow(async_client, cookie)
        inst_id = await _create_instance(async_client, cookie, wf_id)

        # 插入一个已完成的 HITL 节点
        records = [
            {
                "actor_email": "approver@test.example.com",
                "action": "approve",
                "reason": "ok",
                "ts": "2026-05-17T09:30:00Z",
            }
        ]
        await _insert_hitl_node_state(
            workspace_id=two_workspaces["ws_a"].id,
            instance_id=inst_id,
            status="done",
            records=records,
        )
        # 实例本身标记为 completed
        await _update_instance_status(inst_id, "completed")

        r = await async_client.get(
            f"/api/agent_builder/v1/instances/{inst_id}/tracking",
            cookies={"session": cookie},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "completed"
        assert data["current_node"] is None
        assert len(data["records"]) == 1
    finally:
        await _cleanup(db_session)


# ── Test 9: 未登录 401 ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unauthenticated_returns_401(
    async_client, two_workspaces, db_session
):
    """无 session cookie → 401。"""
    try:
        _, cookie = two_workspaces["ws_a_editor"]
        wf_id = await _create_and_publish_workflow(async_client, cookie)
        inst_id = await _create_instance(async_client, cookie, wf_id)

        r = await async_client.get(
            f"/api/agent_builder/v1/instances/{inst_id}/tracking",
            # 不带 cookie
        )
        assert r.status_code == 401, r.text
    finally:
        await _cleanup(db_session)


# ── Test 10: records 按 ts 排序（跨节点聚合）─────────────────────────────────


@pytest.mark.asyncio
async def test_records_sorted_by_ts_ascending(
    async_client, two_workspaces, db_session
):
    """两个节点各有 records，最终时间线按 ts ASC 全局排序。"""
    try:
        _, cookie = two_workspaces["ws_a_editor"]

        wf_id = await _create_and_publish_workflow(async_client, cookie)
        inst_id = await _create_instance(async_client, cookie, wf_id)

        # 节点 1：较晚提交
        await _insert_hitl_node_state(
            workspace_id=two_workspaces["ws_a"].id,
            instance_id=inst_id,
            node_id="hitl_n1",
            status="done",
            records=[
                {
                    "actor_email": "a@test.example.com",
                    "action": "submit",
                    "ts": "2026-05-17T10:00:00Z",
                }
            ],
        )
        # 节点 2：较早提交（用于验证排序）
        await _insert_hitl_node_state(
            workspace_id=two_workspaces["ws_a"].id,
            instance_id=inst_id,
            node_id="hitl_n2",
            status="done",
            records=[
                {
                    "actor_email": "b@test.example.com",
                    "action": "approve",
                    "ts": "2026-05-17T09:00:00Z",
                }
            ],
        )

        r = await async_client.get(
            f"/api/agent_builder/v1/instances/{inst_id}/tracking",
            cookies={"session": cookie},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        records = data["records"]
        assert len(records) == 2
        # ts ASC 排序：09:00 在前，10:00 在后
        assert records[0]["ts"] == "2026-05-17T09:00:00Z"
        assert records[0]["action"] == "approve"
        assert records[1]["ts"] == "2026-05-17T10:00:00Z"
        assert records[1]["action"] == "submit"
    finally:
        await _cleanup(db_session)
