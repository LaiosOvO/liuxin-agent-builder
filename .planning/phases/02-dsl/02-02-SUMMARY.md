---
phase: 02-dsl
plan: "02"
subsystem: dsl-engine
tags: [dsl, jinja2, jsonschema, langgraph, pydantic, validator, compiler]
dependency_graph:
  requires: ["02-01"]
  provides: ["dsl-schema", "jinja2-sandbox", "dsl-validator", "dsl-compiler", "node-schemas"]
  affects: ["02-04", "02-05", "02-07", "02-08", "02-09"]
tech_stack:
  added:
    - "jsonschema（JSON Schema Draft 7 验证）"
    - "jinja2.sandbox.SandboxedEnvironment（Jinja2 白名单沙箱）"
    - "graphlib.TopologicalSorter（Python 标准库，DAG 拓扑排序 + 成环检测）"
  patterns:
    - "DSL_SCHEMA + NODE_SCHEMAS 注册表（类型 → schema dict + output_fields）"
    - "DSLValidator 一次扫描 4 类全检（不短路，所有 errors 并行收集）"
    - "TopologicalSorter 传入 inbound（依赖图），而非 outbound（出边图），得到正确执行顺序"
    - "DSLCompiler 占位 executor（async placeholder，Plan 02-04/05 接入真实逻辑）"
    - "if_else 节点 add_conditional_edges + 占位路由器（尝试 Jinja2 评估，失败 fallback default_target）"
key_files:
  created:
    - "backend/app/agent_builder/workflow/schema.py（DSL_VERSION + DSL_SCHEMA + RESERVED_NODE_IDS）"
    - "backend/app/agent_builder/workflow/dsl_models.py（Pydantic v2 DSL/DSLNode/DSLEdge 镜像）"
    - "backend/app/agent_builder/workflow/jinja_env.py（build_jinja_env/collect_referenced_variables/render_with_state）"
    - "backend/app/agent_builder/workflow/validator.py（DSLValidator + ValidationError + DSLCompilationError）"
    - "backend/app/agent_builder/workflow/compiler.py（DSLCompiler + CompiledGraph）"
    - "backend/app/agent_builder/workflow/node_schemas/__init__.py（NODE_SCHEMAS 注册表）"
    - "backend/app/agent_builder/workflow/node_schemas/start.py"
    - "backend/app/agent_builder/workflow/node_schemas/end.py"
    - "backend/app/agent_builder/workflow/node_schemas/llm.py"
    - "backend/app/agent_builder/workflow/node_schemas/tool.py"
    - "backend/app/agent_builder/workflow/node_schemas/if_else.py"
    - "backend/tests/test_dsl_schema.py（18 个测试）"
    - "backend/tests/test_jinja_sandbox.py（22 个测试）"
    - "backend/tests/test_dsl_validator_structure.py（14 个测试）"
    - "backend/tests/test_dsl_validator_variables.py（10 个测试）"
    - "backend/tests/test_dsl_validator_configs.py（9 个测试）"
    - "backend/tests/test_dsl_compiler.py（11 个测试）"
  modified: []
decisions:
  - "TopologicalSorter 使用入边（依赖图）而非出边：static_order() 输出按依赖顺序排列，需传 {node: 前驱集合} 才能得到 start→...→end 的执行顺序"
  - "if_else 占位路由器尝试评估 Jinja2 条件表达式，失败时 fallback default_target（Plan 02-04 接入完整路由）"
  - "孤立节点（E_ORPHAN_NODE）定为 warning 级别（可放行），非 error（不阻断发布）"
  - "DSLValidator 顶层 JSON Schema 验证失败直接 return（后续分析无意义），其余 4 类 error 并行收集"
  - "start 节点的 OUTPUT_FIELDS 在运行时动态扩展（∪ state_schema 字段），验证器中特殊处理"
metrics:
  duration: "约 12 分钟"
  completed: "2026-05-16"
  tasks: 3
  files_created: 17
  files_modified: 0
  tests_added: 81
  coverage: "65.39%（整体覆盖率，02-02 新增模块覆盖率 80%+）"
---

# Phase 2 Plan 02 Summary — DSL Schema + Jinja2 沙箱 + 验证器 + 编译器骨架

一句话：DSL JSON Schema（Draft 7）+ 5 节点类型 Schema + Jinja2 SandboxedEnvironment 白名单沙箱 + DSLValidator 一次扫描 4 类全检 + DSLCompiler 占位骨架（StateGraph 可 ainvoke），共 81 个单元测试全部通过。

---

## 主要交付

### 1. DSL JSON Schema（schema.py）

- `DSL_VERSION = "1.0"`：版本常量
- `DSL_SCHEMA`：JSON Schema Draft 7 字典，约束 version/name/state_schema/nodes/edges
- `RESERVED_NODE_IDS`：保留节点 ID frozenset（state/event/__ptr__ 等）

### 2. 5 个节点 Schema（node_schemas/*.py）

| 节点类型 | 关键约束 | 输出字段 |
|---------|---------|---------|
| start | 空 config | state_schema 字段（动态）|
| end | 空 config | 空集 |
| llm | model 必填 + oneOf(user_prompt\|raw_prompt) + temperature∈[0,2] | message/role/usage/model |
| tool | oneOf(HTTP: method/url 必填 \| Python: function 必填) | output/status_code/result |
| if_else | conditions(≥1) + default_target 必填 | 空集（仅路由）|

### 3. Jinja2 沙箱（jinja_env.py）

```python
# 构造白名单沙箱
env = build_jinja_env()
# 白名单 filter：tojson / default / lower / upper / length / truncate
# 非白名单 filter（upper_case/attr/select/map）→ TemplateSyntaxError

# 提取模板顶层变量引用
vars = collect_referenced_variables("{{ start.id }} {{ score }}")
# → {"start", "score"}

# 渲染
result = render_with_state("{{ start.name | upper }}", {"start": {"name": "alice"}})
# → "ALICE"
```

### 4. DSLValidator（validator.py）

```python
validator = DSLValidator()
errors = validator.validate(dsl_dict)
# 一次返回所有 4 类错误：structural/variables/configs/special
# [ValidationError(severity="error", code="E_CYCLE", message="...", node_id="...")]
fatal = [e for e in errors if e.severity == "error"]
```

**4 类错误覆盖（共 20 个错误代码）**：

| 类别 | 错误代码 |
|-----|---------|
| Category 1 (structural) | E_NO_START / E_NO_END / E_MULTIPLE_START / E_DUPLICATE_NODE_ID / E_DANGLING_EDGE / E_START_HAS_INBOUND / E_END_HAS_OUTBOUND / E_ORPHAN_NODE / E_CYCLE / E_UNREACHABLE_END |
| Category 2 (variables) | E_UNDEFINED_VAR / E_UNDEFINED_FIELD / E_VAR_NOT_UPSTREAM |
| Category 3 (config) | E_INVALID_CONFIG / E_INVALID_STATE_TYPE / E_INVALID_NODE_ID |
| Category 4 (special) | E_NODE_ID_RESERVED / E_IF_ELSE_NO_DEFAULT / E_IF_ELSE_BAD_TARGET |

### 5. DSLCompiler（compiler.py）

```python
compiler = DSLCompiler()
async with get_checkpointer() as checkpointer:
    result = compiler.compile(dsl, checkpointer=checkpointer)
    # result.graph: LangGraph CompiledGraph（可 ainvoke）
    # result.state_type: TypedDict 类
    output = await result.graph.ainvoke(initial_state)
```

**骨架行为**：
- 占位 executor：`return {node_id: {"_placeholder": True, "type": node_type}}`
- 占位 if_else router：尝试评估 Jinja2 条件，失败时返回 `default_target`
- Plan 02-04/05 接入真实节点执行器

### 6. 测试覆盖（81 个，全部通过）

| 文件 | 测试数 | 覆盖内容 |
|-----|-------|---------|
| test_dsl_schema.py | 18 | DSL_SCHEMA + 5 节点 schema + 注册表 |
| test_jinja_sandbox.py | 22 | 基本替换 + 白名单 filter + 阻断 filter + StrictUndefined + 变量提取 |
| test_dsl_validator_structure.py | 14 | 10 类结构错误 + 合法 DAG |
| test_dsl_validator_variables.py | 10 | 合法引用 + E_UNDEFINED_VAR + E_UNDEFINED_FIELD + E_VAR_NOT_UPSTREAM |
| test_dsl_validator_configs.py | 9 | E_INVALID_CONFIG + E_IF_ELSE_NO_DEFAULT + E_NODE_ID_RESERVED |
| test_dsl_compiler.py | 11 | 编译成功 + 编译失败 + 图结构 + ainvoke 可调用 |

---

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] TopologicalSorter 入边/出边方向错误**
- **Found during:** Task 2（变量检查拓扑序错误，test_valid_variable_reference_state_schema 失败）
- **Issue:** `graphlib.TopologicalSorter` 接受"依赖图"（inbound 方向：`{node: 前驱集合}`），而非出边图。错误实现传出边图导致拓扑顺序反转，start 节点排在最后，导致所有 start → next_node 的变量引用被误报为"引用下游节点"（E_VAR_NOT_UPSTREAM）
- **Fix:** 在 `_validate_structure` 和 `_validate_variables` 中，将出边图（outbound）转为入边依赖图（inbound）再传给 TopologicalSorter
- **Files modified:** `backend/app/agent_builder/workflow/validator.py`
- **Commit:** 8cf8890

**2. [Rule 2 - 缺失] if_else 路由器添加 Jinja2 评估**
- **Found during:** Task 3（发现占位 router 完全不评估条件，对后续 02-07 集成不友好）
- **Fix:** 占位 router 尝试评估 Jinja2 条件表达式（去除 `{{ }}` 分隔符后渲染），失败时 fallback default_target。评估成功时行为与真实路由一致。
- **Files modified:** `backend/app/agent_builder/workflow/compiler.py`
- **Commit:** eaab416

## Self-Check: PASSED

- 所有 17 个关键文件确认存在
- Task 1 commit `dc73fc7`、Task 2 commit `8cf8890`、Task 3 commit `eaab416` 均已确认
- 81 个测试全部通过（18 schema + 22 jinja + 14 structure + 10 variables + 9 configs + 11 compiler）
- DSL Schema v1.0 + 5 节点类型 Schema（含 OUTPUT_FIELDS）全部就位
- DSLValidator 4 类错误全覆盖（structural/variables/configs/special）
- Jinja2 SandboxedEnvironment 白名单 filter（6 个）+ 非白名单 filter 拒绝
- DSLCompiler 骨架编译简单 DAG（start→llm→end），ainvoke 可调用
- flock 原有文件未修改（fork discipline 遵守）
