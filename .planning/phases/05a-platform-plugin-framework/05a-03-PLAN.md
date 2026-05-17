---
phase: 05a-platform-plugin-framework
plan: 03
type: execute
wave: 2
depends_on: ["01"]
files_modified:
  - docs/reading-dify-05a-03-hr-identity-trigger-tool-2026-05-17.md
  - backend/app/agent_builder/platforms/capabilities/hr.py
  - backend/app/agent_builder/platforms/capabilities/identity.py
  - backend/app/agent_builder/platforms/capabilities/trigger.py
  - backend/app/agent_builder/platforms/capabilities/tool.py
  - backend/app/agent_builder/platforms/capabilities/__init__.py
  - tests/platforms/test_capabilities_hr.py
  - tests/platforms/test_capabilities_identity.py
  - tests/platforms/test_capabilities_trigger_tool.py
autonomous: true
requirements:
  - PLUG-FW-01
must_haves:
  truths:
    - "HRCapability resolve_department_members(expression) 方法签名定义（Phase 5.D dept: 表达式接口已就位）"
    - "IdentityCapability is_source_of_truth flag 区分 Huly（True）vs Phase 4 IM provider（False）"
    - "TriggerCapability + ToolCapability v1.1 骨架（仅 Protocol + 最小 method），实现留 Phase 5.D+"
  artifacts:
    - path: "backend/app/agent_builder/platforms/capabilities/hr.py"
      provides: "HRCapability + Employee/Department/LeaveRequest/EmployeeRef + resolve_department_members"
      exports: ["HRCapability", "Employee", "Department", "LeaveRequest", "EmployeeRef", "EmployeeFilter"]
      min_lines: 100
    - path: "backend/app/agent_builder/platforms/capabilities/identity.py"
      provides: "IdentityCapability + UserPrincipal/UserChangeEvent + is_source_of_truth flag"
      exports: ["IdentityCapability", "UserPrincipal", "UserChangeEvent"]
      min_lines: 60
    - path: "backend/app/agent_builder/platforms/capabilities/trigger.py"
      provides: "TriggerCapability v1.1 骨架（subscribe / verify_event）"
      exports: ["TriggerCapability", "TriggerEvent"]
      min_lines: 40
    - path: "backend/app/agent_builder/platforms/capabilities/tool.py"
      provides: "ToolCapability v1.1 骨架（list_tools / invoke_tool）"
      exports: ["ToolCapability", "ToolSpec", "ToolInvocationResult"]
      min_lines: 40
  key_links:
    - from: "backend/app/agent_builder/platforms/capabilities/hr.py"
      to: "Phase 5.D dept: 表达式 (CONTEXT.md DoD #6)"
      via: "resolve_department_members(expression) 接口暴露给 IM-05 节点 assignee 解析"
      pattern: "resolve_department_members"
    - from: "backend/app/agent_builder/platforms/capabilities/identity.py"
      to: "Huly acid test §6 身份反向 sync"
      via: "is_source_of_truth flag + watch_user_changes stream"
      pattern: "is_source_of_truth"
---

<objective>
实现剩余 4 个 Capability Protocol：HR / Identity（完整设计，含 Huly acid test §6 反向 sync 需要的方法）+ Trigger / Tool（v1.1 骨架，实现留 Phase 5.D+）。

Purpose: 与 plan 02 并行，无文件冲突（plan 02 改 im.py/doc.py + capabilities/__init__.py 共享，本 plan 改 hr/identity/trigger/tool.py + capabilities/__init__.py — 需在 capability 同 file 谨慎并行；安排该文件最后追加）。
Output: 4 capability files + 3 测试文件 + 共享 __init__.py 追加。
</objective>

<execution_context>
@/Users/admin/.claude/get-shit-done/workflows/execute-plan.md
@/Users/admin/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/05a-platform-plugin-framework/05a-CONTEXT.md
@.planning/phases/05a-platform-plugin-framework/05a-RESEARCH.md
@docs/plans/2026-05-17-platform-plugin-framework-ADR.md
@docs/plans/2026-05-17-huly-spike-abstraction-acid-test.md

<interfaces>
From docs/plans/2026-05-17-huly-spike-abstraction-acid-test.md §4.2:
HRProvider 草案 — list_employees / get_employee / list_departments / resolve_department_members /
create_leave_request / list_leave_requests / subscribe_changes — 8+ method

From ADR-001 §3.4 IdentityCapability:
- is_source_of_truth: bool
- list_users() / resolve_user(identifier) / watch_user_changes() AsyncIterator
</interfaces>

<parallel_coordination>
**与 plan 02 文件冲突告警**：双 plan 都修改 `backend/app/agent_builder/platforms/capabilities/__init__.py`（追加 export）。
执行策略：
- plan 02 写 `__init__.py` 含 IM + Doc exports
- plan 03 **后 wave 2 完成时** 用 Edit tool **追加** HR/Identity/Trigger/Tool exports（不是覆盖）
- 若两个 plan 真同时跑：第二个收到 file conflict 时重新 Edit 即可（追加语义安全）
- 验证 final `__init__.py` 必含全 8 类 exports
</parallel_coordination>
</context>

<tasks>

<task type="auto">
  <name>Task 0: Dify HR/Identity/Trigger/Tool 阅读文档（CLAUDE.md §2.7 硬性 gate）</name>
  <files>docs/reading-dify-05a-03-hr-identity-trigger-tool-2026-05-17.md</files>
  <action>
**STOP — gate**。

读 Dify 源文件：
1. `/Users/admin/ai/ref/dify/repo/api/core/plugin/entities/plugin_daemon.py` 重点 PluginTriggerProviderEntity / PluginAgentProviderEntity / PluginToolProviderEntity
2. `/Users/admin/ai/ref/dify/repo/api/core/tools/plugin_tool/` 顶层目录或 `__init__.py` — tool 怎么定义 invocation schema
3. `/Users/admin/ai/ref/dify/repo/api/core/plugin/entities/endpoint.py` 重点 webhook event 模式

写到 `docs/reading-dify-05a-03-hr-identity-trigger-tool-2026-05-17.md`，5 节模板（项目概述 / 技术栈 / 架构要点 / 可借鉴的设计模式 / 与本项目关系）。

**关键问题答**：
- Dify 有没有 HR / Identity 概念？（答案：没有；HR 是本项目 acid test 新增，Identity 是反向 sync 新需求）
- Dify Trigger 怎么 dispatch event？（webhook subscriber + endpoint receive）
- Dify Tool 怎么声明 invocation schema？（JSON Schema-based parameters）

**5 借鉴点**：
1. PluginTriggerProviderEntity 怎么声明 event 类型 → 5.A TriggerCapability.subscribe_events
2. PluginToolProviderEntity 怎么声明 tool list → 5.A ToolCapability.list_tools
3. Tool invocation parameters JSON Schema-based → 5.A ToolSpec.input_schema 直接复用 JSON Schema dict
4. Endpoint method enum (POST/GET) → 5.A TriggerCapability 信号触发 模式（暂不实现）
5. Dify 没 HR / Identity 抽象 → 5.A 是新疆域，对应 Huly acid test §4 + §6 报告

License attribution（Dify AGPL-3.0 vs 本项目 Apache-2.0）；**不拷源代码**。≥ 60 行。
  </action>
  <verify>
    <automated>test -f docs/reading-dify-05a-03-hr-identity-trigger-tool-2026-05-17.md && wc -l docs/reading-dify-05a-03-hr-identity-trigger-tool-2026-05-17.md | awk '{exit ($1 >= 60 ? 0 : 1)}' && grep -q "AGPL\|attribution" docs/reading-dify-05a-03-hr-identity-trigger-tool-2026-05-17.md</automated>
  </verify>
  <done>Reading doc ≥ 60 行 + 5 借鉴点 + License attribution + commit 在前</done>
</task>

<task type="auto">
  <name>Task 1: HRCapability + IdentityCapability 完整实现 + 单测</name>
  <files>backend/app/agent_builder/platforms/capabilities/hr.py,backend/app/agent_builder/platforms/capabilities/identity.py,tests/platforms/test_capabilities_hr.py,tests/platforms/test_capabilities_identity.py</files>
  <action>
1. **`backend/app/agent_builder/platforms/capabilities/hr.py`** 按 ADR-001 §3.3 + Huly acid test §4.2 草案：

```python
"""HRCapability — 人事能力（员工 / 部门 / 假期）。

设计要点（ADR-001 §3.3 + Huly acid test §4）：
- Phase 5.D dept: 表达式解析 → resolve_department_members 核心
- create_leave_request 仅 source_of_truth=True 的 plugin 实现；否则 NotImplementedError
- subscribe_changes 用于 sync_from 模式（Huly 主动推变更到我们）
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True)
class EmployeeRef:
    plugin_name: str
    native_id: str


@dataclass(frozen=True)
class Employee:
    ref: EmployeeRef
    username: str
    email: str
    display_name: str
    department_id: str | None = None
    manager_id: str | None = None
    is_active: bool = True
    custom_fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Department:
    id: str
    name: str
    parent_id: str | None = None
    team_lead_employee_id: str | None = None
    member_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class LeaveRequest:
    id: str
    employee_ref: EmployeeRef
    request_type: Literal["vacation", "sick", "pto", "remote", "overtime"]
    start_date: str
    end_date: str
    description: str
    status: Literal["pending", "approved", "rejected"]


@dataclass(frozen=True)
class EmployeeFilter:
    department_id: str | None = None
    active_only: bool = True
    role: str | None = None


@runtime_checkable
class HRCapability(Protocol):
    """人事能力（员工 / 部门 / 假期）。"""

    name: str

    async def list_employees(
        self,
        *,
        filter: EmployeeFilter | None = None,
        cursor: str | None = None,
    ) -> tuple[list[Employee], str | None]:
        """返回 (employees, next_cursor)；cursor None 表示无更多。"""
        ...

    async def get_employee(self, employee_ref: EmployeeRef) -> Employee | None: ...

    async def list_departments(self) -> list[Department]: ...

    async def resolve_department_members(
        self, expression: str
    ) -> list[EmployeeRef]:
        """解析 `dept:研发部` / `role:manager` / `id:abc` 等表达式 → employee_refs。

        Phase 5.D IM-05 节点 assignee 解析的核心接口。
        """
        ...

    async def list_leave_requests(
        self,
        *,
        employee_ref: EmployeeRef | None = None,
        status: Literal["pending", "approved", "rejected"] | None = None,
        cursor: str | None = None,
    ) -> tuple[list[LeaveRequest], str | None]: ...

    async def create_leave_request(
        self,
        *,
        employee_ref: EmployeeRef,
        request_type: Literal["vacation", "sick", "pto", "remote", "overtime"],
        start_date: str,
        end_date: str,
        description: str,
    ) -> LeaveRequest:
        """仅 source_of_truth=True 的 plugin 实现；否则 raise NotImplementedError。"""
        ...
```

≥ 100 行。

2. **`backend/app/agent_builder/platforms/capabilities/identity.py`** 按 ADR-001 §3.4：

```python
"""IdentityCapability — 身份源能力（Huly acid test §6 反向 sync）。"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True)
class UserPrincipal:
    plugin_name: str
    native_id: str
    canonical_username: str
    email: str
    display_name: str
    is_active: bool = True
    extras: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class UserChangeEvent:
    kind: Literal["created", "updated", "deleted", "renamed"]
    principal: UserPrincipal
    previous_principal: UserPrincipal | None = None


@runtime_checkable
class IdentityCapability(Protocol):
    """身份源能力 — 决定 sync 方向。"""

    name: str
    is_source_of_truth: bool

    async def list_users(self) -> list[UserPrincipal]: ...

    async def resolve_user(self, identifier: str) -> UserPrincipal | None:
        """按 email / canonical_username / native_id 查 — plugin 自己理解 identifier 语义。"""
        ...

    async def watch_user_changes(self) -> AsyncIterator[UserChangeEvent]:
        """仅 source_of_truth=True 的 plugin 实现 — 长连接 / WS 推送。

        source_of_truth=False 时 raise NotImplementedError。
        """
        ...
```

≥ 60 行。

3. **`tests/platforms/test_capabilities_hr.py`** ≥ 6 测试，覆盖：
   - `test_hr_capability_isinstance`：MinimalHR pass isinstance
   - `test_employee_frozen`：dataclass 不可变
   - `test_employee_filter_defaults`：所有字段 Optional + default
   - `test_resolve_department_members_signature`：mock plugin 返回 list[EmployeeRef]
   - `test_create_leave_request_source_of_truth_gate`：non-SoT plugin raise NotImplementedError
   - `test_list_employees_returns_tuple_with_cursor`：tuple(list, cursor) shape

4. **`tests/platforms/test_capabilities_identity.py`** ≥ 5 测试，覆盖：
   - `test_identity_capability_isinstance`：双 plugin（is_source_of_truth True/False）
   - `test_user_principal_frozen`
   - `test_user_change_event_kinds`：Literal 枚举边界
   - `test_watch_only_when_source_of_truth`：False plugin 调 raise
   - `test_watch_user_changes_is_async_generator`（High 5 静态断言）：用 `inspect.isasyncgenfunction(SoTMockIdentity.watch_user_changes)` 验证 watch_user_changes 是 async generator function — 防 `if False: yield {}` 模式被误写成普通 async function
     ```python
     import inspect
     assert inspect.isasyncgenfunction(SoTMockIdentity.watch_user_changes), (
         "watch_user_changes 必须是 async generator function（含 yield）"
     )
     ```

代码风格 black + ruff。
  </action>
  <verify>
    <automated>cd backend && python -c "from app.agent_builder.platforms.capabilities.hr import HRCapability, Employee, Department, EmployeeRef, EmployeeFilter, LeaveRequest; from app.agent_builder.platforms.capabilities.identity import IdentityCapability, UserPrincipal, UserChangeEvent; print('OK')" && pytest tests/platforms/test_capabilities_hr.py tests/platforms/test_capabilities_identity.py -v -x 2>&1 | tail -20 && wc -l backend/app/agent_builder/platforms/capabilities/hr.py | awk '{exit ($1 >= 100 ? 0 : 1)}' && wc -l backend/app/agent_builder/platforms/capabilities/identity.py | awk '{exit ($1 >= 60 ? 0 : 1)}'</automated>
  </verify>
  <done>HRCapability + IdentityCapability 可 import；10+ 单测 pass；hr.py ≥ 100 行 + identity.py ≥ 60 行</done>
</task>

<task type="auto">
  <name>Task 2: TriggerCapability + ToolCapability v1.1 骨架 + 测试 + __init__.py 追加</name>
  <files>backend/app/agent_builder/platforms/capabilities/trigger.py,backend/app/agent_builder/platforms/capabilities/tool.py,backend/app/agent_builder/platforms/capabilities/__init__.py,tests/platforms/test_capabilities_trigger_tool.py</files>
  <action>
1. **`backend/app/agent_builder/platforms/capabilities/trigger.py`** v1.1 骨架（实现留 Phase 5.D+）：

```python
"""TriggerCapability — 平台 push event 触发 workflow（v1.1 骨架）。

Phase 5.A 仅定 Protocol；真实接入留 Phase 5.D+。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class TriggerEvent:
    event_type: str          # plugin-defined: "message.new" / "doc.updated" / ...
    payload: dict[str, Any]
    occurred_at: str         # ISO timestamp
    source_extras: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class TriggerCapability(Protocol):
    """事件订阅能力 — plugin 主动推 event 到主进程。"""

    name: str

    async def subscribe_events(
        self,
        event_types: list[str],
    ) -> AsyncIterator[TriggerEvent]: ...

    async def verify_event_signature(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> bool:
        """webhook / WS 模式下校验事件来源真实性。"""
        ...
```

≥ 40 行。

2. **`backend/app/agent_builder/platforms/capabilities/tool.py`** v1.1 骨架：

```python
"""ToolCapability — plugin 提供 RPC tools 给 LLM 节点调用（v1.1 骨架）。

Phase 5.A 仅定 Protocol；真实接入留 Phase 5.D+。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]   # JSON Schema for parameters
    output_schema: dict[str, Any] | None = None
    extras: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolInvocationResult:
    tool_name: str
    success: bool
    result: dict[str, Any] | None = None
    error_message: str | None = None


@runtime_checkable
class ToolCapability(Protocol):
    """LLM Tool 能力 — 让 LLM 节点能调 plugin 暴露的 RPC tools。"""

    name: str

    async def list_tools(self) -> list[ToolSpec]: ...

    async def invoke_tool(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolInvocationResult: ...
```

≥ 40 行。

3. **`backend/app/agent_builder/platforms/capabilities/__init__.py`** — 关键：**用 Edit tool 追加**（不是 Write 覆盖），保留 plan 02 写入的 IM + Doc exports，加上 HR/Identity/Trigger/Tool 全 8 capability：

```python
"""Capability Protocols — 每个 capability 一个 file。"""
from .doc import CommentRef, CRDTDelta, DocCapability, DocInfo, DocRef, UserRef  # noqa: F401
from .hr import (  # noqa: F401
    Department,
    Employee,
    EmployeeFilter,
    EmployeeRef,
    HRCapability,
    LeaveRequest,
)
from .identity import IdentityCapability, UserChangeEvent, UserPrincipal  # noqa: F401
from .im import IMCapability, MessageRef, NormalizedCard, RecipientSpec  # noqa: F401
from .tool import ToolCapability, ToolInvocationResult, ToolSpec  # noqa: F401
from .trigger import TriggerCapability, TriggerEvent  # noqa: F401

__all__ = [
    # IM
    "IMCapability", "MessageRef", "NormalizedCard", "RecipientSpec",
    # Doc
    "DocCapability", "DocInfo", "DocRef", "CRDTDelta", "CommentRef", "UserRef",
    # HR
    "HRCapability", "Employee", "Department", "EmployeeRef", "EmployeeFilter", "LeaveRequest",
    # Identity
    "IdentityCapability", "UserPrincipal", "UserChangeEvent",
    # Trigger (v1.1 skeleton)
    "TriggerCapability", "TriggerEvent",
    # Tool (v1.1 skeleton)
    "ToolCapability", "ToolSpec", "ToolInvocationResult",
]
```

**重要**：若 plan 02 已写过 `__init__.py` 仅含 IM exports，本 plan 必须**重写**它（不是 append — 因为 __all__ 也要重写）。两 plan 顺序执行（plan 02 先 → plan 03 重写）。

4. **`tests/platforms/test_capabilities_trigger_tool.py`** ≥ 5 测试：
   - `test_trigger_capability_isinstance`
   - `test_tool_capability_isinstance`
   - `test_trigger_event_frozen`
   - `test_tool_spec_carries_json_schema`：input_schema 是 dict（不强类型化）
   - `test_subscribe_events_is_async_generator`（High 5 静态断言）：用 `inspect.isasyncgenfunction(MockTrigger.subscribe_events)` 验证 subscribe_events 是 async generator function
     ```python
     import inspect
     assert inspect.isasyncgenfunction(MockTrigger.subscribe_events), (
         "TriggerCapability.subscribe_events 必须是 async generator function"
     )
     ```
  </action>
  <verify>
    <automated>cd backend && python -c "from app.agent_builder.platforms.capabilities import IMCapability, DocCapability, HRCapability, IdentityCapability, TriggerCapability, ToolCapability, TriggerEvent, ToolSpec, ToolInvocationResult; print('all 6 caps importable')" && pytest tests/platforms/test_capabilities_trigger_tool.py -v -x 2>&1 | tail -10 && wc -l backend/app/agent_builder/platforms/capabilities/trigger.py | awk '{exit ($1 >= 40 ? 0 : 1)}' && wc -l backend/app/agent_builder/platforms/capabilities/tool.py | awk '{exit ($1 >= 40 ? 0 : 1)}' && pytest tests/platforms/test_capabilities_im.py tests/platforms/test_capabilities_doc.py tests/platforms/test_capabilities_hr.py tests/platforms/test_capabilities_identity.py tests/platforms/test_capabilities_trigger_tool.py --cov=app/agent_builder/platforms/capabilities --cov-fail-under=80 2>&1 | tail -15</automated>
  </verify>
  <done>6 Capability Protocols 全部 importable from `platforms.capabilities`；5 单测 pass；trigger.py + tool.py 各 ≥ 40 行；**pytest --cov 强制 capabilities/ 覆盖率 ≥ 80%（High 3）**</done>
</task>

</tasks>

<verification>
- [ ] Reading doc commit 在前
- [ ] `pytest tests/platforms/test_capabilities_hr.py tests/platforms/test_capabilities_identity.py tests/platforms/test_capabilities_trigger_tool.py -v` 14+ tests pass
- [ ] `python -c "from app.agent_builder.platforms.capabilities import HRCapability, IdentityCapability, TriggerCapability, ToolCapability"` 无错
- [ ] `__init__.py` __all__ 含 22 export
- [ ] black + ruff 通过
- [ ] Phase 4 81 IM 测试 0 regression
</verification>

<success_criteria>
- 6 Capability Protocol 文件全部存在 + **pytest --cov=app/agent_builder/platforms/capabilities --cov-fail-under=80 强制自动验证（High 3）**
- HRCapability.resolve_department_members 接口为 Phase 5.D dept: 表达式预留
- IdentityCapability.is_source_of_truth 解决 Huly acid test §6 反向 sync 设计问题
- TriggerCapability / ToolCapability 仅骨架（实现留 Phase 5.D+）
- `inspect.isasyncgenfunction` 静态断言覆盖 identity.watch_user_changes / trigger.subscribe_events（High 5 防 `if False: yield {}` 模式被误写）
</success_criteria>

<output>
完成后创建 `.planning/phases/05a-platform-plugin-framework/05a-03-SUMMARY.md`，含：
- Reading doc 链接 + commit hash
- 单测输出（14+ pass）
- **Dify 参考点** 小节：reading doc 中 5 借鉴点指回
- Huly acid test gap → 5.A 解决映射：gap #3 (HRProvider 不存在) / gap #5 (身份反向 sync)
</output>
