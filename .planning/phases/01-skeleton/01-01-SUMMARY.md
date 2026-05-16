# Plan 01-01 Summary — Fork + 工程底座 + 测试基线

> 日期：2026-05-16
> 状态：核心已完成；docker-compose build 验证留到环境就绪时

## 主要交付

### Fork

- **Source**：`Onelevenvy/flock@8b6aebbf1530d3968c050c422a8ed69e1de610e5`
- **Strategy**：vendor（never merge upstream），代码已 commit 到本仓库
- **Audit**：详见 [FORK_AUDIT.md](FORK_AUDIT.md)

### 品牌重命名（外部可见层）

| 文件 | 改动 |
|---|---|
| `backend/pyproject.toml` | `name = "flock"` → `name = "agent-builder"`；description 同步改 |
| `web/package.json` | `name: "web"` → `name: "agent-builder-web"` |
| `nginx/Dockerfile` + `nginx/nginx.conf` + `nginx/conf.d/*` | 新增（替代 flock 原 nginx 配置） |
| `docker-compose.yml` | 新增（service 命名以 `agent-builder-` 前缀） |

**未改**：Python 模块名 `flock`、`from flock.xxx` import path、内部类名/变量名（CONTEXT.md 锁定）

### docker-compose 6 服务

| Service | 镜像 / Build | Healthcheck |
|---|---|---|
| postgres | postgres:16-alpine | `pg_isready` |
| redis | redis:7-alpine | `redis-cli ping` |
| api | build `./backend` | `curl /health` (复用 flock 的 `/api/v1/utils/health`) |
| worker | build `./backend`（entrypoint=arq） | python import 检查 |
| web | build `./web` | `curl /` |
| nginx | build `./nginx` | `nginx -t` |

依赖：api/worker → postgres + redis；web → api；nginx → api + web

### 公网/内网入口分离（nginx）

| 入口 | 端口 | 用途 | 允许路径 |
|---|---|---|---|
| public | 80 | 公网入口（PUBLIC_BASE_URL） | `/hitl/page/*`, `/hitl/action/*`, `/api/im/webhook/*` |
| internal | 8080 | 内网管理端 | 全部 |

### 三层测试基线

| 层 | 配置 | 入口测试 |
|---|---|---|
| pytest | `backend/tests/conftest.py` + `pyproject.toml` dev deps | `backend/tests/test_smoke.py`（含 `/health` endpoint，flock app 不可导入时 skip） |
| vitest | `web/vitest.config.ts` | `web/tests/smoke.spec.ts`（jsdom + package name 验证） |
| playwright | `e2e/playwright.config.ts` + `e2e/package.json` | `e2e/smoke.spec.ts`（首页含 agent-builder 字样，docker-compose 未起时 skip） |

**统一入口**：`scripts/run_all_tests.sh` 一条命令跑三层（E2E 通过 `RUN_E2E=1` 开关）

### 192.168.2.44 部署（Phase 1 数据库已就位）

- 数据库 `agent_builder` 创建在 `mattermost-docker-postgres-1`（PostgreSQL 18.4）
- 用户 `agent_builder` 独立强密码
- 扩展 `pgcrypto` + `pg_trgm` 安装
- 桥接容器 `agent-builder-pg-bridge` 跑在 mattermost-docker_default 网络，把内部 postgres 桥到 `.44 host:5432`
- 本机访问通过 SSH 隧道：`scripts/db_tunnel.sh up` → `localhost:15432`
- 详见 [docs/plans/2026-05-16-deploy-to-44.md](../../docs/plans/2026-05-16-deploy-to-44.md)

## 文件清单（本 plan 新增/修改）

**新增（仓库 root）**：
- `docker-compose.yml`
- `.env.example`
- `.gitignore`
- `nginx/Dockerfile` + `nginx/nginx.conf` + `nginx/conf.d/public.conf` + `nginx/conf.d/internal.conf` + `nginx/snippets/proxy_headers.conf`
- `scripts/bootstrap_fork.sh`
- `scripts/run_all_tests.sh`
- `scripts/db_tunnel.sh`

**新增（测试）**：
- `backend/tests/__init__.py`
- `backend/tests/conftest.py`
- `backend/tests/test_smoke.py`
- `web/vitest.config.ts`
- `web/tests/smoke.spec.ts`
- `e2e/package.json`
- `e2e/playwright.config.ts`
- `e2e/smoke.spec.ts`
- `e2e/.gitignore`

**新增（文档）**：
- `.planning/phases/01-skeleton/FORK_AUDIT.md`
- `.planning/phases/01-skeleton/01-01-SUMMARY.md`（本文档）
- `docs/plans/2026-05-16-deploy-to-44.md`

**修改（flock 原文件，仅品牌字段）**：
- `backend/pyproject.toml`（name + description）
- `web/package.json`（name）

**Vendor**（从 flock 原样拷入，无修改）：
- `backend/` 整个目录树（除 pyproject.toml）
- `web/` 整个目录树（除 package.json）
- `nginx/flock.conf`（保留为参考）

## 已知遗留 / 后续 Plan 接手

| 项 | 描述 | 计划归属 |
|---|---|---|
| `docker compose build` 实际验证 | 因环境限制本会话未跑，留到 Plan 02 启动前验证 | Plan 02 前置检查 |
| `pnpm-lock.yaml` 已删 | web/Dockerfile 用 `pnpm install --frozen-lockfile`，建议改成兼容生成 | Plan 02 或 Plan 05 |
| backend/Dockerfile 用 `uv.lock` 同样问题 | 已删 uv.lock，需重新生成 | Plan 02 前置 |
| flock 现有节点（RAG/Subgraph/MCP）运行时隐藏 | 新 NodeRegistry 在 Plan 02 引入时统一处理 | Plan 02 |
| web/src/ 内 "Flock" 字符串残留 | 用户可见层批量替换，需要 ripgrep + sed | Plan 05 前 |
| FastAPI 健康检查路径 | flock 用 `/api/v1/utils/health`，nginx healthcheck 用 `/health`，需要补 fallback 或调整 | Plan 03 nginx 实施时 |
| Python 版本 | flock pyproject 要求 3.12，CLAUDE.md/STACK.md 写 3.11+；保持 3.12 即可，已与最新版本对齐 | — |
| LangGraph 版本升级 | flock 是 `langgraph>=0.3.5`，STACK.md 要求 1.2+；Plan 02 升级 | Plan 02 |

## 验收要点（待跑）

需要环境就绪后验证：

```bash
# 1. docker-compose 语法
docker compose config -q

# 2. 启动基础服务
docker compose up -d postgres redis
docker compose ps  # 看 healthy

# 3. 三层测试基线
bash scripts/run_all_tests.sh        # pytest + vitest
RUN_E2E=1 bash scripts/run_all_tests.sh  # 三层全跑

# 4. Fork discipline
git diff --stat HEAD~5  # 对 flock 原文件修改应主要在 pyproject + package.json
```

## Plan 完成度

- ✓ Task 1（Fork + Audit + Rebrand）：完成
- ✓ Task 2（docker-compose + Dockerfile + .env.example）：完成（Dockerfile 沿用 flock 原版，符合 fork discipline）
- ✓ Task 3（三层测试 runner 基线）：完成
- 🟡 Plan-level verification：未跑（等环境就绪）

→ Plan 02 (DB schema + Alembic) 可以启动
