"""LegacyIMProviderAdapter 单测（PLUG-FW-04 + IM-LEGACY-WRAP）。

测试覆盖（PLAN.md ≥ 10 + 双轨注册 + 6 家 wrap 全量）：

Task 1 基础测试（10 个 isinstance / supports / send_card / update_card / send_text / subscribe / wrap）：
1. test_adapter_passes_isinstance_im_capability — runtime_checkable Protocol 匹配
2. test_supports_native_buttons_webhook_false — webhook 唯一例外
3. test_supports_native_buttons_feishu_true — 其他 5 家都 True
4. test_supports_threads_always_false — Phase 4 6 家无 thread
5. test_supports_card_update_reads_legacy_field — getattr 字段
6. test_send_card_translates_to_send_hitl_card — 参数映射正确
7. test_send_card_title_split_em_dash — title 拆分 flow_title/node_title
8. test_send_card_title_no_separator_fallback — title 无分隔符 fallback
9. test_update_card_skipped_when_not_supported — supports_card_update=False silently no-op
10. test_update_card_calls_when_supported
11. test_send_text_translates
12. test_subscribe_events_raises_not_implemented — Phase 4.5 业务层处理
13. test_wrap_helper_returns_adapter
14. test_raw_provider_shared_with_adapter — Phase 4 0 regression 关键不变量

Task 2 双轨注册 + 6 家 wrap 测试（追加）：
15. test_register_provider_also_registers_capability
16. test_clear_providers_clears_both_dicts
17. test_all_six_phase4_providers_wrap_correctly
18. test_known_providers_invariant — KNOWN_PROVIDERS 不变

Reference: docs/reading-dify-05a-06-legacy-adapter-2026-05-17.md
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agent_builder.platforms.capabilities.im import (
    IMCapability,
    MessageRef,
    NormalizedCard,
    RecipientSpec,
)
from app.agent_builder.platforms.legacy_im_adapter import (
    LegacyIMProviderAdapter,
    wrap_legacy_provider,
)

# ── Mock Legacy Provider（模拟 Phase 4 IMProvider） ─────────────────────────


class _MockLegacyProvider:
    """模拟 Phase 4 IMProvider — 不依赖具体 Provider 实现（lark_oapi 等）。

    实现 IMProvider Protocol 的所有方法（send_hitl_card / update_card /
    send_supplement_text），用 self.calls list 记录调用历史供断言。
    """

    def __init__(self, name: str, supports_card_update: bool = True) -> None:
        self.name = name
        self.supports_card_update = supports_card_update
        self.calls: list[dict[str, Any]] = []

    async def send_hitl_card(
        self,
        *,
        recipient: str,
        flow_title: str,
        node_title: str,
        applicant_name: str,
        actor_name: str,
        deadline_at: str,
        description: str,
        deeplinks: list[dict[str, str]],
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "method": "send_hitl_card",
                "recipient": recipient,
                "flow_title": flow_title,
                "node_title": node_title,
                "applicant_name": applicant_name,
                "actor_name": actor_name,
                "deadline_at": deadline_at,
                "description": description,
                "deeplinks": deeplinks,
            }
        )
        return {"message_id": f"{self.name}-msg-1", "raw_response": {}}

    async def update_card(
        self, *, message_id: str, new_content: dict[str, Any]
    ) -> None:
        self.calls.append(
            {
                "method": "update_card",
                "message_id": message_id,
                "new_content": new_content,
            }
        )

    async def send_supplement_text(self, *, recipient: str, text: str) -> None:
        self.calls.append(
            {
                "method": "send_supplement_text",
                "recipient": recipient,
                "text": text,
            }
        )


# ── isinstance + cap flags（5 测试）─────────────────────────────────────────


def test_adapter_passes_isinstance_im_capability() -> None:
    """LegacyIMProviderAdapter 必须满足 IMCapability runtime_checkable Protocol。"""
    adapter = LegacyIMProviderAdapter(_MockLegacyProvider("feishu"))
    assert isinstance(adapter, IMCapability)


def test_supports_native_buttons_webhook_false() -> None:
    """webhook 不支持原生卡片（唯一例外）。"""
    adapter = LegacyIMProviderAdapter(_MockLegacyProvider("webhook"))
    assert adapter.supports_native_buttons is False


def test_supports_native_buttons_feishu_true() -> None:
    """feishu / wecom / dingtalk / slack / mattermost 都支持原生卡片。"""
    for name in ["feishu", "wecom", "dingtalk", "slack", "mattermost"]:
        adapter = LegacyIMProviderAdapter(_MockLegacyProvider(name))
        assert adapter.supports_native_buttons is True, f"{name} 应支持原生卡片"


def test_supports_threads_always_false() -> None:
    """Phase 4 6 家都无 thread 支持（CONTEXT.md decision）。"""
    for name in ["feishu", "wecom", "dingtalk", "slack", "mattermost", "webhook"]:
        adapter = LegacyIMProviderAdapter(_MockLegacyProvider(name))
        assert adapter.supports_threads is False, f"{name} 应不支持 thread"


def test_supports_card_update_reads_legacy_field() -> None:
    """supports_card_update 从 legacy 字段读取（getattr 默认 False）。"""
    # 支持
    adapter_true = LegacyIMProviderAdapter(
        _MockLegacyProvider("feishu", supports_card_update=True)
    )
    assert adapter_true.supports_card_update is True

    # 不支持
    adapter_false = LegacyIMProviderAdapter(
        _MockLegacyProvider("wecom", supports_card_update=False)
    )
    assert adapter_false.supports_card_update is False

    # legacy 无该字段 → 默认 False
    class _NoFieldLegacy:
        name = "custom"

        async def send_hitl_card(self, **_: Any) -> dict[str, Any]:
            return {"message_id": "m"}

        async def update_card(self, **_: Any) -> None: ...
        async def send_supplement_text(self, **_: Any) -> None: ...

    adapter_default = LegacyIMProviderAdapter(_NoFieldLegacy())  # type: ignore[arg-type]
    assert adapter_default.supports_card_update is False


# ── send_card 参数映射（4 测试）─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_card_translates_to_send_hitl_card() -> None:
    """send_card(RecipientSpec, NormalizedCard) → legacy.send_hitl_card(str, 多参数) 整体参数映射正确。"""
    legacy = _MockLegacyProvider("feishu")
    adapter = LegacyIMProviderAdapter(legacy)
    msg_ref = await adapter.send_card(
        recipient=RecipientSpec(kind="channel", id="user_123"),
        card=NormalizedCard(
            title="入职流程 — HR 审批",
            body_markdown="待审批",
            actions=[{"action": "approve", "url": "https://x.com/approve"}],
        ),
        idempotency_key="key-1",
    )
    assert msg_ref.plugin_name == "legacy:feishu"
    assert msg_ref.native_id == "feishu-msg-1"
    assert len(legacy.calls) == 1
    call = legacy.calls[0]
    assert call["method"] == "send_hitl_card"
    assert call["recipient"] == "user_123"  # RecipientSpec.id → str
    assert call["deeplinks"] == [{"action": "approve", "url": "https://x.com/approve"}]
    assert call["description"] == "待审批"


@pytest.mark.asyncio
async def test_send_card_title_split_em_dash() -> None:
    """title 含 ' — '（em dash with spaces）→ 拆分为 flow_title + node_title。"""
    legacy = _MockLegacyProvider("slack")
    adapter = LegacyIMProviderAdapter(legacy)
    await adapter.send_card(
        recipient=RecipientSpec(kind="channel", id="C1"),
        card=NormalizedCard(
            title="员工入职流程 — HR 审批",
            body_markdown="body",
            actions=[],
        ),
        idempotency_key="k",
    )
    call = legacy.calls[0]
    assert call["flow_title"] == "员工入职流程"
    assert call["node_title"] == "HR 审批"


@pytest.mark.asyncio
async def test_send_card_title_no_separator_fallback() -> None:
    """title 不含 ' — ' → flow_title=整 title, node_title=""。"""
    legacy = _MockLegacyProvider("dingtalk")
    adapter = LegacyIMProviderAdapter(legacy)
    await adapter.send_card(
        recipient=RecipientSpec(kind="dm_user", id="user_x"),
        card=NormalizedCard(
            title="单标题",
            body_markdown="b",
            actions=[],
        ),
        idempotency_key="k",
    )
    call = legacy.calls[0]
    assert call["flow_title"] == "单标题"
    assert call["node_title"] == ""


@pytest.mark.asyncio
async def test_send_card_empty_legacy_fields() -> None:
    """applicant_name / actor_name / deadline_at 应为空字符串（NormalizedCard 不携带）。"""
    legacy = _MockLegacyProvider("mattermost")
    adapter = LegacyIMProviderAdapter(legacy)
    await adapter.send_card(
        recipient=RecipientSpec(kind="channel", id="C"),
        card=NormalizedCard(title="t", body_markdown="b", actions=[]),
        idempotency_key="k",
    )
    call = legacy.calls[0]
    assert call["applicant_name"] == ""
    assert call["actor_name"] == ""
    assert call["deadline_at"] == ""


# ── update_card（2 测试）───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_card_skipped_when_not_supported() -> None:
    """supports_card_update=False 时 update_card silently no-op（不调底层）。"""
    legacy = _MockLegacyProvider("wecom", supports_card_update=False)
    adapter = LegacyIMProviderAdapter(legacy)
    await adapter.update_card(
        MessageRef(plugin_name="legacy:wecom", native_id="m1"),
        NormalizedCard(title="t", body_markdown="b", actions=[]),
    )
    assert len(legacy.calls) == 0  # silently no-op


@pytest.mark.asyncio
async def test_update_card_calls_when_supported() -> None:
    """supports_card_update=True 时调 legacy.update_card 并传 title + text dict。"""
    legacy = _MockLegacyProvider("feishu", supports_card_update=True)
    adapter = LegacyIMProviderAdapter(legacy)
    await adapter.update_card(
        MessageRef(plugin_name="legacy:feishu", native_id="m1"),
        NormalizedCard(title="新标题", body_markdown="新内容", actions=[]),
    )
    assert len(legacy.calls) == 1
    call = legacy.calls[0]
    assert call["method"] == "update_card"
    assert call["message_id"] == "m1"
    assert call["new_content"] == {"text": "新内容", "title": "新标题"}


# ── send_text（1 测试）────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_text_translates() -> None:
    """send_text(RecipientSpec, str) → legacy.send_supplement_text(str, str)"""
    legacy = _MockLegacyProvider("slack")
    adapter = LegacyIMProviderAdapter(legacy)
    ref = await adapter.send_text(
        RecipientSpec(kind="channel", id="C1234"),
        "已被处理",
    )
    assert ref.plugin_name == "legacy:slack"
    assert ref.native_id == "supplement"
    assert len(legacy.calls) == 1
    call = legacy.calls[0]
    assert call["method"] == "send_supplement_text"
    assert call["recipient"] == "C1234"
    assert call["text"] == "已被处理"


# ── subscribe_events（1 测试）─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_subscribe_events_raises_not_implemented() -> None:
    """subscribe_events raise NotImplementedError（Phase 4.5 业务层处理）。"""
    adapter = LegacyIMProviderAdapter(_MockLegacyProvider("feishu"))
    with pytest.raises(NotImplementedError, match="Phase 4.5"):
        async for _ in adapter.subscribe_events(["message.new"]):
            pass


# ── wrap_legacy_provider helper（1 测试）──────────────────────────────────


def test_wrap_helper_returns_adapter() -> None:
    """wrap_legacy_provider(provider) 返回 LegacyIMProviderAdapter 实例。"""
    legacy = _MockLegacyProvider("dingtalk")
    adapter = wrap_legacy_provider(legacy)
    assert isinstance(adapter, LegacyIMProviderAdapter)
    assert adapter.name == "dingtalk"


# ── 关键不变量：raw provider 共享（1 测试）─────────────────────────────────


def test_raw_provider_shared_with_adapter() -> None:
    """adapter 内部 _legacy 与外部 raw provider 是同一实例（Phase 4 0 regression 关键）。"""
    legacy = _MockLegacyProvider("feishu")
    adapter = LegacyIMProviderAdapter(legacy)
    assert adapter._legacy is legacy  # 同一对象引用
    # 修改 raw provider 状态 → adapter 内部也看到（共享 state）
    legacy.calls.append({"method": "external_call"})
    assert len(adapter._legacy.calls) == 1


# ────────────────────────────────────────────────────────────────────────────
# ── Task 2：双轨注册 + 6 家 wrap + Registry fallback 测试 ────────────────
# ────────────────────────────────────────────────────────────────────────────


def test_register_provider_also_registers_capability() -> None:
    """register_provider 调用后 _PROVIDERS_AS_CAP 也有对应 entry（自动 wrap 副作用）。"""
    from app.agent_builder.notification.providers.base import (
        clear_providers,
        get_capability_for_legacy,
        list_legacy_capabilities,
        register_provider,
    )

    clear_providers()
    register_provider(_MockLegacyProvider("feishu"))

    cap = get_capability_for_legacy("feishu")
    assert cap is not None
    assert isinstance(cap, LegacyIMProviderAdapter)
    assert "feishu" in list_legacy_capabilities()

    clear_providers()


def test_clear_providers_clears_both_dicts() -> None:
    """clear_providers 清空 _PROVIDERS 与 _PROVIDERS_AS_CAP 双 dict。"""
    from app.agent_builder.notification.providers.base import (
        _PROVIDERS,
        _PROVIDERS_AS_CAP,
        clear_providers,
        register_provider,
    )

    clear_providers()
    register_provider(_MockLegacyProvider("feishu"))
    register_provider(_MockLegacyProvider("slack"))

    assert len(_PROVIDERS) == 2
    assert len(_PROVIDERS_AS_CAP) == 2

    clear_providers()
    assert len(_PROVIDERS) == 0
    assert len(_PROVIDERS_AS_CAP) == 0


def test_all_six_phase4_providers_wrap_correctly() -> None:
    """6 家 Phase 4 provider mock 全部能 wrap + isinstance IMCapability。

    覆盖 KNOWN_PROVIDERS 全集：feishu / wecom / dingtalk / slack / mattermost / webhook
    """
    from app.agent_builder.notification.providers.base import (
        clear_providers,
        get_capability_for_legacy,
        register_provider,
    )

    clear_providers()
    names = ["feishu", "wecom", "dingtalk", "slack", "mattermost", "webhook"]
    for n in names:
        register_provider(_MockLegacyProvider(n))

    for n in names:
        cap = get_capability_for_legacy(n)
        assert cap is not None, f"{n} 应已 wrap 到 _PROVIDERS_AS_CAP"
        assert isinstance(
            cap, IMCapability
        ), f"{n} adapter 应满足 IMCapability Protocol"
        assert isinstance(
            cap, LegacyIMProviderAdapter
        ), f"{n} 应为 LegacyIMProviderAdapter"

    clear_providers()


def test_known_providers_invariant() -> None:
    """KNOWN_PROVIDERS frozenset 严格固定 6 家 — 防止后续误改。

    Phase 4 锁定 6 家 IM provider。新增需走完整 plan + 测试。
    """
    from app.agent_builder.notification.providers.base import KNOWN_PROVIDERS

    expected = frozenset(
        {"feishu", "wecom", "dingtalk", "slack", "mattermost", "webhook"}
    )
    assert (
        KNOWN_PROVIDERS == expected
    ), f"KNOWN_PROVIDERS 异常：期望 {expected}，实际 {KNOWN_PROVIDERS}"


def test_wrap_does_not_silently_skip() -> None:
    """wrap 必须真实生效 — 即使 register_provider 接口签名不变，_PROVIDERS_AS_CAP 必有 entry。

    防御性测试：确保 _maybe_wrap_for_capability 真的被调用（不被 ImportError 静默吞）。
    """
    from app.agent_builder.notification.providers.base import (
        _PROVIDERS,
        _PROVIDERS_AS_CAP,
        clear_providers,
        register_provider,
    )

    clear_providers()
    legacy = _MockLegacyProvider("feishu")
    register_provider(legacy)

    # 老 dict 与新 dict 都有 entry
    assert "feishu" in _PROVIDERS
    assert "feishu" in _PROVIDERS_AS_CAP

    # 新 dict 中的 adapter 内部 _legacy 指向同一 raw provider
    assert _PROVIDERS_AS_CAP["feishu"]._legacy is _PROVIDERS["feishu"]
    assert _PROVIDERS_AS_CAP["feishu"]._legacy is legacy

    clear_providers()
