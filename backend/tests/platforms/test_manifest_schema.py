"""PlatformManifest Pydantic v2 schema 单测（PLUG-FW-02 + Phase 5.B Plan 05b-01 PLUG-FW-13）。

测试覆盖（Phase 5.A ≥ 13 + Phase 5.B Plan 05b-01 ≥ 14）：

Phase 5.A（PLUG-FW-02 manifest 基础）：
1. test_valid_huly_manifest_parses — 完整 huly fixture 加载成功 + 字段语义正确
2. test_extra_field_rejected — extra=forbid 模式触发
3. test_empty_capabilities_rejected — @field_validator at_least_one_capability 触发
4. test_invalid_semver_rejected — version="1.0" 不匹配 SemVer 三段
5. test_invalid_name_format_rejected — name 含大写 / 空格 → raise
6. test_runtime_type_python_only — runtime.type="node" → raise
7. test_capability_literal_enum_enforced — capabilities=["unknown_cap"] → raise
8. test_yaml_not_a_mapping_rejected — YAML 顶层是 list 而非 mapping → raise
9. test_load_manifest_file_not_found — 文件不存在 → raise
10. test_load_manifest_invalid_yaml_syntax — YAML 语法错误 → raise
11. test_load_manifest_returns_correct_subtypes — 嵌套子类型正确
12. test_nested_extra_field_rejected — 嵌套 extra=forbid
13. test_optional_fields_use_defaults — Optional 默认值

Phase 5.B Plan 05b-01（PLUG-FW-13 SandboxConfig 扩展）：
TestSandboxConfig class 含 14 测试 — 见类内 docstring。

Reference: Dify `core/plugin/entities/plugin.py` Pydantic v2 校验模式（AGPL-3.0，仅借鉴）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.agent_builder.platforms.exceptions import ManifestValidationError
from app.agent_builder.platforms.manifest import (
    CapabilitySpec,
    PlatformManifest,
    RuntimeConfig,
    SandboxConfig,
    load_manifest,
)

# fixtures/ 目录绝对路径
FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ── Test 1: valid huly manifest 加载成功 + 字段语义全面检查 ──────────────────


def test_valid_huly_manifest_parses() -> None:
    """完整 huly fixture 加载成功 + 全字段语义校验。"""
    manifest = load_manifest(FIXTURES_DIR / "manifest_valid.yaml")

    # 基础元数据
    assert isinstance(manifest, PlatformManifest)
    assert manifest.name == "huly"
    assert manifest.version == "1.0.0"
    assert manifest.description == "Huly platform stub (Phase 5.A acid test)"
    assert manifest.license == "EPL-2.0"
    assert manifest.agent_builder_version == ">=1.0"

    # Runtime
    assert isinstance(manifest.runtime, RuntimeConfig)
    assert manifest.runtime.type == "python"
    assert manifest.runtime.entry == "plugins.huly.huly_plugin"
    assert manifest.runtime.python_version == "3.11"

    # Capabilities — 4 capability 全声明
    assert manifest.capabilities == ["im", "doc", "hr", "identity"]

    # IM cap flags
    assert isinstance(manifest.im, CapabilitySpec)
    assert manifest.im.supports_native_buttons is False
    assert manifest.im.supports_card_update is True
    assert manifest.im.supports_threads is True

    # Doc cap flags
    assert isinstance(manifest.doc, CapabilitySpec)
    assert manifest.doc.supports_collaborative_edit is True
    assert manifest.doc.supports_comments is True

    # Identity cap flags（is_source_of_truth Plan 03 Identity 关键 flag）
    assert isinstance(manifest.identity, CapabilitySpec)
    assert manifest.identity.is_source_of_truth is True

    # HR — fixture 未声明，应为 None
    assert manifest.hr is None

    # Config schema（JSON Schema dict 透传）
    assert manifest.config_schema["type"] == "object"
    assert "endpoint" in manifest.config_schema["required"]

    # Sandbox（Phase 5.B Plan 05b-01: memory_limit → memory rename）
    assert isinstance(manifest.sandbox, SandboxConfig)
    assert manifest.sandbox.cpu_limit == "1.0"
    assert manifest.sandbox.memory == "512Mi"
    assert manifest.sandbox.network == ["huly.example.com:443"]


# ── Test 2: extra=forbid 严格模式 ─────────────────────────────────────────────


def test_extra_field_rejected() -> None:
    """manifest 含未声明字段 → extra=forbid 触发 ManifestValidationError。"""
    with pytest.raises(ManifestValidationError) as exc_info:
        load_manifest(FIXTURES_DIR / "manifest_invalid_extra_field.yaml")

    # 错误信息应提及 extra forbid 或具体字段名
    err_str = str(exc_info.value).lower()
    assert "typo_field" in err_str or "extra" in err_str or "forbid" in err_str


# ── Test 3: at_least_one_capability validator ─────────────────────────────────


def test_empty_capabilities_rejected() -> None:
    """capabilities=[] → @field_validator 触发 raise。"""
    with pytest.raises(ManifestValidationError) as exc_info:
        load_manifest(FIXTURES_DIR / "manifest_no_capabilities.yaml")

    err_str = str(exc_info.value)
    assert "capability" in err_str.lower() or "至少 1 个" in err_str


# ── Test 4: 版本必须三段 SemVer ───────────────────────────────────────────────


def test_invalid_semver_rejected(tmp_path: Path) -> None:
    """version="1.0" 不匹配 pattern ^\\d+\\.\\d+\\.\\d+$ → raise。"""
    bad_manifest = tmp_path / "bad_version.yaml"
    bad_manifest.write_text(
        """
name: testpkg
version: "1.0"
description: "missing patch version"
runtime:
  type: python
  entry: testpkg.main
capabilities:
  - im
config_schema: {}
""",
        encoding="utf-8",
    )

    with pytest.raises(ManifestValidationError) as exc_info:
        load_manifest(bad_manifest)

    err_str = str(exc_info.value).lower()
    assert "version" in err_str or "pattern" in err_str


# ── Test 5: name 必须小写蛇形 ─────────────────────────────────────────────────


def test_invalid_name_format_rejected(tmp_path: Path) -> None:
    """name="Bad-Name" 含大写 → 不匹配 pattern → raise。"""
    bad_manifest = tmp_path / "bad_name.yaml"
    bad_manifest.write_text(
        """
name: "Bad-Name"
version: 1.0.0
description: "name with uppercase"
runtime:
  type: python
  entry: bad.main
capabilities: [im]
config_schema: {}
""",
        encoding="utf-8",
    )

    with pytest.raises(ManifestValidationError) as exc_info:
        load_manifest(bad_manifest)

    err_str = str(exc_info.value).lower()
    assert "name" in err_str or "pattern" in err_str


# ── Test 6: runtime.type v1 仅 python ─────────────────────────────────────────


def test_runtime_type_python_only(tmp_path: Path) -> None:
    """runtime.type="node" → Literal["python"] 不匹配 → raise（v1 锁定）。"""
    bad_manifest = tmp_path / "bad_runtime.yaml"
    bad_manifest.write_text(
        """
name: nodepkg
version: 1.0.0
description: "node runtime not supported in v1"
runtime:
  type: node
  entry: nodepkg.main
capabilities: [im]
config_schema: {}
""",
        encoding="utf-8",
    )

    with pytest.raises(ManifestValidationError) as exc_info:
        load_manifest(bad_manifest)

    err_str = str(exc_info.value).lower()
    assert "node" in err_str or "literal" in err_str or "python" in err_str


# ── Test 7: capabilities Literal 枚举强校验 ──────────────────────────────────


def test_capability_literal_enum_enforced(tmp_path: Path) -> None:
    """capabilities=["unknown_cap"] → Literal 不匹配 → raise。"""
    bad_manifest = tmp_path / "bad_cap.yaml"
    bad_manifest.write_text(
        """
name: badcap
version: 1.0.0
description: "unknown capability name"
runtime:
  type: python
  entry: badcap.main
capabilities:
  - unknown_cap
config_schema: {}
""",
        encoding="utf-8",
    )

    with pytest.raises(ManifestValidationError) as exc_info:
        load_manifest(bad_manifest)

    err_str = str(exc_info.value).lower()
    assert "unknown_cap" in err_str or "literal" in err_str


# ── Test 8: YAML 顶层不是 mapping ─────────────────────────────────────────────


def test_yaml_not_a_mapping_rejected(tmp_path: Path) -> None:
    """YAML 顶层是 list 而非 dict → load_manifest 拒绝（不静默生成空 manifest）。"""
    bad_manifest = tmp_path / "list_top.yaml"
    bad_manifest.write_text("- item1\n- item2\n", encoding="utf-8")

    with pytest.raises(ManifestValidationError) as exc_info:
        load_manifest(bad_manifest)

    err_str = str(exc_info.value).lower()
    assert "mapping" in err_str or "dict" in err_str


# ── Test 9: 文件不存在 ────────────────────────────────────────────────────────


def test_load_manifest_file_not_found(tmp_path: Path) -> None:
    """传不存在的 path → raise ManifestValidationError（不是 FileNotFoundError）。"""
    missing = tmp_path / "does_not_exist.yaml"
    with pytest.raises(ManifestValidationError) as exc_info:
        load_manifest(missing)
    assert "不存在" in str(exc_info.value) or "not" in str(exc_info.value).lower()


# ── Test 10: YAML 语法错误 ────────────────────────────────────────────────────


def test_load_manifest_invalid_yaml_syntax(tmp_path: Path) -> None:
    """YAML 语法错误 → yaml.YAMLError → 翻译为 ManifestValidationError。"""
    bad_manifest = tmp_path / "bad_syntax.yaml"
    bad_manifest.write_text(
        "name: testpkg\nversion: 1.0.0\nruntime: : :\n  type: python\n",
        encoding="utf-8",
    )

    with pytest.raises(ManifestValidationError) as exc_info:
        load_manifest(bad_manifest)

    err_str = str(exc_info.value).lower()
    assert "yaml" in err_str or "parse" in err_str


# ── Test 11: 嵌套子类型正确实例化 + Optional 行为 ─────────────────────────────


def test_load_manifest_returns_correct_subtypes() -> None:
    """嵌套类型（RuntimeConfig / CapabilitySpec / SandboxConfig）正确实例化。"""
    manifest = load_manifest(FIXTURES_DIR / "manifest_valid.yaml")

    # 各嵌套类型 isinstance 检查
    assert isinstance(manifest.runtime, RuntimeConfig)
    assert isinstance(manifest.im, CapabilitySpec)
    assert isinstance(manifest.doc, CapabilitySpec)
    assert isinstance(manifest.identity, CapabilitySpec)
    assert isinstance(manifest.sandbox, SandboxConfig)

    # Optional 字段未声明应 None
    assert manifest.hr is None


# ── Test 12: extra=forbid 也适用于嵌套子模型 ──────────────────────────────────


def test_nested_extra_field_rejected(tmp_path: Path) -> None:
    """runtime 含未声明字段 → 嵌套 RuntimeConfig 也是 extra=forbid。"""
    bad_manifest = tmp_path / "bad_runtime_extra.yaml"
    bad_manifest.write_text(
        """
name: testpkg
version: 1.0.0
description: "runtime has typo field"
runtime:
  type: python
  entry: testpkg.main
  typo_in_runtime: "should reject"
capabilities: [im]
config_schema: {}
""",
        encoding="utf-8",
    )

    with pytest.raises(ManifestValidationError) as exc_info:
        load_manifest(bad_manifest)

    err_str = str(exc_info.value).lower()
    assert "typo_in_runtime" in err_str or "extra" in err_str or "forbid" in err_str


# ── Test 13: 默认值正确填充 ──────────────────────────────────────────────────


def test_optional_fields_use_defaults(tmp_path: Path) -> None:
    """Optional 字段未声明时使用默认值。"""
    minimal_manifest = tmp_path / "minimal.yaml"
    minimal_manifest.write_text(
        """
name: minimal
version: 1.0.0
description: "minimum required fields only"
runtime:
  type: python
  entry: minimal.main
capabilities: [im]
config_schema: {}
""",
        encoding="utf-8",
    )

    manifest = load_manifest(minimal_manifest)
    assert manifest.license is None
    assert manifest.agent_builder_version == ">=1.0"
    assert manifest.runtime.python_version == "3.11"
    assert manifest.im is None  # 即使 capabilities 含 im，未提供 im config block 也合法
    assert manifest.doc is None
    assert manifest.hr is None
    assert manifest.identity is None
    assert manifest.sandbox is None


# ──────────────────────────────────────────────────────────────────────────────
# Phase 5.B Plan 05b-01 — TestSandboxConfig (PLUG-FW-13)
# ──────────────────────────────────────────────────────────────────────────────


class TestSandboxConfig:
    """Phase 5.B Plan 05b-01: SandboxConfig 7 字段 + 2 派生属性 + 3 validators 单测。

    测试矩阵（14 测试）:
        - 默认值 / extra=forbid 兼容（2）
        - memory validator + memory_bytes property（3）
        - cpu_limit pattern + cpu_limit_seconds property（2）
        - network validator（3：缺 port / 含 scheme / 大写）
        - timeout_invoke / timeout_idle 范围（3）
        - env_allowlist 默认（1）
        - huly platform.yaml 加 sandbox 段后 load_manifest 不报错（1）
    """

    # ── 默认值 + extra=forbid ─────────────────────────────────────────────────

    def test_default_values(self) -> None:
        """SandboxConfig() 默认值（restrictive baseline）。"""
        c = SandboxConfig()
        assert c.cpu_limit == "2.0"
        assert c.memory == "1Gi"
        assert c.network == []  # 默认禁所有出站（CONTEXT.md decision）
        assert c.timeout_invoke == 30
        assert c.timeout_idle == 300
        assert c.use_cgroups is False
        assert c.env_allowlist == []  # Pitfall 8 默认 strip all

    def test_extra_field_rejected(self) -> None:
        """extra=forbid 兼容 5.A 决策 — 任何未声明字段 raise。"""
        with pytest.raises(ValidationError, match="unknown_field|extra|forbid"):
            SandboxConfig(unknown_field="x")  # type: ignore[call-arg]

    # ── memory validator + memory_bytes property ──────────────────────────────

    def test_memory_invalid_format_raises(self) -> None:
        """'512MB' 不合法（K8s 必须 Mi 不是 MB）。"""
        with pytest.raises(ValidationError, match="K8s 单位"):
            SandboxConfig(memory="512MB")

    def test_memory_bytes_property(self) -> None:
        """memory_bytes property 派生正确（'512Mi' → 512 * 1024^2）。"""
        c = SandboxConfig(memory="512Mi")
        assert c.memory_bytes == 512 * 1024**2

    def test_memory_default_bytes(self) -> None:
        """默认 '1Gi' → 1024^3 bytes。"""
        c = SandboxConfig()
        assert c.memory_bytes == 1024**3

    # ── cpu_limit pattern + cpu_limit_seconds property ────────────────────────

    def test_cpu_limit_pattern_rejects_letters(self) -> None:
        """cpu_limit='abc' 不匹配 pattern ^\\d+(\\.\\d+)?$。"""
        with pytest.raises(ValidationError, match="cpu_limit|pattern|string_pattern"):
            SandboxConfig(cpu_limit="abc")

    def test_cpu_limit_seconds_property(self) -> None:
        """cpu_limit_seconds property 派生正确（'1.5' → 1.5 * 3600 = 5400）。"""
        c = SandboxConfig(cpu_limit="1.5")
        assert c.cpu_limit_seconds == 5400

    # ── network validator (3 失败 case) ───────────────────────────────────────

    def test_network_entry_invalid_format_raises(self) -> None:
        """含 scheme 不合法（'http://example.com' 必须裸 host:port）。"""
        with pytest.raises(ValidationError, match="host:port"):
            SandboxConfig(network=["http://example.com"])

    def test_network_entry_must_have_port(self) -> None:
        """缺 port 不合法（'example.com'）。"""
        with pytest.raises(ValidationError, match="host:port"):
            SandboxConfig(network=["example.com"])

    def test_network_uppercase_host_raises(self) -> None:
        """大写 host 不合法（regex 仅匹配小写）。"""
        with pytest.raises(ValidationError, match="host:port"):
            SandboxConfig(network=["Example.com:443"])

    def test_network_valid_entries_pass(self) -> None:
        """合法 host:port 列表（多 entry / 子域名 / 含 -）。"""
        c = SandboxConfig(
            network=[
                "example.com:443",
                "api.feishu.cn:443",
                "huly-prod.example.com:8443",
            ]
        )
        assert len(c.network) == 3

    # ── timeout 范围（gt=0, le=3600 / le=86400）─────────────────────────────────

    def test_timeout_invoke_must_be_positive(self) -> None:
        """timeout_invoke=0 触发 gt=0 限制。"""
        with pytest.raises(ValidationError, match="timeout_invoke|greater"):
            SandboxConfig(timeout_invoke=0)

    def test_timeout_invoke_max_3600(self) -> None:
        """timeout_invoke=3601 超 le=3600 限制。"""
        with pytest.raises(ValidationError, match="timeout_invoke|less"):
            SandboxConfig(timeout_invoke=3601)

    def test_timeout_idle_max_86400(self) -> None:
        """timeout_idle=86401 超 le=86400 限制（一天 = 86400s）。"""
        with pytest.raises(ValidationError, match="timeout_idle|less"):
            SandboxConfig(timeout_idle=86401)

    # ── huly platform.yaml 加 sandbox 段后 load_manifest 不报错 ────────────────

    def test_huly_platform_yaml_parses_sandbox_section(self) -> None:
        """plugins/huly/platform.yaml 含 sandbox 段后 load_manifest 仍通过。

        验证 Plan 05b-01 对 plugins/huly/platform.yaml 的扩展未破坏 5.A acid test 数据源。
        Phase 5.C Plan 01 在 sandbox 段追加 docker_networks; 本测试一并校验 huly stack 内网。
        """
        # plugins/huly/platform.yaml 相对 backend/ 路径 = ../plugins/huly/platform.yaml
        huly_path = Path(__file__).parent.parent.parent.parent / "plugins" / "huly" / "platform.yaml"
        assert huly_path.is_file(), f"huly platform.yaml not found at {huly_path}"

        manifest = load_manifest(huly_path)
        assert manifest.sandbox is not None
        assert manifest.sandbox.memory == "512Mi"
        assert manifest.sandbox.network == ["huly.example.com:443"]
        assert manifest.sandbox.env_allowlist == ["HULY_ENDPOINT"]
        assert manifest.sandbox.timeout_invoke == 30
        assert manifest.sandbox.timeout_idle == 300
        assert manifest.sandbox.use_cgroups is False
        # Phase 5.C Plan 01: huly_huly_net 内网 attach（Pattern 4）
        assert manifest.sandbox.docker_networks == ["huly_huly_net"]
        # 派生属性
        assert manifest.sandbox.memory_bytes == 512 * 1024**2
        assert manifest.sandbox.cpu_limit_seconds == 3600  # cpu_limit='1.0' → 3600


# ──────────────────────────────────────────────────────────────────────────────
# Phase 5.C Plan 01 — TestSandboxConfigDockerNetworks (DOC-SANDBOX-NET-01)
# ──────────────────────────────────────────────────────────────────────────────


class TestSandboxConfigDockerNetworks:
    """Phase 5.C Plan 01 — SandboxConfig.docker_networks 字段校验（≥ 5 测试）。

    覆盖矩阵:
        - 默认空 list（PosixResourceSandbox no-op 路径）
        - 合法 docker network 命名（alphanumeric + _/./-/数字混合）
        - 含 `/` 拒（防 docker SDK 隐式拼接路径）
        - 首字符 `-` 拒（docker network create 不接受）
        - 含空格拒
    """

    def test_docker_networks_default_empty_list(self) -> None:
        """默认空 list = no attach（PosixResourceSandbox no-op 路径）。"""
        c = SandboxConfig()
        assert c.docker_networks == []

    def test_docker_networks_valid_names_accepted(self) -> None:
        """合法 docker network 命名（alphanumeric + _/./-）接受。"""
        c = SandboxConfig(
            docker_networks=["huly_huly_net", "my-net", "net.1", "A1net"]
        )
        assert c.docker_networks == ["huly_huly_net", "my-net", "net.1", "A1net"]

    def test_docker_networks_invalid_slash_rejected(self) -> None:
        """含 `/` 的命名 → ValidationError（防 docker SDK 拼接路径）。"""
        with pytest.raises(ValidationError, match="docker network 命名规范"):
            SandboxConfig(docker_networks=["bad/name"])

    def test_docker_networks_invalid_starts_with_dash_rejected(self) -> None:
        """首字符必须 alphanumeric（不允许 `_`/`-` 开头）→ ValidationError。"""
        with pytest.raises(ValidationError, match="docker network 命名规范"):
            SandboxConfig(docker_networks=["-bad"])

    def test_docker_networks_with_space_rejected(self) -> None:
        """含空格 → ValidationError。"""
        with pytest.raises(ValidationError, match="docker network 命名规范"):
            SandboxConfig(docker_networks=["bad name"])

    def test_docker_networks_with_colon_rejected(self) -> None:
        """含 `:` → ValidationError（防 docker SDK 误用 host:port 格式）。"""
        with pytest.raises(ValidationError, match="docker network 命名规范"):
            SandboxConfig(docker_networks=["host:1234"])

    def test_docker_networks_empty_string_rejected(self) -> None:
        """空字符串 entry → ValidationError（regex 不匹配 0 长字符串）。"""
        with pytest.raises(ValidationError, match="docker network 命名规范"):
            SandboxConfig(docker_networks=[""])
