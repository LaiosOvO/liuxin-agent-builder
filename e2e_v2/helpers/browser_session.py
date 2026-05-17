"""browser-harness subprocess 调用封装 — 仅 IM card click（#5）+ delegate UI（#6）spec 用。

设计参考 docs/reading-browser-harness-04-12-2026-05-17.md：
- 通过 subprocess.run() 调用 `browser-harness` CLI（uv tool install 后 PATH 内）
- 每个 spec 用独立 BU_NAME 隔离 daemon（防 chrome state 污染）
- 失败优雅降级：browser-harness 未安装时 skip 而非 fail

注意：
- 大部分 Phase 4 spec 是 pytest+httpx 不需要浏览器
- 仅 #5 IM card 点击跳转决策页 + #6 delegate 表单 UI 流走这里
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class BrowserHarnessResult:
    """browser-harness 调用结果（不可变）。"""

    stdout: str
    stderr: str
    returncode: int


class BrowserHarnessNotInstalled(RuntimeError):
    """browser-harness CLI 不在 PATH 上 — spec 应 skip 而非 fail。"""


def is_browser_harness_available() -> bool:
    """检测 browser-harness CLI 是否可用。"""
    return shutil.which("browser-harness") is not None


def run_browser_harness_script(
    script: str,
    name: str = "default",
    timeout: float = 60.0,
) -> BrowserHarnessResult:
    """通过 heredoc 在 browser-harness daemon 内执行 Python 脚本。

    用法：
        result = run_browser_harness_script('''
new_tab("https://example.com")
wait_for_load(timeout=10)
print(page_info())
        ''', name="spec_im_card")

    Args:
        script: 要执行的 Python 代码（heredoc body — browser-harness helpers 全局可用）
        name: BU_NAME（不同 spec 用不同 name 防 daemon 互冲）
        timeout: 子进程超时秒数

    Returns:
        BrowserHarnessResult 含 stdout / stderr / returncode

    Raises:
        BrowserHarnessNotInstalled: CLI 不在 PATH（spec 应 skip）
        subprocess.TimeoutExpired: timeout 超时
    """
    if not is_browser_harness_available():
        raise BrowserHarnessNotInstalled(
            "browser-harness CLI 不在 PATH — "
            "请执行 `uv tool install -e ~/ai/ref/agent/browser-harness` 安装"
        )

    env = {**os.environ, "BU_NAME": name}
    proc = subprocess.run(
        ["browser-harness"],
        input=script.encode("utf-8"),
        capture_output=True,
        timeout=timeout,
        env=env,
        check=False,  # 由调用方决定如何处理 returncode
    )
    return BrowserHarnessResult(
        stdout=proc.stdout.decode("utf-8", errors="replace"),
        stderr=proc.stderr.decode("utf-8", errors="replace"),
        returncode=proc.returncode,
    )
