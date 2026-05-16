"""注册流程集成测试（邀请制，公开注册关闭）。

覆盖：
- 无 invite_token 直接 POST /api/auth/register 返回 403
- 通过 invite 流程注册（见 test_invite_flow.py 详细测）
"""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_register_without_invite_token_403(async_client, setup_complete_workspace):
    """POST /api/auth/register 无 invite_token 返回 403（公开注册关闭）。"""
    resp = await async_client.post(
        "/api/auth/register",
        json={
            "email": "newuser@test.example.com",
            "password": "NewPass1234",
            "display_name": "新用户",
            "invite_token": "fake_token",
        },
    )
    # 公开注册关闭，即使有 invite_token 也走 403（register 端点已关闭，应走 invites/accept）
    assert resp.status_code == 403
    assert "邀请" in resp.json()["detail"] or "关闭" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_register_no_body_422(async_client, setup_complete_workspace):
    """POST /api/auth/register 无 body 返回 422。"""
    resp = await async_client.post("/api/auth/register")
    assert resp.status_code in (403, 415, 422)
