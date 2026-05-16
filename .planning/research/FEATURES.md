# Feature Research

**Domain:** 可视化拖拽式 LangGraph 工作流编排平台 + 多通道 HITL 审批
**Researched:** 2026-05-16
**Confidence:** HIGH（竞品功能来自官方文档 + WebFetch；HITL UX 来自多源交叉验证）

---

## 竞品对标快速索引

| 平台 | 类型 | 核心差异点 |
|------|------|-----------|
| **n8n** | 通用自动化 | Wait node 实现 HITL，1200+ 集成，无 approval chain 概念 |
| **Dify** | LLM 应用平台 | 无原生 HITL 审批节点，强 RAG + 模型管理 |
| **Langflow** | LLM 可视化构建 | 原生集成 LangGraph，无独立 approval UX |
| **Flowise** | 低代码 LangChain | 拖拽 RAG，v3.1 加 AgentFlow SDK，无 HITL |
| **Coze Studio** | Agent 开发平台 | 拖拽节点，LLM/条件/API 节点，无 HITL 审批链 |
| **Bisheng** | 企业 LLM DevOps | 循环/并行/批处理，HITL 有基础介入，不支持邮件深链 |
| **Camunda** | BPMN 工作流引擎 | 完整 Human Task（Tasklist + Form Builder + SLA），重 |
| **Temporal** | 持久执行引擎 | Signal 驱动 HITL，纯代码，无低代码 UI |
| **Kestra** | 数据编排 | YAML-first，1200+ 插件，无 HITL 审批 |
| **Windmill** | 开发者工作流 | 脚本驱动，内置 App Builder，无审批概念 |
| **Kissflow / ServiceNow** | 企业 BPM | 完整审批 UX，SLA/升级/委托/审计，重量级 |

---

## 一、Table Stakes（用户默认期待，缺失即流失）

### 1.1 编辑器与画布

| 功能 | 为何必要 | 复杂度 | 参考竞品 | 备注 |
|------|----------|--------|----------|------|
| 拖拽节点 / 连线 / 删除 | 所有可视化平台标配 | LOW | n8n、Dify、Coze、Langflow 全有 | PROJECT.md EDIT-01 已覆盖 |
| 节点配置面板（动态表单） | 参数配置必须在画布内完成，跳出即体验断裂 | MEDIUM | n8n、Dify | PROJECT.md EDIT-02 已覆盖 |
| 草稿 / 发布版本分离 | 编辑中的流程不应覆盖运行中的版本 | MEDIUM | n8n（Staging）、Dify（草稿） | PROJECT.md EDIT-03 已覆盖 |
| DSL 导出 / 导入（JSON） | 迁移、备份、Git 版本管理的最低要求 | LOW | n8n 支持，Dify 支持 | PROJECT.md EDIT-04 已覆盖 |
| **执行历史 / 运行列表** | 用户需要知道哪些实例在跑、结果如何 | LOW | n8n Executions 页、Dify 日志 | **PROJECT.md 仅 EXEC-04 提 Timeline，缺独立运行列表** |
| **节点级步进调试（Debug 模式）** | 可视化平台调试无 debug 等于盲飞 | MEDIUM | n8n 可逐节点测试，Dify 有 Debug 面板 | **PROJECT.md 完全缺失** |

### 1.2 节点类型

| 功能 | 为何必要 | 复杂度 | 参考竞品 | 备注 |
|------|----------|--------|----------|------|
| Start / End | 工作流基础边界 | LOW | 全部平台 | PROJECT.md NODE-01 已覆盖 |
| LLM 调用节点 | 核心 AI 能力入口 | LOW | Dify、Coze、Langflow | PROJECT.md NODE-05 已覆盖 |
| If-Else 条件分支 | 基础条件路由 | LOW | 全部平台 | PROJECT.md NODE-03 已覆盖 |
| HTTP API / Tool 节点 | 对接外部系统的最小接口 | LOW | n8n（HTTP Request）、Coze | PROJECT.md NODE-06 已覆盖 |
| Code 节点（Python 沙箱） | 复杂逻辑兜底，缺失则无法处理边缘情况 | MEDIUM | Dify（Python/JS），Langflow | PROJECT.md NODE-09 已覆盖 |
| 并行扇出 / 汇合 | 多路并发是现实业务要求 | MEDIUM | Dify、Bisheng | PROJECT.md NODE-04 已覆盖 |
| Loop / for-each | 批量处理场景必须 | MEDIUM | Dify、Bisheng | PROJECT.md NODE-10 已覆盖 |
| Subgraph（嵌套工作流） | 复用性；复杂流程分解 | HIGH | Dify、Langflow | PROJECT.md NODE-08 已覆盖 |

### 1.3 执行引擎

| 功能 | 为何必要 | 复杂度 | 参考竞品 | 备注 |
|------|----------|--------|----------|------|
| 实例运行 / 暂停 / 恢复 / 中止 | 生产环境管控的基本操作 | MEDIUM | n8n、Camunda | PROJECT.md EXEC-03 已覆盖 |
| Checkpoint 持久化（崩溃恢复） | 长运行流程必须抗崩溃 | HIGH | Temporal（durable exec）、Camunda | PROJECT.md EXEC-02 已覆盖（PostgresSaver） |
| **运行实例列表 + 状态过滤** | 运维必须能找到挂起/失败的实例 | LOW | n8n、Camunda Cockpit | **PROJECT.md 未列出，EXEC-04 仅提 Timeline** |
| **节点执行时间线（Timeline）** | 调试和 SLA 监控的视觉呈现 | MEDIUM | n8n、Camunda | PROJECT.md EXEC-04 已提 |
| **错误重试 / 手动重驱** | 外部依赖偶发失败，无重试等于不可用 | MEDIUM | n8n（retry on failure），Temporal | **PROJECT.md 缺失** |

### 1.4 HITL 审批（审批产品的核心 Table Stakes）

以下是对标 Camunda / Kissflow / ServiceNow 后提炼的审批工作流 Table Stakes：

| 功能 | 为何必要 | 复杂度 | 参考竞品 | 备注 |
|------|----------|--------|----------|------|
| 单人审批 + 邮件通知 | 最基础审批场景 | LOW | n8n Wait+Email，Activepieces Email Approval | PROJECT.md HITL-01/NOTI-01 已覆盖 |
| 审批链（顺序 / 并行全 / 或签） | 复杂审批流的现实需求 | HIGH | Camunda（顺序/并行）、Kissflow | PROJECT.md HITL-02 已覆盖 |
| 审批超时 + 升级策略 | SLA 合规；防止流程卡死 | MEDIUM | Camunda SLA、Kissflow 升级 | PROJECT.md HITL-04 已覆盖 |
| **任务委托 / 转交（Delegation）** | 审批人出差/请假场景；企业审批必备 | MEDIUM | Camunda Delegation、ServiceNow、Kissflow | **PROJECT.md 缺失** |
| **任务重新分配（Reassignment）** | 审批人离职或权限变化 | LOW | Camunda、ServiceNow | **PROJECT.md 缺失** |
| 决策表单配置（JSON Schema） | 审批操作需要收集结构化数据 | MEDIUM | Camunda Form Builder | PROJECT.md HITL-05 已覆盖 |
| **审批意见（Reason / Comment）** | 拒绝/退回时必须留说明，合规和沟通需要 | LOW | 所有企业审批产品均有 | **PROJECT.md 在 action_logs 有 reason 字段但 UI 层未明示** |
| Token 一次性消费防重放 | 邮件链接安全的最低要求 | MEDIUM | activepieces、n8n（无内置，需手动） | PROJECT.md AUTH-05 已覆盖 |
| **审批状态可见（申请人侧）** | 申请人需要知道流程走到哪一步 | LOW | Kissflow、ServiceNow | **PROJECT.md 缺失（目前只有管理员视图）** |
| **催办 / 提醒（Reminder）** | 审批超时前主动提醒，减少不必要升级 | LOW | Kissflow、Camunda | **PROJECT.md 缺失** |

### 1.5 认证与权限

| 功能 | 为何必要 | 复杂度 | 参考竞品 | 备注 |
|------|----------|--------|----------|------|
| 邮箱注册 + 密码登录 | 最基础账号体系 | LOW | 全部 | PROJECT.md AUTH-01 已覆盖 |
| RBAC（角色访问控制） | 多人协作必须有权限隔离 | MEDIUM | n8n、Dify、Camunda | PROJECT.md AUTH-03 已覆盖 |
| Token 即登录（无摩擦外部审批） | 外部审批人不需注册账号 | MEDIUM | 仅 activepieces 有类似设计 | PROJECT.md AUTH-04 已覆盖（差异化） |

### 1.6 通知

| 功能 | 为何必要 | 复杂度 | 参考竞品 | 备注 |
|------|----------|--------|----------|------|
| Email 通知 | 最低通知基线，无 Email 审批产品不成立 | LOW | 全部平台 | PROJECT.md NOTI-01 已覆盖 |
| 通知模板可配置 | 不同业务需要不同邮件内容 | LOW | n8n、Camunda | PROJECT.md NOTI-01 有 Jinja2 模板 |
| **通知发送失败处理 + 重试** | 邮件发不出去审批就卡死 | LOW | 企业邮件发送最佳实践 | **PROJECT.md 缺失** |

---

## 二、Differentiators（真正的竞争优势）

| 功能 | 价值主张 | 复杂度 | 参考竞品 | 备注 |
|------|----------|--------|----------|------|
| **多 IM 通道并行推送（飞书+企微+钉钉+Slack+Mattermost）** | 中国企业市场覆盖全；竞品中无一平台同时支持这 5 个 IM | HIGH | n8n 支持 Slack，不支持中国 IM；Dify/Langflow/Coze 无原生 IM 审批 | PROJECT.md NOTI-02~06 已覆盖 |
| **四态决策（submit/return/reject → approve/return/reject）** | 区分"执行人"和"审核人"职责，比二态（approve/reject）更贴近企业审批现实 | MEDIUM | Camunda 支持，但非默认；其他 AI 平台均为二态 | PROJECT.md HITL-01 已覆盖 |
| **IM L3 双向同步（用户/部门/汇报关系）** | 不依赖手动维护用户表；节点 assignee 可填部门/表达式 | HIGH | 无竞品同时做 IM 账号同步 + workflow assignee 联动 | PROJECT.md IM-01~05 已覆盖 |
| **LangGraph 原生 + PostgresSaver 持久化** | 比 n8n 的 Wait node 更健壮；支持复杂状态机；比 Temporal 更低代码 | HIGH | Langflow 做了 LangGraph 集成但无 HITL 审批 UX | PROJECT.md EXEC-01/02 已覆盖 |
| **节点 Assignee 多形态（email / @user / dept:xxx / dynamic_expr）** | 动态路由审批人；企业组织架构变化不影响流程 | MEDIUM | Camunda 有 Assignment 表达式，但与 IM 无联动 | PROJECT.md IM-05 已覆盖 |
| **DSL 解释执行（热更新）** | 修改流程不需要重启；实例锁版本；与 Dify/n8n 同路但更 LangGraph-native | MEDIUM | Dify、n8n 均用解释执行；Langflow 生成代码 | PROJECT.md EXEC-01 已覆盖 |
| **公网最小暴露面（nginx 仅放行 HITL/IM 路径）** | 内网部署 + 公网审批的安全平衡；竞品未见此设计 | MEDIUM | 无竞品公开此设计 | PROJECT.md NET-01/02 已覆盖 |
| **插件系统（zip包 + 沙箱 + NodeRegistry）** | 第三方节点扩展是平台化产品的必经之路 | HIGH | Dify Plugin Daemon（类似）；n8n 自定义节点（无沙箱） | PROJECT.md PLUG-01~04 已覆盖 |
| **Workspace 多租户隔离** | 支持团队内多个业务线并行使用 | MEDIUM | Dify 有 Workspace；n8n 企业版有 | PROJECT.md AUTH-06 已覆盖 |

---

## 三、Anti-Features（明确不做的功能）

| 反功能 | 为何避免 | 替代方案 |
|--------|----------|----------|
| **IM 内一键决策（Bot 直接消费 token）** | 各 IM 适配器都要承担 token 校验、actor 解析逻辑，重复且易出错；且 IM 平台策略不稳定（webhook URL 变更等） | IM 卡片 = 邮件深链等价物，点击跳 Web 决策页；v1.1 再做 IM-native 决策 |
| **实时双人协作编辑画布** | 分布式锁 + CRDT 实现复杂；工作流编辑非实时协作场景 | 草稿锁（乐观锁 + 版本冲突提示）即可 |
| **完整工作流模板市场（前台）** | v1 仅验证核心引擎；市场需要治理、评分、付费体系 | 本地预置模板（hr 离职模板等） |
| **多模型 Provider 池 UI** | 增加配置复杂度；v1 一个 LLM 即可跑通 | 抽象 LLM adapter，接 GLM；v2 增加 Provider 选择 |
| **节点级 CPU/内存配额 UI** | 沙箱自身有硬限制；配置 UI 价值小、复杂度高 | manifest.yaml 静态声明资源限制即可 |
| **移动端 App（iOS/Android）** | 审批人用手机点邮件链接即可，移动 App 是额外摩擦 | Email 深链 + 移动浏览器自适应 |
| **完整 i18n（国际化）** | v1 只有中文用户；工程成本高 | v1 中文 only，v2 再做 i18n |
| **完整插件 PKI 签名验证** | 密钥分发和验证体系复杂；v1 管理员手动审核足够 | 管理员上传 + dry-run 沙箱验证 |
| **工作流运行中热迁移 DSL** | 实例中途改 DSL 需要状态兼容性保证，极复杂 | 实例锁定创建时的 DSL 版本；新版本仅影响新实例 |
| **实时 AI 生成工作流（自然语言 → DSL）** | 生成质量不可控；不在核心价值主张内 | 手动拖拽 + 预置模板 |
| **原生 OAuth SSO（SAML/OIDC）** | v1 自建账号体系足够；OAuth 集成需要企业 IdP 配合 | 预留接口，v2 实现 SSO |

---

## 四、Feature Dependencies（功能依赖关系）

```
[AUTH-01 自建账号] ──requires──> [AUTH-03 RBAC]
                                      └──requires──> [AUTH-06 Workspace 多租户]

[EDIT-01 拖拽画布]
    └──requires──> [EDIT-02 节点配置面板]
                       └──requires──> [NODE-01~10 节点类型实现]

[EXEC-01 DSL 编译执行]
    └──requires──> [EDIT-03 草稿/发布版本]
    └──requires──> [EXEC-02 PostgresSaver Checkpoint]

[HITL 审批流 HITL-01~05]
    └──requires──> [EXEC-02 Checkpoint]（interrupt + resume 需要持久化）
    └──requires──> [AUTH-04 Token 即登录]
    └──requires──> [NOTI-01 Email 通道]（最小通知基线）
    └──requires──> [NET-01/02 公网入口 + nginx]

[NOTI-02~06 IM 通道]
    └──enhances──> [HITL-01 HITL 节点]
    └──requires──> [IM-04 IM 用户匹配]（推送到正确的人）

[IM-01~03 IM 目录同步]
    └──requires──> [IM-04 邮箱匹配本地账号]
    └──enables──> [IM-05 Assignee 多形态表达式]

[PLUG-01~04 插件系统]
    └──requires──> [EXEC-01 DSL 执行引擎]（插件节点需要注册进 NodeRegistry）
    └──requires──> [AUTH-03 RBAC]（管理员审核插件）

[补充：任务委托（Delegation）— 缺失]
    └──requires──> [AUTH-02 用户 Profile]
    └──requires──> [HITL-01 HITL 节点]
    └──requires──> [NOTI 通知]（通知被委托人）

[补充：错误重试（Error Retry）— 缺失]
    └──requires──> [EXEC-01 DSL 执行引擎]
    └──requires──> [EXEC-04 状态 Timeline]（显示重试次数）
```

### 依赖注解

- **HITL 审批链依赖 Checkpoint**：LangGraph 的 interrupt/resume 机制必须有持久化后端，否则服务重启审批状态丢失。PostgresSaver 是此链条中优先级最高的基础设施。
- **IM 通道依赖 IM 目录同步**：如果 NOTI-02/03/04 在 IM-01/02/03 目录同步之前上线，则只能推送给手动配置了 IM open_id 的用户，体验大打折扣。推荐 IM 通知和 IM 目录同步同一 milestone 交付。
- **插件系统与 DSL 引擎强耦合**：插件节点的注册、调用都依赖 NodeRegistry 和 DSL 解释器，必须在引擎稳定后再开发插件系统。
- **Token 即登录是 HITL 邮件审批的前提**：外部审批人（external 角色）无法普通登录，必须先有 AUTH-04 才能让他们访问决策页。

---

## 五、PROJECT.md 漏洞清单（Gaps）

下表列出竞品分析发现的、PROJECT.md 当前版本未覆盖的功能。每项均标注优先级建议。

| Gap | 类型 | 严重程度 | 建议 |
|-----|------|----------|------|
| **节点级步进调试 / Debug 模式** | Table Stakes | HIGH | 必须加入 v1。无调试能力的低代码平台无法让非编码人员自助排障。建议加 EDIT-05。 |
| **运行实例列表页（状态过滤 + 搜索）** | Table Stakes | HIGH | EXEC-04 仅描述 Timeline，缺少实例列表视图。运维无从管理大量实例。建议加 EXEC-05。 |
| **任务委托 / 转交（Delegation）** | Table Stakes | HIGH | 企业审批场景必备。审批人出差无法处理，需要转给他人。Camunda/Kissflow/ServiceNow 全有。建议加 HITL-06。 |
| **申请人状态可见（流程追踪页）** | Table Stakes | MEDIUM | 申请人提交表单后完全失去反馈。竞品均有"我的申请"视图。建议加 HITL-07。 |
| **催办 / 提醒（Reminder 通知）** | Table Stakes | MEDIUM | 超时升级前的主动提醒。减少不必要 escalation。加到 NOTI 类，建议 NOTI-09。 |
| **通知发送失败重试** | Table Stakes | MEDIUM | 邮件发送偶发失败（SMTP 限流/网络）需要重试队列。当前设计无此容错。 |
| **节点错误重试策略配置** | Table Stakes | MEDIUM | Tool/API 节点调用外部接口会偶发失败，需要 retry + backoff。n8n 有。建议加 EXEC-06。 |
| **执行历史全局视图（跨实例）** | Table Stakes | LOW | 管理员需要跨工作流查看所有运行记录。当前 EXEC-04 仅针对单实例。 |
| **审批意见 UI（前端 Reason/Comment 字段）** | Table Stakes | LOW | action_logs 有 reason 字段但 PROJECT.md 未在 UI 层明确展示。拒绝/退回不填说明是企业合规隐患。 |
| **审批人头像 / 决策进度可视化** | Differentiator | LOW | 审批链进度卡片（已通过 N/M 人），提升审批体验。Kissflow 有。可 v1.x 加。 |
| **工作流变更历史（DSL diff）** | Differentiator | LOW | 版本对比，知道"谁在什么时候改了什么"。n8n 企业版有 Git 集成。可 v2。 |
| **AI 建议节点（Copilot）** | Differentiator | LOW | 输入自然语言推荐节点类型。Dify、n8n 有探索。v2 方向。 |

---

## 六、MVP 定义

### v1 必须交付（Launch With）

- [ ] **拖拽画布 + 节点配置面板**（EDIT-01/02）— 产品存在的基础
- [ ] **草稿 / 发布版本分离**（EDIT-03）— 防止编辑中覆盖运行版本
- [ ] **Start / End / LLM / Tool / HITL / If-Else / Parallel / Notification 节点**（NODE-01~07）— 覆盖 90% 审批场景
- [ ] **DSL 解释执行 + PostgresSaver Checkpoint**（EXEC-01/02）— 引擎稳定是一切的基础
- [ ] **实例运行/暂停/恢复/中止 + Timeline**（EXEC-03/04）— 基本运维能力
- [ ] **HITL 四态 + 审批链 4 种模式 + 超时升级**（HITL-01~04）— 核心差异化
- [ ] **Email 通道 + Token 深链按钮**（NOTI-01，AUTH-04/05）— 最小可用审批路径
- [ ] **节点步进调试**（新增，弥补 Gap）— 非编码用户自助排障的必要工具
- [ ] **运行实例列表页**（新增，弥补 Gap）— 运维管理能力
- [ ] **任务委托**（新增，弥补 Gap）— 企业审批场景不可缺
- [ ] **自建账号 + RBAC（含 external 角色）**（AUTH-01~03）— 权限基础

### v1.x 追加（After Validation）

- [ ] **飞书 / 企微 / 钉钉 IM 通知卡片**（NOTI-02~04）— 验证 Email 路径后追加 IM
- [ ] **IM 目录同步**（IM-01~05）— IM 通知上线后联动
- [ ] **申请人流程追踪页**（弥补 Gap）— 用户反馈驱动
- [ ] **催办 / 提醒通知**（弥补 Gap）— 降低 SLA 违规率
- [ ] **通知发送失败重试**（弥补 Gap）— 提升可靠性
- [ ] **节点错误重试策略**（弥补 Gap）— 提升引擎鲁棒性
- [ ] **DSL 导出 / 导入**（EDIT-04）— 便于迁移

### v2+ 延后（Future Consideration）

- [ ] **Slack / Mattermost 通知**（NOTI-05/06）— 国际化场景
- [ ] **Code 节点 / Loop 节点 / Subgraph 节点**（NODE-09/10/08）— 高级场景
- [ ] **插件系统**（PLUG-01~04）— 平台化方向
- [ ] **Workspace 多租户**（AUTH-06）— SaaS 化方向
- [ ] **工作流变更历史 / DSL diff**（Differentiator）
- [ ] **OAuth SSO**（AUTH 扩展）
- [ ] **移动端优化 / App**（anti-feature for v1）

---

## 七、功能优先级矩阵

| 功能 | 用户价值 | 实现成本 | 优先级 |
|------|----------|----------|--------|
| 拖拽画布 + 节点面板 | HIGH | MEDIUM | P1 |
| DSL 解释执行 + Checkpoint | HIGH | HIGH | P1 |
| HITL 四态 + 邮件深链 | HIGH | HIGH | P1 |
| 审批链 4 种模式 | HIGH | MEDIUM | P1 |
| 自建账号 + RBAC | MEDIUM | LOW | P1 |
| Token 即登录 | HIGH | LOW | P1 |
| 实例 Timeline + 列表页 | MEDIUM | LOW | P1 |
| 节点步进调试 | HIGH | MEDIUM | P1 |
| 任务委托（新增） | HIGH | LOW | P1 |
| 飞书/企微/钉钉通知 | HIGH | MEDIUM | P2 |
| IM 目录同步 | MEDIUM | HIGH | P2 |
| 申请人追踪页（新增） | MEDIUM | LOW | P2 |
| 催办提醒（新增） | MEDIUM | LOW | P2 |
| 错误重试策略（新增） | MEDIUM | LOW | P2 |
| 插件系统 | MEDIUM | HIGH | P3 |
| Workspace 多租户 | LOW | MEDIUM | P3 |
| Code / Loop / Subgraph 节点 | LOW | MEDIUM | P3 |
| Slack / Mattermost | LOW | LOW | P3 |

---

## 八、竞品功能对照表

| 功能维度 | n8n | Dify | Langflow | Camunda | Kissflow | agent-builder (本项目) |
|----------|-----|------|----------|---------|---------|----------------------|
| 拖拽画布 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| LLM 节点 | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| HITL 审批链 | 🔶 Wait node，无链 | ❌ | ❌ | ✅ 重 | ✅ 重 | ✅ 轻量 |
| 四态决策（执行/审核分离） | ❌ | ❌ | ❌ | 🔶 | ✅ | ✅ 差异化 |
| 邮件深链 Token | 🔶 需自建 | ❌ | ❌ | ❌ | ✅ | ✅ |
| Token 即登录（零注册审批） | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ 差异化 |
| 中国 IM（飞书/企微/钉钉） | ❌ | ❌ | ❌ | ❌ | 🔶 部分 | ✅ 差异化 |
| IM 账号目录同步 | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ 差异化 |
| LangGraph 原生支持 | ❌ | ❌ | ✅ | ❌ | ❌ | ✅ |
| Checkpoint 持久化 | 🔶 内存/DB | ❌ | ❌ | ✅ | ✅ | ✅ PostgresSaver |
| 任务委托 | ❌ | ❌ | ❌ | ✅ | ✅ | **计划 v1（补 Gap）** |
| 节点调试模式 | ✅ | ✅ | ✅ | 🔶 | 🔶 | **计划 v1（补 Gap）** |
| 插件市场 | ✅ | ✅ Plugin Daemon | 🔶 | 🔶 | ❌ | v1 基础版 |
| 申请人状态追踪 | ❌ | ❌ | ❌ | ✅ | ✅ | **计划 v1.x（补 Gap）** |
| 审批超时升级 | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| DSL 导出/导入 | ✅ | ✅ | ✅ | 🔶 | ❌ | ✅ |
| 公网最小暴露面设计 | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ 差异化 |

> ✅ = 支持，❌ = 不支持，🔶 = 部分支持 / 需要额外配置

---

## 来源

- [n8n Human-in-the-Loop 文档](https://docs.n8n.io/advanced-ai/human-in-the-loop-tools/)
- [n8n HITL Blog](https://blog.n8n.io/human-in-the-loop-automation/)
- [Dify Workflow Docs](https://docs.dify.ai/en/use-dify/build/workflow-chatflow)
- [Langflow vs Flowise 2026](https://toolhalla.ai/blog/dify-vs-flowise-vs-langflow-2026)
- [Flowise vs LangGraph vs n8n 2026](https://www.index.dev/skill-vs-skill/ai-langgraph-vs-n8n-vs-flowise)
- [Coze Studio 节点文档](https://www.coze.com/open/docs/guides/canvas_node)
- [Bisheng GitHub](https://github.com/dataelement/bisheng)
- [Camunda Human Task 文档](https://docs.camunda.io/docs/components/best-practices/architecture/understanding-human-tasks-management/)
- [Camunda 8.9 Agentic Orchestration](https://camunda.com/blog/2026/04/camunda-8-9-fastest-path-to-agentic-orchestration/)
- [Temporal HITL Python](https://docs.temporal.io/ai-cookbook/human-in-the-loop-python)
- [Kissflow 10 Must-Have Features](https://kissflow.com/workflow/workflow-management-system-10-must-have-features/)
- [Kissflow Low-Code Approval 2026](https://kissflow.com/low-code/low-code-approval/)
- [Approval Workflow Beyond SLAs 2026](https://hridayamsoft.com/resources/blog/6725487603871719101-workflow-automation-in-ecm-beyond-approvals-with-slas-escalations-audit-trails-2026)
- [Open Source AI Agent Comparison 2026 - Jimmy Song](https://jimmysong.io/blog/open-source-ai-agent-workflow-comparison/)
- [Activepieces Review 2026](https://openaiwebs.com/activepieces-ai-review-2026-complete-platform-analysis/)
- [n8n vs Langflow 2026](https://growwstacks.com/blog/n8n-vs-langflow-2026-comparison)

---
*Feature research for: 可视化拖拽式 LangGraph 工作流编排平台 + 多通道 HITL 审批*
*Researched: 2026-05-16*
