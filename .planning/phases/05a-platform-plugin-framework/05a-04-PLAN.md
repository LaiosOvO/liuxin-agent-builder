---
phase: 05a-platform-plugin-framework
plan: 04
type: execute
wave: 3
depends_on: ["02", "03"]
files_modified:
  - docs/reading-dify-05a-04-manifest-registry-2026-05-17.md
  - backend/app/agent_builder/platforms/manifest.py
  - backend/app/agent_builder/platforms/plugin.py
  - backend/app/agent_builder/platforms/registry.py
  - tests/platforms/test_manifest_schema.py
  - tests/platforms/test_registry.py
  - tests/platforms/fixtures/manifest_valid.yaml
  - tests/platforms/fixtures/manifest_invalid_extra_field.yaml
  - tests/platforms/fixtures/manifest_no_capabilities.yaml
autonomous: true
requirements:
  - PLUG-FW-02
  - PLUG-FW-03
must_haves:
  truths:
    - "platform.yaml 可被 PlatformManifest Pydantic schema 校验；extra=forbid 让 typo 立刻 raise"
    - "PlatformPluginRegistry 启动期 discover 完成后含 metadata，懒加载 daemon（首次 get_capability spawn）"
    - "双 workspace 调 get_capability(IMCapability) 拿到的是各自独立 plugin instance（无 cross-tenant leak）"
  artifacts:
    - path: "backend/app/agent_builder/platforms/manifest.py"
      provides: "PlatformManifest Pydantic v2 schema (extra=forbid) + load_manifest(path)"
      exports: ["PlatformManifest", "RuntimeConfig", "CapabilitySpec", "SandboxConfig", "load_manifest"]
      min_lines: 120
    - path: "backend/app/agent_builder/platforms/plugin.py"
      provides: "PlatformPlugin 顶层类（lazy facade 模式）"
      exports: ["PlatformPlugin"]
      min_lines: 80
    - path: "backend/app/agent_builder/platforms/registry.py"
      provides: "PlatformPluginRegistry — per-workspace 隔离 + 启动期 discover + 懒加载"
      exports: ["PlatformPluginRegistry"]
      min_lines: 150
  key_links:
    - from: "backend/app/agent_builder/platforms/registry.py"
      to: "backend/app/models/workspace_plugin_installation.py"
      via: "discover() 时 load 文件系统 plugins/<name>/platform.yaml + DB workspace_plugin_installations 表"
      pattern: "WorkspacePluginInstallation"
    - from: "backend/app/agent_builder/platforms/plugin.py"
      to: "backend/app/agent_builder/platforms/capabilities/*"
      via: "lazy property im/.doc/.hr/.identity 返回 facade（plan 05 daemon_client 完整 wire）"
      pattern: "@property.*IMCapability"
    - from: "tests/platforms/test_registry.py"
      to: "Pitfall 5 workspace 隔离"
      via: "test_two_workspaces_isolated 验证不同 workspace 独立 plugin instance"
      pattern: "test_two_workspaces_isolated"
---

<objective>
实现 Plugin 框架的"声明 + 注册"层：Manifest Pydantic schema（PLUG-FW-02）+ PlatformPlugin 顶层类 + PlatformPluginRegistry（PLUG-FW-03）。本 plan 不实现 daemon client（留 plan 05）；plugin facade 暂用 placeholder 返回 None / 在测试用 MockDaemonClient mock。

Purpose: 后续 plan 05 (LegacyAdapter + Daemon Client + Mock Plugin) 和 plan 06 (HulyPlugin acid test) 都依赖 Registry + Manifest + PlatformPlugin 已就位。
Output: 3 个核心 module + 3 个 fixture manifest YAML + 2 个测试文件。
</objective>

<execution_context>
@/Users/admin/.claude/get-shit-done/workflows/execute-plan.md
@/Users/admin/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/05a-platform-plugin-framework/05a-CONTEXT.md
@.planning/phases/05a-platform-plugin-framework/05a-RESEARCH.md
@docs/plans/2026-05-17-platform-plugin-framework-ADR.md
@backend/app/models/workspace_plugin_installation.py

<interfaces>
From plan 02 + 03 (Capability Protocols):
- IMCapability / DocCapability / HRCapability / IdentityCapability / TriggerCapability / ToolCapability
- 所有 @runtime_checkable

From plan 01 (DB):
- WorkspacePluginInstallation ORM model: workspace_id × plugin_name 唯一

From RESEARCH.md §Pattern 2 (Manifest):
PlatformManifest 字段：name / version / description / license / agent_builder_version / runtime / capabilities / config_schema / im / doc / hr / identity / sandbox

From RESEARCH.md §Pattern 4 (Facade):
PlatformPlugin.im/.doc/.hr/.identity lazy @property，wrap 共享 _daemon
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 0: Dify manifest + plugin_service 阅读文档（CLAUDE.md §2.7 硬性 gate）</name>
  <files>docs/reading-dify-05a-04-manifest-registry-2026-05-17.md</files>
  <action>
读 Dify 源文件：
1. `/Users/admin/ai/ref/dify/repo/api/core/plugin/entities/plugin.py` 重点 PluginDeclaration / PluginEntity / PluginInstallation 字段
2. `/Users/admin/ai/ref/dify/repo/api/services/plugin/plugin_service.py` — install / fetch / get_plugin 方法（不强调 capability 路由细节，看 service 责任边界）
3. 任一 Dify manifest YAML 示例（`/Users/admin/ai/ref/dify/repo/api/core/plugin/manifest_schema/` 若存在），或在 dify repo 找 example plugin yaml
4. `/Users/admin/ai/ref/dify/repo/api/services/plugin/plugin_permission_service.py` — workspace × plugin 隔离思路

写到 `docs/reading-dify-05a-04-manifest-registry-2026-05-17.md`。

**5 借鉴点至少包含**：
1. PluginDeclaration 用 Pydantic BaseModel + Field validator → 5.A PlatformManifest 沿用
2. PluginInstallation 持 tenant_id × plugin_id 唯一 → 5.A workspace_plugin_installations 表对应
3. PluginService.install_plugin 步骤（拉 manifest → 校验 → dry-run → 写库） → 5.A PlatformPluginRegistry.install
4. plugin_permission_service.py per-workspace ACL → 5.A 双 workspace 隔离测试
5. 启动期 vs 懒加载分离 → 5.A discover 启动 / get_capability 才 spawn daemon

License attribution（AGPL vs Apache-2.0）；**不拷源代码**。≥ 60 行。
  </action>
  <verify>
    <automated>test -f docs/reading-dify-05a-04-manifest-registry-2026-05-17.md && wc -l docs/reading-dify-05a-04-manifest-registry-2026-05-17.md | awk '{exit ($1 >= 60 ? 0 : 1)}' && grep -q "AGPL\|attribution" docs/reading-dify-05a-04-manifest-registry-2026-05-17.md</automated>
  </verify>
  <done>Reading doc ≥ 60 行 + 5 借鉴点 + License attribution + commit 在前</done>
</task>

<task type="auto">
  <name>Task 1: PlatformManifest Pydantic schema + load_manifest + fixture YAML + 测试</name>
  <files>backend/app/agent_builder/platforms/manifest.py,tests/platforms/test_manifest_schema.py,tests/platforms/fixtures/manifest_valid.yaml,tests/platforms/fixtures/manifest_invalid_extra_field.yaml,tests/platforms/fixtures/manifest_no_capabilities.yaml</files>
  <action>
1. **`backend/app/agent_builder/platforms/manifest.py`** 按 RESEARCH.md §Pattern 2 完整实现：

```python
"""Phase 5.A PlatformManifest — platform.yaml Pydantic v2 schema。

设计要点（ADR-001 §4 + RESEARCH.md §Pattern 2）：
- ConfigDict(extra="forbid") 让 typo 立刻 raise（防隐式冲突）
- name: 小写蛇形 [a-z][a-z0-9_-]{2,31}
- version: SemVer
- capabilities: list[Literal[...]] 必须 ≥ 1
- runtime.type: v1 仅 "python"（node/go 留 v2）
- config_schema: JSON Schema dict（passthrough，workspace 配 UI 用）
- sandbox: 仅解析不强制（Phase 5.B 落地）
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .exceptions import ManifestValidationError


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["python"]
    entry: str = Field(min_length=1)        # "huly_plugin:main"
    python_version: str = Field(default="3.11", pattern=r"^\d+\.\d+$")


class CapabilitySpec(BaseModel):
    """Capability-specific 配置 — IM/Doc/HR/Identity 共用一个 spec class，按需填字段。"""
    model_config = ConfigDict(extra="forbid")
    supports_native_buttons: bool | None = None
    supports_card_update: bool | None = None
    supports_threads: bool | None = None
    supports_collaborative_edit: bool | None = None
    supports_comments: bool | None = None
    is_source_of_truth: bool | None = None


class SandboxConfig(BaseModel):
    """Phase 5.A 仅解析不强制；Phase 5.B 落地（cgroups v2 / network whitelist）。"""
    model_config = ConfigDict(extra="forbid")
    cpu_limit: str | None = "1.0"
    memory_limit: str | None = "512Mi"
    network: list[str] = Field(default_factory=list)


class PlatformManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,31}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    description: str
    license: str | None = None
    agent_builder_version: str = Field(default=">=1.0")
    runtime: RuntimeConfig
    capabilities: list[Literal["im", "doc", "hr", "identity", "trigger", "tool"]]
    config_schema: dict
    im: CapabilitySpec | None = None
    doc: CapabilitySpec | None = None
    hr: CapabilitySpec | None = None
    identity: CapabilitySpec | None = None
    sandbox: SandboxConfig | None = None

    @field_validator("capabilities")
    @classmethod
    def at_least_one(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("plugin 必须声明至少 1 个 capability")
        return v


def load_manifest(path: str | Path) -> PlatformManifest:
    """加载并校验 platform.yaml。

    Raises:
        ManifestValidationError: 文件不存在 / YAML 格式错 / Pydantic 校验失败
    """
    p = Path(path)
    if not p.is_file():
        raise ManifestValidationError(f"manifest not found: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ManifestValidationError(f"YAML parse error in {p}: {e}") from e
    if not isinstance(raw, dict):
        raise ManifestValidationError(f"manifest top-level must be a mapping: {p}")
    try:
        return PlatformManifest(**raw)
    except Exception as e:
        raise ManifestValidationError(f"schema validation failed for {p}: {e}") from e
```

≥ 120 行。

2. **3 个 fixture YAML**：

`tests/platforms/fixtures/manifest_valid.yaml`：
```yaml
name: huly
version: 1.0.0
description: "Huly platform stub (Phase 5.A acid test)"
license: EPL-2.0
agent_builder_version: ">=1.0"
runtime:
  type: python
  entry: plugins.huly.huly_plugin
  python_version: "3.11"
capabilities:
  - im
  - doc
  - hr
  - identity
config_schema:
  type: object
  required: [endpoint, auth_token]
  properties:
    endpoint:
      type: string
      format: uri
    auth_token:
      type: string
      format: password
im:
  supports_native_buttons: false
  supports_card_update: true
  supports_threads: true
doc:
  supports_collaborative_edit: true
  supports_comments: true
identity:
  is_source_of_truth: true
sandbox:
  cpu_limit: "1.0"
  memory_limit: "512Mi"
  network: ["huly.example.com:443"]
```

`tests/platforms/fixtures/manifest_invalid_extra_field.yaml`：
```yaml
name: bad
version: 1.0.0
description: "manifest with typo — extra=forbid should reject"
runtime:
  type: python
  entry: bad.entry
capabilities: [im]
config_schema: {}
typo_field: "this should raise extra=forbid"
```

`tests/platforms/fixtures/manifest_no_capabilities.yaml`：
```yaml
name: empty
version: 1.0.0
description: "no capabilities — validator should reject"
runtime:
  type: python
  entry: empty.entry
capabilities: []
config_schema: {}
```

3. **`tests/platforms/test_manifest_schema.py`** ≥ 8 测试：
   - `test_valid_huly_manifest_parses`：load fixture/manifest_valid.yaml → PlatformManifest 实例
   - `test_extra_field_rejected`：load manifest_invalid_extra_field.yaml → ManifestValidationError
   - `test_empty_capabilities_rejected`：load manifest_no_capabilities.yaml → ManifestValidationError
   - `test_invalid_semver_rejected`：传 version="1.0" → raise
   - `test_invalid_name_format`：name=" Bad-Name " → raise（必须小写蛇形）
   - `test_runtime_type_python_only`：runtime.type="node" → raise
   - `test_capability_literal_enum`：capabilities=["unknown_cap"] → raise
   - `test_yaml_not_a_mapping_rejected`：load 一个 yaml 内容是 list 的 → raise
  </action>
  <verify>
    <automated>cd backend && python -c "from app.agent_builder.platforms.manifest import PlatformManifest, load_manifest, RuntimeConfig, CapabilitySpec, SandboxConfig; print('OK')" && pytest tests/platforms/test_manifest_schema.py -v -x 2>&1 | tail -15 && wc -l backend/app/agent_builder/platforms/manifest.py | awk '{exit ($1 >= 120 ? 0 : 1)}'</automated>
  </verify>
  <done>PlatformManifest 可 import；load_manifest 解析 valid fixture 成功；invalid fixture 3 种均 raise；8 单测 pass</done>
</task>

<task type="auto">
  <name>Task 2: PlatformPlugin 顶层类 + PlatformPluginRegistry + per-workspace 隔离测试</name>
  <files>backend/app/agent_builder/platforms/plugin.py,backend/app/agent_builder/platforms/registry.py,tests/platforms/test_registry.py</files>
  <action>
1. **`backend/app/agent_builder/platforms/plugin.py`** — lazy facade，本 plan 暂用 placeholder（daemon client 留 plan 05）：

```python
"""PlatformPlugin 顶层类 — lazy facade 模式（ADR-001 §5）。

Phase 5.A：daemon client 留 plan 05 实现；本 module 仅定义 PlatformPlugin
shell 类 + facade 占位（plan 05 注入真 daemon 后 facade 转发到 daemon.invoke）。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .capabilities import (
    DocCapability,
    HRCapability,
    IdentityCapability,
    IMCapability,
    ToolCapability,
    TriggerCapability,
)
from .manifest import PlatformManifest

if TYPE_CHECKING:
    from .daemon_client import PlatformDaemonClient


class PlatformPlugin:
    """一个外部平台 / 工具 / 服务 plugin（可多 capability bundle）。

    用法：
        manifest = load_manifest("plugins/huly/platform.yaml")
        daemon = PlatformDaemonClient(manifest)  # plan 05 实
        plugin = PlatformPlugin(manifest, daemon)
        if plugin.im:
            msg_ref = await plugin.im.send_card(...)
    """

    def __init__(
        self,
        manifest: PlatformManifest,
        daemon: "PlatformDaemonClient | None" = None,
    ):
        self._manifest = manifest
        self._daemon = daemon  # None 表示尚未实例化（懒加载）
        self._cap_cache: dict[str, Any] = {}

    @property
    def name(self) -> str:
        return self._manifest.name

    @property
    def manifest(self) -> PlatformManifest:
        return self._manifest

    @property
    def daemon(self) -> "PlatformDaemonClient | None":
        return self._daemon

    def attach_daemon(self, daemon: "PlatformDaemonClient") -> None:
        """Registry 懒加载时调用 — 注入 daemon 实例。"""
        self._daemon = daemon

    @property
    def im(self) -> IMCapability | None:
        """返回 IM facade（实际转发到 daemon — plan 05 接入）。"""
        if "im" not in self._manifest.capabilities:
            return None
        if "im" not in self._cap_cache:
            from .capability_facades import IMFacade  # plan 05 创建
            self._cap_cache["im"] = IMFacade(self._daemon, self._manifest)
        return self._cap_cache["im"]

    @property
    def doc(self) -> DocCapability | None:
        if "doc" not in self._manifest.capabilities:
            return None
        if "doc" not in self._cap_cache:
            from .capability_facades import DocFacade
            self._cap_cache["doc"] = DocFacade(self._daemon, self._manifest)
        return self._cap_cache["doc"]

    @property
    def hr(self) -> HRCapability | None:
        if "hr" not in self._manifest.capabilities:
            return None
        if "hr" not in self._cap_cache:
            from .capability_facades import HRFacade
            self._cap_cache["hr"] = HRFacade(self._daemon, self._manifest)
        return self._cap_cache["hr"]

    @property
    def identity(self) -> IdentityCapability | None:
        if "identity" not in self._manifest.capabilities:
            return None
        if "identity" not in self._cap_cache:
            from .capability_facades import IdentityFacade
            self._cap_cache["identity"] = IdentityFacade(self._daemon, self._manifest)
        return self._cap_cache["identity"]
```

≥ 80 行。

**重要**：本 plan 写 plugin.py 时，capability_facades 模块还不存在（plan 05 创建）。3 种处理选项：
- (a) `from .capability_facades import IMFacade` 放 `@property` 内部 — 测试时若不调 `plugin.im` 不报错
- (b) 在 plan 04 本 plan 内**创建 stub** `capability_facades.py` 含空 IMFacade/DocFacade/HRFacade/IdentityFacade（plan 05 替换实现）
- **推荐 (b)** — 让 import 跑通

补充创建 `backend/app/agent_builder/platforms/capability_facades.py` stub：
```python
"""Plugin capability facades — Phase 5.A plan 04 stub / plan 05 完整实现。"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .daemon_client import PlatformDaemonClient
    from .manifest import PlatformManifest


class _BaseFacade:
    def __init__(self, daemon: "PlatformDaemonClient | None", manifest: "PlatformManifest"):
        self._daemon = daemon
        self._manifest = manifest


class IMFacade(_BaseFacade):
    """IM facade — plan 05 实接入 daemon.invoke('im', method, **kwargs)。"""
    name = "facade_im_stub"
    supports_native_buttons = False
    supports_card_update = False
    supports_threads = False

    async def send_card(self, *, recipient, card, idempotency_key):
        raise NotImplementedError("Plan 05 实现")

    async def update_card(self, msg_ref, card):
        raise NotImplementedError("Plan 05 实现")

    async def send_text(self, recipient, text):
        raise NotImplementedError("Plan 05 实现")

    async def subscribe_events(self, event_types):
        raise NotImplementedError("Plan 05 实现")
        if False:
            yield {}


class DocFacade(_BaseFacade):
    name = "facade_doc_stub"
    supports_collaborative_edit = False
    supports_comments = False

    async def create_document(self, *, title, markdown, owners=None):
        raise NotImplementedError("Plan 05 实现")

    async def replace_document_content(self, doc_ref, markdown):
        raise NotImplementedError("Plan 05 实现")

    async def apply_document_delta(self, doc_ref, delta):
        raise NotImplementedError("Plan 05 实现")

    async def add_comment(self, *, doc_ref, body, mentions=None):
        raise NotImplementedError("Plan 05 实现")

    async def get_document(self, doc_ref):
        raise NotImplementedError("Plan 05 实现")


class HRFacade(_BaseFacade):
    name = "facade_hr_stub"

    async def list_employees(self, *, filter=None, cursor=None):
        raise NotImplementedError("Plan 05 实现")

    async def get_employee(self, employee_ref):
        raise NotImplementedError("Plan 05 实现")

    async def list_departments(self):
        raise NotImplementedError("Plan 05 实现")

    async def resolve_department_members(self, expression):
        raise NotImplementedError("Plan 05 实现")

    async def list_leave_requests(self, *, employee_ref=None, status=None, cursor=None):
        raise NotImplementedError("Plan 05 实现")

    async def create_leave_request(self, *, employee_ref, request_type, start_date, end_date, description):
        raise NotImplementedError("Plan 05 实现")


class IdentityFacade(_BaseFacade):
    name = "facade_identity_stub"
    is_source_of_truth = False

    async def list_users(self):
        raise NotImplementedError("Plan 05 实现")

    async def resolve_user(self, identifier):
        raise NotImplementedError("Plan 05 实现")

    async def watch_user_changes(self):
        raise NotImplementedError("Plan 05 实现")
        if False:
            yield {}
```

加入 files_modified 列表（add to plan）。

2. **`backend/app/agent_builder/platforms/registry.py`** — 核心：

```python
"""PlatformPluginRegistry — discover / install / get_plugin / get_capability。

设计要点（ADR-001 §6 + CONTEXT.md decisions）：
- 启动期扫描 plugins/*/platform.yaml → metadata 入 _MANIFESTS dict
- per-workspace plugin instance：_PLUGINS dict key (workspace_id, plugin_name)
- 懒加载 daemon：首次 get_plugin(...) 才 spawn daemon（Phase 5.A plan 05 接入）
- get_capability 按 capability 类型查可用 plugin
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workspace_plugin_installation import WorkspacePluginInstallation

from .exceptions import CapabilityMissingError, PluginError
from .manifest import PlatformManifest, load_manifest
from .plugin import PlatformPlugin

_log = logging.getLogger(__name__)


class PlatformPluginRegistry:
    """全局 Registry — 进程级 singleton；Test fixture 调 .clear() 隔离。"""

    _MANIFESTS: dict[str, PlatformManifest] = {}
    _PLUGINS: dict[tuple[uuid.UUID, str], PlatformPlugin] = {}

    @classmethod
    def clear(cls) -> None:
        """测试 fixture 用。"""
        cls._MANIFESTS.clear()
        cls._PLUGINS.clear()

    # ── discover (启动期) ────────────────────────────────────────────────

    @classmethod
    def discover(cls, plugins_root: str | Path) -> list[PlatformManifest]:
        """扫描 plugins/*/platform.yaml → 校验 → 入 _MANIFESTS。

        启动期调用一次。返回成功 load 的 manifest 列表（fail-fast 失败抛 PluginError）。
        """
        root = Path(plugins_root)
        if not root.is_dir():
            _log.warning("plugins root %s does not exist", root)
            return []
        loaded: list[PlatformManifest] = []
        for plugin_dir in sorted(root.iterdir()):
            if not plugin_dir.is_dir():
                continue
            manifest_path = plugin_dir / "platform.yaml"
            if not manifest_path.is_file():
                continue
            try:
                manifest = load_manifest(manifest_path)
            except Exception as e:
                raise PluginError(f"failed to load manifest from {manifest_path}: {e}") from e
            if manifest.name in cls._MANIFESTS:
                raise PluginError(f"duplicate plugin name '{manifest.name}'")
            cls._MANIFESTS[manifest.name] = manifest
            loaded.append(manifest)
            _log.info("registered plugin manifest: %s v%s", manifest.name, manifest.version)
        return loaded

    @classmethod
    def list_manifests(cls) -> list[PlatformManifest]:
        return list(cls._MANIFESTS.values())

    @classmethod
    def get_manifest(cls, plugin_name: str) -> PlatformManifest | None:
        return cls._MANIFESTS.get(plugin_name)

    # ── per-workspace instance ──────────────────────────────────────────

    @classmethod
    async def get_plugin(
        cls,
        workspace_id: uuid.UUID,
        plugin_name: str,
        session: AsyncSession | None = None,
    ) -> PlatformPlugin | None:
        """懒加载：第一次拿就实例化 PlatformPlugin（daemon 暂 None — plan 05 注入）。

        Phase 5.A 不强制要求 plugin 已在 DB workspace_plugin_installations 表 install；
        plan 05 接入完整 install lifecycle 后再加 DB 校验。
        """
        key = (workspace_id, plugin_name)
        if key in cls._PLUGINS:
            return cls._PLUGINS[key]
        manifest = cls._MANIFESTS.get(plugin_name)
        if manifest is None:
            return None
        plugin = PlatformPlugin(manifest=manifest, daemon=None)
        cls._PLUGINS[key] = plugin
        return plugin

    @classmethod
    async def get_capability(
        cls,
        workspace_id: uuid.UUID,
        capability_type: type,
        *,
        prefer: str | None = None,
    ) -> Any | None:
        """按 capability 类型查可用 plugin facade。

        prefer 优先；否则按 _MANIFESTS 顺序找首个声明该 capability 的 plugin。
        找不到返回 None（CONTEXT.md decision: fail-quiet）。
        """
        cap_name = _capability_type_to_name(capability_type)
        if cap_name is None:
            return None

        # 优先 prefer
        candidates: list[str] = []
        if prefer and prefer in cls._MANIFESTS:
            candidates.append(prefer)
        for name in cls._MANIFESTS:
            if name not in candidates:
                candidates.append(name)

        for name in candidates:
            manifest = cls._MANIFESTS[name]
            if cap_name in manifest.capabilities:
                plugin = await cls.get_plugin(workspace_id, name)
                if plugin is None:
                    continue
                facade = getattr(plugin, cap_name, None)
                if facade is not None:
                    return facade
        return None


def _capability_type_to_name(t: type) -> str | None:
    """IMCapability → "im" / DocCapability → "doc" / ..."""
    mapping = {
        "IMCapability": "im",
        "DocCapability": "doc",
        "HRCapability": "hr",
        "IdentityCapability": "identity",
        "TriggerCapability": "trigger",
        "ToolCapability": "tool",
    }
    return mapping.get(t.__name__)
```

≥ 150 行。

3. **`tests/platforms/test_registry.py`** ≥ 8 测试：

```python
"""PlatformPluginRegistry 单测。"""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from app.agent_builder.platforms.capabilities import IMCapability, HRCapability, DocCapability
from app.agent_builder.platforms.exceptions import PluginError
from app.agent_builder.platforms.registry import PlatformPluginRegistry


@pytest.fixture
def fresh_registry():
    PlatformPluginRegistry.clear()
    yield
    PlatformPluginRegistry.clear()


@pytest.fixture
def plugins_dir_with_huly(tmp_path: Path):
    """在 tmp_path 下做 plugins/huly/platform.yaml fixture。"""
    plugin_dir = tmp_path / "plugins" / "huly"
    plugin_dir.mkdir(parents=True)
    fixture = Path(__file__).parent / "fixtures" / "manifest_valid.yaml"
    shutil.copy(fixture, plugin_dir / "platform.yaml")
    return tmp_path / "plugins"


def test_discover_finds_huly(fresh_registry, plugins_dir_with_huly):
    loaded = PlatformPluginRegistry.discover(plugins_dir_with_huly)
    assert len(loaded) == 1
    assert loaded[0].name == "huly"
    assert PlatformPluginRegistry.get_manifest("huly") is not None


def test_discover_empty_dir_returns_empty(fresh_registry, tmp_path):
    result = PlatformPluginRegistry.discover(tmp_path / "doesnt_exist")
    assert result == []


def test_discover_invalid_manifest_raises(fresh_registry, tmp_path):
    bad = tmp_path / "plugins" / "bad"
    bad.mkdir(parents=True)
    (bad / "platform.yaml").write_text("not a valid yaml: : :")
    with pytest.raises(PluginError):
        PlatformPluginRegistry.discover(tmp_path / "plugins")


def test_discover_duplicate_name_raises(fresh_registry, tmp_path):
    """两个目录都叫 huly → raise（duplicate name）。"""
    fixture = Path(__file__).parent / "fixtures" / "manifest_valid.yaml"
    for sub in ["huly1", "huly2"]:
        d = tmp_path / "plugins" / sub
        d.mkdir(parents=True)
        shutil.copy(fixture, d / "platform.yaml")
    # 两个 yaml 都声明 name=huly — discover 时第二个 raise
    with pytest.raises(PluginError, match="duplicate"):
        PlatformPluginRegistry.discover(tmp_path / "plugins")


@pytest.mark.asyncio
async def test_get_plugin_lazy_returns_same_instance(fresh_registry, plugins_dir_with_huly):
    PlatformPluginRegistry.discover(plugins_dir_with_huly)
    ws = uuid.uuid4()
    p1 = await PlatformPluginRegistry.get_plugin(ws, "huly")
    p2 = await PlatformPluginRegistry.get_plugin(ws, "huly")
    assert p1 is p2  # 懒加载缓存


@pytest.mark.asyncio
async def test_two_workspaces_isolated(fresh_registry, plugins_dir_with_huly):
    """**Pitfall 5 关键验证**：双 workspace 拿到的是不同 plugin instance。"""
    PlatformPluginRegistry.discover(plugins_dir_with_huly)
    ws_a = uuid.uuid4()
    ws_b = uuid.uuid4()
    plugin_a = await PlatformPluginRegistry.get_plugin(ws_a, "huly")
    plugin_b = await PlatformPluginRegistry.get_plugin(ws_b, "huly")
    assert plugin_a is not None and plugin_b is not None
    assert plugin_a is not plugin_b   # 关键：双 workspace 隔离


@pytest.mark.asyncio
async def test_get_capability_im_returns_facade(fresh_registry, plugins_dir_with_huly):
    PlatformPluginRegistry.discover(plugins_dir_with_huly)
    cap = await PlatformPluginRegistry.get_capability(
        uuid.uuid4(), IMCapability, prefer="huly"
    )
    assert cap is not None  # facade stub 返回（plan 05 实接入）


@pytest.mark.asyncio
async def test_get_capability_missing_returns_none(fresh_registry, plugins_dir_with_huly):
    """huly manifest 不声明 trigger → get_capability(TriggerCapability) return None（fail-quiet）。"""
    from app.agent_builder.platforms.capabilities import TriggerCapability
    PlatformPluginRegistry.discover(plugins_dir_with_huly)
    cap = await PlatformPluginRegistry.get_capability(uuid.uuid4(), TriggerCapability)
    assert cap is None
```

8 测试，**关键覆盖 Pitfall 5 双 workspace 隔离**。
  </action>
  <verify>
    <automated>cd backend && python -c "from app.agent_builder.platforms.plugin import PlatformPlugin; from app.agent_builder.platforms.registry import PlatformPluginRegistry; print('OK')" && pytest tests/platforms/test_registry.py -v -x 2>&1 | tail -25 && wc -l backend/app/agent_builder/platforms/plugin.py | awk '{exit ($1 >= 80 ? 0 : 1)}' && wc -l backend/app/agent_builder/platforms/registry.py | awk '{exit ($1 >= 150 ? 0 : 1)}'</automated>
  </verify>
  <done>PlatformPlugin + PlatformPluginRegistry + capability_facades stub 可 import；8 单测 pass（含双 workspace 隔离）；3 文件分别 ≥ 80/150/40 行</done>
</task>

</tasks>

<verification>
- [ ] Reading doc commit 在前
- [ ] `pytest tests/platforms/test_manifest_schema.py tests/platforms/test_registry.py -v` 16+ tests pass
- [ ] black + ruff 通过
- [ ] Phase 4 81 IM 测试 0 regression
- [ ] Pitfall 5 双 workspace 隔离测试明确通过
</verification>

<success_criteria>
- PlatformManifest Pydantic v2 schema with extra=forbid + 3 invalid fixture 全 raise
- PlatformPluginRegistry per-workspace 隔离严格（test_two_workspaces_isolated 明确）
- 懒加载缓存：同 workspace 二次 get_plugin 返回同 instance
- get_capability fail-quiet（缺 capability return None 不抛）
- capability_facades.py stub 给 plan 05 留扩展点
</success_criteria>

<output>
完成后创建 `.planning/phases/05a-platform-plugin-framework/05a-04-SUMMARY.md`，含：
- Reading doc 链接 + commit hash
- 16+ 单测输出
- **Dify 参考点** 小节：5 借鉴点指回 reading doc
- 与 plan 05 的对接点：`PlatformPlugin.attach_daemon` 方法 / `capability_facades.py` stub 4 类需要 plan 05 替换为真 daemon 转发
</output>
