---
phase: 04_5-bot-triggers
plan: "01"
subsystem: bot-dispatcher

tags: [pydantic-v2, alembic, mattermost, httpx, bot-dispatcher, bot-yaml, im, audit]

requires:
  - phase: 04-approval-chain-im
    provides: "Phase 4 IM provider 抽象 (MattermostProvider 出站) + lark/wecom/dingtalk/slack 模板"
  - phase: 05-platform-plugin-foundation
    provides: "Phase 5.A workspace_plugin_installations 模式 (0006 migration) + manifest.py ConfigDict(extra='forbid') 模式"

provides:
  - "BotConfig Pydantic v2 schema (12 子 model + 3 @model_validator)"
  - "httpx 0.28+ vs mattermostautodriver 2.0 兼容垫片 (Pitfall 2)"
  - "WorkspaceBotInstallation ORM + UNIQUE (workspace_id, bot_name) 隔离"
  - "BotAuditLog ORM (BIGSERIAL) + outcome/routed_via CHECK 约束"
  - "Alembic 0007 migration (workspace_bot_installations + bot_audit_logs 双表)"
  - "Wave 2-5 plans 共用的 schema 契约（loader / parser / llm_router / registry / listener 输入契约冻结）"

affects:
  - "Wave 2 plans (04_5-02 loader + parser)"
  - "Wave 3 plans (04_5-03 llm_router + registry + dispatcher)"
  - "Wave 4 plans (04_5-05 MattermostListener — 必须 import 前 apply_httpx_patch())"
  - "Wave 5 plans (04_5-06 audit + rate_limit — 写 bot_audit_logs)"
  - "Phase 5.E 飞书/企微/钉钉/Slack 入站 — ProviderSpec.type Literal 扩展"

tech-stack:
  added: []  # 本 plan 未引入新依赖（pydantic v2 / sqlalchemy / alembic 均 Phase 1+ 已锁）
  patterns:
    - "ConfigDict(extra='forbid') 全 12 sub-model（与 Phase 5.A manifest.py 一致）"
    - "3 个 @model_validator(mode='after') 跨字段一致性校验"
    - "递归扫描 model_dump() 检测明文凭据 (Pitfall 7)"
    - "httpx monkey-patch 幂等 + 显式时机控制 (Wave 4 才 apply)"
    - "BIGSERIAL audit log + JSONB cmd_args + 长度 CHECK (防 OOM)"

key-files:
  created:
    - "docs/reading-dify-04_5-01-trigger-nodes-2026-05-18.md"
    - "backend/app/agent_builder/bot_dispatcher/__init__.py"
    - "backend/app/agent_builder/bot_dispatcher/schemas/__init__.py"
    - "backend/app/agent_builder/bot_dispatcher/schemas/bot_config.py"
    - "backend/app/agent_builder/bot_dispatcher/httpx_patch.py"
    - "backend/app/agent_builder/models/workspace_bot_installation.py"
    - "backend/app/agent_builder/models/bot_audit_log.py"
    - "backend/migrations/versions/0007_phase45_bot_dispatcher.py"
    - "backend/tests/agent_builder/bot_dispatcher/conftest.py"
    - "backend/tests/agent_builder/bot_dispatcher/test_bot_config_schema.py"
    - "backend/tests/agent_builder/bot_dispatcher/test_httpx_patch.py"
    - "backend/tests/agent_builder/bot_dispatcher_integration/conftest.py"
    - "backend/tests/agent_builder/bot_dispatcher_integration/test_migration_0007.py"
  modified:
    - "backend/app/agent_builder/models/__init__.py"
    - "backend/migrations/env.py"

key-decisions:
  - "12 sub-model 全部 ConfigDict(extra='forbid') — 防 typo 第一防线（与 Phase 5.A manifest.py 模式一致）"
  - "no_plaintext_credentials 递归扫描而非单层 — 支持 SelfApplySpec.arg_default 等嵌套 dict 内的凭据检测"
  - "凭据检测仅命中 ≥32 char + _token/_secret/_key 后缀（防误伤 env 名占位符如 MM_BOT_TOKEN）"
  - "intents_must_subset_commands 校验时 intents - {ai_qa} ⊆ commands.name（ai_qa 是兜底特殊值）"
  - "ProviderSpec.type 用 Literal[\"mattermost\"]（v1 锁定；5.E 扩展时 union 5 个）"
  - "WorkspaceBotInstallation 仿 0006 plugin 模式 / BotAuditLog 仿 0001 audit_logs BIGSERIAL 模式"
  - "httpx_patch 不 module-level auto-apply — Wave 4 listener startup 显式调用（控制副作用时机）"
  - "raw_message ≤4096 + error_message ≤1024 数据库层 CHECK（防恶意大消息 OOM）"

patterns-established:
  - "Pattern A: bot.yaml schema 是 dispatcher / parser / loader 共用真相源，Wave 1 冻结后 Wave 2-5 只读不改"
  - "Pattern B: 启动期 raise vs 运行时 silent — 三个 @model_validator 让所有配置错误在 BotConfig.model_validate 立即可见（防部署后 silent miss-route）"
  - "Pattern C: monkey-patch 显式时机 — 不 module-level auto-apply 而是 listener startup 调用，幂等保证多 task 重复调用安全"

requirements-completed:
  - R-IM-01
  - R-IM-11
  - R-IM-12
  - N-IM-03

duration: 14min
completed: 2026-05-18
---

# Phase 4.5 Plan 01: bot.yaml schema + DB schema + Pitfall 2 兼容垫片 Summary

**BotConfig Pydantic v2 schema (12 子 model + 3 model_validator) + WorkspaceBotInstallation/BotAuditLog ORM + Alembic 0007 + httpx mattermostautodriver 兼容垫片，为 Wave 2-5 dispatcher/listener/audit 提供单一真相源**

## Performance

- **Duration:** 14 min
- **Started:** 2026-05-17T18:07:03Z
- **Completed:** 2026-05-18T (本 plan 完成时)
- **Tasks:** 4 (Task 0 reading doc + Task 1 schema + Task 2 ORM/migration + Task 3 tests)
- **Files modified:** 15 (13 new + 2 modified)

## Accomplishments

- **Dify reading doc gate** ✓ — 提取 6 条可借鉴模式 + 3 处偏离决策（140 行）
- **BotConfig 12 sub-model 全部 extra=forbid** ✓ — 12 个 BaseModel + 3 个 model_validator 全部启动期 raise
- **Pitfall 2 兼容垫片** ✓ — apply_httpx_patch() 幂等 + 不 auto-apply（Wave 4 显式调用时机）
- **Pitfall 7 防护** ✓ — 递归扫描 model_dump 检测 _token/_secret/_key 后缀 ≥32 char 明文凭据
- **Pitfall 8 防护** ✓ — intents - {ai_qa} ⊆ commands.name 启动期 raise（防 LLM 选了不存在的命令 silent fail）
- **ORM + Alembic 0007** ✓ — 双表 + 5 个 CHECK + 5 个索引 + UNIQUE 约束（与 Phase 5.A 0006 模式一致）
- **测试矩阵** ✓ — 47 cases 全绿（20 schema + 5 httpx + 22 migration）
- **Phase 5.A regression** ✓ — 271 platforms 测试 0 fail
- **Phase 4 IM regression** ✓ — 154 IM provider 测试 0 fail

## Task Commits

每个 Task 独立 atomic commit：

1. **Task 0: Dify reading doc gate** — `4d7b59f` (docs)
2. **Task 1a: httpx 兼容垫片** — `e2187ef` (feat)
3. **Task 1b: BotConfig Pydantic schema** — `b74590c` (feat)
4. **Task 2a: ORM 模型** — `358e7d0` (feat)
5. **Task 2b: Alembic 0007 migration** — `d4897db` (feat)
6. **Task 3: 单元 + 集成测试** — `61b8cd5` (test)
7. **deferred items 标注** — `137841b` (docs)

总计 7 个 commit（含 Task 0 reading doc gate 首 commit）。

## Files Created/Modified

### 新增（13 个文件）

- `docs/reading-dify-04_5-01-trigger-nodes-2026-05-18.md` — Dify trigger 阅读笔记（140 行）
- `backend/app/agent_builder/bot_dispatcher/__init__.py` — 子包入口
- `backend/app/agent_builder/bot_dispatcher/schemas/__init__.py` — schemas 子包 + 显式导出
- `backend/app/agent_builder/bot_dispatcher/schemas/bot_config.py` — 12 sub-model + 3 model_validator（460 行）
- `backend/app/agent_builder/bot_dispatcher/httpx_patch.py` — Pitfall 2 兼容垫片
- `backend/app/agent_builder/models/workspace_bot_installation.py` — Per-workspace bot 安装态 ORM
- `backend/app/agent_builder/models/bot_audit_log.py` — dispatch 审计日志 ORM (BIGSERIAL)
- `backend/migrations/versions/0007_phase45_bot_dispatcher.py` — Alembic 双表 migration
- `backend/tests/agent_builder/__init__.py` + 4 个子包 __init__.py + 2 个 conftest.py
- `backend/tests/agent_builder/bot_dispatcher/test_bot_config_schema.py` — 20 schema unit tests
- `backend/tests/agent_builder/bot_dispatcher/test_httpx_patch.py` — 5 httpx unit tests
- `backend/tests/agent_builder/bot_dispatcher_integration/test_migration_0007.py` — 22 migration integration tests

### 修改（2 个文件）

- `backend/app/agent_builder/models/__init__.py` — 新增 WorkspaceBotInstallation / BotAuditLog 导出
- `backend/migrations/env.py` — autogenerate 发现新表

## Dify 参考点

详见 `docs/reading-dify-04_5-01-trigger-nodes-2026-05-18.md`。提取的 6 条借鉴 + 3 处偏离：

**借鉴（在本 plan 落地）**:
1. `ConfigDict(extra="forbid")` 12 sub-model 全开（来自 Dify `core/trigger/entities/entities.py`）
2. 嵌套 BaseModel 切分（identity / triggers / commands / fallback / audit / help 各自独立）
3. Literal vs StrEnum 选择 — ProviderSpec.type 用 Literal["mattermost"]（v1 锁 1 个）
4. `@model_validator(mode="after")` 跨字段一致性校验
5. tenant_id 注入 + 资源隔离 — workspace_id 第一列 + UNIQUE (workspace_id, bot_name)
6. handler 异常不 leak —— audit_logs.outcome=handler_error 字段预留位置

**偏离（本项目特有）**:
1. `no_plaintext_credentials` validator — Dify 把 credentials 入 YAML（plugin daemon 加密存），本项目硬规则凭据只能 env 注入（N-IM-03）
2. `at_least_one_trigger` validator — Dify webhook 必有 endpoint，bot dispatcher 三触发配错全 False 会变死 bot
3. `intents_must_subset_commands` validator — Dify trigger 与 node 解耦，本项目 LLM intent 直接路由 commands.name 必须一致

## BotConfig schema 设计取舍

| 设计选择 | 选了什么 | 备选 | 理由 |
|---|---|---|---|
| **字段切分粒度** | 12 sub-model（identity / triggers / commands / fallback / audit / help 各自独立） | 1 mega-class | bot.yaml 字段跨四个语义域（dispatch / 触发 / 审计 / help），切多 sub-model 比 5.A manifest 扁平 CapabilitySpec 更清晰 |
| **extra 行为** | `forbid` 全 12 sub-model | `ignore`（默认）/ `allow` | 5.A 已验证 typo 是 bug 常见源，forbid 启动期就 raise |
| **三个 validator 选型** | `@model_validator(mode='after')` | `@field_validator` / `mode='before'` | 三个都是**跨字段**一致性检查（不是单字段约束），model_validator 是正确选择 |
| **凭据扫描范围** | 仅 ≥32 char + _token/_secret/_key 后缀 | 任意长度 / 任意敏感词 | 防误伤 env 名占位符（如 "MM_BOT_TOKEN" 13 chars）和短描述 |
| **凭据扫描深度** | 递归全树 | 仅顶层字段 | 支持 SelfApplySpec.arg_default / cmd_args_json 等嵌套 dict 内检测 |
| **凭据 raise message** | 仅打印字段路径 | 包含 value | value 本身是凭据，打印会 leak 到日志 |
| **ProviderSpec.type** | `Literal["mattermost"]`（v1） | StrEnum 多值 | v1 锁 1 个值，5.E 扩展飞书时 union 5 个仍可控 |

## Pitfall 2/7/8 防护落地点

| Pitfall | 防护点 | 文件 |
|---|---|---|
| **Pitfall 2** (httpx 0.28+ vs mattermostautodriver 2.0) | `apply_httpx_patch()` monkey-patch pop proxies kwarg；幂等；不 auto-apply | `backend/app/agent_builder/bot_dispatcher/httpx_patch.py` |
| **Pitfall 7** (bot.yaml 凭据明文) | `no_plaintext_credentials` @model_validator 递归扫描 _token/_secret/_key 后缀 + value ≥32 char raise | `backend/app/agent_builder/bot_dispatcher/schemas/bot_config.py:L320-L350` |
| **Pitfall 8** (命令 ↔ intent 冲突) | `intents_must_subset_commands` @model_validator 启动期 raise | `backend/app/agent_builder/bot_dispatcher/schemas/bot_config.py:L295-L315` |

## ORM + Migration 字段表

### workspace_bot_installations（9 字段）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | UUID PK | gen_random_uuid() server default |
| workspace_id | UUID NOT NULL | 多租户基线第一列 |
| bot_name | TEXT NOT NULL | 匹配 BotConfig.name pattern |
| yaml_path | TEXT NOT NULL | bot.yaml 文件路径 |
| status | TEXT NOT NULL default 'enabled' | CHECK IN ('enabled','disabled','error') |
| config_snapshot_json | JSONB NOT NULL default '{}' | bot.yaml 加载快照 |
| last_error | TEXT NULL | status=error 时填充 |
| installed_at | TIMESTAMPTZ NOT NULL default now() | |
| updated_at | TIMESTAMPTZ NOT NULL default now() | |

**约束**: UNIQUE (workspace_id, bot_name) + CHECK status
**索引**: ix_workspace_bot_workspace_status (workspace_id, status) + ix_workspace_bot_status_updated (status, updated_at)

### bot_audit_logs（14 字段）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGSERIAL PK | 时序有序 |
| workspace_id | UUID NOT NULL | 多租户基线第一列 |
| bot_name | TEXT NULL | |
| sender_name | TEXT NULL | IM 内部用户名 |
| sender_user_id | UUID NULL | 对齐 agent-builder users.id |
| cmd_name | TEXT NULL | 命中 commands.name |
| cmd_args_json | JSONB NULL | 校验通过的 args dict |
| raw_message | TEXT NULL | CHECK char_length ≤ 4096 |
| outcome | TEXT NOT NULL | CHECK 5 值（success/permission_denied/rate_limited/parse_failed/handler_error） |
| error_message | TEXT NULL | CHECK char_length ≤ 1024 |
| latency_ms | INTEGER NOT NULL default 0 | |
| routed_via | TEXT NOT NULL | CHECK 4 值（slash_command/keyword/llm_intent/ai_qa） |
| llm_confidence | FLOAT NULL | 仅 routed_via=llm_intent 有值 |
| created_at | TIMESTAMPTZ NOT NULL default now() | |

**约束**: 4 个 CHECK
**索引**: ix_bot_audit_workspace_created + ix_bot_audit_outcome_created + ix_bot_audit_bot_name_created

## 与 Wave 2-5 plans 的接口契约

### 冻结的 schema 契约（Wave 2-5 只读不改）

```python
# Wave 2 loader 输入契约
from app.agent_builder.bot_dispatcher.schemas import BotConfig
config = BotConfig(**yaml.safe_load(open("bot.yaml")))

# Wave 3 dispatcher 输入契约
from app.agent_builder.bot_dispatcher.schemas import CommandSpec, FallbackSpec

# Wave 4 listener 启动前置依赖
from app.agent_builder.bot_dispatcher.httpx_patch import apply_httpx_patch
apply_httpx_patch()  # ⚠️ 必须在 import mattermostautodriver 之前
import mattermostautodriver

# Wave 5 audit logger 输出契约
from app.agent_builder.models import BotAuditLog
log = BotAuditLog(
    workspace_id=..., outcome="success", routed_via="slash_command", ...
)
```

### Wave 5 outcome / routed_via 业务代码必须保持一致

```python
# bot_dispatcher.audit 必须使用这 5 值（CHECK 约束兜底）
OUTCOME_VALUES = ("success", "permission_denied", "rate_limited", "parse_failed", "handler_error")
ROUTED_VIA_VALUES = ("slash_command", "keyword", "llm_intent", "ai_qa")
```

## 测试矩阵

| 测试类型 | 文件 | 数量 | 通过率 |
|---|---|---|---|
| 单元测试 — schema | `test_bot_config_schema.py` | 20 | 20/20 |
| 单元测试 — httpx_patch | `test_httpx_patch.py` | 5 | 5/5 |
| 集成测试 — migration 0007 | `test_migration_0007.py` | 22 | 22/22 |
| **小计** | | **47** | **47/47** |

### Regression check

| 测试集 | 数量 | 结果 |
|---|---|---|
| Phase 5.A platforms | 271 | 271 pass / 1 skip / 0 fail |
| Phase 4 IM (excl feishu pre-existing env issue) | 154 | 154 pass / 0 fail |
| **总计 regression** | **425** | **425/425 (除 pre-existing)** |

Pre-existing 环境问题 `lark_oapi` 已记录到 `.planning/phases/04_5-bot-triggers/deferred-items.md`（非本 phase 引入；本 phase 任何代码改动均未触及 feishu provider）。

## Decisions Made

详见 frontmatter `key-decisions`。

## Deviations from Plan

None — 计划严格按 PLAN.md 执行。

- Task 0 reading doc 140 行（≥ 80 行 gate ✓）
- Task 1 拆 2 commit（httpx_patch + BotConfig schema）符合 PLAN.md commit 拆分
- Task 2 拆 2 commit（ORM + Alembic）符合 PLAN.md commit 拆分
- Task 3 测试 47 cases > PLAN.md 要求 ≥ 28 cases

唯一计划外的小动作：
- 新增 `deferred-items.md` 记录 pre-existing `lark_oapi` 环境问题（按 GSD scope boundary 规则该 log 到 deferred 而不是 fix）

## Issues Encountered

None — Task 3 集成测试首次跑触发"relation bot_audit_logs does not exist"是因为 alembic head 还在 0006；执行 `alembic upgrade head` 后立即 22/22 通过。这是预期路径不是 issue。

## User Setup Required

None — 本 plan 不引入外部服务配置（凭据 env 注入由后续 Wave 4 listener 接入时处理）。

## Next Phase Readiness

**Wave 2 plans (04_5-02 loader + parser) 可立即开工**：
- BotConfig schema 已冻结 ✓
- workspace_bot_installations 表已可用 ✓
- bot_audit_logs 表已可用 ✓

**Wave 4 plan (04_5-05 MattermostListener) 启动前置**：
- 必须在 `import mattermostautodriver` 之前调用 `apply_httpx_patch()` ✓
- httpx_patch.py 接口已稳定 ✓

**Phase 5.E 飞书/企微/钉钉/Slack 入站时**：
- 修改 `ProviderSpec.type` Literal 扩展 4 个值即可（schema 其他字段无需改）
- bot_audit_logs / workspace_bot_installations 表无需改

---
*Phase: 04_5-bot-triggers*
*Completed: 2026-05-18*

## Self-Check: PASSED

- 13 个新建文件全部 FOUND
- 7 个 commit hash 全部 FOUND
- 47/47 单元 + 集成测试 pass
- Phase 5.A regression 0 fail
- Phase 4 IM regression 0 fail (除 pre-existing lark_oapi 环境问题已 deferred)
- reading doc 140 行 ≥ 80 行 gate ✓
- reading doc commit `4d7b59f` 早于任何 feat commit（CLAUDE.md §2.7 硬性 gate ✓）
