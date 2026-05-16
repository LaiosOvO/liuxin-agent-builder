"""LLM 节点 Schema 定义。

LLM 节点：
- 调用大语言模型进行推理
- 必须指定 model 字段（格式 "provider:model_name"，如 "openai:gpt-4o"）
- prompt 有两种模式：
  1. 标准模式：user_prompt（必填）+ system_prompt（可选）+ assistant_examples（可选 few-shot）
  2. 高级模式：raw_prompt（原始 messages 数组 JSON）
- oneOf 保证两种模式恰好选一
- 所有 prompt 字段支持 Jinja2 变量插值
"""
from __future__ import annotations

# LLM 节点 JSON Schema
LLM_NODE_SCHEMA: dict = {
    "type": "object",
    "required": ["model"],
    "additionalProperties": False,
    "properties": {
        "model": {
            "type": "string",
            "minLength": 1,
            "description": "LLM 模型标识，格式 provider:model_name（如 openai:gpt-4o）",
        },
        "system_prompt": {
            "type": ["string", "null"],
            "description": "系统提示词，支持 Jinja2 变量插值",
        },
        "user_prompt": {
            "type": "string",
            "description": "用户提示词（标准模式，与 raw_prompt 二选一），支持 Jinja2 变量插值",
        },
        "assistant_examples": {
            "type": "array",
            "items": {"type": "object"},
            "description": "Few-shot 示例列表（可选）",
        },
        "raw_prompt": {
            "type": ["array", "null"],
            "items": {"type": "object"},
            "description": "原始 messages 数组（高级模式，与 user_prompt 二选一），支持 Jinja2 变量插值",
        },
        "temperature": {
            "type": "number",
            "minimum": 0,
            "maximum": 2,
            "description": "采样温度，范围 [0, 2]",
        },
        "timeout_sec": {
            "type": "integer",
            "minimum": 1,
            "maximum": 600,
            "default": 30,
            "description": "超时秒数，默认 30 秒",
        },
        "retry_count": {
            "type": "integer",
            "minimum": 0,
            "maximum": 10,
            "default": 3,
            "description": "重试次数，默认 3 次",
        },
        "backoff_base_sec": {
            "type": "number",
            "minimum": 0,
            "maximum": 60,
            "default": 1,
            "description": "指数退避基础秒数，默认 1 秒",
        },
    },
    "oneOf": [
        {"required": ["user_prompt"]},
        {"required": ["raw_prompt"]},
    ],
}

# LLM 节点输出字段
# 节点执行后写入 state[node_id] = {message, role, usage, model}
LLM_OUTPUT_FIELDS: frozenset[str] = frozenset({
    "message",   # LLM 回复文本
    "role",      # 消息角色（通常为 "assistant"）
    "usage",     # token 用量（prompt_tokens / completion_tokens / total_tokens）
    "model",     # 实际使用的模型名称
})
