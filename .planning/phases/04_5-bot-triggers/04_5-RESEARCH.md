# Phase 4.5: Bot Triggers + Slash 分发 + Reply (双向 IM) - Research

**Researched:** 2026-05-18
**Domain:** IM Bot 入站 dispatcher（WebSocket listener + 命令解析 + LLM intent router + handler 注册表 + 身份对齐 + 速率限制 + 审计），Mattermost 第一 provider 落地
**Confidence:** HIGH（核心模式 / 库版本 / 集成路径均有 reference impl 或既有 Phase 4-5.A 代码可对照）

## Summary

Phase 4.5 是 **业务层 dispatcher**（不是 Capability Protocol 层），跑在 agent-builder 主进程内（v1 不沙箱化），负责把"IM 用户消息 → workflow 触发"这条链路从空白补齐。它**与 Phase 5.A 的 PlatformPlugin / IMCapability.subscribe_events 不冲突**——本 phase 用既有 Phase 4 IMProvider 子集（Mattermost）+ 新增 listener / dispatcher / handler registry / intent router 4 类组件，Phase 5.B+ 后由 PlatformPlugin daemon 提供同样的 subscribe stream 时，listener 实现可以增量替换为 IMCapability.subscribe_events 消费方式（v1 不强制走 daemon——bot listener 是平台代码不是第三方插件）。

hr/offboarding-flow 已有完整 reference impl（mattermost_listener.py 254 行 / bot_command_parser.py 204 行 / bot_intent_router.py 137 行 / bot_handler_registry.py 89 行 / bot_service.py 736 行），核心模式可直接 port 并去掉硬编码：白名单命令从配置驱动、handler 通过 entry-point 字符串解析、intent router prompt 模板化。

设计稿 docs/plans/2026-05-17-im-bot-abstraction-design.md 已明确 13 个 R-IM 需求 + bot.yaml schema + 4 子阶段拆分（5.A/5.B/5.C/5.D）。本 phase 收编原稿 5.A（基础抽象）+ 5.B（LLM intent router）+ 单 provider 落地（Mattermost），其他 IM provider 后移到 Phase 5.E。

**Primary recommendation:** Wave 1 先落 bot.yaml Pydantic schema + DB schema（workspace_bot_installations + bot_audit_logs + bot_rate_limits）+ Alembic 0007 → Wave 2 并行做 BotConfig loader / BotIntentRouter / HandlerRegistry / BotContext → Wave 3 写 BotDispatcher 串接 → Wave 4 MattermostListener 接入（基于既有 Phase 4 MattermostProvider 扩展入站方法）→ Wave 5 builtin handlers（help / status / list / start）+ rate limit + audit → Wave 6 browser-harness E2E gate（4 个 Safe Links UA 矩阵 + Mattermost 容器实测）。预估 6 plans / 14-18 天。

## User Constraints (from OUTLINE.md + additional_context)

### Locked Decisions

- **Provider 范围**：Mattermost P0 落地；飞书/企微/钉钉/Slack 入站留 Phase 5.E（不在本 phase）
- **listener 部署**：主进程 worker（asyncio.create_task），v1 **不沙箱化** bot listener（bot 代码是 agent-builder 平台代码不是第三方插件 — Phase 5.B 沙箱只服务第三方 plugin）
- **bot.yaml 存储**：文件系统 `plugins/bots/<name>.yaml` + DB `workspace_bot_installations` 表（与 Phase 5.A plugin 模式一致 hybrid）
- **handler 函数**：v1 平台内置（agent-builder 仓库内的 Python 模块），不允许 workspace 上传 — workspace handler 留 Phase 6 plugin marketplace
- **LLM intent router**：复用 agent-builder 已配置 LLM provider（GLM / OpenAI 兼容）— 不引入新 LLM SDK
- **测试栈**：pytest + browser-use/browser-harness（CDP 直连 Chrome）—— 禁 Playwright / webapp-testing skill（用户 2026-05-17 硬性指令，详 memory feedback_e2e_browser_harness_only.md）
- **结构化日志**：每 dispatch + LLM call 必带 capability/method/latency/workspace_id/bot_name 字段（Phase 7 Run Viewer 钩子，memory feedback_node_visualization.md）
- **Dify reading doc gate**：Wave 1 第一个 commit 必须是 reading doc（CLAUDE.md §2.7 硬性 gate）— 本 phase 必读 Dify trigger 模块（`api/core/trigger/` + `api/core/workflow/nodes/trigger_webhook/`）

### Claude's Discretion

- **WebSocket 重连策略**：5s 指数退避 vs 固定间隔（推荐固定 5s + jitter ±2s — 与 reference impl 一致 + 加 jitter 防雷击）
- **rate limit 实现**：Redis SET NX + EXPIRE 计数器 vs 滑动窗口（推荐 fixed-window counter — per_user_per_minute=10 简单足够）
- **idempotency_key 格式**：sha256(workspace_id + bot_name + sender_user_id + message_text + minute_bucket) vs message_id（推荐 sha256，防 IM 重推 + 防用户秒重发）
- **bot dispatcher 命令冲突解决**：keywords 优先 vs LLM 优先（推荐 keywords > slash_command > LLM intent — 命中三层任一立即短路）
- **structured log schema**：bot.dispatch.* / bot.listener.* 名空间（推荐与 Phase 4 `im.card.send` 同模式）
- **YAML loader 库**：PyYAML（已是依赖） vs ruamel.yaml（推荐 PyYAML — Phase 5.A 已用）
- **bot.yaml schema 字段聚合 vs 拆分**：推荐 v1 聚合到单一 BotConfig pydantic class（Phase 5.A manifest.py 同模式）

### Deferred Ideas (OUT OF SCOPE)

- 飞书/企微/钉钉/Slack 入站 listener（Phase 5.E）
- DAG IM Trigger 节点 / IM Reply 节点 — 工作流图上的节点形态（Phase 5.E DAG 整合）
- bot.yaml 可视化编辑 UI（v2，画布扩展）
- bot 配置 hot reload SIGHUP（v2）
- 多语言 i18n bot 回复（v1 中文）
- workspace 上传自定义 handler（Phase 6 plugin marketplace）
- handler 函数沙箱（v1 平台代码不沙箱；Phase 6 第三方 handler 走 sandbox）
- bot 跨 workspace 共享账号（v1 每 workspace 独立 bot account 严隔离）
- 多 bot 共存于单 listener 进程（v1 每 bot 一个 listener task；R-IM-09 优化留 v1.5）
- Mattermost slash command 注册到 MM Admin Console API（v1 走 @-mention + DM + keywords 三触发；slash 命令本地 parser 识别即可，不向 MM 注册 trigger 词）

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| **R-IM-01** | YAML/JSON 配置驱动一个 bot：name / provider / triggers / commands / fallback / llm | bot.yaml Pydantic schema（§Standard Stack）+ Phase 5.A manifest.py 借鉴 ConfigDict(extra="forbid") |
| **R-IM-02** | 命令插件式注册（name / args_schema / handler_ref / allowed_roles） | hr/offboarding-flow bot_handler_registry.py 复用 + handler_ref importlib 解析（§Pattern HandlerRegistry） |
| **R-IM-03** | help 命令自动生成（按 allowed_roles 过滤当前 user 可见命令） | 元数据驱动 — 设计稿 §6.1 `handle_help` 模板渲染（builtin handler） |
| **R-IM-04** | LLM intent router（confidence threshold + ai_qa 兜底 + timeout） | hr bot_intent_router.py 复用 + Jinja2 prompt 模板（§Pattern IntentRouter） |
| **R-IM-05** | 触发条件：DM / @mention / keywords 三 OR | hr mattermost_listener._handle_event 触发逻辑（§Architecture Patterns Pattern 4） |
| **R-IM-06** | 身份对齐：sender_name → users 表查 role；失败 reject_friendly | Phase 1 users 表 + Phase 5.A IdentityCapability.resolve_user（§Architecture Patterns 身份对齐） |
| **R-IM-07** | self-apply 模式：自然语言短路 → 默认 sender 为 employee | hr bot_command_parser._SELF_APPLY_PHRASES + SELF_APPLY_SENTINEL pattern |
| **R-IM-11** | dispatch 失败 audit log 入库 | Phase 3 NET-05 audit_logs schema 复用 — 加 bot 子集字段（§Architecture Patterns Pattern 6） |
| **R-IM-12** | 命令限流 per_user_per_minute（Redis fixed-window counter） | Phase 1 redis.asyncio 已有 + Phase 3 HitlTokenStore SET NX 模式（§Don't Hand-Roll） |
| **R-IM-13** | 命令 idempotency_key（同 user 同 args N 秒内只跑一次） | Phase 3 HitlTokenStore jti 模式 + sha256 hash（§Architecture Patterns Pattern 7） |
| **N-IM-01** | 单 listener ≥ 50 msg/s 处理能力 | 主进程 asyncio + handler async（无 sync DB 调用瓶颈 — hr 测实 20/s 是 sync 原因） |
| **N-IM-02** | WS 断线自动重连指数退避（jitter 防雷击） | hr mattermost_listener._run while not stop loop + asyncio.sleep(5) + jitter ±2s |
| **N-IM-03** | 凭证仅 env 注入 / DB 加密存（不入 YAML） | Phase 4 IMCredentialsManager 复用 |
| **N-IM-04** | handler stdout/stderr 捕获到日志（不 leak 到 bot 回复） | dispatcher try/except + logger.exception 统一捕获（§Pitfall 4） |
| **N-IM-05** | LLM intent timeout（5s）超时不阻塞 dispatcher | hr LLMService.complete timeout=20s — 改为 5s + async timeout |

## Standard Stack

### Core (已锁定，Phase 1-5.A 已引入)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.12+ | 运行时 | pyproject `requires-python = ">=3.12"`（agent-builder 已锁） |
| FastAPI | ≥0.110.0 | HTTP + lifespan + WebSocket | 已锁；listener 通过 lifespan startup task 接入 |
| Pydantic | 2.13.4 | bot.yaml schema 校验 | extra=forbid 防 typo（Phase 5.A 已模式） |
| asyncpg | ≥0.29.0 | SQLAlchemy 异步驱动 | 已锁；DB schema 扩展走 asyncpg + SA 2.0 |
| SQLAlchemy | 2.0.49 | ORM | 已锁 |
| Alembic | 1.18.4 | DB migration | 已锁 |
| redis (redis-py) | 7.4.0 | rate limit + idempotency key | 已锁；用 redis.asyncio 模块（不是 aioredis） |
| PyYAML | (已 dep) | bot.yaml loader | yaml.safe_load 即可（Phase 5.A 已模式） |
| httpx | ≥0.28.1 | Mattermost REST（出站回帖） | 已锁；既有 Phase 4 MattermostProvider 直调模式 |
| Jinja2 | 3.1.6 | LLM intent router prompt 渲染 + bot 回复模板 | 已锁 |
| tenacity | ≥8.2.3 | dispatch 失败重试（出站回帖） | 已锁 |
| importlib | stdlib | handler_ref 字符串解析 | hr reference impl 已模式 |

### Mattermost-specific (Phase 4.5 关键)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **mattermostautodriver** | **2.0.0+**（推荐固定 2.0.x — hr 在用） | AsyncDriver + init_websocket 长连 | listener 端订阅 `posted` events；Phase 4 出站走 httpx 直调不依赖 driver — Phase 4.5 入站建议引入 driver 减少 WS handshake / reconnect 自实现成本 |
| **httpx**（已锁） | ≥0.28.1 | 出站回帖（reply_to_thread） + 主动 POST | 复用 Phase 4 MattermostProvider 模式 — driver 仅用入站，出站继续走 httpx 减少耦合 |

**重要兼容性踩坑（HIGH confidence — hr reference impl 已踩）**：

```python
# httpx 0.28+ 移除 `proxies` 参数，mattermostautodriver 2.0 还在传 → monkey-patch 兼容
import httpx as _httpx

_orig_async_client_init = _httpx.AsyncClient.__init__


def _patched_async_client_init(self, *args, **kwargs):
    kwargs.pop("proxies", None)
    return _orig_async_client_init(self, *args, **kwargs)


_httpx.AsyncClient.__init__ = _patched_async_client_init
```

**hr workers/mattermost_listener.py:30-40 line 已 production 验证**。Phase 4.5 listener 必须在 import mattermostautodriver 之前打这个 monkey-patch。

**替代方案考虑**：
- `mattermostdriver`（Vaelor）— sync 为主，不推荐
- `mattermost`（官方 PyPI 包名）— REST only，没 WS
- `matteraio` — async 但更新慢
- **结论**：mattermostautodriver 2.0+ 是当前 Python async + WS 最成熟选择（HIGH confidence — hr 1.5 个月生产部署验证）

### LLM (Phase 4.5 intent router 复用)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| zhipuai | ≥2.1.5 | GLM 调用（agent-builder 已锁） | intent router prompt 调用 — 复用 LLM 节点 provider |
| litellm | ≥1.63.11 | OpenAI 兼容 fallback | 多 LLM provider 兜底 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| mattermostautodriver init_websocket | httpx websocket 自实现 + 自己 handshake | 自实现要复制 reconnect / heartbeat / login auth 逻辑 ~300 行；driver 给 30 行就跑 |
| listener 跑在 backend 主进程 | listener 跑在独立 worker 进程 | v1 主进程减少 deploy 复杂度；v1.5 拆 worker 进程（R-IM-09 多 bot 共存优化） |
| Redis fixed-window counter | Redis 滑动窗口 / Token Bucket | 滑动窗口需要 ZADD + ZREMRANGEBYSCORE 复杂；fixed-window 一行 INCR + EXPIRE 简单足够 |
| sha256(message_text) idempotency | crypto-grade UUID | 用户秒重发同样内容时 sha256 等价；UUID 不防重发 |
| 平台预置 handler 字符串 ref | decorator 全局注册 | hr 已分析：实例化时才有 self 上下文，全局 decorator 不灵活 |
| LangChain LLM client | 复用 agent-builder LLM 节点 provider | LangChain 引入复杂依赖；agent-builder 已有 LLM provider 抽象更内聚 |

**Installation:**

```bash
# pyproject.toml 加：
uv add mattermostautodriver==2.0.0  # 已是 hr 部署版本
# 其他依赖已是 agent-builder 既有 — 无需新增
```

## Architecture Patterns

### Recommended Project Structure

```
backend/app/agent_builder/
├── notification/             # Phase 4 出站 — Phase 4.5 不动
│   └── providers/
│       └── mattermost.py     # 既有 MattermostProvider（出站）
└── bot_dispatcher/           # ← Phase 4.5 新增（业务层 - 与 platforms/ 平级）
    ├── __init__.py
    ├── schemas/              # Pydantic schemas
    │   ├── __init__.py
    │   └── bot_config.py     # BotConfig / CommandSpec / TriggersSpec / IdentitySpec / FallbackSpec / LLMIntentRouterSpec
    ├── loader.py             # load_bot_config(yaml_path | dict) → BotConfig + 启动期 strict validate
    ├── parser.py             # parse_command(raw_text, bot_config) → BotCommand | None（白名单 + 正则 + self_apply 短路）
    ├── llm_router.py         # BotIntentRouter.classify(message, ctx) → IntentResult（5s timeout + ai_qa 兜底）
    ├── registry.py           # HandlerRegistry.resolve(handler_ref) + dispatch(cmd_name, args, ctx)
    ├── context.py            # BotContext dataclass + IMHelpers dataclass（post_channel / send_dm / ensure_in_channel）
    ├── dispatcher.py         # BotDispatcher.dispatch_message(raw_msg, ctx) — 串接 parser → llm_router → registry
    ├── rate_limiter.py       # Redis SET NX per_user_per_minute（dispatch 入口闸）
    ├── idempotency.py        # Redis SET NX sha256 key（防 IM 重推 + 秒重发）
    ├── audit.py              # AuditLogger.dispatch(cmd_name, sender, ws_id, latency, outcome)
    ├── builtin/              # 平台内置 handler — 不允许 workspace 上传
    │   ├── __init__.py
    │   ├── help.py           # handle_help — 元数据驱动 from bot_config.commands
    │   ├── workflow.py       # handle_start / handle_status / handle_list — 调 WorkflowAPI
    │   └── debug.py          # handle_ping / handle_version（调试用）
    └── listeners/
        ├── __init__.py
        ├── base.py           # BotListener Protocol（name / start / stop / register_dispatch）
        └── mattermost.py     # MattermostListener（init_websocket + _handle_event + reconnect loop）

backend/app/agent_builder/services/
└── bot_lifecycle.py          # FastAPI lifespan startup/shutdown：扫描 bot.yaml → init listeners → register dispatch

backend/app/models/
├── workspace_bot_installation.py   # ← 新增 ORM
├── bot_audit_log.py                # ← 新增 ORM
└── bot_rate_limit.py               # ← 新增 ORM（可选 — Redis 优先，DB 仅长期审计）

backend/alembic/versions/
└── 0007_phase45_bot_dispatcher.py  # ← 新增 migration

backend/tests/agent_builder/bot_dispatcher/        # ← 新增 unit tests
backend/tests/agent_builder/bot_dispatcher_integration/  # ← 新增 integration tests
e2e_v2/specs/test_phase_4_5_*.py   # ← 新增 6 个 E2E spec
```

### Pattern 1: BotConfig YAML schema + Strict Validate (R-IM-01)

**What:** bot.yaml → Pydantic BotConfig 一次 parse + 启动期 fail-fast，validate 失败 listener 拒启动。

**When to use:** 每次 bot 启动 + CLI `agent-builder bot validate <yaml>`。

**Example:**

```python
# bot_dispatcher/schemas/bot_config.py
# Source: 设计稿 docs/plans/2026-05-17-im-bot-abstraction-design.md §4.2 + Phase 5.A manifest.py pattern
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class CommandArg(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 防 typo
    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    type: Literal["string", "int", "uuid8_or_uuid36", "enum", "bool"]
    pattern: str | None = None
    choices: list[str] | None = None
    required: bool = True
    multiline: bool = False
    min_length: int | None = None
    default: str | None = None


class SelfApplySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    sentinel_phrases: list[str] = Field(default_factory=list)
    arg_default: dict[str, str] = Field(default_factory=dict)


class CommandSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    description: str = Field(min_length=1)
    args: list[CommandArg] = Field(default_factory=list)
    self_apply: SelfApplySpec | None = None
    handler: str = Field(min_length=1)  # "app.agent_builder.bot_dispatcher.builtin.workflow:start"
    allowed_roles: list[str] = Field(default_factory=lambda: ["admin"])
    category: str | None = None
    example_invocations: list[str] = Field(default_factory=list)


class TriggersSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dm: bool = True
    at_mention: bool = True
    keywords: list[str] = Field(default_factory=list)

    @field_validator("keywords", mode="after")
    @classmethod
    def at_least_one_trigger(cls, v):
        # 校验 dm/at_mention/keywords 至少一个为 True (placeholder — root validator 真校验)
        return v


class IdentitySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["agent_builder_users", "jit_create"] = "agent_builder_users"
    on_unknown: Literal["reject_friendly", "guest_mode", "auto_create"] = "reject_friendly"
    unknown_hint: str | None = None


class LLMIntentRouterSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    intents: list[str] = Field(min_length=1)
    prompt_template_path: str = Field(min_length=1)
    llm: str = Field(min_length=1)


class FallbackSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    llm_intent_router: LLMIntentRouterSpec | None = None
    ai_qa: AIQaSpec | None = None


class BotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_-]{2,31}$")
    description: str = Field(min_length=1)
    provider: ProviderSpec
    triggers: TriggersSpec
    identity: IdentitySpec
    commands: list[CommandSpec] = Field(min_length=1)
    fallback: FallbackSpec | None = None
    audit: AuditSpec | None = None
    help: HelpSpec | None = None
```

**关键约束：** Pydantic v2 `ConfigDict(extra="forbid")` 让所有 typo 启动期 raise（Phase 5.A 已模式）。

### Pattern 2: HandlerRegistry + Importlib Resolve (R-IM-02)

**What:** handler_ref = "module.path:function_name"，运行时 importlib.import_module + getattr。

**When to use:** bot dispatch 时按 cmd_name 查 spec → resolve handler → 调用。

**Example:**

```python
# bot_dispatcher/registry.py
# Source: 设计稿 §5.1 + hr bot_handler_registry.py 复用模式
from __future__ import annotations
import importlib
from collections.abc import Awaitable, Callable
from typing import Any

from .schemas.bot_config import BotConfig, CommandSpec
from .context import BotContext

BotHandler = Callable[[dict[str, Any], BotContext], Awaitable[str]]


class HandlerRegistry:
    """命令 → handler 的动态查表分发器。

    设计差异 vs hr/offboarding-flow（reference impl 改进）：
    - hr: BotService.__init__ 内显式 register("help", self.handle_help)
    - 本项目: handler_ref 字符串 "module:fn" 由 bot.yaml 声明 → import 时机延迟到首次 dispatch
    - 优势: bot.yaml 加新命令免动 dispatcher / Service 类
    - 风险: import error 推迟到运行时 → 必须启动期 validate 时 try-import 一遍（fail-fast）
    """

    def __init__(self, bot_config: BotConfig) -> None:
        self.bot_config = bot_config
        self._cache: dict[str, BotHandler] = {}
        self._specs_by_name: dict[str, CommandSpec] = {
            c.name: c for c in bot_config.commands
        }

    def validate_all_handlers(self) -> None:
        """启动期 import 所有 handler — 失败立即 raise（R-IM-01 fail-fast）。"""
        for spec in self.bot_config.commands:
            self.resolve(spec.handler)

    def resolve(self, handler_ref: str) -> BotHandler:
        if handler_ref in self._cache:
            return self._cache[handler_ref]
        module_path, fn_name = handler_ref.split(":")
        mod = importlib.import_module(module_path)
        fn = getattr(mod, fn_name)
        if not callable(fn):
            raise ValueError(f"handler {handler_ref} not callable")
        self._cache[handler_ref] = fn
        return fn

    def get_spec(self, cmd_name: str) -> CommandSpec | None:
        return self._specs_by_name.get(cmd_name)

    async def dispatch(self, cmd_name: str, args: dict, ctx: BotContext) -> str:
        spec = self.get_spec(cmd_name)
        if spec is None:
            return await self._dispatch_help(ctx)
        self._check_role(spec, ctx)          # raise BotPermissionError
        self._validate_args(spec, args)      # Pydantic dynamic model
        handler = self.resolve(spec.handler)
        return await handler(args, ctx)
```

### Pattern 3: LLM Intent Router with Timeout + AI QA Fallback (R-IM-04)

**What:** parse_command 失败 → 调 LLM (Jinja2 渲染 intent_router prompt) → 解析 JSON → 按 intent 路由 / confidence < threshold 走 ai_qa。

**When to use:** 用户输入非白名单命令时（dispatcher 兜底链）。

**Example:**

```python
# bot_dispatcher/llm_router.py
# Source: hr bot_intent_router.py 复用 + 设计稿 §7.2 改进（template 化 + asyncio.timeout）
from __future__ import annotations
import asyncio
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jinja2

from .schemas.bot_config import BotConfig, LLMIntentRouterSpec
from .context import BotContext

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntentResult:
    intent: str
    args: dict[str, Any]
    confidence: float
    ai_reply: str | None = None
    raw: str = ""


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.S)
    return m.group(1).strip() if m else text


class BotIntentRouter:
    """LLM-based intent router。

    timeout 是硬性：N-IM-05 要求 5s 内不返回 → 直接走 ai_qa 兜底（不阻塞 dispatcher）。
    asyncio.timeout(seconds) 是 Python 3.11+ 推荐 API（比 asyncio.wait_for cleaner）。
    """

    def __init__(self, bot_config: BotConfig, llm_provider) -> None:
        self.bot_config = bot_config
        self.llm = llm_provider
        self._tpl_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(searchpath="prompts/"),
            autoescape=False,  # prompt 不渲染 HTML
        )

    async def classify(
        self, *, message: str, ctx: BotContext
    ) -> IntentResult:
        cfg: LLMIntentRouterSpec = self.bot_config.fallback.llm_intent_router
        if not cfg.enabled:
            return IntentResult(intent="ai_qa", args={}, confidence=0.0)

        tpl = self._tpl_env.get_template(cfg.prompt_template_path)
        prompt = tpl.render(
            bot_name=self.bot_config.name,
            intents=cfg.intents,
            user_message=message,
            sender_username=ctx.user_name,
            sender_role=ctx.user_role or "未注册",
        )

        # structured log: bot.dispatch.llm.attempt（Phase 7 Run Viewer）
        log.info(
            "bot.dispatch.llm.attempt",
            extra={
                "bot_name": self.bot_config.name,
                "workspace_id": ctx.workspace_id,
                "user_name": ctx.user_name,
                "timeout_seconds": cfg.timeout_seconds,
            },
        )

        try:
            async with asyncio.timeout(cfg.timeout_seconds):
                resp = await self.llm.complete(prompt)
        except (asyncio.TimeoutError, Exception) as e:
            log.warning(
                "bot.dispatch.llm.timeout",
                extra={"bot_name": self.bot_config.name, "error": str(e)[:200]},
            )
            return IntentResult(intent="ai_qa", args={}, confidence=0.0)

        try:
            data = json.loads(_strip_json_fences(resp))
        except json.JSONDecodeError:
            log.warning("bot.dispatch.llm.parse_failed", extra={"raw": resp[:200]})
            return IntentResult(
                intent="ai_qa", args={}, confidence=0.0,
                ai_reply=resp.strip()[:1000], raw=resp,
            )

        return IntentResult(
            intent=str(data.get("intent", "ai_qa")).strip().lower(),
            args=data.get("args", {}) or {},
            confidence=float(data.get("confidence", 0.0)),
            ai_reply=(data.get("ai_reply") or "").strip() or None,
            raw=resp,
        )
```

### Pattern 4: Triple-Trigger Listener Filter (R-IM-05)

**What:** WebSocket event → 跳过 bot 自己 → 检查 DM / @-mention / keywords 三 OR → 命中才 dispatch。

**When to use:** MattermostListener._handle_event 内的入口过滤。

**Example:**

```python
# bot_dispatcher/listeners/mattermost.py
# Source: hr workers/mattermost_listener.py:145-198 模式直接 port
async def _handle_event(self, event_str: str) -> None:
    try:
        event = json.loads(event_str) if isinstance(event_str, str) else event_str
    except Exception:
        return
    if event.get("event") != "posted":
        return

    data = event.get("data", {})
    post_str = data.get("post")
    if not post_str:
        return
    try:
        post = json.loads(post_str) if isinstance(post_str, str) else post_str
    except Exception:
        return

    # 1. 跳过 bot 自己消息防死循环（Pitfall 1）
    bot_user_id = self._settings.mattermost_bot_user_id
    if post.get("user_id") == bot_user_id:
        return

    message = post.get("message", "").strip()
    channel_id = post.get("channel_id", "")
    channel_type = data.get("channel_type", "")  # 'D' = DM, 'O' = public, 'P' = private
    sender_name = data.get("sender_name", "").lstrip("@")

    # 2. 三 OR 触发判定（R-IM-05）
    cfg = self._bot_config.triggers
    bot_mention = f"@{self._settings.mattermost_bot_username}"
    is_dm = cfg.dm and channel_type == "D"
    is_at_mentioned = cfg.at_mention and bot_mention in message
    contains_keyword = any(kw in message for kw in cfg.keywords) if cfg.keywords else False
    if not (is_dm or is_at_mentioned or contains_keyword):
        return

    # 3. 结构化日志（Phase 7 钩子）
    log.info(
        "bot.listener.message_received",
        extra={
            "bot_name": self._bot_config.name,
            "sender_name": sender_name,
            "channel_id_prefix": channel_id[:8],
            "is_dm": is_dm,
            "is_at_mentioned": is_at_mentioned,
            "contains_keyword": contains_keyword,
        },
    )

    # 4. 委托给 dispatcher
    await self._dispatcher.dispatch_message(
        sender_name=sender_name,
        sender_user_id=post.get("user_id", ""),
        channel_id=channel_id,
        channel_type=channel_type,
        message=message,
        im_helpers=self._build_helpers(),
    )
```

### Pattern 5: Identity Alignment + Reject Friendly (R-IM-06)

**What:** sender_name → users 表查 → 找不到时走 `on_unknown` 策略（reject_friendly / guest_mode / auto_create）。

**When to use:** Dispatcher 在调 handler 前的身份对齐步骤。

**Example:**

```python
# bot_dispatcher/dispatcher.py 片段
async def _align_identity(
    self, sender_name: str, ctx_in: BotContext
) -> BotContext | None:
    """对齐身份 — 失败时按 bot_config.identity.on_unknown 决策。"""
    async with self._session_factory() as session:
        stmt = select(User).where(
            User.username == sender_name,
            User.workspace_id == ctx_in.workspace_id,  # CLAUDE.md 2.4 多租户隔离
        )
        user = (await session.execute(stmt)).scalar_one_or_none()

    if user:
        return replace(
            ctx_in,
            user_id=user.id,
            user_role=user.role,
            user_email=user.email,
        )

    # 未识别 user — 按 bot_config.identity.on_unknown 决策
    cfg = self._bot_config.identity
    if cfg.on_unknown == "reject_friendly":
        await ctx_in.im_helpers.post_channel(
            ctx_in.channel_id,
            cfg.unknown_hint or f"⚠️ 未识别账号 `{sender_name}`，请联系管理员同步用户表",
        )
        return None
    if cfg.on_unknown == "guest_mode":
        return replace(ctx_in, user_role="guest", user_id=None)
    # auto_create — Phase 5.E 才支持（v1 raise）
    raise NotImplementedError("on_unknown=auto_create 留 Phase 5.E")
```

### Pattern 6: Audit Log (R-IM-11)

**What:** 每次 dispatch 写 `bot_audit_logs` 表（who / cmd / args / outcome / latency / workspace_id），复用 Phase 3 NET-05 audit_logs schema 思路扩展子表。

**When to use:** Dispatcher dispatch 入口（before / after handler 调用）。

**Example schema:**

```python
# backend/app/models/bot_audit_log.py
class BotAuditLog(SQLModel, table=True):
    __tablename__ = "bot_audit_logs"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    workspace_id: UUID = Field(foreign_key="workspaces.id", index=True)
    bot_name: str = Field(max_length=64, index=True)
    sender_name: str = Field(max_length=255, index=True)
    sender_user_id: UUID | None = Field(default=None, foreign_key="users.id")
    cmd_name: str | None = Field(default=None, max_length=64, index=True)
    cmd_args_json: dict | None = Field(default=None, sa_type=JSONB)
    raw_message: str = Field(max_length=4096)  # 截断长消息
    outcome: Literal["success", "permission_denied", "rate_limited", "parse_failed", "handler_error"] = Field(max_length=32)
    error_message: str | None = Field(default=None, max_length=1024)
    latency_ms: int = Field(default=0)
    routed_via: Literal["whitelist", "llm_intent", "ai_qa", "keyword_self_apply"] = Field(max_length=32)
    llm_confidence: float | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)

    __table_args__ = (
        Index("ix_bot_audit_workspace_created", "workspace_id", "created_at"),
        Index("ix_bot_audit_outcome", "outcome", "created_at"),
    )
```

### Pattern 7: Idempotency Key (R-IM-13)

**What:** sha256(workspace_id + bot_name + sender_user_id + cmd_name + canonical_args + bucket_minute) → Redis SET NX → 已存在表示重复请求，返回上次结果（或 silent skip）。

**Why minute_bucket：** 防 IM at-least-once 重推（Mattermost 容许 retry）+ 用户 1 分钟内重复同样命令。

```python
# bot_dispatcher/idempotency.py
import hashlib
import json
from datetime import datetime, UTC


def compute_idempotency_key(
    *, workspace_id: str, bot_name: str, sender_user_id: str,
    cmd_name: str, args: dict[str, str], bucket_minutes: int = 1,
) -> str:
    bucket = datetime.now(UTC).strftime(f"%Y%m%d%H{'%M' if bucket_minutes == 1 else ''}")
    payload = json.dumps(
        {
            "ws": workspace_id, "bot": bot_name, "user": sender_user_id,
            "cmd": cmd_name, "args": dict(sorted(args.items())), "bucket": bucket,
        },
        sort_keys=True, ensure_ascii=False,
    )
    return f"bot:idem:{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


async def check_and_set(redis, key: str, ttl_seconds: int = 120) -> bool:
    """SET NX — True 表示首次（继续 dispatch），False 表示重复（skip）。"""
    return await redis.set(key, "1", nx=True, ex=ttl_seconds) is not None
```

### Anti-Patterns to Avoid

- **❌ Bot 自己消息不过滤**：listener 不跳过 bot_user_id 时，bot 回帖立刻触发自身的 `posted` 事件 → 无限循环（Pitfall 1）
- **❌ GET 路径消费 idempotency_key**：Outlook Safe Links / Microsoft Defender 扫描器对所有 URL 触发 GET — bot dispatcher 收 webhook 时如果 GET 也算 dispatch 就会被预消费（CLAUDE.md §2.5 P0；本 phase 走 WS 长连不暴露 GET endpoint，但 Phase 5.E 加 webhook fallback 时必须防）
- **❌ handler 异常 leak stack trace 到 bot 回复**：暴露内部模块路径 + DB 字段名 — 必须 try/except 统一 wrap 为 "❌ 内部错误，请联系管理员" + audit log（Pitfall 4）
- **❌ LLM intent 不带 timeout**：LLM 慢响应 1 分钟把 listener 协程占住 → 整个 bot 假死（N-IM-05 必须 5s timeout）
- **❌ rate limit 用 sync redis client**：阻塞 listener event loop — 必须用 `redis.asyncio`（aioredis 已停更不能用）
- **❌ bot.yaml 凭据明文存**：N-IM-03 — bot_token / api_secret 必须 env 注入或加密存（Phase 4 IMCredentialsManager 模式）
- **❌ command name 与 LLM intent 名冲突**：validate 期必须断言 `set(commands) >= set(intents) - {"ai_qa"}`（设计稿 §12 风险表）
- **❌ session 横跨 dispatch + handler 同一个**：handler 内 await DB → session 复用导致并发问题 — 每 dispatch 用 `async with session_factory()`（CLAUDE.md §2.4 DISCARD ALL hook）

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| WebSocket 长连 + reconnect | 自己写 ws connection loop | **mattermostautodriver 2.0** `AsyncDriver.init_websocket()` | reconnect / keepalive / heartbeat 30s ping 全包含；hr 1.5 个月生产验证 |
| Rate limit fixed-window counter | 自实现内存 dict + asyncio.Lock | **Redis SET NX + EXPIRE** + `redis.asyncio` | 多 worker 共享 + 自动过期；agent-builder 已用 Phase 3 HitlTokenStore 同模式 |
| Idempotency key（重复请求识别） | 内存 set + 自己定 GC | **Redis SET NX TTL** | 跨进程 + 自动 expire；与 Phase 3 jti 同模式 |
| YAML schema 校验 | 自写 dict.get + isinstance | **Pydantic v2 + ConfigDict(extra="forbid")** | 字段级 validation_error + JSON Schema 生成（前端 UI 可用） |
| Prompt 模板渲染 | 自己 string.format | **Jinja2 environment + FileSystemLoader** | autoescape / for / if 全支持；agent-builder 已用 |
| LLM client | 自写 httpx + retry | **zhipuai SDK / litellm**（agent-builder LLM provider） | 已锁；retry / streaming / cost tracking 全有 |
| Importlib 动态 handler 解析 | eval(f"{module}.{fn}") | **importlib.import_module + getattr** | 不走 eval（安全）；hr reference impl 已验证 |
| asyncio timeout | asyncio.wait_for(...) + 自己 cancel | **`async with asyncio.timeout(seconds):`**（Python 3.11+） | 比 wait_for 更 cleaner（无 cancel race condition） |
| audit log 表 schema | 重新设计 audit 表 | **复用 Phase 3 NET-05 audit_logs** schema 思路 + bot_audit_logs 专表 | bot 子集字段独立，便于 partial index + 查询 |
| 身份对齐 user 查询 | 直接 raw SQL | **SQLAlchemy + WorkspaceScopedQuery**（Phase 1 已抽象） | 多租户隔离自动注入 `WHERE workspace_id =` |

**Key insight:** Phase 4.5 是"业务编排"层 — 重型基础设施（WS / Redis / DB / LLM / YAML）全部沿用 agent-builder 已有的 Phase 1-5.A 工具栈，不引入新依赖。**核心增量只有 1 个新依赖：`mattermostautodriver==2.0.0`**。

## Common Pitfalls

### Pitfall 1: Bot 死循环（Echo Loop）— P0

**What goes wrong:** Bot 回帖给用户的消息被自己的 WS listener 收到，触发同样的 dispatch 流程，bot 又回帖，无限循环。

**Why it happens:** Mattermost `posted` 事件包含所有 channel 内的消息（包括 bot 自己 POST 的）。

**How to avoid:** `_handle_event` 第一行就跳过 `post.user_id == bot_user_id`（hr reference impl line 162-165 模式）。**bot_user_id 必须在 listener 启动期通过 `GET /api/v4/users/me` 获取并 cache**。

**Warning signs:** Mattermost channel 在几秒内堆 100+ 条相同消息 / bot CPU 占满 / Mattermost rate limit 429。

**E2E 检测：** browser-harness 发一条 `@bot help` → 等待 2 秒 → 断言 channel 内 bot 消息数 ≤ 1（不是 2+）。

---

### Pitfall 2: httpx 0.28+ vs mattermostautodriver 兼容 — P0

**What goes wrong:** `from mattermostautodriver import AsyncDriver` 在 httpx ≥0.28 时报 `TypeError: AsyncClient.__init__() got an unexpected keyword argument 'proxies'`。

**Why it happens:** httpx 0.28 移除 `proxies` 参数，mattermostautodriver 2.0 还在传。

**How to avoid:** 在 `import mattermostautodriver` 之前 monkey-patch `httpx.AsyncClient.__init__` 删 `proxies` kwarg（hr reference impl line 30-40）。

**Warning signs:** listener 启动期 import error，根本起不来。

---

### Pitfall 3: WebSocket reconnect 雷击效应 — P1

**What goes wrong:** Mattermost 服务重启时所有 listener 同时断连 + 同时尝试重连 → 同时 hit `/users/login` API → Mattermost 限流 429 → 所有 listener 全失败。

**Why it happens:** 固定间隔 5s reconnect 在多 listener 场景下同步。

**How to avoid:** reconnect 间隔加 jitter（`asyncio.sleep(5 + random.uniform(-2, 2))`）；指数退避 cap 60s（连续失败时增加 wait）。

**Warning signs:** logs 中所有 listener 同一秒重连失败 → 间隔几秒再批量失败。

---

### Pitfall 4: Handler stack trace 暴露 — P0（安全）

**What goes wrong:** handler 抛 `AttributeError: 'NoneType' object has no attribute 'id'`，dispatcher 把异常 str() 后发到 channel → 用户看到内部代码细节。

**Why it happens:** 没有统一异常 wrap。

**How to avoid:** Dispatcher.dispatch 整体 try/except — 业务异常（`BotPermissionError` / `BotFlowNotFoundError` 等）走友好提示 + audit；其他异常一律 wrap 为 "❌ 内部错误（事件 ID: <audit_id>），请联系管理员"（不暴露 stack）。

**Warning signs:** Mattermost channel 出现 `Traceback (most recent call last):` 字样。

---

### Pitfall 5: LLM JSON 返回不严格 — P1

**What goes wrong:** GLM / OpenAI 返回 ` ```json\n{...}\n``` ` 或 prefix "好的，我来分类..." + JSON 后 → `json.loads` 失败。

**Why it happens:** LLM 没遵守 prompt 要求严格 JSON。

**How to avoid:** `_strip_json_fences` 用 regex 提取 fence 内 JSON（hr reference impl 已模式）；解析失败时降级为 ai_qa + 把原始 LLM 输出 truncate 1000 字符当回答（不丢消息）。

**Warning signs:** `bot.dispatch.llm.parse_failed` 日志高频。

---

### Pitfall 6: 多 listener 共享 DB session — P0（多租户隔离）

**What goes wrong:** Listener 协程持一个 session 跨多次 dispatch，并发请求 race condition + workspace_id 被 last write 覆盖 → 跨 workspace 数据泄漏。

**Why it happens:** Python asyncio 协程切换间共享 session 状态。

**How to avoid:** **每次 dispatch 入口 `async with session_factory() as session:`**（CLAUDE.md §2.4 DISCARD ALL hook + WorkspaceScopedQuery）— session 严格不跨 dispatch 边界。

**Warning signs:** integration test 双 workspace 互访不返 403 / 返其他 workspace 数据。

---

### Pitfall 7: bot.yaml 凭据明文 — P0（安全）

**What goes wrong:** `provider.config: {bot_token: "abcdef..."}` 写进 bot.yaml 进 git → token 永久泄漏。

**Why it happens:** 开发者贪图方便。

**How to avoid:** N-IM-03 强制 — bot.yaml 只允许 `config_env_prefix: MM_`，真值从 env 读 / DB 加密存。Pydantic schema 加 `field_validator` 检测疑似 token 字段（含 `_token` / `_secret` / `_key` 后缀的 string）→ 启动期 raise。

**Warning signs:** git diff bot.yaml 看到 32+ 字符的随机字符串。

---

### Pitfall 8: 命令名与 LLM intent 名不一致 — P1

**What goes wrong:** bot.yaml `commands` 有 `start`，`fallback.llm_intent_router.intents` 写成 `starts` → LLM 返回 `intent=starts` 路由失败。

**Why it happens:** typo。

**How to avoid:** loader 启动期断言 `set(cfg.fallback.llm_intent_router.intents) - {"ai_qa"} <= set(c.name for c in cfg.commands)` — 失败 raise + 列出 mismatch。

---

### Pitfall 9: Mattermost @-mention 解析跨 channel — P1

**What goes wrong:** Bot 在 `@bot list` 命令里调 `send_dm("hr.alice", ...)` → MM API 需要先把 alice 加进 bot's DM channel — 没有 `ensure_in_channel` 时静默失败。

**Why it happens:** Mattermost DM channel 要求双方先建立。

**How to avoid:** `IMHelpers.send_dm` 内部先 `users.get_user_by_username(username)` → `channels.create_direct_channel([bot_id, user_id])` → 拿到 DM channel_id → POST 消息（hr workers/mattermost_listener._send_dm_by_username:242-254）。

---

### Pitfall 10: handler 长任务阻塞 listener — P0

**What goes wrong:** Handler 调 LLM 节点跑 60s — listener 协程被占住，期间所有其他消息 backpressure 堆积。

**Why it happens:** Dispatcher 直接 `await handler(args, ctx)` 跑在 listener 协程内。

**How to avoid:** **handler 必须快速返回**（< 2s）。长任务 handler 应：
1. 立即 ack 给用户 "🤖 正在处理，结果稍后..."
2. 调 `ctx.workflow.start(...)` 启动 workflow（异步跑）
3. workflow 末端 Reply 节点把结果推回 thread

Phase 4.5 的 builtin handlers（help / status / list）都是 DB 查询 < 100ms，不会阻塞。但要在 reading doc 明确这条约束。

---

### Pitfall 11: keyword 触发 + LLM 同时跑 — P2（成本）

**What goes wrong:** 用户消息含 "我要离职" 4 字 → 走 self_apply → 路由到 start 命令 → 但 dispatcher 还顺便调了 LLM intent classify → 双倍 LLM 费用。

**Why it happens:** dispatcher 不短路。

**How to avoid:** Dispatcher 串接顺序硬性 — keywords match → 立即短路返回 / parse_command 成功 → 立即短路 / 都失败才调 LLM router。设计稿 §14 开放问题 #3 已明确。

---

### Pitfall 12: ai_qa 兜底无 max_tokens 限制 — P2（成本）

**What goes wrong:** LLM 兜底答用户 "请帮我写一个 1 万字的离职报告"，返回 10K token → 单次 $0.5 + bot 回帖被 MM 截断。

**Why it happens:** ai_qa prompt 没限。

**How to avoid:** `ai_qa.max_tokens: 500` schema 字段 + LLM call 显式传；prompt 内强制 system message "回复不超过 500 字"。

## Code Examples

### Example 1: bot.yaml 完整范例（Mattermost workflow bot）

```yaml
# plugins/bots/agent_builder_workflow.yaml
# Source: 设计稿 §4.1 + 本项目实际节点 API
name: agent-builder-workflow
description: agent-builder 工作流助手 — 通过 IM 启动/查询/列流程

provider:
  type: mattermost
  config_env_prefix: MM_   # MM_URL / MM_BOT_TOKEN / MM_BOT_USERNAME / MM_BOT_USER_ID

triggers:
  dm: true
  at_mention: true
  keywords:
    - 启动流程
    - 查询流程

identity:
  source: agent_builder_users
  on_unknown: reject_friendly
  unknown_hint: "⚠️ 未识别账号，请联系管理员同步账号到 agent-builder users 表"

commands:
  - name: help
    description: 展示帮助
    handler: app.agent_builder.bot_dispatcher.builtin.help:handle_help
    allowed_roles: [admin, editor, viewer]
    category: 通用

  - name: start
    description: 启动工作流（参数：workflow_id 短/长 UUID）
    args:
      - name: workflow_id
        type: uuid8_or_uuid36
        required: true
    handler: app.agent_builder.bot_dispatcher.builtin.workflow:handle_start
    allowed_roles: [admin, editor]
    category: 工作流
    example_invocations:
      - "@agent-builder-workflow start a1b2c3d4"

  - name: status
    description: 查询实例状态（参数：instance_id 短/长 UUID）
    args:
      - name: instance_id
        type: uuid8_or_uuid36
        required: true
    handler: app.agent_builder.bot_dispatcher.builtin.workflow:handle_status
    allowed_roles: [admin, editor, viewer]
    category: 工作流

  - name: list
    description: 列出当前 workspace 的实例（active / completed / stuck / mine）
    args:
      - name: filter
        type: enum
        choices: [active, completed, stuck, mine]
        default: active
        required: false
    handler: app.agent_builder.bot_dispatcher.builtin.workflow:handle_list
    allowed_roles: [admin, editor, viewer]
    category: 工作流

fallback:
  llm_intent_router:
    enabled: true
    confidence_threshold: 0.6
    timeout_seconds: 5
    intents:
      - help
      - start
      - status
      - list
      - ai_qa
    prompt_template_path: intent_router_zh.md
    llm: ${global.default_llm}

  ai_qa:
    enabled: true
    prompt_template_path: ai_qa_zh.md
    max_tokens: 500
    system_message: |
      你是 agent-builder 工作流助手，专注帮助用户启动 / 查询工作流。
      不要回答与工作流无关的问题，礼貌引导用户用 `help` 查看命令。

audit:
  log_dispatch: true
  rate_limit:
    per_user_per_minute: 10
    per_user_per_hour: 100

help:
  auto_generate: true
  group_by: category
  show_examples: true
```

### Example 2: intent_router_zh.md prompt template

```markdown
你是 {{ bot_name }} 的意图分类器。判断用户输入属于以下哪个意图，并返回严格 JSON。

可识别意图：
{% for intent in intents %}
- {{ intent }}
{% endfor %}
- ai_qa（兜底自由问答，当用户输入不属于任何具体意图时）

返回格式（严格 JSON，无多余字段，无 markdown fence）：
{
  "intent": "<上述意图之一>",
  "confidence": <0.0 到 1.0>,
  "args": { "<arg_name>": "<value>" },
  "ai_reply": "<intent=ai_qa 时填，其他时候为 null>"
}

用户输入：
{{ user_message }}

发送者：username={{ sender_username }} role={{ sender_role }}
```

### Example 3: builtin handle_help（元数据驱动）

```python
# bot_dispatcher/builtin/help.py
# Source: 设计稿 §6.1 + agent-builder 风格
from __future__ import annotations
from collections import defaultdict
from app.agent_builder.bot_dispatcher.context import BotContext


async def handle_help(args: dict, ctx: BotContext) -> str:
    cfg = ctx.bot_config
    visible = [
        c for c in cfg.commands
        if ctx.user_role in c.allowed_roles or "admin" == ctx.user_role
    ]

    group_by = (cfg.help.group_by if cfg.help else None) or "none"
    if group_by == "category":
        groups: dict[str, list] = defaultdict(list)
        for c in visible:
            groups[c.category or "其他"].append(c)
    else:
        groups = {"命令清单": visible}

    lines = [f"📖 **{cfg.name}** — {cfg.description}\n"]
    for cat, cmds in groups.items():
        lines.append(f"### {cat}")
        for c in cmds:
            args_str = " ".join(
                f"<{a.name}>" if a.required else f"[{a.name}]" for a in c.args
            )
            lines.append(f"- `@{cfg.name} {c.name} {args_str}` — {c.description}")
            if cfg.help and cfg.help.show_examples and c.example_invocations:
                for ex in c.example_invocations[:2]:
                    lines.append(f"    > 示例：`{ex}`")
        lines.append("")

    if cfg.fallback and cfg.fallback.ai_qa and cfg.fallback.ai_qa.enabled:
        lines.append("> 💡 你也可以直接用自然语言提问，我会尽量帮你路由到对应命令。")

    return "\n".join(lines)
```

### Example 4: FastAPI lifespan 接入

```python
# backend/app/agent_builder/services/bot_lifecycle.py
# Source: hr offboarding_flow/main.py lifespan + Phase 4 MattermostProvider 注册模式
from __future__ import annotations
import asyncio
import logging
from pathlib import Path

from app.agent_builder.bot_dispatcher.loader import load_bot_config
from app.agent_builder.bot_dispatcher.dispatcher import BotDispatcher
from app.agent_builder.bot_dispatcher.listeners.mattermost import MattermostListener

log = logging.getLogger(__name__)


class BotLifecycleManager:
    """FastAPI lifespan 用 — 启动期扫描 bot.yaml + 启动 listeners；shutdown 停 listeners。"""

    def __init__(self) -> None:
        self._listeners: dict[str, MattermostListener] = {}

    async def startup(self, *, settings, session_factory, redis, llm_provider) -> None:
        bot_yaml_dir = Path("plugins/bots/")
        if not bot_yaml_dir.exists():
            log.info("bot.lifecycle.no_bots", extra={"dir": str(bot_yaml_dir)})
            return

        for yaml_path in sorted(bot_yaml_dir.glob("*.yaml")):
            try:
                bot_config = load_bot_config(yaml_path)
                # 启动期 validate（fail-fast）
                bot_config_validated = bot_config.model_dump()
                # 构造 dispatcher
                dispatcher = BotDispatcher(
                    bot_config=bot_config,
                    session_factory=session_factory,
                    redis=redis,
                    llm_provider=llm_provider,
                )
                dispatcher.validate_handlers()  # importlib 一遍

                # 构造 listener（按 provider type 分发）
                if bot_config.provider.type == "mattermost":
                    listener = MattermostListener(
                        bot_config=bot_config, settings=settings
                    )
                    listener.register_dispatch(dispatcher.dispatch_message)
                    await listener.start()
                    self._listeners[bot_config.name] = listener
                    log.info(
                        "bot.lifecycle.started",
                        extra={
                            "bot_name": bot_config.name,
                            "provider": bot_config.provider.type,
                            "commands": [c.name for c in bot_config.commands],
                        },
                    )
            except Exception as e:
                log.exception(
                    "bot.lifecycle.start_failed",
                    extra={"yaml_path": str(yaml_path), "error": str(e)[:200]},
                )
                # v1 严格：一个 bot 起不来阻断启动（防 silent 配置错误）
                raise

    async def shutdown(self) -> None:
        for name, listener in self._listeners.items():
            try:
                await listener.stop()
                log.info("bot.lifecycle.stopped", extra={"bot_name": name})
            except Exception as e:
                log.warning(
                    "bot.lifecycle.stop_failed",
                    extra={"bot_name": name, "error": str(e)[:200]},
                )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| BotService.dispatch 11 个 if/elif 分支 | HandlerRegistry + handler_ref 字符串 | hr 2026-05-17 BOT-08 重构 | 加新命令免动 dispatcher |
| help 文本硬编码 markdown | 元数据驱动 from bot_config.commands | 设计稿 §6.1 | 加命令自动更新 help |
| intent_router prompt 硬编码（INTENT_ROUTER_PROMPT 常量） | Jinja2 模板 + 配置化 intents 列表 | 设计稿 §7.1 | 每 bot 自定意图集 |
| asyncio.wait_for + 自管 cancel | `async with asyncio.timeout(seconds):` | Python 3.11+ | cleaner + 无 race condition |
| aioredis 包 | redis-py 7.4.0 `redis.asyncio` | 2021-12 aioredis 停更 | 已是 agent-builder 锁定 |
| python-jose JWT | PyJWT 2.12.1 | FastAPI 官方迁移 | 已是 agent-builder 锁定 |
| 自实现 WS reconnect | mattermostautodriver `init_websocket` keepalive=True | hr 2026-04 引入 | 30 行 vs 300 行 |

**Deprecated/outdated:**

- aioredis（停更 2021-12） — 用 redis.asyncio
- python-jose JWT（FastAPI 弃用） — 用 PyJWT
- mattermostdriver-asyncio（fork，更新慢） — 用 mattermostautodriver
- handle_xxx if/elif 硬编码 dispatch — 用 HandlerRegistry

## Open Questions

1. **MM bot account 是否需要预加进 workspace channels？**
   - 已知：DM 不需要（任何 user 都可与 bot 私聊）；channel @-mention 需要 bot 先加进 channel
   - 不清楚：v1 是否要在 lifespan startup 时自动 add bot 到所有 channels（侵入性强）
   - 推荐：v1 不自动 — 文档说明"必须先 invite bot 进 channel 才能 @"；E2E test 用 admin 在 setUp 时 add

2. **bot.yaml 的 `${global.default_llm}` 引用如何实现？**
   - 设计稿 §4.1 写了 placeholder，未明确解析机制
   - 推荐：v1 简化 — loader 在加载后做 string interpolation（Jinja2 渲染）；llm 字段直接是 LLM provider name（"glm" / "openai" / ...），对应 agent-builder LLM provider registry
   - 风险：v1.5 需扩展（多 LLM 配置）

3. **handler 是否需要支持 sync 函数？**
   - hr handler_registry 强制 async（line 33 `BotHandler = Callable[..., Awaitable[str]]`）
   - 推荐：v1 强制 async（与 hr 一致）— 防 sync DB 阻塞 listener

4. **bot rate limit 命中后给用户什么提示？**
   - 推荐："⏳ 你近 1 分钟操作太频繁，请稍后再试。"（不暴露具体阈值防被探测）

5. **dispatcher 是否需要支持单 bot 多 workspace？**
   - R-IM-09 是 v1.1 — v1 推荐**每 workspace 一个 bot account 一个 listener**（隔离 + 简单）
   - v1.5 优化：一个 listener 进程 + workspace 路由（按 channel_id → workspace 反查）

6. **LLM intent router 输出 ai_reply 与 ai_qa 输出 reply 是否重叠？**
   - intent=ai_qa 时 LLM 已经返回了 ai_reply（一次调用搞定）
   - 推荐：v1 LLM router 返回 ai_reply 后直接用，不再二次调 ai_qa — 节省一次 LLM call

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio + pytest-httpx + browser-use/browser-harness (E2E CDP) |
| Config file | `backend/pyproject.toml [tool.pytest.ini_options]` + `e2e_v2/pyproject.toml` |
| Quick run command | `cd backend && uv run pytest tests/agent_builder/bot_dispatcher/ -x -q` |
| Full suite command | `cd backend && uv run pytest tests/ -q --cov=app.agent_builder.bot_dispatcher --cov-report=term-missing` |
| E2E suite command | `cd e2e_v2 && RUN_E2E=1 uv run pytest specs/test_phase_4_5_*.py -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| R-IM-01 | bot.yaml Pydantic schema strict validate | unit | `pytest tests/agent_builder/bot_dispatcher/test_bot_config_schema.py -x` | ❌ Wave 1 |
| R-IM-01 | bot.yaml unknown field raise | unit | `pytest tests/agent_builder/bot_dispatcher/test_bot_config_schema.py::test_extra_forbid -x` | ❌ Wave 1 |
| R-IM-02 | HandlerRegistry register / resolve / dispatch | unit | `pytest tests/agent_builder/bot_dispatcher/test_registry.py -x` | ❌ Wave 2 |
| R-IM-02 | handler_ref importlib 解析失败 fail-fast | unit | `pytest tests/agent_builder/bot_dispatcher/test_registry.py::test_handler_import_fails -x` | ❌ Wave 2 |
| R-IM-03 | help 元数据驱动（按 role 过滤） | unit | `pytest tests/agent_builder/bot_dispatcher/test_builtin_help.py -x` | ❌ Wave 5 |
| R-IM-04 | LLM intent classify + confidence | unit (mock LLM) | `pytest tests/agent_builder/bot_dispatcher/test_llm_router.py -x` | ❌ Wave 2 |
| R-IM-04 | LLM timeout → ai_qa 兜底 | unit | `pytest tests/agent_builder/bot_dispatcher/test_llm_router.py::test_timeout_falls_back -x` | ❌ Wave 2 |
| R-IM-05 | DM / @mention / keywords 三 OR 触发 | unit | `pytest tests/agent_builder/bot_dispatcher/test_listener_filter.py -x` | ❌ Wave 4 |
| R-IM-05 | Bot 自己消息跳过（防死循环） | unit | `pytest tests/agent_builder/bot_dispatcher/test_listener_filter.py::test_skip_self -x` | ❌ Wave 4 |
| R-IM-06 | sender_name → users 表对齐 | integration (DB) | `pytest tests/agent_builder/bot_dispatcher_integration/test_identity_alignment.py -x` | ❌ Wave 3 |
| R-IM-06 | reject_friendly 给 unknown user 友好提示 | integration | `pytest tests/agent_builder/bot_dispatcher_integration/test_identity_alignment.py::test_unknown_reject -x` | ❌ Wave 3 |
| R-IM-07 | self_apply 模式 + SELF_APPLY_SENTINEL | unit | `pytest tests/agent_builder/bot_dispatcher/test_parser.py::test_self_apply -x` | ❌ Wave 2 |
| R-IM-11 | dispatch audit log 入库 | integration (DB) | `pytest tests/agent_builder/bot_dispatcher_integration/test_audit.py -x` | ❌ Wave 5 |
| R-IM-12 | rate limit per_user_per_minute（Redis） | integration (Redis) | `pytest tests/agent_builder/bot_dispatcher_integration/test_rate_limit.py -x` | ❌ Wave 5 |
| R-IM-13 | idempotency_key 防重复 | integration (Redis) | `pytest tests/agent_builder/bot_dispatcher_integration/test_idempotency.py -x` | ❌ Wave 5 |
| N-IM-01 | listener ≥ 50 msg/s | integration (load) | `pytest tests/agent_builder/bot_dispatcher_integration/test_throughput.py -x -m slow` | ❌ Wave 5 |
| N-IM-02 | WS 断线重连指数退避 + jitter | integration (mock MM) | `pytest tests/agent_builder/bot_dispatcher_integration/test_reconnect.py -x` | ❌ Wave 4 |
| N-IM-03 | bot.yaml 凭据明文检测 | unit | `pytest tests/agent_builder/bot_dispatcher/test_credential_leak_guard.py -x` | ❌ Wave 1 |
| N-IM-04 | handler 异常不 leak stack 到 bot 回复 | unit | `pytest tests/agent_builder/bot_dispatcher/test_exception_wrapping.py -x` | ❌ Wave 3 |
| N-IM-05 | LLM timeout 5s 不阻塞 dispatcher | unit | `pytest tests/agent_builder/bot_dispatcher/test_llm_router.py::test_async_timeout_isolation -x` | ❌ Wave 2 |
| **E2E** | Mattermost @bot help 收到帮助 | e2e (CDP) | `cd e2e_v2 && pytest specs/test_phase_4_5_help.py -v` | ❌ Wave 6 |
| **E2E** | Mattermost @bot start <wf_id> 启动 workflow | e2e | `cd e2e_v2 && pytest specs/test_phase_4_5_start_workflow.py -v` | ❌ Wave 6 |
| **E2E** | DM "我要启动流程" → LLM 路由到 start | e2e | `cd e2e_v2 && pytest specs/test_phase_4_5_llm_intent.py -v` | ❌ Wave 6 |
| **E2E** | Bot 自己消息不触发死循环 | e2e | `cd e2e_v2 && pytest specs/test_phase_4_5_no_echo_loop.py -v` | ❌ Wave 6 |
| **E2E** | 双 workspace 互不影响 bot dispatch | e2e | `cd e2e_v2 && pytest specs/test_phase_4_5_multi_workspace.py -v` | ❌ Wave 6 |
| **E2E** | rate limit 命中后给友好提示 | e2e | `cd e2e_v2 && pytest specs/test_phase_4_5_rate_limit_e2e.py -v` | ❌ Wave 6 |

### Sampling Rate

- **Per task commit:** `cd backend && uv run pytest tests/agent_builder/bot_dispatcher/ -x -q`（< 30s 单元测试快反馈）
- **Per wave merge:** `cd backend && uv run pytest tests/ -q`（全后端测试）+ `cd e2e_v2 && pytest specs/test_phase_4_5_*.py --collect-only -q`（collect smoke）
- **Phase gate:** Full suite green + E2E green：`cd backend && uv run pytest tests/ -q && cd ../e2e_v2 && RUN_E2E=1 uv run pytest specs/test_phase_4_5_*.py -v`

### Wave 0 Gaps

- [ ] `backend/tests/agent_builder/bot_dispatcher/__init__.py` + conftest fixtures (bot_config_factory, mock_llm, mock_redis, mock_session_factory)
- [ ] `backend/tests/agent_builder/bot_dispatcher_integration/__init__.py` + conftest（真实 PG + Redis testcontainers）
- [ ] `e2e_v2/specs/conftest_phase_4_5.py` + helpers（MM container fixture + bot.yaml fixture + browser-harness CDP setup）
- [ ] `plugins/bots/test_workflow_bot.yaml` — E2E 测试用最小 bot.yaml
- [ ] `prompts/intent_router_zh.md` + `prompts/ai_qa_zh.md` — Jinja2 templates
- [ ] CI 加 `mattermostautodriver==2.0.0` 依赖（uv add）
- [ ] CI 加 Mattermost docker-compose service（已在 .44 mattermost-docker-mattermost-1 但 CI 也需要 — 用 mattermost/mattermost-team-edition image）

*(None of the above exist yet — all Wave 0 prerequisites)*

## Recommended Plan Topology

**6 plans / 6 waves（带 Wave 0 reading doc gate）**:

| Plan | Wave | 内容 | 工作量 | 依赖 | Reading Doc 要求 |
|------|------|-----|--------|------|----------------|
| **04_5-01** | 0 + 1 | Reading doc（Dify trigger / start node）+ bot.yaml schema + DB schema + Alembic 0007（workspace_bot_installations / bot_audit_logs / bot_rate_limits）+ tests 目录骨架 | M | — | ✅ Wave 0 硬性 gate（CLAUDE.md §2.7） |
| **04_5-02** | 2 | BotConfig loader + 启动期 strict validate + credential leak guard + CLI `agent-builder bot validate` | M | 04_5-01 | — |
| **04_5-03** | 2 | BotIntentRouter（LLM intent classify + 5s timeout + ai_qa 兜底）+ Jinja2 prompt templates + asyncio.timeout 模式 | M | 04_5-01 | — |
| **04_5-04** | 3 | HandlerRegistry + BotContext + BotDispatcher（串接 keywords → parse_command → llm_router → handler）+ 身份对齐 + 异常 wrap | L | 04_5-02, 04_5-03 | — |
| **04_5-05** | 4 + 5 | MattermostListener（WS init + 三 OR 触发 + 防 echo loop + reconnect + jitter）+ builtin handlers（help / start / status / list）+ rate limit + audit + idempotency + lifespan 接入 | L | 04_5-04 | — |
| **04_5-06** | 6 | E2E gate (browser-harness CDP) — 6 个 spec 覆盖 Phase 4.5 6 个 success criteria + 验证 Pitfall 1/4/6 回归 | L | 04_5-05 | ✅ browser-harness reading doc gate |

**总估算：** 6 plans / 14-18 天（含 buffer）

**并行机会**：Wave 2 内 Plan 04_5-02（loader）与 04_5-03（llm_router）独立 → 并行 dispatch 两个 Task（CLAUDE.md §2.1）。

**Wave 0 reading doc 要求**（CLAUDE.md §2.7 硬性 gate）：
- `docs/reading-dify-04_5-01-trigger-nodes-2026-05-18.md` 必读：
  - `/Users/admin/ai/ref/dify/repo/api/core/workflow/nodes/trigger_webhook/node.py`（webhook trigger node 模式）
  - `/Users/admin/ai/ref/dify/repo/api/core/trigger/entities/entities.py`（TriggerProviderEntity / EventEntity / Subscription schema）
  - `/Users/admin/ai/ref/dify/repo/api/core/workflow/nodes/start/`（流程入口节点）
- 必须先 commit reading doc 才能 commit 任何 feat: 代码（Task 0 gate）

## Sources

### Primary (HIGH confidence)

- **设计稿** `docs/plans/2026-05-17-im-bot-abstraction-design.md` — 13 R-IM 需求 + bot.yaml schema + 4 子阶段拆分（authoritative）
- **OUTLINE** `.planning/phases/04_5-bot-triggers/04_5-OUTLINE.md` — Slash Dispatcher 后端架构 + provider 优先级
- **ADR-001** `docs/plans/2026-05-17-platform-plugin-framework-ADR.md` — IMCapability.subscribe_events / TriggerCapability v1.1 骨架（本 phase business 层与之解耦）
- **CLAUDE.md** project 项目级硬性规则 — §2.7 Dify reading doc gate + §2.5 Safe Links + §2.4 多租户隔离 + §2.1 并行优先 + §2.2 E2E browser-harness
- **hr/offboarding-flow reference impl** (HIGH — 1.5 个月生产部署验证):
  - `/Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/services/bot_command_parser.py` (parser 模式 204 行)
  - `/Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/services/bot_intent_router.py` (LLM router 模式 137 行)
  - `/Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/services/bot_handler_registry.py` (registry 模式 89 行)
  - `/Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/services/bot_service.py` (dispatch 编排 736 行)
  - `/Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/workers/mattermost_listener.py` (WS listener 254 行)
- **Phase 4 既有代码**:
  - `backend/app/agent_builder/notification/providers/base.py` (IMProvider Protocol)
  - `backend/app/agent_builder/notification/providers/mattermost.py` (Mattermost 出站，本 phase 入站独立)
  - `backend/app/agent_builder/core/im_credentials.py` (IMCredentialsManager 模式)
- **Phase 5.A 既有代码**:
  - `backend/app/agent_builder/platforms/manifest.py` (Pydantic v2 extra=forbid 模式)
  - `backend/app/agent_builder/platforms/capabilities/im.py` (IMCapability subscribe_events stub)
  - `backend/app/agent_builder/platforms/capabilities/trigger.py` (TriggerCapability v1.1 骨架)
- **Phase 3 既有代码**:
  - `backend/app/models/audit_log.py` (NET-05 audit_logs schema 思路)
  - `backend/app/agent_builder/hitl/token_store.py` (Redis SET NX 模式)
- **Dify trigger 模块（参考）**:
  - `/Users/admin/ai/ref/dify/repo/api/core/workflow/nodes/trigger_webhook/node.py`（webhook node 实现）
  - `/Users/admin/ai/ref/dify/repo/api/core/trigger/entities/entities.py`（TriggerProviderEntity / EventEntity）
  - `/Users/admin/ai/ref/dify/repo/api/core/trigger/trigger_manager.py`（trigger lifecycle）

### Secondary (MEDIUM confidence)

- [mattermostautodriver PyPI](https://pypi.org/project/mattermostautodriver/) — 2.0+ async driver，starting 10.8.2 跟随 server release
- [mattermostdriver docs](https://vaelor.github.io/python-mattermost-driver/) — keepalive=True / keepalive_delay=5 参考
- [FastAPI Background Tasks 2026](https://fastapi.tiangolo.com/tutorial/background-tasks/) — lifespan 长任务模式
- [DEV Community: Python Background Tasks Asyncio Traps 2026](https://dev.to/kaushikcoderpy/python-background-tasks-asyncio-traps-fastapi-celery-2026-381i) — 长任务 lifecycle 管理
- agent-builder ROADMAP / REQUIREMENTS.md 既有 Phase 4 收尾状态（NOTI-* 已 Complete）

### Tertiary (LOW confidence — 需 plan 期验证)

- mattermostautodriver 2.0.0 与 server 11.x 兼容性（hr 用过去版本 OK；Phase 4.5 plan-phase 时验证当前 .44 上 MM server 版本）
- Mattermost slash command 注册到 admin console API 是否必需（OUTLINE 写"启动时向 Mattermost 注册 slash 命令列表" — 但本 phase 决定走 @-mention + keywords 三 OR，slash 仅本地 parser 识别 — plan 期需用户确认是否走 MM Admin Console API 注册流程）

## Metadata

**Confidence breakdown:**
- Standard Stack: HIGH — 所有库版本 Phase 1-5.A 已锁；新增 mattermostautodriver 2.0+ 在 hr 生产验证 1.5 个月
- Architecture Patterns: HIGH — hr reference impl 5 个核心文件 + 1.5 个月生产打磨 + 设计稿 §4-§7 已穷举
- Pitfalls: HIGH — 12 个均有 hr / Phase 3 / Phase 4 实战来源 + 测试用例可执行
- LLM intent router: MEDIUM — confidence threshold 0.6 / 5s timeout 是 hr 实测值；本项目 LLM provider（GLM）输出 JSON 严格度需 plan 期复测
- E2E architecture: MEDIUM — browser-harness + MM container 路径已通（Phase 4-12 验证）；MM bot account setup 流程 plan 期需补 helper

**Research date:** 2026-05-18
**Valid until:** 2026-06-18（30 天 — 核心栈稳定；mattermostautodriver 跟随 MM server 11.x 滚动，需关注 server major 升级）

---

## RESEARCH COMPLETE
