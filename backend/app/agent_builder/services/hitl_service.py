"""HITL 业务逻辑层（Plan 03-02）。

被 HITLNodeExecutor + 03-06 API + 03-09 超时催办 worker 复用。

职责：
- batch_create_tokens：节点 enter 时为 actor 每个 allowed_action 写一行 hitl_tokens
- resolve_allowed_actions：根据 phase 计算允许的 action 列表
- (Phase 后续：append_decision_record / resolve_current_actor / escalate)

设计参考 docs/reading-dify-03-02-hitl-executor-2026-05-17.md §4.6：
- Dify HumanInputFormRecipient 1:N（一个 form 多个 recipient）→ 我们用 hitl_tokens
  一对一行（每 actor × action 一行），简化但保留审计能力
- 未拷贝 Dify 源码，仅借鉴 token 表设计

CLAUDE.md 2.4 多租户：
- batch_create_tokens 不直接接收 workspace_id，由 instance_id FK 链路保证
- 调用方（03-06 API / HITLNodeExecutor）须确保 instance_id 属于当前 workspace

CLAUDE.md immutability:
- 本 service 写 DB 但不修改入参 dict（actor list 不变）
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_builder.models.hitl_token import HitlToken

# ── 默认值 ────────────────────────────────────────────────────────────────────

DEFAULT_TOKEN_EXPIRES_IN: Final[int] = 86400  # 24h（与 03-CONTEXT.md §Deadline 一致）

# Phase → allowed actions 映射（CONTEXT.md §Token 4-action 设计）
_ALLOWED_ACTIONS_BY_PHASE: Final[dict[str, list[str]]] = {
    "submit": ["submit", "return", "reject"],
    "review": ["approve", "return", "reject"],
}


class HitlService:
    """HITL 业务逻辑层。

    用法：
        service = HitlService(db)
        tokens = await service.batch_create_tokens(
            instance_id=..., node_state_id=..., actor_id=...,
            allowed_actions=service.resolve_allowed_actions("submit"),
        )
        # tokens 是 list[HitlToken]，已 flush 但未 commit（外层事务管理）
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def batch_create_tokens(
        self,
        *,
        instance_id: UUID,
        node_state_id: UUID,
        actor_id: UUID,
        allowed_actions: list[str],
        expires_in_seconds: int = DEFAULT_TOKEN_EXPIRES_IN,
    ) -> list[HitlToken]:
        """为 actor 批量生成 hitl_tokens 行（每个 allowed_action 一行）。

        Args:
            instance_id: 流程实例 UUID
            node_state_id: 节点状态 UUID
            actor_id: 决策人 user_id
            allowed_actions: 允许的 action 字符串列表（如 ['submit','return','reject']）
            expires_in_seconds: token 过期秒数（默认 24h）

        Returns:
            list[HitlToken]（已 add_all + flush，未 commit）

        Notes:
            - 每行有独立 jti（uuid4），不可冲突
            - 调用方负责 commit（保持事务可组合）
            - allowed_actions 不应包含重复元素（service 层不校验，由 schema 层保证）
        """
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)
        tokens = [
            HitlToken(
                jti=uuid4(),
                instance_id=instance_id,
                node_state_id=node_state_id,
                actor_id=actor_id,
                action=action,
                expires_at=expires_at,
            )
            for action in allowed_actions
        ]
        self.db.add_all(tokens)
        # flush 让 server defaults（created_at）生效但不 commit
        # 外层事务管理：API handler / ExecutionEngine 决定何时 commit
        await self.db.flush()
        return tokens

    async def batch_create_tokens_for_actors(
        self,
        *,
        instance_id: UUID,
        node_state_id: UUID,
        actor_ids: list[UUID],
        allowed_actions: list[str],
        expires_in_seconds: int = DEFAULT_TOKEN_EXPIRES_IN,
    ) -> list[HitlToken]:
        """批量为多个 actor 创建 hitl_tokens 行（Phase 4 chain 模式入口）。

        典型场景（决策依据 04-CONTEXT.md §审批链 4 模式语义）：
        - sequential approve 推进：next_approvers=[B]，给 B 每 allowed_action 一行 token
        - parallel_all / parallel_any 初始化：approvers=[A, B, C]，每人都收到 N 个 action token

        Args:
            instance_id: 流程实例 UUID
            node_state_id: 节点状态 UUID
            actor_ids: 待创建 token 的 actor UUID 列表（可为空 list → 返回空 list）
            allowed_actions: 允许的 action 字符串列表（如 ['approve', 'return', 'reject']）
            expires_in_seconds: token 过期秒数（默认 24h）

        Returns:
            list[HitlToken]，长度 == len(actor_ids) × len(allowed_actions)
            已 add_all + flush（未 commit；外层事务管理）

        Notes:
            - 与 `batch_create_tokens`（单 actor）的区别：本方法接受 list[actor_id] 笛卡尔积展开
            - 所有 token 共享同一 expires_at（同一批次）
            - 每个 (actor, action) 一行 token，独立 jti
            - actor_ids 为空时返回空 list（不抛错）— 调用方按需检查
            - 调用方负责 commit（保持事务可组合）
        """
        if not actor_ids:
            return []

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)
        tokens = [
            HitlToken(
                jti=uuid4(),
                instance_id=instance_id,
                node_state_id=node_state_id,
                actor_id=actor_id,
                action=action,
                expires_at=expires_at,
            )
            for actor_id in actor_ids
            for action in allowed_actions
        ]
        self.db.add_all(tokens)
        # flush 让 server defaults（created_at）生效但不 commit
        # 外层事务管理：API handler / HitlActionService 决定何时 commit
        await self.db.flush()
        return tokens

    async def resolve_allowed_actions(self, phase: str) -> list[str]:
        """根据 phase 计算允许的 action 列表（不带 self，但保留方法签名一致）。

        Phase 3 single 模式状态机：
            - phase=submit → [submit, return, reject]
            - phase=review → [approve, return, reject]

        Args:
            phase: 当前阶段（"submit" / "review"）

        Returns:
            list[str] 允许的 action（按邮件按钮渲染顺序）

        Raises:
            ValueError: 非法 phase
        """
        actions = _ALLOWED_ACTIONS_BY_PHASE.get(phase)
        if actions is None:
            raise ValueError(
                f"非法 phase={phase!r}（合法值：'submit' / 'review'，Phase 3 仅 single 模式）"
            )
        # 返回副本防止调用方误修改全局表
        return list(actions)
