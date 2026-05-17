"""Phase 4.5 bot_dispatcher 单测共享 fixture。

仅 Wave 1（本 plan）需要的 fixture：
- bot_config_factory: 返回最小合法 BotConfig dict
- mock_redis: AsyncMock 占位（Wave 5 rate_limiter / idempotency 才真用）
- mock_llm: AsyncMock complete() 占位（Wave 3 llm_router 才真用）
- mock_session_factory: AsyncSession factory 占位

Wave 2-5 plans 可以追加 fixture（不修改已有 fixture 签名）。
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def bot_config_factory():
    """工厂 fixture — 返回函数，调用即生成最小合法 BotConfig dict。

    用法::

        def test_xxx(bot_config_factory):
            cfg = bot_config_factory()                            # 默认值
            cfg2 = bot_config_factory(name="other-bot")           # override 单字段
            cfg3 = bot_config_factory(commands=[{...}, {...}])   # override 多字段
    """

    def _factory(**overrides: Any) -> dict[str, Any]:
        base = {
            "name": "offboarding-bot",
            "description": "离职流程助手",
            "provider": {
                "type": "mattermost",
                "config_env_prefix": "MM_",
            },
            "triggers": {
                "dm": True,
                "at_mention": True,
                "keywords": ["我要离职"],
            },
            "identity": {
                "source": "agent_builder_users",
                "on_unknown": "reject_friendly",
                "unknown_hint": "未识别账号，请联系管理员",
            },
            "commands": [
                {
                    "name": "start",
                    "description": "启动新的离职流程",
                    "args": [
                        {
                            "name": "employee_id",
                            "type": "string",
                            "pattern": r"^[a-z][a-z0-9._-]{1,30}$",
                            "required": True,
                        }
                    ],
                    "handler": "handlers.flow:start_flow",
                    "allowed_roles": ["admin", "hr"],
                }
            ],
        }
        base.update(overrides)
        return base

    return _factory


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Redis client AsyncMock 占位（Wave 5 真接入时 fakeredis）。"""
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    redis.get = AsyncMock(return_value=None)
    redis.incr = AsyncMock(return_value=1)
    redis.expire = AsyncMock(return_value=True)
    return redis


@pytest.fixture
def mock_llm() -> AsyncMock:
    """LLM provider AsyncMock 占位（Wave 3 llm_router 真用）。"""
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value='{"intent": "ai_qa", "confidence": 0.0, "args": {}}')
    return llm


@pytest.fixture
def mock_session_factory() -> AsyncMock:
    """AsyncSession factory AsyncMock 占位（Wave 5 audit 真用）。"""
    factory = AsyncMock()
    session = AsyncMock()
    session.add = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    factory.return_value.__aenter__.return_value = session
    return factory
