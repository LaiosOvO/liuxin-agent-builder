"""数据库层：AsyncEngine + session 依赖 + WorkspaceScopedQuery + DISCARD ALL hook。

对外导出：
- engine: AsyncEngine 单例
- async_session_maker: async_sessionmaker
- get_db: FastAPI 依赖，yield AsyncSession
- WorkspaceScopedQuery: 多租户查询抽象
- current_workspace_ctx: ContextVar
- register_discard_all_hook: hook 注册函数
"""
from app.agent_builder.db.engine import async_session_maker, engine
from app.agent_builder.db.scoped_query import WorkspaceScopedQuery, current_workspace_ctx
from app.agent_builder.db.session import get_db
from app.agent_builder.db.checkout_hook import register_discard_all_hook

__all__ = [
    "engine",
    "async_session_maker",
    "get_db",
    "WorkspaceScopedQuery",
    "current_workspace_ctx",
    "register_discard_all_hook",
]
