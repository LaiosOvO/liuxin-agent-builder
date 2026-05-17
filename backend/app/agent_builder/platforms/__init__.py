"""Phase 5.A PlatformPlugin 框架（ADR-001）。

通用拖拽式 LangGraph 编排平台的「插件子系统」入口包。
本包定义：
- exceptions: PluginError 家族（Plan 02）
- capabilities/: 6 Capability Protocols（Plan 02 起逐 plan 实现）
- manifest: PlatformManifest Pydantic schema（Plan 03 实现）
- registry: PlatformPluginRegistry per-workspace 隔离（Plan 04 实现）
- legacy_im_adapter: Phase 4 IMProvider → IMCapability 适配（Plan 05 实现）
- daemon_client: JSONRPC over stdio（Plan 06 实现）

Reference: docs/plans/2026-05-17-platform-plugin-framework-ADR.md (ADR-001 Accepted)。
"""
