"""httpx 0.28+ vs mattermostautodriver 2.0 兼容垫片（Pitfall 2 P0）。

Why
---
httpx 0.28 起从 ``httpx.AsyncClient.__init__`` 移除了 ``proxies`` kwarg，
mattermostautodriver 2.0 仍向 AsyncClient 传 ``proxies=None`` —— 触发
``TypeError: __init__() got an unexpected keyword argument 'proxies'`` 在 driver
init 时立即崩。

Wave 4 (Plan 04_5-05) MattermostListener 必须在 ``import mattermostautodriver``
之前调用 ``apply_httpx_patch()``，删掉 driver 强塞的 ``proxies`` kwarg。

幂等性
------
- ``_PATCHED`` 标记防止多次 apply 嵌套 patched_init（多层 stack 调原始 init 也会
  正确工作，因为只保留一次 ``_ORIG_INIT`` 引用，但仍以 ``_PATCHED`` 短路避免无谓代码）
- 多个 listener task 启动时各自调一次 ``apply_httpx_patch()`` 不会出错

副作用控制
----------
- module-level 不 auto-apply（避免任意 import 本 module 即修改全局 httpx 行为）
- Wave 4 listener startup 才 apply（明确 monkey-patch 时机）

Reference
---------
- hr/offboarding-flow workers/mattermost_listener.py:30-40 已生产验证 1.5 个月
- httpx changelog: https://www.python-httpx.org/changelog/  (0.28.0 BREAKING)
- mattermostautodriver upstream issue: 2.0 仍传 proxies kwarg
"""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)

_PATCHED: bool = False
_ORIG_INIT = None  # type: ignore[var-annotated]


def apply_httpx_patch() -> None:
    """Monkey-patch ``httpx.AsyncClient.__init__`` 删除 ``proxies`` kwarg。

    必须在 ``import mattermostautodriver`` 之前调用。多次调用幂等。

    实现：
    1. 首次调用保存原始 ``AsyncClient.__init__`` 引用到模块级 ``_ORIG_INIT``
    2. 用 ``_patched_init`` 替换 ``AsyncClient.__init__``
       — 该 wrapper 调原始 init 前 ``kwargs.pop("proxies", None)`` 删掉 driver 强塞的 kwarg
    3. 标记 ``_PATCHED = True``，后续调用立即 return（幂等）
    """
    global _PATCHED, _ORIG_INIT

    if _PATCHED:
        return

    _ORIG_INIT = httpx.AsyncClient.__init__

    def _patched_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.pop("proxies", None)
        return _ORIG_INIT(self, *args, **kwargs)

    # type: ignore[method-assign] — 我们就是要 monkey-patch 方法
    httpx.AsyncClient.__init__ = _patched_init  # type: ignore[method-assign]
    _PATCHED = True

    log.info("bot.httpx_patch.applied")


def is_patched() -> bool:
    """是否已调用过 ``apply_httpx_patch()``（测试 + 自检用）。"""
    return _PATCHED


__all__ = ["apply_httpx_patch", "is_patched"]
