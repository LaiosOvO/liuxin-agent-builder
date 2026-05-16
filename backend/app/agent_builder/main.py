"""agent-builder FastAPI 应用入口。

在 flock 原有 app.main 基础上，新增 agent-builder 路由和中间件。
Fork discipline：不修改 flock 原文件，所有改动作为新增模块。

挂载顺序（重要）：
1. CORS（最先处理跨域）
2. SlowAPIMiddleware（限频）
3. SetupRedirectMiddleware（setup 状态检查）
4. 路由（setup/auth/invites/me）

startup_checks 在模块 import 时立即执行（不放 lifespan，lifespan 触发太晚）。
"""
from __future__ import annotations

import os
from pathlib import Path

# 1. 加载 .env（优先于所有其他代码）
from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)

# 2. 启动安全校验（在 FastAPI app 构造之前）
from app.agent_builder.security.startup_checks import run_startup_checks

run_startup_checks()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.middleware import SlowAPIMiddleware

from app.agent_builder.api import auth, invites, me, setup
from app.agent_builder.middleware.setup_redirect import SetupRedirectMiddleware
from app.agent_builder.security.rate_limit import limiter
from app.agent_builder.db.checkout_hook import register_discard_all_hook
from app.agent_builder.db.engine import engine

# 注册 DISCARD ALL checkout hook
register_discard_all_hook(engine)

# 创建 FastAPI 应用
agent_builder_app = FastAPI(
    title="agent-builder API",
    description="通用拖拽式 LangGraph 编排平台",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

# ── 中间件挂载（顺序重要）────────────────────────────────────────────────────────

# CORS（最先）
web_origin = os.environ.get("WEB_ORIGIN", "http://localhost:3000")
agent_builder_app.add_middleware(
    CORSMiddleware,
    allow_origins=[web_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# slowapi 限频
agent_builder_app.state.limiter = limiter
agent_builder_app.add_middleware(SlowAPIMiddleware)

# Setup 状态检查（在限频之后）
agent_builder_app.add_middleware(SetupRedirectMiddleware)

# ── 路由注册 ─────────────────────────────────────────────────────────────────────

agent_builder_app.include_router(setup.router, prefix="/api/setup", tags=["setup"])
agent_builder_app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
agent_builder_app.include_router(invites.router, prefix="/api/invites", tags=["invites"])
agent_builder_app.include_router(me.router, prefix="/api", tags=["me"])
