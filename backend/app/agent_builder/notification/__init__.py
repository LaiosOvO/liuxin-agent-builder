"""notification 模块 — Phase 4 IM 抽象层 + Phase 3 邮件通知。

子模块：
- providers/ — IMProvider Protocol + Registry + 5 家 Provider 实现（04-05 抽象 + 04-06..09 具体实现）
- cards/ — 卡片构造抽象（各 Provider 自实现 build_*_card）

Phase 3 已有 backend/app/services/notification_service.py（邮件入队），
Phase 4 扩展到 IM 多通道并发投递（Plan 04-10）— notification_service 增加
enqueue_hitl_multichannel 方法。
"""
