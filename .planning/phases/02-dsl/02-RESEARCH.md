# Phase 2: DSL 引擎 + 基础节点 - 技术研究

**Researched:** 2026-05-16
**Confidence:** HIGH（基于 STACK.md 锁定版本 + flock 现有代码勘察 + CONTEXT.md 16 条决策）
**Phase Requirement IDs:** EDIT-01, EDIT-02, EDIT-03, NODE-01, NODE-03, NODE-05, NODE-06, EXEC-01, EXEC-02, EXEC-03, EXEC-04, EXEC-05

---

## User Constraints（来自 CONTEXT.md，逐字搬运，必须遵守）

### 已锁定决策（不可重新讨论）

**DSL Schema + 变量引用**
1. **State 模型**：**TypedDict**（不用 Pydantic v2；不用自由 dict）
   - 运行时从 DSL `state_schema` 字段动态生成 TypedDict 类
   - 字段名 + Python 类型（str / int / float / bool / list / dict）
2. **变量引用语法**：**Jinja2 子集**
   - 语法：`{{ start.output.name }}`、`{{ llm_1.message | tojson }}`、`{{ user.email }}`
   - 实现：`jinja2.sandbox.SandboxedEnvironment`
   - 仅放行白名单 filter：`tojson` / `default` / `lower` / `upper` / `length` / `truncate`
   - 禁用：循环 / 自定义函数 / 文件 IO
3. **节点输出 → state 写入**：**节点 returns 自动合并**（LangGraph 默认行为）
   - 节点函数 `async def execute(state) -> dict[str, Any]` 返回值合并到 state
   - 节点输出键 = node_id（如 `start` / `llm_1`），用户引用时 `{{ llm_1.<field> }}`
4. **重型数据 Redis pointer**（CLAUDE.md 2.6）：**运行时自动判断**
   - state 字段写入前自动检测 `len(json.dumps(value)) > 4096` → 存 Redis（TTL=30 天） + 替换为 `__ptr__:redis:state:<uuid>`
   - 读取时透明拉回（中间件层）
   - 用户 DSL 与节点代码完全无感知，**不需要**显式声明 reference_fields
   - Redis key 命名空间：`agent_builder:state_ptr:<workspace_id>:<instance_id>:<uuid>`

**LLM 节点行为**
5. **Provider 策略**：**litellm 100+ provider 兼容 + LangChain/LangGraph 集成**
   - 节点配置：`model: "openai/gpt-4o" | "deepseek/deepseek-chat" | "zhipu/glm-4.6" | "anthropic/claude-sonnet-4-5"` 等 litellm 模型字符串
   - 走 `litellm.acompletion()` 异步调用（已在 flock pyproject.toml）
   - 集成 LangChain 的 `ChatLiteLLM` adapter（`from langchain_community.chat_models import ChatLiteLLM`）
   - API Key 从 env 读：`OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `ZHIPUAI_API_KEY` / `DEEPSEEK_API_KEY` 等
6. **Prompt 体验**：**两者都要**
   - 默认 UI：三段编辑 — `system_prompt`（可选）/ `user_prompt`（必填）/ `assistant_examples`（可选）
   - 全部支持 Jinja2 变量插值
   - 高级模式：toggle 切换到 `raw_prompt`（单 messages 数组 JSON 编辑）
7. **流式输出**：**v1 同步，v1.1 加 stream**
   - Phase 2 节点 `await litellm.acompletion(stream=False)`
   - state 一次性写入 `llm_<id>.message` + `llm_<id>.usage`
   - v1.1 Phase 7 增强阶段：开启 stream=True
8. **重试策略**：**3 次指数退避**
   - 节点级默认：`timeout_sec=30`、`retry_count=3`、`backoff_base_sec=1`（即 1s/2s/4s）
   - 节点配置可覆盖：`config.retry_count`、`config.timeout_sec`、`config.backoff_base_sec`
   - 全部重试失败 → 节点 status=`failed` → instance.status=`failed`
   - 节点层用 tenacity 包一层（便于追溯），不用 litellm 内置 `num_retries`

**实时状态同步**
9. **传输协议**：**SSE（Server-Sent Events）**
   - 实现：FastAPI `EventSourceResponse`（`sse-starlette` 库已在 flock 依赖）
   - 后端 LangGraph `app.astream(input, stream_mode="updates")` 生成事件
   - 客户端 EventSource API
   - nginx 配置：`proxy_buffering off`、`proxy_read_timeout 3600s`、`X-Accel-Buffering: no`
10. **推送事件粒度**：**每节点事件**
    - 事件类型 discriminator：`node.start` / `node.complete` / `node.error` / `state.update` / `instance.complete` / `instance.failed`
    - payload schema：`{ event: string, node_id?: string, instance_id: string, timestamp: ISO8601, data: <event-specific> }`
11. **SSE 路由**：**`GET /api/agent_builder/v1/instances/<id>/events`**
    - 每个 instance 独立 SSE channel
    - 后端通过 Redis pub/sub 桥接 LangGraph stream → SSE channel
    - Redis channel name：`agent_builder:instance_events:<instance_id>`
    - 鉴权：复用 Phase 1 的 session cookie
12. **断连重连**：**EventSource 默认 retry + Last-Event-ID 补发**
    - EventSource 自动重连（默认 3s）
    - 每个 SSE 事件带 `id: <monotonic_seq>` 头
    - Redis Stream key：`agent_builder:instance_event_log:<instance_id>`（保留 1 小时事件）

**DSL 验证 + 错误反馈**
13. **不合法 DSL（4 类，全部拦截）**：
    1. DAG 结构错（成环 / Start 不可达 End / 孤立节点 / 边指向不存在节点 / 节点 ID 重复）
    2. 变量引用悬空
    3. 节点配置类型错（schema validation 失败）
    4. 特殊（Start 节点不能有入边、End 节点不能有出边）
14. **错误显示（三层）**：节点边框变红 + 点击节点弹出错误面板 + 侧边栏 Issue 清单
15. **检查时机**：**两阶段**
    1. 增量检（300ms debounce），仅检查变更部分 + 其依赖
    2. 全量复检（发布前），拒绝有 error 的发布；warning 可放行
16. **运行时错误传播**：**节点 status=failed → instance.status=failed → SSE 推 error 事件**
    - 默认不自动重启 instance
    - 不支持节点级 `on_error: skip|stop|retry` v1（统一 stop 模式）

### Claude's Discretion（未指定，Claude 决定）

- Tool 节点表达力：v1 两种 — HTTP 请求（Jinja2 模板化）+ Python function（注册式，受沙箱保护）
- 节点 palette（画布侧边节点库）：分类（Trigger / Process / Logic / End）
- Postgres checkpoint table schema：用 `langgraph-checkpoint-postgres` 默认 schema
- Instance pause 语义：v1 不支持中途 pause（只支持 abort）
- DSL 版本管理：DSL 增加 `version: "1.0"` 字段；instance 创建时锁定快照
- 节点 ID 命名规则：`^[a-z][a-z0-9_]*$`
- 画布节点位置：DSL 中存 `position: {x, y}`
- 实例列表分页：默认 20 条/页

### Deferred Ideas（不要做）

- HITL 节点（NODE-02 → Phase 3）
- 通知节点（NODE-07 → Phase 3）
- Parallel-FanOut / Parallel-FanIn / Subgraph / Loop / Code 节点（→ Phase 5）
- 调试模式（EDIT-05 → Phase 5）
- 工作流 DSL 导入/导出（EDIT-04 → Phase 6）
- 插件机制（PLUG-* → Phase 6）
- 节点级 on_error 策略
- 多人协同编辑

---

## Standard Stack（锁定版本）

### Phase 2 升级版本（关键变更）

| 包 | 现版本（Phase 1） | Phase 2 升级到 | 原因 |
|----|---|---|---|
| **langgraph** | 0.3.5（flock 原）| **1.2.0** | CONTEXT.md 决策；checkpoint-postgres 3.1 需要 |
| **langgraph-checkpoint-postgres** | <=2.0.9（flock 锁）| **3.1.0** | PostgresSaver async API 稳定 |
| **psycopg** | 3.1.13（已有） | **3.1.18+**（保持）| checkpoint 3.1 用 psycopg3 |
| **@xyflow/react** | 12.6.0（已有） | **12.10.2** | 节点拖拽 + 连线 + minimap |

### Phase 2 新增依赖

**后端**
```bash
pip install "langgraph==1.2.0"
pip install "langgraph-checkpoint-postgres==3.1.0"
# litellm 已在 flock pyproject.toml: litellm>=1.63.11（继续用）
# langchain-community 已有: langchain-community>=0.3.19（提供 ChatLiteLLM）
# tenacity 已有: tenacity>=8.2.3
# jinja2 已有: jinja2>=3.1.3（用 SandboxedEnvironment）
# sse-starlette 已有: sse-starlette>=1.6.5
# redis 已有: redis>=5.0.7（升级到 7.4.0 见下）
pip install "redis==7.4.0"  # 升级以用 Stream API
```

**前端**
```bash
npm install reactflow@^11.11  # 保留 flock 已有的 reactflow（节点配置面板）
npm install @xyflow/react@^12.10  # 新版本，本项目 Canvas 用
npm install nanoid  # 节点 ID 生成
npm install eventsource-parser  # SSE 解析
```

**注意：** flock 原 `web/package.json` 同时存在 `reactflow` 11.x 和 `@xyflow/react` 12.x。Phase 2 Canvas 用 `@xyflow/react` v12（最新 API），flock 原节点配置面板可暂保留 `reactflow` 11.x（fork discipline）。

---

## Architecture Patterns

### 1. DSL Schema（JSON 扁平结构）

```json
{
  "version": "1.0",
  "workflow_id": "wf_abc",
  "name": "员工离职流程",
  "state_schema": {
    "employee_id": "str",
    "department": "str",
    "approval_status": "str"
  },
  "nodes": [
    {
      "id": "start",
      "type": "start",
      "position": {"x": 100, "y": 200},
      "config": {}
    },
    {
      "id": "llm_1",
      "type": "llm",
      "position": {"x": 300, "y": 200},
      "config": {
        "model": "openai/gpt-4o",
        "system_prompt": "你是 HR 助理",
        "user_prompt": "请审核员工 {{ start.employee_id }} 的离职申请",
        "timeout_sec": 30,
        "retry_count": 3
      }
    },
    {"id": "end", "type": "end", "position": {"x": 800, "y": 200}}
  ],
  "edges": [
    {"id": "e1", "source": "start", "target": "llm_1"},
    {"id": "e2", "source": "llm_1", "target": "end"}
  ]
}
```

**节点类型 5 个**：`start` / `end` / `llm` / `tool` / `if_else`

**Tool 节点 config**：
- HTTP 模式：`{kind: "http", method: "POST", url: "{{ ... }}", headers: {...}, body: {...}}`
- Python 模式：`{kind: "python", function: "registered_function_name", args: {...}}`

**IfElse 节点 config**：
- `{conditions: [{expr: "{{ llm_1.score > 0.8 }}", target_node_id: "...", label: "high"}], default_target: "..."}`

### 2. DSL → LangGraph StateGraph 编译（DSLCompiler）

**核心组件**：

```python
# backend/app/agent_builder/workflow/state_factory.py
def build_state_typeddict(state_schema: dict[str, str]) -> type[TypedDict]:
    """运行时构造 TypedDict 类（用 typing.TypedDict 动态创建）"""
    PY_TYPE_MAP = {"str": str, "int": int, "float": float, "bool": bool, "list": list, "dict": dict}
    fields = {name: PY_TYPE_MAP[type_str] for name, type_str in state_schema.items()}
    return TypedDict("WorkflowState", fields)  # type: ignore[misc]

# backend/app/agent_builder/workflow/compiler.py
class DSLCompiler:
    async def compile(self, dsl: dict, checkpointer: AsyncPostgresSaver) -> CompiledGraph:
        StateType = build_state_typeddict(dsl["state_schema"])
        graph = StateGraph(StateType)
        for node in dsl["nodes"]:
            node_fn = self._build_node_executor(node)  # 见下
            graph.add_node(node["id"], node_fn)
        for edge in dsl["edges"]:
            if edge.get("conditional"):
                graph.add_conditional_edges(edge["source"], _make_router(edge))
            else:
                graph.add_edge(edge["source"], edge["target"])
        graph.set_entry_point(_find_start_node(dsl))
        graph.set_finish_point(_find_end_node(dsl))
        return graph.compile(checkpointer=checkpointer)
```

**节点 executor 工厂**：

```python
# backend/app/agent_builder/workflow/nodes/registry.py
NODE_EXECUTORS: dict[str, type[BaseNodeExecutor]] = {
    "start": StartNodeExecutor,
    "end": EndNodeExecutor,
    "llm": LLMNodeExecutor,
    "tool": ToolNodeExecutor,
    "if_else": IfElseNodeExecutor,
}

# backend/app/agent_builder/workflow/nodes/base.py
class BaseNodeExecutor:
    def __init__(self, node_config: dict, jinja_env: SandboxedEnvironment):
        self.config = node_config
        self.jinja_env = jinja_env

    async def __call__(self, state: dict) -> dict:
        rendered_config = self._render_jinja(self.config, state)
        try:
            result = await self.execute(rendered_config, state)
        except Exception as exc:
            await self._publish_event("node.error", state, error=str(exc))
            raise
        return {self.config["id"]: result}  # LangGraph 自动 merge 到 state

    async def execute(self, config, state) -> dict:
        raise NotImplementedError
```

### 3. LLM 节点（litellm + LangChain ChatLiteLLM）

**两条路径选其一**（架构上等价，选择更直接的 litellm.acompletion）：

```python
# backend/app/agent_builder/workflow/nodes/llm.py
import litellm
from tenacity import retry, stop_after_attempt, wait_exponential

class LLMNodeExecutor(BaseNodeExecutor):
    async def execute(self, config: dict, state: dict) -> dict:
        messages = self._build_messages(config)  # 三段或 raw_prompt
        
        @retry(
            stop=stop_after_attempt(config.get("retry_count", 3)),
            wait=wait_exponential(multiplier=config.get("backoff_base_sec", 1), max=60),
            reraise=True,
        )
        async def _call_llm():
            return await asyncio.wait_for(
                litellm.acompletion(
                    model=config["model"],
                    messages=messages,
                    temperature=config.get("temperature", 0.7),
                ),
                timeout=config.get("timeout_sec", 30),
            )

        response = await _call_llm()
        return {
            "message": response.choices[0].message.content,
            "role": response.choices[0].message.role,
            "usage": dict(response.usage),
            "model": config["model"],
        }
```

**为何不用 ChatLiteLLM**：直接走 `litellm.acompletion()` 更简单（少一层抽象）；ChatLiteLLM 是 LangChain 风格的 BaseChatModel，需要构造 HumanMessage/SystemMessage 列表，对 Jinja2 模板组装 messages 反而更复杂。两者底层都是 litellm，效果等价。

### 4. State Pointer Pattern（CLAUDE.md 2.6 防 checkpoint 膨胀）

**实现位置**：在 BaseNodeExecutor.__call__ 返回前的 `_swap_large_values_to_pointers` 中间件层。

```python
# backend/app/agent_builder/workflow/state_pointer.py
LARGE_THRESHOLD_BYTES = 4096

async def write_state_with_pointers(
    state_delta: dict, workspace_id: UUID, instance_id: UUID, redis: Redis
) -> dict:
    """对每个值序列化检查长度，超过 4KB 写 Redis 替换为 pointer。"""
    out = {}
    for key, value in state_delta.items():
        encoded = json.dumps(value, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > LARGE_THRESHOLD_BYTES:
            ptr_uuid = uuid.uuid4().hex
            redis_key = f"agent_builder:state_ptr:{workspace_id}:{instance_id}:{ptr_uuid}"
            await redis.set(redis_key, encoded, ex=30 * 86400)
            out[key] = f"__ptr__:redis:state:{ptr_uuid}"
        else:
            out[key] = value
    return out

async def read_state_with_pointers(
    state: dict, workspace_id: UUID, instance_id: UUID, redis: Redis
) -> dict:
    """递归扫描 state 找 __ptr__:redis:state:* 拉回真实值。"""
    # 实现 in 上层服务读 state 时透明替换
```

**对节点透明**：节点 `execute()` 只看到原始 dict，不感知 pointer。

### 5. SSE 推送拓扑（LangGraph stream → Redis pub/sub → SSE channel）

```
┌─ Worker（arq）─────────────────────────────────────────────┐
│  async for event in compiled_graph.astream(input,         │
│                          stream_mode="updates"):          │
│      seq = await redis.incr(f"...:event_seq:{instance_id}")│
│      packet = {"id": seq, "event": "node.start", ...}     │
│      await redis.publish("agent_builder:instance_events:" │
│                          f"{instance_id}", json.dumps(packet))│
│      await redis.xadd(f"...:event_log:{instance_id}", ..., │
│                       maxlen=~3600)                       │
└────────────────────────────────────────────────────────────┘
                            │
                            ▼ (pub/sub)
┌─ API（FastAPI EventSourceResponse）────────────────────────┐
│  GET /api/agent_builder/v1/instances/<id>/events          │
│  → 校验 session + workspace_id                            │
│  → if Last-Event-ID header: 从 Redis Stream xrange 补发    │
│  → async with redis.pubsub() as ps:                       │
│      ps.subscribe(channel)                                 │
│      async for msg in ps.listen():                        │
│          yield ServerSentEvent(id=seq, data=...)          │
└────────────────────────────────────────────────────────────┘
```

**关键点**：
- LangGraph `stream_mode="updates"` 每节点完成回吐 `{node_id: state_delta}`
- Worker 进程负责生事件 + 写 Redis Stream + 发 Redis pub/sub
- API 进程订阅 Redis pub/sub 转发 SSE
- 重连时按 Last-Event-ID 从 Redis Stream 补发（保留 1 小时事件即可）

### 6. DSL 验证器（单遍扫描，输出全部 errors）

```python
# backend/app/agent_builder/workflow/validator.py
@dataclass
class ValidationError:
    severity: Literal["error", "warning"]
    code: str  # cycle / undefined_var / invalid_config / start_has_inbound 等
    message: str  # 中文
    node_id: str | None = None
    edge_id: str | None = None
    field_path: str | None = None  # 如 "config.user_prompt"

class DSLValidator:
    def validate(self, dsl: dict) -> list[ValidationError]:
        errors = []
        errors.extend(self._validate_structure(dsl))      # DAG / 入边出边规则
        errors.extend(self._validate_variables(dsl))      # Jinja2 变量符号表
        errors.extend(self._validate_node_configs(dsl))   # JSON Schema
        return errors
```

**关键算法**：
- **DAG 成环**：DFS 标记 white/gray/black，gray 边即环
- **变量符号表**：节点拓扑序遍历，每个节点的 outputs 加入符号表（key = `<node_id>.<field>`），后续节点 Jinja2 AST 扫描引用必须在符号表中
- **JSON Schema 校验**：每个 node type 维护 `NODE_SCHEMAS: dict[str, jsonschema.Validator]`，校验 config 字段类型和必填

### 7. Workflow / Instance 数据模型（新增表）

| 表 | 用途 |
|---|---|
| `workflows` | 工作流主表（id, workspace_id, name, status='draft'\|'published', created_by, updated_at） |
| `workflow_versions` | 草稿/发布版本快照（workflow_id, version_no, dsl JSONB, published_at, published_by） |
| `flow_instances` | 实例（id, workspace_id, workflow_id, workflow_version_id, dsl_snapshot JSONB, status, created_by, created_at, completed_at） |
| `node_states` | 节点状态（id, workspace_id, instance_id, node_id, status, started_at, completed_at, error, retries） |

**额外（沿用 Phase 1 模型）**：
- `audit_logs`：每次实例创建/中止/失败写一条

**LangGraph checkpoint 表**：用 `langgraph-checkpoint-postgres` 自带 schema（默认表名 `checkpoints` / `checkpoint_writes` / `checkpoint_blobs`）；不写 Alembic（由 PostgresSaver.setup() 创建）。

**索引规则**（CLAUDE.md 2.4 多租户隔离）：
- 所有表 PK 复合索引第一列 `workspace_id`
- 列表查询索引 `(workspace_id, created_at DESC)`
- `flow_instances(workspace_id, workflow_id, status, created_at DESC)` 用于实例列表过滤

### 8. thread_id 含 workspace 前缀（PITFALLS Pitfall 13）

```python
thread_id = f"{workspace_id}:{flow_instance_id}"
```

### 9. React Flow 画布架构

```
web/src/components/agent-builder/canvas/
├── canvas.tsx                # 主 ReactFlow 组件
├── nodes/
│   ├── start-node.tsx       # 自定义节点 (handles + label)
│   ├── end-node.tsx
│   ├── llm-node.tsx
│   ├── tool-node.tsx
│   └── if-else-node.tsx
├── panels/
│   ├── node-palette.tsx     # 左侧拖拽栏
│   ├── config-panel.tsx     # 右侧动态表单（按 node type schema 渲染）
│   └── issue-list.tsx       # 底部 Issue 清单
├── store/
│   ├── canvas-store.ts      # Zustand：nodes, edges, selectedNodeId
│   └── validator-store.ts   # 实时 issues
└── lib/
    ├── dsl-converter.ts     # ReactFlow nodes/edges <-> DSL JSON
    └── validator.ts         # 前端 DSL 校验（与后端逻辑等价）
```

**Zustand store 与 ReactFlow 集成**：用 `applyNodeChanges` / `applyEdgeChanges` 适配 ReactFlow 受控模式。

---

## Don't Hand-Roll（用现成的）

| 不要自建 | 用现成的 |
|---|---|
| HTTP client | `httpx.AsyncClient`（已在 deps） |
| Jinja2 沙箱 | `jinja2.sandbox.SandboxedEnvironment` |
| 拓扑排序 / 环检测 | `graphlib.TopologicalSorter`（Python 3.9+ 标准库） |
| JSON Schema 校验 | `jsonschema` 库 |
| 重试 | `tenacity`（已在 deps） |
| LangGraph state | LangGraph 原生 `StateGraph` + `TypedDict` |
| Postgres checkpoint | `langgraph.checkpoint.postgres.aio.AsyncPostgresSaver` |
| LLM 多 provider | `litellm.acompletion()` |
| SSE | `sse-starlette.EventSourceResponse` |
| Redis pub/sub | `redis.asyncio.Redis.pubsub()` |
| Redis Stream | `redis.asyncio.Redis.xadd/xrange` |
| Canvas | `@xyflow/react` 自定义节点（不要造 SVG） |
| Form rendering | `react-hook-form` + `zod`（已在 deps） |

---

## Common Pitfalls（必须防）

### Pitfall 1：Checkpoint 写入放大（已在 CONTEXT.md 锁定 Pointer Pattern）

**症状**：每节点写 4KB+ state → 10 节点 × 100 并发 = WAL 暴增 → 复制延迟 > 1s

**防护**：所有 state 字段写入前过 `write_state_with_pointers()`；E2E 测试 50 步执行后 `checkpoints` 表 < 10MB。

### Pitfall 6：多租户跨租户泄漏（CLAUDE.md 2.4）

**症状**：连接池复用时 `app.workspace_id` 上下文残留

**防护**：
1. `workflows` / `workflow_versions` / `flow_instances` / `node_states` 全部经 `WorkspaceScopedQuery`
2. thread_id 含 workspace 前缀
3. 集成测试：双 workspace 互访任意实例 API 必须返回 404 或空集

### Pitfall 9：DSL 死锁 + 无限循环

**症状**：用户连成环，编译时未检测

**防护**：
1. DSLValidator 拓扑排序 + DFS 检测环
2. 前端 React Flow 实时检测（连边后立即 DFS）
3. **未来 Loop 节点（Phase 5）** 强制 max_iterations

### Pitfall 11：Fork 上游 diverge（CLAUDE.md 2.3）

**症状**：直接改 flock 已有目录树

**防护**：所有 Phase 2 代码放 `backend/app/agent_builder/workflow/`、`web/src/components/agent-builder/canvas/`、新 API 路由放 `backend/app/agent_builder/api/`；不动 flock 已有节点目录 `backend/app/core/` 和 `web/src/components/nodes/`。

### Pitfall 13：thread_id 无 workspace 前缀（PITFALLS）

**防护**：`thread_id = f"{workspace_id}:{instance_id}"`

### Pitfall 2 & 5（HITL 相关）

Phase 2 不涉及 HITL，但 LangGraph 1.2 + checkpoint 3.1 升级要为 Phase 3 的 `interrupt()/Command(resume=)` 做好兼容验证。研究确认：1.2.0 + checkpoint-postgres 3.1.0 原生支持 `interrupt()` 和 `Command(resume=...)` 模式（langgraph 官方文档），Phase 3 直接用。

---

## Validation Architecture

**三层测试（CLAUDE.md 2.2 强制）**：

| 层 | 工具 | 覆盖目标 | 关键场景 |
|---|---|---|---|
| 单元 | pytest | 每个 service / executor / validator | DSLCompiler / 各 Node executor / Jinja 渲染 / Pointer 写读 / 验证器 4 类错误 |
| 集成 | pytest + 真实 DB / Redis | API + DB + LangGraph 端到端 | POST /workflows → 编译 → 创建 instance → 跑完 → DB 落地；service restart 后 instance 恢复 |
| E2E | Playwright | 浏览器视角 | Canvas 拖 5 节点 → 发布 → 运行 → SSE 实时刷新 → 实例列表过滤 |

**E2E 必测场景**（ROADMAP 5 条 success criteria 对应）：

1. **画布拖拽 5 节点 + 连线 + 保存草稿 + 发布**（覆盖 #1）
2. **运行实例 + SSE 实时显示节点状态**（覆盖 #2）
3. **服务重启 + checkpoint 恢复继续执行**（覆盖 #3，需 docker 重启 api/worker）
4. **实例列表过滤 + 分页 + 搜索**（覆盖 #4）
5. **画布连成环 / 引用悬空变量 → 保存被拒 + 错误高亮**（覆盖 #5）

---

## Code Examples（参考开源实现）

| 项目 | 借鉴点 | 文件位置 |
|---|---|---|
| Dify | Canvas UI + 节点配置面板布局 | `/Users/admin/ai/ref/dify/repo/web/app/components/workflow/` |
| LangGraph 官方 | StateGraph + PostgresSaver 用法 | https://github.com/langchain-ai/langgraph/tree/main/examples |
| flock 本仓 | reactflow 节点定义、Zustand store 模式 | `web/src/components/workflow/` / `web/src/components/nodes/` |
| KirtiJha/langgraph-interrupt-workflow-template | FastAPI + LangGraph stream → SSE 桥接 | GitHub |
| litellm 文档 | acompletion + provider 路由 | https://docs.litellm.ai/docs/providers |

**约束**：参考但不复制（Fork discipline + 独立模块）；学习 API 形式而非直接 import。

---

## Phase 2 工作排期（参考拆分）

| Wave | Plans | 内容 |
|---|---|---|
| 1 | 02-01 | LangGraph 1.2 升级 + checkpoint 3.1 + 兼容性 spike（前置） |
| 2 | 02-02、02-03 | DSL Schema + 编译器 + 验证器（后端） / React Flow Canvas 基础（前端）并行 |
| 3 | 02-04、02-05、02-06 | LangGraph 节点（Start/End/IfElse/Tool） / LLM 节点（litellm） / 状态指针（Redis pointer）并行 |
| 4 | 02-07、02-08 | Execution Engine + SSE 桥接 / Instances API + UI 列表 并行 |
| 5 | 02-09 | DSL Validation 前端实时检查 + 错误 UI |
| 6 | 02-10 | E2E 验收（覆盖 ROADMAP 5 条）|

**为何这样切**：
- 第 1 波单 plan（环境前置，影响所有后续）
- 第 2-4 波每波 2-3 个独立 plan 并行（CLAUDE.md 2.1 强制并行）
- 第 6 波单 plan 收尾（E2E 必须放在所有功能完成后）

---

## Sources

- **STACK.md**（Phase 2 锁定版本，2026-05-16 PyPI 验证）
- **PITFALLS.md** 4 个相关坑（1/6/9/11/13）
- **CLAUDE.md** 强制规则（fork / 多租户 / 测试 / pointer）
- **CONTEXT.md** 16 条 Phase 2 决策（user 已锁定）
- **flock 现有代码**（fork base，backend/app/* + web/src/* 不动）
- **LangGraph 官方文档**（1.2 changelog + checkpoint-postgres 3.1 migration guide）
- **litellm 官方文档**（acompletion + provider list）
- **Dify 源码**（Canvas UI 借鉴，不复制）

---

*Phase 2 research synthesized: 2026-05-16 by orchestrator*
*All locked decisions from CONTEXT.md preserved verbatim*
