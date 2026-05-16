# Phase 4: 审批链 + IM 通知 - Research

**Researched:** 2026-05-17
**Confidence:** HIGH（基于 Phase 3 已落地代码 + IM SDK 官方文档 + CLAUDE.md §2.7 Dify 参考映射）
**Scope:** HITL-02 / HITL-04 / HITL-06 / NOTI-02..07

> 本研究面向 PLAN，目的：把 04-CONTEXT.md 的决策板转化成「能直接拆 plan」的技术细节。

---

## 一、与 Phase 3 已落地代码的延续/扩展关系

Phase 4 不是从零开始，而是**强复用** Phase 3 的 8 个核心模块。下表是「Phase 4 必须扩展什么 / 不应该改什么」：

| Phase 3 模块（已存在） | 行数 | Phase 4 扩展方式 | 必须保持的不变量 |
|---|---:|---|---|
| `backend/app/agent_builder/workflow/hitl_token_store.py` | 209 | **+ `invalidate_chain(instance_id, except_jti)` 方法** — 全实例级失效 | `consume()` 原子 UPDATE 不变；`invalidate_siblings()` 行为不变（同 node_state 内） |
| `backend/app/agent_builder/workflow/hitl_payload.py` | 205 | **+ `compute_chain_advance(payload, action)` 纯函数**：计算下一个 approver / 是否终止；扩展 `build_initial_payload()` 接受 `chain_mode` + `approvers` | `compute_next_status` 单人模式分支保持；`append_record` 不动 |
| `backend/app/agent_builder/services/hitl_action_service.py` | 289 | **submit_action 内 6→7 分叉**：根据 chain_mode 走不同分支；并行模式 reject 时调 `invalidate_chain` | advisory_lock + jti consume + audit_log 不动 |
| `backend/app/agent_builder/services/hitl_service.py` | 124 | **batch_create_tokens 支持 list[actor_id]**（parallel 模式批量）；新增 `create_delegate_token()` | 已有单 actor 入口保留 |
| `backend/app/agent_builder/services/escalation_service.py` | 359 | **resolve_escalate_to 加 2 表达式分支**：`user:<uuid>` / `role:admin` | email 表达式分支不动；dept: 仍抛 NotImplementedError（Phase 5） |
| `backend/app/services/notification_service.py` | 258 | **+ `enqueue_hitl_card()` 通用 IM 入队入口** + `enqueue_hitl_multichannel()` fan-out | 已有 `enqueue_hitl_email` 不改签名（向后兼容） |
| `backend/app/jobs/email_jobs.py` | 294 | 不动，参考其 tenacity + 模板渲染骨架克隆出 `im_jobs.py` | — |
| `backend/app/agent_builder/workflow/nodes/hitl.py` | 169 | **interrupt_payload 加 chain_mode / approvers / current_idx 字段** | interrupt 单点不变；resume value 校验不变 |

**结论**：约 60% 工作量在「**扩展现有模块**」，40% 在「**新增 IM provider + 卡片模板 + delegation API**」。

---

## 二、审批链 4 模式语义形式化（HITL-02）

### 状态结构

`node_state.payload.approval_chain`（Phase 3 已预留字段，仅 `mode='single'` 用）：

```json
{
  "mode": "sequential" | "parallel_all" | "parallel_any" | "single",
  "approvers": ["uuid-A", "uuid-B", "uuid-C"],
  "current_idx": 0,                          // 仅 sequential 用
  "decisions": {                              // 仅 parallel_* 用
    "uuid-A": {"action": "approve", "ts": "..."},
    "uuid-B": null                            // null = 未决策
  },
  "delegated": {                              // 仅 HITL-06：被委托链
    "uuid-A": {"to": "uuid-X", "depth": 1}   // 深度 ≤ 3
  }
}
```

### 状态机（纯函数 `compute_chain_advance`）

```
sequential:
  approve  → if current_idx == len(approvers)-1: done  else current_idx+=1, 给下一人创建 token+通知
  return   → returned（终态，回到上游节点 — LangGraph Command(goto=...) 由调用方决定）
  reject   → rejected（终态，下游不创建任何 token）

parallel_all:
  approve  → 检查 decisions 全 approve → done
           → 否则 in_review，等其他 approver
  return / reject → 立即终止 + invalidate_chain（其他人 token 全失效 + 补通知）

parallel_any:
  approve  → 立即 done + invalidate_chain（其他人 token 全失效 + 补通知"已被 X 处理"）
  return / reject → 立即终止 + invalidate_chain（与 parallel_all 一致：拒绝即终止）

single (Phase 3 保留):
  与 Phase 3 完全一致，submit→in_review→approve→done
```

**关键纯函数签名（hitl_payload.py 新增）**：

```python
def compute_chain_advance(
    payload: dict,
    actor_id: UUID,
    action: Literal["approve", "return", "reject"],
) -> ChainAdvanceResult:
    """计算链推进结果（不修改 payload）"""

@dataclass(frozen=True)
class ChainAdvanceResult:
    new_status: NodeStatus              # in_review | done | rejected | returned
    new_payload: dict                    # immutable 新 payload
    next_approvers: list[UUID]           # 下一轮需要创建 token 的人（sequential 给 1 人）
    invalidate_others: bool              # parallel 模式 reject/any-approve 时 True
    supplement_notify: list[UUID]        # 需补"已终止"通知的 approver（parallel_* 终止时）
```

### Pitfall 防护

- **Pitfall 2 并发 race**：sequential 模式下两个 token 不可能同时活跃（一次只发给一人），advisory_lock 已防护；parallel_* 中 `invalidate_chain` 必须在 advisory_lock 内执行（同 Phase 3）
- **Pitfall 3 Safe Links GET**：链式生成的新 token 同样走 `/hitl/page/<jti>` GET 不消费路径
- **回归测试**：每个模式必有 1 个 E2E 用 OUTLOOK_SAFELINKS_BOT UA 扫 GET 验证 jti 未消费

---

## 三、委托机制 HITL-06 技术方案

### 表结构（不新建表，复用 records 数组）

委托记录存在 `node_state.payload.records`，类型 `delegate`：

```json
{
  "actor_id": "uuid-A",            // 发起委托的人
  "actor_email": "a@example.com",
  "action": "delegate",
  "reason": "我请假 3 天",
  "form_data": {},
  "ts": "2026-05-17T10:00Z",
  "ip": "1.2.3.4",
  "ua": "...",
  "delegate_to_id": "uuid-X",      // 被委托人
  "delegate_to_email": "x@example.com",
  "depth": 1                       // 委托链深度（≤ 3）
}
```

### API 入口（新增）

```
POST /hitl/action/<jwt>?op=delegate
Body: {to_email: "x@example.com", reason: "..."}

校验：
- 当前 actor 必须是 approval_chain.approvers[current_idx]（sequential）
  或 approval_chain.approvers 内（parallel）
- to_email 必须在同 workspace 内
- depth = sum(prev.depth) + 1 ≤ 3 → 否则 409 "委托链超 3 层"
- 不可委托给自己 / 当前已在审批链上的人 → 422

副作用（事务内）：
1. 原 token consume (action='delegate' 写入 used_at + used_ip + used_ua)
2. 给被委托人创建新 token（继承 deadline_at 不重置，jti 新生成）
3. 写 records 加 delegate 类型
4. 更新 payload.approval_chain.delegated 字典
5. 发新通知给被委托人（沿用节点 config.notify_channels）
6. audit_log action='hitl.delegate'
```

### 与超时升级的优先级

- **委托后**：原 actor token 失效；deadline_at **不重置**（CONTEXT.md §委托机制：被委托人继承原 deadline 不重置） — 与 CONTEXT 描述「被委托人有完整 24/48/72h」矛盾
- **修正决策**：CONTEXT 描述更合理（降低委托摩擦），plan 内实现为 deadline_at 重置为 (now + node_config.timeout_seconds)
- **理由**：被委托人是新「上岗」，给完整窗口；与升级（系统强制换人）不同，委托是 actor 主动转交

> **决策板新增**：plan-checker 必须验证 04-02 plan 实现了 deadline_at 重置（不是继承） — 与 CONTEXT 描述一致。

---

## 四、IM Provider 抽象设计

### Protocol（Python typing.Protocol — 走 CLAUDE.md python/patterns.md 鸭子类型）

```python
# backend/app/agent_builder/notification/providers/base.py
from typing import Protocol, runtime_checkable

@runtime_checkable
class IMProvider(Protocol):
    """IM 出站投递接口（Phase 4：仅出站；Phase 4.5 加 subscribe / verify_webhook_signature）"""

    name: str  # "feishu" / "wecom" / "dingtalk" / "slack" / "mattermost"

    async def send_hitl_card(
        self,
        *,
        recipient: str,           # IM user_id（不是 email）
        flow_title: str,
        node_title: str,
        applicant_name: str,
        deadline_at: str,
        description: str,
        deeplinks: list[dict],    # [{"action": "approve", "url": "https://..."}]
    ) -> dict:
        """投递 HITL 决策卡片，返回 {message_id, raw_response}"""

    async def update_card(
        self,
        *,
        message_id: str,
        new_content: dict,        # 各家自定义格式（"已被 X 处理" 文本）
    ) -> None:
        """更新已发送卡片为只读（Phase 4：飞书/Slack/Mattermost 支持，企微/钉钉无此 API 时跳过）"""

    async def send_supplement_text(
        self,
        *,
        recipient: str,
        text: str,
    ) -> None:
        """对不支持卡片 update 的 IM（企微/钉钉）发送补充消息，告知已被处理"""
```

### Factory + Registry（启动时注册到 dict，由配置驱动）

```python
# backend/app/agent_builder/notification/providers/__init__.py
_PROVIDERS: dict[str, IMProvider] = {}

def register_provider(name: str, provider: IMProvider) -> None: ...
def get_provider(name: str) -> IMProvider: ...

# FastAPI lifespan 时调（不在 dependency，避免每请求初始化 SDK client）
```

### 凭据管理

- 每 workspace 一组 IM 凭据（飞书 app_id/app_secret / 企微 corp_id+secret / 钉钉 / Slack / Mattermost）
- 存表 `workspace_im_credentials`（新建）：`(workspace_id, provider, credentials JSONB)`
- Phase 4 不做凭据管理 UI（v1 admin 手动 psql 写入或 .env）
- HMAC 加密存储：用 `HMAC_SECRET` 派生密钥 AES-GCM 加密 credentials 字段
- **Phase 4 简化**：先支持 .env 配置单租户全局 IM 凭据（`FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `WECOM_CORP_ID` / `WECOM_AGENT_ID` / `WECOM_SECRET` / `DINGTALK_APP_KEY` / `DINGTALK_APP_SECRET` / `SLACK_BOT_TOKEN` / `MATTERMOST_URL` / `MATTERMOST_TOKEN`），多 workspace 共享；workspace 级凭据表留 Phase 6 实现

### Provider 实现要点（各家 SDK 速查）

| Provider | SDK + 版本（CLAUDE.md §3 锁定） | 卡片格式 | update 支持 | 关键 API |
|---|---|---|---|---|
| **feishu** | `lark-oapi==1.6.5` | Interactive Card 2.0（columns + button block） | ✓ `messages/v1/{message_id}/patch` | `client.im.v1.message.create()` |
| **wecom** | `wechatpy==1.8.18`（停更，需 spike） | Template Card text_notice + button_list | ✗ 静态卡片 | `WeChatClient.message.send()` — 可能 fallback 到 Bot Webhook |
| **dingtalk** | `dingtalk-stream==0.24.3` | ActionCard btnOrientation=0 | ✗ | `DingTalkStreamClient.send_message_to_user()` |
| **slack** | `slack-bolt==1.28.0` | Block Kit (section + actions block) | ✓ `chat.update` | `app.client.chat_postMessage(blocks=...)` |
| **mattermost** | 原生 HTTP `POST /api/v4/posts` + httpx | Markdown attachment + actions array | ✓ `posts/{post_id}/patch` | 直接 httpx，不用专门 SDK |

### 已知风险（spike 优先级）

1. **企微 wechatpy 停更**：Plan 04-04 第一个 task 必须先 spike templated card API 在 2026 年是否还能用；若失败 fallback 走 Bot Webhook（个人微信群机器人 webhook URL）。spike 在 plan 内单独算一个 30min task
2. **lark-oapi 1.6.5 锁定**：1.6.0-1.6.3 已 yanked，必须 pin 死；Provider 实现时 import 前先 `assert lark.__version__ == "1.6.5"`（启动校验）
3. **mattermost 出站简单**：复用 Phase 4.5 OUTLINE 中 hr/offboarding-flow 的 mattermost driver 借鉴，但 Phase 4 只出站 → 直接 httpx 一行调用够用

---

## 五、IM Notification Node（NOTI-08 多通道并发投递）

### 节点新增 vs 复用？

**决策：复用现有 `notification` 节点 + 扩展 schema**，不新建 IM 专属节点。

理由：
1. NOTI-08 决策板：「节点 `config.notify_channels` 数组」— 是单个节点多通道，不是多个节点
2. 维护成本低：DSL 一致性
3. Phase 3 NotificationNodeExecutor 已用 BaseNodeExecutor 抽象层，加 channels 分发逻辑成本小

### Schema 扩展

`notification_schema.py`：
```python
"channels": {
    "type": "array",
    "items": {"enum": ["email", "feishu", "wecom", "dingtalk", "slack", "mattermost", "webhook"]},
    "minItems": 1,
    "default": ["email"]
}
```

HITL 节点 `hitl_schema.py` 同样加 `notify_channels`（与 notification 节点字段名一致便于复用渲染）。

### NotificationService 新增方法

```python
# backend/app/services/notification_service.py 新增
async def enqueue_hitl_multichannel(
    self,
    *,
    workspace_id, instance_id, node_state_id, recipient_email,
    recipient_im_user_id: dict[str, str] | None,  # {"feishu": "ou_xxx", "wecom": "..."}
    tokens, form_schema, deadline_at, ...,
    channels: list[str],  # ["email", "feishu", "wecom"]
    reminder_round: int = 0,
) -> list[Notification]:
    """fan-out 入队：每个 channel 写 1 行 notifications + enqueue 1 个 job"""
```

### IM user_id 解析（Phase 4 简化）

Phase 4 用户在 DSL 中配置 `assignees: ["user@email.com"]`，Phase 4 通过 `users.im_bindings` JSON 字段（Phase 1 已有列）查 `email → im_user_id` 映射：

```sql
-- users.im_bindings JSONB 示例
{"feishu": "ou_abc123", "wecom": "WuPing", "slack": "U12345"}
```

- 用户首次注册时 `im_bindings = {}`（admin 手动配，Phase 4 不做绑定 UI）
- 找不到 binding → 该 channel 跳过 + 日志 warn（不阻断其他 channel）
- **Phase 5** 做 IM Directory 双向同步，自动填充 `im_bindings`

---

## 六、多通道 sibling 失效

### 决策

- **Phase 3** `invalidate_siblings(node_state_id)` 锁定到「同 node_state」 — Phase 4 一个 node_state 可能对应多个 user × 多个 channel 的 token
- **关键不变量**：jti 是 PRIMARY KEY，每用户每 action 一行 token，多 channel 共享同一组 jti（通知卡片里 4 个按钮深链 jti 相同）
- 所以 `invalidate_siblings` 行为正确：同 node_state_id 所有 jti 全失效，自动覆盖多通道场景

### 新增：`invalidate_chain(instance_id, except_jti)`

```python
# hitl_token_store.py 新增
async def invalidate_chain(
    self,
    instance_id: UUID,
    except_jti: UUID,
) -> list[UUID]:
    """实例级失效（parallel_* 模式 reject 或 any-approve 时调）

    与 invalidate_siblings 区别：
    - invalidate_siblings 锁定到 node_state_id（单节点内）
    - invalidate_chain 跨整个 instance（所有未消费 token 全部失效）

    Returns: 被失效的 jti 列表（用于发"已终止"补通知）
    """
    stmt = (
        update(HitlToken)
        .where(
            HitlToken.instance_id == instance_id,
            HitlToken.jti != except_jti,
            HitlToken.used_at.is_(None),
        )
        .values(
            used_at=datetime.now(timezone.utc),
            used_ip="system:chain-invalidate",
        )
        .returning(HitlToken.jti, HitlToken.actor_id)
    )
    # Redis pipeline 一次性失效
    ...
    return invalidated_jtis_with_actors
```

> **不变量保护**：必须在 advisory_lock 内调（Pitfall 2 防护），与 `invalidate_siblings` 一致。

---

## 七、超时升级表达式解析（HITL-04）

### 现有代码（escalation_service.py:64-112）

仅支持「email 字符串 + fallback workspace admin」。

### Phase 4 扩展

`resolve_escalate_to` 加分支（用 strategy pattern 或 if/elif chain，根据 prefix 路由）：

```python
async def resolve_escalate_to(
    self, *, node_config, workspace_id,
) -> list[str] | None:    # 改：返回 list[email]（role:admin 可能匹配多人）
    if not node_config:
        return None
    expr = node_config.get("escalate_to")
    if not expr:
        return None

    # 1. email
    if isinstance(expr, str) and "@" in expr and ":" not in expr:
        return [expr]

    # 2. user:<uuid>
    if expr.startswith("user:"):
        uid = UUID(expr[5:])
        email = await self._get_user_email(uid, workspace_id)
        return [email] if email else None

    # 3. role:<code>
    if expr.startswith("role:"):
        role_code = expr[5:]
        emails = await self._get_emails_by_role(role_code, workspace_id)
        return emails or None

    # 4. dept:<name> → Phase 5
    if expr.startswith("dept:"):
        raise NotImplementedError("dept: 表达式将于 Phase 5（IM 目录双向同步）实现")

    # 5. fallback workspace admin
    return await self._fallback_workspace_admin_emails(workspace_id)
```

**`role:admin` 解析**：复用现有 `_fallback_workspace_admin_email` 的 SQL，扩展为返回 list 不限 1 个。

### perform_escalation 调整

- `escalate_email` 字段改为 `escalate_emails: list[str]`
- 给每个 email 发一封升级邮件（reminder_round=3）
- audit_log meta 字段加 `escalate_count: len(emails)`
- 测试覆盖：role:admin 在 workspace 有 3 个 admin 时发 3 封

---

## 八、Validation Architecture

> 本节按 CLAUDE.md §2.2 三层测试 + ROADMAP Phase 4 6 条 success criteria 设计。

### 三层测试矩阵

| 层 | 测试对象 | 工具 | 必测点 |
|---|---|---|---|
| **单元** | hitl_payload.compute_chain_advance（4 mode × 3 action = 12 用例）；resolve_escalate_to（4 表达式 × 命中/未命中 = 8 用例）；IMProvider 实现各 SDK 调用 mock 5 用例 / provider | pytest | 纯函数 immutable / 边界 / 异常路径 |
| **集成** | HitlActionService 4 chain mode × DB + Redis 真实 fixture（不 mock）；NotificationService.enqueue_hitl_multichannel 写 5 行 notifications；invalidate_chain 跨 instance 失效；delegate API 深度 3 拒 4 层 | pytest + testcontainers-postgres | 真实 DB advisory_lock / UNIQUE 约束 / Redis pipeline |
| **E2E** | 见下表 ROADMAP 6 条 success criteria 全覆盖 | Playwright via webapp-testing skill | 浏览器视角端到端 + Safe Links bot UA 回归 |

### ROADMAP Phase 4 → E2E spec 映射

| ROADMAP # | 验收准则 | E2E spec 文件 | 关键断言 |
|---|---|---|---|
| 1 | 顺序会签：A 同意后 B 才收到通知；A 拒绝后 B 不收到通知，流程终止 | `e2e/04_chain_sequential.spec.ts` | A approve → B 邮件出现；A reject → B 邮件不出现 + instance.status=rejected |
| 2 | 并行全员：A 拒绝后其余 token 立即失效，流程终止 | `e2e/04_chain_parallel_all.spec.ts` | A reject → B token GET 看到 410；DB hitl_tokens.used_at 全部 NOT NULL |
| 3 | 或签：A 同意后其余 token 立即失效，流程推进 | `e2e/04_chain_parallel_any.spec.ts` | A approve → B token 410；instance 推进到下一节点 |
| 4 | 超时催办 + 升级策略（指派给指定升级人） | `e2e/04_escalation.spec.ts` | 时间快进（fake clock 或测试 fixture timeout=10s）→ mailhog 收升级邮件给 role:admin 用户 |
| 5 | 5 家 IM 卡片投递成功，按钮跳 Web 决策页 | `e2e/04_im_card_delivery.spec.ts` | 5 个 channels 各发一张卡片（mock IM API 验请求 payload + URL 含 jti）|
| 6 | 委托功能 + 审计日志 | `e2e/04_delegation.spec.ts` | POST /hitl/action/<jwt>?op=delegate → 新 token 发被委托人 + audit_log 'hitl.delegate' 存在 + 深度 3 拒 4 层 |

### Safe Links Bot 回归（Pitfall 3 P0）

每个 chain mode E2E 必加 1 个 step：
```typescript
await page.setExtraHTTPHeaders({"User-Agent": OUTLOOK_SAFELINKS_BOT_UA});
await page.goto(deeplink_url);  // GET /hitl/page/<jti>
// 断言 DB hitl_tokens.used_at IS NULL（GET 未消费）
```

### IM 卡片投递 mock 策略

E2E 测试 IM 卡片不走真实飞书/企微/钉钉 API（成本 + 凭据需求）：
- **Mock 方式**：FastAPI 测试启动时注入 `MockIMProvider` 替代真实 provider（pytest fixture）
- **断言**：mock 记录请求 payload，验证：
  1. recipient 字段（IM user_id 不是 email）
  2. card body 含 4 个按钮（同意/退回/拒绝/详情）
  3. 每个按钮 URL 含合法 jti
  4. URL 指向 `PUBLIC_BASE_URL/hitl/page/<jti>`

---

## 九、CLAUDE.md §2.7 Dify 参考映射（每个 plan 必读模块）

> 关键：Dify **没有审批链** — 仅单 actor。本 phase 大量 plan 的 reading doc 要写「Dify 无对应实现，本项目独立设计」。但仍要读 Dify 相关模块对比设计权衡。

| Plan 类别 | 必读 Dify 后端模块 | 必读 Dify 前端 / 其他 | Reading doc 要写的对比点 |
|---|---|---|---|
| 04-01 chain schema 扩展（payload + DB） | `api/models/human_input.py`（确认 Dify 没有 chain 字段，验证「我们独立设计」论点） | — | Dify 单 actor 表 vs 我们 chain 字段；为什么不需要单独 chain 表 |
| 04-02 chain executor + delegation | `api/core/workflow/human_input_policy.py` + `api/services/human_input_service.py` | `web/app/components/workflow/nodes/human-input/`（看 Dify 是否有 chain UI hint，应该没有）| Dify policy 模式 vs 我们 compute_chain_advance 纯函数 |
| 04-03 escalation 表达式扩展 | `api/tasks/human_input_timeout_tasks.py` | — | Dify 没有「升级到上级」逻辑（仅 status=TIMEOUT）；我们独创 actor 替换 + 多 email 通知 |
| 04-04 IMProvider 抽象 | — Dify 无 IM bindings | hr/offboarding-flow Mattermost driver | 借鉴 hr 项目 Provider 接口设计；不复制代码 |
| 04-05..09 各 IM provider | — | 各 IM SDK 官方 quickstart | SDK 官方推荐用法（不抄 Dify） |
| 04-10 multichannel + fanout | `api/tasks/mail_human_input_delivery_task.py` | — | Dify 单 channel email task vs 我们 fan-out 多 channel |
| 04-11 E2E gate | `api/tests/test_containers_integration_tests/tasks/test_mail_human_input_delivery_task.py` | hr/offboarding-flow E2E（如有） | testcontainers 模式参考；Playwright 不在 Dify 范围 |

**Reading doc 命名规范**：`docs/reading-dify-04-XX-{slug}-2026-05-17.md` 或 `docs/reading-im-sdk-04-XX-{provider}-2026-05-17.md`（IM provider 走 SDK doc 不走 Dify）。

---

## 十、Plan 拓扑（拆 plan 的输入）

根据用户 `execution_constraints` 的 8-12 plans / 5-7 waves 设计：

### Wave 1（基础设施 — 必须串行先做）

| Plan | 内容 | 关键文件 | 依赖 |
|---|---|---|---|
| **04-01** | DB schema 扩展 + payload 类型升级 | Alembic 0004（如需新建 `workspace_im_credentials` 表则在此；否则仅 ORM 注释更新）；hitl_payload.py 加 ChainAdvanceResult dataclass + compute_chain_advance | — |
| **04-02** | hitl_token_store 加 invalidate_chain + ORM 索引补充 | hitl_token_store.py + 新增 index `(instance_id, used_at)` | 04-01 |

### Wave 2（chain executor + delegation API — 可并行）

| Plan | 内容 | 关键文件 | 依赖 |
|---|---|---|---|
| **04-03** | HitlActionService chain 分支扩展（4 mode 完整支持） | hitl_action_service.py + 单元 + 集成测试 | 04-01, 04-02 |
| **04-04** | 委托 API 端点 + service 方法 + audit_log | api/hitl.py + hitl_service.py（新增 create_delegate_token）+ 集成测试 | 04-01, 04-02 |
| **04-05** | EscalationService 4 表达式扩展（email/user:/role:/dept: NotImpl） | escalation_service.py + 单元 + 集成测试 | 04-01 |

### Wave 3（IM Provider 抽象 — 必须先做）

| Plan | 内容 | 关键文件 | 依赖 |
|---|---|---|---|
| **04-06** | IMProvider Protocol + Factory + 凭据 .env 加载 + im_jobs.py（克隆 email_jobs.py 模板） | backend/app/agent_builder/notification/providers/{base.py,__init__.py}; backend/app/jobs/im_jobs.py | — |

### Wave 4（5 个 Provider 并发开发 — 4 plans 并行）

| Plan | 内容 | 关键文件 | 依赖 |
|---|---|---|---|
| **04-07** | Feishu Provider（lark-oapi 1.6.5）+ 卡片模板 + 单元（mock SDK） | providers/feishu.py + 模板 | 04-06 |
| **04-08** | WeCom Provider（wechatpy 1.8.18 + 备选 Bot webhook fallback）+ 卡片 + 单元 | providers/wecom.py | 04-06 |
| **04-09** | DingTalk Provider（dingtalk-stream 0.24.3）+ ActionCard + 单元 | providers/dingtalk.py | 04-06 |
| **04-10** | Slack + Mattermost Provider（slack-bolt 1.28.0；mattermost 用 httpx）+ Block Kit / Markdown 卡片 + 单元 | providers/slack.py + providers/mattermost.py | 04-06 |

> 5 个 provider 合并为 4 plans：Slack 和 Mattermost 工作量都偏小，合一个 plan；其他 3 家各一个 plan（避开 token / API 差异点）。

### Wave 5（多通道 fan-out + 节点 schema 扩展）

| Plan | 内容 | 关键文件 | 依赖 |
|---|---|---|---|
| **04-11** | NotificationService.enqueue_hitl_multichannel 多通道 fan-out + notification 节点 schema 加 channels + HITL schema 加 notify_channels + 节点 executor 扩展 | notification_service.py + node_schemas/{hitl_schema, notification_schema}.py + nodes/notification.py | 04-07..04-10 任一（实测可 partial：先支持已完成 provider） |

### Wave 6（HITL 节点 executor + interrupt_payload chain 字段）

| Plan | 内容 | 关键文件 | 依赖 |
|---|---|---|---|
| **04-12** | HITLNodeExecutor 扩展 interrupt_payload 加 chain 字段；ExecutionEngine 集成 compute_chain_advance；ainvoke(Command(resume)) 后链推进逻辑 | nodes/hitl.py + execution_engine.py（若有）| 04-03 |

### Wave 7（E2E gate）

| Plan | 内容 | 关键文件 | 依赖 |
|---|---|---|---|
| **04-13** | 6 个 Playwright spec 覆盖 ROADMAP 全 6 条 + Safe Links bot 回归 + MockIMProvider fixture | e2e/04_chain_sequential.spec.ts 等 6 个 spec + e2e/helpers/im-mock.ts + e2e/helpers/chain-builder.ts | 04-11, 04-12 |

### Plan 总数：13 个 plans（4 个并发的 Provider plans 计入 4，1 chain + 1 token + 1 chain-exec + 1 delegate + 1 escalation + 1 provider abstraction + 1 multichannel + 1 hitl node + 1 e2e gate = 9 顺序 + 4 并行 = 13 plans / 7 waves）

> **实际拆分时 plan-checker 可合并** 04-01 + 04-02（都是基础设施）为 1 plan，最终 11-12 plans 落在用户期望范围。

---

## 十一、关键风险登记

| 风险 | 严重度 | 缓解 |
|---|---|---|
| wechatpy 停更，templated card API 可能失效 | HIGH | 04-08 plan 第一个 task 必须先 30min spike；失败 fallback Bot Webhook（损失 update_card 能力） |
| Mattermost 出站简单但格式跨版本差异 | LOW | 04-10 用 httpx 直 API，不依赖 SDK |
| 测试 IM 卡片需要真实凭据 | MEDIUM | 单元 / 集成全部 mock SDK；E2E 用 MockIMProvider fixture；CI 不调真实 IM API |
| chain 推进 + ainvoke(Command(resume)) 联动复杂 | HIGH | 04-12 plan 拆 2 个 task：先纯函数 compute_chain_advance 测试，再集成 ExecutionEngine + LangGraph resume |
| Pitfall 1 checkpoint 膨胀（chain payload 增大） | MEDIUM | payload 仅存 UUID 字符串数组，估算 ≤ 2KB（10 人 chain 也 < 4KB 阈值） |
| Pitfall 2 invalidate_chain 在 advisory_lock 外执行 | HIGH | plan-checker 必须 verify 04-03 测试代码确实在 lock 内调 |
| Pitfall 3 链式新 token 也走 GET 不消费 | HIGH | 每 chain mode E2E spec 必含 Safe Links bot 回归 step |
| dept: 表达式漏写 NotImplementedError | LOW | 04-05 单元测试明确断言 raise |

---

## 十二、推荐 commit 节奏

每个 plan 内：
1. **Task 0 commit**：reading doc（CLAUDE.md §2.7 硬性 gate）
2. **Task 1 commit**：核心实现 + 单元测试
3. **Task 2 commit**：集成测试（真实 PG + Redis）
4. （可选）**Task 3 commit**：节点 executor 集成 / API 端点
5. **SUMMARY.md** 写完即关 plan

CI 校验脚本（如已配）：检查 plan 内第一个 feat: commit 之前必有 docs: reading-dify-* commit。

---

## 十三、与 Phase 4.5 / Phase 5 的边界

- **Phase 4 不做**：入站 webhook / Slash 分发（→ Phase 4.5）；IM 目录双向同步（→ Phase 5）；workspace 级 IM 凭据 UI（→ Phase 6）
- **Phase 4 留接口**：`IMProvider` Protocol 已为 Phase 4.5 预留 `subscribe()` / `verify_webhook_signature()`（Phase 4 不实现，Phase 4.5 加方法）
- **Phase 4 留 hook**：`EscalationService.resolve_escalate_to` 已为 Phase 5 dept: 表达式留 `NotImplementedError` 分支

---

## RESEARCH COMPLETE

**Confidence:** HIGH
**Files written:** `.planning/phases/04-approval-chain-im/04-RESEARCH.md`
**Next:** plan-phase 进入 step 8 — spawn gsd-planner with this research as input.
