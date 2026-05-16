# FORK_AUDIT — Onelevenvy/flock 快照盘点

> 日期：2026-05-16
> Fork 来源：https://github.com/Onelevenvy/flock
> Fork 时 commit：`8b6aebbf1530d3968c050c422a8ed69e1de610e5`
> 同步策略：**Never merge** — fork = 快照，自此独立演进

## 1. 上游版本盘点

| 维度 | 版本 / 状态 | 备注 |
|------|------------|------|
| Python | `requires-python = ">=3.12"` | flock 锁定 3.12，我们的 STACK.md 锁 3.11+，**冲突**：以 STACK.md 为准，将 pyproject 改为 `>=3.11` |
| FastAPI | `>=0.110.0` | 老于 STACK.md 锁定的 0.136.1，需升级 |
| Pydantic | `>=2.0` | 已是 v2，无需迁移 |
| SQLModel | `>=0.0.21` | flock 用 SQLModel 而非裸 SQLAlchemy；Phase 1 添加 SQLAlchemy 2.0.49 + asyncpg 与之共存（业务表用 SQLAlchemy 直接定义） |
| psycopg | `>=3.1.13` | 已是 psycopg3，符合 langgraph-checkpoint 要求 |
| Alembic | `>=1.12.1` | 较旧，需升至 1.18.4 |
| Authentication | `passlib[bcrypt]>=1.7.4` | STACK.md 已废 passlib，迁 `pwdlib[argon2]` 0.3.0 |
| Sentry SDK | 包含 | 保留 |
| LangChain / LangGraph | `langgraph>=0.3.5` | 远低于 STACK.md 锁定 1.2.0，需升级 |
| Next.js | `^15.2.3` | 低于 STACK.md 锁定 16.2，**Phase 1 暂保留 15.2.3 不强升**（避免引入 codemod 风险，CONTEXT.md `<tailwind_shadcn>` 已说明） |
| @xyflow/react | `^12.6.0` | 已是 v12，符合 |
| Zustand | `^5.0.3` | 符合 |
| Tailwind CSS | `^4.0.15` | 已是 v4，符合 |
| React Flow 节点类型 | 未发现 `register_node` 装饰器模式 | flock 用 routes 注册而非 NodeRegistry；新建 `flock.app.node_registry` 模块（Phase 2） |
| docker-compose | `docker/docker-compose.yml` | flock 自带，使用 nginx + frontend + api + db + redis + qdrant + celery 多服务；我们**替换**为 Phase 1 6-service 精简版 |

## 2. 改造点清单

| 项 | 操作 | 说明 |
|----|------|------|
| flock RAG / Subgraph / MCP 节点 | **keep**（保留代码）+ **hide**（运行时隐藏） | 不删源码，仅 Phase 2 NodeRegistry 不注册它们 |
| flock 现有 auth (passlib + JWT) | **replace** | v1 用我们的 PyJWT 2.12.1 + pwdlib argon2 |
| flock docker-compose | **replace** | 重写为 6-service：api / worker / web / postgres / redis / nginx |
| flock UI 品牌字串（Flock → agent-builder） | **replace** | 外部可见层全替换；内部代码 `from flock.xxx` import 保留 |
| flock pyproject `name = "flock"` | **replace** | 改 `name = "agent-builder-backend"` |
| flock web `name = "web"` | **replace** | 改 `name = "agent-builder-web"` |
| flock 现有 NodeRegistry | **新增** | Phase 2 引入新 `flock.app.node_registry` 仅注册 v1 节点类型 |
| flock celery 任务 | **replace** | v1 用 arq 0.28.0 替代 |
| flock qdrant 依赖 | **deferred** | Phase 1 不需要向量库，docker-compose 移除 qdrant；保留 backend 代码内可能存在的 qdrant client，运行时不连即可 |
| flock Chakra UI | **keep**（先用） | Phase 1 不引入 shadcn 强升级；UI 表单仍可在 Chakra 上写 |
| FLOCK_* env 前缀 | **replace** | 改为 AGENT_BUILDER_* （在 .env.example 体现，运行时若 flock 代码读取 `FLOCK_*`，保持向后兼容） |

## 3. Fork Discipline 自查

| 检查项 | 状态 |
|--------|------|
| flock 原 .py 文件**逻辑**未改动（仅替换字符串字面量） | OK — 本 plan 仅 cp 原文件 + 添加新增模块 |
| 所有新增模块作为独立 sub-package（不动 flock 原目录树） | OK — `backend/app/db/` `backend/app/services/` `backend/app/middleware/` 都是新增 sub-package |
| Python import path 保持 `from flock.xxx`（实际：`from app.xxx`，因 flock 上游也是 `app` 作为顶级包名） | NOTE — flock 上游 backend 顶级包就叫 `app`，不是 `flock`。CLAUDE.md 中说 "保留 flock 字样" 是泛指上游，实际 import 用 `from app.xxx` |
| docker-compose / .env.example / README 是**新增**文件，未覆盖 flock 原文件 | OK |
| nginx 配置作为新增 conf 文件，不覆盖 flock 原 conf | OK — flock 原 `docker/nginx/flock.conf` 保留；新增 `nginx/conf.d/public.conf` 与 `internal.conf` 在 Plan 03 中创建 |

## 4. 目录结构对比

```
agent-builder/
├── backend/          # ← cp 自 flock/backend
│   ├── app/          # 原结构保留
│   │   ├── api/      # flock 原有
│   │   ├── core/     # flock 原有 + 新增 startup_checks.py / rate_limit.py
│   │   ├── db/       # 新增（multi-tenant）
│   │   ├── services/ # 新增（Auth 服务层）
│   │   ├── middleware/ # 新增
│   │   ├── models/   # 新增（v1 业务表 ORM）
│   │   └── schemas/  # 新增（pydantic v2 请求/响应）
│   ├── alembic/      # flock 原有；新增 versions/0001_phase1_schema.py
│   ├── tests/        # 新增三层测试用例
│   └── Dockerfile    # 覆写 flock 原版（多阶段 + uv）
├── web/              # ← cp 自 flock/web
│   ├── src/          # flock 原结构保留
│   ├── app/          # 新增 Next.js App Router（与 src/ 共存）
│   ├── lib/          # 新增 api client + stores
│   ├── components/   # 新增 setup-wizard / login-form 等
│   └── Dockerfile    # 覆写 flock 原版
├── e2e/              # 新增 Playwright 测试
├── nginx/            # 新增（保留 flock docker/nginx/flock.conf 作参考）
├── scripts/          # 新增
└── docker-compose.yml # 新增 6-service 配置
```

## 5. Audit 结论

- 本 fork 是一次性快照；后续与 Onelevenvy/flock 无任何同步关系
- 外部可见层（package name / Docker image / docker-compose service / README）全部 rebrand 为 agent-builder
- 内部 Python 顶级包 `app` 保留（flock 上游就是 `app`）
- Phase 1 新增模块均作为独立 sub-package，未改动 flock 原 .py 文件逻辑代码

---

*FORK_AUDIT generated for Phase 1, Plan 01-01.*
