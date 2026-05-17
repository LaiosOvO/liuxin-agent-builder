"""HRCapability — 人事能力（员工 / 部门 / 假期）。

设计要点（ADR-001 §3.3 + Huly acid test §4.2 草案）：

- **resolve_department_members(expression)**: Phase 5.D `dept:研发部` 表达式解析的核心接口
  — IM-05 节点 assignee 字段写 `dept:研发部` 时，HitlService 通过此 method 解析为
  `list[EmployeeRef]`，再展开为多人审批 token。
- **create_leave_request**: 仅 `source_of_truth=True` 的 plugin 实现（Huly is_source_of_truth=True
  时写真实数据库；Phase 4 IM provider source_of_truth=False 时 NotImplementedError）。
- **subscribe_changes**（留 Phase 5.D 接入）: 用于 sync_from 模式 — Huly 主动推变更到我们
  的本地缓存。

Reference (Dify reading doc `docs/reading-dify-05a-03-hr-identity-trigger-tool-2026-05-17.md`)：
- Dify 无 HR 抽象（Dify 是 AI agent 平台，无企业 HR 概念）— 本 capability **完全新疆域**，参考
  Huly platform spike `docs/plans/2026-05-17-huly-spike-abstraction-acid-test.md` §4 设计
- 仅借鉴 Dify capability 三层分层模式（Declaration / Provider Entity / Invocation Manager）
- License: Dify AGPL-3.0 vs 本项目 Apache-2.0 — 严格不拷源代码，仅借鉴设计模式

CLAUDE.md immutability：所有 dataclass `frozen=True`，list / dict / tuple 走 default_factory。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable


# ── 值对象（Value Objects）─────────────────────────────────────────────────────


@dataclass(frozen=True)
class EmployeeRef:
    """Provider-agnostic 员工引用 — 跨 plugin 唯一标识（plugin_name 前缀）。

    Phase 5.D IM-05 节点 assignee 字段最终展开为 `list[EmployeeRef]`，每条 ref 唯一映射
    到一个 HITL token + 一个 IM message。
    """

    plugin_name: str  # "huly" | "legacy:feishu" | ...
    native_id: str  # plugin 内部员工 ID（Huly account id / 飞书 user_id）


@dataclass(frozen=True)
class Employee:
    """员工实体（plugin 返回）。

    custom_fields 装 plugin-specific 字段（如 Huly chunter status / Lark department_path
    等），主进程不解析 — 用于 Phase 5.D 起 UI 渲染 + 表达式扩展。
    """

    ref: EmployeeRef
    username: str  # canonical 用户名（Huly handle / 飞书 user_id）
    email: str
    display_name: str
    department_id: str | None = None
    manager_id: str | None = None
    is_active: bool = True
    custom_fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Department:
    """部门实体。

    `member_ids` 用 tuple（不可变）— Phase 5.D `dept:研发部` 表达式解析直接读取此字段
    展开成员列表（无需 N+1 查询）。
    """

    id: str
    name: str
    parent_id: str | None = None
    team_lead_employee_id: str | None = None
    member_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class LeaveRequest:
    """请假申请。

    request_type 用 Literal — 防 typo + 类型检查 IDE 自动补全。
    """

    id: str
    employee_ref: EmployeeRef
    request_type: Literal["vacation", "sick", "pto", "remote", "overtime"]
    start_date: str  # ISO date YYYY-MM-DD
    end_date: str  # ISO date YYYY-MM-DD
    description: str
    status: Literal["pending", "approved", "rejected"]


@dataclass(frozen=True)
class EmployeeFilter:
    """list_employees 查询过滤参数。

    全 Optional + default — 不传任何参数等价于全量查询。Phase 5.D HR 节点配置 UI 渲染
    为 React form 可直接对应此 schema（fields 自动生成）。
    """

    department_id: str | None = None
    active_only: bool = True
    role: str | None = None  # "manager" | "ic" | ...（plugin 自定义）


# ── Capability Protocol ────────────────────────────────────────────────────────


@runtime_checkable
class HRCapability(Protocol):
    """人事能力（员工 / 部门 / 假期）。

    Phase 5.A 仅定义 Protocol；具体 plugin 实现在 Phase 5.D（Huly / Lark / 飞书 HR）。
    每方法 docstring 标注 Phase 5.D 对应 plugin 实现路径。

    runtime_checkable 让 `isinstance(plugin, HRCapability)` 走鸭子类型校验（不需继承）。
    """

    name: str  # plugin 名 — Registry 路由用

    async def list_employees(
        self,
        *,
        filter: EmployeeFilter | None = None,
        cursor: str | None = None,
    ) -> tuple[list[Employee], str | None]:
        """分页查询员工 — 返回 (employees, next_cursor)；cursor=None 表示无更多。

        cursor 是 plugin-specific opaque string（Huly 用 timestamp + id；Lark 用 page_token）。
        Phase 5.D 每 plugin 自行实现 cursor 编解码。
        """
        ...

    async def get_employee(self, employee_ref: EmployeeRef) -> Employee | None:
        """按 ref 查单个员工 — 不存在返回 None（fail-quiet）。"""
        ...

    async def list_departments(self) -> list[Department]:
        """全量查部门树 — 一般缓存在主进程（部门数量 << 员工数量）。"""
        ...

    async def resolve_department_members(
        self, expression: str
    ) -> list[EmployeeRef]:
        """解析 `dept:研发部` / `role:manager` / `id:abc` 等表达式 → employee_refs。

        Phase 5.D IM-05 节点 assignee 解析的核心接口。表达式语法（Phase 5.D 落地）：
        - `dept:<部门名>` → 该部门全员（递归子部门由 plugin 决定）
        - `role:<角色名>` → 该 role 全员
        - `id:<employee_id>` → 单人
        - `user:<email>` → 按邮箱查
        - `manager_of:<employee_id>` → 该员工的直属上级
        - 多个用 `,` 分隔（如 `dept:研发部,role:manager`）

        plugin 不识别的表达式 → 返回空 list（不 raise — fail-quiet）。
        """
        ...

    async def list_leave_requests(
        self,
        *,
        employee_ref: EmployeeRef | None = None,
        status: Literal["pending", "approved", "rejected"] | None = None,
        cursor: str | None = None,
    ) -> tuple[list[LeaveRequest], str | None]:
        """分页查请假申请。

        - employee_ref=None: 全公司
        - status=None: 全部状态

        Phase 5.D HR 离职预置模板用此 method 扫描 pending leave。
        """
        ...

    async def create_leave_request(
        self,
        *,
        employee_ref: EmployeeRef,
        request_type: Literal["vacation", "sick", "pto", "remote", "overtime"],
        start_date: str,
        end_date: str,
        description: str,
    ) -> LeaveRequest:
        """提交请假申请 — 仅 source_of_truth=True 的 plugin 实现。

        - Huly HR plugin（is_source_of_truth=True）→ 写 Huly DB 真实数据
        - Phase 4 IM provider（is_source_of_truth=False）→ raise NotImplementedError

        plugin 实现时第一行必检查：
            if not self.is_source_of_truth:
                raise NotImplementedError(...)
        """
        ...
