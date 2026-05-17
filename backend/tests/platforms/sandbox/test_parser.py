"""Phase 5.B Plan 05b-01 — sandbox.parser 单元测试。

测试覆盖（PLAN.md ≥ 12 测试要求）：
- parse_memory SI 单位 (K/M/G/T) × 4
- parse_memory binary 单位 (Ki/Mi/Gi/Ti) × 4
- parse_memory 裸 bytes
- parse_memory 小数值
- parse_memory 非法格式 raise
- parse_memory 负数 raise
- parse_cpu_seconds integer
- parse_cpu_seconds decimal
- parse_cpu_seconds 非法值 raise
- parse_cpu_seconds 负数 raise
"""

from __future__ import annotations

import pytest

from app.agent_builder.platforms.sandbox.parser import parse_cpu_seconds, parse_memory


# ── parse_memory: SI 单位 (10^3 进位) ─────────────────────────────────────────


def test_parse_memory_si_units_K() -> None:
    """K = 1000 bytes。"""
    assert parse_memory("1K") == 1000


def test_parse_memory_si_units_M() -> None:
    """M = 1_000_000 bytes。"""
    assert parse_memory("2M") == 2 * 1000**2


def test_parse_memory_si_units_G() -> None:
    """G = 1_000_000_000 bytes。"""
    assert parse_memory("1G") == 1000**3


def test_parse_memory_si_units_T() -> None:
    """T = 10^12 bytes。"""
    assert parse_memory("1T") == 1000**4


# ── parse_memory: binary 单位 (1024^n 进位) ───────────────────────────────────


def test_parse_memory_binary_units_Ki() -> None:
    """Ki = 1024 bytes。"""
    assert parse_memory("1Ki") == 1024


def test_parse_memory_binary_units_Mi() -> None:
    """Mi = 1024^2 bytes (K8s 标准, 与 512Mi 工业实践一致)。"""
    assert parse_memory("512Mi") == 512 * 1024**2


def test_parse_memory_binary_units_Gi() -> None:
    """Gi = 1024^3 bytes (默认值 1Gi)。"""
    assert parse_memory("1Gi") == 1024**3


def test_parse_memory_binary_units_Ti() -> None:
    """Ti = 1024^4 bytes。"""
    assert parse_memory("1Ti") == 1024**4


# ── parse_memory: edge cases ──────────────────────────────────────────────────


def test_parse_memory_no_unit_is_bytes() -> None:
    """无单位 = 裸 bytes。"""
    assert parse_memory("1024") == 1024


def test_parse_memory_decimal_value() -> None:
    """小数值合法（'1.5Gi' = 1.5 * 1024^3）。"""
    assert parse_memory("1.5Gi") == int(1.5 * 1024**3)


def test_parse_memory_invalid_format_raises() -> None:
    """'512MB' 非法（K8s 必须 Mi 不是 MB）。"""
    with pytest.raises(ValueError, match="K8s 单位"):
        parse_memory("512MB")


def test_parse_memory_negative_raises() -> None:
    """负数不允许（regex 不匹配 -）。"""
    with pytest.raises(ValueError, match="K8s 单位"):
        parse_memory("-1Gi")


def test_parse_memory_empty_string_raises() -> None:
    """空字符串非法。"""
    with pytest.raises(ValueError, match="K8s 单位"):
        parse_memory("")


def test_parse_memory_only_unit_raises() -> None:
    """无数字仅单位非法（'Mi'）。"""
    with pytest.raises(ValueError, match="K8s 单位"):
        parse_memory("Mi")


def test_parse_memory_scientific_notation_raises() -> None:
    """科学记数法不接受（'1e6'）。"""
    with pytest.raises(ValueError, match="K8s 单位"):
        parse_memory("1e6")


# ── parse_cpu_seconds ─────────────────────────────────────────────────────────


def test_parse_cpu_seconds_integer() -> None:
    """'2' → 7200 (2 cores * 3600s)。"""
    assert parse_cpu_seconds("2") == 7200


def test_parse_cpu_seconds_decimal() -> None:
    """'0.5' → 1800 (0.5 core * 3600s)。"""
    assert parse_cpu_seconds("0.5") == 1800


def test_parse_cpu_seconds_one() -> None:
    """'1' → 3600 (1 core * 3600s)。"""
    assert parse_cpu_seconds("1") == 3600


def test_parse_cpu_seconds_default_two() -> None:
    """'2.0' (SandboxConfig 默认) → 7200。"""
    assert parse_cpu_seconds("2.0") == 7200


def test_parse_cpu_seconds_invalid_raises() -> None:
    """非数字 raise ValueError。"""
    with pytest.raises(ValueError, match="cpu_limit"):
        parse_cpu_seconds("abc")


def test_parse_cpu_seconds_negative_raises() -> None:
    """负数 raise ValueError。"""
    with pytest.raises(ValueError, match="不能为负"):
        parse_cpu_seconds("-1.0")
