"""Plugin capability facades —— Phase 5.A Plan 04 stub / Plan 05 完整实现。

设计要点（ADR-001 §5 + RESEARCH.md §Pattern 4）：

- 4 facade（IMFacade / DocFacade / HRFacade / IdentityFacade）共享 `_BaseFacade` 父类
- 每 facade 持 `_daemon: PlatformDaemonClient | None`（Plan 04 暂 None；Plan 05 注入）
- 每 facade 持 `_manifest: PlatformManifest`（读 capability spec 配置）
- 方法签名 100% 对齐 capabilities/{im,doc,hr,identity}.py Protocol 定义（duck typing 兼容）
- Plan 04 所有方法 raise NotImplementedError —— Plan 05 替换为 `await self._daemon.invoke(...)`

为什么 Plan 04 必须建 stub（PLAN.md 决策推荐 (b)）：
- plugin.py 的 `@property im / doc / hr / identity` 内部 `from .capability_facades import IMFacade`
- 若 capability_facades 模块不存在 → import 时 raise ModuleNotFoundError
- 即使测试不调 `plugin.im`，IDE / mypy / 静态分析也会报错
- Plan 05 接入 daemon 时只需替换方法实现，签名 + 文件位置不变 → 0 接口破坏

异步生成器方法（subscribe_events / watch_user_changes）使用 `if False: yield {}` 模式
让 Python 静态分析将其识别为 async generator function（虽然先 raise 不会到达 yield）。

Reference: docs/reading-dify-05a-04-manifest-registry-2026-05-17.md §借鉴点 #6（启动期 vs 懒加载）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .daemon_client import PlatformDaemonClient  # Plan 06 创建
    from .manifest import PlatformManifest


class _BaseFacade:
    """4 capability facade 共享 base 类 — 持 daemon + manifest 引用。

    Plan 05 演进路径：
        async def _invoke(self, capability: str, method: str, **kwargs: Any) -> Any:
            if self._daemon is None:
                raise RuntimeError(f"Facade for {capability} not attached to daemon")
            return await self._daemon.invoke(capability, method, **kwargs)
    """

    def __init__(
        self,
        daemon: PlatformDaemonClient | None,
        manifest: PlatformManifest,
    ) -> None:
        self._daemon = daemon
        self._manifest = manifest


# ── IMFacade ───────────────────────────────────────────────────────────────────


class IMFacade(_BaseFacade):
    """IM capability facade — 实现 capabilities.im.IMCapability Protocol（Plan 02）。

    Plan 04 stub：所有方法 raise NotImplementedError + name="facade_im_stub"
    Plan 05 实接入：方法转发 `await self._daemon.invoke("im", "send_card", **kwargs)`
    """

    # cap flag —— Plan 05 应从 self._manifest.im 读取
    name: str = "facade_im_stub"
    supports_native_buttons: bool = False
    supports_card_update: bool = False
    supports_threads: bool = False

    async def send_card(
        self, *, recipient: Any, card: Any, idempotency_key: str
    ) -> Any:
        raise NotImplementedError("Plan 05 接入 daemon 后实现")

    async def update_card(self, msg_ref: Any, card: Any) -> None:
        raise NotImplementedError("Plan 05 接入 daemon 后实现")

    async def send_text(self, recipient: Any, text: str) -> Any:
        raise NotImplementedError("Plan 05 接入 daemon 后实现")

    async def subscribe_events(
        self, event_types: list[str]
    ) -> AsyncIterator[dict[str, Any]]:
        raise NotImplementedError("Plan 05 接入 daemon 后实现")
        if False:  # 让 Python 识别为 async generator function（不会执行到这里）
            yield {}


# ── DocFacade ──────────────────────────────────────────────────────────────────


class DocFacade(_BaseFacade):
    """Doc capability facade — 实现 capabilities.doc.DocCapability Protocol（Plan 02）。"""

    name: str = "facade_doc_stub"
    supports_collaborative_edit: bool = False
    supports_comments: bool = False

    async def create_document(
        self, *, title: str, markdown: str, owners: list[Any] | None = None
    ) -> Any:
        raise NotImplementedError("Plan 05 接入 daemon 后实现")

    async def replace_document_content(self, doc_ref: Any, markdown: str) -> None:
        raise NotImplementedError("Plan 05 接入 daemon 后实现")

    async def apply_document_delta(self, doc_ref: Any, delta: Any) -> None:
        raise NotImplementedError("Plan 05 接入 daemon 后实现")

    async def add_comment(
        self, *, doc_ref: Any, body: str, mentions: list[Any] | None = None
    ) -> Any:
        raise NotImplementedError("Plan 05 接入 daemon 后实现")

    async def get_document(self, doc_ref: Any) -> Any:
        raise NotImplementedError("Plan 05 接入 daemon 后实现")


# ── HRFacade ───────────────────────────────────────────────────────────────────


class HRFacade(_BaseFacade):
    """HR capability facade — 实现 capabilities.hr.HRCapability Protocol（Plan 03）。"""

    name: str = "facade_hr_stub"

    async def list_employees(
        self, *, filter: Any = None, cursor: str | None = None
    ) -> Any:
        raise NotImplementedError("Plan 05 接入 daemon 后实现")

    async def get_employee(self, employee_ref: Any) -> Any:
        raise NotImplementedError("Plan 05 接入 daemon 后实现")

    async def list_departments(self) -> Any:
        raise NotImplementedError("Plan 05 接入 daemon 后实现")

    async def resolve_department_members(self, expression: str) -> Any:
        """Phase 5.D dept:研发部 表达式解析接口。"""
        raise NotImplementedError("Plan 05 接入 daemon 后实现")

    async def list_leave_requests(
        self,
        *,
        employee_ref: Any = None,
        status: str | None = None,
        cursor: str | None = None,
    ) -> Any:
        raise NotImplementedError("Plan 05 接入 daemon 后实现")

    async def create_leave_request(
        self,
        *,
        employee_ref: Any,
        request_type: str,
        start_date: str,
        end_date: str,
        description: str,
    ) -> Any:
        raise NotImplementedError("Plan 05 接入 daemon 后实现")


# ── IdentityFacade ─────────────────────────────────────────────────────────────


class IdentityFacade(_BaseFacade):
    """Identity capability facade — 实现 capabilities.identity.IdentityCapability Protocol（Plan 03）。

    `is_source_of_truth` flag 解决 Huly acid test §6 反向 sync 设计（Plan 03 决策）：
    - True 时 watch_user_changes 真推送 user 变更事件
    - False 时 watch_user_changes raise NotImplementedError
    """

    name: str = "facade_identity_stub"
    is_source_of_truth: bool = False

    async def list_users(self) -> Any:
        raise NotImplementedError("Plan 05 接入 daemon 后实现")

    async def resolve_user(self, identifier: str) -> Any:
        raise NotImplementedError("Plan 05 接入 daemon 后实现")

    async def watch_user_changes(self) -> AsyncIterator[dict[str, Any]]:
        raise NotImplementedError("Plan 05 接入 daemon 后实现")
        if False:  # async generator function 标记
            yield {}


__all__ = [
    "IMFacade",
    "DocFacade",
    "HRFacade",
    "IdentityFacade",
]
