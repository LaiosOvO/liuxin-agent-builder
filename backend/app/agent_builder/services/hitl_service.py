"""HITL 业务逻辑层（Plan 03-02 + 04-02 chain + 04-03 委托 + 04-11 节点 enter）。

被 HITLNodeExecutor + 03-06 API + 03-09 超时催办 worker + 04-02 chain executor +
04-03 委托 API + 04-11 ExecutionEngine._on_hitl_enter 复用。

职责：
- batch_create_tokens：节点 enter 时为 actor 每个 allowed_action 写一行 hitl_tokens
- batch_create_tokens_for_actors：Phase 4 chain 模式批量为多个 actor 创建 token
- resolve_allowed_actions：根据 phase 计算允许的 action 列表
- create_delegate_token：审批人委托给同事（HITL-06，Plan 04-03 新增）
- resolve_assignees：解析 DSL node_def.config.assignees 表达式列表为 UUID 列表（Plan 04-11 新增）

设计参考 docs/reading-dify-03-02-hitl-executor-2026-05-17.md §4.6
+ docs/reading-dify-04-03-delegation-2026-05-17.md
+ docs/reading-dify-04-11-hitl-node-chain-2026-05-17.md：
- Dify HumanInputFormRecipient 1:N（一个 form 多个 recipient）→ 我们用 hitl_tokens
  一对一行（每 actor × action 一行），简化但保留审计能力
- Dify **无委托特性** — 委托是本项目独立设计（reading doc 已验证）
- assignees 4 表达式 router 与 EscalationService 一致（email / user: / role: / dept:）
  但语义不同：assignees 是节点配置（who can decide），escalation_to 是 timeout 升级配置
  → 在 HitlService 中独立实现 resolve_assignees，避免误复用 EscalationService 内部逻辑
- 未拷贝 Dify 源码，仅借鉴 token 表设计 + 一次性消费模式

CLAUDE.md 2.4 多租户：
- batch_create_tokens 不直接接收 workspace_id，由 instance_id FK 链路保证
- create_delegate_token 强制校验 to_email 在同 workspace 内（不可跨租户委托）
- resolve_assignees 强制 workspace_id 过滤 user / role 查询（防越权拿其他 ws 用户）
- 调用方（03-06 API / HITLNodeExecutor / 04-03 委托 API / 04-11 enter 钩子）须确保
  instance_id 属于当前 workspace

CLAUDE.md immutability:
- 本 service 写 DB 但不修改入参 dict（actor list 不变）
- create_delegate_token 用 {**payload, ...} 构造新 payload 后赋值，不原地 mutate
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_builder.models.flow_instance import FlowInstance
from app.agent_builder.models.hitl_token import HitlToken
from app.agent_builder.models.node_state import NodeState
from app.agent_builder.models.role import Role
from app.agent_builder.models.user import User
from app.agent_builder.models.user_workspace_role import UserWorkspaceRole

logger = logging.getLogger(__name__)

# ── 默认值 ────────────────────────────────────────────────────────────────────

DEFAULT_TOKEN_EXPIRES_IN: Final[int] = 86400  # 24h（与 03-CONTEXT.md §Deadline 一致）

# 委托链深度上限（CONTEXT.md §委托机制 HITL-06：防责任稀释 + 防委托环）
MAX_DELEGATION_DEPTH: Final[int] = 3

# Phase → allowed actions 映射（CONTEXT.md §Token 4-action 设计）
_ALLOWED_ACTIONS_BY_PHASE: Final[dict[str, list[str]]] = {
    "submit": ["submit", "return", "reject"],
    "review": ["approve", "return", "reject"],
}

# 委托被委托人继承的 action 集合（沿用 review phase 三按钮）
_DELEGATE_ACTIONS: Final[tuple[str, ...]] = ("approve", "return", "reject")


# ── 业务异常类（API 层据此差异化错误响应） ─────────────────────────────────────


class DelegateError(Exception):
    """委托业务异常基类（Plan 04-03）。

    Attributes:
        code: 错误码（用于 API 层 HTTP 状态映射）：
            - 'depth_exceeded': 委托链已超 MAX_DELEGATION_DEPTH 层 → 409
            - 'self_delegate': 不能委托给自己 → 422
            - 'circular': 被委托人已在审批链内（防环） → 422
            - 'recipient_not_found': 被委托人不存在或跨 workspace → 422
            - 'cross_workspace': 显式跨租户语义保留（与 recipient_not_found 合并防泄漏）→ 422
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


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

    async def create_delegate_token(
        self,
        *,
        from_user: User,
        to_email: str,
        reason: str,
        node_state: NodeState,
        flow_instance: FlowInstance,
        ip: str,
        ua: str,
        timeout_seconds: int = DEFAULT_TOKEN_EXPIRES_IN,
    ) -> tuple[list[HitlToken], int]:
        """委托当前 actor 的待决策 token 给 to_email 用户（HITL-06，Plan 04-03）。

        本方法只负责：创建被委托人的新 token + 写 records / approval_chain.delegated。
        **不消费原 token** — 由调用方（API 层）在 advisory_lock 内的 HitlTokenStore.consume 完成。

        校验链（顺序敏感）：
        1. 委托链深度 ≤ MAX_DELEGATION_DEPTH（DelegateError 'depth_exceeded'）
        2. to_email 用户存在 + 同 workspace + status='active'（DelegateError 'recipient_not_found'）
        3. to_email != from_user.email（DelegateError 'self_delegate'）
        4. to_user.id 不在 approval_chain.approvers 内（DelegateError 'circular'）

        副作用（外层 advisory_lock 内事务）：
        1. 创建 3 行新 token（approve/return/reject）给被委托人 — jti 新生成，
           deadline_at = now + timeout_seconds（**重置**，不继承原 deadline）
        2. 更新 node_state.payload.records（追加 type=delegate 一条）
        3. 更新 node_state.payload.approval_chain.delegated[from_user.id] = {to, depth}

        Args:
            from_user: 发起委托的当前 actor（已经登录 / 持有原 token）
            to_email: 被委托人邮箱（CITEXT 大小写不敏感匹配）
            reason: 委托原因（API 层校验非空 + ≤ 500 字符）
            node_state: 当前 HITL 节点状态 ORM 行（调用方需 load）
            flow_instance: 流程实例 ORM 行（拿 workspace_id 用于 to_user 同租户校验）
            ip: 发起委托请求的 client IP（写入 records.ip）
            ua: 发起委托请求的 User-Agent（写入 records.ua）
            timeout_seconds: 新 token 过期秒数（默认 24h；RESEARCH.md §三决策修正
                CONTEXT — deadline_at 重置而非继承）

        Returns:
            (new_tokens, depth)
            - new_tokens: 创建的 3 个 HitlToken ORM 实例（approve/return/reject）
            - depth: 本次委托后的委托链深度（用于 API 层 audit_log + 日志）

        Raises:
            DelegateError: 五种错误码之一（code 字段，API 层据此映射 HTTP 状态）
        """
        # ── 1. 委托链深度校验 ─────────────────────────────────────────────
        chain = (node_state.payload or {}).get("approval_chain") or {}
        delegated = chain.get("delegated") or {}
        prev_depth = (delegated.get(str(from_user.id)) or {}).get("depth", 0)
        new_depth = prev_depth + 1
        if new_depth > MAX_DELEGATION_DEPTH:
            raise DelegateError(
                "depth_exceeded",
                f"委托链已超 {MAX_DELEGATION_DEPTH} 层（防责任稀释 + 防委托环）",
            )

        # ── 2. 查 to_email 用户（同 workspace + status='active'）─────────
        # SQL JOIN user_workspace_roles 过滤同 workspace；防 tenant 存在性泄漏
        to_user_stmt = (
            select(User)
            .join(UserWorkspaceRole, UserWorkspaceRole.user_id == User.id)
            .where(
                User.email == to_email,
                UserWorkspaceRole.workspace_id == flow_instance.workspace_id,
                User.status == "active",
            )
            .limit(1)
        )
        to_user = (await self.db.execute(to_user_stmt)).scalar_one_or_none()
        if to_user is None:
            raise DelegateError(
                "recipient_not_found",
                f"被委托人 {to_email} 不在当前 workspace 内或已禁用",
            )

        # ── 3. 防自委托 ────────────────────────────────────────────────────
        if to_user.id == from_user.id:
            raise DelegateError("self_delegate", "不能委托给自己")

        # ── 4. 防环：被委托人不可已在审批链内 ─────────────────────────────
        approvers_str = chain.get("approvers") or []
        approvers_ids = {UUID(a) for a in approvers_str}
        if to_user.id in approvers_ids:
            raise DelegateError(
                "circular",
                f"{to_email} 已在审批链内（防委托环路）",
            )

        # ── 5. 创建 3 行新 token 给被委托人 ────────────────────────────────
        # deadline_at 重置（RESEARCH §三决策）— 被委托人新「上岗」，给完整窗口
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)
        new_tokens = [
            HitlToken(
                jti=uuid4(),
                instance_id=flow_instance.id,
                node_state_id=node_state.id,
                actor_id=to_user.id,
                action=action,
                expires_at=expires_at,
            )
            for action in _DELEGATE_ACTIONS
        ]
        self.db.add_all(new_tokens)
        await self.db.flush()

        # ── 6. 更新 node_state.payload（immutable — 构造新 dict 后赋值 ORM）─
        old_payload = node_state.payload or {}
        now_iso = datetime.now(timezone.utc).isoformat()
        delegate_record = {
            "actor_id": str(from_user.id),
            "actor_email": from_user.email,
            "action": "delegate",
            "reason": reason,
            "form_data": {},
            "ts": now_iso,
            "ip": ip,
            "ua": ua,
            "delegate_to_id": str(to_user.id),
            "delegate_to_email": to_email,
            "depth": new_depth,
        }
        new_chain = {
            **chain,
            "delegated": {
                **delegated,
                str(from_user.id): {
                    "to": str(to_user.id),
                    "depth": new_depth,
                },
            },
        }
        new_payload = {
            **old_payload,
            "records": [*(old_payload.get("records") or []), delegate_record],
            "approval_chain": new_chain,
        }
        # ORM 赋值（SQLAlchemy 会在 commit 时持久化）
        node_state.payload = new_payload

        return new_tokens, new_depth

    # ── Plan 04-11: resolve_assignees 4 表达式路由 ────────────────────────────

    async def resolve_assignees(
        self,
        assignees: list[str],
        workspace_id: UUID,
    ) -> list[UUID]:
        """解析 DSL node_def.config.assignees 表达式列表为 user_id UUID 列表（Plan 04-11）。

        支持 4 种表达式（与 EscalationService.resolve_escalate_to 一致 — Phase 4 04-04）：
        - email:user@example.com 或 user@example.com — Phase 3 兼容
        - user:<uuid> — 单用户 UUID
        - role:<code> — 工作区内角色全部用户（如 admin / editor / viewer）
        - dept:<name> — **Phase 5 实现**（IM 目录同步后），目前抛 NotImplementedError

        Args:
            assignees: DSL 配置中的 assignees 列表（如 ["alice@example.com", "role:admin"]）
            workspace_id: 工作区 UUID（防越权拿其他 ws 用户）

        Returns:
            list[UUID] 去重后的用户 UUID 列表（保持原始 assignees 顺序，但去除重复）；
            空列表表示无法解析任何 assignee（调用方应抛 NodeExecutionError）

        Raises:
            NotImplementedError: dept: 表达式（Phase 5 IM 目录同步后实现）

        Notes:
            - 同一 user_id 在多个表达式中出现时（如 alice@x 也在 role:admin 中）只保留一次
            - 顺序按首次出现顺序保留（防 sequential 模式 approvers[0] 不确定）
            - email 解析失败（用户不存在 / 跨 workspace / inactive）→ log warning + skip
            - user:<uuid> 解析失败 → log warning + skip
            - role:<code> 无匹配用户 → log warning + skip (不抛错 — 与 escalation 一致)
        """
        if not assignees:
            return []

        seen: set[UUID] = set()
        result: list[UUID] = []

        for expr in assignees:
            if not isinstance(expr, str):
                logger.warning("resolve_assignees: 跳过非字符串表达式 %r", expr)
                continue
            expr = expr.strip()
            if not expr:
                continue

            # dept: → Phase 5
            if expr.startswith("dept:"):
                raise NotImplementedError(
                    f"dept: 表达式（{expr}）将于 Phase 5（IM 目录双向同步）实现"
                )

            # user:<uuid>
            if expr.startswith("user:"):
                uid_raw = expr[5:].strip()
                try:
                    uid = UUID(uid_raw)
                except ValueError:
                    logger.warning(
                        "resolve_assignees: 非法 user: 表达式 %r（UUID parse 失败）", expr,
                    )
                    continue
                resolved = await self._resolve_user_uuid(uid, workspace_id)
                if resolved is None:
                    logger.warning(
                        "resolve_assignees: user:%s 在 workspace %s 未找到 active 用户",
                        uid, workspace_id,
                    )
                    continue
                if resolved not in seen:
                    seen.add(resolved)
                    result.append(resolved)
                continue

            # role:<code>
            if expr.startswith("role:"):
                role_code = expr[5:].strip()
                role_uuids = await self._resolve_role_uuids(role_code, workspace_id)
                if not role_uuids:
                    logger.warning(
                        "resolve_assignees: role:%s 在 workspace %s 未匹配任何 active 用户",
                        role_code, workspace_id,
                    )
                    continue
                for uid in role_uuids:
                    if uid not in seen:
                        seen.add(uid)
                        result.append(uid)
                continue

            # email:<addr> 或裸 email (含 @ 且不含 :)
            if expr.startswith("email:"):
                email_addr = expr[6:].strip()
            elif "@" in expr and ":" not in expr:
                email_addr = expr
            else:
                logger.warning(
                    "resolve_assignees: 无法识别表达式 %r（合法：email / email:<addr> / user:<uuid> / role:<code> / dept:<name>）",
                    expr,
                )
                continue

            resolved = await self._resolve_email_uuid(email_addr, workspace_id)
            if resolved is None:
                logger.warning(
                    "resolve_assignees: email=%s 在 workspace %s 未找到 active 用户",
                    email_addr, workspace_id,
                )
                continue
            if resolved not in seen:
                seen.add(resolved)
                result.append(resolved)

        return result

    async def _resolve_user_uuid(
        self,
        user_id: UUID,
        workspace_id: UUID,
    ) -> UUID | None:
        """查 user_id 是否属于 workspace_id 且 active。

        多租户隔离：JOIN UserWorkspaceRole 强制 workspace_id 匹配。
        """
        stmt = (
            select(User.id)
            .join(UserWorkspaceRole, UserWorkspaceRole.user_id == User.id)
            .where(
                User.id == user_id,
                UserWorkspaceRole.workspace_id == workspace_id,
                User.status == "active",
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _resolve_email_uuid(
        self,
        email: str,
        workspace_id: UUID,
    ) -> UUID | None:
        """查 email 用户的 UUID（必须属于 workspace_id + active）。

        email 使用 CITEXT 大小写不敏感匹配（User.email 是 CITEXT 列）。
        """
        stmt = (
            select(User.id)
            .join(UserWorkspaceRole, UserWorkspaceRole.user_id == User.id)
            .where(
                User.email == email,
                UserWorkspaceRole.workspace_id == workspace_id,
                User.status == "active",
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _resolve_role_uuids(
        self,
        role_code: str,
        workspace_id: UUID,
    ) -> list[UUID]:
        """查 workspace 内具有 role_code 的所有 active 用户 UUID 列表。

        distinct() 防同一 user 多角色重复（PK 约束已防，distinct 是兜底）。
        """
        stmt = (
            select(User.id)
            .join(UserWorkspaceRole, UserWorkspaceRole.user_id == User.id)
            .join(Role, Role.id == UserWorkspaceRole.role_id)
            .where(
                UserWorkspaceRole.workspace_id == workspace_id,
                Role.code == role_code,
                User.status == "active",
            )
            .distinct()
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
