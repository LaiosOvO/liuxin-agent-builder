# Dify 阅读笔记 — HITL 节点 enter 时机与 chain 集成对比（Plan 04-11）

> 日期: 2026-05-17
> 仓库: https://github.com/langgenius/dify (commit c0bdd679, local clone /Users/admin/ai/ref/dify/repo/)
> Stars: ~141k

## 项目概述（一句话）

Dify 是国内最成熟的开源 LLM 工作流编排平台；其 HumanInputAdapter 提供**单 actor** form-based human-in-the-loop 决策原语（无多人会签 / 无 chain mode / 无 4 模式状态机），与本项目 Plan 04-11 多人审批链节点 enter 时机集成的需求**有显著差异**。

## 技术栈（关键技术选择）

| 维度 | Dify | 本项目（Plan 04-11） |
|------|------|---------------------|
| 编排引擎 | 自研 graphon (Graph + Variable Pool) | LangGraph 1.2 (StateGraph + Checkpoint) |
| 节点 enter 时机 | GraphEngine 调度 + HumanInputForm INSERT | LangGraph node fn 入口 + ExecutionEngine `_on_hitl_enter` 钩子 |
| 决策机制 | submit form by token (单 actor 抢锁) | LangGraph interrupt + `Command(resume=...)` (单 interrupt 点) |
| 多 actor 协同 | 否 (1 form = 1 recipient lifecycle) | 4 模式 chain (single / sequential / parallel_all / parallel_any) |
| Token 批量创建 | 否 (per-recipient submit lock) | `batch_create_tokens_for_actors` (N actors × M actions) |
| Multichannel 通知 | 仅 email + WebApp | email + 5 家 IM provider (NOTI-08 multichannel fan-out) |
| Payload 结构 | Pydantic Annotated discriminator | dict + JSONB + hitl_payload 纯函数模式 |

## 架构要点（核心架构模式）

### Dify HumanInputAdapter 单 actor enter 流程（简化图）

```
ExecutionEngine 调度 HumanInputNode
    │
    ▼
[enter] HumanInputAdapter.create_form
    ├─→ HumanInputForm INSERT (status=pending)
    ├─→ for each recipient in EmailDeliveryConfig.recipients:
    │   └─→ HumanInputFormRecipient INSERT (1:N from form)
    │   └─→ HumanInputFormDelivery INSERT (channel-specific dispatch metadata)
    ├─→ enqueue Celery task: mail_human_input_delivery_task (per delivery row)
    ▼
[interrupt] node yields control to ExecutionEngine
    │
    │  (graph state persisted in graphon)
    │  (邮件 worker 推送 → 用户点击 → /human_input/submit_form_by_token)
    ▼
[resume] HumanInputService.submit_form_by_token
    ├─→ load HumanInputForm + verify token jti unused
    ├─→ mark_submitted (RETURNING optimistic lock)
    ├─→ enqueue resume_app_execution (Celery)
    ▼
[graph continue] GraphEngine.resume(form_data)
```

### 本项目 HITL 节点 enter 流程（Plan 04-11 设计）

```
ExecutionEngine.run_instance 调度 HITL 节点
    │
    ▼
[enter] ExecutionEngine._on_hitl_enter(node_def, instance_id, ...)
    ├─→ 解析 node_def.config:
    │   ├─→ chain_mode (default 'single')
    │   ├─→ assignees ['email', 'user:<uuid>', 'role:<code>']
    │   ├─→ notify_channels (default ['email'])
    │   └─→ timeout_seconds + form_schema
    ├─→ HitlService.resolve_assignees() → list[UUID] approver_uuids
    ├─→ NodeState INSERT (status='waiting_human')
    ├─→ build_initial_payload(chain_mode, approvers=approver_uuids, ...) → node_state.payload
    ├─→ if chain_mode in ('single', 'sequential'):
    │       target_actors = [approver_uuids[0]]   # 仅首发审批人
    │   else:  # parallel_all / parallel_any
    │       target_actors = approver_uuids        # 全部并发收 token
    ├─→ HitlService.batch_create_tokens_for_actors(actor_ids=target_actors, ...) (Plan 04-02)
    ├─→ commit (jti 全部生效)
    ├─→ for actor_id in target_actors:
    │       actor = await db.get(User, actor_id)
    │       NotificationService.enqueue_hitl_multichannel(  # Plan 04-10
    │           channels=notify_channels,
    │           recipient_email=actor.email,
    │           recipient_im_bindings=actor.im_bindings,
    │           tokens=actor_tokens,
    │           ...
    │       )
    ├─→ log.info("hitl.node.entered", extra={chain_mode, approvers_count, channels})
    ▼
[interrupt] HITLNodeExecutor.__call__ → interrupt({
    node_state_id, phase, form_schema, deadline_at,
    current_actor,
    # Plan 04-11 新增 chain 元数据
    chain_mode, approvers, current_idx, notify_channels
})
    │
    │  (LangGraph checkpoint 持久化 state)
    │  (多 channel 通知 fan-out → 用户决策)
    ▼
[resume] API /hitl/action/<jti> POST
    ├─→ HitlActionService.submit_action() (Plan 04-02 chain executor)
    ├─→ compute_chain_advance() → ChainAdvanceResult
    ├─→ if 推进 → ainvoke(Command(resume=decision))
    │
    ▼
[graph continue] LangGraph resume → __call__ 第二次执行 → interrupt 返回 decision
```

### 关键差异点

| # | 维度 | Dify | 本项目 |
|---|------|------|--------|
| 1 | enter 时机 | GraphEngine 调度节点 → 节点内部调 `create_form` | ExecutionEngine `_on_hitl_enter` 钩子（在 node fn `__call__` 之前） |
| 2 | 多 actor 处理 | 无 (1 form 1 lifecycle) | chain_mode 决定 token 创建策略（first-only vs all） |
| 3 | 通知 fan-out | per-recipient + per-channel Celery task | per-actor enqueue_hitl_multichannel（API 内部循环 channels） |
| 4 | interrupt payload | 完整 form definition + token URL | + chain_mode / approvers / current_idx / notify_channels（前端进度渲染） |
| 5 | resume 后状态推进 | mark_submitted optimistic lock + Celery resume | compute_chain_advance pure func + LangGraph Command(resume) |
| 6 | 失败补偿 | per-delivery retry queue | Phase 3 既有 03-08 tenacity + 03-09 timeout escalation |

## 可借鉴的设计模式

1. **enter / interrupt / resume 三段式生命周期分离**
   - Dify: `create_form` (副作用) → ExecutionEngine 暂停 → `submit_form_by_token` (副作用 + resume)
   - 本项目: `_on_hitl_enter` (副作用) → `interrupt()` (暂停) → `submit_action` + `Command(resume)` (副作用 + resume)
   - **借鉴点**：副作用归外（enter 钩子），纯函数归内（`__call__` 仅读 state + 抛 interrupt），保证 LangGraph 重跑时不重复发邮件

2. **token 创建 batch 入口**
   - Dify: `HumanInputFormRecipient` per-form 一行 + dispatch metadata 表 1:N
   - 本项目: `batch_create_tokens_for_actors(actor_ids=[...])` 笛卡尔积一次入库（Plan 04-02 已落地）
   - **借鉴点**：批量入库 + 单 commit，避免 N 次 INSERT 引发 N 次 fsync

3. **enter 钩子之后才 commit + enqueue**
   - Dify: `create_form` 内同步 INSERT 全部行 → commit → 触发 Celery worker
   - 本项目: `_on_hitl_enter` 内 INSERT NodeState + tokens → commit → 循环 enqueue_hitl_multichannel
   - **借鉴点**：commit 后才 enqueue (Pitfall 2)，防 worker 抢跑事务未提交行

4. **interrupt payload 含决策上下文 + 前端进度元数据**
   - Dify: payload 含 form schema + button labels + recipient hints（form 渲染所需）
   - 本项目: payload 含 form_schema + deadline_at + chain_mode + approvers + current_idx（决策页 + 进度条渲染所需）
   - **借鉴点**：前端无需另调 API 拿 chain 状态（payload 即元数据 + 状态机），减少一次 HTTP round trip

5. **per-recipient resolve + missing skip**
   - Dify: recipient 列表内任一 `reference_id` 解析失败 → 跳过该 recipient + warn 日志
   - 本项目: assignees 表达式（email / user:<uuid> / role:<code>）解析失败时跳过 + log warning
   - **借鉴点**：单 recipient 解析失败不阻塞其他 actor / channel

## 与本项目的关系

### 应用到 Plan 04-11 的具体方式

1. **`ExecutionEngine._on_hitl_enter` 钩子作为节点 enter 时机**
   - 与 Dify 在 `create_form` 内集中处理副作用一致
   - 解析 chain_mode + assignees + notify_channels → 决定 token 创建策略 + 通知 fan-out 范围

2. **`HitlService.resolve_assignees` 复用 EscalationService 4 表达式 router**
   - email / user:<uuid> / role:<code> 已在 EscalationService 落地（Plan 04-04）
   - dept:<name> 抛 NotImplementedError（与 EscalationService 一致 — Phase 5 实现）
   - **不复用 EscalationService 代码**，而是在 HitlService 中独立实现一个 resolve_assignees 方法（语义不同：assignees 是节点配置 vs escalation_to 是 timeout 升级配置）

3. **chain_mode → token 创建策略表**

   | chain_mode | target_actors | tokens 数量 | 通知 fan-out 范围 |
   |-----------|---------------|------------|------------------|
   | single | [approvers[0]] | 1 × len(actions) | 1 actor × len(channels) |
   | sequential | [approvers[0]] | 1 × len(actions) | 1 actor × len(channels) |
   | parallel_all | approvers (全部) | N × len(actions) | N actors × len(channels) |
   | parallel_any | approvers (全部) | N × len(actions) | N actors × len(channels) |

4. **interrupt_payload 扩展（4 新字段）**
   - chain_mode / approvers / current_idx → 前端决策页渲染进度条 + 显示其他参与人姓名
   - notify_channels → 前端可显示用户从哪个 channel 收到通知（IM 卡片跳转返回 web 决策页时上下文一致）

5. **结构化日志 `hitl.node.entered`**
   - Phase 7 Run Viewer 时间线渲染钩子（与 04-02 `hitl.chain.advance` 结构化日志范式一致）
   - extra dict 含 chain_mode / approvers_count / notify_channels / instance_id / node_state_id

### Plan 04-11 100% 独立设计部分（Dify 无对应）

- **4 chain mode 状态机** (Plan 04-01/04-02 已落地)
- **multichannel fan-out per-actor** (Plan 04-10 已落地)
- **interrupt_payload chain 进度元数据** (本 plan 实现)
- **Phase 3 single 100% 向后兼容** (chain_mode default='single' + 旧 DSL 无 chain_mode 字段 → 走 single 路径)

## License & Attribution

- Dify 是 **AGPL-3.0**；本项目 **Apache-2.0**
- 本 plan **未拷贝 Dify 源码** — 仅借鉴**设计模式 / 命名规范 / 数据结构思路**
- 4 chain mode 状态机 Dify 无对应代码可抄；本项目独立设计

## 参考链接（local clone path）

- `/Users/admin/ai/ref/dify/repo/api/core/workflow/human_input_adapter.py` (form 配置 + EmailDeliveryConfig Pydantic discriminator)
- `/Users/admin/ai/ref/dify/repo/api/core/workflow/human_input_forms.py` (HumanInputForm ORM 模型 + recipient/delivery 子表)
- `/Users/admin/ai/ref/dify/repo/api/core/workflow/human_input_policy.py` (form lifecycle policy decisions)
- 历史 reading docs:
  - `docs/reading-dify-03-02-hitl-executor-2026-05-17.md` (Phase 3 HITLNodeExecutor 基础)
  - `docs/reading-dify-04-01-chain-payload-2026-05-17.md` (chain payload + ChainAdvanceResult)
  - `docs/reading-dify-04-02-chain-executor-2026-05-17.md` (chain executor 4 mode)
  - `docs/reading-dify-04-10-multichannel-2026-05-17.md` (multichannel fan-out NOTI-08)

---

*生成于 2026-05-17，作为 Plan 04-11 的 Task 0 reading doc gate（CLAUDE.md §2.7 HARD GATE）*
