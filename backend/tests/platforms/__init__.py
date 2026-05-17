"""Phase 5.A platforms 单元测试包。

测试范围（Wave 1-6 累积填充）：
- Capability Protocols 类型签名（plan 02）
- Manifest Pydantic schema 校验（plan 03）
- PlatformPluginRegistry per-workspace 隔离（plan 04）
- LegacyIMProviderAdapter Phase 4 零 regression（plan 05）
- PlatformDaemonClient JSONRPC 单元（plan 06）
- MockPlatformPlugin 多 capability negotiation（plan 06）
- Migration 0006 smoke test（plan 01 本 plan）

集成测试（真起 daemon 子进程 / mock huly server）在 tests/platforms_integration/。
"""
