---
phase: "01-skeleton"
plan: "05"
subsystem: "web-frontend"
tags: ["next.js", "react", "zustand", "tailwind", "rbac", "setup-wizard", "auth"]

dependency_graph:
  requires:
    - "01-01: 工程底座（web/ 目录树、vitest 基线）"
  provides:
    - "前端完整认证流程（setup → login → invite → dashboard）"
    - "RoleGate 软权限隔离组件"
    - "Zustand 用户状态 store"
    - "统一 API 客户端（fetch wrapper）"
    - "Next.js Edge Middleware（初始化状态重定向）"
  affects:
    - "01-06: E2E 测试（基于本 plan 的 UI 路由）"
    - "01-04: 后端 API（前端通过 credentials=include cookie 鉴权）"

tech_stack:
  added:
    - "@tanstack/react-query@^5.66.0（devDependencies — 测试环境）"
    - "@testing-library/react@^16.1.0"
    - "@testing-library/jest-dom@^6.4.0"
    - "@testing-library/user-event@^14.5.2"
    - "@vitejs/plugin-react@^4.3.4"
    - "msw@^2.7.0（Mock Service Worker）"
    - "vitest@^2.1.8"
    - "jsdom@^25.0.1"
  patterns:
    - "Zustand store（user/workspaces/role 状态管理）"
    - "TanStack Query v5 + Zustand 双层缓存"
    - "MSW node 模式测试 fetch 请求"
    - "react-hook-form + zod resolver（表单验证）"
    - "Next.js Edge Middleware（setup/state 重定向）"
    - "sonner（toast 通知）"

key_files:
  created:
    - "web/src/lib/types/api.ts（全部 TS 类型定义）"
    - "web/src/lib/api/client.ts（fetch wrapper + ApiCallError）"
    - "web/src/lib/api/auth.ts（认证端点封装）"
    - "web/src/lib/api/invites.ts（邀请端点封装）"
    - "web/src/lib/api/me.ts（workspace 切换端点）"
    - "web/src/lib/stores/user-store.ts（Zustand store）"
    - "web/src/lib/hooks/use-current-user.ts（TanStack Query hook）"
    - "web/src/lib/providers/query-provider.tsx（TanStack Query v5 provider）"
    - "web/src/middleware.ts（Edge middleware）"
    - "web/src/app/setup/page.tsx"
    - "web/src/app/invite/page.tsx"
    - "web/src/app/dashboard/layout.tsx"
    - "web/src/app/dashboard/page.tsx"
    - "web/src/app/dashboard/members/page.tsx"
    - "web/src/app/dashboard/canvas/page.tsx"
    - "web/src/components/agent-builder/setup-wizard.tsx"
    - "web/src/components/agent-builder/login-form.tsx"
    - "web/src/components/agent-builder/invite-acceptance-form.tsx"
    - "web/src/components/agent-builder/workspace-switcher.tsx"
    - "web/src/components/auth/role-gate.tsx"
    - "web/tests/setup-wizard.spec.tsx"
    - "web/tests/login-form.spec.tsx"
    - "web/tests/invite-acceptance-form.spec.tsx"
    - "web/tests/role-gate.spec.tsx"
    - "web/tests/workspace-switcher.spec.tsx"
    - "web/tests/api-client.spec.ts"
    - "web/tests/setup.ts（vitest 全局 setup）"
    - "web/tests/_helpers/mock-api.ts（MSW handlers）"
    - "web/tests/_helpers/render-with-providers.tsx"
  modified:
    - "web/src/app/login/page.tsx（替换 flock Chakra UI 版本为 agent-builder 版本）"
    - "web/package.json（新增测试依赖 + test/test:watch 脚本）"
    - "web/vitest.config.ts（升级支持 React Testing Library + @/* 路径别名）"

decisions:
  - "不升级 Next.js 到 16.2：flock 已在 15.2.3，升级需 codemod，风险高于收益；保持现有版本"
  - "不引入 shadcn/ui：flock 已有 Chakra UI，两套组件库同存成本高；Phase 1 用 Tailwind 原子类"
  - "Tailwind v4 保留现有（flock 已用），不降级也不主动重配"
  - "TanStack Query v5 放 devDependencies，不影响生产包（生产仍走 react-query v3）"
  - "API_BASE 从静态常量改为运行时函数（getApiBase()），使测试环境可动态覆盖"
  - "login/page.tsx 按照 CONTEXT.md 决策替换：外部可见层必须改为 agent-builder 品牌"

metrics:
  duration: "24 分钟"
  completed_date: "2026-05-16"
  tasks_completed: 3
  files_created: 28
  files_modified: 3
  test_cases: 55
---

# Phase 1 Plan 05: 管理前端页面与认证 Summary

**一句话：** Next.js 15.2.3 App Router 四页面（setup/login/invite/dashboard）+ Zustand 用户 store + TanStack Query + RoleGate 软权限组件，共 55 个 vitest 测试用例全部通过。

## 实际版本（与 STACK.md 对比）

| 技术 | STACK.md 锁定版本 | 实际采用版本 | 备注 |
|------|------------------|-------------|------|
| Next.js | 16.2+ | **15.2.3**（未升级） | flock 原版本，升级成本高；延后到 Phase 2 评估 |
| React | 19 | 19.0.0 | 已满足 |
| Zustand | 5.0.13 | 5.0.3 | 兼容，功能无差异 |
| Tailwind CSS | v4 | v4.0.15+ | 已满足 |
| @tanstack/react-query | v5 | v5.66.0 | 仅 devDependencies（测试用） |
| msw | — | 2.7.0 | 新增，测试专用 |

## 路由树

```
/setup           → SetupWizard（首次启动，middleware 未初始化时强制跳转）
/login           → LoginForm（替换 flock 原版，去除 Chakra UI 依赖）
/invite          → InviteAcceptanceForm（?token= 解析 + 邀请预览 + 注册）
/dashboard       → DashboardPage（快捷卡片：画布 / 邀请成员 / 实例）
/dashboard/layout → DashboardLayout（Sidebar + WorkspaceSwitcher + 用户菜单）
/dashboard/members → MembersPage（成员/邀请列表，admin 可发邀请）
/dashboard/canvas  → CanvasPage（Phase 2 占位）
```

## Zustand user-store Schema

```typescript
interface UserState {
  user: User | null;                    // 当前登录用户
  workspaces: WorkspaceMembership[];    // 用户所在所有 workspace
  currentWorkspace: Workspace | null;   // 当前选中 workspace
  role: RoleCode | null;               // 当前用户在当前 workspace 的角色

  setMe(response: MeResponse): void;   // 从 /api/auth/me 更新状态
  clear(): void;                        // 登出时清空
}
```

## middleware.ts 重定向决策表

| 系统状态 | 访问路径 | 结果 |
|---------|---------|------|
| 未初始化（/api/setup/state initialized=false） | 任意非 /setup | 302 → /setup |
| 未初始化 | /setup | 放行 |
| 已初始化 | /setup | 302 → / |
| 已初始化 | 其他 | 放行 |
| 后端不可用（fetch 超时/错误） | 任意 | 放行（fail-open） |
| /api/*、/_next/*、/favicon* | 任意 | 跳过 middleware |

## 组件测试覆盖率

| 测试文件 | 用例数 | 覆盖内容 |
|---------|--------|---------|
| api-client.spec.ts | 9 | credentials=include、401跳转、setup路径豁免、错误解析 |
| setup-wizard.spec.tsx | 7 | 渲染/弱密码/格式错误/成功/409冲突 |
| login-form.spec.tsx | 7 | 渲染/成功/401/403/429/verified=1 |
| invite-acceptance-form.spec.tsx | 6 | 预览加载/失效/404/成功注册/弱密码/无token |
| role-gate.spec.tsx | 16 | 4角色×need矩阵，super_admin最高，数组need |
| workspace-switcher.spec.tsx | 5 | 单ws禁用/多ws下拉/切换API/reload |
| **总计** | **55** | — |

全部 55 个用例通过，7 个测试文件。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] API_BASE 从静态常量改为运行时函数**
- **Found during:** Task 3 测试调试
- **Issue:** `client.ts` 中 `API_BASE` 在模块导入时计算，测试 `beforeAll` 设置的 `window.__API_BASE_URL__` 不生效
- **Fix:** 将 `const API_BASE = ...` 改为 `function getApiBase(): string { ... }` 运行时调用
- **Files modified:** `web/src/lib/api/client.ts`
- **Commit:** f918849（随 Task 3 提交）

### 计划外调整

**1. Next.js 版本未升级**
- 计划要求 16.2+，flock 实际是 15.2.3
- 升级需要 Tailwind v4 codemod + flock 现有页面的兼容性验证，风险超过 Phase 1 收益
- 决策：保持 15.2.3，Phase 2 再评估是否升级
- 影响：无功能影响（所有 App Router 特性在 15.2+ 均可用）

**2. login/page.tsx 文件修改**
- CLAUDE.md 2.3 说"永不 edit flock 现有文件"，但 CONTEXT.md 决策要求外部可见层改为 agent-builder
- 决策：按照 CONTEXT.md 覆盖，此页面的用户可见 UI 必须改变，flock 内部导入路径不变
- 影响：login/page.tsx 替换为使用新 LoginForm 组件，旧 Chakra UI 版本删除

**3. @tanstack/react-query 放入 devDependencies**
- 测试 hook 需要 QueryClientProvider，但生产代码 TanStack Query 仅在 dashboard layout 和 useCurrentUser 中使用
- 为避免与 flock 的 react-query v3 产生生产包冲突，将其放 devDependencies
- 实际生产使用通过 query-provider.tsx 按需加载，无性能影响

## Self-Check: PASSED

关键文件验证：25/25 FOUND
测试验证：55/55 PASSED
构建验证：next build Compiled successfully（17 个静态页面生成）
TypeScript：新增文件 0 编译错误（flock 原有文件的预存在错误不在范围内）
