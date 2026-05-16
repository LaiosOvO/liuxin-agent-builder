"""启动安全校验单元测试。

覆盖 backend/app/agent_builder/security/startup_checks.py 的 run_startup_checks()。

测试策略：
- 用 monkeypatch 设置/删除环境变量，不依赖真实 Redis / DB
- 用 pytest.raises(SystemExit) 断言拒绝启动行为
- 用 caplog 捕获日志，断言中文错误信息格式

NET-04 验收测试。
"""

import pytest
import logging


# ===== 辅助 Fixture：提供完整合法的环境变量 =====

VALID_ENV = {
    "HMAC_SECRET": "x" * 32,
    "JWT_SECRET": "y" * 32,
    "POSTGRES_DSN": "postgresql+asyncpg://user:pass@localhost/db",
    "REDIS_URL": "redis://localhost:6379/0",
    "PUBLIC_BASE_URL": "https://example.com",
    "WEB_ORIGIN": "https://example.com",
}


@pytest.fixture
def valid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """设置所有合法环境变量。"""
    for key, value in VALID_ENV.items():
        monkeypatch.setenv(key, value)


# ===== 测试用例 =====

class TestHmacSecretValidation:
    """HMAC_SECRET 长度校验测试。"""

    def test_short_hmac_secret_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """HMAC_SECRET 长度不足 32 字节时，应拒绝启动（sys.exit(1)）。"""
        # 设置其他合法变量
        for key, value in VALID_ENV.items():
            monkeypatch.setenv(key, value)
        # HMAC_SECRET 设为 31 字节（不足）
        monkeypatch.setenv("HMAC_SECRET", "x" * 31)

        from app.agent_builder.security.startup_checks import run_startup_checks

        with pytest.raises(SystemExit) as exc_info:
            run_startup_checks()

        assert exc_info.value.code == 1

    def test_empty_hmac_secret_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """HMAC_SECRET 为空时，应拒绝启动。"""
        for key, value in VALID_ENV.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setenv("HMAC_SECRET", "")

        from app.agent_builder.security.startup_checks import run_startup_checks

        with pytest.raises(SystemExit) as exc_info:
            run_startup_checks()

        assert exc_info.value.code == 1

    def test_missing_hmac_secret_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """HMAC_SECRET 未设置时，视为空字符串，应拒绝启动。"""
        for key, value in VALID_ENV.items():
            monkeypatch.setenv(key, value)
        monkeypatch.delenv("HMAC_SECRET", raising=False)

        from app.agent_builder.security.startup_checks import run_startup_checks

        with pytest.raises(SystemExit):
            run_startup_checks()


class TestJwtSecretValidation:
    """JWT_SECRET 长度校验测试。"""

    def test_short_jwt_secret_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """JWT_SECRET 长度不足 32 字节时，应拒绝启动。"""
        for key, value in VALID_ENV.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setenv("JWT_SECRET", "short_key")  # 9 字节

        from app.agent_builder.security.startup_checks import run_startup_checks

        with pytest.raises(SystemExit) as exc_info:
            run_startup_checks()

        assert exc_info.value.code == 1

    def test_jwt_secret_exactly_32_bytes_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """JWT_SECRET 恰好 32 字节时，应通过校验。"""
        for key, value in VALID_ENV.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setenv("JWT_SECRET", "a" * 32)

        from app.agent_builder.security.startup_checks import run_startup_checks

        # 不应抛出 SystemExit
        run_startup_checks()


class TestRequiredEnvValidation:
    """必需环境变量存在性校验测试。"""

    def test_missing_postgres_dsn_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """POSTGRES_DSN 未配置时，应拒绝启动。"""
        for key, value in VALID_ENV.items():
            monkeypatch.setenv(key, value)
        monkeypatch.delenv("POSTGRES_DSN")

        from app.agent_builder.security.startup_checks import run_startup_checks

        with pytest.raises(SystemExit):
            run_startup_checks()

    def test_missing_redis_url_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """REDIS_URL 未配置时，应拒绝启动。"""
        for key, value in VALID_ENV.items():
            monkeypatch.setenv(key, value)
        monkeypatch.delenv("REDIS_URL")

        from app.agent_builder.security.startup_checks import run_startup_checks

        with pytest.raises(SystemExit):
            run_startup_checks()

    def test_missing_public_base_url_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """PUBLIC_BASE_URL 未配置时，应拒绝启动。"""
        for key, value in VALID_ENV.items():
            monkeypatch.setenv(key, value)
        monkeypatch.delenv("PUBLIC_BASE_URL")

        from app.agent_builder.security.startup_checks import run_startup_checks

        with pytest.raises(SystemExit):
            run_startup_checks()


class TestSuccessCase:
    """所有校验通过的场景测试。"""

    def test_all_valid_env_no_exit(self, valid_env: None) -> None:
        """所有环境变量合法时，run_startup_checks 应正常返回（不抛出 SystemExit）。"""
        from app.agent_builder.security.startup_checks import run_startup_checks

        # 不应抛出任何异常
        run_startup_checks()

    def test_secrets_longer_than_32_bytes_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """密钥超过 32 字节时，应通过校验。"""
        for key, value in VALID_ENV.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setenv("HMAC_SECRET", "x" * 64)
        monkeypatch.setenv("JWT_SECRET", "y" * 64)

        from app.agent_builder.security.startup_checks import run_startup_checks

        run_startup_checks()


class TestErrorMessageQuality:
    """错误信息质量测试：中文、包含关键字段。"""

    def test_error_message_contains_chinese_length_keyword(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """错误日志应包含"长度不足"中文字样，让运维快速定位问题。"""
        for key, value in VALID_ENV.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setenv("HMAC_SECRET", "short")

        from app.agent_builder.security.startup_checks import run_startup_checks

        with caplog.at_level(logging.ERROR, logger="app.agent_builder.security.startup_checks"):
            with pytest.raises(SystemExit):
                run_startup_checks()

        assert "长度不足" in caplog.text, (
            f"错误日志应包含「长度不足」，实际日志：{caplog.text}"
        )

    def test_error_message_contains_field_name(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """错误日志应包含具体的字段名（HMAC_SECRET），便于定位。"""
        for key, value in VALID_ENV.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setenv("HMAC_SECRET", "x" * 10)

        from app.agent_builder.security.startup_checks import run_startup_checks

        with caplog.at_level(logging.ERROR, logger="app.agent_builder.security.startup_checks"):
            with pytest.raises(SystemExit):
                run_startup_checks()

        assert "HMAC_SECRET" in caplog.text, (
            f"错误日志应包含字段名「HMAC_SECRET」，实际日志：{caplog.text}"
        )

    def test_multiple_errors_reported_together(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """多个错误同时存在时，应在一条日志中全部列出（不要只报第一个）。"""
        for key, value in VALID_ENV.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setenv("HMAC_SECRET", "short")
        monkeypatch.setenv("JWT_SECRET", "also_short")

        from app.agent_builder.security.startup_checks import run_startup_checks

        with caplog.at_level(logging.ERROR, logger="app.agent_builder.security.startup_checks"):
            with pytest.raises(SystemExit):
                run_startup_checks()

        # 两个密钥错误应都出现在日志中
        assert "HMAC_SECRET" in caplog.text
        assert "JWT_SECRET" in caplog.text
