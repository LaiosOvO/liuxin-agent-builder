# agent-builder 平台抽象总览：IM + 协作文档

> **作者**：来自 offboarding-flow 实战 + Phase 4 IMProvider 落地
> **日期**：2026-05-17
> **状态**：总览（指向 IM bot + DocProvider 两份详细设计稿）

---

## 0. 这份文档解决什么

`agent-builder` v1 演进过程中，我们提炼出两类**跨平台抽象**：

1. **IM 协作抽象**：让用户在 Mattermost / 飞书 / 钉钉 / Slack 中**通过聊天驱动工作流**，并把流程结果**回帖到 IM**
2. **协作文档抽象**：让工作流执行结果**自动写入** Outline / 飞书文档 / 企微微盘 / 钉钉文档，并支持 **AI 智能 @ 协作人**

两类抽象都遵循同一组**架构原则**，本文档汇总这些原则 + 指向详细设计稿。

---

## 1. 抽象拓扑总览

```
                            ┌─────────────────────────┐
                            │   agent-builder DAG     │
                            │  (LangGraph workflow)   │
                            └────┬──────────┬─────────┘
                                 │          │
              ┌──────────────────┼──────────┼──────────────────┐
              │                  │          │                  │
              ▼                  ▼          ▼                  ▼
       ┌──────────┐       ┌──────────┐ ┌──────────┐    ┌──────────┐
       │im_trigger│       │im_notify │ │doc_write │    │im_card_  │
       │(入站触发)│       │(出站通知)│ │(写文档)  │    │notify    │
       │Phase 5.A │       │Phase 5.D │ │Phase 5.C │    │Phase 4 ✓ │
       └────┬─────┘       └────┬─────┘ └────┬─────┘    └────┬─────┘
            │                  │            │                │
            └──────┬───────────┘            └───────┬────────┘
                   │                                │
                   ▼                                ▼
            ┌────────────┐                   ┌────────────┐
            │ IMProvider │                   │DocProvider │
            │  Protocol  │                   │  Protocol  │
            │ (Phase 4 ✓)│                   │(Phase 5.A) │
            └─────┬──────┘                   └─────┬──────┘
                  │                                │
        ┌─────────┼─────────┐            ┌─────────┼─────────┐
        ▼         ▼         ▼            ▼         ▼         ▼
     Feishu  Mattermost  Slack       Outline   Lark    DingTalk
     ✓ 04-06  ✓ 04-09   ✓ 04-09      P5.B P0   P5.B P0  P5.D P1
     WeCom   DingTalk   Webhook      WeCom Drive
     ✓ 04-07 ✓ 04-08   ✓ 04-09       P5.D P1

                            ┌─────────────────────────┐
                            │  user_platform_mappings │
                            │  (IM ID ↔ Doc ID ↔      │
                            │   canonical username)   │
                            │  Phase 5.A 建表          │
                            └─────────────────────────┘
```

---

## 2. 共享架构原则

| 原则 | IM 抽象 | Doc 抽象 |
|---|---|---|
| **Protocol over ABC** | `IMProvider` (Phase 4 ✓) | `DocProvider` (Phase 5.A) |
| **runtime_checkable** | ✓ | ✓ |
| **Registry pattern** | `IMRegistry` (Phase 4 04-05 ✓) | `DocProviderRegistry` (Phase 5.A) |
| **per-workspace credentials** | `IMCredentialsManager` (Phase 4 ✓) | `DocCredentialsManager` (Phase 5.A) |
| **凭据加密存储** | env + DB workspace_settings | 同模式复用 |
| **Mock provider for tests** | `MockIMProvider` (Phase 4 ✓) | `MockDocProvider` (Phase 5.A) |
| **能力声明 (supports_*)** | `supports_card_update` | `supports_comments` |
| **structured 日志** | `logger.info("im.card.send", ...)` | `logger.info("doc.write", ...)` |
| **Phase 7 可视化钩子** | extra 字段供 Run Viewer 消费 | 同 |
| **跨平台 user mapping** | `user_platform_mappings` 表 | 同表共用 |
| **DAG 节点类型集成** | `im_card_notify` / `im_trigger` / `im_notify` | `doc_write` / `doc_mention` |
| **AI 智能** | LLM intent router (IM bot 抽象) | `ai_suggest_mentions` |

---

## 3. Phase 拆分（建议）

| Phase | 内容 | 详见 |
|-------|------|------|
| **Phase 4** ✓ | IM 出站卡片通知（5 家 provider + multichannel） | 已完成 04-05..11 |
| **Phase 4.5** | IM bot 入站触发（5.A 基础抽象 + 5.B LLM intent router） | [im-bot-abstraction §10](./2026-05-17-im-bot-abstraction-design.md) |
| **Phase 5.A** | DocProvider 基础抽象（Protocol + Registry + Credentials + user mappings） | [doc-provider-abstraction §9](./2026-05-17-doc-provider-abstraction-design.md) |
| **Phase 5.B** | DocProvider 真接入（Outline + Lark Docs + AI suggest mentions） | 同上 |
| **Phase 5.C** | DAG 节点集成（im_trigger / im_notify / doc_write / doc_mention） | im-bot §10 + doc-provider §9 |
| **Phase 5.D** | WeCom Drive + DingTalk Doc + 其余 IM provider 入站 | 两稿 |
| **Phase 5.E** | IM 目录同步（dept: 表达式解析依赖 — 原 ROADMAP Phase 5） | 待评审是否合并到 5.D |

---

## 4. 与 Phase 4 已完成工作的关系

**Phase 4 已完成**：
- ✓ `IMProvider` Protocol + Registry + Mock（04-05 SUMMARY）
- ✓ Feishu + WeCom + DingTalk + Slack + Mattermost + Webhook 共 6 provider（04-06/07/08/09 SUMMARYs）
- ✓ `IMCredentialsManager` per-workspace 凭据（04-05 SUMMARY）
- ✓ NotificationService.enqueue_hitl_multichannel 多通道 fan-out（04-10 SUMMARY）
- ✓ HITLNodeExecutor chain + interrupt_payload chain fields + multichannel enqueue（04-11 SUMMARY）

**这意味着 Phase 5.A 起步就有了**：
- IMProvider 已是稳定接口 — 入站 listener 只需加 `subscribe(event_types) -> AsyncIterator[Event]` 方法
- 凭据管理模式已成熟 — DocCredentialsManager 可零成本复用
- Registry / Mock 模式已验证 — DocProviderRegistry 直接套
- multichannel 出站基础设施已建 — im_notify 节点（Phase 5.D）只需薄包装

**Phase 4 还差什么（落地 IM 协作 + Doc 协作 v1 完整闭环）**：
- IMProvider 加入站事件订阅接口（`subscribe` / `unsubscribe`）
- bot.yaml 配置加载 + HandlerRegistry dispatcher（IM bot 抽象 §5）
- DocProvider Protocol + 4 providers 实现（Doc 抽象 §4 + §8）
- user_platform_mappings 表 + sync 命令（两稿共用 §5 / §13）
- DAG 加 4 个新节点类型（im_trigger / im_notify / doc_write / doc_mention）

---

## 5. 跨抽象一致性检查清单（验收用）

每次新增 provider / 节点类型 / 抽象层时，都用这个清单验收：

- [ ] Protocol 而非 ABC + runtime_checkable
- [ ] frozen dataclass for credentials + DTO
- [ ] Registry + factory.get(workspace_id) per-tenant
- [ ] Mock 实现用于测试
- [ ] 能力声明 property（supports_*）
- [ ] structured log 含 workspace_id + provider + api + latency
- [ ] tenacity 重试 1s/2s/4s（Phase 3 既有模式）
- [ ] 凭据从 env / DB 加密存，不入 YAML/code
- [ ] 跨 workspace 隔离测试（双 workspace 互不串扰）
- [ ] reading doc Task 0（CLAUDE.md §2.7）
- [ ] 三层测试 unit + integration（真实 DB）+ E2E（browser-use/browser-harness）

---

## 6. 参考文档索引

| 文档 | 范围 |
|---|---|
| [im-bot-abstraction-design](./2026-05-17-im-bot-abstraction-design.md) | IM bot 入站 + LLM intent router + 命令路由 + bot.yaml schema |
| [doc-provider-abstraction-design](./2026-05-17-doc-provider-abstraction-design.md) | DocProvider Protocol + 4 平台 + AI suggest mentions + DAG 节点 |
| [dify-integration-offboarding-meeting](../dify-integration-offboarding-meeting-2026-05-17.md) | 用 Dify Workflow 配置驱动 AI 子流程的可选方案（与本系列正交） |
| Phase 4 ROADMAP + plans | IM 出站基础（已完成） |
| Phase 4.5 OUTLINE | Bot Triggers 早期 outline（已链接到本系列） |

---

## 7. 下一步

1. **Phase 4 收尾**（当前进行中 — Wave 7 04-12 E2E gate 启动后完成）
2. **`/gsd:discuss-phase 4.5`** — 用 [im-bot-abstraction §10 Phase 5.A + 5.B] 作为 CONTEXT 输入
3. **`/gsd:discuss-phase 5`** — 用 [doc-provider-abstraction §9 + im-bot-abstraction Phase 5.C + 5.D] + 原 ROADMAP IM 目录同步合并

---

*overview 完*
