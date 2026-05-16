"""JWT 服务单元测试。

覆盖 3 类 token：
- Session token：签发 + 校验 + 过期
- Email verification token：签发 + decode_verify_only（不消费）
- Invite token：签发 + decode_verify_only + purpose mismatch
- decode_consume_jti：通过 mock DB 测试消费逻辑

注意：decode_consume_jti 的数据库消费集成测试在 test_invite_flow / test_registration_flow。
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 设置测试用环境变量（startup_checks 需要）
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-32-bytes-minimum--!")
os.environ.setdefault("HMAC_SECRET", "test-hmac-secret-32-bytes-minimum-!")
os.environ.setdefault("POSTGRES_DSN", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("PUBLIC_BASE_URL", "http://localhost:3000")
os.environ.setdefault("WEB_ORIGIN", "http://localhost:3000")

from app.services.jwt_service import (
    TokenAlreadyUsedError,
    TokenExpired,
    TokenInvalid,
    TokenPurposeMismatch,
    compute_token_hash,
    decode_consume_jti,
    decode_session,
    decode_verify_only,
    sign_email_verification,
    sign_invite,
    sign_session,
)


# ── 测试数据 ─────────────────────────────────────────────────────────────────────

FAKE_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
FAKE_WS_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
FAKE_EMAIL = "test@example.com"
FAKE_ROLE = "editor"


# ── Session Token 测试 ───────────────────────────────────────────────────────────


class TestSignSession:
    """Session token 签发测试。"""

    def test_returns_string(self):
        """sign_session 返回字符串。"""
        token = sign_session(FAKE_USER_ID, FAKE_WS_ID)
        assert isinstance(token, str)
        assert "." in token  # JWT 格式：header.payload.signature

    def test_decode_valid_token(self):
        """签发的 token 能正确解码。"""
        token = sign_session(FAKE_USER_ID, FAKE_WS_ID)
        claims = decode_session(token)
        assert claims["sub"] == str(FAKE_USER_ID)
        assert claims["ws"] == str(FAKE_WS_ID)

    def test_token_has_exp(self):
        """token 包含 exp 字段。"""
        token = sign_session(FAKE_USER_ID, FAKE_WS_ID)
        claims = decode_session(token)
        assert "exp" in claims
        assert claims["exp"] > 0

    def test_custom_ttl(self):
        """自定义 TTL 影响 exp 时间。"""
        token1 = sign_session(FAKE_USER_ID, FAKE_WS_ID, ttl_hours=1)
        token24 = sign_session(FAKE_USER_ID, FAKE_WS_ID, ttl_hours=24)
        claims1 = decode_session(token1)
        claims24 = decode_session(token24)
        # 24h token 的 exp 远大于 1h token
        assert claims24["exp"] > claims1["exp"] + 3600 * 10


class TestDecodeSession:
    """Session token 解码测试。"""

    def test_expired_token_raises(self):
        """过期 token 抛 TokenExpired。"""
        # 使用 freezegun 模拟时间过去
        import jwt
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(FAKE_USER_ID),
            "ws": str(FAKE_WS_ID),
            "iat": int((now - timedelta(hours=25)).timestamp()),
            "exp": int((now - timedelta(hours=1)).timestamp()),
        }
        expired_token = jwt.encode(payload, os.environ["JWT_SECRET"], algorithm="HS256")

        with pytest.raises(TokenExpired):
            decode_session(expired_token)

    def test_invalid_token_raises(self):
        """无效 token 抛 TokenInvalid。"""
        with pytest.raises(TokenInvalid):
            decode_session("not.a.valid.jwt")

    def test_tampered_token_raises(self):
        """篡改 token 抛 TokenInvalid。"""
        token = sign_session(FAKE_USER_ID, FAKE_WS_ID)
        # 篡改 payload 部分
        parts = token.split(".")
        tampered = parts[0] + ".TAMPERED" + parts[2]
        with pytest.raises(TokenInvalid):
            decode_session(tampered)


# ── Email Verification Token 测试 ────────────────────────────────────────────────


class TestEmailVerificationToken:
    """邮箱验证 token 测试。"""

    def test_sign_returns_tuple(self):
        """sign_email_verification 返回 (str, UUID)。"""
        token, jti = sign_email_verification(FAKE_USER_ID, FAKE_WS_ID)
        assert isinstance(token, str)
        assert isinstance(jti, uuid.UUID)

    def test_decode_verify_only_valid(self):
        """合法 token decode_verify_only 返回 payload。"""
        token, jti = sign_email_verification(FAKE_USER_ID, FAKE_WS_ID)
        payload = decode_verify_only(token, "email_verification")
        assert payload["sub"] == str(FAKE_USER_ID)
        assert payload["jti"] == str(jti)
        assert payload["purpose"] == "email_verification"

    def test_decode_verify_does_not_consume(self):
        """decode_verify_only 不操作 DB（纯解码）。"""
        token, jti = sign_email_verification(FAKE_USER_ID, FAKE_WS_ID)
        # 调用多次不应有任何副作用（无 DB mock）
        payload1 = decode_verify_only(token, "email_verification")
        payload2 = decode_verify_only(token, "email_verification")
        assert payload1["jti"] == payload2["jti"]

    def test_setup_super_admin_no_workspace(self):
        """setup 阶段 workspace_id 可为 None。"""
        token, jti = sign_email_verification(FAKE_USER_ID, workspace_id=None)
        payload = decode_verify_only(token, "email_verification")
        assert payload["workspace_id"] is None


# ── Invite Token 测试 ────────────────────────────────────────────────────────────


class TestInviteToken:
    """邀请 token 测试。"""

    def test_sign_returns_tuple(self):
        """sign_invite 返回 (str, UUID)。"""
        token, jti = sign_invite(FAKE_WS_ID, FAKE_EMAIL, FAKE_ROLE, FAKE_USER_ID)
        assert isinstance(token, str)
        assert isinstance(jti, uuid.UUID)

    def test_decode_verify_only_valid(self):
        """合法邀请 token 解码正确。"""
        token, jti = sign_invite(FAKE_WS_ID, FAKE_EMAIL, FAKE_ROLE, FAKE_USER_ID)
        payload = decode_verify_only(token, "invite")
        assert payload["email"] == FAKE_EMAIL.lower()
        assert payload["target_role"] == FAKE_ROLE
        assert payload["workspace_id"] == str(FAKE_WS_ID)
        assert payload["jti"] == str(jti)
        assert payload["purpose"] == "invite"

    def test_purpose_mismatch_raises(self):
        """purpose 不匹配抛 TokenPurposeMismatch。"""
        token, _ = sign_invite(FAKE_WS_ID, FAKE_EMAIL, FAKE_ROLE, FAKE_USER_ID)
        with pytest.raises(TokenPurposeMismatch):
            decode_verify_only(token, "email_verification")  # 错误 purpose

    def test_email_verification_vs_invite_purpose(self):
        """邮箱验证 token 用邀请 purpose 解码失败。"""
        token, _ = sign_email_verification(FAKE_USER_ID, FAKE_WS_ID)
        with pytest.raises(TokenPurposeMismatch):
            decode_verify_only(token, "invite")


# ── decode_consume_jti 测试（Mock DB）────────────────────────────────────────────


class TestDecodeConsumeJti:
    """decode_consume_jti 消费测试（Mock AsyncSession）。"""

    @pytest.mark.asyncio
    async def test_consume_invite_token_success(self):
        """有效 token + DB 返回一行 → 成功返回 payload。"""
        token, jti = sign_invite(FAKE_WS_ID, FAKE_EMAIL, FAKE_ROLE, FAKE_USER_ID)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (uuid.uuid4(),)  # 返回一行
        mock_db.execute.return_value = mock_result

        payload = await decode_consume_jti(token, "invites", mock_db)
        assert payload["purpose"] == "invite"
        assert payload["email"] == FAKE_EMAIL.lower()

        # 确认 DB 执行了 UPDATE
        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args
        sql_text = str(call_args[0][0])
        assert "invites" in sql_text
        assert "used_at" in sql_text

    @pytest.mark.asyncio
    async def test_consume_already_used_raises(self):
        """DB 返回零行（jti 已用）→ 抛 TokenAlreadyUsedError。"""
        token, jti = sign_invite(FAKE_WS_ID, FAKE_EMAIL, FAKE_ROLE, FAKE_USER_ID)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None  # 零行
        mock_db.execute.return_value = mock_result

        with pytest.raises(TokenAlreadyUsedError):
            await decode_consume_jti(token, "invites", mock_db)

    @pytest.mark.asyncio
    async def test_expired_token_raises_before_db(self):
        """过期 token → 抛 TokenExpired（不查 DB）。"""
        import jwt
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        payload = {
            "jti": str(uuid.uuid4()),
            "workspace_id": str(FAKE_WS_ID),
            "email": FAKE_EMAIL,
            "target_role": FAKE_ROLE,
            "invited_by": str(FAKE_USER_ID),
            "purpose": "invite",
            "iat": int((now - timedelta(hours=25)).timestamp()),
            "exp": int((now - timedelta(hours=1)).timestamp()),
        }
        expired_token = jwt.encode(payload, os.environ["JWT_SECRET"], algorithm="HS256")

        mock_db = AsyncMock()

        with pytest.raises(TokenExpired):
            await decode_consume_jti(expired_token, "invites", mock_db)

        # 确认未调用 DB
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_token_raises_before_db(self):
        """无效 token → 抛 TokenInvalid（不查 DB）。"""
        mock_db = AsyncMock()

        with pytest.raises(TokenInvalid):
            await decode_consume_jti("not.valid.jwt", "invites", mock_db)

        mock_db.execute.assert_not_called()


# ── compute_token_hash 测试 ──────────────────────────────────────────────────────


class TestComputeTokenHash:
    """token hash 测试。"""

    def test_returns_hex_string(self):
        """返回 64 字符 hex 字符串（SHA256）。"""
        token = sign_session(FAKE_USER_ID, FAKE_WS_ID)
        h = compute_token_hash(token)
        assert isinstance(h, str)
        assert len(h) == 64
        # 仅含 hex 字符
        assert all(c in "0123456789abcdef" for c in h)

    def test_different_tokens_different_hashes(self):
        """不同 token 得到不同哈希。"""
        t1 = sign_session(FAKE_USER_ID, FAKE_WS_ID)
        t2 = sign_session(FAKE_USER_ID, uuid.uuid4())  # 不同 ws
        assert compute_token_hash(t1) != compute_token_hash(t2)

    def test_same_token_same_hash(self):
        """相同 token 得到相同哈希（确定性）。"""
        token = sign_session(FAKE_USER_ID, FAKE_WS_ID)
        assert compute_token_hash(token) == compute_token_hash(token)
