"""RBAC 权限控制服务。

实现 CONTEXT.md 中的 4 角色权限矩阵（v1 硬编码，不做动态权限）。

角色层级（从高到低）：
  super_admin > admin > editor > viewer > external

外部角色（external）只能通过 HITL token 访问，不能登录 web 管理端（Phase 3 实现）。

FastAPI Depends 工厂：
  - require_role(*roles): 检查当前用户在当前 workspace 有足够角色权限
  - require_workspace_member(workspace_id): 检查用户是否属于该工作区
"""
from __future__ import annotations

import enum
import logging
from typing import Callable

from fastapi import Depends, HTTPException, status

log = logging.getLogger(__name__)

# ── 角色层级定义 ─────────────────────────────────────────────────────────────────

# 角色代码（与 roles 表 code 字段对齐）
ROLE_SUPER_ADMIN = "super_admin"
ROLE_ADMIN = "admin"
ROLE_EDITOR = "editor"
ROLE_VIEWER = "viewer"
ROLE_EXTERNAL = "external"

# 角色层级（数值越大权限越高）
ROLE_HIERARCHY: dict[str, int] = {
    ROLE_EXTERNAL: 0,
    ROLE_VIEWER: 1,
    ROLE_EDITOR: 2,
    ROLE_ADMIN: 3,
    ROLE_SUPER_ADMIN: 4,
}


class Permission(str, enum.Enum):
    """系统权限枚举（覆盖 CONTEXT.md RBAC 矩阵）。"""

    # Workspace 管理
    CREATE_WORKSPACE = "create_workspace"
    DELETE_WORKSPACE = "delete_workspace"
    MANAGE_WORKSPACE_SETTINGS = "manage_workspace_settings"

    # 成员管理
    INVITE_MEMBER = "invite_member"
    REMOVE_MEMBER = "remove_member"
    VIEW_MEMBERS = "view_members"

    # 工作流
    CREATE_WORKFLOW = "create_workflow"
    EDIT_WORKFLOW = "edit_workflow"
    DELETE_WORKFLOW = "delete_workflow"
    PUBLISH_WORKFLOW = "publish_workflow"
    RUN_WORKFLOW = "run_workflow"
    VIEW_WORKFLOW = "view_workflow"

    # 实例
    VIEW_INSTANCE = "view_instance"
    CANCEL_INSTANCE = "cancel_instance"

    # HITL（Phase 3 用）
    VIEW_HITL_PAGE = "view_hitl_page"

    # 插件（Phase 6 用）
    MANAGE_PLUGIN = "manage_plugin"
    VIEW_PLUGIN = "view_plugin"

    # 审计（Phase 7 用）
    VIEW_AUDIT = "view_audit"


# ── 权限矩阵（v1 硬编码）────────────────────────────────────────────────────────

ROLE_PERMISSIONS: dict[str, set[Permission]] = {
    ROLE_SUPER_ADMIN: {
        # super_admin 拥有全部权限
        *list(Permission),
    },
    ROLE_ADMIN: {
        Permission.MANAGE_WORKSPACE_SETTINGS,
        Permission.INVITE_MEMBER,
        Permission.REMOVE_MEMBER,
        Permission.VIEW_MEMBERS,
        Permission.CREATE_WORKFLOW,
        Permission.EDIT_WORKFLOW,
        Permission.DELETE_WORKFLOW,
        Permission.PUBLISH_WORKFLOW,
        Permission.RUN_WORKFLOW,
        Permission.VIEW_WORKFLOW,
        Permission.VIEW_INSTANCE,
        Permission.CANCEL_INSTANCE,
        Permission.VIEW_HITL_PAGE,
        Permission.MANAGE_PLUGIN,
        Permission.VIEW_PLUGIN,
        Permission.VIEW_AUDIT,
    },
    ROLE_EDITOR: {
        Permission.VIEW_MEMBERS,
        Permission.CREATE_WORKFLOW,
        Permission.EDIT_WORKFLOW,
        Permission.PUBLISH_WORKFLOW,
        Permission.RUN_WORKFLOW,
        Permission.VIEW_WORKFLOW,
        Permission.VIEW_INSTANCE,
        Permission.VIEW_HITL_PAGE,
        Permission.VIEW_PLUGIN,
    },
    ROLE_VIEWER: {
        Permission.VIEW_MEMBERS,
        Permission.VIEW_WORKFLOW,
        Permission.VIEW_INSTANCE,
        Permission.VIEW_HITL_PAGE,
        Permission.VIEW_PLUGIN,
    },
    ROLE_EXTERNAL: {
        # external 只有 HITL 页面权限（通过 token 访问，不能登录管理端）
        Permission.VIEW_HITL_PAGE,
    },
}


def has_permission(role_code: str, perm: Permission) -> bool:
    """检查角色是否拥有指定权限。

    Args:
        role_code: 角色代码（如 'admin'）
        perm: 权限枚举值

    Returns:
        True 表示有权限
    """
    return perm in ROLE_PERMISSIONS.get(role_code, set())


def _get_role_level(role_code: str) -> int:
    """获取角色层级值（越大越高）。"""
    return ROLE_HIERARCHY.get(role_code, -1)


# ── FastAPI Depends 工厂 ────────────────────────────────────────────────────────


def require_role(*allowed_codes: str) -> Callable:
    """FastAPI Depends 工厂：要求当前用户在当前 workspace 拥有指定角色之一。

    用法：
        @router.post("/api/invites")
        async def create_invite(
            ...,
            _: None = Depends(require_role("admin", "super_admin")),
        ):
            ...

    Args:
        *allowed_codes: 允许的角色代码列表

    Returns:
        FastAPI Depends 可用的异步函数
    """
    async def _check(
        current_user_and_role: tuple = Depends(_get_current_user_and_role),
    ) -> None:
        user, role_code = current_user_and_role

        # super_admin 跨 workspace 全局通行
        if user.is_super_admin:
            return

        if role_code not in allowed_codes:
            log.warning(
                "RBAC 拒绝：user=%s role=%s required_any=%s",
                user.id,
                role_code,
                allowed_codes,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="权限不足",
            )

    return _check


def require_workspace_member(workspace_id_param: str = "workspace_id") -> Callable:
    """FastAPI Depends 工厂：要求当前用户是指定 workspace 的成员。

    从路径参数中读取 workspace_id（参数名由 workspace_id_param 指定）。

    Args:
        workspace_id_param: 路径参数名

    Returns:
        FastAPI Depends 可用的异步函数
    """
    async def _check(
        request: "Request",
        current_user_and_role: tuple = Depends(_get_current_user_and_role),
    ) -> None:
        from fastapi import Request as FastAPIRequest
        user, role_code = current_user_and_role

        # super_admin 跨 workspace 全局通行
        if user.is_super_admin:
            return

        # 从路径参数读取 workspace_id
        import uuid
        ws_id_str = request.path_params.get(workspace_id_param)
        if not ws_id_str:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"缺少路径参数 {workspace_id_param}",
            )

        try:
            ws_id = uuid.UUID(ws_id_str)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"无效的 workspace_id 格式：{ws_id_str}",
            )

        # 从 session token 中验证用户当前 workspace 是否匹配
        # （实际上 get_current_user 已从 session 解析出 ws，不匹配时直接 403）
        import uuid as _uuid
        from app.agent_builder.db.scoped_query import current_workspace_ctx
        ctx_ws = current_workspace_ctx.get()

        if ctx_ws is None or ctx_ws != ws_id:
            log.warning(
                "workspace 隔离拒绝：user=%s ctx_ws=%s requested_ws=%s",
                user.id,
                ctx_ws,
                ws_id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="您不属于该工作区，或当前 session 未切换到该工作区",
            )

    return _check


# ── 内部依赖（被 require_role 调用）─────────────────────────────────────────────


async def _get_current_user_and_role(
    request: "Request" = None,
) -> tuple:
    """从请求上下文获取当前用户和其在当前 workspace 中的角色代码。

    被 require_role 调用，用于角色检查。
    实际依赖注入在 api/deps.py 中的 get_current_user 完成。
    """
    # 这里使用 request.state 中已由 get_current_user 存储的信息
    # 实际实现在 deps.py 通过 Depends 链完成
    # 此函数是占位符，真正的实现见 api/deps.py 中的 require_role 替换版本
    raise NotImplementedError(
        "请使用 api/deps.py 中的 require_role 实现，而非直接调用此函数"
    )
