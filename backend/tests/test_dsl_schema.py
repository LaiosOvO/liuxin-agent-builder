"""DSL JSON Schema 单元测试。

验证：
- 合法 DSL 通过 jsonschema.validate
- 非法版本、节点类型、节点 ID 等被正确拦截
- 各节点 schema 约束生效（LLM oneOf / IfElse 必填字段等）
"""
from __future__ import annotations

import pytest
import jsonschema

from app.agent_builder.workflow.schema import DSL_SCHEMA, DSL_VERSION, RESERVED_NODE_IDS
from app.agent_builder.workflow.node_schemas import NODE_SCHEMAS, get_node_schema, get_node_output_fields


# ─── 基础合法 DSL 用于各测试复用 ───────────────────────────────────────────────
VALID_DSL = {
    "version": "1.0",
    "name": "测试工作流",
    "state_schema": {
        "employee_id": "str",
        "department": "str",
        "approval_status": "str",
    },
    "nodes": [
        {
            "id": "start",
            "type": "start",
            "position": {"x": 100.0, "y": 200.0},
            "config": {},
        },
        {
            "id": "llm_review",
            "type": "llm",
            "position": {"x": 300.0, "y": 200.0},
            "config": {
                "model": "openai:gpt-4o",
                "user_prompt": "请审核 {{ start.employee_id }}",
                "temperature": 0.7,
                "timeout_sec": 30,
                "retry_count": 3,
                "backoff_base_sec": 1,
            },
        },
        {
            "id": "end_ok",
            "type": "end",
            "position": {"x": 700.0, "y": 100.0},
            "config": {},
        },
    ],
    "edges": [
        {"id": "e1", "source": "start", "target": "llm_review"},
        {"id": "e2", "source": "llm_review", "target": "end_ok"},
    ],
}


class TestValidDsl:
    """合法 DSL 通过 schema 验证"""

    def test_valid_dsl_passes_schema(self):
        """示例 DSL 通过 jsonschema.validate，无异常"""
        # 不应抛出任何异常
        jsonschema.validate(VALID_DSL, DSL_SCHEMA)

    def test_dsl_version_constant(self):
        """DSL_VERSION 常量值为 '1.0'"""
        assert DSL_VERSION == "1.0"

    def test_reserved_node_ids_contains_state(self):
        """保留 ID 集合包含 'state' / 'event' / '__ptr__' 等关键字"""
        assert "state" in RESERVED_NODE_IDS
        assert "event" in RESERVED_NODE_IDS
        assert "__ptr__" in RESERVED_NODE_IDS


class TestInvalidVersion:
    """非法版本号被拦截"""

    def test_invalid_version_fails(self):
        """version='0.9' 不符合 const='1.0'，应抛 ValidationError"""
        bad_dsl = {**VALID_DSL, "version": "0.9"}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad_dsl, DSL_SCHEMA)

    def test_missing_version_fails(self):
        """缺少 version 字段，应抛 ValidationError"""
        bad_dsl = {k: v for k, v in VALID_DSL.items() if k != "version"}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad_dsl, DSL_SCHEMA)


class TestInvalidNodeType:
    """非法节点类型被拦截"""

    def test_invalid_node_type_fails(self):
        """type='custom' 不在枚举中，应抛 ValidationError"""
        bad_nodes = list(VALID_DSL["nodes"])
        bad_nodes[0] = {**bad_nodes[0], "type": "custom"}
        bad_dsl = {**VALID_DSL, "nodes": bad_nodes}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad_dsl, DSL_SCHEMA)


class TestInvalidNodeIdPattern:
    """非法节点 ID 格式被拦截"""

    def test_invalid_node_id_uppercase_fails(self):
        """id='StartNode' 含大写字母，不符合 pattern，应抛 ValidationError"""
        bad_nodes = list(VALID_DSL["nodes"])
        bad_nodes[0] = {**bad_nodes[0], "id": "StartNode"}
        bad_dsl = {**VALID_DSL, "nodes": bad_nodes}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad_dsl, DSL_SCHEMA)

    def test_invalid_node_id_starts_with_digit_fails(self):
        """id='1start' 以数字开头，不符合 pattern，应抛 ValidationError"""
        bad_nodes = list(VALID_DSL["nodes"])
        bad_nodes[0] = {**bad_nodes[0], "id": "1start"}
        bad_dsl = {**VALID_DSL, "nodes": bad_nodes}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad_dsl, DSL_SCHEMA)


class TestLlmNodeSchema:
    """LLM 节点 schema 约束"""

    def test_llm_node_requires_user_or_raw_prompt(self):
        """LLM 节点 config 只有 model，缺少 user_prompt 或 raw_prompt，
        jsonschema 不会在顶层 DSL_SCHEMA 拦截（config 类型为 object），
        但节点级 LLM_NODE_SCHEMA 应拦截。"""
        from app.agent_builder.workflow.node_schemas.llm import LLM_NODE_SCHEMA
        # config 只有 model，未满足 oneOf（user_prompt 或 raw_prompt）
        bad_config = {"model": "openai:gpt-4o"}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad_config, LLM_NODE_SCHEMA)

    def test_llm_node_valid_with_user_prompt(self):
        """LLM 节点 config 含 user_prompt，通过 LLM_NODE_SCHEMA 验证"""
        from app.agent_builder.workflow.node_schemas.llm import LLM_NODE_SCHEMA
        config = {"model": "openai:gpt-4o", "user_prompt": "请回答：{{ start.question }}"}
        jsonschema.validate(config, LLM_NODE_SCHEMA)

    def test_llm_node_invalid_temperature_fails(self):
        """temperature=3.5 超过最大值 2，应被拦截"""
        from app.agent_builder.workflow.node_schemas.llm import LLM_NODE_SCHEMA
        config = {"model": "openai:gpt-4o", "user_prompt": "test", "temperature": 3.5}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(config, LLM_NODE_SCHEMA)


class TestIfElseNodeSchema:
    """IfElse 节点 schema 约束"""

    def test_if_else_node_requires_default_target(self):
        """IfElse 节点缺 default_target，应抛 ValidationError"""
        from app.agent_builder.workflow.node_schemas.if_else import IF_ELSE_NODE_SCHEMA
        bad_config = {
            "conditions": [
                {"expr": "{{ x > 0 }}", "target_node_id": "end_ok"},
            ],
            # 缺 default_target
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad_config, IF_ELSE_NODE_SCHEMA)

    def test_if_else_node_requires_at_least_one_condition(self):
        """IfElse 节点 conditions 为空列表，应抛 ValidationError（minItems=1）"""
        from app.agent_builder.workflow.node_schemas.if_else import IF_ELSE_NODE_SCHEMA
        bad_config = {
            "conditions": [],
            "default_target": "end_no",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad_config, IF_ELSE_NODE_SCHEMA)


class TestNodeSchemasRegistry:
    """节点 Schema 注册表功能"""

    def test_all_node_types_registered(self):
        """所有 5 种节点类型都在 NODE_SCHEMAS 中注册"""
        expected = {"start", "end", "llm", "tool", "if_else"}
        assert set(NODE_SCHEMAS.keys()) == expected

    def test_get_node_schema_returns_dict(self):
        """get_node_schema 返回 dict 类型"""
        schema = get_node_schema("llm")
        assert isinstance(schema, dict)

    def test_get_node_output_fields_llm(self):
        """LLM 节点输出字段包含 message/role/usage/model"""
        fields = get_node_output_fields("llm")
        assert "message" in fields
        assert "role" in fields
        assert "usage" in fields
        assert "model" in fields

    def test_get_node_output_fields_end_is_empty(self):
        """End 节点输出字段为空集"""
        fields = get_node_output_fields("end")
        assert len(fields) == 0

    def test_get_unknown_node_type_raises(self):
        """查询未知节点类型应抛 KeyError"""
        with pytest.raises(KeyError):
            get_node_schema("unknown_type")
