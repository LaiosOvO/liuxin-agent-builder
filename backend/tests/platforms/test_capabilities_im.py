"""IMCapability Protocol 单测 — isinstance + duck typing 路径 + 值对象不可变 + async generator 静态断言。

测试覆盖（plan 02 要求 ≥ 6 测试）：
1. test_im_capability_isinstance_minimal — runtime_checkable 生效（最小实现 pass）
2. test_im_capability_isinstance_with_extras — RecipientSpec extras 字段 default_factory
3. test_recipient_spec_immutable — frozen=True
4. test_normalized_card_immutable — frozen=True + actions 字段
5. test_message_ref_immutable — frozen=True + extras 字段
6. test_recipient_spec_kind_enumerated — Literal 三态运行时构造
7. test_subscribe_events_is_async_generator — inspect.isasyncgenfunction 静态断言（High 5 关键）
8. test_im_capability_isinstance_missing_method_fails — runtime_checkable negative case

直接子模块 import — Plan 02 不写 capabilities/__init__.py 完整 exports（Plan 03 独占）。
"""

from __future__ import annotations

import inspect

from app.agent_builder.platforms.capabilities.im import (
    IMCapability,
    MessageRef,
    NormalizedCard,
    RecipientSpec,
)


class _MinimalIM:
    """最小实现 — 仅用于 isinstance check + duck typing 覆盖。"""

    name = "mock_min"
    supports_native_buttons = True
    supports_card_update = True
    supports_threads = False

    async def send_card(self, *, recipient, card, idempotency_key):
        return MessageRef(plugin_name="mock", native_id="m1")

    async def update_card(self, msg_ref, card):
        pass

    async def send_text(self, recipient, text):
        return MessageRef(plugin_name="mock", native_id="t1")

    async def subscribe_events(self, event_types):
        if False:  # pragma: no cover
            yield {}


class _IMWithoutSubscribe:
    """Negative case — 缺 subscribe_events 方法。"""

    name = "missing_subscribe"
    supports_native_buttons = True
    supports_card_update = True
    supports_threads = False

    async def send_card(self, *, recipient, card, idempotency_key):
        return MessageRef(plugin_name="x", native_id="x")

    async def update_card(self, msg_ref, card):
        pass

    async def send_text(self, recipient, text):
        return MessageRef(plugin_name="x", native_id="x")


# ── 测试 ──────────────────────────────────────────────────────────────────────


def test_im_capability_isinstance_minimal():
    """runtime_checkable 生效 — _MinimalIM 无需继承也 pass isinstance。"""
    assert isinstance(_MinimalIM(), IMCapability)


def test_im_capability_isinstance_with_extras():
    """RecipientSpec extras 字段 default_factory 工作。"""
    r = RecipientSpec(kind="thread", id="ch1", extras={"parent_message_id": "m1"})
    assert r.extras == {"parent_message_id": "m1"}
    # 默认空 dict
    r_default = RecipientSpec(kind="channel", id="ch2")
    assert r_default.extras == {}


def test_recipient_spec_immutable():
    """RecipientSpec frozen=True — 不可变（assign 触发 FrozenInstanceError）。"""
    r = RecipientSpec(kind="dm_user", id="user_abc")
    try:
        r.id = "user_xyz"  # type: ignore[misc]
    except Exception:
        # FrozenInstanceError (subclass of AttributeError) — 预期行为
        pass
    else:
        raise AssertionError("RecipientSpec should be frozen")


def test_normalized_card_immutable():
    """NormalizedCard frozen=True + actions 字段结构。"""
    c = NormalizedCard(
        title="审批请求",
        body_markdown="**申请人**: 张三\n**金额**: 1000",
        actions=[
            {"action": "approve", "label": "批准", "url": "https://x/a"},
            {"action": "reject", "label": "拒绝", "url": "https://x/r"},
        ],
    )
    assert c.title == "审批请求"
    assert len(c.actions) == 2
    assert c.actions[0]["action"] == "approve"
    # frozen 断言
    try:
        c.title = "篡改"  # type: ignore[misc]
    except Exception:
        pass
    else:
        raise AssertionError("NormalizedCard should be frozen")


def test_message_ref_immutable():
    """MessageRef frozen=True + extras 字段 default_factory。"""
    m = MessageRef(plugin_name="huly", native_id="abc")
    assert m.plugin_name == "huly"
    assert m.native_id == "abc"
    assert m.extras == {}
    # with extras
    m2 = MessageRef(plugin_name="legacy:feishu", native_id="123", extras={"raw": "{}"})
    assert m2.extras == {"raw": "{}"}
    # frozen 断言
    try:
        m.native_id = "xyz"  # type: ignore[misc]
    except Exception:
        pass
    else:
        raise AssertionError("MessageRef should be frozen")


def test_recipient_spec_kind_enumerated():
    """RecipientSpec.kind 限定 channel/dm_user/thread — 运行时构造 3 种合法 kind。"""
    for k in ["channel", "dm_user", "thread"]:
        r = RecipientSpec(kind=k, id="x")  # type: ignore[arg-type]
        assert r.kind == k
    # Literal 类型本身的 args（mypy 静态校验 — 运行时仅文档用途）
    # 这里仅断言 dataclass 不阻止合法值；非法值不强制运行时校验（依赖 mypy）


def test_subscribe_events_is_async_generator():
    """subscribe_events 必须是 async generator function（含 yield，即使在 if False 分支）。

    High 5 静态断言：使用 inspect.isasyncgenfunction 验证。
    `if False: yield {}` 模式让 Python 把方法当 async generator 编译，
    哪怕 yield 在不可达分支也能通过 isasyncgenfunction 检查。

    isinstance(_MinimalIM(), IMCapability) 仅校验属性 + 方法名存在，
    不检查方法是否为 async generator —— 必须显式断言。
    """
    assert inspect.isasyncgenfunction(
        _MinimalIM.subscribe_events
    ), "subscribe_events 必须是 async generator function（含 yield）"


def test_im_capability_isinstance_missing_method_fails():
    """runtime_checkable negative case — 缺方法时 isinstance 返回 False。

    Python typing.Protocol runtime_checkable 行为：检查所有 Protocol 声明的方法 / 属性
    是否在被检对象上存在（不检查类型 / 签名）。_IMWithoutSubscribe 缺 subscribe_events
    方法名 → isinstance 应返回 False。
    """
    assert not isinstance(
        _IMWithoutSubscribe(), IMCapability
    ), "缺 subscribe_events 方法的类不应 pass isinstance(IMCapability)"
