# 参考阅读笔记 — Phase 5.C E2E gate (browser-harness)

> 日期: 2026-05-18
> 仓库1: https://github.com/langgenius/dify (local clone `/Users/admin/ai/ref/dify/repo/`, AGPL-3.0)
> 仓库2: https://github.com/browser-use/browser-harness (local clone `/Users/admin/ai/ref/agent/browser-harness/`, MIT, ~13k stars)
> Stars: Dify ~141k / browser-harness ~13k
> Plan: `.planning/phases/05c-doc-capability/05c-08-PLAN.md` (Wave 5 收官 gate)

## 项目概述（一句话）

Dify 是国内最成熟的 LLM 应用平台（含 workflow 编排），其 `api/tests/integration_tests/` 是真跑 workflow + DB + Redis 的工程集成测样板；browser-harness 是 CDP 直连用户已开 Chrome 的 self-improving Python harness，每次跑都让 agent 改进 `agent-workspace/agent_helpers.py`。本 plan 05c-08 借鉴 Dify integration_tests **fixture 风格** + 用 browser-harness 跑真 plugin（Outline + Lark + Huly）出口 E2E，并机械化扫 license attribution 防 Pitfall 8 AGPL 污染。

## 技术栈对照

| 维度 | Dify | browser-harness | 本项目 05c-08 |
|------|------|------|------|
| 测试粒度 | integration_tests（真 DB/真 Redis/真 LLM，无 mock） | E2E（真用户 Chrome :9222） | 集成测 + browser-harness E2E + license audit 双层 gate |
| Fixture 模式 | `pytest.fixture` + `Workflow` 真实例 + `workflow_run.outputs` 断言 | heredoc `browser-harness <<'PY' ... PY` + helpers 预导入（`new_tab` / `capture_screenshot` / `click_at_xy` / `js`） | `e2e/conftest.py` 提供 `screenshot_dir` / `outline_base_url` / `huly_base_url` 三 session fixture |
| 浏览器策略 | 不涉及（后端集成测） | **CDP 直连用户运行中 Chrome**（不起 headless），保留登录态/cookie/扩展 | 用户 Chrome :9222 → CDP → `new_tab` 三 spec 共享同一 daemon |
| 与 Playwright 关键差异 | Dify 不跑前端 E2E（仅 cypress 简单 smoke） | self-improving + heredoc 防 shell quote mangling + 坐标点击优先（不 selector hunt） | 历史 Playwright `*.spec.ts` 保留不删，新 5.C spec 用 Python browser-harness（CLAUDE.md §2.2 + memory feedback_e2e_browser_harness_only） |
| 状态校验 | `assert workflow.features_dict == EXPECTED` | `capture_screenshot()` → 读图找目标 → 操作 → 再 `capture_screenshot()` verify | DAG 跑完后双重 verify：API state 读 + browser-harness 截图视觉确认 |

**关键发现**：Dify `api/tests/integration_tests/workflow/test_sync_workflow.py` 仅 57 行，主要做 DSL 字段兼容性校验，**不是真 spawn workflow 进程**——这反过来证明 browser-harness 真 CDP E2E 对我们项目更合适：我们要验证的是「DAG 编排 → plugin daemon → 真 SaaS 出文档 + UI 真渲染」全链路，远比 Dify 集成测覆盖的范围深。

## 架构要点

三层串联（文字简图）：

```
[ pytest -m e2e ]                          ← 入口
        │
        ▼
[ e2e/conftest.py session fixture ]        ← Task 1 产出
   • screenshot_dir (docs/e2e-screenshots-2026-05-18/)
   • outline_base_url=http://192.168.2.44:3000
   • huly_base_url=http://192.168.2.44:8087
        │
        ▼
[ 3 个 browser-harness Python spec ]       ← Task 2-4 产出（Outline / Lark / Huly）
   • subprocess.run(["browser-harness"], input=heredoc_py, text=True)
   • 每个 spec：DAG 配 doc_write 节点 → POST publish + run → 等终态 → CDP 验真渲染
        │
        ▼
[ browser-harness daemon @ /tmp/bu-default.sock ]
        │
        ▼ CDP WS
[ 用户已开 Chrome :9222 ]                   ← Way 2: --remote-debugging-port=9222
        │
        ▼ Input.dispatchMouseEvent (compositor 层穿透 iframe/shadow)
[ 真 Outline .44:3000 / Lark Cloud / Huly .44:8087 UI ]
        │
        ▼
[ structured log assert (6 字段) + license audit + Phase 5.A/B regression ]
        │
        ▼
[ VERIFICATION.md 草稿（plan 01-08 全 DoD truth） ]
```

边界约束：E2E **不 mock 任何外部服务**——Outline / Lark / Huly 都是真实例；plugin daemon 真 spawn；docker network attach 真走（Pitfall 5 三模式触发）。

## 可借鉴的设计模式

1. **Dify integration_tests fixture 模式 → 我们 conftest 风格**
   - Source: `/Users/admin/ai/ref/dify/repo/api/tests/integration_tests/workflow/test_sync_workflow.py:44` `def test_workflow_features()` 用真 `Workflow` model 构造而非 mock
   - Target: `e2e/conftest.py` 三 session fixture（`screenshot_dir` / `outline_base_url` / `huly_base_url`） + 每 spec 自己组装 `dsl_builder` 而非引入 framework 抽象
   - Why：Dify 60+ integration test 都坚持「真对象 + 真断言」，从未引入 mock layer；我们 plan 5C-SC-5 必须真出文档，同样禁 mock

2. **browser-harness `capture_screenshot()` first → `click_at_xy()` → re-screenshot verify**（替代 Playwright locator 路径）
   - Source: `/Users/admin/ai/ref/agent/browser-harness/SKILL.md` "What actually works" §84-85 「Suppress the Playwright-habit reflex of 'locate first, then click' — no getBoundingClientRect, no selector hunt」
   - Target: 三 spec（`test_doc_write_outline_*.py` / `_lark_*.py` / `_huly_*.py`）必走「截图 → 读 pixel → 坐标点 → 再截图 verify」，**禁止** `page.locator("h1:has-text(...)")` Playwright 风格的等待
   - Why：CDP `Input.dispatchMouseEvent` 在 Chrome 浏览器进程做 hit-testing，自动穿透 iframe / shadow DOM / cross-origin；Outline 富文本编辑器和 Huly 协作编辑器都重 iframe，selector 路径会被 framework hack 拖死

3. **heredoc 调用约定 `browser-harness <<'PY' ... PY`（防 shell quote mangling）**
   - Source: `SKILL.md` §14-26 「Use the heredoc form for every multi-line command. It prevents shell quote mangling inside Python strings and JavaScript snippets.」
   - Target: 每个 spec 用 `subprocess.run(["browser-harness"], input=textwrap.dedent("""..."""), text=True, capture_output=True, check=True)` 把 Python payload 通过 stdin 灌入，**禁止**在命令行里拼 `-c "<python code>"`（双引号 + JS 字符串会被 shell 拆碎）
   - Why：本 plan 三 spec 都要在 `js()` 里嵌 JS 选择器 + 中文字符串（如 `"E2E 测试文档"`），heredoc 是唯一保 quote 安全的入口

4. **CDP 直连用户 Chrome 保留登录态（避免重复登录摩擦）**
   - Source: `install.md` §"Way 1: chrome://inspect" + `SKILL.md` §"Design constraints" 「Connect to the user's running Chrome. Don't launch your own browser.」
   - Target: 文档化要求用户启动 Chrome 时带 `--remote-debugging-port=9222 --user-data-dir=~/.chrome-e2e`（install.md Way 2，避开 macOS 平台默认 dir 被 silently no-op 的坑），登录 Outline / Lark / Huly 一次后 session cookie 复用整个 5.C suite
   - Why：Lark Cloud SSO 走多步 OAuth，Huly 需 workspace token，每次 spec 重登要花 30s+；CDP 直连让首登 cookie 沉淀到 user-data-dir，后续所有 spec 零成本复用

5. **Pattern 7 structured log 6 字段断言（Phase 7 Run Viewer 契约保证）**
   - Source: `.planning/phases/05c-doc-capability/05c-RESEARCH.md` §Pattern 7 (line 794-836) `log_capability_call(plugin_name=, capability=, method=, latency_ms=, outcome=, **extras)` + Phase 5.B `PlatformDaemonClient.invoke` 已有埋点
   - Target: Task 6 `backend/tests/platforms/test_structured_log_coverage.py` — 真跑 doc_capability.write_document → 解析 stdout JSON line → 断言 6 个必填字段（`plugin_name` / `workspace_id` / `capability` / `method` / `latency_ms` / `outcome`）每条都齐 + `outcome` 在合法集 `{"success","error","timeout","blocked"}` 内
   - Why：Phase 7 Run Viewer 完全靠这 6 字段做时间线与过滤；本 plan 必须固化字段契约，否则 Phase 7 接力时会大返工

6. **license_attribution_audit fail-loud CI 钩子设计（Pitfall 8 防御）**
   - Source: `.planning/phases/05c-doc-capability/05c-RESEARCH.md` §Pattern 12 「license + AGPL 防御 — grep `# Inspired by` 注释在每 huly 文件」+ §Common Pitfalls #8 hr 是 Apache-2.0 但 Huly server 是 AGPL，port 文件必须显式声明非 derived source
   - Target: `scripts/license_attribution_audit.py` 扫 `backend/app/plugins/huly/_internal/*.py`，每个文件首 20 行必含 `# Inspired by hr/offboarding-flow design under Apache-2.0 — not derived source`，缺一个 `sys.exit(1)` + stderr 列出缺失文件名；`backend/tests/platforms/test_license_attribution_audit.py` 用 `tmp_path` 造 3 文件（2 合规 + 1 缺）→ `subprocess.run` script → 断言 exit code 1 + stderr 含缺失文件名
   - Why：手工 review 必会漏，机械化 audit 是唯一可信 gate；fail-loud（exit 1）比 warning 更安全——CI 阻断 vs 静默通过的代价差 100x

7. **browser-harness gotcha 防御**（conftest 文档化提醒）
   - Source: `SKILL.md` §104-115 "Gotchas (field-tested)"
   - Target: `e2e/conftest.py` docstring 列三条必须遵守：
     - **`new_tab(url)` 而非 `goto_url(url)`**——后者污染用户活动 tab（spec 跑完用户工作丢失）
     - **`ensure_real_tab()`**——daemon 默认 session 可能 stale，spec 开头调一次
     - **过滤 `chrome://omnibox-popup`**——这是假 tab target，`page_info()` 可能命中
   - Why：本 plan 一旦污染用户活动 tab 会被立刻投诉；这三条是直接踩坑后的总结，写在 conftest docstring 里防新 spec 作者复踩

## 与本项目的关系

本 plan 05c-08 是 **Phase 5.C 出口 gate** —— 必须证明 plan 01-07 真实工作 + Phase 5.A 271 regression + Phase 5.B 5/5 acid test regression 0 退化：

- **3 个 browser-harness Python spec**（Task 2/3/4）真出文档真渲染，覆盖 5C-SC-5 `E2E with browser-harness：DAG 跑完 → Outline 出文档 → 协作人收 @ 提醒`
- **license attribution audit**（Task 5）+ **audit script 单测**（Task 6） 是 5C-FW-04 多 capability plugin 测试 4 维度的「license + AGPL 防御」维度落地
- **Pattern 7 structured log coverage 集成测**（Task 7）固化 Phase 7 Run Viewer 6 字段契约
- **VERIFICATION.md 草稿**（Task 8）回写 plan 01-08 全 DoD truth + 5C-SC-1~5 全 success criteria 验收
- **历史 Playwright `*.spec.ts`**（Phase 1/2/3 留下 19 个）保留不删（per CLAUDE.md §2.2），但 Phase 4+ 新 E2E 一律 browser-harness（用户 2026-05-17 指令 + memory feedback_e2e_browser_harness_only）

**硬性纪律重申（违反即返工）**：
- **禁止** `from playwright.sync_api import sync_playwright` 自起浏览器
- **禁止** `playwright install chromium` 装新浏览器实例
- **禁止** 默认 `Skill("webapp-testing")`——该 skill 走 Playwright headless，仅当 user 明确要求降级或 browser-harness 真不可用时才用
- **必须** 用 `subprocess.run(["browser-harness"], input=heredoc, text=True)` 走 CDP 直连用户 :9222 Chrome

## License attribution

- **Dify (AGPL-3.0)**：仅借鉴 `integration_tests/workflow/test_sync_workflow.py` 的 fixture 风格（真对象 + 真断言无 mock）+ `workflow_service.validate` 链路思路；**不拷贝任何 Dify 源代码**到本仓库；reading doc 本身只写设计模式不贴 Dify 源码片段（per CLAUDE.md §2.7 "License 注意"）
- **browser-harness (MIT)**：命令字符串 + helper 命名风格 + heredoc 调用约定可自由使用；`SKILL.md` / `install.md` / `agent-workspace/agent_helpers.py` 思路引用无许可证负担
- **hr/offboarding-flow (Apache-2.0)**：每个 `backend/app/plugins/huly/_internal/*.py` 必含 `# Inspired by hr/offboarding-flow design under Apache-2.0 — not derived source` 头注释；本 plan Task 5 `license_attribution_audit.py` 机械化扫描确保 100% 覆盖
- **Huly server (AGPL-3.0)**：我们**只通过 HTTP API + collab service /rpc** 接入，**永不**拷贝 Huly server 源码或 schema 定义到本仓库；TS 协议借鉴仅在 hr docs 中以注释形式记录
