# Dify 阅读笔记 — HITL 节点 executor（interrupt/resume 集成）

> 日期: 2026-05-17
> 仓库: https://github.com/langgenius/dify (commit c0bdd679, local clone /Users/admin/ai/ref/dify/repo/)
> Stars: ~141k
> Plan: 03-02 HITL node executor — LangGraph 1.2 interrupt + Command(resume) 集成

---

## 1. 项目概述（一句话）

Dify 是国内最成熟的开源 LLM workflow 平台（Apache + 部分 AGPL），其 HITL（Human-In-The-Loop）实现已在生产环境打磨 2 年余；本次阅读的目标是借鉴 **节点 pause/resume 流程的状态机设计 / payload schema / pause-reason 流转**，用 LangGraph 1.2 原生 interrupt + Command(resume) 重新实现一遍（不照抄 AGPL 源码）。

## 2. 技术栈（关键技术选择）

| 维度 | Dify | 本项目（agent-builder） | 备注 |
|---|---|---|---|
| Graph 框架 | 自研 graphon | LangGraph 1.2.0 | 我们用 LangGraph 原生 interrupt() |
| Checkpoint | 自研持久化 + Redis cache | langgraph-checkpoint-postgres 3.1 (AsyncPostgresSaver) | 已在 Phase 2 02-01 落地 |
| HITL pause | `pause_reason` 列表（多类型 pause） | `interrupt({...})` 单值 payload | LangGraph 1.2 native，更简洁 |
| Form schema | `FormDefinition` Pydantic discriminator | JSON Schema Draft-7（jsonschema 4.x） | 直接 portable，前端 RJSF 也吃 |
| Resume 注入 | `resume_app_execution(form_id, submitted_data)` Celery 任务 | `graph.ainvoke(Command(resume={...}), {"configurable":{"thread_id":...}})` | LangGraph 内建幂等 + checkpoint 已写 |
| 状态机 | `HumanInputFormStatus`（pending/submitted/expired） | 4 态枚举（submit/approve/return/reject） → node status 5 → 3 终态 | 我们更细颗粒 |
| Recipient 三态 | Bound / External / WebApp | v1 只 single（actor_id），Phase 4 才上多人 | 简化 |

## 3. 架构要点（核心架构模式）

```
Dify (graphon) HITL flow：
   compile(workflow) → run_node → node 发现是 HumanInput → 
     write HumanInputForm row + HumanInputFormRecipient（携 access_token） + 
     emit pause_reason=HUMAN_INPUT_REQUIRED → 
     workflow runner 看到 pause_reason 即终止并写 checkpoint
   user POST /forms/<token>/submit → 
     human_input_service.submit_form() 校验 form_schema → 
     resume_app_execution(form_id, submitted_data) Celery 任务
       → 重新加载 checkpoint，调用 graphon.resume_with_form_submission()
       → 节点 re-execute，看到 form 已 submitted 直接读 submitted_data 返回

agent-builder HITL flow（本 plan 实现）：
   DSLCompiler 见到 type=hitl → NODE_EXECUTORS["hitl"](node_def)
   ExecutionEngine.invoke(state, config{thread_id}) →
     HITLNodeExecutor.__call__(state):
       1. 检查 state.__node_state_id（由 ExecutionEngine 在 enter 时注入）
       2. interrupt({node_state_id, phase, form_schema, deadline_at, current_actor})
          → LangGraph 自动 raise GraphInterrupt + write checkpoint
       3. (graph 暂停，DB 已持久化全部 state)
   用户 POST /hitl/action/<jwt> → 
     graph.ainvoke(Command(resume={action, reason, form_data, jti, actor_id, ip, ua}), {"thread_id":...})
     → LangGraph 重新 invoke HITLNodeExecutor.__call__：
       1. interrupt() 检测到 resume value 已存在 → 直接返回 {action, ...}
       2. 节点函数继续：validate_form_data + append_record + 返回 {self.node_id: decision_dict}
```

## 4. 可借鉴的设计模式（具体文件路径 + 模式名 + 一句话说明）

### 4.1 EmailDeliveryConfig 收件人三态分离
- **文件**: `api/core/workflow/human_input_adapter.py:41-66`
- **模式**: `BoundRecipient | ExternalRecipient`（pydantic discriminator）+ `EmailRecipients.items[]`
- **借鉴**: 本 plan v1 single 模式只一个 actor_id（users.id），暂不区分内/外部；Phase 4 多人审批引入

### 4.2 EmailDeliveryConfig.body 占位符替换
- **文件**: `api/core/workflow/human_input_adapter.py:101-119`
- **模式**: `URL_PLACEHOLDER = "{{#url#}}"` + `replace_url_placeholder(body, url)` + 二次 variable_pool 渲染
- **借鉴**: 03-04 邮件 Jinja2 模板 + 03-06 token URL 注入会用类似模式

### 4.3 HumanInputSurface 路由分层
- **文件**: `api/core/workflow/human_input_policy.py:11-21`
- **模式**: `_ALLOWED_RECIPIENT_TYPES_BY_SURFACE` 把 service_api / console 路径分离；前者只允许 STANDALONE_WEB_APP recipient，后者允许 console/backstage
- **借鉴**: 本 plan 暂不区分（v1 只 public hitl 路径）；Phase 5 多通道引入时复用此 surface 概念

### 4.4 RECIPIENT_TOKEN_PRIORITY 优先级表
- **文件**: `api/core/workflow/human_input_policy.py:25-29` + `get_preferred_form_token()` 41-53
- **模式**: 同一 form 可能有多个 recipient，按 BACKSTAGE > CONSOLE > STANDALONE_WEB_APP 取最高优先 token 暴露给客户端
- **借鉴**: v1 single 模式不需要（actor 与 token 1:1）；Phase 4 多人审批 + escalation 时用得到

### 4.5 enrich_human_input_pause_reasons 富化模式
- **文件**: `api/core/workflow/human_input_policy.py:56-73`
- **模式**: 把 `form_token` / `expiration_time` 注入 pause_reason 字典，前端流式响应直接渲染
- **借鉴**: 本 plan interrupt 的 payload 直接含 `deadline_at` / `form_schema` / `node_state_id` 三字段，省了 enrich 一步

### 4.6 HumanInputService submitted_data 校验
- **文件**: `api/services/human_input_service.py:1-99`（特别是 `FormSubmittedError` / `validate_human_input_submission`）
- **模式**: 提交时一次性 `validate_human_input_submission(form_definition, submitted_data)` + 已提交 412 重试拦截
- **借鉴**:
  - hitl_payload.py `validate_form_data()` 走 jsonschema Draft7Validator
  - 03-06 POST /hitl/action 用 jti UNIQUE 拦重提交（不用 412 用 409 + 同节点其他 token 一并失效）

## 5. 与本项目的关系（如何应用到当前 plan）

| 本 plan 文件 | 借鉴自 Dify | 改写要点 |
|---|---|---|
| `nodes/hitl.py` | `human_input_adapter.py` + `human_input_policy.py` | 用 LangGraph 1.2 原生 interrupt 替代 graphon pause_reason；不抄源码 |
| `hitl_payload.py` `build_initial_payload` | Dify `FormDefinition` + `HumanInputFormRecipient.expiration_time` 一并写 | 纯函数 + 默认值合并 + ISO8601 时间格式 |
| `hitl_payload.py` `compute_next_status` | Dify `HumanInputFormStatus` 状态机 | 我们四态而非三态（增加 returned） |
| `hitl_payload.py` `validate_form_data` | `validate_human_input_submission()` | jsonschema Draft7Validator，依赖 jsonschema 4.x 而非自研 |
| `hitl_service.py` `batch_create_tokens` | Dify `HumanInputForm` + `HumanInputFormRecipient` 1:N 关系 | 简化为 hitl_tokens 单表，每 allowed_action 一行 |
| `hitl_service.py` `resolve_allowed_actions` | Dify `RECIPIENT_TOKEN_PRIORITY` 优先级 | v1 只两个 phase（submit/review）固定 actions |

## 6. 与 hr/offboarding-flow 对照（5-10 行业务参考）

hr/offboarding-flow（M3 期初稿）在 PRD §7 「双通道通知 + 邮件深链审批」与本 phase 同源。其 LangGraph interrupt + Postgres saver 流程印证了：
- `interrupt(value)` 第一次抛 `GraphInterrupt`，写 checkpoint；第二次 ainvoke 时 `Command(resume=v)` 注入 v，interrupt() 直接返回 v
- thread_id 须保持 `{workspace_id}:{instance_id}`（防 Pitfall 13 跨租户碰撞 — 已在 02-01 落地）
- pause 期间 DB checkpoint 已写完整 state，进程重启可恢复（已在 02-03 测过）

业务对照：hr 离职流程的「主管审批 → HR 审批 → 终结」三段是 v2 多人审批（HITL-02），v1 单段 single 即可演示价值。

## 7. LangGraph 1.2 interrupt/resume 最佳实践（关键深度笔记）

### 7.1 interrupt() 是函数级 pause，节点函数会被"重跑"

来自 `langgraph/types.py:801-890`（venv 中已实测）：

```python
def interrupt(value: Any) -> Any:
    """Interrupt the graph with a resumable exception from within a node.
    ...
    The graph resumes from the start of the node, **re-executing** all logic.
    ...
    """
    conf = get_config()["configurable"]
    scratchpad = conf[CONFIG_KEY_SCRATCHPAD]
    idx = scratchpad.interrupt_counter()
    if scratchpad.resume:
        if idx < len(scratchpad.resume):
            conf[CONFIG_KEY_SEND]([(RESUME, scratchpad.resume)])
            return scratchpad.resume[idx]
    # ... no resume → raise GraphInterrupt
```

**关键**：节点函数 resume 后**从头重跑**，不是"从 interrupt 处继续"。所以 pre-interrupt 副作用（写 DB、发邮件）会**执行两次**。

**对策**：本 plan 把"创建 token + 入队邮件"这种副作用放到 **ExecutionEngine 注入 __node_state_id 时**（外部 once-only），而不是在 `__call__` 内部。`__call__` 内部只做：
1. 读 state.__node_state_id（由 engine 注入 once）
2. interrupt(payload)（resume 后会直接返回 resume value）
3. 校验 form_data + 返回 decision dict

副作用归外，纯函数归内 — 第二次 re-execute 时也安全。

### 7.2 Command(resume=...) 注入示例（venv 实测）

```python
# 来自 langgraph/types.py:867-879 example block
config = {"configurable": {"thread_id": uuid.uuid4()}}
for chunk in graph.stream({"foo": "abc"}, config):
    print(chunk)  # > {'__interrupt__': (Interrupt(value='what is your age?', id='...'),)}

# resume
for chunk in graph.stream(Command(resume="some input from a human!!!"), config):
    print(chunk)  # > {'node': {'human_value': 'some input from a human!!!'}}
```

**对应到本项目**：
```python
# 03-06 POST /hitl/action handler
await graph.ainvoke(
    Command(resume={
        "action": "approve",
        "reason": "",
        "form_data": {...},
        "jti": str(jti),
        "actor_id": str(user.id),
        "ip": client_ip,
        "ua": user_agent,
    }),
    {"configurable": {"thread_id": f"{workspace_id}:{instance_id}"}},
)
```

### 7.3 thread_id resume 并发：三层防护

来自 PITFALLS.md Pitfall 2（并发竞争）：

| 层 | 实现 | 已落地 |
|---|---|---|
| Postgres advisory lock | `SELECT pg_advisory_xact_lock(hash(thread_id))` | 03-06 |
| jti 原子消费 | `UPDATE hitl_tokens SET used_at=NOW() WHERE jti=:jti AND used_at IS NULL RETURNING *` 零行 = 409 | 03-01（HitlTokenStore.consume） |
| LangGraph checkpoint 锁 | AsyncPostgresSaver 内建 `latest_version`（乐观并发） | LangGraph 1.2 内建 |

本 plan 不实现 1 与 3（外层）；专注节点内部 interrupt + payload 计算。

### 7.4 单节点 multi-actor 不在 Phase 3 范围

`build_initial_payload` 接受 `approvers: list[UUID]` 参数（默认 [current_actor_id]）但 v1 不暴露 `mode=sequential/parallel_*`。Phase 4 才会在节点 enter 时根据 approval_chain.mode 决定是发 1 个 actor 邮件还是发多个。

### 7.5 重要陷阱：LangGraph 剥离 dunder 前缀字段（集成测试发现）

实测 venv 中 langgraph 1.2.0：**`__xxx` 前缀的 state 字段会被 StateGraph 内部当作"保留命名空间"剥离**，节点函数中看不到此字段。

```python
# bad — node 看不到此字段
state = {"__node_state_id": "abc"}

# good — 用单下划线前缀（约定 "internal" 但不被剥离）
state = {"_node_state_id": "abc"}
```

**本 plan 修正**：所有 `__node_state_id` 改为 `_node_state_id`，包括：
- `HITLNodeExecutor.__call__` 内读取
- 集成测试初始 state
- 后续 03-06 ExecutionEngine 注入时的字段名也按此约定

**根因**：LangGraph 1.2 内部用 `__interrupt__` / `__pregel_pull__` 等 dunder key 做控制消息，把所有 `__xxx` 视为保留 namespace 剥离。

---

## 8. 防陷阱小结（PITFALLS）

| Pitfall | 本 plan 防护 |
|---|---|
| Pitfall 1 (checkpoint 膨胀) | form_schema 写 node_state.payload 限制在 4KB；超大 form_schema → 03-06 用 Redis pointer |
| Pitfall 2 (interrupt 并发) | 本 plan 节点内部不防护，03-06 实现 advisory lock；本 plan 集成测试验证 single resume 流 |
| Pitfall 3 (Safe Links GET 消费) | 本 plan 不做 API，但单测中确认 `__call__` 不直接写 DB（POST 路径才会调 HitlTokenStore.consume） |
| Pitfall 13 (thread_id 跨租户) | 02-01 已落 `{workspace_id}:{instance_id}` 格式；本 plan 测试中复用 |

---

## 9. 测试策略对照

| 测试层 | 本 plan 范围 | 文件 |
|---|---|---|
| 单元（纯函数） | build_initial_payload / append_record / compute_next_status / validate_form_data | test_hitl_payload.py |
| 单元（节点级，mock interrupt） | __call__ 调 interrupt 参数正确 + resume 后行为 | test_hitl_node_executor.py |
| 集成（真实 LangGraph + InMemorySaver） | 端到端 pause + Command(resume) + state 落地 | test_hitl_interrupt_resume.py |
| 集成（真实 PG） | HitlService.batch_create_tokens 写 3 行 hitl_tokens | test_hitl_service.py |

---

## Attribution

- 仅借鉴 Dify 的设计模式 / 字段命名 / 状态机思路
- **未拷贝 Dify 源码**（Dify AGPL，本项目 Apache）
- LangGraph 1.2 interrupt/resume 用法来自 official docs + 仓库内 venv types.py docstring example
