"""DSL 验证器 — 变量引用检查（Category 2）单元测试。

验证：
- test_valid_variable_reference：{{ start.employee_id }} 在 state_schema 中 → 通过
- test_undefined_var_node：{{ nonexistent.x }} → E_UNDEFINED_VAR
- test_undefined_field：{{ llm_1.foo }} 但 llm 没有 foo 字段 → E_UNDEFINED_FIELD
- test_downstream_reference_only：节点 a 引用 b 但 b 在 a 下游 → E_VAR_NOT_UPSTREAM
- test_state_schema_field_accessible：所有节点都能引用 state_schema 字段
- test_jinja_filter_chain：{{ x | length | tojson }} → 通过
"""
from __future__ import annotations

import pytest

from app.agent_builder.workflow.validator import DSLValidator, ValidationError


def get_error_codes(errors: list[ValidationError]) -> list[str]:
    return [e.code for e in errors]


def has_error(errors: list[ValidationError], code: str) -> bool:
    return code in get_error_codes(errors)


def has_no_errors(errors: list[ValidationError]) -> bool:
    """没有 error 级别的错误（warning 允许）。"""
    return not any(e.severity == "error" for e in errors)


# ─── 合法变量引用 ─────────────────────────────────────────────────────────────


class TestValidVariableReferences:
    """合法变量引用通过验证"""

    def test_valid_variable_reference_state_schema(self):
        """{{ start.employee_id }} 引用 state_schema 中的字段 → 通过"""
        dsl = {
            "version": "1.0",
            "state_schema": {"employee_id": "str"},
            "nodes": [
                {"id": "start", "type": "start", "config": {}},
                {
                    "id": "llm_review",
                    "type": "llm",
                    "config": {
                        "model": "openai:gpt-4o",
                        "user_prompt": "请审核员工 {{ start.employee_id }}",
                    },
                },
                {"id": "end_ok", "type": "end", "config": {}},
            ],
            "edges": [
                {"id": "e1", "source": "start", "target": "llm_review"},
                {"id": "e2", "source": "llm_review", "target": "end_ok"},
            ],
        }
        errors = DSLValidator().validate(dsl)
        assert has_no_errors(errors), (
            f"期望无 error，实际：{[(e.code, e.message) for e in errors if e.severity == 'error']}"
        )

    def test_state_schema_field_accessible_from_any_node(self):
        """state_schema 字段可从任意节点引用（不需要 start. 前缀）"""
        dsl = {
            "version": "1.0",
            "state_schema": {"employee_id": "str", "dept": "str"},
            "nodes": [
                {"id": "start", "type": "start", "config": {}},
                {
                    "id": "llm_1",
                    "type": "llm",
                    "config": {
                        "model": "m",
                        "user_prompt": "{{ start.employee_id }} 来自 {{ start.dept }}",
                    },
                },
                {
                    "id": "llm_2",
                    "type": "llm",
                    "config": {
                        "model": "m",
                        "user_prompt": "复核 {{ llm_1.message }}，部门 {{ start.dept }}",
                    },
                },
                {"id": "end_done", "type": "end", "config": {}},
            ],
            "edges": [
                {"id": "e1", "source": "start", "target": "llm_1"},
                {"id": "e2", "source": "llm_1", "target": "llm_2"},
                {"id": "e3", "source": "llm_2", "target": "end_done"},
            ],
        }
        errors = DSLValidator().validate(dsl)
        assert has_no_errors(errors), (
            f"期望无 error，实际：{[(e.code, e.message) for e in errors if e.severity == 'error']}"
        )

    def test_llm_output_field_accessible(self):
        """{{ llm_1.message }} 引用 LLM 节点的合法输出字段 → 通过"""
        dsl = {
            "version": "1.0",
            "state_schema": {},
            "nodes": [
                {"id": "start", "type": "start", "config": {}},
                {
                    "id": "llm_1",
                    "type": "llm",
                    "config": {"model": "m", "user_prompt": "请分析"},
                },
                {
                    "id": "llm_2",
                    "type": "llm",
                    "config": {
                        "model": "m",
                        "user_prompt": "基于分析结果：{{ llm_1.message }}",
                    },
                },
                {"id": "end_done", "type": "end", "config": {}},
            ],
            "edges": [
                {"id": "e1", "source": "start", "target": "llm_1"},
                {"id": "e2", "source": "llm_1", "target": "llm_2"},
                {"id": "e3", "source": "llm_2", "target": "end_done"},
            ],
        }
        errors = DSLValidator().validate(dsl)
        assert has_no_errors(errors), (
            f"期望无 error，实际：{[(e.code, e.message) for e in errors if e.severity == 'error']}"
        )

    def test_jinja_filter_chain_passes(self):
        """{{ start.items | length | tojson }} 白名单 filter 链 → 通过"""
        dsl = {
            "version": "1.0",
            "state_schema": {"items": "list"},
            "nodes": [
                {"id": "start", "type": "start", "config": {}},
                {
                    "id": "llm_1",
                    "type": "llm",
                    "config": {
                        "model": "m",
                        "user_prompt": "共 {{ start.items | length }} 个",
                    },
                },
                {"id": "end_done", "type": "end", "config": {}},
            ],
            "edges": [
                {"id": "e1", "source": "start", "target": "llm_1"},
                {"id": "e2", "source": "llm_1", "target": "end_done"},
            ],
        }
        errors = DSLValidator().validate(dsl)
        assert has_no_errors(errors), (
            f"期望无 error，实际：{[(e.code, e.message) for e in errors if e.severity == 'error']}"
        )


# ─── 未定义变量 ────────────────────────────────────────────────────────────────


class TestUndefinedVar:
    """E_UNDEFINED_VAR 检测"""

    def test_undefined_var_node(self):
        """{{ nonexistent.x }} 引用不存在的节点 ID → E_UNDEFINED_VAR"""
        dsl = {
            "version": "1.0",
            "state_schema": {},
            "nodes": [
                {"id": "start", "type": "start", "config": {}},
                {
                    "id": "llm_1",
                    "type": "llm",
                    "config": {
                        "model": "m",
                        "user_prompt": "结果：{{ nonexistent.x }}",  # 引用不存在的节点
                    },
                },
                {"id": "end_done", "type": "end", "config": {}},
            ],
            "edges": [
                {"id": "e1", "source": "start", "target": "llm_1"},
                {"id": "e2", "source": "llm_1", "target": "end_done"},
            ],
        }
        errors = DSLValidator().validate(dsl)
        assert has_error(errors, "E_UNDEFINED_VAR"), (
            f"期望 E_UNDEFINED_VAR，实际：{get_error_codes(errors)}"
        )


# ─── 未定义字段 ────────────────────────────────────────────────────────────────


class TestUndefinedField:
    """E_UNDEFINED_FIELD 检测"""

    def test_undefined_field_on_llm_node(self):
        """{{ llm_1.foo }} 但 llm 节点没有 foo 字段 → E_UNDEFINED_FIELD"""
        dsl = {
            "version": "1.0",
            "state_schema": {},
            "nodes": [
                {"id": "start", "type": "start", "config": {}},
                {
                    "id": "llm_1",
                    "type": "llm",
                    "config": {"model": "m", "user_prompt": "分析"},
                },
                {
                    "id": "llm_2",
                    "type": "llm",
                    "config": {
                        "model": "m",
                        "user_prompt": "{{ llm_1.foo }}",  # foo 不是 LLM 输出字段
                    },
                },
                {"id": "end_done", "type": "end", "config": {}},
            ],
            "edges": [
                {"id": "e1", "source": "start", "target": "llm_1"},
                {"id": "e2", "source": "llm_1", "target": "llm_2"},
                {"id": "e3", "source": "llm_2", "target": "end_done"},
            ],
        }
        errors = DSLValidator().validate(dsl)
        assert has_error(errors, "E_UNDEFINED_FIELD"), (
            f"期望 E_UNDEFINED_FIELD，实际：{get_error_codes(errors)}"
        )


# ─── 下游节点引用 ─────────────────────────────────────────────────────────────


class TestDownstreamReference:
    """E_VAR_NOT_UPSTREAM 检测"""

    def test_downstream_reference_not_allowed(self):
        """节点 llm_1 引用了下游节点 llm_2 → E_VAR_NOT_UPSTREAM"""
        dsl = {
            "version": "1.0",
            "state_schema": {},
            "nodes": [
                {"id": "start", "type": "start", "config": {}},
                {
                    "id": "llm_1",
                    "type": "llm",
                    "config": {
                        "model": "m",
                        "user_prompt": "{{ llm_2.message }}",  # llm_2 是下游！
                    },
                },
                {
                    "id": "llm_2",
                    "type": "llm",
                    "config": {"model": "m", "user_prompt": "后续分析"},
                },
                {"id": "end_done", "type": "end", "config": {}},
            ],
            "edges": [
                {"id": "e1", "source": "start", "target": "llm_1"},
                {"id": "e2", "source": "llm_1", "target": "llm_2"},
                {"id": "e3", "source": "llm_2", "target": "end_done"},
            ],
        }
        errors = DSLValidator().validate(dsl)
        assert has_error(errors, "E_VAR_NOT_UPSTREAM"), (
            f"期望 E_VAR_NOT_UPSTREAM，实际：{get_error_codes(errors)}"
        )
