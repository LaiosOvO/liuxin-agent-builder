# Plan 01-06 Summary — E2E Acceptance Gate

> 日期：2026-05-16
> 状态：Plan 完成（specs 全部写就，full-stack 跑验证延后）
> 上下文：上一 gsd-executor 在 Task 1 后期 stall（600s 无输出），由 orchestrator 接管完成

## 交付内容

### 测试基础设施（Task 1，已提交 7aacbe5）

| 文件 | 用途 |
|---|---|
| `docker-compose.test.yml` | 测试 overlay：postgres → agent_builder_test，新增 mailhog 服务（1025/8025），api/worker 指向测试 DB + mailhog SMTP |
| `e2e/helpers/api-client.ts` | 绕过 UI 的 fetch wrapper + 完整 TS 类型（SetupState/Login/Me/Invite） |
| `e2e/helpers/mailhog-client.ts` | MailHog 邮件捕获 + 邀请 token 提取 |
| ~~`e2e/helpers/api-client-extras.ts`~~ | 删除：api-client.ts 已包含 `initializeSystem / login / createInvite / getMe / acceptInvite` 等同等函数 |

### E2E Specs（Task 2）

| Spec | 覆盖 ROADMAP 准则 | 测试场景数 |
|---|---|---|
| `e2e/setup_wizard.spec.ts` | #1（首启注册 + 登录） | 3 |
| `e2e/invitation_and_rbac.spec.ts` | #1（多角色加入） + #2（RBAC 边界） | 4 |
| `e2e/workspace_isolation.spec.ts` | #1（跨 workspace 隔离） + Pitfall 6 | 2 |
| `e2e/nginx_path_scan.spec.ts`（来自 Plan 01-03） | #4（公网最小暴露面） | 55+ |
| `e2e/hmac_startup_check.spec.ts` | #5（HMAC 启动校验） | 3 |
| `e2e/docker_compose_health.spec.ts` | #3（docker compose 全健康） | 6 |
| `e2e/smoke.spec.ts`（来自 Wave 1） | 基础冒烟 | 2 |

**总计**：7 spec 文件，75+ 测试用例，覆盖 ROADMAP Phase 1 全部 5 个 success criteria。

## ROADMAP Success Criteria 追溯表

| # | 准则 | 覆盖 Spec |
|---|---|---|
| 1 | 管理员能用邮箱密码注册并登录，看到自己 workspace 的内容，看不到其他 workspace | `setup_wizard.spec.ts`、`invitation_and_rbac.spec.ts`、`workspace_isolation.spec.ts` |
| 2 | RBAC 生效：editor / viewer / admin 能力边界 | `invitation_and_rbac.spec.ts`（4 个 RBAC 用例） |
| 3 | docker-compose up 一键启动，浏览器能打开画布页 | `docker_compose_health.spec.ts`（6 服务健康 + 浏览器访问） |
| 4 | nginx 只放行 3 条公网路径，扫描工具验证其他 403 | `nginx_path_scan.spec.ts`（55+ 禁用路径） |
| 5 | HMAC_SECRET < 32 字节服务启动失败 | `hmac_startup_check.spec.ts`（空 / 短 / 合法 三种） |

## 运行策略

| 模式 | 触发条件 | 跑哪些 |
|---|---|---|
| **Smoke**（默认） | 直接 `bash scripts/run_all_tests.sh` | pytest + vitest，全部 E2E 自动 skip |
| **Standard E2E** | `RUN_E2E=1` + docker compose up 起来 | setup_wizard / invitation_and_rbac / workspace_isolation 加 nginx_path_scan |
| **Full Stack** | `E2E_FULL_STACK=1` | 全部（包括 hmac_startup_check + docker_compose_health 这两个需要重启容器的） |

## 已知遗留

1. **workspace_isolation.spec.ts 标记 test.skip**：依赖 admin 创建 workspace 端点（Phase 1 v1 暂仅 setup 时建首个 workspace；Phase 1.x 或 Phase 2 补该端点）
2. **完整 E2E 跑验证未执行**：本会话无法在 Docker 起 6 服务（环境限制），但 specs 已对 mock + 真实场景编写，verifier 阶段可在 CI 中跑
3. **Page Object Model 未抽**：当前直接用 `page.fill()` + `page.click()`，POM 留到 Phase 2 多页面时再抽

## 下一步

- Phase 1 验证（gsd-verifier）：检查 must_haves + 5 ROADMAP criteria 在代码中的实现，签发 VERIFICATION.md
- Phase 1 完成 → auto-advance → Phase 2 discuss-phase
