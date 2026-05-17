"""PlatformPluginRegistry 单测（PLUG-FW-03）。

测试覆盖（PLAN.md ≥ 8 测试要求）：

1. test_discover_finds_huly — 单 plugin 扫描成功
2. test_discover_empty_dir_returns_empty — 不存在的 plugins root 返回 [] 不 raise
3. test_discover_invalid_manifest_raises — 单个 manifest 校验失败 → PluginError fail-fast
4. test_discover_duplicate_name_raises — 两个目录同 name → PluginError
5. test_discover_skips_dirs_without_platform_yaml — 子目录无 platform.yaml 静默跳过
6. test_get_plugin_lazy_returns_same_instance — 同 workspace 二次访问返回缓存
7. test_two_workspaces_isolated — **Pitfall 5 关键防护**：双 workspace 不同 instance
8. test_get_plugin_unknown_returns_none — 未 discover 的 plugin 返回 None
9. test_get_capability_im_returns_facade — 按 IMCapability 类型路由返回 IMFacade
10. test_get_capability_missing_returns_none — 缺 capability fail-quiet
11. test_get_capability_prefer_works — prefer 参数优先生效
12. test_get_capability_unknown_type_returns_none — 未知 capability_type 返回 None
13. test_list_manifests_returns_loaded — list_manifests 返回所有 discover 结果

Reference: docs/reading-dify-05a-04-manifest-registry-2026-05-17.md §借鉴点 #3/4/5/6
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from app.agent_builder.platforms.capabilities import (
    DocCapability,
    HRCapability,
    IdentityCapability,
    IMCapability,
    TriggerCapability,
)
from app.agent_builder.platforms.capability_facades import (
    DocFacade,
    HRFacade,
    IdentityFacade,
    IMFacade,
)
from app.agent_builder.platforms.exceptions import PluginError
from app.agent_builder.platforms.registry import PlatformPluginRegistry

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def fresh_registry():
    """每个测试都从干净的 Registry 开始（class var 状态清空）。"""
    PlatformPluginRegistry.clear()
    yield
    PlatformPluginRegistry.clear()


@pytest.fixture
def plugins_dir_with_huly(tmp_path: Path) -> Path:
    """tmp_path/plugins/huly/platform.yaml 单 plugin 安装。"""
    plugin_dir = tmp_path / "plugins" / "huly"
    plugin_dir.mkdir(parents=True)
    fixture = FIXTURES_DIR / "manifest_valid.yaml"
    shutil.copy(fixture, plugin_dir / "platform.yaml")
    return tmp_path / "plugins"


# ── Discover 相关测试（5 个）──────────────────────────────────────────────────


def test_discover_finds_huly(fresh_registry, plugins_dir_with_huly: Path) -> None:
    """单 plugin 扫描成功 + manifest 入 _MANIFESTS。"""
    loaded = PlatformPluginRegistry.discover(plugins_dir_with_huly)

    assert len(loaded) == 1
    assert loaded[0].name == "huly"
    assert loaded[0].version == "1.0.0"
    assert PlatformPluginRegistry.get_manifest("huly") is not None
    assert PlatformPluginRegistry.get_manifest("nonexistent") is None


def test_discover_empty_dir_returns_empty(fresh_registry, tmp_path: Path) -> None:
    """不存在的 plugins root 静默返回 []（启动期不阻断）。"""
    result = PlatformPluginRegistry.discover(tmp_path / "does_not_exist")
    assert result == []
    assert PlatformPluginRegistry.list_manifests() == []


def test_discover_invalid_manifest_raises(fresh_registry, tmp_path: Path) -> None:
    """单个 manifest 校验失败 → fail-fast raise PluginError。"""
    bad_dir = tmp_path / "plugins" / "bad"
    bad_dir.mkdir(parents=True)
    # YAML 顶层是 list 而非 dict → ManifestValidationError → 翻译为 PluginError
    (bad_dir / "platform.yaml").write_text("- item1\n- item2\n", encoding="utf-8")

    with pytest.raises(PluginError) as exc_info:
        PlatformPluginRegistry.discover(tmp_path / "plugins")

    assert "bad" in str(exc_info.value) or "mapping" in str(exc_info.value).lower()


def test_discover_duplicate_name_raises(fresh_registry, tmp_path: Path) -> None:
    """两个不同目录的 platform.yaml 声明同一 name → PluginError("duplicate")。"""
    fixture = FIXTURES_DIR / "manifest_valid.yaml"
    for sub in ["huly1", "huly2"]:
        d = tmp_path / "plugins" / sub
        d.mkdir(parents=True)
        shutil.copy(fixture, d / "platform.yaml")

    with pytest.raises(PluginError, match="duplicate"):
        PlatformPluginRegistry.discover(tmp_path / "plugins")


def test_discover_skips_dirs_without_platform_yaml(
    fresh_registry, tmp_path: Path
) -> None:
    """子目录无 platform.yaml 时静默跳过（CI / docs 目录常见）。"""
    # huly 有 manifest
    huly_dir = tmp_path / "plugins" / "huly"
    huly_dir.mkdir(parents=True)
    shutil.copy(FIXTURES_DIR / "manifest_valid.yaml", huly_dir / "platform.yaml")

    # docs / __pycache__ 无 manifest（应跳过）
    (tmp_path / "plugins" / "docs").mkdir()
    (tmp_path / "plugins" / "__pycache__").mkdir()
    (tmp_path / "plugins" / "docs" / "README.md").write_text("# docs", encoding="utf-8")

    loaded = PlatformPluginRegistry.discover(tmp_path / "plugins")
    assert len(loaded) == 1
    assert loaded[0].name == "huly"


# ── get_plugin 相关测试（3 个） ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_plugin_lazy_returns_same_instance(
    fresh_registry, plugins_dir_with_huly: Path
) -> None:
    """同 workspace 二次 get_plugin 返回缓存的同一 instance（懒加载语义）。"""
    PlatformPluginRegistry.discover(plugins_dir_with_huly)

    ws = uuid.uuid4()
    p1 = await PlatformPluginRegistry.get_plugin(ws, "huly")
    p2 = await PlatformPluginRegistry.get_plugin(ws, "huly")

    assert p1 is not None
    assert p2 is not None
    assert p1 is p2  # 关键：缓存语义（懒加载）
    assert p1.name == "huly"
    assert p1.daemon is None  # Plan 04 暂未注入 daemon


@pytest.mark.asyncio
async def test_two_workspaces_isolated(
    fresh_registry, plugins_dir_with_huly: Path
) -> None:
    """**Pitfall 5 关键验证**：双 workspace 调同 plugin 拿不同 instance。

    防护：_PLUGINS dict key 是 (workspace_id, plugin_name) tuple。
    若实现错为单 dict[plugin_name] → 两个 workspace 拿同 instance → 串户事故。
    """
    PlatformPluginRegistry.discover(plugins_dir_with_huly)

    ws_a = uuid.uuid4()
    ws_b = uuid.uuid4()

    plugin_a = await PlatformPluginRegistry.get_plugin(ws_a, "huly")
    plugin_b = await PlatformPluginRegistry.get_plugin(ws_b, "huly")

    assert plugin_a is not None
    assert plugin_b is not None
    assert plugin_a is not plugin_b  # 关键：双 workspace 隔离
    # 但 manifest 是只读共享的（同一引用）
    assert plugin_a.manifest is plugin_b.manifest


@pytest.mark.asyncio
async def test_get_plugin_unknown_returns_none(
    fresh_registry, plugins_dir_with_huly: Path
) -> None:
    """未 discover 的 plugin 返回 None（不 raise）。"""
    PlatformPluginRegistry.discover(plugins_dir_with_huly)
    ws = uuid.uuid4()
    result = await PlatformPluginRegistry.get_plugin(ws, "nonexistent_plugin")
    assert result is None


# ── get_capability 相关测试（4 个）────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_capability_im_returns_facade(
    fresh_registry, plugins_dir_with_huly: Path
) -> None:
    """按 IMCapability 类型查 → 返回 IMFacade stub（Plan 05 接入 daemon 后变真转发）。"""
    PlatformPluginRegistry.discover(plugins_dir_with_huly)
    ws = uuid.uuid4()

    cap = await PlatformPluginRegistry.get_capability(ws, IMCapability, prefer="huly")
    assert cap is not None
    assert isinstance(cap, IMFacade)  # Plan 04 stub class

    # 类似检查其他 capability —— huly fixture 含 im/doc/hr/identity 4 个
    doc_cap = await PlatformPluginRegistry.get_capability(ws, DocCapability)
    assert isinstance(doc_cap, DocFacade)

    hr_cap = await PlatformPluginRegistry.get_capability(ws, HRCapability)
    assert isinstance(hr_cap, HRFacade)

    identity_cap = await PlatformPluginRegistry.get_capability(ws, IdentityCapability)
    assert isinstance(identity_cap, IdentityFacade)


@pytest.mark.asyncio
async def test_get_capability_missing_returns_none(
    fresh_registry, plugins_dir_with_huly: Path
) -> None:
    """huly manifest 未声明 trigger → get_capability(TriggerCapability) 返回 None（fail-quiet）。"""
    PlatformPluginRegistry.discover(plugins_dir_with_huly)
    ws = uuid.uuid4()

    cap = await PlatformPluginRegistry.get_capability(ws, TriggerCapability)
    assert cap is None  # 关键：不 raise，fail-quiet 决策


@pytest.mark.asyncio
async def test_get_capability_prefer_works(fresh_registry, tmp_path: Path) -> None:
    """prefer 参数让指定 plugin 排第一位（影响 multi-plugin 同 capability 时选择）。"""
    # 安装两个 plugin 都支持 im：huly + alt_im
    fixture = FIXTURES_DIR / "manifest_valid.yaml"

    huly_dir = tmp_path / "plugins" / "huly"
    huly_dir.mkdir(parents=True)
    shutil.copy(fixture, huly_dir / "platform.yaml")

    # 第二个 plugin 改 name 为 alt_im，仅声明 im
    alt_dir = tmp_path / "plugins" / "alt_im"
    alt_dir.mkdir(parents=True)
    alt_manifest = (
        "name: alt_im\n"
        "version: 1.0.0\n"
        "description: 'alternative IM plugin'\n"
        "runtime:\n"
        "  type: python\n"
        "  entry: alt_im.main\n"
        "capabilities:\n"
        "  - im\n"
        "config_schema: {}\n"
    )
    (alt_dir / "platform.yaml").write_text(alt_manifest, encoding="utf-8")

    PlatformPluginRegistry.discover(tmp_path / "plugins")
    ws = uuid.uuid4()

    # prefer="alt_im" → 返回 alt_im 的 facade
    cap_alt = await PlatformPluginRegistry.get_capability(
        ws, IMCapability, prefer="alt_im"
    )
    plugin_alt = await PlatformPluginRegistry.get_plugin(ws, "alt_im")
    assert cap_alt is plugin_alt.im

    # prefer="huly" → 返回 huly 的 facade
    cap_huly = await PlatformPluginRegistry.get_capability(
        ws, IMCapability, prefer="huly"
    )
    plugin_huly = await PlatformPluginRegistry.get_plugin(ws, "huly")
    assert cap_huly is plugin_huly.im


@pytest.mark.asyncio
async def test_get_capability_unknown_type_returns_none(
    fresh_registry, plugins_dir_with_huly: Path
) -> None:
    """未知 capability type（不在 _CAPABILITY_TYPE_TO_NAME 表）→ 返回 None。"""
    PlatformPluginRegistry.discover(plugins_dir_with_huly)
    ws = uuid.uuid4()

    class UnknownCapability:
        """模拟未知 capability 类型（不在 6 capability 中）。"""

    cap = await PlatformPluginRegistry.get_capability(ws, UnknownCapability)
    assert cap is None


# ── 辅助方法（1 个）──────────────────────────────────────────────────────────


def test_list_manifests_returns_loaded(
    fresh_registry, plugins_dir_with_huly: Path
) -> None:
    """list_manifests 返回所有 discover 的 manifest（read-only snapshot）。"""
    assert PlatformPluginRegistry.list_manifests() == []

    PlatformPluginRegistry.discover(plugins_dir_with_huly)
    manifests = PlatformPluginRegistry.list_manifests()
    assert len(manifests) == 1
    assert manifests[0].name == "huly"
