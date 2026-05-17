"""Unit tests — backend/app/agent_builder/notification/providers/wecom.py（Plan 04-07）。

测试覆盖（≥ 10 用例）：

主路径（wechatpy app message）：
1. test_provider_satisfies_im_provider_protocol：runtime_checkable Protocol
2. test_provider_name_is_wecom_constant
3. test_supports_card_update_is_false：企微限制
4. test_send_via_app_message_success：mock wechatpy client → status='ok'
5. test_send_via_app_message_passes_msgtype_markdown
6. test_send_raises_connection_error_on_wechatpy_exception：包装异常
7. test_send_raises_connection_error_on_app_errcode_nonzero：企微 errcode≠0

Fallback 路径（Bot Webhook）：
8. test_send_via_bot_webhook_success：pytest_httpx 200 + errcode=0
9. test_send_via_bot_webhook_raises_on_http_error：httpx 400 → ConnectionError
10. test_send_via_bot_webhook_raises_on_errcode：errcode=400 → ConnectionError

Update / supplement：
11. test_update_card_raises_not_implemented：企微限制
12. test_subscribe_raises_not_implemented：Phase 4.5 预留
13. test_verify_webhook_signature_raises_not_implemented：Phase 4.5 预留
14. test_send_supplement_text_via_app_message：成功路径
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.agent_builder.notification.providers.base import (
    PROVIDER_WECOM,
    IMProvider,
)
from app.agent_builder.notification.providers.wecom import WeComProvider


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def app_provider() -> WeComProvider:
    """主路径 WeComProvider（app message）。"""
    return WeComProvider(
        corp_id="corp123",
        agent_id="1000002",
        secret="secret-xyz",
        use_bot_fallback=False,
    )


@pytest.fixture
def webhook_provider() -> WeComProvider:
    """fallback 路径 WeComProvider（Bot Webhook）。"""
    return WeComProvider(
        corp_id="",
        agent_id="",
        secret="",
        bot_webhook_key="bot-key-abc",
        use_bot_fallback=True,
    )


_DEFAULT_SEND_KWARGS = dict(
    recipient="user_zhangsan",
    flow_title="员工入职流程",
    node_title="HR 审批",
    applicant_name="张三",
    actor_name="李经理",
    deadline_at="2026-05-18T10:00:00Z",
    description="新员工入职审批",
    deeplinks=[
        {"action": "approve", "url": "https://example.com/approve/jwt"},
        {"action": "return", "url": "https://example.com/return/jwt"},
        {"action": "reject", "url": "https://example.com/reject/jwt"},
        {"action": "detail", "url": "https://example.com/detail/jwt"},
    ],
)


# ── 1-3 Protocol + 元数据 ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_provider_satisfies_im_provider_protocol(app_provider: WeComProvider) -> None:
    """WeComProvider 实现 IMProvider Protocol（runtime_checkable 鸭子类型）。"""
    assert isinstance(app_provider, IMProvider)


@pytest.mark.unit
def test_provider_name_is_wecom_constant(app_provider: WeComProvider) -> None:
    """name 属性等于 PROVIDER_WECOM 常量。"""
    assert app_provider.name == PROVIDER_WECOM
    assert app_provider.name == "wecom"


@pytest.mark.unit
def test_supports_card_update_is_false(app_provider: WeComProvider) -> None:
    """企微 markdown 消息不支持 update — supports_card_update 为 False。"""
    assert app_provider.supports_card_update is False


# ── 4-5 主路径 app message 成功 ───────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_via_app_message_success(
    app_provider: WeComProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    """主路径成功：wechatpy client.message.send 返回 errcode=0。"""
    mock_send = MagicMock(return_value={"errcode": 0, "errmsg": "ok", "msgid": "msg-001"})

    # monkeypatch wechatpy WeChatClient
    fake_client = MagicMock()
    fake_client.message.send = mock_send
    monkeypatch.setattr(app_provider, "_get_client", lambda: fake_client)

    result = await app_provider.send_hitl_card(**_DEFAULT_SEND_KWARGS)

    assert result["message_id"] == "msg-001"
    assert result["raw_response"]["errcode"] == 0
    # mock_send 被调用一次，且 msg 字段含 markdown
    mock_send.assert_called_once()
    call_args = mock_send.call_args
    # send(agent_id, user_ids, msg=...)
    assert call_args.kwargs.get("msg") or call_args.args[-1]
    msg = call_args.kwargs.get("msg") or call_args.args[-1]
    assert msg["msgtype"] == "markdown"
    assert "markdown" in msg


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_via_app_message_passes_correct_agent_id_and_recipient(
    app_provider: WeComProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    """主路径调用时 agent_id + user_ids 透传正确。"""
    mock_send = MagicMock(return_value={"errcode": 0, "errmsg": "ok"})
    fake_client = MagicMock()
    fake_client.message.send = mock_send
    monkeypatch.setattr(app_provider, "_get_client", lambda: fake_client)

    await app_provider.send_hitl_card(**_DEFAULT_SEND_KWARGS)

    call_args = mock_send.call_args
    # agent_id 是第一个位置参数（或 kwargs）— wechatpy 要求 int 类型，本 provider
    # 在数字字符串场景下自动转 int
    agent_id = call_args.kwargs.get("agent_id") or call_args.args[0]
    user_ids = call_args.kwargs.get("user_ids") or call_args.args[1]
    assert agent_id == 1000002  # int（wechatpy API 要求）
    assert user_ids == "user_zhangsan"


# ── 6-7 主路径异常处理 ────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_raises_connection_error_on_wechatpy_exception(
    app_provider: WeComProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    """wechatpy WeChatClientException 被包装为 ConnectionError（触发 tenacity 重试）。"""
    from wechatpy.exceptions import WeChatClientException

    def _raise(*args, **kwargs):
        raise WeChatClientException(40001, "invalid credential")

    fake_client = MagicMock()
    fake_client.message.send = _raise
    monkeypatch.setattr(app_provider, "_get_client", lambda: fake_client)

    with pytest.raises(ConnectionError) as exc_info:
        await app_provider.send_hitl_card(**_DEFAULT_SEND_KWARGS)
    # 错误信息包含原始 wechatpy errcode/errmsg 便于排查
    assert "40001" in str(exc_info.value) or "invalid credential" in str(exc_info.value)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_raises_connection_error_on_app_errcode_nonzero(
    app_provider: WeComProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    """企微 API 返回 errcode≠0（业务错误）也抛 ConnectionError。"""
    fake_client = MagicMock()
    fake_client.message.send = MagicMock(
        return_value={"errcode": 60011, "errmsg": "no privilege to access"}
    )
    monkeypatch.setattr(app_provider, "_get_client", lambda: fake_client)

    with pytest.raises(ConnectionError) as exc_info:
        await app_provider.send_hitl_card(**_DEFAULT_SEND_KWARGS)
    assert "60011" in str(exc_info.value) or "no privilege" in str(exc_info.value)


# ── 8-10 Bot Webhook fallback 路径 ────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_via_bot_webhook_success(
    webhook_provider: WeComProvider, httpx_mock
) -> None:
    """fallback 路径成功：httpx_mock 200 + errcode=0。"""
    httpx_mock.add_response(
        url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=bot-key-abc",
        method="POST",
        json={"errcode": 0, "errmsg": "ok"},
    )

    result = await webhook_provider.send_hitl_card(**_DEFAULT_SEND_KWARGS)

    assert result["raw_response"]["errcode"] == 0
    # bot webhook 没有 msgid（企微 webhook 不返回） → message_id 是固定标识
    assert "message_id" in result

    # 验证发出的 body 是 markdown msgtype
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    import json

    body = json.loads(requests[0].content)
    assert body["msgtype"] == "markdown"
    assert "markdown" in body
    assert "[同意]" in body["markdown"]["content"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_via_bot_webhook_raises_on_http_error(
    webhook_provider: WeComProvider, httpx_mock
) -> None:
    """fallback HTTP 4xx/5xx → ConnectionError。"""
    httpx_mock.add_response(
        url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=bot-key-abc",
        method="POST",
        status_code=400,
        text="bad request",
    )

    with pytest.raises(ConnectionError) as exc_info:
        await webhook_provider.send_hitl_card(**_DEFAULT_SEND_KWARGS)
    assert "400" in str(exc_info.value) or "bad request" in str(exc_info.value)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_via_bot_webhook_raises_on_errcode(
    webhook_provider: WeComProvider, httpx_mock
) -> None:
    """fallback HTTP 200 但 errcode≠0 → ConnectionError。"""
    httpx_mock.add_response(
        url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=bot-key-abc",
        method="POST",
        json={"errcode": 93000, "errmsg": "invalid webhook url"},
    )

    with pytest.raises(ConnectionError) as exc_info:
        await webhook_provider.send_hitl_card(**_DEFAULT_SEND_KWARGS)
    assert "93000" in str(exc_info.value) or "invalid webhook" in str(exc_info.value)


# ── 11-13 update_card / Phase 4.5 接口 ────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_card_raises_not_implemented(
    app_provider: WeComProvider,
) -> None:
    """企微 markdown 消息不支持 update → 显式 NotImplementedError。

    调用方应基于 supports_card_update=False 改用 send_supplement_text 兜底。
    """
    with pytest.raises(NotImplementedError) as exc_info:
        await app_provider.update_card(message_id="msg-001", new_content={"key": "v"})
    # 错误信息明确提示走 send_supplement_text
    msg = str(exc_info.value)
    assert "supplement" in msg.lower() or "不支持" in msg or "static" in msg.lower()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subscribe_raises_not_implemented(app_provider: WeComProvider) -> None:
    """Phase 4.5 预留接口默认抛 NotImplementedError。"""
    with pytest.raises(NotImplementedError):
        await app_provider.subscribe(on_event=lambda e: None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_webhook_signature_raises_not_implemented(
    app_provider: WeComProvider,
) -> None:
    """Phase 4.5 预留接口默认抛 NotImplementedError。"""
    with pytest.raises(NotImplementedError):
        await app_provider.verify_webhook_signature(headers={}, body=b"")


# ── 14 send_supplement_text 成功路径 ──────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_supplement_text_via_app_message(
    app_provider: WeComProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    """补发文本（app message 路径）成功。"""
    mock_send = MagicMock(return_value={"errcode": 0, "errmsg": "ok"})
    fake_client = MagicMock()
    fake_client.message.send = mock_send
    monkeypatch.setattr(app_provider, "_get_client", lambda: fake_client)

    await app_provider.send_supplement_text(
        recipient="user_zhangsan", text="流程已被李经理同意"
    )

    mock_send.assert_called_once()
    msg = mock_send.call_args.kwargs.get("msg")
    # 补发文本走 text 消息（最简单）
    assert msg["msgtype"] == "text"
    assert "李经理" in msg["text"]["content"]


# ── 15 fallback 模式下 send_supplement_text ───────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_supplement_text_via_bot_webhook(
    webhook_provider: WeComProvider, httpx_mock
) -> None:
    """fallback 模式下补发文本走 bot webhook（text msgtype）。"""
    httpx_mock.add_response(
        url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=bot-key-abc",
        method="POST",
        json={"errcode": 0, "errmsg": "ok"},
    )

    await webhook_provider.send_supplement_text(
        recipient="ignored-in-webhook-mode", text="流程已处理"
    )

    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    import json

    body = json.loads(requests[0].content)
    assert body["msgtype"] == "text"


# ── 16 配置校验：use_bot_fallback=True 但无 bot_webhook_key 抛 ─────────────────


@pytest.mark.unit
def test_init_raises_when_fallback_enabled_without_bot_key() -> None:
    """use_bot_fallback=True 但 bot_webhook_key 缺失 → ValueError（启动 fast-fail）。"""
    with pytest.raises(ValueError) as exc_info:
        WeComProvider(
            corp_id="",
            agent_id="",
            secret="",
            bot_webhook_key="",
            use_bot_fallback=True,
        )
    assert "bot_webhook_key" in str(exc_info.value)


# ── 17 自动 fallback 选择：app creds 缺失 + bot_webhook_key 存在 → 启用 ────────


@pytest.mark.unit
def test_init_auto_enables_fallback_when_only_bot_key_configured() -> None:
    """app 凭据缺失但 bot_webhook_key 配置 → 自动 use_bot_fallback=True。"""
    provider = WeComProvider(
        corp_id="",
        agent_id="",
        secret="",
        bot_webhook_key="bot-abc",
        use_bot_fallback=False,  # 未显式开启，但应自动启用
    )
    assert provider.use_bot_fallback is True
