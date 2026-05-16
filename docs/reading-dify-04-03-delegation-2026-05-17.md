# Dify 阅读笔记 — 委托机制 HITL-06（Plan 04-03）

> 日期: 2026-05-17
> 仓库: https://github.com/langgenius/dify (commit `e7e6fe88`, local clone `/Users/admin/ai/ref/dify/repo/`)
> Stars: ~141k

## 项目概述

Dify 是开源 LLM 应用开发平台（chat / agent / workflow）。本次专项阅读：在 Dify 的 HumanInput
（v1.10 加入的 "插入式表单等待用户填" 节点）模块中，验证「**Dify 是否支持审批委托 / 转交 / 重新分配**」。

## 技术栈

- Flask + SQLAlchemy（同步）
- Celery shared_task（任务异步化）
- 短 token form_token（数据库主键 token，不走 JWT）

## 架构要点

```
┌─────────────────────────────────────────────────────────────────┐
│ Dify HumanInput 模块                                             │
├─────────────────────────────────────────────────────────────────┤
│ Form (HumanInputFormRecord) ─── 1:1 ─── HumanInputFormRecipient  │
│         │                                                        │
│         │ (递归触发)                                              │
│         ▼                                                        │
│ HumanInputDelivery (邮件 / IM 投递任务)                          │
└─────────────────────────────────────────────────────────────────┘
```

**关键事实**：Dify 的 Form ↔ Recipient ↔ Delivery **三表设计中没有任何 "delegate / transfer / reassign /
forward" 字段或方法**。

### 搜索验证

```bash
# 全仓搜索 delegate / transfer (排除 file transfer)
grep -ni "delegate\|transfer\|reassign\|forward" \
    /Users/admin/ai/ref/dify/repo/api/services/human_input_service.py
# 0 行命中

# Workflow 核心目录
grep -rln "delegate" /Users/admin/ai/ref/dify/repo/api/core/workflow/
# 0 文件命中

# Models 目录
grep -ni "delegate" /Users/admin/ai/ref/dify/repo/api/models/human_input.py
# 0 行命中
```

**human_input_service.py 26 个 public 方法**全为单 actor 决策路径（`submit_form_by_token` /
`ensure_form_active` / `_ensure_not_submitted` / `_validate_submission` 等），**没有委托 / 转交 / 重分配
的任何方法或字段**。

### 单 actor 假设的设计后果

Dify 的 HumanInput 模型：
- `HumanInputFormRecord.token` — 单一 PK token（表单级别，非按 actor）
- `HumanInputFormRecipient` — 1:N 但 v1.10 内部 enforce N=1（only 1 recipient per form record）
- `RecipientType` — `email_address` / `user_id` / `iframe`，三种均为单接收人模型

因此 **Dify 没有「转交他人审批」概念**：表单要么被该 recipient 提交，要么超时 → 流程 TIMEOUT 终态。

## 可借鉴的设计模式

### 1. 不可借鉴：委托业务逻辑

Dify 完全没有委托相关代码 — **本项目原创设计**。无 Dify 模式可参考。

### 2. 部分借鉴：Token 一次性消费 → Phase 3 已落地

Dify `submit_form_by_token` 走 `_ensure_not_submitted` + UPDATE → 类似我们 Phase 3 已实现的
`HitlTokenStore.consume()` 原子 UPDATE。**Phase 4 委托复用 Phase 3 store API**：

- `store.consume(jti, ip, ua)` — 消费原 token（action 标记为 'delegate' 由 used_ip 区分）
- 实际本 plan 复用 `HitlActionService` 的 advisory_lock + consume 流程（不重写）

### 3. 借鉴：纯函数 + immutable payload

Dify `_validate_submission` 是纯函数（input → bool）— Phase 4 我们的 `create_delegate_token` 同样
保持纯函数特征（**只验证 + 返回 (new_tokens, depth)**），副作用（DB add_all + node_state.payload 更新）
集中在 service 边界。

## 与本项目的关系

| 比较点                       | Dify                          | 本项目 04-03                                                  |
| ---------------------------- | ----------------------------- | ------------------------------------------------------------- |
| 是否支持委托                 | ✗ 完全没有                    | ✓ HITL-06 原创设计                                            |
| 委托链深度                   | N/A                           | ≤ 3 层 (防责任稀释 + 防委托环)                                |
| 委托后 deadline_at           | N/A                           | **重置** = now + node_config.timeout_seconds (RESEARCH §三决策) |
| 原 token 处理                | N/A                           | 立即消费（store.consume + action='delegate' 标记）            |
| 被委托人 token               | N/A                           | 新签发 3 个（approve/return/reject），独立 jti                |
| 被委托人是否需主动接受       | N/A                           | **被动接受**（CONTEXT.md 决策 — 降低摩擦）                    |
| 防自委                       | N/A                           | ✓ to_email != from_user.email → 422                          |
| 防环                         | N/A                           | ✓ to_user 不可在 approvers 内 → 422                          |
| 跨 workspace                 | N/A                           | ✗ 必须同 workspace → 422 (recipient_not_found)               |
| 审计日志                     | N/A                           | audit_log action='hitl.delegate' + meta(from/to/depth/reason) |
| 结构化日志                   | N/A                           | logger.info('hitl.chain.delegate', extra={...}) 供 Phase 7 用 |

## 设计要点（实施时回查）

### 1. 委托深度计算

```python
chain = (node_state.payload or {}).get("approval_chain", {})
delegated = chain.get("delegated", {})
prev_depth = delegated.get(str(from_user.id), {}).get("depth", 0)
new_depth = prev_depth + 1
if new_depth > 3:
    raise DelegateError("depth_exceeded", "委托链已超 3 层（防责任稀释）")
```

### 2. 防环验证（双层）

```python
# 第一层：禁止自委托
if to_user.id == from_user.id:
    raise DelegateError("self_delegate", "不能委托给自己")

# 第二层：被委托人不能已在 approvers 内
approvers_ids = {UUID(a) for a in chain.get("approvers", [])}
if to_user.id in approvers_ids:
    raise DelegateError("circular", f"{to_email} 已在审批链内")
```

### 3. records 追加格式（CONTEXT.md §委托机制）

```python
{
    "actor_id": str(from_user.id),
    "actor_email": from_user.email,
    "action": "delegate",
    "reason": reason,
    "form_data": {},
    "ts": now.isoformat(),
    "ip": ip,
    "ua": ua,
    "delegate_to_id": str(to_user.id),
    "delegate_to_email": to_email,
    "depth": new_depth,
}
```

### 4. approval_chain.delegated 字典更新

```python
new_chain = {
    **chain,
    "delegated": {
        **(chain.get("delegated") or {}),
        str(from_user.id): {"to": str(to_user.id), "depth": new_depth},
    },
}
```

### 5. 错误码 → HTTP 状态码映射表

| DelegateError code      | HTTP 状态码 | 含义                          |
| ----------------------- | ----------- | ----------------------------- |
| `depth_exceeded`        | 409         | 委托链已超 3 层               |
| `self_delegate`         | 422         | 不能委托给自己                |
| `circular`              | 422         | 被委托人已在审批链内（防环）  |
| `recipient_not_found`   | 422         | 被委托人不存在或跨 workspace  |
| `cross_workspace`       | 422         | 显式跨租户（保留语义，可与 recipient_not_found 合一） |

> 实施时：`cross_workspace` 与 `recipient_not_found` 在 SQL JOIN 内同时过滤（WHERE workspace_id =
> :ws AND status = 'active'），统一返回 `recipient_not_found` 防租户存在性泄漏（Phase 3 03-08 已建立
> 的 "防泄漏存在性" 原则一致）。

### 6. JWT 签发复用 Phase 3 HitlTokenService.sign

委托产生的新 token 与既有 batch_create_tokens 路径一致 —
**不变量**：新 token 的 jti / aud='hitl' / iss='agent_builder' / expires_at = now + timeout_seconds。
不需要新签发器。

## 风险与守门

### Pitfall 防护

- **Pitfall 2 并发 race**：必须在 advisory_lock 内调 `create_delegate_token`（与 Phase 3
  submit_action 一致）— 否则两个并发委托请求可能同时消费 jti + 同时创建两批新 token。
- **Pitfall 3 Safe Links GET**：被委托人收到的新 token 同样走 `/hitl/page/<jti>` GET 不消费路径
  （HitlTokenService.decode 路径不变）。
- **Pitfall 13 跨租户碰撞**：`thread_id = "{workspace_id}:{instance_id}"` 不动；委托不变更
  instance_id，所以 thread_id 不变 — 锁 key 一致。

### 测试关键点

| 用例分类                                              | 数量 | 关键断言                                                                   |
| ----------------------------------------------------- | ---- | -------------------------------------------------------------------------- |
| Service 单元（真实 PG）                               | 9    | 3 token 创建 / deadline 重置 / records 追加 / chain.delegated / 5 错误码   |
| API 集成（真实 PG + Redis）                           | 5    | 201 happy / 409 depth / 422 self / audit_log 写入 / 原 token consumed     |

### CONTEXT.md vs RESEARCH.md 矛盾点

- **CONTEXT.md §委托机制**：「被委托人 token 继承：deadline_at 不变（不重置）」
- **RESEARCH.md §三**："修正决策：CONTEXT 描述更合理（降低委托摩擦），plan 内实现为 deadline_at 重置"

**实施决策**：**deadline_at 重置**（与 RESEARCH 一致，CONTEXT 已被 RESEARCH 修正）。
被委托人是新「上岗」，给完整 24h 窗口。

## License 注意

- Dify: AGPL-3.0；本项目: Apache-2.0
- 本 plan 完全原创设计 — **没有任何 Dify 代码可复制**（Dify 无委托特性）。
- 仅借鉴 token 一次性消费的设计模式（Phase 3 已做，与 Dify `submit_form_by_token` 思路一致）。

---

**Reading doc 已写完**，后续 plan 内所有 code commit 必须在此 doc commit 之后。
