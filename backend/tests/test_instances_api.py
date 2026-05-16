"""实例 CRUD API 集成测试（10 个）。

测试用例：
1.  test_start_instance_201              — 创建实例成功 201
2.  test_start_instance_unpublished_workflow_409 — 未发布工作流 409
3.  test_start_instance_viewer_403       — viewer 无法创建实例
4.  test_start_instance_cross_workspace_404 — 跨 workspace 访问 404
5.  test_list_instances_filter_by_status  — 按状态过滤
6.  test_list_instances_filter_by_workflow_id — 按工作流过滤
7.  test_list_instances_search_by_id_substring — 按 ID 前缀搜索
8.  test_list_instances_pagination        — 分页（25 条 / page=1 size=10）
9.  test_get_instance_includes_node_states — 详情含 node_states[]
10. test_abort_instance_sets_status_aborted — 中止实例

使用真实 Postgres，禁止 mock DB（CLAUDE.md 2.2）。
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

# ── 公共 DSL ──────────────────────────────────────────────────────────────────

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


# ── 辅助：清理 ────────────────────────────────────────────────────────────────

async def cleanup_all_tables(db_session):
    """清理所有工作流/实例相关表。"""
    from sqlalchemy import text
    await db_session.execute(text("DELETE FROM node_states"))
    await db_session.execute(text("DELETE FROM flow_instances"))
    await db_session.execute(text("DELETE FROM workflow_versions"))
    await db_session.execute(text("DELETE FROM workflows"))
    await db_session.commit()


# ── 辅助：创建并发布工作流 ────────────────────────────────────────────────────

async def _create_and_publish_workflow(async_client, cookie, name: str = "测试工作流") -> str:
    """创建工作流、保存草稿、发布，返回 workflow_id。"""
    create_r = await async_client.post(
        "/api/agent_builder/v1/workflows",
        json={"name": name},
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


# ── Test 1: 创建实例 201 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_instance_201(async_client, two_workspaces, db_session):
    """editor 创建实例（基于已发布工作流），返回 201。"""
    try:
        _, cookie = two_workspaces["ws_a_editor"]
        wf_id = await _create_and_publish_workflow(async_client, cookie)

        inst_r = await async_client.post(
            f"/api/agent_builder/v1/workflows/{wf_id}/instances",
            json={"initial_input": {"foo": "bar"}},
            cookies={"session": cookie},
        )
        assert inst_r.status_code == 201, inst_r.text
        data = inst_r.json()
        assert data["workflow_id"] == wf_id
        assert data["status"] == "pending"
        assert data["initial_input"] == {"foo": "bar"}
    finally:
        await cleanup_all_tables(db_session)


# ── Test 2: 未发布工作流 409 ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_instance_unpublished_workflow_409(async_client, two_workspaces, db_session):
    """未发布的工作流创建实例返回 409。"""
    try:
        _, cookie = two_workspaces["ws_a_editor"]

        # 只创建，不发布
        create_r = await async_client.post(
            "/api/agent_builder/v1/workflows",
            json={"name": "未发布工作流"},
            cookies={"session": cookie},
        )
        wf_id = create_r.json()["id"]

        inst_r = await async_client.post(
            f"/api/agent_builder/v1/workflows/{wf_id}/instances",
            json={"initial_input": {}},
            cookies={"session": cookie},
        )
        assert inst_r.status_code == 409, inst_r.text
    finally:
        await cleanup_all_tables(db_session)


# ── Test 3: viewer 403 ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_instance_viewer_403(async_client, two_workspaces, db_session):
    """viewer 无法创建实例，返回 403。"""
    try:
        _, admin_cookie = two_workspaces["ws_a_admin"]
        _, viewer_cookie = two_workspaces["ws_a_viewer"]

        wf_id = await _create_and_publish_workflow(async_client, admin_cookie, "viewer 测试")

        inst_r = await async_client.post(
            f"/api/agent_builder/v1/workflows/{wf_id}/instances",
            json={"initial_input": {}},
            cookies={"session": viewer_cookie},
        )
        assert inst_r.status_code == 403, inst_r.text
    finally:
        await cleanup_all_tables(db_session)


# ── Test 4: 跨 workspace 404 ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_instance_cross_workspace_404(async_client, two_workspaces, db_session):
    """ws_b 用户访问 ws_a 的工作流，返回 404。"""
    try:
        _, cookie_a = two_workspaces["ws_a_editor"]
        _, cookie_b = two_workspaces["ws_b_editor"]

        wf_id = await _create_and_publish_workflow(async_client, cookie_a, "A 的工作流")

        # ws_b 用户尝试在 ws_a 的工作流下创建实例
        inst_r = await async_client.post(
            f"/api/agent_builder/v1/workflows/{wf_id}/instances",
            json={"initial_input": {}},
            cookies={"session": cookie_b},
        )
        assert inst_r.status_code == 404, inst_r.text
    finally:
        await cleanup_all_tables(db_session)


# ── Test 5: 按状态过滤 ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_instances_filter_by_status(async_client, two_workspaces, db_session):
    """按 status 过滤实例列表。"""
    try:
        _, cookie = two_workspaces["ws_a_editor"]
        wf_id = await _create_and_publish_workflow(async_client, cookie, "状态过滤测试")

        # 创建 3 个实例
        ids = []
        for i in range(3):
            r = await async_client.post(
                f"/api/agent_builder/v1/workflows/{wf_id}/instances",
                json={"initial_input": {"i": i}},
                cookies={"session": cookie},
            )
            ids.append(r.json()["id"])

        # 手动将第一个改为 aborted（模拟中止）
        abort_r = await async_client.post(
            f"/api/agent_builder/v1/instances/{ids[0]}/abort",
            cookies={"session": cookie},
        )
        assert abort_r.status_code == 200

        # 按 status=pending 过滤（应返回 2 个）
        list_r = await async_client.get(
            "/api/agent_builder/v1/instances",
            params={"status": "pending"},
            cookies={"session": cookie},
        )
        assert list_r.status_code == 200
        data = list_r.json()
        assert data["total"] >= 2
        for item in data["items"]:
            assert item["status"] == "pending"

        # 按 status=aborted 过滤（应返回 ≥ 1 个）
        list_r2 = await async_client.get(
            "/api/agent_builder/v1/instances",
            params={"status": "aborted"},
            cookies={"session": cookie},
        )
        assert list_r2.status_code == 200
        aborted_ids = [i["id"] for i in list_r2.json()["items"]]
        assert ids[0] in aborted_ids
    finally:
        await cleanup_all_tables(db_session)


# ── Test 6: 按工作流 ID 过滤 ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_instances_filter_by_workflow_id(async_client, two_workspaces, db_session):
    """按 workflow_id 过滤实例列表（两个工作流的实例不互相干扰）。"""
    try:
        _, cookie = two_workspaces["ws_a_editor"]
        wf1_id = await _create_and_publish_workflow(async_client, cookie, "工作流1")
        wf2_id = await _create_and_publish_workflow(async_client, cookie, "工作流2")

        # 给 wf1 创建 2 个实例
        for _ in range(2):
            await async_client.post(
                f"/api/agent_builder/v1/workflows/{wf1_id}/instances",
                json={"initial_input": {}},
                cookies={"session": cookie},
            )

        # 给 wf2 创建 1 个实例
        await async_client.post(
            f"/api/agent_builder/v1/workflows/{wf2_id}/instances",
            json={"initial_input": {}},
            cookies={"session": cookie},
        )

        # 按 wf1 过滤
        list_r = await async_client.get(
            "/api/agent_builder/v1/instances",
            params={"workflow_id": wf1_id},
            cookies={"session": cookie},
        )
        assert list_r.status_code == 200
        data = list_r.json()
        assert data["total"] == 2
        for item in data["items"]:
            assert item["workflow_id"] == wf1_id

        # 按 wf2 过滤
        list_r2 = await async_client.get(
            "/api/agent_builder/v1/instances",
            params={"workflow_id": wf2_id},
            cookies={"session": cookie},
        )
        assert list_r2.json()["total"] == 1
    finally:
        await cleanup_all_tables(db_session)


# ── Test 7: 按 ID 前缀搜索 ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_instances_search_by_id_substring(async_client, two_workspaces, db_session):
    """按实例 ID 前缀搜索。"""
    try:
        _, cookie = two_workspaces["ws_a_editor"]
        wf_id = await _create_and_publish_workflow(async_client, cookie, "搜索测试")

        # 创建一个实例
        inst_r = await async_client.post(
            f"/api/agent_builder/v1/workflows/{wf_id}/instances",
            json={"initial_input": {}},
            cookies={"session": cookie},
        )
        inst_id = inst_r.json()["id"]

        # 用 ID 前 8 位搜索
        prefix = inst_id[:8]
        list_r = await async_client.get(
            "/api/agent_builder/v1/instances",
            params={"search": prefix},
            cookies={"session": cookie},
        )
        assert list_r.status_code == 200
        data = list_r.json()
        assert data["total"] >= 1
        ids = [i["id"] for i in data["items"]]
        assert inst_id in ids
    finally:
        await cleanup_all_tables(db_session)


# ── Test 8: 分页（25 条 / page=1 size=10）────────────────────────────────────

@pytest.mark.asyncio
async def test_list_instances_pagination(async_client, two_workspaces, db_session):
    """插入 25 条，page=1 size=10 返回 10 条，total=25。"""
    try:
        _, cookie = two_workspaces["ws_a_editor"]
        wf_id = await _create_and_publish_workflow(async_client, cookie, "分页测试")

        # 创建 25 个实例
        for i in range(25):
            r = await async_client.post(
                f"/api/agent_builder/v1/workflows/{wf_id}/instances",
                json={"initial_input": {"seq": i}},
                cookies={"session": cookie},
            )
            assert r.status_code == 201

        # page=1, size=10
        list_r = await async_client.get(
            "/api/agent_builder/v1/instances",
            params={"workflow_id": wf_id, "page": 1, "page_size": 10},
            cookies={"session": cookie},
        )
        assert list_r.status_code == 200
        data = list_r.json()
        assert data["total"] == 25
        assert len(data["items"]) == 10
        assert data["page"] == 1
        assert data["page_size"] == 10

        # page=3, size=10 → 5 条
        list_r2 = await async_client.get(
            "/api/agent_builder/v1/instances",
            params={"workflow_id": wf_id, "page": 3, "page_size": 10},
            cookies={"session": cookie},
        )
        assert len(list_r2.json()["items"]) == 5
    finally:
        await cleanup_all_tables(db_session)


# ── Test 9: 详情含 node_states[] ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_instance_includes_node_states(async_client, two_workspaces, db_session):
    """实例详情接口返回 node_states[]（即使为空列表）。"""
    try:
        _, cookie = two_workspaces["ws_a_editor"]
        wf_id = await _create_and_publish_workflow(async_client, cookie, "详情测试")

        inst_r = await async_client.post(
            f"/api/agent_builder/v1/workflows/{wf_id}/instances",
            json={"initial_input": {}},
            cookies={"session": cookie},
        )
        inst_id = inst_r.json()["id"]

        # 先插入一个 node_state 记录（模拟执行引擎写入）
        from app.agent_builder.models.node_state import NodeState
        from app.agent_builder.db.engine import async_session_maker
        async with async_session_maker() as s:
            # 获取 workspace_id
            from app.agent_builder.models.flow_instance import FlowInstance
            from sqlalchemy import select
            inst_result = await s.execute(
                select(FlowInstance).where(FlowInstance.id == inst_id)
            )
            inst_obj = inst_result.scalar_one_or_none()

            if inst_obj:
                ns = NodeState(
                    workspace_id=inst_obj.workspace_id,
                    instance_id=inst_id,
                    node_id="start",
                    node_type="start",
                    status="completed",
                )
                s.add(ns)
                await s.commit()

        detail_r = await async_client.get(
            f"/api/agent_builder/v1/instances/{inst_id}",
            cookies={"session": cookie},
        )
        assert detail_r.status_code == 200
        data = detail_r.json()
        assert "node_states" in data
        assert isinstance(data["node_states"], list)
        # 应能找到我们插入的节点
        node_ids = [ns["node_id"] for ns in data["node_states"]]
        assert "start" in node_ids
    finally:
        await cleanup_all_tables(db_session)


# ── Test 10: 中止实例 ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_abort_instance_sets_status_aborted(async_client, two_workspaces, db_session):
    """中止实例后 status 变为 aborted。"""
    try:
        _, cookie = two_workspaces["ws_a_editor"]
        wf_id = await _create_and_publish_workflow(async_client, cookie, "中止测试")

        inst_r = await async_client.post(
            f"/api/agent_builder/v1/workflows/{wf_id}/instances",
            json={"initial_input": {}},
            cookies={"session": cookie},
        )
        assert inst_r.status_code == 201
        inst_id = inst_r.json()["id"]

        # 中止
        abort_r = await async_client.post(
            f"/api/agent_builder/v1/instances/{inst_id}/abort",
            cookies={"session": cookie},
        )
        assert abort_r.status_code == 200, abort_r.text
        assert abort_r.json()["status"] == "aborted"

        # 再次中止 → 409
        abort_r2 = await async_client.post(
            f"/api/agent_builder/v1/instances/{inst_id}/abort",
            cookies={"session": cookie},
        )
        assert abort_r2.status_code == 409
    finally:
        await cleanup_all_tables(db_session)
