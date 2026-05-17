# browser-harness 阅读笔记 — Phase 4 Plan 12 E2E 工具栈切换

> 日期: 2026-05-17
> 仓库: https://github.com/browser-use/browser-harness
> 本地 clone: /Users/admin/ai/ref/agent/browser-harness/
> Stars: 12.9k
> License: MIT
> 上游 commit (clone 时): latest main

## 项目概述

**browser-harness** 是 browser-use 团队出品的极简 CDP 浏览器控制框架（~1k 行核心代码）。它把一个 LLM agent 直接接到真实运行的 Chrome 浏览器上，通过单一 WebSocket（Chrome DevTools Protocol）发送指令、读取响应、自我编辑 helper。

设计哲学：**The Bitter Lesson of Agent Harnesses** — 不要写僵硬的测试框架/选择器配置，让 agent 在运行时自己写出需要的 helper，并把可复用的部分沉淀到 `agent-workspace/domain-skills/<site>/`。

与 Playwright 的本质差异：
- Playwright 是**声明式**测试框架（locator + assertion）
- browser-harness 是**命令式 CDP 控制工具** + **agent 自适应学习模式**
- Playwright 由开发者写完整 spec；browser-harness 由 agent 在跑的时候补全 helper

## 技术栈

| 维度 | browser-harness 选择 |
| ---- | ---- |
| 语言 | Python 3.11+ |
| 协议 | Chrome DevTools Protocol（WS 单 socket） |
| 依赖 | 极简：`websocket-client` + `Pillow`（截图缩放可选） |
| 浏览器 | Chrome / Chromium / Edge（任何支持 CDP 的） |
| 入口 | CLI `browser-harness` (uv tool install -e .) |
| 通信 | Unix socket /tmp/bu-<NAME>.sock 与 daemon 通信 |
| 远端 | Browser Use Cloud（隐身、代理、captcha） |

## 架构要点

```
┌────────────────────┐    Heredoc    ┌────────────────────┐
│  Python E2E spec  │ ──────────────▶│  browser-harness    │
│  (pytest)         │                │   CLI process       │
└────────────────────┘                └─────────┬──────────┘
                                                │ IPC
                                                ▼
                                      ┌────────────────────┐
                                      │ browser_harness.   │
                                      │   daemon (常驻)      │
                                      └─────────┬──────────┘
                                                │ CDP WS
                                                ▼
                                      ┌────────────────────┐
                                      │  Chrome / Chromium  │
                                      └────────────────────┘
```

调用方式（heredoc）：

```bash
browser-harness <<'PY'
new_tab("https://example.com")
wait_for_load()
print(page_info())
PY
```

stdout 收 print 输出 → pytest 断言。

## 核心 API（src/browser_harness/helpers.py）

| 类别 | 函数 | 用途 |
| ---- | ---- | ---- |
| 导航 | `new_tab(url)` / `goto_url(url)` | 打开新 tab / 跳转 |
| 等待 | `wait_for_load()` / `wait_for_element(sel, visible=True)` / `wait_for_network_idle()` | 各种就绪 |
| DOM | `js(expression)` / `dispatch_key(sel, key)` | 注入 JS / 派发事件 |
| 输入 | `click_at_xy(x, y)` / `fill_input(sel, text)` / `press_key(key)` | 鼠标 / 键盘 |
| 视觉 | `capture_screenshot(path, full=True)` / `page_info()` | 截图 / 视口信息 |
| Tab | `list_tabs()` / `current_tab()` / `switch_tab(id)` | 多 tab 管理 |
| 网络 | `http_get(url, headers=...)` | 不走浏览器的纯 HTTP（关键 — Safe Links bot UA 模拟） |
| 上传 | `upload_file(sel, path)` | 通过 DOM.setFileInputFiles |
| 远端 | `start_remote_daemon(name, profileName=...)` | Browser Use Cloud 隔离 |

## 与 Playwright 相比的优势 / 取舍

| 维度 | Playwright | browser-harness | 我们的取舍 |
| ---- | ---- | ---- | ---- |
| 学习曲线 | 中（locator / fixture） | 低（纯 CDP + 全局函数） | 拓展不再需要学新 framework |
| selector 健壮 | Locator 自动 retry + smart wait | 手写 `wait_for_element()` | Spec 写更长但完全可控 |
| 并行 | 内置 worker | 多 daemon (`BU_NAME=spec1` 等) | E2E spec 并发简单 |
| LLM 自愈 | 无 | agent 跑时自己补 helper | Plan 04-12 没用此特性（仍是预写 spec） |
| Bot UA 模拟 | `setExtraHTTPHeaders` 全局 | `http_get(url, headers={'UA': ...})` | 后者更直接：不走浏览器栈，纯 HTTP 验证 jti 不消费 |
| Mailhog 集成 | `request.get()` Playwright fixture | 直接 `httpx.AsyncClient` | 同等水平 |
| 多 tab 测试 | `context.newPage()` | `new_tab()` | 一致 |

## 如何配置 LLM（Plan 04-12 暂未使用）

browser-harness 自带 agent 模式（编辑 `agent_helpers.py`），但 **Plan 04-12 不启用 agent 自愈**，仅用纯 CDP 控制 API。需要时可设：

```bash
# 用 Browser Use Cloud（云浏览器 + LLM 自愈）
export BROWSER_USE_API_KEY="bu_..."

# 或自定义 agent_helpers.py（本项目可往里加 hitl-specific helper）
export BH_AGENT_WORKSPACE=/path/to/our/workspace
```

## 如何模拟 bot UA（Safe Links 回归测试关键）

**两种方式**：

**方式 A（推荐）— http_get 纯 HTTP 不走浏览器**
```python
# browser-harness heredoc 内
from browser_harness.helpers import http_get
resp_body = http_get(
    "http://localhost:8080/hitl/page/<token>",
    headers={"User-Agent": "Mozilla/5.0 SafeLinksScanner/1.0"}
)
# resp_body 是字符串
print(resp_body[:200])
```

**方式 B（次选）— httpx 直接（更标准）**
```python
# pytest spec 外（不需要 browser-harness）
import httpx
async with httpx.AsyncClient() as client:
    r = await client.get(
        f"{BASE}/hitl/page/{token}",
        headers={"User-Agent": OUTLOOK_SAFE_LINKS_UA},
    )
    assert r.status_code == 200
```

**结论**：Plan 04-12 用方式 B（pytest + httpx），更适合不需要浏览器交互的 bot UA 回归。仅在「真实用户走 UI 决策」流程时才进 browser-harness heredoc。

## 如何与 mailhog / Postgres 容器协同

| 服务 | 端口 | spec 访问方式 |
| ---- | ---- | ---- |
| Postgres (test) | 15432 | `asyncpg.connect()` 直连 — 不通过 browser |
| Redis (test) | 16379 | `redis.asyncio.Redis()` 直连 |
| MailHog SMTP | 1025 | 后端注入；spec 不直接连 |
| MailHog API | 8025 | `httpx.AsyncClient` 直接 GET |
| FastAPI | 8000 / 8080 (nginx) | pytest 用 httpx；UI 流用 browser-harness |
| Next.js | 3000 | UI 流走 browser-harness |

**协同模式**：
1. pytest spec 启动前用 fixture 准备 admin + workspace + workflow（API 直调，快 10x）
2. UI 交互流（点决策按钮）走 `browser-harness <<'PY' ... PY` heredoc
3. mailhog 验证 + DB 验证仍走 `httpx` / `asyncpg`（spec 主体不用浏览器）
4. bot UA 回归用 `httpx` 直接发 GET，断言 token 未消费

## 可借鉴的设计模式

| 模式 | browser-harness 来源 | 应用到 Plan 04-12 |
| ---- | ---- | ---- |
| 单 IPC daemon 复用 | `_send({"method": ..., "params": ...})` | spec 间共享 daemon 减少启动开销 |
| BU_NAME 多浏览器隔离 | `BU_NAME=spec1 browser-harness` | 并行 spec 互不干扰 |
| heredoc 注入 | `browser-harness <<'PY' ... PY` | spec 内嵌 Python 控制 + stdout 通信 |
| http_get（不走浏览器） | `helpers.http_get(url, headers=...)` | bot UA 模拟（无 chrome 启动开销） |
| `agent_helpers.py` 外置 | `AGENT_WORKSPACE/agent_helpers.py` | 项目 site-specific helper 沉淀（Phase 5+ 用） |
| 截图缩放 `max_dim=1800` | `capture_screenshot(max_dim=1800)` | 失败时上传可读截图 |

## 与本项目的关系（Phase 4 Plan 12 适配）

**E2E spec 结构（Python + browser-harness 混合模式）**：

```
e2e_v2/                              # 新目录，与 Phase 1-3 e2e/ 共存
├─ README.md                         # 三档运行模式说明
├─ pyproject.toml                    # uv / pip 依赖（pytest + httpx + asyncpg + browser-harness）
├─ conftest.py                       # pytest fixture：API 客户端 / mailhog / DB
├─ helpers/
│  ├─ __init__.py
│  ├─ api_client.py                  # 类似 Phase 3 api-client.ts 的 Python port
│  ├─ mailhog_client.py              # 类似 Phase 3 mailhog-client.ts 的 Python port
│  ├─ hitl_builder.py                # DSL builder（顺序 / parallel_all / parallel_any）
│  ├─ chain_builder.py               # 4-node chain DSL helper
│  ├─ im_mock_client.py              # 拉取 /api/test/im_mock_calls 的 fixture
│  ├─ safe_links_uas.py              # 4 种 bot UA 常量
│  └─ browser_session.py             # 封装 browser-harness 子进程调用
├─ pages/
│  └─ hitl_decision_page.py          # 决策页操作脚本（browser-harness heredoc 模板）
└─ specs/
   ├─ test_04_chain_sequential.py   # ROADMAP #1
   ├─ test_04_chain_parallel_all.py # ROADMAP #2
   ├─ test_04_chain_parallel_any.py # ROADMAP #3
   ├─ test_04_escalation.py         # ROADMAP #4
   ├─ test_04_im_card_delivery.py   # ROADMAP #5
   └─ test_04_delegation.py         # ROADMAP #6
```

**为何分目录 `e2e_v2/`？**
- Phase 1/2/3 已通过验收的 11 个 Playwright spec 保留不动（CLAUDE.md §2.3 fork discipline + 不破坏既有信号）
- Phase 4 用 browser-harness 新栈，避免 Playwright/Python 工具混用导致 npm/pnpm 依赖冲突

**Smoke / Standard / Full 三档**：
- Smoke（默认 CI）: `pytest e2e_v2/` → 全 skip （`@pytest.mark.skipif(not RUN_E2E)`）
- Standard: `RUN_E2E=1 pytest e2e_v2/` → 跑全 6 spec（约 8-10 min）
- Full: `E2E_FULL_STACK=1 pytest e2e_v2/` → + escalation 真实快进 spec（约 15 min）

**Safe Links bot regression 在 3 chain spec 共享**：
- `helpers/safe_links_uas.py` 定义 OUTLOOK / DEFENDER / SLACKBOT / GOOGLEBOT 4 UA
- 每个 chain spec 末尾 parametrize 跑 4 个 UA 的 GET 测试
- 用 `httpx.AsyncClient` 不启动浏览器 — 快 + 不污染 daemon

**为何不需要真启动 browser-harness 进程**：
- Plan 04-12 主要测试维度是 **API + DB + mailhog 状态机**（顺序/并行/拒绝/失效/补通知/审计日志）
- 仅 ROADMAP #5 IM 卡片点击跳决策页 + ROADMAP #6 委托表单提交 **需要 UI**
- 因此大部分 spec 是 pytest + httpx，**仅 2 spec 嵌 browser-harness heredoc** 跑 UI

## 关键实现细节（Spec 内调用 browser-harness）

```python
# e2e_v2/helpers/browser_session.py
import subprocess
import shlex


def run_browser_harness_script(script: str, name: str = "default", timeout: float = 60) -> str:
    """在 browser-harness daemon 内执行 Python 脚本，返回 stdout。

    Args:
        script: 要执行的 Python 代码（heredoc body）
        name: BU_NAME 隔离（不同 spec 用不同 name 防止 daemon 冲突）
        timeout: 子进程超时秒数

    Returns:
        stdout 字符串（spec 用 print() 输出关键状态）

    Raises:
        subprocess.CalledProcessError: 退出码非 0
        TimeoutError: 超时
    """
    env = {"BU_NAME": name}
    result = subprocess.run(
        ["browser-harness"],
        input=script.encode(),
        capture_output=True,
        timeout=timeout,
        env={**os.environ, **env},
        check=True,
    )
    return result.stdout.decode()
```

Spec 内：

```python
async def test_im_card_click_lands_on_decision_page(api):
    # ... 准备 workflow + 启动实例 + 验证 mock IM call ...
    deeplink = mock_calls[0].payload["deeplinks"][0]["url"]

    # 启动浏览器，点 deeplink，断言决策页加载
    stdout = run_browser_harness_script(f"""
new_tab("{deeplink}")
wait_for_load(timeout=10)
info = page_info()
print(f"URL={{info['url']}}")
print(f"TITLE={{info['title']}}")
""")
    assert "/hitl/page/" in stdout
    assert "审批" in stdout or "决策" in stdout
```

## 注意事项 / 边界情况

1. **CI 环境无桌面 Chrome**：browser-harness 需要可连 CDP 的 Chrome。CI 用 `--headless --remote-debugging-port=9222` 启动 Chrome 后传 `BU_CDP_URL` 给 daemon
2. **macOS 安全弹窗**：本地开发 Way 1（chrome://inspect/）首次会弹窗 — 仅本地开发体验，CI 走 headless 不会触发
3. **daemon 残留进程**：测试结束后清理 `/tmp/bu-<NAME>.sock`（fixture teardown）
4. **stdout 长度限制**：大 page_info() / 截图 base64 别走 stdout — 用文件交换
5. **Chrome 144+ "Allow remote debugging?" popup**：headless 模式不触发

## 决策摘要（用于 Plan 04-12 实现）

| 决策 | 取舍 |
| ---- | ---- |
| 用 browser-harness vs Playwright | Playwright（既有 11 spec）保留；新栈用 browser-harness 写 6 spec |
| 全 spec 都启浏览器 vs 选择性启 | 仅 IM card click（#5）+ delegate UI（#6）启浏览器；其他 spec 全 pytest+httpx |
| 一个 daemon 串行 vs 多 BU_NAME 并行 | spec 间序列化（pytest 默认）— 多 daemon 浪费资源 |
| pytest fixture 抽象 vs spec 自管 | conftest.py + helpers/ + pages/ 三层职责，与 Phase 3 e2e/ 对齐 |
| browser-harness 全局 vs 子进程 | 子进程隔离每个 spec 的 chrome state（无残留 cookie） |
| Safe Links bot 用浏览器 vs httpx | httpx — 不走浏览器更直接验证后端 GET 行为 |

## Phase 4 Plan 12 ↔ ROADMAP Phase 4 6 个 success criteria 一一对应

| ROADMAP # | Spec | UI 启浏览器？ |
| ---- | ---- | ---- |
| 1. 顺序会签 | `test_04_chain_sequential.py` | 否（纯 API + mailhog 即可） |
| 2. 并行全员同意 | `test_04_chain_parallel_all.py` | 否 |
| 3. 或签 | `test_04_chain_parallel_any.py` | 否 |
| 4. 超时升级 | `test_04_escalation.py` | 否（等 timeout） |
| 5. IM 卡片投递 + 点击跳决策页 | `test_04_im_card_delivery.py` | 是（点 deeplink 看决策页） |
| 6. 委托 + 审计日志 | `test_04_delegation.py` | 是（决策页 delegate 表单） |

## 后续可演进方向（Phase 5+）

- 把 `agent-workspace/domain-skills/agent-builder-decision-page/` 给 browser-harness — 让 agent 自学决策页选择器 → 后续 plan 写 spec 更省力
- 用 Browser Use Cloud + 真账号跑「真飞书 / 真 Slack」回归（仅 staging，不入 CI）
- 与 hr 离职模板 E2E（Phase 7）共享 hitl_decision_page.py 模板

---

*Reading doc 是 plan 的第一个 commit（Task 0 硬性 gate） — CLAUDE.md §2.7*
*与 docs/reading-dify-04-12-e2e-2026-05-17.md 配套，构成 Plan 04-12 的双重 reference*
