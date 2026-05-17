---
phase: 05a-platform-plugin-framework
plan: 07
type: execute
wave: 5
depends_on: ["05", "06"]
files_modified:
  - docs/reading-dify-05a-07-huly-acid-test-2026-05-17.md
  - plugins/huly/__init__.py
  - plugins/huly/platform.yaml
  - plugins/huly/huly_plugin.py
  - tests/platforms_integration/conftest.py
  - tests/platforms_integration/mock_huly_server.py
  - tests/platforms_integration/test_huly_acid_test.py
  - tests/platforms_integration/test_fault_isolation.py
autonomous: true
requirements:
  - PLUG-FW-07
must_haves:
  truths:
    - "HulyPlugin daemon 子进程被真实 spawn（不是 mock JSONRPC client）"
    - "1 个 IMCapability.send_card 端到端：主进程 → JSONRPC stdio → daemon process → mock huly server → 返回 MessageRef 成功"
    - "Fault isolation：kill daemon child process → 主进程下次 invoke 立即 raise PluginDaemonExitedError < 2s（不超时 30s）"
    - "manifest plugin (huly) 经 Registry.get_capability(IMCapability) 取到 facade → facade.send_card → daemon.invoke 链路通"
  artifacts:
    - path: "plugins/huly/platform.yaml"
      provides: "Huly plugin manifest — 声明 IM/Doc/HR/Identity 4 capability + runtime entry"
      contains: "name: huly"
    - path: "plugins/huly/huly_plugin.py"
      provides: "HulyPlugin daemon entrypoint — JSONRPC over stdio main loop + im.send_card 真实实现（调 mock_huly_server）"
      exports: ["main"]
      min_lines: 80
    - path: "tests/platforms_integration/mock_huly_server.py"
      provides: "aiohttp stub server 模拟 Huly chunter API — /api/v1/chunter/messages POST 返回 {message_id}"
      min_lines: 40
    - path: "tests/platforms_integration/test_huly_acid_test.py"
      provides: "真 subprocess spawn + real JSONRPC WS roundtrip + 1 IMCapability.send_card 端到端成功"
      min_lines: 80
    - path: "tests/platforms_integration/test_fault_isolation.py"
      provides: "kill daemon child process → 下次 invoke 立即 raise PluginDaemonExitedError 测试（< 2s 不超时）"
      min_lines: 50
  key_links:
    - from: "tests/platforms_integration/test_huly_acid_test.py"
      to: "plugins/huly/huly_plugin.py"
      via: "subprocess spawn `python -u -m plugins.huly.huly_plugin` + 真 JSONRPC stdio roundtrip"
      pattern: "create_subprocess_exec.*huly_plugin"
    - from: "plugins/huly/huly_plugin.py"
      to: "tests/platforms_integration/mock_huly_server.py"
      via: "im.send_card 实现内部 aiohttp POST 到 HULY_ENDPOINT（env var 注入 mock server URL）"
      pattern: "HULY_ENDPOINT"
    - from: "tests/platforms_integration/test_fault_isolation.py"
      to: "backend/app/agent_builder/platforms/daemon_client.py"
      via: "daemon SIGKILL → _read_loop 检测 stdout 关闭 → 所有 pending future set_exception(PluginDaemonExitedError)"
      pattern: "PluginDaemonExitedError"
---

<objective>
**Phase 5.A 最强硬性要求落地（Blocker 1 修复）**：HulyPlugin stub acid test 真实跑通 — 不是"1 mock call 抽象通过"，是真起 Python daemon 子进程 + mock huly server 起本地端口 + JSONRPC over stdio roundtrip + fault isolation 验证。

Purpose: 用户 2026-05-17 三连质疑后最硬性的要求（CONTEXT.md `<decisions>` "HulyPlugin Acid Test 范围 + 验收硬性"）— 不再让"抽象只在纸面"发生。一旦此 plan 通过：5.B 沙箱 / 5.C Doc 接入 / 5.D HR 接入都是 fill-in-blanks，框架已被实测验证可工作。

Output: 1 reading doc + 3 plugin 源文件 + 4 集成测文件（conftest 已在 plan 01 创建，本 plan 追加 fixture）。
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
@backend/app/agent_builder/platforms/daemon_client.py
@backend/app/agent_builder/platforms/registry.py
@backend/app/agent_builder/platforms/capability_facades.py
@tests/platforms/fixtures/manifest_valid.yaml

<interfaces>
From plan 05 (PlatformDaemonClient):
- `PlatformDaemonClient(module_entry: str, env: dict | None, invoke_timeout: float).invoke(capability, method, **kwargs) -> Any`
- 已实现 fault isolation：daemon 退出 → _read_loop 关闭 → _pending future set_exception(PluginDaemonExitedError)
- `start()` / `close()` 生命周期；close 是 idempotent

From plan 05 (IMFacade):
- IMFacade.send_card(*, recipient: RecipientSpec, card: NormalizedCard, idempotency_key: str) → MessageRef
- 内部走 daemon.invoke("im", "send_card", recipient=asdict(recipient), card=asdict(card), idempotency_key=...)

From plan 04 (Registry):
- `PlatformPluginRegistry.discover(plugins_root)` 扫描 `plugins/*/platform.yaml`
- `PlatformPluginRegistry.get_plugin(workspace_id, plugin_name)` 懒加载 PlatformPlugin
- `PlatformPluginRegistry.get_capability(workspace_id, IMCapability, prefer='huly')` → facade

From RESEARCH.md Example 3 (HulyPlugin daemon entrypoint 范例):
- HULY_ENDPOINT env var
- METHODS dict 路由 method_name → async handler
- main loop: stdin readline → json.loads envelope → handler(params) → 写 stdout

From CONTEXT.md `<decisions>` "HulyPlugin Acid Test 范围 + 验收硬性":
- stub 深度：最小 1 capability call 真实跑通（im.send_card）
- 其他 3 capability (doc/hr/identity) 仅 facade 占位 NotImplementedError
- Mock huly server：Python aiohttp 本地 stub（不真接 Huly self-host）
- 验收硬性 DoD：
  1. 1 ainvoke 成功（端到端经过 JSONRPC stdio）
  2. Fault isolation：daemon crash 主进程不受影响 + 明确错误
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 0: Dify dify-plugin-daemon + Phase 4 mock provider 阅读文档（CLAUDE.md §2.7 硬性 gate）</name>
  <files>docs/reading-dify-05a-07-huly-acid-test-2026-05-17.md</files>
  <action>
**STOP — gate**。先 commit reading doc 才能写 acid test 代码。

读以下源文件：
1. `/Users/admin/ai/ref/dify/repo/api/services/plugin/plugin_service.py` 重点 daemon spawn 调度的部分（invoke / install 时如何起 daemon process）
2. `/Users/admin/ai/ref/dify/repo/api/core/plugin/entities/plugin_daemon.py` — Response envelope + error code 模式
3. 本仓 Phase 4 mock provider 模式：`backend/app/agent_builder/notification/providers/feishu.py` 看 Phase 4 怎么写 provider；以及其测试 `tests/test_im_provider_feishu.py` 看 mock server fixture 模式
4. dify-plugin-daemon README (https://github.com/langgenius/dify-plugin-daemon) — 仅看 README 不读 Go 源码（license 隔离）

写到 `docs/reading-dify-05a-07-huly-acid-test-2026-05-17.md`，5 节模板：

**5 借鉴点至少包含**：
1. **Dify daemon spawn 模式** — Dify Go daemon 独立进程；5.A Python subprocess + JSONRPC stdio 简化版（Plan 05 已实现）
2. **PluginDaemonInnerError code 设计** → 5.A acid test 验证 error envelope 携带 code（method not found = -32601）
3. **Phase 4 mock provider 测试模式**（aiohttp.web stub server + free_port fixture）→ 5.A mock_huly_server 直接复用此模式
4. **Dify install task subprocess 隔离** → 5.A fault isolation 验证：daemon SIGKILL 不影响主进程 webhook 等其他流程
5. **acid test "真起 subprocess" vs "mock client" 教训** — Pitfall 9：若只 mock `daemon.invoke` 则抽象仍在纸面（用户三连质疑的真因）

License attribution：Dify AGPL-3.0 vs 本项目 Apache-2.0；**不拷源代码**。≥ 60 行。
  </action>
  <verify>
    <automated>test -f docs/reading-dify-05a-07-huly-acid-test-2026-05-17.md && wc -l docs/reading-dify-05a-07-huly-acid-test-2026-05-17.md | awk '{exit ($1 >= 60 ? 0 : 1)}' && grep -q "AGPL\|attribution" docs/reading-dify-05a-07-huly-acid-test-2026-05-17.md && grep -q "可借鉴的设计模式" docs/reading-dify-05a-07-huly-acid-test-2026-05-17.md</automated>
  </verify>
  <done>Reading doc ≥ 60 行 + 5 借鉴点 + License attribution + 含"acid test 真起 subprocess vs mock client 教训"借鉴点 + commit 在前</done>
</task>

<task type="auto">
  <name>Task 1: plugins/huly/ 三件套（manifest + __init__ + daemon entrypoint）</name>
  <files>plugins/huly/__init__.py,plugins/huly/platform.yaml,plugins/huly/huly_plugin.py</files>
  <action>
Reading doc commit 已 ✓ 才允许写代码。

1. **`plugins/huly/__init__.py`** 空 + docstring：
```python
"""Huly platform plugin — Phase 5.A acid test stub。

仅实 1 个 IMCapability.send_card 端到端；其他 capability 返回 NotImplementedError。
真实接入 Huly chunter / document / hr 留 Phase 5.C / 5.D。
"""
```

2. **`plugins/huly/platform.yaml`** — manifest（直接复用 `tests/platforms/fixtures/manifest_valid.yaml` 的内容；这就是 acid test 用的 huly 声明）：

```yaml
name: huly
version: 1.0.0
description: "Huly platform stub (Phase 5.A acid test)"
license: EPL-2.0
agent_builder_version: ">=1.0"
runtime:
  type: python
  entry: plugins.huly.huly_plugin
  python_version: "3.11"
capabilities:
  - im
  - doc
  - hr
  - identity
config_schema:
  type: object
  required: [endpoint, auth_token]
  properties:
    endpoint:
      type: string
      format: uri
    auth_token:
      type: string
      format: password
im:
  supports_native_buttons: false
  supports_card_update: true
  supports_threads: true
doc:
  supports_collaborative_edit: true
  supports_comments: true
identity:
  is_source_of_truth: true
sandbox:
  cpu_limit: "1.0"
  memory_limit: "512Mi"
  network: ["huly.example.com:443"]
```

3. **`plugins/huly/huly_plugin.py`** — daemon entrypoint（按 RESEARCH.md Example 3，独立实现不抄 Dify）：

```python
"""HulyPlugin daemon entrypoint — JSONRPC over stdio。

子进程跑 `python -u -m plugins.huly.huly_plugin`：
- 读 stdin 行分隔 JSONRPC envelope
- 路由 method 到 handler
- 结果走 stdout（行分隔 JSON）

Phase 5.A 仅实现 im.send_card（调 mock huly server）；其他 capability raise NotImplementedError。
真实接入 Huly chunter / document / hr 留 Phase 5.C / 5.D。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

import aiohttp


# HULY_ENDPOINT 由主进程通过 env var 注入（test fixture 注入 mock server URL）
HULY_ENDPOINT = os.environ.get("HULY_ENDPOINT", "http://localhost:18765")


async def im_send_card(params: dict) -> dict:
    """IMCapability.send_card 真实接入 mock huly chunter API。

    params 来自主进程 IMFacade.send_card → asdict(recipient) + asdict(card) + idempotency_key
    """
    recipient = params["recipient"]
    card = params["card"]
    idempotency_key = params["idempotency_key"]
    body = {
        "channel": recipient["id"],
        "message": f"## {card['title']}\n\n{card['body_markdown']}",
        "idempotency_key": idempotency_key,
    }
    timeout = aiohttp.ClientTimeout(total=5.0)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            f"{HULY_ENDPOINT}/api/v1/chunter/messages",
            json=body,
        ) as resp:
            data = await resp.json()
    return {
        "plugin_name": "huly",
        "native_id": data["message_id"],
        "extras": {"channel": recipient["id"]},
    }


async def _not_implemented(params: dict) -> dict:
    """其他 capability 占位 — Phase 5.C / 5.D 实接入。"""
    raise NotImplementedError(
        "HulyPlugin Phase 5.A 仅实现 im.send_card；其他 method 留 Phase 5.C / 5.D"
    )


METHODS = {
    "im.send_card": im_send_card,
    # 其他 capability 占位 — 显式 NotImplementedError 比 method not found 更友好
    "im.update_card": _not_implemented,
    "im.send_text": _not_implemented,
    "doc.create_document": _not_implemented,
    "doc.apply_document_delta": _not_implemented,
    "hr.list_employees": _not_implemented,
    "hr.resolve_department_members": _not_implemented,
    "identity.list_users": _not_implemented,
}


async def _process_envelope(envelope: dict) -> dict:
    method_name = envelope.get("method", "")
    handler = METHODS.get(method_name)
    rid = envelope.get("id")
    if handler is None:
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "error": {
                "code": -32601,
                "message": f"Method not found: {method_name}",
            },
        }
    try:
        result = await handler(envelope.get("params", {}))
        return {"jsonrpc": "2.0", "id": rid, "result": result}
    except NotImplementedError as e:
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "error": {"code": -32603, "message": str(e)},
        }
    except Exception as e:
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "error": {"code": -32000, "message": f"Internal error: {e}"},
        }


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
        response = await _process_envelope(envelope)
        out_line = (json.dumps(response) + "\n").encode("utf-8")
        sys.stdout.buffer.write(out_line)
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    asyncio.run(main())
```

≥ 80 行。代码风格：black + ruff 通过。

**重要**：huly_plugin.py 是**独立创作**，**不允许**拷贝 Dify dify-plugin-daemon Go 源码。RESEARCH.md Example 3 仅示意 — 本任务必须重写 JSONRPC dispatch / 错误处理 / aiohttp 调用代码（CLAUDE.md §2.7 反模式校验）。
  </action>
  <verify>
    <automated>test -f plugins/huly/platform.yaml && test -f plugins/huly/huly_plugin.py && wc -l plugins/huly/huly_plugin.py | awk '{exit ($1 >= 80 ? 0 : 1)}' && cd backend && python -c "import yaml; m = yaml.safe_load(open('../plugins/huly/platform.yaml')); assert m['name'] == 'huly' and 'im' in m['capabilities']; print('manifest OK')" && python -c "import plugins.huly.huly_plugin as mod; assert hasattr(mod, 'main') and callable(mod.main); print('entry callable')"</automated>
  </verify>
  <done>3 文件存在；manifest YAML 可被 PlatformManifest schema 校验；huly_plugin.py 可被 import + main 是 callable async function；≥ 80 行</done>
</task>

<task type="auto">
  <name>Task 2: mock_huly_server + acid test 真子进程 spawn + 1 send_card 端到端</name>
  <files>tests/platforms_integration/conftest.py,tests/platforms_integration/mock_huly_server.py,tests/platforms_integration/test_huly_acid_test.py</files>
  <action>
1. **追加 fixture 到 `tests/platforms_integration/conftest.py`**（plan 01 已创建，本 task 用 Edit append）：

```python


# ── Phase 5.A plan 07 huly acid test fixtures ──────────────────────────────


@pytest_asyncio.fixture
async def mock_huly_server(free_port):
    """启动 aiohttp mock huly server，yield URL，结束时 cleanup。"""
    from tests.platforms_integration.mock_huly_server import build_mock_app
    from aiohttp import web

    app = build_mock_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", free_port)
    await site.start()
    url = f"http://127.0.0.1:{free_port}"
    try:
        yield url
    finally:
        await runner.cleanup()
```

2. **`tests/platforms_integration/mock_huly_server.py`** — aiohttp stub：

```python
"""Mock Huly chunter API — Phase 5.A acid test。

监听本地端口模拟 Huly /api/v1/chunter/messages POST：
- 接受 {channel, message, idempotency_key} body
- 返回 {message_id: f"huly-msg-{uuid4()}"}
- 不真接 Huly self-host（CONTEXT.md decision）
"""
from __future__ import annotations

import uuid

from aiohttp import web


async def chunter_messages_handler(request: web.Request) -> web.Response:
    body = await request.json()
    if "channel" not in body or "message" not in body:
        return web.json_response(
            {"error": "missing channel or message"}, status=400
        )
    return web.json_response(
        {
            "message_id": f"huly-msg-{uuid.uuid4().hex[:8]}",
            "channel": body["channel"],
            "echoed_message_preview": body["message"][:50],
        }
    )


def build_mock_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/api/v1/chunter/messages", chunter_messages_handler)
    return app
```

≥ 40 行。

3. **`tests/platforms_integration/test_huly_acid_test.py`** — 真子进程 spawn + 1 send_card 端到端：

```python
"""Phase 5.A HulyPlugin acid test — 真起 daemon 子进程 + JSONRPC stdio roundtrip。

**用户硬性 DoD #1**：1 ainvoke 成功（端到端经过 JSONRPC stdio）。
不接受任何 mock `daemon.invoke` 的偷懒（Pitfall 9 / 用户三连质疑场景）。
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from app.agent_builder.platforms.capabilities.im import (
    IMCapability,
    NormalizedCard,
    RecipientSpec,
)
from app.agent_builder.platforms.daemon_client import PlatformDaemonClient
from app.agent_builder.platforms.manifest import load_manifest
from app.agent_builder.platforms.plugin import PlatformPlugin
from app.agent_builder.platforms.capability_facades import IMFacade


HULY_MODULE = "plugins.huly.huly_plugin"


@pytest.mark.asyncio
async def test_huly_plugin_real_subprocess_send_card_end_to_end(
    mock_huly_server,
):
    """**Phase 5.A 最强硬性要求落地**：

    1. 真起 plugins.huly.huly_plugin 子进程（不 mock daemon_client.invoke）
    2. 主进程通过 JSONRPC stdio 发 im.send_card request
    3. daemon 内 aiohttp 调 mock_huly_server /api/v1/chunter/messages
    4. mock server 返回 {message_id}
    5. daemon 转 JSONRPC response 回 stdout
    6. 主进程 IMFacade.send_card 拿到 MessageRef（含 native_id 是 huly-msg-* 格式）

    验证标准：
    - 测试运行时间 > 200ms（说明真起 subprocess，不是同进程 mock）
    - MessageRef.plugin_name == "huly"
    - MessageRef.native_id 以 "huly-msg-" 开头（mock server 生成格式）
    """
    import time
    start = time.monotonic()

    # 注入 mock huly server URL 到 daemon env
    daemon = PlatformDaemonClient(
        module_entry=HULY_MODULE,
        env={"HULY_ENDPOINT": mock_huly_server},
        invoke_timeout=5.0,
    )
    # 加载真 manifest
    manifest = load_manifest(Path(__file__).parent.parent / "platforms" / "fixtures" / "manifest_valid.yaml")
    plugin = PlatformPlugin(manifest=manifest, daemon=daemon)

    try:
        # IMFacade.send_card → daemon.invoke("im", "send_card", ...) → 真子进程
        im_cap: IMCapability = plugin.im  # type: ignore[assignment]
        assert im_cap is not None
        # 显式构造 IMFacade（plugin.im 已经返回 IMFacade per plan 05）
        assert isinstance(im_cap, IMFacade), f"plugin.im 应当返回 IMFacade，实际 {type(im_cap)}"

        msg_ref = await im_cap.send_card(
            recipient=RecipientSpec(kind="channel", id="channel-acid-test"),
            card=NormalizedCard(
                title="Phase 5.A Acid Test",
                body_markdown="HulyPlugin stub end-to-end roundtrip",
                actions=[],
            ),
            idempotency_key="acid-test-key-001",
        )

        # 关键断言：MessageRef 内容来自 mock huly server
        assert msg_ref.plugin_name == "huly", msg_ref
        assert msg_ref.native_id.startswith("huly-msg-"), msg_ref
        assert msg_ref.extras.get("channel") == "channel-acid-test"
    finally:
        await daemon.close()

    elapsed = time.monotonic() - start
    # Pitfall 9 防护：真起 subprocess 必然耗时 > 200ms；快于此说明被 mock 了
    assert elapsed > 0.2, (
        f"acid test 仅 {elapsed:.3f}s — 远低于 subprocess spawn 成本，"
        "说明根本没真起 daemon 进程（Pitfall 9 / 用户三连质疑场景）"
    )


@pytest.mark.asyncio
async def test_huly_plugin_method_not_implemented_returns_error(
    mock_huly_server,
):
    """其他 capability 调用返回明确 -32603 NotImplementedError（不是 -32601 method not found）。"""
    from app.agent_builder.platforms.exceptions import PluginInvocationError

    daemon = PlatformDaemonClient(
        module_entry=HULY_MODULE,
        env={"HULY_ENDPOINT": mock_huly_server},
        invoke_timeout=5.0,
    )
    try:
        with pytest.raises(PluginInvocationError) as exc_info:
            await daemon.invoke("doc", "create_document", title="x", markdown="y", owners=[])
        # 验证 error 是 NotImplementedError（-32603），不是 method not found（-32601）
        assert exc_info.value.error_payload.get("code") == -32603
        assert "Phase 5.C" in exc_info.value.error_payload.get("message", "") or "NotImplemented" in str(exc_info.value)
    finally:
        await daemon.close()


@pytest.mark.asyncio
async def test_huly_plugin_via_registry_get_capability(
    mock_huly_server,
    monkeypatch,
):
    """**端到端集成**：Registry.discover → get_capability(IMCapability, prefer='huly') → send_card 真跑通。

    验证 capability_routing 完整链路：manifest discover → PlatformPlugin → IMFacade → daemon.invoke → real subprocess
    """
    import os
    import tempfile
    import shutil
    from app.agent_builder.platforms.registry import PlatformPluginRegistry

    # 准备临时 plugins/ 目录，复制 huly fixture
    with tempfile.TemporaryDirectory() as tmp:
        plugin_dir = Path(tmp) / "plugins" / "huly"
        plugin_dir.mkdir(parents=True)
        fixture_yaml = Path(__file__).parent.parent / "platforms" / "fixtures" / "manifest_valid.yaml"
        shutil.copy(fixture_yaml, plugin_dir / "platform.yaml")

        PlatformPluginRegistry.clear()
        try:
            PlatformPluginRegistry.discover(Path(tmp) / "plugins")

            ws = uuid.uuid4()
            plugin = await PlatformPluginRegistry.get_plugin(ws, "huly")
            assert plugin is not None

            # 手动 attach daemon（plan 05 留接口；plan 07 acid test 显式注入 env）
            daemon = PlatformDaemonClient(
                module_entry=HULY_MODULE,
                env={"HULY_ENDPOINT": mock_huly_server},
                invoke_timeout=5.0,
            )
            plugin.attach_daemon(daemon)

            cap = await PlatformPluginRegistry.get_capability(ws, IMCapability, prefer="huly")
            assert cap is not None
            assert cap.name == "huly"

            msg_ref = await cap.send_card(
                recipient=RecipientSpec(kind="channel", id="registry-acid-channel"),
                card=NormalizedCard(title="Registry Path", body_markdown="end-to-end", actions=[]),
                idempotency_key="registry-key-1",
            )
            assert msg_ref.plugin_name == "huly"
            assert msg_ref.native_id.startswith("huly-msg-")

            await daemon.close()
        finally:
            PlatformPluginRegistry.clear()
```

**关键覆盖**：
- 真 subprocess spawn（timing > 200ms 防护 Pitfall 9）
- 1 send_card 端到端 mock server roundtrip
- 其他 method NotImplementedError 路径
- Registry → IMFacade → daemon → subprocess 完整链路
  </action>
  <verify>
    <automated>cd backend && pytest tests/platforms_integration/test_huly_acid_test.py -v -x 2>&1 | tail -25 && test -f tests/platforms_integration/mock_huly_server.py && wc -l tests/platforms_integration/mock_huly_server.py | awk '{exit ($1 >= 40 ? 0 : 1)}' && wc -l tests/platforms_integration/test_huly_acid_test.py | awk '{exit ($1 >= 80 ? 0 : 1)}'</automated>
  </verify>
  <done>3 集成测全 pass；test_huly_plugin_real_subprocess_send_card_end_to_end 耗时 > 200ms 确认真 subprocess；MessageRef 内容来自 mock huly server；Registry → IMFacade → daemon → subprocess 链路通；NotImplementedError 路径明确 -32603 error code</done>
</task>

<task type="auto">
  <name>Task 3: Fault isolation test — daemon SIGKILL → 下次 invoke 立即 raise < 2s</name>
  <files>tests/platforms_integration/test_fault_isolation.py</files>
  <action>
**用户硬性 DoD #2**：daemon process 崩溃，主进程不受影响 + capability call 返回明确错误。

写 `tests/platforms_integration/test_fault_isolation.py`：

```python
"""Phase 5.A HulyPlugin fault isolation test。

**用户硬性 DoD #2**：daemon 子进程被 kill → 主进程下次 invoke 必须：
1. 立即 raise PluginDaemonExitedError（不是 PluginInvocationError）
2. 耗时 < 2s（不能走 invoke_timeout=30s 路径，否则等于 fault isolation 失败）
3. 主进程其他流程不受影响（webhook / DB 等 — 由 process isolation 天然保证，本测仅验证 invoke 路径）
"""
from __future__ import annotations

import asyncio
import os
import signal
import time

import pytest

from app.agent_builder.platforms.daemon_client import PlatformDaemonClient
from app.agent_builder.platforms.exceptions import (
    PluginDaemonExitedError,
    PluginInvocationError,
)


HULY_MODULE = "plugins.huly.huly_plugin"


@pytest.mark.asyncio
async def test_kill_daemon_then_invoke_raises_immediately(mock_huly_server):
    """SIGKILL daemon 子进程 → 主进程下次 invoke 在 < 2s 内 raise PluginDaemonExitedError。

    验证步骤：
    1. start daemon + 跑 1 个成功 invoke 验证 daemon 活
    2. os.kill(daemon._proc.pid, SIGKILL) 强杀子进程
    3. 等待 daemon process 被 reap（~50ms）
    4. 下次 invoke → 必须 raise PluginDaemonExitedError 且耗时 < 2s
    """
    daemon = PlatformDaemonClient(
        module_entry=HULY_MODULE,
        env={"HULY_ENDPOINT": mock_huly_server},
        invoke_timeout=2.0,  # 低 timeout 确保 fault isolation 走 daemon-exit 路径而非 timeout 路径
    )

    try:
        # Step 1: 验证 daemon 活
        result = await daemon.invoke(
            "im", "send_card",
            recipient={"kind": "channel", "id": "warmup"},
            card={"title": "warmup", "body_markdown": "x", "actions": []},
            idempotency_key="warmup-key",
        )
        assert result["plugin_name"] == "huly"
        assert daemon._proc is not None
        daemon_pid = daemon._proc.pid

        # Step 2: SIGKILL daemon 子进程
        os.kill(daemon_pid, signal.SIGKILL)

        # Step 3: 等待 daemon process 被 reap（_read_loop 检测 stdout EOF）
        # 短 sleep 让 asyncio reactor 处理 SIGCHLD + read_loop 关闭
        await asyncio.sleep(0.2)

        # Step 4: 下次 invoke 必须 raise PluginDaemonExitedError 且耗时 < 2s
        start = time.monotonic()
        with pytest.raises(PluginDaemonExitedError):
            await daemon.invoke(
                "im", "send_card",
                recipient={"kind": "channel", "id": "post-kill"},
                card={"title": "after kill", "body_markdown": "x", "actions": []},
                idempotency_key="post-kill-key",
            )
        elapsed = time.monotonic() - start

        # 关键断言：fault isolation 必须快
        assert elapsed < 2.0, (
            f"daemon kill 后 invoke 耗时 {elapsed:.3f}s ≥ 2.0s — "
            "走 timeout 路径而非 fault isolation（用户硬性 DoD #2 失败）"
        )
    finally:
        # close 是 idempotent（plan 05 已保证）
        await daemon.close()


@pytest.mark.asyncio
async def test_daemon_crash_does_not_hang_main_process(mock_huly_server):
    """daemon crash 后主进程能正常 close 并起新 daemon 实例（不死锁）。"""
    daemon = PlatformDaemonClient(
        module_entry=HULY_MODULE,
        env={"HULY_ENDPOINT": mock_huly_server},
        invoke_timeout=2.0,
    )
    try:
        # 起 daemon
        await daemon.invoke(
            "im", "send_card",
            recipient={"kind": "channel", "id": "first"},
            card={"title": "first", "body_markdown": "x", "actions": []},
            idempotency_key="first-key",
        )
        os.kill(daemon._proc.pid, signal.SIGKILL)
        await asyncio.sleep(0.2)
    finally:
        # close 不应 hang（即使 daemon 已死）
        start = time.monotonic()
        await daemon.close()
        elapsed = time.monotonic() - start
        assert elapsed < 6.0, f"close 耗时 {elapsed:.3f}s — 应 < 6s（terminate 5s timeout + reap）"

    # 起一个新 daemon — 主进程不受前次崩溃影响
    daemon2 = PlatformDaemonClient(
        module_entry=HULY_MODULE,
        env={"HULY_ENDPOINT": mock_huly_server},
        invoke_timeout=5.0,
    )
    try:
        result = await daemon2.invoke(
            "im", "send_card",
            recipient={"kind": "channel", "id": "post-crash-new-daemon"},
            card={"title": "recovery", "body_markdown": "x", "actions": []},
            idempotency_key="recovery-key",
        )
        assert result["plugin_name"] == "huly"
    finally:
        await daemon2.close()
```

≥ 50 行。

**关键覆盖**：
- SIGKILL daemon → 主进程下次 invoke < 2s raise PluginDaemonExitedError
- close 不死锁（即使 daemon 已死）
- 主进程能起新 daemon 继续工作（fault 局部化）
  </action>
  <verify>
    <automated>cd backend && pytest tests/platforms_integration/test_fault_isolation.py -v -x 2>&1 | tail -20 && wc -l tests/platforms_integration/test_fault_isolation.py | awk '{exit ($1 >= 50 ? 0 : 1)}'</automated>
  </verify>
  <done>2 fault isolation 测试 pass；test_kill_daemon_then_invoke_raises_immediately 计时断言 < 2s 通过；test_daemon_crash_does_not_hang_main_process 验证新 daemon 起得来</done>
</task>

</tasks>

<verification>
- [ ] Reading doc commit hash 早于 task 1-3 commit hash（CLAUDE.md §2.7 gate）
- [ ] `pytest tests/platforms_integration/test_huly_acid_test.py -v` 3 tests pass
- [ ] `pytest tests/platforms_integration/test_fault_isolation.py -v` 2 tests pass
- [ ] test_huly_plugin_real_subprocess_send_card_end_to_end 耗时 > 200ms（真 subprocess 防护）
- [ ] test_kill_daemon_then_invoke_raises_immediately 耗时 < 2s（fault isolation 防护）
- [ ] `python -c "import plugins.huly.huly_plugin"` 可 import
- [ ] black + ruff 通过
- [ ] Phase 4 既有测试 + Plan 06 LegacyAdapter 测试 0 regression：`pytest tests/test_im_provider_*.py tests/platforms/ -v` 全部 PASS
</verification>

<success_criteria>
**用户 2026-05-17 三连质疑后最硬性的 5 验收 DoD（CONTEXT.md `<decisions>` "HulyPlugin Acid Test 范围 + 验收硬性"）全部落地**：

1. [x] HulyPlugin stub 真实运行：1 ainvoke 成功（端到端经过 JSONRPC stdio）— test_huly_plugin_real_subprocess_send_card_end_to_end
2. [x] Fault isolation 验证：daemon process 崩溃，主进程不受影响 + capability call 返回明确错误 — test_kill_daemon_then_invoke_raises_immediately + test_daemon_crash_does_not_hang_main_process
3. [x] LegacyIMProviderAdapter 让 Phase 4 6 家 provider 通过新接口被调用，所有 Phase 4 测试 0 regression — 由 plan 06 保证（本 plan verify 段含 regression check）
4. [x] 6 Capability Protocols 文件存在 + 单元测试覆盖 ≥ 80% — 由 plan 02 + plan 03 保证（plan 03 verify 含 --cov-fail-under=80）
5. [x] PlatformPluginRegistry per-workspace 隔离测试通过 — 由 plan 04 保证（test_two_workspaces_isolated）

**本 plan 独有贡献**：DoD #1 + DoD #2 实测（真 subprocess + SIGKILL fault isolation 双重验证）— 让"抽象只在纸面"永不重演。
</success_criteria>

<output>
完成后创建 `.planning/phases/05a-platform-plugin-framework/05a-07-SUMMARY.md`，至少含：
- Reading doc 链接 + commit hash
- 5 集成测试输出（pass 数 + 耗时数字截图）
- **关键计时数字**：
  - acid test send_card 耗时（必须 > 200ms 确认真 subprocess）
  - fault isolation kill→raise 耗时（必须 < 2s 确认非 timeout 路径）
- **Dify 参考点** 小节：5 借鉴点指回 reading doc
- **DoD 5 项逐条勾选**（指回测试函数名 + commit hash）
- **整 Phase 5.A 最终验收报告**：所有 7 plan 串联表（plan → DoD 映射 → 通过状态）
</output>
