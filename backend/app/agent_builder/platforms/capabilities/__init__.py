"""Capability Protocols — 6 capability，每个一个 file。

Phase 5.A Plan 03 独占写本 __init__.py（避免与 Plan 02 并行写冲突）。

Re-exports（按 capability 类别分组）：
- IM (Plan 02): IMCapability + RecipientSpec / NormalizedCard / MessageRef
- Doc (Plan 02): DocCapability + DocRef / DocInfo / CRDTDelta / CommentRef / UserRef
- HR (Plan 03): HRCapability + Employee / Department / EmployeeRef / EmployeeFilter / LeaveRequest
- Identity (Plan 03): IdentityCapability + UserPrincipal / UserChangeEvent
- Trigger (Plan 03, v1.1 骨架): TriggerCapability + TriggerEvent
- Tool (Plan 03, v1.1 骨架): ToolCapability + ToolSpec / ToolInvocationResult

Plan 03 用条件 import 处理 Plan 02 doc.py 尚未存在的场景：__all__ 字段仅在
对应模块 import 成功时包含其 export。这让 Plan 03 可独立 commit 不卡 Plan 02 进度。

Reference: docs/reading-dify-05a-03-hr-identity-trigger-tool-2026-05-17.md
- 借鉴点 #1: PluginCategory 枚举 → capabilities 集合
"""
from __future__ import annotations

# ── HR (Plan 03) — 必须存在 ──────────────────────────────────────────────────
from .hr import (
    Department,
    Employee,
    EmployeeFilter,
    EmployeeRef,
    HRCapability,
    LeaveRequest,
)

# ── Identity (Plan 03) — 必须存在 ────────────────────────────────────────────
from .identity import (
    IdentityCapability,
    UserChangeEvent,
    UserPrincipal,
)

# ── Trigger (Plan 03, v1.1 骨架) — 必须存在 ──────────────────────────────────
from .trigger import TriggerCapability, TriggerEvent

# ── Tool (Plan 03, v1.1 骨架) — 必须存在 ─────────────────────────────────────
from .tool import ToolCapability, ToolInvocationResult, ToolSpec

# ── IM (Plan 02) — 已存在则 re-export ────────────────────────────────────────
try:
    from .im import IMCapability, MessageRef, NormalizedCard, RecipientSpec
    _IM_EXPORTED = True
except ImportError:  # Plan 02 未完成时 graceful fallback
    _IM_EXPORTED = False

# ── Doc (Plan 02) — 已存在则 re-export ───────────────────────────────────────
try:
    from .doc import (
        CommentRef,
        CRDTDelta,
        DocCapability,
        DocInfo,
        DocRef,
        UserRef,
    )
    _DOC_EXPORTED = True
except ImportError:  # Plan 02 未完成时 graceful fallback
    _DOC_EXPORTED = False


# ── __all__ — 按模块可用性动态构建 ─────────────────────────────────────────────

__all__ = [
    # HR (Plan 03)
    "HRCapability",
    "Employee",
    "Department",
    "EmployeeRef",
    "EmployeeFilter",
    "LeaveRequest",
    # Identity (Plan 03)
    "IdentityCapability",
    "UserPrincipal",
    "UserChangeEvent",
    # Trigger (Plan 03, v1.1 skeleton)
    "TriggerCapability",
    "TriggerEvent",
    # Tool (Plan 03, v1.1 skeleton)
    "ToolCapability",
    "ToolSpec",
    "ToolInvocationResult",
]

# 条件追加 IM/Doc exports（仅在对应模块 import 成功时）
if _IM_EXPORTED:
    __all__ += ["IMCapability", "RecipientSpec", "NormalizedCard", "MessageRef"]

if _DOC_EXPORTED:
    __all__ += [
        "DocCapability",
        "DocInfo",
        "DocRef",
        "CRDTDelta",
        "CommentRef",
        "UserRef",
    ]
