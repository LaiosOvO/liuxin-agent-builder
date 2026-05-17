"""SlackProvider 单元测试（Plan 04-09 NOTI-05）— httpx-mock 拦截 Slack Web API。

测试覆盖（≥ 7 用例）：
1. test_slack_provider_satisfies_improvider_protocol：runtime_checkable
2. test_send_hitl_card_posts_to_chat_postMessage：HTTP 调用 + body / headers 正确
3. test_send_hitl_card_returns_ts_and_channel_as_message_id：返回 channel:ts
4. test_send_hitl_card_5xx_raises_connection_error：HTTP 500 → ConnectionError
5. test_send_hitl_card_ok_false_raises_runtime_error：ok=false → RuntimeError
6. test_send_hitl_card_ok_false_ratelimited_raises_connection_error：限流可重试
7. test_update_card_calls_chat_update_with_channel_and_ts：update_card 路径
8. test_send_supplement_text_uses_chat_postMessage_without_blocks
9. test_supports_card_update_is_true
10. test_constructor_rejects_empty_bot_token

CLAUDE.md 2.2：用 pytest-httpx 替代真实网络（test fixture 自动隔离）。
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.agent_builder.notification.providers.base import IMProvider, PROVIDER_SLACK
from app.agent_builder.notification.providers.slack import SlackProvider


# ── Fixture ─────────────────────────────────────────────────────────────────


@pytest.fixture
def slack_provider() -> SlackProvider:
    """构造 SlackProvider 实例（token 用占位符 — 测试中 mock HTTP）。"""
    return SlackProvider(bot_token="xoxb-test-token-12345")


@pytest.fixture
def hitl_card_args() -> dict[str, Any]:
    """典型 send_hitl_card 参数字典。"""
    return {
        "recipient": "C123ABC456",
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


# ── Protocol ─────────────────────────────────────────────────────────────────


def test_slack_provider_satisfies_improvider_protocol(slack_provider):
    """SlackProvider 满足 IMProvider 鸭子类型。"""
    assert isinstance(slack_provider, IMProvider)
    assert slack_provider.name == PROVIDER_SLACK


def test_supports_card_update_is_true(slack_provider):
    """SlackProvider.supports_card_update 为 True（chat.update 支持）。"""
    assert slack_provider.supports_card_update is True


def test_constructor_rejects_empty_bot_token():
    """空 bot_token 抛 ValueError。"""
    with pytest.raises(ValueError, match="bot_token 不能为空"):
        SlackProvider(bot_token="")


# ── send_hitl_card ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_hitl_card_posts_to_chat_postMessage(
    slack_provider, hitl_card_args, httpx_mock
):
    """send_hitl_card 调用 POST chat.postMessage，body 含 channel + blocks + text。"""
    httpx_mock.add_response(
        url="https://slack.com/api/chat.postMessage",
        json={"ok": True, "ts": "1234567890.123456", "channel": "C123ABC456"},
    )

    await slack_provider.send_hitl_card(**hitl_card_args)

    request = httpx_mock.get_request()
    assert request is not None
    assert request.method == "POST"
    assert request.headers["Authorization"] == "Bearer xoxb-test-token-12345"
    body = json.loads(request.read())
    assert body["channel"] == "C123ABC456"
    assert "blocks" in body
    assert isinstance(body["blocks"], list)
    assert "text" in body
    # 4 个 button
    actions = body["blocks"][-1]
    assert actions["type"] == "actions"
    assert len(actions["elements"]) == 4


@pytest.mark.asyncio
async def test_send_hitl_card_returns_ts_and_channel_as_message_id(
    slack_provider, hitl_card_args, httpx_mock
):
    """返回 message_id 为 channel:ts 复合格式（chat.update 需要 channel+ts）。"""
    httpx_mock.add_response(
        url="https://slack.com/api/chat.postMessage",
        json={"ok": True, "ts": "1234567890.999", "channel": "C123ABC456"},
    )

    result = await slack_provider.send_hitl_card(**hitl_card_args)

    assert result["message_id"] == "C123ABC456:1234567890.999"
    assert result["raw_response"]["ok"] is True


@pytest.mark.asyncio
async def test_send_hitl_card_5xx_raises_connection_error(
    slack_provider, hitl_card_args, httpx_mock
):
    """HTTP 5xx → ConnectionError（tenacity 可重试）。"""
    httpx_mock.add_response(
        url="https://slack.com/api/chat.postMessage",
        status_code=503,
        text="service unavailable",
    )

    with pytest.raises(ConnectionError, match="Slack chat.postMessage"):
        await slack_provider.send_hitl_card(**hitl_card_args)


@pytest.mark.asyncio
async def test_send_hitl_card_ok_false_raises_runtime_error(
    slack_provider, hitl_card_args, httpx_mock
):
    """ok=false + invalid_auth → RuntimeError（业务错误不重试）。"""
    httpx_mock.add_response(
        url="https://slack.com/api/chat.postMessage",
        json={"ok": False, "error": "invalid_auth"},
    )

    with pytest.raises(RuntimeError, match="invalid_auth"):
        await slack_provider.send_hitl_card(**hitl_card_args)


@pytest.mark.asyncio
async def test_send_hitl_card_ok_false_ratelimited_raises_connection_error(
    slack_provider, hitl_card_args, httpx_mock
):
    """ok=false + ratelimited → ConnectionError（可重试）。"""
    httpx_mock.add_response(
        url="https://slack.com/api/chat.postMessage",
        json={"ok": False, "error": "ratelimited"},
    )

    with pytest.raises(ConnectionError, match="ratelimited"):
        await slack_provider.send_hitl_card(**hitl_card_args)


# ── update_card ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_card_calls_chat_update_with_channel_and_ts(
    slack_provider, httpx_mock
):
    """update_card 调用 chat.update，body 含 channel + ts。"""
    httpx_mock.add_response(
        url="https://slack.com/api/chat.update",
        json={"ok": True, "ts": "1234567890.999", "channel": "C123ABC456"},
    )

    await slack_provider.update_card(
        message_id="C123ABC456:1234567890.999",
        new_content={"text": "已被 王五 审批"},
    )

    request = httpx_mock.get_request()
    assert request is not None
    body = json.loads(request.read())
    assert body["channel"] == "C123ABC456"
    assert body["ts"] == "1234567890.999"
    assert body["text"] == "已被 王五 审批"


@pytest.mark.asyncio
async def test_update_card_rejects_malformed_message_id(slack_provider):
    """message_id 不含 ':' 抛 ValueError。"""
    with pytest.raises(ValueError, match="channel:ts"):
        await slack_provider.update_card(
            message_id="invalid_no_colon",
            new_content={"text": "x"},
        )


# ── send_supplement_text ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_supplement_text_uses_chat_postMessage_without_blocks(
    slack_provider, httpx_mock
):
    """send_supplement_text 调用 chat.postMessage，body 仅含 channel + text。"""
    httpx_mock.add_response(
        url="https://slack.com/api/chat.postMessage",
        json={"ok": True, "ts": "1234567890.111", "channel": "C123ABC456"},
    )

    await slack_provider.send_supplement_text(
        recipient="C123ABC456",
        text="流程已被 王五 同意",
    )

    request = httpx_mock.get_request()
    body = json.loads(request.read())
    assert body["channel"] == "C123ABC456"
    assert body["text"] == "流程已被 王五 同意"
    assert "blocks" not in body  # 补充文本不带 blocks
