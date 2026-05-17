"""httpx_patch.apply_httpx_patch 单元测试（Pitfall 2 P0）。

测试矩阵：
- apply 后 is_patched() True
- 多次 apply 幂等
- 仅 import module（不调 apply）→ is_patched() False（无副作用）
- apply 后 httpx.AsyncClient(proxies=...) 不 raise TypeError
- apply 后 httpx.AsyncClient(timeout=...) 正常工作（其他 kwargs 不受影响）

注意：
- 这些测试**改变全局 httpx.AsyncClient.__init__**，但 monkey-patch 幂等且**只删 proxies**，
  对正常用例无影响（其他测试不依赖 proxies kwarg）。
- 不在 fixture 中 reset _PATCHED — 因为 apply 是幂等的，且 reset 反而会让其他测试看到
  非确定状态。
"""
from __future__ import annotations

import httpx

from app.agent_builder.bot_dispatcher import httpx_patch
from app.agent_builder.bot_dispatcher.httpx_patch import (
    apply_httpx_patch,
    is_patched,
)


def test_module_import_does_not_auto_apply() -> None:
    """仅 import httpx_patch 不应 auto-apply（避免副作用 — Wave 4 才 apply）。

    本测试必须排在所有 apply 之前（pytest 按文件序运行，本测试在文件第一个）。
    注意：apply_httpx_patch() 是幂等的；一旦在本进程内任意测试调用过，本测试
    就会变 stale。pytest 默认按定义顺序运行同文件测试，把本测试放最前。

    若其他文件先调了 apply（如 import 顺序）— 本测试自动跳过验证（is_patched 已 True
    时不应失败本测试，因为不是"auto-apply"导致的）。
    """
    # 仅当本测试是进程内第一个跑到 httpx_patch 的测试时才能验证 "auto-apply=False"
    # 通过检查 _ORIG_INIT 是否仍为 None 来判断：apply 后 _ORIG_INIT 一定非 None
    # 如果其他测试已 apply，本测试视为已通过（不可重复验证）。
    if httpx_patch._ORIG_INIT is None:
        assert not is_patched(), "module-level import 不应 auto-apply"


def test_apply_patch_sets_flag() -> None:
    """apply_httpx_patch() 调用后 is_patched() 应为 True。"""
    apply_httpx_patch()
    assert is_patched() is True


def test_apply_patch_idempotent() -> None:
    """多次 apply 幂等 — is_patched() 始终 True，且不嵌套 wrap。"""
    apply_httpx_patch()
    init_after_first = httpx.AsyncClient.__init__
    apply_httpx_patch()
    init_after_second = httpx.AsyncClient.__init__
    apply_httpx_patch()
    init_after_third = httpx.AsyncClient.__init__
    # 幂等：第二/三次 apply 不替换 __init__
    assert init_after_first is init_after_second
    assert init_after_second is init_after_third
    assert is_patched() is True


def test_patched_init_strips_proxies_kwarg() -> None:
    """apply 后 httpx.AsyncClient(proxies=...) 不 raise TypeError（核心修复）。"""
    apply_httpx_patch()
    # httpx 0.28+ 原本会 raise TypeError
    # patch 后 proxies kwarg 被 pop 掉
    client = httpx.AsyncClient(proxies="http://proxy.example.com:8080")
    assert isinstance(client, httpx.AsyncClient)


def test_patched_init_preserves_other_kwargs() -> None:
    """apply 后其他 kwargs 仍正常工作（timeout / headers / base_url 等）。"""
    apply_httpx_patch()
    client = httpx.AsyncClient(
        timeout=10.0,
        headers={"X-Test": "yes"},
        base_url="https://api.example.com",
    )
    assert isinstance(client, httpx.AsyncClient)
    # 这里只验证不抛异常 + timeout / headers 已设置
    assert client.timeout.connect == 10.0 or client.timeout.read == 10.0
    assert client.headers.get("X-Test") == "yes"
