"""DocCapability Protocol — Phase 5.A 协作文档能力契约（ADR-001 §3.2）。

设计要点（解决 Huly acid test §3.2 gap #2）：
- 拆分双路径：
  * `replace_document_content(doc_ref, markdown)` — 全量替换（Outline / Lark / WeCom）
  * `apply_document_delta(doc_ref, delta)` — CRDT delta（Huly / Notion）
- `supports_collaborative_edit: bool` cap flag 让调用方决定走哪条路径
  * True → 走 apply_document_delta；调用 replace_document_content raise NotImplementedError
  * False → 走 replace_document_content；调用 apply_document_delta raise NotImplementedError
- 6 值对象：DocRef / DocInfo / CRDTDelta / CommentRef / UserRef（dataclass frozen=True）

为什么拆双路径：
- Y.js CRDT 模型对协作文档要求 delta 增量更新，全量替换会破坏 CRDT 一致性
- Outline / Lark / WeCom 等传统平台仅支持全量替换 API
- 之前 DocProvider 设计（被 ADR-001 取代）用单一 `update_document` 含糊语义，
  在 Huly acid test 上 30% fit；本设计明确分离避免运行时混淆

Reference: docs/reading-dify-05a-02-capability-protocols-2026-05-17.md
- 借鉴点 #3（每 capability 一 file 组织）
- 借鉴点 #5（Declaration vs Runtime — runtime_checkable Protocol）
- 独有创新：双路径 + cap flag（Dify 无对应模式，本项目原创）

CLAUDE.md immutability：所有值对象 dataclass(frozen=True)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# ── 值对象（dataclass frozen=True）─────────────────────────────────────────────


@dataclass(frozen=True)
class DocRef:
    """Provider-agnostic 文档 handle — 用于 update / replace / apply_delta / 评论 等操作。

    与 IMCapability.MessageRef 同模式：plugin_name 前缀避免跨 plugin id 碰撞。

    Attributes:
        plugin_name: 标识来源 plugin（如 "huly" / "outline" / "lark"）
        native_id: 该 plugin 内部文档 ID
        extras: 调试 / 兼容字段（如 huly 的 collaboration_id）
    """

    plugin_name: str
    native_id: str
    extras: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DocInfo:
    """文档元信息 + 可选 content。

    部分 plugin（如 Huly）get_document 不返回 content_markdown 避免 N+1 调用；
    上层需要 content 时显式调 fetchMarkup 二跳。

    Attributes:
        doc_ref: 文档 handle
        title: 文档标题
        url: 浏览器可访问的 URL（可选；部分 plugin 不暴露 URL）
        content_markdown: 文档正文 Markdown（可选；Huly 等需二跳获取的 plugin 返回 None）
    """

    doc_ref: DocRef
    title: str
    url: str | None = None
    content_markdown: str | None = None


@dataclass(frozen=True)
class CRDTDelta:
    """CRDT delta 通用容器 — Phase 5.C 落地具体 Y.js / Automerge 格式。

    本 plan 02 仅定义 schema；实际 delta payload 编解码留 Plan 07+ HulyPlugin 落地。

    Attributes:
        format: delta 格式标识 — "yjs" | "automerge" | "json-patch"
        payload: 二进制 delta（Y.js 是二进制，Automerge 是二进制，json-patch 是 UTF-8 JSON 编码）
    """

    format: str
    payload: bytes


@dataclass(frozen=True)
class UserRef:
    """跨 plugin 用户 handle — 用于 add_comment.mentions / owners 等参数。

    与 DocRef 同模式：plugin_name 前缀避免跨 plugin id 碰撞。
    Phase 5.D 与 IdentityCapability.UserPrincipal 联动（user_platform_mappings 表查询）。

    Attributes:
        plugin_name: 标识来源 plugin
        native_id: 该 plugin 内部 user ID
    """

    plugin_name: str
    native_id: str


@dataclass(frozen=True)
class CommentRef:
    """评论 handle — 用于后续 update / delete / reply 操作。

    Attributes:
        plugin_name: 标识来源 plugin
        native_id: 该 plugin 内部 comment ID
        parent_doc_ref: 评论所属文档（便于追溯 + 删除时联级清理）
    """

    plugin_name: str
    native_id: str
    parent_doc_ref: DocRef


# ── DocCapability Protocol ────────────────────────────────────────────────────


@runtime_checkable
class DocCapability(Protocol):
    """协作文档能力 — create / replace / apply_delta / 评论 / 查文档。

    实现要求（任何 plugin 类声明 capabilities 含 "doc" 时）：
    - 类属性：name / supports_collaborative_edit / supports_comments
    - 方法：create_document / replace_document_content / apply_document_delta /
      add_comment / get_document 全部实现

    双路径设计（关键）：
    - supports_collaborative_edit=False（如 Outline / Lark / WeCom）：
      * replace_document_content 正常实现（全量替换 markdown）
      * apply_document_delta raise NotImplementedError（不支持 CRDT）
    - supports_collaborative_edit=True（如 Huly / Notion）：
      * apply_document_delta 正常实现（应用 CRDT delta）
      * replace_document_content raise NotImplementedError（破坏 CRDT 一致性）

    调用方约定：根据 cap flag 选路径
        if plugin.supports_collaborative_edit:
            await plugin.apply_document_delta(doc_ref, delta)
        else:
            await plugin.replace_document_content(doc_ref, markdown)

    supports_comments 语义：
    - True 时 add_comment 正常实现
    - False 时 add_comment 可 raise NotImplementedError（调用方应预检 flag）
    """

    name: str
    """Plugin 名（"huly" / "outline" / ...）"""

    supports_collaborative_edit: bool
    """True 走 apply_document_delta；False 走 replace_document_content"""

    supports_comments: bool
    """是否支持评论"""

    async def create_document(
        self,
        *,
        title: str,
        markdown: str,
        owners: list[UserRef] | None = None,
    ) -> DocRef:
        """创建新文档。

        Args:
            title: 文档标题
            markdown: 初始内容（Markdown 格式）
            owners: 文档 owner 列表（None 时由调用方上下文决定）

        Returns:
            DocRef — 用于后续 replace / apply_delta / 评论 操作
        """
        ...

    async def replace_document_content(
        self,
        doc_ref: DocRef,
        markdown: str,
    ) -> None:
        """全量替换文档内容 — 仅 supports_collaborative_edit=False 时调用。

        Outline / Lark / WeCom 等传统平台路径。

        Raises:
            NotImplementedError: 当 plugin supports_collaborative_edit=True 时
                                 （Huly / Notion CRDT 一致性要求；调用方应走 apply_document_delta）

        Args:
            doc_ref: 目标文档 handle
            markdown: 完整新内容（Markdown）
        """
        ...

    async def apply_document_delta(
        self,
        doc_ref: DocRef,
        delta: CRDTDelta,
    ) -> None:
        """应用 CRDT delta — 仅 supports_collaborative_edit=True 时调用。

        Huly / Notion 等 CRDT 协作平台路径。

        Raises:
            NotImplementedError: 当 plugin supports_collaborative_edit=False 时
                                 （Outline / Lark 不支持 CRDT；调用方应走 replace_document_content）

        Args:
            doc_ref: 目标文档 handle
            delta: CRDT delta（format=yjs/automerge/json-patch + 二进制 payload）
        """
        ...

    async def add_comment(
        self,
        *,
        doc_ref: DocRef,
        body: str,
        mentions: list[UserRef] | None = None,
    ) -> CommentRef:
        """在文档上添加评论。

        Args:
            doc_ref: 目标文档 handle
            body: 评论内容（Markdown 格式）
            mentions: @ 提及的用户列表（None 时不 @）

        Returns:
            CommentRef — 用于后续 update / delete / reply 操作

        Raises:
            NotImplementedError: 当 plugin supports_comments=False 时
        """
        ...

    async def get_document(self, doc_ref: DocRef) -> DocInfo | None:
        """查询文档信息（含可选 content）。

        Args:
            doc_ref: 目标文档 handle

        Returns:
            DocInfo — 文档元信息 + 可选 content_markdown
                     （Huly 等需二跳获取 content 的 plugin 返回 content_markdown=None）
            None — 文档不存在或无访问权限
        """
        ...
