# Phase 3: HITL 单节点 + Email 审批 - Context

**Gathered:** 2026-05-17
**Status:** Ready for planning
**P0 价值演示阶段**：本 phase 完成即可演示"邮件深链一键决策推流程"完整主路径

<domain>
## Phase Boundary

HITL 节点（LangGraph `interrupt()`）→ Email 通知（SMTP + Jinja2 模板 + 4 个 token 链接）→ 公网回调 `/hitl/page/*` + `/hitl/action/*` → Token 即登录（30min session cookie）→ 决策页四态提交 → workflow resume（`Command(resume=...)`）→ 申请人追踪页（实例进度可视化）。

**Phase 3 涵盖 13 个 requirements**：
HITL-01, HITL-03, HITL-05, HITL-07, NOTI-01, NOTI-08, NOTI-09, NOTI-10, AUTH-04, AUTH-05, NET-05, NODE-02, NODE-07

**Phase 3 不做（在后续 phase）**：
- 审批链多人模式（HITL-02 / HITL-04 → Phase 4）
- 委托/转交（HITL-06 → Phase 4）
- IM 通知（NOTI-02..07 → Phase 4）
- Mattermost bot 双向接入（→ Phase 4.5）

</domain>

<decisions>
## Implementation Decisions

### HITL 节点状态机 + interrupt payload

- **node_states.payload schema**（保存审批链所有可重现状态）：
  ```python
  {
    "phase": "submit" | "review",  # 当前阶段
    "current_actor": {"id": "u_xxx", "email": "...", "role": "executor|reviewer"},
    "approval_chain": {
      "mode": "single",  # Phase 3 仅 single；其它 sequential/parallel_all/parallel_any → Phase 4
      "approvers": [resolved_user_ids],
      "current_idx": 0,
    },
    "records": [
      {"actor_id": "...", "actor_email": "...", "action": "submit|approve|return|reject",
       "reason": "可选文本", "form_data": {}, "ts": "ISO8601", "ip": "...", "ua": "..."}
    ],
    "pending_approvers": [user_ids],  # 仅 review 阶段用
    "started_at": "ISO8601",
    "deadline_at": "ISO8601",
    "form_schema": {...}  # 决策页表单字段定义（JSON Schema）
  }
  ```

- **LangGraph interrupt + resume**：
  ```python
  # HITL 节点函数
  async def hitl_execute(state, config):
      decision = interrupt({
          "node_state_id": ...,
          "form_schema": ...,
          "deadline_at": ...,
          "phase": "submit",
      })
      # decision = {action, reason, form_data} from Command(resume=...)
      return {"decision": decision, "completed_at": now()}
  ```
  - 终态满足时：`graph.invoke(Command(resume={action, reason, form_data}), config={"configurable": {"thread_id": instance_id}})`
  - 中间态（仅多人审批链才有，Phase 3 单人不会）：仅 update node_state.payload，不动 LangGraph

- **节点 status 5 态 + 3 终态**（与 02-CONTEXT.md §5.1 一致）：
  ```
  pending → waiting_human → in_review → done | rejected | returned
  ```
  - `pending`：节点已入 DAG 但 enter 函数还没跑
  - `waiting_human`：执行人提交前
  - `in_review`：执行人 submit 后 → 进入审核（**Phase 3 单人模式下，submit 直接走到 review，再 approve = done**）
  - `done` / `rejected` / `returned`：终态

- **Deadline 与超时**：
  - 节点 enter 时 `payload.deadline_at = now() + node_config.timeout_seconds`（默认 24h）
  - **arq 后台 worker** 每分钟扫一次：`SELECT * FROM node_states WHERE status IN ('waiting_human','in_review') AND deadline_at < now()`
  - 触发超时升级路径（详见 §邮件模板 + 超时催办策略）

### Token 4-action 设计 + 安全细节

- **Token 批量生成**：节点 enter 时为 current_actor 的每个 `allowed_action` 生成独立 JWT token：
  - 执行人阶段：`submit / return / reject` → 3 个 token，1 封邮件含 3 个按钮
  - 审核人阶段：`approve / return / reject` → 3 个 token，1 封邮件含 3 个按钮
  - JWT payload：`{iss, aud:"hitl", iat, exp, jti, flow_id, node_state_id, actor_id, role, allowed_actions:[ACTION], ...}`
  - HMAC HS256 签名（HMAC_SECRET ≥ 32 字节，启动校验 — Phase 1 已落）

- **jti 一次性存储**：
  ```sql
  hitl_tokens (
    jti UUID PK,
    instance_id UUID,
    node_state_id UUID,
    actor_id UUID,
    action VARCHAR(16),  -- submit/approve/return/reject
    expires_at TIMESTAMP,
    used_at TIMESTAMP NULL,
    used_ip VARCHAR(64) NULL,
    used_ua VARCHAR(256) NULL
  )
  ```
  - **Postgres 是权威**；Redis (TTL 24h) 是加速缓存（`SET NX agent_builder:jti:<id> 24h`）
  - 检查顺序：Redis → Postgres（cache miss 时）

- **Safe Links bot UA 白名单**（Pitfall 3 P0 防护）：
  ```python
  BOT_UA_PATTERNS = (
      "microsoftdefender",  # MS Defender Safe Links
      "outlook-safelinks",  # Outlook Safe Links
      "slackbot-linkexpanding",
      "twitterbot",
      "facebookexternalhit",
      "linkedinbot",
      "whatsapp",
      "googlebot",
      "telegrambot",
      "discordbot",
      "duckduckbot",
      "baiduspider",
      "bingbot",
  )
  def is_bot_ua(ua: str) -> bool: return any(p in ua.lower() for p in BOT_UA_PATTERNS)
  ```
  - `GET /hitl/page/<token>` 检测到 bot UA → 返回静态 HTML "您看到的是邮件扫描，未触发任何状态变更"（不签 cookie / 不动 jti / 不写 token.viewed）
  - 检测不到 bot UA → 正常签 session cookie + 标记 `viewed_at`（但 jti 仍未消费）

- **Token 生命周期**：
  1. node enter → batch 生成 3 token（actor 当前阶段允许的 action）→ 写 `hitl_tokens` → 发邮件
  2. 用户点 link → `GET /hitl/page/<token>`
     - 校验签名 + exp + jti 未消费
     - bot UA 直接返回静态页
     - 真实用户：签 30min session cookie（httpOnly + secure）+ 渲染决策表单
  3. 用户点按钮提交 → `POST /hitl/action/<token>`（cookie + form data）
     - 校验 cookie session ↔ jti 一致 → 加 advisory lock(thread_id) → 消费 jti
     - **同节点其他未消费 token 一并 invalidate**：`UPDATE hitl_tokens SET used_at=now() WHERE node_state_id=? AND used_at IS NULL`（DB 事务原子）+ Redis pipeline DEL
     - 写 `action_logs`（NET-05 决策审计 — IP/UA/ts/decision）
     - `graph.invoke(Command(resume={action, reason, form_data}), config)`
     - 返回成功页面
  4. 同 token 重提交 → jti 已消费 → 返回 409 + 友好提示

- **公网路径暴露**（Phase 1 NET-02 已锁定）：仅 `/hitl/page/*` + `/hitl/action/*` + `/api/im/webhook/*` 通过 public nginx server_block；其它路径 403

### 决策页 UI / UX

- **表单模式**（非简单按钮直接消费）：
  - 显示当前 actor、phase（提交 vs 审核）、申请详情、流程上下文（state 关键字段）、历史 records（前序谁做了什么）
  - 表单字段：
    - **action**（必选）：单选/按钮组（提交 / 退回 / 拒绝 或 通过 / 退回 / 拒绝）
    - **reason**（可选，建议必填于退回/拒绝）：textarea
    - **form_data**（动态字段，按 `payload.form_schema` 渲染）
  - 移动端响应式适配（Tailwind 默认）

- **附件上传**：**v1 不做**（避免文件存储+病毒扫描复杂度），form_data 仅文本/数字/枚举字段。附件 → Phase 7 增强

- **超时显示**：静态显示 `deadline_at` 倒计时（前端 `setInterval(1000)` 更新展示，不轮询后端）。超时后页面禁用提交按钮，提示"已超时，请联系 admin"

- **撤销已提交**：**v1 不可撤销**（jti 一次性，符合审计要求）。如需修改 → 走"撤销重提"（admin 操作，Phase 7）

- **决策成功页**：显示"已记录您的决策"+ 当前流程状态 + 链接（如可登录则可去 dashboard，未登录则提示流程进度页 — HITL-07 申请人追踪页同款）

### 申请人追踪页（HITL-07）

- 路径：`/dashboard/instances/<id>/tracking`（已登录用户）
- 信息：
  - 实例当前阶段（哪个节点正在等谁）
  - 完整 records 时间线（哪步谁做了什么 / 何时）
  - 当前节点截止时间
- 隐私：申请人能看到**审批人姓名 + 决策 + 时间**（不能看到 IP / UA）；admin 能看全
- 路由权限：实例的 `applicant_id == current_user.id` 才可访问，否则 403

### 邮件模板 + 超时催办策略

- **邮件 HTML 设计**（Jinja2 模板）：
  - **品牌头**：agent-builder logo + "审批通知" 标题
  - **正文**：申请人 / 流程 / 节点 / 描述（来自 form_schema.description）
  - **截止时间**：明文显示
  - **3 个 action 按钮**：颜色区分（绿/黄/红 或 蓝/灰/红）+ 点击跳深链
  - **footer**：发件方 + "这是系统业务邮件，不可退订" 提示
  - **明文 fallback**：含纯文本版本（4 个 URL 列在底部）

- **多语言**：v1 中文 only（i18n 留 v2）

- **SMTP 失败重试**（NOTI-10）：
  - arq queue `notifications` 入队，aiosmtplib 发
  - 失败 → tenacity 重试 3 次指数退避（1s/2s/4s）
  - 全 fail → 写 `notifications.status='failed' + error_message`，触发 admin 告警（管理员后台 / IM）

- **催办策略**（NOTI-09 + 超时升级）：
  - 节点 enter 时 `deadline_at = now() + timeout` (默认 24h，节点可配)
  - **24h 节点未提交 → 首次催办**：再发同样邮件 + 主题加 `[催办]` 前缀
  - **48h 未提交 → 二次催办**
  - **72h（或节点 config.escalate_after）未提交 → 升级到 HR/admin**：
    - 重新解析升级人（节点配置 `escalate_to: role:admin` 或 `escalate_to: dept:HR`，复用 Phase 5 assignee resolver；Phase 3 简化为 `escalate_to: user_email`）
    - 把升级人加入 current_actor，发邮件给升级人
    - records 加 `{action: "escalate", actor: "system", reason: "timeout", ts: ...}`

- **去重 / 并发**：催办 worker 用 `notifications` 表去重（`(instance_id, node_state_id, channel, recipient, reminder_round)` UNIQUE）；同时刻多 worker 抢锁不重发

### Claude's Discretion（未指定）

- **Workflow Trigger 节点**：v1 通过 API `POST /api/agent_builder/v1/workflows/<id>/instances` 启动；不做 IM trigger（→ Phase 4.5）
- **邀请人 / Applicant 字段**：从 instance 启动时的 `creator_id` 或 form 字段 `applicant_email` 取
- **HITL 节点配置 UI**：Canvas 节点点击右侧 panel 编辑（form_schema + assignees + timeout_seconds + escalate_to）
- **form_schema**：JSON Schema 子集（type: object，properties 为各字段，required 数组）；前端用 RJSF 或 react-hook-form + zod 渲染
- **Sentry / 监控接入**：v1 不接（Phase 7）
- **国际化日期格式**：v1 中文格式 `2026-05-17 14:23:00`
- **邮件预览**：admin 配置邮件模板时可预览（v1.x，Phase 7 增强；v1 模板固定）

</decisions>

<specifics>
## Specific Ideas

- **参考 hr/offboarding-flow** (CLAUDE.md 2.7 reading doc gate)：
  - hr/PRD.md §7 双通道通知 + §8 LangGraph interrupt + Postgres saver — 与本 phase 设计同源
  - hr/ 已实现的 email + Mattermost notification 路径 → 借鉴
- **参考 Dify**（CLAUDE.md 2.7 reading doc gate）：
  - `api/core/workflow/human_input_adapter.py` + `api/models/human_input.py`：HITL 表单与 token 的关系
  - `api/core/workflow/email_delivery/mail_human_input_delivery_task.py`：邮件模板与 token 链接的拼装
  - 我们用 LangGraph 原生 interrupt + 自管 hitl_tokens 表（Dify 用 graphon），所以**借鉴模式 不照抄结构**
- **Outlook Safe Links 真实测试 UA 串**：
  ```
  Mozilla/5.0 (compatible; AC-Detector-Tool/1.0; +safelinks.protection.outlook.com)
  ```
  集成测试中模拟此 UA，断言 jti 未消费 + 返回静态页

</specifics>

<deferred>
## Deferred Ideas

- **多人审批链 4 模式**（HITL-02）→ Phase 4
- **任务委托 / 转交**（HITL-06）→ Phase 4
- **IM 通知卡片**（NOTI-02..07）→ Phase 4
- **Mattermost bot 入站 trigger**（→ Phase 4.5 OUTLINE）
- **附件上传**（决策页 + 邮件附件）→ Phase 7
- **撤销已提交（撤销重提）**→ Phase 7
- **邮件模板可视化编辑器**→ Phase 7
- **i18n 多语言模板**→ v2
- **审计日志导出 CSV/Excel**→ Phase 7
- **决策页移动 App 原生体验**→ v2+

</deferred>

---

*Phase: 03-hitl-email*
*Context gathered: 2026-05-17*
