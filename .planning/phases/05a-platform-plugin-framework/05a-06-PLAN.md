---
phase: 05a-platform-plugin-framework
plan: 06
type: execute
wave: 4
depends_on: ["04"]
files_modified:
  - docs/reading-dify-05a-06-legacy-adapter-2026-05-17.md
  - backend/app/agent_builder/platforms/legacy_im_adapter.py
  - backend/app/agent_builder/notification/providers/base.py
  - tests/platforms/test_legacy_im_adapter.py
autonomous: true
requirements:
  - PLUG-FW-04
  - IM-LEGACY-WRAP
must_haves:
  truths:
    - "register_provider() 调用后，老 IMProvider 自动在 _PROVIDERS_AS_CAP dict 中以 LegacyIMProviderAdapter 包装存在"
    - "新代码通过 get_capability(IMCapability, prefer='feishu') 调老 Phase 4 provider，参数自动从 RecipientSpec/NormalizedCard 转旧 str/dict"
    - "Phase 4 81 IM 测试套 + e2e_v2 26 specs 0 regression"
  artifacts:
    - path: "backend/app/agent_builder/platforms/legacy_im_adapter.py"
      provides: "LegacyIMProviderAdapter — Phase 4 IMProvider → IMCapability 适配层"
      exports: ["LegacyIMProviderAdapter", "wrap_legacy_provider"]
      min_lines: 100
    - path: "backend/app/agent_builder/notification/providers/base.py"
      provides: "register_provider() 增强：自动 wrap 并存入 _PROVIDERS_AS_CAP（不破坏老 dict）"
      contains: "_PROVIDERS_AS_CAP"
  key_links:
    - from: "backend/app/agent_builder/notification/providers/base.py"
      to: "backend/app/agent_builder/platforms/legacy_im_adapter.py"
      via: "register_provider 调用 wrap_legacy_provider(provider) → 存入新 dict"
      pattern: "wrap_legacy_provider"
    - from: "backend/app/agent_builder/platforms/registry.py"
      to: "_PROVIDERS_AS_CAP"
      via: "get_capability(IMCapability) fallback：找不到 manifest plugin 时查 _PROVIDERS_AS_CAP"
      pattern: "_PROVIDERS_AS_CAP"
---

<objective>
实现 LegacyIMProviderAdapter — 让 Phase 4 6 家 IMProvider（feishu / wecom / dingtalk / slack / mattermost / webhook）通过新 IMCapability 接口被调用，**Phase 4 既有测试 0 regression**。

Purpose: 用户硬性 DoD #3 — "LegacyIMProviderAdapter 让 Phase 4 6 家 IMProvider 通过新 IMCapability 接口被调用，Phase 4 测试零 regression"。这是用户最敏感的兼容承诺。
Output: LegacyIMProviderAdapter + base.py 增强（_PROVIDERS_AS_CAP）+ 测试覆盖 Phase 4 6 家 + Registry fallback。
</objective>

<execution_context>
@/Users/admin/.claude/get-shit-done/workflows/execute-plan.md
@/Users/admin/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/05a-platform-plugin-framework/05a-CONTEXT.md
@.planning/phases/05a-platform-plugin-framework/05a-RESEARCH.md
@docs/plans/2026-05-17-platform-plugin-framework-ADR.md
@backend/app/agent_builder/notification/providers/base.py
@backend/app/agent_builder/platforms/capabilities/im.py
@backend/app/agent_builder/platforms/registry.py

<interfaces>
From Phase 4 backend/app/agent_builder/notification/providers/base.py:
```python
@runtime_checkable
class IMProvider(Protocol):
    name: str
    async def send_hitl_card(self, *, recipient: str, flow_title: str, node_title: str,
                              applicant_name: str, actor_name: str, deadline_at: str,
                              description: str, deeplinks: list[dict[str, str]]) -> dict[str, Any]: ...
    async def update_card(self, *, message_id: str, new_content: dict[str, Any]) -> None: ...
    async def send_supplement_text(self, *, recipient: str, text: str) -> None: ...

def register_provider(provider: IMProvider) -> None: ...
def get_provider(name: str) -> IMProvider: ...
```

From plan 02 IMCapability:
```python
@runtime_checkable
class IMCapability(Protocol):
    name: str
    supports_native_buttons: bool
    supports_card_update: bool
    supports_threads: bool
    async def send_card(*, recipient: RecipientSpec, card: NormalizedCard, idempotency_key: str) -> MessageRef: ...
    async def update_card(msg_ref: MessageRef, card: NormalizedCard) -> None: ...
    async def send_text(recipient: RecipientSpec, text: str) -> MessageRef: ...
    async def subscribe_events(event_types: list[str]) -> AsyncIterator[...]: ...
```

**关键 mapping**：
- recipient: str → RecipientSpec(kind="channel", id=str)
- send_hitl_card 多参数 → NormalizedCard(title=flow_title+node_title, body_markdown=description, actions=deeplinks)
- 返回 dict[str, Any] → MessageRef(plugin_name="legacy:feishu", native_id=msg_id)
- update_card msg_ref: MessageRef → message_id: str
- send_text → send_supplement_text
- subscribe_events → 留空 / NotImplementedError（Phase 4.5 业务层处理）
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 0: Dify legacy / migration 阅读文档（CLAUDE.md §2.7 硬性 gate）</name>
  <files>docs/reading-dify-05a-06-legacy-adapter-2026-05-17.md</files>
  <action>
读 Dify 与 legacy migration 相关源文件：
1. `/Users/admin/ai/ref/dify/repo/api/services/plugin/data_migration.py` — Dify 怎么把老 model provider 数据迁到新 plugin 模式
2. `/Users/admin/ai/ref/dify/repo/api/services/plugin/plugin_migration.py` — plugin migration 整体流程
3. `/Users/admin/ai/ref/dify/repo/api/services/plugin/plugin_auto_upgrade_service.py` — auto upgrade 思路（虽然 5.A 不做）

写到 `docs/reading-dify-05a-06-legacy-adapter-2026-05-17.md`。

**5 借鉴点**：
1. Dify data_migration 双轨并存模式 → 5.A 双 dict (_PROVIDERS + _PROVIDERS_AS_CAP) 共存思路
2. Dify migration 是 schema 重写 + 数据搬迁；5.A 是 in-memory adapter wrap（更轻量，因为我们还没把 Phase 4 provider 数据持久化到新表）
3. 老接口保留 + 新接口并存策略 → 5.A get_provider() / get_capability() 双路径
4. 自动 wrap 不强制迁移 → 用户决策："Phase 4 6 家 IMProvider 永不强制迁移"
5. 老 IMProvider 部分字段（如 supports_threads）默认 false → adapter 设默认值

License attribution；不拷源代码；≥ 50 行。
  </action>
  <verify>
    <automated>test -f docs/reading-dify-05a-06-legacy-adapter-2026-05-17.md && wc -l docs/reading-dify-05a-06-legacy-adapter-2026-05-17.md | awk '{exit ($1 >= 50 ? 0 : 1)}' && grep -q "AGPL\|attribution" docs/reading-dify-05a-06-legacy-adapter-2026-05-17.md</automated>
  </verify>
  <done>Reading doc ≥ 50 行 + 5 借鉴点 + License attribution + commit 在前</done>
</task>

<task type="auto">
  <name>Task 1: LegacyIMProviderAdapter 实现 + 单测</name>
  <files>backend/app/agent_builder/platforms/legacy_im_adapter.py,tests/platforms/test_legacy_im_adapter.py</files>
  <action>
1. **`backend/app/agent_builder/platforms/legacy_im_adapter.py`** 按 RESEARCH.md Example 2 + ADR-001 §8 完整实现：

```python
"""LegacyIMProviderAdapter — Phase 4 IMProvider → IMCapability 适配层。

用户硬性 DoD #3：让 Phase 4 6 家 IMProvider（feishu / wecom / dingtalk / slack /
mattermost / webhook）通过新 IMCapability 接口被调用，所有 Phase 4 测试 0 regression。

设计要点（ADR-001 §8 + CONTEXT.md decision）：
- IMProvider.send_hitl_card(recipient: str, ...) → IMCapability.send_card(recipient: RecipientSpec, card: NormalizedCard, idempotency_key)
- IMProvider.update_card(message_id: str, new_content: dict) → IMCapability.update_card(msg_ref: MessageRef, card: NormalizedCard)
- IMProvider.send_supplement_text(recipient: str, text: str) → IMCapability.send_text(recipient: RecipientSpec, text: str)
- subscribe_events 留空（Phase 4.5 业务层处理）
- supports_threads = False（Phase 4 6 家无 thread 支持）
- supports_card_update 沿用 legacy provider 字段
- supports_native_buttons 默认 True（Phase 4 6 家除 webhook 外都支持原生卡片）
"""
from __future__ import annotations

from typing import Any

from app.agent_builder.notification.providers.base import IMProvider

from .capabilities.im import IMCapability, MessageRef, NormalizedCard, RecipientSpec


class LegacyIMProviderAdapter:
    """把 Phase 4 IMProvider 包装为 IMCapability。

    Phase 4 既有调用方仍走 get_provider(name) → 老接口，0 改动。
    新代码可走 PlatformPluginRegistry.get_capability(IMCapability, prefer=name)
    → 拿到本 adapter，参数自动转换。
    """

    def __init__(self, legacy: IMProvider):
        self._legacy = legacy

    @property
    def name(self) -> str:
        return self._legacy.name

    @property
    def supports_native_buttons(self) -> bool:
        # webhook 不支持原生卡片，其他 5 家都支持
        return self._legacy.name != "webhook"

    @property
    def supports_card_update(self) -> bool:
        return getattr(self._legacy, "supports_card_update", False)

    @property
    def supports_threads(self) -> bool:
        # Phase 4 6 家都无 thread 支持
        return False

    async def send_card(
        self,
        *,
        recipient: RecipientSpec,
        card: NormalizedCard,
        idempotency_key: str,
    ) -> MessageRef:
        """RecipientSpec → str + NormalizedCard → 多参数 → legacy.send_hitl_card"""
        # Phase 4 recipient 都是 str（channel_user_id / open_id / userid 等）
        legacy_recipient = recipient.id

        # NormalizedCard.actions → deeplinks
        deeplinks = [
            {"action": a.get("action", ""), "url": a.get("url", "")}
            for a in card.actions
        ]

        # NormalizedCard.title → flow_title + node_title 合并
        # （legacy 接口分两字段 — 我们 normalize 为单 title；用 "—" 拆分还原近似语义）
        title_parts = card.title.split(" — ", 1)
        flow_title = title_parts[0] if title_parts else card.title
        node_title = title_parts[1] if len(title_parts) > 1 else ""

        # 其他 legacy 字段无法从 NormalizedCard 恢复 → 用 extras 或空字符串
        result = await self._legacy.send_hitl_card(
            recipient=legacy_recipient,
            flow_title=flow_title,
            node_title=node_title,
            applicant_name="",      # NormalizedCard 不携带 — 调用方应在 body_markdown 含
            actor_name="",
            deadline_at="",
            description=card.body_markdown,
            deeplinks=deeplinks,
        )

        return MessageRef(
            plugin_name=f"legacy:{self._legacy.name}",
            native_id=str(result.get("message_id", "")),
            extras={"raw_keys": ",".join(sorted(result.keys()))},
        )

    async def update_card(
        self,
        msg_ref: MessageRef,
        card: NormalizedCard,
    ) -> None:
        """MessageRef → message_id + NormalizedCard → new_content dict"""
        if not self.supports_card_update:
            # 兼容旧行为：不支持时静默 noop（legacy NotificationService 有 fallback）
            return
        await self._legacy.update_card(
            message_id=msg_ref.native_id,
            new_content={"text": card.body_markdown, "title": card.title},
        )

    async def send_text(
        self,
        recipient: RecipientSpec,
        text: str,
    ) -> MessageRef:
        """RecipientSpec → str → legacy.send_supplement_text"""
        await self._legacy.send_supplement_text(
            recipient=recipient.id,
            text=text,
        )
        return MessageRef(
            plugin_name=f"legacy:{self._legacy.name}",
            native_id="supplement",  # legacy 不返回 message_id
        )

    async def subscribe_events(self, event_types: list[str]):
        """Phase 4.5 业务层处理 — 5.A LegacyAdapter 不实现。"""
        raise NotImplementedError(
            f"legacy:{self._legacy.name} subscribe_events — 由 Phase 4.5 业务层处理"
        )
        if False:
            yield {}


def wrap_legacy_provider(provider: IMProvider) -> LegacyIMProviderAdapter:
    """Helper — base.py register_provider 调它自动 wrap。"""
    return LegacyIMProviderAdapter(provider)
```

≥ 100 行。

2. **`tests/platforms/test_legacy_im_adapter.py`** ≥ 8 测试：

```python
"""LegacyIMProviderAdapter 单测 — 验证 Phase 4 6 家 provider 全 mock pass。"""
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


class _MockLegacyProvider:
    """模拟 Phase 4 IMProvider（不依赖具体 Provider 实现）。"""
    def __init__(self, name: str, supports_card_update: bool = True):
        self.name = name
        self.supports_card_update = supports_card_update
        self.calls: list[dict[str, Any]] = []

    async def send_hitl_card(self, *, recipient, flow_title, node_title, applicant_name, actor_name, deadline_at, description, deeplinks):
        self.calls.append({"method": "send_hitl_card", "recipient": recipient, "deeplinks": deeplinks, "description": description})
        return {"message_id": f"{self.name}-msg-1", "raw_response": {}}

    async def update_card(self, *, message_id, new_content):
        self.calls.append({"method": "update_card", "message_id": message_id, "new_content": new_content})

    async def send_supplement_text(self, *, recipient, text):
        self.calls.append({"method": "send_supplement_text", "recipient": recipient, "text": text})


def test_adapter_passes_isinstance_im_capability():
    """LegacyIMProviderAdapter 必须满足 IMCapability runtime_checkable。"""
    adapter = LegacyIMProviderAdapter(_MockLegacyProvider("feishu"))
    assert isinstance(adapter, IMCapability)


def test_supports_native_buttons_webhook_false():
    """webhook 不支持原生卡片。"""
    adapter = LegacyIMProviderAdapter(_MockLegacyProvider("webhook"))
    assert adapter.supports_native_buttons is False


def test_supports_native_buttons_feishu_true():
    adapter = LegacyIMProviderAdapter(_MockLegacyProvider("feishu"))
    assert adapter.supports_native_buttons is True


def test_supports_threads_always_false():
    """Phase 4 6 家都无 thread 支持。"""
    for name in ["feishu", "wecom", "dingtalk", "slack", "mattermost", "webhook"]:
        adapter = LegacyIMProviderAdapter(_MockLegacyProvider(name))
        assert adapter.supports_threads is False, name


@pytest.mark.asyncio
async def test_send_card_translates_to_send_hitl_card():
    """send_card(RecipientSpec, NormalizedCard) → legacy.send_hitl_card(str, 多参数)"""
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
    assert call["recipient"] == "user_123"  # str 转换
    assert call["deeplinks"] == [{"action": "approve", "url": "https://x.com/approve"}]
    assert call["description"] == "待审批"


@pytest.mark.asyncio
async def test_update_card_skipped_when_not_supported():
    """supports_card_update=False 时 update_card 静默 noop。"""
    legacy = _MockLegacyProvider("wecom", supports_card_update=False)
    adapter = LegacyIMProviderAdapter(legacy)
    await adapter.update_card(
        MessageRef(plugin_name="legacy:wecom", native_id="m1"),
        NormalizedCard(title="t", body_markdown="b", actions=[]),
    )
    assert len(legacy.calls) == 0  # 不调底层


@pytest.mark.asyncio
async def test_update_card_calls_when_supported():
    legacy = _MockLegacyProvider("feishu", supports_card_update=True)
    adapter = LegacyIMProviderAdapter(legacy)
    await adapter.update_card(
        MessageRef(plugin_name="legacy:feishu", native_id="m1"),
        NormalizedCard(title="t", body_markdown="b", actions=[]),
    )
    assert len(legacy.calls) == 1
    assert legacy.calls[0]["method"] == "update_card"


@pytest.mark.asyncio
async def test_send_text_translates():
    legacy = _MockLegacyProvider("slack")
    adapter = LegacyIMProviderAdapter(legacy)
    ref = await adapter.send_text(RecipientSpec(kind="channel", id="C1234"), "hello")
    assert ref.plugin_name == "legacy:slack"
    assert legacy.calls[0]["method"] == "send_supplement_text"
    assert legacy.calls[0]["recipient"] == "C1234"
    assert legacy.calls[0]["text"] == "hello"


@pytest.mark.asyncio
async def test_subscribe_events_raises_not_implemented():
    adapter = LegacyIMProviderAdapter(_MockLegacyProvider("feishu"))
    with pytest.raises(NotImplementedError, match="Phase 4.5"):
        async for _ in adapter.subscribe_events(["message.new"]):
            pass


def test_wrap_helper_returns_adapter():
    legacy = _MockLegacyProvider("dingtalk")
    adapter = wrap_legacy_provider(legacy)
    assert isinstance(adapter, LegacyIMProviderAdapter)
    assert adapter.name == "dingtalk"
```
  </action>
  <verify>
    <automated>cd backend && python -c "from app.agent_builder.platforms.legacy_im_adapter import LegacyIMProviderAdapter, wrap_legacy_provider; print('OK')" && pytest tests/platforms/test_legacy_im_adapter.py -v -x 2>&1 | tail -25 && wc -l backend/app/agent_builder/platforms/legacy_im_adapter.py | awk '{exit ($1 >= 100 ? 0 : 1)}'</automated>
  </verify>
  <done>LegacyIMProviderAdapter 可 import；10 单测 pass；isinstance(adapter, IMCapability) True；Phase 4 6 家 mock 全转换正确</done>
</task>

<task type="auto">
  <name>Task 2: base.py 增强 — register_provider 自动 wrap + _PROVIDERS_AS_CAP + Phase 4 regression 验证</name>
  <files>backend/app/agent_builder/notification/providers/base.py,tests/platforms/test_legacy_im_adapter.py</files>
  <action>
1. **`backend/app/agent_builder/notification/providers/base.py`** — 用 Edit tool，**只追加**新代码，**绝不修改**已有 Protocol / `register_provider` / `get_provider` / `_PROVIDERS` 签名或行为：

在文件末尾追加：

```python


# ── Phase 5.A 增强：双轨 Registry（_PROVIDERS_AS_CAP）─────────────────────────
# 用户硬性 DoD #3：register_provider 自动 wrap 为 LegacyIMProviderAdapter
# 存入 _PROVIDERS_AS_CAP，让 PlatformPluginRegistry.get_capability(IMCapability,
# prefer=name) fallback 拿到 IMCapability 接口实现，**0 改动老代码**。

_PROVIDERS_AS_CAP: dict[str, "LegacyIMProviderAdapter"] = {}  # noqa: F821 (forward ref)


def _maybe_wrap_for_capability(provider: "IMProvider") -> None:
    """register_provider 时自动 wrap 一份为 IMCapability，存入双轨 dict。"""
    try:
        from app.agent_builder.platforms.legacy_im_adapter import (
            LegacyIMProviderAdapter,
        )
    except ImportError:
        # 测试隔离场景下（platforms 模块未加载）允许失败 — 老路径仍工作
        return
    _PROVIDERS_AS_CAP[provider.name] = LegacyIMProviderAdapter(provider)


# 修改 register_provider 在末尾调 _maybe_wrap_for_capability — 见下方 monkey-patch 注释
```

但**注意**：上面的"末尾追加"会导致 register_provider 不调用 _maybe_wrap_for_capability。**真正的实现**：用 Edit tool 修改 register_provider 函数体，在 `_PROVIDERS[provider.name] = provider` **后**追加一行 `_maybe_wrap_for_capability(provider)`。

完整 register_provider 改造后大致：

```python
def register_provider(provider: IMProvider) -> None:
    """注册 Provider（FastAPI lifespan startup 时调用）。
    
    Phase 5.A 增强：自动 wrap 为 LegacyIMProviderAdapter 并存入 _PROVIDERS_AS_CAP，
    使新代码可通过 PlatformPluginRegistry.get_capability(IMCapability) 调用。
    """
    if provider.name not in KNOWN_PROVIDERS:
        raise ValueError(
            f"unknown provider name '{provider.name}'；"
            f"必须是 KNOWN_PROVIDERS 之一: {sorted(KNOWN_PROVIDERS)}"
        )
    _PROVIDERS[provider.name] = provider
    _maybe_wrap_for_capability(provider)
```

新增 helper 函数 `get_capability_for_legacy(name: str) -> LegacyIMProviderAdapter | None`：

```python
def get_capability_for_legacy(name: str) -> "LegacyIMProviderAdapter | None":
    """新代码用 — 拿老 provider 的 IMCapability 接口实现。"""
    return _PROVIDERS_AS_CAP.get(name)


def list_legacy_capabilities() -> list[str]:
    return sorted(_PROVIDERS_AS_CAP.keys())
```

clear_providers 也需追加 `_PROVIDERS_AS_CAP.clear()`：

```python
def clear_providers() -> None:
    """清空 Provider 注册表 — 测试 fixture 用。"""
    _PROVIDERS.clear()
    _PROVIDERS_AS_CAP.clear()
```

**风险控制**：
- `_maybe_wrap_for_capability` 用 try/except ImportError 包住 import — 测试隔离时若 platforms 模块未加载不报错（fallback：仅老路径）
- register_provider 签名不变，IMProvider Protocol 不变，老调用 0 改动
- KNOWN_PROVIDERS frozenset 不变

2. **追加测试到 `tests/platforms/test_legacy_im_adapter.py`**（用 Edit append）：

```python


# ── Phase 4 regression + 双轨注册测试 ────────────────────────────────────────


def test_register_provider_also_registers_capability():
    """register_provider 调用后 _PROVIDERS_AS_CAP 也有对应 entry。"""
    from app.agent_builder.notification.providers.base import (
        clear_providers,
        get_capability_for_legacy,
        register_provider,
        list_legacy_capabilities,
    )
    clear_providers()
    register_provider(_MockLegacyProvider("feishu"))
    cap = get_capability_for_legacy("feishu")
    assert cap is not None
    assert isinstance(cap, LegacyIMProviderAdapter)
    assert "feishu" in list_legacy_capabilities()
    clear_providers()


def test_clear_providers_clears_both_dicts():
    from app.agent_builder.notification.providers.base import (
        _PROVIDERS,
        _PROVIDERS_AS_CAP,
        clear_providers,
        register_provider,
    )
    clear_providers()
    register_provider(_MockLegacyProvider("feishu"))
    register_provider(_MockLegacyProvider("slack"))
    assert len(_PROVIDERS) == 2 and len(_PROVIDERS_AS_CAP) == 2
    clear_providers()
    assert len(_PROVIDERS) == 0 and len(_PROVIDERS_AS_CAP) == 0


def test_all_six_phase4_providers_wrap_correctly():
    """6 家 Phase 4 provider mock 全部能 wrap + isinstance IMCapability。"""
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
        assert cap is not None, n
        assert isinstance(cap, IMCapability), n
    clear_providers()
```

3. **关键 regression 验证**：在 plan execute 时 verify 阶段必跑 Phase 4 既有测试套 0 regression：

```bash
cd backend && pytest tests/test_im_provider_*.py tests/test_notification_*.py -v --tb=short
```

预期：所有既有测试 PASS（数字应与 STATE.md 记录的 81 一致或更多）。
  </action>
  <verify>
    <automated>cd backend && pytest tests/platforms/test_legacy_im_adapter.py -v -x 2>&1 | tail -20 && pytest tests/test_im_provider_*.py -v -x 2>&1 | tail -10 && python -c "from app.agent_builder.notification.providers.base import _PROVIDERS_AS_CAP, get_capability_for_legacy, list_legacy_capabilities; print('dual registry exists')"</automated>
  </verify>
  <done>Phase 4 既有 IM 测试 0 regression；新增 3 测试 pass（_PROVIDERS_AS_CAP 双轨注册）；register_provider 行为兼容 + 增加 wrap 副作用；clear_providers 双 dict 都清空</done>
</task>

</tasks>

<verification>
- [ ] Reading doc commit 在前
- [ ] `pytest tests/platforms/test_legacy_im_adapter.py -v` 13+ tests pass
- [ ] `pytest tests/test_im_provider_*.py -v` Phase 4 既有测试**全部 PASS**（数字 ≥ 81）
- [ ] `pytest tests/test_notification_*.py -v` 0 regression
- [ ] `python -c "from app.agent_builder.notification.providers.base import IMProvider, register_provider"` 老 API 不变
- [ ] black + ruff 通过
</verification>

<success_criteria>
- LegacyIMProviderAdapter 实现 IMCapability Protocol 100%（runtime_checkable + 4 method + 3 cap flag）
- base.py 双轨 Registry（_PROVIDERS + _PROVIDERS_AS_CAP）共存
- Phase 4 81 IM 测试 0 regression — 用户硬性 DoD #3
- 6 家 Phase 4 provider 模拟 wrap 全 isinstance IMCapability
- KNOWN_PROVIDERS 不变；老调用 API 不变；新代码可走 `get_capability_for_legacy(name)` 拿 IMCapability
</success_criteria>

<output>
完成后创建 `.planning/phases/05a-platform-plugin-framework/05a-06-SUMMARY.md`，含：
- Reading doc 链接 + commit hash
- LegacyAdapter 13 单测输出
- **Phase 4 regression 报告**：pytest tests/test_im_provider_*.py 完整数字（pass / fail / skip）— 必须 0 fail
- **Dify 参考点** 小节
- 给 plan 07 的对接点：HulyPlugin 启动后 Registry 中既有 huly (manifest plugin) 又有 6 家 legacy adapter，capability_routing 验证
</output>
