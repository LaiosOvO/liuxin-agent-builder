# 参考阅读笔记 — LarkDocsPlugin (Dify + lark-oapi 实战)

> 日期: 2026-05-18
> 仓库:
>   - **Dify** https://github.com/langgenius/dify (local clone `/Users/admin/ai/ref/dify/repo/`, AGPL-3.0 — **仅借鉴模式 / 不拷源码**)
>   - **lark-oapi** https://github.com/larksuite/oapi-sdk-python (PyPI 1.6.5, MIT — **作 dependency import**)
>   - **飞书 Open Platform 官方文档** https://open.feishu.cn/document/ (公开规范)
> Stars: Dify ~141k / lark-oapi ~700
> Plan: 05c-04 — **LarkDocsPlugin (DocCapability + IdentityCapability multi-facet)** Wave 2
> 上游已读 reading docs（避免重复造轮子）:
>   - `docs/reading-im-sdk-04-06-feishu-2026-05-17.md`（Phase 4.06 lark-oapi 1.6.5 / Builder / Response / asyncio 包装）
>   - `docs/reading-dify-04-01-chain-payload-2026-05-17.md` 等 Phase 4 系列（HITL chain payload，本 plan 不重复涉及）

---

## 1. 项目概述（一句话）

**LarkDocsPlugin** 是 Phase 5.C 的**首个 multi-capability plugin** —— `DocCapability + IdentityCapability` 共享**单 daemon 进程 + 单 `lark.Client` 实例**，通过 markdown → Lark Block JSON 二段写入支持飞书文档创建/全量替换/评论 + @人，并以 manifest 静态 identity_map（v1）将业务 username 解析为 `lark_open_id`，沿用 Phase 4.06 FeishuProvider 已验证的 lark-oapi 1.6.5 + `asyncio.to_thread` 包装模式。

---

## 2. 技术栈关键技术选择

### 2.1 Dify 调研结论（关键 ❗）

执行命令验证：

```bash
ls /Users/admin/ai/ref/dify/repo/api/core/tools/builtin_tool/providers/
# → __init__.py / _positions.py / audio / code / time / webscraper
ls /Users/admin/ai/ref/dify/repo/api/core/tools/ | grep -i "lark\|feishu"
# → (空 — 无内置 lark/feishu provider)
```

**结论**：**Dify 不在 `builtin_tool` 内置 lark/feishu provider**，飞书相关能力全部走 Dify Plugin Marketplace（第三方 plugin 形态，runtime 是 dify-plugin-daemon 子进程）。本 plan 因此 **没有对应 Dify 模块可借鉴具体 Lark Docs API 实现**。

但仍可借鉴 Dify 已沉淀的工程模式（已在前序 reading doc 涵盖，本 doc 引用即可）：
1. **Plugin manifest YAML schema 分组**：Dify plugin `manifest.yaml` 用 `meta` / `endpoints` / `tools` / `models` 分块声明能力 → 与本 plan `platform.yaml` 的 `capabilities: [doc, identity]` + `doc:` / `identity:` 子段同构（5a-01 reading doc 涵盖）
2. **Plugin daemon 进程隔离 + JSONRPC envelope**：Dify plugin 走 stdin/stdout JSONRPC 与主进程通信 → 本项目 5.A Plan 04 PlatformPlugin 沿用（5a-04/5a-05 reading doc 涵盖）
3. **Tool credential lifecycle**：Dify `api/core/tools/__base/tool_provider.py` 抽象 credential validate + storage → 本 plan `manifest.config_schema` 声明 `app_id` / `app_secret` / `identity_map`，主进程通过 IMCredentialsManager 一致管理（沿用 Phase 4 模式）

因此本 reading doc 的"借鉴部分"主要来自**lark-oapi 官方 SDK + 飞书 Open Platform 文档 + 本项目 Phase 4.06 FeishuProvider 已验证模式**，而**不是** Dify 源码。

### 2.2 lark-oapi 1.6.5（关键约束）

- **CLAUDE.md §3 强制版本锁定**：`backend/pyproject.toml` 已 pin `"lark-oapi==1.6.5"`
- **yanked 历史（必须 pin 的原因）**：
  - **1.6.0 / 1.6.1 / 1.6.2 / 1.6.3 全部已被 PyPI yanked**（`pip install lark-oapi==1.6.2` 会直接 ResolutionImpossible 拒绝）
  - 1.6.4 存在但被项目跳过（飞书官方未在 release notes 公开 yank 原因，经验法则：飞书官方 SDK 通常 yank 因 import 不兼容 / runtime AttributeError / token 协议变更）
  - 1.6.5 是 Phase 4.06 已验证稳定线，本 plan 直接复用同版本，**不引入新 lark-oapi 依赖**（避免 backend / plugins 二处 SDK 版本漂移）
- **能力覆盖**：本 plan 用到的所有 API 都在 1.6.5 已稳定：
  - `lark_oapi.api.docx.v1`：`CreateDocumentRequest` + `ConvertRequest` + `CreateDocumentBlockChildrenRequest`
  - `lark_oapi.api.drive.v1`：`CreateCommentRequest`（评论 + @人）
  - `lark_oapi.api.contact.v3`：`GetUserRequest` / `BatchGetIdRequest`（identity v1 只读，list_users 用）
- **tenant_access_token 自动管理**：SDK 内置 cache + 自动 refresh（TTL ~6900s），**严禁自己写 refresh 逻辑**

### 2.3 marko 2.2.2（markdown AST 解析）

- 选 marko 不选 mistletoe：扩展系统更友好；BSD-3-Clause 兼容 Apache-2.0
- 用 `marko.ast_renderer.ASTRenderer` 拿到 element name=snake_case 树（marko 官方推荐方式）
- v1 仅使用 CommonMark 0.31.2 基础 + GFM 风格元素（不引入 table / footnote 扩展，留 v2）
- `_BLOCK_MAP` / `_MARK_MAP` 显式映射（防 Pitfall 6 节点名错位 — marko 节点名是 `strong_emphasis` 不是 `strong`）

### 2.4 飞书 Open Platform 文档关键约束

- 单 `blocks/convert` 请求最大 **10,485,760 字符**（10 MiB）→ Pitfall 3 防御
- 单次 `documents/{id}/blocks/{block_id}/children` 创建最大 **1000 block**（超出需分批；本 plan 按 800 切片留 200 余量）
- `merge_info` 字段必须从 table block 移除（read-only）
- 图片需 3 步：convert → create blocks → 单独上传素材填 image_id（v1 不支持，markdown 中的 `image` 退化为占位文本 + 提醒日志）
- 评论 @ 人通过 markdown body 内插入 `<at user_id="ou_xxx"></at>` 锚点（Lark 富文本 mention 语法）

---

## 3. SDK 版本验证（沿用 Phase 4.06 §3 模式）

**陷阱**：`lark.__version__` 属性**不存在**（直接访问返回 `'unknown'`）
**正确做法**：`importlib.metadata.version("lark-oapi")`（沿用 Phase 4 reading doc §3 + `backend/app/agent_builder/notification/providers/feishu.py:50-58`）

```python
from importlib.metadata import PackageNotFoundError, version as _pkg_version

_EXPECTED_LARK_VERSION = "1.6.5"

def _resolve_lark_version() -> str:
    try:
        return _pkg_version("lark-oapi")
    except PackageNotFoundError:
        return "unknown"
```

LarkDocsPlugin daemon 启动期校验：
- `actual_version != "1.6.5"` → `log.warning(...)`（不抛错 — 开发环境可能短暂不一致，与 Phase 4 行为一致）
- 单元测试通过 `monkeypatch` 替换返回值模拟版本不一致

---

## 4. 架构要点（核心架构模式）

### 4.1 整体拓扑

```
   主进程 (FastAPI / LangGraph)
              │ invoke ("doc.create_document" / "identity.resolve_user")
              ▼ JSONRPC over stdio  (Phase 5.B PlatformDaemonClient.invoke)
   ┌─────────────────────────────────────────────────────────────┐
   │ LarkDocsPlugin daemon (单进程 / 单 lark.Client / 单 token cache) │
   │                                                               │
   │  ┌──────────────────────┐    ┌─────────────────────────────┐ │
   │  │ DocFacade            │    │ IdentityFacade              │ │
   │  │ - create_document    │    │ - resolve_user              │ │
   │  │ - replace_content    │    │ - list_users                │ │
   │  │ - add_comment        │    │ - watch (NotImplementedError│ │
   │  │ - apply_delta (NotImpl) │  │     — is_source_of_truth=F)│ │
   │  └──────────┬───────────┘    └─────────────┬───────────────┘ │
   │             │  共享                        │                  │
   │             ▼                              ▼                  │
   │   ┌──────────────────────────────────────────────────────┐   │
   │   │ LarkAsyncClient (daemon 进程级单例)                    │   │
   │   │  - lark.Client (Builder 模式 / token cache 内置)      │   │
   │   │  - asyncio.to_thread wrapper                          │   │
   │   │  - markdown_to_lark_blocks                            │   │
   │   │  - identity_resolver (manifest 静态 map v1)           │   │
   │   └──────────────────────────────────────────────────────┘   │
   └─────────────────────────────────────────────────────────────┘
              │ httpx (Phase 5.B AllowlistTransport 校验)
              ▼
   open.feishu.cn:443 + passport.feishu.cn:443 + lf-cdn-tos.bytescm.com:443
```

### 4.2 multi-capability facet 共享 client（最关键设计）

参考 Phase 5.A Plan 04 PlatformPlugin facet 模式（`plugins/huly/platform.yaml` 已声明 4 capability）：

```python
# plugins/lark_docs/lark_docs_plugin.py 概念示意（非完整代码）
class LarkDocsPlugin:
    """Phase 5.C 首个 multi-capability plugin —— doc + identity 共享单 client。"""

    def __init__(self, manifest, credentials):
        # daemon 启动期一次性 build lark.Client（懒初始化 via @property）
        self._client = LarkAsyncClient(
            app_id=credentials.app_id,
            app_secret=credentials.app_secret,
            identity_map=manifest.config.identity_map,  # v1 静态
        )

    @property
    def doc(self) -> DocCapability:
        return _LarkDocFacade(self._client)

    @property
    def identity(self) -> IdentityCapability:
        return _LarkIdentityFacade(self._client)  # 同一个 _client 引用
```

**反模式（不要做）**：
- ❌ DocFacade / IdentityFacade 各自 `lark.Client.builder().build()` → 两套 token cache + 两份 connection pool → 浪费 + 限流风险翻倍
- ❌ 在模块顶层（不在 `_ensure_client` 内）`asyncio.Lock()` → daemon 可能尚未 event loop，会 RuntimeError

### 4.3 Lark Docs 二段写入（关键 API 流程）

```
markdown
   │
   ▼ POST /open-apis/docx/v1/documents/blocks/convert
     (lark_oapi.api.docx.v1.ConvertRequest)
   │
   ▼  返回 blocks[] (List[Block]) + first_level_block_ids[]
   │
   ▼ 按 800 block 切片（Pitfall 3 防 1000 上限），逐批：
     POST /open-apis/docx/v1/documents/{doc_id}/blocks/{root_block_id}/children
     (lark_oapi.api.docx.v1.CreateDocumentBlockChildrenRequest, descendants=[])
```

create_document 完整 4 步：
1. `docx.v1.document.create(title)` → 返回 `document_id`（root block_id == document_id）
2. `docx.v1.document.convert(content_type="markdown", content=md)` → 返回 `blocks[]`
3. **长度 + 数量预校验**：
   - 字符长度 > 10 MiB → `raise ValueError("markdown 超过飞书 10MB 上限")`
   - blocks 数 > 800 → 分批，每批 ≤ 800
4. `document_block.create(children=batch, descendants=batch)` × N 批

replace_document_content 类似，先删除 root block 全部子节点（`batch_update.delete`），再走 step 2-4 重写入。

### 4.4 评论 + @ 人通过 identity_resolver

```
add_comment(body_markdown, mentions=[UserRef(plugin_name='lark_docs', native_id='ou_xxx')])
   │
   ▼ identity_resolver: native_id 已是 ou_xxx → 直接用（v1 调用方已查过）
       若 caller 传 canonical_username 而非 native_id：identity_map[username] 静态查 ou_xxx
   │
   ▼ body 内插入 <at user_id="ou_xxx"></at> Lark 富文本锚点（Open Platform 评论 markdown 语法）
   │
   ▼ drive.v1.comment.create(file_token=document_id, content=body_with_at)
   │
   ▼ 返回 comment_id → CommentRef
```

### 4.5 IdentityResolver v1 静态 map 设计

- v1 仅从 `manifest.config_schema.identity_map` 静态读取 `{ username: lark_open_id }`
- `is_source_of_truth = False`（Lark 不是身份源头，watch_user_changes 抛 NotImplementedError）
- v1 不调用 `contact.v3.batch_get_id` 动态查询 → 避免 Phase 5.C 引入身份同步副作用
- 5.D 接 HRCapability 反向 sync 才动态：daemon 启动期一次性拉取 + 后续 watch_user_changes 增量 → 替换静态 map

---

## 5. 可借鉴的设计模式

> 7+ 借鉴点，标注每点的 source（哪个 reading doc / 哪个文件）+ 落地到 plan 05c-04 的具体哪个文件

1. **Phase 4.06 FeishuProvider 同步 SDK + asyncio.to_thread 包装模式**
   - Source: `backend/app/agent_builder/notification/providers/feishu.py:104-118`（`@property client` 延迟构造）+ `docs/reading-im-sdk-04-06-feishu-2026-05-17.md` §8
   - 借鉴：lark-oapi 1.6.5 全部为同步 API → daemon async 上下文必须 `asyncio.to_thread(sync_fn, *args)` 包装；client 通过 `@property` 延迟构造避免 module import 时建立连接
   - 落地：`plugins/lark_docs/_internal/lark_async_client.py` — 沿用 Builder 模式 + 延迟 client + `_async_call(sync_fn, *args)` helper

2. **importlib.metadata.version 取 SDK 版本（绕过 `lark.__version__` 不存在陷阱）**
   - Source: `reading-im-sdk-04-06-feishu-2026-05-17.md` §3 + `backend/app/agent_builder/notification/providers/feishu.py:50-58`
   - 借鉴：`importlib.metadata.version("lark-oapi")` + 启动期 warning（不抛错）
   - 落地：`plugins/lark_docs/_internal/lark_async_client.py` 在 LarkAsyncClient `__init__` 校验 `_resolve_lark_version() == "1.6.5"` → 不匹配 `log.warning`

3. **Builder 模式 + Response.success() 校验（lark-oapi 全局约定）**
   - Source: `reading-im-sdk-04-06-feishu-2026-05-17.md` §4.2 + 飞书 Open Platform SDK 文档
   - 借鉴：所有 lark-oapi 调用必须 `req = XxxRequest.builder().request_body(YyyRequestBody.builder()...build()).build()` → `resp = client.xxx.v1.yyy.zzz(req)` → `if not resp.success(): raise RuntimeError(f"{resp.code} {resp.msg} log_id={resp.get_log_id()}")`
   - 落地：`plugins/lark_docs/_internal/lark_async_client.py` 内 `create_document` / `convert` / `batch_create_blocks` / `create_comment` 全部包装统一 `_call_and_check(req, fn)` helper

4. **Phase 5.A Plan 04 PlatformPlugin facet 模式（multi-capability 共享 daemon）**
   - Source: `backend/app/agent_builder/platforms/plugin.py` + `plugins/huly/platform.yaml`（4 capability bundle）
   - 借鉴：`LarkDocsPlugin.doc` + `.identity` 两个 `@property` 返回 facade，**facade 持有同一个 `LarkAsyncClient` 引用**，token cache + connection pool 全 daemon 共享
   - 落地：`plugins/lark_docs/lark_docs_plugin.py` — `LarkDocsPlugin` 类（DocCapability + IdentityCapability 双 facet facade）

5. **Phase 5.B Plan 05b-03 AllowlistTransport（manifest.sandbox.network 显式 host:port 白名单）**
   - Source: `backend/app/agent_builder/platforms/sandbox/runner.py`（PLUG-FW-11 已 done）+ `05c-RESEARCH.md` Pitfall 7
   - 借鉴：manifest 显式列 `open.feishu.cn:443` + `passport.feishu.cn:443` + `lf-cdn-tos.bytescm.com:443`（飞书 CDN，图片素材用，v1 不接图但留位）→ 启动期 AllowlistTransport 校验；**不放 wildcard**（Pitfall 7 Phase 5.B 锁定 exact match）
   - 落地：`plugins/lark_docs/platform.yaml` `sandbox.network` 段

6. **Phase 5.C RESEARCH §Pattern 3 二段写入 + Pitfall 3 分批策略**
   - Source: `05c-RESEARCH.md` §Pattern 3（Lark Docs 二段写入 markdown→blocks/convert→batch_create_blocks）+ Pitfall 3（10MB/1000 block 限制）
   - 借鉴：convert API 字符 10 MiB / batch 1000 block 是飞书 server 强校验上限；客户端先 pre-check `len(md.encode('utf-8')) <= 10*1024*1024` → batch ≤ 800（留 200 余量防边界 off-by-one）
   - 落地：`plugins/lark_docs/_internal/lark_async_client.py` 在 `replace_document_content` 内：先校验字符长度 → marko parse → 800 block 切片循环 `await batch_create_blocks(...)`

7. **Phase 5.C RESEARCH §Pattern 5 marko AST → 节点映射表（防 Pitfall 6 节点名错位）**
   - Source: `05c-RESEARCH.md` §Pattern 5 marko AST renderer + Pitfall 6 节点名错位（marko 节点名是 `strong_emphasis` 不是 `strong`）
   - 借鉴：12 元素严格映射 `_BLOCK_MAP` + `_MARK_MAP`，每个映射 unit test 单独覆盖（heading 1-6 / paragraph / bulletList / orderedList / blockquote / code_block / link / em / strong / code / image / hr）
   - 落地：`plugins/lark_docs/_internal/markdown_to_lark_block.py` — `_BLOCK_MAP` / `_MARK_MAP` 双字典 + `markdown_to_lark_blocks(md)` 入口；测试 `tests/platforms/test_lark_docs_plugin.py` 对每个映射写一条 unit test

8. **IdentityResolver v1 静态 map 设计（5.D HR 反向 sync 留扩展点）**
   - Source: `05c-CONTEXT.md` Decision 1 LarkDocsPlugin + `05c-RESEARCH.md` §Pattern 6 PersonUuid 解析（Huly 实战经验：LRU + TTL，Lark v1 不需 LRU 因为静态 map 本身就是字典）
   - 借鉴：v1 仅 `manifest.config.identity_map: dict[str, str]` 静态读 + `resolve_user(username) → UserPrincipal(native_id=identity_map[username])`；`is_source_of_truth=False` → `watch_user_changes` 抛 `NotImplementedError`；5.D 才接 HRCapability 反向 sync 动态化
   - 落地：`plugins/lark_docs/_internal/identity_resolver.py` — `IdentityResolver(static_map=...)` 单类 + `resolve(username) → ou_xxx | None` + `list_principals() → list[UserPrincipal]`

9. **Phase 4.06 ConnectionError 重试边界 + 其他错误直接 fail**
   - Source: `backend/app/agent_builder/notification/providers/feishu.py:11-14` "ConnectionError 触发 im_jobs.tenacity 重试；其他错误直接 fail"
   - 借鉴：daemon 内部不做 tenacity（避免 daemon 阻塞）→ 主进程 PlatformDaemonClient.invoke 一层统一重试 ConnectionError；daemon 抛业务错误（resp.code != 0）一律直接 fail，让上游决策
   - 落地：`plugins/lark_docs/_internal/lark_async_client.py` 内不引入 tenacity；ConnectionError 透传，业务错误 raise RuntimeError + log_id

10. **License attribution 防御（不拷源码 + 文件头注释）**
    - Source: `CLAUDE.md` §2.7 + `05c-RESEARCH.md` Pitfall 8
    - 借鉴：不拷贝 Dify 源码（Dify 也没 lark provider，无可拷）；lark-oapi MIT 兼容 Apache-2.0 → 直接作为 dependency import（不拷 SDK 源码）；marko BSD-3-Clause 兼容 Apache-2.0 → 直接 import；本 plan 全部为独立创作
    - 落地：每个新文件头部加 `# LarkDocsPlugin - 自主实现，未拷贝任何上游源码` 注释（CLAUDE.md §2.7）

---

## 6. 与本项目的关系

本 plan（05c-04）实现 **LarkDocsPlugin（DocCapability + IdentityCapability 双 facet）**，是 Phase 5.C 5 个 success criteria 中的 **#2（5C-SC-2 "LarkDocsProvider plugin + markdown→blocks 转换 + 评论 + @人"）**。

**在 Phase 5.C 三 plugin 中的定位**:

| Plugin | Capability 数 | 难度 | 设计要点 |
|---|---|---|---|
| 02 OutlinePlugin | 1 (Doc only) | P0 最简 | markdown 透传，httpx 直调 — 验证 plugin 框架最简路径 |
| **04 LarkDocsPlugin (本 plan)** | **2 (Doc + Identity)** | **P0 中等** | **markdown→Lark Block 二段写入 + 共享单 client + IdentityResolver v1 静态 map** |
| 03 HulyPlugin | 4 (Doc + IM + Identity + Tracker stub) | P0 一体化 acid test | hr 1454 行 Python port + collab service 二步流程 + per-user Channel + LRU cache |

本 plan 是 **multi-cap 中等难度的参考样板**：
- 验证 PlatformPlugin facet 模式在 plugin 沙箱环境的可移植性
- 验证 Phase 4.06 FeishuProvider 已锁 lark-oapi 1.6.5 + asyncio 包装能否在 plugin daemon 复用（结论：完全可以，pin 同版本即可）
- 不引入 Huly 的 collab service / docker network attach 等复杂度，专注 multi-cap facet + Lark Docs API 二段写入

**对后续 phase 的接口承诺**:
- v1.1 留 `ai_suggest_mentions` LLM 钩子（prompt 模板 `plugins/lark_docs/prompts/ai_suggest_mentions_zh.md` v1 仅占位）
- 5.D 接 HRCapability 反向 sync 时 `IdentityResolver` 从 static map 动态化（构造函数加 `dynamic_source: Callable | None`，v1 默认 None）
- v2 升级 Lark CRDT delta 时 `supports_collaborative_edit` 从 False 改 True（飞书 Block 改造为 collaborative 后）

**License attribution**（CLAUDE.md §2.7 强制）:
- **Dify** AGPL-3.0 → 仅借鉴 plugin manifest YAML 设计思路（已在 5a-01/04 reading doc 涵盖，本 plan 不直接接触 Dify 源码）
- **lark-oapi** MIT → 兼容 Apache-2.0，直接作 dependency import（不拷源码 + 不 vendor）
- **marko** BSD-3-Clause → 兼容 Apache-2.0，直接作 dependency import
- **本项目** agent-builder Apache-2.0（与 flock 一致）
- **本 plan 输出代码全部为独立创作**，每个新文件加 `# LarkDocsPlugin - 自主实现` 头注释

---

> **Reading doc gate**：本文档已 commit 后才允许写代码（CLAUDE.md §2.7 Task 0 硬性 gate）
> **后续 commit 顺序**：Task 1 manifest skeleton → Task 2 lark_async_client → Task 3 markdown_to_lark_block + identity_resolver → Task 4 plugin facade → Task 5/6 unit + integration tests
