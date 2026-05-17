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
