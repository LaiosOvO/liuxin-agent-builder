"""Setup 重定向中间件。

逻辑（PLAN 描述）：
1. 请求路径以 /api/ 开头：
   - _setup_complete == False 且路径不在 /api/setup/*：
     → 返回 503 with {error: "setup required", redirect: "/setup"}
   - _setup_complete == True 且路径以 /api/setup/：
     → 返回 404
2. 其他请求（前端路由）：直接放行（前端自己根据 /api/setup/state 判断）

DB 查询用进程内缓存（setup_service.is_setup_complete），避免每请求查 DB。
注意：使用缓存的 session 创建（不占用连接池资源）。
"""
from __future__ import annotations

import logging

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = logging.getLogger(__name__)

# 不受 setup 状态影响的路径前缀（白名单）
_SETUP_PREFIX = "/api/setup/"
_API_PREFIX = "/api/"
# Plan 04-12：测试辅助路由白名单（仅 ENABLE_TEST_API=1 时挂载，需绕过 setup gate）
_TEST_HELPERS_PREFIX = "/api/test/"


class SetupRedirectMiddleware(BaseHTTPMiddleware):
    """FastAPI 中间件：根据 setup 状态控制 API 访问。

    未初始化时：/api/* 非 setup 路由返回 503
    初始化后：/api/setup/* 返回 404（setup 路由隐藏）

    挂载位置：SlowAPIMiddleware 之后（保证限频先生效，再判断 setup）
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # 只处理 /api/ 前缀的请求
        if not path.startswith(_API_PREFIX):
            return await call_next(request)

        # Plan 04-12：test_helpers 路由白名单（仅 ENABLE_TEST_API=1 时挂载，绕过 setup gate）
        if path.startswith(_TEST_HELPERS_PREFIX):
            return await call_next(request)

        # 获取 setup 状态（使用进程内缓存，避免每请求查 DB）
        setup_complete = await self._is_setup_complete(request)

        if not setup_complete:
            # 未初始化：只允许访问 /api/setup/ 路由
            if not path.startswith(_SETUP_PREFIX):
                log.debug("setup 未完成，阻断请求：%s", path)
                return JSONResponse(
                    status_code=503,
                    content={
                        "error": "setup required",
                        "redirect": "/setup",
                        "message": "系统尚未初始化，请先完成 Setup 向导",
                    },
                )
        else:
            # 已初始化：setup 路由对外返回 404
            if path.startswith(_SETUP_PREFIX):
                log.debug("setup 已完成，隐藏 setup 路由：%s", path)
                return JSONResponse(
                    status_code=404,
                    content={"detail": "Not Found"},
                )

        return await call_next(request)

    async def _is_setup_complete(self, request: Request) -> bool:
        """读取 setup 状态（优先进程内缓存，缓存未命中时查 DB）。

        注意：中间件不能使用 FastAPI Depends，需要手动管理 DB session。
        使用独立 session，不与请求 session 共享（避免 event loop 冲突）。
        """
        import app.services.setup_service as svc_module

        # 直接读取 module-level 缓存变量（避免额外导入）
        cached = svc_module._setup_complete
        if cached is not None:
            return cached

        # 缓存未命中，查 DB（创建临时 session）
        try:
            from app.agent_builder.db.engine import async_session_maker
            from app.services.setup_service import is_setup_complete

            async with async_session_maker() as session:
                result = await is_setup_complete(session)
                await session.close()
                return result
        except Exception as e:
            log.error("检查 setup 状态失败：%s", e)
            # 失败时 fail-close（阻止访问）
            return False
