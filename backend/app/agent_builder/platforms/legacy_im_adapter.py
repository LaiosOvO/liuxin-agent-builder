"""LegacyIMProviderAdapter — Phase 4 IMProvider → IMCapability 适配层（PLUG-FW-04 + IM-LEGACY-WRAP）。

用户硬性 DoD #3：让 Phase 4 6 家 IMProvider（feishu / wecom / dingtalk / slack /
mattermost / webhook）通过新 IMCapability 接口被调用，所有 Phase 4 测试 0 regression。

设计要点（ADR-001 §8 + CONTEXT.md decision + RESEARCH.md Example 2）：

1. **零接口破坏**：Phase 4 既有 `register_provider(provider)` 行为 100% 不变；
   adapter 仅在 base.py `_PROVIDERS_AS_CAP` dict 中存放，不影响老 `_PROVIDERS` dict。

2. **同一 raw provider 实例共享**：adapter 内部 `self._legacy` 指向同一 IMProvider，
   `get_provider(name)` 和 `_PROVIDERS_AS_CAP[name]._legacy` 是同一对象 —— 共享连接池 /
   credential / state。Phase 4 测试 0 regression 的根本保障。

3. **参数映射**：
   - IMProvider.send_hitl_card(recipient: str, flow_title, node_title, ...) (8 keyword args)
       → IMCapability.send_card(*, recipient: RecipientSpec, card: NormalizedCard, idempotency_key)
   - IMProvider.update_card(message_id: str, new_content: dict) → IMCapability.update_card(msg_ref, card)
   - IMProvider.send_supplement_text(recipient, text) → IMCapability.send_text(recipient, text)
   - subscribe_events 留空（Phase 4.5 业务层处理 —— Plan 06 仅 raise NotImplementedError）

4. **cap flags 推导**（无 manifest 来源，从 legacy 字段推导）：
   - supports_native_buttons: webhook 不支持原生卡片，其他 5 家都支持
   - supports_card_update: 沿用 `getattr(legacy, "supports_card_update", False)`
   - supports_threads: Phase 4 6 家都无 thread 支持（CONTEXT.md decision，5.D 才接入真 thread 平台）

5. **lossy field 映射**（NormalizedCard 3 字段 → legacy 8 字段）：
   - title.split(" — ", 1) → flow_title + node_title（最佳还原）
   - body_markdown → description
   - actions → deeplinks
   - applicant_name / actor_name / deadline_at 留空字符串（NormalizedCard 不携带）

Reference:
- docs/reading-dify-05a-06-legacy-adapter-2026-05-17.md（5 借鉴点）
- Dify api/services/plugin/data_migration.py（双轨数据共存模式，AGPL-3.0）
本 module 100% 独立创作，仅借鉴 Dify 设计哲学。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.agent_builder.notification.providers.base import IMProvider

from .capabilities.im import (
    IMCapability,  # noqa: F401 — used for isinstance check in tests
    MessageRef,
    NormalizedCard,
    RecipientSpec,
)

__all__ = ["LegacyIMProviderAdapter", "wrap_legacy_provider"]


# ── 常量 ──────────────────────────────────────────────────────────────────────

# Phase 4 KNOWN_PROVIDERS 全集（用于 supports_native_buttons 推导）
# webhook 是通用 HTTP webhook 投递，不支持原生卡片渲染
_NO_NATIVE_BUTTONS = frozenset({"webhook"})

# legacy provider 字段 supports_card_update 的 fallback 默认值
_DEFAULT_SUPPORTS_CARD_UPDATE = False

# title 拆分分隔符（NormalizedCard.title → legacy flow_title + node_title 最佳还原）
_TITLE_SEPARATOR = " — "


class LegacyIMProviderAdapter:
    """把 Phase 4 IMProvider 包装为 IMCapability。

    Phase 4 既有调用方仍走 `get_provider(name)` → 老接口，0 改动。
    新代码可走 `PlatformPluginRegistry.get_capability(IMCapability, prefer=name)`
    → fallback 到 _PROVIDERS_AS_CAP 拿到本 adapter，参数自动转换。

    Attributes:
        _legacy: 底层 Phase 4 IMProvider 实例（同一引用，与 `_PROVIDERS[name]` 共享）

    Properties (implementing IMCapability Protocol):
        name: str — plugin 名（=legacy.name，如 "feishu"）
        supports_native_buttons: bool — webhook 外 5 家都 True
        supports_card_update: bool — 从 legacy.supports_card_update 字段推导
        supports_threads: bool — Phase 4 6 家都 False
    """

    def __init__(self, legacy: IMProvider) -> None:
        """构造 adapter。

        Args:
            legacy: Phase 4 IMProvider 实例（由 `register_provider` 调用方提供）

        Note:
            不深拷贝、不复制 legacy state —— 共享同一引用，确保 connection pool /
            credential 不重复，且 `get_provider(name)` 与 adapter 内部 self._legacy
            是 `is` 同一对象（Phase 4 0 regression 关键不变量）。
        """
        self._legacy = legacy

    @property
    def name(self) -> str:
        """Plugin 名（=底层 legacy.name）。"""
        return self._legacy.name

    @property
    def supports_native_buttons(self) -> bool:
        """是否支持原生卡片按钮（webhook 不支持，其他 5 家都支持）。

        Phase 4 6 家实情：
        - feishu / wecom / dingtalk / slack / mattermost：原生 Interactive Card / ActionCard / Block Kit
        - webhook：通用 HTTP webhook，由接收端自行渲染（不强制 markdown / 按钮支持）
        """
        return self._legacy.name not in _NO_NATIVE_BUTTONS

    @property
    def supports_card_update(self) -> bool:
        """是否支持 update_card（沿用 legacy provider 字段）。

        Phase 4 6 家实情：
        - 飞书 / Slack / Mattermost：True（有对应 update API）
        - 企微 / 钉钉：False（无 update API；调用方走 send_supplement_text 兜底）
        - webhook：False（取决于接收端，默认 False 安全降级）
        """
        return getattr(
            self._legacy, "supports_card_update", _DEFAULT_SUPPORTS_CARD_UPDATE
        )

    @property
    def supports_threads(self) -> bool:
        """是否支持 thread reply（Phase 4 6 家都不支持）。

        Phase 4 没设计 thread 概念，所有 IMProvider.send_hitl_card 仅支持单一 recipient（用户级 DM）。
        Huly 等一体化平台真支持 thread —— 待 Phase 5.D 落地（5.A 仅留 RecipientSpec(kind="thread") plumbing）。
        """
        return False

    # ── send_card：RecipientSpec + NormalizedCard → legacy 8 字段 ─────────────

    async def send_card(
        self,
        *,
        recipient: RecipientSpec,
        card: NormalizedCard,
        idempotency_key: str,
    ) -> MessageRef:
        """投递卡片消息（Phase 4 send_hitl_card 适配）。

        参数映射：
        - RecipientSpec.id → legacy recipient: str（kind 信息丢失 — Phase 4 6 家都是 user_id / channel_id 一维）
        - NormalizedCard.title → legacy flow_title + node_title（用 " — " 拆分还原）
        - NormalizedCard.body_markdown → legacy description
        - NormalizedCard.actions → legacy deeplinks（保留 action + url，舍弃 label）
        - idempotency_key：暂未传入 legacy（Phase 4 6 家自带幂等 jti 机制；adapter 层不重复）

        Args:
            recipient: 投递目标（Phase 4 6 家仅支持 user_id / channel_id，kind 信息忽略）
            card: 平台无关卡片 schema
            idempotency_key: 幂等键（Phase 4 已通过 jti 实现，此处仅 plumbing）

        Returns:
            MessageRef(plugin_name="legacy:{name}", native_id={message_id})

        Raises:
            ConnectionError / TimeoutError: legacy provider 网络错误（透传）
            其他：legacy provider 业务错误（透传）
        """
        # Phase 4 recipient 都是 str（channel_user_id / open_id / userid 等），kind 不区分
        legacy_recipient = recipient.id

        # NormalizedCard.actions → legacy deeplinks（保留 action + url 字段）
        deeplinks = [
            {"action": str(a.get("action", "")), "url": str(a.get("url", ""))}
            for a in card.actions
        ]

        # NormalizedCard.title → 拆分为 legacy flow_title + node_title
        # 用 " — " (em dash + spaces) 作为约定分隔符（约定俗成的 "流程 — 节点" 模式）
        # 若 title 不含分隔符，flow_title=整 title，node_title=""
        title_parts = card.title.split(_TITLE_SEPARATOR, 1)
        flow_title = title_parts[0] if title_parts else card.title
        node_title = title_parts[1] if len(title_parts) > 1 else ""

        # 其他 5 个 legacy 字段无法从 NormalizedCard 恢复 → 空字符串
        # （调用方应在 body_markdown 中包含申请人/审批人/截止时间等信息）
        result = await self._legacy.send_hitl_card(
            recipient=legacy_recipient,
            flow_title=flow_title,
            node_title=node_title,
            applicant_name="",
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

    # ── update_card：MessageRef + NormalizedCard → legacy message_id + dict ──

    async def update_card(
        self,
        msg_ref: MessageRef,
        card: NormalizedCard,
    ) -> None:
        """更新已发送卡片（如改为只读 + "已被 X 处理"）。

        语义：
        - supports_card_update=False（企微 / 钉钉 / webhook）：silently no-op（与 legacy 行为一致）
        - supports_card_update=True（飞书 / Slack / Mattermost）：调 legacy.update_card

        Args:
            msg_ref: send_card 返回的 MessageRef
            card: 新卡片内容（NormalizedCard 形式）

        Note:
            legacy.update_card 接受 dict 形式的 new_content，本 adapter 仅映射
            title + text 两字段（actions 在 update 场景一般不变；Phase 4 6 家也仅
            支持 text/title 更新）。
        """
        if not self.supports_card_update:
            # 兼容旧行为：不支持 update 时 silently no-op
            # （legacy NotificationService 已有 send_supplement_text 兜底路径）
            return

        await self._legacy.update_card(
            message_id=msg_ref.native_id,
            new_content={
                "text": card.body_markdown,
                "title": card.title,
            },
        )

    # ── send_text：RecipientSpec + text → legacy send_supplement_text ───────

    async def send_text(
        self,
        recipient: RecipientSpec,
        text: str,
    ) -> MessageRef:
        """补发纯文本消息（"已被 X 处理" 等）。

        参数映射：
        - RecipientSpec.id → legacy recipient: str
        - text → legacy text

        Args:
            recipient: 投递目标（kind 信息忽略）
            text: 纯文本内容

        Returns:
            MessageRef(plugin_name="legacy:{name}", native_id="supplement")
            注：legacy.send_supplement_text 不返回 message_id，adapter 用占位符 "supplement"
        """
        await self._legacy.send_supplement_text(
            recipient=recipient.id,
            text=text,
        )
        return MessageRef(
            plugin_name=f"legacy:{self._legacy.name}",
            native_id="supplement",
        )

    # ── subscribe_events：Phase 4.5 业务层处理 ──────────────────────────────

    async def subscribe_events(
        self,
        event_types: list[str],
    ) -> AsyncIterator[dict[str, Any]]:
        """订阅入站事件 —— Phase 4.5 业务层处理，5.A LegacyAdapter 不实现。

        Phase 4 IMProvider Protocol 含 `subscribe` 方法（默认 raise NotImplementedError），
        但 LegacyAdapter 不直接转发到 legacy.subscribe —— 因为：
        1. Phase 4 6 家 provider 自带 subscribe 默认 NotImplementedError
        2. Phase 4.5 入站事件订阅设计上独立于 IMCapability（走业务层 webhook 入口）
        3. 强行套用会引入接口不匹配（IMProvider.subscribe(on_event) vs IMCapability.subscribe_events(event_types))

        Args:
            event_types: 订阅的事件类型列表（如 ["message", "card.button_click"]）

        Raises:
            NotImplementedError: Phase 4.5 业务层处理 — 调用方应改走业务层 dispatcher

        Note:
            `if False: yield {}` 模式让 Python 静态分析将此方法识别为 async generator function。
            实际 raise 在 yield 之前，但 inspect.isasyncgenfunction 仍返回 True。
        """
        raise NotImplementedError(
            f"legacy:{self._legacy.name} subscribe_events — 由 Phase 4.5 业务层处理"
        )
        if False:  # pragma: no cover — 仅为 async generator function 标记
            yield {}


# ── Helper 函数 ───────────────────────────────────────────────────────────────


def wrap_legacy_provider(provider: IMProvider) -> LegacyIMProviderAdapter:
    """工厂函数 — base.py register_provider 调它自动 wrap。

    用法（base.py 内部）：
        from app.agent_builder.platforms.legacy_im_adapter import wrap_legacy_provider
        _PROVIDERS_AS_CAP[provider.name] = wrap_legacy_provider(provider)

    Args:
        provider: Phase 4 IMProvider 实例

    Returns:
        LegacyIMProviderAdapter 实例（含同一 raw provider 引用）
    """
    return LegacyIMProviderAdapter(provider)
