"""Phase 5.B sandbox runtime: resource limits / network allowlist / watchdog / cgroups.

本子包提供 plugin daemon 沙箱外壳所需 helper：

- `parser`: K8s 风格资源单位解析（memory / cpu）— Wave 2/3 runner 共享
- `runner`: SandboxRunner Protocol + PosixResourceSandbox（Plan 05b-02）
- `network`: AllowlistTransport + make_sandboxed_http_client（Plan 05b-03）
- `watchdog`: SandboxWatchdog asyncio task — 监控 RSS + SIGTERM grace → SIGKILL（Plan 05b-04）
- `idle_reaper`: IdleDaemonReaper asyncio task — 扫 last_invoke_at > timeout_idle auto-close（Plan 05b-04）
- `cgroups_v2`: CgroupsV2Sandbox + is_cgroups_v2_available — Linux opt-in（Plan 05b-05）

Phase 5.A 的 manifest.SandboxConfig 字段消费由本子包驱动。
"""

from __future__ import annotations

from .cgroups_v2 import CgroupsV2Sandbox, is_cgroups_v2_available
from .idle_reaper import IdleDaemonReaper
from .network import AllowlistTransport, make_sandboxed_http_client
from .parser import parse_cpu_seconds, parse_memory
from .runner import PosixResourceSandbox, SandboxRunner
from .watchdog import SandboxWatchdog

__all__ = [
    "AllowlistTransport",
    "CgroupsV2Sandbox",
    "IdleDaemonReaper",
    "PosixResourceSandbox",
    "SandboxRunner",
    "SandboxWatchdog",
    "is_cgroups_v2_available",
    "make_sandboxed_http_client",
    "parse_cpu_seconds",
    "parse_memory",
]
