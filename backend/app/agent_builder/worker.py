"""arq worker 入口（Phase 2 引入，Phase 1 不含此文件）。

启动命令：
    arq app.agent_builder.worker.WorkerSettings

功能：
- run_instance_arq：接收 arq 任务，调用 workflow.runner.run_instance
- WorkerSettings：arq worker 配置（Redis 连接 / 注册函数 / keep_result）

重启恢复：
- worker 启动时（on_startup hook）调用 ExecutionEngine.restart_pending_instances_on_startup
- LangGraph AsyncPostgresSaver checkpoint 自动从断点续跑

设计决策：
- 使用 arq 0.28+（CLAUDE.md 技术栈锁定）
- REDIS_URL 环境变量配置（与 Redis pub/sub 共用同一个 Redis 实例）
- keep_result = 3600（秒）：任务结果保留 1 小时用于调试
"""
from __future__ import annotations

import logging
import os
from uuid import UUID

logger = logging.getLogger(__name__)


async def run_instance_arq(ctx: dict, instance_id: str) -> None:
    """arq worker 入口函数。

    接收 arq 分发的任务，转调 runner.run_instance。

    Args:
        ctx: arq worker 上下文（含 redis 连接等）
        instance_id: 流程实例 UUID 字符串
    """
    from app.agent_builder.workflow.runner import run_instance

    logger.info("arq: 开始执行实例 %s", instance_id)
    await run_instance(UUID(instance_id))
    logger.info("arq: 实例 %s 执行完毕", instance_id)


async def on_startup(ctx: dict) -> None:
    """Worker 启动时：恢复 pending/running 实例。

    扫描 flow_instances WHERE status IN ('pending', 'running')，
    逐个重新 enqueue（LangGraph 内部从 checkpoint 续跑）。
    """
    logger.info("arq worker on_startup: 检查未完成实例...")
    try:
        from app.agent_builder.db.engine import async_session_maker
        from app.agent_builder.workflow.execution_engine import ExecutionEngine
        from app.agent_builder.workflow.redis_client import get_redis

        redis = get_redis()
        async with async_session_maker() as db:
            engine = ExecutionEngine(db=db, redis=redis, arq_pool=ctx.get("redis"))
            count = await engine.restart_pending_instances_on_startup()

        logger.info("arq worker on_startup: 重新提交 %d 个未完成实例", count)
    except Exception as exc:
        logger.warning("arq worker on_startup: 实例恢复失败（不阻断 worker 启动）: %s", exc)


class WorkerSettings:
    """arq worker 配置。

    配置项：
    - functions：注册的任务函数列表
    - redis_settings：从 REDIS_URL env 读取（默认 redis://localhost:6379/0）
    - keep_result：任务结果保留秒数（调试用）
    - on_startup：启动钩子（恢复未完成实例）
    """
    from arq.connections import RedisSettings

    functions = [run_instance_arq]
    on_startup = on_startup
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    )
    keep_result = 3600
