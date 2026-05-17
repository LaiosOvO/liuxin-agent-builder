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

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .exceptions import ManifestValidationError

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
    """Plugin 沙箱配置 — Phase 5.A 仅解析不强制；Phase 5.B 落地（cgroups v2 / network whitelist）。

    Fields:
        cpu_limit: str — "1.0" 表示 1 个 CPU 核（cgroup CPU quota）
        memory_limit: str — "512Mi" 等 K8s 资源单位
        network: list[str] — 允许出网的 host:port 白名单（"example.com:443"）
    """

    model_config = ConfigDict(extra="forbid")

    cpu_limit: str | None = "1.0"
    memory_limit: str | None = "512Mi"
    network: list[str] = Field(default_factory=list)


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
