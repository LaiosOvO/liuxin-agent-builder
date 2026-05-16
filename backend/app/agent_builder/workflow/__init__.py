"""agent-builder 工作流模块。

公共 API（Phase 2 波次 1 交付）：
- get_checkpointer(): AsyncPostgresSaver context manager
- ensure_checkpoint_tables(): 启动时调用一次，创建 LangGraph checkpoint 表
- build_thread_id(): 构造含 workspace 前缀的 thread_id（防 Pitfall 13）
- parse_thread_id(): 解析 thread_id 为 (workspace_id, instance_id)
- build_state_typeddict(): 从 DSL state_schema 动态构造 TypedDict 类
- SCHEMA_TYPES: 支持的 Python 类型字符串列表
"""
from app.agent_builder.workflow.checkpoint import (
    build_thread_id,
    ensure_checkpoint_tables,
    get_checkpointer,
    parse_thread_id,
)
from app.agent_builder.workflow.types import SCHEMA_TYPES, build_state_typeddict

__all__ = [
    "get_checkpointer",
    "ensure_checkpoint_tables",
    "build_thread_id",
    "parse_thread_id",
    "build_state_typeddict",
    "SCHEMA_TYPES",
]
