"""JWT 签发与校验服务。

本 plan 涉及 3 类 JWT（全部 HS256，密钥 settings.JWT_SECRET）：
1. Session token（登录后 cookie）—— sub=user_id, ws=ws_id, exp=24h sliding, iat
2. Email verification token —— sub=user_id, jti=uuid, exp=24h, purpose='email_verification'
3. Invite token —— jti=uuid, workspace_id, email, target_role, exp=24h, purpose='invite'

jti 一次性消费规则（verification / invite；Session 不消费）：
- 通过 UPDATE ... SET used_at=NOW() WHERE jti=:jti AND used_at IS NULL RETURNING *
- 零行 → 已消费或不存在 → 抛 TokenAlreadyUsedError
- GET 验证页面不消费（只在 POST 落地时消费）
"""
from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, TypedDict

import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# ── 常量 ────────────────────────────────────────────────────────────────────────
ALGORITHM = "HS256"
SESSION_TTL_HOURS = 24
VERIFICATION_TTL_HOURS = 24
INVITE_TTL_HOURS = 24


def _get_jwt_secret() -> str:
    """运行时读取 JWT_SECRET（startup_checks 已保证存在且 ≥ 32 字节）。"""
    secret = os.environ.get("JWT_SECRET", "")
    if not secret:
        raise RuntimeError("JWT_SECRET 未配置，请检查 startup_checks")
    return secret


# ── 错误类型 ─────────────────────────────────────────────────────────────────────


class TokenInvalid(Exception):
    """JWT 签名无效或格式错误。"""


class TokenExpired(Exception):
    """JWT 已过期。"""


class TokenAlreadyUsedError(Exception):
    """jti 已被消费（一次性 token）。"""


class TokenPurposeMismatch(Exception):
    """JWT purpose 字段不符合预期。"""


# ── TypedDict 定义 ───────────────────────────────────────────────────────────────


class SessionClaims(TypedDict):
    """Session JWT payload。"""

    sub: str  # user_id（str 格式 UUID）
    ws: str  # workspace_id（str 格式 UUID）
    iat: int
    exp: int


class EmailVerificationClaims(TypedDict):
    """邮箱验证 JWT payload。"""

    sub: str  # user_id
    jti: str  # uuid
    workspace_id: str | None  # setup 阶段可为 None
    purpose: str  # "email_verification"
    iat: int
    exp: int


class InviteClaims(TypedDict):
    """邀请 JWT payload。"""

    jti: str  # uuid
    workspace_id: str
    email: str
    target_role: str
    invited_by: str  # user_id
    purpose: str  # "invite"
    iat: int
    exp: int


# ── 工具函数 ──────────────────────────────────────────────────────────────────────


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(token: str) -> str:
    """计算 token 的 SHA256 哈希（审计用，不存明文）。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ── Session Token ────────────────────────────────────────────────────────────────


def sign_session(
    user_id: uuid.UUID | str,
    workspace_id: uuid.UUID | str,
    ttl_hours: int = SESSION_TTL_HOURS,
) -> str:
    """签发 Session JWT（登录后存入 httpOnly cookie）。

    Args:
        user_id: 用户 ID
        workspace_id: 当前工作区 ID
        ttl_hours: 有效期小时数（默认 24h）

    Returns:
        签名后的 JWT 字符串
    """
    now = _now_utc()
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "ws": str(workspace_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=ttl_hours)).timestamp()),
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=ALGORITHM)


def decode_session(token: str) -> SessionClaims:
    """解码并校验 Session JWT。

    Args:
        token: JWT 字符串

    Returns:
        SessionClaims TypedDict

    Raises:
        TokenExpired: token 已过期
        TokenInvalid: token 无效（签名错误、格式错误等）
    """
    try:
        payload = jwt.decode(
            token,
            _get_jwt_secret(),
            algorithms=[ALGORITHM],
            options={"require": ["sub", "ws", "exp", "iat"]},
        )
        return SessionClaims(
            sub=payload["sub"],
            ws=payload["ws"],
            iat=payload["iat"],
            exp=payload["exp"],
        )
    except jwt.ExpiredSignatureError as e:
        raise TokenExpired("Session token 已过期") from e
    except jwt.PyJWTError as e:
        raise TokenInvalid(f"Session token 无效：{e}") from e


# ── Email Verification Token ─────────────────────────────────────────────────────


def sign_email_verification(
    user_id: uuid.UUID | str,
    workspace_id: uuid.UUID | str | None = None,
    ttl_hours: int = VERIFICATION_TTL_HOURS,
) -> tuple[str, uuid.UUID]:
    """签发邮箱验证 JWT。

    Args:
        user_id: 用户 ID
        workspace_id: 工作区 ID（setup 阶段 super_admin 为 None）
        ttl_hours: 有效期小时数（默认 24h）

    Returns:
        (jwt_string, jti_uuid) — jti 需存入 email_verifications 表
    """
    now = _now_utc()
    jti = uuid.uuid4()
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "jti": str(jti),
        "workspace_id": str(workspace_id) if workspace_id else None,
        "purpose": "email_verification",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=ttl_hours)).timestamp()),
    }
    token = jwt.encode(payload, _get_jwt_secret(), algorithm=ALGORITHM)
    return token, jti


# ── Invite Token ─────────────────────────────────────────────────────────────────


def sign_invite(
    workspace_id: uuid.UUID | str,
    email: str,
    role_code: str,
    invited_by: uuid.UUID | str,
    ttl_hours: int = INVITE_TTL_HOURS,
) -> tuple[str, uuid.UUID]:
    """签发邀请 JWT。

    Args:
        workspace_id: 目标工作区 ID
        email: 被邀请人邮箱
        role_code: 目标角色代码（admin/editor/viewer）
        invited_by: 邀请人 user_id
        ttl_hours: 有效期小时数（默认 24h）

    Returns:
        (jwt_string, jti_uuid) — jti 需存入 invites 表
    """
    now = _now_utc()
    jti = uuid.uuid4()
    payload: dict[str, Any] = {
        "jti": str(jti),
        "workspace_id": str(workspace_id),
        "email": email.lower(),
        "target_role": role_code,
        "invited_by": str(invited_by),
        "purpose": "invite",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=ttl_hours)).timestamp()),
    }
    token = jwt.encode(payload, _get_jwt_secret(), algorithm=ALGORITHM)
    return token, jti


# ── 通用：仅校验（GET 用，不消费 jti）────────────────────────────────────────────


def decode_verify_only(token: str, expected_purpose: str) -> dict[str, Any]:
    """校验 JWT 签名 + exp + purpose，但不消费 jti。

    用于 GET 预览端点（如 GET /api/invites/accept?token=）。

    Args:
        token: JWT 字符串
        expected_purpose: 预期的 purpose 字段值

    Returns:
        解码后的 payload 字典

    Raises:
        TokenExpired: token 已过期
        TokenInvalid: token 无效
        TokenPurposeMismatch: purpose 不匹配
    """
    try:
        payload = jwt.decode(
            token,
            _get_jwt_secret(),
            algorithms=[ALGORITHM],
        )
    except jwt.ExpiredSignatureError as e:
        raise TokenExpired("Token 已过期") from e
    except jwt.PyJWTError as e:
        raise TokenInvalid(f"Token 无效：{e}") from e

    if payload.get("purpose") != expected_purpose:
        raise TokenPurposeMismatch(
            f"Token purpose 不匹配：期望 {expected_purpose}，实际 {payload.get('purpose')}"
        )

    return payload


# ── 通用：校验 + 消费（POST 用）──────────────────────────────────────────────────


async def decode_consume_jti(
    token: str,
    table: Literal["invites", "email_verifications"],
    db: AsyncSession,
) -> dict[str, Any]:
    """校验 JWT 签名 + exp，并在 DB 中一次性消费 jti。

    通过 UPDATE ... SET used_at=NOW() WHERE jti=:jti AND used_at IS NULL RETURNING *
    实现幂等消费：零行 → 已消费 → 抛 TokenAlreadyUsedError。

    仅用于 POST 落地端点（Pitfall 3 防护：GET 不消费）。

    Args:
        token: JWT 字符串
        table: 目标表名（'invites' 或 'email_verifications'）
        db: AsyncSession

    Returns:
        解码后的 payload 字典

    Raises:
        TokenExpired: token 已过期
        TokenInvalid: token 无效
        TokenAlreadyUsedError: jti 已被消费
    """
    # 1. 先校验签名和 exp
    try:
        payload = jwt.decode(
            token,
            _get_jwt_secret(),
            algorithms=[ALGORITHM],
        )
    except jwt.ExpiredSignatureError as e:
        raise TokenExpired("Token 已过期") from e
    except jwt.PyJWTError as e:
        raise TokenInvalid(f"Token 无效：{e}") from e

    jti_str = payload.get("jti")
    if not jti_str:
        raise TokenInvalid("Token 缺少 jti 字段")

    # 2. 原子消费：UPDATE WHERE used_at IS NULL
    result = await db.execute(
        text(
            f"UPDATE {table} SET used_at = NOW() "
            f"WHERE jti = :jti AND used_at IS NULL "
            f"RETURNING id"
        ),
        {"jti": jti_str},
    )
    row = result.fetchone()

    if row is None:
        raise TokenAlreadyUsedError(f"Token 已被使用或不存在（jti={jti_str}）")

    return payload


def compute_token_hash(token: str) -> str:
    """计算 token 的 SHA256 哈希，用于审计存储。

    Args:
        token: JWT 字符串

    Returns:
        hex 格式 SHA256 哈希
    """
    return _sha256(token)
