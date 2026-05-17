"""Phase 5.B sandbox runtime: resource limits / network allowlist / watchdog / cgroups.

本子包提供 plugin daemon 沙箱外壳所需 helper：

- `parser`: K8s 风格资源单位解析（memory / cpu）— Wave 2/3 runner 共享
- `runner` (Wave 2 待加): SandboxRunner Protocol + PosixResourceSandbox + CgroupsV2Sandbox
- `network` (Wave 2 待加): AllowlistTransport + NetworkBlockedError
- `watchdog` (Wave 3 待加): asyncio 任务定期检查资源 + SIGTERM grace
- `idle_reaper` (Wave 3 待加): idle daemon 自动 close

Phase 5.A 的 manifest.SandboxConfig 字段消费由本子包驱动。
"""

from __future__ import annotations
