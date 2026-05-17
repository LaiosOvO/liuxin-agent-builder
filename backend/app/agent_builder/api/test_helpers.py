"""测试辅助 API 端点 — 仅 ENABLE_TEST_API=1 时挂载（Plan 04-12）。

设计动机：
- E2E spec 需要观察后端内部状态（MockIMProvider.calls / hitl_tokens.used_at）
- 不通过 ORM 查询（避免 spec 进程持有 DB 连接复杂性）
- 通过 HTTP endpoint 暴露读取接口（spec 用 httpx 调）

安全约束：
- 必须仅在测试环境挂载（main.py 通过 os.environ['ENABLE_TEST_API']=='1' 控制）
- 生产环境绝对不能挂载（会泄露 mock 状态 + bypass 鉴权）
- 路由前缀 /api/test 便于 nginx 黑名单（双层防御）

提供 endpoints（4 个）：
- GET  /api/test/im_mock_calls?provider=X      — 返回 MockIMProvider 调用记录
- POST /api/test/im_mock_clear?provider=X      — 清空指定 provider 的 mock 记录（或全部）
- GET  /api/test/hitl_tokens?jti=X             — 返回 hitl_token.used_at 状态（Safe Links 回归）
- GET  /api/test/audit_logs?action=X&limit=N   — 返回最近的 audit_log 行（委托/升级回归）

CLAUDE.md immutability：
- 响应都是新 dict（不返回 ORM 对象）
- 不在 endpoint 内修改任何业务表
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_builder.api.deps import get_db
from app.agent_builder.models.audit_log import AuditLog
from app.agent_builder.models.hitl_token import HitlToken

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/test", tags=["test-helpers"])


# ── IM Mock Provider 状态查询 ────────────────────────────────────────────────


@router.get("/im_mock_calls")
async def get_im_mock_calls(
    provider: str = Query(..., description="Provider 名（feishu/wecom/dingtalk/slack/mattermost/webhook）"),
) -> list[dict[str, Any]]:
    """获取指定 IM Provider 的 mock 调用记录。

    返回的每条记录包含：
    - method: 'send_hitl_card' / 'update_card' / 'send_supplement_text'
    - recipient: IM 用户 ID（或空字符串 — update_card 场景）
    - payload: dict 调用参数快照

    Raises:
        404: Provider 未注册
        409: Provider 不是 MockIMProvider 实例（生产 Provider 不暴露 calls）
    """
    from app.agent_builder.notification.providers.base import get_provider
    from app.agent_builder.notification.providers.mock import MockIMProvider

    try:
        prov = get_provider(provider)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider '{provider}' 未注册",
        ) from exc

    if not isinstance(prov, MockIMProvider):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Provider '{provider}' 不是 MockIMProvider — 仅测试 mock 可暴露 calls",
        )

    # 返回 mock 调用记录的快照（frozen dataclass 转 dict）
    return [
        {
            "method": call.method,
            "recipient": call.recipient,
            "payload": call.payload,
        }
        for call in prov.calls
    ]


@router.post("/im_mock_clear")
async def clear_im_mock_calls(
    provider: str = Query(
        ..., description="Provider 名；传 'all' 清空所有 Mock Provider"
    ),
) -> dict[str, Any]:
    """清空指定 Mock Provider 的调用记录（spec 之间隔离用）。

    Args:
        provider: Provider 名；传 'all' 清空所有 Mock Provider

    Returns:
        {"cleared": ["feishu", "wecom", ...], "count": N}
    """
    from app.agent_builder.notification.providers.base import list_providers, get_provider
    from app.agent_builder.notification.providers.mock import MockIMProvider

    cleared: list[str] = []
    if provider == "all":
        for name in list_providers():
            prov = get_provider(name)
            if isinstance(prov, MockIMProvider):
                prov.reset()
                cleared.append(name)
    else:
        try:
            prov = get_provider(provider)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Provider '{provider}' 未注册",
            ) from exc
        if not isinstance(prov, MockIMProvider):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Provider '{provider}' 不是 MockIMProvider",
            )
        prov.reset()
        cleared.append(provider)

    return {"cleared": cleared, "count": len(cleared)}


# ── HitlToken 状态查询（Safe Links 回归测试 P0）────────────────────────────


@router.get("/hitl_tokens")
async def get_hitl_token_status(
    jti: str = Query(..., description="JWT jti claim（UUID）"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """查询 hitl_token 的 used_at 状态（验证 GET 不消费 jti — CLAUDE.md §2.5 P0）。

    用于 Safe Links bot regression spec：
    - bot UA GET 后查 used_at 必须为 None
    - 真实用户 POST 后查 used_at 必须不为 None

    Returns:
        {"jti": str, "used_at": str|None, "consumed": bool, "exists": bool}

    Raises:
        422: jti 不是合法 UUID
    """
    try:
        jti_uuid = UUID(jti)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"jti '{jti}' 不是合法 UUID",
        ) from exc

    result = await db.execute(select(HitlToken).where(HitlToken.jti == jti_uuid))
    token = result.scalar_one_or_none()

    if token is None:
        return {
            "jti": jti,
            "used_at": None,
            "consumed": False,
            "exists": False,
        }

    return {
        "jti": jti,
        "used_at": token.used_at.isoformat() if token.used_at else None,
        "consumed": token.used_at is not None,
        "exists": True,
        "used_ip": token.used_ip,
        "used_ua": token.used_ua,
    }


# ── AuditLog 查询（委托 / 升级回归用）────────────────────────────────────


@router.get("/audit_logs")
async def get_recent_audit_logs(
    action: str | None = Query(None, description="按 action 过滤（如 hitl.delegate / hitl.escalate）"),
    instance_id: str | None = Query(None, description="按 instance_id 过滤"),
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """查询最近的 audit_log 行（spec 用于断言副作用已落库）。

    返回字段（避免暴露脱敏字段 — 测试场景不限制）：
    - id, created_at, action, actor_id, workspace_id
    - target_type, target_id
    - meta (JSONB)
    - ip, user_agent
    """
    stmt = select(AuditLog).order_by(desc(AuditLog.id)).limit(limit)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if instance_id:
        try:
            inst_uuid = UUID(instance_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"instance_id '{instance_id}' 不是合法 UUID",
            ) from exc
        # AuditLog 没有 instance_id 列，通过 meta JSONB 过滤
        stmt = stmt.where(AuditLog.meta["instance_id"].astext == str(inst_uuid))

    result = await db.execute(stmt)
    rows = result.scalars().all()

    return [
        {
            "id": int(row.id),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "action": row.action,
            "actor_user_id": str(row.actor_user_id) if row.actor_user_id else None,
            "actor_meta": dict(row.actor_meta) if row.actor_meta else {},
            "workspace_id": str(row.workspace_id) if row.workspace_id else None,
            "target_type": row.target_type,
            "target_id": str(row.target_id) if row.target_id else None,
            "meta": dict(row.meta) if row.meta else {},
            "ip": row.ip,
            "user_agent": row.user_agent,
            "actor_ip": getattr(row, "actor_ip", None),
            "actor_ua": getattr(row, "actor_ua", None),
            "decision": getattr(row, "decision", None),
        }
        for row in rows
    ]


# ── 健康检查（确认 test_helpers 已挂载）────────────────────────────────


@router.get("/ping")
async def ping() -> dict[str, str]:
    """spec 用于探测 test_helpers 路由是否成功挂载。"""
    return {"status": "ok", "module": "test_helpers"}
