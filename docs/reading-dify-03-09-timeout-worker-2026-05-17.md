# Dify 阅读笔记 — Human Input Timeout Tasks（超时催办 worker）

> 日期: 2026-05-17
> 仓库: https://github.com/langgenius/dify (commit c0bdd679, local clone /Users/admin/ai/ref/dify/repo/)
> Stars: ~141k
> 适用 plan: 03-09 HITL 超时催办 worker（arq cron + 24h/48h/72h 阶梯 + 72h 升级）

---

## 1. 项目概述（一句话）

Dify 的 HITL 超时扫描 worker `api/tasks/human_input_timeout_tasks.py` 通过 Celery `@shared_task(name="human_input_form_timeout.check_and_resume", queue="schedule_executor")` 每隔固定时间扫一次 `HumanInputForm.expiration_time <= now()`，命中后调 `form_repo.mark_timeout(form_id, status=TIMEOUT/EXPIRED)` 写入状态终态并 `service.enqueue_resume(workflow_run_id)` 让 LangGraph 走超时分支 — **只标记超时不主动催办**（无中间提醒 / 升级人逻辑）。

---

## 2. 技术栈（关键技术选择）

| 维度 | Dify | 本项目 |
|---|---|---|
| 调度器 | **Celery beat**（crontab 定义在 `extensions/ext_celery.py`） | **arq cron**（CLAUDE.md §3 锁定，`from arq.cron import cron`） |
| Worker 入口 | `@shared_task(name=..., queue="schedule_executor")` | `async def scan_hitl_timeouts(ctx) -> int` arq function（注册到 `WorkerSettings.cron_jobs`） |
| 超时类型 | **node_timeout / global_timeout** 两种（per-form expiration_time + per-tenant 全局上限） | **三档阶梯催办**（24h reminder_round=1 / 48h round=2 / 72h escalate）+ 节点级 `escalate_after` 配置 |
| 状态终态 | `HumanInputFormStatus.TIMEOUT` / `EXPIRED` + `service.enqueue_resume()`（流程走 timeout 分支） | `notifications` 表 INSERT 催办记录 + 升级时改 `node_state.payload.current_actor` + 写 audit_log |
| 主动催办 | **无**（仅标记 timeout 让流程自己处理） | **有**（NOTI-09 — 每档 round 主动发邮件给原 actor 或升级人）|
| 并发安全 | session-level 事务 + `session.scalars(...).all()` 取出后再批量处理 | **PG advisory_xact_lock(hash(node_state_id))** + `notifications` UNIQUE 约束双保险 |

---

## 3. 架构要点（核心架构模式）

### 3.1 Dify 超时扫描流程（简图）

```
Celery beat（每分钟）
     ↓ enqueue schedule_executor queue
check_and_handle_human_input_timeouts(limit=100):
  1. session.scalars(
       select(HumanInputForm).where(
         status == WAITING,
         expiration_time <= now() OR created_at <= now - global_timeout
       ).limit(100)
     )
  2. for form in expired_forms:
       if form.form_kind == DELIVERY_TEST:
           form_repo.mark_timeout(form_id, status=TIMEOUT, reason='delivery_test_timeout')
           continue
       is_global = _is_global_timeout(form, global_timeout_seconds, now=now)
       record = form_repo.mark_timeout(
           form_id, 
           status=EXPIRED if is_global else TIMEOUT, 
           reason='global_timeout' if is_global else 'node_timeout'
       )
       if is_global:
           _handle_global_timeout(...)  # stop workflow_run + delete pause state
       else:
           service.enqueue_resume(record.workflow_run_id)  # LangGraph 走 timeout 分支
```

### 3.2 全局超时处理 `_handle_global_timeout`

```python
def _handle_global_timeout(*, form_id, workflow_run_id, node_id, session_factory):
    with session_factory() as session, session.begin():
        workflow_run = session.get(WorkflowRun, workflow_run_id)
        workflow_run.status = STOPPED
        workflow_run.error = f"Human input global timeout at node {node_id}"
        workflow_run.finished_at = now
        # 删除 LangGraph pause state object（释放存储）
        pause_model = session.scalar(select(WorkflowPause).where(...))
        storage.delete(pause_model.state_object_key)
        pause_model.resumed_at = now
```

### 3.3 关键观察：Dify **没有**主动催办 worker

Dify 的"超时"是**单一时间点终态**（form.expiration_time 一过就标记 TIMEOUT 并停止 waiting 流程），**不主动发邮件 / IM 提醒**。原因：Dify 的 HITL 是表单填写场景（用户主动找表单提交），不是审批工作流场景（审批人需要被推送）。

**本项目场景不同**：审批人不会主动检查邮箱；如果不催办，72h 后超时直接走 escalate 分支用户体验差。**NOTI-09 要求**：24h/48h 各发一封催办邮件，72h 升级到 admin/HR。

---

## 4. 可借鉴的设计模式（具体文件路径 + 模式名）

### 4.1 ✅ Pattern A: cron 调度扫描查询模式

**Dify 源码**：`api/tasks/human_input_timeout_tasks.py:66-79`

```python
stmt = (
    select(HumanInputForm)
    .where(
        HumanInputForm.status == HumanInputFormStatus.WAITING,
        timeout_filter,  # expiration_time <= now() OR created_at <= now - global_timeout
    )
    .order_by(HumanInputForm.id.asc())
    .limit(limit)
)
expired_forms = session.scalars(stmt).all()
```

**借鉴点**：
1. WHERE 双条件用 `status IN (...waiting...)` + 时间维度（保证只扫"有意义的待处理"）
2. ORDER BY id ASC（FIFO 公平 + 索引顺序扫描）
3. LIMIT 100（防止一次拿太多 OOM；多 worker 可水平扩）

**本项目应用**：
```python
result = await db.execute(
    select(NodeState).where(
        NodeState.status.in_(["waiting_human", "in_review"]),
        NodeState.payload["deadline_at"].astext.cast(DateTime) < now,
    )
    .order_by(NodeState.id.asc())  # 顺序处理
    .limit(100)
)
```

差异：我们的 `deadline_at` 存在 `node_states.payload` JSONB 里（03-06 plan 已落 payload 列），需要 JSONB path expression 转 timestamp 比较。

### 4.2 ✅ Pattern B: 不同超时档位走不同处理路径

**Dify 源码**：`_is_global_timeout` + `if is_global: _handle_global_timeout` 二分支。

**借鉴点**：单个 worker 函数内根据时间档位 dispatch 到不同 handler，避免冗余的多 worker 实现。

**本项目应用**：单个 `scan_hitl_timeouts` 内根据 `elapsed` 与阈值比较 + 当前 `reminder_round` 状态 → dispatch 到 `_trigger_reminder(round=1)` / `_trigger_reminder(round=2)` / `_trigger_escalation`。状态从 `notifications` 表 SELECT MAX(reminder_round) 推导（vs Dify 用 form.status 推导）。

### 4.3 ✅ Pattern C: 异常隔离（不让单个失败阻塞整批）

**Dify 源码**：`human_input_timeout_tasks.py:103-113`

```python
for form_model in expired_forms:
    try:
        ...
    except Exception:
        logger.exception(
            "Failed to handle timeout for form_id=%s workflow_run_id=%s",
            form_model.id,
            form_model.workflow_run_id,
        )
```

**借鉴点**：每节点处理 try/except 包裹，单失败不影响其他节点处理。

**本项目应用**：scan_hitl_timeouts 主循环每个 `ns` 处理用 try/except 包裹（防多 worker race 时单一 advisory_lock 失败导致整批 abort）。

### 4.4 ⚠️ Pattern D: enqueue_resume → service 调用解耦（不可直接照搬）

Dify 调 `service.enqueue_resume(workflow_run_id)` 让另一个 Celery task 处理 LangGraph resume；目的是把"扫超时"和"推进流程"分两个 worker 解耦。

**本项目不同**：催办不需要 resume（only escalation 才换 actor）；reminder 路径只是 enqueue email，不动 LangGraph 状态。escalation 路径才会修改 `node_state.payload.current_actor` + records 加 escalate，但仍**不** ainvoke graph（v1 简化：升级后下一档 24h 再过 deadline 时由 worker 再扫一次即可；不主动触发 LangGraph timeout 分支）。

### 4.5 ✅ Pattern E: limit + ORDER BY 防 OOM

**Dify**：`limit=100`。**本项目沿用** — `scan_hitl_timeouts(ctx) -> int` 默认 limit=100；如积压超过 100，下一次 cron tick 继续处理（最坏延迟 60s）。

---

## 5. 与 hr/offboarding-flow 对照

hr 项目**没有**专门的 timeout worker（项目尚未实现 deadline 超时催办，仅记录"截止时间"字段供 UI 显示）。

**hr 启发**：Mattermost 卡片消息 + 邮件双通道并行催办 — 我们 Phase 4 接入 IM 时复用 `NotificationService.enqueue_hitl_email`（→ 改为 `enqueue_hitl_notifications` channels=['email','feishu']）。本 plan 仅做 email 催办。

---

## 6. 与本项目的关系（如何应用到当前 plan）

| Dify / hr 模式 | 本项目落点 | 文件 |
|---|---|---|
| Celery `@shared_task` cron | arq `cron(scan_hitl_timeouts, minute=set(range(60)), second={0})` | `backend/app/agent_builder/worker.py`（注册到 WorkerSettings.cron_jobs） |
| `HumanInputForm.expiration_time` | `node_states.payload['deadline_at']` JSONB path | `backend/app/jobs/hitl_timeout_jobs.py`（**本 plan 新建**） |
| `form_repo.mark_timeout(...)` | `notifications` INSERT round=N（不动 node_state.status，等 escalate 时才改 payload） | `backend/app/jobs/hitl_timeout_jobs.py` |
| `is_global_timeout` 二分支 | `elapsed >= 72h → escalate; 48h → round=2; 24h → round=1` 三分支 | `backend/app/jobs/hitl_timeout_jobs.py` |
| `service.enqueue_resume` | `NotificationService.enqueue_hitl_email(reminder_round=N)` 复用 | `backend/app/services/notification_service.py`（03-04 已建） |
| **无** Dify 等价 — 升级路径独创 | `EscalationService.perform_escalation` 解析升级人 + 写 records + audit + 发邮件 | `backend/app/agent_builder/services/escalation_service.py`（**本 plan 新建**） |

---

## 7. 我们的 arq cron 与 Celery beat 的区别（强制 §7）

**强制 §7 小节** — CLAUDE.md 2.7 reading-first 要求显式记录"为什么不照搬 Dify"。

| 维度 | Celery beat（Dify） | arq cron（本项目） | 选择理由 |
|---|---|---|---|
| **架构** | 独立进程 `celery beat` 推送任务到 broker，worker 消费 | 单进程内置 — `WorkerSettings.cron_jobs` 由 arq worker 主循环按时间触发 | arq 内置 cron 不需要额外进程，部署更简单（CLAUDE.md §3 技术栈锁定 arq 0.28+） |
| **同步性** | Celery task 默认同步阻塞，需要 async 包装（如 `asgiref.sync_to_async`） | arq 原生 asyncio，与 `aiosmtplib` / `asyncpg` / `langgraph` 全异步同构 | 避免上下文切换开销 + 不阻塞事件循环（NOTI-09 + asyncpg 异步生态） |
| **多 worker 唯一性** | Celery beat 单实例触发（broker 中只有 1 个调度入口），多 worker 抢任务 | arq 的 `cron(unique=True)`（默认值）让多 worker 中只有一个执行 | 防多 worker race（与 advisory_lock 双保险） |
| **配置语法** | `crontab(minute='*/1')` 或 `crontab(minute=0)` | `cron(scan_hitl_timeouts, minute=set(range(60)), second={0})` 每分钟 0 秒触发 | arq 配置粒度到秒 + 字段类型为 `set[int]`，比 crontab 更易类型校验 |
| **失败重试** | Celery 默认重试由 broker 配置 | arq cron 默认 `max_tries=1`（不重试 — 因 cron 下次会再触发） | scan 失败不重试，60s 后再来；防"补发风暴" |
| **运维监控** | Flower、Celery events | arq 内置 `health-check` + Redis key 监控 | 简单部署 + Redis 已是基础设施 |

**结论**：arq cron 完全覆盖 Dify Celery beat 用例，且更适合 Python asyncio 异步生态。本 plan 用 `from arq.cron import cron` + `WorkerSettings.cron_jobs` 实现。

---

## 8. 风险与边界（reading doc 风险清单）

| # | 风险 | 缓解 |
|---|---|---|
| 1 | **多 worker 并发扫描同一节点 → 重复发邮件** | UNIQUE 约束（03-01 已建）+ advisory_xact_lock(node_state_id) 双保险 |
| 2 | **payload JSONB 中 deadline_at 字段不存在或格式错** | scan 时校验：`if not isinstance(deadline_at, str): continue`；不抛 |
| 3 | **escalate_to 字段未配置（节点 config 缺失）** | fallback 到 workspace_id 下 super_admin 或 admin 角色的 email（Phase 5 expand role:admin/dept:HR） |
| 4 | **node 状态在 scan 与 advisory_lock 之间被外部 POST 改变（如用户刚好点了按钮）** | advisory_lock 内**重新查 node_state.status**，已是 `done/rejected/returned` 则 skip |
| 5 | **reminder 邮件失败（SMTP 不可达）** | 复用 03-04 tenacity 3 次重试 + notifications.status='failed' 终态；下次 cron 不会重发（UNIQUE 约束）|
| 6 | **大批量超时节点处理时间超过 cron 周期（60s）** | LIMIT 100 + 下次 cron 继续；如积压持续报警（Phase 7 监控）|

---

## 9. 引用清单（reading doc 自检 — 文件:行 来自 Dify 源码）

- `/Users/admin/ai/ref/dify/repo/api/tasks/human_input_timeout_tasks.py:56-113`：`check_and_handle_human_input_timeouts` 主函数
- `/Users/admin/ai/ref/dify/repo/api/tasks/human_input_timeout_tasks.py:22-29`：`_is_global_timeout` 全局超时判定
- `/Users/admin/ai/ref/dify/repo/api/tasks/human_input_timeout_tasks.py:32-53`：`_handle_global_timeout` 全局超时处理
- `/Users/admin/ai/ref/dify/repo/api/tasks/mail_human_input_delivery_task.py:46-48`：`_build_form_link`（03-04 已借鉴）
- `/Users/admin/ai/ref/dify/repo/api/models/human_input.py`（HumanInputForm/Delivery/Recipient — 03-01 已借鉴）

**Attribution**：本 plan **不会拷贝** Dify 源码到本项目。仅借鉴**设计模式**（cron 扫描 + try/except 隔离 + limit 防 OOM）+ **数据结构思路**（按时间档位 dispatch）+ **边界考虑**（多 worker race / 异常隔离）。本项目实现重写 — 中文注释 + asyncio 风格 + 三档阶梯 + EscalationService 独创。

---

*Plan: 03-09*
*Reading doc 写完 = CLAUDE.md 2.7 GATE 解锁。下一步: 实现 hitl_timeout_jobs.py + EscalationService + 测试。*
