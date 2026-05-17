# Dify 阅读笔记 — Plugin 网络白名单（AllowlistTransport 对照）

> 日期: 2026-05-18
> 仓库: https://github.com/langgenius/dify (本地 clone `/Users/admin/ai/ref/dify/repo/`, commit `c0bdd679`)
> Stars: ~141k
> 模块映射: CLAUDE.md §2.7 — `api/services/plugin/plugin_service.py`、`api/core/plugin/manager.py`、`api/core/plugin/impl/base.py`、`api/core/plugin/entities/plugin.py`、`web/app/components/plugins/plugin-detail-panel/`

## 项目概述（一句话）

Dify 是开源 LLMOps 平台，自 2024 中开始把 Plugin 子系统从 in-process import 抽到独立的 Go 进程（`dify-plugin-daemon`）— Python 主仓库通过 HTTP/JSONRPC 走 daemon 做 plugin 注册与调用，**网络隔离与资源限制全部下沉到 Go daemon 层（cgroups + namespace 真隔离）**。Python 主仓库本身不做 plugin 级别的网络白名单。

## 技术栈对照

| 维度 | Dify | agent-builder (本项目) |
|---|---|---|
| Plugin 运行宿主 | 独立 Go daemon (`dify-plugin-daemon` 仓库) | Python subprocess 子进程 (Phase 5.A `PlatformDaemonClient`) |
| Plugin 与主进程通信 | HTTP/JSONRPC over TCP (`PLUGIN_DAEMON_URL`) | JSONRPC over stdio (line-delimited) |
| 资源限制 | Linux cgroups + namespace（daemon Go 层 syscall） | Python `resource.setrlimit` baseline（Plan 05b-02）+ Linux cgroups v2 opt-in（Plan 05b-05） |
| 网络隔离 | network namespace（daemon Go 层）+ marketplace 审核 | **application-level httpx Transport 注入**（本 Plan v1） |
| Python 主仓库的 httpx 客户端用途 | 仅用于"主仓库 → Go daemon"自己的出站 RPC | 用于"plugin daemon 子进程内"出站到第三方 API（Huly / 飞书等） |
| 网络拒绝时的反馈 | daemon 层 syscall 失败 → HTTP 错误 envelope | `NetworkBlockedError`（`backend/app/agent_builder/platforms/exceptions.py:112`，Plan 05b-02 已占位） |
| 通配符（`*.example.com`） | 不适用（namespace 是 host/IP 级） | **v1 不支持**，manifest validator 已限定 exact `host:port` |

**结论**：**Dify Python 主仓库没有 application-level 网络白名单**。它的对等位置是 Go daemon 的 namespace 隔离，不在 Python 层做。本项目 v1 选 application-level httpx Transport 注入是更轻量的 trade-off — 0 二进制依赖、cross-platform（macOS dev 友好），代价是 `import requests; requests.get(...)` 这类绕过 httpx 的代码完全脱离白名单（Pitfall 3 v1 trade-off）。

## 架构要点

### Dify Plugin 出站请求拦截点（多层）

```
┌──────────────────────────────────────────────────────────────┐
│ Python 主仓库 (api/core/plugin/impl/base.py)                  │
│  _httpx_client = httpx.Client(trust_env=False) ← 池化         │
│  仅供主仓库 → Go daemon 自己 RPC 用                            │
└────────────────────────┬─────────────────────────────────────┘
                         │ HTTP/JSONRPC (PLUGIN_DAEMON_URL)
                         ▼
┌──────────────────────────────────────────────────────────────┐
│ Go daemon (dify-plugin-daemon 仓库 — 不在 Python 树内)         │
│  ├─ namespace（network ns / pid ns / mnt ns）                  │
│  ├─ cgroups v2（cpu/memory）                                   │
│  └─ marketplace permission（前端 install-plugin/ 流程审核）     │
└────────────────────────┬─────────────────────────────────────┘
                         │ syscall 拒绝
                         ▼
                  plugin 代码（任何 HTTP 库出站均受 ns 约束）
```

### agent-builder 的简化路径（Python 单宿主）

```
┌──────────────────────────────────────────────────────────────┐
│ 主进程 (PlatformDaemonClient)                                  │
│   spawn → plugin subprocess (stdio JSONRPC)                   │
│   env: PLUGIN_NETWORK_ALLOW=host1:443,host2:443               │
└────────────────────────┬─────────────────────────────────────┘
                         │ stdio JSONRPC
                         ▼
┌──────────────────────────────────────────────────────────────┐
│ plugin daemon entrypoint (plugins/huly/huly_plugin.py)        │
│   _parse_network_allow() → list[str]                          │
│   ┌────────────────────────────┐                              │
│   │ if allow_list:             │                              │
│   │   client = make_sandboxed_ │ ← 本 Plan helper             │
│   │     http_client(allow)     │   注入 AllowlistTransport     │
│   │   await client.post(...)   │                              │
│   │ else:                      │                              │
│   │   await aiohttp_legacy()   │ ← 5.A fallback (env-gated)    │
│   └────────────────────────────┘                              │
└────────────────────────┬─────────────────────────────────────┘
                         │ httpx.AsyncBaseTransport.handle_async_request
                         ▼
┌──────────────────────────────────────────────────────────────┐
│ AllowlistTransport.handle_async_request                       │
│   urlparse(request.url) → (host, port)                        │
│   if (host, port) not in allow_set:                           │
│     log.warning("network.blocked ...")                        │
│     raise NetworkBlockedError(host, port)                     │
│   else:                                                       │
│     return await delegate.handle_async_request(request)       │
└──────────────────────────────────────────────────────────────┘
```

**关键拦截点**：httpx Transport 的 `handle_async_request` 是发请求前的最后一道公开扩展点 — 检查通过才会进入真正的 TCP 连接 / TLS handshake，是阻断 DNS 解析与数据外泄的最佳点。

## 可借鉴的设计模式

### 1. 池化 / 显式注入 httpx 客户端（参考 `api/core/plugin/impl/base.py:56-59`）

Dify:
```python
_httpx_client: httpx.Client = get_pooled_http_client(
    "plugin_daemon",
    lambda: httpx.Client(
        limits=httpx.Limits(max_keepalive_connections=50, max_connections=100),
        trust_env=False,
    ),
)
```

**借鉴点**：把 httpx.Client 当作**显式注入的依赖**而不是模块级 import 时立刻创建 — `make_sandboxed_http_client(allow_list)` 也是 factory pattern，调用方决定何时构造、传入什么白名单。

**显式偏离**：Dify 用 `httpx.Client`（同步）+ pool；我们用 `httpx.AsyncClient`（异步） — plugin daemon 内部跑 asyncio event loop。

### 2. `trust_env=False` 切断环境变量旁路（参考同上）

Dify 用 `trust_env=False` 让 httpx 不读 `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` 环境变量。

**借鉴点**：本 Plan 内部 `httpx.AsyncHTTPTransport()` delegate 默认行为已隔离；plugin daemon 不应通过 proxy 绕过白名单。Plan 04 `_build_filtered_env` strip-all 后即使 PROXY env 也不会传到 daemon，双重防护。

### 3. Pydantic v2 嵌套 Permission BaseModel（参考 `api/core/plugin/entities/plugin.py:29-58`）

Dify 在 `PluginResourceRequirements.Permission` 下嵌套 Tool/Model/Node/Endpoint/Storage 子类做权限声明（虽然不包括 network）。

**显式偏离**：本项目 manifest 用扁平 `sandbox.network: list[str]`（Plan 05b-01 已落） — 因为 v1 只需 host:port 白名单，没必要嵌套类。Phase 6 marketplace 上才考虑 `Permission` 嵌套（如 `read_only` / `write_allowed` 区分）。

### 4. httpx Transport API 子类化（参考 httpx BSD-3 官方文档 https://www.python-httpx.org/advanced/transports/）

httpx 公开的 `AsyncBaseTransport.handle_async_request(request) -> Response` 是合法的子类化扩展点。Dify 没用这个 API（它的隔离在 Go daemon 层），但 httpx 文档建议子类化做：
- 自定义重试策略
- 日志记录与监控
- **网络白名单（与本项目对应）**

**关键设计点（reading 时验证）**：
- `aclose()` 必须 async（不是 `close`）— `httpx.AsyncBaseTransport.aclose` 与 `httpx.AsyncClient` 的 lifecycle 接口对齐
- 子类不需要实现 `__aenter__` / `__aexit__` — httpx.AsyncClient 自己管理 transport lifecycle
- `httpx.MockTransport(callable)` 是测试时 inject 假 response 的标准方法，**不应**真正发请求

### 5. 默认 deny + 显式 allowlist（restrictive baseline）

Dify Permission 子模型默认 `enabled=False` — 不显式 enable 就拒绝。

**借鉴点**：`AllowlistTransport([])` = 拒所有出站。即 manifest 不写 `sandbox.network: [...]` → 默认空白名单 → 任何 host 都被拒。这是 v1 安全核心（Pitfall 8 conservative default）。

### 6. 结构化日志（参考 Dify `logger.exception("Request to Plugin Daemon Service failed")` `api/core/plugin/impl/base.py:93`）

Dify 在 httpx.RequestError 时用 `logger.exception` 记录上下文。

**借鉴点**：本项目 `AllowlistTransport.handle_async_request` 拒绝时记 `_log.warning("network.blocked host=%s port=%s scheme=%s ...")` —— 监控系统可以基于 `network.blocked` event 串告警 / dashboard。

## 与本项目的关系

### v1 trade-off：application-level 而非 OS-level

- **接受的代价**：plugin 代码用 `urllib.request.urlopen()` / `requests.get()` / 裸 socket 完全绕过 httpx → 不进 AllowlistTransport → 不受白名单约束
- **缓解措施**：
  - **plugin developer guide**（待 Phase 6 marketplace 上线）强制要求 plugin 用 `make_sandboxed_http_client(allow_list)`
  - **代码审查**（marketplace 上 plugin 前）grep `^import requests|^import urllib|^import socket` 给警告
  - **structured log**：`network.blocked` event 监控异常出站；如果 plugin 真用 requests 绕过，DNS / Connect timeout 监控也能告警

### Pitfall 3 v1 trade-off 接受范围

Pitfall 3（README §Pitfalls）说明 application-level 白名单的天然弱点：
- **不能阻挡** `import requests; requests.get(target)` —— plugin 用别的 HTTP 库就绕过
- **不能阻挡** 进程内 raw socket（`socket.socket().connect((host, port))`）
- **不能阻挡** subprocess 调 curl / wget

**v1 接受 + v2 修复路径**：
- Phase 6 marketplace 引入 OS-level 真隔离 — Linux network namespace（unshare(CLONE_NEWNET)）+ veth pair + DNS resolver 拦截
- Phase 6 同时强制 plugin 通过 `make_sandboxed_http_client` API（marketplace 上架审核 + 静态分析）

### 与 Plan 05b-01 / 05b-02 的契约链

```
05b-01 SandboxConfig.network: list[str]    ← manifest schema 已定义
    ↓ 主进程读 manifest 解出 list
05b-02 PluginError.NetworkBlockedError(host, port, allowlist) ← 异常类已占位
    ↓ 主进程注入 env PLUGIN_NETWORK_ALLOW="host1:443,host2:443"
05b-03 (本 Plan) AllowlistTransport + make_sandboxed_http_client
    ↓ plugin daemon 显式 import 调 helper
05b-04 PlatformDaemonClient._build_filtered_env strip-all + env_allowlist 转 PLUGIN_NETWORK_ALLOW
```

本 Plan 完成 `AllowlistTransport` 与 plugin 集成的 v1 闭环；Plan 04 把 env 注入也从主进程接力起来。

### huly_plugin env-gated 集成（兼容 5.A acid test）

- **5.A acid test 不设 `PLUGIN_NETWORK_ALLOW` env** → 走 fallback aiohttp 路径（5.A 原实现） → 0 regression
- **Plan 05b-03 集成测设 env** → 走新 httpx + AllowlistTransport 路径
- 用 `if allow_list:` 分支保留旧路径，**不删 5.A aiohttp 代码** — 重要降级回退路径

### HIGH-2 fix：lazy import 防 daemon spawn ModuleNotFoundError

`plugins/huly/huly_plugin.py` 是 plugin subprocess 入口；它 import `from app.agent_builder.platforms.sandbox.network import ...` 时必须在**函数体内 try/except**（lazy import），否则若 PYTHONPATH 未含 `backend/`，5.A acid test 子进程 spawn 时立刻 ModuleNotFoundError 死掉。

**实现策略**：把 `from app.agent_builder.platforms.sandbox.network import make_sandboxed_http_client` 放到 `im_send_card` 函数内、`if allow_list:` 分支里 → 仅在 env 触发新路径时才 import → 5.A acid test 不触发该 import → 0 regression。

## License attribution

- **Dify** — AGPL-3.0；本笔记仅记录公开设计概念（`PluginResourceRequirements` 字段结构、httpx 池化 pattern、`Permission` 嵌套思路）。**严禁拷贝 Dify 源码**到本仓。
- **httpx** — BSD-3-Clause；公开 API `AsyncBaseTransport` / `MockTransport` / `AsyncHTTPTransport` 可自由引用。
- 本项目 `agent-builder` — Apache-2.0（与 flock fork 一致）；`AllowlistTransport` 与 `make_sandboxed_http_client` 100% 独立创作。
