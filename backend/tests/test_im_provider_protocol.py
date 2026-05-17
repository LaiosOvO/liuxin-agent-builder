"""IMProvider Protocol + Registry + MockIMProvider 单元测试（Plan 04-05 Task 1）。

测试覆盖（≥ 8 用例）：
1. test_mock_provider_satisfies_protocol：runtime_checkable isinstance 校验
2. test_register_and_get_provider：注册 + 获取
3. test_get_unknown_provider_raises_keyerror：未注册抛 KeyError
4. test_register_provider_with_invalid_name_raises：不在 KNOWN_PROVIDERS 抛 ValueError
5. test_list_providers_returns_registered_names：列表 + sorted
6. test_clear_providers_for_test_isolation：清空 fixture
7. test_subscribe_raises_not_implemented：Phase 4.5 预留接口
8. test_verify_webhook_signature_raises_not_implemented：Phase 4.5 预留接口
9. test_mock_records_send_hitl_card_call：calls 列表填充
10. test_mock_records_update_card_and_supplement_text：3 method 都记录
11. test_mock_fail_send_hitl_card_raises_connection_error：错误模拟
12. test_mock_fail_count_simulates_intermittent_failure：tenacity 重试场景
13. test_mock_returns_message_id_and_raw_response：返回结构
14. test_known_providers_frozenset_contains_5：5 家常量定义
15. test_card_payload_is_frozen：HitlCardPayload immutable

CLAUDE.md 2.2 单元测试：纯 Python，无 DB / Redis 依赖。
"""
from __future__ import annotations

import pytest

from app.agent_builder.notification.cards.base import CardBuilder, HitlCardPayload
from app.agent_builder.notification.providers.base import (
    KNOWN_PROVIDERS,
    PROVIDER_DINGTALK,
    PROVIDER_FEISHU,
    PROVIDER_MATTERMOST,
    PROVIDER_SLACK,
    PROVIDER_WEBHOOK,
    PROVIDER_WECOM,
    IMProvider,
    clear_providers,
    get_provider,
    list_providers,
    register_provider,
)
from app.agent_builder.notification.providers.mock import (
    MockCallRecord,
    MockIMProvider,
)


# ── Fixture：每个测试隔离 Registry ───────────────────────────────────────────


@pytest.fixture(autouse=True)
def isolate_registry():
    """每个测试前后清空 Registry — 防止注册泄漏到下个测试。"""
    clear_providers()
    yield
    clear_providers()


# ── Protocol 鸭子类型校验 ────────────────────────────────────────────────────


def test_mock_provider_satisfies_protocol():
    """MockIMProvider 满足 IMProvider Protocol（runtime_checkable）。"""
    mock = MockIMProvider(name=PROVIDER_FEISHU)
    assert isinstance(mock, IMProvider)


def test_known_providers_frozenset_contains_6():
    """KNOWN_PROVIDERS 包含 6 家 IM 常量名（Plan 04-09 新增 webhook）。"""
    assert KNOWN_PROVIDERS == frozenset(
        {
            PROVIDER_FEISHU,
            PROVIDER_WECOM,
            PROVIDER_DINGTALK,
            PROVIDER_SLACK,
            PROVIDER_MATTERMOST,
            PROVIDER_WEBHOOK,
        }
    )
    assert len(KNOWN_PROVIDERS) == 6
    # frozenset 不可变（添加抛 AttributeError）
    with pytest.raises(AttributeError):
        KNOWN_PROVIDERS.add("evil")  # type: ignore[attr-defined]


# ── Registry CRUD ────────────────────────────────────────────────────────────


def test_register_and_get_provider():
    """注册 Provider 后可通过 get_provider 取回。"""
    mock = MockIMProvider(name=PROVIDER_FEISHU)
    register_provider(mock)
    got = get_provider(PROVIDER_FEISHU)
    assert got is mock
    assert got.name == PROVIDER_FEISHU


def test_get_unknown_provider_raises_keyerror():
    """未注册的 provider 抛 KeyError + 携带已注册列表。"""
    mock = MockIMProvider(name=PROVIDER_FEISHU)
    register_provider(mock)
    with pytest.raises(KeyError) as exc_info:
        get_provider(PROVIDER_SLACK)
    # 错误信息携带已注册列表（便于排查）
    assert PROVIDER_SLACK in str(exc_info.value)
    assert PROVIDER_FEISHU in str(exc_info.value)


def test_register_provider_with_invalid_name_raises():
    """register_provider 拒绝不在 KNOWN_PROVIDERS 的名字（typo 防护）。"""
    class FakeProvider:
        name = "fake_provider_typo"

        async def send_hitl_card(self, **kwargs):  # pragma: no cover
            pass

        async def update_card(self, **kwargs):  # pragma: no cover
            pass

        async def send_supplement_text(self, **kwargs):  # pragma: no cover
            pass

    with pytest.raises(ValueError) as exc_info:
        register_provider(FakeProvider())  # type: ignore[arg-type]
    assert "fake_provider_typo" in str(exc_info.value)
    assert "KNOWN_PROVIDERS" in str(exc_info.value)


def test_list_providers_returns_registered_names():
    """list_providers 返回已注册 name 列表（sorted 稳定顺序）。"""
    register_provider(MockIMProvider(name=PROVIDER_SLACK))
    register_provider(MockIMProvider(name=PROVIDER_FEISHU))
    register_provider(MockIMProvider(name=PROVIDER_WECOM))
    # sorted 顺序（稳定可预测）
    assert list_providers() == sorted(
        [PROVIDER_FEISHU, PROVIDER_SLACK, PROVIDER_WECOM]
    )


def test_clear_providers_for_test_isolation():
    """clear_providers 清空注册表（测试 fixture 用）。"""
    register_provider(MockIMProvider(name=PROVIDER_FEISHU))
    assert len(list_providers()) == 1
    clear_providers()
    assert list_providers() == []


# ── Phase 4.5 预留接口（默认 NotImplementedError）──────────────────────────


@pytest.mark.asyncio
async def test_subscribe_raises_not_implemented():
    """Phase 4 Mock provider subscribe 默认抛 NotImplementedError + 提示 Phase 4.5。"""
    mock = MockIMProvider(name=PROVIDER_FEISHU)
    with pytest.raises(NotImplementedError) as exc_info:
        await mock.subscribe(on_event=lambda e: None)
    assert "Phase 4.5" in str(exc_info.value)
    assert PROVIDER_FEISHU in str(exc_info.value)


@pytest.mark.asyncio
async def test_verify_webhook_signature_raises_not_implemented():
    """Phase 4 Mock provider verify_webhook_signature 默认抛 NotImplementedError。"""
    mock = MockIMProvider(name=PROVIDER_SLACK)
    with pytest.raises(NotImplementedError) as exc_info:
        await mock.verify_webhook_signature(
            headers={"x-slack-signature": "v0=xxx"},
            body=b"test",
        )
    assert "Phase 4.5" in str(exc_info.value)
    assert PROVIDER_SLACK in str(exc_info.value)


# ── MockIMProvider 行为 ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mock_records_send_hitl_card_call():
    """MockIMProvider.send_hitl_card 记录调用 + 返回 message_id。"""
    mock = MockIMProvider(name=PROVIDER_FEISHU)
    result = await mock.send_hitl_card(
        recipient="ou_test_user_001",
        flow_title="员工入职流程",
        node_title="HR 审批",
        applicant_name="张三",
        actor_name="李四",
        deadline_at="2026-05-18T10:00:00Z",
        description="请审批此员工入职申请",
        deeplinks=[
            {"action": "approve", "url": "https://example.com/hitl/page/jti-1"},
            {"action": "return", "url": "https://example.com/hitl/page/jti-2"},
            {"action": "reject", "url": "https://example.com/hitl/page/jti-3"},
        ],
    )
    # 返回结构
    assert result["message_id"] == "mock-msg-1"
    assert result["raw_response"]["ok"] is True
    assert result["raw_response"]["provider"] == PROVIDER_FEISHU
    # calls 记录
    assert len(mock.calls) == 1
    rec = mock.calls[0]
    assert rec.method == "send_hitl_card"
    assert rec.recipient == "ou_test_user_001"
    assert rec.payload["flow_title"] == "员工入职流程"
    assert rec.payload["actor_name"] == "李四"
    assert len(rec.payload["deeplinks"]) == 3


@pytest.mark.asyncio
async def test_mock_records_update_card_and_supplement_text():
    """MockIMProvider 3 个 method（send/update/supplement）都记录到 calls。"""
    mock = MockIMProvider(name=PROVIDER_SLACK)
    await mock.send_hitl_card(
        recipient="U001",
        flow_title="F",
        node_title="N",
        applicant_name="A",
        actor_name="X",
        deadline_at="2026-01-01",
        description="d",
        deeplinks=[],
    )
    await mock.update_card(
        message_id="mock-msg-1",
        new_content={"text": "已被 X 处理"},
    )
    await mock.send_supplement_text(
        recipient="U002",
        text="流程已被 X 同意",
    )

    assert len(mock.calls) == 3
    assert [c.method for c in mock.calls] == [
        "send_hitl_card",
        "update_card",
        "send_supplement_text",
    ]
    # update_card recipient 空字符串
    assert mock.calls[1].recipient == ""
    assert mock.calls[1].payload["message_id"] == "mock-msg-1"
    assert mock.calls[1].payload["new_content"] == {"text": "已被 X 处理"}
    # supplement_text
    assert mock.calls[2].payload["text"] == "流程已被 X 同意"


@pytest.mark.asyncio
async def test_mock_fail_send_hitl_card_raises_connection_error():
    """fail_send_hitl_card=True 时所有 send_hitl_card 抛 ConnectionError。"""
    mock = MockIMProvider(name=PROVIDER_FEISHU, fail_send_hitl_card=True)
    with pytest.raises(ConnectionError) as exc_info:
        await mock.send_hitl_card(
            recipient="r",
            flow_title="f",
            node_title="n",
            applicant_name="a",
            actor_name="x",
            deadline_at="2026-01-01",
            description="d",
            deeplinks=[],
        )
    assert "simulated network error" in str(exc_info.value)
    assert PROVIDER_FEISHU in str(exc_info.value)


@pytest.mark.asyncio
async def test_mock_fail_count_simulates_intermittent_failure():
    """fail_count=2 → 前 2 次 send_hitl_card 抛错，第 3 次成功（测 tenacity 重试场景）。"""
    mock = MockIMProvider(name=PROVIDER_WECOM, fail_count=2)

    # 第 1 次：抛 ConnectionError
    with pytest.raises(ConnectionError):
        await mock.send_hitl_card(
            recipient="r1",
            flow_title="f",
            node_title="n",
            applicant_name="a",
            actor_name="x",
            deadline_at="2026-01-01",
            description="d",
            deeplinks=[],
        )
    # 第 2 次：抛 ConnectionError
    with pytest.raises(ConnectionError):
        await mock.send_hitl_card(
            recipient="r1",
            flow_title="f",
            node_title="n",
            applicant_name="a",
            actor_name="x",
            deadline_at="2026-01-01",
            description="d",
            deeplinks=[],
        )
    # 第 3 次：成功
    result = await mock.send_hitl_card(
        recipient="r1",
        flow_title="f",
        node_title="n",
        applicant_name="a",
        actor_name="x",
        deadline_at="2026-01-01",
        description="d",
        deeplinks=[],
    )
    assert result["message_id"] == "mock-msg-1"  # 仅 1 次成功 = calls 列表只 1 条
    assert len(mock.calls) == 1


def test_mock_call_record_is_frozen():
    """MockCallRecord 是 frozen dataclass — 不可修改。"""
    rec = MockCallRecord(method="send_hitl_card", recipient="r", payload={"k": "v"})
    with pytest.raises(Exception):  # FrozenInstanceError
        rec.method = "evil"  # type: ignore[misc]


def test_mock_reset_clears_calls_and_attempts():
    """MockIMProvider.reset 清空 calls + send_attempts。"""
    mock = MockIMProvider(name=PROVIDER_FEISHU, fail_count=1)
    mock._send_attempts = 5
    mock.calls.append(
        MockCallRecord(method="send_hitl_card", recipient="r", payload={})
    )
    mock.reset()
    assert mock.calls == []
    assert mock._send_attempts == 0


# ── HitlCardPayload immutability ────────────────────────────────────────────


def test_hitl_card_payload_is_frozen():
    """HitlCardPayload 是 frozen dataclass — 不可修改。"""
    payload = HitlCardPayload(
        flow_title="F",
        node_title="N",
        applicant_name="A",
        actor_name="X",
        deadline_at="2026-01-01",
        description="d",
        deeplinks=(),
    )
    with pytest.raises(Exception):  # FrozenInstanceError
        payload.flow_title = "evil"  # type: ignore[misc]


def test_hitl_card_payload_default_deeplinks_is_empty_tuple():
    """HitlCardPayload deeplinks 默认空 tuple（不可变）。"""
    payload = HitlCardPayload(
        flow_title="F",
        node_title="N",
        applicant_name="A",
        actor_name="X",
        deadline_at="2026-01-01",
        description="d",
    )
    assert payload.deeplinks == ()
    assert isinstance(payload.deeplinks, tuple)


def test_card_builder_protocol_is_runtime_checkable_optional():
    """CardBuilder 是 Protocol — Mock 实现可注入。"""
    class FakeCardBuilder:
        provider_name = "fake"

        def build_hitl_card(self, payload):
            return {"fake": True}

        def build_supplement_text(self, *, who_processed, action):
            return f"已被 {who_processed} {action}"

    builder: CardBuilder = FakeCardBuilder()  # type: ignore[assignment]
    payload = HitlCardPayload(
        flow_title="F",
        node_title="N",
        applicant_name="A",
        actor_name="X",
        deadline_at="2026-01-01",
        description="d",
    )
    card = builder.build_hitl_card(payload)
    assert card == {"fake": True}
    text = builder.build_supplement_text(who_processed="李四", action="同意")
    assert "李四" in text
    assert "同意" in text
