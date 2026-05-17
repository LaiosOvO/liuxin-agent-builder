---
phase: 05c-doc-capability
plan: 08
type: execute
wave: 5
depends_on:
  - "06"
  - "07"
files_modified:
  - docs/reading-dify-05c-08-e2e-gate-2026-05-18.md
  - e2e/conftest.py
  - e2e/05c_outline_doc_write_spec.py
  - e2e/05c_lark_docs_doc_write_spec.py
  - e2e/05c_huly_4cap_doc_write_im_spec.py
  - scripts/license_attribution_audit.py
  - backend/tests/platforms/test_license_attribution_audit.py
  - backend/tests/platforms_integration/test_run_viewer_structured_log_coverage.py
  - .planning/phases/05c-doc-capability/05c-VERIFICATION.md
autonomous: true
requirements:
  - 5C-SC-5
  - 5C-FW-03
  - 5C-FW-04

must_haves:
  truths:
    - "Dify integration_tests 阅读文档已 commit（CLAUDE.md §2.7 硬性 gate） + 含 browser-harness 接入约定"
    - "用户 Chrome 跑 :9222 + e2e/conftest.py 提供 browser-harness session fixture（ensure_real_tab + new_tab + 截图保存）"
    - "browser-harness Outline E2E spec 真出文档 — DAG 配 doc_write 节点 (或直调 DocCapability service fallback) → 真 Outline @192.168.2.44:3000 出文档 + URL 校验 + 视觉截图"
    - "browser-harness Lark E2E spec 真出飞书文档 + IdentityCapability @ 人 verify（评论 mention lark_open_id 解析正确）"
    - "browser-harness Huly E2E spec 真出文档 + 二步流程 collab service blob ref 生效（UI 真渲染 not blank — Pitfall 1 防护）+ IMCapability per-user Channel send_card verify（hr §5.2 教训防回归）"
    - "license_attribution_audit.py 扫 backend/app/plugins/huly/_internal/*.py 每个文件含 `# Inspired by hr/offboarding-flow design under Apache-2.0 — not derived source` 头注释，缺一个 exit 1（fail-loud）"
    - "license audit script 单测：tmp_path 造 3 文件（2 合规 + 1 缺 attribution）→ 跑 script → exit 1 + stderr 含 缺失文件名"
    - "Run Viewer structured log coverage 集成测：真 daemon 调 doc_create_document → 抓 log → 断言 Pattern 7 schema 6 字段（plugin_name / workspace_id / capability / method / latency_ms / outcome）全在；若 Phase 7 Run Viewer 框架未做 → 降级 grep log file"
    - "Phase 5.A 271 platforms tests 全绿（regression — `pytest backend/tests/platforms/ -x` 0 fail）"
    - "Phase 5.B 5/5 acid test 全绿（regression — `pytest backend/tests/platforms_integration/test_huly_acid_test.py test_fault_isolation.py -v` 0 fail）"
    - "Phase 5.C plan 01-07 全 plugin 三层测试通过（unit + integration + 本 plan 加 E2E）"
    - "VERIFICATION.md 草稿存在，逐条覆盖 plan 01-08 全 DoD truth + Phase 5.C ROADMAP Success Criteria 1-5 + Anti-Patterns 复查"
  artifacts:
    - path: "docs/reading-dify-05c-08-e2e-gate-2026-05-18.md"
      provides: "Dify integration_tests workflow / browser-harness SKILL.md 阅读笔记（5 节标准模板 + E2E 接入注意）"
      min_lines: 80
    - path: "e2e/conftest.py"
      provides: "browser-harness Chrome :9222 ensure fixture + 截图目录 fixture（共享给 3 个 05c_*_spec.py）"
      contains: "browser_harness"
    - path: "e2e/05c_outline_doc_write_spec.py"
      provides: "Outline E2E spec — browser-harness Python（NOT Playwright TS）"
      contains: "browser-harness|new_tab|capture_screenshot"
    - path: "e2e/05c_lark_docs_doc_write_spec.py"
      provides: "Lark Docs E2E spec + IdentityCapability @ 人 verify"
      contains: "browser-harness|lark"
    - path: "e2e/05c_huly_4cap_doc_write_im_spec.py"
      provides: "Huly 4-cap E2E spec + IMCapability per-user Channel verify + Pitfall 1 防护"
      contains: "browser-harness|huly|192.168.2.44:8087"
    - path: "scripts/license_attribution_audit.py"
      provides: "CI hook — scan backend/app/plugins/huly/_internal/*.py attribution 头注释，缺则 exit 1 fail-loud（5C-FW-04）"
      contains: "Inspired by hr/offboarding-flow"
    - path: "backend/tests/platforms/test_license_attribution_audit.py"
      provides: "license audit script 单测（tmp_path 造合规/不合规文件 → 验证 exit code + stderr）"
      contains: "license_attribution_audit"
    - path: "backend/tests/platforms_integration/test_run_viewer_structured_log_coverage.py"
      provides: "Pattern 7 structured log 6 字段覆盖集成测（真 daemon spawn + capability call + caplog/logfile assertion）"
      contains: "plugin_name.*workspace_id.*capability.*method.*latency_ms.*outcome"
    - path: ".planning/phases/05c-doc-capability/05c-VERIFICATION.md"
      provides: "Phase 5.C 出口 VERIFICATION 草稿 — 覆盖 plan 01-08 全 DoD truth + ROADMAP SC 1-5"
      contains: "Goal Achievement"
  key_links:
    - from: "e2e/05c_outline_doc_write_spec.py"
      to: "192.168.2.44:3000 (Outline self-hosted)"
      via: "browser-harness new_tab + capture_screenshot 视觉确认文档渲染"
      pattern: "new_tab.*192\\.168\\.2\\.44"
    - from: "e2e/05c_huly_4cap_doc_write_im_spec.py"
      to: "192.168.2.44:8087 (Huly self-hosted, SSH tunnel)"
      via: "browser-harness 验真 Document UI 不空白 (Pitfall 1) + Channel send_card 视觉确认"
      pattern: "huly|192\\.168\\.2\\.44"
    - from: "scripts/license_attribution_audit.py"
      to: "backend/app/plugins/huly/_internal/*.py"
      via: "Path.glob + Path.read_text + 行首注释匹配"
      pattern: "Inspired by hr/offboarding-flow"
    - from: "backend/tests/platforms/test_license_attribution_audit.py"
      to: "scripts/license_attribution_audit.py"
      via: "subprocess.run script + assert returncode"
      pattern: "subprocess.run.*license_attribution_audit"
    - from: "backend/tests/platforms_integration/test_run_viewer_structured_log_coverage.py"
      to: "Pattern 7 log_capability_call (plugin daemon 内)"
      via: "caplog capture LogRecord → assert all 6 fields present"
      pattern: "plugin_name.*latency_ms.*outcome"
    - from: ".planning/phases/05c-doc-capability/05c-VERIFICATION.md"
      to: "plan 01-08 全 PLAN.md must_haves"
      via: "逐 truth 对照 + Evidence 列指向真实测试输出"
      pattern: "Observable Truths"
---

<objective>
Phase 5.C 出口 E2E gate — 通过 browser-harness CDP 直连用户 Chrome 跑 3 个真实 plugin spec（Outline / Lark / Huly），加 license attribution audit CI hook + Pattern 7 structured log coverage 集成测，最后跑 Phase 5.A 271 regression + Phase 5.B 5/5 acid test regression + 写 Phase 5.C VERIFICATION.md 草稿覆盖 plan 01-08 全 DoD truth。

Purpose: CLAUDE.md §2.2 强制要求每 phase 必须有 E2E browser-harness 覆盖所有 ROADMAP Success Criteria；全局 CLAUDE.md + memory feedback_e2e_browser_harness_only 强制 E2E 必走 browser-harness（CDP 直连用户 Chrome，禁止 Playwright sync_playwright / 禁止默认 webapp-testing skill）；license attribution audit 是 Pitfall 8 AGPL 防御的机械化 CI hook；Pattern 7 structured log 是 Phase 7 Run Viewer 接力的契约保证。本 plan 是 Phase 5.C 收官 gate，必须证明 plan 01-07 真实工作 + 全 phase regression 0 退化。

Output: 1 reading doc + 1 conftest fixture + 3 个 browser-harness Python E2E spec + 1 license audit script + 1 audit script unit test + 1 Pattern 7 structured log integration test + 1 VERIFICATION.md 草稿。
</objective>

<execution_context>
@/Users/admin/.claude/get-shit-done/workflows/execute-plan.md
@/Users/admin/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/05c-doc-capability/05c-CONTEXT.md
@.planning/phases/05c-doc-capability/05c-RESEARCH.md
@CLAUDE.md
@~/.claude/CLAUDE.md
@~/ai/ref/agent/browser-harness/SKILL.md

<interfaces>
<!-- Pattern 7 structured log schema (RESEARCH §Pattern 7, line 794-837) -->
<!-- 6 required fields + extras dict -->

```python
# Source: 05c-RESEARCH.md §Pattern 7
_log.info("platform.plugin.invoke", extra={
    "plugin_name": str,           # "outline" | "lark_docs" | "huly"
    "workspace_id": str | None,   # contextvars current_workspace_id
    "capability": str,            # "doc" | "im" | "identity" | "tracker"
    "method": str,                # "create_document" | "send_card" | "resolve_user_ref" ...
    "latency_ms": int,
    "outcome": str,               # "success" | "error" | "timeout" | "blocked"
    # extras: idempotency_key / doc_id 前 8 字符 / recipient_kind ...
})
```

<!-- browser-harness usage (SKILL.md) -->
<!-- 调用约定：heredoc + Python，daemon 自动启动；首次导航 new_tab(url) -->
<!-- 已就绪 helpers：new_tab / wait_for_load / capture_screenshot / click_at_xy / page_info / ensure_real_tab / js -->

```bash
browser-harness <<'PY'
new_tab("http://192.168.2.44:3000/doc/{outline_doc_id}")
wait_for_load()
img = capture_screenshot()
info = page_info()
print(info)
PY
```

<!-- Phase 5.A acid test regression baseline (must stay 0 fail) -->
<!-- Phase 5.B 271 platforms tests (Phase 5.B VERIFICATION.md 已记) -->
<!-- 271 = 162 (5.A) + 109 (5.B plans 01-05 unit + sandbox) -->
<!-- 5/5 = test_huly_acid_test.py + test_fault_isolation.py -->

```
backend/tests/platforms/                  # unit, 271 tests
backend/tests/platforms_integration/      # integration, 含 huly_acid + fault_isolation 5 tests
```

<!-- License attribution string format（CONTEXT Decision 8）-->
<!-- 每个 backend/app/plugins/huly/_internal/*.py 文件头必须含： -->
```python
# Inspired by hr/offboarding-flow design under Apache-2.0 — not derived source
```
</interfaces>
</context>

<reference>
Dify 模块映射（CLAUDE.md §2.7）:
- 后端必读：`api/services/workflow_service.py` —— grep `validate|DSL.*lint|integrity` 至少 30 行（Phase 5.C 我们要验证 plugin daemon 接入 workflow 编排是否真跑通，理解 Dify 工作流 validate 思路）
- 集成测参考：`api/tests/integration_tests/workflow/test_sync_workflow.py` —— 看 Dify 怎么写 workflow integration test（不拷代码）
- 集成测参考：`api/tests/integration_tests/services/plugin/` —— plugin install integration test 风格
- browser-harness 必读：`~/ai/ref/agent/browser-harness/SKILL.md` 全文（usage / interaction-skills / what actually works / gotchas）+ agent-workspace/agent_helpers.py 命名规范（如有）

借鉴重点（reading doc 必含）:
1. Dify workflow_service.validate 思路 → 我们 plugin daemon 接入 workflow 编排时如何 lint
2. Dify integration_tests/workflow/test_sync_workflow 真跑 workflow 模式 → 我们 E2E 跑 doc_write 节点参考
3. Dify integration_tests/services/plugin install 流程 → 我们 plugin 注册 → E2E 流程参考
4. browser-harness vs Playwright 关键差异：CDP 直连用户 Chrome（不起 headless）/ 用户登录态保留 / 截图 verify 默认而非 selector 等待
5. browser-harness gotchas：goto_url 会污染用户活动 tab → 必须用 new_tab() / 默认 daemon session 可能 stale → ensure_real_tab() / chrome://omnibox-popup 是假 tab 需过滤

License: Dify AGPL-3.0 仅借鉴 test 风格 + workflow validate 思路；browser-harness MIT 可放心借鉴；hr/offboarding-flow 已按 Phase 5.C 全 plan 一贯 attribution 规则处理。
</reference>

<tasks>

<task type="auto">
  <name>Task 0: Dify integration_tests + browser-harness 阅读文档（CLAUDE.md §2.7 硬性 gate）</name>
  <files>docs/reading-dify-05c-08-e2e-gate-2026-05-18.md</files>
  <action>
**STOP — 这是后续所有 commit 的前置 gate**。先 commit 此文档才允许写代码（CLAUDE.md §2.7 + memory feedback_reference_first）。

读以下文件（Read 工具，理解设计模式，不要 grep 也不要贴源码）:

1. `/Users/admin/ai/ref/dify/repo/api/services/workflow_service.py` — grep `validate|lint|verify|integrity|graph_engine_factory` 关键方法（理解 Dify workflow 校验链）
2. `/Users/admin/ai/ref/dify/repo/api/tests/integration_tests/workflow/test_sync_workflow.py` — 完整读（理解 Dify 真跑 workflow 集成测的 fixture / setup / assertion 模式）
3. `/Users/admin/ai/ref/dify/repo/api/tests/integration_tests/services/plugin/` 下任一 plugin 集成测（理解 plugin install + daemon spawn 风格）
4. `/Users/admin/ai/ref/agent/browser-harness/SKILL.md` 全文（已加载在 system context，重读确认接入约定）
5. `/Users/admin/ai/ref/agent/browser-harness/install.md`（如存在 —— 用 Read 工具查；不存在则跳过）

写到 `docs/reading-dify-05c-08-e2e-gate-2026-05-18.md`，**完全按 CLAUDE.md §2.7 阅读文档 5 节模板**：

```markdown
# Dify + browser-harness 阅读笔记 — Phase 5.C E2E Gate

> 日期: 2026-05-18
> 仓库1: https://github.com/langgenius/dify (local clone /Users/admin/ai/ref/dify/repo/, AGPL-3.0)
> 仓库2: https://github.com/browser-use/browser-harness (local clone /Users/admin/ai/ref/agent/browser-harness/, MIT)
> Stars: Dify ~141k / browser-harness ~13k

## 项目概述（一句话）
Dify 是国内最成熟的 LLM 应用平台（含 workflow 编排）；browser-harness 是 CDP 直连用户 Chrome 的 self-improving Python harness。本 plan 借鉴 Dify workflow 集成测风格 + 用 browser-harness 跑真 plugin 出口 E2E。

## 技术栈对照
- Dify workflow_service.validate 用 graph_engine_factory 校验拓扑 / 变量引用 / 节点 schema
- Dify integration_tests/workflow/test_sync_workflow.py 用 pytest fixture 真 spawn workflow 进程 + 真 LLM call
- browser-harness 用 CDP `Input.dispatchMouseEvent` 直接坐标点击（不走 selector），保留用户 Chrome 登录态 + cookie
- 与 Playwright 关键差异：browser-harness 是 self-improving（agent 改 agent_helpers.py），Playwright 是 once-and-done

## 架构要点
（文字 + 简图描述 3 层）：
1. **Dify integration test 层**：pytest fixture → spawn worker → 真 DB + 真 Redis + 真 LLM
2. **本项目 E2E 层**：pytest fixture → ensure user Chrome :9222 → browser-harness heredoc → new_tab → capture_screenshot
3. **隔离边界**：E2E 不 mock 任何外部服务（Outline/Lark/Huly 都是真实例 @ 192.168.2.44）

## 可借鉴的设计模式（必含 5-6 条 + source → target 对应）
1. **workflow_service.validate** (`api/services/workflow_service.py` `_validate_workflow_graph` 函数) → 我们 v1.5 doc_write 节点接入时如何 lint plugin manifest 与节点 config 一致性（本 plan 不实现节点接入，但 reading doc 留参考）
2. **test_sync_workflow.py fixture 模式**（`@pytest.fixture` + `setup_workflow` + `assert workflow_run.outputs`） → 我们 E2E spec 的 fixture 风格（`browser_harness` + `api_client` + `dsl_builder` 三 fixture）
3. **plugin install integration test**（如有 — `test_plugin_install.py` 风格）→ 我们 E2E 跑前确保 plugin 已 register 到 workspace
4. **browser-harness `capture_screenshot()` first → `click_at_xy()` → re-screenshot verify** 模式（SKILL.md "What actually works"）→ 我们三 spec 必走此模式（不写 selector hunt）
5. **browser-harness `new_tab(url)` 而非 `goto_url(url)`**（SKILL.md gotcha）→ 避免污染用户活动 tab，conftest fixture 必须文档化
6. **browser-harness `ensure_real_tab()` 处理 stale session**（SKILL.md gotcha）→ 我们 conftest 在每 spec 开始处调用一次防御

## 与本项目的关系
本 plan 是 Phase 5.C 出口 gate：
- 3 个 browser-harness Python spec（NOT Playwright TS — 历史 Playwright spec 保留不删，新 spec 用 browser-harness）
- 跑通 Outline / Lark / Huly 三平台真出文档（5C-SC-5）
- license attribution audit script 是 5C-FW-04 的 CI hook
- Pattern 7 structured log coverage 集成测保证 Phase 7 Run Viewer 接力契约

## License attribution
- Dify (AGPL-3.0): 仅借鉴 workflow_service.validate + integration test fixture 思路；**不拷贝任何 Dify 源代码**
- browser-harness (MIT): 命令字符串 + helper 命名风格可自由使用
- hr/offboarding-flow: 每个 backend/app/plugins/huly/_internal/*.py 已含 `# Inspired by hr/offboarding-flow design under Apache-2.0 — not derived source` 头注释（本 plan 自动审计）
```

文档最少 80 行 + 5-6 个借鉴点必须含 source file → target file 的明确对应关系 + License attribution 显式。**不要**贴 Dify 源代码片段（许可证）。

commit message: `docs(05c-08): add Dify integration_tests + browser-harness reading doc`
  </action>
  <verify>
    <automated>test -f /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05c-08-e2e-gate-2026-05-18.md && wc -l /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05c-08-e2e-gate-2026-05-18.md | awk '{exit ($1 >= 80 ? 0 : 1)}' && grep -q "AGPL\|MIT" /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05c-08-e2e-gate-2026-05-18.md && grep -q "可借鉴的设计模式" /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05c-08-e2e-gate-2026-05-18.md && grep -q "browser-harness" /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05c-08-e2e-gate-2026-05-18.md</automated>
  </verify>
  <done>Reading doc 存在 ≥ 80 行 + 含 License attribution + 含「可借鉴的设计模式」5+ 条 + 含 browser-harness 章节；git commit hash 早于 Task 1+ 的 commit hash（CLAUDE.md §2.7 gate）</done>
</task>

<task type="auto">
  <name>Task 1: e2e/conftest.py browser-harness session fixture（Chrome :9222 ensure + 截图目录）</name>
  <files>e2e/conftest.py</files>
  <action>
Reading doc 已 commit ✓（CLAUDE.md §2.7 gate 通过），才能开始写代码。

**注意：** 现有 `e2e/conftest.py` 可能不存在（历史 Playwright spec.ts 用 `playwright.config.ts`）。本任务新增 Python 版 conftest 给 browser-harness specs 用。如果文件已存在 → 用 Edit 工具增加 fixture 而非覆盖；如果不存在 → 用 Write 工具创建。

**创建 / 扩展 `e2e/conftest.py`**：

```python
"""Phase 5.C browser-harness E2E 共享 fixture。

CLAUDE.md §2.2 + 全局 CLAUDE.md 强制规则：E2E 一律走 browser-harness（CDP 直连用户 Chrome :9222），
禁止 Playwright sync_playwright / 禁止默认 webapp-testing skill。

历史 Playwright `*.spec.ts` 文件暂保留不删（per CLAUDE.md §2.2），新 5.C spec 用 Python + browser-harness。

Fixtures:
- ``browser_harness`` — 确保 Chrome :9222 可达 + 提供 helper 调用 入口
- ``screenshot_dir`` — 截图保存目录 `docs/e2e-screenshots-2026-05-18/`（全局 CLAUDE.md 约定）
- ``outline_base_url`` — http://192.168.2.44:3000 (Phase 5.C 真实例)
- ``huly_base_url`` — http://192.168.2.44:8087 (Phase 1 SSH tunnel 已配，per CONTEXT specifics)
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
from datetime import date
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def screenshot_dir() -> Path:
    """全局 CLAUDE.md 约定：截图保存到 `docs/e2e-screenshots-{date}/`。"""
    today = date.today().isoformat()
    d = Path(__file__).parent.parent / "docs" / f"e2e-screenshots-{today}"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture(scope="session")
def outline_base_url() -> str:
    """Outline self-hosted on .44 (CONTEXT specifics line 144)."""
    return os.environ.get("OUTLINE_BASE_URL", "http://192.168.2.44:3000")


@pytest.fixture(scope="session")
def huly_base_url() -> str:
    """Huly self-hosted on .44 (Phase 1 SSH tunnel, CONTEXT specifics line 145)."""
    return os.environ.get("HULY_BASE_URL", "http://192.168.2.44:8087")


def _is_chrome_9222_alive() -> bool:
    """检测用户 Chrome 是否已用 --remote-debugging-port=9222 启动（全局 CLAUDE.md §1）。"""
    try:
        with socket.create_connection(("127.0.0.1", 9222), timeout=1.0):
            return True
    except (OSError, ConnectionRefusedError):
        return False


@pytest.fixture(scope="session")
def browser_harness():
    """browser-harness session — 确保 user Chrome :9222 + 提供 heredoc 调用入口。

    Returns:
        Callable[[str], subprocess.CompletedProcess]: 调用方式 ``browser_harness(py_code)`` → 跑一段
        browser-harness heredoc Python，返回 CompletedProcess（stdout/stderr/returncode）。

    Skip 条件：
    - browser-harness 不在 PATH（用户未装 → `pip install browser-harness` 或 clone）
    - Chrome :9222 不通（用户未用 `--remote-debugging-port=9222` 启动 Chrome）
    """
    if shutil.which("browser-harness") is None:
        pytest.skip(
            "browser-harness 未安装 — 全局 CLAUDE.md §1 要求安装："
            "git clone https://github.com/browser-use/browser-harness ~/ai/ref/agent/browser-harness"
        )
    if not _is_chrome_9222_alive():
        pytest.skip(
            "Chrome :9222 不通 — 全局 CLAUDE.md §1 要求用户 Chrome 已用 "
            "`--remote-debugging-port=9222` 启动；参考 browser-harness install.md"
        )

    def _run(py_code: str, *, timeout: float = 60.0) -> subprocess.CompletedProcess:
        """跑一段 browser-harness Python heredoc。"""
        return subprocess.run(
            ["browser-harness"],
            input=py_code,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )

    return _run


@pytest.fixture(autouse=True, scope="session")
def _ensure_real_tab_on_session_start(browser_harness):
    """每 session 开头调一次 ensure_real_tab() 防 stale daemon session（SKILL.md gotcha）。"""
    if browser_harness is None:
        return
    browser_harness("ensure_real_tab()\nprint('session_ready')")
```

避坑（SKILL.md gotchas）:
- 必须用 `new_tab(url)` 而非 `goto_url(url)` —— 后者污染用户活动 tab（fixture 文档化）
- daemon session 可能 stale —— `ensure_real_tab()` autouse fixture 防御
- `omnibox-popup` 是假 page target，verify 时用 `page_info()` 排除
- Chrome :9222 不通时 **skip 而非 fail** —— 让 dev 环境无 Chrome 时也能跑其他测试

commit message: `feat(05c-08): add e2e/conftest.py browser-harness session fixture`
  </action>
  <verify>
    <automated>test -f /Users/admin/ai/resume/interview/liuxin/agent-builder/e2e/conftest.py && python3 -c "import ast; tree = ast.parse(open('/Users/admin/ai/resume/interview/liuxin/agent-builder/e2e/conftest.py').read()); names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}; assert {'screenshot_dir', 'outline_base_url', 'huly_base_url', 'browser_harness'}.issubset(names), f'缺 fixture: {names}'; print('all fixtures OK')"</automated>
  </verify>
  <done>e2e/conftest.py 存在；4 个 fixture（browser_harness / screenshot_dir / outline_base_url / huly_base_url）存在；ast 解析通过；browser_harness fixture 含 :9222 检测 + skip 逻辑</done>
</task>

<task type="auto">
  <name>Task 2: e2e/05c_outline_doc_write_spec.py — Outline E2E（browser-harness 真出文档）</name>
  <files>e2e/05c_outline_doc_write_spec.py</files>
  <action>
**关键约束（全局 CLAUDE.md + memory feedback_e2e_browser_harness_only）**:
- 禁止 `from playwright.sync_api import sync_playwright`
- 禁止 `Skill("webapp-testing")`
- E2E 全走 browser-harness CDP（用户 Chrome :9222）+ Python（非 TypeScript spec.ts）

创建 `e2e/05c_outline_doc_write_spec.py`:

```python
"""Phase 5.C Outline E2E — 真出 markdown 文档 + URL 校验 + 视觉截图。

测试链路：
1. 调 agent-builder API（如 doc_write 节点已实现 v1.5 → 拖 DAG 跑；否则直调 DocCapability service fallback）
2. plugin daemon (outline) `doc.create_document` → Outline API documents.create
3. 拿 outline_doc_id → browser-harness 打开 Outline UI 验证渲染

依赖：
- Outline @ 192.168.2.44:3000（CONTEXT specifics line 144）
- 用户已 seed Outline collection（如未 seed → spec 内创建）
- browser-harness Chrome :9222 已启动（conftest fixture skip）

CLAUDE.md §2.2 + 全局 §1: 必走 browser-harness（CDP 直连用户 Chrome），禁止 Playwright。

License: 100% 独立创作；fixture 模式参考 Dify integration_tests/workflow/test_sync_workflow.py。
"""
from __future__ import annotations

import os
import uuid

import httpx
import pytest


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.outline,
    pytest.mark.skipif(
        not os.environ.get("RUN_E2E"),
        reason="E2E 默认 skip，CI 显式 RUN_E2E=1 触发",
    ),
]


@pytest.fixture(scope="module")
def outline_api_token() -> str:
    """从 env 读 Outline API token（用户 seed）。"""
    token = os.environ.get("OUTLINE_API_TOKEN")
    if not token:
        pytest.skip("OUTLINE_API_TOKEN 未设置 — 用户需在 .env 配 Outline self-hosted token")
    return token


def test_outline_doc_write_real_render(
    browser_harness,
    outline_base_url,
    outline_api_token,
    screenshot_dir,
):
    """端到端：DocCapability.create_document → 真 Outline 出文档 → browser-harness 视觉确认。

    步骤：
    1. 调 agent-builder DocCapability service（fallback：如 v1.5 doc_write 节点未做，直调 service layer）
    2. 拿 outline_doc_id
    3. 用 Outline REST documents.info 校验 markdown 存在
    4. browser-harness new_tab Outline UI → wait_for_load → capture_screenshot 保存
    """
    run_id = uuid.uuid4().hex[:8]
    title = f"E2E Outline {run_id}"
    markdown = (
        f"# E2E 测试文档 {run_id}\n\n"
        "这是 Phase 5.C 出口 gate 由 browser-harness 自动验证生成。\n\n"
        "## 章节 2\n\n- 列表项 1\n- 列表项 2\n"
    )

    # Step 1: 调 agent-builder API（v1.5 节点未做 → 直调 service layer endpoint）
    # 假设存在 `/api/v1/test/doc_capability/create_document` 测试 endpoint（Plan 07 或本 plan 期降级方案）
    api_base = os.environ.get("API_BASE_URL", "http://localhost:8000")
    workspace_id = os.environ.get("E2E_WORKSPACE_ID", "00000000-0000-0000-0000-000000000001")

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{api_base}/api/v1/test/doc_capability/create_document",
            json={
                "plugin_name": "outline",
                "workspace_id": workspace_id,
                "title": title,
                "markdown": markdown,
                "collection_id": os.environ.get("OUTLINE_COLLECTION_ID", "default"),
            },
        )
    assert resp.status_code == 200, f"API 调用失败 {resp.status_code}: {resp.text[:300]}"
    result = resp.json()
    outline_doc_id = result["native_id"]
    assert outline_doc_id, f"未返回 native_id: {result}"

    # Step 2: Outline REST 校验 markdown 存在（不走 browser，纯 API verify）
    with httpx.Client(timeout=10.0) as client:
        doc_resp = client.post(
            f"{outline_base_url}/api/documents.info",
            headers={"Authorization": f"Bearer {outline_api_token}"},
            json={"id": outline_doc_id},
        )
    assert doc_resp.status_code == 200, f"Outline documents.info 失败: {doc_resp.text[:300]}"
    doc_data = doc_resp.json()["data"]
    assert run_id in doc_data["text"], f"文档内容未含 run_id: {doc_data['text'][:200]}"

    # Step 3: browser-harness 打开 Outline UI 视觉确认（CDP 直连用户 Chrome）
    screenshot_path = screenshot_dir / f"outline_{run_id}.png"
    bh_code = f"""
import base64
new_tab("{outline_base_url}/doc/{outline_doc_id}")
wait_for_load()
img_b64 = capture_screenshot()
with open("{screenshot_path}", "wb") as f:
    f.write(base64.b64decode(img_b64))
info = page_info()
print("title:", info.get("title"))
print("url:", info.get("url"))
print("screenshot_saved:", "{screenshot_path}")
"""
    result_bh = browser_harness(bh_code, timeout=45.0)
    assert result_bh.returncode == 0, (
        f"browser-harness 失败 returncode={result_bh.returncode}\n"
        f"stdout={result_bh.stdout}\nstderr={result_bh.stderr}"
    )
    assert "screenshot_saved" in result_bh.stdout, f"截图未保存: {result_bh.stdout}"
    assert screenshot_path.exists(), f"截图文件不存在: {screenshot_path}"

    # Step 4: page_info 含 doc title 暗示渲染成功（避免 selector hunt — SKILL.md 推荐）
    assert title in result_bh.stdout or outline_doc_id[:8] in result_bh.stdout, (
        f"page_info 未含 doc 标题或 ID: {result_bh.stdout}"
    )
```

避坑:
- `RUN_E2E=1` env gate —— CI 默认不跑（避免无 Chrome :9222 环境失败）
- 截图保存到 `docs/e2e-screenshots-2026-05-18/`（screenshot_dir fixture）
- API endpoint `/api/v1/test/doc_capability/create_document` 在 Plan 07 或本 plan **创建测试专用 endpoint**（不在生产 path）；若 v1.5 节点已实现 → 改走拖 DAG 流程
- 不在 spec 内创建 Outline collection —— 用户 seed（`OUTLINE_COLLECTION_ID` env）
- screenshot 用 `base64.b64decode` 解码 `capture_screenshot()` 返回值（SKILL.md 约定）

commit message: `test(05c-08): add Outline E2E spec via browser-harness (5C-SC-5)`
  </action>
  <verify>
    <automated>test -f /Users/admin/ai/resume/interview/liuxin/agent-builder/e2e/05c_outline_doc_write_spec.py && python3 -c "import ast; src = open('/Users/admin/ai/resume/interview/liuxin/agent-builder/e2e/05c_outline_doc_write_spec.py').read(); ast.parse(src); assert 'sync_playwright' not in src, 'spec 不应包含 Playwright 调用'; assert 'browser-harness' in src or 'browser_harness' in src, 'spec 必须用 browser-harness'; assert 'new_tab' in src and 'capture_screenshot' in src, '必须用 browser-harness 标准 helpers'; print('Outline spec OK')"</automated>
  </verify>
  <done>Outline E2E spec 存在；无 sync_playwright 引用；含 browser-harness / new_tab / capture_screenshot；spec 在 RUN_E2E=1 + Chrome :9222 + OUTLINE_API_TOKEN 三条件齐时可真跑通（spec syntax 验证 + skip 逻辑齐全）</done>
</task>

<task type="auto">
  <name>Task 3: e2e/05c_lark_docs_doc_write_spec.py — Lark Docs E2E + IdentityCapability @ 人 verify</name>
  <files>e2e/05c_lark_docs_doc_write_spec.py</files>
  <action>
创建 `e2e/05c_lark_docs_doc_write_spec.py`:

```python
"""Phase 5.C Lark Docs E2E — markdown → Lark blocks 转换 + IdentityCapability @ 人验证。

测试链路：
1. 调 agent-builder DocCapability.create_document（plugin=lark_docs）
2. plugin daemon (lark_docs) → markdown → Lark Block via /docx/v1/documents/blocks/convert
3. 调 IdentityCapability.resolve_user_ref(email) → 拿 lark_open_id
4. 调 DocCapability.add_comment(@open_id) → 评论 mention
5. browser-harness 打开 Lark 文档 UI → 截图 + 视觉确认 @ 人渲染

依赖：
- Lark 凭据（用户已有，CONTEXT specifics line 146 — sandbox app 可选）
- E2E test workspace 在 agent-builder 已配 lark_docs plugin
- 测试 Lark user email 存在（IdentityCapability resolve）

CLAUDE.md §2.2 + 全局 §1: 必走 browser-harness（CDP 直连用户 Chrome），禁止 Playwright。
"""
from __future__ import annotations

import os
import uuid

import httpx
import pytest


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.lark_docs,
    pytest.mark.skipif(
        not os.environ.get("RUN_E2E"),
        reason="E2E 默认 skip，CI 显式 RUN_E2E=1 触发",
    ),
]


@pytest.fixture(scope="module")
def lark_test_user_email() -> str:
    email = os.environ.get("LARK_E2E_TEST_USER_EMAIL")
    if not email:
        pytest.skip("LARK_E2E_TEST_USER_EMAIL 未设置 — 需 sandbox 中真实 user email 供 @ 人测试")
    return email


def test_lark_doc_write_with_mention_real_render(
    browser_harness,
    screenshot_dir,
    lark_test_user_email,
):
    """端到端：Lark 真出文档 + @ 人评论 + browser-harness 视觉验证。"""
    run_id = uuid.uuid4().hex[:8]
    title = f"E2E Lark {run_id}"
    markdown = (
        f"# Phase 5.C Lark E2E {run_id}\n\n"
        "## 段落一\n\n这是用 marko AST 转 Lark Block 的验证文档。\n\n"
        "## 段落二\n\n- 列表项 A\n- 列表项 B\n"
    )

    api_base = os.environ.get("API_BASE_URL", "http://localhost:8000")
    workspace_id = os.environ.get("E2E_WORKSPACE_ID", "00000000-0000-0000-0000-000000000001")

    # Step 1: 调 agent-builder 创建文档
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{api_base}/api/v1/test/doc_capability/create_document",
            json={
                "plugin_name": "lark_docs",
                "workspace_id": workspace_id,
                "title": title,
                "markdown": markdown,
                "folder_token": os.environ.get("LARK_E2E_FOLDER_TOKEN"),
            },
        )
    assert resp.status_code == 200, f"DocCapability.create_document 失败: {resp.text[:300]}"
    result = resp.json()
    document_id = result["native_id"]
    doc_url = result.get("extras", {}).get("url", "")
    assert document_id, f"未返回 document_id: {result}"

    # Step 2: 调 IdentityCapability.resolve_user_ref → 拿 lark_open_id
    with httpx.Client(timeout=15.0) as client:
        identity_resp = client.post(
            f"{api_base}/api/v1/test/identity_capability/resolve_user_ref",
            json={
                "plugin_name": "lark_docs",
                "workspace_id": workspace_id,
                "user_ref": {"kind": "email", "value": lark_test_user_email},
            },
        )
    assert identity_resp.status_code == 200, f"IdentityCapability resolve 失败: {identity_resp.text[:300]}"
    identity_data = identity_resp.json()
    lark_open_id = identity_data["native_id"]
    assert lark_open_id.startswith("ou_"), f"lark_open_id 格式异常: {lark_open_id}"

    # Step 3: 调 DocCapability.add_comment 加 @ 人评论
    with httpx.Client(timeout=15.0) as client:
        comment_resp = client.post(
            f"{api_base}/api/v1/test/doc_capability/add_comment",
            json={
                "plugin_name": "lark_docs",
                "workspace_id": workspace_id,
                "document_id": document_id,
                "comment_markdown": f"请 @{lark_test_user_email} 审核此文档 (run {run_id})",
                "mentions": [{"native_id": lark_open_id}],
            },
        )
    assert comment_resp.status_code == 200, f"add_comment 失败: {comment_resp.text[:300]}"

    # Step 4: browser-harness 打开 Lark 文档 UI 视觉确认（用户 Chrome 应已登录飞书）
    if not doc_url:
        # Lark Docs URL pattern: https://{tenant}.feishu.cn/docx/{document_id}
        tenant_subdomain = os.environ.get("LARK_TENANT_SUBDOMAIN", "feishu")
        doc_url = f"https://{tenant_subdomain}.feishu.cn/docx/{document_id}"

    screenshot_path = screenshot_dir / f"lark_{run_id}.png"
    bh_code = f"""
import base64
new_tab("{doc_url}")
wait_for_load()
# 给 Lark 渲染时间（Block 渲染异步）
import time
time.sleep(3)
img_b64 = capture_screenshot()
with open("{screenshot_path}", "wb") as f:
    f.write(base64.b64decode(img_b64))
info = page_info()
print("title:", info.get("title"))
print("url:", info.get("url"))
print("screenshot_saved:", "{screenshot_path}")
"""
    result_bh = browser_harness(bh_code, timeout=60.0)
    assert result_bh.returncode == 0, (
        f"browser-harness 失败\nstdout={result_bh.stdout}\nstderr={result_bh.stderr}"
    )
    assert screenshot_path.exists(), f"截图未保存: {screenshot_path}"

    # Step 5: 验证 Lark Docs URL 已渲染（page_info url 含 docx/{document_id}）
    assert document_id[:8] in result_bh.stdout, f"page url 未含 doc id: {result_bh.stdout}"
```

避坑:
- 用户 Chrome 应**已登录飞书**（CDP 直连，保留 cookie — 全局 CLAUDE.md §1 关键优势）
- Lark Block 渲染异步 → `time.sleep(3)` 等渲染（不写 selector hunt）
- 文档 URL 优先从 API 返回的 `extras.url` 取，回退到 pattern `https://{subdomain}.feishu.cn/docx/{id}`
- `LARK_E2E_FOLDER_TOKEN` 可选 — 默认根目录
- 评论 mention 用 lark_open_id 而非 email（lark-oapi 1.6.5 API 约定）

commit message: `test(05c-08): add Lark Docs E2E spec with IdentityCapability @ verification (5C-SC-5)`
  </action>
  <verify>
    <automated>test -f /Users/admin/ai/resume/interview/liuxin/agent-builder/e2e/05c_lark_docs_doc_write_spec.py && python3 -c "import ast; src = open('/Users/admin/ai/resume/interview/liuxin/agent-builder/e2e/05c_lark_docs_doc_write_spec.py').read(); ast.parse(src); assert 'sync_playwright' not in src, '不应包含 Playwright'; assert 'browser_harness' in src and 'new_tab' in src and 'capture_screenshot' in src, '必须用 browser-harness'; assert 'resolve_user_ref' in src and 'add_comment' in src, '必须含 IdentityCapability + add_comment 调用'; print('Lark spec OK')"</automated>
  </verify>
  <done>Lark E2E spec 存在；无 Playwright；含 browser-harness API；含 IdentityCapability.resolve_user_ref + DocCapability.add_comment 调用；截图保存 + page_info verify</done>
</task>

<task type="auto">
  <name>Task 4: e2e/05c_huly_4cap_doc_write_im_spec.py — Huly 4-cap E2E（二步流程 + per-user Channel）</name>
  <files>e2e/05c_huly_4cap_doc_write_im_spec.py</files>
  <action>
创建 `e2e/05c_huly_4cap_doc_write_im_spec.py`:

```python
"""Phase 5.C Huly 4-cap bundle E2E — 二步流程文档 + IMCapability per-user Channel send_card 验证。

测试链路（multi-capability 单 daemon 真接入）：
1. DocCapability.create_document → 二步流程（create shell → collab service createContent → update content=blobRef）
2. 验证 Huly UI 文档**真渲染 not blank**（Pitfall 1 P0 必防 — hr §4.3 教训）
3. IMCapability.send_card → per-user Channel `dm-{username}` 模式（hr §5.2 教训防回归 — 禁 chunter:DirectMessage 静默 reject）
4. 验证 Huly UI Channel 真出 card

依赖：
- Huly @ 192.168.2.44:8087（Phase 1 SSH tunnel 已配，CONTEXT specifics line 145）
- hr 已 seed 13 users + SocialIdentity + Employee mixin（CONTEXT specifics line 147）
- HulyPlugin daemon 已 attach huly_huly_net docker network（Phase 5.C Wave 1 5C-FW-01 落地）
- 用户 Chrome :9222 已登录 Huly admin

CLAUDE.md §2.2 + 全局 §1: 必走 browser-harness（CDP 直连用户 Chrome），禁止 Playwright。

License: 100% 独立创作；测试 Huly 二步流程行为，不复制 hr 实现。
"""
from __future__ import annotations

import os
import uuid

import httpx
import pytest


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.huly,
    pytest.mark.skipif(
        not os.environ.get("RUN_E2E"),
        reason="E2E 默认 skip，CI 显式 RUN_E2E=1 触发",
    ),
]


@pytest.fixture(scope="module")
def huly_test_username() -> str:
    """hr 已 seed 用户 username（demo.local domain）。"""
    return os.environ.get("HULY_E2E_TEST_USERNAME", "alice")


@pytest.fixture(scope="module")
def huly_test_teamspace_id() -> str:
    """Huly Teamspace _id（document 容器）— 用户 seed。"""
    tid = os.environ.get("HULY_E2E_TEAMSPACE_ID")
    if not tid:
        pytest.skip("HULY_E2E_TEAMSPACE_ID 未设置 — hr seed 后用户取 Teamspace _id 配 env")
    return tid


def test_huly_doc_write_two_step_render_and_im_send_card(
    browser_harness,
    huly_base_url,
    screenshot_dir,
    huly_test_username,
    huly_test_teamspace_id,
):
    """端到端：Huly 二步流程文档 + per-user Channel send_card + 视觉双验证。"""
    run_id = uuid.uuid4().hex[:8]
    title = f"E2E Huly {run_id}"
    markdown = (
        f"# Phase 5.C Huly 二步流程 E2E {run_id}\n\n"
        "## 验证目标\n\n"
        "1. collab service createContent 写入 blob ref 成功\n"
        "2. update_doc(content=blob_ref) 完成二步流程\n"
        "3. Huly UI 文档**真渲染**（不是 blank — Pitfall 1 P0 防护）\n"
    )

    api_base = os.environ.get("API_BASE_URL", "http://localhost:8000")
    workspace_id = os.environ.get("E2E_WORKSPACE_ID", "00000000-0000-0000-0000-000000000001")

    # Step 1: 调 agent-builder DocCapability.create_document → Huly 二步流程
    with httpx.Client(timeout=45.0) as client:
        resp = client.post(
            f"{api_base}/api/v1/test/doc_capability/create_document",
            json={
                "plugin_name": "huly",
                "workspace_id": workspace_id,
                "title": title,
                "markdown": markdown,
                "collection_id": huly_test_teamspace_id,
            },
        )
    assert resp.status_code == 200, f"Huly create_document 失败: {resp.text[:300]}"
    result = resp.json()
    huly_doc_id = result["native_id"]
    collab_blob_ref = result["extras"]["collab_blob_ref"]
    assert collab_blob_ref, f"二步流程未返回 collab_blob_ref（可能 collab service unreachable）: {result}"
    # blob ref 格式：{docId}-content-{timestamp}（hr §4.3）
    assert "content" in collab_blob_ref, f"blob_ref 格式异常: {collab_blob_ref}"

    # Step 2: browser-harness 打开 Huly Document UI 验证真渲染（Pitfall 1 P0）
    doc_url = f"{huly_base_url}/workbench/agent-builder-e2e/document?objectId={huly_doc_id}"
    doc_screenshot = screenshot_dir / f"huly_doc_{run_id}.png"
    bh_code_doc = f"""
import base64
import time
new_tab("{doc_url}")
wait_for_load()
time.sleep(4)  # Huly collab 渲染需时间
img_b64 = capture_screenshot()
with open("{doc_screenshot}", "wb") as f:
    f.write(base64.b64decode(img_b64))
info = page_info()
print("title:", info.get("title"))
print("url:", info.get("url"))
# 通过 DOM js 查询 doc title 元素验证渲染（用 js 而非 selector hunt — SKILL.md "What actually works"）
visible_text = js("document.body.innerText.slice(0, 500)")
print("visible_text_first_500:", visible_text)
"""
    result_doc = browser_harness(bh_code_doc, timeout=60.0)
    assert result_doc.returncode == 0, (
        f"Huly doc browser-harness 失败\nstdout={result_doc.stdout}\nstderr={result_doc.stderr}"
    )
    # Pitfall 1 P0 防护：UI 不能 blank — visible_text 必须含 run_id 或标题片段
    assert run_id in result_doc.stdout or "二步流程" in result_doc.stdout, (
        f"Huly UI blank — 二步流程未生效 (Pitfall 1)! visible_text={result_doc.stdout}"
    )

    # Step 3: IMCapability.send_card → per-user Channel `dm-{username}`（hr §5.2 防回归）
    with httpx.Client(timeout=30.0) as client:
        im_resp = client.post(
            f"{api_base}/api/v1/test/im_capability/send_card",
            json={
                "plugin_name": "huly",
                "workspace_id": workspace_id,
                "recipient": {"kind": "dm_user", "value": huly_test_username},
                "card_payload": {
                    "title": f"E2E Huly Card {run_id}",
                    "body": f"二步流程文档已创建：{title}",
                    "url": doc_url,
                },
                "idempotency_key": f"e2e-{run_id}",
            },
        )
    assert im_resp.status_code == 200, f"IMCapability send_card 失败: {im_resp.text[:300]}"
    im_result = im_resp.json()
    channel_id = im_result["extras"]["channel_id"]
    channel_name = im_result["extras"].get("channel_name", "")
    # hr §5.2：必须走 per-user Channel `dm-{username}` 命名（chunter:Channel）
    # NOT chunter:DirectMessage（server 静默 reject）
    assert channel_name.startswith("dm-") or huly_test_username in channel_name, (
        f"Channel naming 异常 — 可能仍走 chunter:DirectMessage (hr §5.2 P0 回归)! "
        f"channel_name={channel_name}"
    )

    # Step 4: browser-harness 打开 Huly Channel UI 视觉验证 card
    channel_url = f"{huly_base_url}/workbench/agent-builder-e2e/chunter?objectId={channel_id}"
    channel_screenshot = screenshot_dir / f"huly_channel_{run_id}.png"
    bh_code_channel = f"""
import base64
import time
new_tab("{channel_url}")
wait_for_load()
time.sleep(3)
img_b64 = capture_screenshot()
with open("{channel_screenshot}", "wb") as f:
    f.write(base64.b64decode(img_b64))
visible_text = js("document.body.innerText.slice(0, 800)")
print("channel_visible_text:", visible_text)
"""
    result_channel = browser_harness(bh_code_channel, timeout=45.0)
    assert result_channel.returncode == 0, (
        f"Huly channel browser-harness 失败: {result_channel.stderr}"
    )
    assert run_id in result_channel.stdout, (
        f"Channel UI 未渲染 card 含 run_id: {result_channel.stdout}"
    )
    assert channel_screenshot.exists()
```

避坑（hr 教训汇总）:
- **Pitfall 1 P0 防护**：必须验证 Huly UI 真渲染（`visible_text` 含 run_id / 标题）— blank 即说明二步流程未生效
- **hr §5.2 P0 防护**：必须验证 channel_name 是 `dm-{username}` 模式（chunter:Channel）— 防回归 chunter:DirectMessage
- 用户 Chrome 必须**已登录 Huly admin**（CDP 直连，cookie 保留）
- Huly collab 渲染异步 → `time.sleep(4)` 等渲染
- 用 `js("document.body.innerText.slice(0, 500)")` 取 DOM 文本而非 selector hunt（SKILL.md "What actually works"）
- `huly_test_teamspace_id` 必须从 hr seed 后 user 提供（spec 不创建 Teamspace）
- 单 daemon 4-cap：`/api/v1/test/doc_capability/...` + `/api/v1/test/im_capability/...` 复用同一个 huly plugin daemon（如未 reuse → daemon spawn 2 次说明 client lifecycle 有问题）

commit message: `test(05c-08): add Huly 4-cap E2E spec with two-step doc + per-user Channel verify (5C-SC-5, Pitfall 1, hr §5.2)`
  </action>
  <verify>
    <automated>test -f /Users/admin/ai/resume/interview/liuxin/agent-builder/e2e/05c_huly_4cap_doc_write_im_spec.py && python3 -c "import ast; src = open('/Users/admin/ai/resume/interview/liuxin/agent-builder/e2e/05c_huly_4cap_doc_write_im_spec.py').read(); ast.parse(src); assert 'sync_playwright' not in src; assert 'browser_harness' in src and 'new_tab' in src and 'capture_screenshot' in src and 'js(' in src; assert 'collab_blob_ref' in src, '必须 verify collab service blob ref'; assert 'dm-' in src or 'channel_name' in src, '必须 verify per-user Channel naming'; assert '192.168.2.44' in src or 'huly_base_url' in src; print('Huly spec OK')"</automated>
  </verify>
  <done>Huly E2E spec 存在；无 Playwright；含 browser-harness + js() DOM 查询；含 collab_blob_ref 验证（二步流程）+ per-user Channel `dm-` naming 验证（hr §5.2 防回归）；含 Pitfall 1 P0 防护（visible_text 非 blank）；两张截图（doc + channel）保存</done>
</task>

<task type="auto">
  <name>Task 5: scripts/license_attribution_audit.py — AGPL 防御 CI hook（5C-FW-04）</name>
  <files>scripts/license_attribution_audit.py</files>
  <action>
创建 `scripts/license_attribution_audit.py`:

```python
#!/usr/bin/env python3
"""License attribution audit — Phase 5.C 5C-FW-04 + Pitfall 8 CI hook。

扫描 backend/app/plugins/huly/_internal/*.py 每个文件必须包含 attribution 头注释：

    # Inspired by hr/offboarding-flow design under Apache-2.0 — not derived source

缺失任一文件 → exit 1 + stderr 打印缺失文件路径（fail-loud — 严禁静默通过）。

设计理由（CONTEXT Decision 8 + Pitfall 8）:
- hr/offboarding-flow 是 internal 研究稿，license 未明确（保守按可能 AGPL 处理）
- 本项目 Apache-2.0；不能拷贝 hr 源码
- 借鉴 hr 设计模式（rest_client / tx_factory / tx_operations / platform_client / collab RPC）必须每文件标注 attribution
- CI 跑此 script 阻断未标注文件入主分支

License: 100% 独立创作；纯文本审计逻辑。
"""
from __future__ import annotations

import sys
from pathlib import Path

REQUIRED_ATTRIBUTION = "Inspired by hr/offboarding-flow design under Apache-2.0 — not derived source"

# 默认扫描目标（CLI 可覆盖第 1 arg）
DEFAULT_SCAN_ROOT = Path("backend/app/plugins/huly/_internal")


def audit_directory(scan_root: Path) -> tuple[list[Path], list[Path]]:
    """扫描目录下所有 *.py 文件，返回 (compliant, missing) 两个列表。"""
    if not scan_root.exists():
        # 目录不存在 — 视为 0 文件（Phase 5.C 早期 plan 期合法）
        return [], []

    compliant: list[Path] = []
    missing: list[Path] = []

    for py_file in sorted(scan_root.rglob("*.py")):
        if py_file.name == "__init__.py":
            content = py_file.read_text(encoding="utf-8")
            if not content.strip():
                continue
        try:
            content = py_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError) as e:
            print(f"[WARN] 无法读 {py_file}: {e}", file=sys.stderr)
            missing.append(py_file)
            continue

        # 头部 30 行内必须含 attribution（避免误匹配代码中提到字符串）
        head = "\n".join(content.splitlines()[:30])
        if REQUIRED_ATTRIBUTION in head:
            compliant.append(py_file)
        else:
            missing.append(py_file)

    return compliant, missing


def main(argv: list[str]) -> int:
    """CLI 入口 — 返回 exit code（0 = 全合规 / 1 = 缺失文件 fail-loud）。"""
    if len(argv) > 1:
        scan_root = Path(argv[1])
    else:
        scan_root = DEFAULT_SCAN_ROOT

    compliant, missing = audit_directory(scan_root)

    print(f"License attribution audit: scan_root={scan_root}")
    print(f"  Compliant files: {len(compliant)}")
    print(f"  Missing attribution: {len(missing)}")

    if missing:
        print(
            f"\n[FAIL] {len(missing)} file(s) 缺少必需的 attribution 头注释 "
            f"({REQUIRED_ATTRIBUTION!r}):",
            file=sys.stderr,
        )
        for f in missing:
            print(f"  - {f}", file=sys.stderr)
        print(
            "\nFix: 在每个文件头部 docstring 后加：\n"
            f"    # {REQUIRED_ATTRIBUTION}\n",
            file=sys.stderr,
        )
        return 1

    print("[PASS] 所有 huly _internal 文件已含 attribution 头注释。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

避坑:
- **fail-loud**：发现缺失 → exit 1 + stderr 详细文件列表 + 修复指引（绝不静默 exit 0）
- 只扫头部 30 行 — 避免误匹配代码中字符串
- `__init__.py` 空文件跳过 — 但有实质内容仍审计
- CLI 可传第 1 arg 覆盖 scan_root（方便单测用 tmp_path）
- 目录不存在 → 视为 0 文件（早期 plan 期 huly/_internal 还未创建时合法）
- shebang `#!/usr/bin/env python3` + chmod +x 让 CI 直接调

执行后 `chmod +x scripts/license_attribution_audit.py`。

commit message: `feat(05c-08): add license attribution audit script (5C-FW-04 CI hook, Pitfall 8)`
  </action>
  <verify>
    <automated>test -f /Users/admin/ai/resume/interview/liuxin/agent-builder/scripts/license_attribution_audit.py && python3 -c "import ast; src = open('/Users/admin/ai/resume/interview/liuxin/agent-builder/scripts/license_attribution_audit.py').read(); ast.parse(src); assert 'Inspired by hr/offboarding-flow' in src; assert 'audit_directory' in src and 'def main' in src; assert 'sys.exit' in src or 'return 1' in src, '必须 fail-loud'; print('audit script OK')" && python3 /Users/admin/ai/resume/interview/liuxin/agent-builder/scripts/license_attribution_audit.py /tmp/nonexistent_dir_for_test 2>&1 | grep -q "Compliant files: 0"</automated>
  </verify>
  <done>scripts/license_attribution_audit.py 存在 + ast 解析通过 + 含 REQUIRED_ATTRIBUTION 常量 + main 函数 fail-loud (return 1)；不存在目录调用返回 0 + Compliant files: 0</done>
</task>

<task type="auto">
  <name>Task 6: backend/tests/platforms/test_license_attribution_audit.py — audit script 单测</name>
  <files>backend/tests/platforms/test_license_attribution_audit.py</files>
  <action>
创建 `backend/tests/platforms/test_license_attribution_audit.py`:

```python
"""License attribution audit script 单测 (Phase 5.C 08 / 5C-FW-04 / Pitfall 8)。

测试矩阵 (≥ 5 case)：
1. 全合规目录 → exit 0
2. 部分缺失 → exit 1 + stderr 含具体缺失文件名
3. 全缺失 → exit 1 + stderr 含每个文件
4. 不存在目录 → exit 0 (Compliant files: 0)
5. 空 __init__.py 跳过审计
6. 非空 __init__.py 审计
7. 头部 31 行后含 attribution 视为缺失（防误匹配代码字符串）

License: 100% 独立创作；纯单测逻辑。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
AUDIT_SCRIPT = REPO_ROOT / "scripts" / "license_attribution_audit.py"
ATTRIBUTION = "# Inspired by hr/offboarding-flow design under Apache-2.0 — not derived source"


def _run_audit(scan_root: Path) -> subprocess.CompletedProcess:
    """跑 audit script 并返回 CompletedProcess。"""
    return subprocess.run(
        [sys.executable, str(AUDIT_SCRIPT), str(scan_root)],
        capture_output=True,
        text=True,
        check=False,
        timeout=15.0,
    )


def _write_compliant(path: Path, name: str = "module.py") -> Path:
    f = path / name
    f.write_text(
        f'"""Test module."""\n{ATTRIBUTION}\n\ndef foo(): pass\n',
        encoding="utf-8",
    )
    return f


def _write_missing(path: Path, name: str = "module.py") -> Path:
    f = path / name
    f.write_text(
        '"""Test module without attribution."""\n\ndef foo(): pass\n',
        encoding="utf-8",
    )
    return f


def test_audit_script_exists():
    assert AUDIT_SCRIPT.exists(), f"audit script 必须存在: {AUDIT_SCRIPT}"


def test_all_compliant_exits_zero(tmp_path):
    """全合规目录 → exit 0 + stdout 含 PASS。"""
    _write_compliant(tmp_path, "rest_client.py")
    _write_compliant(tmp_path, "tx_factory.py")
    _write_compliant(tmp_path, "tx_operations.py")

    result = _run_audit(tmp_path)
    assert result.returncode == 0, f"全合规应 exit 0 — stderr={result.stderr}"
    assert "PASS" in result.stdout
    assert "Compliant files: 3" in result.stdout


def test_partial_missing_exits_one_with_filenames(tmp_path):
    """2 合规 + 1 缺失 → exit 1 + stderr 含缺失文件名（fail-loud）。"""
    _write_compliant(tmp_path, "rest_client.py")
    _write_compliant(tmp_path, "tx_factory.py")
    _write_missing(tmp_path, "tx_operations.py")  # 缺 attribution

    result = _run_audit(tmp_path)
    assert result.returncode == 1, f"缺失应 exit 1 — stdout={result.stdout}"
    assert "FAIL" in result.stderr
    assert "tx_operations.py" in result.stderr, (
        f"stderr 必须含具体缺失文件名（fail-loud）: {result.stderr}"
    )
    assert "Missing attribution: 1" in result.stdout


def test_all_missing_exits_one_lists_all(tmp_path):
    """全缺失 → exit 1 + stderr 含每个文件。"""
    f1 = _write_missing(tmp_path, "a.py")
    f2 = _write_missing(tmp_path, "b.py")
    f3 = _write_missing(tmp_path, "c.py")

    result = _run_audit(tmp_path)
    assert result.returncode == 1
    for name in ["a.py", "b.py", "c.py"]:
        assert name in result.stderr, f"{name} 必须在 stderr 列出"


def test_nonexistent_dir_exits_zero(tmp_path):
    """不存在目录 → exit 0 + Compliant files: 0（早期 plan 期合法）。"""
    nonexistent = tmp_path / "nonexistent_subdir"
    result = _run_audit(nonexistent)
    assert result.returncode == 0
    assert "Compliant files: 0" in result.stdout


def test_empty_init_py_skipped(tmp_path):
    """空 __init__.py 跳过审计。"""
    (tmp_path / "__init__.py").write_text("", encoding="utf-8")
    _write_compliant(tmp_path, "module.py")

    result = _run_audit(tmp_path)
    assert result.returncode == 0
    # 只 1 个 module.py 算 compliant，__init__.py 跳过
    assert "Compliant files: 1" in result.stdout


def test_nonempty_init_py_audited(tmp_path):
    """非空 __init__.py 必须含 attribution（否则 fail）。"""
    (tmp_path / "__init__.py").write_text(
        'from .module import foo\n',  # 非空但无 attribution
        encoding="utf-8",
    )

    result = _run_audit(tmp_path)
    assert result.returncode == 1
    assert "__init__.py" in result.stderr


def test_attribution_after_30_lines_treated_missing(tmp_path):
    """头部 30 行后含 attribution 视为缺失（防误匹配代码字符串）。"""
    content = '"""Docstring."""\n' + "\n" * 35 + f"{ATTRIBUTION}\n"
    (tmp_path / "module.py").write_text(content, encoding="utf-8")

    result = _run_audit(tmp_path)
    assert result.returncode == 1, "30 行后才出现 attribution 应视为缺失"
```

避坑:
- `REPO_ROOT` 用 `Path(__file__).resolve().parents[3]` 计算 — `backend/tests/platforms/test_*.py` 上推 3 级 = repo root
- 用 `subprocess.run` + `sys.executable` 跨 Python venv 调 script（不依赖 PATH）
- `tmp_path` fixture 自动隔离 — 每测独立目录
- 测试覆盖：合规 / 部分缺失 / 全缺失 / 不存在 / __init__.py 空跳过 / 非空审计 / 头部 30 行截断

commit message: `test(05c-08): add license attribution audit script unit tests (≥ 7 cases, 5C-FW-04)`
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -m pytest tests/platforms/test_license_attribution_audit.py -v 2>&1 | tail -20</automated>
  </verify>
  <done>≥ 7 单测全 pass；audit script 在 tmp_path 跑 → exit code 与预期一致；stderr 含缺失文件名（fail-loud 验证）</done>
</task>

<task type="auto">
  <name>Task 7: backend/tests/platforms_integration/test_run_viewer_structured_log_coverage.py — Pattern 7 schema 覆盖集成测</name>
  <files>backend/tests/platforms_integration/test_run_viewer_structured_log_coverage.py</files>
  <action>
创建 `backend/tests/platforms_integration/test_run_viewer_structured_log_coverage.py`:

```python
"""Pattern 7 structured log schema 覆盖集成测 (Phase 5.C 08 / Phase 7 Run Viewer 接力契约)。

验证：真 plugin daemon 调 DocCapability.create_document → caplog 捕获 `platform.plugin.invoke` LogRecord
→ 断言 6 字段全在（plugin_name / workspace_id / capability / method / latency_ms / outcome）+ extras dict。

若 Phase 7 Run Viewer 框架已就绪 → 走 Run Viewer log stream API verify schema；
若未做 → 降级 grep log file pattern verify。

测试矩阵 (≥ 3 case)：
1. 成功调用 → outcome="success" + latency_ms ≥ 0
2. 失败调用（mock plugin fails）→ outcome="error" + error 字段含异常类型
3. 多 capability 顺序调用 → 每 capability 一条 log + plugin_name 一致

License: 100% 独立创作；测试 schema 形状，不复制实现。
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from contextvars import ContextVar

import pytest

# 复用 Phase 5.B daemon client + Phase 5.A capability facade（如未导出 → fallback 到直调 log 函数）
try:
    from app.agent_builder.platforms.daemon_client import PlatformDaemonClient
    from app.agent_builder.platforms.capability_facades import DocCapabilityFacade
    HAS_DAEMON = True
except ImportError:
    HAS_DAEMON = False

# Pattern 7 schema — 6 必需字段
PATTERN_7_REQUIRED_FIELDS = {
    "plugin_name",
    "workspace_id",
    "capability",
    "method",
    "latency_ms",
    "outcome",
}

# Pattern 7 log message marker
LOG_MESSAGE = "platform.plugin.invoke"

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif(not HAS_DAEMON, reason="Phase 5.A/B daemon client 未就绪"),
]


def _extract_pattern7_extras(record: logging.LogRecord) -> dict:
    """从 LogRecord 提取 Pattern 7 extras 字段（structured log 用 extra= 参数注入到 record 属性）。"""
    return {
        field: getattr(record, field, None)
        for field in PATTERN_7_REQUIRED_FIELDS
    }


async def test_successful_capability_call_emits_pattern_7_log(caplog, mock_plugin_workspace):
    """成功调用：6 字段全在 + outcome=success + latency_ms ≥ 0。"""
    workspace_id = mock_plugin_workspace["workspace_id"]
    caplog.set_level(logging.INFO, logger="agent_builder.platform_plugin")

    async with PlatformDaemonClient(
        plugin_name="mock_plugin",
        workspace_id=workspace_id,
    ) as client:
        result = await client.invoke(
            capability="doc",
            method="create_document",
            params={"title": "Pattern 7 test", "markdown": "# Test"},
        )

    invoke_records = [r for r in caplog.records if r.message == LOG_MESSAGE]
    assert len(invoke_records) >= 1, (
        f"必须至少 1 条 `{LOG_MESSAGE}` log record；找到 {len(caplog.records)} 条 record"
    )

    rec = invoke_records[-1]
    extras = _extract_pattern7_extras(rec)
    missing = [f for f in PATTERN_7_REQUIRED_FIELDS if extras[f] is None and f != "workspace_id"]
    assert not missing, f"Pattern 7 缺字段 {missing}（实际 extras={extras}）"

    assert extras["plugin_name"] == "mock_plugin"
    assert extras["capability"] == "doc"
    assert extras["method"] == "create_document"
    assert extras["outcome"] == "success"
    assert isinstance(extras["latency_ms"], int) and extras["latency_ms"] >= 0


async def test_failed_capability_call_emits_outcome_error(caplog, mock_plugin_workspace):
    """失败调用：outcome=error + log 含异常类型 hint。"""
    workspace_id = mock_plugin_workspace["workspace_id"]
    caplog.set_level(logging.INFO, logger="agent_builder.platform_plugin")

    async with PlatformDaemonClient(
        plugin_name="mock_plugin_fails",
        workspace_id=workspace_id,
    ) as client:
        with pytest.raises(Exception):
            await client.invoke(
                capability="doc",
                method="create_document",
                params={"title": "fail", "markdown": "# Fail"},
            )

    invoke_records = [r for r in caplog.records if r.message == LOG_MESSAGE]
    assert any(getattr(r, "outcome", None) == "error" for r in invoke_records), (
        f"必须至少 1 条 outcome=error 的 log；实际 outcomes={[getattr(r, 'outcome', None) for r in invoke_records]}"
    )


async def test_multi_capability_call_each_emits_one_log(caplog, mock_plugin_workspace):
    """多 capability 顺序调用：每 capability 一条 log + plugin_name 一致。"""
    workspace_id = mock_plugin_workspace["workspace_id"]
    caplog.set_level(logging.INFO, logger="agent_builder.platform_plugin")

    async with PlatformDaemonClient(
        plugin_name="mock_multi_cap_plugin",
        workspace_id=workspace_id,
    ) as client:
        await client.invoke(capability="doc", method="create_document", params={"title": "a", "markdown": "x"})
        await client.invoke(capability="im", method="send_card", params={"recipient": "u1", "card_payload": {}})
        await client.invoke(capability="identity", method="resolve_user_ref", params={"user_ref": {"kind": "email", "value": "a@b.c"}})

    invoke_records = [r for r in caplog.records if r.message == LOG_MESSAGE]
    capabilities_logged = {getattr(r, "capability", None) for r in invoke_records}
    assert {"doc", "im", "identity"}.issubset(capabilities_logged), (
        f"3 capability 都需 log，实际 logged={capabilities_logged}"
    )
    # plugin_name 必一致
    plugin_names = {getattr(r, "plugin_name", None) for r in invoke_records}
    assert plugin_names == {"mock_multi_cap_plugin"}, (
        f"同 plugin 多 capability 必同 plugin_name；实际={plugin_names}"
    )


# 降级路径：如 Phase 7 Run Viewer log stream API 已实现，可加测验证 Run Viewer 能消费此 schema
# （本 plan 不强制 — Phase 7 plan 期落地 Run Viewer 时验证回环）


@pytest.fixture
async def mock_plugin_workspace(tmp_path):
    """mock workspace + 已 register 的 mock plugin (Phase 5.A 已就绪 fixture)."""
    workspace_id = uuid.uuid4()
    return {"workspace_id": str(workspace_id)}
```

避坑:
- `caplog.set_level(logging.INFO, logger="agent_builder.platform_plugin")` 必须显式指定 logger name（Pattern 7 用此 logger）
- LogRecord 的 `extra=` 字段会自动挂到 record 属性上（`getattr(record, "plugin_name", None)`）
- `workspace_id` 可为 None（fixture 未注入 contextvars 时）— skip 该字段的 None 检查
- 失败用例 `mock_plugin_fails` 假设 Phase 5.A mock_plugin 有 fail 变体（或在 conftest 内 mock）
- 如 daemon import 失败 → pytest.skip（避免 phase 早期 import 错误阻塞）
- Phase 7 Run Viewer 接力点：本测验证 schema 形状；Phase 7 实现时验证 Run Viewer UI 能正确渲染此 6 字段
- 降级方案：如真 daemon spawn 在 CI 慢 → fallback 到直调 `log_capability_call` 函数 unit-level verify schema

commit message: `test(05c-08): add Pattern 7 structured log coverage integration test (Phase 7 Run Viewer contract)`
  </action>
  <verify>
    <automated>test -f /Users/admin/ai/resume/interview/liuxin/agent-builder/backend/tests/platforms_integration/test_run_viewer_structured_log_coverage.py && python3 -c "import ast; src = open('/Users/admin/ai/resume/interview/liuxin/agent-builder/backend/tests/platforms_integration/test_run_viewer_structured_log_coverage.py').read(); ast.parse(src); assert 'PATTERN_7_REQUIRED_FIELDS' in src; required = {'plugin_name', 'workspace_id', 'capability', 'method', 'latency_ms', 'outcome'}; assert all(f in src for f in required), f'缺字段断言'; print('Pattern 7 schema test OK')"</automated>
  </verify>
  <done>集成测文件存在 + ast 解析通过 + 含 PATTERN_7_REQUIRED_FIELDS set + 含 6 字段全断言；≥ 3 测 case（success / error / multi-capability）；caplog 设 logger="agent_builder.platform_plugin"</done>
</task>

<task type="auto">
  <name>Task 8: 跑 Phase 5.A 271 platforms regression（出口 gate 1/3）</name>
  <files></files>
  <action>
**回归测试 — 不写代码，只跑 Phase 5.A 271 platforms tests 确认 0 fail。**

跑 Phase 5.A regression（CONTEXT specifics 提到 Phase 5.A 162 + 5.B Plan 04-05 109 = 271 platforms unit tests）：

```bash
cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && \
  python -m pytest tests/platforms/ -x --tb=short 2>&1 | tee /tmp/05c-08-platforms-regression.log
```

**验收准则：**
- `0 failed` 必须
- 含本 plan 新加的 `test_license_attribution_audit.py` ≥ 7 测（如计数已变 → 验证 + 在 SUMMARY.md 注明）
- 总数应 ≥ 271 + 本 plan 加的 7 = 278

**如有 fail：**
- 不允许 skip / xfail / 改测试期望
- 必须修源代码使测试通过 — 这是 Phase 5.C 出口 gate
- 失败原因记入本 plan SUMMARY.md "Regression 处理" 小节

无 commit（仅跑测试 + 把 log 存 `/tmp/05c-08-platforms-regression.log` 给后续 VERIFICATION 引用）。
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -m pytest tests/platforms/ --tb=no -q 2>&1 | tail -5 | grep -E "passed|failed" | grep -v "failed"</automated>
  </verify>
  <done>`pytest backend/tests/platforms/` 报告 `N passed, 0 failed`（N ≥ 271 + 本 plan 加的 7 测）；regression log 保存到 /tmp/</done>
</task>

<task type="auto">
  <name>Task 9: 跑 Phase 5.B 5/5 acid test + 集成测 regression（出口 gate 2/3）</name>
  <files></files>
  <action>
**回归测试 — 跑 Phase 5.B acid test + fault_isolation 5/5 测确认 0 fail。**

```bash
cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && \
  python -m pytest \
    tests/platforms_integration/test_huly_acid_test.py \
    tests/platforms_integration/test_fault_isolation.py \
    -v --tb=short 2>&1 | tee /tmp/05c-08-acid-test-regression.log
```

**验收准则：**
- `5 passed` 必须（test_huly_acid_test.py + test_fault_isolation.py 共 5 测，per Phase 5.B VERIFICATION.md baseline）
- 0 failed
- 含本 plan 新加的 `test_run_viewer_structured_log_coverage.py` ≥ 3 测（如 daemon 不可用 → skip 算 pass）

**如 daemon spawn 失败（CI 环境）：**
- 集成测 skip 是合法的（Pattern 7 测有 `skipif not HAS_DAEMON`）
- 但 5/5 acid test 必须真跑 — 不允许 skip

**如有 fail：**
- 修源代码（不改测试）
- 记入 SUMMARY.md

无 commit（仅跑测试 + log 保存）。

**额外（如有时间）：** 也跑 Phase 4 IM 81 测确认无回归（CLAUDE.md §2.2 三层测试要求）：
```bash
cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && \
  python -m pytest tests/test_im_provider_*.py tests/notification/ -q --tb=no 2>&1 | tail -3
```
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -m pytest tests/platforms_integration/test_huly_acid_test.py tests/platforms_integration/test_fault_isolation.py --tb=no -q 2>&1 | tail -3 | grep -E "passed" | grep -v "failed"</automated>
  </verify>
  <done>5/5 acid test 全绿（5 passed, 0 failed）；regression log 保存；如 Pattern 7 集成测 skip → 在 SUMMARY 注明原因</done>
</task>

<task type="auto">
  <name>Task 10: 写 .planning/phases/05c-doc-capability/05c-VERIFICATION.md 草稿（出口 gate 3/3）</name>
  <files>.planning/phases/05c-doc-capability/05c-VERIFICATION.md</files>
  <action>
**写 Phase 5.C 整 phase 的 VERIFICATION.md 草稿** —— 参照 Phase 5.B VERIFICATION.md 格式（`.planning/phases/05b-plugin-sandbox/05b-VERIFICATION.md`），覆盖 plan 01-08 全 DoD truth + Phase 5.C ROADMAP Success Criteria 1-5。

**文档结构（必含 6 节）：**

```markdown
---
phase: 05c-doc-capability
verified: 2026-05-18T00:00:00+08:00
status: draft  # 本 plan 出草稿；正式 verify 在 /gsd:verify-work 时改 passed/failed
score: TBD
re_verification: false
---

# Phase 5.C: DocCapability 真接入 Verification Report (Draft)

**Phase Goal:** Outline + Lark + Huly multi-capability plugin 真实跑通，CRDT collab edit 不冲突
**Drafted:** 2026-05-18 (Plan 08 produced)
**Status:** DRAFT — 正式 verify 在 `/gsd:verify-work` 阶段填 Evidence 列

---

## Goal Achievement

### Observable Truths

逐 plan 01-08 的 must_haves.truths 列表 → 在此表汇总：

| Plan | # | Truth | Status | Evidence |
|------|---|-------|--------|----------|
| 01 | 1 | (从 plan 01 PLAN.md must_haves 抄) | TBD | (verify 期填) |
| 01 | 2 | ... | TBD | ... |
| 02 | 1 | OutlinePlugin manifest + 6 method 实现 | TBD | ... |
| ... | | | | |
| 08 | 1 | Dify integration_tests + browser-harness 阅读文档已 commit | TBD | docs/reading-dify-05c-08-...md ≥ 80 行 + commit hash |
| 08 | 2 | browser-harness Outline E2E spec 真出文档 | TBD | e2e/05c_outline_doc_write_spec.py + RUN_E2E=1 跑通截图 |
| 08 | 3 | browser-harness Lark E2E spec 真出飞书文档 + @ 人 verify | TBD | ... |
| 08 | 4 | browser-harness Huly E2E spec 二步流程 + per-user Channel | TBD | ... |
| 08 | 5 | license_attribution_audit exit 1 fail-loud | TBD | scripts/...py + pytest 7 测 |
| 08 | 6 | Pattern 7 schema 6 字段覆盖集成测 | TBD | pytest tests/...py ≥ 3 测 |
| 08 | 7 | Phase 5.A 271 regression 0 fail | TBD | /tmp/05c-08-platforms-regression.log |
| 08 | 8 | Phase 5.B 5/5 acid regression 0 fail | TBD | /tmp/05c-08-acid-test-regression.log |

**Score: TBD/TBD truths verified** (verify 期算)

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/plugins/outline/outline_plugin.py` | OutlinePlugin manifest + 6 method | TBD | plan 02 deliverable |
| `backend/app/plugins/lark_docs/lark_docs_plugin.py` | LarkDocsPlugin + markdown→blocks | TBD | plan 03 deliverable |
| `backend/app/plugins/huly/huly_plugin.py` | HulyPlugin 4-cap bundle | TBD | plan 05 deliverable |
| `backend/app/plugins/huly/_internal/rest_client.py` | hr port 286 行 + attribution | TBD | plan 04 deliverable |
| `backend/app/plugins/huly/_internal/tx_factory.py` | hr port 220 行 + attribution | TBD | plan 04 deliverable |
| `backend/app/plugins/huly/_internal/tx_operations.py` | hr port 182 行 + attribution | TBD | plan 04 deliverable |
| `backend/app/plugins/huly/_internal/platform_client.py` | hr port 76 行 + attribution | TBD | plan 04 deliverable |
| `backend/app/plugins/huly/_internal/constants.py` | hr port 72 行 + attribution | TBD | plan 04 deliverable |
| `backend/app/plugins/huly/_internal/markdown_to_prosemirror.py` | marko→ProseMirror + attribution | TBD | plan 04 deliverable |
| `backend/app/plugins/huly/_internal/collab_client.py` | HulyCollabClient + attribution | TBD | plan 05 deliverable |
| `e2e/05c_outline_doc_write_spec.py` | browser-harness Outline E2E | TBD | plan 08 deliverable |
| `e2e/05c_lark_docs_doc_write_spec.py` | browser-harness Lark E2E | TBD | plan 08 deliverable |
| `e2e/05c_huly_4cap_doc_write_im_spec.py` | browser-harness Huly E2E | TBD | plan 08 deliverable |
| `scripts/license_attribution_audit.py` | CI hook fail-loud | TBD | plan 08 deliverable |
| `.planning/phases/05c-doc-capability/05c-VERIFICATION.md` | 本文档 | YES | self-reference |
| 8 reading docs (Plan 01-08) | Dify reading doc ≥ 80 行 each | TBD | plan 01-08 Task 0 |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| OutlinePlugin.doc.create_document | Outline /api/documents.create | httpx + api_token Bearer | TBD | plan 02 + plan 08 E2E |
| LarkDocsPlugin.doc.create_document | Lark /docx/v1/documents | lark-oapi async wrapper | TBD | plan 03 + plan 08 E2E |
| HulyPlugin.doc.create_document | Huly REST + collab service RPC | 二步流程（hr §4.3）| TBD | plan 05 + plan 08 E2E (Pitfall 1 防护) |
| HulyPlugin.im.send_card | per-user Channel `dm-{username}` | hr §5.2 防 chunter:DirectMessage | TBD | plan 05 + plan 08 E2E |
| HulyPlugin.identity.resolve_user_ref | SocialIdentity → Employee mixin | LRU cache (hr §5.5) | TBD | plan 05 |
| All capability calls | Pattern 7 structured log | log_capability_call() | TBD | plan 07 + plan 08 集成测 |
| huly/_internal/*.py | attribution 头注释 | grep `Inspired by hr/offboarding-flow` | TBD | plan 08 audit script |

---

### Requirements Coverage (Success Criteria 1-5 + FW-01..04)

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| 5C-SC-1 | 02 | OutlinePlugin manifest + 6 method + 集成测 | TBD | plan 02 三层测试 + plan 08 Outline E2E |
| 5C-SC-2 | 03 | LarkDocsPlugin markdown→blocks + 评论 @ 人 | TBD | plan 03 三层测试 + plan 08 Lark E2E |
| 5C-SC-3 | 05 | HulyPlugin DocCapability 二步流程 + collab apply | TBD | plan 05 三层测试 + plan 08 Huly E2E (Pitfall 1) |
| 5C-SC-4 | (v1.5 deferred) | doc_write/doc_mention 节点 + AI suggest | DEFERRED | Capability + ai_suggest_mentions 接口 in plan 06 |
| 5C-SC-5 | 08 | E2E browser-harness DAG → 真出文档 + @ 提醒 | TBD | plan 08 三 spec 真跑 |
| 5C-FW-01 | 01 | SandboxRunner docker_networks 字段扩展 | TBD | plan 01 deliverable |
| 5C-FW-02 | 04 | hr B-full-channel 1454 行 port | TBD | plan 04 deliverable (836 行 70% 零改 + 551 行 capability 改造) |
| 5C-FW-03 | 05+06 | Multi-capability plugin 1 daemon 4 facet 测试 | TBD | plan 05 unit + integration + plan 08 E2E |
| 5C-FW-04 | 08 | License attribution CI hook | TBD | plan 08 audit script + pytest 7 测 |

---

### Anti-Patterns Found

(verify 期填 — 复查 plan 01-08 是否有以下问题：)
- Playwright spec 写新增 5.C 文件（违反 CLAUDE.md §2.2 强制 browser-harness）
- 拷贝 hr 源码（违反 CONTEXT Decision 8 + Pitfall 8）
- daemon 内直调 LLM（违反 Pitfall 8 跨进程隔离）
- mock huly server 替代真实例 E2E（违反 Decision 9 三层测试）

---

### Pitfall 防护落地验证

| Pitfall | 防护描述 | 落地验证 |
|---------|----------|----------|
| Pitfall 1 | Huly content 字段非 raw markdown — 必走 collab service blob ref | plan 05 二步流程 + plan 08 Huly E2E visible_text 非 blank 断言 |
| Pitfall 2 | Huly DM chunter:DirectMessage 静默 reject — 走 per-user Channel | plan 05 IMCapability 默认 dm_user → dm-{username} + plan 08 E2E channel_name 断言 |
| Pitfall 3 | Lark blocks/convert 10MB / 1000 block 限制 | plan 03 chunking + 测试 |
| Pitfall 4 | Outline rate limiter 429 | plan 02 tenacity AsyncRetrying |
| Pitfall 5 | docker network attach 失败 | plan 01 SandboxRunner docker_networks + plan 04 集成测 |
| Pitfall 6 | marko AST 节点名 vs ProseMirror 节点名 | plan 04 markdown_to_prosemirror mapping + 单测 |
| Pitfall 7 | AllowlistTransport host wildcard | (Phase 5.B 已锁 exact match — 本 phase 不扩) |
| Pitfall 8 | hr port 文件无 attribution → AGPL 风险 | plan 08 audit script CI hook fail-loud |
| Pitfall 9 | lark_open_id vs PersonUuid 双源 | plan 03 + plan 05 各自缓存（Phase 5.D 反向 sync 解决） |
| Pitfall 10 | HulyPlatformClient daemon 内单例 + 多 facet 并发死锁 | plan 05 asyncio.Lock + 集成测 |
| Pitfall 11 | prosemirror ListItem 必须含 paragraph | plan 04 schema 校验 + 单测 |
| Pitfall 12 | tenacity AsyncRetrying 与 daemon timeout 叠加 | plan 02 + plan 03 retry config |

---

### Pattern 7 Run Viewer 接力契约

Phase 7 Run Viewer 将消费 `agent_builder.platform_plugin` logger 的 `platform.plugin.invoke` LogRecord：
- 必需 6 字段已固化（plan 08 Pattern 7 测保证 schema 稳定）
- Phase 7 plan 期可基于此 schema 直接渲染 Run Viewer UI

---

## Next Steps

- 待 `/gsd:execute-phase 05c` 全 plan 完成后跑 `/gsd:verify-work 05c` 把 TBD 全填 Evidence
- Phase 5.D 接力：HRCapability + Identity 反向 sync（dept: 表达式 + watch_user_changes）

---

*Draft generated by plan 08 (Wave 5 出口 gate)；正式 verify 由 `/gsd:verify-work` 触发。*
```

避坑:
- 状态用 `draft` 不是 `passed/failed` —— 正式 verify 在 `/gsd:verify-work` 阶段
- 所有 Status 列填 `TBD` —— 让 verify 期机械化对照
- Evidence 列指向具体文件 + 测试输出 log 路径
- 不重复 plan PLAN.md 内容 — 仅汇总 must_haves 形成全 phase 视图
- Pattern 7 / Pitfall / Anti-pattern 部分必须含 —— 这是 verify 期复查依据
- 文档至少 100 行才有意义

commit message: `docs(05c-08): draft Phase 5.C VERIFICATION.md covering plan 01-08 DoD truths + ROADMAP SC 1-5`
  </action>
  <verify>
    <automated>test -f /Users/admin/ai/resume/interview/liuxin/agent-builder/.planning/phases/05c-doc-capability/05c-VERIFICATION.md && wc -l /Users/admin/ai/resume/interview/liuxin/agent-builder/.planning/phases/05c-doc-capability/05c-VERIFICATION.md | awk '{exit ($1 >= 100 ? 0 : 1)}' && grep -q "Goal Achievement" /Users/admin/ai/resume/interview/liuxin/agent-builder/.planning/phases/05c-doc-capability/05c-VERIFICATION.md && grep -q "Observable Truths" /Users/admin/ai/resume/interview/liuxin/agent-builder/.planning/phases/05c-doc-capability/05c-VERIFICATION.md && grep -q "Required Artifacts" /Users/admin/ai/resume/interview/liuxin/agent-builder/.planning/phases/05c-doc-capability/05c-VERIFICATION.md && grep -q "5C-SC-5" /Users/admin/ai/resume/interview/liuxin/agent-builder/.planning/phases/05c-doc-capability/05c-VERIFICATION.md && grep -q "status: draft" /Users/admin/ai/resume/interview/liuxin/agent-builder/.planning/phases/05c-doc-capability/05c-VERIFICATION.md</automated>
  </verify>
  <done>05c-VERIFICATION.md ≥ 100 行 + status=draft + 含 Goal Achievement / Observable Truths / Required Artifacts / 5C-SC-1..5 / Pitfall 防护落地 / Pattern 7 接力 6 节</done>
</task>

</tasks>

<verification>
**Plan 08 phase-local checks**:
- [ ] Reading doc commit hash 早于 Task 1-10 任一 feat/test commit（CLAUDE.md §2.7 校验）
- [ ] `pytest e2e/05c_outline_doc_write_spec.py --collect-only` 显示 1 test 收集成功（不真跑）
- [ ] `pytest e2e/05c_lark_docs_doc_write_spec.py --collect-only` 显示 1 test
- [ ] `pytest e2e/05c_huly_4cap_doc_write_im_spec.py --collect-only` 显示 1 test
- [ ] `pytest backend/tests/platforms/test_license_attribution_audit.py -v` ≥ 7/7 pass
- [ ] `pytest backend/tests/platforms_integration/test_run_viewer_structured_log_coverage.py --collect-only` ≥ 3 tests collected
- [ ] `python3 scripts/license_attribution_audit.py /tmp/nonexistent` exit 0
- [ ] `python3 scripts/license_attribution_audit.py backend/app/plugins/huly/_internal` exit 0（如 plan 04-05 全部加 attribution）或 exit 1（仍有缺失 → 必须修，不能 skip）

**Phase 5.A regression**:
- [ ] `pytest backend/tests/platforms/ --tb=no -q` 0 fail（含本 plan 加的 7 测）

**Phase 5.B regression**:
- [ ] `pytest backend/tests/platforms_integration/test_huly_acid_test.py test_fault_isolation.py -v` 5/5 pass

**E2E 真跑（user 端机器，CI 可 skip）**:
- [ ] `RUN_E2E=1 pytest e2e/05c_outline_doc_write_spec.py -v` 全绿（用户启动 Chrome :9222 + Outline @ .44 + OUTLINE_API_TOKEN env）
- [ ] `RUN_E2E=1 pytest e2e/05c_lark_docs_doc_write_spec.py -v` 全绿（用户 Chrome 已登录飞书 + LARK_E2E_TEST_USER_EMAIL env）
- [ ] `RUN_E2E=1 pytest e2e/05c_huly_4cap_doc_write_im_spec.py -v` 全绿（用户 Chrome 已登录 Huly + HULY_E2E_TEAMSPACE_ID env）
- [ ] 截图 ≥ 4 张保存到 docs/e2e-screenshots-2026-05-18/

**VERIFICATION.md gate**:
- [ ] `.planning/phases/05c-doc-capability/05c-VERIFICATION.md` 存在 + status=draft + ≥ 100 行
- [ ] 含 plan 01-08 全 must_haves.truths 汇总（即使 Status=TBD）
- [ ] 含 ROADMAP Success Criteria 1-5 对应表

**Reading doc gate**:
- [ ] `git log --oneline -20 | grep "docs(05c-08)" | head -1` 是 Task 0 reading doc，commit 早于任何 feat(05c-08)/test(05c-08) commit
</verification>

<success_criteria>
1. **Reading doc gate**: docs/reading-dify-05c-08-e2e-gate-2026-05-18.md ≥ 80 行 + 5-6 借鉴点明确 source→target + commit 在前（CLAUDE.md §2.7）
2. **browser-harness 强制**: 3 个 05c_*.py spec **零 Playwright 引用**（grep `sync_playwright` 0 hits）+ 全用 `browser_harness` fixture + `new_tab` + `capture_screenshot` + `js()` helper
3. **Outline E2E 真跑通**: RUN_E2E=1 时 spec 调 real Outline @ 192.168.2.44:3000 出文档 + 截图保存 + page_info verify
4. **Lark E2E 真跑通**: RUN_E2E=1 时 spec 调 real Lark + IdentityCapability.resolve_user_ref + add_comment(@open_id) + UI 截图
5. **Huly E2E 真跑通**: RUN_E2E=1 时 spec 调 real Huly @ 192.168.2.44:8087 + collab_blob_ref 验证（二步流程）+ per-user Channel `dm-` naming 验证（hr §5.2 防回归）+ Pitfall 1 P0 防护（visible_text 非 blank）
6. **License attribution audit**: scripts/license_attribution_audit.py fail-loud + ≥ 7 单测全绿 + 跑实际 huly/_internal/ 目录返回 exit 0（如有缺失必须修）
7. **Pattern 7 structured log coverage**: 集成测断言 6 字段（plugin_name/workspace_id/capability/method/latency_ms/outcome）+ outcome enum（success/error）+ multi-capability plugin_name 一致
8. **Phase 5.A regression**: `pytest backend/tests/platforms/` 0 fail（≥ 271 + 本 plan 加的 7 测）
9. **Phase 5.B regression**: `pytest backend/tests/platforms_integration/test_huly_acid_test.py test_fault_isolation.py` 5/5 pass
10. **VERIFICATION.md 草稿**: status=draft + ≥ 100 行 + 含 Observable Truths / Artifacts / Key Links / Requirements Coverage / Anti-Patterns / Pitfall 防护 / Pattern 7 接力 6 节 + 覆盖 plan 01-08 全 must_haves
11. **三层测试齐**: unit (audit script 7 测) + integration (Pattern 7 schema ≥ 3 测) + E2E (3 browser-harness spec)
12. **Phase 5.C 出口 gate 三项全绿**: 5.A regression + 5.B acid test regression + plan 01-08 全 plugin 三层测试通过
</success_criteria>

<output>
完成后创建 `.planning/phases/05c-doc-capability/05c-08-SUMMARY.md`，至少含:
- Reading doc 链接 + commit hash + 5-6 借鉴点摘要
- 3 个 E2E spec 真跑结果（如 RUN_E2E=1 在用户机器跑过 → 贴截图链接 + 跑出的文档 URL）
- license attribution audit script 跑 backend/app/plugins/huly/_internal/ 实际目录的输出（Compliant N, Missing 0）
- Pattern 7 集成测 caplog 输出片段（证明 6 字段都 emit 了）
- Phase 5.A regression 数字（X passed, 0 failed）+ log path `/tmp/05c-08-platforms-regression.log`
- Phase 5.B 5/5 acid test regression 数字 + log path
- VERIFICATION.md 草稿 path + 覆盖的 plan 01-08 must_haves 总数
- **Dify 参考点** 小节：指回 reading doc 5-6 借鉴点对应实现
- **Regression 处理** 小节（如遇 fail 必须记录修复过程，不允许 skip）
- **Phase 5.C 出口总结**: 12 success criteria 逐条 ✓ / X 状态
- **Phase 5.D 接力点**: HRCapability + Identity 反向 sync 准备就绪信号（Pattern 7 log + per-user Channel + LRU cache 已落地）
</output>
