"""Phase 5.A PlatformPlugin 顶层类 —— lazy facade 模式（ADR-001 §5 + RESEARCH.md §Pattern 4）。

设计要点：

- 一个 plugin 1 instance（plus 1 daemon 进程，Plan 05 实例化）
- 多 capability bundle：`@property im / doc / hr / identity` 4 facade 都 wrap 同一 `_daemon`
- lazy 缓存：首次访问 `.im` 时 instantiate IMFacade 入 `_cap_cache`，二次访问返回 cache
- daemon 注入：Plan 04 暂 None；Plan 05 通过 `attach_daemon(daemon)` 注入

Phase 5.A Plan 04（本 plan）：
- PlatformPlugin shell + 4 facade lazy property
- daemon 字段为 None —— Plan 05 加入 PlatformDaemonClient + Plan 06 JSONRPC over stdio
- capability_facades 4 stub class 已建（capability_facades.py 同 plan 创建）

Phase 5.A Plan 05+ 演进：
- LegacyIMProviderAdapter 让 Phase 4 6 家 IMProvider 通过新 IMCapability 接口被调用
- PlatformDaemonClient JSONRPC over stdio 真接入
- facade `await self._daemon.invoke(...)` 真转发

Phase 5.A Plan 07 (Huly acid test)：
- discover → get_plugin → plugin.im.send_card → daemon stdin → daemon → mock huly server → daemon stdout → MessageRef 端到端

Reference:
- docs/reading-dify-05a-04-manifest-registry-2026-05-17.md §借鉴点 #6（启动期 vs 懒加载分离）
- Dify api/core/plugin/entities/plugin.py:143-167 (PluginInstallation / PluginEntity, AGPL-3.0)
本 module 100% 独立创作，仅借鉴 lazy facade 思路。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .manifest import PlatformManifest

if TYPE_CHECKING:
    from .capabilities import (
        DocCapability,
        HRCapability,
        IdentityCapability,
        IMCapability,
    )
    from .daemon_client import PlatformDaemonClient  # Plan 06 创建


class PlatformPlugin:
    """一个外部平台 / 工具 / 服务 plugin（可多 capability bundle）。

    Attributes:
        _manifest: 此 plugin 的 manifest（discover 期 load）
        _daemon: PlatformDaemonClient 实例（Plan 04 暂 None；Plan 05 注入）
        _cap_cache: capability facade lazy 缓存（"im"/"doc"/... → facade instance）

    用法（v1.1 Plan 05 完整链路）：
        manifest = load_manifest("plugins/huly/platform.yaml")
        daemon = PlatformDaemonClient(manifest)  # Plan 05/06
        plugin = PlatformPlugin(manifest, daemon)
        if plugin.im:
            msg_ref = await plugin.im.send_card(
                recipient=RecipientSpec(kind="channel", id="general"),
                card=NormalizedCard(title="...", body_markdown="...", actions=[]),
                idempotency_key="..."
            )
    """

    def __init__(
        self,
        manifest: PlatformManifest,
        daemon: PlatformDaemonClient | None = None,
    ) -> None:
        self._manifest = manifest
        self._daemon = daemon  # None 表示尚未实例化 daemon（懒加载）
        self._cap_cache: dict[str, Any] = {}

    # ── 只读元数据 ─────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        """Plugin 唯一名（manifest.name）。"""
        return self._manifest.name

    @property
    def manifest(self) -> PlatformManifest:
        """完整 manifest（只读访问）。"""
        return self._manifest

    @property
    def daemon(self) -> PlatformDaemonClient | None:
        """当前 daemon 实例（Plan 04 期返回 None）。"""
        return self._daemon

    # ── daemon 注入（Plan 05 演进点）─────────────────────────────────────────────

    def attach_daemon(self, daemon: PlatformDaemonClient) -> None:
        """Registry 懒加载时调用 —— 注入 daemon 实例。

        Plan 04 不会被调（Registry 不创建 daemon），但接口预留 Plan 05+ 用。
        重复 attach 抛 RuntimeError 防误用（每 plugin 1 daemon 严格 1:1）。
        """
        if self._daemon is not None:
            raise RuntimeError(
                f"PlatformPlugin '{self.name}' 已 attach daemon，不允许重复 attach"
            )
        self._daemon = daemon

    # ── Capability lazy properties（4 facade，共享 daemon）────────────────────

    @property
    def im(self) -> IMCapability | None:
        """IM capability facade（若 manifest 声明 im）。

        Plan 04 stub：返回 IMFacade 实例（方法 raise NotImplementedError）
        Plan 05+：真转发到 `await self._daemon.invoke("im", method, **kwargs)`
        """
        if "im" not in self._manifest.capabilities:
            return None
        if "im" not in self._cap_cache:
            from .capability_facades import IMFacade

            self._cap_cache["im"] = IMFacade(self._daemon, self._manifest)
        return self._cap_cache["im"]

    @property
    def doc(self) -> DocCapability | None:
        """Doc capability facade（若 manifest 声明 doc）。"""
        if "doc" not in self._manifest.capabilities:
            return None
        if "doc" not in self._cap_cache:
            from .capability_facades import DocFacade

            self._cap_cache["doc"] = DocFacade(self._daemon, self._manifest)
        return self._cap_cache["doc"]

    @property
    def hr(self) -> HRCapability | None:
        """HR capability facade（若 manifest 声明 hr）。"""
        if "hr" not in self._manifest.capabilities:
            return None
        if "hr" not in self._cap_cache:
            from .capability_facades import HRFacade

            self._cap_cache["hr"] = HRFacade(self._daemon, self._manifest)
        return self._cap_cache["hr"]

    @property
    def identity(self) -> IdentityCapability | None:
        """Identity capability facade（若 manifest 声明 identity）。"""
        if "identity" not in self._manifest.capabilities:
            return None
        if "identity" not in self._cap_cache:
            from .capability_facades import IdentityFacade

            self._cap_cache["identity"] = IdentityFacade(self._daemon, self._manifest)
        return self._cap_cache["identity"]

    # ── repr 便于调试 / log ─────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"<PlatformPlugin name={self.name!r} "
            f"version={self._manifest.version!r} "
            f"capabilities={self._manifest.capabilities} "
            f"daemon_attached={self._daemon is not None}>"
        )


__all__ = ["PlatformPlugin"]
