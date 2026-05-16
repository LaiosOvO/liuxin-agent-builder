"""HitlTokenService 单元测试（10+ 用例）。

覆盖范围（plan 03-03 must_haves）：
- sign 返回 JWT 字符串
- sign / decode round-trip 字段完整
- 异常细分：InvalidSignature / TokenExpired / InvalidAudience / HitlTokenError
- payload 含全部 required claims
- 不同 action 产生不同 payload
- 复用 Phase 1 _get_jwt_secret（mock 验证）

注意：本测试为**纯单元测试**，不依赖 Postgres / Redis。
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

import jwt as pyjwt
import pytest

# 设置测试用环境变量（startup_checks 需要 JWT_SECRET >= 32 字节）
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-32-bytes-minimum--!")
os.environ.setdefault("HMAC_SECRET", "test-hmac-secret-32-bytes-minimum-!")
os.environ.setdefault("POSTGRES_DSN", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("PUBLIC_BASE_URL", "http://localhost:3000")
os.environ.setdefault("WEB_ORIGIN", "http://localhost:3000")

from app.services.hitl_token_service import (
    JWT_ALG,
    JWT_AUD,
    JWT_ISS,
    HitlTokenError,
    HitlTokenService,
    InvalidAudience,
    InvalidSignature,
    TokenExpired,
)
from app.services.jwt_service import _get_jwt_secret

# ── 测试数据 ─────────────────────────────────────────────────────────────────────

FAKE_JTI = uuid.UUID("00000000-0000-0000-0000-000000000001")
FAKE_INSTANCE_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
FAKE_NODE_STATE_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")
FAKE_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-000000000004")


def _make_token(
    *,
    action: str = "submit",
    role: str = "executor",
    expires_in_minutes: int = 30,
) -> str:
    """工厂函数：生成 valid HITL token。"""
    return HitlTokenService.sign(
        jti=FAKE_JTI,
        instance_id=FAKE_INSTANCE_ID,
        node_state_id=FAKE_NODE_STATE_ID,
        actor_id=FAKE_ACTOR_ID,
        action=action,  # type: ignore[arg-type]
        role=role,  # type: ignore[arg-type]
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes),
    )


# ── Sign 测试 ────────────────────────────────────────────────────────────────────


class TestHitlTokenServiceSign:
    """HitlTokenService.sign 签发测试。"""

    def test_sign_returns_jwt_string(self):
        """sign 返回 JWT 三段式字符串（header.payload.signature）。"""
        token = _make_token()
        assert isinstance(token, str)
        assert token.count(".") == 2  # JWT 三段式

    def test_sign_uses_HMAC_secret_from_jwt_service(self):
        """sign 调用 _get_jwt_secret() — 复用 Phase 1（不重读 env）。"""
        with patch(
            "app.services.hitl_token_service._get_jwt_secret",
            wraps=_get_jwt_secret,
        ) as spy:
            _make_token()
            assert spy.call_count >= 1

    def test_sign_different_actions_produce_different_payloads(self):
        """不同 action 的 token payload 中 allowed_actions 不同。"""
        token_submit = _make_token(action="submit")
        token_approve = _make_token(action="approve")
        # 不强等长度（exp 时间略有差异也不影响）— 直接看 allowed_actions
        payload_submit = HitlTokenService.decode(token_submit)
        payload_approve = HitlTokenService.decode(token_approve)
        assert payload_submit["allowed_actions"] == ["submit"]
        assert payload_approve["allowed_actions"] == ["approve"]


# ── Decode 测试 ──────────────────────────────────────────────────────────────────


class TestHitlTokenServiceDecode:
    """HitlTokenService.decode 校签 + 异常映射测试。"""

    def test_sign_decode_roundtrip(self):
        """sign 后 decode 拿到一致的字段。"""
        token = _make_token(action="submit", role="executor")
        payload = HitlTokenService.decode(token)
        assert payload["jti"] == str(FAKE_JTI)
        assert payload["flow_id"] == str(FAKE_INSTANCE_ID)
        assert payload["node_state_id"] == str(FAKE_NODE_STATE_ID)
        assert payload["actor_id"] == str(FAKE_ACTOR_ID)
        assert payload["role"] == "executor"
        assert payload["allowed_actions"] == ["submit"]
        assert payload["aud"] == JWT_AUD
        assert payload["iss"] == JWT_ISS

    def test_decode_payload_contains_all_required_claims(self):
        """payload 含全部 required claims（jti/exp/iat/aud/iss + 业务字段）。"""
        token = _make_token()
        payload = HitlTokenService.decode(token)
        for claim in ("jti", "exp", "iat", "aud", "iss",
                      "flow_id", "node_state_id", "actor_id", "role", "allowed_actions"):
            assert claim in payload, f"缺字段 {claim}"

    def test_decode_with_wrong_signature_raises_InvalidSignature(self):
        """换密钥签的 token → InvalidSignature。"""
        # 用错误密钥手工签一个 token（aud/iss/require 都正确，只是签名错）
        now = datetime.now(timezone.utc)
        bad_token = pyjwt.encode(
            {
                "iss": JWT_ISS,
                "aud": JWT_AUD,
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(minutes=30)).timestamp()),
                "jti": str(FAKE_JTI),
                "flow_id": str(FAKE_INSTANCE_ID),
                "node_state_id": str(FAKE_NODE_STATE_ID),
                "actor_id": str(FAKE_ACTOR_ID),
                "role": "executor",
                "allowed_actions": ["submit"],
            },
            "wrong-secret-32-bytes-minimum-!!!",  # 不同密钥
            algorithm=JWT_ALG,
        )
        with pytest.raises(InvalidSignature):
            HitlTokenService.decode(bad_token)

    def test_decode_with_expired_token_raises_TokenExpired(self):
        """exp 在过去的 token → TokenExpired。"""
        secret = _get_jwt_secret()
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        expired_token = pyjwt.encode(
            {
                "iss": JWT_ISS,
                "aud": JWT_AUD,
                "iat": int((past - timedelta(seconds=30)).timestamp()),
                "exp": int(past.timestamp()),  # 过期
                "jti": str(FAKE_JTI),
                "flow_id": str(FAKE_INSTANCE_ID),
                "node_state_id": str(FAKE_NODE_STATE_ID),
                "actor_id": str(FAKE_ACTOR_ID),
                "role": "executor",
                "allowed_actions": ["submit"],
            },
            secret,
            algorithm=JWT_ALG,
        )
        with pytest.raises(TokenExpired):
            HitlTokenService.decode(expired_token)

    def test_decode_with_wrong_audience_raises_InvalidAudience(self):
        """aud 不是 'hitl'（如换成 'session'） → InvalidAudience。"""
        secret = _get_jwt_secret()
        now = datetime.now(timezone.utc)
        wrong_aud_token = pyjwt.encode(
            {
                "iss": JWT_ISS,
                "aud": "session",  # 错误 aud（Phase 1 session token 用 'session'）
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(minutes=30)).timestamp()),
                "jti": str(FAKE_JTI),
                "flow_id": str(FAKE_INSTANCE_ID),
                "node_state_id": str(FAKE_NODE_STATE_ID),
                "actor_id": str(FAKE_ACTOR_ID),
                "role": "executor",
                "allowed_actions": ["submit"],
            },
            secret,
            algorithm=JWT_ALG,
        )
        with pytest.raises(InvalidAudience):
            HitlTokenService.decode(wrong_aud_token)

    def test_decode_with_invalid_format_raises_HitlTokenError(self):
        """随便一个字符串 → HitlTokenError（兜底）。"""
        with pytest.raises(HitlTokenError):
            HitlTokenService.decode("not-a-jwt-string")

    def test_decode_with_missing_required_claim_raises_HitlTokenError(self):
        """缺 jti 字段 → HitlTokenError（require 校验失败）。"""
        secret = _get_jwt_secret()
        now = datetime.now(timezone.utc)
        # 故意不放 jti
        token_no_jti = pyjwt.encode(
            {
                "iss": JWT_ISS,
                "aud": JWT_AUD,
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(minutes=30)).timestamp()),
                # 注意：缺 jti
                "flow_id": str(FAKE_INSTANCE_ID),
                "node_state_id": str(FAKE_NODE_STATE_ID),
                "actor_id": str(FAKE_ACTOR_ID),
                "role": "executor",
                "allowed_actions": ["submit"],
            },
            secret,
            algorithm=JWT_ALG,
        )
        with pytest.raises(HitlTokenError):
            HitlTokenService.decode(token_no_jti)

    def test_decode_uses_HMAC_secret_from_jwt_service(self):
        """decode 调用 _get_jwt_secret()（复用 Phase 1）。"""
        token = _make_token()
        with patch(
            "app.services.hitl_token_service._get_jwt_secret",
            wraps=_get_jwt_secret,
        ) as spy:
            HitlTokenService.decode(token)
            assert spy.call_count >= 1


# ── 安全性 / 隔离测试 ────────────────────────────────────────────────────────────


class TestHitlTokenServiceAudienceIsolation:
    """audience 隔离测试 — 确保 HITL token 不能串用到 Phase 1 其他 aud 路径。"""

    def test_hitl_aud_is_distinct_from_phase1(self):
        """常量 JWT_AUD = 'hitl'（CONTEXT.md §Token 4-action）。"""
        assert JWT_AUD == "hitl"

    def test_phase1_session_token_cannot_be_decoded_as_hitl(self):
        """用 Phase 1 sign_session 签的 token 用 HitlTokenService.decode 解 → InvalidAudience。

        Phase 1 session token aud 缺失或为 session/未设定；
        HitlTokenService 强制要求 aud='hitl'，应抛 InvalidAudience 或 HitlTokenError。
        """
        from app.services.jwt_service import sign_session

        session_token = sign_session(FAKE_ACTOR_ID, FAKE_INSTANCE_ID)
        # Phase 1 session token 没有 aud 字段 → require 校验先失败
        # 或 PyJWT 在 audience 参数存在时优先校 aud → InvalidAudienceError
        # 两种情况都被映射为 HitlTokenError 家族
        with pytest.raises(HitlTokenError):
            HitlTokenService.decode(session_token)
