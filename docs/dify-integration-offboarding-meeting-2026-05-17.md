# Dify 配置驱动：离职流程 + 会议总结 + 智能 @人 + 跨平台协作文档

> 日期：2026-05-17
> 关联项目：`/Users/admin/ai/resume/interview/liuxin/hr/` (offboarding-flow)
> 设计目标：把 LangGraph 状态机 / 邮件 / IM @人 / 协作文档 通过 **Dify workflow** 配置化，零代码切换
> 状态：设计草案，待评审

---

## 1. 当前实现现状（hr 项目里已经做的）

### 1.1 已有抽象层

```
hr/backend/src/offboarding_flow/
├── providers/                          ← 已实现：跨平台抽象
│   ├── base.py                         (DocProvider / IMProvider Protocol)
│   ├── outline_provider.py             (Outline 协作文档)
│   ├── mattermost_provider.py          (Mattermost IM)
│   ├── lark_provider.py                (飞书 文档+IM)
│   ├── wecom_provider.py               (企微 stub)
│   ├── dingtalk_provider.py            (钉钉 stub)
│   └── factory.py                      (按 .env DOC_PROVIDER/IM_PROVIDER 路由)
├── flow_engine/
│   ├── nodes/                          (LangGraph 10+ 节点 hardcode)
│   └── provider_mapping.py             ← 已实现：per-node/per-role provider 覆写表
├── services/
│   ├── meeting_service.py              ← 已实现：会议纪要 3 层 AI 分析（提取 + 逐项 + 个人 brief）
│   ├── handover_service.py             ← 已实现：节点 advance 后 AI 自动生成交接文档
│   ├── bot_service.py                  ← 8 命令 + meeting-* + users-sync
│   └── llm_service.py                  (统一 GLM 调用 + disclaimer)
└── workers/
    └── mattermost_listener.py          (bot WebSocket 长连 + DM 主动推送)
```

### 1.2 已跑通的 demo 链路

1. **离职流程**：`bot meeting-ingest` 不算；`POST /api/flows` → manager_review interrupt → advance → handover doc 自动到 Outline + DM @ 协作人 + flow.context 写回 URL
2. **会议纪要**：MM channel 里发 `@offboarding-bot meeting-ingest <粘贴纪要>` → AI 提取 → 逐 task/blocker/decision 单独 LLM 分析 → Outline 文档 + 各 owner DM 个性化 brief

### 1.3 现有抽象的局限（要解决的）

| 局限 | 影响 |
|---|---|
| LangGraph 节点 DAG 写死在代码里 | 流程改动要重新部署 |
| AI prompt 写死在 `llm/prompts.py` | 调 prompt 要改代码 |
| Provider mapping 写在 Python dict | 运营改不了 |
| `@ 人` 逻辑硬编码（按 username 文本匹配） | 跨平台 user ID 映射不够灵活 |
| 触发时机硬编码在 `node_service.submit_action` | 想加"卡点超 3 天自动 @ 上级"这种规则要改代码 |

## 2. Dify 集成目标

把上述 **5 个硬编码点** 全部交给 Dify Workflow 配置驱动：

```
┌─────────────────────────────────────────────────┐
│ Dify Workflow Studio (UI 配置)                  │
│  ├── 流程 DAG（拖拽节点 + 条件边）             │
│  ├── Prompt 模板（每个节点自带 LLM 节点）       │
│  ├── 平台路由（节点选择 Outline/Lark/WeCom）    │
│  ├── @人规则（按 role/部门/标签动态查）         │
│  └── 触发时机（节点 entry / advance / timeout） │
└────────────────┬────────────────────────────────┘
                 │ Workflow DSL (JSON/YAML)
                 ▼
┌─────────────────────────────────────────────────┐
│ offboarding-flow 后端                            │
│  ├── DifyClient (新增) ← 调 Dify Workflow API   │
│  ├── 各 Provider 注册为 Dify Tool               │
│  └── Webhook → 接收 Dify 节点回调               │
└─────────────────────────────────────────────────┘
                 │ Tool Call
                 ▼
┌─────────────────────────────────────────────────┐
│ Provider 实现层（不动）                          │
│  Outline / Lark / Mattermost / WeCom / DingTalk │
└─────────────────────────────────────────────────┘
```

## 3. 集成方案（三选一）

### 方案 A：Dify 作为 LangGraph 替代品（重）

把 LangGraph DAG 整体迁到 Dify Workflow。

- 优点：流程完全 UI 可视化；非工程师能改流程
- 缺点：丢失 LangGraph 的 checkpoint / interrupt 灵活性；要重写 10 节点；离线场景不可用
- 适合：长期 strategic 选择
- 工作量：~3 周

### 方案 B：Dify 作为 AI Workflow 服务（中）⭐ 推荐

LangGraph 仍然管流程状态机；**AI 相关的所有工作**（prompt 渲染、LLM 调用、文档生成、@人选择）外包给 Dify Workflow。

- 优点：只迁 AI 部分；prompts 在 Dify UI 改；@ 人规则在 Dify 配；LangGraph 还在
- 缺点：LangGraph + Dify 双系统
- 工作量：~1 周
- **demo / POC 走 B**

### 方案 C：Dify 作为 Tool 提供方（轻）

仅把 Dify 当作 "智能 @ 人推荐" / "AI 文档草稿" 的微服务调用。

- 优点：嵌入式，最小侵入
- 缺点：发挥不出 Dify 的 Workflow 价值
- 工作量：~2 天

## 4. 方案 B 详细设计

### 4.1 Dify 端 — 创建 4 个 Workflow

| Workflow 名 | 触发 | 输入 | 输出 | 替换的硬编码 |
|---|---|---|---|---|
| **handover_doc_generator** | 节点 advance | `node_name, result_text, employee_id, actor` | `{markdown, owners_to_mention[]}` | `handover_service.generate_node_handover` |
| **meeting_extract_and_analyze** | bot meeting-ingest | `raw_text` | `{title, tasks[], blockers[], decisions[]}` | `meeting_service.extract + analyze` |
| **smart_mention** | 任意需要 @ 人时 | `context (node/event), participants[]` | `[{username, reason}]` 排序后的 @ 人列表 | hardcoded `_NODE_META.assignee` |
| **personal_brief** | 给 owner 发 DM 时 | `owner, meeting_context, my_items[]` | `markdown brief` | `meeting_service.generate_personal_brief` |

每个 Workflow 是 Dify Studio UI 配置的，结构：
```
[Input] → [LLM 节点 - 用 Prompt 模板] → [Code 节点 - 解析/校验] → [Output]
```

### 4.2 后端 — 加 DifyClient

`backend/src/offboarding_flow/dify/client.py`:
```python
class DifyClient:
    async def run_workflow(workflow_id: str, inputs: dict) -> dict
    async def stream_workflow(workflow_id: str, inputs: dict) -> AsyncIterator[Event]
```

调用方式：
```python
# 旧（hardcoded prompt + GLM）
md = await llm.complete(HANDOVER_NODE_PROMPT, ctx)

# 新（Dify workflow）
result = await dify.run_workflow("handover_doc_generator", inputs={
    "node_name": "manager_review",
    "result_text": "...",
    "employee_id": "zhang.san",
    "actor": "li.si",
})
md = result["markdown"]
owners = result["owners_to_mention"]
```

### 4.3 智能 @ 人 - smart_mention Workflow 设计

输入：
```json
{
  "event_type": "handover_doc_created",
  "node_name": "device_return",
  "involved_users": ["zhang.san", "it.charlie"],
  "department_users": [...]
}
```

Dify Workflow 内部：
1. LLM 节点：「分析当前事件 + 涉及人员，按相关性排序应该 @ 谁」
2. Code 节点：去重 + filter 出实际存在的 username
3. Output 节点：返回 `[{username, role, reason}]`

替代当前 hardcode 的逻辑：
```python
# 旧
next_assignee = _NODE_META[next_node]["assignee"]
await im.send_dm(next_assignee, msg)

# 新
mentions = await dify.run_workflow("smart_mention", inputs=event)
for m in mentions:
    await im.send_dm(m["username"], render_with_reason(msg, m["reason"]))
```

### 4.4 协作文档创建 + @ 人

handover_doc_generator Workflow 内：
1. LLM 生成 markdown
2. **新增 LLM 节点**：「分析文档内容，识别需要 @ 的协作人」
3. 输出 `{markdown, mentions: [{username, position_in_doc}]}`

后端拿到后：
```python
doc = await doc_provider.create_document(title=..., markdown=md)
# 文档创建后，在文档评论区 @ 每个 mention
for m in mentions:
    await doc_provider.add_comment_mention(doc.id, m["username"], "请关注此处")
```

需要给 DocProvider Protocol 加：
```python
async def add_comment_mention(doc_id, username, comment_text) -> None
```

### 4.5 跨平台 User ID 映射

Dify 不知道 Mattermost ↔ Outline ↔ Lark 的 user ID 对应关系。

方案：后端维护一张 `user_platform_mappings` 表，Dify 通过 HTTP Tool 查询：

```sql
CREATE TABLE app.user_platform_mappings (
    username TEXT PRIMARY KEY,  -- 内部 canonical username
    mattermost_id TEXT,
    outline_email TEXT,
    lark_open_id TEXT,
    wecom_userid TEXT,
    dingtalk_userid TEXT,
    department TEXT,
    role TEXT
);
```

Dify Workflow 里通过 HTTP 工具调 `GET /api/users/{username}/mapping` 获取所有平台 ID，然后路由到对应 provider。

## 5. 实现路径 (方案 B)

### Phase 1：基础设施（2 天）
- [ ] 起 Dify self-hosted（docker compose）
- [ ] 后端加 `DifyClient` (httpx 调 Dify API)
- [ ] 加 `user_platform_mappings` 表 + sync 命令
- [ ] 加 HTTP 工具 endpoint：`/api/users/{username}/mapping` 给 Dify 调

### Phase 2：迁移 AI 工作流到 Dify（3 天）
- [ ] 在 Dify Studio 建 4 个 Workflow（handover / meeting / smart_mention / personal_brief）
- [ ] 后端 `handover_service` 替换 LLM 直调为 `dify.run_workflow`
- [ ] 后端 `meeting_service` 同上
- [ ] 保留旧 GLM 调用作 fallback（Dify 不可达时降级）

### Phase 3：智能 @人（2 天）
- [ ] smart_mention Workflow 调通
- [ ] DocProvider 加 `add_comment_mention`（Outline / Lark 各自实现）
- [ ] handover trigger 流程中调用

### Phase 4：runtime 切换 + 灰度（1 天）
- [ ] `.env` 加 `USE_DIFY=true/false` 总开关
- [ ] 每个 service 加 `_use_dify()` 判断
- [ ] 监控 Dify 响应时间 / 成功率

## 6. 风险与决策点

| 风险 | 缓解 |
|---|---|
| Dify Workflow 响应慢（每次调要 5-10s） | 异步触发 + outbox 兜底，不阻塞 LangGraph |
| Dify self-host 运维复杂 | docker compose 一套 5 容器，加监控告警 |
| Prompt 在 Dify Studio 改了忘 commit | Dify DSL 定期 export 到 Git（自动化） |
| User ID 映射不及时 | sync 命令定时跑（cron 5 min） |
| Dify 厂商绑定 | DifyClient 抽象层，未来可换 n8n / Activepieces |

## 7. 决策点 — 等待用户回答

1. **是否走方案 B**（LangGraph + Dify 混合）？还是 A（全迁 Dify）/ C（最小集成）？
2. **Dify self-host 还是 SaaS**？self-host 数据可控但要运维；SaaS 即开即用但出库
3. **smart_mention 第一版用规则 or 全 LLM**？规则稳但死板，LLM 智能但贵 + 慢
4. **DocProvider.add_comment_mention 优先级**？Outline 有原生评论 API，Lark 也有，企微钉钉要确认

## 8. 关联文件清单（已在 hr 项目里）

- 流程定义：`hr/PRD.md` v0.4
- 节点 DAG：`hr/backend/src/offboarding_flow/flow_engine/graph.py`
- Provider 抽象：`hr/backend/src/offboarding_flow/providers/`
- 节点 ↔ Provider 映射：`hr/backend/src/offboarding_flow/flow_engine/provider_mapping.py`
- 会议纪要服务：`hr/backend/src/offboarding_flow/services/meeting_service.py`
- 节点交接服务：`hr/backend/src/offboarding_flow/services/handover_service.py`

## 9. 参考

- Dify 自部署：https://docs.dify.ai/getting-started/install-self-hosted/docker-compose
- Dify Workflow API：https://docs.dify.ai/guides/workflow/workflow-as-tool
- LangGraph + Dify 集成思路：本目录 `reading-dify-*.md` 系列阅读笔记
- Outline 评论 API：https://www.getoutline.com/developers
- Lark 文档 / IM API：https://open.feishu.cn/document
