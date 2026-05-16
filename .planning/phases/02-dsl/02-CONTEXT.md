# Phase 2: DSL 引擎 + 基础节点 - Context

**Gathered:** 2026-05-16
**Status:** Ready for planning

<domain>
## Phase Boundary

DSL 定义/校验 → LangGraph StateGraph 编译 → 5 个基础节点（Start / End / LLM / Tool / IfElse）→ PostgresSaver checkpoint → 实例运行/暂停/恢复/中止 → SSE 实时节点状态推送 → 实例列表页（filter + search + pagination）。

**Phase 2 涵盖 13 个 requirements**：
EDIT-01, EDIT-02, EDIT-03, NODE-01, NODE-03, NODE-05, NODE-06, EXEC-01, EXEC-02, EXEC-03, EXEC-04, EXEC-05

**Phase 2 不做（在后续 phase）**：
- HITL 节点（NODE-02 → Phase 3）
- Parallel-FanOut / Parallel-FanIn / Subgraph / Loop / Code（NODE-04/08/09/10 → Phase 5）
- 通知节点（NODE-07 → Phase 3）
- 调试模式（EDIT-05 → Phase 5）
- 工作流 DSL 导入/导出（EDIT-04 → Phase 6）
- 插件机制（PLUG-* → Phase 6）

</domain>

<decisions>
## Implementation Decisions

### DSL Schema + 变量引用

- **State 模型**：**TypedDict**（LangGraph 官方推荐路径）
  - 运行时从 DSL `state_schema` 字段动态生成 TypedDict 类
  - 字段名 + Python 类型（str / int / float / bool / list / dict）
  - 不用 Pydantic v2（与 LangGraph 1.x 兼容性有坑），不用自由 dict（无类型提示）
- **变量引用语法**：**Jinja2 子集**
  - 语法：`{{ start.output.name }}`、`{{ llm_1.message | tojson }}`、`{{ user.email }}`
  - 实现：`jinja2.sandbox.SandboxedEnvironment`，仅放行白名单 filter（`tojson` / `default` / `lower` / `upper` / `length` / `truncate`）
  - 禁用：循环 / 自定义函数 / 文件 IO
  - 与 Dify/n8n 同路；用户学习成本低
- **节点输出 → state 写入**：**节点 returns 自动合并**（LangGraph 默认行为）
  - 节点函数 `async def execute(state) -> dict[str, Any]` 返回值合并到 state
  - 不强制 DSL 中声明 outputs 映射，简化用户编写
  - 节点输出键 = node_id（如 `start` / `llm_1`），用户引用时 `{{ llm_1.<field> }}`
- **重型数据 Redis pointer（CLAUDE.md 2.6）**：**运行时自动判断**
  - state 字段写入前自动检测 `len(json.dumps(value)) > 4096` → 存 Redis（TTL=30 天） + 替换为 `__ptr__:redis:state:<uuid>`
  - 读取时透明拉回（中间件层）
  - 用户 DSL 与节点代码完全无感知，**不需要**显式声明 reference_fields
  - 适用：LLM 长输出、上传文件内容、IM 卡片 raw body 等
  - Redis key 命名空间：`agent_builder:state_ptr:<workspace_id>:<instance_id>:<uuid>`

### LLM 节点行为

- **Provider 策略**：**LangChain `init_chat_model` + 按需 native provider 包**（2026-05-16 修正：去掉 litellm 层，避免 LangChain → litellm → provider 三层包装）
  - 节点配置：`model: "zhipuai:glm-4.6" | "anthropic:claude-sonnet-4-5" | "openai:gpt-4o" | "deepseek:deepseek-chat" | "ollama:llama3"` 等 `init_chat_model` 字符串格式
  - 实现：`from langchain.chat_models import init_chat_model; chat = init_chat_model(model_str, **config)`
  - 装包按需：`langchain-openai`（GPT）/`langchain-anthropic`（Claude）/`langchain-community`（GLM via ChatZhipuAI、DeepSeek、Ollama 等长尾）
  - API Key 从 env 读：`OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `ZHIPUAI_API_KEY` / `DEEPSEEK_API_KEY`
  - 节点配置可覆盖：`api_base` / `api_key`（用于自部署 OpenAI-compatible 网关，如 Ollama）
  - **不用 litellm**：用户直觉对了——LangChain 已是 LLM client 抽象层，再叠 litellm 是冗余；直接 init_chat_model 原生不打折，bug 排查路径短一层
- **Prompt 体验**：**两者都要**（默认 multi-turn，高级可切原始 prompt）
  - 默认 UI：三段编辑 — `system_prompt`（可选）/ `user_prompt`（必填）/ `assistant_examples`（可选，few-shot）
  - 全部支持 Jinja2 变量插值
  - 高级模式：toggle 切换到 `raw_prompt`（单 messages 数组 JSON 编辑），用于复杂 multi-turn / tool calling
- **流式输出**：**v1 同步，v1.1 加 stream**
  - Phase 2 节点 `await litellm.acompletion(stream=False)` 同步等返回
  - state 一次性写入 `llm_<id>.message` + `llm_<id>.usage`
  - v1.1 Phase 7 增强阶段：开启 stream=True，token 增量通过 SSE 推到前端（与 Area 3 SSE 拓扑天然兼容）
- **重试策略**：**3 次指数退避 + 上报状态机**
  - 节点级默认：`timeout_sec=30`、`retry_count=3`、`backoff_base_sec=1`（即 1s/2s/4s）
  - 节点配置可覆盖：`config.retry_count`、`config.timeout_sec`、`config.backoff_base_sec`
  - 全部重试失败 → 节点 status=`failed` → instance.status=`failed`（默认）
  - 用 `tenacity` 在节点层包一层，控制更易追溯（LangChain 各 provider 自带 retry 也可叠加，但统一在节点层做更易调试）

### 实时状态同步

- **传输协议**：**SSE (Server-Sent Events)**
  - 实现：FastAPI `EventSourceResponse`（`sse-starlette` 库已在 flock 依赖）
  - 后端 LangGraph `app.astream(input, stream_mode="updates")` 生成事件
  - 客户端 EventSource API（浏览器原生支持，无需依赖）
  - nginx 配置：`proxy_buffering off`、`proxy_read_timeout 3600s`、`X-Accel-Buffering: no`
- **推送事件粒度**：**每节点事件**
  - 事件类型 discriminator：`node.start` / `node.complete` / `node.error` / `state.update` / `instance.complete` / `instance.failed`
  - payload schema：`{ event: string, node_id?: string, instance_id: string, timestamp: ISO8601, data: <event-specific> }`
  - 未来扩展（v1.1）：`llm.token` 增量事件用于流式
- **SSE 路由**：**`GET /api/agent_builder/v1/instances/<id>/events`**
  - 每个 instance 独立 SSE channel
  - 后端通过 Redis pub/sub 桥接 LangGraph stream → SSE channel
  - Redis channel name：`agent_builder:instance_events:<instance_id>`
  - 鉴权：复用 Phase 1 的 session cookie（SSE 默认带 cookie）
  - 多浏览器/多用户订阅同一 instance 互不干扰（Redis pub/sub fan-out）
- **断连重连**：**EventSource 默认 retry + Last-Event-ID 补发**
  - EventSource 自动重连（默认 3s）
  - 每个 SSE 事件带 `id: <monotonic_seq>` 头
  - 重连请求头含 `Last-Event-ID: <seq>` → 后端从 Redis Stream 取该 seq 之后的事件补发
  - Redis Stream key：`agent_builder:instance_event_log:<instance_id>`（保留 1 小时事件）
  - 防止用户刷新页面/SSE 断流丢节点状态

### DSL 验证 + 错误反馈

- **不合法 DSL（4 类，全部拦截）**：
  1. **DAG 结构错**：成环 / Start 不可达 End / 孤立节点 / 边指向不存在节点 / 节点 ID 重复
  2. **变量引用悬空**：`{{ nonexistent.x }}` 指向未定义节点输出或 state 字段
  3. **节点配置类型错**：`retry_count = -1`、`timeout_sec = "abc"`、`model = null` 等 schema validation 失败
  4. **特殊**：Start 节点不能有入边、End 节点不能有出边
- **错误显示（三层）**：
  1. **节点边框变红**：第一眼提示，画布上直观
  2. **点击节点弹出错误面板**：显示该节点所有错误 + 修复建议
  3. **侧边栏 Issue 清单**：所有错误聚合列表，点击跳转到节点
  4. 设计参考：Dify Canvas 的 Issue Panel + 节点状态视觉
- **检查时机**：**两阶段都检**
  1. **增量检（边编辑边检）**：每次画布操作（节点添加/删除/边变更/属性编辑）触发 debounced 300ms 检查
     - 仅检查变更部分 + 其依赖（局部 DAG 子图）
     - 结果实时反映到 UI
  2. **全量复检（发布前）**：点"发布"按钮触发全量 validation
     - 拒绝有 error 的发布
     - warning 可放行（如未使用的节点）
- **运行时错误传播**：**节点 status=failed → instance.status=failed → SSE 推 error 事件**
  - LangGraph 节点 raise exception → 节点表 row update status='failed' + error_message + traceback
  - 默认不自动重启 instance（与节点内 LLM 重试区分开）
  - SSE 推 `node.error` 事件 + `instance.failed` 事件
  - 用户可在实例详情页看到失败节点 + 错误详情，决定手动 retry instance 或修改 DSL 重新创建实例
  - 不支持节点级 `on_error: skip|stop|retry` v1（统一 stop 模式，简化）

### Claude's Discretion（未指定，Claude 决定）

- **Tool 节点表达力**：v1 两种 — HTTP 请求（method/url/headers/body 全部 Jinja2 模板化）+ Python function（注册式，受沙箱保护，Phase 6 插件用同样机制）
- **节点 paletter（画布侧边节点库）**：分类（Trigger / Process / Logic / End），每类含 icon + 描述 + 拖拽 handle
- **Postgres checkpoint table schema**：用 `langgraph-checkpoint-postgres` 默认 schema，不自建（避免与上游 diverge）；Alembic 跳过这些表
- **Instance pause 语义**：v1 不支持中途 pause（只支持 abort）；pause 留到 Phase 3 HITL 自然出现
- **DSL 版本管理**：DSL 增加 `version: "1.0"` 字段；instance 创建时锁定 DSL 版本快照（不随 workflow 草稿/发布变化）
- **节点 ID 命名规则**：用户起 + 校验 `^[a-z][a-z0-9_]*$`；前端拖入时自动生成 `<type>_<seq>`
- **画布节点位置**：DSL 中存 `position: {x, y}` 用于回显，不影响执行
- **画布缩放/平移**：React Flow 默认能力，不额外配置
- **实例列表分页**：默认 20 条/页，URL query 化（便于分享）
- **画布 zoom 范围**：0.25× ~ 2×，鼠标滚轮 + 按钮
- **执行可观测**：每个 instance 默认开 trace log 写 `action_logs` 表（与 Phase 1 一致）

</decisions>

<specifics>
## Specific Ideas

- **画布交互参考 Dify**：节点拖拽 + 连线 + 右键菜单 + 多选 + 复制粘贴；侧边栏节点库 + 节点配置 panel 三栏式
- **DSL 设计语言参考 Dify YAML / langgraph-builder JSON**：扁平 nodes[] + edges[]（不嵌套），变量插值用 Jinja2 与 Dify 完全同语法（便于用户从 Dify 迁移）
- **检查器实现参考 TypeScript Compiler API 思路**：单遍 DAG 拓扑排序 + 变量符号表收集 + Schema 校验，所有 error 一次性返回（不要修一个 error 才发现下一个）
- **实例列表参考 GitHub Actions Runs 页**：state filter（running/paused/failed/completed）+ workflow filter + time range + 搜索（按 employee_id / instance_id）+ 分页

</specifics>

<deferred>
## Deferred Ideas

讨论中浮现但属其它 phase / v2 的想法：

- **节点级 on_error 策略**（skip/stop/retry）→ Phase 7 增强（v1 统一 stop）
- **DSL 跑到一半改 → 半自动迁移**（WF-V2-02）→ v2
- **节点级 CPU/内存 quota 配置 UI**（PROJECT.md Out of Scope）→ v2
- **多人协同编辑**（EDIT-V2-02）→ v2
- **画布版本时间线 + diff**（EDIT-V2-01）→ v2
- **DSL 导出独立 Python 项目**（决策板 #2 锁定 不做）→ 永不做
- **Tool 节点的 OpenAPI 自动导入**（生成 HTTP 节点配置）→ Phase 6 插件市场
- **Token 用量计费 / cost 跟踪** → Phase 7 可观测性
- **画布快捷键（撤销 / 删除 / 复制）** → Phase 5 增强（v1 用菜单 + 删除键即可）
- **代码导出 / 调试模式步进**（EDIT-05）→ Phase 5

</deferred>

---

*Phase: 02-dsl*
*Context gathered: 2026-05-16*
