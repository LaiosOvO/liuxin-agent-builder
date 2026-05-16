---
phase: 02-dsl
plan: "04"
subsystem: workflow-nodes
tags: [executor, start, end, if_else, tool, node-registry, jinja2, tenacity, httpx]
dependency_graph:
  requires: [02-02]
  provides: [NODE_EXECUTORS, BaseNodeExecutor, StartNodeExecutor, EndNodeExecutor, IfElseNodeExecutor, ToolNodeExecutor, tool_registry]
  affects: [02-05, 02-07, compiler.py]
tech_stack:
  added: [tenacity, httpx, pytest-httpx]
  patterns: [BaseNodeExecutor抽象基类, NODE_EXECUTORS注册表, IfElse延迟Jinja2求值, TOOL_REGISTRY装饰器注册]
key_files:
  created:
    - backend/app/agent_builder/workflow/nodes/base.py
    - backend/app/agent_builder/workflow/nodes/start.py
    - backend/app/agent_builder/workflow/nodes/end.py
    - backend/app/agent_builder/workflow/nodes/if_else.py
    - backend/app/agent_builder/workflow/nodes/tool.py
    - backend/app/agent_builder/workflow/nodes/__init__.py
    - backend/app/agent_builder/workflow/tool_registry.py
    - backend/tests/test_node_start_end.py
    - backend/tests/test_node_if_else.py
    - backend/tests/test_node_tool_http.py
    - backend/tests/test_node_tool_python.py
    - backend/tests/test_compiler_with_real_executors.py
    - docs/reading-dify-02-04-base-nodes-2026-05-16.md
  modified:
    - backend/app/agent_builder/workflow/compiler.py
    - backend/app/agent_builder/workflow/llm_client.py
decisions:
  - "IfElse.resolve_route 使用原始 self.config 而非 _render_config 结果：conditions[].expr 是 Jinja2 模板，提前渲染导致 UndefinedError，必须延迟到求值时"
  - "Tool Python 模式不传 timeout_sec（TOOL_PYTHON_SCHEMA 无此字段），HTTP 模式支持"
  - "NODE_EXECUTORS 手动注册（非 pkgutil 自动发现）：项目规模小，可读性优先"
  - "DSLCompiler._make_if_else_router 使用 IfElseNodeExecutor.resolve_route 而非内联实现，DRY"
  - "llm_client.py 修复：'return ... from exc' 语法错误（from 子句仅适用于 raise，不适用于 return）"
metrics:
  duration_minutes: 16
  completed_date: 2026-05-16
  tasks_completed: 3
  files_created: 13
  files_modified: 2
  tests_added: 37
---

# Phase 2 Plan 04: 基础节点 Executor + NodeRegistry Summary

一句话：4 个非 LLM 节点（Start/End/IfElse/Tool）executor + BaseNodeExecutor 基类（Jinja2 渲染 + tenacity 重试 + asyncio 超时）+ NODE_EXECUTORS 注册表 + 37 个测试全部通过，DSLCompiler 从 placeholder 升级为真实 executor 分发。

## 完成情况

### Task 0（Reading Doc Gate）
- Dify 阅读文档：`docs/reading-dify-02-04-base-nodes-2026-05-16.md`
- Commit: `f1298d5` — docs(02-04): Dify 基础节点 reading note
- 阅读范围：`api/core/workflow/node_factory.py`、`web/app/components/workflow/nodes/`（start/end/if-else/tool/components.ts）

### Task 1: BaseNodeExecutor + tool_registry + Start/End
- Commit: `a191f29`
- 文件：`nodes/base.py` / `nodes/start.py` / `nodes/end.py` / `tool_registry.py` / `nodes/__init__.py`
- 测试：12 个通过

### Task 2: IfElse + Tool（HTTP + Python）
- Commit: `f5bbd9d`
- 文件：`nodes/if_else.py` / `nodes/tool.py` + 3 个测试文件
- 测试：19 个通过（8 IfElse + 6 HTTP + 5 Python）

### Task 3: DSLCompiler 接入真实 executor
- Commit: `2946777`
- 文件：`compiler.py`（修改）/ `test_compiler_with_real_executors.py`
- 测试：6 个端到端集成测试通过

## Dify 参考点

详见：`docs/reading-dify-02-04-base-nodes-2026-05-16.md`

| 参考点 | Dify 路径 | 我们的应用 |
|--------|-----------|-----------|
| 字典式注册表 + 工厂分发 | `api/core/workflow/node_factory.py:379-444` | `NODE_EXECUTORS` + `DSLCompiler._build_node_executor` |
| 前端组件双映射 | `web/app/components/workflow/nodes/components.ts:54-110` | 后端 `NODE_EXECUTORS`，前端同理 |
| IfElse case_id + logical_operator | `web/app/components/workflow/nodes/if-else/types.ts:49-61` | 我们用 Jinja2 expr 字符串（更简单） |
| 惰性注册 + lru_cache | `api/core/workflow/node_factory.py:105-121` | 我们手动 import，规模小不需要自动发现 |
| DifyNodeFactory 工厂模式 | `api/core/workflow/node_factory.py:263-452` | 参考工厂分发思路，简化为 dict 查找 |

## 偏离 / 自动修复

### 自动修复 Issues（Rule 1 - Bug）

**1. [Rule 1 - Bug] 修复 llm_client.py `return ... from exc` 语法错误**
- 发现于：Task 1 执行阶段（测试收集时导入报错）
- 问题：`return LLMAuthError(f"认证失败: {exc}") from exc` — `from exc` 语法仅适用于 `raise`，不适用于 `return`
- 修复：去掉所有 `return ... from exc` 中的 `from exc` 链式，函数 `_map_provider_error` 只是工厂方法，返回异常实例而不是抛出
- 文件：`backend/app/agent_builder/workflow/llm_client.py`

### 设计偏离

**IfElse.resolve_route 使用原始 config**
- 计划原意：`execute(config, state)` 中的 `config` 是 `_render_config` 渲染后的结果
- 发现问题：`conditions[].expr` 是 Jinja2 模板字符串，在 `_render_config` 阶段被提前渲染时，若模板引用了未定义变量会抛 `UndefinedError`，导致测试失败
- 修复：`execute()` 传 `self.config`（原始未渲染）给 `resolve_route()`，延迟求值在 `resolve_route` 中进行
- 影响：`resolve_route` 方法签名仍是 `(config, state)` → 兼容，仅内部语义变化

**集成测试 state_schema 需包含节点 ID 字段**
- 发现：LangGraph TypedDict 状态只保留 schema 中声明的字段，节点输出 `{node_id: result}` 若未在 schema 声明则被丢弃
- 处理：集成测试 DSL 的 state_schema 中显式声明 `start/end/tool_1/branch` 等节点 ID 字段为 `dict` 类型

## 自检结果

```
FOUND: backend/app/agent_builder/workflow/nodes/base.py
FOUND: backend/app/agent_builder/workflow/nodes/start.py
FOUND: backend/app/agent_builder/workflow/nodes/end.py
FOUND: backend/app/agent_builder/workflow/nodes/if_else.py
FOUND: backend/app/agent_builder/workflow/nodes/tool.py
FOUND: backend/app/agent_builder/workflow/nodes/__init__.py
FOUND: backend/app/agent_builder/workflow/tool_registry.py
FOUND: docs/reading-dify-02-04-base-nodes-2026-05-16.md

Commits:
FOUND: f1298d5 (docs)
FOUND: a191f29 (Task 1)
FOUND: f5bbd9d (Task 2)
FOUND: 2946777 (Task 3)

Tests: 37 passed / 0 failed
```

## Self-Check: PASSED
