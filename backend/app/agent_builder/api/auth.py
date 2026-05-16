"""认证相关 API 路由。

端点：
- POST /api/auth/register         : 邀请制注册（invite_token 必填）
- GET  /api/auth/verify-email     : 邮箱验证（点击邮件链接触发，消费 jti）
- POST /api/auth/login            : 登录（签发 session cookie）
- POST /api/auth/logout           : 退出（清除 session cookie）

注意（邮箱验证 GET vs HITL token GET 的区别）：
- 邮箱验证 GET 消费 jti：链接点击 = 用户主动确认邮箱所有权，一次性动作，消费符合预期
- HITL token GET 不消费：防止 Safe Links 扫描器 GET 预消费，导致用户无法审批（Pitfall 3）
- 两者语义不同，注释清楚区分，互不干扰
"""
from __future__ import annotations

import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_builder.db.session import get_db
from app.agent_builder.models.user import User, UserStatus
from app.agent_builder.models.user_workspace_role import UserWorkspaceRole
from app.agent_builder.models.role import Role
from app.agent_builder.security.rate_limit import limiter
from app.schemas.auth import LoginRequest, LoginResponse, MessageResponse
from app.services import audit as audit_service
from app.services.jwt_service import (
    TokenAlreadyUsedError,
    TokenExpired,
    TokenInvalid,
    sign_session,
)
from app.services.password import verify_password
from app.services.registration_service import verify_email

log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/register", response_model=MessageResponse)
@limiter.limit("3/minute")
async def register(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """邀请制注册（invite_token 必填）。

    公开注册关闭（CONTEXT.md 决策）。
    必须通过邀请 token 注册，转到 invites/accept 路径处理。
    此端点存在为了 API 规范性，实际注册逻辑在 POST /api/invites/accept。

    注意：此端点仅返回提示信息，引导用户使用邀请链接。
    """
    # 公开注册关闭，返回明确提示
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="公开注册已关闭，请通过管理员发送的邀请邮件注册",
    )


@router.get("/verify-email")
async def verify_email_endpoint(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """邮箱验证（点击邮件链接触发）。

    注意：此端点的 GET 消费 jti，这与 HITL token 规则不同。
    区别：
    - 邮箱验证：用户主动点击链接 = 确认邮箱所有权，GET 即消费（一步完成）
    - HITL token（Pitfall 3）：Safe Links 扫描器会 GET 链接，不应消费
    邮箱验证不存在扫描器问题（链接仅发给用户自己的邮箱），GET 消费合理。

    验证成功：重定向到 /login?verified=1
    验证失败（已用/过期）：重定向到 /login?error=...
    """
    base_url = os.environ.get("PUBLIC_BASE_URL", "http://localhost:3000")

    try:
        user = await verify_email(db=db, token=token, request=request)
        await db.commit()
        log.info("邮箱验证成功：user=%s", user.id)
        return RedirectResponse(url=f"{base_url}/login?verified=1")
    except TokenAlreadyUsedError:
        return RedirectResponse(url=f"{base_url}/login?error=token_used")
    except TokenExpired:
        return RedirectResponse(url=f"{base_url}/login?error=token_expired")
    except TokenInvalid:
        return RedirectResponse(url=f"{base_url}/login?error=token_invalid")
    except Exception as exc:
        log.error("邮箱验证失败：%s", exc)
        return RedirectResponse(url=f"{base_url}/login?error=unknown")


@router.post("/login")
@limiter.limit("10/minute")
async def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """用户登录（签发 session cookie）。

    流程：
    1. 校验邮箱 + 密码
    2. 检查用户状态（active）
    3. 加载用户 workspace + 角色
    4. 签发 session JWT（24h sliding window）
    5. 设置 httpOnly cookie
    6. 写 audit_log

    请求限频：每 IP 每分钟最多 10 次（防暴力破解，Plan 03 slowapi）。
    """
    email = str(body.email).lower()

    # 查询用户
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    # 密码校验（防时序攻击：无论用户是否存在都校验密码）
    if user is None or not verify_password(body.password, user.password_hash):
        # 写失败审计（仅用户存在时）
        if user is not None:
            await audit_service.log(
                db,
                action="login.failed",
                actor_user_id=user.id,
                meta={"email": email, "reason": "wrong_password"},
                request=request,
            )
            await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        )

    # 检查用户状态
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

    # 获取用户的第一个 workspace（TODO: Phase 2 实现多 workspace 切换）
    uwr_result = await db.execute(
        select(UserWorkspaceRole)
        .where(UserWorkspaceRole.user_id == user.id)
        .limit(1)
    )
    uwr = uwr_result.scalar_one_or_none()

    if uwr is None and not user.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户未加入任何工作区",
        )

    # super_admin 可能没有 workspace 绑定（如刚初始化后还没创建第二个）
    workspace_id = uwr.workspace_id if uwr else uuid.UUID(
        "00000000-0000-0000-0000-000000000000"
    )
    role_code = "super_admin" if user.is_super_admin else None

    if uwr and not user.is_super_admin:
        role_result = await db.execute(
            select(Role).where(Role.id == uwr.role_id)
        )
        role = role_result.scalar_one_or_none()
        role_code = role.code if role else "viewer"

    # 签发 session token
    session_token = sign_session(user.id, workspace_id)

    # 更新最后登录时间
    from datetime import datetime, timezone
    user.last_login_at = datetime.now(timezone.utc)

    # 写 audit_log
    await audit_service.log(
        db,
        action="login.success",
        workspace_id=workspace_id if uwr else None,
        actor_user_id=user.id,
        meta={"email": email},
        request=request,
    )
    await db.commit()

    # 设置 httpOnly cookie
    is_production = os.environ.get("APP_ENV", "development") == "production"
    response.set_cookie(
        key="session",
        value=session_token,
        httponly=True,
        samesite="lax",
        secure=is_production,
        max_age=86400,  # 24h
    )

    log.info("登录成功：user=%s", user.id)

    return LoginResponse(
        user_id=user.id,
        workspace_id=workspace_id,
        role=role_code or "viewer",
        redirect_to="/dashboard",
    )


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """退出登录（清除 session cookie）。

    清除 httpOnly session cookie。
    v1 不维护 session 黑名单（token 自然过期），若需强制失效见 v2 TODO。

    写 audit_log（用户 ID 从 cookie 中解析，未登录时忽略）。
    """
    from app.services.jwt_service import decode_session

    session_cookie = request.cookies.get("session")
    user_id = None

    if session_cookie:
        try:
            claims = decode_session(session_cookie)
            user_id = uuid.UUID(claims["sub"])
            ws_id = uuid.UUID(claims["ws"])

            await audit_service.log(
                db,
                action="logout",
                workspace_id=ws_id,
                actor_user_id=user_id,
                request=request,
            )
            await db.commit()
        except Exception:
            pass  # token 解析失败时忽略 audit

    # 清除 cookie
    response.delete_cookie(key="session", httponly=True, samesite="lax")

    return MessageResponse(message="已成功退出登录")
