# Architecture Research

**Domain:** 可视化拖拽工作流编排平台 + 多通道 HITL 审批 + 公网回调
**Researched:** 2026-05-16
**Confidence:** HIGH（基于 Dify 源码直读 + 设计文档分析）

---

## Standard Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Web 前端 (Next.js 14+)                           │
│  ┌─────────────────┐  ┌──────────────────┐  ┌────────────────────────┐  │
│  │  Canvas 编辑器   │  │  实例监控 Timeline │  │  HITL 决策页           │  │
│  │  (React Flow)   │  │  (WebSocket 实时) │  │  /form/[token]        │  │
│  │  + 节点面板      │  │  节点状态时间轴    │  │  (公网可匿名访问)       │  │
│  └────────┬────────┘  └────────┬─────────┘  └───────────┬────────────┘  │
└───────────┼─────────────────────┼────────────────────────┼───────────────┘
            │ REST                 │ WebSocket              │ REST (公网)
            ▼                     ▼                        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     API 网关层 (FastAPI)                                  │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌───────────────┐  │
│  │ /api/v1/     │ │ /api/v1/     │ │ /hitl/page/* │ │ /api/im/      │  │
│  │ workflows    │ │ instances    │ │ /hitl/action/│ │ webhook/*     │  │
│  │ (DSL CRUD)   │ │ (exec ctrl)  │ │ * (公网端点) │ │ (IM 卡片回调) │  │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └───────┬───────┘  │
└─────────┼────────────────┼────────────────┼─────────────────┼───────────┘
          │                │                │                 │
          ▼                ▼                ▼                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    核心引擎层 (DSL → LangGraph)                           │
│  ┌───────────────────┐  ┌────────────────┐  ┌──────────────────────┐   │
│  │  DSL Compiler      │  │  NodeRegistry  │  │  HITL Chain Engine   │   │
│  │  dsl → StateGraph  │  │  (三层节点)    │  │  (四态 + 四种审批链) │   │
│  │  compile() 热更新  │  │  内置/一等/插件 │  │  单 interrupt 自管   │   │
│  └────────┬───────────┘  └───────┬────────┘  └──────────┬───────────┘   │
│           └──────────────────────▼───────────────────────┘               │
│                        ┌──────────────────┐                               │
│                        │  Execution Eng.  │                               │
│                        │  ainvoke/aresume │                               │
│                        │  PostgresSaver   │                               │
│                        └──────────────────┘                               │
└──────────┬──────────────────────┬──────────────────────┬──────────────────┘
           │                      │                      │
           ▼                      ▼                      ▼
┌──────────────────┐  ┌──────────────────────┐  ┌───────────────────────┐
│ Notification     │  │ IM Directory         │  │ Plugin Sandbox        │
│ Adapters         │  │ Connectors           │  │ (子进程 + cgroups)    │
│ (Protocol 接口)  │  │ (Protocol 接口)      │  │ + stdio IPC           │
│ email/feishu/    │  │ feishu/wecom/        │  │ + network whitelist   │
│ wecom/dingtalk/  │  │ dingtalk             │  │                       │
│ slack/mattermost │  │ 用户/部门/汇报关系   │  │                       │
│ /webhook         │  │ 定时同步→im_directory│  │                       │
└──────────────────┘  └──────────────────────┘  └───────────────────────┘
           │                      │
           ▼                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    持久化层 (PostgreSQL + Redis)                           │
│  PostgreSQL:                                                             │
│    workflows / flow_instances / node_states / action_logs               │
│    users / workspaces / plugins / im_directory                           │
│    notifications / hitl_tokens                                           │
│    langgraph_checkpoints (PostgresSaver 专属表)                          │
│  Redis:                                                                  │
│    jti 黑名单 / rate limit 计数器 / session cache                        │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Component Boundaries（组件边界）

| 组件 | 职责 | 与谁通信 | 通信方式 |
|------|------|----------|----------|
| **Web Canvas** | DSL 可视化编辑、节点面板、状态监控 | Backend API | REST + WebSocket |
| **HITL 决策页** | token 解码登录、渲染审批表单、提交决策 | Backend API (公网) | REST |
| **FastAPI Router** | 路由、鉴权中间件、rate limit | Core Engine / Adapters | 函数调用 |
| **DSL Compiler** | DSL JSON → LangGraph StateGraph | NodeRegistry, Executor | 函数调用 |
| **NodeRegistry** | 三层节点注册与查找（内置/一等/插件） | DSL Compiler, Plugin Sandbox | 函数调用 / stdio IPC |
| **Execution Engine** | ainvoke / aresume，管理 thread 生命周期 | PostgresSaver, HITL Chain | 函数调用 / Postgres |
| **PostgresSaver** | LangGraph checkpoint 持久化 | Postgres | SQL |
| **HITL Chain Engine** | 四态状态机 + 四种审批链算法 | Notification Adapters, Token Service | 函数调用 |
| **Token Service** | JWT 签发/校验/jti 一次性消费 | Redis / Postgres (hitl_tokens) | Redis SET / SQL |
| **Notification Adapters** | 按 Protocol 统一接口向各通道推送消息（单向） | 各 IM/SMTP API（外部） | HTTP |
| **IM Directory Connectors** | 拉取 IM 组织架构，写 im_directory 表 | 各 IM API（外部）/ Postgres | HTTP / SQL |
| **Assignee Resolver** | 将 DSL assignee 表达式解析为 user_id 列表 | im_directory, users | SQL |
| **Plugin Sandbox** | 隔离运行第三方插件节点 | NodeRegistry（接收任务）/ cgroups | stdio IPC |

---

## Data Flow（数据流向）

### Flow 1：Canvas → DSL → 发布

```
用户拖拽节点/连线
  ↓ React Flow onNodesChange / onEdgesChange
Zustand WorkflowStore 实时更新
  ↓ 防抖 500ms
PATCH /api/v1/workflows/{id}/draft  → 存草稿 (workflows.draft JSONB)
  ↓ 用户点"发布"
POST /api/v1/workflows/{id}/publish → dsl_validator.validate()
  → workflows.dsl = draft, version++, status = published
```

### Flow 2：DSL → 执行引擎编译运行

```
POST /api/v1/instances          (input: workflow_id + context)
  ↓
dsl = load_published_dsl(workflow_id)
  ↓
graph = DSLCompiler.compile(dsl)   # dsl_compile() 动态组装 StateGraph
  ↓
instance = create_flow_instance()  # thread_id = instance.id
  ↓
await graph.ainvoke(input, config={"configurable": {"thread_id": thread_id}})
  ↓ (异步后台)
LangGraph 执行各节点
  ↓ HITL 节点 → interrupt(hitl_payload)
PostgresSaver 写 checkpoint
  ↓
node_state.status = waiting_human
```

### Flow 3：HITL 节点激活 → 多通道通知

```
HITL 节点 execute() 被调用
  ↓
读取 dsl.config.approval_chain 解析 approvers
  → AssigneeResolver 查 im_directory / users 表
  ↓
初始化 approval_chain_state 写入 node_state.payload
  ↓
生成 N 个 JWT token（每个 action 一个）
  → hitl_tokens 表写入 jti 记录
  ↓
HITL Chain Engine: send_notifications(recipients, channels)
  → Notification Adapters 并行推送（email/feishu/wecom/...）
  ↓
调用 interrupt(snapshot)  ← LangGraph 暂停到 checkpoint
```

### Flow 4：Token 回调 → 审批链推进 → LangGraph resume

```
审批人收邮件/IM 卡片
  ↓ 点击按钮
GET /hitl/page/{token}              ← nginx 放行，仅此路径
  → TokenService.verify(token)      : 校验签名 + exp + jti 未消费
  → 生成 30min session cookie (携带 jti)
  → 渲染对应角色决策页（前端）
用户填写表单 → 点"确认"
  ↓
POST /hitl/action/{token}          (cookie + body)
  → 校验 cookie.jti == token.jti
  → TokenService.consume(jti)       : Redis SET NX / Postgres advisory lock
  → write action_logs
  → HITL Chain Engine: on_approver_action(state, actor, action)
      case DONE/TERMINATE/RETURN:
        update node_state.status
        await graph.ainvoke(
          Command(resume=decision),
          config={"configurable": {"thread_id": thread_id}}
        )
      case CONTINUE:
        仅更新 node_state.payload (current_idx / pending_approvers)
        发送下一位通知 → 不触动 LangGraph
```

### Flow 5：IM Directory 同步 → Assignee 解析

```
定时任务 (每 1h) / 手动触发
  ↓
ImDirectoryConnector[feishu/wecom/dingtalk].list_users()
  → 增量 diff 写 im_directory 表
  ↓
后台 job: 按 email 字段匹配 users 表
  → 自动更新 users.im_bindings[feishu_open_id / wecom_userid / ...]
  ↓
HITL 节点进入时:
  AssigneeResolver.resolve("dept:研发部")
    → 查 im_directory WHERE department = '研发部'
    → 返回 user_id 列表
```

### Flow 6：插件安装 → 节点注册 → Canvas 使用

```
管理员上传 plugin.zip
  ↓
POST /admin/plugins → 解压 → 校验 manifest.yaml + schema.json
  → dry-run(sandbox): 启动子进程执行 node.py health check
  → PASS → plugins 表 status = registered
  ↓
NodeRegistry.register(plugin_manifest)
  → 画布节点面板 API 返回新节点类型
  ↓
DSL 中可使用该节点 type
  ↓ 执行时
DSL Compiler 遇到 plugin_type
  → NodeRegistry.resolve(type) → PluginNode wrapper
  → PluginSandbox.invoke(node.py, inputs) via stdio IPC
  → 返回 outputs → 写入 LangGraph state
```

---

## Critical Sequence Diagrams（关键时序图）

### Seq-1：HITL 端到端（邮件深链审批）

```
用户/系统          FastAPI             HITL Engine        LangGraph          PostgresSaver
   │                  │                    │                 │                    │
   │ POST /instances  │                    │                 │                    │
   │─────────────────>│                    │                 │                    │
   │                  │ compile(dsl)       │                 │                    │
   │                  │────────────────────────────────────> │                    │
   │                  │                    │   ainvoke()     │                    │
   │                  │                    │                 │ checkpoint_write()  │
   │                  │                    │                 │────────────────────>│
   │                  │                    │    interrupt()  │                    │
   │                  │                    │ <───────────────│                    │
   │                  │ enter_hitl_node()  │                 │                    │
   │                  │ ──────────────────>│                 │                    │
   │                  │                    │ resolve_approvers()                  │
   │                  │                    │ (AssigneeResolver)                   │
   │                  │                    │                 │                    │
   │                  │                    │ generate_tokens(N)                   │
   │                  │                    │ jti→hitl_tokens+Redis                │
   │                  │                    │                 │                    │
   │                  │                    │ send_email(token_links)              │
   │                  │                    │ [并行推 feishu/wecom 卡片]           │
   │                  │                    │                 │                    │
审批人               │                    │                 │                    │
   │  GET /hitl/page/{token}              │                 │                    │
   │─────────────────>│                    │                 │                    │
   │                  │ verify_token()     │                 │                    │
   │                  │ set session cookie │                 │                    │
   │ <─────────────── │ (30min, jti 携带) │                 │                    │
   │  渲染决策表单     │                    │                 │                    │
   │  POST /hitl/action/{token} + cookie  │                 │                    │
   │─────────────────>│                    │                 │                    │
   │                  │ verify_cookie_jti  │                 │                    │
   │                  │ consume_jti (Redis NX + advisory_lock)                   │
   │                  │ write action_log   │                 │                    │
   │                  │ ──────────────────>│                 │                    │
   │                  │                    │ on_approver_action(DONE)             │
   │                  │                    │ update node_state→done               │
   │                  │                    │ ainvoke(Command(resume=approve))     │
   │                  │                    │────────────────>│                    │
   │                  │                    │                 │ checkpoint_write()  │
   │                  │                    │                 │────────────────────>│
   │ <─────────────── │ 200 OK (已审批)    │                 │                    │
```

### Seq-2：Plugin Sandbox 调用

```
DSL Compiler         NodeRegistry        PluginSandbox         node.py (子进程)
     │                    │                   │                      │
     │ resolve("com.x.t") │                   │                      │
     │───────────────────>│                   │                      │
     │ <─── PluginNode{manifest, schema}      │                      │
     │                    │                   │                      │
LangGraph 执行到插件节点  │                   │                      │
     │ execute(inputs)    │                   │                      │
     │─────────────────────────────────────> │                      │
     │                    │    spawn_or_reuse_subprocess()           │
     │                    │                   │──────────────────────>│
     │                    │    stdin: {"inputs": {...}}              │
     │                    │                   │──────────────────────>│
     │                    │                   │   (cgroups cpu/mem)  │
     │                    │                   │   (squid proxy ACL)  │
     │                    │    stdout: {"outputs": {...}}            │
     │                    │                   │<──────────────────────│
     │                    │                   │                      │
     │ <─── outputs ────────────────────────  │                      │
     │ write to StateGraph state              │                      │

超时场景:
     │                    │    timeout_sec 到达                      │
     │                    │                   │ SIGKILL(pid)         │
     │                    │                   │──────────────────────>│
     │ <─── PluginTimeoutError               │                      │
```

### Seq-3：IM 卡片决策回调（L3 集成）

```
审批人(IM内)       IM Bot Server       FastAPI /im/webhook/*      HITL Engine
     │                  │                       │                      │
     │ 点击卡片按钮      │                       │                      │
     │ (携带 action_url) │                       │                      │
     │────────────────> │                       │                      │
     │                  │ POST /api/im/webhook/feishu                  │
     │                  │──────────────────────>│                      │
     │                  │                       │ verify_im_sign()     │
     │                  │                       │ 取 card_action.value │
     │                  │                       │  → token (嵌入卡片)  │
     │                  │                       │──────────────────────>│
     │                  │                       │   同 Seq-1 Token路径  │
     │                  │                       │ (verify+consume+resume)
     │                  │ 更新卡片(已审批状态)   │ <─────────────────────│
     │                  │<──────────────────────│                      │
     │ 卡片变为"已处理"  │                       │                      │
     │<─────────────────│                       │                      │

注意: v1 设计将 IM 卡片按钮指向 Web 决策页 URL（非直接回调），
      v1.1 增强才做 IM 内一键决策（上图为 v1.1 路径）。
      v1 路径: 卡片按钮 = 邮件深链等价物 → 用户点开 Web 页 → 同 Seq-1。
```

---

## Module Tree 验证与改进

### 设计文档 §3.2 模块树 — 确认与改进

原树基本正确，以下是几处改进建议：

**改进 1：DSL compiler 拆分 `interpreter.py`**

原 `dsl/compiler.py` 需要承担 schema 解析 + StateGraph 组装 + 节点注册查找，建议拆成：
```
api/core/dsl/
├── schema.py        # Pydantic 模型（DSL JSON → 强类型）
├── validator.py     # 语义校验（环检测、节点 type 是否注册等）
├── compiler.py      # DSL → LangGraph StateGraph（组装逻辑）
└── interpreter.py   # 运行时解释（动态 edge condition 求值）
```

**改进 2：`adapters/` 拆出 `assignee_resolver.py`**

AssigneeResolver 横跨 im_directory 和 users，不属于 notification 也不属于 im_directory，应独立：
```
api/adapters/
├── notification/       （原有）
├── im_directory/       （原有）
├── assignee_resolver.py  ← 新增（email / @user / dept: 表达式解析）
└── llm/
```

**改进 3：`api/core/hitl/` 补充 `timeout.py`**

超时升级策略（HITL-04）需要独立模块：
```
api/core/hitl/
├── chain.py         # 4 种审批链算法
├── token.py         # JWT 签发/校验/jti 消费
├── session.py       # token → cookie
└── timeout.py       # 节点级超时 + 升级策略（APScheduler job）
```

**改进 4：区分 `api/` 路由层与 `core/` 业务层目录命名**

原树中 `api/api/v1/` 层级冗余，建议：
```
agent-builder/
├── backend/              # 替代原 api/（避免同名混乱）
│   ├── app/              # FastAPI application factory
│   ├── core/             # 业务核心（无 HTTP 依赖）
│   ├── routers/          # HTTP 路由（原 api/v1/）
│   ├── adapters/         # 外部集成适配器
│   ├── nodes/            # 节点实现
│   ├── plugin_runtime/   # 沙箱
│   └── models/           # ORM 模型
└── frontend/             # Next.js（原 web/）
```

---

## Architectural Patterns（关键架构模式）

### Pattern 1：单 interrupt + 自管审批链状态

**What:** LangGraph 只做一次 interrupt，审批链内部状态（current_idx, records, pending_approvers）存在 `node_states.payload` JSONB 里，由应用层（HITL Chain Engine）自管。只有审批链到终态（DONE/TERMINATE/RETURN）时才调用 `Command(resume=decision)` 恢复 LangGraph。

**Why:** 避免每次审批动作都写 LangGraph checkpoint（减少 checkpoint 膨胀）；简化 thread 状态恢复路径；多步审批不等于多次 interrupt。

**Example:**
```python
# HITL Chain Engine 核心分支（伪代码）
def on_approver_action(node_state_id, actor, action) -> ChainResult:
    state = load_chain_state(node_state_id)  # 从 node_states.payload 读
    state = state.apply(actor, action)        # 不可变更新，返回新 state
    save_chain_state(node_state_id, state)    # 写回 payload

    match state.outcome:
        case CONTINUE:
            send_next_notification(state)     # 发下一位通知，不动 LangGraph
            return CONTINUE
        case DONE | TERMINATE | RETURN:
            update_node_status(node_state_id, state.outcome)
            await graph.ainvoke(              # 只有此时才 resume
                Command(resume=state.decision),
                config={"configurable": {"thread_id": thread_id}}
            )
            return state.outcome
```

**Confidence:** HIGH（设计文档 §5.2 锁定，与 LangGraph interrupt 官方文档一致）

---

### Pattern 2：Token 走 Path 而非 Query

**What:** HITL 深链格式为 `/hitl/page/{token}`，token 在 URL path 中，不在 query string 中。

**Why:** query string 出现在 Referrer header、nginx access log、浏览器历史、服务端 access log；path 中的敏感参数同样可能出现在日志，但通过 nginx 路由规则可屏蔽特定路径段的日志记录；同时 path 形态与 Clerk magic link、Activepieces approval link 的业界惯例一致。

**Token 生命周期（安全要点）:**
1. 页面展示阶段（GET）：**不消费 jti**，只验签发 session cookie（携带 jti，30min）
2. 决策提交阶段（POST）：**才消费 jti**，使用 Redis SET NX + Postgres advisory lock 防并发双提交
3. 同一 node_state 任一 token 被消费后，其他 token 同时失效（检查 node_state.status）

**Confidence:** HIGH（设计文档 §6 详细描述）

---

### Pattern 3：Notification Adapter Protocol（单向推）

**What:** 所有通知通道实现统一 `NotificationAdapter` Protocol，HITL 节点只依赖抽象接口；IM 卡片按钮指向 Web 决策页（不在 IM 内处理 token），安全逻辑集中在 Web 后端。

**Why (参考 Dify 的实现):** Dify 的 `mail_human_input_delivery_task.py` 证明了这一模式：邮件发送是异步 Celery 任务，内容渲染（Jinja2/SandboxedEnvironment）与发送解耦。v1 各 IM 适配器只实现"渲染卡片 + 发送"，不实现 token 消费，降低安全风险。

```python
class NotificationAdapter(Protocol):
    name: str
    async def send(
        self,
        recipient: Recipient,
        template: NotificationTemplate,
        context: dict,
    ) -> NotificationResult: ...
```

**Confidence:** HIGH（基于 Dify 源码 + 设计文档 §7.1）

---

### Pattern 4：NodeRegistry 三层注册

**What:** 参照 Dify `node_factory.py` 的 `register_nodes()` + `resolve_workflow_node_class()` 模式，但简化为三层：

```python
class NodeRegistry:
    _registry: dict[str, type[BaseNode]] = {}  # 不可变，每次注册返回新 dict

    @classmethod
    def register(cls, node_type: str, node_class: type[BaseNode]) -> None:
        # 内置/一等公民：启动时自动 import 注册（模块 side effect）
        cls._registry = {**cls._registry, node_type: node_class}

    @classmethod
    def register_plugin(cls, manifest: PluginManifest) -> None:
        # 插件：PluginNode wrapper，执行时走 sandbox IPC
        cls._registry = {**cls._registry, manifest.id: PluginNode(manifest)}

    @classmethod
    def resolve(cls, node_type: str) -> type[BaseNode]:
        if node_type not in cls._registry:
            raise UnknownNodeTypeError(node_type)
        return cls._registry[node_type]
```

**Dify 差异:** Dify 使用 `graphon` 包（外部工作流引擎）+ `_import_node_package` 自动发现；本项目用 LangGraph，节点不需要自描述 `__init_subclass__`，Registry 可更简单。

**Confidence:** HIGH（直接参照 Dify node_factory.py 源码）

---

### Pattern 5：Plugin Sandbox（子进程 stdio IPC）

**What:** 每个插件节点在独立子进程运行（重用 worker pool）；通过 stdin/stdout 传递 JSON；cgroups v2 限制 CPU/内存；squid proxy 限制网络。

**Dify 的做法（参考）:** Dify 使用独立的 `plugin-daemon` 进程（Go 服务，通过 HTTP 与主 API 通信）。v1 本项目不做独立 daemon 服务，而是在 API worker 进程内管理子进程池，减少部署复杂度。

**v1 边界:** 不做独立 Plugin Daemon；macOS dev 环境用 `resource.setrlimit`，Linux 生产用 cgroups v2。

```python
class PluginSandbox:
    async def invoke(self, plugin_id: str, inputs: dict) -> dict:
        proc = await self._get_or_spawn(plugin_id)
        payload = json.dumps({"inputs": inputs}).encode()
        stdout, _ = await asyncio.wait_for(
            proc.communicate(input=payload),
            timeout=self._timeout(plugin_id)
        )
        return json.loads(stdout)
```

**Confidence:** MEDIUM（子进程 + stdio IPC 是行业成熟模式；cgroups v2 API 在 Linux 5.8+ 可用）

---

## Anti-Patterns to Avoid（反模式）

### Anti-Pattern 1：每次审批动作都 resume LangGraph

**What people do:** 把审批链的每一步（发下一人通知、中间状态更新）都做成 `Command(resume=...)`。
**Why it's wrong:** 导致 LangGraph checkpoint 膨胀；恢复路径复杂；状态图难调试；PostgresSaver 写入量是必要值的 N 倍。
**Do this instead:** 单 interrupt，应用层 HITL Chain Engine 自管审批链状态，只在终态时才 resume（设计文档 §5.2 锁定）。

### Anti-Pattern 2：Token 存 query string

**What people do:** `/hitl/action?token=eyJ...` 
**Why it's wrong:** Token 出现在 Referrer header、nginx access_log、CDN 日志、浏览器书签/历史；一次泄露 = token 被重放。
**Do this instead:** Token 放 URL path：`/hitl/page/{token}`，nginx 对此路径关闭 access_log 或 mask 敏感段。

### Anti-Pattern 3：在 IM Webhook 回调中直接 consume jti

**What people do:** 各 IM 适配器（飞书/企微）的 webhook 端点各自实现 token 校验和消费逻辑。
**Why it's wrong:** 安全逻辑分散在多个端点，易遗漏（缺 rate limit、jti check、advisory lock）；IM 平台签名验证（HMAC-SHA256）和 HITL token 校验是两层不同的安全机制，混在一起难维护。
**Do this instead:** v1 IM 卡片按钮 = Web 深链（与邮件等价），所有 token 消费统一在 `/hitl/action/{token}` 端点；v1.1 再在 IM webhook 端点里通过已绑定 open_id 识别身份完成一键决策。

### Anti-Pattern 4：启动时动态编译 DSL 为 Python 代码

**What people do:** `dsl_to_python_code(dsl)` → `exec(code)` → 得到一个 StateGraph。
**Why it's wrong:** 热更新不友好（需要进程重启）；exec 有安全风险；调试困难；与 Dify/n8n 解释执行路线背离。
**Do this instead:** 解释执行：`DSLCompiler.compile(dsl)` 动态组装 StateGraph，每次 invoke 前编译（可 lru_cache 缓存），无 exec（设计文档 §2 决策 #2 锁定）。

### Anti-Pattern 5：多租户用数据库前缀区分

**What people do:** 用 `ws_{id}_workflows` 等表名前缀区分 workspace 数据。
**Why it's wrong:** 无法使用 FK、无法联查、DDL 变更噩梦、连接池浪费。
**Do this instead:** 所有表加 `workspace_id` 列 + 行级隔离（所有查询必须带 `WHERE workspace_id = ?`），通过应用层 middleware 注入。

---

## Build Order（构建依赖顺序）

以下依赖图决定了里程碑顺序：

```
Level 0（无外部依赖，可并行）:
  ├── Postgres 表结构 (DDL)
  ├── DSL schema.py (Pydantic 模型)
  └── NotificationAdapter Protocol 接口定义

Level 1（依赖 Level 0）:
  ├── DSL Compiler (依赖 schema + NodeRegistry stub)
  ├── NodeRegistry (依赖 BaseNode Protocol)
  ├── Email Adapter (依赖 NotificationAdapter Protocol)
  └── 用户/账号/鉴权系统 (依赖 Postgres)

Level 2（依赖 Level 1）:
  ├── Execution Engine (依赖 DSL Compiler + PostgresSaver)
  ├── Token Service (依赖 Postgres hitl_tokens + Redis)
  └── 基础节点: Start/End/LLM/Tool/IfElse (依赖 NodeRegistry)

Level 3（依赖 Level 2）:
  ├── HITL Chain Engine (依赖 Token Service + Email Adapter + Execution Engine)
  ├── HITL 节点实现 (依赖 HITL Chain Engine + NodeRegistry)
  └── 公网路由 /hitl/page/* /hitl/action/* (依赖 Token Service)

Level 4（依赖 Level 3）:
  ├── 审批链 4 种模式 (依赖 HITL Chain Engine)
  ├── IM Notification Adapters (飞书/企微/钉钉)
  └── HITL 决策页 (前端，依赖 Token Service + API)

Level 5（依赖 Level 4）:
  ├── IM Directory Connectors (依赖 im_directory 表 + IM API)
  ├── AssigneeResolver (依赖 im_directory + users)
  └── 并行/Loop/Subgraph 节点 (依赖 Execution Engine)

Level 6（依赖 Level 5）:
  ├── Plugin Sandbox (依赖 NodeRegistry + subprocess)
  ├── Plugin 安装流程 (依赖 Sandbox + plugins 表)
  └── 节点面板动态加载 (前端，依赖 NodeRegistry API)
```

**对应里程碑映射:**
- M1 = Level 0-1（Skeleton + 账号体系）
- M2 = Level 1-2（DSL + 引擎 + 基础节点）
- M3 = Level 2-3（HITL 四态 + Email + Token）
- M4 = Level 3-4（审批链 4 种 + IM 通知卡片）
- M5 = Level 5（IM 目录同步 + Assignee Resolver）
- M6 = Level 6（插件机制）

---

## Integration Points（集成点）

### 外部服务集成

| 服务 | 集成模式 | 关键注意点 |
|------|----------|------------|
| **PostgreSQL** | SQLAlchemy async + asyncpg | PostgresSaver 需独立 connection pool（避免与业务 pool 竞争） |
| **Redis** | aioredis / redis-py async | jti 黑名单用 `SET jti EX {ttl} NX`，原子防重放 |
| **SMTP** | aiosmtplib + Jinja2 | 邮件渲染用 `ImmutableSandboxedEnvironment`（参照 Dify）防模板注入 |
| **飞书 Bot** | 飞书开放平台 API v3 | 卡片消息需 tenant_access_token（2h 过期，需 refresh） |
| **企业微信** | 企微应用消息 API | 需 corp_id + agent_id；card 回调需验证 msg_signature |
| **钉钉** | 钉钉 ActionCard | 需 appKey；Webhook 签名 = timestamp+secret HMAC-SHA256 |
| **Slack** | Block Kit + Events API | Bot token scope: `chat:write, im:write`；Interactivity callback URL |
| **Mattermost** | Incoming Webhook | 最简单；Slash command 回调验证 token |

### 内部边界

| 边界 | 通信方式 | 注意点 |
|------|----------|--------|
| DSL Compiler ↔ NodeRegistry | 同进程函数调用 | NodeRegistry 必须在 compile() 前完成注册（启动时完成） |
| Execution Engine ↔ PostgresSaver | LangGraph 内部（async SQLAlchemy） | thread_id = flow_instance_id，保持全局唯一 |
| HITL Engine ↔ Notification Adapters | 同进程 async 调用（并行 gather） | 发送失败不应阻塞审批链推进，需 try/except per adapter |
| API Server ↔ Plugin Sandbox | subprocess stdio | 严格限制 sandbox 的 env（不传数据库 URL / API key） |
| Web Canvas ↔ FastAPI | REST + WebSocket | WebSocket 用于实例状态实时推送（节点 entering/done/waiting_human） |

---

## Scaling Considerations（扩展性考虑）

| 规模 | 架构调整 |
|------|----------|
| **0-100 工作流** | 单机 Docker Compose 足够；API worker 4进程；无需拆分 |
| **100-1000 工作流** | worker 进程拆出为独立容器（api/worker 分离）；Redis 做 rate limit cluster |
| **1000+ 并发实例** | LangGraph Execution 换 Celery/ARQ 任务队列；Plugin Sandbox 独立服务（类 Dify Plugin Daemon）；读写分离 |

**v1 场景:** 内网部署，预期 <100 工作流，单机 Docker Compose 足够。扩展路径留在 v2。

---

## Sources

- `/Users/admin/ai/ref/dify/repo/api/core/workflow/node_factory.py` — NodeRegistry 自注册模式
- `/Users/admin/ai/ref/dify/repo/api/core/workflow/human_input_policy.py` — HITL Token 优先级策略
- `/Users/admin/ai/ref/dify/repo/api/core/workflow/human_input_adapter.py` — Email 模板 + Recipient 模型
- `/Users/admin/ai/ref/dify/repo/api/models/human_input.py` — HumanInputForm ORM + 状态字段
- `/Users/admin/ai/ref/dify/repo/api/tasks/mail_human_input_delivery_task.py` — 邮件异步发送模式
- `/Users/admin/ai/ref/dify/repo/api/libs/email_template_renderer.py` — Jinja2 SandboxedEnvironment
- `/Users/admin/ai/ref/dify/repo/api/core/plugin/impl/base.py` — Plugin Daemon HTTP 通信模式
- `/Users/admin/ai/ref/dify/ARCHITECTURE_SUMMARY.md` — Dify Canvas 前端 Zustand 状态管理
- `/Users/admin/ai/resume/interview/liuxin/agent-builder/docs/plans/2026-05-16-agent-builder-design.md` — 项目设计文档（主要依据）
- LangGraph 官方文档：interrupt + Command(resume=) 模式（MEDIUM confidence，训练数据）
- langgraph-checkpoint-postgres PyPI（MEDIUM confidence，训练数据）

---

*Architecture research for: agent-builder（可视化拖拽工作流编排平台 + 多通道 HITL 审批）*
*Researched: 2026-05-16*
