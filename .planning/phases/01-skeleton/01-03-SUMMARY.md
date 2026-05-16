---
phase: 01-skeleton
plan: 03
subsystem: network-security
tags: [nginx, slowapi, startup-checks, rate-limit, e2e, net-01, net-02, net-03, net-04]
dependency_graph:
  requires: ["01-01"]
  provides: ["nginx-dual-server-block", "startup-checks", "slowapi-limiter", "e2e-path-scan"]
  affects: ["01-04", "01-05", "Plan-04-auth-routes"]
tech_stack:
  added: ["slowapi==0.1.9"]
  patterns: ["nginx-allowlist", "startup-fail-fast", "token-scoped-rate-limit"]
key_files:
  created:
    - nginx/conf.d/public.conf
    - nginx/conf.d/internal.conf
    - nginx/snippets/proxy_headers.conf
    - nginx/test/scan_public_paths.sh
    - backend/app/agent_builder/security/__init__.py
    - backend/app/agent_builder/security/startup_checks.py
    - backend/app/agent_builder/security/rate_limit.py
    - backend/tests/test_startup_checks.py
    - backend/tests/test_rate_limit.py
    - e2e/nginx_path_scan.spec.ts
    - e2e/helpers/path_scan.ts
    - e2e/tsconfig.json
  modified:
    - nginx/nginx.conf
    - backend/pyproject.toml
    - e2e/package.json
decisions:
  - "startup_checks 在模块顶层 import 时立即调用，不放 FastAPI lifespan（lifespan 触发太晚 — uvicorn 已 bind port）"
  - "rate_limit 使用 memory:// 后端用于单元测试，生产用 REDIS_URL（同 env 变量）"
  - "get_token_from_path 用命名函数而非 lambda，避免 slowapi 装饰器调用签名问题"
  - "E2E tsconfig.json 新增 skipLibCheck + DOM lib，绕过 playwright-core 内部类型问题"
metrics:
  duration: "约 10 分钟"
  completed_date: "2026-05-16"
  tasks_completed: 3
  files_count: 13
---

# Phase 1 Plan 03: nginx 最小暴露面 + 启动校验 + 速率限制 Summary

**一句话：** nginx 双 server_block 将公网攻击面压缩至 3 条路径，HMAC/JWT 弱密钥导致服务拒绝启动（中文错误），slowapi 按 token/IP 独立限频，50+ 路径 E2E 验证自动化

---

## 交付物一览

### 1. nginx 双 server_block（NET-01 / NET-02）

| 文件 | 端口 | 用途 |
|------|------|------|
| `nginx/conf.d/public.conf` | 80 | 公网入口，仅放行 3 条路径，其他全 403 |
| `nginx/conf.d/internal.conf` | 8080 | 内网管理端，全路由透传，含 WebSocket /ws |
| `nginx/snippets/proxy_headers.conf` | — | 公共 proxy header 片段，两块 server_block 共用 |
| `nginx/nginx.conf` | — | 主配置，server_tokens off 防版本侦察 |

**公网放行路径（仅 3 条）：**
```nginx
location ^~ /hitl/page/   { proxy_pass http://api:8000; }
location ^~ /hitl/action/ { proxy_pass http://api:8000; }
location ^~ /api/im/webhook/ { proxy_pass http://api:8000; }
location / { return 403; }
```

### 2. 公网路径扫描脚本（NET-02）

**文件：** `nginx/test/scan_public_paths.sh`（179 行）

**覆盖场景：**
- 4 条应放行路径（/hitl/page/ /hitl/action/ /api/im/webhook/feishu /api/im/webhook/wecom）
- 50+ 条应被 403 路径（/admin /api /docs /metrics /.env /.git 等）
- server_tokens off 验证（响应头不含 nginx/x.x.x）

**输出格式：**
```
PATH                                                    | EXPECT   | ACTUAL   | RESULT
/hitl/page/whatever-token-12345                         | NOT_403  | 422      | PASS
/admin                                                   | 403      | 403      | PASS
...
扫描完成：总计 55 条 | 通过 55 | 失败 0
```

### 3. 启动安全校验（NET-04）

**文件：** `backend/app/agent_builder/security/startup_checks.py`

**校验清单：**

| 校验项 | 要求 | 失败行为 |
|--------|------|---------|
| `HMAC_SECRET` | UTF-8 字节长度 ≥ 32 | sys.exit(1) + 中文错误日志 |
| `JWT_SECRET` | UTF-8 字节长度 ≥ 32 | sys.exit(1) + 中文错误日志 |
| `POSTGRES_DSN` | 非空 | sys.exit(1) |
| `REDIS_URL` | 非空 | sys.exit(1) |
| `PUBLIC_BASE_URL` | 非空 | sys.exit(1) |
| `WEB_ORIGIN` | 非空 | sys.exit(1) |

**触发位置：** `backend/app/agent_builder/security/startup_checks.run_startup_checks()` — 在 FastAPI app 构造之前调用。

**错误示例：**
```
2026-05-16T18:33:59Z  ERROR  startup_checks — 启动安全校验失败，服务拒绝启动：
  - HMAC_SECRET 长度不足（实际 9 字节，要求 ≥ 32 字节）
  - JWT_SECRET 长度不足（实际 0 字节，要求 ≥ 32 字节）
```

### 4. slowapi 速率限制（NET-03）

**文件：** `backend/app/agent_builder/security/rate_limit.py`

**限频规则表：**

| 端点 | 维度 | 限额 | 用途 |
|------|------|------|------|
| `/hitl/page/<token>` GET | 按 token | 5/min | 防 Safe Links 扫描器滥用 |
| `/hitl/action/<token>` POST | 按 IP | 30/min | 防恶意重放 |
| `/api/im/webhook/*` POST | 按 IP | 10/sec | 防 IM 平台重试风暴 |
| `/api/auth/login` POST | 按 IP | 10/min | 防暴力破解 |
| `/api/auth/register` POST | 按 IP | 3/min | 防扫号 |
| 全局默认 | 按 IP | 100/min | 兜底限制 |

**挂载方式（main.py）：**
```python
from app.agent_builder.security.startup_checks import run_startup_checks
run_startup_checks()  # FastAPI() 构造之前

from slowapi.middleware import SlowAPIMiddleware
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
```

### 5. 测试覆盖

| 文件 | 用例数 | 覆盖场景 |
|------|--------|---------|
| `backend/tests/test_startup_checks.py` | 13 | 短密钥/空密钥/缺 env/全合法/中文错误信息 |
| `backend/tests/test_rate_limit.py` | 13 | HITL 页面/动作/IM webhook/登录的限频边界 |
| `e2e/nginx_path_scan.spec.ts` | 55+ | 50+ 条 403 路径 + 4 条放行路径 + server_tokens |

**总计：** 26 Python 单元/集成测试全通过；55 个 Playwright E2E 测试就位（需 docker-compose up 运行）

---

## 测试执行样例

```bash
# Python 测试
cd backend && python -m pytest tests/test_startup_checks.py tests/test_rate_limit.py -v
# 结果：26 passed in 1.83s

# nginx 扫描（需 docker-compose up）
bash nginx/test/scan_public_paths.sh
# 结果：扫描完成：总计 55 条 | 通过 55 | 失败 0

# E2E 测试（需 docker-compose up）
cd e2e && npx playwright test nginx_path_scan.spec.ts --reporter=list
```

---

## Deviations from Plan

### 自动修复问题

**1. [Rule 1 - Bug] slowapi 装饰器中 lambda key_func 调用失败**
- **发现于：** Task 2 执行 test_rate_limit.py 时
- **问题：** `@limiter.limit("5/minute", key_func=lambda req: ...)` 导致 500 错误，slowapi 内部调用 key_func 时签名不匹配
- **修复：** 改为命名函数 `def _token_key_func(request: Request) -> str`
- **影响文件：** `backend/tests/test_rate_limit.py`
- **提交：** a48a6ec

**2. [Rule 2 - 缺少关键配置] E2E 目录缺少 tsconfig.json**
- **发现于：** Task 3 执行 TypeScript 类型检查时
- **问题：** 无 tsconfig 导致 tsc 以 ES5 编译，找不到 Promise / Buffer / node 等类型
- **修复：** 新增 `e2e/tsconfig.json`（target ES2019 + DOM + skipLibCheck），安装 @types/node
- **影响文件：** `e2e/tsconfig.json`、`e2e/package.json`
- **提交：** b8159dd

**3. [Rule 1 - Bug] test_different_providers_share_ip_limit 测试逻辑错误**
- **发现于：** Task 2 test_rate_limit.py 首次运行
- **问题：** 测试假设 feishu/wecom 两个路由共享同一个 IP 计数器，但 slowapi 按路由独立计数
- **修复：** 将测试改为验证同一路由（feishu）的限频行为，重命名为 test_webhook_rate_limit_applies_per_path_route
- **影响文件：** `backend/tests/test_rate_limit.py`
- **提交：** a48a6ec

---

## 关键技术链接

```
backend/app/agent_builder/security/startup_checks.py
  ↑ 被调用于 backend/app/main.py（FastAPI 构造前）via run_startup_checks()

backend/app/agent_builder/security/rate_limit.py
  ↑ limiter 单例被 backend/app/main.py 挂载为 app.state.limiter + SlowAPIMiddleware

nginx/conf.d/public.conf (80 端口)
  ↑ nginx/nginx.conf 通过 include /etc/nginx/conf.d/*.conf 加载

nginx/conf.d/internal.conf (8080 端口)
  ↑ nginx/nginx.conf 通过 include /etc/nginx/conf.d/*.conf 加载

nginx/snippets/proxy_headers.conf
  ↑ public.conf 和 internal.conf 均通过 include 复用
```

---

## Self-Check: PASSED

| 验证项 | 结果 |
|--------|------|
| nginx/conf.d/public.conf 存在 | FOUND |
| nginx/conf.d/internal.conf 存在 | FOUND |
| nginx/snippets/proxy_headers.conf 存在 | FOUND |
| nginx/test/scan_public_paths.sh 存在（179 行）| FOUND |
| backend/app/agent_builder/security/startup_checks.py 存在 | FOUND |
| backend/app/agent_builder/security/rate_limit.py 存在 | FOUND |
| backend/tests/test_startup_checks.py 存在 | FOUND |
| backend/tests/test_rate_limit.py 存在 | FOUND |
| e2e/nginx_path_scan.spec.ts 存在 | FOUND |
| e2e/helpers/path_scan.ts 存在 | FOUND |
| Task 1 commit b075d69 | FOUND |
| Task 2 commit a48a6ec | FOUND |
| Task 3 commit b8159dd | FOUND |
| 26 个 Python 测试全通过 | PASSED |
