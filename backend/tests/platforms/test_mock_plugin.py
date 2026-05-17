"""MockPlatformPlugin 单测 — 多 capability 声明 + isinstance 协议校验 + capability 路径（PLUG-FW-06）。

测试覆盖：
- test_mock_plugin_multi_capability_facade: 4 capability 同时声明 + isinstance Protocol 校验
- test_mock_im_records_sent: MockIMCapability.send_card 记录历史
- test_mock_im_update_card: update_card 路径
- test_mock_im_send_text: send_text 路径
- test_mock_doc_create_document_returns_docref: create_document 返回 DocRef
- test_mock_doc_crdt_raises: apply_document_delta raise NotImplementedError（mock 不支持 CRDT）
- test_mock_doc_add_comment_returns_comment_ref: add_comment 路径
- test_mock_hr_resolve_department_members: resolve_department_members 返回 1 个 EmployeeRef
- test_mock_hr_create_leave_raises: create_leave_request raise（mock 不是 source_of_truth）
- test_mock_identity_watch_raises: watch_user_changes raise（is_source_of_truth=False）
- test_mock_plugin_repr: __repr__ 不报错
- test_mock_plugin_undeclared_capability_returns_none: manifest 不声明的 capability 返回 None
- test_mock_capabilities_isinstance_protocol: 每个 Mock<Cap> 类 isinstance 对应 Protocol
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent_builder.platforms.capabilities import (
    CRDTDelta,
    DocCapability,
    DocRef,
    EmployeeRef,
    HRCapability,
    IdentityCapability,
    IMCapability,
    NormalizedCard,
    RecipientSpec,
)
from app.agent_builder.platforms.manifest import load_manifest
from app.agent_builder.platforms.mock_plugin import (
    MockDocCapability,
    MockHRCapability,
    MockIdentityCapability,
    MockIMCapability,
    MockPlatformPlugin,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def valid_manifest():
    """加载 Plan 04 fixture — capabilities: [im, doc, hr, identity]."""
    return load_manifest(FIXTURES_DIR / "manifest_valid.yaml")


@pytest.fixture
def manifest_no_capabilities_path(tmp_path):
    """构造一个仅声明 [im] 的 manifest（用于 undeclared capability 测试）— 在 test 内 inline 写。"""
    p = tmp_path / "manifest_im_only.yaml"
    p.write_text(
        """
name: imonly
version: 1.0.0
description: "IM only"
runtime:
  type: python
  entry: foo.bar
capabilities: [im]
config_schema: {}
im:
  supports_native_buttons: true
""".strip(),
        encoding="utf-8",
    )
    return p


# ── 多 capability + Protocol 校验 ─────────────────────────────────────────────


def test_mock_plugin_multi_capability_facade(valid_manifest) -> None:
    """4 capability 同时声明 — 每个 isinstance 对应 Protocol（duck typing）."""
    plugin = MockPlatformPlugin(valid_manifest)
    assert plugin.im is not None
    assert plugin.doc is not None
    assert plugin.hr is not None
    assert plugin.identity is not None
    assert isinstance(plugin.im, IMCapability)
    assert isinstance(plugin.doc, DocCapability)
    assert isinstance(plugin.hr, HRCapability)
    assert isinstance(plugin.identity, IdentityCapability)


def test_mock_capabilities_isinstance_protocol() -> None:
    """每个 MockX 类直接 isinstance 对应 Protocol — 即使不通过 Plugin 也走 duck typing."""
    assert isinstance(MockIMCapability(), IMCapability)
    assert isinstance(MockDocCapability(), DocCapability)
    assert isinstance(MockHRCapability(), HRCapability)
    assert isinstance(MockIdentityCapability(), IdentityCapability)


def test_mock_plugin_undeclared_capability_returns_none(
    manifest_no_capabilities_path,
) -> None:
    """manifest 仅声明 [im] 时 — plugin.doc / .hr / .identity 全 None（与 PlatformPlugin 行为一致）."""
    manifest = load_manifest(manifest_no_capabilities_path)
    plugin = MockPlatformPlugin(manifest)
    assert plugin.im is not None  # 声明了
    assert plugin.doc is None
    assert plugin.hr is None
    assert plugin.identity is None


# ── IM capability 行为 ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mock_im_records_sent(valid_manifest) -> None:
    """MockIMCapability.send_card 记录历史 + 返回 deterministic MessageRef."""
    plugin = MockPlatformPlugin(valid_manifest)
    cap = plugin.im
    assert cap is not None
    msg = await cap.send_card(
        recipient=RecipientSpec(kind="channel", id="c1"),
        card=NormalizedCard(title="t", body_markdown="b", actions=[]),
        idempotency_key="k1",
    )
    assert msg.plugin_name == "mock"
    assert msg.native_id == "mock-1"
    # 历史
    assert len(cap.sent) == 1  # type: ignore[attr-defined]
    assert cap.sent[0][2] == "k1"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_mock_im_update_card(valid_manifest) -> None:
    """update_card 记录到 updated 列表."""
    plugin = MockPlatformPlugin(valid_manifest)
    cap = plugin.im
    assert cap is not None
    msg = await cap.send_card(
        recipient=RecipientSpec(kind="channel", id="c1"),
        card=NormalizedCard(title="t", body_markdown="b", actions=[]),
        idempotency_key="k1",
    )
    new_card = NormalizedCard(title="t2", body_markdown="b2", actions=[])
    await cap.update_card(msg, new_card)
    assert len(cap.updated) == 1  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_mock_im_send_text(valid_manifest) -> None:
    """send_text 返回 MessageRef 含 recipient id."""
    plugin = MockPlatformPlugin(valid_manifest)
    cap = plugin.im
    assert cap is not None
    msg = await cap.send_text(RecipientSpec(kind="dm_user", id="u42"), "hello")
    assert msg.native_id == "text-u42"


# ── Doc capability 行为 ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mock_doc_create_document_returns_docref(valid_manifest) -> None:
    """create_document 返回带 plugin_name='mock' + uuid native_id 的 DocRef."""
    plugin = MockPlatformPlugin(valid_manifest)
    cap = plugin.doc
    assert cap is not None
    doc = await cap.create_document(title="My Doc", markdown="hello")
    assert doc.plugin_name == "mock"
    assert len(doc.native_id) > 0


@pytest.mark.asyncio
async def test_mock_doc_crdt_raises(valid_manifest) -> None:
    """apply_document_delta raise NotImplementedError — mock supports_collaborative_edit=False."""
    plugin = MockPlatformPlugin(valid_manifest)
    cap = plugin.doc
    assert cap is not None
    with pytest.raises(NotImplementedError):
        await cap.apply_document_delta(
            DocRef(plugin_name="mock", native_id="d1"),
            CRDTDelta(format="yjs", payload=b""),
        )


@pytest.mark.asyncio
async def test_mock_doc_add_comment_returns_comment_ref(valid_manifest) -> None:
    """add_comment 返回 CommentRef 含 parent_doc_ref."""
    plugin = MockPlatformPlugin(valid_manifest)
    cap = plugin.doc
    assert cap is not None
    doc_ref = DocRef(plugin_name="mock", native_id="d1")
    comment = await cap.add_comment(doc_ref=doc_ref, body="great!")
    assert comment.plugin_name == "mock"
    assert comment.parent_doc_ref is doc_ref


# ── HR capability 行为 ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mock_hr_resolve_department_members(valid_manifest) -> None:
    """resolve_department_members 返回 1 个 EmployeeRef（mock 固定 demo）."""
    plugin = MockPlatformPlugin(valid_manifest)
    cap = plugin.hr
    assert cap is not None
    result = await cap.resolve_department_members("dept:研发部")
    assert len(result) == 1
    assert isinstance(result[0], EmployeeRef)
    assert result[0].plugin_name == "mock"


@pytest.mark.asyncio
async def test_mock_hr_create_leave_raises(valid_manifest) -> None:
    """create_leave_request raise — mock 不是 source_of_truth."""
    plugin = MockPlatformPlugin(valid_manifest)
    cap = plugin.hr
    assert cap is not None
    with pytest.raises(NotImplementedError):
        await cap.create_leave_request(
            employee_ref=EmployeeRef(plugin_name="mock", native_id="e1"),
            request_type="vacation",
            start_date="2026-05-17",
            end_date="2026-05-18",
            description="test",
        )


# ── Identity capability 行为 ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mock_identity_watch_raises(valid_manifest) -> None:
    """watch_user_changes raise — mock is_source_of_truth=False."""
    plugin = MockPlatformPlugin(valid_manifest)
    cap = plugin.identity
    assert cap is not None
    assert cap.is_source_of_truth is False
    with pytest.raises(NotImplementedError):
        # async generator — 必须真正迭代才触发 raise
        async for _evt in cap.watch_user_changes():
            break  # pragma: no cover


# ── 调试辅助 ─────────────────────────────────────────────────────────────────


def test_mock_plugin_repr(valid_manifest) -> None:
    """__repr__ 不报错 + 含 capabilities 列表."""
    plugin = MockPlatformPlugin(valid_manifest)
    r = repr(plugin)
    assert "MockPlatformPlugin" in r
    assert "huly" in r
    assert "im" in r
