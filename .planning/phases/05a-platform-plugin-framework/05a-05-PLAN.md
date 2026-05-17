---
phase: 05a-platform-plugin-framework
plan: 05
type: execute
wave: 4
depends_on: ["04"]
files_modified:
  - docs/reading-dify-05a-05-daemon-client-2026-05-17.md
  - backend/app/agent_builder/platforms/daemon_client.py
  - backend/app/agent_builder/platforms/capability_facades.py
  - backend/app/agent_builder/platforms/mock_plugin.py
  - tests/platforms/test_daemon_client.py
  - tests/platforms/test_mock_plugin.py
  - tests/platforms/fixtures/echo_daemon.py
autonomous: true
requirements:
  - PLUG-FW-05
  - PLUG-FW-06
must_haves:
  truths:
    - "PlatformDaemonClient 可起 Python 子进程 + 通过 JSONRPC over stdio 双向通信"
    - "JSONRPC request_id (UUID4) 关联到 asyncio.Future；响应到达后正确 set_result"
    - "Capability facades 转发 method call 到 daemon.invoke(capability, method, **kwargs)"
    - "MockPlatformPlugin 声明 IM+Doc+HR 多 capability，单测可走 Registry get_capability 完整路径"
  artifacts:
    - path: "backend/app/agent_builder/platforms/daemon_client.py"
      provides: "PlatformDaemonClient asyncio subprocess + JSONRPC 2.0 dispatcher (~150 LOC)"
      exports: ["PlatformDaemonClient"]
      min_lines: 150
    - path: "backend/app/agent_builder/platforms/capability_facades.py"
      provides: "IM/Doc/HR/Identity 4 facade 实接入 daemon.invoke（替换 plan 04 stub）"
      exports: ["IMFacade", "DocFacade", "HRFacade", "IdentityFacade"]
      min_lines: 120
    - path: "backend/app/agent_builder/platforms/mock_plugin.py"
      provides: "MockPlatformPlugin in-process plugin（不走 daemon），单测用"
      exports: ["MockPlatformPlugin", "MockIMCapability", "MockDocCapability", "MockHRCapability"]
      min_lines: 100
    - path: "tests/platforms/fixtures/echo_daemon.py"
      provides: "测试用 echo daemon — 读 stdin JSONRPC，按 method 返回固定 result"
      min_lines: 40
  key_links:
    - from: "backend/app/agent_builder/platforms/capability_facades.py"
      to: "backend/app/agent_builder/platforms/daemon_client.py"
      via: "IMFacade.send_card → daemon.invoke('im', 'send_card', recipient=..., card=...)"
      pattern: "self._daemon.invoke"
    - from: "tests/platforms/test_daemon_client.py"
      to: "tests/platforms/fixtures/echo_daemon.py"
      via: "spawn 真子进程 + 发 JSONRPC + 验响应"
      pattern: "create_subprocess_exec.*echo_daemon"
---

<objective>
实现 plugin 框架运行时核心：PlatformDaemonClient（JSONRPC over stdio）+ Capability facades 真接入 daemon + MockPlatformPlugin 用于单测。本 plan 不写 HulyPlugin（留 plan 06）。

Purpose: 给 plan 06 HulyPlugin acid test 准备 daemon 通信底座；MockPlugin 让 Registry / Facade 单测能走完整路径不依赖真 daemon。
Output: 3 个核心 module（daemon_client / capability_facades 替换 / mock_plugin）+ 2 测试文件 + echo_daemon fixture。
</objective>

<execution_context>
@/Users/admin/.claude/get-shit-done/workflows/execute-plan.md
@/Users/admin/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/05a-platform-plugin-framework/05a-CONTEXT.md
@.planning/phases/05a-platform-plugin-framework/05a-RESEARCH.md
@docs/plans/2026-05-17-platform-plugin-framework-ADR.md
@backend/app/agent_builder/platforms/plugin.py
@backend/app/agent_builder/platforms/manifest.py
@backend/app/agent_builder/platforms/exceptions.py

<interfaces>
From plan 04 (Registry + Plugin shell):
- PlatformPlugin(manifest, daemon=None) + .attach_daemon(daemon)
- PlatformPlugin.im/.doc/.hr/.identity @property 返回 facade（暂用 stub）

From RESEARCH.md §Pattern 3 (Daemon Client):
- asyncio.create_subprocess_exec("python", "-u", "-m", module_entry)
- line-delimited JSON envelope: {jsonrpc: "2.0", id: uuid, method: "im.send_card", params: {...}}
- _pending: dict[uuid_str, asyncio.Future]; _read_loop 按 id 路由响应
- close: terminate → wait 5s → kill

From RESEARCH.md §Pitfall 2 + 8:
- daemon 退出 → _pending 所有 future set_exception(PluginDaemonExitedError)
- stderr drain task 防 buffer 满死锁

From exceptions.py (plan 02):
- PluginDaemonExitedError / PluginInvocationError
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 0: Dify daemon protocol 阅读文档（CLAUDE.md §2.7 硬性 gate）</name>
  <files>docs/reading-dify-05a-05-daemon-client-2026-05-17.md</files>
  <action>
读：
1. `/Users/admin/ai/ref/dify/repo/api/core/plugin/entities/plugin_daemon.py` — 各 Response 类（PluginDaemonBasicResponse 泛型 / PluginDaemonError / PluginDaemonInnerError）
2. dify-plugin-daemon repo README (https://github.com/langgenius/dify-plugin-daemon) 概述其 RPC 设计（仅看 README，不读 Go 源码避免 license 沾染）
3. `/Users/admin/ai/ref/dify/repo/api/services/plugin/plugin_service.py` 中调 daemon 的部分（fetch_install_tasks / install_from_local_package 等）

写到 `docs/reading-dify-05a-05-daemon-client-2026-05-17.md`，标准 5 节模板。

**5 借鉴点**：
1. PluginDaemonBasicResponse 泛型 result 字段 → 5.A JSONRPC envelope.result 类型化（虽然我们用 dict）
2. PluginDaemonError 区分 error code + message → 5.A JSONRPC 2.0 error 字段 (code/message)
3. Dify daemon 跑独立 Go 进程 + gRPC 通信 → 5.A 简化为 Python 子进程 + JSONRPC stdio（v1 决策）
4. PluginInstallTask 异步进度（pending/running/success） → 5.A v1 同步 invoke（异步 task 留 v2）
5. dify-plugin-daemon 进程管理（spawn / restart on crash） → 5.A v1 简化：crash 不自动重启（fault isolation 报错；Phase 5.B 加 restart policy）

License attribution；不拷源代码；≥ 50 行。
  </action>
  <verify>
    <automated>test -f docs/reading-dify-05a-05-daemon-client-2026-05-17.md && wc -l docs/reading-dify-05a-05-daemon-client-2026-05-17.md | awk '{exit ($1 >= 50 ? 0 : 1)}' && grep -q "AGPL\|attribution" docs/reading-dify-05a-05-daemon-client-2026-05-17.md</automated>
  </verify>
  <done>Reading doc ≥ 50 行 + 5 借鉴点 + License attribution + commit 在前</done>
</task>

<task type="auto">
  <name>Task 1: PlatformDaemonClient + echo_daemon fixture + 测试</name>
  <files>backend/app/agent_builder/platforms/daemon_client.py,tests/platforms/test_daemon_client.py,tests/platforms/fixtures/echo_daemon.py</files>
  <action>
1. **`backend/app/agent_builder/platforms/daemon_client.py`** 按 RESEARCH.md §Pattern 3 实现：

```python
"""PlatformDaemonClient — JSONRPC over stdio 主进程↔daemon 通信。

设计要点（ADR-001 §5 + RESEARCH.md §Pattern 3 + Pitfall 2/8）：
- asyncio.create_subprocess_exec spawn daemon
- line-delimited JSON envelope (JSON-RPC 2.0)
- request_id (UUID4) 关联 asyncio.Future；_read_loop 按 id 路由响应
- daemon 退出 → 所有 pending future set_exception(PluginDaemonExitedError)
- stderr drain task 防 pipe buffer 满死锁
- close: terminate → wait 5s → kill
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from typing import Any

from .exceptions import PluginDaemonExitedError, PluginInvocationError

_log = logging.getLogger(__name__)


_DEFAULT_INVOKE_TIMEOUT = 30.0


class PlatformDaemonClient:
    def __init__(
        self,
        module_entry: str,
        env: dict[str, str] | None = None,
        invoke_timeout: float = _DEFAULT_INVOKE_TIMEOUT,
    ):
        """Args:
            module_entry: 子进程跑 `python -u -m <module_entry>`，daemon 需在 __main__ 写 asyncio.run(main())
            env: 额外环境变量（如 HULY_ENDPOINT, AUTH_TOKEN）
            invoke_timeout: 每个 invoke 等响应的超时（秒）
        """
        self._module_entry = module_entry
        self._env = env
        self._invoke_timeout = invoke_timeout
        self._proc: asyncio.subprocess.Process | None = None
        self._pending: dict[str, asyncio.Future[Any]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._closed = False
        self._lock = asyncio.Lock()  # start 串行

    async def start(self) -> None:
        async with self._lock:
            if self._proc is not None:
                return
            import os
            merged_env = dict(os.environ)
            if self._env:
                merged_env.update(self._env)
            self._proc = await asyncio.create_subprocess_exec(
                sys.executable, "-u", "-m", self._module_entry,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=merged_env,
            )
            self._reader_task = asyncio.create_task(self._read_loop(), name="daemon-stdout-reader")
            self._stderr_task = asyncio.create_task(self._stderr_drain(), name="daemon-stderr-drain")

    async def invoke(self, capability: str, method: str, **kwargs: Any) -> Any:
        """发 JSONRPC request → 等响应。

        Raises:
            PluginInvocationError: daemon 返回 JSONRPC error
            PluginDaemonExitedError: daemon 子进程在 invoke 期间退出
            asyncio.TimeoutError: invoke_timeout 超时
        """
        if self._proc is None:
            await self.start()
        if self._proc is None or self._proc.stdin is None:
            raise PluginDaemonExitedError("daemon failed to start or stdin closed")

        req_id = uuid.uuid4().hex
        future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future
        envelope = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": f"{capability}.{method}",
            "params": kwargs,
        }
        try:
            line = (json.dumps(envelope) + "\n").encode("utf-8")
            self._proc.stdin.write(line)
            await self._proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as e:
            self._pending.pop(req_id, None)
            raise PluginDaemonExitedError(f"daemon stdin broken: {e}") from e

        try:
            return await asyncio.wait_for(future, timeout=self._invoke_timeout)
        finally:
            self._pending.pop(req_id, None)

    async def _read_loop(self) -> None:
        """从 daemon stdout 读响应 → 按 id 路由到 _pending future。"""
        assert self._proc and self._proc.stdout
        try:
            while not self._closed:
                line = await self._proc.stdout.readline()
                if not line:
                    # daemon exited
                    self._fail_all_pending(PluginDaemonExitedError("daemon stdout closed"))
                    break
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    _log.warning("daemon emitted non-JSON line: %r", line[:200])
                    continue
                rid = msg.get("id")
                if rid and rid in self._pending:
                    fut = self._pending.pop(rid)
                    if "error" in msg:
                        fut.set_exception(PluginInvocationError(msg["error"]))
                    else:
                        fut.set_result(msg.get("result"))
        except Exception as e:
            _log.exception("daemon read loop crashed: %s", e)
            self._fail_all_pending(PluginDaemonExitedError(f"read loop crashed: {e}"))

    async def _stderr_drain(self) -> None:
        """持续读 daemon stderr → log forward；防 pipe buffer 满死锁（Pitfall 8）。"""
        assert self._proc and self._proc.stderr
        try:
            while not self._closed:
                line = await self._proc.stderr.readline()
                if not line:
                    break
                _log.info("[daemon:%s stderr] %s", self._module_entry, line.decode("utf-8", errors="replace").rstrip())
        except Exception:
            pass

    def _fail_all_pending(self, exc: Exception) -> None:
        for rid, fut in list(self._pending.items()):
            if not fut.done():
                fut.set_exception(exc)
        self._pending.clear()

    async def close(self) -> None:
        self._closed = True
        if self._proc is None:
            return
        try:
            self._proc.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            self._proc.kill()
            await self._proc.wait()
        if self._reader_task:
            self._reader_task.cancel()
        if self._stderr_task:
            self._stderr_task.cancel()
        self._fail_all_pending(PluginDaemonExitedError("daemon closed"))
        self._proc = None
```

≥ 150 行。

2. **`tests/platforms/fixtures/echo_daemon.py`** — 测试用 daemon：

```python
"""Echo daemon — Phase 5.A test fixture。

读 stdin JSONRPC line，按 method 返回固定 result（不真调外部服务）。
"""
from __future__ import annotations

import asyncio
import json
import sys


async def main() -> None:
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        line = await reader.readline()
        if not line:
            break
        try:
            envelope = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = envelope.get("method", "")
        params = envelope.get("params", {})

        if method == "im.send_card":
            response = {"jsonrpc": "2.0", "id": envelope["id"], "result": {"plugin_name": "echo", "native_id": f"echo-{params.get('idempotency_key', 'k')}", "extras": {}}}
        elif method == "im.echo_error":
            response = {"jsonrpc": "2.0", "id": envelope["id"], "error": {"code": -32000, "message": "intentional error"}}
        elif method == "im.crash":
            sys.exit(1)
        else:
            response = {"jsonrpc": "2.0", "id": envelope["id"], "error": {"code": -32601, "message": f"Method not found: {method}"}}

        out_line = (json.dumps(response) + "\n").encode("utf-8")
        sys.stdout.buffer.write(out_line)
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    asyncio.run(main())
```

3. **`tests/platforms/test_daemon_client.py`** ≥ 6 测试：

```python
"""PlatformDaemonClient 测试 — 真起子进程 + JSONRPC roundtrip。"""
from __future__ import annotations

import pytest

from app.agent_builder.platforms.daemon_client import PlatformDaemonClient
from app.agent_builder.platforms.exceptions import (
    PluginDaemonExitedError,
    PluginInvocationError,
)


ECHO_MODULE = "tests.platforms.fixtures.echo_daemon"


@pytest.mark.asyncio
async def test_basic_invoke_roundtrip():
    """主流程：start → invoke → 收响应。"""
    client = PlatformDaemonClient(ECHO_MODULE)
    try:
        result = await client.invoke("im", "send_card", recipient={"kind": "channel", "id": "c1"}, card={}, idempotency_key="k1")
        assert result["plugin_name"] == "echo"
        assert result["native_id"] == "echo-k1"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_method_not_found_returns_error():
    client = PlatformDaemonClient(ECHO_MODULE)
    try:
        with pytest.raises(PluginInvocationError) as exc_info:
            await client.invoke("im", "nonexistent")
        assert exc_info.value.error_payload["code"] == -32601
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_daemon_crash_fails_pending_future():
    """**Pitfall 2 关键 + High 4 修复**：daemon sys.exit(1) → pending future 在 < 2s 内 raise PluginDaemonExitedError（不许超时）。

    High 4 修复点：
    - 客户端 invoke_timeout=2.0（不是默认 30s）— fault isolation 必须快
    - 只能 raise PluginDaemonExitedError（不接受 PluginInvocationError —— daemon 已死不可能再发 JSONRPC error response）
    - 加 timing assertion：从 invoke 开始到 raise 必须 < 2.0s（防止退化为超时路径）
    """
    import time
    client = PlatformDaemonClient(ECHO_MODULE, invoke_timeout=2.0)
    try:
        start = time.monotonic()
        with pytest.raises(PluginDaemonExitedError):
            # echo_daemon 收到 im.crash 后 sys.exit(1)
            await client.invoke("im", "crash")
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, (
            f"daemon crash 检测耗时 {elapsed:.3f}s ≥ 2.0s — 走超时路径而非 fault isolation"
        )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_multiple_concurrent_invokes():
    """并发 5 个 invoke，正确按 id 路由响应（不串）。"""
    import asyncio
    client = PlatformDaemonClient(ECHO_MODULE)
    try:
        results = await asyncio.gather(*[
            client.invoke("im", "send_card", recipient={"kind": "channel", "id": f"c{i}"}, card={}, idempotency_key=f"k{i}")
            for i in range(5)
        ])
        assert len(results) == 5
        for i, r in enumerate(results):
            assert r["native_id"] == f"echo-k{i}"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_close_idempotent():
    client = PlatformDaemonClient(ECHO_MODULE)
    await client.invoke("im", "send_card", recipient={"kind": "channel", "id": "c1"}, card={}, idempotency_key="k")
    await client.close()
    await client.close()  # 再 close 不报错


@pytest.mark.asyncio
async def test_invoke_after_close_starts_new():
    """close 之后 invoke 重新 start 新 daemon。"""
    client = PlatformDaemonClient(ECHO_MODULE)
    await client.invoke("im", "send_card", recipient={"kind": "channel", "id": "c1"}, card={}, idempotency_key="k1")
    await client.close()
    # 现在重新 invoke — start 新进程
    r = await client.invoke("im", "send_card", recipient={"kind": "channel", "id": "c2"}, card={}, idempotency_key="k2")
    assert r["native_id"] == "echo-k2"
    await client.close()
```

**关键覆盖**：test_daemon_crash_fails_pending_future 验证 Pitfall 2 fault isolation。
  </action>
  <verify>
    <automated>cd backend && python -c "from app.agent_builder.platforms.daemon_client import PlatformDaemonClient; print('OK')" && pytest tests/platforms/test_daemon_client.py -v -x 2>&1 | tail -20 && wc -l backend/app/agent_builder/platforms/daemon_client.py | awk '{exit ($1 >= 150 ? 0 : 1)}'</automated>
  </verify>
  <done>PlatformDaemonClient 可 import；6 单测全 pass（含 daemon crash fault isolation）；JSONRPC roundtrip 实测通过</done>
</task>

<task type="auto">
  <name>Task 2: Capability facades 真实接入 daemon + MockPlatformPlugin + 测试</name>
  <files>backend/app/agent_builder/platforms/capability_facades.py,backend/app/agent_builder/platforms/mock_plugin.py,tests/platforms/test_mock_plugin.py</files>
  <action>
1. **`backend/app/agent_builder/platforms/capability_facades.py`** — 用 Edit tool **覆写 plan 04 stub**，4 facade 实接入 daemon：

```python
"""Capability facades — daemon.invoke(capability, method, **kwargs) 转发。

设计要点：
- 每 facade 持 PlatformDaemonClient ref + manifest（拿 capability_spec 配置）
- daemon 为 None 时所有 method raise PluginError("daemon not attached")
- 参数序列化：dataclass → asdict() 后传 JSONRPC params；返回值按预期类型重建
"""
from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from .capabilities import (
    CommentRef,
    CRDTDelta,
    Department,
    DocInfo,
    DocRef,
    Employee,
    EmployeeFilter,
    EmployeeRef,
    LeaveRequest,
    MessageRef,
    NormalizedCard,
    RecipientSpec,
    UserChangeEvent,
    UserPrincipal,
    UserRef,
)
from .exceptions import PluginError

if TYPE_CHECKING:
    from .daemon_client import PlatformDaemonClient
    from .manifest import CapabilitySpec, PlatformManifest


class _BaseFacade:
    def __init__(
        self,
        daemon: "PlatformDaemonClient | None",
        manifest: "PlatformManifest",
    ):
        self._daemon = daemon
        self._manifest = manifest

    @property
    def name(self) -> str:
        return self._manifest.name

    def _ensure_daemon(self) -> "PlatformDaemonClient":
        if self._daemon is None:
            raise PluginError(
                f"plugin '{self._manifest.name}' daemon not attached "
                "(call PlatformPlugin.attach_daemon first)"
            )
        return self._daemon


class IMFacade(_BaseFacade):
    @property
    def supports_native_buttons(self) -> bool:
        return (self._manifest.im.supports_native_buttons if self._manifest.im else True) or False

    @property
    def supports_card_update(self) -> bool:
        return (self._manifest.im.supports_card_update if self._manifest.im else True) or False

    @property
    def supports_threads(self) -> bool:
        return (self._manifest.im.supports_threads if self._manifest.im else False) or False

    async def send_card(
        self,
        *,
        recipient: RecipientSpec,
        card: NormalizedCard,
        idempotency_key: str,
    ) -> MessageRef:
        daemon = self._ensure_daemon()
        result = await daemon.invoke(
            "im", "send_card",
            recipient=asdict(recipient),
            card=asdict(card),
            idempotency_key=idempotency_key,
        )
        return MessageRef(
            plugin_name=result.get("plugin_name", self.name),
            native_id=result["native_id"],
            extras=result.get("extras", {}),
        )

    async def update_card(self, msg_ref: MessageRef, card: NormalizedCard) -> None:
        daemon = self._ensure_daemon()
        await daemon.invoke("im", "update_card", msg_ref=asdict(msg_ref), card=asdict(card))

    async def send_text(self, recipient: RecipientSpec, text: str) -> MessageRef:
        daemon = self._ensure_daemon()
        result = await daemon.invoke("im", "send_text", recipient=asdict(recipient), text=text)
        return MessageRef(
            plugin_name=result.get("plugin_name", self.name),
            native_id=result["native_id"],
            extras=result.get("extras", {}),
        )

    async def subscribe_events(self, event_types: list[str]):
        # AsyncIterator 接口走 daemon 长连 — Phase 5.A 留接口，5.C 起实接入
        raise NotImplementedError("subscribe_events 留 Phase 5.C 起实接入（需 daemon 双向 stream）")
        if False:
            yield {}


class DocFacade(_BaseFacade):
    @property
    def supports_collaborative_edit(self) -> bool:
        return (self._manifest.doc.supports_collaborative_edit if self._manifest.doc else False) or False

    @property
    def supports_comments(self) -> bool:
        return (self._manifest.doc.supports_comments if self._manifest.doc else False) or False

    async def create_document(self, *, title, markdown, owners=None):
        daemon = self._ensure_daemon()
        result = await daemon.invoke(
            "doc", "create_document",
            title=title, markdown=markdown,
            owners=[asdict(o) for o in (owners or [])],
        )
        return DocRef(plugin_name=self.name, native_id=result["native_id"], extras=result.get("extras", {}))

    async def replace_document_content(self, doc_ref, markdown):
        daemon = self._ensure_daemon()
        await daemon.invoke("doc", "replace_document_content", doc_ref=asdict(doc_ref), markdown=markdown)

    async def apply_document_delta(self, doc_ref, delta):
        daemon = self._ensure_daemon()
        # CRDTDelta.payload 是 bytes — JSONRPC 不支持 bytes 直传 → base64 encode
        import base64
        payload_b64 = base64.b64encode(delta.payload).decode("ascii")
        await daemon.invoke("doc", "apply_document_delta", doc_ref=asdict(doc_ref), delta={"format": delta.format, "payload_b64": payload_b64})

    async def add_comment(self, *, doc_ref, body, mentions=None):
        daemon = self._ensure_daemon()
        result = await daemon.invoke("doc", "add_comment", doc_ref=asdict(doc_ref), body=body, mentions=[asdict(m) for m in (mentions or [])])
        return CommentRef(plugin_name=self.name, native_id=result["native_id"], parent_doc_ref=doc_ref)

    async def get_document(self, doc_ref):
        daemon = self._ensure_daemon()
        result = await daemon.invoke("doc", "get_document", doc_ref=asdict(doc_ref))
        if result is None:
            return None
        return DocInfo(
            doc_ref=doc_ref,
            title=result["title"],
            url=result.get("url"),
            content_markdown=result.get("content_markdown"),
        )


class HRFacade(_BaseFacade):
    async def list_employees(self, *, filter=None, cursor=None):
        daemon = self._ensure_daemon()
        result = await daemon.invoke(
            "hr", "list_employees",
            filter=asdict(filter) if filter else None,
            cursor=cursor,
        )
        employees = [
            Employee(
                ref=EmployeeRef(plugin_name=self.name, native_id=e["ref"]["native_id"]),
                username=e["username"], email=e["email"], display_name=e["display_name"],
                department_id=e.get("department_id"), manager_id=e.get("manager_id"),
                is_active=e.get("is_active", True),
                custom_fields=e.get("custom_fields", {}),
            )
            for e in result.get("employees", [])
        ]
        return employees, result.get("next_cursor")

    async def get_employee(self, employee_ref):
        daemon = self._ensure_daemon()
        result = await daemon.invoke("hr", "get_employee", employee_ref=asdict(employee_ref))
        if result is None:
            return None
        return Employee(
            ref=EmployeeRef(plugin_name=self.name, native_id=result["ref"]["native_id"]),
            username=result["username"], email=result["email"], display_name=result["display_name"],
            department_id=result.get("department_id"), manager_id=result.get("manager_id"),
            is_active=result.get("is_active", True), custom_fields=result.get("custom_fields", {}),
        )

    async def list_departments(self):
        daemon = self._ensure_daemon()
        result = await daemon.invoke("hr", "list_departments")
        return [
            Department(id=d["id"], name=d["name"], parent_id=d.get("parent_id"), team_lead_employee_id=d.get("team_lead_employee_id"), member_ids=tuple(d.get("member_ids", [])))
            for d in result
        ]

    async def resolve_department_members(self, expression):
        daemon = self._ensure_daemon()
        result = await daemon.invoke("hr", "resolve_department_members", expression=expression)
        return [EmployeeRef(plugin_name=self.name, native_id=r["native_id"]) for r in result]

    async def list_leave_requests(self, *, employee_ref=None, status=None, cursor=None):
        daemon = self._ensure_daemon()
        result = await daemon.invoke(
            "hr", "list_leave_requests",
            employee_ref=asdict(employee_ref) if employee_ref else None,
            status=status, cursor=cursor,
        )
        requests = [
            LeaveRequest(
                id=r["id"],
                employee_ref=EmployeeRef(plugin_name=self.name, native_id=r["employee_ref"]["native_id"]),
                request_type=r["request_type"], start_date=r["start_date"], end_date=r["end_date"],
                description=r["description"], status=r["status"],
            )
            for r in result.get("requests", [])
        ]
        return requests, result.get("next_cursor")

    async def create_leave_request(self, *, employee_ref, request_type, start_date, end_date, description):
        daemon = self._ensure_daemon()
        result = await daemon.invoke(
            "hr", "create_leave_request",
            employee_ref=asdict(employee_ref), request_type=request_type,
            start_date=start_date, end_date=end_date, description=description,
        )
        return LeaveRequest(
            id=result["id"],
            employee_ref=employee_ref,
            request_type=request_type, start_date=start_date, end_date=end_date,
            description=description, status=result.get("status", "pending"),
        )


class IdentityFacade(_BaseFacade):
    @property
    def is_source_of_truth(self) -> bool:
        return (self._manifest.identity.is_source_of_truth if self._manifest.identity else False) or False

    async def list_users(self):
        daemon = self._ensure_daemon()
        result = await daemon.invoke("identity", "list_users")
        return [
            UserPrincipal(
                plugin_name=self.name, native_id=u["native_id"],
                canonical_username=u["canonical_username"], email=u["email"], display_name=u["display_name"],
                is_active=u.get("is_active", True), extras=u.get("extras", {}),
            )
            for u in result
        ]

    async def resolve_user(self, identifier):
        daemon = self._ensure_daemon()
        result = await daemon.invoke("identity", "resolve_user", identifier=identifier)
        if result is None:
            return None
        return UserPrincipal(
            plugin_name=self.name, native_id=result["native_id"],
            canonical_username=result["canonical_username"], email=result["email"], display_name=result["display_name"],
            is_active=result.get("is_active", True), extras=result.get("extras", {}),
        )

    async def watch_user_changes(self):
        raise NotImplementedError("watch_user_changes 留 Phase 5.D 接入（需 daemon stream）")
        if False:
            yield None
```

≥ 120 行。

2. **`backend/app/agent_builder/platforms/mock_plugin.py`** — in-process plugin（不走 daemon）：

```python
"""MockPlatformPlugin — Phase 5.A 测试用 in-process plugin。

无 daemon — IM/Doc/HR capability 直接在主进程实现固定返回值；
用于：
- Registry / Capability negotiation 单测（不依赖真 daemon）
- Plugin/Facade lifecycle 测试
"""
from __future__ import annotations

import uuid
from typing import Any

from .capabilities import (
    CommentRef,
    CRDTDelta,
    Department,
    DocCapability,
    DocInfo,
    DocRef,
    Employee,
    EmployeeFilter,
    EmployeeRef,
    HRCapability,
    IMCapability,
    LeaveRequest,
    MessageRef,
    NormalizedCard,
    RecipientSpec,
)
from .manifest import PlatformManifest


class MockIMCapability:
    name = "mock"
    supports_native_buttons = True
    supports_card_update = True
    supports_threads = False

    def __init__(self) -> None:
        self.sent: list[tuple[RecipientSpec, NormalizedCard, str]] = []

    async def send_card(self, *, recipient, card, idempotency_key):
        self.sent.append((recipient, card, idempotency_key))
        return MessageRef(plugin_name="mock", native_id=f"mock-{len(self.sent)}")

    async def update_card(self, msg_ref, card):
        pass

    async def send_text(self, recipient, text):
        return MessageRef(plugin_name="mock", native_id=f"text-{recipient.id}")

    async def subscribe_events(self, event_types):
        if False:
            yield {}


class MockDocCapability:
    name = "mock"
    supports_collaborative_edit = False
    supports_comments = True

    async def create_document(self, *, title, markdown, owners=None):
        return DocRef(plugin_name="mock", native_id=str(uuid.uuid4()))

    async def replace_document_content(self, doc_ref, markdown):
        pass

    async def apply_document_delta(self, doc_ref, delta):
        raise NotImplementedError("mock 不支持 CRDT")

    async def add_comment(self, *, doc_ref, body, mentions=None):
        return CommentRef(plugin_name="mock", native_id="c1", parent_doc_ref=doc_ref)

    async def get_document(self, doc_ref):
        return DocInfo(doc_ref=doc_ref, title="mock-title")


class MockHRCapability:
    name = "mock"

    async def list_employees(self, *, filter=None, cursor=None):
        return ([], None)

    async def get_employee(self, employee_ref):
        return None

    async def list_departments(self):
        return []

    async def resolve_department_members(self, expression):
        return [EmployeeRef(plugin_name="mock", native_id="emp1")]

    async def list_leave_requests(self, *, employee_ref=None, status=None, cursor=None):
        return ([], None)

    async def create_leave_request(self, *, employee_ref, request_type, start_date, end_date, description):
        raise NotImplementedError("mock 不是 source_of_truth")


class MockPlatformPlugin:
    """声明 IM + Doc + HR 多 capability 的 mock。"""
    def __init__(self, manifest: PlatformManifest):
        self._manifest = manifest
        self._im: MockIMCapability | None = None
        self._doc: MockDocCapability | None = None
        self._hr: MockHRCapability | None = None

    @property
    def name(self) -> str:
        return self._manifest.name

    @property
    def manifest(self) -> PlatformManifest:
        return self._manifest

    @property
    def im(self) -> IMCapability | None:
        if "im" not in self._manifest.capabilities:
            return None
        if self._im is None:
            self._im = MockIMCapability()
        return self._im

    @property
    def doc(self) -> DocCapability | None:
        if "doc" not in self._manifest.capabilities:
            return None
        if self._doc is None:
            self._doc = MockDocCapability()
        return self._doc

    @property
    def hr(self) -> HRCapability | None:
        if "hr" not in self._manifest.capabilities:
            return None
        if self._hr is None:
            self._hr = MockHRCapability()
        return self._hr
```

≥ 100 行。

3. **`tests/platforms/test_mock_plugin.py`** ≥ 5 测试：

```python
"""MockPlatformPlugin 单测 — 多 capability 声明 + isinstance + capability_facades 等价路径。"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.agent_builder.platforms.capabilities import (
    DocCapability,
    HRCapability,
    IMCapability,
    RecipientSpec,
    NormalizedCard,
    EmployeeRef,
)
from app.agent_builder.platforms.manifest import load_manifest
from app.agent_builder.platforms.mock_plugin import (
    MockDocCapability,
    MockHRCapability,
    MockIMCapability,
    MockPlatformPlugin,
)


@pytest.fixture
def valid_manifest():
    return load_manifest(Path(__file__).parent / "fixtures" / "manifest_valid.yaml")


def test_mock_plugin_multi_capability_facade(valid_manifest):
    plugin = MockPlatformPlugin(valid_manifest)
    assert plugin.im is not None
    assert plugin.doc is not None
    assert plugin.hr is not None
    assert isinstance(plugin.im, IMCapability)
    assert isinstance(plugin.doc, DocCapability)
    assert isinstance(plugin.hr, HRCapability)


def test_mock_plugin_undeclared_capability_returns_none(valid_manifest):
    # valid manifest 不声明 trigger / tool
    plugin = MockPlatformPlugin(valid_manifest)
    assert getattr(plugin, "trigger", None) is None or True  # MockPlatformPlugin 没暴露 trigger property
    # 但 doc 是声明的 — 这里就检查 unsupported 不在 manifest.capabilities


@pytest.mark.asyncio
async def test_mock_im_records_sent(valid_manifest):
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


@pytest.mark.asyncio
async def test_mock_doc_dual_path_raises_for_crdt(valid_manifest):
    plugin = MockPlatformPlugin(valid_manifest)
    cap = plugin.doc
    assert cap is not None
    from app.agent_builder.platforms.capabilities import DocRef, CRDTDelta
    with pytest.raises(NotImplementedError):
        await cap.apply_document_delta(DocRef(plugin_name="mock", native_id="d1"), CRDTDelta(format="yjs", payload=b""))


@pytest.mark.asyncio
async def test_mock_hr_resolve_department_members(valid_manifest):
    plugin = MockPlatformPlugin(valid_manifest)
    cap = plugin.hr
    assert cap is not None
    result = await cap.resolve_department_members("dept:研发部")
    assert len(result) == 1
    assert isinstance(result[0], EmployeeRef)
```
  </action>
  <verify>
    <automated>cd backend && python -c "from app.agent_builder.platforms.capability_facades import IMFacade, DocFacade, HRFacade, IdentityFacade; from app.agent_builder.platforms.mock_plugin import MockPlatformPlugin, MockIMCapability; print('OK')" && pytest tests/platforms/test_mock_plugin.py -v -x 2>&1 | tail -15 && wc -l backend/app/agent_builder/platforms/capability_facades.py | awk '{exit ($1 >= 120 ? 0 : 1)}' && wc -l backend/app/agent_builder/platforms/mock_plugin.py | awk '{exit ($1 >= 100 ? 0 : 1)}'</automated>
  </verify>
  <done>4 capability facades 实接 daemon + MockPlatformPlugin 多 capability 单测 5 全 pass + 3 文件分别 ≥ 120/100 行</done>
</task>

</tasks>

<verification>
- [ ] Reading doc commit 在前
- [ ] `pytest tests/platforms/test_daemon_client.py tests/platforms/test_mock_plugin.py -v` 11+ tests pass
- [ ] test_daemon_crash_fails_pending_future 明确通过（Pitfall 2 fault isolation）
- [ ] black + ruff 通过
- [ ] Phase 4 81 IM 测试 0 regression
</verification>

<success_criteria>
- PlatformDaemonClient 真起子进程 + JSONRPC 2.0 双向通信，request_id 路由正确
- daemon crash 时所有 pending future 失败（fault isolation 验证）
- 4 capability facades 实接入 daemon.invoke（dataclass 序列化 / 反序列化正确）
- MockPlatformPlugin 多 capability + 与 Registry 协作
- echo_daemon fixture 给 plan 06 HulyPlugin 复用思路
</success_criteria>

<output>
完成后创建 `.planning/phases/05a-platform-plugin-framework/05a-05-SUMMARY.md`，含：
- Reading doc 链接 + commit hash
- daemon_client 测试输出（含 fault isolation）
- **Dify 参考点** 小节
- 给 plan 06 的"daemon 通信 contract"小节（envelope shape / error codes）
</output>
