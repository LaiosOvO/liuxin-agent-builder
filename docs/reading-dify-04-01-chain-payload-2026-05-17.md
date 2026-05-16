# Dify 阅读笔记 — human_input.py（Phase 4-01 审批链 payload + invalidate_chain）

> 日期: 2026-05-17
> 仓库: https://github.com/langgenius/dify （local clone /Users/admin/ai/ref/dify/repo/）
> Stars: ~141k
> Plan: 04-01 — 审批链 chain payload + token_store.invalidate_chain + Alembic 0005 partial index

---

## 1. 项目概述（一句话）

Dify 是国内最成熟的开源 LLM Workflow / Agent 编排平台，**Human Input 节点仅支持单 actor 决策**，没有审批链（approval chain）概念。

---

## 2. 技术栈

- **ORM**: SQLAlchemy 2.x `Mapped[]` + `mapped_column()` 风格
- **PK 策略**: `StringUUID` 自定义类型（字符串存 UUID） + `DefaultFieldsMixin` 提供 `id/created_at/updated_at`
- **状态机**: `HumanInputFormStatus` 用 Python `StrEnum`（waiting / submitted / expired 三态终态）
- **三层 ORM 拆分**: `HumanInputForm`（表单本体）+ `HumanInputDelivery`（投递方式）+ `HumanInputFormRecipient`（收件人）
- **关系**: `relationship(lazy="raise")` 强制显式预加载（避免 N+1）
- **Token 字段**: 32 字符长度（base62 ~180 bit 熵）

---

## 3. 架构要点（核心架构模式）

### Dify 单 actor 表 vs 我们 chain 字段（对比简图）

```
Dify 模式（单 actor）:
  HumanInputForm
    ├─ status: waiting / submitted / expired   (一行 = 一个决策 lifecycle)
    ├─ selected_action_id (单选)
    ├─ submitted_data (单提交)
    ├─ submission_user_id (单决策人)
    └─ completed_by_recipient_id (单收件人)
  ↓ 1:N
  HumanInputDelivery (投递方式：email / console / standalone_web_app）
  ↓ 1:N
  HumanInputFormRecipient (收件人 = email/账号)

  → 单 actor 提交后 form_id 置 submitted，整个 form 终结。
  → 多收件人是「谁先点谁拿走」的抢锁语义，不是「N 人协同决策」。

我们 Phase 4 chain 模式（多 actor 协同）:
  node_state.payload.approval_chain (JSONB 内嵌字段)
    ├─ mode: single | sequential | parallel_all | parallel_any
    ├─ approvers: [uuid-A, uuid-B, uuid-C]
    ├─ current_idx: 0   (仅 sequential 用)
    ├─ decisions: {uuid-A: {action, ts}, uuid-B: None}  (仅 parallel_* 用)
    └─ delegated: {uuid-A: {to: uuid-X, depth: 1}}  (HITL-06 委托)

  → 同一节点同时存在 N 个未消费 token（parallel_all/any）
  → invalidate_chain(instance_id) 是「parallel_* reject / parallel_any approve」
     时的核心副作用：跨 node_state 全实例失效未消费 token
```

### 关键差异：Dify 没有「跨实例失效」的概念

Dify 一个 `HumanInputForm` 行就是一个独立的 form lifecycle，多收件人共享一个 `selected_action_id`/`submitted_data` 字段 — 第一个提交者获胜，剩余收件人后续提交会被 `FormSubmittedError`（HTTP 412）拒绝。没有「主动失效未消费 token」逻辑。

我们的 `invalidate_chain` 主动失效是为了：
1. 给被失效的 actor 发**补通知**（"已被 X 处理"，UX 友好）
2. 让被失效 token 的 POST /hitl/action 返回 410（流程已终止）而不是 409（重复提交）—— 语义更精确
3. 释放数据库行（`used_at` NOT NULL）和 Redis key，加速后续 `is_consumed` 查询

---

## 4. 可借鉴的设计模式

### 4.1 三层 ORM 拆分模式（仅参考结构，**不复用 Dify 表**）

| Dify 表 | 字段语义 | 我们的对应 |
|---|---|---|
| `human_input_forms` | form 本体 + 提交记录字段（submitted_at / submission_user_id） | `node_states.payload.records` 数组（JSONB） |
| `human_input_form_deliveries` | 投递方式（email/console/webapp） | `notifications.channel` 字段（email/feishu/wecom/...） |
| `human_input_form_recipients` | 多收件人（同 form 多个 email） | `hitl_tokens` 表（每 actor × action 一行） |

**借鉴点**: Dify 三表拆分使「投递」「身份」「业务状态」职责清晰；我们保持类似的拆分但**单层化**（不需要新建表 — 复用 `hitl_tokens` 通过 `(instance_id, actor_id, action)` 隐含的关系）。

### 4.2 immutable payload 模式（dataclass frozen + Literal）

虽然 Dify ORM 字段是 mutable（SQLAlchemy 风格），但其 Pydantic `BaseModel`（如 `EmailMemberRecipientPayload`）使用 `Annotated + Field(discriminator="TYPE")` 走类型识别 union。

**借鉴**: 我们的 `ChainAdvanceResult` 用 Python stdlib `@dataclass(frozen=True)` 替代 Pydantic（避免 v1 引入 Pydantic 校验链）：
- `frozen=True` 保证返回值不可变（与 CLAUDE.md immutability 一致）
- `field(default_factory=list)` 防共享 mutable 默认值陷阱
- 单源类型定义 + `Literal["single", "sequential", ...]` 防字符串 typo

### 4.3 状态枚举 Literal vs Enum

Dify 用 `StrEnum`（`HumanInputFormStatus.WAITING`），我们 Phase 3 已沉淀用 `Literal["pending", "waiting_human", ...]`。

**借鉴边界**: Literal 更轻量但缺少 introspection；项目内 hitl_payload.py 已采用 Literal 风格，保持一致。`ChainMode` 沿用 Literal。

### 4.4 advisory_lock 在数据访问层外部

Dify 的 `FormSubmittedError(code=412)` 是**应用层抢锁**（依赖 status 字段一致性 + Session 行锁）。

**借鉴**: 我们 Phase 3 03-06 已用 `pg_advisory_xact_lock(hash(thread_id))` 做并发隔离 — Phase 4 `invalidate_chain` **必须在外层 advisory_lock 内**调用（Pitfall 2 防护），这点 plan 已明示。

---

## 5. 与本项目的关系

### chain 字段是独立设计（不抄 Dify）

**理由**:
1. **HITL-02 是本项目独创需求**（多人审批链 4 模式）— Dify 无对应实现，借鉴不上
2. **Dify 是 AGPL-3.0**，本项目是 Apache-2.0 — 即使 Dify 有 chain 也不能复用代码
3. **chain payload 设计哲学不同**：Dify「一 form 一 actor」+ status 字段；我们「一节点 N actor」+ JSONB 内嵌 approval_chain

### 与 Phase 3 已落地代码的延续

- **复用** `hitl_payload.build_initial_payload` + `append_record`（不破坏 Phase 3 single 模式行为）
- **新增** `compute_chain_advance` 纯函数（4 mode × 3 action = 12 状态机分支）
- **新增** `ChainAdvanceResult` 不可变数据类（frozen dataclass + factory default list）
- **复用** `HitlTokenStore.invalidate_siblings` 模式（同 SQL + Redis pipeline 风格），新增 `invalidate_chain`（差别：scope 从 node_state_id 升到 instance_id）
- **复用** Alembic migration 0003 partial index 模式（`postgresql_where` 子句），新增 0005 `(instance_id, used_at)` 加速 invalidate_chain 扫描

---

## 6. ChainAdvanceResult dataclass 设计依据

### 为什么用 `@dataclass(frozen=True)` 而非 Pydantic / TypedDict / NamedTuple？

| 选项 | 优 | 劣 | 决策 |
|---|---|---|---|
| **frozen dataclass** | stdlib / 类型友好 / `__eq__`自动 / immutable | 无运行时 validation | ✓ 采用（不需要 validation 因为是返回值非输入） |
| Pydantic v2 BaseModel | runtime validation | 引入依赖 + 序列化开销 | ✗ 不需要 |
| TypedDict | 零开销 | 无 frozen 保证 + 无 default_factory | ✗ 缺 frozen |
| NamedTuple | immutable + tuple-like | 无 default_factory（NamedTuple 限制） | ✗ 缺 default_factory |

### 字段设计

```python
@dataclass(frozen=True)
class ChainAdvanceResult:
    new_status: NodeStatus               # in_review | done | rejected | returned
    new_payload: dict[str, Any]           # immutable 新 payload，调用方写入
    next_approvers: list[UUID] = field(default_factory=list)
    invalidate_others: bool = False
    supplement_notify: list[UUID] = field(default_factory=list)
```

- `new_status`: 沿用 Phase 3 `NodeStatus` Literal
- `new_payload`: dict copy（用 `{**payload, ...}` + 新 list/dict），保证调用前后入参 `payload` deep equal
- `next_approvers`: sequential approve 时返回下一个 [UUID]；parallel_* 始终空 list
- `invalidate_others`: True 时调用方需调 `HitlTokenStore.invalidate_chain(instance_id, except_jti)`
- `supplement_notify`: parallel_* reject/any approve 时返回**剩余未决策 actor**列表，调用方负责发"已终止/已被处理"补通知

### default_factory 防共享陷阱

```python
# ❌ 错误：所有实例共享同一 list 引用
next_approvers: list[UUID] = []
# ✓ 正确：每次实例化都新建 list
next_approvers: list[UUID] = field(default_factory=list)
```

### Literal vs Enum 一致性

`ChainMode = Literal["single", "sequential", "parallel_all", "parallel_any"]` 与 Phase 3 `NodeStatus` / `Action` Literal 风格一致，避免类型族混杂。

---

## 7. 阅读检查清单

- [x] 读 `/Users/admin/ai/ref/dify/repo/api/models/human_input.py`（200 行，含 HumanInputForm + Delivery + Recipient + Payload BaseModel discriminator）
- [x] 读 `/Users/admin/ai/ref/dify/repo/api/services/human_input_service.py`（前 100 行，确认单 actor `submitted` lifecycle）
- [x] grep `chain|approver|parallel_all|parallel_any|sequential` 在 Dify api/models/ 全空（强证据：Dify 无 chain）
- [x] 沉淀 ChainAdvanceResult dataclass 设计依据 + frozen + default_factory 防共享陷阱
- [x] 沉淀「Dify 无 chain — 本项目独立设计」论点
- [x] 沉淀「invalidate_chain 是我们独创副作用，Dify 用 FormSubmittedError 抢锁不主动失效」对比

---

## 8. 实施红线

1. ❌ **不复制 Dify 源码**（AGPL → Apache 不兼容）
2. ✓ **借鉴 frozen dataclass + Literal 模式**（设计模式可借鉴）
3. ✓ **invalidate_chain 必须在 advisory_lock 内调用**（Pitfall 2 — Phase 3 已沉淀）
4. ✓ **build_initial_payload 默认 `mode=single`**（Phase 3 向后兼容）
5. ✓ **0005 partial index 加速 invalidate_chain 扫描**（`WHERE used_at IS NULL`）
6. ✓ **所有 helper 严格 immutability**（用 `{**payload, ...}` + new list/dict）

---

**Next**: Task 1 - hitl_payload 扩展 + Task 2 - hitl_token_store + Alembic 0005 partial index。
