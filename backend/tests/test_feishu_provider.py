"""FeishuProvider 单元测试（Plan 04-06 Task 2）。

测试覆盖（≥ 10 用例）：
1. FeishuProvider 满足 IMProvider Protocol（runtime_checkable）
2. send_hitl_card 成功 → 返回 message_id + raw_response
3. send_hitl_card 调用 client.im.v1.message.create 正确 payload (interactive + open_id)
4. send_hitl_card 失败 → 抛 ConnectionError 含 code/msg/log_id
5. send_hitl_card 卡片 content 是 json.dumps 的字符串（不是 dict）
6. update_card 成功 → 不抛错
7. update_card 失败 → 抛 ConnectionError
8. update_card 234016 (24h 外 patch) → log warning 不抛错
9. send_supplement_text msg_type=text + content {"text":...}
10. send_supplement_text 失败 → 仅 log warning 不抛错
11. subscribe / verify_webhook_signature → NotImplementedError
12. 版本不匹配触发 warning
13. client 延迟初始化（property 第一次访问才构造）

策略：monkeypatch `client.im.v1.message.create` / `.patch` 返回 mock response
不打飞书真实 API（CLAUDE.md 单元测试不依赖外部服务）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.agent_builder.notification.providers.base import (
    PROVIDER_FEISHU,
    IMProvider,
)
from app.agent_builder.notification.providers.feishu import (
    _EXPECTED_LARK_VERSION,
    FeishuProvider,
    _resolve_lark_version,
)


# ── Mock Lark Response ────────────────────────────────────────────────────────


@dataclass
class _MockData:
    """Mock CreateMessageResponseBody — 仅 message_id 字段。"""

    message_id: str = "om_mock_message_id_12345"


class _MockLarkResponse:
    """Mock lark BaseResponse — 完整覆盖 success() / code / msg / data / get_log_id()。"""

    def __init__(
        self,
        *,
        code: int = 0,
        msg: str = "success",
        message_id: str = "om_mock_message_id_12345",
        log_id: str | None = "log_mock_67890",
    ) -> None:
        self.code = code
        self.msg = msg
        self.data = _MockData(message_id=message_id) if code == 0 else None
        self._log_id = log_id

    def success(self) -> bool:
        return self.code == 0

    def get_log_id(self) -> str | None:
        return self._log_id


# ── 标准 send_hitl_card 入参 ─────────────────────────────────────────────────


@pytest.fixture
def hitl_card_payload() -> dict:
    return {
        "recipient": "ou_target_user_open_id",
        "flow_title": "员工入职流程",
        "node_title": "HR 审批",
        "applicant_name": "张三",
        "actor_name": "李四",
        "deadline_at": "2026-05-18T18:00:00Z",
        "description": "请确认入职信息无误后审批。",
        "deeplinks": [
            {"action": "approve", "url": "https://app.example.com/hitl/page/jti-A"},
            {"action": "return", "url": "https://app.example.com/hitl/page/jti-R"},
            {"action": "reject", "url": "https://app.example.com/hitl/page/jti-X"},
        ],
    }


@pytest.fixture
def provider() -> FeishuProvider:
    """新构造 FeishuProvider（不实际连接飞书 — client 延迟初始化）。"""
    return FeishuProvider(app_id="cli_test_app_id", app_secret="test_secret")


# ── Protocol 鸭子类型 ────────────────────────────────────────────────────────


def test_feishu_provider_satisfies_im_provider_protocol(provider: FeishuProvider):
    """FeishuProvider 满足 IMProvider Protocol（runtime_checkable）。"""
    assert isinstance(provider, IMProvider)
    assert provider.name == PROVIDER_FEISHU


def test_provider_client_lazy_initialization(provider: FeishuProvider):
    """client 是 @property 延迟初始化 — 构造时未访问。"""
    assert provider._client is None
    # 第一次访问触发构造
    c = provider.client
    assert c is not None
    assert provider._client is c
    # 第二次访问返回同一实例
    assert provider.client is c


# ── SDK 版本校验 ─────────────────────────────────────────────────────────────


def test_resolve_lark_version_returns_installed_version():
    """_resolve_lark_version 返回 importlib.metadata 安装版本。"""
    v = _resolve_lark_version()
    # 测试环境固定安装 1.6.5（CLAUDE.md §3）
    assert v == _EXPECTED_LARK_VERSION


def test_init_warns_when_version_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    """版本不匹配触发 warning（不抛错）。"""
    monkeypatch.setattr(
        "app.agent_builder.notification.providers.feishu._resolve_lark_version",
        lambda: "1.0.0",  # 故意伪造旧版本
    )
    caplog.set_level("WARNING", logger="app.agent_builder.notification.providers.feishu")
    FeishuProvider(app_id="x", app_secret="y")
    # 应有 warning 提示版本不匹配
    assert any("1.0.0" in r.message and "1.6.5" in r.message for r in caplog.records)


def test_init_no_warning_when_version_matches(
    caplog: pytest.LogCaptureFixture,
):
    """版本匹配 1.6.5 → 无 warning。"""
    caplog.set_level("WARNING", logger="app.agent_builder.notification.providers.feishu")
    FeishuProvider(app_id="x", app_secret="y")
    # 1.6.5 与 _EXPECTED 一致 → 不应有任何 warning
    version_warnings = [r for r in caplog.records if "lark-oapi 版本" in r.message]
    assert version_warnings == []


# ── send_hitl_card ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_hitl_card_success_returns_message_id(
    monkeypatch: pytest.MonkeyPatch,
    provider: FeishuProvider,
    hitl_card_payload: dict,
):
    """send_hitl_card 成功 → 返回 message_id + raw_response（含 log_id）。"""
    mock_response = _MockLarkResponse(message_id="om_xyz_123", log_id="log_abc_999")
    monkeypatch.setattr(
        provider.client.im.v1.message, "create", lambda req: mock_response
    )
    result = await provider.send_hitl_card(**hitl_card_payload)

    assert result["message_id"] == "om_xyz_123"
    assert result["raw_response"]["code"] == 0
    assert result["raw_response"]["msg"] == "success"
    assert result["raw_response"]["log_id"] == "log_abc_999"


@pytest.mark.asyncio
async def test_send_hitl_card_calls_create_with_interactive_msg_type(
    monkeypatch: pytest.MonkeyPatch,
    provider: FeishuProvider,
    hitl_card_payload: dict,
):
    """send_hitl_card 应该调 client.im.v1.message.create with msg_type='interactive'。"""
    captured_request: list[Any] = []

    def _capture(req):
        captured_request.append(req)
        return _MockLarkResponse()

    monkeypatch.setattr(provider.client.im.v1.message, "create", _capture)
    await provider.send_hitl_card(**hitl_card_payload)

    assert len(captured_request) == 1
    req = captured_request[0]
    # 检查 receive_id_type
    assert req.receive_id_type == "open_id"
    # 检查 body 含 interactive + receive_id
    body = req.request_body
    assert body.msg_type == "interactive"
    assert body.receive_id == "ou_target_user_open_id"


@pytest.mark.asyncio
async def test_send_hitl_card_content_is_json_string_not_dict(
    monkeypatch: pytest.MonkeyPatch,
    provider: FeishuProvider,
    hitl_card_payload: dict,
):
    """content 必须是 json.dumps 后的字符串（不是 dict）— 飞书 API 要求。"""
    captured_request: list[Any] = []

    def _capture(req):
        captured_request.append(req)
        return _MockLarkResponse()

    monkeypatch.setattr(provider.client.im.v1.message, "create", _capture)
    await provider.send_hitl_card(**hitl_card_payload)

    body = captured_request[0].request_body
    # content 是字符串（不是 dict）
    assert isinstance(body.content, str)
    # 字符串解析回 dict 应该是合法 JSON
    import json as _json
    card = _json.loads(body.content)
    # 卡片字段断言
    assert "config" in card
    assert "header" in card
    assert "elements" in card
    # header 含流程标题
    assert "员工入职流程" in card["header"]["title"]["content"]


@pytest.mark.asyncio
async def test_send_hitl_card_raises_connection_error_on_failure(
    monkeypatch: pytest.MonkeyPatch,
    provider: FeishuProvider,
    hitl_card_payload: dict,
):
    """response.success()=False → 抛 ConnectionError 含 code/msg/log_id（让 tenacity 重试）。"""
    mock_response = _MockLarkResponse(
        code=99991663, msg="飞书内部服务器错误", log_id="log_err_111"
    )
    monkeypatch.setattr(
        provider.client.im.v1.message, "create", lambda req: mock_response
    )

    with pytest.raises(ConnectionError) as exc_info:
        await provider.send_hitl_card(**hitl_card_payload)

    err_text = str(exc_info.value)
    assert "99991663" in err_text
    assert "log_err_111" in err_text
    assert "send_hitl_card" in err_text


@pytest.mark.asyncio
async def test_send_hitl_card_raises_on_token_expired(
    monkeypatch: pytest.MonkeyPatch,
    provider: FeishuProvider,
    hitl_card_payload: dict,
):
    """11201 token 过期 → 同样抛 ConnectionError（im_jobs 用尽重试后写 failed）。"""
    mock_response = _MockLarkResponse(code=11201, msg="token expired")
    monkeypatch.setattr(
        provider.client.im.v1.message, "create", lambda req: mock_response
    )
    with pytest.raises(ConnectionError) as exc_info:
        await provider.send_hitl_card(**hitl_card_payload)
    assert "11201" in str(exc_info.value)


@pytest.mark.asyncio
async def test_send_hitl_card_3_deeplinks_become_3_buttons(
    monkeypatch: pytest.MonkeyPatch,
    provider: FeishuProvider,
    hitl_card_payload: dict,
):
    """3 个 deeplinks 在卡片 action 元素中渲染为 3 个按钮。"""
    captured_request: list[Any] = []

    def _capture(req):
        captured_request.append(req)
        return _MockLarkResponse()

    monkeypatch.setattr(provider.client.im.v1.message, "create", _capture)
    await provider.send_hitl_card(**hitl_card_payload)

    import json as _json
    card = _json.loads(captured_request[0].request_body.content)
    action_block = next(e for e in card["elements"] if e.get("tag") == "action")
    assert len(action_block["actions"]) == 3


# ── update_card ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_card_calls_patch_with_message_id(
    monkeypatch: pytest.MonkeyPatch,
    provider: FeishuProvider,
):
    """update_card 调 client.im.v1.message.patch with 正确 message_id。"""
    captured_request: list[Any] = []

    def _capture(req):
        captured_request.append(req)
        return _MockLarkResponse()

    monkeypatch.setattr(provider.client.im.v1.message, "patch", _capture)
    await provider.update_card(
        message_id="om_target_id",
        new_content={"config": {}, "elements": []},
    )

    assert len(captured_request) == 1
    assert captured_request[0].message_id == "om_target_id"


@pytest.mark.asyncio
async def test_update_card_serializes_content_to_json_string(
    monkeypatch: pytest.MonkeyPatch,
    provider: FeishuProvider,
):
    """update_card body.content 必须是 json.dumps 字符串（飞书 API 要求）。"""
    captured_request: list[Any] = []

    def _capture(req):
        captured_request.append(req)
        return _MockLarkResponse()

    monkeypatch.setattr(provider.client.im.v1.message, "patch", _capture)
    new_card = {
        "config": {"wide_screen_mode": True},
        "header": {"template": "grey"},
        "elements": [{"tag": "note", "elements": []}],
    }
    await provider.update_card(message_id="om_xxx", new_content=new_card)

    body = captured_request[0].request_body
    assert isinstance(body.content, str)
    import json as _json
    assert _json.loads(body.content) == new_card


@pytest.mark.asyncio
async def test_update_card_raises_connection_error_on_failure(
    monkeypatch: pytest.MonkeyPatch,
    provider: FeishuProvider,
):
    """update_card 失败（非 24h 过期）→ 抛 ConnectionError。"""
    mock_response = _MockLarkResponse(code=99991663, msg="internal error")
    monkeypatch.setattr(
        provider.client.im.v1.message, "patch", lambda req: mock_response
    )
    with pytest.raises(ConnectionError) as exc_info:
        await provider.update_card(
            message_id="om_xxx", new_content={"elements": []}
        )
    assert "99991663" in str(exc_info.value)


@pytest.mark.asyncio
async def test_update_card_skips_when_message_expired(
    monkeypatch: pytest.MonkeyPatch,
    provider: FeishuProvider,
    caplog: pytest.LogCaptureFixture,
):
    """code=234016（消息已过期 24h 外 patch）→ log warning 不抛错。"""
    mock_response = _MockLarkResponse(code=234016, msg="message expired")
    monkeypatch.setattr(
        provider.client.im.v1.message, "patch", lambda req: mock_response
    )
    caplog.set_level("WARNING", logger="app.agent_builder.notification.providers.feishu")

    # 不应抛错
    await provider.update_card(
        message_id="om_old", new_content={"elements": []}
    )

    # 应有 warning 含 message_id + 24h 提示
    assert any(
        "om_old" in r.message and ("24h" in r.message or "过期" in r.message)
        for r in caplog.records
    )


# ── send_supplement_text ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_supplement_text_uses_text_msg_type(
    monkeypatch: pytest.MonkeyPatch,
    provider: FeishuProvider,
):
    """send_supplement_text 应该 msg_type='text' + content={"text":...}。"""
    captured_request: list[Any] = []

    def _capture(req):
        captured_request.append(req)
        return _MockLarkResponse()

    monkeypatch.setattr(provider.client.im.v1.message, "create", _capture)
    await provider.send_supplement_text(
        recipient="ou_user_xxx", text="该流程已被张三同意"
    )

    body = captured_request[0].request_body
    assert body.msg_type == "text"
    assert body.receive_id == "ou_user_xxx"

    # content 是 {"text": "..."} 的 JSON 字符串
    import json as _json
    content = _json.loads(body.content)
    assert content == {"text": "该流程已被张三同意"}


@pytest.mark.asyncio
async def test_send_supplement_text_failure_only_warns_no_raise(
    monkeypatch: pytest.MonkeyPatch,
    provider: FeishuProvider,
    caplog: pytest.LogCaptureFixture,
):
    """send_supplement_text 失败仅 log warning（非关键路径，不抛错）。"""
    mock_response = _MockLarkResponse(code=99991663, msg="fail")
    monkeypatch.setattr(
        provider.client.im.v1.message, "create", lambda req: mock_response
    )
    caplog.set_level("WARNING", logger="app.agent_builder.notification.providers.feishu")

    # 不应抛错
    await provider.send_supplement_text(recipient="ou_x", text="hi")

    # 应有 warning
    assert any("send_supplement_text failed" in r.message for r in caplog.records)


# ── Phase 4.5 接口 ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_subscribe_raises_not_implemented(provider: FeishuProvider):
    """subscribe 抛 NotImplementedError（Phase 4.5 实现）。"""
    with pytest.raises(NotImplementedError) as exc_info:
        await provider.subscribe(on_event=lambda e: None)
    assert "Phase 4.5" in str(exc_info.value)
    assert PROVIDER_FEISHU in str(exc_info.value)


@pytest.mark.asyncio
async def test_verify_webhook_signature_raises_not_implemented(provider: FeishuProvider):
    """verify_webhook_signature 抛 NotImplementedError（Phase 4.5 实现）。"""
    with pytest.raises(NotImplementedError) as exc_info:
        await provider.verify_webhook_signature(headers={}, body=b"")
    assert "Phase 4.5" in str(exc_info.value)
    assert PROVIDER_FEISHU in str(exc_info.value)
