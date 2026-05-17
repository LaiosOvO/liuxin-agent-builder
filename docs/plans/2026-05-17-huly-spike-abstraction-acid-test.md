# Huly Acid Test — Provider 抽象有效性评估

> 日期: 2026-05-17
> 目的：用 Huly (all-in-one HR + chat + docs 平台) 作为压力测试，暴露当前 agent-builder Provider 抽象的设计 gap
> 阅读输入：Huly platform clone @ `/Users/admin/ai/ref/agent/huly` (commit 未 tag，分支 main) + 我们的 3 份设计稿 + Phase 4 IMProvider 已落地实现
> **结论先行**：IMProvider **60% fit**（核心 fit，但有 4 处协议层 gap），DocProvider **30% fit**（CRDT 模型与全量 `update_document(markdown)` 根本性冲突），HRProvider **当前 0% — 需新增**。**抽象可演进，但需要 3 处协议级补丁 + 引入 PlatformBundle facet 模式**。Huly 不是 "再加一个 provider" 那么简单，它是一个**反向源点**（source-of-truth）平台，逼迫我们承认现有抽象隐含的 "外部系统是被动 sync 目标" 假设站不住脚。

---

## 1. Huly 技术栈 + 核心模型简介

Huly 是一个**单仓多服务**的协作 OS，**30+ 微服务**用 **CockroachDB + Redpanda(Kafka) + MinIO + Elasticsearch + Redis** 撑起一个把 Slack/Notion/Linear/BambooHR 合一的产品。

**核心 transport 是 Tx-protocol over WebSocket**（端口 3332 transactor 服务），辅以 REST（`account:3000` 登录 / `datalake:4030` 文件 / `collaborator:3078` Y.js CRDT 同步）。**没有 REST POST/PUT 的传统 CRUD API** — 所有写都是 `tx(createDoc / updateDoc / removeDoc / addCollection / createMixin)`，由 transactor 收下广播到所有连接的 client + 写 CockroachDB + 发 Kafka 事件。

**数据模型核心**：所有数据都是 `Doc`（带 `_id: Ref<this>`、`_class: Ref<Class<this>>`、`space: Ref<Space>`、`modifiedOn`、`modifiedBy`）。`Doc` 上可以**附 Mixin**（横切关注 — 比如 `Staff extends Employee` 把 HR 的 `department` 字段附加到 contact 的 `Employee` 上）和 **AttachedDoc**（一对多 collection，如 `Request` attach to `Staff.requests`）。客户端用 `findAll(_class, query, options)` 查所有东西，用 `createDoc(_class, space, attrs)` 写所有东西 — **一组 API 通杀 chunter + document + hr**。

---

## 2. IMProvider × Huly chunter

### 2.1 Fit map（6 个 Protocol 方法 → Huly chunter 操作）

| 我们的方法 | Huly 对应 | 怎么映射 | Fit 度 |
|---|---|---|---|
| `name: str` (= `"huly"`) | 平台名常量 | 加 `PROVIDER_HULY = "huly"` 到 `KNOWN_PROVIDERS` | OK |
| `send_hitl_card(recipient, ...)` | `client.createDoc(chunter.class.ChatMessage, space=channelRef, {message: <markup>, attachments: ...})` | `recipient` 必须是 `Ref<Channel \| DirectMessage>`（不是 user_id！见 §2.2 gap 1）；卡片 4 按钮无原生支持 → 退化为 markdown link 列表 | **50% — 部分** |
| `update_card(message_id, new_content)` | `client.updateDoc(chunter.class.ChatMessage, space, msgRef, {message: <new markup>, editedOn: now})` | 直接编辑消息内容（Huly 支持 editedOn 字段）；但**改不了 attachments collection 的子节点**，需 removeCollection + addCollection | **70% — 较 fit** | 
| `send_supplement_text(recipient, text)` | `client.createDoc(chunter.class.ChatMessage, channelRef, {message: <plain markup>})` | 简单的"再发一条消息"模式，几乎完全 fit | **OK** |
| `subscribe(on_event)` [Phase 4.5] | `client.findAll(...)` + **subscribe to Tx stream**（WebSocket transactor 推 Tx event） | Huly 没有 webhook 概念 — 它的"入站"是**长连 WS 接收 Tx broadcast**。需要保持 WS 连接 + 过滤 `core.class.TxCreateDoc` where `objectClass = chunter.class.ChatMessage` | **30% — transport 模型完全不同** |
| `verify_webhook_signature(headers, body)` [Phase 4.5] | **不适用** | Huly 是有状态 WS 长连接 + JWT bearer token，不存在 per-request 签名 | **N/A — 永不实现** |

### 2.2 Gaps

**Gap 1 — recipient 字段类型语义不匹配**。我们的 `recipient: str` 在飞书是 `open_id`、Slack 是 `U...`、Mattermost 是 `channel_id`。Huly 的 recipient 是 `Ref<Channel> | Ref<DirectMessage>`（一个 32 字符 hex），而且**直接给 user 发 DM 必须先调 `getDirectChannel(client, me, employeeAccount) -> Ref<DirectMessage>`**（即"DM channel 是先创建的，不是直接给 user_id 发"）。这逼出一个 gap：**recipient 抽象需要从 `str` 升级为 `RecipientSpec`**（带 type discriminator: `"channel"` / `"dm_user"` / `"thread"`），或者 IMProvider 加 `resolve_dm_channel(user_id) -> recipient_id` helper method。

**Gap 2 — HITL 卡片 4 按钮在 Huly 是 attachment 而不是原生 block**。Huly 的 `ChatMessage` 只有 `message: Markup`（HTML/markdown 文本）+ `attachments: number`（计数器，子文档走 AttachedDoc 模式）。**没有飞书 Interactive Card / Slack Block Kit / DingTalk ActionCard 类型的原生按钮 schema**。最 fit 的折衷是：把 4 个 deeplink 渲染成 markdown bullet list（`- [批准](https://...)` ...）作为 message 主体。这意味着：**`supports_card_update` 应该新增第三态**："update_card 可以改 message 文本，但按钮永远是 markdown link — 没法变 disabled 灰按钮"。

**Gap 3 — transport 是 stateful WebSocket，不是 stateless HTTP**。我们的 `MattermostProvider` 在每次 `send_hitl_card` 调用都 `async with httpx.AsyncClient(timeout=...)` — 短连接、无状态。Huly 必须**先 `connect(url, {token, workspace}) -> PlatformClient` 建立 WS 长连接**，然后所有操作通过这个 client。这逼出 lifecycle 管理：`HulyIMProvider.__init__` 不能简单存 `bot_token`，必须**懒/启动时连 WS 并保留 PlatformClient handle**，并加 `async def close()` 关闭连接。**当前 IMProvider Protocol 没有 lifecycle hook**（无 `connect()` / `close()`），需补充。

**Gap 4 — workspace 维度内嵌于 client 而不是参数**。我们的 `IMRegistry.get(workspace_id, name)` 返回的 provider 实例对所有调用是同一个。Huly 的 `connect(..., workspace=...)` 是**按 Huly workspace 选目标空间**（Huly 的 workspace 不是我们的 multi-tenant workspace，是它内部的命名空间）— 两个语义不同的 "workspace" 重叠会造成混乱。需要在 `HulyIMCredentials` dataclass 上区分 `our_workspace_id` (UUID) 和 `huly_workspace_url_name` (str)，或者注入 helper 时显式 map。

### 2.3 Verdict

**小改可演进**。`send_hitl_card` / `update_card` / `send_supplement_text` 3 个核心出站方法都能在 Huly chunter 上找到对应 createDoc/updateDoc 操作，**功能上 fit 60-70%**。但 4 处协议层 gap（recipient 类型、按钮退化、WS lifecycle、workspace 命名空间冲突）必须先在 base.py 上补，否则 HulyIMProvider 写出来要么不优雅（强行 string-encode 复杂语义到 `recipient`），要么破坏 Protocol（绕过 `name/methods` 加 ad-hoc 方法）。**推荐：见 §8 行动 1-2**。

---

## 3. DocProvider × Huly document

### 3.1 Fit map（6 个设计稿方法 → Huly document 操作）

| 我们设计稿方法 | Huly 对应 | 怎么映射 | Fit 度 |
|---|---|---|---|
| `create_document(title, markdown, owner_usernames, folder_id)` | `client.createDoc(document.class.Document, teamspaceRef, {title, content: markupRef, parent: parentRef, rank})` + 先 `client.uploadMarkup(...)` 把 markdown 转成 `MarkupBlobRef` 存到 datalake | `folder_id` → `parent: Ref<Document>`（doc 也是树形）；`owner_usernames` 没直接字段，要走 Mixin 加 `acl` | **40% — 两步操作 + content 不是 inline** |
| `update_document(doc_id, markdown, title)` | **这是问题的核心** — 见 §3.2 gap 1 | 全量 markdown 替换在 Huly 是**反 CRDT 范式**的：`Document.content` 是 `MarkupBlobRef`（Y.js 二进制文档快照），不是 markdown 字符串。直接 `uploadMarkup(...)` 重传一个新 blob ref 会**丢失所有正在协作编辑用户的 awareness state + 制造 Y.js 冲突** | **15% — 根本性冲突** |
| `get_document(doc_id)` | `client.findOne(document.class.Document, {_id: doc_id})` + `fetchMarkup(...)` 把 blob ref 转回 markdown | 两步 + format 转换；OK | OK |
| `list_documents(query, limit)` | `client.findAll(document.class.Document, {title: {$regex: query}}, {limit})` | 直接 fit；Huly 支持 mongo 风格 query | OK |
| `add_comment_mention(doc_id, username, text)` | `client.addCollection(chunter.class.ChatMessage, space, attachedTo=doc_id, attachedToClass=document.class.Document, collection='comments', {message: '<text with @uuid>'})` | Comment 走 chunter ChatMessage attached 到 Document（chunter/document 跨插件复用！）；mention 用 markup 内嵌 `@<AccountUuid>` 语法 | **70% — 较 fit** |
| `ensure_users(users)` | **不属于 doc 抽象** — Huly user 由 `account-service` 管 | 应该走 HR 抽象 / contact 插件，不应放在 DocProvider 里。其实现有设计稿这个方法本来就有点跑偏 | gap not-Huly-specific |

### 3.2 Gaps

**Gap 1 — `update_document(markdown)` 全量替换 vs Y.js CRDT 协作编辑根本性冲突**。Huly Document 的 `content: MarkupBlobRef` 不是字符串，而是**指向 datalake 中一个 Y.Doc binary snapshot 的 ref**。当用户打开文档时，Huly client 通过 `collaborator:3078` WebSocket 加载 Y.Doc 并开始实时同步编辑增量。如果我们在 bot 侧调 `uploadMarkup(...)` 生成新 blob → `updateDoc(content=newRef)`：

- **正在编辑的用户看不到我们的更新**（他们的 client 持有旧 Y.Doc 副本，不会自动 reload）
- **下次他们 commit edit 时会把 Y.Doc snapshot 重新写回 → 覆盖 / 冲突我们的更新**
- 即使没人编辑，rewrite blob ref 也**丢失 Y.js 编辑历史**（snapshots / version vector）

正确的做法是：bot 也要**作为 Y.Doc 的 collaborator**，通过 collaborator service 应用 Y.js 增量更新（`Y.Doc.applyUpdate(diff)`），而不是覆盖式上传。这意味着 **`update_document(markdown)` 在 Huly 上语义错误，应改成 `apply_document_delta(doc_id, delta_ops)`**，或者引入两个分离的接口：

```python
async def replace_document_content(doc_id, markdown)  # 适用 Outline/Lark — 全量替换语义
async def apply_document_delta(doc_id, delta)         # 适用 Huly — CRDT 增量语义
```

并加 capability flag：`supports_full_replace: bool` / `supports_delta_apply: bool`。

**Gap 2 — content 是 blob ref 而非 inline 字符串**。我们的 `DocInfo.content` 不存在（设计稿里只有 id/url/title），但调用方拿到 `DocInfo` 后通常会 `get_document(id)` 再读 markdown。Huly 这一步**必须经过 `fetchMarkup` 把 blob ref 转换回 markdown（额外一跳 RPC + format 转换）**。这没有破坏 Protocol，但增加 latency 1x → 2x — 应该在性能 NFR 中体现（doc-provider §3.2 N-DOC-01 写的 ≤3s 在 Huly 上可能要 ≤5s）。

**Gap 3 — `owner_usernames` 没有自然映射**。Outline 有 `members`，Lark 有 `collaborators`，但 Huly Document 没有 owner/member 字段 — **权限走 Space 层级**（Document 在 Teamspace 里，Teamspace 有 members）。`create_document(owner_usernames=[...])` 在 Huly 上要么：
- (a) 把 owners 加到 Teamspace.members（**副作用：他们能看到该 Teamspace 所有文档**，安全洞）
- (b) 创建一个新 Teamspace 专给这个 doc（**副作用：用户文档列表里多出一堆 1-doc Teamspace**）
- (c) 忽略 `owner_usernames` 参数（不优雅）

正确解法：**owner 模型需要从 protocol 移到 Provider impl 层各家自定**，或者 `DocProvider.supports_per_doc_owners: bool` capability flag + 不支持时 raise + 调用方有 fallback 策略。

**Gap 4 — folder_id 是 parent Document，不是文件夹概念**。设计稿写 `folder_id`，但 Huly Document 是**树形**（`parent: Ref<Document>`），没有独立的 folder class。一个 Document 既是文档又是 folder。这其实 Outline 也类似（Collection 概念），但 Lark/钉钉是显式文件夹 — 用一个 `folder_id: str | None` 字段调和过得去，但需要在 Huly 实现里文档说明 "folder_id 是 parent doc id"。

### 3.3 Verdict

**大改**。`update_document(markdown)` 在 CRDT 模型下语义错误，**必须拆成 `replace_content` 和 `apply_delta` 两个方法 + capability flag**，否则 HulyDocProvider 要么造成数据丢失要么默默退化为只读。`owner_usernames` 在 Huly 上也站不住，需要降级为 optional capability。**整个 DocProvider Protocol 需要重新审视**：当前是按 "Outline/Notion 这类静态 markdown 管理" 思路设计的，遇到 "Y.js 协作编辑器" 模型就崩。**推荐：见 §8 行动 3-4**。

---

## 4. HRProvider (NEW)

### 4.1 为什么需要新 Protocol

**现有抽象覆盖不到 HR 域。** Phase 4 IMProvider 是出站消息、Phase 5 DocProvider 是文档读写，**两者都不涉及"员工是谁/部门结构/请假申请/汇报关系"**。但 agent-builder 的关键定位场景（HR 离职流、入职流、请假审批）必须解析 `assignee: dept:研发部` / `manager_of(employee_id)` / `request_status` 这些表达式 — **目前我们只能从 LDAP/外部 HRIS sync 数据进我们自己的 employees 表**，相当于把 HRIS 当成被动数据源。Huly HR 是**主动语义层**（有 Department/Staff/Request/PublicHoliday class），如果我们想把 Huly 作为 HR source-of-truth 而不是双写，必须有一个 `HRProvider` Protocol 来**抽象 HR 操作 + 解决"who is the source of truth"**问题（见 §6）。

### 4.2 拟定的 HRProvider Protocol 草案

```python
@dataclass(frozen=True)
class Employee:
    id: str                       # provider 内 employee id
    username: str                 # canonical username (我们内部)
    email: str
    display_name: str
    department_id: str | None
    manager_id: str | None        # 上级 employee id
    is_active: bool
    custom_fields: dict[str, str]  # provider-specific 扩展

@dataclass(frozen=True)
class Department:
    id: str
    name: str
    parent_id: str | None         # 部门树
    team_lead_employee_id: str | None
    member_ids: list[str]

@dataclass(frozen=True)
class LeaveRequest:
    id: str
    employee_id: str
    request_type: str             # "vacation" | "sick" | "pto" | "remote" | "overtime"
    start_date: str               # ISO date
    end_date: str
    description: str
    status: str                   # "pending" | "approved" | "rejected"

@runtime_checkable
class HRProvider(Protocol):
    name: str                     # "huly_hr" | "bamboohr" | "workday" | ...
    is_source_of_truth: bool      # True → 我们 sync_from；False → 我们 sync_to

    # ── 读操作（最少 4 个） ───────────────────────────────────────────────
    async def list_employees(
        self,
        *,
        department_id: str | None = None,
        active_only: bool = True,
        cursor: str | None = None,
    ) -> tuple[list[Employee], str | None]: ...   # 返回 (employees, next_cursor)

    async def get_employee(self, *, employee_id: str) -> Employee | None: ...

    async def list_departments(self) -> list[Department]: ...

    async def get_employee_by_username(self, *, username: str) -> Employee | None: ...

    async def resolve_department_members(
        self,
        *,
        department_expr: str,         # "dept:研发部" / "dept:engineering/backend"
    ) -> list[Employee]: ...          # Phase 5 必备 — 解析 assignee 表达式

    # ── 写操作（按 source_of_truth 决定是否实现） ──────────────────────────
    async def create_leave_request(
        self,
        *,
        employee_id: str,
        request_type: str,
        start_date: str,
        end_date: str,
        description: str,
    ) -> LeaveRequest:
        """source_of_truth=True 的 provider 才实现；否则 NotImplementedError"""
        ...

    async def list_leave_requests(
        self,
        *,
        employee_id: str | None = None,
        status: str | None = None,
        cursor: str | None = None,
    ) -> tuple[list[LeaveRequest], str | None]: ...

    # ── 事件订阅（用于 sync_from 模式实时跟随 Huly 变更） ──────────────────
    async def subscribe_changes(
        self,
        *,
        on_employee_change: Callable[[Employee, str], Awaitable[None]],  # (employee, "created"|"updated"|"deleted")
        on_department_change: Callable[[Department, str], Awaitable[None]],
    ) -> None:
        """长连订阅 — Huly 实现：listen 到 transactor TxCreateDoc/TxUpdateDoc on Employee/Department class"""
        ...
```

### 4.3 Fit map vs Huly hr plugin

| HRProvider 方法 | Huly 对应 | Fit 度 |
|---|---|---|
| `list_employees(department_id, active_only)` | `client.findAll(hr.mixin.Staff, {department: deptRef})` — Staff 是 Employee 加 HR mixin | OK |
| `get_employee(id)` | `client.findOne(contact.class.Employee, {_id: id})` | OK |
| `list_departments()` | `client.findAll(hr.class.Department, {})` | OK |
| `get_employee_by_username(username)` | 需要先 lookup `contact.class.Channel`（社交账号映射）拿 `Person` → 拿 Employee mixin — **2-3 跳查询** | 50% — 实现复杂 |
| `resolve_department_members("dept:研发部")` | 先 `findOne(Department, {name: "研发部"})` → 拿 `members: Ref<Employee>[]` → 递归子部门 `parent=deptId` | OK — Huly 部门是显式树 |
| `create_leave_request(...)` | `client.createDoc(hr.class.Request, space, {attachedTo: staffRef, type: requestTypeRef, tzDate, tzDueDate, description})` | OK — Huly Request 完整支持 |
| `list_leave_requests(employee_id, status)` | `client.findAll(hr.class.Request, {attachedTo: staffRef})` — 注意 Huly Request **没有 status 字段**！状态由所属 Space / 关联 task 推断 | 60% — status 语义不直接 |
| `subscribe_changes(on_employee_change, ...)` | WS 订阅 transactor Tx stream，过滤 `objectClass IN (Employee, Staff, Department)` | OK — Huly 天然推送 |

**注意**：Huly 的 `Request` 模型**比一般 HR 系统简陋**（无 approver/approval workflow 字段），它把审批流交给 Huly 自家的 process 服务做。如果我们 source_of_truth=Huly，要在 Huly 里建审批 process；如果我们 source_of_truth=agent-builder，则只把 leave request 当成"通知 Huly 知道"。

---

## 5. 一体化平台问题：PlatformBundle facet 模式

### 5.1 现有抽象的局限

我们的 `IMRegistry / DocProviderRegistry` 是**按 abstraction 分桶**：所有 IM provider 在一个 dict，所有 Doc provider 在另一个 dict。`get_provider("feishu")` 隐含假设 "飞书是 IM 平台"，`get_provider("outline")` 隐含 "outline 是 Doc 平台"。Huly 一个实例同时是 IM + Doc + HR + Project，**当用户在 workspace_settings 里写 `default_doc_provider: huly` 和 `default_im_provider: huly` 时，会发生**：

- 两个独立的 `HulyIMProvider` 和 `HulyDocProvider` 实例
- 每个都建一个 `connect(url, {token, workspace})` WebSocket — **2x WS 连接 + 2x token 解析 + 2x credentials lookup**
- 没办法在 IM provider 和 Doc provider 之间共享 `PlatformClient.findAll` cache / hierarchy 

更糟的是：HR 抽象引入后 → 3x WS 连接到同一个 huly 实例。

### 5.2 拟定 PlatformBundle 模式

新增一层 `PlatformBundle` 抽象，**1 个 platform 实例 = 1 个 client connection + N 个 facet**：

```python
@runtime_checkable
class PlatformBundle(Protocol):
    """all-in-one 平台 bundle — 1 connection × multiple facets"""
    name: str                     # "huly" | (未来) "notion-with-comments" 等
    
    @property
    def im(self) -> IMProvider | None: ...   # None 表示该 facet 不支持
    @property
    def doc(self) -> DocProvider | None: ...
    @property
    def hr(self) -> HRProvider | None: ...
    
    async def health_check(self) -> bool: ...
    async def close(self) -> None: ...        # 关闭底层 client（共享 WS 连接）


class HulyPlatform:
    """Huly bundle — 1 PlatformClient × 3 facets"""
    name = "huly"
    
    def __init__(self, *, url, token, huly_workspace, our_workspace_id):
        self._client: PlatformClient | None = None   # lazy connect
        self._url = url
        self._token = token
        self._huly_ws = huly_workspace
        self._our_ws_id = our_workspace_id
        # facets 持 weak ref 到 self._client
        self._im: HulyIMProvider | None = None
        self._doc: HulyDocProvider | None = None
        self._hr: HulyHRProvider | None = None
    
    async def _ensure_client(self) -> PlatformClient:
        if self._client is None:
            self._client = await connect(self._url, {token: self._token, workspace: self._huly_ws})
        return self._client
    
    @property
    def im(self) -> IMProvider:
        if self._im is None: self._im = HulyIMProvider(bundle=self)
        return self._im
    # ... 同理 doc / hr
    
    async def close(self):
        if self._client: await self._client.close()
```

**单业务平台（Mattermost / Outline / 飞书）依然走老路** — 直接注册 IMProvider 实现，不需要包成 PlatformBundle。**bundle 是 opt-in**，只有 all-in-one 平台才用。

### 5.3 Registry 改造

引入**两层 registry**：

```
PlatformRegistry  ── 注册 PlatformBundle 实例（按 workspace_id × platform_name）
       │
       ├── 写入时：bundle.im → IMRegistry 自动注册 facet 引用
       ├──        bundle.doc → DocProviderRegistry 自动注册 facet 引用
       └──        bundle.hr → HRRegistry（新）自动注册 facet 引用
```

调用方写 `IMRegistry.get(ws_id, "huly").send_hitl_card(...)` 仍能工作 — 因为 IMRegistry 里存的是 facet 引用，**底下复用 bundle 的 WS 连接**。`PlatformBundle` 对调用方透明，仅在 bootstrap / shutdown 时显式 use。

**为什么不直接 deprecate IMRegistry 等？** 向后兼容 + Mattermost / Slack 这种单业务 provider 不需要 bundle 抽象（KISS）。

---

## 6. 身份模型：Huly as source of truth

### 6.1 当前 user_platform_mappings 假设

设计稿 `doc-provider-abstraction §5` 的表结构（节选）：

```
canonical_username TEXT NOT NULL,    -- agent-builder 内部 username (主键的一部分)
user_id UUID,                        -- 关联到 agent-builder users 表（可空）
outline_email TEXT,                  -- Outline 平台 user 标识
lark_open_id TEXT,
wecom_userid TEXT,
sync_source TEXT,                    -- "outline-sync" | "lark-sync" | "manual"
```

**隐含假设**：`canonical_username` 是**我们这边的主语义**，外部平台 ID 是"映射目标"。`sync_source` 是个标签字段，但**没有任何机制让外部平台变更反向更新 canonical_username**。这是 **sync-to** 模式 — 我们写 user，把 user 推送 / 验证到外部平台。

### 6.2 Huly 反向 — sync-from

Huly 的 HR 模块就是公司 HR system：employees 来自 Huly contact 表，department 来自 Huly hr.Department，离职 / 入职都是在 Huly 里操作的。**Huly 才是 canonical user 的源点**，agent-builder 的 `users` 表应该**reflect** Huly 的状态，而不是反过来。

**数据模型补丁建议**：

1. **`workspace_settings` 加 `identity_source: enum`**：值 `"local"` (默认) / `"huly"` / `"lark_contact"` / `"slack_scim"`。当 = `"huly"` 时，agent-builder users 表的 `username / email / department / manager_id` 字段变为**只读 cache**，由 `HulyHRProvider.subscribe_changes(...)` 实时同步。
2. **`user_platform_mappings` 加 `is_authoritative: bool`**：标识哪个 platform_id 是**主标识**。Huly 模式下 `huly_account_uuid` 是 authoritative。
3. **新增 `identity_sync_jobs` 表**：跑 incremental sync（initial full sync + delta sync via WS subscribe）。失败重试 / lag metrics 走 Phase 7 Observability。
4. **`canonical_username` 在 Huly 模式下的语义重定义**：它不再是"我们自己起的名字"，而是 Huly `Account.primarySocialId.value`（或 fallback 到 Employee.name slug）。冲突时 (e.g. Huly 改 username) 走 rename-cascade 流程。

**关键 implication**：HRProvider 应该被设计成**支持 `is_source_of_truth=True` 的 provider 优先**（Huly / BambooHR / Workday 这类），并且 PlatformBundle 层应保证 **只有 HR facet 是 source_of_truth 时，IM/Doc facet 才能用 mapping 的 user_id 不做 fallback 查询**（否则要 fallback 到 email 等）。

---

## 7. 评估总结

### 7.1 Protocol 字段 fit 度统计

| 抽象 | 现有字段数 | Huly 可直接映射 | 需新增协议字段 | 完全不适用 / 需替代设计 |
|---|---|---|---|---|
| **IMProvider** (Phase 4 已实现) | 6 (name + 3 出站 + 2 入站) | 3 (send_hitl_card 部分 / update_card / send_supplement_text) | 2 (RecipientSpec / lifecycle close) | 1 (verify_webhook_signature — Huly 用 WS bearer) |
| **DocProvider** (设计稿) | 6 (name + 5 ops) | 2 (get_document / list_documents) | 3 (apply_delta / capability flags / owner 模型) | 1 (update_document 全量替换语义) |
| **HRProvider** (本文档新提) | 0 | — | 8+ (列上表) | — |
| **PlatformBundle** (本文档新提) | 0 | — | 5 (name / im / doc / hr / close) | — |

### 7.2 整体结论

**当前抽象可演进，不需要推倒重设。** Phase 4 IMProvider 的 Protocol-over-ABC + Registry + Mock 这套核心架构方法论是对的（Huly 也能套），**问题在于 Protocol 字段的具体 schema 是按 "stateless HTTP 短连 + 静态消息卡片" 设计的**。Huly 暴露了 3 个我们之前没考虑的维度：

1. **Transport lifecycle** — 长连接平台需要显式 connect/close
2. **Recipient polymorphism** — channel id 不是简单 string，可能需要 spec object
3. **Content mutability model** — 全量替换 vs 增量 delta 是两类语义

而 **DocProvider 还在设计稿阶段，是引入这些改进的最佳时机** — 一旦 Outline/Lark Docs 真接入后再改会破坏向后兼容。

**HR 域是真正的新疆域** — 必须新增 HRProvider Protocol，且必须先回答 "Huly 是 source-of-truth 还是 sync target"。这影响 user_platform_mappings 表结构和 identity 模块整个设计。

**PlatformBundle facet 模式不复杂，建议作为 5.A 一起引入**（30 行代码，2 个新 file），否则未来再加 Notion/ClickUp（也是 all-in-one）会重复 Huly 的痛点。

---

## 8. 下一步（5 个 prioritized actions）

### 8.1 P0 — IMProvider Protocol 补丁（1 周内可做，不破坏现有 6 个 provider）

加 3 个 optional 字段到 `IMProvider` Protocol：

```python
class IMProvider(Protocol):
    name: str
    supports_card_update: bool
    supports_native_buttons: bool = True   # 新 — Huly 是 False（按钮退化为 markdown link）
    requires_persistent_connection: bool = False  # 新 — Huly 是 True
    
    async def connect(self) -> None:        # 新 — 默认 no-op；Huly impl 建 WS
        ...
    async def close(self) -> None:           # 新 — 默认 no-op；Huly impl 关 WS
        ...
```

**现有 6 个 provider 都加默认实现**（`connect/close` 默认 pass，`supports_native_buttons = True`），**0 行业务代码改动**。Registry 在 shutdown 时遍历 `provider.close()`。这 3 个字段让 HulyIMProvider stub 可在 ~200 行写出。

### 8.2 P0 — recipient 字段升级为 RecipientSpec

引入 frozen dataclass：

```python
@dataclass(frozen=True)
class RecipientSpec:
    kind: Literal["channel", "dm_user", "thread"]
    id: str                  # channel id / user id / thread root msg id
    extras: dict[str, str] = field(default_factory=dict)
```

`send_hitl_card(recipient: RecipientSpec, ...)`。**向后兼容**：旧调用方传 `str` → 转 wrapper 自动 `RecipientSpec(kind="channel", id=...)`。Huly impl 看到 `kind="dm_user"` 时自动调 `getDirectChannel(...)` 解析。

### 8.3 P0 — DocProvider Protocol 拆 update 语义

**在 Outline / Lark Docs 真接入之前**（doc-provider-abstraction §9 Phase 5.B）改 Protocol：

```python
class DocProvider(Protocol):
    supports_full_replace: bool        # True for Outline/Lark/WeCom; False for Huly
    supports_delta_apply: bool         # True for Huly; False for others
    
    async def replace_document_content(self, *, doc_id, markdown, title=None) -> None:
        """全量替换 — supports_full_replace=True 才实现"""
        ...
    async def apply_document_delta(self, *, doc_id, delta_ops) -> None:
        """CRDT 增量 — supports_delta_apply=True 才实现"""
        ...
```

**调用方**：DocWriteNodeExecutor 优先 `apply_delta`，fallback `replace`。`doc_write` 节点配置加 `update_strategy: "replace" | "delta" | "auto"`。

### 8.4 P1 — 引入 HRProvider + PlatformBundle 框架（Phase 5.A 一起做）

新建 `backend/app/agent_builder/notification/hr/base.py` + `platform_bundle.py`，规模约 250 行：

- `HRProvider` Protocol（§4.2 草案）
- `HRRegistry`（仿 IMRegistry）
- `PlatformBundle` Protocol（§5.2 草案）
- `PlatformRegistry`（按 (workspace_id, platform_name) key）
- Mock 实现 + 单测 ≥ 15

**写一个 `HulyPlatform` skeleton**（不真接入，stub 返回固定数据）作为 PlatformBundle 第一个 case，证明 facet 模式自洽。

### 8.5 P1 — 决策 identity source-of-truth 设计

启动 spike：写一份 ADR 决定 `workspace_settings.identity_source` 4 模式 (`local` / `huly` / `lark_contact` / `slack_scim`) 的：

- user_platform_mappings 表 schema 变更（加 `is_authoritative` / 新 `identity_sync_jobs` 表）
- 冲突解决策略（external rename → cascade vs reject vs prompt）
- 失败 fallback（Huly 挂了 → fall back to last-known mapping vs reject all auth）

**这一步必须在 Phase 5.A 之前完成**，否则 user_platform_mappings 表建好后再改 schema 风险大。

---

## 9. 附录：HulyIMProvider stub 草图（伪代码）

```python
# backend/app/agent_builder/notification/providers/huly.py
"""HulyIMProvider — 验证 Protocol 字段能 fit Huly chunter API。

不真实现 — 只展示映射思路。真接入需 pip install @hcengineering/api-client (or 
通过 huly-py SDK，目前未官方 publish — 可能需要包装 TS client via subprocess
or 自己拿 WebSocket + Tx-protocol 二开)。
"""
from dataclasses import dataclass
from typing import Any, Literal

from app.agent_builder.notification.providers.base import (
    PROVIDER_HULY,  # 需先加到 KNOWN_PROVIDERS
    RecipientSpec,   # §8.2 新引入
)


@dataclass(frozen=True)
class HulyCredentials:
    url: str                      # http://huly.local:8087
    token: str                    # JWT — 通过 account-service 登录拿到
    huly_workspace: str           # Huly 内部 workspace url name
    our_workspace_id: str         # UUID — 用于 multi-tenant 隔离


class HulyIMProvider:
    """Stub — 1 个 PlatformClient 持 WS 长连，多次 send 复用同一连接。"""

    name: str = PROVIDER_HULY
    supports_card_update: bool = True
    supports_native_buttons: bool = False  # Huly 无原生按钮，退化为 markdown link
    requires_persistent_connection: bool = True  # WS 长连

    def __init__(self, creds: HulyCredentials) -> None:
        self._creds = creds
        self._client: "PlatformClient | None" = None  # huly_py.PlatformClient

    # ── lifecycle ────────────────────────────────────────────────────────
    
    async def connect(self) -> None:
        """启动时 / 第一次 send 前调 — 建 WS 长连。"""
        from huly_py import connect  # 假设的 Python SDK
        self._client = await connect(
            self._creds.url,
            token=self._creds.token,
            workspace=self._creds.huly_workspace,
        )

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None

    # ── 出站 ─────────────────────────────────────────────────────────────

    async def send_hitl_card(
        self,
        *,
        recipient: RecipientSpec,
        flow_title: str,
        node_title: str,
        applicant_name: str,
        actor_name: str,
        deadline_at: str,
        description: str,
        deeplinks: list[dict[str, str]],
    ) -> dict[str, Any]:
        if self._client is None:
            await self.connect()
        
        # Step 1: 解析 recipient → Huly ChannelRef
        channel_ref = await self._resolve_channel(recipient)
        
        # Step 2: 把 4 按钮降级为 markdown link list（gap 2）
        message_markup = self._render_hitl_markdown(
            flow_title, node_title, applicant_name, actor_name,
            deadline_at, description, deeplinks,
        )
        
        # Step 3: 映射到 createDoc(chunter.class.ChatMessage, channelRef, {...})
        from huly_py import chunter, core
        msg_id = await self._client.create_doc(
            _class=chunter.class_.ChatMessage,
            space=channel_ref,
            attributes={
                "message": message_markup,
                "attachments": 0,
                "attachedTo": channel_ref,
                "attachedToClass": chunter.class_.Channel,
                "collection": "messages",
            },
        )
        return {
            "message_id": msg_id,
            "raw_response": {"channel_ref": channel_ref, "markup_len": len(message_markup)},
        }

    async def update_card(self, *, message_id: str, new_content: dict[str, Any]) -> None:
        if self._client is None:
            await self.connect()
        from huly_py import chunter
        # 直接编辑 ChatMessage.message + editedOn — Huly 支持
        await self._client.update_doc(
            _class=chunter.class_.ChatMessage,
            space=new_content["space_ref"],  # 需要调用方提供 (或者 lookup 一次)
            objectId=message_id,
            operations={
                "message": new_content["message"],
                "editedOn": int(time.time() * 1000),  # Huly Timestamp = ms
            },
        )

    async def send_supplement_text(self, *, recipient: RecipientSpec, text: str) -> None:
        # 复用 send_hitl_card 路径但 message_markup 是纯文本
        await self.send_hitl_card(
            recipient=recipient,
            flow_title="", node_title="", applicant_name="", actor_name="",
            deadline_at="", description=text, deeplinks=[],
        )

    # ── 辅助 ─────────────────────────────────────────────────────────────

    async def _resolve_channel(self, recipient: RecipientSpec) -> str:
        """RecipientSpec → Huly Ref<Channel|DirectMessage>"""
        if recipient.kind == "channel":
            return recipient.id  # 直接是 channel ref
        elif recipient.kind == "dm_user":
            # 调 utils.getDirectChannel — 我方 account_uuid 来自 self._client.get_account()
            me = (await self._client.get_account()).uuid
            return await self._client.get_or_create_dm(me, recipient.id)
        elif recipient.kind == "thread":
            # ThreadMessage attached to a parent ChatMessage
            return recipient.id  # 实际需要走 ThreadMessage 创建分支
        raise ValueError(f"未知 recipient.kind: {recipient.kind}")

    @staticmethod
    def _render_hitl_markdown(*, ...) -> str:
        # 简化：md 模板渲染（实际共用 cards/mattermost_card.py 那一套）
        return f"""## {flow_title} — {node_title}

**申请人**：{applicant_name}  
**截止**：{deadline_at}

{description}

请选择：
{chr(10).join(f'- [{d["action"]}]({d["url"]})' for d in deeplinks)}
"""

    # ── Phase 4.5 入站（Huly 模式：WS subscribe 而非 webhook） ──────────

    async def subscribe(self, on_event: Any) -> None:
        """Huly 入站：保持 WS 连接监听 Tx broadcast。"""
        if self._client is None:
            await self.connect()
        # 伪代码：filter Tx where objectClass = chunter.class.ChatMessage
        async for tx in self._client.subscribe_tx():
            if tx.objectClass == "chunter.class.ChatMessage" and tx.txType == "TxCreateDoc":
                await on_event(self._tx_to_event(tx))

    async def verify_webhook_signature(self, headers, body) -> bool:
        # Huly 无 webhook — 此方法不适用。Bot dispatcher 应该在 platform 维度看
        # `supports_webhook` capability 跳过此 provider 的 webhook route。
        raise NotImplementedError(
            f"{self.name} 是 WebSocket-based，没有 webhook 概念 — 不应调此方法"
        )
```

**关键 takeaway from stub**：

- 200 行 + 1 个外部依赖（hypothetical `huly_py` SDK，或我们自己包 WS client）就能写出
- 必须先有 §8.1 / §8.2 的 Protocol 补丁，否则会写很多 `# HACK` / 强转
- `update_card` 需要 `new_content["space_ref"]` 这个 Huly-specific 字段 — 暴露了**通用 Protocol vs provider-specific 字段**的张力，可能需要 `new_content: dict[str, Any]` 之外再加 `provider_metadata: dict[str, str]` 字段（或者每个 provider 自己在 `send_hitl_card` 时把 metadata 编码进 `message_id` 字符串）

---

*报告完*
