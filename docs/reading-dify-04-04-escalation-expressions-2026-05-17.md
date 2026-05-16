# Dify 阅读笔记 — Escalation 表达式解析

> 日期: 2026-05-17
> 仓库: https://github.com/langgenius/dify (commit e7e6fe88, local clone /Users/admin/ai/ref/dify/repo/)
> Stars: ~141k
> Plan: 04-04 — HITL-04 完整 4 表达式解析（email / user: / role: / dept:NotImpl）

## 项目概述

Dify 是 LangGenius 开源的 LLM 应用开发平台，含可视化工作流（含 Human Input 节点）。
本笔记聚焦其 HITL 超时处理逻辑（与本项目 escalation_service 对照），用于澄清「Dify 仅 status=TIMEOUT」与「本项目 actor 替换 + 多 email 通知」的设计分歧。

## 技术栈

- `Celery shared_task` （vs 本项目 arq cron `unique=True`）
- `sqlalchemy.orm.sessionmaker` 显式 session_factory（vs 本项目 `async_session_maker`）
- `HumanInputFormStatus.WAITING/TIMEOUT/EXPIRED` 三态（vs 本项目 4 档阶梯催办 round=0/1/2/3）

## 架构要点

```
Dify timeout flow:
  Celery beat (周期 N min)
    → check_and_handle_human_input_timeouts(limit=100)
      → 查 WAITING + expiration_time<=now 的 form
        → mark_timeout(status=TIMEOUT|EXPIRED, reason=node_timeout|global_timeout)
        → if global: 直接 STOP workflow_run + delete pause object
        → else: service.enqueue_resume(workflow_run_id) ← 让 graph 走 timeout 分支

本项目 escalation flow (对比):
  arq cron (60s)
    → scan_hitl_timeouts(limit=100)
      → 查 waiting_human + deadline_at<=now 的 node_state
        → advisory_xact_lock(hash(ns_id))
        → 三档阶梯：催办 round=1/2 (24h/48h) → 升级 round=3 (72h)
        → 升级 = resolve_escalate_to → 替换 current_actor → 发新邮件 + audit_log
```

**核心差异**：Dify「超时即终止流程或让 graph 处理 timeout 分支」；本项目「超时主动催办 + 升级换 actor」（业务场景：审批场景 actor 通常人不主动看邮件，需系统主动催办+升级）。

## 可借鉴的设计模式

### 1. 「Scan worker + 业务 service 解耦」模式

**Dify 路径**：`api/tasks/human_input_timeout_tasks.py:57-113`

```python
@shared_task(name="human_input_form_timeout.check_and_resume", queue="schedule_executor")
def check_and_handle_human_input_timeouts(limit: int = 100):
    session_factory = sessionmaker(bind=db.engine, expire_on_commit=False)
    form_repo = HumanInputFormSubmissionRepository()
    service = HumanInputService(session_factory, form_repository=form_repo)
    # ... 扫超时表 ...
    for form_model in expired_forms:
        try:
            record = form_repo.mark_timeout(...)
            service.enqueue_resume(record.workflow_run_id)
        except Exception:
            logger.exception(...)
```

**借鉴点**：
- scan worker 只做「扫表 + 路由调度」，**不持有业务逻辑**
- 业务逻辑落到 service（`HumanInputService` / 本项目 `EscalationService`）
- 单 form 异常 try/except 包住 — 不阻塞其他 form 处理
- 本项目 Phase 3 03-09 已落地此模式（scan_hitl_timeouts.py + EscalationService）

### 2. 「reason 字段路由不同处理分支」模式

**Dify 路径**：`api/tasks/human_input_timeout_tasks.py:95-97`

```python
record = form_repo.mark_timeout(
    form_id=form_model.id,
    timeout_status=HumanInputFormStatus.EXPIRED if is_global else HumanInputFormStatus.TIMEOUT,
    reason="global_timeout" if is_global else "node_timeout",
)
```

**借鉴点**：
- 用 `reason` 字段标记触发原因，便于审计 + 不同处理分支
- 本项目 04-04 中升级写 audit_log.meta.reason='timeout_72h'（已是同模式）

### 3. 「Expression Prefix Routing」模式（本项目独立设计 — Dify 无）

**Dify 无对应实现**：Dify HITL 仅 `assignee: list[user_email]` 静态字符串，**没有动态表达式解析**。

本项目独立设计原因：
- 审批场景常见需求：role:admin 自动找 workspace admin、dept:HR 找部门负责人
- 静态 email 列表 → 用户离职/换岗后失效 → 维护负担
- 表达式解析 → 运行时动态查询 → 跟随组织结构变化

**实现模式**（参考 K8s label selector、cron 表达式风格）：

```python
async def resolve_escalate_to(self, *, node_config, workspace_id) -> list[str] | None:
    if not node_config:
        return await self._fallback_workspace_admin_emails(workspace_id) or None

    expr = node_config.get("escalate_to")
    if not expr or not isinstance(expr, str):
        return await self._fallback_workspace_admin_emails(workspace_id) or None

    expr = expr.strip()

    # 1. dept:<name> — Phase 5 IM 目录同步后实现
    if expr.startswith("dept:"):
        raise NotImplementedError(...)

    # 2. user:<uuid>
    if expr.startswith("user:"):
        try:
            uid = UUID(expr[5:].strip())
        except ValueError:
            return None
        email = await self._get_user_email(uid, workspace_id)
        return [email] if email else None

    # 3. role:<code>
    if expr.startswith("role:"):
        role_code = expr[5:].strip()
        emails = await self._get_emails_by_role(role_code, workspace_id)
        return emails or None

    # 4. email (default) - "@" in expr and ":" not in expr
    if "@" in expr and ":" not in expr:
        return [expr]

    # 5. fallback
    return await self._fallback_workspace_admin_emails(workspace_id) or None
```

**优先级顺序**：`dept:` (raise) > `user:` > `role:` > email > fallback

### 4. 「workspace_id WHERE 注入」多租户隔离

**Dify 路径**：无显式 workspace 概念（单租户）。

本项目 helper 必须每个查询加 `workspace_id` 条件（CLAUDE.md §2.4）：

```python
async def _get_user_email(self, user_id, workspace_id) -> str | None:
    stmt = (
        select(User.email)
        .join(UserWorkspaceRole, UserWorkspaceRole.user_id == User.id)
        .where(
            User.id == user_id,
            UserWorkspaceRole.workspace_id == workspace_id,  # ← 防越权
            User.status == "active",
        )
        .limit(1)
    )
```

防止 attacker 配置 `user:<其他 workspace 的 uuid>` 越权拿到他人 email。

### 5. 「distinct() 防重复」多 admin 邮件去重

**Dify 路径**：N/A（无 role 概念）

本项目设计：

```python
async def _get_emails_by_role(self, role_code, workspace_id) -> list[str]:
    stmt = (
        select(User.email)
        .join(UserWorkspaceRole, UserWorkspaceRole.user_id == User.id)
        .join(Role, Role.id == UserWorkspaceRole.role_id)
        .where(
            UserWorkspaceRole.workspace_id == workspace_id,
            Role.code == role_code,
            User.status == "active",
        )
        .distinct()  # 防同一 user 有多角色（理论上 PK 约束已防，但 distinct 是兜底）
    )
```

## 与本项目的关系

### 直接借鉴（Plan 04-04 应用）

1. **scan worker + service 解耦** — Phase 3 03-09 已落地，04-04 不动 scan，仅扩展 service
2. **reason 字段路由** — audit_log.meta.reason='timeout_72h' 已在用，04-04 保留
3. **try/except 包住单个升级人** — 多 admin 时一个邮件失败不阻塞其他

### 独立设计（本 plan 创新）

1. **表达式解析** — 4 prefix 路由（dept:/user:/role:/email）
2. **list[str] 返回类型** — role:admin 可能匹配多人；向后兼容 fallback 返回 list
3. **dept: NotImplementedError** — 留 Phase 5 IM 目录同步 hook
4. **多 email perform_escalation** — 遍历发邮件 + 写多条 audit_log（每 email 独立审计）
5. **structured logger** — `hitl.escalation.resolved` 含 expression/matched_count/workspace_id

### 后续 Phase 关系

- **Phase 5** IM 目录同步 → 实现 `dept:<name>` 表达式（查 im_directory 表）
- **Phase 7** 可观测性 → 用 `hitl.escalation.resolved` 日志做表达式命中分析

## 关键边界情况清单

| 表达式 | 输入示例 | 期望返回 | 备注 |
|---|---|---|---|
| `email:user@x.com` (legacy) | `manager@company.com` | `['manager@company.com']` | Phase 3 兼容 — 含 @ + 无 `:` |
| `user:<uuid>` 命中 | `user:550e8400-...` | `['user@x.com']` | 同 workspace + active |
| `user:<uuid>` 跨 ws | `user:550e8400-...` (在其他 ws) | `None` | workspace_id 过滤 |
| `user:<非uuid>` | `user:abc` | `None` | UUID parse fail |
| `role:admin` 多人 | 3 个 admin | `['a@x.com', 'b@x.com', 'c@x.com']` | distinct |
| `role:unknown` | `role:xxxxx` | `None` 或 fallback | 无匹配 → fallback admin |
| `dept:<name>` | `dept:研发部` | `raise NotImplementedError` | Phase 5 留 hook |
| 乱码 | `gibberish` | fallback admin | 不匹配任何 prefix |
| `None` / `''` | None / "" | fallback admin | 同 Phase 3 行为 |

## 测试覆盖矩阵（≥ 12 测试）

| 测试 | resolve / perform | 覆盖点 |
|---|---|---|
| test_resolve_email_returns_single_email_list | resolve | email 兼容 → [email] |
| test_resolve_user_uuid_returns_email | resolve | user: 命中 |
| test_resolve_user_uuid_wrong_workspace_returns_none | resolve | workspace_id 越权防护 |
| test_resolve_user_uuid_invalid_returns_none | resolve | UUID parse fail |
| test_resolve_role_admin_returns_multiple | resolve | role: 多人 |
| test_resolve_role_unknown_returns_fallback | resolve | role: miss → fallback |
| test_resolve_dept_raises_not_implemented | resolve | dept: NotImpl |
| test_resolve_invalid_expr_falls_back | resolve | 乱码 → fallback |
| test_resolve_empty_falls_back | resolve | None / '' |
| test_perform_with_3_role_admins_sends_3_emails | perform | role:admin 多人发邮件 |
| test_perform_writes_3_audit_logs | perform | 多人写多 audit_log |
| test_perform_dept_expression_skips_escalation | perform | dept: catch NotImpl 不阻塞 |
| test_perform_no_escalator_skips | perform | None 跳过 |
| test_perform_logs_structured_escalation_resolved | perform | structured log |

## License & Attribution

- Dify 是 AGPL-3.0；本笔记仅记录设计模式 / 命名规范 / 数据结构思路
- **严禁**复制 Dify 代码到本项目（agent-builder 是 Apache-2.0）
- 本项目实现独立从 0 写起（表达式解析 Dify 无对应代码可抄）

---

*Phase: 04-approval-chain-im*
*Plan: 04-04*
*Reading doc committed as Task 0 (CLAUDE.md §2.7 hard gate)*
