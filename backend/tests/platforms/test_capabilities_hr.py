"""HRCapability Protocol 单测 — isinstance + dataclass 不可变 + 业务语义。

测试范围：
1. runtime_checkable isinstance 路径（鸭子类型）
2. 6 dataclass frozen=True 不可变性
3. EmployeeFilter 全 Optional 默认值
4. resolve_department_members 接口签名（Phase 5.D dept: 表达式预留）
5. create_leave_request source_of_truth gate（非权威 plugin raise NotImplementedError）
6. list_employees 返回 tuple(list, cursor) shape

直接子模块 import（capabilities/__init__.py 由 Plan 03 独占；本测试用直接子模块路径
不依赖 __init__ re-export 完成时机）。
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Literal

import pytest

from app.agent_builder.platforms.capabilities.hr import (
    Department,
    Employee,
    EmployeeFilter,
    EmployeeRef,
    HRCapability,
    LeaveRequest,
)


# ── Mock plugin: source_of_truth=True（Huly 风格）────────────────────────────────


class _SourceOfTruthHRPlugin:
    """模拟 Huly HR plugin — is_source_of_truth=True，所有方法实现。"""

    name = "huly_hr_mock"
    is_source_of_truth = True

    async def list_employees(
        self,
        *,
        filter: EmployeeFilter | None = None,
        cursor: str | None = None,
    ) -> tuple[list[Employee], str | None]:
        emps = [
            Employee(
                ref=EmployeeRef(plugin_name=self.name, native_id="emp001"),
                username="alice",
                email="alice@example.com",
                display_name="Alice",
                department_id="dept_rd",
                is_active=True,
            ),
        ]
        return (emps, None)

    async def get_employee(self, employee_ref: EmployeeRef) -> Employee | None:
        if employee_ref.native_id == "emp001":
            return Employee(
                ref=employee_ref,
                username="alice",
                email="alice@example.com",
                display_name="Alice",
            )
        return None

    async def list_departments(self) -> list[Department]:
        return [
            Department(
                id="dept_rd",
                name="研发部",
                member_ids=("emp001", "emp002"),
            ),
        ]

    async def resolve_department_members(self, expression: str) -> list[EmployeeRef]:
        if expression == "dept:研发部":
            return [
                EmployeeRef(plugin_name=self.name, native_id="emp001"),
                EmployeeRef(plugin_name=self.name, native_id="emp002"),
            ]
        return []  # fail-quiet 未识别 expression

    async def list_leave_requests(
        self,
        *,
        employee_ref: EmployeeRef | None = None,
        status: Literal["pending", "approved", "rejected"] | None = None,
        cursor: str | None = None,
    ) -> tuple[list[LeaveRequest], str | None]:
        return ([], None)

    async def create_leave_request(
        self,
        *,
        employee_ref: EmployeeRef,
        request_type: Literal["vacation", "sick", "pto", "remote", "overtime"],
        start_date: str,
        end_date: str,
        description: str,
    ) -> LeaveRequest:
        return LeaveRequest(
            id="leave001",
            employee_ref=employee_ref,
            request_type=request_type,
            start_date=start_date,
            end_date=end_date,
            description=description,
            status="pending",
        )


# ── Mock plugin: source_of_truth=False（飞书 IM 兼职 HR 风格）─────────────────────


class _NonSourceOfTruthHRPlugin:
    """模拟 Phase 4 IM provider 兼职 HR — is_source_of_truth=False。

    create_leave_request 必须 raise NotImplementedError（plugin 没有写权限）。
    """

    name = "feishu_legacy_hr_mock"
    is_source_of_truth = False

    async def list_employees(
        self,
        *,
        filter: EmployeeFilter | None = None,
        cursor: str | None = None,
    ) -> tuple[list[Employee], str | None]:
        return ([], None)

    async def get_employee(self, employee_ref: EmployeeRef) -> Employee | None:
        return None

    async def list_departments(self) -> list[Department]:
        return []

    async def resolve_department_members(self, expression: str) -> list[EmployeeRef]:
        return []

    async def list_leave_requests(
        self,
        *,
        employee_ref: EmployeeRef | None = None,
        status: Literal["pending", "approved", "rejected"] | None = None,
        cursor: str | None = None,
    ) -> tuple[list[LeaveRequest], str | None]:
        return ([], None)

    async def create_leave_request(
        self,
        *,
        employee_ref: EmployeeRef,
        request_type: Literal["vacation", "sick", "pto", "remote", "overtime"],
        start_date: str,
        end_date: str,
        description: str,
    ) -> LeaveRequest:
        raise NotImplementedError(
            f"{self.name} is_source_of_truth=False, cannot create_leave_request"
        )


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_hr_capability_isinstance_source_of_truth():
    """runtime_checkable 生效 — Mock 无需继承也 pass isinstance。"""
    plugin = _SourceOfTruthHRPlugin()
    assert isinstance(plugin, HRCapability)


def test_hr_capability_isinstance_non_source_of_truth():
    """非权威 plugin 同样 pass isinstance（鸭子类型不挑权威性）。"""
    plugin = _NonSourceOfTruthHRPlugin()
    assert isinstance(plugin, HRCapability)


def test_employee_frozen():
    """Employee dataclass frozen=True — 不可变。"""
    emp = Employee(
        ref=EmployeeRef(plugin_name="x", native_id="y"),
        username="alice",
        email="alice@e.com",
        display_name="Alice",
    )
    with pytest.raises((AttributeError, Exception)):
        emp.username = "bob"  # type: ignore[misc]


def test_employee_ref_frozen():
    """EmployeeRef dataclass frozen=True。"""
    ref = EmployeeRef(plugin_name="x", native_id="y")
    with pytest.raises((AttributeError, Exception)):
        ref.native_id = "z"  # type: ignore[misc]


def test_department_frozen_with_tuple_member_ids():
    """Department member_ids 用 tuple（不可变）。"""
    dept = Department(id="d1", name="研发部", member_ids=("emp1", "emp2"))
    assert isinstance(dept.member_ids, tuple)
    assert dept.member_ids == ("emp1", "emp2")
    with pytest.raises((AttributeError, Exception)):
        dept.name = "其他"  # type: ignore[misc]


def test_leave_request_literal_types():
    """LeaveRequest request_type / status 用 Literal 类型。"""
    lr = LeaveRequest(
        id="l1",
        employee_ref=EmployeeRef(plugin_name="x", native_id="y"),
        request_type="vacation",
        start_date="2026-05-20",
        end_date="2026-05-22",
        description="出游",
        status="pending",
    )
    assert lr.request_type == "vacation"
    assert lr.status == "pending"


def test_employee_filter_defaults():
    """EmployeeFilter 所有字段 Optional + default — 不传等价全量查询。"""
    f = EmployeeFilter()
    assert f.department_id is None
    assert f.active_only is True  # 默认 True
    assert f.role is None


def test_employee_filter_with_partial_args():
    """EmployeeFilter 部分 args — 只传 department_id。"""
    f = EmployeeFilter(department_id="dept_rd")
    assert f.department_id == "dept_rd"
    assert f.active_only is True  # 仍然默认 True
    assert f.role is None


def test_resolve_department_members_signature():
    """resolve_department_members 返回 list[EmployeeRef] — Phase 5.D dept: 表达式接口预留。"""

    async def go():
        plugin = _SourceOfTruthHRPlugin()
        refs = await plugin.resolve_department_members("dept:研发部")
        assert isinstance(refs, list)
        assert all(isinstance(r, EmployeeRef) for r in refs)
        assert len(refs) == 2
        assert refs[0].plugin_name == "huly_hr_mock"
        # 未识别 expression → 空 list（fail-quiet）
        empty = await plugin.resolve_department_members("unknown:xxx")
        assert empty == []

    asyncio.run(go())


def test_create_leave_request_source_of_truth_gate():
    """非 source_of_truth plugin 调 create_leave_request → raise NotImplementedError。"""

    async def go():
        non_sot = _NonSourceOfTruthHRPlugin()
        with pytest.raises(NotImplementedError) as exc_info:
            await non_sot.create_leave_request(
                employee_ref=EmployeeRef(plugin_name="x", native_id="y"),
                request_type="vacation",
                start_date="2026-05-20",
                end_date="2026-05-22",
                description="test",
            )
        assert "is_source_of_truth=False" in str(exc_info.value)

    asyncio.run(go())


def test_create_leave_request_source_of_truth_ok():
    """source_of_truth=True plugin 正常 create_leave_request。"""

    async def go():
        sot = _SourceOfTruthHRPlugin()
        lr = await sot.create_leave_request(
            employee_ref=EmployeeRef(plugin_name="huly_hr_mock", native_id="emp001"),
            request_type="vacation",
            start_date="2026-05-20",
            end_date="2026-05-22",
            description="出游",
        )
        assert lr.id == "leave001"
        assert lr.status == "pending"
        assert lr.request_type == "vacation"

    asyncio.run(go())


def test_list_employees_returns_tuple_with_cursor():
    """list_employees 返回 tuple(list[Employee], cursor) shape — 分页接口契约。"""

    async def go():
        plugin = _SourceOfTruthHRPlugin()
        result = await plugin.list_employees()
        assert isinstance(result, tuple)
        assert len(result) == 2
        employees, cursor = result
        assert isinstance(employees, list)
        assert all(isinstance(e, Employee) for e in employees)
        assert cursor is None  # 单页返回完毕

    asyncio.run(go())


def test_list_leave_requests_returns_tuple_with_cursor():
    """list_leave_requests 同样返回 tuple(list, cursor)。"""

    async def go():
        plugin = _SourceOfTruthHRPlugin()
        result = await plugin.list_leave_requests()
        assert isinstance(result, tuple)
        leaves, cursor = result
        assert isinstance(leaves, list)
        assert cursor is None

    asyncio.run(go())
