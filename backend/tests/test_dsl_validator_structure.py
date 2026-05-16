"""DSL 验证器 — 结构类错误（Category 1）单元测试。

验证 10 类结构错误全部被正确识别：
- E_CYCLE: 节点连成环
- E_UNREACHABLE_END: end 节点从 start 不可达
- E_DANGLING_EDGE: 边指向不存在节点
- E_DUPLICATE_NODE_ID: 节点 ID 重复
- E_START_HAS_INBOUND: start 节点有入边
- E_END_HAS_OUTBOUND: end 节点有出边
- E_NO_START: 无 start 节点
- E_NO_END: 无 end 节点
- E_MULTIPLE_START: 多个 start 节点
- E_ORPHAN_NODE: 孤立节点
"""
from __future__ import annotations

import pytest

from app.agent_builder.workflow.validator import DSLValidator, ValidationError


def make_dsl(
    nodes: list[dict],
    edges: list[dict],
    state_schema: dict | None = None,
    name: str = "测试工作流",
) -> dict:
    """构造最小 DSL dict，避免每个测试重复写 version/state_schema。"""
    return {
        "version": "1.0",
        "name": name,
        "state_schema": state_schema or {},
        "nodes": nodes,
        "edges": edges,
    }


def get_error_codes(errors: list[ValidationError]) -> list[str]:
    """提取错误代码列表。"""
    return [e.code for e in errors]


def has_error(errors: list[ValidationError], code: str) -> bool:
    """检查错误列表中是否包含指定错误代码。"""
    return code in get_error_codes(errors)


# ─── 基础节点工厂 ────────────────────────────────────────────────────────────


def start_node(nid: str = "start") -> dict:
    return {"id": nid, "type": "start", "config": {}}


def end_node(nid: str = "end") -> dict:
    return {"id": nid, "type": "end", "config": {}}


def llm_node(nid: str = "llm_1") -> dict:
    return {
        "id": nid,
        "type": "llm",
        "config": {"model": "openai:gpt-4o", "user_prompt": "hello"},
    }


def edge(eid: str, src: str, tgt: str) -> dict:
    return {"id": eid, "source": src, "target": tgt}


# ─── 成环检测 ────────────────────────────────────────────────────────────────


class TestCycleDetection:
    """E_CYCLE 检测"""

    def test_cycle_detected_two_nodes(self):
        """两节点互相指向 a→b→a 形成环，应报 E_CYCLE"""
        # 注意：需要有合法的 start + end，成环在中间
        # 因为 JSON Schema 要求 nodes 里面每个节点类型必须是合法的
        # 这里用 start→a→b→a 形成局部环 + end 不可达（E_UNREACHABLE_END）
        nodes = [
            start_node(),
            {"id": "node_a", "type": "llm", "config": {"model": "m", "user_prompt": "p"}},
            {"id": "node_b", "type": "llm", "config": {"model": "m", "user_prompt": "p"}},
            end_node(),
        ]
        edges = [
            edge("e1", "start", "node_a"),
            edge("e2", "node_a", "node_b"),
            edge("e3", "node_b", "node_a"),  # 形成环
        ]
        dsl = make_dsl(nodes, edges)
        errors = DSLValidator().validate(dsl)
        assert has_error(errors, "E_CYCLE"), f"期望 E_CYCLE，实际：{get_error_codes(errors)}"

    def test_no_cycle_linear_dag(self):
        """线性 DAG 不报成环错误"""
        nodes = [start_node(), llm_node(), end_node()]
        edges_list = [edge("e1", "start", "llm_1"), edge("e2", "llm_1", "end")]
        dsl = make_dsl(nodes, edges_list)
        errors = DSLValidator().validate(dsl)
        assert not has_error(errors, "E_CYCLE"), f"不应有 E_CYCLE，实际：{get_error_codes(errors)}"


# ─── 不可达 end ──────────────────────────────────────────────────────────────


class TestUnreachableEnd:
    """E_UNREACHABLE_END 检测"""

    def test_unreachable_end_node(self):
        """存在两个 end 节点，其中一个从 start 不可达，应报 E_UNREACHABLE_END"""
        nodes = [
            start_node(),
            llm_node(),
            end_node("end_ok"),
            end_node("end_orphan"),  # 没有边指向它
        ]
        edges_list = [
            edge("e1", "start", "llm_1"),
            edge("e2", "llm_1", "end_ok"),
        ]
        dsl = make_dsl(nodes, edges_list)
        errors = DSLValidator().validate(dsl)
        assert has_error(errors, "E_UNREACHABLE_END"), (
            f"期望 E_UNREACHABLE_END，实际：{get_error_codes(errors)}"
        )


# ─── 悬空边 ──────────────────────────────────────────────────────────────────


class TestDanglingEdge:
    """E_DANGLING_EDGE 检测"""

    def test_dangling_edge_source_not_exist(self):
        """边的 source 节点不存在，应报 E_DANGLING_EDGE"""
        nodes = [start_node(), end_node()]
        edges_list = [
            edge("e1", "start", "end"),
            edge("e2", "ghost_node", "end"),  # ghost_node 不存在
        ]
        dsl = make_dsl(nodes, edges_list)
        errors = DSLValidator().validate(dsl)
        assert has_error(errors, "E_DANGLING_EDGE"), (
            f"期望 E_DANGLING_EDGE，实际：{get_error_codes(errors)}"
        )

    def test_dangling_edge_target_not_exist(self):
        """边的 target 节点不存在，应报 E_DANGLING_EDGE"""
        nodes = [start_node(), end_node()]
        edges_list = [
            edge("e1", "start", "nowhere"),  # nowhere 不存在
        ]
        dsl = make_dsl(nodes, edges_list)
        errors = DSLValidator().validate(dsl)
        assert has_error(errors, "E_DANGLING_EDGE"), (
            f"期望 E_DANGLING_EDGE，实际：{get_error_codes(errors)}"
        )


# ─── 重复节点 ID ─────────────────────────────────────────────────────────────


class TestDuplicateNodeId:
    """E_DUPLICATE_NODE_ID 检测"""

    def test_duplicate_node_id(self):
        """两个 id='llm_1' 的节点，应报 E_DUPLICATE_NODE_ID"""
        nodes = [
            start_node(),
            {"id": "llm_1", "type": "llm", "config": {"model": "m", "user_prompt": "p"}},
            {"id": "llm_1", "type": "llm", "config": {"model": "m", "user_prompt": "q"}},
            end_node(),
        ]
        edges_list = [
            edge("e1", "start", "llm_1"),
            edge("e2", "llm_1", "end"),
        ]
        dsl = make_dsl(nodes, edges_list)
        errors = DSLValidator().validate(dsl)
        assert has_error(errors, "E_DUPLICATE_NODE_ID"), (
            f"期望 E_DUPLICATE_NODE_ID，实际：{get_error_codes(errors)}"
        )


# ─── Start/End 边约束 ─────────────────────────────────────────────────────────


class TestStartEndEdgeConstraints:
    """E_START_HAS_INBOUND / E_END_HAS_OUTBOUND 检测"""

    def test_start_has_inbound(self):
        """start 节点有入边，应报 E_START_HAS_INBOUND"""
        nodes = [start_node(), llm_node(), end_node()]
        edges_list = [
            edge("e1", "start", "llm_1"),
            edge("e2", "llm_1", "end"),
            edge("e3", "llm_1", "start"),  # start 节点入边
        ]
        dsl = make_dsl(nodes, edges_list)
        errors = DSLValidator().validate(dsl)
        assert has_error(errors, "E_START_HAS_INBOUND"), (
            f"期望 E_START_HAS_INBOUND，实际：{get_error_codes(errors)}"
        )

    def test_end_has_outbound(self):
        """end 节点有出边，应报 E_END_HAS_OUTBOUND"""
        nodes = [start_node(), llm_node(), end_node()]
        edges_list = [
            edge("e1", "start", "llm_1"),
            edge("e2", "llm_1", "end"),
            edge("e3", "end", "llm_1"),  # end 节点出边
        ]
        dsl = make_dsl(nodes, edges_list)
        errors = DSLValidator().validate(dsl)
        assert has_error(errors, "E_END_HAS_OUTBOUND"), (
            f"期望 E_END_HAS_OUTBOUND，实际：{get_error_codes(errors)}"
        )


# ─── Start/End 存在性 ─────────────────────────────────────────────────────────


class TestStartEndExistence:
    """E_NO_START / E_NO_END / E_MULTIPLE_START 检测"""

    def test_no_start_node(self):
        """无 start 节点，应报 E_NO_START"""
        nodes = [
            llm_node(),
            end_node(),
        ]
        edges_list = [edge("e1", "llm_1", "end")]
        dsl = make_dsl(nodes, edges_list)
        errors = DSLValidator().validate(dsl)
        assert has_error(errors, "E_NO_START"), (
            f"期望 E_NO_START，实际：{get_error_codes(errors)}"
        )

    def test_no_end_node(self):
        """无 end 节点，应报 E_NO_END"""
        nodes = [
            start_node(),
            llm_node(),
        ]
        edges_list = [edge("e1", "start", "llm_1")]
        dsl = make_dsl(nodes, edges_list)
        errors = DSLValidator().validate(dsl)
        assert has_error(errors, "E_NO_END"), (
            f"期望 E_NO_END，实际：{get_error_codes(errors)}"
        )

    def test_multiple_start_nodes(self):
        """两个 start 节点，应报 E_MULTIPLE_START"""
        nodes = [
            start_node("start_a"),
            start_node("start_b"),
            end_node(),
        ]
        edges_list = [
            edge("e1", "start_a", "end"),
            edge("e2", "start_b", "end"),
        ]
        dsl = make_dsl(nodes, edges_list)
        errors = DSLValidator().validate(dsl)
        assert has_error(errors, "E_MULTIPLE_START"), (
            f"期望 E_MULTIPLE_START，实际：{get_error_codes(errors)}"
        )


# ─── 孤立节点 ────────────────────────────────────────────────────────────────


class TestOrphanNode:
    """E_ORPHAN_NODE 检测"""

    def test_orphan_node(self):
        """孤立节点（无入边无出边且不是 start），应报 E_ORPHAN_NODE（warning）"""
        nodes = [
            start_node(),
            llm_node("llm_isolated"),  # 孤立节点
            end_node(),
        ]
        edges_list = [edge("e1", "start", "end")]
        dsl = make_dsl(nodes, edges_list)
        errors = DSLValidator().validate(dsl)
        orphan_errors = [e for e in errors if e.code == "E_ORPHAN_NODE"]
        assert len(orphan_errors) > 0, (
            f"期望 E_ORPHAN_NODE，实际：{get_error_codes(errors)}"
        )
        # 孤立节点是 warning 级别
        assert all(e.severity == "warning" for e in orphan_errors)


# ─── 合法 DSL（无错误）────────────────────────────────────────────────────────


class TestValidStructure:
    """合法结构不报错"""

    def test_simple_linear_dag_passes(self):
        """start → llm → end 线性 DAG，无结构错误"""
        nodes = [start_node(), llm_node(), end_node()]
        edges_list = [edge("e1", "start", "llm_1"), edge("e2", "llm_1", "end")]
        dsl = make_dsl(nodes, edges_list)
        errors = DSLValidator().validate(dsl)
        fatal = [e for e in errors if e.severity == "error"]
        assert len(fatal) == 0, f"不应有 error，实际：{[(e.code, e.message) for e in fatal]}"

    def test_multiple_end_nodes_passes(self):
        """start → if_else → end_a / end_b，两个 end 都可达"""
        nodes = [
            start_node(),
            {
                "id": "branch",
                "type": "if_else",
                "config": {
                    "conditions": [{"expr": "{{ x > 0 }}", "target_node_id": "end_a"}],
                    "default_target": "end_b",
                },
            },
            end_node("end_a"),
            end_node("end_b"),
        ]
        edges_list = [edge("e1", "start", "branch")]
        dsl = make_dsl(nodes, edges_list, state_schema={"x": "int"})
        errors = DSLValidator().validate(dsl)
        fatal = [e for e in errors if e.severity == "error"]
        assert len(fatal) == 0, f"不应有 error，实际：{[(e.code, e.message) for e in fatal]}"
