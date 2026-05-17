from pathlib import Path

from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.routing import APIRoute
from sqlmodel import Session
from starlette.middleware.cors import CORSMiddleware

from app.api.main import api_router
from app.core.config import settings
from app.core.db import engine, init_db, init_modelprovider_model_db


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


if settings.SENTRY_DSN:
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    with Session(engine) as session:
        init_db(session)
        init_modelprovider_model_db(session)

    # Plan 04-07：注册 IM Providers（按 .env 配置决定哪些 Provider 启用）
    _register_im_providers()

    yield
    # Shutdown


def _register_im_providers() -> None:
    """根据 .env 凭据注册可用的 IM Provider（Plan 04-07+ 各 plan 增量补充）。

    各 Provider 仅当对应凭据齐全时才注册；未配置不影响其他 Provider 运行。
    """
    import logging

    from app.agent_builder.core.im_credentials import IMCredentialsManager
    from app.agent_builder.notification.providers.base import register_provider

    logger = logging.getLogger(__name__)
    mgr = IMCredentialsManager()

    # Plan 04-07: WeComProvider
    if mgr.has_wecom():
        try:
            from app.agent_builder.notification.providers.wecom import (
                WeComProvider,
            )

            creds = mgr.wecom()
            provider = WeComProvider(
                corp_id=creds.corp_id,
                agent_id=creds.agent_id,
                secret=creds.secret,
                bot_webhook_key=creds.bot_webhook_key,
            )
            register_provider(provider)
            mode = "bot_webhook" if provider.use_bot_fallback else "app_message"
            logger.info(
                "im.provider.registered",
                extra={"provider": "wecom", "mode": mode},
            )
        except (ValueError, ImportError) as e:
            # ValueError：凭据组合非法（不应发生 — has_wecom 已校验）
            # ImportError：wechatpy 未安装
            logger.warning(
                "im.provider.register_failed",
                extra={"provider": "wecom", "error": str(e)},
            )


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
    debug=True,
    lifespan=lifespan,
)

# Set all CORS enabled origins
# if settings.BACKEND_CORS_ORIGINS:
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True, log_level="debug")
