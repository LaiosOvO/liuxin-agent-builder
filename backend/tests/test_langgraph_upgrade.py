"""LangGraph 1.2 + checkpoint-postgres 3.1 升级验证测试。

验证目标：
- langgraph 版本已锁定 1.2.0
- AsyncPostgresSaver 可导入
- ChatLiteLLM（flock 兼容性）可导入
- redis 版本 7.4.0
- flock smoke 不破坏（import 层面）
"""
from __future__ import annotations

import importlib.metadata


def test_langgraph_version_pinned():
    """langgraph 版本必须以 1.2. 开头。"""
    version = importlib.metadata.version("langgraph")
    assert version.startswith("1.2."), f"langgraph 版本期望 1.2.x，实际: {version}"


def test_async_postgres_saver_importable():
    """AsyncPostgresSaver 必须可从 langgraph.checkpoint.postgres.aio 导入。"""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # noqa: F401

    assert AsyncPostgresSaver is not None, "AsyncPostgresSaver 导入失败"


def test_chat_litellm_importable():
    """ChatLiteLLM 必须可从 langchain_community.chat_models 导入（flock 兼容性）。"""
    from langchain_community.chat_models import ChatLiteLLM  # noqa: F401

    assert ChatLiteLLM is not None, "ChatLiteLLM 导入失败"


def test_redis_py_version():
    """redis-py 版本必须为 7.4.0。"""
    version = importlib.metadata.version("redis")
    assert version.startswith("7."), f"redis 版本期望 7.x，实际: {version}"
    assert version == "7.4.0", f"redis 版本期望精确锁定 7.4.0，实际: {version}"


def test_flock_smoke_not_broken():
    """flock 主要依赖模块 import 不报错（保证 flock 原代码不被新版本破坏）。

    检查关键 flock 用到的 langchain 包可正常导入。
    注意：不导入 langchain_sandbox（已在 Phase 2 注释，等 Phase 6 插件机制替代）。
    """
    # langchain 核心
    import langchain  # noqa: F401
    import langchain_community  # noqa: F401
    import langchain_openai  # noqa: F401

    # litellm（flock LLM 节点用）
    import litellm  # noqa: F401

    # langgraph（升级后版本）
    from langgraph.graph import StateGraph  # noqa: F401

    # psycopg3（checkpoint 用）
    import psycopg  # noqa: F401

    assert True, "所有关键 flock 依赖模块均可正常导入"


def test_checkpoint_postgres_version():
    """langgraph-checkpoint-postgres 版本必须为 3.1.0。"""
    version = importlib.metadata.version("langgraph-checkpoint-postgres")
    assert version == "3.1.0", (
        f"langgraph-checkpoint-postgres 版本期望 3.1.0，实际: {version}"
    )


def test_psycopg3_available():
    """psycopg3 必须可用（langgraph-checkpoint-postgres 3.1 依赖）。"""
    import psycopg  # noqa: F401
    from psycopg_pool import AsyncConnectionPool  # noqa: F401

    version = importlib.metadata.version("psycopg")
    # psycopg3 版本应 >= 3.1
    major, minor = version.split(".")[:2]
    assert int(major) >= 3, f"psycopg 版本期望 >=3.x，实际: {version}"
    assert int(minor) >= 1, f"psycopg 版本期望 >=3.1，实际: {version}"
