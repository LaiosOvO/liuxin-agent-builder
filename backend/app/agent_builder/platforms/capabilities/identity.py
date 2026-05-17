"""IdentityCapability — 身份源能力（Huly acid test §6 反向 sync 解决方案）。

设计要点（ADR-001 §3.4）：

- **is_source_of_truth: bool flag** — 区分 Huly (True) vs Phase 4 IM provider (False)，
  决定 sync 方向：
    - Huly is_source_of_truth=True → 我们的本地 users 表跟随 Huly 变更（pull from Huly）
    - 飞书 / 钉钉 IM provider is_source_of_truth=False → 我们的本地用户主动 push 到 IM
- **watch_user_changes() async generator** — 长连接 / WebSocket 推送，仅
  source_of_truth=True 的 plugin 实现；其他 plugin raise NotImplementedError
- **resolve_user(identifier)** — plugin 自己理解 identifier 语义（email / canonical_username
  / native_id），不在主进程强制 schema

Reference (Dify reading doc `docs/reading-dify-05a-03-hr-identity-trigger-tool-2026-05-17.md`)：
- Dify 无 Identity 抽象（Dify 用自家 OAuth + JWT 管 account）— 本 capability **完全新疆域**
- 借鉴 Dify Plugin Daemon JSONRPC envelope 模式（pending/streaming response）→
  `watch_user_changes()` async generator 对应 streaming RPC
- License: Dify AGPL-3.0 vs 本项目 Apache-2.0 — 严格不拷源代码

CLAUDE.md immutability：UserPrincipal / UserChangeEvent dataclass `frozen=True`。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable


# ── 值对象（Value Objects）─────────────────────────────────────────────────────


@dataclass(frozen=True)
class UserPrincipal:
    """统一用户主体 — 跨 plugin 唯一标识 (plugin_name + native_id) 主键。

    canonical_username 是 plugin-认可 的标准用户名（如 Huly handle / 飞书 user_id 全 plugin
    内唯一），主进程用它在 `users` 表存 `canonical_username` 字段（Phase 5.D `email_index`
    + `canonical_username_index` 双重索引保证查询效率）。

    extras 装 plugin-specific 字段（如 Huly account permissions / Lark tenant_id 等）。
    """

    plugin_name: str  # "huly" | "legacy:feishu" | ...
    native_id: str  # plugin 内部 ID（Huly account id / 飞书 open_id）
    canonical_username: str
    email: str
    display_name: str
    is_active: bool = True
    extras: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class UserChangeEvent:
    """User 变更事件（watch_user_changes 流式推送）。

    `kind` 枚举（Literal）：
    - `created`: 新建用户 — previous_principal=None
    - `updated`: 字段变更（如 email / display_name） — previous_principal 含老值
    - `deleted`: 注销 — previous_principal 含最终状态
    - `renamed`: canonical_username 变更（特殊场景，影响 audit log 追溯）

    上层（Phase 5.D UserSyncService）按 kind 分流到对应 handler。
    """

    kind: Literal["created", "updated", "deleted", "renamed"]
    principal: UserPrincipal
    previous_principal: UserPrincipal | None = None  # created 时 None；其他 kind 必有


# ── Capability Protocol ────────────────────────────────────────────────────────


@runtime_checkable
class IdentityCapability(Protocol):
    """身份源能力 — 决定 sync 方向（Huly acid test §6 反向 sync 解决方案）。

    Phase 5.A 仅定义 Protocol；具体 plugin 实现在 Phase 5.D（Huly Identity / 飞书
    Contact / 钉钉 OAPI）。

    runtime_checkable 让 `isinstance(plugin, IdentityCapability)` 走鸭子类型校验。

    **关键 flag**: `is_source_of_truth: bool` —
    - True (Huly Identity)：watch_user_changes() async generator 真实推送；
      `users` 表跟随 Huly 变更（pull from Huly）
    - False (Phase 4 IM provider)：watch_user_changes() raise NotImplementedError；
      `users` 表为本地权威，主动 push 到 IM provider
    """

    name: str  # plugin 名 — Registry 路由用
    is_source_of_truth: bool  # **决定 sync 方向**

    async def list_users(self) -> list[UserPrincipal]:
        """全量查所有 users — 一般 plugin 实现含分页（迭代器内部聚合）。

        Phase 5.D 启动期一次性 import 用；常规查询走 resolve_user。
        """
        ...

    async def resolve_user(self, identifier: str) -> UserPrincipal | None:
        """按 email / canonical_username / native_id 查 — plugin 自己理解 identifier 语义。

        - Huly 优先 email 查；fallback handle
        - 飞书优先 user_id 查；fallback email
        plugin 不识别 identifier → 返回 None（fail-quiet）。
        """
        ...

    def watch_user_changes(self) -> AsyncIterator[UserChangeEvent]:
        """长连接推送 user 变更（仅 source_of_truth=True 的 plugin 实现）。

        **重要**：此方法签名是 async generator function（含 `yield`）— 注意定义时即使没
        真实事件也要写 `if False: yield UserChangeEvent(...)` 让 Python 标记为
        `inspect.isasyncgenfunction == True`，否则会被识别为普通 async function。

        用法（调用方 Phase 5.D UserSyncService）：
            async for event in identity_cap.watch_user_changes():
                if event.kind == "created":
                    await user_sync.handle_create(event.principal)
                elif event.kind == "updated":
                    await user_sync.handle_update(event.principal, event.previous_principal)
                ...

        is_source_of_truth=False 的 plugin 实现：
            async def watch_user_changes(self):
                raise NotImplementedError(
                    f"{self.name} is_source_of_truth=False, cannot watch user changes"
                )
                if False:
                    yield UserChangeEvent(...)  # 让 Python 标记为 asyncgenfunction
        """
        ...
