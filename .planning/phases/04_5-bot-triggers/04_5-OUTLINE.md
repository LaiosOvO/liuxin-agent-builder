# Phase 4.5: Bot Triggers + Reply (双向 IM) — Outline

> 日期: 2026-05-16
> 状态: OUTLINE — 正式 CONTEXT + plans 待 Phase 2 执行结束后通过 `/gsd:discuss-phase 4.5` 走标准 GSD 流程

## 背景

Phase 4 规划了 **IM 出站通知**（飞书/企微/钉钉/Slack/Mattermost 卡片通知），但只能从 workflow 主动外推。

用户新需求：**入站 → 触发 workflow**（用户在 IM 里 @bot 或发消息，workflow 跑起来 + 把结果回帖到原线程）。

例：在 Mattermost 频道里 `@AgentBuilder 帮我查一下离职流程进度` → workflow 跑「查流程」节点 → bot 回帖结果到该 thread。

## Goal

通用 IM Bot 双向接入，加新 IM 仅需实现 Provider 接口。

**Mattermost 第一个 P0 落地**；其它 IM (飞书/企微/钉钉/Slack) 作为可插拔 provider 后补。

## 范围

### 新增 2 类节点

| 节点 | 角色 | 流程位置 | 配置 |
|---|---|---|---|
| **Trigger Node** | workflow **起点**（替代 Start，或并存）| 第一个节点 | provider(mattermost/feishu/...) + bot_id + 触发条件 (@mention / DM / channel scope / **slash command**) |
| **Reply Node** | 把当前 state 字段回帖到**原 IM 线程** | 任意位置（通常末端，可中段汇报）| provider + thread_id (来自 trigger 节点 state) + message template (Jinja2) |

**与 Notification 节点（Phase 4）的区别**：Notification 主动外推到任意指定收件人；Reply 仅在 trigger 起源的 thread 回帖（同一对话上下文）。

### Slash 命令分发（用户 2026-05-16 追加需求）

**目标**：单个 bot 接收多个 slash 命令（如 `/leave` `/approve` `/status` `/help`），不同命令分发到不同 workflow 或同一 workflow 的不同入口子图。

**实现方式（推荐 A）**：

**A. 每个 slash 命令绑定一个 Trigger 节点**（推荐 — 与 DAG 一致性高）
- Trigger 节点配置 `slash_command: "/leave"`，仅当 IM 消息以该命令开头时触发该 workflow
- 一个 bot 多个 slash → 多个独立 workflow 各自有自己的 Trigger 节点
- 优点：清晰 / 每 workflow 独立 / 易理解
- 缺点：N 个命令 = N 个 workflow 文件（适合大 IM bot 平台）

**B. 单 workflow 内部 IfElse 分发**（适合命令逻辑高度同构场景）
- 单 Trigger 节点接所有消息（无 slash 过滤）
- 紧接一个 IfElse 节点按 `state.trigger.slash_command` 路由到不同分支
- 优点：单 workflow 内部聚合 / 共享前后处理
- 缺点：DSL 复杂 / 单点 workflow 跑挂全 bot down

**C. Bot Dispatcher 元 workflow**（高级模式，可选）
- 一个"Dispatcher workflow"用 Subgraph 节点封装：根据 slash 调用不同子 workflow
- 类似 url-routing 中间件思路
- 优点：组合性强，可以中心化管命令权限/统计
- 缺点：抽象层多，调试链路长

**v1 实现**：A（推荐）。Trigger 节点 `slash_command` 字段，单一命令绑单一 workflow。同 bot 多命令通过同一 bot account 关联多 workflow 实现。Bot 入站消息进来后，Slash Dispatcher 层根据命令前缀路由到匹配的 Trigger 节点。

**Slash Dispatcher 后端架构**：
```
IM 消息 (e.g., "/leave 2026-05-20 sick")
   ↓ Bot Provider 入站
Slash Dispatcher (backend/app/agent_builder/adapters/bot/dispatcher.py)
   ↓ 按 slash 前缀查询匹配 workflow
   ↓ 找到匹配的 Trigger 节点
   ↓ 启动该 workflow 实例 (thread_id / user_id / message / parsed_args 注入 state)
LangGraph 跑起来
```

**Slash 命令注册中心**：表 `bot_slash_commands` 记 `(provider, bot_id, slash_command, workflow_id, description, help_text)`，用于：
- IM 启动时向 Mattermost 注册 slash 命令列表（让 `/help` 自动列出可用命令）
- 入站消息时反查路由
- Admin UI 可视化管理（这个 bot 注册了哪些 slash → 哪个 workflow）

### Provider 抽象

```python
class BotProvider(Protocol):
    name: str  # mattermost / feishu / wecom / dingtalk / slack

    async def subscribe(self, on_event: Callable) -> None: ...  # 入站事件流
    async def reply_to_thread(self, thread_id: str, content: str) -> None: ...  # 出站回帖
    async def verify_webhook_signature(self, headers, body) -> bool: ...  # 防伪造
```

每个 IM 一个 Provider 实现，在 `backend/app/agent_builder/adapters/bot/` 下。

### Provider 优先级

| Provider | 优先级 | Phase 4.5 子阶段 | 状态 |
|---|---|---|---|
| Mattermost | **P0** | 4.5.1 (Mattermost 主线 + 抽象层) | 必做 |
| 飞书 (Lark) | P1 | 4.5.2 | 大概率做 |
| 企业微信 | P1 | 4.5.2 | 看用户场景 |
| 钉钉 | P1 | 4.5.2 | 看用户场景 |
| Slack | P1 | 4.5.2 | 海外团队备选 |

### Mattermost 实现要点

- 入站：Mattermost **Outgoing Webhook** OR **Bot WebSocket Event Stream** — WebSocket 更实时
- 出站：Mattermost API `POST /api/v4/posts` 含 `root_id` 回帖到 thread
- 鉴权：Bot Personal Access Token + Webhook secret 验签
- 部署：.44 上的 mattermost-docker-mattermost-1 已经在跑；agent-builder 创建一个 Bot 账号 + 配 token

## Plans 粗布局（待 discuss-phase 阶段细化）

| Plan | 内容 | 工作量 |
|---|---|---|
| 04_5-01 | Bot Provider 接口 + Trigger Node + Reply Node 节点抽象 + NodeRegistry 注册 | M |
| 04_5-02 | **Slash Dispatcher 后端** + bot_slash_commands 表 + 路由匹配 + admin API | M |
| 04_5-03 | Mattermost Provider 实现（WebSocket 入站 + REST 出站 + 签名验证 + slash 命令注册到 Mattermost） | L |
| 04_5-04 | Trigger 节点 → workflow 启动集成（thread_id / user_id / message / parsed_args 注入 state） | M |
| 04_5-05 | Reply 节点 → 出站回帖 + Jinja2 模板 + 长消息分段 | S-M |
| 04_5-06 | 前端：Trigger / Reply 节点 UI + 配置面板 + Slash 管理页 | M |
| 04_5-07 | 飞书 / 企微 / 钉钉 / Slack Provider 实现（4 个 provider，可并行）| L |
| 04_5-08 | E2E：Mattermost 主线 (slash 路由 + 多命令) + 4 个其他 IM provider 各自 smoke | L |

**总估算**：7-9 plans / 3-4 周

## 与 Phase 4 / Phase 5 的关系

- **Phase 4（IM 通知出站）**：先做。Phase 4.5 复用 Phase 4 的 IM Adapter 抽象。
- **Phase 5（IM 目录双向同步）**：先做。Phase 4.5 可用 Phase 5 已同步的 user/dept 信息（trigger 节点可识别发起人 user_id）。
- **Phase 4.5 实施时机**：在 Phase 4 + 5 之后插入，作为 4.5 子阶段（不影响 Phase 5 → Phase 6 主线，仅是补充）

## 已知风险

1. **Mattermost WebSocket 长连接**：bot 长在线 = 一个 worker 一直占用。可考虑 1 个 worker / 多个 workspace 共享或拆 bot 进程
2. **Webhook 签名验证**：每个 IM 签名机制不同（HMAC / RSA / proprietary），需 provider 各自实现
3. **Trigger 事件去重**：Mattermost 可能重复推送（at-least-once），workflow 不能重复触发同一消息
4. **多 workspace 一个 bot**：bot 账号是否 per-workspace 还是单租户共享 — 安全 vs 复杂度

## 下一步

- Phase 2 完成（仅剩 02-10 E2E gate）
- Phase 3 + Phase 4 完成（提供 IM Adapter 抽象）
- **`/gsd:discuss-phase 4.5`** 把本 OUTLINE 细化为 CONTEXT.md（16+ 决策板）
- `/gsd:plan-phase 4.5` 拆 7 plans
- `/gsd:execute-phase 4.5` 实施
