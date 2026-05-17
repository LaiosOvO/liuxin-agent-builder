# Dify 阅读笔记 — Legacy / Migration 模块（Phase 5.A Plan 06 LegacyIMProviderAdapter 参考）

> 日期: 2026-05-17
> 仓库: <https://github.com/langgenius/dify> (commit `e7e6fe88` (auto-pulled 2026-05-16), local clone `/Users/admin/ai/ref/dify/repo/`)
> Stars: ~141k
> License attribution: Dify is **AGPL-3.0**, this project (agent-builder) is **Apache-2.0**.
> 仅借鉴**设计模式 / 数据结构 / 边界考虑**，**严禁拷源代码** —— CLAUDE.md §2.7 强制规则。

---

## 项目概述

Dify 是国内最成熟的开源 LLM Workflow / Agent 平台（141k stars，2 年 + 数百贡献者）。其 plugin 体系经历了从「内置 Python class 注册」到「daemon 进程 plugin」的迁移，留下了一整套**老数据 → 新 plugin schema 的迁移逻辑**与**新老 provider 共存策略**。这正是 Phase 5.A Plan 06 LegacyIMProviderAdapter 要解决的核心场景：**Phase 4 老 IMProvider（6 家：飞书/企微/钉钉/Slack/Mattermost/Webhook）必须通过新 IMCapability 接口被调用，且 Phase 4 既有测试 0 regression**。

本次 reading focus：
- `api/services/plugin/data_migration.py`（212 行）—— Dify 把数据库表中的老 provider 字段（`provider_name="openai"` → `"langgenius/openai/openai"`）迁到 plugin 命名空间的整体策略
- `api/services/plugin/plugin_migration.py`（619 行）—— plugin 安装迁移流程（含 tenant 维度并发处理、失败列表、idempotent 重试）
- `api/services/plugin/plugin_auto_upgrade_service.py`（85 行）—— 租户级 plugin 升级策略（whitelist/blacklist/fix-only/all 4 模式）

---

## 技术栈

| 维度 | Dify 实现 | 本项目 Plan 06 对照 |
| --- | --- | --- |
| 迁移触发 | CLI `flask migrate plugins` + chunked batch | **不做** — Plan 06 in-memory adapter wrap（无持久化迁移；只要 `register_provider()` 调用就自动 wrap） |
| 双轨期数据 | DB 表 `provider_name` 同时存「裸 name」+「plugin namespace name」 | **双 dict** —— `_PROVIDERS: dict[str, IMProvider]`（老） + `_PROVIDERS_AS_CAP: dict[str, LegacyIMProviderAdapter]`（新） |
| 老 schema 兼容 | `select where provider_name not like '%/%'` 识别旧记录 | LegacyIMProviderAdapter wrap 旧 IMProvider，方法签名转译 |
| 失败处理 | `failed_ids: list[str]`，跳过继续；最后报告 | 5.A Plan 06 `_maybe_wrap_for_capability` 用 try/except ImportError 静默 fallback（测试隔离场景） |
| 调度入口 | `PluginDataMigration.migrate()` classmethod | `register_provider()` 入口零接口破坏，内部追加 `_maybe_wrap_for_capability(provider)` |

---

## 架构要点

### Dify 的「双轨期数据共存」模式（关键借鉴）

Dify 把老 model provider 数据从 `provider_name="openai"` 迁到 `"langgenius/openai/openai"` 的过程不是**一次性 cutover**：

```
[Dify 迁移期数据库实际状态]
DB 表：
  providers
  ├─ row1: provider_name = "openai"                      ← 旧记录（未迁）
  ├─ row2: provider_name = "langgenius/openai/openai"    ← 迁完
  └─ row3: provider_name = "google"                      ← 旧记录（未迁）

Dify 应用层（model_provider_factory）：
  - 读取时：name 含 "/" → 走 plugin 路由；不含 "/" → 走 legacy 内置 provider
  - 写入时：永远写 "langgenius/openai/openai" 命名空间形式
  - migration CLI 把所有 row 改成命名空间形式

[本项目 Plan 06 类比]
内存中：
  _PROVIDERS       = {"feishu": FeishuProvider(), "wecom": WecomProvider()}   ← Phase 4 老路径
  _PROVIDERS_AS_CAP = {"feishu": LegacyAdapter(FeishuProvider), 
                       "wecom": LegacyAdapter(WecomProvider)}                 ← Phase 5.A 新路径

调用方：
  - 旧代码：get_provider("feishu") → 拿 IMProvider，调 send_hitl_card(recipient: str, ...)
  - 新代码：get_capability_for_legacy("feishu") → 拿 LegacyAdapter（实 IMCapability），
            调 send_card(*, recipient: RecipientSpec, card: NormalizedCard, ...)
  - Registry.get_capability(IMCapability, prefer="feishu") fallback 到 _PROVIDERS_AS_CAP
```

**核心差异**：
- Dify 持久化层有迁移痛点（需 chunk + worker pool + idempotent SQL）— 我们只是 in-memory 双 dict，**轻量级 N 倍**
- Dify 旧 + 新 schema 共存于同一 DB 表 —— 我们是**两个独立 dict**，更清晰
- Dify migration CLI 是**强制**（v0.x → v1.x cutover） —— 本项目 LegacyAdapter wrap 是**自动**（register_provider 调一次就完成 wrap，永远不强制迁移 — CONTEXT.md 决策）

### Dify 的「新老接口并存」原则

```
Dify provider 调用路径（迁移期同时支持）：
┌────────────────────────────────────────────────────────────┐
│  ModelProviderFactory.get_provider_schema(provider_name)   │
│         │                                                   │
│         ├─ 命名空间形式（含 "/"）→ PluginService 路由      │
│         └─ 裸名形式 → 内置 Python class 路由（Provider）   │
└────────────────────────────────────────────────────────────┘

本项目 Plan 06（PlatformPluginRegistry.get_capability）：
┌─────────────────────────────────────────────────────────────────┐
│  Registry.get_capability(workspace_id, IMCapability, prefer)    │
│         │                                                        │
│         ├─ manifest plugin 候选（_MANIFESTS dict 中找到）→ Facade│
│         └─ manifest 查无 + cap_name == "im" →                   │
│             fallback 到 _PROVIDERS_AS_CAP[prefer or first]      │
│             返回 LegacyIMProviderAdapter                        │
└─────────────────────────────────────────────────────────────────┘
```

**为什么需要 fallback**：CONTEXT.md decision 明确「新老 plugin 完全共存」+「同一 workspace 可同时有老 register_provider 注册的 feishu 和新 manifest 注册的 huly」。但如果 workspace 还**没安装任何 manifest plugin** → 老的 Phase 4 6 家 IMProvider 必须能通过新 `get_capability(IMCapability)` 接口拿到 —— 这就是 **Blocker 3 修复**的核心：`registry.get_capability` 当 `cap_name=="im"` 且 manifest 候选用尽时，**fallback 查 `_PROVIDERS_AS_CAP`**。

### 简图 — 双轨注册 + fallback

```
┌──────────────────── startup ────────────────────┐
│                                                  │
│  notification.providers register_provider:       │
│  ┌────────────────────────────────────────────┐ │
│  │ FeishuProvider() → _PROVIDERS["feishu"]    │ │
│  │                  └→ _maybe_wrap_for_cap()  │ │
│  │                     └→ LegacyAdapter wrap  │ │
│  │                        → _PROVIDERS_AS_CAP │ │
│  │                          ["feishu"]        │ │
│  └────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────┘
            ▼                       ▼
  老代码 get_provider("feishu")     新代码 Registry.get_capability(IMCapability, prefer="feishu")
            │                       │
            │                       ▼
            │              查 _MANIFESTS["feishu"] → 没有 manifest plugin "feishu"
            │                       │
            │                       ▼
            │              cap_name=="im" → fallback 到 _PROVIDERS_AS_CAP
            │                       │
            ▼                       ▼
   IMProvider (raw)         LegacyIMProviderAdapter
   .send_hitl_card(...)     .send_card(*, recipient: RecipientSpec, ...)
            │                       │
            ▼                       ▼
   飞书原始 API 调用        adapter 内部转参 → 调底层 self._legacy.send_hitl_card
                                   │
                                   ▼
                          飞书原始 API 调用（共享同一实例）
```

---

## 可借鉴的设计模式（5 借鉴点对应 PLAN.md Task 0 要求）

### 借鉴点 1：双轨并存而非强制 cutover（来源：`data_migration.py:14-26` `PluginDataMigration.migrate`）

**Dify 原始模式**：
- migrate() classmethod 串行调多个 `migrate_db_records(...)`，每个表独立处理
- 老 schema（裸 provider_name）和新 schema（命名空间形式）**共存于同一表**，迁完一行算一行
- 任意时刻读取层都能容忍两种形式（应用层 detect + 路由）

**借鉴到 Plan 06**：
- `_PROVIDERS` 老 dict 不动 + `_PROVIDERS_AS_CAP` 新 dict 内部 wrap
- `register_provider` 接口签名 100% 不变（Phase 4 调用方零改动）
- `register_provider` 内部追加一行 `_maybe_wrap_for_capability(provider)` 写入新 dict
- 老代码走 `get_provider(name)` ；新代码走 `get_capability_for_legacy(name)` 或 Registry fallback
- **不强制迁移**（CONTEXT.md 决策 + 用户硬性 DoD #3）

**关键设计点 — 简化**：Dify 持久化层迁移需要批处理 + 失败列表 + worker pool；我们是内存中 wrap，**只需一行赋值** + try/except ImportError。

### 借鉴点 2：迁移失败容忍 + 静默降级（来源：`plugin_migration.py:103-104` `except Exception` + `data_migration.py:55-57` `failed_ids`）

**Dify 原始模式**：
```python
try:
    plugins = cls.extract_installed_plugin_ids(tenant_id)
    ...
except Exception:
    logger.exception("Failed to process tenant %s", tenant_id)
# 不 raise，继续下一个 tenant
```

**借鉴到 Plan 06**：
```python
def _maybe_wrap_for_capability(provider: "IMProvider") -> None:
    try:
        from app.agent_builder.platforms.legacy_im_adapter import (
            LegacyIMProviderAdapter,
        )
    except ImportError:
        # 测试隔离场景：platforms 模块未加载 → 静默 fallback（老路径仍工作）
        return
    _PROVIDERS_AS_CAP[provider.name] = LegacyIMProviderAdapter(provider)
```

**关键设计点**：测试场景下（特别是 Phase 4 单测）可能根本没 import `app.agent_builder.platforms.*` —— 那 wrap 注定失败，但**不能 raise**（会破坏 Phase 4 既有 51+ 测试 0 regression 承诺）。Dify 的 `except Exception + logger.exception` 模式直接套用，我们用更精确的 `ImportError` 捕获（仅捕获我们能容忍的失败）。

### 借鉴点 3：老接口字段最小化保留（来源：`data_migration.py:67-72` 处理 retrieval_model 部分字段）

**Dify 原始模式**：Dify 把 retrieval_model 这种**部分字段**单独处理（reranking_model.reranking_provider_name），其他字段不动。

**借鉴到 Plan 06**：LegacyAdapter 把 NormalizedCard 转 legacy 8 字段时，**仅必要字段填充**：

```python
async def send_card(self, *, recipient: RecipientSpec, card: NormalizedCard, idempotency_key: str) -> MessageRef:
    # 必须填的：recipient、deeplinks、description、title
    title_parts = card.title.split(" — ", 1)
    flow_title = title_parts[0] if title_parts else card.title
    node_title = title_parts[1] if len(title_parts) > 1 else ""
    
    result = await self._legacy.send_hitl_card(
        recipient=recipient.id,
        flow_title=flow_title,
        node_title=node_title,
        applicant_name="",    # NormalizedCard 不携带 — 留空
        actor_name="",
        deadline_at="",
        description=card.body_markdown,
        deeplinks=[{"action": a.get("action", ""), "url": a.get("url", "")} for a in card.actions],
    )
```

**关键设计点**：legacy `send_hitl_card` 接口分了 `flow_title` + `node_title` 两段，新 NormalizedCard 单 `title` 字段无法 100% 还原。借鉴 Dify「部分字段重写、其他默认」思路：用 " — " 作为分隔符 fallback 拆分（不是完美，但 lossy ≤ 1 字段 + 不破坏老 provider 接口）；其他 5 个老字段填空字符串。

### 借鉴点 4：迁移后旧接口仍可用（来源：`plugin_migration.py` 整体设计）

**Dify 原始模式**：迁移完成后**老接口仍然可用** —— `provider_name="openai"` 形式的查询仍能 hit 命名空间形式记录（应用层路由层兜底）。

**借鉴到 Plan 06**：
- Phase 4 `register_provider("feishu", FeishuProvider())` 调用方式 100% 不变
- Phase 4 `get_provider("feishu")` 仍然返回原 IMProvider（不返回 LegacyAdapter）
- 新代码可走 `get_capability_for_legacy("feishu")` 或 Registry fallback 拿 LegacyAdapter
- **同一 FeishuProvider 实例同时被两个 dict 引用**（老 dict 持 raw，新 dict 持 wrap 后的 adapter，但 adapter 内部 `self._legacy` 指向同一 raw provider —— 共享底层资源 / connection pool）

**关键设计点 — 关键不变量**：`get_provider(name) is _PROVIDERS_AS_CAP[name]._legacy`（同一 raw provider 实例）。Phase 4 测试 0 regression 的根本保障。

### 借鉴点 5：cap flags 推导（来源：Dify provider declaration `supports_*` 字段惯例）

**Dify 原始模式**：每个 provider declaration 含一组 capability flags（`supports_function_call` / `supports_streaming` / `supports_image_input` 等），从 plugin declaration YAML 读取。

**借鉴到 Plan 06**：LegacyAdapter 从底层 IMProvider 推导 cap flags：

```python
@property
def supports_native_buttons(self) -> bool:
    # Phase 4 6 家：webhook 无原生卡片，其他 5 家都支持
    return self._legacy.name != "webhook"

@property
def supports_card_update(self) -> bool:
    # 沿用 legacy provider 字段（Phase 4 FeishuProvider/SlackProvider/MattermostProvider 有，企微/钉钉无）
    return getattr(self._legacy, "supports_card_update", False)

@property
def supports_threads(self) -> bool:
    # Phase 4 6 家都无 thread 支持（CONTEXT.md decision，5.D 才接入 Huly 等真 thread 平台）
    return False
```

**关键设计点**：Dify 是从 manifest YAML 显式声明，本项目老 IMProvider 没 manifest —— 退一步用**硬编码 + getattr 默认值**推导。安全性：
- `name != "webhook"` 是基于 Phase 4 6 家实情硬编码（webhook 不支持原生卡片）
- `supports_card_update` 用 `getattr(..., default=False)` 防止 AttributeError
- `supports_threads` 直接 False（Phase 4 没设计 thread 概念）

---

## 与本项目的关系

### 直接应用到 Plan 06 的核心代码

| Dify 借鉴点 | Plan 06 落地位置 |
| --- | --- |
| #1 双轨并存而非强制 cutover | `backend/app/agent_builder/notification/providers/base.py` `_PROVIDERS_AS_CAP` dict 与 `_PROVIDERS` 双轨 |
| #2 迁移失败容忍 | `_maybe_wrap_for_capability` 的 try/except ImportError 静默降级 |
| #3 老接口字段最小化保留 | `LegacyIMProviderAdapter.send_card` 中 `title.split(" — ", 1)` 部分字段拆分 + 空字符串填充 |
| #4 迁移后旧接口仍可用 | `register_provider` 签名 + `_PROVIDERS` 行为 100% 不变 + 同一 raw provider 实例共享 |
| #5 cap flags 推导 | `supports_native_buttons/supports_card_update/supports_threads` properties from legacy fields |

### 给 Plan 07 (HulyPlugin acid test) 的对接

Plan 07 HulyPlugin manifest 启动后，PlatformPluginRegistry 中既有 manifest plugin (huly) 又有 6 家 legacy adapter (`_PROVIDERS_AS_CAP`)。`get_capability(IMCapability)` 路由：

```
without prefer:
  1. 遍历 _MANIFESTS 查 "im" capability → 找到 huly → 返回 huly.im facade
  2. 仅当 _MANIFESTS 全部 plugin 都不支持 im 时，才 fallback 到 _PROVIDERS_AS_CAP

with prefer="feishu":
  1. _MANIFESTS["feishu"] 不存在 → 不取 manifest plugin
  2. fallback 到 _PROVIDERS_AS_CAP["feishu"] → 返回 LegacyAdapter(FeishuProvider)

with prefer="huly":
  1. _MANIFESTS["huly"] 存在且声明 "im" → 返回 huly.im facade（不 fallback）
```

**关键 capability routing 不变量**：manifest plugin 优先 → legacy fallback。Plan 06 测试覆盖这两个路径 + 缺失场景。

### 风险防护对照表

| Pitfall | Dify 经验 | Plan 06 防护 |
| --- | --- | --- |
| 强制迁移破坏老调用 | Dify 用应用层路由层兼容（不强制 SQL update） | 不强制 wrap；老调用走 get_provider 0 改动 |
| wrap 失败 cascade | Dify try/except + logger.exception | try/except ImportError 静默降级，仅老路径保留 |
| 两套 schema 数据飘移 | Dify 一表两形式 → 应用层 detect 路由 | 双 dict 不共享 key，但同一 raw provider 实例共享（避免数据飘移） |
| 测试隔离破坏 | Dify 用 `clear_session()` fixture | `clear_providers()` 加 `_PROVIDERS_AS_CAP.clear()` 一并清空 |

---

## License Attribution

本 reading doc 引用 Dify 源文件路径仅作**模式参考**，无任何 Dify 源码片段直接拷贝。本项目（agent-builder）的 LegacyIMProviderAdapter 实现是**独立创作**：

- Dify `PluginDataMigration` 是数据库 schema 迁移工具（212 行）
- 本项目 `LegacyIMProviderAdapter` 是内存 adapter wrap（< 130 行）
- 共同的**设计哲学**：双轨并存 + 老接口零破坏 + 失败静默降级 + 部分字段最小化映射

License 兼容性：
- **Dify**: AGPL-3.0 (Affero GPL)
- **agent-builder**: Apache-2.0
- **借鉴范围**：仅设计模式 / 数据结构思路 / 边界考虑 / 命名规范
- **禁止**：任何源码片段直接拷贝（CLAUDE.md §2.7 强制规则）

---

## 总结

Dify 的 plugin migration 系统是一套**生产级、批量化、容忍失败**的数据迁移工具，针对几十万个租户的几百万行数据。本项目 Plan 06 是**轻量级、in-memory、自动触发**的 adapter wrap，针对 6 家 Phase 4 IMProvider —— **设计哲学高度一致，但工程复杂度差几个数量级**。

Plan 06 实现策略：
1. **register_provider 接口不动** —— Phase 4 调用零改动（借鉴 Dify 老接口保留原则）
2. **_PROVIDERS_AS_CAP 内部 dict** —— wrap 后存放（借鉴 Dify 双轨数据共存）
3. **try/except ImportError 静默降级** —— 测试隔离场景兼容（借鉴 Dify failed_ids + logger.exception）
4. **LegacyAdapter 字段最小化映射** —— NormalizedCard → 8 字段 send_hitl_card（借鉴 Dify 部分字段保留 + 空填充）
5. **cap flags 推导** —— supports_native_buttons/supports_card_update/supports_threads from legacy fields（借鉴 Dify provider declaration capability flags）

**Plan 07 acid test 直接受益**：HulyPlugin 启动后，Registry 中 manifest plugin 与 legacy adapter 共存；新代码无论调 `get_capability(IMCapability, prefer="huly")` 还是 `prefer="feishu"`，都能路由到正确实现（前者走 manifest facade，后者走 legacy fallback）。

---

*Reading docs for: agent-builder Phase 5.A Plan 06 LegacyIMProviderAdapter*
*Date: 2026-05-17*
*Reviewer: Claude Opus 4.7 (1M context)*
