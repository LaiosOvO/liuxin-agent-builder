"""DSL 验证器模块。

提供：
- ValidationError：单个验证错误数据类（4 类错误通用）
- DSLValidator：一次扫描返回所有错误（不要修一个 error 才发现下一个）
- DSLCompilationError：编译时使用，包装 ValidationError 列表

4 类错误（全部在 validate() 一次调用中返回）：
- Category 1（structural）：DAG 结构错（成环/不可达 end/孤立节点/悬空边/重复 ID 等）
- Category 2（variables）：变量引用悬空（{{ x.y }} x 不在符号表 or y 不在输出字段）
- Category 3（config）：节点配置类型错（不符合各节点 JSON Schema）
- Category 4（special）：特殊规则（if_else 无 default / Start 有入边 / End 有出边等）

设计原则：
- 一次扫描：所有 4 类检查并行收集 errors，不因一类 error 短路
- 拓扑序遍历：变量检查按节点拓扑序，只允许引用上游节点（不允许引用下游）
- 符号表构造：节点 id ∪ state_schema 字段名 → 所有合法的顶层变量
- if_else 条件中 expr 也做变量检查（extract 顶层变量 + filter 链）

错误代码说明：
    E_NO_START            — 无 start 节点
    E_NO_END              — 无 end 节点
    E_MULTIPLE_START      — 超过一个 start 节点
    E_DUPLICATE_NODE_ID   — 节点 ID 重复
    E_DANGLING_EDGE       — 边指向不存在节点
    E_START_HAS_INBOUND   — start 节点有入边
    E_END_HAS_OUTBOUND    — end 节点有出边
    E_ORPHAN_NODE         — 节点孤立（无入无出，除 start 外）
    E_CYCLE               — 节点连成环
    E_UNREACHABLE_END     — end 节点从 start 不可达
    E_INVALID_NODE_ID     — 节点 ID 格式不合规
    E_NODE_ID_RESERVED    — 节点 ID 命中保留字
    E_INVALID_CONFIG      — 节点 config 不符合其 JSON Schema
    E_INVALID_STATE_TYPE  — state_schema 字段类型不在支持列表
    E_IF_ELSE_NO_DEFAULT  — if_else 节点缺 default_target
    E_IF_ELSE_BAD_TARGET  — if_else 条件目标节点不存在
    E_UNDEFINED_VAR       — 模板引用变量不在符号表
    E_UNDEFINED_FIELD     — 模板引用 node_id.field，field 不在该节点输出字段
    E_VAR_NOT_UPSTREAM    — 引用了下游节点（拓扑序检查）
"""
from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass, field as dc_field
from typing import Literal

import jsonschema
from graphlib import TopologicalSorter, CycleError

from app.agent_builder.workflow.jinja_env import build_jinja_env, collect_referenced_variables
from app.agent_builder.workflow.node_schemas import get_node_schema, get_node_output_fields, NODE_SCHEMAS
from app.agent_builder.workflow.schema import DSL_SCHEMA, RESERVED_NODE_IDS
from app.agent_builder.workflow.types import SCHEMA_TYPES

# 节点 ID 合法格式（小写字母开头，仅含小写字母/数字/下划线）
NODE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass
class ValidationError:
    """单个 DSL 验证错误。

    Attributes:
        severity: "error"（阻断执行）或 "warning"（可放行）
        code: 错误代码（如 E_CYCLE）
        message: 中文错误描述
        node_id: 涉及的节点 ID（可选）
        edge_id: 涉及的边 ID（可选）
        field_path: 涉及的字段路径（如 "config.temperature"，可选）
    """

    severity: Literal["error", "warning"]
    code: str
    message: str
    node_id: str | None = None
    edge_id: str | None = None
    field_path: str | None = None

    def to_dict(self) -> dict:
        """序列化为字典（API 响应用）。"""
        result: dict = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }
        if self.node_id is not None:
            result["node_id"] = self.node_id
        if self.edge_id is not None:
            result["edge_id"] = self.edge_id
        if self.field_path is not None:
            result["field_path"] = self.field_path
        return result

    def __repr__(self) -> str:
        parts = [f"{self.code}[{self.severity}]", self.message]
        if self.node_id:
            parts.append(f"node={self.node_id}")
        if self.edge_id:
            parts.append(f"edge={self.edge_id}")
        return " | ".join(parts)


class DSLCompilationError(Exception):
    """DSL 编译失败异常，包含所有验证错误列表。"""

    def __init__(self, errors: list[ValidationError]) -> None:
        self.errors = errors
        codes = [e.code for e in errors]
        super().__init__(f"DSL 编译失败，{len(errors)} 个错误：{codes}")


class DSLValidator:
    """DSL 一次扫描 4 类全检验证器。

    调用方式：
        validator = DSLValidator()
        errors = validator.validate(dsl_dict)
        fatal = [e for e in errors if e.severity == "error"]
        if fatal:
            raise DSLCompilationError(fatal)
    """

    def __init__(self) -> None:
        self._jinja_env = build_jinja_env()

    def validate(self, dsl: dict) -> list[ValidationError]:
        """验证 DSL dict，一次返回所有 4 类错误。

        Args:
            dsl: DSL 原始字典（来自 JSON 解析）

        Returns:
            ValidationError 列表（空列表表示无错误）
            同一次调用可能包含多类错误。
        """
        errors: list[ValidationError] = []

        # Step 1：顶层 JSON Schema 验证（快速拦截结构完全错误的 DSL）
        try:
            jsonschema.validate(dsl, DSL_SCHEMA)
        except jsonschema.ValidationError as e:
            field_path = ".".join(str(p) for p in e.absolute_path) if e.absolute_path else None
            errors.append(ValidationError(
                severity="error",
                code="E_INVALID_DSL",
                message=f"DSL 顶层结构错误：{e.message}",
                field_path=field_path,
            ))
            # 顶层结构错，后续分析无意义
            return errors

        # Step 2：4 类全检（并行收集，不互相短路）
        nodes: list[dict] = dsl.get("nodes", [])
        edges: list[dict] = dsl.get("edges", [])
        state_schema: dict = dsl.get("state_schema", {})

        errors.extend(self._validate_state_schema(state_schema))
        errors.extend(self._validate_node_ids(nodes))
        errors.extend(self._validate_structure(nodes, edges))
        errors.extend(self._validate_node_configs(nodes))
        errors.extend(self._validate_variables(dsl, nodes, edges, state_schema))

        return errors

    # ─── Category 0: state_schema 类型检查 ────────────────────────────────────

    def _validate_state_schema(self, state_schema: dict) -> list[ValidationError]:
        """检查 state_schema 字段类型是否在支持列表中。"""
        errors: list[ValidationError] = []
        for field_name, type_str in state_schema.items():
            if type_str not in SCHEMA_TYPES:
                errors.append(ValidationError(
                    severity="error",
                    code="E_INVALID_STATE_TYPE",
                    message=(
                        f"state_schema 字段 '{field_name}' 的类型 '{type_str}' 不支持，"
                        f"支持的类型：{SCHEMA_TYPES}"
                    ),
                    field_path=f"state_schema.{field_name}",
                ))
        return errors

    # ─── Category 3+4: 节点 ID 格式 + 保留字检查 ─────────────────────────────

    def _validate_node_ids(self, nodes: list[dict]) -> list[ValidationError]:
        """检查节点 ID 格式（pattern）和保留字（reserved）。"""
        errors: list[ValidationError] = []
        for node in nodes:
            nid = node.get("id", "")
            if not NODE_ID_PATTERN.match(nid):
                errors.append(ValidationError(
                    severity="error",
                    code="E_INVALID_NODE_ID",
                    message=f"节点 ID '{nid}' 格式不合规，须满足 ^[a-z][a-z0-9_]*$",
                    node_id=nid,
                ))
            if nid in RESERVED_NODE_IDS:
                errors.append(ValidationError(
                    severity="error",
                    code="E_NODE_ID_RESERVED",
                    message=f"节点 ID '{nid}' 是保留字，不可使用",
                    node_id=nid,
                ))
        return errors

    # ─── Category 1: DAG 结构检查 ─────────────────────────────────────────────

    def _validate_structure(
        self,
        nodes: list[dict],
        edges: list[dict],
    ) -> list[ValidationError]:
        """检查 DAG 结构（全部 7 类结构错误 + 成环 + 不可达 end）。"""
        errors: list[ValidationError] = []

        # 构造节点 ID 集合 + 类型映射
        node_ids: set[str] = set()
        node_type_map: dict[str, str] = {}
        seen_ids: set[str] = set()

        for node in nodes:
            nid = node.get("id", "")
            ntype = node.get("type", "")
            if nid in seen_ids:
                errors.append(ValidationError(
                    severity="error",
                    code="E_DUPLICATE_NODE_ID",
                    message=f"节点 ID '{nid}' 重复，所有节点 ID 必须唯一",
                    node_id=nid,
                ))
            seen_ids.add(nid)
            node_ids.add(nid)
            node_type_map[nid] = ntype

        # 检查 start/end 节点数量
        start_nodes = [n for n in nodes if n.get("type") == "start"]
        end_nodes = [n for n in nodes if n.get("type") == "end"]

        if len(start_nodes) == 0:
            errors.append(ValidationError(
                severity="error",
                code="E_NO_START",
                message="DSL 中没有 start 节点，每个工作流必须有且仅有一个 start 节点",
            ))
        elif len(start_nodes) > 1:
            ids = [n["id"] for n in start_nodes]
            errors.append(ValidationError(
                severity="error",
                code="E_MULTIPLE_START",
                message=f"DSL 中有多个 start 节点（{ids}），每个工作流只能有一个 start 节点",
            ))

        if len(end_nodes) == 0:
            errors.append(ValidationError(
                severity="error",
                code="E_NO_END",
                message="DSL 中没有 end 节点，每个工作流必须至少有一个 end 节点",
            ))

        # 检查边（悬空、Start 入边、End 出边）
        # 同时构造入度/出度 map（用于孤立节点检测）
        inbound: dict[str, list[str]] = defaultdict(list)   # node_id → [source node_ids]
        outbound: dict[str, list[str]] = defaultdict(list)  # node_id → [target node_ids]

        for edge in edges:
            eid = edge.get("id", "")
            src = edge.get("source", "")
            tgt = edge.get("target", "")

            # 悬空边检查
            if src not in node_ids:
                errors.append(ValidationError(
                    severity="error",
                    code="E_DANGLING_EDGE",
                    message=f"边 '{eid}' 的起点 '{src}' 不是合法节点 ID",
                    edge_id=eid,
                    node_id=src,
                ))
                continue  # 避免后续用不存在的节点做其他检查
            if tgt not in node_ids:
                errors.append(ValidationError(
                    severity="error",
                    code="E_DANGLING_EDGE",
                    message=f"边 '{eid}' 的终点 '{tgt}' 不是合法节点 ID",
                    edge_id=eid,
                    node_id=tgt,
                ))
                continue

            # Start 节点不能有入边
            if node_type_map.get(tgt) == "start":
                errors.append(ValidationError(
                    severity="error",
                    code="E_START_HAS_INBOUND",
                    message=f"start 节点 '{tgt}' 不能有入边（边 '{eid}'）",
                    node_id=tgt,
                    edge_id=eid,
                ))

            # End 节点不能有出边
            if node_type_map.get(src) == "end":
                errors.append(ValidationError(
                    severity="error",
                    code="E_END_HAS_OUTBOUND",
                    message=f"end 节点 '{src}' 不能有出边（边 '{eid}'）",
                    node_id=src,
                    edge_id=eid,
                ))

            inbound[tgt].append(src)
            outbound[src].append(tgt)

        # if_else 节点的条件目标也算出边（用于可达性 + 孤立节点检测）
        # 注意：if_else 本身的边不在 edges[] 中，但 conditions[].target_node_id 是隐式出边
        for node in nodes:
            if node.get("type") == "if_else":
                nid = node.get("id", "")
                cfg = node.get("config", {})
                conditions = cfg.get("conditions", [])
                default_target = cfg.get("default_target")

                # 条件目标节点
                for cond in conditions:
                    tgt = cond.get("target_node_id", "")
                    if tgt and tgt in node_ids:
                        outbound[nid].append(tgt)
                        inbound[tgt].append(nid)
                    elif tgt:
                        errors.append(ValidationError(
                            severity="error",
                            code="E_IF_ELSE_BAD_TARGET",
                            message=f"if_else 节点 '{nid}' 的条件目标 '{tgt}' 不存在",
                            node_id=nid,
                        ))

                # default_target
                if default_target:
                    if default_target in node_ids:
                        outbound[nid].append(default_target)
                        inbound[default_target].append(nid)
                    else:
                        errors.append(ValidationError(
                            severity="error",
                            code="E_IF_ELSE_BAD_TARGET",
                            message=f"if_else 节点 '{nid}' 的 default_target '{default_target}' 不存在",
                            node_id=nid,
                        ))

        # 孤立节点检测（除 start 外，节点既无入边又无出边为孤立）
        for node in nodes:
            nid = node.get("id", "")
            ntype = node.get("type", "")
            if ntype == "start":
                continue  # start 无入边是正常的
            has_inbound = bool(inbound.get(nid))
            has_outbound = bool(outbound.get(nid))
            if not has_inbound and not has_outbound and ntype != "end":
                errors.append(ValidationError(
                    severity="warning",
                    code="E_ORPHAN_NODE",
                    message=f"节点 '{nid}' 没有入边也没有出边（孤立节点）",
                    node_id=nid,
                ))

        # 成环检测（使用 graphlib.TopologicalSorter）
        # TopologicalSorter 接受的是"依赖图"：{node: 该节点依赖的节点集合}
        # 对于执行顺序（A→B→C），TopologicalSorter 需要 {B: {A}, C: {B}}（入边/前驱）
        # 使用入边（inbound）构造依赖图，而非出边（outbound）
        try:
            dep_graph: dict[str, set[str]] = {nid: set() for nid in node_ids}
            for tgt, srcs in inbound.items():
                dep_graph[tgt] = set(srcs)
            sorter = TopologicalSorter(dep_graph)
            topo_order = list(sorter.static_order())
        except CycleError as e:
            # e.args[1] 是环中的节点列表
            cycle_nodes = list(e.args[1]) if len(e.args) > 1 else []
            errors.append(ValidationError(
                severity="error",
                code="E_CYCLE",
                message=f"检测到循环依赖，涉及节点：{cycle_nodes}",
            ))
            topo_order = []  # 有环时拓扑序无意义

        # 不可达 end 检测（BFS 从 start 出发）
        if topo_order and start_nodes and end_nodes:
            start_id = start_nodes[0]["id"]
            reachable: set[str] = set()
            queue: deque[str] = deque([start_id])
            while queue:
                nid = queue.popleft()
                if nid in reachable:
                    continue
                reachable.add(nid)
                for tgt in outbound.get(nid, []):
                    if tgt not in reachable:
                        queue.append(tgt)

            for end_node in end_nodes:
                end_id = end_node["id"]
                if end_id not in reachable:
                    errors.append(ValidationError(
                        severity="error",
                        code="E_UNREACHABLE_END",
                        message=f"end 节点 '{end_id}' 从 start 节点不可达",
                        node_id=end_id,
                    ))

        return errors

    # ─── Category 3: 节点 config 校验 ─────────────────────────────────────────

    def _validate_node_configs(self, nodes: list[dict]) -> list[ValidationError]:
        """对每个节点用对应类型的 JSON Schema 校验 config。"""
        errors: list[ValidationError] = []

        for node in nodes:
            nid = node.get("id", "")
            ntype = node.get("type", "")
            config = node.get("config", {})

            # 跳过未知类型节点（E_INVALID_NODE_TYPE 已在 JSON Schema 层拦截）
            if ntype not in NODE_SCHEMAS:
                continue

            node_schema = get_node_schema(ntype)

            # if_else 节点额外检查 default_target 是否存在（此处仅检查字段存在性）
            if ntype == "if_else":
                if not config.get("default_target"):
                    errors.append(ValidationError(
                        severity="error",
                        code="E_IF_ELSE_NO_DEFAULT",
                        message=f"if_else 节点 '{nid}' 缺少 default_target 字段",
                        node_id=nid,
                        field_path="config.default_target",
                    ))

            try:
                jsonschema.validate(config, node_schema)
            except jsonschema.ValidationError as e:
                field_path_parts = ["config"] + [str(p) for p in e.absolute_path]
                errors.append(ValidationError(
                    severity="error",
                    code="E_INVALID_CONFIG",
                    message=f"节点 '{nid}'（类型 {ntype}）配置错误：{e.message}",
                    node_id=nid,
                    field_path=".".join(field_path_parts),
                ))

        return errors

    # ─── Category 2: 变量引用检查 ─────────────────────────────────────────────

    def _validate_variables(
        self,
        dsl: dict,
        nodes: list[dict],
        edges: list[dict],
        state_schema: dict,
    ) -> list[ValidationError]:
        """检查所有模板变量引用是否合法（上游存在 + 字段存在）。"""
        errors: list[ValidationError] = []

        # 构造全局符号表（所有节点 ID ∪ state_schema 字段名）
        node_ids: set[str] = {n["id"] for n in nodes}
        state_fields: set[str] = set(state_schema.keys())
        all_symbols: set[str] = node_ids | state_fields

        # 构造输出字段映射：node_id → 该节点的输出字段集合
        output_fields_map: dict[str, frozenset[str]] = {}
        node_type_map: dict[str, str] = {n["id"]: n["type"] for n in nodes}

        for nid, ntype in node_type_map.items():
            if ntype in NODE_SCHEMAS:
                base_fields = get_node_output_fields(ntype)
                if ntype == "start":
                    # start 节点的输出字段 = state_schema 字段 ∪ "output"
                    output_fields_map[nid] = base_fields | state_fields
                else:
                    output_fields_map[nid] = base_fields
            else:
                output_fields_map[nid] = frozenset()

        # state_schema 字段：在任意节点的模板中都可直接用（不需要 node_id. 前缀）
        # 即 {{ employee_id }} 也是合法的（等价于 {{ start.employee_id }}）

        # 构造拓扑序（用于检查下游引用）
        # 先构造 outbound 图（节点 ID → 下游节点 ID 集合）
        outbound: dict[str, set[str]] = defaultdict(set)
        for edge in edges:
            src = edge.get("source", "")
            tgt = edge.get("target", "")
            if src in node_ids and tgt in node_ids:
                outbound[src].add(tgt)

        # if_else 的隐式出边
        for node in nodes:
            if node.get("type") == "if_else":
                nid = node["id"]
                cfg = node.get("config", {})
                for cond in cfg.get("conditions", []):
                    tgt = cond.get("target_node_id", "")
                    if tgt in node_ids:
                        outbound[nid].add(tgt)
                default_tgt = cfg.get("default_target", "")
                if default_tgt in node_ids:
                    outbound[nid].add(default_tgt)

        # 拓扑排序（如果有环，已在 _validate_structure 中报错，这里跳过）
        # TopologicalSorter 接受"依赖图"：{node: 依赖的前驱节点集合}（即入边方向）
        # 对于执行顺序 A→B→C，需要 {B: {A}, C: {B}}，按此得到正确执行顺序
        try:
            inbound_for_topo: dict[str, set[str]] = {nid: set() for nid in node_ids}
            for nid in node_ids:
                for tgt in outbound.get(nid, set()):
                    if tgt in node_ids:
                        inbound_for_topo[tgt].add(nid)
            topo_order = list(TopologicalSorter(inbound_for_topo).static_order())
        except CycleError:
            # 有环时，拓扑序无意义，跳过变量检查
            return errors

        # 按拓扑序（从前到后）检查每个节点的模板变量
        # 已访问节点集：只允许引用已遍历过的节点（即上游节点）
        visited_nodes: set[str] = set()

        for nid in topo_order:
            node = next((n for n in nodes if n["id"] == nid), None)
            if node is None:
                continue

            ntype = node.get("type", "")
            config = node.get("config", {})

            # 提取当前节点 config 中所有 string 字段（包括嵌套）
            template_strings = _extract_template_strings(config)

            for tmpl, field_path in template_strings:
                if "{{" not in tmpl and "{%" not in tmpl:
                    continue  # 无模板语法，跳过

                try:
                    top_vars = collect_referenced_variables(tmpl, self._jinja_env)
                except Exception:
                    # 模板语法错误已在 jinja_env 层报，这里忽略
                    continue

                for var_name in top_vars:
                    if var_name in state_fields:
                        # state_schema 字段，始终合法（任意节点均可引用）
                        continue

                    if var_name not in all_symbols:
                        # 符号不存在
                        errors.append(ValidationError(
                            severity="error",
                            code="E_UNDEFINED_VAR",
                            message=(
                                f"节点 '{nid}' 的字段 '{field_path}' 引用了未定义变量 '{var_name}'，"
                                f"合法符号：节点 ID {sorted(node_ids)} + state 字段 {sorted(state_fields)}"
                            ),
                            node_id=nid,
                            field_path=f"config.{field_path}",
                        ))
                        continue

                    # var_name 是节点 ID，检查是否上游
                    if var_name not in visited_nodes and var_name != nid:
                        errors.append(ValidationError(
                            severity="error",
                            code="E_VAR_NOT_UPSTREAM",
                            message=(
                                f"节点 '{nid}' 的字段 '{field_path}' 引用了下游或同级节点 '{var_name}'，"
                                f"只能引用已执行完毕的上游节点"
                            ),
                            node_id=nid,
                            field_path=f"config.{field_path}",
                        ))
                        continue

                    # 检查字段名（{{ node_id.field }}）
                    # jinja2.meta 只给顶层变量，字段名需从原模板提取
                    # 通过正则从模板中找 var_name.<field> 模式
                    field_refs = _extract_field_refs(tmpl, var_name)
                    node_out_fields = output_fields_map.get(var_name, frozenset())

                    for field_ref in field_refs:
                        if field_ref and field_ref not in node_out_fields and node_out_fields:
                            errors.append(ValidationError(
                                severity="error",
                                code="E_UNDEFINED_FIELD",
                                message=(
                                    f"节点 '{nid}' 的字段 '{field_path}' 引用了 '{var_name}.{field_ref}'，"
                                    f"但 {node_type_map.get(var_name)} 节点只有输出字段：{sorted(node_out_fields)}"
                                ),
                                node_id=nid,
                                field_path=f"config.{field_path}",
                            ))

            visited_nodes.add(nid)

        return errors


# ─── 辅助函数 ──────────────────────────────────────────────────────────────────

def _extract_template_strings(
    obj: object,
    path: str = "",
) -> list[tuple[str, str]]:
    """递归提取 dict/list 中所有字符串字段及其路径。

    Returns:
        [(字符串值, 字段路径)] 列表
    """
    results: list[tuple[str, str]] = []
    if isinstance(obj, str):
        results.append((obj, path))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            sub_path = f"{path}.{k}" if path else k
            results.extend(_extract_template_strings(v, sub_path))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            sub_path = f"{path}[{i}]"
            results.extend(_extract_template_strings(item, sub_path))
    return results


def _extract_field_refs(template_str: str, var_name: str) -> list[str]:
    """从模板字符串中提取 var_name.<field> 的字段名列表。

    例如：
        template = "{{ llm_1.message | upper }}"
        var_name = "llm_1"
        → ["message"]

    Args:
        template_str: Jinja2 模板字符串
        var_name: 顶层变量名（节点 ID）

    Returns:
        字段名列表（可能为空）
    """
    # 匹配 var_name.field_name（字段名：字母/数字/下划线）
    pattern = re.compile(
        r"\{\{[^}]*\b" + re.escape(var_name) + r"\s*\.\s*([a-zA-Z_][a-zA-Z0-9_]*)"
    )
    return pattern.findall(template_str)
