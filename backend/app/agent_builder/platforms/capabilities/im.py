"""IMCapability Protocol — Phase 5.A 通讯能力契约（ADR-001 §3.1）。

设计要点：
- `@runtime_checkable Protocol` — 鸭子类型，plugin 实现类无需继承
- 多态 RecipientSpec — 解决 Huly acid test gap #a（channel / DM / thread 多场景）
- `supports_*` cap flags — 卡片功能能力协商（Huly gap #b：原生按钮 vs markdown 链接降级）
- NormalizedCard — 平台无关卡片 schema，各 Provider 适配为各家 markup
- MessageRef — provider-agnostic 消息 handle，用于 update_card / 后续 ack 等操作
- subscribe_events — Phase 4.5 IM bot 入站订阅升级（async generator pattern）

对 Phase 4 IMProvider 的升级：
- Phase 4: send_hitl_card(recipient: str, flow_title, ...) → dict
- Phase 5.A: send_card(*, recipient: RecipientSpec, card: NormalizedCard, idempotency_key) → MessageRef
- 通过 LegacyIMProviderAdapter（Plan 05）让 Phase 4 6 家 provider 0 regression 走新接口

Reference: docs/reading-dify-05a-02-capability-protocols-2026-05-17.md
- 借鉴点 #2（method 声明 → Python Protocol async 方法签名）
- 借鉴点 #3（每 capability 一 file 组织）
- 借鉴点 #5（Declaration vs Runtime — runtime_checkable 允许 mock 不继承）

CLAUDE.md immutability：所有值对象 dataclass(frozen=True)。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

# ── 值对象（dataclass frozen=True）─────────────────────────────────────────────


@dataclass(frozen=True)
class RecipientSpec:
    """多态 recipient — 描述消息投递目标。

    解决 Huly acid test gap #a：
    - Phase 4 仅支持 `recipient: str`（IM 用户 ID 单一形式）
    - Huly 等一体化平台同时有 channel post / DM / thread reply 三种场景
    - 用 `kind: Literal["channel", "dm_user", "thread"]` 明确表达

    Attributes:
        kind: "channel" — 频道 post；"dm_user" — 私聊；"thread" — 线程回复
        id: 平台内部 ID（channel_id / user_id / thread_id）
        extras: 平台特定额外字段（如 Huly thread reply 需 parent_message_id）
    """

    kind: Literal["channel", "dm_user", "thread"]
    id: str
    extras: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MessageRef:
    """Provider-agnostic 消息 handle — 用于 update_card / 删除 / ack 等后续操作。

    Phase 4 返回 dict {"message_id": ..., "raw_response": ...}，
    Phase 5.A 升级为强类型 dataclass，plugin_name 前缀避免跨 plugin id 碰撞。

    Attributes:
        plugin_name: 标识来源 plugin（如 "huly" / "legacy:feishu" / "mock"）
        native_id: 该 plugin 内部消息 ID（用于 update_card 等回查）
        extras: 调试 / 兼容字段（如 raw response stringified）
    """

    plugin_name: str
    native_id: str
    extras: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedCard:
    """平台无关卡片 schema —— 各 Provider 适配为各家 markup（Feishu Interactive Card / Slack Block Kit / Huly Markdown / ...）。

    极简 3 字段设计，避免 Phase 4 send_hitl_card 8 个 keyword 参数臃肿。
    各 Provider 在 send_card 时翻译为自家格式（如 Feishu 走 Interactive Card 2.0，
    Slack 走 Block Kit，Huly 走纯 Markdown）。

    Attributes:
        title: 卡片标题
        body_markdown: 卡片正文（Markdown 格式；各 Provider 渲染策略自定）
        actions: 按钮列表 [{"action": "approve", "label": "批准", "url": "https://..."}]
                 - action: 业务侧 action 名（approve/reject/return/detail 等）
                 - label: 按钮显示文本
                 - url: 深链 URL（HITL token 链接）
    """

    title: str
    body_markdown: str
    actions: list[dict[str, str]]


# ── IMCapability Protocol ────────────────────────────────────────────────────


@runtime_checkable
class IMCapability(Protocol):
    """对外通讯能力 — 发卡片 / DM / channel post / 接事件。

    实现要求（任何 plugin 类声明 capabilities 含 "im" 时）：
    - 类属性：name / supports_native_buttons / supports_card_update / supports_threads
    - 方法：send_card / update_card / send_text / subscribe_events 全部实现
    - subscribe_events 必须是 async generator function（含 yield，即使在 if False 分支）

    runtime_checkable 行为：
        isinstance(obj, IMCapability) — True 当 obj 含所有声明属性 + 方法名（不检查方法签名 / 类型）
        静态类型检查（mypy）会校验方法签名

    cap flags 语义：
    - supports_native_buttons: True 时 Provider 渲染原生按钮（如 Feishu Interactive Card）；
      False 时降级为 markdown 链接列表（如 Huly 纯文本）
    - supports_card_update: True 时 update_card 真正修改原卡片；
      False 时 update_card silently no-op，调用方应走 send_text 补发
    - supports_threads: True 时 RecipientSpec(kind="thread") 走 thread reply；
      False 时把 thread reply 降级为 channel post
    """

    name: str
    """Plugin 名（"huly" / "legacy:feishu" / ...）"""

    supports_native_buttons: bool
    """是否支持原生卡片按钮（False 降级为 markdown 链接）"""

    supports_card_update: bool
    """是否支持 update_card（False 时 update_card silently no-op）"""

    supports_threads: bool
    """是否支持 thread reply（False 时 thread → channel post 降级）"""

    async def send_card(
        self,
        *,
        recipient: RecipientSpec,
        card: NormalizedCard,
        idempotency_key: str,
    ) -> MessageRef:
        """投递卡片消息。

        Phase 4 对应：send_hitl_card —— 但参数简化为 3 个，卡片内容打包到 NormalizedCard。

        Args:
            recipient: 投递目标（多态 channel / dm_user / thread）
            card: 平台无关卡片 schema
            idempotency_key: 幂等键（防重复投递；Phase 4 通过 jti 已建立模式）

        Returns:
            MessageRef — 用于 update_card 等后续操作

        Raises:
            ConnectionError / TimeoutError: 网络错误（调用方应重试）
            PluginInvocationError: daemon 业务错误
        """
        ...

    async def update_card(self, msg_ref: MessageRef, card: NormalizedCard) -> None:
        """更新已发送卡片（如改为只读 + "已被 X 处理"）。

        Phase 4 对应：update_card(message_id, new_content) —— 但 new_content 改为 NormalizedCard。

        Args:
            msg_ref: send_card 返回的 MessageRef
            card: 新内容（NormalizedCard 形式，让 update 与 send 对称）

        语义：
            supports_card_update=True 时真正修改原卡片；
            supports_card_update=False 时实现可 silently no-op（调用方自行 send_text 补发）。
        """
        ...

    async def send_text(self, recipient: RecipientSpec, text: str) -> MessageRef:
        """补发纯文本消息（如 "已被 X 处理" 兜底）。

        Phase 4 对应：send_supplement_text —— 升级为带 MessageRef 返回（便于追溯）。

        Args:
            recipient: 投递目标（与 send_card 同 RecipientSpec 多态）
            text: 纯文本内容

        Returns:
            MessageRef — 用于后续追溯
        """
        ...

    async def subscribe_events(
        self,
        event_types: list[str],
    ) -> AsyncIterator[dict[str, Any]]:
        """订阅入站 IM 事件（Phase 4.5 IM bot 升级）。

        实现 hint：用 `if False: yield {}` pattern 让方法成为 async generator function，
        否则即使方法名 / 签名匹配，inspect.isasyncgenfunction 会 False。

        例：
            async def subscribe_events(self, event_types):
                if False:  # pragma: no cover
                    yield {}
                async for raw in self._daemon.stream("im.subscribe", event_types=event_types):
                    yield raw

        Args:
            event_types: 订阅的事件类型列表（如 ["message", "card.button_click"]）

        Yields:
            原始事件 dict（各 Provider 自定 schema；上层 dispatcher 解析）
        """
        ...
