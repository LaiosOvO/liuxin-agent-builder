"""PlatformPlugin + capability_facades stub 单测。

测试覆盖：
1. test_plugin_repr — __repr__ 含 name/version/capabilities
2. test_plugin_name_and_manifest_accessors — name / manifest property 返回正确值
3. test_plugin_daemon_none_by_default — Plan 04 daemon 默认 None
4. test_plugin_attach_daemon — attach_daemon 注入成功 + 重复 attach raise
5. test_plugin_lazy_facades_im — 首次访问 .im 实例化 IMFacade + 二次返回 cache
6. test_plugin_facade_missing_capability_returns_none — 未声明的 capability 返回 None
7. test_plugin_all_4_facades_cached — 4 facade 都被 cache（IM/Doc/HR/Identity）
8. test_facade_methods_raise_plugin_error_when_daemon_missing — daemon=None 时 raise PluginError（Plan 05 演进）
9. test_facade_share_same_daemon — 4 facade 共享同一 _daemon 引用
10. test_facade_async_generator_is_marked — subscribe_events / watch_user_changes 是 async generator function
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from app.agent_builder.platforms.capability_facades import (
    DocFacade,
    HRFacade,
    IdentityFacade,
    IMFacade,
)
from app.agent_builder.platforms.manifest import load_manifest
from app.agent_builder.platforms.plugin import PlatformPlugin

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def huly_manifest():
    """加载完整 huly fixture（含 4 capability：im/doc/hr/identity 中的 3 个 + im）。

    注：fixture manifest 含 capabilities=[im, doc, hr, identity]。
    """
    # 临时改 fixture，让 HR 也声明（fixture YAML 不变，临时构造）
    return load_manifest(FIXTURES_DIR / "manifest_valid.yaml")


@pytest.fixture
def im_only_plugin(tmp_path: Path):
    """构造仅 im capability 的 plugin —— 测 missing capability 返回 None。"""
    p = tmp_path / "im_only.yaml"
    p.write_text(
        """
name: imonly
version: 1.0.0
description: "IM-only plugin (test fixture)"
runtime:
  type: python
  entry: imonly.main
capabilities: [im]
config_schema: {}
""",
        encoding="utf-8",
    )
    manifest = load_manifest(p)
    return PlatformPlugin(manifest=manifest, daemon=None)


# ── PlatformPlugin 基础属性（4 测试）──────────────────────────────────────────


def test_plugin_repr(huly_manifest) -> None:
    """__repr__ 含 name / version / capabilities / daemon_attached。"""
    plugin = PlatformPlugin(manifest=huly_manifest, daemon=None)
    repr_str = repr(plugin)
    assert "huly" in repr_str
    assert "1.0.0" in repr_str
    assert "daemon_attached=False" in repr_str


def test_plugin_name_and_manifest_accessors(huly_manifest) -> None:
    """name / manifest property 返回正确值。"""
    plugin = PlatformPlugin(manifest=huly_manifest, daemon=None)
    assert plugin.name == "huly"
    assert plugin.manifest is huly_manifest


def test_plugin_daemon_none_by_default(huly_manifest) -> None:
    """Plan 04 PlatformPlugin daemon 默认 None。"""
    plugin = PlatformPlugin(manifest=huly_manifest, daemon=None)
    assert plugin.daemon is None


def test_plugin_attach_daemon(huly_manifest) -> None:
    """attach_daemon 注入成功 + 重复 attach raise RuntimeError。"""
    plugin = PlatformPlugin(manifest=huly_manifest, daemon=None)

    # 模拟一个 daemon（Plan 06 才有真实 PlatformDaemonClient）
    mock_daemon = object()
    plugin.attach_daemon(mock_daemon)  # type: ignore[arg-type]
    assert plugin.daemon is mock_daemon

    # 重复 attach 抛
    with pytest.raises(RuntimeError, match="重复 attach"):
        plugin.attach_daemon(mock_daemon)  # type: ignore[arg-type]


# ── PlatformPlugin lazy facade（3 测试）─────────────────────────────────────


def test_plugin_lazy_facades_im(huly_manifest) -> None:
    """首次访问 .im 实例化 IMFacade + 二次返回缓存（懒加载）。"""
    plugin = PlatformPlugin(manifest=huly_manifest, daemon=None)

    im1 = plugin.im
    assert isinstance(im1, IMFacade)

    # 二次访问返回同 instance（缓存）
    im2 = plugin.im
    assert im1 is im2


def test_plugin_facade_missing_capability_returns_none(im_only_plugin) -> None:
    """plugin 仅声明 im → .doc / .hr / .identity 返回 None。"""
    assert isinstance(im_only_plugin.im, IMFacade)
    assert im_only_plugin.doc is None
    assert im_only_plugin.hr is None
    assert im_only_plugin.identity is None


def test_plugin_all_4_facades_cached(huly_manifest) -> None:
    """4 facade 都被 cache（im/doc/hr/identity）。注：fixture 不含 hr，仅 3 个。"""
    plugin = PlatformPlugin(manifest=huly_manifest, daemon=None)

    # huly manifest_valid.yaml 含 capabilities=[im, doc, hr, identity]
    im_f = plugin.im
    doc_f = plugin.doc
    hr_f = plugin.hr
    identity_f = plugin.identity

    assert isinstance(im_f, IMFacade)
    assert isinstance(doc_f, DocFacade)
    assert isinstance(hr_f, HRFacade)
    assert isinstance(identity_f, IdentityFacade)

    # 二次访问全返回 cache
    assert plugin.im is im_f
    assert plugin.doc is doc_f
    assert plugin.hr is hr_f
    assert plugin.identity is identity_f


# ── capability_facades stub 行为（3 测试）─────────────────────────────────


@pytest.mark.asyncio
async def test_facade_methods_raise_plugin_error_when_daemon_missing(
    huly_manifest,
) -> None:
    """**Plan 05 演进**：daemon=None 时所有 facade method raise PluginError（fail-fast）。

    Plan 04 stub 行为是 raise NotImplementedError；Plan 05 接入真 daemon 后，
    daemon 缺失走 _ensure_daemon() 校验 → raise PluginError("daemon not attached")。
    调用方应先 attach_daemon(daemon) 再调 method。
    """
    from app.agent_builder.platforms.capabilities import (
        MessageRef,
        NormalizedCard,
        RecipientSpec,
    )
    from app.agent_builder.platforms.exceptions import PluginError

    plugin = PlatformPlugin(manifest=huly_manifest, daemon=None)

    # IMFacade methods —— 用真实 dataclass 参数（asdict() 序列化要求）
    im_f = plugin.im
    recipient = RecipientSpec(kind="channel", id="c1")
    card = NormalizedCard(title="t", body_markdown="b", actions=[])
    msg_ref = MessageRef(plugin_name="huly", native_id="x")
    with pytest.raises(PluginError, match="daemon not attached"):
        await im_f.send_card(recipient=recipient, card=card, idempotency_key="k1")
    with pytest.raises(PluginError, match="daemon not attached"):
        await im_f.update_card(msg_ref, card)
    with pytest.raises(PluginError, match="daemon not attached"):
        await im_f.send_text(recipient, "hi")

    # DocFacade methods
    doc_f = plugin.doc
    with pytest.raises(PluginError, match="daemon not attached"):
        await doc_f.create_document(title="t", markdown="md")

    # HRFacade methods
    hr_f = plugin.hr
    with pytest.raises(PluginError, match="daemon not attached"):
        await hr_f.resolve_department_members("dept:研发部")

    # IdentityFacade methods
    identity_f = plugin.identity
    with pytest.raises(PluginError, match="daemon not attached"):
        await identity_f.list_users()


def test_facade_share_same_daemon(huly_manifest) -> None:
    """4 facade 共享同一 _daemon 引用（lazy facade 关键设计）。"""
    mock_daemon = object()
    plugin = PlatformPlugin(manifest=huly_manifest, daemon=mock_daemon)  # type: ignore[arg-type]

    assert plugin.im._daemon is mock_daemon
    assert plugin.doc._daemon is mock_daemon
    assert plugin.hr._daemon is mock_daemon
    assert plugin.identity._daemon is mock_daemon


def test_facade_async_generator_is_marked() -> None:
    """subscribe_events / watch_user_changes 是 async generator function（不是普通 coroutine）。

    Plan 02/03 的 High 5 关键 pattern：用 `if False: yield {}` 让 Python 标记为 asyncgenfunction。
    capability_facades stub 也必须保留这个标记，否则未来真实现时签名不兼容。
    """
    # IMFacade.subscribe_events
    assert inspect.isasyncgenfunction(IMFacade.subscribe_events)

    # IdentityFacade.watch_user_changes
    assert inspect.isasyncgenfunction(IdentityFacade.watch_user_changes)
