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
| **Trigger Node** | workflow **起点**（替代 Start，或并存）| 第一个节点 | provider(mattermost/feishu/...) + bot_id + 触发条件 (@mention / DM / channel scope) |
| **Reply Node** | 把当前 state 字段回帖到**原 IM 线程** | 任意位置（通常末端，可中段汇报）| provider + thread_id (来自 trigger 节点 state) + message template (Jinja2) |

**与 Notification 节点（Phase 4）的区别**：Notification 主动外推到任意指定收件人；Reply 仅在 trigger 起源的 thread 回帖（同一对话上下文）。

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
| 04_5-02 | Mattermost Provider 实现（WebSocket 入站 + REST 出站 + 签名验证） | L |
| 04_5-03 | Trigger 节点 → workflow 启动集成（thread_id / user_id / message 注入 state） | M |
| 04_5-04 | Reply 节点 → 出站回帖 + Jinja2 模板 + 长消息分段 | S-M |
| 04_5-05 | 前端：Trigger / Reply 节点 UI + 配置面板 | M |
| 04_5-06 | 飞书 / 企微 / 钉钉 / Slack Provider 实现（4 个 provider，可并行）| L |
| 04_5-07 | E2E：Mattermost 主线 + 4 个其他 IM provider 各自 smoke | L |

**总估算**：6-8 plans / 2-3 周

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
