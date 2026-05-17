"""Phase 5.B sandbox runtime: resource limits / network allowlist / watchdog / cgroups.

本子包提供 plugin daemon 沙箱外壳所需 helper：

- `parser`: K8s 风格资源单位解析（memory / cpu）— Wave 2/3 runner 共享
- `runner`: SandboxRunner Protocol + PosixResourceSandbox（Plan 05b-02）
- `network`: AllowlistTransport + make_sandboxed_http_client（Plan 05b-03）
- `watchdog`: SandboxWatchdog asyncio task — 监控 RSS + SIGTERM grace → SIGKILL（Plan 05b-04）
- `idle_reaper`: IdleDaemonReaper asyncio task — 扫 last_invoke_at > timeout_idle auto-close（Plan 05b-04）

Phase 5.A 的 manifest.SandboxConfig 字段消费由本子包驱动。
"""

from __future__ import annotations

from .idle_reaper import IdleDaemonReaper
from .network import AllowlistTransport, make_sandboxed_http_client
from .parser import parse_cpu_seconds, parse_memory
from .runner import PosixResourceSandbox, SandboxRunner
from .watchdog import SandboxWatchdog

__all__ = [
    "AllowlistTransport",
    "IdleDaemonReaper",
    "PosixResourceSandbox",
    "SandboxRunner",
    "SandboxWatchdog",
    "make_sandboxed_http_client",
    "parse_cpu_seconds",
    "parse_memory",
]
