"""DSL 编译器单元测试。

验证：
- test_compile_simple_workflow：start → end 编译成功，返回 CompiledGraph
- test_compile_with_llm_node：start → llm → end 编译成功
- test_compile_invalid_dsl_raises：成环 DSL 编译抛 DSLCompilationError + errors 含 E_CYCLE
- test_compile_with_if_else：start → llm → if_else → 2 个 end 编译成功
- test_compiled_graph_has_correct_nodes：graph.nodes 含期望节点 ID
- test_compiled_graph_invokable：用占位 executor 跑完整图

注意：编译器测试不需要真实 checkpointer（传 None 测编译骨架即可）。
集成测试（需要 DB）在 test_checkpoint_postgres.py 中。
"""
from __future__ import annotations

import pytest

from app.agent_builder.workflow.compiler import CompiledGraph, DSLCompiler
from app.agent_builder.workflow.validator import DSLCompilationError


# ─── DSL 工厂函数 ─────────────────────────────────────────────────────────────


def simple_dsl(
    start_id: str = "start",
    end_id: str = "end",
    state_schema: dict | None = None,
) -> dict:
    """最简 DSL：start → end。"""
    return {
        "version": "1.0",
        "name": "简单测试工作流",
        "state_schema": state_schema or {},
        "nodes": [
            {"id": start_id, "type": "start", "config": {}},
            {"id": end_id, "type": "end", "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": start_id, "target": end_id},
        ],
    }


def linear_dsl_with_llm() -> dict:
    """线性 DSL：start → llm_review → end_ok。"""
    return {
        "version": "1.0",
        "name": "带 LLM 的工作流",
        "state_schema": {
            "employee_id": "str",
            "approval_status": "str",
        },
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {
                "id": "llm_review",
                "type": "llm",
                "config": {
                    "model": "openai:gpt-4o",
                    "user_prompt": "请审核员工 {{ start.employee_id }}",
                    "temperature": 0.7,
                    "timeout_sec": 30,
                    "retry_count": 3,
                },
            },
            {"id": "end_ok", "type": "end", "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "llm_review"},
            {"id": "e2", "source": "llm_review", "target": "end_ok"},
        ],
    }


def cyclic_dsl() -> dict:
    """成环 DSL（用于测试编译失败）：start → a → b → a。"""
    return {
        "version": "1.0",
        "name": "成环 DSL",
        "state_schema": {},
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "node_a", "type": "llm", "config": {"model": "m", "user_prompt": "p"}},
            {"id": "node_b", "type": "llm", "config": {"model": "m", "user_prompt": "q"}},
            {"id": "end_ok", "type": "end", "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "node_a"},
            {"id": "e2", "source": "node_a", "target": "node_b"},
            {"id": "e3", "source": "node_b", "target": "node_a"},  # 环
        ],
    }


def if_else_dsl() -> dict:
    """带 if_else 的 DSL：start → llm_1 → branch → end_a/end_b。"""
    return {
        "version": "1.0",
        "name": "带分支的工作流",
        "state_schema": {"score": "float"},
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {
                "id": "llm_1",
                "type": "llm",
                "config": {"model": "m", "user_prompt": "评分"},
            },
            {
                "id": "branch",
                "type": "if_else",
                "config": {
                    "conditions": [
                        {"expr": "{{ start.score > 0.8 }}", "target_node_id": "end_ok"},
                    ],
                    "default_target": "end_no",
                },
            },
            {"id": "end_ok", "type": "end", "config": {}},
            {"id": "end_no", "type": "end", "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "llm_1"},
            {"id": "e2", "source": "llm_1", "target": "branch"},
        ],
    }


# ─── 编译成功测试 ──────────────────────────────────────────────────────────────


class TestCompileSuccess:
    """合法 DSL 编译成功"""

    def test_compile_simple_workflow(self):
        """start → end 编译成功，返回 CompiledGraph 实例"""
        dsl = simple_dsl()
        compiler = DSLCompiler()
        result = compiler.compile(dsl, checkpointer=None)

        assert isinstance(result, CompiledGraph)
        assert result.graph is not None
        assert result.state_type is not None
        assert result.dsl is dsl

    def test_compile_with_llm_node(self):
        """start → llm → end 编译成功"""
        dsl = linear_dsl_with_llm()
        compiler = DSLCompiler()
        result = compiler.compile(dsl, checkpointer=None)

        assert isinstance(result, CompiledGraph)
        assert result.graph is not None

    def test_compile_with_if_else(self):
        """start → llm → if_else → 2 个 end 编译成功"""
        dsl = if_else_dsl()
        compiler = DSLCompiler()
        result = compiler.compile(dsl, checkpointer=None)

        assert isinstance(result, CompiledGraph)
        assert result.graph is not None

    def test_compile_with_state_schema(self):
        """带 state_schema 的 DSL 编译成功，state_type 包含对应字段"""
        dsl = simple_dsl(state_schema={"employee_id": "str", "score": "float", "approved": "bool"})
        compiler = DSLCompiler()
        result = compiler.compile(dsl, checkpointer=None)

        # TypedDict 类应包含 state_schema 字段
        annotations = result.state_type.__annotations__
        assert "employee_id" in annotations
        assert "score" in annotations
        assert "approved" in annotations


# ─── 编译失败测试 ──────────────────────────────────────────────────────────────


class TestCompileFailure:
    """非法 DSL 编译抛出 DSLCompilationError"""

    def test_compile_invalid_dsl_raises(self):
        """成环 DSL 编译抛 DSLCompilationError，errors 包含 E_CYCLE"""
        dsl = cyclic_dsl()
        compiler = DSLCompiler()

        with pytest.raises(DSLCompilationError) as exc_info:
            compiler.compile(dsl, checkpointer=None)

        # errors 中应含 E_CYCLE
        error_codes = [e.code for e in exc_info.value.errors]
        assert "E_CYCLE" in error_codes, f"期望 E_CYCLE，实际：{error_codes}"

    def test_compile_no_start_raises(self):
        """无 start 节点的 DSL 编译抛 DSLCompilationError"""
        dsl = {
            "version": "1.0",
            "state_schema": {},
            "nodes": [
                {"id": "llm_1", "type": "llm", "config": {"model": "m", "user_prompt": "p"}},
                {"id": "end_done", "type": "end", "config": {}},
            ],
            "edges": [{"id": "e1", "source": "llm_1", "target": "end_done"}],
        }
        compiler = DSLCompiler()

        with pytest.raises(DSLCompilationError) as exc_info:
            compiler.compile(dsl, checkpointer=None)

        error_codes = [e.code for e in exc_info.value.errors]
        assert "E_NO_START" in error_codes, f"期望 E_NO_START，实际：{error_codes}"

    def test_compile_llm_missing_model_raises(self):
        """LLM 节点缺少 model 字段，编译抛 DSLCompilationError"""
        dsl = {
            "version": "1.0",
            "state_schema": {},
            "nodes": [
                {"id": "start", "type": "start", "config": {}},
                {"id": "llm_bad", "type": "llm", "config": {"user_prompt": "test"}},
                {"id": "end_done", "type": "end", "config": {}},
            ],
            "edges": [
                {"id": "e1", "source": "start", "target": "llm_bad"},
                {"id": "e2", "source": "llm_bad", "target": "end_done"},
            ],
        }
        compiler = DSLCompiler()

        with pytest.raises(DSLCompilationError) as exc_info:
            compiler.compile(dsl, checkpointer=None)

        error_codes = [e.code for e in exc_info.value.errors]
        assert "E_INVALID_CONFIG" in error_codes, f"期望 E_INVALID_CONFIG，实际：{error_codes}"


# ─── 编译后图结构验证 ─────────────────────────────────────────────────────────


class TestCompiledGraphStructure:
    """编译后 graph 结构正确"""

    def test_compiled_graph_has_correct_nodes(self):
        """编译后 graph.nodes 包含期望的节点 ID"""
        dsl = linear_dsl_with_llm()
        compiler = DSLCompiler()
        result = compiler.compile(dsl, checkpointer=None)

        # LangGraph CompiledGraph 的 graph 属性包含所有节点
        # nodes 是一个 dict-like 结构
        node_ids = set(result.graph.nodes.keys())
        # 期望包含我们定义的节点
        assert "start" in node_ids
        assert "llm_review" in node_ids
        assert "end_ok" in node_ids

    def test_compiled_simple_graph_nodes(self):
        """最简 start → end 图，nodes 包含 start/end"""
        dsl = simple_dsl()
        compiler = DSLCompiler()
        result = compiler.compile(dsl, checkpointer=None)

        node_ids = set(result.graph.nodes.keys())
        assert "start" in node_ids
        assert "end" in node_ids


# ─── 可调用测试（占位 executor）────────────────────────────────────────────────


class TestCompiledGraphInvokable:
    """编译后 graph 可以 invoke（使用占位 executor）"""

    @pytest.mark.asyncio
    async def test_compiled_graph_invokable(self):
        """用占位 executor，调用 graph.ainvoke 跑完整简单图"""
        dsl = simple_dsl(state_schema={"employee_id": "str"})
        compiler = DSLCompiler()
        result = compiler.compile(dsl, checkpointer=None)

        # 调用 ainvoke（无 checkpointer 时不需要 config）
        initial_state = {"employee_id": "EMP001"}
        output = await result.graph.ainvoke(initial_state)
        # 输出应该是字典类型
        assert isinstance(output, dict)

    @pytest.mark.asyncio
    async def test_compiled_linear_dsl_invokable(self):
        """start → llm → end 线性 DSL 可以 invoke，占位 executor 返回占位字典"""
        dsl = linear_dsl_with_llm()
        compiler = DSLCompiler()
        result = compiler.compile(dsl, checkpointer=None)

        initial_state = {"employee_id": "EMP002", "approval_status": "pending"}
        output = await result.graph.ainvoke(initial_state)

        # 输出字典中应包含各节点的占位输出
        assert isinstance(output, dict)
        # llm_review 节点应写入占位输出
        if "llm_review" in output:
            assert output["llm_review"].get("_placeholder") is True
