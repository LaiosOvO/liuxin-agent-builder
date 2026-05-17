"""bot.yaml schema 子包 — 显式导出 BotConfig + 全 12 子模型。

设计依据：
- docs/plans/2026-05-17-im-bot-abstraction-design.md §4 bot.yaml schema 设计
- docs/reading-dify-04_5-01-trigger-nodes-2026-05-18.md §可借鉴的设计模式 #1-#4
- Phase 5.A platforms/manifest.py 一致 ConfigDict(extra="forbid") 模式

导出清单：
- BotConfig            — 顶层 schema（含 3 个 @model_validator）
- ProviderSpec         — IM 平台标识 + env 前缀
- TriggersSpec         — DM / @mention / keywords 三 OR
- IdentitySpec         — sender → users 表对齐策略
- CommandSpec          — 单命令声明（name / args / handler / allowed_roles）
- CommandArg           — 单参数声明（type / pattern / choices / multiline）
- SelfApplySpec        — 自助起流程模式（自然语言短路）
- FallbackSpec         — 命令失败兜底（LLM router + ai_qa）
- LLMIntentRouterSpec  — LLM 意图分类（confidence_threshold + timeout）
- AIQaSpec             — 自由问答兜底配置
- RateLimitSpec        — per_user_per_minute 限流配置（R-IM-12）
- AuditSpec            — dispatch 审计开关（R-IM-11）
- HelpSpec             — help 命令自动生成配置（R-IM-03）
"""
from __future__ import annotations

from app.agent_builder.bot_dispatcher.schemas.bot_config import (
    AIQaSpec,
    AuditSpec,
    BotConfig,
    CommandArg,
    CommandSpec,
    FallbackSpec,
    HelpSpec,
    IdentitySpec,
    LLMIntentRouterSpec,
    ProviderSpec,
    RateLimitSpec,
    SelfApplySpec,
    TriggersSpec,
)

__all__ = [
    "BotConfig",
    "ProviderSpec",
    "TriggersSpec",
    "IdentitySpec",
    "CommandSpec",
    "CommandArg",
    "SelfApplySpec",
    "FallbackSpec",
    "LLMIntentRouterSpec",
    "AIQaSpec",
    "RateLimitSpec",
    "AuditSpec",
    "HelpSpec",
]
