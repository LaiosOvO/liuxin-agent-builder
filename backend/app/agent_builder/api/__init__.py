"""agent-builder API 路由模块。

所有 API 路由在此注册，通过 router 对象暴露给 main.py。

子模块：
- deps.py   : FastAPI 依赖（get_current_user / require_role 等）
- setup.py  : /api/setup/ 路由
- auth.py   : /api/auth/ 路由
- invites.py: /api/invites/ 路由
- me.py     : /api/auth/me + /api/me/ 路由
"""
from fastapi import APIRouter

from app.agent_builder.api import auth, invites, me, setup

router = APIRouter()

router.include_router(setup.router, prefix="/api/setup", tags=["setup"])
router.include_router(auth.router, prefix="/api/auth", tags=["auth"])
router.include_router(invites.router, prefix="/api/invites", tags=["invites"])
router.include_router(me.router, prefix="/api", tags=["me"])
