"""Phase 5.A HulyPlugin acid test — 真起 daemon 子进程 + JSONRPC stdio roundtrip。

**用户硬性 DoD #1**（CONTEXT.md §HulyPlugin Acid Test 验收硬性）：
- 1 ainvoke 成功（端到端经过 JSONRPC stdio）
- 不接受任何 mock ``daemon.invoke`` 的偷懒（Pitfall 9 / 用户三连质疑场景）

测试链路（4 段串联）：
1. mock_huly_server fixture 起 aiohttp stub 监听本地端口
2. PlatformDaemonClient 真起 ``python -u -m plugins.huly.huly_plugin`` 子进程
   （env HULY_ENDPOINT 指向 mock server；cwd 指向项目根让 plugin module 可见）
3. 主进程通过 JSONRPC stdio 发 im.send_card → daemon 真 aiohttp POST mock server
4. mock server 返回 ``{message_id: huly-msg-...}`` → daemon JSONRPC response → 主进程拿 MessageRef

防 mock 客户端退化的关键防御（Pitfall 9）：
- ``elapsed > 0.2`` (200ms) timing assert — 真 subprocess spawn + Python 启动 + JSONRPC roundtrip
  累计 > 200ms；若 < 200ms 说明根本没起子进程，测试自动 fail
"""

from __future__ import annotations

import shutil
import tempfile
import time
import uuid
from pathlib import Path

import pytest

from app.agent_builder.platforms.capabilities.im import (
    IMCapability,
    NormalizedCard,
    RecipientSpec,
)
from app.agent_builder.platforms.capability_facades import IMFacade
from app.agent_builder.platforms.daemon_client import PlatformDaemonClient
from app.agent_builder.platforms.exceptions import PluginInvocationError
from app.agent_builder.platforms.manifest import load_manifest
from app.agent_builder.platforms.plugin import PlatformPlugin
from app.agent_builder.platforms.registry import PlatformPluginRegistry

HULY_MODULE = "plugins.huly.huly_plugin"


# ── Test 1: 真子进程 + JSONRPC roundtrip + 1 IMCapability.send_card 端到端 ─────


@pytest.mark.asyncio
async def test_huly_plugin_real_subprocess_send_card_end_to_end(
    mock_huly_server: str,
    project_root: str,
) -> None:
    """**Phase 5.A 最强硬性要求落地**（用户 2026-05-17 三连质疑后定为不可妥协）：

    1. 真起 ``plugins.huly.huly_plugin`` 子进程（不 mock daemon_client.invoke）
    2. 主进程通过 JSONRPC stdio 发 im.send_card request
    3. daemon 内 aiohttp 调 ``mock_huly_server/api/v1/chunter/messages``
    4. mock server 返回 ``{message_id: huly-msg-<hex>}``
    5. daemon 转 JSONRPC response 回 stdout
    6. 主进程 IMFacade.send_card 拿到 MessageRef（含 native_id 是 huly-msg-* 格式）

    验证标准（断言全部必须通过）：
    - 测试运行时间 ``elapsed > 0.2s`` — 真起 subprocess 防护（Pitfall 9）
    - MessageRef.plugin_name == "huly"
    - MessageRef.native_id 以 ``"huly-msg-"`` 开头（mock server 生成格式）
    - MessageRef.extras["channel"] == 发送时指定的 channel id
    """
    start = time.monotonic()

    # 注入 mock huly server URL 到 daemon env
    daemon = PlatformDaemonClient(
        module_entry=HULY_MODULE,
        env={"HULY_ENDPOINT": mock_huly_server},
        invoke_timeout=5.0,
        cwd=project_root,
    )
    # 加载真 manifest
    manifest_path = (
        Path(__file__).resolve().parents[1]
        / "platforms"
        / "fixtures"
        / "manifest_valid.yaml"
    )
    manifest = load_manifest(manifest_path)
    plugin = PlatformPlugin(manifest=manifest, daemon=daemon)

    try:
        # IMFacade.send_card → daemon.invoke("im", "send_card", ...) → 真子进程
        im_cap: IMCapability | None = plugin.im
        assert (
            im_cap is not None
        ), "huly manifest 声明 'im' capability，plugin.im 不应为 None"
        # plugin.im 已经返回 IMFacade（Plan 04/05 真接入完成）
        assert isinstance(
            im_cap, IMFacade
        ), f"plugin.im 应当返回 IMFacade，实际 {type(im_cap)}"

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
        assert (
            msg_ref.plugin_name == "huly"
        ), f"plugin_name 期望 'huly'，实际 {msg_ref.plugin_name}"
        assert msg_ref.native_id.startswith("huly-msg-"), (
            f"native_id 应当以 'huly-msg-' 开头（mock server 生成格式），"
            f"实际 {msg_ref.native_id}"
        )
        assert msg_ref.extras.get("channel") == "channel-acid-test"
    finally:
        await daemon.close()

    elapsed = time.monotonic() - start
    # Pitfall 9 防护：真起 subprocess 必然耗时 > 200ms；
    # 若 < 200ms 说明被 mock 了，acid test 已退化（用户三连质疑场景）
    assert elapsed > 0.2, (
        f"acid test 仅 {elapsed:.3f}s — 远低于 subprocess spawn 成本，"
        "说明根本没真起 daemon 进程（Pitfall 9 / 用户三连质疑场景）"
    )


# ── Test 2: NotImplemented 路径（其他 capability method 走 -32603 error） ─────


@pytest.mark.asyncio
async def test_huly_plugin_method_not_implemented_returns_error(
    mock_huly_server: str,
    project_root: str,
) -> None:
    """其他 capability 调用返回明确 -32603 NotImplementedError（不是 -32601 method not found）。

    区分两种错误：
    - -32601 (Method not found): method 名根本不在 METHODS dict（如 typo）
    - -32603 (Internal error / NotImplementedError): method 名在 METHODS dict
      但 handler 抛 NotImplementedError（"Phase 5.C/5.D 实接入"）

    本测试调 ``doc.create_document``（METHODS dict 中存在但走 _not_implemented），
    应当返回 -32603 而非 -32601。
    """
    daemon = PlatformDaemonClient(
        module_entry=HULY_MODULE,
        env={"HULY_ENDPOINT": mock_huly_server},
        invoke_timeout=5.0,
        cwd=project_root,
    )
    try:
        with pytest.raises(PluginInvocationError) as exc_info:
            await daemon.invoke(
                "doc",
                "create_document",
                title="acid-test-doc",
                markdown="placeholder body",
                owners=[],
            )
        # 关键断言：error code == -32603 NotImplementedError 路径
        error_code = exc_info.value.error_payload.get("code")
        assert error_code == -32603, (
            f"doc.create_document 应当走 NotImplementedError 路径（-32603），"
            f"实际 code={error_code}, payload={exc_info.value.error_payload}"
        )
        # message 应该提到 Phase 5.C 或 NotImplemented
        msg = exc_info.value.error_payload.get("message", "")
        assert (
            "Phase 5.C" in msg or "Phase 5.D" in msg or "NotImplemented" in msg
        ), f"error message 应含 'Phase 5.C/5.D' 或 'NotImplemented'，实际 {msg!r}"
    finally:
        await daemon.close()


# ── Test 3: 通过 Registry 完整链路 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_huly_plugin_via_registry_get_capability(
    mock_huly_server: str,
    project_root: str,
) -> None:
    """**端到端集成**：Registry.discover → get_capability(IMCapability, prefer='huly') → send_card 真跑通。

    验证 capability_routing 完整链路：
    manifest discover → PlatformPlugin → IMFacade → daemon.invoke → real subprocess → mock server

    实施细节：
    - 用 tempdir 复制 huly manifest 隔离测试（不污染全局 plugins/ 目录）
    - PlatformPluginRegistry.clear() 测试前后清空保隔离
    - 显式 attach_daemon 注入 PlatformDaemonClient（Plan 05 留接口；
      Plan 07 acid test 显式注入 env + cwd）
    """
    # 准备临时 plugins/ 目录，复制 huly fixture
    with tempfile.TemporaryDirectory() as tmp:
        plugin_dir = Path(tmp) / "plugins" / "huly"
        plugin_dir.mkdir(parents=True)
        fixture_yaml = (
            Path(__file__).resolve().parents[1]
            / "platforms"
            / "fixtures"
            / "manifest_valid.yaml"
        )
        shutil.copy(fixture_yaml, plugin_dir / "platform.yaml")

        PlatformPluginRegistry.clear()
        try:
            PlatformPluginRegistry.discover(Path(tmp) / "plugins")

            ws = uuid.uuid4()
            plugin = await PlatformPluginRegistry.get_plugin(ws, "huly")
            assert plugin is not None, "Registry 应找到 huly plugin"

            # 手动 attach daemon（Plan 04/05 留接口；Plan 07 acid test 显式注入 env + cwd）
            daemon = PlatformDaemonClient(
                module_entry=HULY_MODULE,
                env={"HULY_ENDPOINT": mock_huly_server},
                invoke_timeout=5.0,
                cwd=project_root,
            )
            plugin.attach_daemon(daemon)

            cap = await PlatformPluginRegistry.get_capability(
                ws, IMCapability, prefer="huly"
            )
            assert cap is not None, "get_capability 应当找到 huly IM facade"
            # facade.name 从 manifest 读 → "huly"
            assert cap.name == "huly", f"facade.name 应当是 'huly'，实际 {cap.name!r}"

            msg_ref = await cap.send_card(
                recipient=RecipientSpec(kind="channel", id="registry-acid-channel"),
                card=NormalizedCard(
                    title="Registry Path",
                    body_markdown="end-to-end registry path verification",
                    actions=[],
                ),
                idempotency_key="registry-key-1",
            )
            assert msg_ref.plugin_name == "huly"
            assert msg_ref.native_id.startswith("huly-msg-"), (
                f"通过 Registry 路径也应当走真 mock huly server, "
                f"native_id={msg_ref.native_id!r}"
            )

            await daemon.close()
        finally:
            PlatformPluginRegistry.clear()
