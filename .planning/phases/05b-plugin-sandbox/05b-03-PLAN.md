---
phase: 05b-plugin-sandbox
plan: 03
type: execute
wave: 2
depends_on:
  - "05b-01"
files_modified:
  - docs/reading-dify-05b-03-network-allowlist-2026-05-17.md
  - backend/app/agent_builder/platforms/sandbox/network.py
  - backend/tests/platforms/sandbox/test_network.py
  - backend/tests/platforms_integration/test_network_allowlist.py
  - backend/tests/platforms_integration/fixtures/network_test_daemon.py
  - plugins/huly/huly_plugin.py
autonomous: true
requirements:
  - PLUG-FW-11

must_haves:
  truths:
    - "AllowlistTransport 子类化 httpx.AsyncBaseTransport — handle_async_request 检查 host:port 在白名单"
    - "白名单匹配规则：exact (host, port) 匹配（host 自动 lowercase，缺 port 时按 scheme 补齐 80/443）"
    - "非白名单 host raise NetworkBlockedError（Plan 05b-02 已定义占位）"
    - "make_sandboxed_http_client(allow_list) helper 返回 httpx.AsyncClient 注入 AllowlistTransport"
    - "AllowlistTransport 默认 delegate 为 httpx.AsyncHTTPTransport；测试可 inject MockTransport"
    - "v1 不支持通配符（*.example.com）— exact 匹配（manifest validator 已校验格式）"
    - "huly_plugin.py 升级用 make_sandboxed_http_client 替代裸 aiohttp（env-gated 兼容 5.A acid test）"
    - "Dify 阅读文档先于代码 commit（CLAUDE.md §2.7 硬性 gate）"
  artifacts:
    - path: "docs/reading-dify-05b-03-network-allowlist-2026-05-17.md"
      provides: "Dify plugin 网络隔离实现思路 + httpx Transport API 设计点"
      min_lines: 80
    - path: "backend/app/agent_builder/platforms/sandbox/network.py"
      provides: "AllowlistTransport class + make_sandboxed_http_client helper"
      contains: "class AllowlistTransport"
    - path: "backend/tests/platforms/sandbox/test_network.py"
      provides: "AllowlistTransport 单元测试（block / allow / case-insensitive / port-default）"
    - path: "backend/tests/platforms_integration/test_network_allowlist.py"
      provides: "AllowlistTransport 端到端 daemon spawn 集成测"
    - path: "backend/tests/platforms_integration/fixtures/network_test_daemon.py"
      provides: "测试 daemon entrypoint — 尝试出网，断言 NetworkBlockedError"
    - path: "plugins/huly/huly_plugin.py"
      provides: "演示集成：im_send_card 内 env-gated 用 make_sandboxed_http_client"
  key_links:
    - from: "backend/app/agent_builder/platforms/sandbox/network.py"
      to: "backend/app/agent_builder/platforms/exceptions.py"
      via: "raise NetworkBlockedError(Plan 05b-02 已占位定义)"
      pattern: "from ..exceptions import NetworkBlockedError"
    - from: "plugins/huly/huly_plugin.py"
      to: "backend/app/agent_builder/platforms/sandbox/network.py"
      via: "im_send_card 内调 make_sandboxed_http_client(allow_list)"
      pattern: "make_sandboxed_http_client"
---

<objective>
实现 application-level 网络白名单 — `AllowlistTransport`（httpx `AsyncBaseTransport` 子类化）+ `make_sandboxed_http_client(allow_list)` helper。plugin daemon entrypoint 显式注入沙箱化 httpx client；非白名单 host 调用 raise `NetworkBlockedError`（Plan 05b-02 已占位定义）。

Purpose: 网络白名单是 plugin 安全控制的关键 — manifest `sandbox.network: ["huly.example.com:443"]` 声明后，plugin 仅能访问白名单 host；其它 host 立即 raise NetworkBlockedError（不真发 HTTP 防数据泄漏）。

Output: 1 个 Dify reading doc + sandbox/network.py（AllowlistTransport + make_sandboxed_http_client）+ 单元测试 + 集成测 daemon fixture + 修改 huly_plugin.py 演示真实集成（env-gated 不破坏 5.A acid test）。
</objective>

<execution_context>
@/Users/admin/.claude/get-shit-done/workflows/execute-plan.md
@/Users/admin/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/phases/05b-plugin-sandbox/05b-CONTEXT.md
@.planning/phases/05b-plugin-sandbox/05b-RESEARCH.md
@.planning/phases/05b-plugin-sandbox/05b-01-PLAN.md
@backend/app/agent_builder/platforms/exceptions.py
@backend/app/agent_builder/platforms/sandbox/runner.py
@plugins/huly/huly_plugin.py
@plugins/huly/platform.yaml
@CLAUDE.md

<interfaces>
From backend/app/agent_builder/platforms/sandbox/network.py（本 plan 创建）:
```python
import httpx
class AllowlistTransport(httpx.AsyncBaseTransport):
    def __init__(self, allow_list: list[str], *, delegate: httpx.AsyncBaseTransport | None = None) -> None: ...
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response: ...
    async def aclose(self) -> None: ...

def make_sandboxed_http_client(allow_list: list[str]) -> httpx.AsyncClient:
    """plugin daemon 显式调此 helper 拿沙箱化 client。"""
```

From backend/app/agent_builder/platforms/exceptions.py（Plan 05b-02 已定义占位）:
```python
class NetworkBlockedError(Exception): ...
```

5.A plugins/huly/huly_plugin.py 兼容策略:
- 5.A acid test 不设 `PLUGIN_NETWORK_ALLOW` env → 走 fallback aiohttp 路径 → 0 regression
- Plan 05b-03 集成测设 env → 走新 httpx + AllowlistTransport 路径
</interfaces>
</context>

<reference>
Dify 模块映射（CLAUDE.md §2.7）:
- 后端必读: `api/services/plugin/plugin_service.py` （grep "network\|outbound\|whitelist\|httpx\|aiohttp\|requests" 至少 30 行）
- 后端参考: `api/core/plugin/manager.py` （plugin 网络策略注入）
- 前端补充: `web/app/components/plugins/` 任一 permission 组件
- 第三方参考: httpx 官方 docs https://www.python-httpx.org/advanced/transports/ （BSD-3 公开 API 可引用）

借鉴重点（reading doc 必含）:
1. Dify 是否有网络白名单？什么层级（OS-level vs application-level）
2. httpx Transport API 子类化模式
3. Dify plugin 内 HTTP 库选择倾向（httpx / aiohttp / requests）
4. urlparse 提取 host/port 与 port 默认值（80/443）策略
5. v2 真隔离思路（namespace / iptables — 本 phase 不投入）

License: Dify AGPL-3.0 vs agent-builder Apache-2.0 — 严禁拷代码。httpx BSD-3 公开 API 可引用。
</reference>

<tasks>

<task type="auto">
  <name>Task 0: Dify reading doc（CLAUDE.md §2.7 硬性 gate）</name>
  <files>docs/reading-dify-05b-03-network-allowlist-2026-05-17.md</files>
  <action>
    阅读以下 Dify 文件并写阅读笔记（先 commit 此 doc 才能进 Task 1）:

    1. `/Users/admin/ai/ref/dify/repo/api/services/plugin/plugin_service.py` — grep "network|whitelist|allow|outbound|http" 至少 30 行
    2. `/Users/admin/ai/ref/dify/repo/api/core/plugin/manager.py` — grep 同上
    3. 前端补充: `/Users/admin/ai/ref/dify/repo/web/app/components/plugins/` ls 任一 permission/security 组件

    若 Dify 无 application-level 网络白名单（很可能），明确记录此差异点 — 说明本项目 v1 application-level + httpx 注入是更轻量方案。

    文档结构按 CLAUDE.md §2.7 模板:
    - 项目概述
    - 技术栈对照（Dify daemon Go cgroups namespace vs 本项目 Python httpx Transport API）
    - 架构要点（plugin 出站请求拦截点选型）
    - 可借鉴设计模式 4-6 条（httpx 公开 API 引用 + Dify 设计概念）
    - 与本项目关系（v1 application-level trade-off + Pitfall 3 旁路风险 + v2 隔离规划）
    - License attribution

    最少 80 行；commit message: `docs(05b-03): add Dify network allowlist reading doc`。
  </action>
  <verify>
    <automated>test -f /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05b-03-network-allowlist-2026-05-17.md && wc -l /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05b-03-network-allowlist-2026-05-17.md | awk '{exit ($1>=80)?0:1}'</automated>
  </verify>
  <done>reading doc 文件存在；≥ 80 行；git log 显示本 doc commit 在 Task 1 之前。</done>
</task>

<task type="auto">
  <name>Task 1: AllowlistTransport + make_sandboxed_http_client helper + huly_plugin 集成</name>
  <files>
    backend/app/agent_builder/platforms/sandbox/network.py
    plugins/huly/huly_plugin.py
  </files>
  <action>
    1. 创建 `backend/app/agent_builder/platforms/sandbox/network.py`:

    完整代码骨架（按 RESEARCH §Pattern 3 实现）:
    ```python
    """AllowlistTransport — application-level 网络白名单（PLUG-FW-11）。

    设计要点（RESEARCH §Pattern 3 + Pitfall 3 + reading doc）:
    - httpx.AsyncBaseTransport 子类化 — 注入点最干净（vs socket monkey-patch）
    - exact (host, port) 匹配；host lowercase；port 缺省按 scheme 补齐 80/443
    - 非白名单 host raise NetworkBlockedError
    - delegate 默认 httpx.AsyncHTTPTransport；测试可 inject MockTransport
    - v1 不支持通配符（manifest validator 已校验 host:port exact 格式）

    旁路警告（Pitfall 3 v1 trade-off）:
        plugin 内 `import requests; requests.get(...)` 完全绕开（不走 httpx）
        v1: plugin developer guide 强制要求用 make_sandboxed_http_client()
        v2: Phase 6 marketplace 上 nsjail / network namespace 真隔离

    License: 100% 独立创作；引用 httpx BSD-3 公开 API（不拷 Dify AGPL 代码）。
    """
    from __future__ import annotations
    import logging
    from urllib.parse import urlparse
    import httpx
    from ..exceptions import NetworkBlockedError

    _log = logging.getLogger(__name__)


    class AllowlistTransport(httpx.AsyncBaseTransport):
        def __init__(
            self,
            allow_list: list[str],
            *,
            delegate: httpx.AsyncBaseTransport | None = None,
        ) -> None:
            self._allow_set: set[tuple[str, int]] = set()
            for entry in allow_list:
                host, _, port_str = entry.partition(":")
                if not port_str:
                    _log.warning("AllowlistTransport entry missing port: %r", entry)
                    continue
                self._allow_set.add((host.lower(), int(port_str)))
            self._delegate = delegate or httpx.AsyncHTTPTransport()

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            parsed = urlparse(str(request.url))
            host = (parsed.hostname or "").lower()
            port = parsed.port or (443 if parsed.scheme == "https" else 80)

            if (host, port) not in self._allow_set:
                _log.warning(
                    "network.blocked host=%s port=%s scheme=%s — not in allow_list (%d entries)",
                    host, port, parsed.scheme, len(self._allow_set),
                )
                raise NetworkBlockedError(
                    f"network blocked by sandbox: {host}:{port} not in allow_list"
                )
            return await self._delegate.handle_async_request(request)

        async def aclose(self) -> None:
            await self._delegate.aclose()


    def make_sandboxed_http_client(
        allow_list: list[str],
        *,
        timeout: float = 10.0,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=AllowlistTransport(allow_list),
            timeout=httpx.Timeout(timeout),
        )

    __all__ = ["AllowlistTransport", "make_sandboxed_http_client"]
    ```

    2. 修改 `plugins/huly/huly_plugin.py` — env-gated 升级（保留 5.A acid test 兼容）:

    - 顶部加 import: `from app.agent_builder.platforms.sandbox.network import make_sandboxed_http_client`
    - 新增 helper `_parse_network_allow()`: 读 `os.environ.get("PLUGIN_NETWORK_ALLOW", "")` 拆 "," 分隔
    - `im_send_card` 函数内: `allow_list = _parse_network_allow()`；如果 `allow_list` 非空走 httpx 路径，否则走原 aiohttp 路径
    - 5.A acid test 不设 env → 自动走 aiohttp fallback → 0 regression

    避坑:
    - `httpx.AsyncBaseTransport.aclose()` 必须 async（不是 close）— delegate.aclose() 也 async
    - urlparse 对 IPv6 处理特殊；v1 假定 host 是 hostname（manifest validator 约束）
    - `httpx.MockTransport(lambda req: httpx.Response(200, json={"ok": True}))` 是测试 inject 路径
    - 不要全局 monkey-patch httpx（RESEARCH §Anti-Patterns 禁止）— 仅 plugin 显式调 helper
    - aiohttp fallback 路径保留 huly_plugin 全部既有代码（不删；仅 if/else 分支）

    commit messages:
    - `feat(05b-03): add AllowlistTransport + make_sandboxed_http_client (PLUG-FW-11)`
    - `feat(05b-03): integrate sandboxed http client in huly_plugin (env-gated, fallback compat)`
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -c "from app.agent_builder.platforms.sandbox.network import AllowlistTransport, make_sandboxed_http_client; import httpx; assert issubclass(AllowlistTransport, httpx.AsyncBaseTransport); c = make_sandboxed_http_client(['example.com:443']); assert isinstance(c, httpx.AsyncClient)"</automated>
  </verify>
  <done>AllowlistTransport 是 httpx.AsyncBaseTransport 子类；make_sandboxed_http_client 返回 AsyncClient；huly_plugin import 成功；5.A acid test 在 PLUGIN_NETWORK_ALLOW 未设时走 aiohttp 路径不变。</done>
</task>

<task type="auto">
  <name>Task 2: 单元测试 + 集成测 + 5.A regression</name>
  <files>
    backend/tests/platforms/sandbox/test_network.py
    backend/tests/platforms_integration/test_network_allowlist.py
    backend/tests/platforms_integration/fixtures/network_test_daemon.py
  </files>
  <action>
    1. 单元测试 `backend/tests/platforms/sandbox/test_network.py` ≥ 10 测:

    - `test_allowlist_blocks_unlisted_host`: AllowlistTransport(["example.com:443"]) + httpx.MockTransport delegate → GET https://other.com → raises NetworkBlockedError
    - `test_allowlist_allows_whitelisted_host`: 同上 → GET https://example.com → 返回 200 (走 MockTransport delegate)
    - `test_allowlist_host_case_insensitive`: allow=["Example.COM:443"] → GET https://EXAMPLE.com → 200（规则化 lowercase）
    - `test_allowlist_https_default_port_443`: allow=["example.com:443"] → GET https://example.com（无显式 port）→ 200
    - `test_allowlist_http_default_port_80`: allow=["example.com:80"] → GET http://example.com → 200
    - `test_allowlist_port_mismatch_blocked`: allow=["example.com:443"] → GET http://example.com:80 → raises（port 不同）
    - `test_allowlist_empty_blocks_everything`: AllowlistTransport([]) → 任何 GET → raises（restrictive 默认）
    - `test_allowlist_malformed_entry_skipped_with_warning`: allow=["bad-no-port", "example.com:443"] → 第一条 skip warning，第二条仍工作
    - `test_make_sandboxed_http_client_returns_AsyncClient`: 返回值 isinstance httpx.AsyncClient
    - `test_make_sandboxed_http_client_uses_allowlist`: helper 返回 client → GET 非白名单 raises NetworkBlockedError
    - `test_aclose_propagates_to_delegate`: MockTransport.aclose 被调（断言 mock 的 aclose called）
    - `test_NetworkBlockedError_message_contains_host_port`: raised exception str 含 "blocked" + host + ":" + port

    所有用 `@pytest.mark.asyncio` + httpx.MockTransport delegate（不真发请求）。

    2. 集成测 fixture `backend/tests/platforms_integration/fixtures/network_test_daemon.py`:

    一个 daemon entrypoint，启动后用 make_sandboxed_http_client + 试 GET 两个 host（一个白名单内一个外）+ 打印结果到 stdout:
    ```python
    """fixture daemon — 测 AllowlistTransport 集成场景."""
    import asyncio, os, sys
    from app.agent_builder.platforms.sandbox.network import make_sandboxed_http_client
    from app.agent_builder.platforms.exceptions import NetworkBlockedError

    async def main() -> int:
        allow = os.environ.get("PLUGIN_NETWORK_ALLOW", "").split(",")
        allow = [e.strip() for e in allow if e.strip()]
        target = os.environ.get("TARGET_URL", "https://blocked.example.com/")

        async with make_sandboxed_http_client(allow) as client:
            try:
                r = await client.get(target, timeout=2.0)
                print(f"unexpected_ok:{r.status_code}", flush=True)
                return 0
            except NetworkBlockedError as e:
                print(f"blocked:{e}", flush=True)
                return 10
            except Exception as e:
                # 真发请求失败（DNS / timeout）— v1 接受作为 fallback 信号
                print(f"network_error:{type(e).__name__}:{e}", flush=True)
                return 20

    if __name__ == "__main__":
        sys.exit(asyncio.run(main()))
    ```

    3. 集成测 `backend/tests/platforms_integration/test_network_allowlist.py` ≥ 4 测（@pytest.mark.sandbox_integration）:

    - `test_daemon_with_empty_allow_blocks_everything`: subprocess 跑 fixture daemon，env PLUGIN_NETWORK_ALLOW="" + TARGET_URL=https://blocked.example.com/ → stdout 含 "blocked:" + returncode == 10
    - `test_daemon_with_target_in_allow_attempts_real_request`: env PLUGIN_NETWORK_ALLOW="blocked.example.com:443" → AllowlistTransport 放行 → 真发请求（DNS 失败也算"通过白名单"）→ stdout 含 "network_error:" 或 "unexpected_ok:" → returncode != 10（不被 blocked）
    - `test_daemon_target_not_in_allow_is_blocked`: env PLUGIN_NETWORK_ALLOW="other-host.com:443" + TARGET_URL=https://blocked.example.com/ → stdout 含 "blocked:" + returncode == 10
    - `test_daemon_loglevel_warning_emitted_when_blocked`: capture stderr 包含 "network.blocked"（structured log）

    用 `asyncio.subprocess.create_subprocess_exec` 直接起 fixture daemon 子进程；不依赖 Wave 3 的 PlatformDaemonClient（Wave 2 plans 不修改 daemon_client.py）。

    4. **5.A regression check**:
    - `pytest backend/tests/platforms/ -x` 5.A 162 测试 0 regression（本 plan 仅新增文件 + huly_plugin env-gated 不变 acid test 行为）
    - `pytest backend/tests/platforms_integration/test_huly_acid_test.py -v` 5.A 3 acid test 0 regression（未设 PLUGIN_NETWORK_ALLOW → 走 aiohttp fallback）
    - `pytest backend/tests/notification/ -x` Phase 4 81 IM 0 regression

    避坑:
    - `httpx.MockTransport` 接收 `lambda req: httpx.Response(200, ...)` —— request 类型是 `httpx.Request` 不是 `httpx.Connection`
    - urlparse 对 `https://example.com:443/` 的 port 是 443（显式时）；对 `https://example.com/` port 是 None → 补 443
    - 集成测 daemon 必须用 `cwd=backend/`（让 `from app.agent_builder...` 能 import）
    - 不要试图断言真发请求成功（DNS 不可控）；断言 blocked vs not-blocked 的区分即可
    - Phase 4 IM 测试中可能因 lark_oapi/wecom 等 SDK 缺失 skip（不算 regression）

    commit messages:
    - `test(05b-03): add AllowlistTransport unit tests (≥ 10 cases)`
    - `test(05b-03): add network_test_daemon fixture + integration tests`
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -m pytest tests/platforms/sandbox/test_network.py -v 2>&1 | tail -20</automated>
  </verify>
  <done>
    单元测试 ≥ 10 全 pass；集成测 ≥ 4 全 pass（@pytest.mark.sandbox_integration）；5.A 162 platforms + 3 acid test + 81 IM 0 regression；huly_plugin.py 集成无破坏。
  </done>
</task>

</tasks>

<verification>
**phase-local checks**:
- `pytest backend/tests/platforms/sandbox/test_network.py -v` ≥ 10 测全绿
- `pytest backend/tests/platforms_integration/test_network_allowlist.py -v` ≥ 4 测全绿

**5.A regression**:
- `pytest backend/tests/platforms/ -x` 0 fail（162 测试）
- `pytest backend/tests/platforms_integration/test_huly_acid_test.py -v` 3 acid test 0 fail
- `pytest backend/tests/platforms_integration/test_fault_isolation.py -v` 2 fault isolation 0 fail

**Phase 4 regression**:
- `pytest backend/tests/notification/ -x` 81 IM 0 regression

**reading doc gate**:
- `git log --oneline -10 | head` docs(05b-03) commit 早于任何 feat(05b-03) commit
</verification>

<success_criteria>
1. **AllowlistTransport 子类化**: 是 httpx.AsyncBaseTransport 子类，handle_async_request override 正确
2. **匹配规则正确**: exact (host, port) lowercase；port 默认按 scheme 补齐（80/443）
3. **拒绝模式正确**: 空 allow_list = 禁所有（restrictive baseline 防 Pitfall 3 安全核心）
4. **make_sandboxed_http_client helper**: 返回正确 httpx.AsyncClient with transport
5. **huly_plugin 集成 env-gated**: 5.A acid test 不设 env → 0 regression；新集成测设 env → 走新路径
6. **测试覆盖**: 单元 ≥ 10 + 集成 ≥ 4 全绿
7. **5.A regression**: 162 platforms + 5/5 acid test + 81 IM 0 regression
8. **reading doc gate**: docs commit 早于 feat commit（CLAUDE.md §2.7）
</success_criteria>

<output>
After completion, create `.planning/phases/05b-plugin-sandbox/05b-03-SUMMARY.md` 含:
- Dify 借鉴点（Dify 无对应 application-level 实现 → 本项目独创轻量方案）
- AllowlistTransport 设计取舍（exact match vs glob 通配符 / port 默认值策略）
- Pitfall 3 v1 trade-off 接受范围（requests / urllib 旁路 — v2 marketplace 上 namespace 真隔离）
- 集成测 daemon fixture 模式（Wave 3 plans 可复用 fixtures/ 子包结构）
</output>
</content>
</invoke>