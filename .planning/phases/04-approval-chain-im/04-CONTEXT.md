# Phase 4: 审批链 + IM 通知 - Context

**Gathered:** 2026-05-17
**Status:** Ready for planning

<domain>
## Phase Boundary

实现多人审批链（4 模式：单人 / 顺序 / 并行全员同意 / 或签任一同意）+ 5 家 IM 卡片
通知（飞书 / 企微 / 钉钉 / Slack / Mattermost）+ 审批委托（HITL-06）+ 超时升级
（HITL-04 完整 4 表达式解析模式中的前 3 种 — dept 表达式留 Phase 5）。

**Requirements:** HITL-02, HITL-04, HITL-06, NOTI-02, NOTI-03, NOTI-04, NOTI-05, NOTI-06, NOTI-07

**Phase 4.5（Bot Triggers + Slash 双向 IM）** 是后续插入分支，专做入站 webhook
+ Slash 分发；本 Phase 4 仅做**出站**卡片投递与点击跳 Web 决策。
</domain>

<decisions>
## Implementation Decisions

### 审批链 4 模式语义（HITL-02 + ROADMAP #1-3）

**顺序会签（sequential）**
- A → B → C 链式触发：A 同意后才生成 B 的 token + 发通知；A 拒绝立即终止
- A 拒绝 → B/C **不生成 token，流程立即终止**；写 audit_log `chain.terminated_by_reject` + 实例 status=rejected
- 不发"已终止"补通知给 B/C（他们从未被骚扰，无需补）
- A 退回（return）→ 回到上游 HITL 节点重决策；非链式回滚

**并行会签 — 全员同意（parallel_all）**
- 所有审批人同时收到 token + 通知
- A 拒绝 → **其余 B/C/D 未提交 token 立即失效** + 发"已终止（被 X 拒绝）"补通知
- 所有人同意才推进
- 补通知是轻量邮件 / IM 卡片更新（决策页跳转 410 改为友好"已被处理"页）

**或签 — 任一同意（parallel_any）**
- 所有审批人同时收到 token + 通知
- A 同意 → 其余 B/C/D 未提交 token 立即失效 + 发"已被 A 处理"补通知 + 流程推进
- 任一拒绝 → 全部失效 + 终止（与并行全同 — 拒绝即终止）

**单人审批（single）** — Phase 3 已实现，本 phase 不重做

### 拒绝 ≡ 终止语义

- 拒绝 = 流程立即终止，**不可 retry**（需用户重启新实例）
- 审计完整性 > 操作便利性
- admin 后门 endpoint 留给 Phase 7 可观测性 + 运维工具
- DSL 不引入 `config.on_reject_retry` 类字段（保持四态决策简洁）

### 委托机制 HITL-06

- **委托链深度上限 = 3 层**（A → B → C → D 禁止 — 防委托环 + 责任稀释）
- **委托后原 token 立即失效**，新 token 创建发给被委托人
- 被委托人 token 继承：jti 新生成、actor_id 改为委托人、allowed_actions 沿用、deadline_at 不变（不重置）
- 委托记录写入 `node_state.payload.records` 数组，type='delegate'，含 from_actor / to_actor / reason / ts
- **不需要被委托人主动确认**（被动接受 — 若不响应走原超时催办 + 升级；目标是降低委托摩擦）
- 委托记录在申请人追踪页 + admin 审计都可见（脱敏规则沿用 Phase 3）

### 5 家 IM 卡片设计（NOTI-02/03/04/05/06）

- **各家用原生卡片格式**（不强制统一视觉）：
  - 飞书 interactive card（columns + button block）
  - 企微 template card（text_notice + button_list）
  - 钉钉 ActionCard（btnOrientation=0 横排按钮）
  - Slack Block Kit（section + actions block）
  - Mattermost Markdown attachment（actions array）
- **字段统一**：每张卡片必含 标题 / 申请人 / 审批节点名 / 截止时间倒计时 / 3 按钮（同意 / 退回 / 拒绝）+ 申请详情链接
- **按钮点击 = 跳 Web 决策页**（不在 IM 内表单填写完成决策 — 5 家 button action API 差异过大；Web 决策页已在 Phase 3 完成）
- **决策后卡片更新策略**：
  - 飞书/Slack/Mattermost 支持卡片 update API → 决策后 update 卡片为只读 + 显示"已被 X 决策"
  - 企微/钉钉静态卡片 → 发补卡片"流程已决策"（不更新原卡片）
- **签名验证**：本 Phase 4 仅做**出站**投递；webhook 入站签名验证留 Phase 4.5

### 多通道并发投递（NOTI-08 强化）

- 节点 `config.notify_channels` 数组：`["email", "feishu", "wecom"]` → 并发同发，不分优先级
- 任一通道用户决策即 sibling 失效（其他通道用户点击看到"已被 X 处理"）
- notifications 表已有 UNIQUE 去重约束（Phase 3 03-01 已建），多通道是 channel 维度，不冲突

### 超时升级 HITL-04 完整 4 表达式解析

- `config.escalate_to` 支持 4 种表达式：
  - `email:user@example.com` — Phase 4 实现
  - `user:<uuid>` — Phase 4 实现
  - `role:admin` — Phase 4 实现（解析为 workspace 内 role=admin 用户列表）
  - `dept:研发部` — **Phase 5 实现**（依赖 IM 目录同步）
- **升级 ≡ 原审批人 token 失效** + 新 token 创建给升级目标 + 发新通知（多通道沿用节点 config）
- 原审批人若已点击 token 链接进入决策页但未提交，提交时返回 410（已升级）+ 错误页提示"流程已超时升级"
- **委托优先级 > 升级**：委托后超时计时从委托发生时间重新起算（被委托人有完整 24/48/72h）

### 失效广播

- Phase 3 已有 `HitlTokenStore.invalidate_siblings` — Phase 4 复用，但 sibling 定义从"同 node_state_id"扩展到"同 instance_id 的活跃链节点 token"（chain-level invalidate）
- Phase 4 新增 `invalidate_chain(instance_id, except_jti)` 方法服务并行全/或签的全失效

### Claude's Discretion
- IM Provider 抽象接口的具体方法分布（一个 ImProvider 还是按 send_card / update_card / get_user 分多个接口）
- 各 IM 卡片模板的具体 JSON 字段映射
- arq job 重试在 IM 通道下的 backoff（沿用 Phase 3 1s/2s/4s 模式）
- Provider 工厂注册位置（startup hook vs FastAPI dependency）

</decisions>

<specifics>
## Specific Ideas

- 参考 hr/offboarding-flow 项目的 Provider 抽象（已存在飞书 / Mattermost stub），但本项目重写为自己的 IMProvider Protocol（不复用 hr 代码，仅参考接口设计）
- Dify 参考：`api/core/workflow/email_delivery/` 已读过模式（NotificationService.enqueue_*），IM 通道延续这套通用入队 + arq job + tenacity 重试
- 飞书 SDK 用 `lark-oapi==1.6.5`（CLAUDE.md §3 锁定 — 1.6.0/1/2/3 已 yanked）
- 企微：`wechatpy==1.8.18`（停更，需 spike templated card API 是否仍可用 — 可能需要 fallback Bot webhook）
- 钉钉：`dingtalk-stream==0.24.3`
- Slack：`slack-bolt==1.28.0`
- Mattermost：复用 Phase 4.5 OUTLINE 中已 spike 的 mattermost-driver / mattermostautodriver 二选一（Phase 4 仅出站 webhook，简单 HTTP POST）

</specifics>

<deferred>
## Deferred Ideas

- **Bot 入站 webhook / Slash 分发** → Phase 4.5（已有 OUTLINE.md）
- **IM 目录双向同步** → Phase 5（实现 dept 表达式需要 im_directory 表 + sync 任务）
- **审批人节点 token 跨实例委托审计聚合**（"我帮谁做过多少决策"）→ Phase 7 可观测性
- **admin force-resume 拒绝实例的后门 endpoint** → Phase 7 运维工具
- **IM 卡片 i18n（多语言模板）** → v2
- **IM Bot 主动询问/澄清场景**（B 想加备注问 A） → Phase 4.5 双向 + RAG

</deferred>

---

*Phase: 04-approval-chain-im*
*Context gathered: 2026-05-17*
