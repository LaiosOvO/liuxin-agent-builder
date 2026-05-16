# Dify 阅读笔记 — Chain Executor（HitlActionService 4 模式分叉）

> 日期: 2026-05-17
> 仓库: https://github.com/langgenius/dify (本地 clone `/Users/admin/ai/ref/dify/repo/`)
> Stars: ~141k
> 本文档对应 Plan 04-02（chain executor — 4 模式状态推进）；CLAUDE.md §2.7 硬性 reading gate

---

## 项目概述（一句话）

Dify 是 LLM 应用编排平台，含工作流（含 HumanInputForm 单审批人节点），但**没有审批链概念** — 单 actor 模式：一个 form 只接收一个 recipient 的决策。

## 技术栈（关键技术选择）

- **SQLAlchemy Engine + sessionmaker** — 事务边界由 service 层显式管理（`with self._session_factory() as session:`）
- **HumanInputFormSubmissionRepository** — Repository pattern 封装数据访问
- **mark_submitted** — 原子标记 form 已提交（与本项目 `HitlTokenStore.consume()` 类似的「乐观锁 + RETURNING」模式）
- **resume_app_execution** — 表单提交后异步唤起工作流（Celery task）；本项目对应 `graph_resumer` 注入回调

## 架构要点（核心架构模式 — 简图）

```
Dify HumanInputForm 单 actor 流程：
   POST /web/form_token/submit
      ↓
   HumanInputService.submit_form_by_token(form_token, action_id, form_data)
      ↓
   form = repo.get_by_token(form_token)              # 仅一个 recipient_id
   ensure_form_active(form)                          # 状态机校验：not submitted + 未过期
   _validate_submission(form, action_id, form_data)  # jsonschema 校验
      ↓
   result = repo.mark_submitted(form_id, action_id, form_data)
      ↓ (form 已 marked submitted；后续 GET 抛 FormSubmittedError 412)
   enqueue_resume(workflow_run_id)                   # Celery task 推 workflow 继续

边界处理：
   • FormSubmittedError 412 — 重复提交（与本项目 JtiAlreadyConsumed 409 类似）
   • FormExpiredError 412 — 已过期（与本项目 TokenExpired 410 类似）
   • InvalidFormDataError 400 — schema 校验失败（与本项目 FormDataValidationError 422 类似）

注意：**Dify 一个 form 仅一个 recipient** — 多人通过抢锁语义实现（先到先得）。
```

## 可借鉴的设计模式

### 1. Service 层事务边界统一管理（`HumanInputService.submit_form_by_token`）

- **路径**：`/Users/admin/ai/ref/dify/repo/api/services/human_input_service.py:155-184`
- **模式**：service 方法是顶层事务边界 — `validate → mark_submitted → enqueue_resume` 在一个事务内完成
- **本项目应用**：`HitlActionService.submit_action` 已沿用此模式（advisory_lock → consume → invalidate → update payload → audit → commit 串行）
- **Phase 4 扩展**：在 commit 前插入 chain 分叉 + invalidate_chain + 补通知 enqueue

### 2. 副作用统一末尾触发（`enqueue_resume` 调用位置）

- **路径**：`human_input_service.py:184` — `mark_submitted` 后才 enqueue Celery
- **理由**：副作用（task enqueue）一旦失败不能回滚；置于事务末尾确保 DB 写入已成功
- **本项目应用**：
  - 通知入队（`enqueue_hitl_email` / `enqueue_generic_email`）在 chain 分支内调用，但**在 commit 之前**（与 NotificationService 自身 commit 的事务边界协调） — 注意 NotificationService 内部已 commit，故 chain 推进期间 enqueue 的通知**实际是 fire-and-forget**
  - 不阻塞主事务

### 3. Repository pattern 替代直接 SQL（`HumanInputFormSubmissionRepository.mark_submitted`）

- **模式**：HumanInputFormSubmissionRepository 封装 `UPDATE ... WHERE id=:id AND submitted=FALSE RETURNING *`
- **本项目应用**：`HitlTokenStore.consume` + `invalidate_chain` 已经是 repository pattern；service 层只调用，不写 SQL
- **Phase 4 扩展**：chain 推进期间复用 04-01 已建的 `compute_chain_advance` 纯函数 + `invalidate_chain` repo 方法

## 与本项目的关系

### 对比：Dify 单 actor vs 本项目 4 chain mode 分叉

| 维度 | Dify HumanInputForm | 本项目 HITL chain |
| --- | --- | --- |
| **actor 数量** | 单 recipient | 1..N（4 模式可选） |
| **冲突处理** | FormSubmittedError 412（抢锁） | `invalidate_chain` 主动失效（parallel_*）+ next_approver 推进（sequential） |
| **token 数量** | 1 form_token | N × allowed_actions（每 actor 每 action 一行） |
| **状态推进** | 直接 `mark_submitted` | `compute_chain_advance` 纯函数算下一步 + service 触发副作用 |
| **补通知** | 无 — 单 actor 不需要 | parallel_* 终止时发"已被 X 处理"或"已被 X 拒绝" |

### 借鉴点

1. **Service 顶层事务**：本项目 `HitlActionService.submit_action` 沿用 Dify 单 service 一个事务的模式 — Phase 4 chain 分叉在事务内完成，不引入子事务
2. **副作用集中末尾**：chain 分支内 `invalidate_chain` + `_supplement_notify` + `batch_create_tokens_for_actors` + `enqueue_hitl_email` 均在 commit 之前
3. **Repository pattern**：复用 04-01 的 `HitlTokenStore.invalidate_chain` + `HitlService.batch_create_tokens_for_actors`，service 层只写业务流程

### 独立设计点（Dify 没有的）

1. **`compute_chain_advance` 纯函数 + 4 mode 状态机**：04-01 已建（`hitl_payload.py`）；本 plan 04-02 调用方
2. **invalidate_chain 主动失效**：替代 Dify 的「抢锁」语义；用 PG `UPDATE ... RETURNING` 一次性失效全 instance 未消费 token
3. **补通知 `_supplement_notify`**：parallel_* 模式独有 — 发"已被 X 处理"邮件给被失效的其他 approver；Dify 单 actor 不需要
4. **结构化日志 `hitl.chain.advance`**：包含 chain_mode/actor_id/action/new_status/next_approvers_count/invalidated_count — 供 Phase 7 Run Viewer 检索；Dify 无类似机制

## 不借鉴的部分（AGPL 风险 + 不适用）

1. **Dify FormSubmittedError 抢锁语义**：不适合多 actor 协同 — 本项目用主动失效（invalidate_chain）+ 补通知
2. **Dify enqueue_resume Celery task**：本项目沿用 Phase 3 `_resume_graph` 注入回调模式（避免 Celery 依赖）
3. **不复制 Dify 源码**：仅借鉴**设计模式**（service 边界 / Repository pattern / 副作用末尾触发），所有实现独立创作

## Phase 4 Plan 04-02 实施要点

### chain 分支决策表（service 内伪代码）

```python
# HitlActionService.submit_action 内 step 6 chain 分叉
chain_result = compute_chain_advance(ns.payload, actor_id, action)

# 6a. parallel_* 终止 → 失效其他 token + 补通知
if chain_result.invalidate_others:
    invalidated = await store.invalidate_chain(instance_id, except_jti=jti)
    await self._supplement_notify(invalidated, action, actor_email)

# 6b. sequential approve 推进 → 给下一人创建 token + 通知
if chain_result.next_approvers:
    new_tokens = await hitl_svc.batch_create_tokens_for_actors(
        instance_id, node_state_id,
        actor_ids=chain_result.next_approvers,
        allowed_actions=["approve", "return", "reject"],
    )
    await self._enqueue_chain_notifications(new_tokens, ns, chain_result)

# 7. 写 node_state 状态用 chain_result.new_payload + new_status
ns.payload = chain_result.new_payload
ns.status = chain_result.new_status
```

### 结构化日志（Phase 7 Run Viewer 钩子）

```python
log.info(
    "hitl.chain.advance",
    extra={
        "chain_mode": chain.get("mode"),
        "actor_id": str(actor_id),
        "action": action,
        "new_status": chain_result.new_status,
        "next_approvers_count": len(chain_result.next_approvers),
        "invalidated_count": len(invalidated_chain),
        "instance_id": str(instance_id),
        "node_state_id": str(node_state_id),
    },
)
```

### 测试矩阵（18+ 集成测试）

- 4 mode × 3 action = 12 基础组合
- 边界用例：sequential 最后一人 approve done / parallel_all 部分 approve 仍 in_review / parallel_any 拒绝即终止
- 异常路径：actor 不在 approvers / compute_chain_advance 抛异常事务回滚
- 日志验证：caplog 捕获 `hitl.chain.advance` record

## 总结

**Dify 没有审批链** — `human_input_service.py` 全文 grep `chain|approver` 0 命中（已验证）。Phase 4 04-02 是独立设计 + 借鉴 Dify service 层事务边界 / Repository pattern / 副作用集中末尾的工程模式。

具体代码**不复用 Dify**（AGPL 风险），仅借鉴**设计模式**。
