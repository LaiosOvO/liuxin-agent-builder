"""WebhookProvider 单元测试（Plan 04-09 NOTI-07）— HMAC 签名 + httpx-mock。

测试覆盖（≥ 7 用例）：
1. test_webhook_provider_satisfies_improvider_protocol
2. test_supports_card_update_is_false
3. test_send_hitl_card_posts_to_delivery_url：HTTP 调用 + body 正确
4. test_send_hitl_card_includes_hmac_signature_header：X-Agent-Builder-Signature 存在且 64 hex
5. test_send_hitl_card_signature_round_trip_verifies：自验签 round-trip
6. test_send_hitl_card_signature_is_stable_with_sort_keys：不同插入顺序产生相同签名
7. test_send_hitl_card_5xx_raises_connection_error
8. test_send_hitl_card_4xx_raises_runtime_error
9. test_update_card_raises_not_implemented：通用 webhook 不支持 update
10. test_send_supplement_text_posts_supplement_event
11. test_constructor_rejects_empty_delivery_url
12. test_compute_signature_64_hex_chars
13. test_signature_changes_when_payload_changes
14. test_send_hitl_card_envelope_contains_required_fields

CLAUDE.md 2.2：用 pytest-httpx mock + monkeypatch HMAC_SECRET。
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from app.agent_builder.notification.cards.webhook_payload import (
    WEBHOOK_EVENT_HITL_REQUIRED,
    WEBHOOK_EVENT_HITL_SUPPLEMENT,
)
from app.agent_builder.notification.providers.base import (
    IMProvider,
    PROVIDER_WEBHOOK,
)
from app.agent_builder.notification.providers.webhook import (
    EVENT_HEADER,
    SIGNATURE_HEADER,
    WebhookProvider,
    compute_signature,
    serialize_payload,
    verify_signature,
)


# ── Fixture ─────────────────────────────────────────────────────────────────


@pytest.fixture
def hmac_secret() -> str:
    return "test-hmac-secret-32-bytes-minimum-!"


@pytest.fixture
def webhook_provider(hmac_secret) -> WebhookProvider:
    """构造 WebhookProvider — 显式传 hmac_secret 隔离 env。"""
    return WebhookProvider(
        delivery_url="https://user-system.example.com/webhook",
        hmac_secret=hmac_secret,
    )


@pytest.fixture
def hitl_card_args() -> dict[str, Any]:
    """典型 send_hitl_card 参数。"""
    return {
        "recipient": "user_xyz",
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


def test_webhook_provider_satisfies_improvider_protocol(webhook_provider):
    """WebhookProvider 满足 IMProvider 鸭子类型。"""
    assert isinstance(webhook_provider, IMProvider)
    assert webhook_provider.name == PROVIDER_WEBHOOK


def test_supports_card_update_is_false(webhook_provider):
    """WebhookProvider.supports_card_update 为 False。"""
    assert webhook_provider.supports_card_update is False


def test_constructor_rejects_empty_delivery_url():
    """空 delivery_url 抛 ValueError。"""
    with pytest.raises(ValueError, match="delivery_url 不能为空"):
        WebhookProvider(delivery_url="", hmac_secret="x" * 32)


# ── 签名工具单元测试 ─────────────────────────────────────────────────────────


def test_compute_signature_64_hex_chars(hmac_secret):
    """compute_signature 输出 64 字符 hex（SHA256）。"""
    sig = compute_signature(payload_bytes=b'{"k":"v"}', secret=hmac_secret)
    assert len(sig) == 64
    int(sig, 16)  # 必须能解析为 hex


def test_signature_changes_when_payload_changes(hmac_secret):
    """payload 变化 → signature 必须变化。"""
    sig1 = compute_signature(payload_bytes=b'{"k":"v1"}', secret=hmac_secret)
    sig2 = compute_signature(payload_bytes=b'{"k":"v2"}', secret=hmac_secret)
    assert sig1 != sig2


def test_serialize_payload_sort_keys_and_compact():
    """serialize_payload 用 sort_keys + 紧凑分隔符（无空格）。"""
    bytes1 = serialize_payload({"b": 2, "a": 1})
    bytes2 = serialize_payload({"a": 1, "b": 2})
    # 同字段不同插入顺序 → 相同字节序列
    assert bytes1 == bytes2
    # 紧凑：无空格
    assert b": " not in bytes1
    assert b", " not in bytes1


def test_verify_signature_round_trip(hmac_secret):
    """compute + verify 一致性 round trip。"""
    body = b'{"event":"test"}'
    sig = compute_signature(payload_bytes=body, secret=hmac_secret)
    assert verify_signature(payload_bytes=body, signature=sig, secret=hmac_secret) is True
    # 错误签名应失败
    assert verify_signature(payload_bytes=body, signature="0" * 64, secret=hmac_secret) is False


def test_compute_signature_rejects_empty_secret():
    """空 secret 抛 RuntimeError。"""
    with pytest.raises(RuntimeError, match="HMAC_SECRET 未配置"):
        compute_signature(payload_bytes=b"x", secret="")


# ── send_hitl_card ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_hitl_card_posts_to_delivery_url(
    webhook_provider, hitl_card_args, httpx_mock
):
    """send_hitl_card 调用 POST <delivery_url>，body 含 event + 业务字段。"""
    httpx_mock.add_response(
        url="https://user-system.example.com/webhook",
        json={"received": True},
    )

    await webhook_provider.send_hitl_card(**hitl_card_args)

    request = httpx_mock.get_request()
    assert request is not None
    assert request.method == "POST"
    assert request.headers["Content-Type"] == "application/json"
    body = json.loads(request.read())
    # 验证 envelope 字段
    assert body["event"] == WEBHOOK_EVENT_HITL_REQUIRED
    assert body["recipient"] == "user_xyz"
    assert body["flow_title"] == "员工入职"
    assert body["node_title"] == "HR 审批"
    assert body["applicant_name"] == "张三"
    assert body["actor_name"] == "李四"
    assert body["deadline_at"] == "2026-05-18T18:00:00Z"
    assert body["description"] == "请审批"
    assert len(body["deeplinks"]) == 4


@pytest.mark.asyncio
async def test_send_hitl_card_includes_hmac_signature_header(
    webhook_provider, hitl_card_args, httpx_mock
):
    """请求 header 含 X-Agent-Builder-Signature 且为 64 字符 hex。"""
    httpx_mock.add_response(
        url="https://user-system.example.com/webhook",
        json={"ok": True},
    )

    await webhook_provider.send_hitl_card(**hitl_card_args)

    request = httpx_mock.get_request()
    sig = request.headers[SIGNATURE_HEADER]
    assert sig is not None
    assert len(sig) == 64
    int(sig, 16)  # 必须是 hex
    # event header 也应在
    assert request.headers[EVENT_HEADER] == WEBHOOK_EVENT_HITL_REQUIRED


@pytest.mark.asyncio
async def test_send_hitl_card_signature_round_trip_verifies(
    webhook_provider, hitl_card_args, hmac_secret, httpx_mock
):
    """自验签：用同密钥对 request body 重新计算签名，必须与 header 一致。"""
    httpx_mock.add_response(
        url="https://user-system.example.com/webhook",
        json={"ok": True},
    )

    await webhook_provider.send_hitl_card(**hitl_card_args)

    request = httpx_mock.get_request()
    raw_body = request.read()
    sig_in_header = request.headers[SIGNATURE_HEADER]

    # 用户端验签 round trip
    is_valid = verify_signature(
        payload_bytes=raw_body, signature=sig_in_header, secret=hmac_secret
    )
    assert is_valid is True


@pytest.mark.asyncio
async def test_send_hitl_card_envelope_contains_required_fields(
    webhook_provider, hitl_card_args, httpx_mock
):
    """envelope 含所有必需字段：event / recipient / instance_id / node_state_id / 业务字段 / deeplinks。"""
    httpx_mock.add_response(
        url="https://user-system.example.com/webhook",
        json={},
    )

    await webhook_provider.send_hitl_card(**hitl_card_args)

    body = json.loads(httpx_mock.get_request().read())
    required = {
        "event",
        "recipient",
        "instance_id",
        "node_state_id",
        "flow_title",
        "node_title",
        "applicant_name",
        "actor_name",
        "deadline_at",
        "description",
        "deeplinks",
    }
    assert required.issubset(set(body.keys())), (
        f"envelope 缺字段：{required - set(body.keys())}"
    )


@pytest.mark.asyncio
async def test_send_hitl_card_returns_message_id(
    webhook_provider, hitl_card_args, httpx_mock
):
    """返回 message_id 为 'webhook:<hash>:<recipient>' 格式。"""
    httpx_mock.add_response(
        url="https://user-system.example.com/webhook",
        json={"echo": "ok"},
    )

    result = await webhook_provider.send_hitl_card(**hitl_card_args)

    assert result["message_id"].startswith("webhook:")
    assert "user_xyz" in result["message_id"]
    assert result["raw_response"]["echo"] == "ok"


@pytest.mark.asyncio
async def test_send_hitl_card_5xx_raises_connection_error(
    webhook_provider, hitl_card_args, httpx_mock
):
    """HTTP 5xx → ConnectionError（tenacity 可重试）。"""
    httpx_mock.add_response(
        url="https://user-system.example.com/webhook",
        status_code=502,
        text="bad gateway",
    )

    with pytest.raises(ConnectionError, match="Webhook HTTP 502"):
        await webhook_provider.send_hitl_card(**hitl_card_args)


@pytest.mark.asyncio
async def test_send_hitl_card_4xx_raises_runtime_error(
    webhook_provider, hitl_card_args, httpx_mock
):
    """HTTP 4xx（非 429）→ RuntimeError（不重试）。"""
    httpx_mock.add_response(
        url="https://user-system.example.com/webhook",
        status_code=403,
        text="signature invalid",
    )

    with pytest.raises(RuntimeError, match="Webhook HTTP 403"):
        await webhook_provider.send_hitl_card(**hitl_card_args)


@pytest.mark.asyncio
async def test_send_hitl_card_429_raises_connection_error(
    webhook_provider, hitl_card_args, httpx_mock
):
    """HTTP 429 → ConnectionError（限流可重试）。"""
    httpx_mock.add_response(
        url="https://user-system.example.com/webhook",
        status_code=429,
        text="rate limited",
    )

    with pytest.raises(ConnectionError, match="Webhook HTTP 429"):
        await webhook_provider.send_hitl_card(**hitl_card_args)


# ── update_card ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_card_raises_not_implemented(webhook_provider):
    """update_card 抛 NotImplementedError（通用 webhook 无 update）。"""
    with pytest.raises(NotImplementedError, match="update_card 不支持"):
        await webhook_provider.update_card(
            message_id="webhook:abc:user_xyz",
            new_content={"text": "x"},
        )


# ── send_supplement_text ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_supplement_text_posts_supplement_event(
    webhook_provider, httpx_mock
):
    """send_supplement_text POST 新 envelope，event=hitl_supplement。"""
    httpx_mock.add_response(
        url="https://user-system.example.com/webhook",
        json={"ok": True},
    )

    await webhook_provider.send_supplement_text(
        recipient="user_xyz",
        text="流程已被 王五 同意",
    )

    request = httpx_mock.get_request()
    body = json.loads(request.read())
    assert body["event"] == WEBHOOK_EVENT_HITL_SUPPLEMENT
    assert body["recipient"] == "user_xyz"
    assert body["text"] == "流程已被 王五 同意"
    # event header 也应是 supplement
    assert request.headers[EVENT_HEADER] == WEBHOOK_EVENT_HITL_SUPPLEMENT


# ── env secret 回退 ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_secret_from_env_when_not_in_constructor(
    monkeypatch, hitl_card_args, httpx_mock
):
    """构造时不传 hmac_secret 时，运行时从 env 读取。"""
    monkeypatch.setenv("HMAC_SECRET", "env-secret-32-bytes-minimum-len-x!")
    httpx_mock.add_response(
        url="https://env-test.example.com/hook",
        json={},
    )

    p = WebhookProvider(delivery_url="https://env-test.example.com/hook")
    await p.send_hitl_card(**hitl_card_args)

    request = httpx_mock.get_request()
    sig = request.headers[SIGNATURE_HEADER]
    # 签名应能用 env secret 验签
    raw_body = request.read()
    assert verify_signature(
        payload_bytes=raw_body, signature=sig, secret="env-secret-32-bytes-minimum-len-x!"
    )
