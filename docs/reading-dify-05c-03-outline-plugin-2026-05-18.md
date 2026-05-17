# Dify 阅读笔记 — OutlinePlugin httpx + 429 retry

> 日期: 2026-05-18
> 仓库: https://github.com/langgenius/dify (local clone `/Users/admin/ai/ref/dify/repo/`, commit `e7e6fe88`, AGPL-3.0)
> Outline OpenAPI 一手参考: https://github.com/outline/openapi/blob/main/spec3.yml (~Outline 32k stars, BUSL-1.1)
> Plan 锚点: `.planning/phases/05c-doc-capability/05c-03-PLAN.md` Task 0（Wave 2，OutlinePlugin daemon）
> Stars: Dify ~141k / Outline ~32k

## 项目概述（一句话）

Dify 的 **HTTP 出口模块** (`api/core/helper/ssrf_proxy.py` + `http_client_pooling.py`) 与 **Tool credential schema** (`api/core/tools/entities/tool_entities.py` + `api/core/entities/provider_entities.py`) 是 OutlinePlugin daemon（httpx + tenacity + manifest config_schema）最高同构的两个参考点 — 一边是 retry/超时/池化的工程化经验，一边是凭据声明式 schema 的成熟模型；本 plan 完整借鉴其设计模式，但在 Apache-2.0 / async-first / JSONRPC 路径下独立重写。

## 技术栈对照

| 维度 | Dify HTTP 出口 / Tool 模块 | OutlinePlugin（本 plan） |
|---|---|---|
| HTTP client | `httpx.Client`（同步，池化） | `httpx.AsyncClient`（异步，每请求新建） |
| 客户端池化 | `HttpClientPoolFactory` + key 维度（verified/unverified） | v1 不池化（daemon 单进程 + 单 plugin = 单 base_url 已够），v1.5 按需引入 |
| Retry 触发码 | `STATUS_FORCELIST = [429, 500, 502, 503, 504]` | `retry_if_exception_type(httpx.HTTPStatusError) & status in (429, 502, 503, 504)`（500 在 Outline 表语义错乱不重试） |
| Retry 退避 | `time.sleep(BACKOFF_FACTOR * (2 ** (retries - 1)))`，BACKOFF=0.5 | `tenacity AsyncRetrying + wait_exponential(min=1, max=4)` |
| Retry 最大次数 | `SSRF_DEFAULT_MAX_RETRIES`（config 可调，默认 3） | 锁定 2 次（Pitfall 12 daemon timeout 叠加约束） |
| Timeout 分层 | `httpx.Timeout(timeout / connect / read / write)` 4 维 | 简化为单 `httpx.Timeout(10.0)` total（daemon 内部不暴露给用户配） |
| 凭据 schema | `ProviderConfig + BasicProviderConfig.Type.SECRET_INPUT` Pydantic 模型 | `platform.yaml: config_schema.properties.api_token.format=password` JSON Schema |
| 凭据加密落地 | `core/helper/encrypter.py` AES-GCM | Phase 2 已实现 `WorkspaceSecretCipher`（KMS envelope），plan 02 接 |
| 网络出口防护 | SSRF Squid 代理 + proxy_mounts | Phase 5.B `AllowlistTransport` host:port 精确匹配（Pitfall 7） |
| Error envelope | `ToolSSRFError / MaxRetriesExceededError` 类型化 | daemon dispatcher 统一翻译 → JSONRPC `-32000`（业务） / `-32603`（internal） |
| 分布式 trace | OTEL `HTTPXClientInstrumentor` + 手工 traceparent fallback | v1 仅 structured log（Phase 7 Run Viewer 钩子，见 §Pattern 7） |

## 架构要点

```
[Dify HTTP 出口链路]
  ToolNode.execute()
    → ssrf_proxy.make_request(method, url, max_retries)
      → _get_ssrf_client(verify=bool)               # 池化（thread-safe singleton）
        → get_pooled_http_client(key, builder)      # HttpClientPoolFactory.get_or_create
      → client.request() 同步阻塞
      → 检查 STATUS_FORCELIST → time.sleep(backoff) → retry
      → 检查 Squid 标头 (Server: squid / Via: squid) → 抛 ToolSSRFError
    → 返回 httpx.Response

[OutlinePlugin daemon 链路]
  主进程 PlatformDaemonClient.invoke("doc", "create_document", {...})
    → JSONRPC over stdio (envelope)
    → daemon main() 协程 dispatch METHODS["doc.create_document"]
      → OutlineClient(api_token).documents_create(title, text, collection_id, ...)
        → tenacity AsyncRetrying(stop=2, wait_exp(1, 4), retry_on=429|502|503|504)
          → httpx.AsyncClient(transport=AllowlistTransport(httpx.AsyncHTTPTransport()))
            → POST {base_url}/api/documents.create (markdown 透传 text 字段)
            → r.raise_for_status() → r.json()["data"]
      → 返回 DocRef(plugin_name="outline", native_id=data["id"], extras=...)
    → JSONRPC success envelope → 主进程

[Retry 时序对比]
  Dify (max_retries=3, backoff=0.5):
    req → 429 → sleep 0.5s → req → 429 → sleep 1s → req → 429 → sleep 2s → req → fail
    总耗时上限 ≈ 4 req + 3.5s sleep ≈ 23.5s（含每次 HTTP 5s）

  OutlinePlugin (stop_after_attempt=2, wait_exp(1, 4)):
    req → 429 → sleep 1s → req → 429 → sleep 2s → req → fail
    总耗时上限 ≈ 3 req + 3s sleep ≈ 9-10s < daemon invoke_timeout 30s 的 1/3（Pitfall 12 防超）

[Mock outline server 测试拓扑]
  pytest fixture spawn aiohttp test server @ 127.0.0.1:18088
    → 注册 /api/documents.create / .update / .info / .delete / comments.create 5 路由
    → in-memory _DOCS_STORE / _COMMENTS_STORE dict (test 间 fixture reset)
    → /api/documents.create 可注入 429 series (Pitfall 4 复现) 验证 retry 真触发
  OutlinePlugin daemon subprocess spawn (真 subprocess elapsed > 0.2s)
    → manifest network.allowed_hosts: ["127.0.0.1:18088"]
    → 真 httpx → 真 AllowlistTransport → 真打 mock server roundtrip
    → 验证 DocRef.native_id ∈ _DOCS_STORE（端到端写入路径）
```

## 可借鉴的设计模式（5 条必含 + 1 条 Outline 一手参考）

1. **HTTP retry on 5xx / 429 + exponential backoff**（Dify `api/core/helper/ssrf_proxy.py:133-209`：`make_request` 的 `STATUS_FORCELIST` 检查 + `time.sleep(BACKOFF_FACTOR * (2 ** (retries - 1)))` + `MaxRetriesExceededError`）
   - Dify 设计：sync `while retries <= max_retries` 循环 + 触发码白名单 + 指数退避因子可配 + 上限错误显式抛
   - OutlinePlugin 借鉴：异步 `tenacity AsyncRetrying(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=4), retry=retry_if_exception(_is_outline_retryable))`；剔除 500（Outline 500 是 schema 错乱，重试无意义）；保留 429/502/503/504；指数因子 1→2→4
   - 落点：`plugins/outline/_internal/client.py: OutlineClient.documents_create / documents_update / comments_create` 用一个 `_with_retry()` decorator 统一包

2. **Timeout 分层（connect / read / write / total）**（Dify `api/core/helper/ssrf_proxy.py:138-144`：`httpx.Timeout(timeout=..., connect=..., read=..., write=...)` 四维 + 各自 config 项 `SSRF_DEFAULT_CONNECT_TIME_OUT / READ_TIME_OUT / WRITE_TIME_OUT`）
   - Dify 设计：四维度独立，便于诊断"卡 connect"vs"卡 read"; 通过 dify_config 暴露给运维
   - OutlinePlugin 借鉴：简化为单 `httpx.Timeout(10.0)` total；理由：plugin daemon 内部不向用户暴露 HTTP 调优 UI（plugin manifest 只放业务字段），daemon 调用上限 30s 已留足；若 v1.5 需诊断再拆维度
   - 落点：`OutlineClient.__init__(timeout=10.0)` 单参数；Outline OpenAPI 通常 < 3s 响应，10s 已有 3x 余量

3. **Tool credentials schema — type + form_type + required + label/help/placeholder**（Dify `api/core/entities/provider_entities.py:168-219`：`BasicProviderConfig.Type = {SECRET_INPUT, TEXT_INPUT, SELECT, BOOLEAN}` + `ProviderConfig.{required, default, options, label, help, url, placeholder}`；Dify `api/core/tools/entities/tool_entities.py:435` 用 `credentials_schema: list[ProviderConfig]` 挂在 `ToolProviderEntity` 上）
   - Dify 设计：声明式 schema → 渲染 Tool 安装表单 + 后端按 type 加密 + form_type 控制 UI 显示（SECRET_INPUT = mask 黑色圆点输入框）
   - OutlinePlugin 借鉴：用 JSON Schema 等价描述 — `platform.yaml: config_schema.properties.api_token = {type: string, format: password, label.zh: "API Token", help.zh: "Outline 设置→API tokens 生成"}`，`format: password` 等价于 Dify `SECRET_INPUT`；前端按 `format == "password"` 渲染密码输入框
   - 落点：`plugins/outline/platform.yaml: config_schema` + `backend/app/agent_builder/platforms/registry.py` validate hook（早期 fail-fast 缺字段或 token 长度异常）

4. **HTTP body content-type 区分 (json / form / raw / binary)**（Dify HTTP 节点通过 `HttpRequestNodeBody.type` 字段在 entities 里建模 — 见 `api/configs/remote_settings_sources/nacos/http_request.py` 与 tests `api/tests/fixtures/workflow/http_request_with_json_tool_workflow.yml`）
   - Dify 设计：每节点声明 body type → executor 切不同序列化路径（json.dumps / urlencode / raw bytes / multipart）
   - OutlinePlugin 借鉴：Outline 6 个 endpoint 全是 `application/json`；OutlineClient 简化为只有 `json=...` 路径，**不开放** form / multipart；future-proof：若某天 Outline 加 attachments 上传，新增 `documents_attach()` 独立 method 走 multipart，不污染主路径
   - 落点：`OutlineClient.documents_create(..., json=payload)`；payload 中文要 `json.dumps(..., ensure_ascii=False)`（Pitfall — mock server 收不到正确 UTF-8）

5. **Error envelope 翻译（HTTP exception → 类型化业务错误）**（Dify `api/core/helper/ssrf_proxy.py:46-49` 的 `MaxRetriesExceededError` + `core/tools/errors.py:ToolSSRFError` + 在 `make_request` 内部检查 Squid header 主动抛错；调用方层级用 `request_error = httpx.RequestError` 暴露统一类型）
   - Dify 设计：httpx 原生异常 → 包成类型化业务错误（带语义：MaxRetries / SSRF / RequestError），调用方 catch 业务异常而非 httpx 异常 — 解耦上层与 httpx 版本
   - OutlinePlugin 借鉴：daemon dispatcher (Pattern 1 引用 `huly_plugin.py` 模板) 统一捕获 `httpx.HTTPStatusError → JSONRPC -32000 + structured log outcome="http_error"`；`tenacity.RetryError → -32000 + outcome="rate_limited"`；`NetworkBlockedError (Phase 5.B AllowlistTransport) → -32000 + outcome="network_blocked"`；`NotImplementedError → -32603 + outcome="not_supported"`
   - 落点：`plugins/outline/outline_plugin.py: _wrap_jsonrpc_errors()` decorator 应用在 5 个 capability method 上

6. **Outline OpenAPI 一手参考 — endpoint 语义对照**（Outline OpenAPI spec3.yml，与 Dify 无关，单独验证 OutlinePlugin 调用正确性）
   - 关键 endpoint:
     - `POST /api/documents.create`：`text` 字段直接接 markdown 透传（不需先 convert blocks，区别于 Lark）
     - `POST /api/documents.update`：`append=false` (默认) 即全量替换；`append=true` 追加；本 plan `replace_document_content` 走 false
     - `POST /api/comments.create`：`data` 字段是 **ProseMirror JSON**（不是 markdown）— 上层 add_comment 需 markdown→ProseMirror 转换（v1 简化：只支持纯文本，markdown 高级特性 v1.5）
     - `POST /api/documents.info`：**POST 不是 GET**（与一般 REST 反直觉，易踩）
     - `POST /api/documents.delete`：永久删除（无 trash 概念，谨慎）
   - 鉴权：`Authorization: Bearer {api_token}`，token 在 Outline 设置→API tokens 生成；OutlinePlugin manifest `config_schema.api_token` 直接对应
   - 限速：默认 `1000 req/min/IP`（Pitfall 4）；Outline self-host `.env: RATE_LIMITER_REQUESTS=10000` 可调；agent-builder 集成测 .44 部署已调高
   - 落点：`plugins/outline/_internal/client.py` 6 个 method 一一对应；`tests/platforms_integration/fixtures/mock_outline_server.py` mock 5 个核心路由

## 与本项目的关系

本 plan (05c-03) 实现 OutlinePlugin daemon — DocCapability 单 capability，是 Phase 5.C 三 plugin（Outline / Lark / Huly）复杂度最低、端到端最完整的样板。借鉴 Dify HTTP 出口的 retry + 池化 + error envelope 设计、Tool credential schema 的声明式建模思路，但因为：(1) 我们是 async-first（asyncio + httpx.AsyncClient）； (2) plugin daemon JSONRPC 而非 Dify 单进程；(3) Outline API 远比 Dify 通用 HTTP 节点窄（6 endpoint，全 json）； 实现层完全独立重写。后续 plan 04 (LarkDocsPlugin) / 05-07 (HulyPlugin) 复用本 plan 验证过的 daemon spawn + AllowlistTransport + tenacity retry 三层模板，叠加 multi-capability / CRDT delta / docker network attach 等增量复杂度。

集成测试拓扑（mock outline server @ `127.0.0.1:18088`）也借鉴 Dify `api/tests/unit_tests/core/workflow/nodes/http_request/` 的 mock httpbin / mock server fixture 思路，但用 aiohttp web.Application 自建本地 mock，避开网络依赖；in-memory dict store 保证测试间隔离 + fixture reset。

## License 与 attribution

- Dify AGPL-3.0 + Python sync HTTP node + Pydantic 凭据 schema
- Outline BUSL-1.1（OpenAPI spec 单独按 MIT/CC 公开 — 仅参考 endpoint 签名）
- agent-builder Apache-2.0 + Python async OutlinePlugin
- **100% 独立创作**；仅借鉴**设计模式 / retry 策略 / credential schema 思路 / endpoint 调用模式**
- **严禁拷贝**任何 Dify 源代码（含 `make_request` retry 循环实现、`MaxRetriesExceededError` 类名、`ProviderConfig` Pydantic 字段顺序等）；若实现"几乎一样"，重写一遍换语法（CLAUDE.md §2.7 硬性约束）
- 每文件头部加 attribution 注释：`# Inspired by Dify HTTP node / ProviderConfig design — re-implemented under Apache-2.0`
