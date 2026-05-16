"""FastAPI 依赖（Depends）定义 — agent-builder 专用。

主要依赖：
- get_current_user: 从 session cookie 解析当前登录用户（未登录 401）
- get_optional_user: session cookie 缺失返回 None（setup 阶段用）
- get_current_workspace: 加载当前工作区对象
- require_role: RBAC 角色检查 Depends 工厂
- require_workspace_member: workspace 归属检查 Depends 工厂

Session cookie 格式：
  httpOnly + SameSite=Lax（生产加 Secure），名为 "session"
  payload: {sub: user_id, ws: workspace_id, iat, exp}
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_builder.db.scoped_query import current_workspace_ctx
from app.agent_builder.db.session import get_db
from app.agent_builder.models.role import Role
from app.agent_builder.models.user import User, UserStatus
from app.agent_builder.models.user_workspace_role import UserWorkspaceRole
from app.agent_builder.models.workspace import Workspace
from app.services.jwt_service import TokenExpired, TokenInvalid, decode_session

log = logging.getLogger(__name__)


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """从 session cookie 解析当前登录用户。

    1. 读取 cookie["session"]
    2. decode_session → SessionClaims
    3. 加载 User from DB
    4. 检查 user.status == 'active'
    5. 设置 current_workspace_ctx（用于 WorkspaceScopedQuery）

    Args:
        request: FastAPI Request
        db: AsyncSession

    Returns:
        User 对象（已验证、已激活）

    Raises:
        HTTPException(401): 未登录 / token 无效 / 用户不存在
        HTTPException(403): 账号未激活 / 已禁用
    """
    session_cookie = request.cookies.get("session")
    if not session_cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录，请先登录",
        )

    try:
        claims = decode_session(session_cookie)
    except TokenExpired:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录已过期，请重新登录",
        )
    except TokenInvalid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的登录凭证",
        )

    user_id = uuid.UUID(claims["sub"])
    ws_id = uuid.UUID(claims["ws"])

    # 加载用户
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
        )

    if user.status == UserStatus.pending_verification.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号待邮箱验证，请查收验证邮件",
        )

    if user.status == UserStatus.disabled.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用，请联系管理员",
        )

    # 设置 workspace context（WorkspaceScopedQuery 用）
    current_workspace_ctx.set(ws_id)

    # 在 request.state 中存储当前 workspace_id，供 require_role 使用
    request.state.current_user = user
    request.state.current_workspace_id = ws_id

    return user


async def get_optional_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """从 session cookie 尝试解析当前用户，失败返回 None。

    用于 setup 阶段的端点（未登录时也需要访问）。

    Args:
        request: FastAPI Request
        db: AsyncSession

    Returns:
        User 对象（已登录）或 None（未登录）
    """
    session_cookie = request.cookies.get("session")
    if not session_cookie:
        return None

    try:
        claims = decode_session(session_cookie)
    except (TokenExpired, TokenInvalid):
        return None

    user_id = uuid.UUID(claims["sub"])
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_current_workspace(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Workspace:
    """加载当前工作区对象。

    从 request.state.current_workspace_id（由 get_current_user 设置）加载。

    Args:
        request: FastAPI Request
        db: AsyncSession
        current_user: 当前登录用户

    Returns:
        Workspace 对象

    Raises:
        HTTPException(404): 工作区不存在
    """
    ws_id: uuid.UUID = request.state.current_workspace_id
    result = await db.execute(select(Workspace).where(Workspace.id == ws_id))
    workspace = result.scalar_one_or_none()
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="当前工作区不存在",
        )
    return workspace


async def _get_user_workspace_role(
    user: User,
    workspace_id: uuid.UUID,
    db: AsyncSession,
) -> Optional[str]:
    """查询用户在指定工作区的角色代码。

    Args:
        user: User 对象
        workspace_id: 工作区 ID
        db: AsyncSession

    Returns:
        角色代码字符串（如 'admin'）或 None（用户不属于该工作区）
    """
    if user.is_super_admin:
        return "super_admin"

    result = await db.execute(
        select(UserWorkspaceRole)
        .where(
            UserWorkspaceRole.user_id == user.id,
            UserWorkspaceRole.workspace_id == workspace_id,
        )
    )
    uwr = result.scalar_one_or_none()
    if uwr is None:
        return None

    role_result = await db.execute(
        select(Role).where(Role.id == uwr.role_id)
    )
    role = role_result.scalar_one_or_none()
    return role.code if role else None


def require_role(*allowed_codes: str):
    """FastAPI Depends 工厂：要求当前用户在当前 workspace 拥有指定角色之一。

    用法：
        @router.post("/api/invites")
        async def create_invite(
            ...,
            _rbac: None = Depends(require_role("admin", "super_admin")),
        ):
            ...

    Args:
        *allowed_codes: 允许的角色代码（如 "admin", "super_admin"）

    Returns:
        FastAPI Depends 可用的异步函数
    """
    async def _check(
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ) -> None:
        # super_admin 全局通行
        if current_user.is_super_admin:
            return

        ws_id: uuid.UUID = request.state.current_workspace_id
        role_code = await _get_user_workspace_role(current_user, ws_id, db)

        if role_code is None or role_code not in allowed_codes:
            log.warning(
                "RBAC 拒绝：user=%s role=%s required_any=%s",
                current_user.id,
                role_code,
                allowed_codes,
            )
            # 写 audit_log：使用独立 session 确保在 HTTPException 回滚前提交
            # （get_db 遇到异常会 rollback，不能复用请求 session）
            try:
                from app.agent_builder.db.engine import async_session_maker
                from app.services.audit import log as audit_log

                async with async_session_maker() as audit_session:
                    await audit_log(
                        audit_session,
                        action="rbac.denied",
                        workspace_id=ws_id,
                        actor_user_id=current_user.id,
                        meta={
                            "role": role_code,
                            "required": list(allowed_codes),
                            "path": str(request.url),
                        },
                        request=request,
                    )
                    await audit_session.commit()
            except Exception:
                pass

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="权限不足",
            )

    return _check


def require_workspace_member():
    """FastAPI Depends 工厂：要求当前用户属于 workspace_id 路径参数指定的工作区。

    用法（路径参数 workspace_id）：
        @router.get("/api/workspaces/{workspace_id}/users")
        async def list_users(
            workspace_id: uuid.UUID,
            _member: None = Depends(require_workspace_member()),
        ):
            ...

    Returns:
        FastAPI Depends 可用的异步函数
    """
    async def _check(
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ) -> None:
        # super_admin 全局通行
        if current_user.is_super_admin:
            return

        ws_id_str = request.path_params.get("workspace_id")
        if not ws_id_str:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="缺少路径参数 workspace_id",
            )

        try:
            ws_id = uuid.UUID(ws_id_str)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"无效的 workspace_id 格式：{ws_id_str}",
            )

        role_code = await _get_user_workspace_role(current_user, ws_id, db)
        if role_code is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="您不属于该工作区",
            )

    return _check
