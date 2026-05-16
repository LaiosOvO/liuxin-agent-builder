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

    # 可直接调用 hook 函数（测试用）：
    from app.agent_builder.db.checkout_hook import discard_all
    discard_all(mock_conn, None, None)
"""
from __future__ import annotations

import logging

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


def discard_all(dbapi_conn, conn_record, conn_proxy) -> None:  # type: ignore[no-untyped-def]
    """每次连接从池中取出时执行 DISCARD ALL。

    作为顶层函数导出，便于单元测试直接调用和 spy。

    注意：DISCARD ALL 不能在事务块内执行。
    asyncpg 的 SQLAlchemy 适配器（AsyncAdapt_asyncpg_connection）支持通过
    _connection._Connection__transaction 检测事务状态，或使用 `SET` 替代方案。

    Args:
        dbapi_conn: 底层 DBAPI 连接（asyncpg 同步适配器包装）
        conn_record: SQLAlchemy 连接记录对象
        conn_proxy: SQLAlchemy 连接代理对象
    """
    try:
        # asyncpg 适配器的同步连接需要在事务外执行 DISCARD ALL
        # 检查是否在事务中，如果在则先 ROLLBACK
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("DISCARD ALL")
        except Exception:
            # DISCARD ALL 在事务内失败时，先 ROLLBACK 再重试
            try:
                cursor.execute("ROLLBACK")
                cursor.execute("DISCARD ALL")
            except Exception as rollback_exc:
                logger.warning("DISCARD ALL（含 ROLLBACK）执行失败：%s", rollback_exc)
                cursor.close()
                return
        cursor.close()
        logger.debug("DISCARD ALL 执行成功（连接从池取出）")
    except Exception as exc:
        # 记录错误但不阻断连接借出（fail-open for connection，fail-close for auth）
        logger.warning("DISCARD ALL 执行失败：%s", exc)


def register_discard_all_hook(engine: AsyncEngine) -> None:
    """在 AsyncEngine 的底层同步引擎上注册 checkout hook。

    AsyncEngine 内部持有一个 sync_engine，checkout 事件在同步层触发。
    重复注册是幂等的（SQLAlchemy 同一 listener 只注册一次）。
    """
    event.listen(engine.sync_engine, "checkout", discard_all)
