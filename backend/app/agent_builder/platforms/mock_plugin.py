"""MockPlatformPlugin — Phase 5.A Plan 05 测试用 in-process plugin（PLUG-FW-06）。

无 daemon — IM/Doc/HR/Identity capability 直接在主进程实现固定返回值；
不通过 JSONRPC over stdio，用于：

- Registry / Capability negotiation 单测（不依赖真 daemon 进程）
- Plugin / Facade lifecycle 测试
- Phase 5.B/5.C/5.D 业务层单测时替换真 plugin（隔离测试）

设计要点：
- 4 个 Mock<Capability> class 实现对应 Protocol（duck typing；isinstance 通过）
- MockPlatformPlugin 持 manifest + lazy 4 capability instance
- 与 PlatformPlugin 同 interface（name/manifest/im/doc/hr/identity properties）
  — 这样 Registry 等通用代码可同时处理 MockPlatformPlugin 与 PlatformPlugin
- 每方法返回 deterministic value（便于断言）；可选 record 调用历史（如 MockIMCapability.sent）

CLAUDE.md immutability：
- 4 个 capability 暴露的 ref（MessageRef/DocRef/...）走 dataclass(frozen=True) 不可变
- self.sent 列表是 instance state（test 可读，但不暴露给外部修改）

Reference: docs/reading-dify-05a-05-daemon-client-2026-05-17.md 借鉴点 #5（v1 不自动重启 → mock 无生命周期复杂度）
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Literal

from .capabilities import (
    CommentRef,
    CRDTDelta,
    Department,
    DocCapability,
    DocInfo,
    DocRef,
    Employee,
    EmployeeFilter,
    EmployeeRef,
    HRCapability,
    IdentityCapability,
    IMCapability,
    LeaveRequest,
    MessageRef,
    NormalizedCard,
    RecipientSpec,
    UserPrincipal,
    UserRef,
)

if TYPE_CHECKING:
    from .manifest import PlatformManifest


# ── MockIMCapability ──────────────────────────────────────────────────────────


class MockIMCapability:
    """In-process IM capability — 单测用，不走 JSONRPC。

    records sent / updated / text 历史便于断言：
        cap = MockIMCapability()
        await cap.send_card(...)
        assert len(cap.sent) == 1
    """

    name = "mock"
    supports_native_buttons = True
    supports_card_update = True
    supports_threads = False

    def __init__(self) -> None:
        self.sent: list[tuple[RecipientSpec, NormalizedCard, str]] = []
        self.updated: list[tuple[MessageRef, NormalizedCard]] = []
        self.texts: list[tuple[RecipientSpec, str]] = []

    async def send_card(
        self,
        *,
        recipient: RecipientSpec,
        card: NormalizedCard,
        idempotency_key: str,
    ) -> MessageRef:
        self.sent.append((recipient, card, idempotency_key))
        return MessageRef(plugin_name="mock", native_id=f"mock-{len(self.sent)}")

    async def update_card(self, msg_ref: MessageRef, card: NormalizedCard) -> None:
        self.updated.append((msg_ref, card))

    async def send_text(self, recipient: RecipientSpec, text: str) -> MessageRef:
        self.texts.append((recipient, text))
        return MessageRef(plugin_name="mock", native_id=f"text-{recipient.id}")

    async def subscribe_events(self, event_types: list[str]):
        # Phase 5.C/5.D 业务接入时实现；当前空 generator
        if False:  # pragma: no cover
            yield {}


# ── MockDocCapability ─────────────────────────────────────────────────────────


class MockDocCapability:
    """In-process Doc capability — supports_collaborative_edit=False 路径（mock 不模拟 CRDT）."""

    name = "mock"
    supports_collaborative_edit = False
    supports_comments = True

    def __init__(self) -> None:
        self.created: list[tuple[str, str]] = []  # (title, markdown)

    async def create_document(
        self,
        *,
        title: str,
        markdown: str,
        owners: list[UserRef] | None = None,
    ) -> DocRef:
        self.created.append((title, markdown))
        return DocRef(plugin_name="mock", native_id=str(uuid.uuid4()))

    async def replace_document_content(self, doc_ref: DocRef, markdown: str) -> None:
        pass

    async def apply_document_delta(self, doc_ref: DocRef, delta: CRDTDelta) -> None:
        raise NotImplementedError(
            "MockDocCapability supports_collaborative_edit=False — 调用方应走 replace_document_content"
        )

    async def add_comment(
        self,
        *,
        doc_ref: DocRef,
        body: str,
        mentions: list[UserRef] | None = None,
    ) -> CommentRef:
        return CommentRef(
            plugin_name="mock",
            native_id="c1",
            parent_doc_ref=doc_ref,
        )

    async def get_document(self, doc_ref: DocRef) -> DocInfo | None:
        return DocInfo(doc_ref=doc_ref, title="mock-title")


# ── MockHRCapability ──────────────────────────────────────────────────────────


class MockHRCapability:
    """In-process HR capability — resolve_department_members 等返回 deterministic value。"""

    name = "mock"

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
        # Phase 5.D 表达式解析 demo — 返回 1 个固定 EmployeeRef
        return [EmployeeRef(plugin_name="mock", native_id="emp1")]

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
            "MockHRCapability is_source_of_truth=False — 不写真实 leave 数据"
        )


# ── MockIdentityCapability ────────────────────────────────────────────────────


class MockIdentityCapability:
    """In-process Identity capability — is_source_of_truth=False 走 push 路径。"""

    name = "mock"
    is_source_of_truth = False

    async def list_users(self) -> list[UserPrincipal]:
        return []

    async def resolve_user(self, identifier: str) -> UserPrincipal | None:
        return None

    async def watch_user_changes(self):
        raise NotImplementedError(
            "MockIdentityCapability is_source_of_truth=False — 不能 watch user changes"
        )
        if False:  # pragma: no cover
            yield None


# ── MockPlatformPlugin ────────────────────────────────────────────────────────


class MockPlatformPlugin:
    """声明 IM + Doc + HR + Identity 4 capability 的 mock plugin。

    与 PlatformPlugin 同 interface — Registry 等通用代码可同时处理：
        plugin.name / plugin.manifest / plugin.im / plugin.doc / plugin.hr / plugin.identity

    每 capability 仅在 manifest.capabilities 声明时返回 instance（否则 None — 与 PlatformPlugin 一致）。

    用法（test）::

        manifest = load_manifest(fixture_path)  # capabilities: [im, doc, hr, identity]
        plugin = MockPlatformPlugin(manifest)
        assert isinstance(plugin.im, IMCapability)
        msg = await plugin.im.send_card(recipient=..., card=..., idempotency_key="k1")
        assert msg.plugin_name == "mock"
    """

    def __init__(self, manifest: PlatformManifest) -> None:
        self._manifest = manifest
        self._im: MockIMCapability | None = None
        self._doc: MockDocCapability | None = None
        self._hr: MockHRCapability | None = None
        self._identity: MockIdentityCapability | None = None

    @property
    def name(self) -> str:
        return self._manifest.name

    @property
    def manifest(self) -> PlatformManifest:
        return self._manifest

    @property
    def im(self) -> IMCapability | None:
        if "im" not in self._manifest.capabilities:
            return None
        if self._im is None:
            self._im = MockIMCapability()
        return self._im

    @property
    def doc(self) -> DocCapability | None:
        if "doc" not in self._manifest.capabilities:
            return None
        if self._doc is None:
            self._doc = MockDocCapability()
        return self._doc

    @property
    def hr(self) -> HRCapability | None:
        if "hr" not in self._manifest.capabilities:
            return None
        if self._hr is None:
            self._hr = MockHRCapability()
        return self._hr

    @property
    def identity(self) -> IdentityCapability | None:
        if "identity" not in self._manifest.capabilities:
            return None
        if self._identity is None:
            self._identity = MockIdentityCapability()
        return self._identity

    def __repr__(self) -> str:
        return (
            f"<MockPlatformPlugin name={self.name!r} "
            f"capabilities={self._manifest.capabilities}>"
        )


__all__ = [
    "MockPlatformPlugin",
    "MockIMCapability",
    "MockDocCapability",
    "MockHRCapability",
    "MockIdentityCapability",
]
