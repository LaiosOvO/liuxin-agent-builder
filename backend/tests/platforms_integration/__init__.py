"""Phase 5.A platforms 集成测试包。

集成测真起 daemon 子进程 + mock huly server，验证：
- HulyPlugin acid test 端到端 JSONRPC roundtrip（plan 07）
- Fault isolation（daemon 崩溃，主进程不受影响）（plan 07）
- Workspace 隔离 + daemon 共享底层 client facade（plan 07）

与 tests/platforms/ 区别：本目录测试真实 spawn subprocess，慢但贴近生产。
"""
