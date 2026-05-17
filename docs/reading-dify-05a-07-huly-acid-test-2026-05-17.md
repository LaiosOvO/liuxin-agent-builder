# Dify 阅读笔记 — Huly Acid Test (Plan 05a-07)

> 日期: 2026-05-17
> 仓库: https://github.com/langgenius/dify (local clone /Users/admin/ai/ref/dify/repo/, AGPL-3.0)
> 配套独立仓库: https://github.com/langgenius/dify-plugin-daemon (Go 实现，AGPL-3.0；本次仅看 README)
> Stars: ~141k
> 本项目: agent-builder (Apache-2.0)
> Plan: 05a-07 — HulyPlugin acid test 真子进程 spawn + mock huly server + JSONRPC stdio roundtrip + fault isolation

---

## 项目概述（一句话）

Dify dify-plugin-daemon 是为主进程 ↔ plugin 进程通信而设的独立 Go daemon，承载 install / list / invoke 三类 RPC；agent-builder 5.A 因不需多语言（v1 仅 Python）+ 不需 K8s pod 隔离，简化为「主进程 asyncio.create_subprocess_exec 直接 spawn Python module + JSONRPC stdio」单进程模型。

## 技术栈

| 关注点 | Dify | agent-builder 5.A 选择 |
| --- | --- | --- |
| daemon 进程语言 | Go | Python（v1 锁定；node/go 留 v2） |
| 通信协议 | HTTP（独立 K8s pod） | JSONRPC 2.0 over stdio（嵌入式 subprocess） |
| Envelope schema | Pydantic `PluginDaemonBasicResponse[T]` | 自写 dict + JSONRPC 2.0 标准字段 |
| install / lifecycle | `PluginInstallTask` 异步状态机 + Event(Info/Done/Error) | v1 同步 invoke；install lifecycle 留 Phase 6 |
| 错误传播 | `PluginDaemonError` + `PluginDaemonInnerError`（code + message） | JSONRPC 2.0 error envelope（code/message/data） |
| 进程管理 | 由 Go daemon 内部维护 process pool + restart policy | v1 主进程 SIGTERM/SIGKILL；crash 不自动重启（fault isolation 立即失败） |

---

## 架构要点（核心架构模式，用简图说明）

### Dify 架构（独立 K8s pod 模式）

```
┌─────────────────────────────────┐
│ Dify api (Python FastAPI)        │
│  PluginService.invoke(plugin_id, │
│  method, params)                 │
└──────────────┬──────────────────┘
               │ HTTP（独立 pod）
               ▼
┌─────────────────────────────────┐
│ dify-plugin-daemon (Go)          │
│  - manage process pool           │
│  - PluginInstallTask 状态机      │
│  - PluginDaemonBasicResponse[T] │
└──────────────┬──────────────────┘
               │ stdio JSONRPC（pod 内 child）
               ▼
┌─────────────────────────────────┐
│ Plugin process (Python / Node)   │
│  - 各家 plugin 自家实现          │
└─────────────────────────────────┘
```

### agent-builder 5.A 架构（嵌入式 subprocess 模式，简化）

```
┌──────────────────────────────────────────┐
│ agent-builder backend (Python FastAPI)    │
│  ┌─────────────────────────────────┐    │
│  │ PlatformPluginRegistry          │    │
│  │  .discover('plugins/')          │    │
│  │  .get_capability(IMCapability)  │    │
│  └─────────────┬───────────────────┘    │
│                │                          │
│  ┌─────────────▼───────────────────┐    │
│  │ PlatformPlugin (lazy facade)    │    │
│  │  .im → IMFacade                 │    │
│  │  .doc → DocFacade               │    │
│  └─────────────┬───────────────────┘    │
│                │                          │
│  ┌─────────────▼───────────────────┐    │
│  │ PlatformDaemonClient            │    │
│  │  .invoke('im', 'send_card', …)  │    │
│  └─────────────┬───────────────────┘    │
│                │ asyncio.subprocess     │
└────────────────┼──────────────────────────┘
                 │ stdin/stdout pipe (JSONRPC 2.0 line-delimited)
                 ▼
┌──────────────────────────────────────────┐
│ Plugin daemon process (Python -u -m)      │
│  plugins.huly.huly_plugin                 │
│  - main loop: stdin readline → dispatch  │
│  - METHODS dict 路由 method_name → fn    │
│  - im.send_card → aiohttp → mock huly    │
└─────────────────┬────────────────────────┘
                  │ HTTP POST
                  ▼
┌──────────────────────────────────────────┐
│ Mock Huly server (aiohttp.web)            │
│  POST /api/v1/chunter/messages            │
│   → {message_id: "huly-msg-…"}            │
└──────────────────────────────────────────┘
```

**核心差异**：
- Dify 把 daemon 视为「平台基础设施」（独立部署、独立扩缩）
- 5.A 把 daemon 视为「主进程的子进程」（嵌入式、与主进程共生命周期）
- 简化让 5.A 在 v1 无需 K8s + 无需 HTTP overhead；代价是 daemon 跨主机 / 跨副本扩展能力延后（留 v2）

---

## 可借鉴的设计模式

### 1. Dify daemon spawn 模式 → 5.A Python subprocess + JSONRPC stdio 简化版

**Dify 源文件**：`api/services/plugin/plugin_service.py` (整个 PluginService) + dify-plugin-daemon README
**模式**：
- Dify PluginService 调用方写 `await PluginInstaller.invoke(plugin_id, method, params)`
- PluginInstaller 持有到 Go daemon 的 HTTP client
- Go daemon 内部用 process pool 管理 plugin 子进程，按需 spawn / reuse

**5.A 借鉴点**：
- 调用方接口同样简单：`await daemon.invoke("im", "send_card", **kwargs)`（Plan 05 已实现）
- 但跳过 HTTP / process pool 抽象层 — 主进程直接 `asyncio.create_subprocess_exec` 起 `python -u -m <module>` 子进程
- daemon 进程与主进程 1:1 生命周期共生 — start / close 都是主进程显式控制
- Pitfall 9 防护：测试必须真起子进程而非 mock client（否则抽象只在纸面 — 即用户 2026-05-17 三连质疑的场景）

**Plan 05a-07 应用**：
- `plugins/huly/huly_plugin.py` 是 daemon entrypoint（独立创作，不抄 Dify 源码）
- 测试时 `PlatformDaemonClient("plugins.huly.huly_plugin", env={...})` 真起子进程
- Acid test timing assert `elapsed > 200ms` 验证 subprocess 真起（mock client 不可能 > 200ms）

### 2. PluginDaemonInnerError code 设计 → 5.A acid test 验证 JSONRPC error envelope

**Dify 源文件**：`api/core/plugin/entities/plugin_daemon.py:126-141` (PluginDaemonError / PluginDaemonInnerError)
**模式**：
- 错误从 daemon 返回时含 `error_type: str` + `message: str` 双字段
- 不同 error_type 触发主进程不同处理路径（如 retry vs raise vs fallback）

**5.A 借鉴点**：
- 5.A 用 JSON-RPC 2.0 标准错误码而非自由字符串：
  - `-32601`: Method not found（daemon 不识别 method 名）
  - `-32602`: Invalid params（参数类型错）
  - `-32603`: Internal error（daemon handler 抛 unexpected exception 含 NotImplementedError）
  - `-32000~-32099`: 业务错误（plugin 自定义）
- error envelope 含 code（int）+ message（str）+ 可选 data（any）
- 主进程 `PluginInvocationError(error_payload)` 通过 `error_payload.get("code")` 分流

**Plan 05a-07 应用**：
- `huly_plugin.py` METHODS dict 不识别的 method → 返回 `-32601 Method not found`
- METHODS dict 已注册但 handler 抛 `NotImplementedError` → 返回 `-32603 Internal error`（含 "Phase 5.C / 5.D" 文本）
- acid test `test_huly_plugin_method_not_implemented_returns_error` 显式断言 code == -32603

### 3. Phase 4 mock provider 测试模式 → 5.A mock_huly_server 直接复用

**Phase 4 源文件**：`backend/app/agent_builder/notification/providers/feishu.py` + `tests/test_*_provider.py`（HTTP mock 模式）
**Phase 5.A Plan 01 conftest**：`backend/tests/platforms_integration/conftest.py` 已提供 `free_port` fixture（socket bind 0）

**模式**：
- Phase 4 测试用 `httpx_mock` 拦截到飞书 OpenAPI 的 HTTP 出站
- 但 5.A 不能拦截 daemon 子进程的 HTTP 出站（daemon 在独立进程，主进程 mock 不到）
- 改用「真起 aiohttp.web stub server 监听本地端口」让 daemon 真发 HTTP

**5.A 借鉴点**：
- `mock_huly_server.py` 用 `aiohttp.web.Application + add_post("/api/v1/chunter/messages")`
- 监听 `127.0.0.1:<free_port>`（fixture 分配）
- 接受 daemon 真 HTTP POST，返回 `{message_id: f"huly-msg-{uuid4().hex[:8]}"}`
- daemon 通过 `HULY_ENDPOINT` env var 知道 mock server URL（test fixture 注入）

**Plan 05a-07 应用**：
- `tests/platforms_integration/mock_huly_server.py` 实现 `build_mock_app()`（aiohttp）
- `tests/platforms_integration/conftest.py` 追加 `mock_huly_server` fixture（启动 + cleanup）
- `huly_plugin.py` `os.environ.get("HULY_ENDPOINT")` 读 mock server URL

### 4. Dify install task subprocess 隔离 → 5.A fault isolation 实测

**Dify 源文件**：`api/services/plugin/plugin_service.py` + `entities/plugin_daemon.py:144-165` (PluginInstallTask)
**模式**：
- Dify install / invoke 都跑在 Go daemon 进程，主进程 crash 不影响 daemon（pod 隔离）
- 反过来 daemon crash 主进程通过 HTTP timeout 检测，不会同步死锁

**5.A 借鉴点**：
- 5.A daemon 与主进程通过 stdin/stdout pipe 通信，主进程必须主动检测 daemon EOF（pipe closed → daemon exited）
- `_read_loop` 检测 `stdout.readline()` 返回空 bytes → `_fail_all_pending(PluginDaemonExitedError)`（Plan 05 已实现）
- 关键 SLO：**daemon crash 后下次 invoke 立即失败（< 2s），不许走 30s timeout**

**Plan 05a-07 应用**：
- `test_kill_daemon_then_invoke_raises_immediately`：
  1. 起 daemon + 跑 1 个成功 invoke（warmup，验证 daemon 活）
  2. `os.kill(daemon._proc.pid, signal.SIGKILL)` 强杀
  3. `await asyncio.sleep(0.2)` 让 asyncio reactor 处理 SIGCHLD + 关闭 stdout
  4. 下次 invoke → 必须 raise `PluginDaemonExitedError` **且耗时 < 2s**（timing assert）
- `test_daemon_crash_does_not_hang_main_process`：起新 daemon 继续工作（验证主进程完好）

### 5. Acid test "真起 subprocess" vs "mock client" 教训 — Pitfall 9 防护

**Pitfall 9 来源**：CONTEXT.md `<decisions>` § "HulyPlugin Acid Test 范围 + 验收硬性" + 用户 2026-05-17 三连质疑
**模式（反模式）**：
- 「偷懒在 acid test 直接 mock `PlatformDaemonClient.invoke`」 → 表面 1 capability call 通过，实际抽象仍在纸面
- 用户三连质疑场景：「Phase 5.A 看起来都过了但根本没真起 daemon」

**5.A 关键防御**：
- **timing assert**：测试运行时间必须 `> 200ms`（subprocess spawn + Python 启动 + JSONRPC roundtrip 累计成本）
- 若 < 200ms 说明被 mock 了 → 直接 fail 该测试
- 主断言之外，timing 是「测试本身的元测试」 — 验证测试没退化为 mock

**Plan 05a-07 应用**：
- `test_huly_plugin_real_subprocess_send_card_end_to_end` 最后一行：
  ```python
  assert elapsed > 0.2, (
      f"acid test 仅 {elapsed:.3f}s — 远低于 subprocess spawn 成本，"
      "说明根本没真起 daemon 进程（Pitfall 9 / 用户三连质疑场景）"
  )
  ```
- `test_kill_daemon_then_invoke_raises_immediately` 反向 timing assert `< 2.0s` 确保不走 invoke_timeout 路径

---

## 与本项目的关系（如何应用到当前 plan）

| Dify 源文件 | 借鉴模式 | 5.A Plan 05a-07 落地 module | 状态 |
| --- | --- | --- | --- |
| `plugin_service.py` + dify-plugin-daemon README | daemon spawn 模式简化 | `plugins/huly/huly_plugin.py` 独立创作 | 本 plan 实现 |
| `plugin_daemon.py:126-141` PluginDaemonError | JSONRPC error envelope code/message 设计 | `huly_plugin.py` METHODS NotImplementedError → -32603 | 本 plan 实现 |
| Phase 4 mock provider 模式（httpx_mock） | aiohttp stub server 监听本地端口 | `tests/platforms_integration/mock_huly_server.py` | 本 plan 实现 |
| `plugin_service.py` install task subprocess | fault isolation 实测 SIGKILL daemon | `tests/platforms_integration/test_fault_isolation.py` | 本 plan 实现 |
| 用户三连质疑 — Pitfall 9 | timing assert 防 mock client 退化 | `test_huly_plugin_real_subprocess_send_card_end_to_end` elapsed > 0.2s | 本 plan 实现 |

### License Attribution（critical）

- **Dify**: AGPL-3.0
- **dify-plugin-daemon**: AGPL-3.0
- **agent-builder**: Apache-2.0

**严禁拷贝 Dify / dify-plugin-daemon 源代码到本仓库**。本 plan 所有代码（`plugins/huly/huly_plugin.py` / `mock_huly_server.py` / acid test / fault isolation test）均为独立创作：
- 仅借鉴 Dify 的**设计模式 / 数据结构思路 / 边界考虑**
- JSONRPC 2.0 是公开标准（https://www.jsonrpc.org/specification），不属于 Dify 知识产权
- aiohttp.web stub 用法是 Python 生态标准模式
- subprocess + asyncio 用法是 Python 标准库

### 关键 Pitfall 列表（reading 提取）

| # | Pitfall | 防御策略 |
| - | --- | --- |
| 2 | daemon crash 主进程 hang | `_read_loop` 检测 stdout EOF → `_fail_all_pending` (Plan 05 已实现) |
| 8 | stderr pipe buffer 满 daemon 假死 | `_stderr_drain` 独立 task (Plan 05 已实现) |
| 9 | acid test 走 mock 而非真 daemon | **本 plan 重点**：timing assert > 200ms |

### 反模式（绝对不写）

1. ❌ `with mock.patch("PlatformDaemonClient.invoke")` 在 acid test 内 → 抽象只在纸面
2. ❌ 用 `subprocess.Popen` 替代 `asyncio.create_subprocess_exec` → 阻塞 event loop
3. ❌ acid test 不带 timing assert → 退化为 mock 不被发现
4. ❌ fault isolation test 用大 invoke_timeout（如 30s）→ 测试通过但 SLO 失败仍可能发生
5. ❌ 拷贝 Dify Go 源码到本仓库 → AGPL/Apache 许可证混淆 + Dify 内部 API 演进时本项目跟不上

---

## 借鉴点对照总表（每条标注 Dify source file → 5.A target module）

| # | Dify 源 | 借鉴模式 | 5.A target | 行数估算 |
| - | --- | --- | --- | --- |
| 1 | `plugin_service.py` + daemon README | daemon spawn 简化为 subprocess + stdio | `plugins/huly/huly_plugin.py` | ≥ 80 行 |
| 2 | `plugin_daemon.py:126-141` PluginDaemonError | JSONRPC error envelope code/message | `huly_plugin.py` METHODS dict + dispatch | (含在上一行) |
| 3 | Phase 4 mock provider + httpx_mock | aiohttp.web stub local port | `tests/platforms_integration/mock_huly_server.py` | ≥ 40 行 |
| 4 | `plugin_service.py` install subprocess | SIGKILL fault isolation 实测 | `tests/platforms_integration/test_fault_isolation.py` | ≥ 50 行 |
| 5 | 用户三连质疑 + Pitfall 9 | timing > 200ms 防 mock client 退化 | `tests/platforms_integration/test_huly_acid_test.py` | ≥ 80 行 |

---

## 总结

Plan 05a-07 是 Phase 5.A 的最后一块拼图（acid test），把 Plan 01-06 累积的 PlatformPlugin / Capability Protocols / Manifest / Registry / DaemonClient / LegacyAdapter 链路从「单测各自通过」推进到「真实链路端到端通」。

**5 借鉴点全部围绕一个核心**：**让抽象不仅在单测中通过、更在真子进程 + 真 mock server + 真 JSONRPC roundtrip + 真 SIGKILL fault isolation 中通过**。

用户 2026-05-17 三连质疑后的核心要求：**timing 数字（> 200ms / < 2.0s）是测试本身的元测试，它确保「acid test 永远是 acid test」而不是「装作 acid test 的 mock test」**。

---

*Reading date: 2026-05-17*
*Plan: 05a-07*
*Reading by: Claude (executor)*
