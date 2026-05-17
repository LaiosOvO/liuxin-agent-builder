r"""Phase 5.A PlatformManifest — platform.yaml Pydantic v2 schema（PLUG-FW-02）。

设计要点（ADR-001 §4 + RESEARCH.md §Pattern 2 + reading doc §1）：

- `ConfigDict(extra="forbid")` 让 typo 立刻 raise（防隐式冲突 — CONTEXT.md 决策强制）
- `name`: 小写蛇形 `[a-z][a-z0-9_-]{2,31}`（比 Dify `^[a-z0-9_-]{1,128}$` 更严，便于 daemon 进程名 / 文件路径生成）
- `version`: 三段 SemVer `^\d+\.\d+\.\d+$`（v1 简化；Dify 用 packaging.Version 接受 dev/rc 后缀）
- `capabilities`: `list[Literal[...]]` 必须 ≥ 1（多 capability 是核心创新，区别 Dify 单 category）
- `runtime.type`: v1 仅 `"python"`（node/go 留 v2）
- `config_schema`: JSON Schema dict（passthrough，workspace 配置 UI 用；Plan 05+ 前端自动渲染）
- `sandbox`: 仅解析不强制（Phase 5.B 落地 cgroups v2 / network whitelist）

异常翻译：所有解析 / 校验失败一律 raise `ManifestValidationError`（exceptions 集中定义）。

Reference: Dify `api/core/plugin/entities/plugin.py:70-141` (PluginDeclaration, AGPL-3.0)
本 module 100% 独立创作，不拷贝任何 Dify 源码；仅借鉴 Pydantic v2 + extra=forbid 模式。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .exceptions import ManifestValidationError
from .sandbox.parser import parse_cpu_seconds, parse_memory

# network entry regex: 仅允许小写 host + 必须 port（v1 不支持通配符 / scheme）
_NETWORK_ENTRY_RE = re.compile(r"^[a-z0-9.-]+:\d+$")

# ── docker network 命名 regex（Phase 5.C Pattern 4 / Pitfall 5）─────────────────
# Docker 网络名规范（与 `docker network create` 接受的格式一致）：
# - 首字符必须 alphanumeric
# - 后续字符允许 alphanumeric + `_` `.` `-`
# - 不允许 `/` `:` 空格等特殊符（防 manifest 误写导致 docker SDK 隐式拼接产生不可预期 network）
_DOCKER_NET_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")

# ── Sub-models（嵌套结构，借鉴 Dify 嵌套 BaseModel 组织风格）─────────────────────


class RuntimeConfig(BaseModel):
    """Plugin 进程运行时声明 — daemon 子进程启动信息。

    v1 仅 Python 运行时；node/go 留 v2（CONTEXT.md §Deferred Ideas 明确）。

    Fields:
        type: Literal["python"] — v1 锁定（v2 加 "node" / "go"）
        entry: str — daemon 模块路径，如 "plugins.huly.huly_plugin"
        python_version: str — pattern "X.Y" — Plan 05+ subprocess 用对应 venv
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["python"]
    entry: str = Field(min_length=1)
    python_version: str = Field(default="3.11", pattern=r"^\d+\.\d+$")


class CapabilitySpec(BaseModel):
    """Capability-specific 配置 — IM/Doc/HR/Identity 共用 spec class，按需填字段。

    所有字段都是 Optional `bool | None` —— 让单一 spec class 服务多 capability
    （vs 为每 capability 写一 sub-model）。Plan 05+ daemon 接入时按 capability
    类型只读对应字段；多余字段 v1 不强校验（v2 可拆细）。

    设计取舍：聚合 vs 分散
    - 聚合（当前）：单 CapabilitySpec 含所有 cap flag —— extra=forbid 仍生效防 typo
    - 分散（v2）：IMCapabilitySpec / DocCapabilitySpec / ... 各自一 class
    v1 选聚合 — 字段少（6 个），union union 模型让 manifest YAML 结构平
    """

    model_config = ConfigDict(extra="forbid")

    # IM cap flags（Plan 02 IMCapability 协议对应）
    supports_native_buttons: bool | None = None
    supports_card_update: bool | None = None
    supports_threads: bool | None = None

    # Doc cap flags（Plan 02 DocCapability 协议对应）
    supports_collaborative_edit: bool | None = None
    supports_comments: bool | None = None

    # Identity cap flags（Plan 03 IdentityCapability 协议对应）
    is_source_of_truth: bool | None = None


class SandboxConfig(BaseModel):
    """Plugin 沙箱配置 — Phase 5.A placeholder + Phase 5.B 全量字段 + validators。

    Phase 5.B Plan 05b-01 扩展:
        - rename `memory_limit` → `memory`（K8s 风格 + RESEARCH 决策对齐）
        - 加 4 新字段: `timeout_invoke` / `timeout_idle` / `use_cgroups` / `env_allowlist`
        - 给 `cpu_limit` / `memory` / `network` 加 Pydantic v2 validators
        - 加 2 派生属性: `memory_bytes` / `cpu_limit_seconds`（Wave 2/3 runner 用）

    Fields:
        cpu_limit: str — Docker style cores（"1.0" = 1 核 / "0.5" = 半核）
        memory: str — K8s 单位（"512Mi" / "1Gi" / "2.5Gi"）
        network: list[str] — host:port 出网白名单（仅小写 host + 必须 port；不支持通配符）
        timeout_invoke: int — 单次 invoke 超时秒数（gt=0, le=3600）
        timeout_idle: int — daemon idle 自动 close 秒数（gt=0, le=86400）
        use_cgroups: bool — Linux opt-in cgroups v2（False = setrlimit baseline）
        env_allowlist: list[str] — 传给 daemon 的 env 变量白名单（默认 [] strip all — Pitfall 8 防 secret 泄漏）

    Properties:
        memory_bytes: int — `parse_memory(self.memory)` 派生
        cpu_limit_seconds: int — `parse_cpu_seconds(self.cpu_limit)` 派生

    默认值（manifest 未声明 sandbox 段时, RESEARCH 决策）:
        cpu_limit="2.0" / memory="1Gi" / network=[] 禁所有出站 / timeout_invoke=30 /
        timeout_idle=300 / use_cgroups=False / env_allowlist=[] strip all

    Reference: Dify `PluginResourceRequirements` 设计模式（仅借鉴 field_validator + Field
    约束模式；K8s 单位字符串 + property 派生 int 是本项目独有，详见
    docs/reading-dify-05b-01-sandbox-config-2026-05-17.md）。
    """

    model_config = ConfigDict(extra="forbid")

    cpu_limit: str = Field(default="2.0", pattern=r"^\d+(\.\d+)?$")
    memory: str = Field(default="1Gi")
    network: list[str] = Field(default_factory=list)
    timeout_invoke: int = Field(default=30, gt=0, le=3600)
    timeout_idle: int = Field(default=300, gt=0, le=86400)
    use_cgroups: bool = False
    env_allowlist: list[str] = Field(default_factory=list)

    # ── Phase 5.C Pattern 4 新增（接口对外冻结后 Wave 2 三 plan 复用）────────────
    docker_networks: list[str] = Field(default_factory=list)
    """Daemon spawn 后需要 attach 的 docker network 列表（Phase 5.C 新增）。

    默认空 list = no attach（PosixResourceSandbox no-op；CgroupsV2Sandbox 也跳过）。

    典型使用场景:
    - Huly plugin 必须 attach `huly_huly_net` 才能调 collaborator:3078
    - 其他平台（Outline / Lark / Slack）走公网 → 留空 list 即可

    与 `network` 字段区别:
    - `network`: application-level 白名单（httpx AllowlistTransport 校验 host:port）
    - `docker_networks`: kernel-level docker bridge 网络 attach（daemon 容器化部署时能访问的网络）

    Reference: Phase 5.C RESEARCH.md §Pattern 4 / Pitfall 5。
    """

    @field_validator("memory")
    @classmethod
    def memory_must_be_k8s_format(cls, v: str) -> str:
        """K8s 单位字符串校验（"512Mi" / "1Gi" / "2.5Gi" / 裸 bytes "1024"）。

        失败 raise ValueError（Pydantic 自动包装为 ValidationError）。
        """
        try:
            parse_memory(v)
        except ValueError as e:
            raise ValueError(str(e)) from e
        return v

    @field_validator("network")
    @classmethod
    def network_entries_must_be_host_port(cls, v: list[str]) -> list[str]:
        """每条 entry 必须为小写 host:port 格式（regex `^[a-z0-9.-]+:\\d+$`）。

        v1 不支持通配符（"*.feishu.cn:443"）— 留 v2 解决；不支持 scheme
        ("http://example.com")— 必须 host:port 形式。
        """
        for entry in v:
            if not _NETWORK_ENTRY_RE.match(entry):
                raise ValueError(
                    f"network entry 必须是小写 host:port 格式（如 'example.com:443'），"
                    f"实际: {entry!r}"
                )
        return v

    @field_validator("docker_networks")
    @classmethod
    def docker_networks_must_be_valid_names(cls, v: list[str]) -> list[str]:
        """每条 docker network 名必须符合 docker network 命名规范（Phase 5.C Pitfall 5）。

        防 manifest 误写（如带 `/` 或空格）导致 docker SDK 隐式拼接产生不可预期 network。
        """
        for entry in v:
            if not _DOCKER_NET_RE.match(entry):
                raise ValueError(
                    f"docker_networks entry 必须符合 docker network 命名规范"
                    f"（首字符 alphanumeric，后续允许 alphanumeric/_/./-），实际: {entry!r}"
                )
        return v

    @property
    def memory_bytes(self) -> int:
        """返回 memory 字符串解析后的 bytes 整数（Wave 2 RLIMIT_AS 用）。"""
        return parse_memory(self.memory)

    @property
    def cpu_limit_seconds(self) -> int:
        """返回 cpu_limit 派生的 RLIMIT_CPU 累积秒数（Wave 2 RLIMIT_CPU 用）。"""
        return parse_cpu_seconds(self.cpu_limit)


# ── PlatformManifest（顶层 schema）─────────────────────────────────────────────


class PlatformManifest(BaseModel):
    """platform.yaml 顶层 schema — 1 个 plugin 1 个 manifest 文件。

    `extra=forbid` 让任何未声明字段立刻 raise ValidationError（防 typo + 防隐式冲突）。

    Fields:
        name: 小写蛇形（[a-z][a-z0-9_-]{2,31}）— 用作 daemon 进程名 / 文件路径 segment
        version: 三段 SemVer（^\\d+\\.\\d+\\.\\d+$）— v1 简化（不接受 dev/rc 后缀）
        description: 任意字符串 — 配 UI 展示用
        license: Optional — 提示用户合规要求（如 "AGPL-3.0" / "MIT" / "EPL-2.0"）
        agent_builder_version: SemVer range（默认 ">=1.0"）— 启动期校验本项目版本兼容
        runtime: 运行时配置（Plan 05+ daemon spawn 用）
        capabilities: 至少 1 个 capability（多 capability 可同时声明 — 区别 Dify 单 category）
        config_schema: JSON Schema dict — 透传不强类型化（workspace 配置 UI 自动渲染）
        im/doc/hr/identity: Optional CapabilitySpec — 每 capability 独立配置子树
        sandbox: Optional —— Phase 5.A 仅解析不强制（5.B 加进程隔离）

    Validators:
        - capabilities 至少 1 个（@field_validator）
        - 字段级 pattern 校验交给 Field(pattern=...) （Pydantic 内置）

    用法：
        manifest = load_manifest(Path("plugins/huly/platform.yaml"))
        if "im" in manifest.capabilities:
            print(f"Plugin {manifest.name} v{manifest.version} supports IM")
            print(f"  Card update: {manifest.im.supports_card_update}")
    """

    model_config = ConfigDict(extra="forbid")

    # ── 基础元数据 ─────────────────────────────────────────────────────────────
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,31}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    description: str
    license: str | None = None
    agent_builder_version: str = Field(default=">=1.0")

    # ── 运行时 + capabilities ──────────────────────────────────────────────────
    runtime: RuntimeConfig
    capabilities: list[Literal["im", "doc", "hr", "identity", "trigger", "tool"]]

    # ── 配置 schema（JSON Schema 透传）──────────────────────────────────────────
    config_schema: dict[str, Any]

    # ── Capability-specific 配置（Optional）─────────────────────────────────────
    im: CapabilitySpec | None = None
    doc: CapabilitySpec | None = None
    hr: CapabilitySpec | None = None
    identity: CapabilitySpec | None = None

    # ── 沙箱（Phase 5.A 仅解析 / 5.B 强制）─────────────────────────────────────
    sandbox: SandboxConfig | None = None

    # ── Field-level validators ─────────────────────────────────────────────────

    @field_validator("capabilities")
    @classmethod
    def at_least_one_capability(cls, v: list[str]) -> list[str]:
        """plugin 必须声明至少 1 个 capability —— 防空 plugin 注册。"""
        if not v:
            raise ValueError(
                "plugin 必须声明至少 1 个 capability（im/doc/hr/identity/trigger/tool）"
            )
        return v


# ── 解析入口 ───────────────────────────────────────────────────────────────────


def load_manifest(path: str | Path) -> PlatformManifest:
    """加载并校验 platform.yaml 文件 → 返回 PlatformManifest 实例。

    解析步骤：
    1. 文件存在性 / 类型检查（必须是 file）
    2. `yaml.safe_load`（Pitfall 3 防注入 —— 永远不用 yaml.load）
    3. 顶层必须是 mapping（dict） —— 防 YAML 是 list / scalar 时静默生成空 manifest
    4. Pydantic v2 校验（含 extra=forbid + Field pattern + validator）

    Args:
        path: platform.yaml 文件绝对 / 相对路径

    Returns:
        PlatformManifest: 校验通过的 frozen-by-pydantic-v2 manifest 实例

    Raises:
        ManifestValidationError: 任意解析 / 校验失败（用 `from e` 保留原异常 chain）

    用法：
        from app.agent_builder.platforms.manifest import load_manifest
        manifest = load_manifest("plugins/huly/platform.yaml")

    Reference: Dify `core/plugin/entities/plugin.py` Pydantic v2 模式（AGPL-3.0，仅借鉴思路）
    """
    p = Path(path)

    if not p.is_file():
        raise ManifestValidationError(f"manifest 文件不存在或不是文件: {p}")

    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ManifestValidationError(f"YAML 解析失败 ({p}): {e}") from e

    if not isinstance(raw, dict):
        raise ManifestValidationError(
            f"manifest 顶层必须是 mapping（dict）类型，实际为 {type(raw).__name__}: {p}"
        )

    try:
        return PlatformManifest(**raw)
    except Exception as e:
        # Pydantic ValidationError / TypeError / 任何 schema 校验失败统一翻译
        raise ManifestValidationError(f"manifest schema 校验失败 ({p}): {e}") from e


__all__ = [
    "PlatformManifest",
    "RuntimeConfig",
    "CapabilitySpec",
    "SandboxConfig",
    "load_manifest",
]
