# agent-builder 设计文档

> 版本: v0.1（草案）
> 日期: 2026-05-16
> 作者: liuxin
> 状态: 待评审
> 关联讨论: brainstorming 会话（共 6 轮决策 + 4 个 P1 收尾）

---

## 1. 项目背景与定位

### 1.1 一句话定位

**通用拖拽式 LangGraph 编排平台**（"LangGraph as Service"）：用户在 Web 画布上拖拽节点 → 实时存为 DSL → 一键部署可运行实例 → 节点支持邮件 / 多 IM 通道的人工审批（四态决策） → 公网可访问、Token 即登录。

### 1.2 设计目标

- **画布即引擎**：拖拽 / 连线即时生效，不需要代码生成或重启
- **审批即邮件**：HITL 节点默认走"邮件 + 公网深链"，无需安装 App
- **多 IM 平行**：企微 / 飞书 / 钉钉 / Slack / Mattermost 全主流 IM 都能作为通知通道与决策入口
- **平台化扩展**：插件市场支持第三方节点

### 1.3 非目标（YAGNI）

- ❌ 不重新发明工作流引擎（用 LangGraph）
- ❌ 不重新发明拖拽 UI（fork [Onelevenvy/flock](https://github.com/Onelevenvy/flock)）
- ❌ v1 不做工作流模板市场（仅本地预置）
- ❌ v1 不做多模型 Provider 池（接一个 LLM 即可）
- ❌ v1 不做节点级 CPU/内存 quota（沙箱有，但配额留到 v2）

---

## 2. 范围与决策板

### 2.1 决策板（v0.1 锁定）

| # | 维度 | 决策 |
| -- | ---- | ---- |
| 1 | 执行引擎 | LangGraph + `PostgresSaver`（`thread_id` = `flow_instance_id`） |
| 2 | 画布转换 | **DSL/JSON 解释执行**：dsl → 动态组装 StateGraph → compile → ainvoke。热更新友好 |
| 3 | 节点类型 | Start / End / LLM / Tool / **HITL** / If-Else / Parallel-FanOut / Parallel-FanIn / Loop / Subgraph / API / Code / Notification |
| 4 | HITL 决策 | **四态**：执行人 `submit / return / reject` → in_review → 审核人 `approve / return / reject` |
| 5 | 审批链 | **全 4 种**：单人 / 顺序会签 / 并行会签（全员同意）/ 或签（任一同意） |
| 6 | 通知通道 | Email + 企微 + 飞书 + 钉钉 + Slack + Mattermost + Webhook |
| 7 | IM 集成深度 | **L3 全能双向**：交互卡片 + 账号双向同步 + 部门树 / 汇报关系拉取 |
| 8 | HITL 中断模式 | **单 interrupt + 自管审批链状态**（state 写在 `node_state.payload`） |
| 9 | 认证 | **自建账号体系**：邮箱 + 密码 + 部门 + 角色；预留 OAuth |
| 10 | 节点扩展 | **成熟插件市场**：内置 + 一等公民 + 第三方插件三层 |
| 11 | 公网入口 | `PUBLIC_BASE_URL` + nginx/Caddy 反代，仅暴露 `/hitl/callback/*` `/api/im/webhook/*` |
| 12 | 深链 Token | PyJWT HS256，每个 action 独立 token；jti 一次性消费；走 path 不走 query |
| 13 | Token 即登录 | 用户点击邮件链接 → 解 token 拿 actor + role → 换 session cookie → 渲染对应角色处理页 |
| 14 | 多租户 | workspace 级隔离，单实例多 workflow |
| 15 | Skeleton | **Fork [Onelevenvy/flock](https://github.com/Onelevenvy/flock)** + 借鉴 [agent-inbox](https://github.com/langchain-ai/agent-inbox) HITL schema + [activepieces](https://github.com/activepieces/activepieces) 邮件 UX + Dify Canvas UI 风格 |

---

## 3. 系统架构

### 3.1 高层架构

```
┌──────────────────────────────────────────────────────────────────┐
│                          前端（Next.js）                          │
│  ┌──────────────┐ ┌──────────────┐ ┌─────────────────────────┐  │
│  │ 画布编辑器   │ │ 实例监控     │ │ HITL 决策页（Token 登录） │  │
│  │ (React Flow) │ │ (Timeline)   │ │ (路径 /flow/:id/node/:s) │  │
│  └──────────────┘ └──────────────┘ └─────────────────────────┘  │
└──────────────────────────────┬───────────────────────────────────┘
                               │ REST + WebSocket
┌──────────────────────────────▼───────────────────────────────────┐
│                        后端 API 层 (FastAPI)                      │
│  ┌─────────┐ ┌──────────┐ ┌────────────┐ ┌──────────────────┐  │
│  │ workflow│ │ instance │ │ hitl       │ │ admin (account+  │  │
│  │ /v1     │ │ /v1      │ │ /callback  │ │ workspace+plugin)│  │
│  └─────────┘ └──────────┘ └────────────┘ └──────────────────┘  │
└──────────────────────────────┬───────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────┐
│              核心引擎 (DSL → LangGraph StateGraph)                │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  DSL 编译器: dsl_compile(dsl) -> StateGraph              │   │
│  │  节点注册中心: NodeRegistry (内置 + 一等公民 + 插件)    │   │
│  │  执行调度器: dispatch(instance) -> ainvoke / aresume    │   │
│  │  Checkpointer: PostgresSaver (持久化中断/恢复)          │   │
│  └──────────────────────────────────────────────────────────┘   │
└───────┬─────────────────┬─────────────────┬─────────────────────┘
        │                 │                 │
┌───────▼────────┐ ┌──────▼─────────┐ ┌────▼──────────────────────┐
│ Notification    │ │ IM Directory   │ │ Plugin Sandbox            │
│ Adapters        │ │ Connectors     │ │ ┌──────────────────────┐  │
│ ├ email         │ │ ├ feishu       │ │ │ Subprocess Pool      │  │
│ ├ feishu        │ │ ├ wecom        │ │ │ + resource limits   │  │
│ ├ wecom         │ │ ├ dingtalk     │ │ │ + network policy    │  │
│ ├ dingtalk      │ │ └ mattermost   │ │ │ + stdio IPC         │  │
│ ├ slack         │ │ (用户/部门/    │ │ └──────────────────────┘  │
│ ├ mattermost    │ │  汇报关系同步) │ │                            │
│ └ webhook       │ │                │ │                            │
└─────────────────┘ └────────────────┘ └────────────────────────────┘
        │
┌───────▼──────────────────────────────────────────────────────────┐
│                持久化 (PostgreSQL + Redis)                         │
│  Postgres: workflows / instances / node_states / action_logs /    │
│            users / workspaces / plugins / im_directory            │
│  Redis: jti 黑名单 / rate limit / session cache                  │
└───────────────────────────────────────────────────────────────────┘
```

### 3.2 模块树

```
agent-builder/
├── api/                              # FastAPI 后端 (fork from flock)
│   ├── core/
│   │   ├── dsl/                      # DSL ↔ StateGraph 编译器
│   │   │   ├── schema.py
│   │   │   ├── compiler.py
│   │   │   └── validator.py
│   │   ├── executor/                 # 调度 + checkpoint + resume
│   │   ├── hitl/                     # 四态决策 + 审批链 + token
│   │   │   ├── chain.py              # 4 种审批链算法
│   │   │   ├── token.py              # JWT 签发 / 校验 / jti 消费
│   │   │   └── session.py            # token → cookie 换登录态
│   │   ├── auth/                     # 自建账号体系 + RBAC
│   │   └── registry/                 # NodeRegistry
│   ├── nodes/                        # 节点实现
│   │   ├── builtin/                  # Start/End/IfElse/Parallel/Loop/Code
│   │   ├── core/                     # LLM/Tool/HITL/Notification/API
│   │   └── plugin_loader.py
│   ├── adapters/
│   │   ├── notification/             # 邮件 + IM 通知（单向推）
│   │   │   ├── email/
│   │   │   ├── feishu/
│   │   │   ├── wecom/
│   │   │   ├── dingtalk/
│   │   │   ├── slack/
│   │   │   ├── mattermost/
│   │   │   └── webhook/
│   │   ├── im_directory/             # IM ↔ 账号双向同步 (L3)
│   │   │   ├── feishu_directory.py
│   │   │   ├── wecom_directory.py
│   │   │   └── dingtalk_directory.py
│   │   └── llm/
│   ├── api/v1/
│   │   ├── workflows.py              # CRUD + 部署 + 版本
│   │   ├── instances.py              # 运行 + 状态 + 中止
│   │   ├── hitl_callback.py          # 公网入口
│   │   ├── im_webhook.py             # IM 卡片回调
│   │   └── admin/
│   ├── plugin_runtime/               # 子进程沙箱
│   └── models/                       # SQLAlchemy ORM
├── web/                              # Next.js 前端 (fork from flock)
│   ├── app/canvas/                   # 拖拽画布
│   ├── app/flow/[id]/node/[sid]/     # HITL 决策页 (token 登录)
│   ├── app/admin/                    # 工作区 + 账号 + 插件管理
│   └── components/
├── deploy/
│   ├── docker-compose.yml
│   ├── nginx/                        # 公网反代配置
│   └── .env.example
├── templates/                        # 预置 workflow DSL
└── docs/plans/                       # 本文档及后续设计文档
```

---

## 4. 数据模型

### 4.1 DSL Schema (JSON)

```jsonc
{
  "version": "1.0",
  "id": "wf-uuid",
  "workspace_id": "ws-uuid",
  "name": "标准离职流程",
  "state_schema": {
    "employee_id": {"type": "string"},
    "decisions": {"type": "object"}
  },
  "nodes": [
    {
      "id": "start",
      "type": "start",
      "config": {}
    },
    {
      "id": "manager_review",
      "type": "hitl",
      "config": {
        "title": "直属上级审批",
        "form_schema": { /* JSON Schema 描述决策页表单 */ },
        "approval_chain": {
          "mode": "sequential",         // single | sequential | parallel_all | parallel_any
          "approvers": [
            {"resolve": "static", "user_id": "u_001"},
            {"resolve": "dynamic", "expr": "$.employee.manager_email"}
          ],
          "timeout_seconds": 86400,
          "on_timeout": "escalate_to_hr"
        },
        "channels": ["email", "feishu"],
        "deeplink_actions": ["approve", "return", "reject"]
      }
    },
    {
      "id": "hr_initial",
      "type": "hitl",
      "config": { /* ... */ }
    }
  ],
  "edges": [
    {"from": "start", "to": "manager_review"},
    {"from": "manager_review", "to": "hr_initial", "when": "$.last_action == 'approve'"},
    {"from": "manager_review", "to": "END",        "when": "$.last_action == 'reject'"}
  ]
}
```

### 4.2 持久化表（核心）

```sql
-- 工作区（多租户根）
workspaces (
  id UUID PK, name VARCHAR(64), created_at TIMESTAMP
)

-- 用户（自建账号体系）
users (
  id UUID PK,
  workspace_id UUID,
  email VARCHAR(128) UNIQUE,
  password_hash VARCHAR(255),
  display_name VARCHAR(64),
  department VARCHAR(128),
  role VARCHAR(32),                    -- admin / editor / viewer / external
  im_bindings JSONB,                   -- {feishu: open_id, wecom: userid, ...}
  created_at TIMESTAMP
)

-- 工作流定义（一份 DSL = 一个版本）
workflows (
  id UUID PK,
  workspace_id UUID,
  name VARCHAR(128),
  dsl JSONB,                           -- 当前发布版
  draft JSONB,                         -- 草稿
  version INT,                         -- 单调递增
  status ENUM(draft, published, archived),
  created_by UUID,
  updated_at TIMESTAMP
)

-- 运行实例
flow_instances (
  id UUID PK,
  workflow_id UUID,
  dsl_version INT,                     -- 实例锁定的 DSL 版本
  thread_id VARCHAR(64),               -- LangGraph checkpoint
  status ENUM(running, paused, terminated, completed),
  context JSONB,                       -- 流程上下文
  created_at TIMESTAMP,
  updated_at TIMESTAMP
)

-- 节点状态
node_states (
  id UUID PK,
  instance_id UUID,
  node_id VARCHAR(64),                 -- DSL 中的节点 ID
  status ENUM(pending, running, waiting_human, in_review, done, rejected, returned),
  payload JSONB,                       -- 含 approval_chain_state:
                                       --   {current_step:1, records:[{actor,action,ts}], pending:[...]}
  entered_at TIMESTAMP,
  completed_at TIMESTAMP
)

-- 决策日志
action_logs (
  id UUID PK,
  instance_id UUID,
  node_state_id UUID,
  actor_id UUID,
  action ENUM(submit, approve, advance, return, reject),
  reason TEXT,
  payload JSONB,
  ip VARCHAR(64),
  user_agent VARCHAR(256),
  created_at TIMESTAMP
)

-- 通知记录
notifications (
  id UUID PK,
  instance_id UUID,
  node_state_id UUID,
  channel VARCHAR(32),                 -- email/feishu/wecom/...
  recipient VARCHAR(256),
  token_jti VARCHAR(64),
  link TEXT,
  status ENUM(sent, failed, viewed, consumed),
  sent_at TIMESTAMP
)

-- Token 一次性消费（Postgres 版；高频场景可换 Redis）
hitl_tokens (
  jti UUID PK,
  instance_id UUID,
  node_state_id UUID,
  actor_id UUID,
  action VARCHAR(16),
  expires_at TIMESTAMP,
  used_at TIMESTAMP NULL
)

-- IM 目录同步快照
im_directory (
  id UUID PK,
  workspace_id UUID,
  im_type VARCHAR(16),                 -- feishu/wecom/dingtalk
  external_id VARCHAR(128),
  name VARCHAR(64),
  email VARCHAR(128),
  department VARCHAR(128),
  manager_external_id VARCHAR(128),
  raw JSONB,
  synced_at TIMESTAMP
)

-- 插件
plugins (
  id UUID PK,
  workspace_id UUID,
  name VARCHAR(64),
  version VARCHAR(16),
  manifest JSONB,
  schema JSONB,
  package_path VARCHAR(256),
  status ENUM(uploaded, sandboxed, registered, disabled),
  installed_at TIMESTAMP
)
```

---

## 5. HITL 四态决策 + 审批链

### 5.1 状态转换

```
[pending] --enter--> [waiting_human (submit_phase)]
        执行人提交表单
[waiting_human] --submit--> [in_review]
              --return--> 回到上游节点
              --reject--> [rejected] -> END

[in_review] --approve--> 1. 审批链未结束 → 留在 in_review，通知下一位
                       2. 审批链终态满足 → [done] → 推进
[in_review] --return--> 回到上游
[in_review] --reject--> [rejected] -> END
```

### 5.2 四种审批链算法（单 interrupt 自管状态）

伪代码：

```python
# node_state.payload["approval_chain_state"]
state = {
  "mode": "sequential",               # single | sequential | parallel_all | parallel_any
  "approvers": [...resolved user_ids],
  "current_idx": 0,                   # sequential 用
  "records": [],                      # 历史决策
  "pending_approvers": [...]          # parallel 用
}

def on_approver_action(state, actor, action):
    state.records.append({actor, action, ts: now()})
    if action == "reject":
        return TERMINATE                 # 任一拒绝 → 流程拒绝
    if action == "return":
        return RETURN_TO_UPSTREAM         # 任一退回 → 退回
    # action == "approve"
    if state.mode == "single":
        return DONE
    elif state.mode == "sequential":
        state.current_idx += 1
        if state.current_idx >= len(state.approvers):
            return DONE
        send_notify(state.approvers[state.current_idx])
        return CONTINUE
    elif state.mode == "parallel_all":
        state.pending_approvers.remove(actor)
        if not state.pending_approvers:
            return DONE
        return CONTINUE
    elif state.mode == "parallel_any":
        return DONE                        # 任一同意立刻通过
```

只有返回 `DONE / TERMINATE / RETURN_TO_UPSTREAM` 时才调用 `graph.invoke(Command(resume=...))` 让 LangGraph 推进。`CONTINUE` 仅更新 node_state 并发新通知，**不动 LangGraph state**。

### 5.3 邮件按钮（四态）

执行人邮件：
```
[✓ 提交]  [↩ 退回]  [✗ 拒绝]
```

审核人邮件：
```
[✅ 通过]  [↩ 退回]  [✗ 拒绝]
```

每个按钮 = 一个独立 JWT（4 个 action 4 个 token），路径形如：

```
{PUBLIC_BASE_URL}/flow/{flow_id}/node/{node_state_id}/?token=<jwt>
```

---

## 6. 认证与 Token 设计

### 6.1 自建账号体系

- 注册：邮箱 + 密码（bcrypt 12 轮）+ 显示名 + 部门 + 角色
- 登录：邮箱密码 + JWT session（24h，httpOnly cookie）
- RBAC：`admin / editor / viewer / external`
  - `admin`：工作区全权 + 用户管理 + 插件审核
  - `editor`：workflow CRUD + 部署
  - `viewer`：只读
  - `external`：仅能通过邮件 token 访问决策页（不能登录 Web）
- IM 绑定：用户在 profile 中绑定 IM `open_id`，使决策邮件可以同时推 IM

### 6.2 HITL Token (公网入口)

**Token Payload**：

```json
{
  "iss": "agent-builder",
  "aud": "hitl",
  "iat": ..., "exp": ...,
  "jti": "uuid",
  "flow_id": "...",
  "node_state_id": "...",
  "actor_id": "u_xxx",
  "role": "executor | reviewer",
  "allowed_actions": ["approve", "return", "reject"]
}
```

**生命周期**：

1. HITL 节点 enter → 渲染 4 个 token + 4 个 deeplink → 发邮件 / IM
2. 用户点击 → `GET /hitl/page/<token>`
   - 校验签名 + exp + jti 未消费
   - **不立刻消费 jti**，签发 30min session cookie（`X-Hitl-Token: jti`）
   - 渲染对应角色页面（前端拿 token payload 渲染表单）
3. 用户提交决策 → `POST /hitl/action/<token>` (cookie + body)
   - 校验 session cookie 与 token jti 一致
   - **此时消费 jti**（事务里 advisory lock on flow_id）
   - 写 action_logs，触发审批链算法
   - 满足终态时调用 LangGraph resume
4. 同一 token 提交一次后即失效，其他 token（即同节点其他 action）也一并失效

**安全要点**：

- ✅ Token 走 URL path 而非 query（防 referrer / 日志泄露）
- ✅ Token = 唯一的身份证明（无需另登录）；转发是合法用例（HR 可代点），审计记录 IP/UA
- ✅ Rate limit：每 token 每分钟 ≤ 5 次 GET、每 IP 每分钟 ≤ 30 次回调
- ✅ HMAC 密钥从 env 读取，启动时校验长度 ≥ 32 字节
- ✅ 公网入口 nginx 仅放行 `/hitl/callback/*` `/hitl/page/*` `/api/im/webhook/*`，Web 管理端走内网/VPN

---

## 7. 通知通道与 IM L3 集成

### 7.1 Notification Adapter 接口（单向推送）

```python
class NotificationAdapter(Protocol):
    name: str

    async def send(
        self,
        recipient: Recipient,          # email/im_open_id/webhook_url
        template: NotificationTemplate, # title + body + actions[]
        context: dict,
    ) -> NotificationResult: ...
```

实例化适配器：
- `email`: aiosmtplib + Jinja2
- `feishu`: 卡片消息 (template_card) + Bot 回调
- `wecom`: 模板卡片 + 应用消息
- `dingtalk`: ActionCard + 工作通知
- `slack`: Block Kit + Interactivity URL
- `mattermost`: Incoming Webhook + slash command 回调
- `webhook`: 通用 POST JSON

**Action 卡片**：每个 IM 的卡片携带 4 个 token-bound URL（与邮件一致），用户在 IM 内点击直达决策页（不跳 IM 内做处理，统一在 Web 决策页签收）。这样：(a) 各 IM 适配器只需实现"渲染卡片"； (b) 安全 / 鉴权 / token 消费统一在 Web 后端做。

> 取舍说明：原本 L3 选项里"IM 内一键决策"意味着 IM Bot 回调处直接消费 token + resume。但这会让各 IM 适配器都承担 token 校验 / actor 身份解析逻辑，重复且易出错。改为「IM 卡片 = 邮件深链的等价物，用户点开就回 Web」，安全集中。「IM 一键决策」可作为 v1.1 增强：通过预绑定 actor 的 IM open_id 信任源识别身份。

### 7.2 IM Directory Connector（双向同步）

每个 IM 类型一个 connector，定时拉取（默认 1h）：

```python
class ImDirectoryConnector(Protocol):
    async def list_users(self) -> list[ImUser]: ...
    async def list_departments(self) -> list[ImDept]: ...
    async def list_managers(self) -> dict[user_id, manager_id]: ...
```

同步策略：
- 拉取存入 `im_directory` 表（diff 写入，不删除历史）
- 后台 job 把 IM 用户匹配本地 `users.email` → 自动写 `users.im_bindings`
- workflow DSL 中的 `assignees` 可填 `email / @feishu_username / @wecom_userid / dept:研发部`，由 resolver 在节点进入时解析为 user_id list

---

## 8. 节点扩展机制（"做的成熟"）

### 8.1 三层节点

| 层 | 来源 | 加载方式 |
| -- | ---- | --------- |
| **内置** | 引擎核心 | 直接 import |
| **一等公民** | 业务核心（LLM/Tool/HITL/Notification/API） | 直接 import，但实现遵循 Node 协议 |
| **插件** | 第三方上传 | 沙箱子进程，stdio IPC |

### 8.2 插件包结构

```
my_plugin.zip
├── manifest.yaml         # id, version, author, icon, category, runtime
├── schema.json           # input/output/config JSON Schema
├── node.py               # 必须实现 BaseNode.execute(ctx, inputs) -> outputs
├── requirements.txt      # 白名单 + 版本锁
└── README.md
```

`manifest.yaml`：

```yaml
id: com.example.translate-en2zh
name: 英译中翻译节点
version: 1.0.0
author: example
category: tool
runtime: python3.11
permissions:
  network: ["api.openai.com"]      # 网络白名单
  memory_mb: 256
  cpu_cores: 0.5
  timeout_sec: 30
```

### 8.3 沙箱执行

- 每个插件节点在独立子进程跑（重用 worker pool）
- Linux `cgroups v2` 限 CPU/内存（macOS dev 用 resource limits）
- 网络走 squid proxy + ACL（仅放行 manifest 声明的 host）
- IPC：stdin 写 JSON 输入，stdout 读 JSON 输出，stderr 收日志
- 超时强杀

### 8.4 安装流程

1. 管理员上传 zip → `POST /admin/plugins`
2. 后端解压 → 校验签名 → 校验 manifest schema → dry-run (sandbox) → 通过则状态 `registered`
3. 注册到 `NodeRegistry`，画布的节点面板立即可见
4. 卸载：先把所有使用该插件的实例 pause → 状态 `disabled`

### 8.5 v1 边界

- v1 提供：上传安装 / 沙箱运行 / 卸载 / 简单分类
- v1 不做：市场前台、评分、付费、签名验证 PKI（密钥分发由管理员手动）

---

## 9. 部署

### 9.1 docker-compose 服务

```yaml
services:
  api:         # FastAPI (uvicorn workers=4)
  worker:      # LangGraph 异步执行
  web:         # Next.js
  postgres:    # 15+
  redis:       # 7+
  nginx:       # 公网反代
  plugin-sandbox-pool:  # 沙箱子进程池
```

### 9.2 公网入口

仅 `nginx` 容器对外暴露 80/443，且仅放行：
- `GET /hitl/page/*`       → web (token 登录页)
- `POST /hitl/action/*`    → api
- `POST /api/im/webhook/*` → api (IM Bot 回调)
- 其他全部 403

Web 管理端走内网/VPN（直连内网 IP:3000 或 Cloudflare Access）。

### 9.3 环境变量

```
# 公网入口
PUBLIC_BASE_URL=https://approve.example.com

# 数据库
DATABASE_URL=postgresql+asyncpg://...
REDIS_URL=redis://...

# 安全
HMAC_SECRET=<32+ bytes 随机>
JWT_ISSUER=agent-builder
TOKEN_TTL_SECONDS=86400

# SMTP（示例，实际从 secret 注入，不进代码）
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USER=...
SMTP_PASSWORD=...        # 从 secret manager 读，不在 .env 提交
SMTP_FROM=...

# IM 适配器（示例）
FEISHU_APP_ID=...
FEISHU_APP_SECRET=...
WECOM_CORP_ID=...
WECOM_AGENT_ID=...
WECOM_SECRET=...
DINGTALK_APP_KEY=...
DINGTALK_APP_SECRET=...
SLACK_BOT_TOKEN=...
SLACK_SIGNING_SECRET=...
MATTERMOST_URL=...
MATTERMOST_BOT_TOKEN=...

# LLM
LLM_PROVIDER=glm
GLM_API_KEY=...
```

---

## 10. 路线图

| 里程碑 | 内容 | 周期 | 验收 |
| ------ | ---- | ---- | ---- |
| **M0** 设计评审 | 本文档评审通过 | 1-2 天 | doc commit |
| **M1** Skeleton | Fork flock → 跑通本地 dev → docker-compose 起来 → 改名 → 自建账号体系 | 1 周 | 能注册/登录/拖一个 demo 流程 |
| **M2** DSL + 引擎 | DSL schema + compiler + 5 个内置节点 + Postgres checkpoint | 2 周 | 简单 DAG 端到端跑通 |
| **M3** HITL 四态 | 单节点 HITL + 邮件适配器 + Token 鉴权 + Web 决策页 | 1.5 周 | 邮件审批端到端 demo（单人） |
| **M4** 审批链 + IM 通知 | 4 种审批链 + feishu/wecom/dingtalk 通知卡片 | 2 周 | 多人会签 demo + 飞书卡片决策 |
| **M5** IM 目录同步 | feishu/wecom/dingtalk 三家双向同步 + 节点 assignee 多形态 | 2 周 | 拉到部门树，按部门指派审批 |
| **M6** 插件机制 | 沙箱 + manifest + 上传安装 + 一个示例插件 | 2 周 | 跑通第三方节点 |
| **M7** 模板与可观测 | 模板预置（含 hr 离职示例） + Timeline + audit | 1 周 | 完整 demo 视频 |

**总计**：约 11-12 周（2.5-3 人月）；P1 路径（M0-M3）2-3 周可出可演示版本。

---

## 11. 风险与待决

### 已锁定（不再讨论）
- ✅ Fork flock 作为 skeleton（许可证 Apache-2.0，兼容）
- ✅ DSL 解释执行（不做代码生成）
- ✅ 单 interrupt + 自管审批链状态
- ✅ Token 即登录（不做独立 OAuth）
- ✅ 不再对齐 hr/PRD 三态/四态差异（按四态做）

### 待决
- ⚠️ **节点 assignee 表达式解析器**：目前规划 `email / @im_user / dept:xxx / dynamic_expr`。需要在 M2 阶段定一个简单的 JsonPath / Jinja 子集，避免引入完整表达式引擎。
- ⚠️ **flock 上游 merge 策略**：fork 后大概率会改动很多核心文件，未来 merge 上游会冲突。建议：(a) 改造点尽量集中在新增模块（adapters、hitl、auth），尽量少动 flock 现有文件；(b) 每月 cherry-pick 上游关键 bug fix。
- ⚠️ **多语言**：v1 中文 only，i18n 留到 v2。
- ⚠️ **WebSocket 实时画布**：flock 是否已有？需要 M1 阶段确认。

### 调研参考

- [Onelevenvy/flock](https://github.com/Onelevenvy/flock) — Skeleton
- [langchain-ai/agent-inbox](https://github.com/langchain-ai/agent-inbox) — HITL UX schema
- [langchain-ai/langgraph-builder](https://github.com/langchain-ai/langgraph-builder) — LangGraph DSL 参考（项目已归档但思路可借鉴）
- [activepieces](https://github.com/activepieces/activepieces) — 邮件审批 piece
- [n8n approval workflow](https://community.n8n.io/t/approval-workflow-in-n8n/17428) — 邮件 token 设计
- [LangGraph Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) — interrupt + Command(resume=)
- [langgraph-checkpoint-postgres](https://pypi.org/project/langgraph-checkpoint-postgres/)
- [Dify](https://github.com/langgenius/dify) — Canvas UI 设计语言（已 clone 到 `/Users/admin/ai/ref/dify/repo`）
- [Dify Plugin Daemon 设计](https://github.com/langgenius/dify-plugin-daemon) — 插件沙箱参考
- [KirtiJha/langgraph-interrupt-workflow-template](https://github.com/KirtiJha/langgraph-interrupt-workflow-template) — FastAPI + 中断恢复样例

---

> 下一步：本文档评审通过后，建立 worktree → fork Onelevenvy/flock → 进入 M1 阶段。
