# 协作文档 (DocProvider) 通用抽象设计

> **作者**：来自 offboarding-flow 实战提炼
> **日期**：2026-05-17
> **状态**：设计稿（与 [im-bot-abstraction-design](./2026-05-17-im-bot-abstraction-design.md) 配套，待 Phase 5/6 评审）
> **关联**：[`dify-integration-offboarding-meeting-2026-05-17.md`](../dify-integration-offboarding-meeting-2026-05-17.md) §4.4

---

## 0. 背景

### 0.1 为什么需要这个需求

`agent-builder` 当前 v1 工作流只能通过：

- 邮件发链接
- IM 卡片发链接（Phase 4 已完成）
- Web 决策页

但**很多真实业务**需要把流程过程沉淀为**协作文档**：

- 离职流程「最终交接清单」 → 写一篇 Markdown 文档共享给接手人
- 会议纪要分析 → AI 总结后写到 Outline / 飞书文档让团队后续可检索
- 审批通过后自动生成《XX 项目立项文档》到协作平台
- DAG 节点输出大段结构化内容（如 LLM 生成的代码审查报告）— 比 IM 卡片更合适

如果每次 deploy 都要从 0 接 Outline / 飞书文档 / 企微 Drive / 钉钉 Drive，每家 API 200-500 行模板代码，且认证 / 权限 / 评论 / @人 接口完全不同。

### 0.2 已有 reference impl

`hr/offboarding-flow` 项目已经实现并跑通了 DocProvider Protocol + 4 个平台 stub/真实接入：

| 文件 | 作用 |
|---|---|
| `providers/base.py` | DocProvider + IMProvider Protocol（共 119 行清晰定义） |
| `providers/outline_provider.py` | Outline 真接入（开源协作文档，最完整） |
| `providers/lark_provider.py` | 飞书文档真接入 |
| `providers/wecom_provider.py` | 企微微盘 stub |
| `providers/dingtalk_provider.py` | 钉钉文档 stub |
| `providers/factory.py` | 按 env `DOC_PROVIDER` 选择 |

**本设计的目标**：把它抽象成 agent-builder 内置能力，加上**多租户 + per-workspace 凭证 + agent-builder 节点类型集成 + AI @人 智能**。

---

## 1. 目标 / 非目标

### 1.1 目标（v1 in scope）

| ID | 目标 | 验证方式 |
|---|---|---|
| G1 | 一份 DocProvider Protocol 统一所有平台 API | hr 4 providers 可零改 port + agent-builder Outline 接入实跑 |
| G2 | per-workspace 凭据加密存储 + factory.get_doc_provider(workspace_id) 多租户隔离 | 双 workspace 同时用不同 Outline 实例不串扰 |
| G3 | DAG 新增 `doc_write` 节点：DSL 配置 title + markdown 模板，自动写到协作文档 | 一份 DSL 跑完自动出 Outline 文档 |
| G4 | DAG 新增 `doc_mention` 节点：识别 markdown 中需要 @ 的协作人，按 DocProvider API 加评论 @ 提醒 | 文档创建后协作人 IM 收 @ 提醒 |
| G5 | `add_comment_mention(doc_id, username, comment_text)` 统一接口跨平台一致 | Outline + Lark 都实现，企微钉钉 stub |
| G6 | 跨平台 user ID 映射：内部 canonical username → 4 家 user_id 一站查询 | 同时 mention 在 Outline + 飞书都生效 |
| G7 | AI 智能生成文档：DAG 节点输出 markdown 时自动调 LLM "识别需 @ 的协作人" 并标记 | 离职流程文档创建后自动 @ 接手人 |

### 1.2 非目标（v1 out of scope）

- ❌ **协作文档编辑器集成**：v1 仅写入，不做 in-app 编辑（用户去原平台编辑）
- ❌ **文档版本回滚**：依赖原平台版本功能（Outline / Lark 都有）
- ❌ **跨平台双写同步**：v1 一个 workspace 选一个 provider；多 provider 镜像同步 v2 再做
- ❌ **附件 / 图片上传**：v1 纯 markdown 文本；附件 v1.5
- ❌ **细粒度文档权限管理**：v1 用平台默认权限（workspace 内可见）

---

## 2. 现状：hr/offboarding-flow DocProvider 实现快照

### 2.1 它做对的部分（值得复用）

```python
@runtime_checkable
class DocProvider(Protocol):
    name: str
    async def create_document(self, *, title, markdown, owner_usernames=None) -> DocInfo
    async def update_document(self, *, doc_id, markdown, title=None) -> None
    async def list_documents(self, *, query=None, limit=10) -> list[DocInfo]
    async def get_document(self, doc_id) -> DocInfo | None
    async def ensure_users(self, users) -> dict[str, list[str]]
```

清晰、最小、Protocol 而非 ABC（鸭子类型 + runtime_checkable 双保险）。

### 2.2 它做得不够通用的部分（本设计要改进）

| 痛点 | 现状 | 期望 |
|---|---|---|
| 凭据从 global env 取 | `OUTLINE_API_KEY` 全平台一个 | per-workspace DB 字段 + 加密存 |
| factory 单例 | `get_doc_provider()` 全进程一个 | `get_doc_provider(workspace_id)` 多租户 |
| 缺 @人 评论接口 | 仅创建/更新文档，无评论 | 加 `add_comment_mention(doc_id, username, text)` |
| 缺 AI 智能化钩子 | 文档内容用户自己写 markdown | 加 `ai_suggest_mentions(markdown) -> list[str]` LLM 钩子 |
| 缺 doc 节点与 DAG 集成 | 业务代码手调 provider | 画布加 `doc_write` / `doc_mention` 节点类型 |
| 缺统一的 user 映射 | 用 username 字符串匹配 | 中央 `user_platform_mappings` 表（与 IM 抽象共用） |

---

## 3. 需求清单

### 3.1 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| R-DOC-01 | DocProvider Protocol 完整定义 + ProviderError 统一异常 | P0 |
| R-DOC-02 | per-workspace 凭据加密存（复用 Phase 4 IMCredentialsManager 模式） | P0 |
| R-DOC-03 | `DocCredentialsManager.get_doc_credentials(workspace_id, provider_name)` | P0 |
| R-DOC-04 | `DocProviderRegistry` + factory.get(workspace_id) | P0 |
| R-DOC-05 | OutlineProvider 完整实现（v1 P0 — 最成熟的开源） | P0 |
| R-DOC-06 | LarkDocsProvider 完整实现（v1 P0 — 国内首选） | P0 |
| R-DOC-07 | WeComDriveProvider stub + skeleton（v1 P1，留接口） | P1 |
| R-DOC-08 | DingTalkProvider stub + skeleton（v1 P1） | P1 |
| R-DOC-09 | DocProvider 加 `add_comment_mention(doc_id, username, text)` | P0 |
| R-DOC-10 | `ai_suggest_mentions(markdown, context) -> list[str]` LLM 钩子 | P1 |
| R-DOC-11 | 节点类型 `doc_write`：title + markdown Jinja → 调 create_document | P0 |
| R-DOC-12 | 节点类型 `doc_mention`：拿 doc_id + mentions → 调 add_comment_mention | P0 |
| R-DOC-13 | user_platform_mappings 表：canonical username → outline_email / lark_open_id / wecom_userid / dingtalk_userid | P0 |
| R-DOC-14 | sync 命令：从平台拉 user list 自动建/更 user_platform_mappings | P1 |
| R-DOC-15 | DocProvider 调用失败重试（tenacity，复用 Phase 3 模式） | P1 |

### 3.2 非功能需求

| ID | 需求 |
|---|---|
| N-DOC-01 | create_document 端到端 ≤ 3s（含 LLM 生成 + 平台写入） |
| N-DOC-02 | 凭据从 env 注入 + per-workspace DB 加密存，禁止进 YAML/code |
| N-DOC-03 | 失败：调 add_comment_mention 失败时不阻断主流程（仅写 audit_log） |
| N-DOC-04 | provider 调用日志含 workspace_id / provider / api / latency 用于 Phase 7 Observability |

---

## 4. Protocol Schema 设计

### 4.1 DocProvider Protocol（agent-builder 扩展版）

```python
# backend/app/agent_builder/notification/doc_providers/base.py
from typing import Protocol, runtime_checkable
from dataclasses import dataclass

class ProviderError(Exception):
    """DocProvider 调用失败统一异常。"""

@dataclass(frozen=True)
class DocInfo:
    id: str                # 平台内 doc id
    url: str               # 完整可访问 URL（用于邮件 / IM 卡片嵌入）
    title: str
    provider: str          # "outline" | "lark" | "wecom" | "dingtalk"
    created_at: str        # ISO8601

@dataclass(frozen=True)
class DocComment:
    """文档评论。"""
    id: str
    body: str
    author_id: str
    mentions: list[str]    # @ 到的 user_id 列表
    created_at: str

@dataclass(frozen=True)
class DocCredentials:
    """加密存储的凭据（与 IMCredentials 同模式）。"""
    workspace_id: str
    provider_name: str
    api_key: str | None
    base_url: str | None
    bot_token: str | None
    additional: dict[str, str]   # provider-specific extras

@runtime_checkable
class DocProvider(Protocol):
    """协作文档平台抽象 — 实现：OutlineProvider / LarkDocsProvider / WeComDrive / DingTalkDoc"""

    name: str                # "outline" | "lark" | "wecom" | "dingtalk"
    supports_comments: bool  # 能力声明（v1 Outline/Lark=True，WeCom/DingTalk=False）

    async def create_document(
        self,
        *,
        title: str,
        markdown: str,
        owner_usernames: list[str] | None = None,
        folder_id: str | None = None,
    ) -> DocInfo: ...

    async def update_document(
        self,
        *,
        doc_id: str,
        markdown: str,
        title: str | None = None,
    ) -> None: ...

    async def get_document(self, doc_id: str) -> DocInfo | None: ...

    async def list_documents(
        self,
        *,
        query: str | None = None,
        limit: int = 10,
    ) -> list[DocInfo]: ...

    async def add_comment_mention(
        self,
        *,
        doc_id: str,
        username: str,           # canonical username（系统内）
        comment_text: str,       # 评论正文（含 @username markdown 语法）
    ) -> DocComment:
        """在文档评论区 @ 协作人 — supports_comments=False 时抛 NotImplementedError"""
        ...

    async def ensure_users(self, users: list[dict[str, str]]) -> dict[str, list[str]]:
        """同步外部 user 到平台（已存在的 skip）。返回 created/skipped 列表。"""
        ...
```

### 4.2 DocCredentialsManager（per-workspace 凭据）

```python
class DocCredentialsManager:
    """从 workspace settings + env 读取凭据 — 加密存储模式与 IMCredentialsManager 一致。"""

    @staticmethod
    def get_outline_credentials(workspace_id: UUID) -> OutlineCredentials | None: ...

    @staticmethod
    def get_lark_credentials(workspace_id: UUID) -> LarkDocsCredentials | None: ...

    @staticmethod
    def get_wecom_credentials(workspace_id: UUID) -> WeComDriveCredentials | None: ...

    @staticmethod
    def get_dingtalk_credentials(workspace_id: UUID) -> DingTalkDocCredentials | None: ...
```

### 4.3 DocProviderRegistry

```python
class DocProviderRegistry:
    """provider_name → DocProvider class 工厂注册"""

    @classmethod
    def register(cls, name: str, provider_cls: type[DocProvider]) -> None: ...

    @classmethod
    def get(cls, workspace_id: UUID, name: str) -> DocProvider | None:
        """构造一个 provider 实例（懒加载凭据）。"""
        ...

    @classmethod
    def get_workspace_default(cls, workspace_id: UUID) -> DocProvider | None:
        """按 workspace_settings.default_doc_provider 选择。"""
        ...
```

---

## 5. user_platform_mappings 表设计

跨平台 user ID 映射 — IM bot 抽象设计稿 §4.5 已经提到，本设计与之共用。

```sql
CREATE TABLE app.user_platform_mappings (
    id BIGSERIAL PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES app.workspaces(id) ON DELETE CASCADE,
    canonical_username TEXT NOT NULL,        -- agent-builder 内部 username
    user_id UUID REFERENCES app.users(id),   -- 关联到 agent-builder users 表（如有账号）

    -- Doc 平台
    outline_email TEXT,
    lark_open_id TEXT,
    wecom_userid TEXT,
    dingtalk_userid TEXT,

    -- IM 平台（同表共享 — 避免双表 join）
    mattermost_id TEXT,
    slack_user_id TEXT,

    -- 元信息
    email TEXT,                              -- 主邮箱（同步用 key）
    display_name TEXT,
    department TEXT,
    role TEXT,                               -- canonical role
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sync_source TEXT,                        -- "outline-sync" | "lark-sync" | "manual"

    UNIQUE (workspace_id, canonical_username)
);

CREATE INDEX ix_user_mappings_ws_email ON app.user_platform_mappings (workspace_id, email);
CREATE INDEX ix_user_mappings_ws_lark ON app.user_platform_mappings (workspace_id, lark_open_id);
-- ... 其他 platform_id 索引
```

**sync 命令**（R-DOC-14 / IM-R-similar）：

```bash
agent-builder mappings sync --workspace <ws-id> --source outline
agent-builder mappings sync --workspace <ws-id> --source lark
```

定时跑（cron 5min）保证 mapping 不滞后。

---

## 6. DAG 节点设计

### 6.1 `doc_write` 节点

```yaml
nodes:
  - id: handover_doc
    type: doc_write
    config:
      provider: ${workspace.default_doc_provider}    # 或显式 "outline"
      title: "${vars.employee_name} 离职交接清单"
      markdown_template: |
        # ${vars.employee_name} 离职交接

        ## 基本信息
        - **员工**：${vars.employee_name}
        - **离职日**：${vars.last_day}
        - **接手人**：${vars.successor}

        ## 在交项目
        ${vars.projects | bullet_list}

        ## 待办事项
        ${vars.todos | checkbox_list}

      owner_usernames:
        - ${vars.manager_username}
        - ${vars.hr_username}
    outputs:
      doc_id: string
      doc_url: string
```

### 6.2 `doc_mention` 节点

```yaml
nodes:
  - id: mention_successor
    type: doc_mention
    depends_on: [handover_doc]
    config:
      doc_id: ${handover_doc.doc_id}
      mentions:                           # 显式列表
        - username: ${vars.successor}
          comment: "请重点关注「待办事项」部分，有疑问联系 @${vars.applicant_username}"
        - username: ${vars.manager_username}
          comment: "审核确认"

  - id: ai_mention_collaborators
    type: doc_mention
    depends_on: [handover_doc]
    config:
      doc_id: ${handover_doc.doc_id}
      ai_suggest:                         # AI 智能识别
        enabled: true
        prompt: "分析文档内容，识别其中提到的协作人并标记其 username"
```

### 6.3 与 IM Notify 节点的协同

```yaml
nodes:
  - id: handover_doc
    type: doc_write
    ...

  - id: notify_successor
    type: im_notify                       # Phase 5.D 的节点（im-bot-abstraction §9.2）
    depends_on: [handover_doc, ai_mention_collaborators]
    config:
      bot_ref: offboarding-bot
      channel: dm
      to: ${vars.successor}
      template: |
        🔔 你被加为「${vars.employee_name} 离职」交接人
        交接清单已创建：${handover_doc.doc_url}
        重要待办我已在文档评论区 @ 了你
```

---

## 7. AI 智能 @人 集成

借鉴 dify-integration 文档 §4.4 设计：DAG 跑完 handover_doc 后，AI 分析文档内容自动识别需 @ 的协作人。

### 7.1 ai_suggest_mentions 流程

```python
async def ai_suggest_mentions(
    markdown: str,
    workspace_id: UUID,
    *,
    llm: LLMProvider,
    user_mappings: list[UserMapping],
) -> list[MentionSuggestion]:
    """让 LLM 分析 markdown，返回应 @ 的 canonical_username 列表 + 理由。"""

    prompt = render_template("ai_suggest_mentions_zh.md", {
        "markdown": markdown,
        "available_users": [{"username": m.canonical_username, "role": m.role, "dept": m.department}
                            for m in user_mappings],
    })
    raw = await llm.complete(prompt, timeout=10, response_format="json")
    return MentionSuggestion.model_validate_json(raw)
```

prompt 模板（`prompts/ai_suggest_mentions_zh.md`）：

```
你是 agent-builder 的协作人识别器。分析以下文档，找出**必须由特定人协作**的部分，返回 JSON。

可用 user 池（仅从此选）：
{{#each available_users}}
- @{{username}} ({{role}}, {{dept}})
{{/each}}

返回 JSON（严格格式）：
{
  "mentions": [
    {"username": "<from pool>", "reason": "<具体原因>", "context_snippet": "<原文片段>"}
  ]
}

文档：
{{markdown}}
```

### 7.2 与 Dify Workflow 集成（可选 — dify-integration 文档方案 B）

如果用户选择走 Dify Workflow 而不是直调 LLM：

```python
async def ai_suggest_mentions_via_dify(markdown, ctx):
    result = await dify.run_workflow("smart_mention", inputs={
        "event_type": "doc_created",
        "doc_content": markdown,
        "involved_users": ctx.user_mappings_to_dict(),
    })
    return MentionSuggestion(**result)
```

`USE_DIFY=true` 时切换走 Dify，false 时直调 LLM — 与 IM bot 抽象 §7 LLM intent router 一致的双路设计。

---

## 8. Provider 实现优先级

### Phase 5.A — Outline + Lark Docs（v1 P0）

**Outline**（首选 — 开源 + API 完整 + 自托管友好）：
- 已 docker-compose 部署在 .44 服务器（同 mattermost-postgres）
- Token-based auth（personal access token）
- API: REST /api/documents.create / .update / .info / .list
- 评论 API: /api/comments.create + mention 通过 `@uuid` 语法

**飞书文档**（国内首选）：
- `lark-oapi==1.6.5` SDK
- Block-based content（不是纯 markdown — 需要 markdown→blocks 转换工具）
- Comment API: `docx.v1.document.create_comment`
- @人需要 lark_open_id（user_platform_mappings 提供）

### Phase 5.B — WeCom Drive + DingTalk Doc（v1 P1）

**企微微盘**：
- `wechatpy==1.8.18`（停更，API 限制类似 Phase 4 04-07 WeCom card 经验）
- spike 30min 验证 markdown 文档写入 API 是否仍可用
- 如失败 fallback 调通用 API endpoint

**钉钉文档**：
- `dingtalk-stream==0.24.3` 加 dingtalk-doc-api 调用
- 评论 + @人需要 unionId

---

## 9. Phase 拆分（建议）

### Phase 5.A — DocProvider 基础抽象（2 周）

| 任务 | 输出 |
|---|---|
| 1. `DocProvider` Protocol + DocInfo + DocComment + ProviderError | `notification/doc_providers/base.py` |
| 2. `DocCredentialsManager` 5 家凭据 dataclass + per-workspace load | `core/doc_credentials.py` |
| 3. `DocProviderRegistry` factory | `notification/doc_providers/registry.py` |
| 4. `MockDocProvider` 用于测试 + E2E | `notification/doc_providers/mock.py` |
| 5. `user_platform_mappings` 表 + Alembic + ORM model | `models/user_platform_mapping.py` |
| 6. `add_comment_mention` 接口设计 + 单测 | base + mock |
| 7. 单元 + 集成测试 ≥ 20 | pytest |

### Phase 5.B — Outline + Lark Docs 真接入（2 周）

| 任务 | 输出 |
|---|---|
| 1. `OutlineProvider` 实现完整 6 method | `notification/doc_providers/outline.py` |
| 2. `LarkDocsProvider` 实现 + markdown→blocks 转换 | `notification/doc_providers/lark_docs.py` |
| 3. mapping sync 命令: `agent-builder mappings sync --source outline / lark` | `cli/mappings.py` |
| 4. ai_suggest_mentions LLM 钩子 + prompt template | `notification/doc_ai/` |
| 5. 集成测试 + provider monkeypatch HTTP | pytest |
| 6. E2E：用 hr 离职流程跑通自动生成 Outline 文档 + AI @人 | browser-use/browser-harness |

### Phase 5.C — DAG 节点集成（1.5 周）

| 任务 | 输出 |
|---|---|
| 1. DSL schema 加 `doc_write` / `doc_mention` 节点类型 | `workflow/node_schemas/doc_*.py` |
| 2. DocWriteNodeExecutor + DocMentionNodeExecutor | `workflow/nodes/doc_*.py` |
| 3. 画布 UI：节点拖拽 + 配置面板 + Jinja markdown 预览 | frontend |
| 4. E2E：拖一个 4 节点 DAG（HITL → doc_write → ai_mention → im_notify）→ 跑通 | browser-use/browser-harness |

### Phase 5.D — WeCom + DingTalk Doc（v1 P1，1.5 周）

| 任务 | 输出 |
|---|---|
| 1. WeCom Drive spike + provider 实现（或 stub） | `notification/doc_providers/wecom_drive.py` |
| 2. DingTalk Doc 实现 | `notification/doc_providers/dingtalk_doc.py` |
| 3. 集成测试（如果 SDK 可用）/ stub 测试 | pytest |

---

## 10. 验收标准（DoD）

### Phase 5.A 验收

- [ ] DocProvider Protocol + 5 个核心 method 单元测试 100% 覆盖
- [ ] `DocCredentialsManager` 加密存 / 解密读 / per-workspace 隔离测试通过
- [ ] `user_platform_mappings` 表 sync 命令跑通（mock data）
- [ ] MockDocProvider 可注入到 DAG runner 测试

### Phase 5.B 验收

- [ ] Outline 真接入：create + update + comment + mention 端到端 ≤ 3s
- [ ] Lark Docs 真接入：markdown → blocks 转换 + comment + mention 通过
- [ ] ai_suggest_mentions 跑 5 真实文档 → 准确率 ≥ 80%（人工 review）
- [ ] mapping sync 命令从 Outline / Lark 拉到 user 列表入库

### Phase 5.C 验收

- [ ] 画布拖 `doc_write` 节点 → 配置 title + markdown → 发布 → 跑工作流 → Outline 出文档
- [ ] `doc_mention` ai_suggest 模式：节点跑完后协作人 IM 收 @ 提醒
- [ ] E2E 用 browser-use/browser-harness 覆盖完整流程

---

## 11. 风险 + 兜底

| 风险 | 概率 | 影响 | 兜底 |
|---|---|---|---|
| Lark Docs markdown → blocks 转换易脆 | 高 | 文档格式错乱 | 用 `marko` 库做 AST 解析 + 严格映射；失败 fallback "plain text block" |
| ai_suggest_mentions LLM 调用慢 / 失败 | 中 | doc_mention 节点超时 | 默认 timeout 10s + 失败 fallback "不 @ 任何人，仅写 audit" |
| user_platform_mappings 不完整 | 高 | mention 找不到目标 | 节点配置 `on_unknown: skip / fail / fallback_to_email`；默认 skip + audit warn |
| Outline 自托管挂掉 | 中 | doc_write 全部失败 | 健康检查节点；provider call 加 circuit breaker |
| 跨 workspace 凭据泄漏 | 低 | 安全 | DocCredentialsManager 强制 workspace_id 入参 + 加密存 + 不入 log |

---

## 12. 与 IM bot 抽象设计的对照

| 维度 | DocProvider | IMProvider (Phase 4 已建) | IM Bot Dispatcher (本系列另一文档) |
|---|---|---|---|
| Protocol | DocProvider | IMProvider | BotConfig + HandlerRegistry |
| 凭据 | DocCredentialsManager | IMCredentialsManager | 复用 IMCredentialsManager |
| Registry | DocProviderRegistry | IMRegistry | — |
| user 映射 | user_platform_mappings 表 | 复用同表 | identity.source |
| 节点类型 | doc_write / doc_mention | im_card_notify (Phase 4 04-11) | im_trigger / im_notify |
| AI 智能 | ai_suggest_mentions | — | LLMIntentRouter |

**复用**：
- `user_platform_mappings` 表跨 IM + Doc 共用
- 凭据加密存模式一致（Phase 4 IMCredentialsManager 已建）
- factory + Registry 设计模式一致

---

## 13. 参考资料

| 来源 | 路径 |
|---|---|
| hr/offboarding-flow DocProvider reference impl | `/Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/providers/` |
| Outline API 文档 | https://www.getoutline.com/developers |
| 飞书文档 API | https://open.feishu.cn/document/server-docs/docs/docs-overview |
| Phase 4 IMProvider 已建抽象 | `backend/app/agent_builder/notification/providers/base.py` |
| IM bot 抽象设计稿 | `./2026-05-17-im-bot-abstraction-design.md` |
| Dify 集成方案（含 DocProvider 增强建议 §4.4） | `../dify-integration-offboarding-meeting-2026-05-17.md` |

---

## 14. 开放问题（待评审）

1. **markdown→blocks 转换**：自己写 vs 用 `pandoc`/`marko` 库？
   - 推荐：`marko`（Python pure，AST 完整，依赖少）
2. **add_comment_mention 失败语义**：仅 audit_log 还是节点 failed？
   - 推荐：v1 仅 audit_log + 节点 status="completed_with_warnings"（不 fail，因 doc 已创建）
3. **AI suggest 用 agent-builder 自带 LLM 还是必须 Dify Workflow？**
   - 推荐：v1 用 agent-builder 自带 LLM（GLM / OpenAI），Dify Workflow 走 v2
4. **mapping sync 凭据**：Outline admin token 才能拉 user list — 是否新增 admin-only credential 字段？
   - 推荐：加 `outline_admin_token` 字段 + 提示用户只读 token 也可工作但 sync 失败
5. **WeCom / DingTalk Drive 是否必要？**
   - 推荐：v1 P1 仅 stub + 接口；真实接入按用户需求拉单 P2 实现

---

*文档完*
