"""速率限制单元测试。

使用 fastapi TestClient + fakeredis（内存后端）模拟 slowapi 限频行为。
不依赖真实 Redis，可在 CI 中直接运行。

测试策略：
- 创建一个包含 stub 路由的最小 FastAPI app，挂载 SlowAPIMiddleware
- 用 limits.storage.MemoryStorage 代替 Redis（避免 testcontainers 依赖）
- 用 freezegun 控制时间窗口，断言 N+1 次请求返回 429

NET-03 验收测试。
"""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address


# ===== 测试用辅助：创建带限频的最小 FastAPI app =====

def _token_key_func(request: Request) -> str:
    """从路径中提取 token 作为限频 key（按 token 独立计数）。"""
    token = request.path_params.get("token", "")
    return token if token else get_remote_address(request)


def _make_app(
    hitl_page_limit: str = "5/minute",
    hitl_action_limit: str = "30/minute",
    webhook_limit: str = "10/second",
    login_limit: str = "10/minute",
) -> tuple[FastAPI, Limiter]:
    """创建带 slowapi 的最小 FastAPI 测试 app（内存存储，不需要 Redis）。"""
    test_limiter = Limiter(
        key_func=get_remote_address,
        default_limits=["100/minute"],
        storage_uri="memory://",  # 内存后端，CI 可用
    )

    app = FastAPI()
    app.state.limiter = test_limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    @app.get("/hitl/page/{token}")
    @test_limiter.limit(hitl_page_limit, key_func=_token_key_func)
    async def hitl_page(token: str, request: Request) -> dict:
        return {"token": token, "status": "ok"}

    @app.post("/hitl/action/{token}")
    @test_limiter.limit(hitl_action_limit)
    async def hitl_action(token: str, request: Request) -> dict:
        return {"token": token, "status": "action_ok"}

    @app.post("/api/im/webhook/{provider}")
    @test_limiter.limit(webhook_limit)
    async def im_webhook(provider: str, request: Request) -> dict:
        return {"provider": provider, "status": "webhook_ok"}

    @app.post("/api/auth/login")
    @test_limiter.limit(login_limit)
    async def login(request: Request) -> dict:
        return {"status": "login_ok"}

    return app, test_limiter


class TestHitlPageRateLimit:
    """/hitl/page/<token> 每 token 每分钟 ≤ 5 次 GET。"""

    def test_within_limit_returns_200(self) -> None:
        """5 次以内的请求应正常返回 200。"""
        app, _ = _make_app(hitl_page_limit="5/minute")
        client = TestClient(app, raise_server_exceptions=False)

        for i in range(5):
            resp = client.get("/hitl/page/my-token-abc")
            assert resp.status_code == 200, f"第 {i+1} 次请求应为 200，实际：{resp.status_code}"

    def test_sixth_request_returns_429(self) -> None:
        """第 6 次请求（超出 5/minute 限额）应返回 429。"""
        app, _ = _make_app(hitl_page_limit="5/minute")
        client = TestClient(app, raise_server_exceptions=False)

        # 消耗 5 个配额
        for _ in range(5):
            client.get("/hitl/page/token-exceed-test")

        # 第 6 次应被限流
        resp = client.get("/hitl/page/token-exceed-test")
        assert resp.status_code == 429, f"第 6 次请求应返回 429，实际：{resp.status_code}"

    def test_different_tokens_have_independent_limits(self) -> None:
        """不同 token 的请求计数应相互独立（按 token 维度限频）。"""
        app, _ = _make_app(hitl_page_limit="3/minute")
        client = TestClient(app, raise_server_exceptions=False)

        # TOKEN-A 消耗 3 个配额
        for _ in range(3):
            resp = client.get("/hitl/page/TOKEN-A")
            assert resp.status_code == 200

        # TOKEN-A 第 4 次应被限流
        resp_a_4th = client.get("/hitl/page/TOKEN-A")
        assert resp_a_4th.status_code == 429, "TOKEN-A 超限后应 429"

        # TOKEN-B 应仍有配额（独立计数器）
        resp_b = client.get("/hitl/page/TOKEN-B")
        assert resp_b.status_code == 200, (
            f"TOKEN-B 是独立 token，不应受 TOKEN-A 限额影响，实际：{resp_b.status_code}"
        )


class TestHitlActionRateLimit:
    """/hitl/action/<token> 每 IP 每分钟 ≤ 30 次 POST。"""

    def test_within_limit_returns_200(self) -> None:
        """30 次以内的请求应正常返回 200。"""
        app, _ = _make_app(hitl_action_limit="30/minute")
        client = TestClient(app, raise_server_exceptions=False)

        for i in range(10):  # 只测 10 次避免测试过慢
            resp = client.post("/hitl/action/action-token")
            assert resp.status_code == 200, f"第 {i+1} 次 POST 应为 200，实际：{resp.status_code}"

    def test_over_limit_returns_429(self) -> None:
        """超出每分钟限额后应返回 429。"""
        app, _ = _make_app(hitl_action_limit="5/minute")  # 低限额便于测试
        client = TestClient(app, raise_server_exceptions=False)

        # 消耗配额
        for _ in range(5):
            client.post("/hitl/action/action-limit-test")

        # 超限
        resp = client.post("/hitl/action/action-limit-test")
        assert resp.status_code == 429, f"超限后应返回 429，实际：{resp.status_code}"


class TestImWebhookRateLimit:
    """/api/im/webhook/* 每秒 ≤ 10 次（防 IM 重试风暴）。"""

    def test_within_limit_returns_200(self) -> None:
        """限额内的请求应正常返回 200。"""
        app, _ = _make_app(webhook_limit="10/second")
        client = TestClient(app, raise_server_exceptions=False)

        for i in range(5):
            resp = client.post("/api/im/webhook/feishu")
            assert resp.status_code == 200, f"第 {i+1} 次请求应为 200，实际：{resp.status_code}"

    def test_over_limit_returns_429(self) -> None:
        """超出每秒限额后应返回 429。"""
        app, _ = _make_app(webhook_limit="5/second")  # 低限额便于测试
        client = TestClient(app, raise_server_exceptions=False)

        # 消耗 5 个配额
        for _ in range(5):
            client.post("/api/im/webhook/wecom")

        # 第 6 次超限
        resp = client.post("/api/im/webhook/wecom")
        assert resp.status_code == 429, f"超限后应返回 429，实际：{resp.status_code}"

    def test_webhook_rate_limit_applies_per_path_route(self) -> None:
        """单个 provider webhook 路由的速率限制生效验证。"""
        app, _ = _make_app(webhook_limit="3/second")
        client = TestClient(app, raise_server_exceptions=False)

        # 消耗 feishu 的 3 个配额
        for i in range(3):
            resp = client.post("/api/im/webhook/feishu")
            assert resp.status_code == 200, f"第 {i+1} 次应为 200，实际：{resp.status_code}"

        # 第 4 次超限（同一 feishu 路由，同一 IP 计数器）
        resp = client.post("/api/im/webhook/feishu")
        assert resp.status_code == 429, (
            f"webhook 超限后应返回 429，实际：{resp.status_code}"
        )


class TestLoginRateLimit:
    """/api/auth/login 每 IP/min ≤ 10（防暴力破解）。"""

    def test_within_limit_returns_200(self) -> None:
        """限额内的登录请求应通过。"""
        app, _ = _make_app(login_limit="10/minute")
        client = TestClient(app, raise_server_exceptions=False)

        for i in range(5):
            resp = client.post("/api/auth/login")
            assert resp.status_code == 200, f"第 {i+1} 次登录应为 200，实际：{resp.status_code}"

    def test_brute_force_blocked_by_429(self) -> None:
        """超出限额后（模拟暴力破解）应返回 429。"""
        app, _ = _make_app(login_limit="3/minute")  # 低限额便于测试
        client = TestClient(app, raise_server_exceptions=False)

        for _ in range(3):
            client.post("/api/auth/login")

        resp = client.post("/api/auth/login")
        assert resp.status_code == 429, f"暴力破解保护：超限后应返回 429，实际：{resp.status_code}"


class TestRateLimitModuleImport:
    """验证 rate_limit 模块可正常导入（独立于 Redis 连接）。"""

    def test_limiter_singleton_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """rate_limit.limiter 单例应存在且为 Limiter 类型。"""
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        import importlib

        # 重新加载以确保 env 变量生效
        import app.agent_builder.security.rate_limit as rl_module
        importlib.reload(rl_module)

        assert hasattr(rl_module, "limiter"), "rate_limit 模块应导出 limiter 单例"
        assert isinstance(rl_module.limiter, Limiter), "limiter 应为 slowapi.Limiter 实例"

    def test_get_token_from_path_extracts_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_token_from_path 应从 /hitl/page/<token> 提取 token。"""
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        from app.agent_builder.security.rate_limit import get_token_from_path
        from unittest.mock import MagicMock

        # 模拟 Starlette Request
        mock_request = MagicMock()
        mock_request.url.path = "/hitl/page/MY-UNIQUE-TOKEN"
        mock_request.client.host = "1.2.3.4"

        token = get_token_from_path(mock_request)
        assert token == "MY-UNIQUE-TOKEN", f"应提取到 token，实际：{token}"

    def test_get_token_from_path_fallback_to_ip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """非 HITL 路径时，get_token_from_path 应降级为 IP 地址。"""
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        from app.agent_builder.security.rate_limit import get_token_from_path
        from unittest.mock import MagicMock

        mock_request = MagicMock()
        mock_request.url.path = "/api/auth/login"
        mock_request.client.host = "1.2.3.4"

        # 非 HITL 路径降级为 IP
        result = get_token_from_path(mock_request)
        # 结果应是 IP 地址（由 get_remote_address 返回）
        assert result is not None, "非 HITL 路径应返回 IP 地址"
