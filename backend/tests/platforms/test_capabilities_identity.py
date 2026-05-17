"""IdentityCapability Protocol 单测 — runtime_checkable + is_source_of_truth gate + async generator 静态断言。

测试范围：
1. runtime_checkable isinstance 路径（双 plugin：SoT True / False）
2. UserPrincipal dataclass frozen=True
3. UserChangeEvent kind Literal 边界
4. watch_user_changes 仅 source_of_truth=True 实现（非权威 plugin raise NotImplementedError）
5. **isasyncgenfunction 静态断言**（High 5 防 `if False: yield ...` 模式被误写成普通 async function）

直接子模块 import（capabilities/__init__.py 由 Plan 03 独占）。
"""
from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator

import pytest

from app.agent_builder.platforms.capabilities.identity import (
    IdentityCapability,
    UserChangeEvent,
    UserPrincipal,
)


# ── Mock plugin: is_source_of_truth=True（Huly Identity 风格）────────────────────


class _SourceOfTruthIdentity:
    """模拟 Huly Identity plugin — is_source_of_truth=True，watch_user_changes 真实推。"""

    name = "huly_identity_mock"
    is_source_of_truth = True

    async def list_users(self) -> list[UserPrincipal]:
        return [
            UserPrincipal(
                plugin_name=self.name,
                native_id="user001",
                canonical_username="alice",
                email="alice@example.com",
                display_name="Alice",
            ),
            UserPrincipal(
                plugin_name=self.name,
                native_id="user002",
                canonical_username="bob",
                email="bob@example.com",
                display_name="Bob",
            ),
        ]

    async def resolve_user(self, identifier: str) -> UserPrincipal | None:
        if identifier in ("alice@example.com", "alice", "user001"):
            return UserPrincipal(
                plugin_name=self.name,
                native_id="user001",
                canonical_username="alice",
                email="alice@example.com",
                display_name="Alice",
            )
        return None

    async def watch_user_changes(self) -> AsyncIterator[UserChangeEvent]:
        """真实 async generator — 推 1 个 created event。"""
        yield UserChangeEvent(
            kind="created",
            principal=UserPrincipal(
                plugin_name=self.name,
                native_id="user003",
                canonical_username="charlie",
                email="charlie@example.com",
                display_name="Charlie",
            ),
        )


# ── Mock plugin: is_source_of_truth=False（Phase 4 IM provider 风格）─────────────


class _NonSourceOfTruthIdentity:
    """模拟 Phase 4 IM provider — is_source_of_truth=False，watch_user_changes raise。"""

    name = "feishu_legacy_identity_mock"
    is_source_of_truth = False

    async def list_users(self) -> list[UserPrincipal]:
        return []

    async def resolve_user(self, identifier: str) -> UserPrincipal | None:
        return None

    async def watch_user_changes(self) -> AsyncIterator[UserChangeEvent]:
        """非权威 plugin raise — 第一行 raise NotImplementedError。

        关键：仍要写 `if False: yield UserChangeEvent(...)` 让 Python 标记为
        asyncgenfunction，否则 isasyncgenfunction 返回 False。
        """
        raise NotImplementedError(
            f"{self.name} is_source_of_truth=False, cannot watch user changes"
        )
        if False:  # pragma: no cover
            yield UserChangeEvent(  # type: ignore[unreachable]
                kind="created",
                principal=UserPrincipal(
                    plugin_name=self.name,
                    native_id="x",
                    canonical_username="x",
                    email="x",
                    display_name="x",
                ),
            )


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_identity_capability_isinstance_source_of_truth():
    """runtime_checkable 鸭子类型 — Mock 无需继承也 pass isinstance。"""
    plugin = _SourceOfTruthIdentity()
    assert isinstance(plugin, IdentityCapability)


def test_identity_capability_isinstance_non_source_of_truth():
    """非权威 plugin 仍 pass isinstance（鸭子类型不挑权威性）— SoT flag 仅运行时分流用。"""
    plugin = _NonSourceOfTruthIdentity()
    assert isinstance(plugin, IdentityCapability)


def test_user_principal_frozen():
    """UserPrincipal dataclass frozen=True — 不可变。"""
    up = UserPrincipal(
        plugin_name="x",
        native_id="y",
        canonical_username="alice",
        email="alice@e.com",
        display_name="Alice",
    )
    with pytest.raises((AttributeError, Exception)):
        up.email = "bob@e.com"  # type: ignore[misc]


def test_user_principal_extras_default():
    """UserPrincipal.extras 默认空 dict（default_factory，非全局共享）。"""
    up1 = UserPrincipal(
        plugin_name="x", native_id="y",
        canonical_username="alice", email="a@e.com", display_name="A",
    )
    up2 = UserPrincipal(
        plugin_name="x", native_id="z",
        canonical_username="bob", email="b@e.com", display_name="B",
    )
    assert up1.extras == {}
    assert up2.extras == {}
    # default_factory 保证不同实例的 extras 是独立对象（非同一 dict）
    assert up1.extras is not up2.extras


def test_user_change_event_kinds():
    """UserChangeEvent.kind Literal 4 枚举边界。"""
    principal = UserPrincipal(
        plugin_name="x", native_id="y",
        canonical_username="alice", email="a@e.com", display_name="A",
    )
    for kind in ("created", "updated", "deleted", "renamed"):
        event = UserChangeEvent(kind=kind, principal=principal)  # type: ignore[arg-type]
        assert event.kind == kind


def test_user_change_event_with_previous_principal():
    """UserChangeEvent.updated kind 携带 previous_principal。"""
    new_p = UserPrincipal(
        plugin_name="x", native_id="y",
        canonical_username="alice_new", email="new@e.com", display_name="A New",
    )
    old_p = UserPrincipal(
        plugin_name="x", native_id="y",
        canonical_username="alice", email="old@e.com", display_name="A Old",
    )
    event = UserChangeEvent(kind="updated", principal=new_p, previous_principal=old_p)
    assert event.previous_principal is not None
    assert event.previous_principal.email == "old@e.com"
    assert event.principal.email == "new@e.com"


def test_watch_user_changes_raises_for_non_source_of_truth():
    """非权威 plugin 调 watch_user_changes → raise NotImplementedError。"""

    async def go():
        non_sot = _NonSourceOfTruthIdentity()
        with pytest.raises(NotImplementedError) as exc_info:
            async for _event in non_sot.watch_user_changes():
                break  # 不会到这里
        assert "is_source_of_truth=False" in str(exc_info.value)

    asyncio.run(go())


def test_watch_user_changes_yields_for_source_of_truth():
    """source_of_truth=True plugin 调 watch_user_changes → yield UserChangeEvent。"""

    async def go():
        sot = _SourceOfTruthIdentity()
        events = []
        async for event in sot.watch_user_changes():
            events.append(event)
        assert len(events) == 1
        assert events[0].kind == "created"
        assert events[0].principal.canonical_username == "charlie"

    asyncio.run(go())


def test_watch_user_changes_is_async_generator_function():
    """**High 5 静态断言**: watch_user_changes 必须是 async generator function（含 yield）。

    防 `if False: yield {}` 模式被误写成普通 async function（这是 Python 语义陷阱：
    async def 内必须有 yield 才会成为 async generator function，否则是 coroutine function）。

    isasyncgenfunction 返回 True 才证明 `async for ... in watch_user_changes()` 能工作。
    """
    # source_of_truth=True plugin 必须是 asyncgenfunction
    assert inspect.isasyncgenfunction(_SourceOfTruthIdentity.watch_user_changes), (
        "_SourceOfTruthIdentity.watch_user_changes 必须是 async generator function（含 yield）"
    )
    # source_of_truth=False plugin 也必须是 asyncgenfunction（即使第一行 raise，含 `if False: yield`）
    assert inspect.isasyncgenfunction(_NonSourceOfTruthIdentity.watch_user_changes), (
        "_NonSourceOfTruthIdentity.watch_user_changes 必须是 async generator function "
        "（即使 raise，也要含 `if False: yield ...` 让 Python 标记为 asyncgenfunction）"
    )


def test_resolve_user_returns_none_for_unknown_identifier():
    """resolve_user fail-quiet — 未知 identifier 返回 None，不 raise。"""

    async def go():
        plugin = _SourceOfTruthIdentity()
        result = await plugin.resolve_user("unknown@xxx.com")
        assert result is None

    asyncio.run(go())


def test_list_users_returns_list_of_user_principals():
    """list_users 返回 list[UserPrincipal]。"""

    async def go():
        plugin = _SourceOfTruthIdentity()
        users = await plugin.list_users()
        assert isinstance(users, list)
        assert all(isinstance(u, UserPrincipal) for u in users)
        assert len(users) == 2

    asyncio.run(go())
