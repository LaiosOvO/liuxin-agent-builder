"""DingTalkProvider 集成测试（Plan 04-08 Task 2）。

测试覆盖（≥ 8 用例）：
1. test_provider_implements_improvider_protocol: runtime_checkable Protocol 校验
2. test_provider_name_is_dingtalk
3. test_send_hitl_card_calls_oapi_with_correct_payload
4. test_send_hitl_card_returns_message_id_from_task_id
5. test_send_hitl_card_raises_connection_error_on_oapi_errcode_nonzero
6. test_send_hitl_card_raises_connection_error_on_network_failure
7. test_update_card_raises_not_implemented_with_supplement_hint
8. test_send_supplement_text_uses_text_msgtype
9. test_send_hitl_card_includes_access_token_in_query_params
10. test_send_hitl_card_uses_agent_id_in_body
11. test_subscribe_raises_not_implemented
12. test_verify_webhook_signature_raises_not_implemented
13. test_send_hitl_card_action_card_msgtype_correct
14. test_send_hitl_card_passes_recipient_as_userid_list
15. test_get_access_token_raises_connection_error_when_sdk_returns_none

Mock 策略：
- httpx.AsyncClient 注入 fake transport（pytest-httpx 风格 — 但自实现 mock 避免引入新 fixture）
- sdk_client 注入 SimpleNamespace 模拟 get_access_token

CLAUDE.md 2.2 单元测试 + 集成测试：纯 Python mock，无真实 DB / 网络。
"""
from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.agent_builder.core.im_credentials import DingTalkCredentials
from app.agent_builder.notification.providers.base import (
    PROVIDER_DINGTALK,
    IMProvider,
)
from app.agent_builder.notification.providers.dingtalk import (
    DingTalkProvider,
    _DingTalkSendResult,
)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_fake_sdk_client(token: str | None = "fake_access_token_12345") -> Any:
    """构造一个 fake SDK client，仅含 get_access_token 方法。"""
    fake = SimpleNamespace()
    fake.get_access_token = MagicMock(return_value=token)
    return fake


def _make_credentials() -> DingTalkCredentials:
    return DingTalkCredentials(app_key="test_app_key", app_secret="test_app_secret")


def _make_provider_with_mock_http(
    *,
    handler: Any,
    sdk_token: str | None = "fake_access_token_12345",
) -> DingTalkProvider:
    """构造一个带 mock httpx client 的 DingTalkProvider。

    Args:
        handler: httpx.MockTransport 的 request handler 函数
        sdk_token: 模拟 SDK get_access_token 返回值（None 模拟失败）
    """
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(
        base_url="https://oapi.dingtalk.com",
        transport=transport,
    )
    return DingTalkProvider(
        credentials=_make_credentials(),
        agent_id=999000,
        http_client=http_client,
        sdk_client=_make_fake_sdk_client(token=sdk_token),
    )


def _standard_deeplinks() -> list[dict[str, str]]:
    return [
        {"action": "approve", "url": "https://app.example.com/hitl/page/jti-1"},
        {"action": "return", "url": "https://app.example.com/hitl/page/jti-2"},
        {"action": "reject", "url": "https://app.example.com/hitl/page/jti-3"},
    ]


# ── Protocol 校验 ───────────────────────────────────────────────────────────


def test_provider_implements_improvider_protocol():
    """DingTalkProvider 满足 IMProvider Protocol（runtime_checkable）。"""

    def _ok_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errcode": 0, "task_id": 1})

    provider = _make_provider_with_mock_http(handler=_ok_handler)
    assert isinstance(provider, IMProvider)


def test_provider_name_is_dingtalk():
    """provider.name 必须是 'dingtalk'（PROVIDER_DINGTALK 常量）。"""

    def _ok_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errcode": 0, "task_id": 1})

    provider = _make_provider_with_mock_http(handler=_ok_handler)
    assert provider.name == "dingtalk"
    assert provider.name == PROVIDER_DINGTALK


# ── send_hitl_card 正向 ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_hitl_card_calls_oapi_with_correct_payload():
    """send_hitl_card 调用 OAPI asyncsend_v2 + body 含 agent_id/userid_list/msg。"""
    captured: dict[str, Any] = {}

    def _capture_handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        captured["method"] = request.method
        return httpx.Response(
            200,
            json={"errcode": 0, "errmsg": "ok", "task_id": 1234567},
        )

    provider = _make_provider_with_mock_http(handler=_capture_handler)
    result = await provider.send_hitl_card(
        recipient="dt_user_001",
        flow_title="员工入职流程",
        node_title="HR 审批",
        applicant_name="张三",
        actor_name="李四",
        deadline_at="2026-05-18T10:00:00Z",
        description="入职信息已填写。",
        deeplinks=_standard_deeplinks(),
    )

    # 调用走到 asyncsend_v2
    assert "/topapi/message/corpconversation/asyncsend_v2" in captured["url"]
    assert captured["method"] == "POST"

    # body 字段
    body = captured["body"]
    assert body["agent_id"] == 999000
    assert body["userid_list"] == "dt_user_001"
    assert "msg" in body

    # 返回值结构
    assert "message_id" in result
    assert "raw_response" in result
    assert result["message_id"] == "1234567"


@pytest.mark.asyncio
async def test_send_hitl_card_returns_message_id_from_task_id():
    """返回的 message_id 来自 OAPI 响应的 task_id 字段。"""

    def _ok_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"errcode": 0, "errmsg": "ok", "task_id": 987654321},
        )

    provider = _make_provider_with_mock_http(handler=_ok_handler)
    result = await provider.send_hitl_card(
        recipient="dt_user_001",
        flow_title="F",
        node_title="N",
        applicant_name="A",
        actor_name="B",
        deadline_at="2026-05-18T10:00:00Z",
        description="D",
        deeplinks=[],
    )
    assert result["message_id"] == "987654321"
    assert result["raw_response"]["task_id"] == "987654321"


@pytest.mark.asyncio
async def test_send_hitl_card_action_card_msgtype_correct():
    """body.msg 必须是 ActionCard 结构（msgtype='action_card'）。"""
    captured: dict[str, Any] = {}

    def _capture_handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"errcode": 0, "task_id": 1})

    provider = _make_provider_with_mock_http(handler=_capture_handler)
    await provider.send_hitl_card(
        recipient="u1",
        flow_title="F",
        node_title="N",
        applicant_name="A",
        actor_name="B",
        deadline_at="d",
        description="desc",
        deeplinks=_standard_deeplinks(),
    )
    msg = captured["body"]["msg"]
    assert msg["msgtype"] == "action_card"
    assert msg["action_card"]["btn_orientation"] == "0"
    assert len(msg["action_card"]["btn_json_list"]) == 3


@pytest.mark.asyncio
async def test_send_hitl_card_includes_access_token_in_query_params():
    """access_token 必须传到 OAPI URL 的 query string。"""
    captured: dict[str, Any] = {}

    def _capture_handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"errcode": 0, "task_id": 1})

    provider = _make_provider_with_mock_http(
        handler=_capture_handler,
        sdk_token="fake_access_token_12345",
    )
    await provider.send_hitl_card(
        recipient="u1",
        flow_title="F",
        node_title="N",
        applicant_name="A",
        actor_name="B",
        deadline_at="d",
        description="desc",
        deeplinks=[],
    )
    assert "access_token=fake_access_token_12345" in captured["url"]


@pytest.mark.asyncio
async def test_send_hitl_card_passes_recipient_as_userid_list():
    """recipient 参数被传到 body.userid_list 字段（钉钉字段名）。"""
    captured: dict[str, Any] = {}

    def _capture_handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"errcode": 0, "task_id": 1})

    provider = _make_provider_with_mock_http(handler=_capture_handler)
    await provider.send_hitl_card(
        recipient="manager_zhang_001",
        flow_title="F",
        node_title="N",
        applicant_name="A",
        actor_name="B",
        deadline_at="d",
        description="desc",
        deeplinks=[],
    )
    assert captured["body"]["userid_list"] == "manager_zhang_001"


# ── send_hitl_card 错误路径 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_hitl_card_raises_connection_error_on_oapi_errcode_nonzero():
    """OAPI 返 errcode != 0 应抛 ConnectionError（触发 tenacity 重试）。"""

    def _err_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"errcode": 40078, "errmsg": "access_token expired"},
        )

    provider = _make_provider_with_mock_http(handler=_err_handler)
    with pytest.raises(ConnectionError) as exc_info:
        await provider.send_hitl_card(
            recipient="u1",
            flow_title="F",
            node_title="N",
            applicant_name="A",
            actor_name="B",
            deadline_at="d",
            description="desc",
            deeplinks=[],
        )
    assert "40078" in str(exc_info.value)
    assert "access_token expired" in str(exc_info.value)


@pytest.mark.asyncio
async def test_send_hitl_card_raises_connection_error_on_network_failure():
    """网络层 ConnectError → ConnectionError（触发 tenacity 重试）。"""

    def _net_err_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    provider = _make_provider_with_mock_http(handler=_net_err_handler)
    with pytest.raises(ConnectionError) as exc_info:
        await provider.send_hitl_card(
            recipient="u1",
            flow_title="F",
            node_title="N",
            applicant_name="A",
            actor_name="B",
            deadline_at="d",
            description="desc",
            deeplinks=[],
        )
    assert "网络错" in str(exc_info.value)


@pytest.mark.asyncio
async def test_send_hitl_card_raises_connection_error_on_500():
    """HTTP 500 → ConnectionError（OAPI 临时不可用）。"""

    def _server_err_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="service unavailable")

    provider = _make_provider_with_mock_http(handler=_server_err_handler)
    with pytest.raises(ConnectionError) as exc_info:
        await provider.send_hitl_card(
            recipient="u1",
            flow_title="F",
            node_title="N",
            applicant_name="A",
            actor_name="B",
            deadline_at="d",
            description="desc",
            deeplinks=[],
        )
    assert "503" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_access_token_raises_connection_error_when_sdk_returns_none():
    """SDK get_access_token 返 None（凭据错 / 网络错）→ ConnectionError。"""

    def _never_called(_request: httpx.Request) -> httpx.Response:
        # 不应该走到这里（token 获取失败应在 OAPI 调用前抛）
        return httpx.Response(200, json={"errcode": 0, "task_id": 1})

    provider = _make_provider_with_mock_http(
        handler=_never_called,
        sdk_token=None,  # SDK 返回 None
    )
    with pytest.raises(ConnectionError) as exc_info:
        await provider.send_hitl_card(
            recipient="u1",
            flow_title="F",
            node_title="N",
            applicant_name="A",
            actor_name="B",
            deadline_at="d",
            description="desc",
            deeplinks=[],
        )
    assert "access_token" in str(exc_info.value)


# ── update_card ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_card_raises_not_implemented_with_supplement_hint():
    """update_card 抛 NotImplementedError 且提示用 send_supplement_text。"""

    def _ok_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errcode": 0, "task_id": 1})

    provider = _make_provider_with_mock_http(handler=_ok_handler)
    with pytest.raises(NotImplementedError) as exc_info:
        await provider.update_card(message_id="msg-1", new_content={"foo": "bar"})
    error_msg = str(exc_info.value)
    assert "send_supplement_text" in error_msg
    assert "钉钉" in error_msg or "ActionCard" in error_msg


# ── send_supplement_text ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_supplement_text_uses_text_msgtype():
    """send_supplement_text 应发送 msgtype='text' 工作通知。"""
    captured: dict[str, Any] = {}

    def _capture_handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"errcode": 0, "task_id": 555})

    provider = _make_provider_with_mock_http(handler=_capture_handler)
    await provider.send_supplement_text(
        recipient="dt_user_001",
        text="流程已被 张三 [同意]",
    )

    msg = captured["body"]["msg"]
    assert msg["msgtype"] == "text"
    assert msg["text"]["content"] == "流程已被 张三 [同意]"
    assert captured["body"]["userid_list"] == "dt_user_001"


@pytest.mark.asyncio
async def test_send_supplement_text_raises_connection_error_on_oapi_failure():
    """send_supplement_text OAPI 失败 → ConnectionError。"""

    def _err_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errcode": 60011, "errmsg": "user not found"})

    provider = _make_provider_with_mock_http(handler=_err_handler)
    with pytest.raises(ConnectionError) as exc_info:
        await provider.send_supplement_text(recipient="invalid_user", text="x")
    assert "60011" in str(exc_info.value)


# ── Phase 4.5 stub ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_subscribe_raises_not_implemented():
    """subscribe 抛 NotImplementedError（Phase 4.5 实现）。"""

    def _ok_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errcode": 0, "task_id": 1})

    provider = _make_provider_with_mock_http(handler=_ok_handler)
    with pytest.raises(NotImplementedError) as exc_info:
        await provider.subscribe(on_event=lambda e: None)
    assert "Phase 4.5" in str(exc_info.value)


@pytest.mark.asyncio
async def test_verify_webhook_signature_raises_not_implemented():
    """verify_webhook_signature 抛 NotImplementedError（Phase 4.5 实现）。"""

    def _ok_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errcode": 0, "task_id": 1})

    provider = _make_provider_with_mock_http(handler=_ok_handler)
    with pytest.raises(NotImplementedError) as exc_info:
        await provider.verify_webhook_signature(headers={}, body=b"")
    assert "Phase 4.5" in str(exc_info.value)


# ── 内部 result dataclass ─────────────────────────────────────────────────


def test_dingtalk_send_result_is_frozen():
    """_DingTalkSendResult 是 frozen dataclass（immutability）。"""
    result = _DingTalkSendResult(errcode=0, errmsg="ok", task_id="123")
    with pytest.raises(Exception):  # FrozenInstanceError 继承自 AttributeError
        result.errcode = 99  # type: ignore[misc]


# ── aclose ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aclose_closes_http_client():
    """aclose 关闭 httpx client（可重复调用不抛错）。"""

    def _ok_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errcode": 0, "task_id": 1})

    provider = _make_provider_with_mock_http(handler=_ok_handler)
    # send 一次创建 connections（虽然 mock transport）
    await provider.send_hitl_card(
        recipient="u1",
        flow_title="F",
        node_title="N",
        applicant_name="A",
        actor_name="B",
        deadline_at="d",
        description="desc",
        deeplinks=[],
    )
    # 关闭 — 不应该抛错
    await provider.aclose()
    # 重复关闭也不抛（_http_client 被设为 None）
    await provider.aclose()
