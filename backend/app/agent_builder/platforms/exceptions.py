"""Phase 5.A Plugin Framework 异常集中定义。

集中定义所有 plugin 子系统相关异常类，便于：
- import 路径稳定（不分散到各 capability 文件）
- except 子句一次 import 多个类型
- 错误码 / 错误类型映射 daemon RPC envelope（Plan 06）

异常继承层级：
    PluginError                          ← 顶层 base
    ├── ManifestValidationError          ← manifest YAML / Pydantic 校验失败
    ├── CapabilityMissingError           ← plugin 不声明所请求的 capability
    ├── PluginDaemonExitedError          ← daemon 子进程意外退出（fault isolation）
    └── PluginInvocationError            ← daemon 返回 JSONRPC error 业务错

设计参考（Dify reading doc §3.5）：
- Dify `PluginDaemonError` (api/core/plugin/entities/plugin_daemon.py:126) — 集中 error_type 字段
- Dify `PluginDaemonInnerError` (同上 :135) — 错误码 + message 双字段
本项目独立创作 Python 异常层级，不引入 error_type 字符串字段（用 isinstance 子类型分流即可）。
"""

from __future__ import annotations


class PluginError(Exception):
    """Plugin 子系统所有异常的 base class。

    用法：
        try:
            await daemon.invoke("im", "send_card", ...)
        except PluginError as e:
            log.error("plugin call failed", exc_info=e)
    """


class ManifestValidationError(PluginError):
    """Manifest YAML / Pydantic schema 校验失败。

    触发时机（Plan 03）：
    - `yaml.safe_load(open(manifest_path))` 解析失败
    - `PlatformManifest(**raw_dict)` Pydantic 校验失败（含 extra=forbid 触发）
    - manifest 声明的 capability 与文件名集合不一致
    """


class CapabilityMissingError(PluginError):
    """Plugin 不声明所请求的 capability。

    触发时机（Plan 04 PluginRegistry）：
    - 调用方 `registry.get_capability(IMCapability, prefer="huly")` 但 huly plugin manifest
      未声明 `capabilities: ["im"]`
    - Registry 返回 None；上层显式 raise（fail-quiet 默认 None；显式 require 时 raise）
    """


class PluginDaemonExitedError(PluginError):
    """Daemon 子进程意外退出（fault isolation 关键）。

    触发时机（Plan 06 PlatformDaemonClient）：
    - `_read_loop` 检测 `stdout.readline()` 返回空 bytes（daemon 已 exit）
    - 主进程对所有 pending Future `set_exception(PluginDaemonExitedError(returncode=...))`
    - 调用方下次 `await daemon.invoke(...)` 立刻 raise（不 hang 30s timeout）

    用户硬性要求（CONTEXT.md §HulyPlugin Acid Test DoD #2）必须覆盖。
    """


class PluginInvocationError(PluginError):
    """Plugin daemon 返回 JSONRPC error 业务错（非 transport 错误）。

    触发时机（Plan 06 PlatformDaemonClient._read_loop）：
    - daemon 返回 `{"jsonrpc":"2.0","id":...,"error":{"code":-32601,"message":"Method not found"}}`
    - 主进程对对应 Future `set_exception(PluginInvocationError(error_payload))`

    Attributes:
        error_payload: dict — daemon 返回的 error 对象（含 code/message/data 等字段）
    """

    def __init__(self, error_payload: dict):
        self.error_payload = error_payload
        super().__init__(
            f"Plugin invocation error: code={error_payload.get('code', '?')} "
            f"message={error_payload.get('message', '?')}"
        )


class SandboxLimitExceeded(PluginError):
    """Sandbox 资源超限（CPU / memory）— watchdog 检测时 raise。

    触发时机（Wave 3 watchdog task，Plan 05b-04）：
    - watchdog 每 5s 读 `/proc/<pid>/status` RSS 或 cgroup `memory.current`
    - 发现 RSS > `sandbox.memory_bytes` → SIGTERM grace 3s → SIGKILL
    - 同时 raise SandboxLimitExceeded 给所有 pending invoke future（不阻塞）

    本 Plan 05b-02 仅定义异常类（占位），Wave 3 真消费。

    Attributes:
        kind: 限制类型（"cpu" / "memory" / "nproc" / "nofile"）
        limit: 限制值（bytes / seconds / count）
        actual: 实际值（超限时的观测值）
    """

    def __init__(self, kind: str, limit: int, actual: int | None = None):
        self.kind = kind
        self.limit = limit
        self.actual = actual
        msg = f"Sandbox {kind} limit exceeded: limit={limit}"
        if actual is not None:
            msg += f" actual={actual}"
        super().__init__(msg)


class NetworkBlockedError(PluginError):
    """非白名单 host:port 出站 — AllowlistTransport raise（Plan 05b-03）。

    触发时机（Plan 05b-03 AllowlistTransport.handle_async_request）：
    - daemon httpx.AsyncClient 发起 HTTP 请求
    - AllowlistTransport 检查 `url.host:url.port` 不在 `sandbox.network` 白名单
    - raise NetworkBlockedError("xxx.com:443 not in allowlist")

    本 Plan 05b-02 仅定义异常类（占位），Plan 05b-03 真消费。

    Attributes:
        host: 被拦截的 host
        port: 被拦截的 port
        allowlist: 当前白名单（dict 或 list）
    """

    def __init__(self, host: str, port: int, allowlist: list[str] | None = None):
        self.host = host
        self.port = port
        self.allowlist = allowlist or []
        super().__init__(
            f"Network egress blocked: {host}:{port} not in allowlist "
            f"(size={len(self.allowlist)})"
        )


__all__ = [
    "PluginError",
    "ManifestValidationError",
    "CapabilityMissingError",
    "PluginDaemonExitedError",
    "PluginInvocationError",
    "SandboxLimitExceeded",
    "NetworkBlockedError",
]
