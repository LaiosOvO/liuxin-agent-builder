"""Phase 4.5 IM Bot Dispatcher — 业务层 dispatcher / parser / llm_router / handler registry / listener。

模块边界（与 Phase 5.A platforms/ 平级）：
- platforms/      — Capability Protocol 层（IMCapability / DocCapability 等抽象）
- bot_dispatcher/ — IM 入站业务 dispatcher（本包，绑定 Mattermost 第一 provider）
- notification/   — 出站通知 provider（Phase 4 既有，不重叠）

子模块（Wave 1 仅落以下 2 个，Wave 2-5 补全）：
- schemas/        — bot.yaml Pydantic v2 schema（BotConfig + 12 子 model）
- httpx_patch.py  — Pitfall 2 兼容垫片（httpx 0.28+ vs mattermostautodriver 2.0）

后续 Wave（不在本 plan）将新增：
- loader.py / parser.py / llm_router.py / registry.py / context.py / dispatcher.py
- rate_limiter.py / idempotency.py / audit.py
- builtin/{help,workflow,debug}.py
- listeners/{base,mattermost}.py
"""
from __future__ import annotations
