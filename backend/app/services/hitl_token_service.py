"""HITL Token JWT 服务 — HS256 签发 + 解码（aud='hitl'）。

设计参考 docs/reading-dify-03-03-hitl-token-2026-05-17.md §7 GET 不消费 jti 契约。

设计要点：
- 复用 Phase 1 jwt_service._get_jwt_secret()（启动校验 JWT_SECRET >= 32 字节）
- aud='hitl' 严格与 Phase 1 session/email-verification/invite token 区分
- decode 仅校签 + exp + aud + iss + require 字段；**不消费 jti**（消费由 03-06 HitlTokenStore.consume 完成）
- 异常细分（InvalidSignature / TokenExpired / InvalidAudience）便于 API 层做差异化错误页

参考实现：
- Dify api/libs/passport.py PassportService — 5 行 jwt.encode/decode 骨架（设计模式借鉴，AGPL → 重写）
- Phase 1 backend/app/services/jwt_service.py — sign_session/decode_session 风格一致
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Final, Literal
from uuid import UUID

import jwt as pyjwt

from app.services.jwt_service import _get_jwt_secret

log = logging.getLogger(__name__)

# ── 常量 ─────────────────────────────────────────────────────────────────────────
JWT_AUD: Final[str] = "hitl"
JWT_ISS: Final[str] = "agent_builder"
JWT_ALG: Final[str] = "HS256"

# 允许的 HITL action 类型（与 hitl_tokens.action 列一致）
HitlAction = Literal["submit", "approve", "return", "reject"]
HitlRole = Literal["executor", "reviewer"]

# decode 时强制要求的字段
_REQUIRED_CLAIMS: Final[tuple[str, ...]] = ("jti", "exp", "iat", "aud", "iss")


# ── 业务异常类（service 层细分，让 API 层按类型决定 HTTP 状态与文案） ───────────────


class HitlTokenError(Exception):
    """HITL Token 校验异常基类（兜底用，不应直接抛出）。"""


class InvalidSignature(HitlTokenError):
    """JWT 签名错误 — 通常意味着 token 被篡改或密钥不匹配。"""


class TokenExpired(HitlTokenError):
    """JWT 已过期 — UX 上提示"链接已过期，请联系管理员重发邮件"。"""


class InvalidAudience(HitlTokenError):
    """audience 不匹配 — 防止 session/email-verify/invite 等其他 aud 的 token 串用到 HITL 路径。"""


# ── HitlTokenService ─────────────────────────────────────────────────────────────


class HitlTokenService:
    """HITL Token JWT 签发与解码。

    职责边界（reading doc §7）：
    - sign：组装 payload + HS256 签名；**不写 DB**（由 HitlTokenStore.create_batch 落表）
    - decode：校签 + exp + aud + iss + require 字段；**不读 DB**、**不消费 jti**

    多线程安全：所有方法为 @staticmethod，无共享可变状态。
    """

    @staticmethod
    def sign(
        *,
        jti: UUID,
        instance_id: UUID,
        node_state_id: UUID,
        actor_id: UUID,
        action: HitlAction,
        role: HitlRole,
        expires_at: datetime,
    ) -> str:
        """签发 HITL token（HS256）。

        Args:
            jti: JWT ID，UUID，与 hitl_tokens.jti 主键一致
            instance_id: workflow instance（即 LangGraph thread_id 的实例侧 UUID）
            node_state_id: HITL 节点状态行 ID（node_states 表）
            actor_id: 接收人 user_id
            action: 此 token 允许的单个动作（submit / approve / return / reject）
            role: 接收人在本审批中的角色（executor / reviewer）
            expires_at: 过期时刻（UTC datetime；建议与 hitl_tokens.expires_at 一致）

        Returns:
            JWT 字符串（HS256，三段 base64url 用 `.` 拼接）

        Raises:
            RuntimeError: JWT_SECRET 未配置（实际由 startup_checks 保证不会发生）
        """
        secret = _get_jwt_secret()
        now = datetime.now(timezone.utc)
        payload: dict[str, Any] = {
            "iss": JWT_ISS,
            "aud": JWT_AUD,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
            "jti": str(jti),
            "flow_id": str(instance_id),
            "node_state_id": str(node_state_id),
            "actor_id": str(actor_id),
            "role": role,
            "allowed_actions": [action],
        }
        return pyjwt.encode(payload, secret, algorithm=JWT_ALG)

    @staticmethod
    def decode(token: str) -> dict[str, Any]:
        """解码 HITL token — 校签 + exp + aud + iss + require 字段。

        **不消费 jti**（CLAUDE.md 2.5 GET 不消费 jti 契约）。
        消费由 03-06 plan 的公网 API 在 POST 路径调用 HitlTokenStore.consume 完成。

        Args:
            token: JWT 字符串

        Returns:
            解码后的完整 payload dict

        Raises:
            TokenExpired: token 已过期
            InvalidAudience: audience 不是 'hitl'（防 cross-token 滥用）
            InvalidSignature: 签名错误（token 被篡改 / 密钥不匹配）
            HitlTokenError: 其他 PyJWT 校验错误（含缺字段、格式错误、issuer 不匹配等）
        """
        secret = _get_jwt_secret()
        try:
            payload = pyjwt.decode(
                token,
                secret,
                algorithms=[JWT_ALG],
                audience=JWT_AUD,
                issuer=JWT_ISS,
                options={"require": list(_REQUIRED_CLAIMS)},
            )
        except pyjwt.ExpiredSignatureError as e:
            raise TokenExpired(f"HITL token 已过期：{e}") from e
        except pyjwt.InvalidAudienceError as e:
            raise InvalidAudience(f"audience 不匹配（期望 'hitl'）：{e}") from e
        except pyjwt.InvalidSignatureError as e:
            raise InvalidSignature(f"签名错误：{e}") from e
        except pyjwt.InvalidTokenError as e:
            # 兜底：缺字段 / issuer 错 / 格式错 / 等
            raise HitlTokenError(f"HITL token 校验失败：{e}") from e
        return payload
