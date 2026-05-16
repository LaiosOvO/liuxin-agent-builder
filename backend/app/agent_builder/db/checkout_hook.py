"""DISCARD ALL checkout hook（防 Pitfall 6 PgBouncer session mode 上下文污染）。

每次从连接池借出连接时执行 DISCARD ALL，清空：
- session 级变量（SET xxx）
- 临时表（TEMP TABLE）
- 预准备语句（PREPARE）
- advisory locks（pg_advisory_lock）

参考：PITFALLS.md Pitfall 6 / CVE-2024-10976 类似场景。

用法：
    from app.agent_builder.db.checkout_hook import register_discard_all_hook
    register_discard_all_hook(engine)  # engine 为 AsyncEngine
"""
from __future__ import annotations

import logging

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


def register_discard_all_hook(engine: AsyncEngine) -> None:
    """在 AsyncEngine 的底层同步引擎上注册 checkout hook。

    AsyncEngine 内部持有一个 sync_engine，checkout 事件在同步层触发。
    """

    @event.listens_for(engine.sync_engine, "checkout")
    def discard_all(dbapi_conn, conn_record, conn_proxy) -> None:  # type: ignore[no-untyped-def]
        """每次连接从池中取出时执行 DISCARD ALL。

        参数均为 SQLAlchemy 内部参数，直接透传不使用。
        dbapi_conn: 底层 DBAPI 连接（asyncpg 在同步包装器中）
        conn_record: 连接记录对象
        conn_proxy: 连接代理对象
        """
        try:
            cursor = dbapi_conn.cursor()
            cursor.execute("DISCARD ALL")
            cursor.close()
            logger.debug("DISCARD ALL 执行成功（连接从池取出）")
        except Exception as exc:
            # 记录错误但不阻断连接借出（fail-open for connection，fail-close for auth）
            logger.warning("DISCARD ALL 执行失败：%s", exc)
