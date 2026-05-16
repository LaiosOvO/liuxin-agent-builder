"""Setup 流程 API 路由。

端点：
- GET  /api/setup/state      : 查询 setup 状态（公开，不需要认证）
- POST /api/setup/initialize : 首次初始化（创建 super_admin + workspace）

Setup 流程规则（CONTEXT.md）：
- 未初始化时所有 /api/* 请求返回 503（SetupRedirectMiddleware 控制）
- 初始化后 /api/setup/* 返回 404（SetupRedirectMiddleware 控制）
- setup 路由不经过 require_role 装饰；自身判断状态
- 限频：每 IP 每分钟最多 3 次（防止扫号）
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_builder.db.session import get_db
from app.agent_builder.security.rate_limit import limiter
from app.schemas.setup import InitializeRequest, SetupStateResponse
from app.services.jwt_service import sign_session
from app.services.setup_service import initialize_first_admin, is_setup_complete

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/state", response_model=SetupStateResponse)
async def get_setup_state(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SetupStateResponse:
    """查询系统 setup 状态。

    返回 {initialized: true/false, version: "1.0.0"}。
    前端根据 initialized=false 决定是否显示 setup 向导页。

    注意：SetupRedirectMiddleware 在初始化后会对此端点返回 404，
    因此前端只有在 setup 完成前才能访问此接口。
    """
    initialized = await is_setup_complete(db)
    return SetupStateResponse(initialized=initialized, version="1.0.0")


@router.post("/initialize", status_code=status.HTTP_200_OK)
@limiter.limit("3/minute")
async def initialize_setup(
    request: Request,
    body: InitializeRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """执行首次 setup 初始化。

    创建 super_admin 用户 + 第一个 workspace + admin role 绑定 + 审计日志。
    初始化完成后签发 session cookie，直接登录。

    请求限频：每 IP 每分钟最多 3 次（防扫号）。

    Returns:
        {message, user_id, workspace_id}（同时 Set-Cookie: session）

    Raises:
        HTTPException(409): 系统已初始化（重复调用）
        HTTPException(422): 密码强度不足（Pydantic 已校验 min_length，这里校验内容）
    """
    # 检查是否已初始化
    if await is_setup_complete(db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="系统已初始化，不能重复执行 setup",
        )

    try:
        user, workspace = await initialize_first_admin(
            db=db,
            email=str(body.email),
            password=body.password,
            display_name=body.display_name,
            workspace_name=body.workspace_name,
            request=request,
        )
        await db.commit()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )

    # 签发 session token（直接登录）
    session_token = sign_session(user.id, workspace.id)

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

    log.info("setup 初始化完成：user=%s workspace=%s", user.id, workspace.id)

    return {
        "message": "初始化成功，已自动登录",
        "user_id": str(user.id),
        "workspace_id": str(workspace.id),
    }
