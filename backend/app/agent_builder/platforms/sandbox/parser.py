"""K8s 风格资源单位解析 helper（Phase 5.B sandbox runner 共享）。

设计要点：

- **不依赖 Pydantic**：保持轻量；manifest.py 的 SandboxConfig validator 通过 import 调用本模块函数
- **0 第三方依赖**：仅用 stdlib `re`；不引入 humanfriendly（CLAUDE.md 鼓励无依赖优先）
- **支持 SI + binary 双单位**：K/M/G/T (1000^n) + Ki/Mi/Gi/Ti (1024^n) + 空单位（裸 bytes）
- **失败 raise ValueError**：调用方（Pydantic field_validator）会自动包装为 ValidationError

Reference: K8s API 资源单位规范 https://kubernetes.io/docs/reference/kubernetes-api/common-definitions/quantity/
"""

from __future__ import annotations

import re

# ── K8s 内存单位 regex + 乘子表 ────────────────────────────────────────────────

# 数字（可含小数）+ 可选单位后缀；不接受负数 / 科学记数法
_MEMORY_RE = re.compile(r"^(\d+(?:\.\d+)?)(Ki|Mi|Gi|Ti|K|M|G|T|)$")

# SI = 10^3 进位；binary = 2^10 进位；空 = 1（裸 bytes）
_MEMORY_MULTIPLIERS: dict[str, int] = {
    "": 1,
    "K": 1000,
    "M": 1000**2,
    "G": 1000**3,
    "T": 1000**4,
    "Ki": 1024,
    "Mi": 1024**2,
    "Gi": 1024**3,
    "Ti": 1024**4,
}


def parse_memory(value: str) -> int:
    """解析 K8s 风格内存字符串为 bytes 整数。

    支持单位:
        - SI (1000^n): K / M / G / T
        - Binary (1024^n): Ki / Mi / Gi / Ti
        - 空（裸 bytes）: "1024" → 1024

    示例:
        parse_memory("512Mi") == 536870912    # 512 * 1024^2
        parse_memory("1Gi")   == 1073741824   # 1 * 1024^3
        parse_memory("1.5Gi") == 1610612736   # 1.5 * 1024^3
        parse_memory("1G")    == 1000000000   # 1 * 1000^3
        parse_memory("1024")  == 1024         # 裸 bytes

    Args:
        value: K8s 单位字符串

    Returns:
        bytes 数量（int）

    Raises:
        ValueError: 格式不匹配（含负数 / 非法单位 / 空字符串 / 非数字）
    """
    m = _MEMORY_RE.match(value)
    if not m:
        raise ValueError(
            f"memory 必须是 K8s 单位格式（如 '512Mi' / '1Gi' / '1024'），实际: {value!r}"
        )
    val, unit = m.group(1), m.group(2)
    return int(float(val) * _MEMORY_MULTIPLIERS[unit])


def parse_cpu_seconds(cpu_limit: str) -> int:
    """CPU limit '2.0' → RLIMIT_CPU 累积总秒数（保守 3600s × cores）。

    背景:
        RLIMIT_CPU 是**累积 CPU 秒数**，非 quota / rate。一旦子进程消费 CPU 时间
        总量超此值，内核发 SIGXCPU 信号。真正的 CPU quota 限制由 cgroups v2
        `CPUQuota=` 提供（Linux opt-in，Wave 3 CgroupsV2Sandbox 实现）。

        本函数给 long-running plugin 足够余量：
            3600s × cores = 3600s × 2 = 7200s（2 小时单 daemon 累积 CPU）

    示例:
        parse_cpu_seconds("2.0") == 7200    # 3600 * 2
        parse_cpu_seconds("0.5") == 1800    # 3600 * 0.5
        parse_cpu_seconds("1")   == 3600    # 3600 * 1

    Args:
        cpu_limit: Docker-style cores 字符串（"1.0" / "0.5" / "2"）

    Returns:
        累积 CPU 秒数（int）

    Raises:
        ValueError: 非法浮点格式（float() 转换失败）
    """
    try:
        cores = float(cpu_limit)
    except (TypeError, ValueError) as e:
        raise ValueError(
            f"cpu_limit 必须是浮点数字符串（如 '1.0' / '0.5' / '2'），实际: {cpu_limit!r}"
        ) from e
    if cores < 0:
        raise ValueError(f"cpu_limit 不能为负数，实际: {cpu_limit!r}")
    return int(cores * 3600)


__all__ = ["parse_memory", "parse_cpu_seconds"]
