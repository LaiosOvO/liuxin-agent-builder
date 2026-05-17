"""PlatformManifest Pydantic v2 schema 单测（PLUG-FW-02）。

测试覆盖（PLAN.md ≥ 8 测试要求）：
1. test_valid_huly_manifest_parses — 完整 huly fixture 加载成功 + 字段语义正确
2. test_extra_field_rejected — extra=forbid 模式触发（manifest_invalid_extra_field.yaml）
3. test_empty_capabilities_rejected — @field_validator at_least_one_capability 触发
4. test_invalid_semver_rejected — version="1.0" 不匹配 SemVer 三段
5. test_invalid_name_format_rejected — name 含大写 / 空格 → raise
6. test_runtime_type_python_only — runtime.type="node" → raise（v1 仅 Python）
7. test_capability_literal_enum_enforced — capabilities=["unknown_cap"] → raise
8. test_yaml_not_a_mapping_rejected — YAML 顶层是 list 而非 mapping → raise
9. test_load_manifest_file_not_found — 文件不存在 → raise
10. test_load_manifest_invalid_yaml_syntax — YAML 语法错误 → raise
11. test_load_manifest_returns_correct_subtypes — 嵌套 RuntimeConfig / CapabilitySpec / SandboxConfig 正确实例化

Reference: Dify `core/plugin/entities/plugin.py` Pydantic v2 校验模式（AGPL-3.0，仅借鉴）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

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
