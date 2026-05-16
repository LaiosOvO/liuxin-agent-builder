"""Tool 节点 Schema 定义。

Tool 节点：
- 调用外部工具（HTTP 请求 或 Python 函数）
- 通过 kind 字段区分两种模式：
  1. kind="http"：HTTP 请求（method/url/headers/body，全部支持 Jinja2 模板）
  2. kind="python"：Python 函数调用（注册式，函数名 + 参数，沙箱执行）
- 两种 schema 通过 oneOf 实现
"""
from __future__ import annotations

# HTTP Tool 节点 JSON Schema
TOOL_HTTP_SCHEMA: dict = {
    "type": "object",
    "required": ["kind", "method", "url"],
    "additionalProperties": False,
    "properties": {
        "kind": {
            "const": "http",
            "description": "工具类型标识，固定为 http",
        },
        "method": {
            "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"],
            "description": "HTTP 请求方法",
        },
        "url": {
            "type": "string",
            "description": "请求 URL，支持 Jinja2 变量插值",
        },
        "headers": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": "请求头，值支持 Jinja2 变量插值",
        },
        "body": {
            "type": ["object", "string", "null"],
            "description": "请求体（object 或 JSON 字符串），支持 Jinja2 变量插值",
        },
        "timeout_sec": {
            "type": "integer",
            "minimum": 1,
            "maximum": 60,
            "default": 10,
            "description": "超时秒数，默认 10 秒",
        },
        "retry_count": {
            "type": "integer",
            "minimum": 0,
            "default": 2,
            "description": "重试次数，默认 2 次",
        },
    },
}

# Python Tool 节点 JSON Schema
TOOL_PYTHON_SCHEMA: dict = {
    "type": "object",
    "required": ["kind", "function"],
    "additionalProperties": False,
    "properties": {
        "kind": {
            "const": "python",
            "description": "工具类型标识，固定为 python",
        },
        "function": {
            "type": "string",
            "pattern": "^[a-z][a-z0-9_.]*$",
            "description": "Python 函数点路径（如 my_module.my_func），需已在注册表中注册",
        },
        "args": {
            "type": "object",
            "description": "传给函数的关键字参数，值支持 Jinja2 变量插值",
        },
    },
}

# Tool 节点 JSON Schema（oneOf HTTP|Python）
TOOL_NODE_SCHEMA: dict = {
    "oneOf": [TOOL_HTTP_SCHEMA, TOOL_PYTHON_SCHEMA],
    "description": "Tool 节点配置，kind 字段决定类型：http 或 python",
}

# Tool 节点输出字段
# HTTP: output（响应体）+ status_code（HTTP 状态码）
# Python: output（函数返回值）+ result（同 output，兼容别名）
TOOL_OUTPUT_FIELDS: frozenset[str] = frozenset({
    "output",       # 通用输出字段（HTTP 响应体 / Python 函数返回值）
    "status_code",  # HTTP 状态码（仅 HTTP 类型有效）
    "result",       # Python 函数结果别名（兼容）
})
