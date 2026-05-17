"""DocCapability Protocol 单测 — runtime_checkable + 双路径互斥 + 值对象不可变。

测试覆盖（plan 02 要求 ≥ 6 测试）：
1. test_doc_capability_isinstance_outline — 全量替换风格 plugin isinstance pass
2. test_doc_capability_isinstance_huly — CRDT 风格 plugin isinstance pass
3. test_doc_ref_immutable — frozen=True
4. test_crdt_delta_carries_format — format + payload 字段
5. test_doc_info_optional_content — content_markdown 可为 None（Huly 二跳风格）
6. test_user_ref_immutable — UserRef 不可变
7. test_comment_ref_carries_parent — CommentRef.parent_doc_ref 关联
8. test_dual_path_mutual_exclusion — 调错路径 raise NotImplementedError（核心 Huly gap 解决）
9. test_doc_capability_negative_missing_method — runtime_checkable negative case

直接子模块 import — Plan 02 不写 capabilities/__init__.py 完整 exports（Plan 03 独占）。
"""

from __future__ import annotations

import asyncio

from app.agent_builder.platforms.capabilities.doc import (
    CommentRef,
    CRDTDelta,
    DocCapability,
    DocInfo,
    DocRef,
    UserRef,
)


class _OutlineLikeDoc:
    """全量替换路径 plugin（Outline / Lark 风格）。"""

    name = "outline_mock"
    supports_collaborative_edit = False
    supports_comments = True

    async def create_document(self, *, title, markdown, owners=None):
        return DocRef(plugin_name="outline_mock", native_id="doc1")

    async def replace_document_content(self, doc_ref, markdown):
        # 正常实现 — 全量替换
        pass

    async def apply_document_delta(self, doc_ref, delta):
        raise NotImplementedError(
            "Outline 不支持 CRDT delta（supports_collaborative_edit=False）"
        )

    async def add_comment(self, *, doc_ref, body, mentions=None):
        return CommentRef(
            plugin_name="outline_mock",
            native_id="cmt1",
            parent_doc_ref=doc_ref,
        )

    async def get_document(self, doc_ref):
        return DocInfo(
            doc_ref=doc_ref,
            title="Outline doc",
            url="https://outline.example.com/doc/1",
            content_markdown="# Hello",
        )


class _HulyLikeDoc:
    """CRDT 路径 plugin（Huly / Notion 风格）。"""

    name = "huly_mock"
    supports_collaborative_edit = True
    supports_comments = True

    async def create_document(self, *, title, markdown, owners=None):
        return DocRef(plugin_name="huly_mock", native_id="doc1")

    async def replace_document_content(self, doc_ref, markdown):
        raise NotImplementedError(
            "Huly 是 CRDT 一致性模型，必须走 apply_document_delta（supports_collaborative_edit=True）"
        )

    async def apply_document_delta(self, doc_ref, delta):
        # 正常实现 — 应用 CRDT delta
        pass

    async def add_comment(self, *, doc_ref, body, mentions=None):
        return CommentRef(
            plugin_name="huly_mock",
            native_id="cmt1",
            parent_doc_ref=doc_ref,
        )

    async def get_document(self, doc_ref):
        # Huly 二跳风格 — 不在 get_document 返回 content（需后续 fetchMarkup）
        return DocInfo(
            doc_ref=doc_ref,
            title="Huly doc",
            url="https://huly.example.com/d/1",
            content_markdown=None,
        )


class _DocWithoutApplyDelta:
    """Negative case — 缺 apply_document_delta 方法。"""

    name = "missing"
    supports_collaborative_edit = False
    supports_comments = False

    async def create_document(self, *, title, markdown, owners=None):
        return DocRef(plugin_name="x", native_id="x")

    async def replace_document_content(self, doc_ref, markdown):
        pass

    async def add_comment(self, *, doc_ref, body, mentions=None):
        return CommentRef(plugin_name="x", native_id="c", parent_doc_ref=doc_ref)

    async def get_document(self, doc_ref):
        return None


# ── 测试 ──────────────────────────────────────────────────────────────────────


def test_doc_capability_isinstance_outline():
    """runtime_checkable 生效 — Outline 风格（全量替换）pass isinstance。"""
    assert isinstance(_OutlineLikeDoc(), DocCapability)


def test_doc_capability_isinstance_huly():
    """runtime_checkable 生效 — Huly 风格（CRDT）pass isinstance。"""
    assert isinstance(_HulyLikeDoc(), DocCapability)


def test_doc_ref_immutable():
    """DocRef frozen=True + default extras。"""
    d = DocRef(plugin_name="x", native_id="y")
    assert d.plugin_name == "x"
    assert d.extras == {}
    # with extras
    d2 = DocRef(plugin_name="huly", native_id="z", extras={"collab_id": "c1"})
    assert d2.extras["collab_id"] == "c1"
    # frozen 断言
    try:
        d.plugin_name = "z"  # type: ignore[misc]
    except Exception:
        pass
    else:
        raise AssertionError("DocRef should be frozen")


def test_crdt_delta_carries_format():
    """CRDTDelta format + payload 字段（Y.js / Automerge / json-patch 三选一）。"""
    delta = CRDTDelta(format="yjs", payload=b"\x00\x01\x02")
    assert delta.format == "yjs"
    assert delta.payload == b"\x00\x01\x02"
    # Automerge
    delta2 = CRDTDelta(format="automerge", payload=b"automerge_bytes")
    assert delta2.format == "automerge"
    # json-patch (utf-8 encoded JSON)
    delta3 = CRDTDelta(
        format="json-patch", payload=b'[{"op":"add","path":"/x","value":1}]'
    )
    assert delta3.format == "json-patch"
    # frozen 断言
    try:
        delta.format = "other"  # type: ignore[misc]
    except Exception:
        pass
    else:
        raise AssertionError("CRDTDelta should be frozen")


def test_doc_info_optional_content():
    """DocInfo content_markdown 可为 None（Huly 二跳风格）+ url 也可为 None。"""
    # Outline 风格：含 content
    info1 = DocInfo(
        doc_ref=DocRef(plugin_name="x", native_id="y"),
        title="t",
        url="https://x/y",
        content_markdown="# hi",
    )
    assert info1.content_markdown == "# hi"
    # Huly 风格：content 二跳
    info2 = DocInfo(
        doc_ref=DocRef(plugin_name="huly", native_id="z"),
        title="huly doc",
        url="https://huly/z",
        content_markdown=None,
    )
    assert info2.content_markdown is None
    # 无 URL（部分内部 plugin）
    info3 = DocInfo(
        doc_ref=DocRef(plugin_name="internal", native_id="a"),
        title="internal",
    )
    assert info3.url is None
    assert info3.content_markdown is None


def test_user_ref_immutable():
    """UserRef frozen=True。"""
    u = UserRef(plugin_name="huly", native_id="user_abc")
    assert u.plugin_name == "huly"
    try:
        u.native_id = "user_xyz"  # type: ignore[misc]
    except Exception:
        pass
    else:
        raise AssertionError("UserRef should be frozen")


def test_comment_ref_carries_parent():
    """CommentRef.parent_doc_ref 关联文档（便于追溯 + 联级删除）。"""
    doc = DocRef(plugin_name="huly", native_id="doc1")
    cmt = CommentRef(plugin_name="huly", native_id="cmt1", parent_doc_ref=doc)
    assert cmt.parent_doc_ref == doc
    assert cmt.parent_doc_ref.native_id == "doc1"
    # frozen 断言
    try:
        cmt.native_id = "cmt2"  # type: ignore[misc]
    except Exception:
        pass
    else:
        raise AssertionError("CommentRef should be frozen")


def test_dual_path_mutual_exclusion():
    """核心：双路径互斥 — 调错路径 raise NotImplementedError。

    解决 Huly acid test gap #2：
    - Outline (supports_collaborative_edit=False) 调 apply_document_delta → raise
    - Huly (supports_collaborative_edit=True) 调 replace_document_content → raise
    """
    outline = _OutlineLikeDoc()
    huly = _HulyLikeDoc()

    async def check():
        # Outline 不应支持 CRDT
        try:
            await outline.apply_document_delta(
                DocRef(plugin_name="outline", native_id="d1"),
                CRDTDelta(format="yjs", payload=b""),
            )
            raise AssertionError(
                "Outline should raise NotImplementedError on apply_document_delta"
            )
        except NotImplementedError:
            pass  # 预期行为

        # Huly 不应支持全量替换
        try:
            await huly.replace_document_content(
                DocRef(plugin_name="huly", native_id="d1"),
                "## new content",
            )
            raise AssertionError(
                "Huly should raise NotImplementedError on replace_document_content"
            )
        except NotImplementedError:
            pass  # 预期行为

        # 反向：双方调对路径应正常
        await outline.replace_document_content(
            DocRef(plugin_name="outline", native_id="d1"), "## hi"
        )
        await huly.apply_document_delta(
            DocRef(plugin_name="huly", native_id="d1"),
            CRDTDelta(format="yjs", payload=b"\x00"),
        )

    asyncio.run(check())


def test_doc_capability_negative_missing_method():
    """runtime_checkable negative case — 缺 apply_document_delta 方法 → isinstance False。"""
    assert not isinstance(
        _DocWithoutApplyDelta(), DocCapability
    ), "缺 apply_document_delta 的类不应 pass isinstance(DocCapability)"
