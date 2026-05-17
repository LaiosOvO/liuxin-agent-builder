---
phase: 05a-platform-plugin-framework
plan: 02
type: execute
wave: 2
depends_on: ["01"]
files_modified:
  - docs/reading-dify-05a-02-capability-protocols-2026-05-17.md
  - backend/app/agent_builder/platforms/__init__.py
  - backend/app/agent_builder/platforms/capabilities/__init__.py
  - backend/app/agent_builder/platforms/capabilities/im.py
  - backend/app/agent_builder/platforms/capabilities/doc.py
  - backend/app/agent_builder/platforms/exceptions.py
  - tests/platforms/test_capabilities_im.py
  - tests/platforms/test_capabilities_doc.py
autonomous: true
requirements:
  - PLUG-FW-01
must_haves:
  truths:
    - "IMCapability Protocol 可被 isinstance 检查（runtime_checkable 生效）"
    - "DocCapability supports_collaborative_edit / supports_full_replace 双路径设计（Huly gap #2 解决）"
    - "RecipientSpec / NormalizedCard / MessageRef / DocRef / CRDTDelta 不可变值对象（frozen=True）"
  artifacts:
    - path: "backend/app/agent_builder/platforms/capabilities/im.py"
      provides: "IMCapability Protocol + RecipientSpec/NormalizedCard/MessageRef"
      exports: ["IMCapability", "RecipientSpec", "NormalizedCard", "MessageRef"]
      min_lines: 90
    - path: "backend/app/agent_builder/platforms/capabilities/doc.py"
      provides: "DocCapability Protocol + DocRef/CRDTDelta/CommentRef + 双路径方法 replace_document_content / apply_document_delta"
      exports: ["DocCapability", "DocRef", "CRDTDelta", "CommentRef", "DocInfo"]
      min_lines: 90
    - path: "backend/app/agent_builder/platforms/exceptions.py"
      provides: "PluginError / ManifestValidationError / CapabilityMissingError / PluginDaemonExitedError / PluginInvocationError 集中定义"
      exports: ["PluginError", "CapabilityMissingError", "PluginDaemonExitedError"]
  key_links:
    - from: "tests/platforms/test_capabilities_im.py"
      to: "backend/app/agent_builder/platforms/capabilities/im.py"
      via: "isinstance(MockIM(), IMCapability) → True"
      pattern: "isinstance.*IMCapability"
    - from: "backend/app/agent_builder/platforms/capabilities/doc.py"
      to: "Huly acid test 报告 §3.2 gap 1"
      via: "拆 replace_document_content / apply_document_delta 解决 CRDT 冲突"
      pattern: "supports_collaborative_edit"
---

<objective>
实现 6 Capability Protocols 的前 2 个（IM / Doc）+ exceptions 模块。每个 Protocol `@runtime_checkable` + 配套不可变值对象（dataclass frozen=True）+ 单测覆盖 isinstance 路径 + duck typing 路径。

Purpose: Capability 是后续 Registry / LegacyAdapter / HulyPlugin 的协议地基；IM 直接对应 Phase 4，Doc 解决 Huly CRDT gap。
Output: 4 文件 + 2 测试文件 + exception 模块。
</objective>

<execution_context>
@/Users/admin/.claude/get-shit-done/workflows/execute-plan.md
@/Users/admin/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/05a-platform-plugin-framework/05a-CONTEXT.md
@.planning/phases/05a-platform-plugin-framework/05a-RESEARCH.md
@docs/plans/2026-05-17-platform-plugin-framework-ADR.md
@docs/plans/2026-05-17-huly-spike-abstraction-acid-test.md
@backend/app/agent_builder/notification/providers/base.py

<interfaces>
<!-- Phase 4 IMProvider Protocol 风格（5.A IMCapability 沿用） -->

From backend/app/agent_builder/notification/providers/base.py:
```python
@runtime_checkable
class IMProvider(Protocol):
    name: str
    async def send_hitl_card(self, *, recipient: str, flow_title: str, ...) -> dict[str, Any]: ...
    async def update_card(self, *, message_id: str, new_content: dict[str, Any]) -> None: ...
```

5.A 在此基础上：
- recipient: str → RecipientSpec（多态 kind: channel / dm_user / thread）
- 返回 dict → MessageRef（dataclass frozen=True）
- card 参数集中为 NormalizedCard
- 新增 supports_native_buttons / supports_threads cap flags
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 0: Dify capability + endpoint 阅读文档（CLAUDE.md §2.7 硬性 gate）</name>
  <files>docs/reading-dify-05a-02-capability-protocols-2026-05-17.md</files>
  <action>
**STOP — 后续 commit 的前置 gate**。

读 Dify 源文件：
1. `/Users/admin/ai/ref/dify/repo/api/core/plugin/entities/endpoint.py` — EndpointDeclaration / EndpointProviderDeclaration 怎么声明 capability（method enum）
2. `/Users/admin/ai/ref/dify/repo/api/core/plugin/entities/plugin_daemon.py` — PluginToolProviderEntity / PluginModelProviderEntity / PluginDatasourceProviderEntity / PluginAgentProviderEntity 等 capability 子类
3. `/Users/admin/ai/ref/dify/repo/api/core/plugin/manager/tool.py`（若存在）或 `/Users/admin/ai/ref/dify/repo/api/core/tools/plugin_tool/` 目录顶层 — tool provider 怎么 dispatch capability call
4. `/Users/admin/ai/ref/dify/repo/api/core/plugin/entities/plugin.py` 重点 `PluginCategory` 枚举（"model" / "tool" / "agent" / "extension" 等）

写到 `docs/reading-dify-05a-02-capability-protocols-2026-05-17.md`，标准 5 节模板（参考 docs/reading-dify-05a-01-* 文档结构）。

**5 借鉴点至少包含**：
1. **PluginCategory 枚举**（plugin.py）→ 5.A `capabilities: list[Literal["im","doc","hr","identity","trigger","tool"]]` 对应
2. **EndpointMethodEnum**（endpoint.py 假设有 / GET POST 等）→ 5.A capability 内的 method 声明思路
3. **每 capability 一个 Entity 类**（PluginToolProviderEntity 等）→ 5.A 每 Protocol 一个 file 组织
4. **Provider runtime credentials**（怎么从 manifest 传到 capability 实现）→ 5.A workspace_plugin_installations.credentials_json 流转
5. **Capability 声明 vs runtime invocation 分离**（Declaration entity vs Entity）→ 5.A Manifest 静态声明 vs Capability instance 调用

**License attribution** 必须含；**不拷源代码**。

文档 ≥ 60 行，5 借鉴点指回 5.A 具体模块。
  </action>
  <verify>
    <automated>test -f docs/reading-dify-05a-02-capability-protocols-2026-05-17.md && wc -l docs/reading-dify-05a-02-capability-protocols-2026-05-17.md | awk '{exit ($1 >= 60 ? 0 : 1)}' && grep -q "AGPL\|Apache-2.0\|attribution" docs/reading-dify-05a-02-capability-protocols-2026-05-17.md</automated>
  </verify>
  <done>Reading doc ≥ 60 行 + License attribution + 5 借鉴点明确指回 5.A 模块 + commit 在前</done>
</task>

<task type="auto">
  <name>Task 1: exceptions 模块 + IMCapability Protocol + 值对象</name>
  <files>backend/app/agent_builder/platforms/__init__.py,backend/app/agent_builder/platforms/capabilities/__init__.py,backend/app/agent_builder/platforms/capabilities/im.py,backend/app/agent_builder/platforms/exceptions.py,tests/platforms/test_capabilities_im.py</files>
  <action>
Reading doc commit 已 ✓ 才能写代码。

1. **`backend/app/agent_builder/platforms/__init__.py`** 空文件 + 顶部 docstring `"""Phase 5.A PlatformPlugin 框架（ADR-001）。"""`

2. **`backend/app/agent_builder/platforms/capabilities/__init__.py`** export 集合：
```python
"""Capability Protocols — 每个 capability 一个 file。"""
from .im import IMCapability, MessageRef, NormalizedCard, RecipientSpec  # noqa: F401

__all__ = ["IMCapability", "MessageRef", "NormalizedCard", "RecipientSpec"]
```
（doc 在 Task 2 加进去）

3. **`backend/app/agent_builder/platforms/exceptions.py`**：
```python
"""Phase 5.A Plugin Framework 异常集中定义。"""
from __future__ import annotations


class PluginError(Exception):
    """Base for all plugin-related errors."""


class ManifestValidationError(PluginError):
    """Manifest YAML / Pydantic schema 校验失败。"""


class CapabilityMissingError(PluginError):
    """Plugin 不声明所请求的 capability。"""


class PluginDaemonExitedError(PluginError):
    """Daemon 子进程意外退出（fault isolation 关键）。"""


class PluginInvocationError(PluginError):
    """Plugin daemon 返回 JSONRPC error（非 transport 错误）。"""

    def __init__(self, error_payload: dict):
        self.error_payload = error_payload
        super().__init__(f"Plugin invocation error: {error_payload.get('message', '?')}")
```

4. **`backend/app/agent_builder/platforms/capabilities/im.py`**：完整实现按 RESEARCH.md `## Pattern 1` Example：
   - `RecipientSpec(kind: Literal["channel","dm_user","thread"], id: str, extras: dict)` frozen=True
   - `MessageRef(plugin_name: str, native_id: str, extras: dict)` frozen=True
   - `NormalizedCard(title: str, body_markdown: str, actions: list[dict])` frozen=True
   - `IMCapability` Protocol `@runtime_checkable`：
     - `supports_native_buttons: bool`
     - `supports_card_update: bool`
     - `supports_threads: bool`
     - `name: str` （为方便 Registry 路由）
     - `async send_card(*, recipient: RecipientSpec, card: NormalizedCard, idempotency_key: str) -> MessageRef`
     - `async update_card(msg_ref: MessageRef, card: NormalizedCard) -> None`
     - `async send_text(recipient: RecipientSpec, text: str) -> MessageRef`
     - `async subscribe_events(event_types: list[str]) -> AsyncIterator[dict[str, Any]]`
   - 每方法带 docstring 说明语义 + Phase 4 对应映射
   - 文件 ≥ 90 行

5. **`tests/platforms/test_capabilities_im.py`** 单测：
```python
"""IMCapability Protocol 单测 — isinstance + duck typing 路径。"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.agent_builder.platforms.capabilities import (
    IMCapability,
    MessageRef,
    NormalizedCard,
    RecipientSpec,
)


class _MinimalIM:
    """最小实现 — 仅用于 isinstance check。"""
    name = "mock_min"
    supports_native_buttons = True
    supports_card_update = True
    supports_threads = False

    async def send_card(self, *, recipient, card, idempotency_key):
        return MessageRef(plugin_name="mock", native_id="m1")

    async def update_card(self, msg_ref, card):
        pass

    async def send_text(self, recipient, text):
        return MessageRef(plugin_name="mock", native_id="t1")

    async def subscribe_events(self, event_types):
        if False:
            yield {}


def test_im_capability_isinstance():
    """runtime_checkable 生效 — _MinimalIM 无需继承也 pass isinstance。"""
    assert isinstance(_MinimalIM(), IMCapability)


def test_recipient_spec_immutable():
    """RecipientSpec frozen=True — 不可变。"""
    r = RecipientSpec(kind="dm_user", id="user_abc")
    try:
        r.id = "user_xyz"  # type: ignore
    except (AttributeError, Exception):
        pass
    else:
        raise AssertionError("RecipientSpec should be frozen")


def test_normalized_card_immutable():
    c = NormalizedCard(title="t", body_markdown="b", actions=[])
    assert c.title == "t"


def test_message_ref_immutable():
    m = MessageRef(plugin_name="huly", native_id="abc")
    assert m.plugin_name == "huly"


def test_kinds_enumerated():
    """RecipientSpec.kind 限定 channel/dm_user/thread。"""
    for k in ["channel", "dm_user", "thread"]:
        RecipientSpec(kind=k, id="x")  # type: ignore[arg-type] — Literal check
```

≥ 5 测试，覆盖 isinstance + 3 dataclass 不可变性 + Literal 枚举。
  </action>
  <verify>
    <automated>cd backend && python -c "from app.agent_builder.platforms.capabilities import IMCapability, RecipientSpec, NormalizedCard, MessageRef; print('OK')" && pytest tests/platforms/test_capabilities_im.py -v -x 2>&1 | tail -15 && wc -l backend/app/agent_builder/platforms/capabilities/im.py | awk '{exit ($1 >= 90 ? 0 : 1)}'</automated>
  </verify>
  <done>IMCapability + 3 值对象可 import；5 单测 pass；im.py ≥ 90 行</done>
</task>

<task type="auto">
  <name>Task 2: DocCapability Protocol + 双路径 replace/apply_delta + 单测</name>
  <files>backend/app/agent_builder/platforms/capabilities/doc.py,backend/app/agent_builder/platforms/capabilities/__init__.py,tests/platforms/test_capabilities_doc.py</files>
  <action>
1. **`backend/app/agent_builder/platforms/capabilities/doc.py`** 按 ADR-001 §3.2 + Huly acid test §3.2 gap 1：

```python
"""DocCapability — 协作文档能力。

设计要点（参考 ADR-001 §3.2 + Huly acid test §3.2 gap 1）：
- 拆分 replace_document_content（全量替换 — Outline/Lark）vs apply_document_delta（CRDT delta — Huly/Notion）
- supports_collaborative_edit cap flag 让调用方决定走哪条路径
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class DocRef:
    plugin_name: str
    native_id: str
    extras: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DocInfo:
    doc_ref: DocRef
    title: str
    url: str | None = None
    content_markdown: str | None = None  # 部分 plugin 不返回（如 Huly 需 fetchMarkup 二跳）


@dataclass(frozen=True)
class CRDTDelta:
    """Y.js / Automerge 通用 delta 容器 — Phase 5.C 落地具体格式。"""
    format: str           # "yjs" | "automerge" | "json-patch"
    payload: bytes        # 二进制 delta（或 JSON encoded）


@dataclass(frozen=True)
class CommentRef:
    plugin_name: str
    native_id: str
    parent_doc_ref: DocRef


@dataclass(frozen=True)
class UserRef:
    plugin_name: str
    native_id: str


@runtime_checkable
class DocCapability(Protocol):
    """协作文档能力。"""

    name: str
    supports_collaborative_edit: bool   # True: 用 apply_document_delta；False: 用 replace_document_content
    supports_comments: bool

    async def create_document(
        self,
        *,
        title: str,
        markdown: str,
        owners: list[UserRef] | None = None,
    ) -> DocRef: ...

    async def replace_document_content(
        self,
        doc_ref: DocRef,
        markdown: str,
    ) -> None:
        """全量替换 — 仅当 supports_collaborative_edit=False 时调用（Outline / Lark / WeCom）。
        
        若 plugin supports_collaborative_edit=True 调用此方法 → raise NotImplementedError。
        """
        ...

    async def apply_document_delta(
        self,
        doc_ref: DocRef,
        delta: CRDTDelta,
    ) -> None:
        """CRDT delta — 仅当 supports_collaborative_edit=True 时调用（Huly / Notion）。
        
        若 plugin supports_collaborative_edit=False 调用此方法 → raise NotImplementedError。
        """
        ...

    async def add_comment(
        self,
        *,
        doc_ref: DocRef,
        body: str,
        mentions: list[UserRef] | None = None,
    ) -> CommentRef: ...

    async def get_document(self, doc_ref: DocRef) -> DocInfo | None: ...
```

文件 ≥ 90 行。每方法 docstring 说明双路径语义。

2. **`backend/app/agent_builder/platforms/capabilities/__init__.py`** 追加 doc exports：
```python
from .doc import CommentRef, CRDTDelta, DocCapability, DocInfo, DocRef, UserRef  # noqa: F401

__all__ = [
    "IMCapability", "MessageRef", "NormalizedCard", "RecipientSpec",
    "DocCapability", "DocRef", "DocInfo", "CRDTDelta", "CommentRef", "UserRef",
]
```

3. **`tests/platforms/test_capabilities_doc.py`** 单测：

```python
"""DocCapability 单测 — runtime_checkable + 双路径 + 值对象不可变。"""
from __future__ import annotations

from app.agent_builder.platforms.capabilities import (
    CRDTDelta,
    DocCapability,
    DocInfo,
    DocRef,
)


class _OutlineLikeDoc:
    """全量替换路径 plugin（Outline / Lark 风格）。"""
    name = "outline_mock"
    supports_collaborative_edit = False
    supports_comments = True

    async def create_document(self, *, title, markdown, owners=None):
        return DocRef(plugin_name="outline_mock", native_id="doc1")

    async def replace_document_content(self, doc_ref, markdown):
        pass

    async def apply_document_delta(self, doc_ref, delta):
        raise NotImplementedError("Outline 不支持 CRDT")

    async def add_comment(self, *, doc_ref, body, mentions=None):
        return None  # type: ignore

    async def get_document(self, doc_ref):
        return None


class _HulyLikeDoc:
    """CRDT 路径 plugin（Huly / Notion 风格）。"""
    name = "huly_mock"
    supports_collaborative_edit = True
    supports_comments = True

    async def create_document(self, *, title, markdown, owners=None):
        return DocRef(plugin_name="huly_mock", native_id="doc1")

    async def replace_document_content(self, doc_ref, markdown):
        raise NotImplementedError("Huly 是 CRDT，必须走 apply_document_delta")

    async def apply_document_delta(self, doc_ref, delta):
        pass

    async def add_comment(self, *, doc_ref, body, mentions=None):
        return None  # type: ignore

    async def get_document(self, doc_ref):
        return None


def test_doc_capability_isinstance_outline():
    assert isinstance(_OutlineLikeDoc(), DocCapability)


def test_doc_capability_isinstance_huly():
    assert isinstance(_HulyLikeDoc(), DocCapability)


def test_doc_ref_immutable():
    d = DocRef(plugin_name="x", native_id="y")
    assert d.plugin_name == "x"


def test_crdt_delta_carries_format():
    delta = CRDTDelta(format="yjs", payload=b"\x00\x01")
    assert delta.format == "yjs"


def test_doc_info_optional_content():
    info = DocInfo(doc_ref=DocRef(plugin_name="x", native_id="y"), title="t")
    assert info.content_markdown is None  # Huly 二跳风格


def test_dual_path_mutual_exclusion():
    """全量替换 vs CRDT 二选一，调错路径 raise。"""
    import asyncio
    outline = _OutlineLikeDoc()
    huly = _HulyLikeDoc()
    
    async def check():
        try:
            await outline.apply_document_delta(DocRef(plugin_name="x", native_id="y"), CRDTDelta(format="yjs", payload=b""))
            assert False, "should raise"
        except NotImplementedError:
            pass
        
        try:
            await huly.replace_document_content(DocRef(plugin_name="x", native_id="y"), "## hi")
            assert False, "should raise"
        except NotImplementedError:
            pass
    
    asyncio.run(check())
```

≥ 6 测试，覆盖双 plugin 风格 isinstance + 值对象 + 双路径互斥 raise。
  </action>
  <verify>
    <automated>cd backend && python -c "from app.agent_builder.platforms.capabilities import DocCapability, DocRef, CRDTDelta, DocInfo; print('OK')" && pytest tests/platforms/test_capabilities_doc.py -v -x 2>&1 | tail -15 && wc -l backend/app/agent_builder/platforms/capabilities/doc.py | awk '{exit ($1 >= 90 ? 0 : 1)}'</automated>
  </verify>
  <done>DocCapability + 5 值对象可 import；6 单测 pass；doc.py ≥ 90 行；双路径互斥语义明确（错路径 NotImplementedError）</done>
</task>

</tasks>

<verification>
- [ ] Reading doc commit 在前
- [ ] `pytest tests/platforms/test_capabilities_im.py tests/platforms/test_capabilities_doc.py -v` 11+ tests pass
- [ ] `python -c "from app.agent_builder.platforms.capabilities import IMCapability, DocCapability"` 无错
- [ ] black + ruff 通过
- [ ] Phase 4 81 IM 测试 0 regression
</verification>

<success_criteria>
- IMCapability + DocCapability Protocol 定义清晰，方法签名匹配 ADR-001 §3.1/3.2
- 双路径（replace vs apply_delta）解决 Huly gap #2
- 6 dataclass 全部 frozen=True（CLAUDE.md immutability）
- runtime_checkable isinstance 路径单测覆盖 ≥ 2 plugin 风格
- exceptions 模块 5 异常类集中定义
</success_criteria>

<output>
完成后创建 `.planning/phases/05a-platform-plugin-framework/05a-02-SUMMARY.md`，含：
- 两 reading doc 链接 + commit hash
- Capability 测试输出（pass 数）
- **Dify 参考点** 小节：5 借鉴点指回 reading doc
- Huly acid test gap → 5.A 解决映射：gap #1 (Recipient) / gap #2 (DocProvider CRDT)
</output>
