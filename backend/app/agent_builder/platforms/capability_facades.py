"""Capability facades — daemon.invoke(capability, method, **kwargs) 真转发实现（Plan 05）。

设计要点（ADR-001 §5 + RESEARCH.md §Pattern 4 + reading doc 借鉴点 #1）:

- 4 facade（IMFacade / DocFacade / HRFacade / IdentityFacade）共享 `_BaseFacade` 父类
- 每 facade 持 `_daemon: PlatformDaemonClient | None`（Plan 06 HulyPlugin 通过 attach_daemon 注入）
- 每 facade 持 `_manifest: PlatformManifest`（读 capability spec 配置）
- 方法签名 100% 对齐 capabilities/{im,doc,hr,identity}.py Protocol 定义（duck typing 兼容）
- daemon 为 None 时所有 method raise PluginError("daemon not attached") — fail-fast
- 参数序列化：dataclass → asdict() 后传 JSONRPC params；返回值按预期类型重建

**Plan 04 → Plan 05 演进**:
- Plan 04: 所有方法 raise NotImplementedError（stub）
- Plan 05（本 plan）: 所有方法转发 ``await self._daemon.invoke("im", "send_card", **kwargs)``
- 接口签名 + 文件位置 0 改动 → Plan 04 调用方代码 0 破坏

**关键序列化考虑**：
- dataclass 值对象（RecipientSpec / NormalizedCard / DocRef 等）通过 ``dataclasses.asdict`` 转 dict
- ``CRDTDelta.payload: bytes`` 走 base64 编码（JSONRPC 不支持 bytes 直传）
- list[dataclass] 必须 ``[asdict(x) for x in xs]`` 而非 asdict() 直接（asdict 递归 dataclass 但不递归 list 内）
- 返回值 daemon 给的 dict → facade 重建 dataclass（plugin_name 从 self.name 默认；daemon 也可显式返回）

异步生成器方法（subscribe_events / watch_user_changes）保持 NotImplementedError + ``if False: yield {}`` 模式：
- 这些方法需要 daemon 双向 stream，留 Phase 5.C/5.D 落地（CONTEXT.md 决策）
- ``if False: yield {}`` 让 Python 静态分析识别为 async generator function（保 Plan 02/03 静态断言）

Reference: docs/reading-dify-05a-05-daemon-client-2026-05-17.md
- 借鉴点 #1: PluginDaemonBasicResponse[T] envelope.result 思路（v1 dict 透传）
- 借鉴点 #2: error code/message 双字段（daemon raise PluginInvocationError 由调用方 catch）
- 借鉴点 #3: stdio JSONRPC vs HTTP

License: 100% 独立创作，仅借鉴 Dify AGPL-3.0 设计模式。
"""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Literal

from .capabilities import (
    CommentRef,
    CRDTDelta,
    Department,
    DocInfo,
    DocRef,
    Employee,
    EmployeeFilter,
    EmployeeRef,
    LeaveRequest,
    MessageRef,
    NormalizedCard,
    RecipientSpec,
    UserPrincipal,
    UserRef,
)
from .exceptions import PluginError

if TYPE_CHECKING:
    from .daemon_client import PlatformDaemonClient
    from .manifest import PlatformManifest


# ── _BaseFacade ────────────────────────────────────────────────────────────────


class _BaseFacade:
    """4 capability facade 共享 base 类 — 持 daemon + manifest 引用。

    daemon 为 None 时所有 method raise PluginError（fail-fast）。
    通过 _ensure_daemon() 在每个方法入口校验。
    """

    def __init__(
        self,
        daemon: PlatformDaemonClient | None,
        manifest: PlatformManifest,
    ) -> None:
        self._daemon = daemon
        self._manifest = manifest

    @property
    def name(self) -> str:
        """Plugin 名（从 manifest 读 — 用于 MessageRef.plugin_name 等）。"""
        return self._manifest.name

    def _ensure_daemon(self) -> PlatformDaemonClient:
        """daemon 注入校验 — None 时 raise（fail-fast 防 silent 失败）。"""
        if self._daemon is None:
            raise PluginError(
                f"plugin '{self._manifest.name}' daemon not attached "
                "(call PlatformPlugin.attach_daemon first)"
            )
        return self._daemon


# ── IMFacade ───────────────────────────────────────────────────────────────────


class IMFacade(_BaseFacade):
    """IM capability facade — 实现 capabilities.im.IMCapability Protocol（Plan 02）。

    转发 ``await self._daemon.invoke("im", method, **kwargs)``，
    序列化 dataclass 参数 + 反序列化 result dict 为强类型 dataclass 返回值。
    """

    @property
    def supports_native_buttons(self) -> bool:
        """从 manifest.im 读 cap flag；未声明默认 False。"""
        if (
            self._manifest.im is None
            or self._manifest.im.supports_native_buttons is None
        ):
            return False
        return self._manifest.im.supports_native_buttons

    @property
    def supports_card_update(self) -> bool:
        if self._manifest.im is None or self._manifest.im.supports_card_update is None:
            return False
        return self._manifest.im.supports_card_update

    @property
    def supports_threads(self) -> bool:
        if self._manifest.im is None or self._manifest.im.supports_threads is None:
            return False
        return self._manifest.im.supports_threads

    async def send_card(
        self,
        *,
        recipient: RecipientSpec,
        card: NormalizedCard,
        idempotency_key: str,
    ) -> MessageRef:
        """转发到 daemon im.send_card；返回值 dict 重建为 MessageRef。"""
        daemon = self._ensure_daemon()
        result = await daemon.invoke(
            "im",
            "send_card",
            recipient=asdict(recipient),
            card=asdict(card),
            idempotency_key=idempotency_key,
        )
        return MessageRef(
            plugin_name=result.get("plugin_name", self.name),
            native_id=result["native_id"],
            extras=result.get("extras", {}),
        )

    async def update_card(self, msg_ref: MessageRef, card: NormalizedCard) -> None:
        """转发到 daemon im.update_card；无返回值（None）。"""
        daemon = self._ensure_daemon()
        await daemon.invoke(
            "im",
            "update_card",
            msg_ref=asdict(msg_ref),
            card=asdict(card),
        )

    async def send_text(self, recipient: RecipientSpec, text: str) -> MessageRef:
        """转发到 daemon im.send_text；返回值 dict 重建为 MessageRef。"""
        daemon = self._ensure_daemon()
        result = await daemon.invoke(
            "im",
            "send_text",
            recipient=asdict(recipient),
            text=text,
        )
        return MessageRef(
            plugin_name=result.get("plugin_name", self.name),
            native_id=result["native_id"],
            extras=result.get("extras", {}),
        )

    async def subscribe_events(
        self, event_types: list[str]
    ) -> AsyncIterator[dict[str, Any]]:
        """订阅 IM 入站事件 — Phase 5.C/5.D daemon 双向 stream 接入后实现。

        当前 raise NotImplementedError。``if False: yield {}`` 让 Python 标记为
        async generator function（保 Plan 02/03 inspect.isasyncgenfunction 静态断言）。
        """
        raise NotImplementedError(
            "subscribe_events 留 Phase 5.C/5.D 接入（需 daemon 双向 stream）"
        )
        if False:  # pragma: no cover
            yield {}


# ── DocFacade ──────────────────────────────────────────────────────────────────


class DocFacade(_BaseFacade):
    """Doc capability facade — 实现 capabilities.doc.DocCapability Protocol（Plan 02）。"""

    @property
    def supports_collaborative_edit(self) -> bool:
        if (
            self._manifest.doc is None
            or self._manifest.doc.supports_collaborative_edit is None
        ):
            return False
        return self._manifest.doc.supports_collaborative_edit

    @property
    def supports_comments(self) -> bool:
        if self._manifest.doc is None or self._manifest.doc.supports_comments is None:
            return False
        return self._manifest.doc.supports_comments

    async def create_document(
        self,
        *,
        title: str,
        markdown: str,
        owners: list[UserRef] | None = None,
    ) -> DocRef:
        """转发到 daemon doc.create_document；返回 DocRef。"""
        daemon = self._ensure_daemon()
        result = await daemon.invoke(
            "doc",
            "create_document",
            title=title,
            markdown=markdown,
            owners=[asdict(o) for o in (owners or [])],
        )
        return DocRef(
            plugin_name=result.get("plugin_name", self.name),
            native_id=result["native_id"],
            extras=result.get("extras", {}),
        )

    async def replace_document_content(self, doc_ref: DocRef, markdown: str) -> None:
        """全量替换文档（仅 supports_collaborative_edit=False 时调用）。"""
        daemon = self._ensure_daemon()
        await daemon.invoke(
            "doc",
            "replace_document_content",
            doc_ref=asdict(doc_ref),
            markdown=markdown,
        )

    async def apply_document_delta(self, doc_ref: DocRef, delta: CRDTDelta) -> None:
        """应用 CRDT delta（仅 supports_collaborative_edit=True 时调用）。

        ``CRDTDelta.payload: bytes`` JSONRPC 不支持 bytes 直传 → base64 encode。
        """
        daemon = self._ensure_daemon()
        payload_b64 = base64.b64encode(delta.payload).decode("ascii")
        await daemon.invoke(
            "doc",
            "apply_document_delta",
            doc_ref=asdict(doc_ref),
            delta={"format": delta.format, "payload_b64": payload_b64},
        )

    async def add_comment(
        self,
        *,
        doc_ref: DocRef,
        body: str,
        mentions: list[UserRef] | None = None,
    ) -> CommentRef:
        """添加评论 — 返回 CommentRef（含 parent_doc_ref 用于联级清理）。"""
        daemon = self._ensure_daemon()
        result = await daemon.invoke(
            "doc",
            "add_comment",
            doc_ref=asdict(doc_ref),
            body=body,
            mentions=[asdict(m) for m in (mentions or [])],
        )
        return CommentRef(
            plugin_name=result.get("plugin_name", self.name),
            native_id=result["native_id"],
            parent_doc_ref=doc_ref,
        )

    async def get_document(self, doc_ref: DocRef) -> DocInfo | None:
        """查询文档元信息 + 可选 content；None 表示不存在 / 无权限。"""
        daemon = self._ensure_daemon()
        result = await daemon.invoke(
            "doc",
            "get_document",
            doc_ref=asdict(doc_ref),
        )
        if result is None:
            return None
        return DocInfo(
            doc_ref=doc_ref,
            title=result["title"],
            url=result.get("url"),
            content_markdown=result.get("content_markdown"),
        )


# ── HRFacade ───────────────────────────────────────────────────────────────────


class HRFacade(_BaseFacade):
    """HR capability facade — 实现 capabilities.hr.HRCapability Protocol（Plan 03）。"""

    async def list_employees(
        self,
        *,
        filter: EmployeeFilter | None = None,
        cursor: str | None = None,
    ) -> tuple[list[Employee], str | None]:
        """分页查询员工 — daemon 返回 ``{"employees": [...], "next_cursor": ...}``。"""
        daemon = self._ensure_daemon()
        result = await daemon.invoke(
            "hr",
            "list_employees",
            filter=asdict(filter) if filter else None,
            cursor=cursor,
        )
        employees = [
            Employee(
                ref=EmployeeRef(
                    plugin_name=e["ref"].get("plugin_name", self.name),
                    native_id=e["ref"]["native_id"],
                ),
                username=e["username"],
                email=e["email"],
                display_name=e["display_name"],
                department_id=e.get("department_id"),
                manager_id=e.get("manager_id"),
                is_active=e.get("is_active", True),
                custom_fields=e.get("custom_fields", {}),
            )
            for e in result.get("employees", [])
        ]
        return employees, result.get("next_cursor")

    async def get_employee(self, employee_ref: EmployeeRef) -> Employee | None:
        """按 ref 查单员工 — None 表示不存在。"""
        daemon = self._ensure_daemon()
        result = await daemon.invoke(
            "hr",
            "get_employee",
            employee_ref=asdict(employee_ref),
        )
        if result is None:
            return None
        return Employee(
            ref=EmployeeRef(
                plugin_name=result["ref"].get("plugin_name", self.name),
                native_id=result["ref"]["native_id"],
            ),
            username=result["username"],
            email=result["email"],
            display_name=result["display_name"],
            department_id=result.get("department_id"),
            manager_id=result.get("manager_id"),
            is_active=result.get("is_active", True),
            custom_fields=result.get("custom_fields", {}),
        )

    async def list_departments(self) -> list[Department]:
        """全量查部门树（一般缓存）。"""
        daemon = self._ensure_daemon()
        result = await daemon.invoke("hr", "list_departments")
        return [
            Department(
                id=d["id"],
                name=d["name"],
                parent_id=d.get("parent_id"),
                team_lead_employee_id=d.get("team_lead_employee_id"),
                member_ids=tuple(d.get("member_ids", [])),
            )
            for d in result
        ]

    async def resolve_department_members(self, expression: str) -> list[EmployeeRef]:
        """Phase 5.D ``dept:研发部`` 表达式解析 — 返回 EmployeeRef 列表（不识别返回空）。"""
        daemon = self._ensure_daemon()
        result = await daemon.invoke(
            "hr",
            "resolve_department_members",
            expression=expression,
        )
        return [
            EmployeeRef(
                plugin_name=r.get("plugin_name", self.name),
                native_id=r["native_id"],
            )
            for r in result
        ]

    async def list_leave_requests(
        self,
        *,
        employee_ref: EmployeeRef | None = None,
        status: Literal["pending", "approved", "rejected"] | None = None,
        cursor: str | None = None,
    ) -> tuple[list[LeaveRequest], str | None]:
        """分页查请假申请 — daemon 返回 ``{"requests": [...], "next_cursor": ...}``。"""
        daemon = self._ensure_daemon()
        result = await daemon.invoke(
            "hr",
            "list_leave_requests",
            employee_ref=asdict(employee_ref) if employee_ref else None,
            status=status,
            cursor=cursor,
        )
        requests = [
            LeaveRequest(
                id=r["id"],
                employee_ref=EmployeeRef(
                    plugin_name=r["employee_ref"].get("plugin_name", self.name),
                    native_id=r["employee_ref"]["native_id"],
                ),
                request_type=r["request_type"],
                start_date=r["start_date"],
                end_date=r["end_date"],
                description=r["description"],
                status=r["status"],
            )
            for r in result.get("requests", [])
        ]
        return requests, result.get("next_cursor")

    async def create_leave_request(
        self,
        *,
        employee_ref: EmployeeRef,
        request_type: Literal["vacation", "sick", "pto", "remote", "overtime"],
        start_date: str,
        end_date: str,
        description: str,
    ) -> LeaveRequest:
        """提交请假申请（仅 source_of_truth=True 的 plugin 实现）。"""
        daemon = self._ensure_daemon()
        result = await daemon.invoke(
            "hr",
            "create_leave_request",
            employee_ref=asdict(employee_ref),
            request_type=request_type,
            start_date=start_date,
            end_date=end_date,
            description=description,
        )
        return LeaveRequest(
            id=result["id"],
            employee_ref=employee_ref,
            request_type=request_type,
            start_date=start_date,
            end_date=end_date,
            description=description,
            status=result.get("status", "pending"),
        )


# ── IdentityFacade ─────────────────────────────────────────────────────────────


class IdentityFacade(_BaseFacade):
    """Identity capability facade — 实现 capabilities.identity.IdentityCapability Protocol（Plan 03）.

    `is_source_of_truth` flag 解决 Huly acid test §6 反向 sync 设计（Plan 03 决策）：
    - True 时 watch_user_changes 真推送 user 变更事件（Phase 5.D 落地）
    - False 时 watch_user_changes raise NotImplementedError
    """

    @property
    def is_source_of_truth(self) -> bool:
        if (
            self._manifest.identity is None
            or self._manifest.identity.is_source_of_truth is None
        ):
            return False
        return self._manifest.identity.is_source_of_truth

    async def list_users(self) -> list[UserPrincipal]:
        """全量查所有 users（一般 plugin 实现含分页内部聚合）。"""
        daemon = self._ensure_daemon()
        result = await daemon.invoke("identity", "list_users")
        return [
            UserPrincipal(
                plugin_name=u.get("plugin_name", self.name),
                native_id=u["native_id"],
                canonical_username=u["canonical_username"],
                email=u["email"],
                display_name=u["display_name"],
                is_active=u.get("is_active", True),
                extras=u.get("extras", {}),
            )
            for u in result
        ]

    async def resolve_user(self, identifier: str) -> UserPrincipal | None:
        """按 email / canonical_username / native_id 查 — None 表示不识别。"""
        daemon = self._ensure_daemon()
        result = await daemon.invoke(
            "identity",
            "resolve_user",
            identifier=identifier,
        )
        if result is None:
            return None
        return UserPrincipal(
            plugin_name=result.get("plugin_name", self.name),
            native_id=result["native_id"],
            canonical_username=result["canonical_username"],
            email=result["email"],
            display_name=result["display_name"],
            is_active=result.get("is_active", True),
            extras=result.get("extras", {}),
        )

    async def watch_user_changes(self) -> AsyncIterator[dict[str, Any]]:
        """User 变更长连推送 — Phase 5.D 接入。当前 raise NotImplementedError."""
        raise NotImplementedError(
            "watch_user_changes 留 Phase 5.D 接入（需 daemon 双向 stream + source_of_truth=True）"
        )
        if False:  # pragma: no cover
            yield {}


__all__ = [
    "IMFacade",
    "DocFacade",
    "HRFacade",
    "IdentityFacade",
]
