"""MattermostProvider 单元测试（Plan 04-09 NOTI-06）— httpx-mock 拦截 v4 API。

测试覆盖（≥ 7 用例）：
1. test_mattermost_provider_satisfies_improvider_protocol
2. test_send_hitl_card_posts_to_api_v4_posts：POST /api/v4/posts + body 正确
3. test_send_hitl_card_returns_post_id_as_message_id
4. test_send_hitl_card_5xx_raises_connection_error
5. test_send_hitl_card_4xx_raises_runtime_error
6. test_update_card_uses_patch_endpoint：PUT /api/v4/posts/<id>/patch
7. test_send_supplement_text_posts_without_attachments
8. test_supports_card_update_is_true
9. test_constructor_rejects_empty_base_url_or_token
10. test_base_url_trailing_slash_stripped
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from app.agent_builder.notification.providers.base import (
    IMProvider,
    PROVIDER_MATTERMOST,
)
from app.agent_builder.notification.providers.mattermost import MattermostProvider


# ── Fixture ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mm_provider() -> MattermostProvider:
    """构造 MattermostProvider 实例。"""
    return MattermostProvider(
        base_url="https://mm.example.com",
        bot_token="mm-test-token-12345",
    )


@pytest.fixture
def hitl_card_args() -> dict[str, Any]:
    """典型 send_hitl_card 参数。"""
    return {
        "recipient": "ch_abc123",
        "flow_title": "员工入职",
        "node_title": "HR 审批",
        "applicant_name": "张三",
        "actor_name": "李四",
        "deadline_at": "2026-05-18T18:00:00Z",
        "description": "请审批",
        "deeplinks": [
            {"action": "approve", "url": "https://example.com/approve"},
            {"action": "return", "url": "https://example.com/return"},
            {"action": "reject", "url": "https://example.com/reject"},
            {"action": "detail", "url": "https://example.com/detail"},
        ],
    }


# ── Protocol / 构造 ──────────────────────────────────────────────────────────


def test_mattermost_provider_satisfies_improvider_protocol(mm_provider):
    """MattermostProvider 满足 IMProvider 鸭子类型。"""
    assert isinstance(mm_provider, IMProvider)
    assert mm_provider.name == PROVIDER_MATTERMOST


def test_supports_card_update_is_true(mm_provider):
    """MattermostProvider.supports_card_update 为 True（post patch 支持）。"""
    assert mm_provider.supports_card_update is True


def test_constructor_rejects_empty_base_url_or_token():
    """空 base_url / bot_token 抛 ValueError。"""
    with pytest.raises(ValueError, match="base_url 不能为空"):
        MattermostProvider(base_url="", bot_token="t")
    with pytest.raises(ValueError, match="bot_token 不能为空"):
        MattermostProvider(base_url="https://mm.example.com", bot_token="")


def test_base_url_trailing_slash_stripped():
    """base_url 尾部 / 被 strip。"""
    p = MattermostProvider(
        base_url="https://mm.example.com/",
        bot_token="t",
    )
    # private attr, but verifying behavior
    assert p._base_url == "https://mm.example.com"


# ── send_hitl_card ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_hitl_card_posts_to_api_v4_posts(
    mm_provider, hitl_card_args, httpx_mock
):
    """send_hitl_card 调用 POST /api/v4/posts，body 含 channel_id + message + props。"""
    httpx_mock.add_response(
        url="https://mm.example.com/api/v4/posts",
        json={"id": "post_id_xyz", "channel_id": "ch_abc123", "create_at": 1234567890},
    )

    await mm_provider.send_hitl_card(**hitl_card_args)

    request = httpx_mock.get_request()
    assert request is not None
    assert request.method == "POST"
    assert request.headers["Authorization"] == "Bearer mm-test-token-12345"
    body = json.loads(request.read())
    assert body["channel_id"] == "ch_abc123"
    assert "message" in body
    assert "props" in body
    assert "attachments" in body["props"]
    assert len(body["props"]["attachments"]) == 1
    # attachment 含 4 个 actions
    attachment = body["props"]["attachments"][0]
    assert len(attachment["actions"]) == 4


@pytest.mark.asyncio
async def test_send_hitl_card_returns_post_id_as_message_id(
    mm_provider, hitl_card_args, httpx_mock
):
    """返回 message_id 为 Mattermost post id。"""
    httpx_mock.add_response(
        url="https://mm.example.com/api/v4/posts",
        json={"id": "post_id_xyz_123", "channel_id": "ch_abc123"},
    )

    result = await mm_provider.send_hitl_card(**hitl_card_args)

    assert result["message_id"] == "post_id_xyz_123"
    assert result["raw_response"]["id"] == "post_id_xyz_123"


@pytest.mark.asyncio
async def test_send_hitl_card_5xx_raises_connection_error(
    mm_provider, hitl_card_args, httpx_mock
):
    """HTTP 5xx → ConnectionError（tenacity 可重试）。"""
    httpx_mock.add_response(
        url="https://mm.example.com/api/v4/posts",
        status_code=503,
        text="service unavailable",
    )

    with pytest.raises(ConnectionError, match="Mattermost /api/v4/posts HTTP 503"):
        await mm_provider.send_hitl_card(**hitl_card_args)


@pytest.mark.asyncio
async def test_send_hitl_card_4xx_raises_runtime_error(
    mm_provider, hitl_card_args, httpx_mock
):
    """HTTP 4xx（非 429） → RuntimeError（业务错误不重试）。"""
    httpx_mock.add_response(
        url="https://mm.example.com/api/v4/posts",
        status_code=404,
        text="channel not found",
    )

    with pytest.raises(RuntimeError, match="HTTP 404"):
        await mm_provider.send_hitl_card(**hitl_card_args)


@pytest.mark.asyncio
async def test_send_hitl_card_429_raises_connection_error(
    mm_provider, hitl_card_args, httpx_mock
):
    """HTTP 429（限流）→ ConnectionError（可重试）。"""
    httpx_mock.add_response(
        url="https://mm.example.com/api/v4/posts",
        status_code=429,
        text="too many requests",
    )

    with pytest.raises(ConnectionError, match="HTTP 429"):
        await mm_provider.send_hitl_card(**hitl_card_args)


# ── update_card ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_card_uses_patch_endpoint(mm_provider, httpx_mock):
    """update_card 调用 PUT /api/v4/posts/<id>/patch。"""
    httpx_mock.add_response(
        url="https://mm.example.com/api/v4/posts/post_id_xyz/patch",
        method="PUT",
        json={"id": "post_id_xyz"},
    )

    await mm_provider.update_card(
        message_id="post_id_xyz",
        new_content={"message": "已被 王五 审批"},
    )

    request = httpx_mock.get_request()
    assert request.method == "PUT"
    body = json.loads(request.read())
    assert body["message"] == "已被 王五 审批"


@pytest.mark.asyncio
async def test_update_card_rejects_empty_message_id(mm_provider):
    """空 message_id 抛 ValueError。"""
    with pytest.raises(ValueError, match="message_id 不能为空"):
        await mm_provider.update_card(message_id="", new_content={"message": "x"})


@pytest.mark.asyncio
async def test_update_card_rejects_empty_new_content(mm_provider):
    """new_content 不含 message / props 抛 ValueError。"""
    with pytest.raises(ValueError, match="message.*props"):
        await mm_provider.update_card(
            message_id="post_id_xyz",
            new_content={"unknown": "field"},
        )


# ── send_supplement_text ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_supplement_text_posts_without_attachments(
    mm_provider, httpx_mock
):
    """send_supplement_text 调用 POST /api/v4/posts，body 仅含 channel_id + message。"""
    httpx_mock.add_response(
        url="https://mm.example.com/api/v4/posts",
        json={"id": "post_supp_id"},
    )

    await mm_provider.send_supplement_text(
        recipient="ch_abc123",
        text="流程已被 王五 同意",
    )

    request = httpx_mock.get_request()
    body = json.loads(request.read())
    assert body["channel_id"] == "ch_abc123"
    assert body["message"] == "流程已被 王五 同意"
    assert "props" not in body  # 补充文本不带 props.attachments
