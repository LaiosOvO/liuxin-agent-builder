"""HITL jti 黑名单存储 — Redis 加速 + Postgres 权威。

设计参考 docs/reading-dify-03-01-hitl-schema-2026-05-17.md：
- Postgres 是权威存储（hitl_tokens.used_at IS NULL 表示未消费）
- Redis 是加速缓存（SET NX agent_builder:jti:<id> 24h）
- check 顺序：Redis hit → True；miss → 查 PG → 命中则回填 Redis

CLAUDE.md 2.5 GET 不消费 jti：
- consume() 仅由 POST /hitl/action 路径调用
- GET /hitl/page 路径只检 is_consumed() 不写 used_at

并发安全：
- `UPDATE ... WHERE jti=? AND used_at IS NULL RETURNING *` 零行返回 = 已被消费
- 两个并发请求拿同一 jti，Postgres 行锁保证仅一个 UPDATE 成功
- AUTH-05 一次性消费由 Postgres 行锁兜底，Redis 仅做读加速

不变性（CLAUDE.md 全局规则 Immutability）：
- 方法返回新对象（HitlToken 或 None）；不 mutate 入参
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_builder.models.hitl_token import HitlToken

log = logging.getLogger(__name__)

# Redis key 前缀 + TTL（与 token expires_at 24h 默认值对齐）
_REDIS_PREFIX = "agent_builder:jti:"
_REDIS_TTL_SECONDS = 86400  # 24h


def _redis_key(jti: UUID) -> str:
    """构造 Redis key（中央化避免分散字符串拼接）。"""
    return f"{_REDIS_PREFIX}{jti}"


class HitlTokenStore:
    """HITL jti 一次性消费 + 黑名单存储。

    实例化建议（依赖注入）：
        async def get_hitl_token_store(
            db: AsyncSession = Depends(get_db_session),
            redis: Redis = Depends(get_redis),
        ) -> HitlTokenStore:
            return HitlTokenStore(db=db, redis=redis)
    """

    def __init__(self, db: AsyncSession, redis: Redis) -> None:
        """构造函数。

        Args:
            db: SQLAlchemy AsyncSession（权威存储）
            redis: redis.asyncio.Redis 客户端（加速缓存）
        """
        self.db = db
        self.redis = redis

    async def is_consumed(self, jti: UUID) -> bool:
        """检查 jti 是否已消费（Redis-first，miss 回查 PG）。

        调用路径：
        1. GET /hitl/page/<token>（仅查不写）
        2. POST /hitl/action/<token>（先查，再走 consume() 原子消费）

        Args:
            jti: token 的 jti claim（UUID）

        Returns:
            True = 已消费 / 不存在；False = 未消费可继续

        Notes:
            未找到 token 行也视为"已消费"语义（防止非法 jti 通过 None 漏过校验）。
            这与 consume() 零行返回 None 语义一致。
        """
        key = _redis_key(jti)

        # 1. Redis 缓存层（hot path）
        if await self.redis.exists(key):
            return True

        # 2. Redis miss → 查 Postgres 权威
        result = await self.db.execute(
            select(HitlToken.used_at).where(HitlToken.jti == jti)
        )
        row = result.one_or_none()

        if row is None:
            # token 不存在（伪造 jti 或已被删除）→ 视为已消费
            return True

        used_at = row[0]
        if used_at is not None:
            # PG 显示已消费 → 回填 Redis 加速后续查询
            await self.redis.set(key, "consumed", ex=_REDIS_TTL_SECONDS)
            return True

        # 真正未消费
        return False

    async def consume(
        self,
        jti: UUID,
        ip: str | None = None,
        ua: str | None = None,
    ) -> HitlToken | None:
        """原子消费 jti：UPDATE ... WHERE used_at IS NULL RETURNING *。

        AUTH-05 一次性消费 + Pitfall 2 防护：
        - Postgres 行锁保证两个并发请求仅一个 UPDATE 成功（RETURNING 1 行）
        - 落败请求 RETURNING 0 行 → 返回 None

        Args:
            jti: token 的 jti claim
            ip: 客户端 IP（写入 used_ip 审计字段）
            ua: 客户端 User-Agent（写入 used_ua 审计字段）

        Returns:
            HitlToken：成功消费（首次提交）
            None：已被消费 / 不存在（重复提交 / 伪造 jti）

        Notes:
            调用方负责事务管理（commit/rollback）。
            建议外层包裹 pg_advisory_xact_lock(thread_id_hash) 防 interrupt/resume 竞态。
        """
        now = datetime.now(timezone.utc)

        stmt = (
            update(HitlToken)
            .where(HitlToken.jti == jti, HitlToken.used_at.is_(None))
            .values(used_at=now, used_ip=ip, used_ua=ua)
            .returning(HitlToken)
        )
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()

        if row is not None:
            # PG 成功消费 → 同步设 Redis 加速后续 is_consumed 查询
            await self.redis.set(
                _redis_key(jti),
                "consumed",
                ex=_REDIS_TTL_SECONDS,
            )
            log.info("hitl_token.consumed jti=%s ip=%s", jti, ip)

        return row

    async def invalidate_siblings(
        self,
        node_state_id: UUID,
        except_jti: UUID,
    ) -> int:
        """同 node_state_id 下其他未消费 token 批量失效（HITL-01 防重复决策）。

        典型场景：
        - 执行人收到邮件，submit / return / reject 3 个 token
        - 用户点击 submit → 同时把 return / reject 两个 token 标记为已消费
        - 防止用户事后又点 return 触发二次决策

        Args:
            node_state_id: 节点状态 UUID
            except_jti: 排除的 jti（刚被合法消费的那一个，不要再标记）

        Returns:
            被失效的 token 数量（典型 0~2）

        Notes:
            used_ip 写入 "system:sibling-invalidate" 标识系统级失效（与真实用户消费区分）；
            used_ua 留 NULL（系统无 UA 概念）。
        """
        now = datetime.now(timezone.utc)

        stmt = (
            update(HitlToken)
            .where(
                HitlToken.node_state_id == node_state_id,
                HitlToken.jti != except_jti,
                HitlToken.used_at.is_(None),
            )
            .values(
                used_at=now,
                used_ip="system:sibling-invalidate",
            )
            .returning(HitlToken.jti)
        )
        result = await self.db.execute(stmt)
        invalidated_jtis = list(result.scalars().all())

        if invalidated_jtis:
            # Redis pipeline 批量设置
            async with self.redis.pipeline(transaction=False) as pipe:
                for jti in invalidated_jtis:
                    pipe.set(_redis_key(jti), "consumed", ex=_REDIS_TTL_SECONDS)
                await pipe.execute()

            log.info(
                "hitl_token.siblings_invalidated count=%d node_state_id=%s except=%s",
                len(invalidated_jtis),
                node_state_id,
                except_jti,
            )

        return len(invalidated_jtis)
