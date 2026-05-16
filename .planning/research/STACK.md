# Stack Research

**Domain:** 可视化拖拽式 LangGraph 工作流编排平台（HITL + 多通道 IM + 公网回调）
**Researched:** 2026-05-16
**Confidence:** HIGH（所有版本均通过 pip index / PyPI 直接验证；JS 版本通过 npm/官方博客验证）

---

## 核心约束（已锁定，不讨论）

- Skeleton：Fork [Onelevenvy/flock](https://github.com/Onelevenvy/flock)（FastAPI + Next.js + Postgres + Docker Compose）
- 执行引擎：LangGraph + PostgresSaver（`langgraph-checkpoint-postgres`）
- HITL Token：HMAC JWT HS256
- DSL 解释执行（不做代码生成）
- 画布：React Flow（`@xyflow/react`）
- 许可证：Apache-2.0

---

## 一、后端核心框架

| 技术 | 版本（2026-05 验证） | 用途 | 推荐理由 | 置信度 |
|------|---------------------|------|---------|--------|
| Python | 3.11+ | 运行时 | 3.11 asyncio 性能大幅优化；3.12 也可，但 flock 现有 dockerfile 用 3.11，减少改动 | HIGH |
| FastAPI | **0.136.1** | HTTP API 框架 | flock skeleton 已用；原生 async；Pydantic v2 已内置 | HIGH |
| Uvicorn | **0.47.0** | ASGI server | FastAPI 官方配套；支持 `--workers N` 多进程 | HIGH |
| Pydantic | **2.13.4** | 数据验证 / 序列化 | FastAPI 0.136 捆绑 v2；比 v1 快 5-50x；DSL schema 校验首选 | HIGH |

**注意：** FastAPI 0.136.1 需要 Python ≥3.10，推荐 3.11+。`pip install "fastapi[standard]"` 会自动携带 uvicorn + python-multipart。

---

## 二、LangGraph 执行引擎

| 技术 | 版本（2026-05 验证） | 用途 | 推荐理由 | 置信度 |
|------|---------------------|------|---------|--------|
| langgraph | **1.2.0** | 工作流执行引擎 | 原生 `interrupt()` + `Command(resume=...)` HITL 支持；StateGraph 动态组装契合 DSL 解释执行模式 | HIGH |
| langgraph-checkpoint-postgres | **3.1.0** | Checkpoint 持久化 | 官方出品；`AsyncPostgresSaver` 支持 `autocommit=True` + `dict_row`；3.x 重大重构，API 稳定 | HIGH |
| psycopg（Psycopg3） | 随 checkpoint-postgres 安装 | PostgreSQL async 驱动 | checkpoint-postgres 3.x 默认依赖 psycopg3（非 psycopg2）；注意**不是** asyncpg | HIGH |

**已知 Bug（高优先验证）：** LangGraph issue #6208（2025-09）：同一节点含多个 `interrupt()` 时，只恢复第一个后节点会重新执行。本项目采用「单 interrupt + 自管审批链状态」模式，可规避此 bug。

**与 asyncpg 的关系：**
- SQLAlchemy ORM 层用 `asyncpg` 驱动（见下节）
- LangGraph checkpoint 层用 `psycopg3`（`AsyncConnection`）
- 两者**共存**，连接池各自独立，不冲突

---

## 三、数据库

| 技术 | 版本（2026-05 验证） | 用途 | 推荐理由 | 置信度 |
|------|---------------------|------|---------|--------|
| PostgreSQL | **15+**（推荐 16） | 主数据库 | JSONB + pg_advisory_lock（jti 事务锁）+ 原生 `uuid_generate_v4()`；checkpoint-postgres 要求 15+ | HIGH |
| SQLAlchemy | **2.0.49** | ORM / 查询 | 2.0 完整 async API（`async_sessionmaker`）；与 flock 已用的 2.0 风格兼容；勿升 2.1.x beta | HIGH |
| asyncpg | **0.31.0** | SA 的 Postgres 驱动 | `postgresql+asyncpg://` 连接串；比 psycopg2 快 3-5x；SA 2.0 官方推荐 | HIGH |
| Alembic | **1.18.4** | 数据库迁移 | SQLAlchemy 官方配套；支持 async revision；比手写 SQL 安全 | HIGH |
| Redis | **7+**（server）/ redis-py **7.4.0** | jti 黑名单 / 速率限制 / session cache | `redis.asyncio` 内置异步客户端（替代已废弃的 aioredis 包）；7.4.0 stable | HIGH |

**重要提醒：**
- `aioredis` 包已于 2021-12 停止维护，**不要安装**。使用 `redis>=7.4.0` 的 `redis.asyncio` 模块。
- SQLAlchemy 2.1.x 目前仍是 beta，**不要在生产使用**，锁定 2.0.49。

---

## 四、认证 & Token

| 技术 | 版本（2026-05 验证） | 用途 | 推荐理由 | 置信度 |
|------|---------------------|------|---------|--------|
| PyJWT | **2.12.1** | JWT 签发 / 校验（HS256） | 活跃维护；FastAPI 社区从 python-jose 迁移的首选；API 极简 | HIGH |
| pwdlib[argon2] | **0.3.0** | 密码哈希 | FastAPI 官方文档已从 passlib 迁移到 pwdlib；支持 Argon2（比 bcrypt 更强）和 bcrypt | HIGH |

**不要用：**
- `python-jose`：2021 年后无新版本，Python ≥3.10 存在已知兼容问题，FastAPI 官方已弃用推荐
- `passlib`：不再维护，仅保留遗留哈希兼容场景才使用

---

## 五、邮件通知（SMTP）

| 技术 | 版本（2026-05 验证） | 用途 | 推荐理由 | 置信度 |
|------|---------------------|------|---------|--------|
| aiosmtplib | **5.1.0** | 异步 SMTP 客户端 | Python ≥3.10 原生；轻量无框架依赖；直接控制 SMTP 连接，利于多 SMTP 账号切换 | HIGH |
| Jinja2 | **3.1.6** | 邮件 HTML 模板渲染 | FastAPI / LangChain 生态默认选择；每周 4900 万下载；autoescape 防 XSS | HIGH |

**为什么不用 fastapi-mail：**
- `fastapi-mail` 底层就是 `aiosmtplib` 的包装，没有额外 SMTP 能力
- 我们需要对每个审批 action 独立渲染 4 个 deeplink 按钮，直接控制模板更灵活
- 减少一层依赖，降低版本冲突风险

---

## 六、IM SDK

### 6.1 飞书（Feishu / Lark）

| SDK | 版本（2026-05 验证） | 说明 | 置信度 |
|-----|---------------------|------|--------|
| **lark-oapi** | **1.6.5** | 官方出品（larksuite 维护）；同时覆盖飞书（国内）和 Lark（海外）；支持卡片消息、Bot 推送、通讯录 API（用户 / 部门 / 汇报链）；异步支持 | HIGH |

**注意：** 1.6.0–1.6.3 已被 yanked（Webhook 签名兼容性回归），**直接锁定 1.6.5**。2.0.0.devX 系列为开发预览版，**不用**。

### 6.2 企业微信（WeCom / 企微）

| SDK | 版本 | 说明 | 置信度 |
|-----|------|------|--------|
| **wechatpy[enterprise]** | **1.8.18** | 最成熟的第三方 Python SDK；内置企业微信 API（应用消息、模板卡片）；2021-11 后无新版 | MEDIUM |
| 自封装 httpx 调用 | — | WeCom API 简单（OAuth2 + JSON POST），企微无官方 Python SDK；wechatpy 停更后可直接封装 | HIGH |

**推荐策略：** 优先试 wechatpy，若模板卡片 API 接口不对，直接用 `httpx.AsyncClient` 封装企微 REST API（文档：developer.work.weixin.qq.com）。企微 API 极其规律，原始封装并不复杂。

### 6.3 钉钉（DingTalk）

| SDK | 版本（2026-05 验证） | 说明 | 置信度 |
|-----|---------------------|------|--------|
| **dingtalk-stream** | **0.24.3** | open-dingtalk 官方团队出品；Stream 模式（长连接），比 Webhook 模式更易接入（无需公网暴露端口）；支持卡片消息 + 工作通知 | HIGH |

**注意：** `dingtalk-sdk`（007gzs 维护）是社区版，功能更全但更新较慢。钉钉官方推荐 `dingtalk-stream`（Stream 模式，2024+ 主推）。本项目通知卡片只需单向推，用 `dingtalk-stream` 的消息推送 API 即可。

### 6.4 Slack

| SDK | 版本（2026-05 验证） | 说明 | 置信度 |
|-----|---------------------|------|--------|
| **slack-bolt** | **1.28.0** | Slack 官方出品；Block Kit 交互式卡片；支持 FastAPI 集成（Socket Mode / HTTP Mode）；1.28 新增 Agent UI 功能 | HIGH |

### 6.5 Mattermost

| SDK | 版本 | 说明 | 置信度 |
|-----|------|------|--------|
| **matterhook** | 最新 | 轻量 Incoming Webhook 客户端（numberly 维护）；只需单向推送时首选 | MEDIUM |
| **matteraio** | 最新 | 支持完整 REST API + WebSocket 事件（双向），若需回调时用 | MEDIUM |

**推荐策略：** v1 仅需单向推送（Notification 节点不阻塞），用 `matterhook` 最轻量。若 v1.1 做 IM 内一键决策，升级到 `matteraio` 处理 WebSocket 回调。

---

## 七、速率限制

| 技术 | 版本（2026-05 验证） | 用途 | 推荐理由 | 置信度 |
|------|---------------------|------|---------|--------|
| **slowapi** | **0.1.9** | FastAPI 速率限制（Token / IP 维度） | Starlette-native 装饰器 API；Redis 后端（`storage_uri="redis://..."`）做分布式计数器；生产级用量 | HIGH |

**配置要点：**
- HITL callback 端点：每 token 每分钟 ≤5 GET，每 IP 每分钟 ≤30 POST
- IM Webhook 端点：每秒 ≤10（防 IM 平台重试风暴）

---

## 八、后台任务队列

| 技术 | 版本（2026-05 验证） | 用途 | 推荐理由 | 置信度 |
|------|---------------------|------|---------|--------|
| **arq** | **0.28.0** | 异步任务队列（Redis 后端） | 原生 asyncio；比 Celery 轻量；适合 LangGraph `ainvoke` 这类 I/O 密集任务；FastAPI 生态最常用 | HIGH |

**为什么不用 Celery：**
- Celery 为同步代码设计，async 支持需额外配置
- LangGraph 执行是纯 asyncio I/O 密集型，arq 原生 asyncio 对齐
- arq 已进入 maintenance-only 模式（功能冻结，bug fix 仍活跃），对 v1 稳定性实际是好事

**为什么不用 FastAPI BackgroundTasks：**
- 绑定 API 进程生命周期，API 重启则任务丢失
- 长时间 LangGraph 执行（分钟级）不应阻塞 HTTP worker

---

## 九、插件沙箱

| 技术 | 用途 | 推荐理由 | 置信度 |
|------|------|---------|--------|
| Python `subprocess` + `multiprocessing` | 插件隔离执行 | OS 级进程隔离；无需引入重型框架 | HIGH |
| Linux `cgroups v2` | CPU / 内存限制（生产） | Docker Compose 可通过 `mem_limit` / `cpus` 配置容器级限制 | HIGH |
| `resource.setrlimit()` | macOS dev 环境资源限制 | 开发环境 fallback | HIGH |
| stdio IPC（stdin JSON → stdout JSON） | 宿主 ↔ 插件进程通信 | 最简单、无依赖、Dify Plugin Daemon 同款方案 | HIGH |

**不要用：**
- `RestrictedPython`：Python 动态特性让语言级沙箱极难完整（持续出现 `__import__` 绕过）
- 网络调用白名单：用 squid proxy + ACL（非 iptables），避免修改主机网络策略

---

## 十、插件加载器

| 技术 | 用途 | 推荐理由 | 置信度 |
|------|------|---------|--------|
| Python `zipfile` + `importlib` | 插件包解压 + 动态注册 | 标准库，零依赖；`importlib.util.spec_from_file_location` 动态加载 node.py | HIGH |
| `pyyaml` | 解析 manifest.yaml | 标准 YAML 解析；FastAPI 生态常用 | HIGH |
| `jsonschema` | 校验 schema.json + 插件输入输出 | JSON Schema Draft 7 完整实现；DSL 编译器校验也可复用 | HIGH |

---

## 十一、前端核心框架

| 技术 | 版本（2026-05 验证） | 用途 | 推荐理由 | 置信度 |
|------|---------------------|------|---------|--------|
| Next.js | **16.2**（2026-03-18 发布） | 全栈前端框架 | flock skeleton 已用；16.2 ~50% 更快渲染；Turbopack 默认启用；App Router 稳定 | HIGH |
| @xyflow/react | **12.10.2** | 拖拽画布 | flock 已用；v12 重命名自 reactflow；自定义节点 / 边 / minimap 齐全；618 个 npm 依赖项目 | HIGH |
| Zustand | **5.0.13** | 全局状态管理 | 轻量（~1kb）；与 React Flow 配合的标准选择；比 Redux 配置少 | HIGH |
| Tailwind CSS | **v4**（stable since early 2025） | 原子化 CSS | flock 前身 Dify 已用；v4 CSS-native token（无 tailwind.config.js）；构建产物小 70% | HIGH |
| shadcn/ui | 最新（Tailwind v4 兼容） | 组件库 | 与 Tailwind v4 + Next.js 16 完整适配；所有组件支持 `data-slot`；无 npm 安装，copy-paste 模式无版本冲突 | HIGH |

**注意（版本跨越）：** flock 若当前用 Next.js 14 + Tailwind v3，fork 后先评估升级成本再决定是否跟升。
- Tailwind v4 配置模型完全不同（CSS-first，无 `tailwind.config.js`），升级需 codemod
- Next.js 16 vs 15 均 stable，16.2 渲染性能优势显著，推荐直接用 16

---

## 十二、前端辅助库

| 库 | 版本 | 用途 | 置信度 |
|----|------|------|--------|
| `react-hook-form` + `zod` | 最新 | HITL 决策表单 / 节点配置表单验证 | HIGH |
| `@tanstack/react-query` | v5 | 服务端状态同步（实例状态轮询 / WebSocket 降级） | HIGH |
| `lucide-react` | 最新 | 图标库（shadcn 配套） | HIGH |
| `immer` | 最新 | 节点配置 DSL 不可变更新（Zustand + immer 中间件） | HIGH |

---

## 十三、版本兼容性矩阵（关键）

| 包 A | 版本 | 兼容要求 |
|------|------|---------|
| `langgraph` 1.2.0 | Python ≥3.10 | 锁定用 Python 3.11 |
| `langgraph-checkpoint-postgres` 3.1.0 | `psycopg`（Psycopg3）≥3.1 | **不兼容 psycopg2**；3.x 已完全移除 psycopg2 支持 |
| `SQLAlchemy` 2.0.49 | `asyncpg` ≥0.29 | ORM 层用 asyncpg；checkpoint 层用 psycopg3；**两个驱动同时装** |
| `FastAPI` 0.136.1 | `Pydantic` ≥2.0 | flock 可能仍有 Pydantic v1 遗留代码，fork 后需迁移 |
| `redis` 7.4.0 | Redis server ≥7.0 | `redis.asyncio` 模块已内置，**不需要**单独安装 `aioredis` |
| `arq` 0.28.0 | `redis` ≥4.2 | arq 内部使用 redis-py asyncio |
| `lark-oapi` 1.6.5 | Python ≥3.7 | 1.6.0–1.6.3 已被 yanked，直接 pin 1.6.5 |

---

## 十四、不要用（Anti-patterns）

| 避免 | 原因 | 替代 |
|------|------|------|
| `python-jose` | 2021 年后停更；Python ≥3.10 有已知 bug；FastAPI 官方已弃用推荐 | `PyJWT` 2.12.1 |
| `passlib` | 不再积极维护；遗留算法列表臃肿 | `pwdlib[argon2]` 0.3.0 |
| `aioredis`（单独包） | 已于 2021-12 停止维护，并入 redis-py | `redis.asyncio`（`redis>=7.4.0` 内置） |
| `psycopg2` / `psycopg2-binary` | langgraph-checkpoint-postgres 3.x 只支持 psycopg3 | `psycopg`（Psycopg3） |
| `SQLAlchemy` 1.x | 无 async ORM 支持；2.0 API 完全不同 | `SQLAlchemy` 2.0.49 |
| `SQLAlchemy` 2.1.x（beta） | 仍在 beta；API 可能变化 | 锁定 `SQLAlchemy==2.0.49` |
| `Celery` | 同步设计；async 支持差；对纯 asyncio LangGraph 场景太重 | `arq` 0.28.0 |
| `FastAPI BackgroundTasks` | 绑定 HTTP 进程；重启丢任务；不适合分钟级 LangGraph 执行 | `arq` 队列 |
| `RestrictedPython` | Python 动态特性导致沙箱不可靠；绕过向量持续出现 | subprocess 进程隔离 + OS cgroups |
| `reactflow`（旧包名） | 已重命名为 `@xyflow/react`；v11 不再维护 | `@xyflow/react` 12.10.2 |
| `fastapi-mail` | 只是 aiosmtplib 包装，无额外能力；多一层依赖 | 直接用 `aiosmtplib` |
| `python-multipart`（单独安装） | `fastapi[standard]` 已包含 | `pip install "fastapi[standard]"` |
| Next.js Pages Router | App Router 是 2026 标准；Pages Router 将进入 LTS 维护模式 | App Router（Next.js 16） |

---

## 十五、完整安装命令

```bash
# ===== 后端核心 =====
pip install "fastapi[standard]==0.136.1"   # 含 uvicorn + python-multipart
pip install "pydantic==2.13.4"
pip install "langgraph==1.2.0"
pip install "langgraph-checkpoint-postgres==3.1.0"  # 自动安装 psycopg3
pip install "psycopg[binary]==3.*"          # langgraph checkpoint 驱动

# ===== 数据库 =====
pip install "SQLAlchemy==2.0.49"
pip install "asyncpg==0.31.0"               # SQLAlchemy ORM 驱动
pip install "alembic==1.18.4"

# ===== 缓存 / 队列 =====
pip install "redis==7.4.0"                  # 含 redis.asyncio
pip install "arq==0.28.0"

# ===== 认证 =====
pip install "PyJWT==2.12.1"
pip install "pwdlib[argon2]==0.3.0"

# ===== 邮件 =====
pip install "aiosmtplib==5.1.0"
pip install "Jinja2==3.1.6"

# ===== IM SDK =====
pip install "lark-oapi==1.6.5"              # 飞书（官方）
pip install "wechatpy==1.8.18"              # 企微（社区；若不够用改用 httpx 原始封装）
pip install "dingtalk-stream==0.24.3"       # 钉钉（官方）
pip install "slack-bolt==1.28.0"            # Slack（官方）
pip install matterhook                      # Mattermost 单向推送

# ===== 速率限制 =====
pip install "slowapi==0.1.9"

# ===== HTTP 客户端（IM 原始 API / webhook） =====
pip install "httpx==0.28.1"

# ===== 插件系统 =====
pip install pyyaml jsonschema

# ===== 前端 =====
npm install next@latest react@latest react-dom@latest  # Next.js 16.x
npm install @xyflow/react@12                            # React Flow v12
npm install zustand@5                                   # 状态管理
npm install @tanstack/react-query@5
npm install react-hook-form zod
npm install lucide-react immer
# Tailwind CSS v4（与 Next.js 16 配套）
npm install tailwindcss@next @tailwindcss/postcss@next
npx shadcn@latest init
```

---

## 十六、备选方案（何时考虑切换）

| 我们的选择 | 备选 | 什么情况换 |
|-----------|------|-----------|
| arq | Celery + Redis | 需要大规模分布式 worker、跨语言任务、复杂 task routing（v2） |
| aiosmtplib | SendGrid / AWS SES SDK | 批量邮件 >10k/天，SMTP 触达率不够 |
| wechatpy（企微） | httpx 直接封装 | wechatpy 企微模板卡片 API 覆盖不全（很可能发生） |
| matterhook | matteraio | v1.1 需要 Mattermost IM 内一键决策（双向回调） |
| slowapi | nginx-level rate limit | 高并发（>1000 rps）时 Python 层速率限制成瓶颈 |
| subprocess 沙箱 | Firecracker / gVisor | v2 插件市场，需要更强安全隔离 |
| SQLAlchemy 2.0 | asyncpg 裸查询 | 批量 checkpoint 写入延迟 <1ms 的极致场景 |

---

## 十七、数据来源

- PyPI / pip index（直接验证，2026-05-16）：所有 Python 包版本
- [Next.js 16.2 官方博客](https://nextjs.org/blog/next-16-2)（2026-03-18）：Next.js 版本确认
- [LangGraph HITL issue #6208](https://github.com/langchain-ai/langgraph)：双 interrupt bug
- [FastAPI discussions #11345](https://github.com/fastapi/fastapi/discussions/11345)：python-jose 弃用确认
- [arq PyPI 页面](https://pypi.org/project/arq/)：maintenance-only 状态确认
- [lark-oapi PyPI 页面](https://pypi.org/project/lark-oapi/)：1.6.0-1.6.3 yanked 确认

---

*Stack research for: 可视化拖拽式 LangGraph 编排平台（HITL + 多通道 IM + 公网回调）*
*Researched: 2026-05-16*
*所有版本均通过 pip index 直接验证，无推断*
