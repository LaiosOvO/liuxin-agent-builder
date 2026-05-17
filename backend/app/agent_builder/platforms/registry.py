"""Phase 5.A PlatformPluginRegistry —— per-workspace 隔离 + 启动期 discover + 懒加载（PLUG-FW-03）。

设计要点（ADR-001 §6 + CONTEXT.md decisions + RESEARCH.md §5）：

1. **启动期扫描**：`discover(plugins_root)` 扫描 `plugins/*/platform.yaml` → load manifest 入
   `_MANIFESTS` 全局 dict（仅 metadata，不 spawn daemon —— Pitfall 9 防隐性 daemon 启动）

2. **per-workspace 隔离**（Pitfall 5 核心防护）：
   - `_PLUGINS` 内部 key 是 `(workspace_id, plugin_name)` tuple
   - 同 plugin 在不同 workspace 拿不同 PlatformPlugin instance
   - 单 daemon process 一对一 workspace × plugin（v1 决策；v1.5 可考虑共享）

3. **懒加载 daemon**：
   - `discover()` 仅 load manifest，**不 spawn daemon**
   - `get_plugin(workspace_id, plugin_name)` 首次访问才 instantiate PlatformPlugin
   - Plan 04 暂 daemon=None；Plan 05+ 内部 spawn PlatformDaemonClient

4. **get_capability** 按 Capability 类型路由（替代直接 `get_plugin(...).im`）：
   - `get_capability(workspace_id, IMCapability, prefer="huly")` 找首个声明 IM 的 plugin
   - 缺 capability 返回 None（fail-quiet —— CONTEXT.md 决策）
   - 调用方显式 `if cap is None: log + skip`

5. **classmethod-only 设计**（借鉴 Dify PluginService 静态方法）：
   - 进程级 singleton（_MANIFESTS / _PLUGINS 模块级 class var）
   - 测试用 `clear()` fixture 隔离
   - 无实例状态 —— 多 worker 共享同一 Registry（manifest 只读 + plugin lazy create）

Reference:
- docs/reading-dify-05a-04-manifest-registry-2026-05-17.md §借鉴点 #3/4/5/6
- Dify api/services/plugin/plugin_service.py:45+ (PluginService static methods, AGPL-3.0)
本 module 100% 独立创作（不拷 Dify ORM session 模式 / 不拷 PluginInstaller 通信层）。
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from .exceptions import PluginError
from .manifest import PlatformManifest, load_manifest
from .plugin import PlatformPlugin

_log = logging.getLogger(__name__)


# ── Capability 类型名映射 ─────────────────────────────────────────────────────


_CAPABILITY_TYPE_TO_NAME: dict[str, str] = {
    "IMCapability": "im",
    "DocCapability": "doc",
    "HRCapability": "hr",
    "IdentityCapability": "identity",
    "TriggerCapability": "trigger",
    "ToolCapability": "tool",
}


def _capability_type_to_name(t: type) -> str | None:
    """`IMCapability` → `"im"` / `DocCapability` → `"doc"` / ...

    用类型 `__name__` 做映射（vs `__qualname__` 含 module 前缀）。
    未知 capability type 返回 None。
    """
    return _CAPABILITY_TYPE_TO_NAME.get(t.__name__)


# ── Registry（进程级 singleton 通过模块级 class var 实现）─────────────────────


class PlatformPluginRegistry:
    """全局 Registry —— 进程级 singleton（classmethod-only + 模块级 class var）。

    用法：
        # 启动期（main / lifespan startup）
        PlatformPluginRegistry.discover("plugins/")

        # 运行时（节点执行 / API handler）
        plugin = await PlatformPluginRegistry.get_plugin(workspace_id, "huly")
        if plugin and plugin.im:
            msg_ref = await plugin.im.send_card(...)

        # 或按 capability 类型查（不知道 plugin 名）
        im_cap = await PlatformPluginRegistry.get_capability(
            workspace_id, IMCapability, prefer="huly"
        )

    测试隔离：
        @pytest.fixture
        def fresh_registry():
            PlatformPluginRegistry.clear()
            yield
            PlatformPluginRegistry.clear()
    """

    # 模块级状态（class var）—— 进程内多 worker 共享
    _MANIFESTS: dict[str, PlatformManifest] = {}
    _PLUGINS: dict[tuple[uuid.UUID, str], PlatformPlugin] = {}

    # ── 测试用清空 ─────────────────────────────────────────────────────────────

    @classmethod
    def clear(cls) -> None:
        """清空全部 manifest / plugin 缓存 —— 测试 fixture 用。

        生产期不应调用（除非热重载 plugin —— Phase 5.A v1 不支持，留 v2）。
        """
        cls._MANIFESTS.clear()
        cls._PLUGINS.clear()

    # ── discover（启动期扫描）──────────────────────────────────────────────────

    @classmethod
    def discover(cls, plugins_root: str | Path) -> list[PlatformManifest]:
        """启动期扫描 plugins/*/platform.yaml → 校验 → 入 _MANIFESTS dict。

        扫描规则：
        - 仅扫一级子目录（`plugins/<plugin_name>/platform.yaml`，不递归）
        - 子目录名不需与 manifest.name 一致（manifest.name 才是唯一标识）
        - 无 platform.yaml 的子目录静默跳过（CI / docs 文件夹常见）

        失败处理（fail-fast，启动期阻断）：
        - 任一 manifest 校验失败 → raise PluginError（含原 ManifestValidationError chain）
        - 两个不同目录的 platform.yaml 声明同一 name → raise PluginError("duplicate")

        Returns:
            list[PlatformManifest]: 成功 load 的 manifest 列表（按目录名排序）

        Raises:
            PluginError: 任一文件解析失败 / 重复 name
        """
        root = Path(plugins_root)

        if not root.is_dir():
            _log.warning("plugins root %s 不存在，跳过 discover", root)
            return []

        loaded: list[PlatformManifest] = []

        for plugin_dir in sorted(root.iterdir()):
            if not plugin_dir.is_dir():
                continue

            manifest_path = plugin_dir / "platform.yaml"
            if not manifest_path.is_file():
                continue

            try:
                manifest = load_manifest(manifest_path)
            except Exception as e:
                raise PluginError(
                    f"failed to load manifest from {manifest_path}: {e}"
                ) from e

            if manifest.name in cls._MANIFESTS:
                raise PluginError(
                    f"duplicate plugin name '{manifest.name}' "
                    f"(already loaded; conflict at {manifest_path})"
                )

            cls._MANIFESTS[manifest.name] = manifest
            loaded.append(manifest)
            _log.info(
                "registered plugin manifest: name=%s version=%s capabilities=%s",
                manifest.name,
                manifest.version,
                manifest.capabilities,
            )

        return loaded

    # ── manifest metadata accessors ────────────────────────────────────────────

    @classmethod
    def list_manifests(cls) -> list[PlatformManifest]:
        """列出已 discover 的所有 manifest（read-only snapshot）。"""
        return list(cls._MANIFESTS.values())

    @classmethod
    def get_manifest(cls, plugin_name: str) -> PlatformManifest | None:
        """按 plugin name 查 manifest（未找到返回 None）。"""
        return cls._MANIFESTS.get(plugin_name)

    # ── per-workspace plugin instance（懒加载）────────────────────────────────

    @classmethod
    async def get_plugin(
        cls,
        workspace_id: uuid.UUID,
        plugin_name: str,
    ) -> PlatformPlugin | None:
        """获取 per-workspace plugin 实例（首次创建，二次缓存）。

        Pitfall 5 防护：内部 key 是 `(workspace_id, plugin_name)` tuple，
        双 workspace 调同 plugin_name 返回不同 instance。

        Args:
            workspace_id: 所属 workspace（CLAUDE.md §2.4 多租户基线）
            plugin_name: manifest.name（小写蛇形）

        Returns:
            PlatformPlugin: 缓存或新创建的 instance
            None: manifest 未 discover 过

        Note:
            Phase 5.A Plan 04 暂不强制要求 plugin 已在 DB workspace_plugin_installations
            表 install；Plan 05+ install lifecycle 接入后再加 DB 校验（按 status='installed' 过滤）。
        """
        key = (workspace_id, plugin_name)

        # 二次访问：返回缓存
        if key in cls._PLUGINS:
            return cls._PLUGINS[key]

        # 首次访问：查 manifest，若有则 instantiate
        manifest = cls._MANIFESTS.get(plugin_name)
        if manifest is None:
            return None

        # Plan 04 暂 daemon=None；Plan 05 在此 spawn PlatformDaemonClient
        plugin = PlatformPlugin(manifest=manifest, daemon=None)
        cls._PLUGINS[key] = plugin

        _log.debug(
            "instantiated plugin for workspace: workspace_id=%s plugin=%s",
            workspace_id,
            plugin_name,
        )
        return plugin

    # ── get_capability（按 capability type 路由）─────────────────────────────

    @classmethod
    async def get_capability(
        cls,
        workspace_id: uuid.UUID,
        capability_type: type,
        *,
        prefer: str | None = None,
    ) -> Any | None:
        """按 capability 类型查可用 plugin facade。

        路由逻辑：
        1. capability_type 翻译为 cap_name（IMCapability → "im"）— 未知 type 返回 None
        2. 候选 plugin 列表：prefer（若指定且在 _MANIFESTS）放第一 + 其余 _MANIFESTS 顺序
        3. 遍历候选，找首个声明该 capability 的 plugin，返回其 facade
        4. 全部 candidates 都不支持 → 返回 None（fail-quiet）

        Args:
            workspace_id: 所属 workspace（per-workspace 隔离）
            capability_type: 6 Capability Protocols 之一（IMCapability/DocCapability/...）
            prefer: 优先选此 plugin（按 manifest.name）；若未声明该 capability 跳过

        Returns:
            facade instance（Plan 04 stub 阶段方法 raise NotImplementedError）
            None: 无任何 plugin 声明此 capability（fail-quiet 决策）

        Note:
            v1 Plan 04 fail-quiet 返回 None；调用方需显式 `if cap is None: log + fallback`
            （CONTEXT.md 决策；vs raise 让节点执行不中断）
        """
        cap_name = _capability_type_to_name(capability_type)
        if cap_name is None:
            _log.debug(
                "unknown capability type %s; returning None", capability_type.__name__
            )
            return None

        # 候选列表：prefer 优先 + 其余 _MANIFESTS 顺序（dict 是 ordered Python 3.7+）
        candidates: list[str] = []
        if prefer and prefer in cls._MANIFESTS:
            candidates.append(prefer)
        for name in cls._MANIFESTS:
            if name not in candidates:
                candidates.append(name)

        for name in candidates:
            manifest = cls._MANIFESTS[name]
            if cap_name not in manifest.capabilities:
                continue

            plugin = await cls.get_plugin(workspace_id, name)
            if plugin is None:
                continue

            facade = getattr(plugin, cap_name, None)
            if facade is not None:
                return facade

        # ── Blocker 3 修复：fallback 到 _PROVIDERS_AS_CAP（LegacyAdapter wrapped）─
        #
        # 当 manifest plugin 没声明该 capability 时，查 Phase 4 老 IMProvider 双轨注册表
        # 让"Phase 4 6 家 provider 通过 get_capability(IMCapability) 调到"承诺真正落地。
        #
        # 仅适用 cap_name == "im"（其他 capability 不存在 LegacyAdapter）：
        # - prefer 优先（与 manifest plugin 路由保持语义一致）
        # - 否则按 sorted name 取首个（确定性 fallback）
        # - ImportError 捕获保证 notification.providers.base 未加载时静默失败（fail-quiet）
        #
        # 参考：docs/reading-dify-05a-06-legacy-adapter-2026-05-17.md
        # 借鉴点 1（双轨并存）+ 借鉴点 2（失败容忍 + 静默降级）
        if cap_name == "im":
            try:
                from app.agent_builder.notification.providers.base import (
                    _PROVIDERS_AS_CAP,
                )
            except ImportError:
                return None

            # prefer 优先
            if prefer and prefer in _PROVIDERS_AS_CAP:
                return _PROVIDERS_AS_CAP[prefer]
            # 否则返回任一已注册的 legacy adapter（按 name 排序确定性）
            for name in sorted(_PROVIDERS_AS_CAP.keys()):
                return _PROVIDERS_AS_CAP[name]

        return None


__all__ = ["PlatformPluginRegistry"]
