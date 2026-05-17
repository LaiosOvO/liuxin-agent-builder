# Phase 4 E2E v2 — browser-harness + pytest

> Phase 4 Plan 12 — 工具切换：Playwright → browser-use/browser-harness（用户 2026-05-17 指令）
> Phase 1-3 既有 11 个 Playwright spec 保留不动，位于 `e2e/`

## 测试目标

覆盖 ROADMAP Phase 4 全 6 个 success criteria（一一对应）：

| ROADMAP # | Criterion | Spec | UI? |
| ---- | ---- | ---- | ---- |
| 1 | 顺序会签 A→B→C，A 拒绝立即终止 | `specs/test_04_chain_sequential.py` | 否 |
| 2 | 并行全员同意，A 拒绝触发 invalidate_chain + 补通知 | `specs/test_04_chain_parallel_all.py` | 否 |
| 3 | 或签任一同意推进 + 其余 token 失效 | `specs/test_04_chain_parallel_any.py` | 否 |
| 4 | 节点超时催办 + 升级策略生效 | `specs/test_04_escalation.py` | 否 |
| 5 | 5 家 IM 卡片投递 + 点击跳决策页 | `specs/test_04_im_card_delivery.py` | 是 |
| 6 | 委托 + 委托记录写审计日志 | `specs/test_04_delegation.py` | 是 |

**Safe Links bot regression** 在 3 个 chain mode spec 共享（CLAUDE.md §2.5 P0）。

## 工具栈

| 维度 | 选择 |
| ---- | ---- |
| 语言 | Python 3.11+ |
| 测试框架 | pytest + pytest-asyncio |
| HTTP 客户端 | httpx |
| 浏览器控制 | browser-harness (CDP, 仅 #5 / #6 spec) |
| 邮件验证 | MailHog API + httpx |
| Mock IM | MockIMProvider + GET /api/test/im_mock_calls |

## 目录结构

```
e2e_v2/
├─ README.md                                # 本文件
├─ pyproject.toml                           # 依赖 + pytest 配置
├─ conftest.py                              # pytest fixture: API client / mailhog / DB
├─ helpers/
│  ├─ __init__.py
│  ├─ api_client.py                         # API 调用（auth / workflow / instance）
│  ├─ mailhog_client.py                     # MailHog 邮件解析 + bot UA fetch
│  ├─ hitl_builder.py                       # HITL DSL 单人模式
│  ├─ chain_builder.py                      # chain mode DSL (sequential/parallel_all/parallel_any)
│  ├─ im_mock_client.py                     # GET /api/test/im_mock_calls 等
│  ├─ safe_links_uas.py                     # 4 种 bot UA 常量
│  └─ browser_session.py                    # browser-harness subprocess 调用封装
├─ pages/
│  └─ hitl_decision_page.py                 # 决策页 browser-harness 操作模板
└─ specs/
   ├─ test_04_chain_sequential.py          # ROADMAP #1
   ├─ test_04_chain_parallel_all.py        # ROADMAP #2
   ├─ test_04_chain_parallel_any.py        # ROADMAP #3
   ├─ test_04_escalation.py                # ROADMAP #4
   ├─ test_04_im_card_delivery.py          # ROADMAP #5
   └─ test_04_delegation.py                # ROADMAP #6
```

## 三档运行模式（与 Phase 1-3 e2e/ 对齐）

| 模式 | 触发 | 跑哪些 spec | 时长估算 |
| ---- | ---- | ---- | ---- |
| Smoke（默认 CI） | `pytest e2e_v2/` | 默认全部 skip（`@pytest.mark.skipif(not RUN_E2E)`） | 0s |
| Standard | `RUN_E2E=1 pytest e2e_v2/` | 全 6 spec（不含真实快进时间） | ~8-10 min |
| Full | `E2E_FULL_STACK=1 pytest e2e_v2/` | + 真实时间快进 escalation spec | ~15 min |

```bash
# Smoke（默认）
pytest e2e_v2/

# Standard — 全 6 spec
RUN_E2E=1 pytest e2e_v2/

# 只跑单个 spec
RUN_E2E=1 pytest e2e_v2/specs/test_04_chain_sequential.py -v

# Full — 含 timeout 真实快进
E2E_FULL_STACK=1 pytest e2e_v2/

# 收集所有 spec（不跑）
pytest e2e_v2/ --collect-only
```

## 启动测试环境

```bash
# 1. 启动 backend + DB + Redis + MailHog（开发环境 docker-compose）
docker-compose -f docker-compose.dev.yml up -d

# 2. 启动后端（必须 ENABLE_TEST_API=1）
cd backend && ENABLE_TEST_API=1 uvicorn app.agent_builder.main:agent_builder_app --port 8000

# 3. 启动前端（仅 #5 / #6 spec 需要 — 启浏览器用）
cd frontend && pnpm dev

# 4. 跑 E2E
RUN_E2E=1 pytest e2e_v2/
```

## 工具切换记录

- **2026-05-17 用户指令**：把 E2E 工具从 Playwright 改为 browser-use/browser-harness
- **设计原则**：4 chain/escalation spec 纯 pytest+httpx（不需浏览器）；2 UI 流 spec（IM 卡片点击 + 委托）走 browser-harness
- **Phase 1-3 Playwright spec 保留不动**：fork discipline + 不破坏既有信号

## Safe Links bot regression（CLAUDE.md §2.5 P0）

每个 chain mode spec 末尾共享 4 bot UA parametrize 测试：
- `OUTLOOK_AC_DETECTOR_UA` = `Mozilla/5.0 (compatible; Microsoft-Outlook-AC-Detector-Tool/1.0)`
- `MICROSOFT_DEFENDER_UA` = `Mozilla/5.0 SafeLinksScanner/1.0`
- `SLACKBOT_UA` = `Mozilla/5.0 (compatible; Slackbot-LinkExpanding 1.0)`
- `GOOGLEBOT_UA` = `Mozilla/5.0 (compatible; Googlebot/2.1)`

每个 UA 测试断言：
1. GET /hitl/page/<token> 返回 200
2. GET /api/test/hitl_tokens?jti=<jti> 返回 used_at IS NULL
3. 真实用户随后 POST 仍可成功（反证 jti 未消费）

## 参考文档

- `docs/reading-browser-harness-04-12-2026-05-17.md` — 工具栈完整对比
- `docs/reading-dify-04-12-e2e-2026-05-17.md` — Dify E2E 缺失结论 + 借鉴模式
- `.planning/phases/04-approval-chain-im/04-CONTEXT.md` — Phase 4 决策与边界
- `.planning/phases/04-approval-chain-im/04-12-PLAN.md` — 本 plan 完整定义
