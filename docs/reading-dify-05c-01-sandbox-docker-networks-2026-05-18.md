# Dify 阅读笔记 — Plan 05c-01 SandboxRunner docker_networks 字段扩展

> 日期: 2026-05-18
> 仓库: https://github.com/langgenius/dify (local clone `/Users/admin/ai/ref/dify/repo/`, AGPL-3.0)
> Stars: ~141k
> 本项目许可证: Apache-2.0（agent-builder fork 自 flock）— **严禁拷源代码，仅借鉴设计模式 / 数据结构思路 / 错误处理哲学**

---

## 项目概述（一句话）

Dify 是国内最成熟的开源 LLM 应用平台；其 **plugin 子系统** 通过 `manifest (PluginDeclaration) + 远端独立 daemon 进程 (dify-plugin-daemon, Go) + HTTP/SSE 控制面 (BasePluginClient/PluginInstaller)` 三段式实现第三方扩展（tool / model / endpoint / datasource / trigger / agent-strategy）；**与本 plan 关注的"daemon spawn 后 docker network 副作用"对应的是 Dify daemon lifecycle 强化（manifest 声明 → installer pipeline → 远端 daemon 编排），可借鉴的是 declaration field 扩展节奏 + installer 客户端的错误归一化 + 资源声明分层（permission / resource / scope）**。

## 技术栈（关键技术选择）

- **Pydantic v2 BaseModel + ConfigDict + field_validator / model_validator**（manifest 校验主力 — `core/plugin/entities/plugin.py`）
- **StrEnum** 把"来源 / 类别 / 范围"等离散枚举写成代码可枚举常量（`PluginInstallationSource`, `PluginCategory`, `PluginInstallationScope`）
- **dify-plugin-daemon 是独立 Go 进程**（不是 Python subprocess）—— 用 HTTP/JSON envelope 通信 + `BasePluginClient._request_with_plugin_daemon_response` 统一封装；与 agent-builder Phase 5.B 走 Python `asyncio.create_subprocess_exec` + cgroups v2 的本地 daemon 模型不同，但 **"client 主进程 ⇄ daemon 子系统"的边界抽象高度一致**
- **资源限制委托容器编排层**（Docker / Kubernetes）—— `PluginResourceRequirements` 只声明 memory + permission 矩阵，不亲自 setrlimit / cgroups（vs 我们走 cgroups v2 + setrlimit baseline）
- **httpx 客户端池化 + 集中错误归一化**（`get_pooled_http_client("plugin_daemon", ...)` + `_handle_plugin_daemon_error` 22 种 match-case） — daemon 副作用失败时不向上抛 raw exception，统一翻译为业务异常类型
- **packaging.version.Version 校验 minimum_dify_version**（manifest meta 层做版本兼容性 declaration，给前向 / 后向兼容留口子）

## 架构要点

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 1: Manifest Declaration（声明层）                          │
│  - PluginDeclaration (entities/plugin.py)                       │
│  - PluginResourceRequirements: memory + Permission(tool/model/  │
│    node/endpoint/storage)                                       │
│  - Meta.minimum_dify_version → packaging.Version 校验            │
└──────────────────────────┬──────────────────────────────────────┘
                           │ Pydantic 校验（拒绝非法字段）
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Layer 2: PluginService (services/plugin/plugin_service.py)     │
│  - install_from_local_pkg / install_from_github / from_marketplace│
│  - _check_marketplace_only_permission()                         │
│  - _check_plugin_installation_scope() ← 4 档 enum match-case     │
│  - upgrade_plugin_with_marketplace / with_github                │
└──────────────────────────┬──────────────────────────────────────┘
                           │ 编排逻辑（先 decode → 校 scope → 调 manager）
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Layer 3: PluginInstaller (impl/plugin.py)                      │
│  - upload_pkg / upload_bundle / install_from_identifiers        │
│  - fetch_plugin_manifest / decode_plugin_from_identifier        │
│  - uninstall / upgrade_plugin / check_tools_existence           │
└──────────────────────────┬──────────────────────────────────────┘
                           │ 走 BasePluginClient._request_*
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Layer 4: BasePluginClient (impl/base.py) + daemon (Go process) │
│  - httpx 池化（max_connections=100, keepalive=50）                │
│  - _handle_plugin_daemon_error: 22 错误类型 → 业务异常 match-case │
│  - traceparent 注入（W3C distributed tracing）                   │
└─────────────────────────────────────────────────────────────────┘
```

对应到本 plan 的映射：

- **Layer 1**（Manifest Declaration）⇄ `agent_builder/platforms/manifest.py::SandboxConfig`（本 plan 加 `docker_networks: list[str]` 字段）
- **Layer 2**（Service Orchestration）⇄ `agent_builder/platforms/daemon_client.py::_start`（本 plan 加 1 行 `docker_networks=self._sandbox_config.docker_networks`）
- **Layer 3**（Installer / 工具方法）⇄ `agent_builder/platforms/sandbox/runner.py::SandboxRunner` Protocol（本 plan 在 Protocol 加 kwarg）
- **Layer 4**（Daemon-side 副作用 + 错误归一化）⇄ `agent_builder/platforms/sandbox/cgroups_v2.py::_attach_docker_networks`（本 plan 加 3-mode RuntimeError + terminate daemon）

## 可借鉴的设计模式（5 项，每项含 Dify 路径 + 我们 target 模块映射）

### 1. manifest 字段向后兼容策略：默认值 + Pydantic v2 field_validator

**Dify 源**: `/Users/admin/ai/ref/dify/repo/api/core/plugin/entities/plugin.py:26-58`（`PluginResourceRequirements` + 嵌套 `Permission` class）和 `:82-91`（`Meta.validate_minimum_dify_version` 用 `packaging.Version` 校验）

**Takeaway**: Dify 全部 plugin manifest 字段走 `Field(default=None)` 或 `default_factory=list`，旧 manifest 缺新字段时**不报错，按默认值进入**。新字段加 `@field_validator` 做单值校验（如 `validate_minimum_dify_version` 用 `packaging.Version` 抛 `InvalidVersion → ValueError`），错误信息含字段名 + 实际值（"Invalid version format: {v}"）。

**与本项目映射**: 我们的 `SandboxConfig.docker_networks: list[str] = Field(default_factory=list)` 完全沿用此模式 —— 旧 plugin.yaml（Phase 5.B 7 字段）不需要改任何东西就能兼容；validator `docker_networks_must_be_valid_names` 沿用 Dify 错误信息风格："docker_networks entry 必须符合 docker network 命名规范，实际: {entry!r}"。**不引入嵌套 dict（如 `sandbox.network.docker: [...]`），保持扁平 list，与 Dify `permission.tool.enabled: bool` 同样的浅层结构**，但仍提供精细校验。

### 2. daemon lifecycle hook 注入点：在 install pipeline "spawn 后立即配 / 失败立即 cleanup"

**Dify 源**: `/Users/admin/ai/ref/dify/repo/api/services/plugin/plugin_service.py:400-415`（`install_from_local_pkg`：`decode → check_scope → install_from_identifiers`，每一步独立、可失败、可回滚）以及 `:515-584`（`uninstall`：先查 plugin → 删 credentials → 调 daemon uninstall，每一步事务化）

**Takeaway**: Dify 把 daemon spawn / install / uninstall 拆成多个独立 hook，**每个 hook 失败时调用方负责 cleanup**（如 `install_from_local_pkg` 失败时不会留半装 plugin，因为 `decode` 走在 `install` 前；`uninstall` 失败时 credentials 删除事务在 daemon uninstall 之外，部分失败可独立恢复）。`PluginService` 是一个**编排层**，自己不做副作用，把"做事"全代理给 `PluginInstaller`。

**与本项目映射**: 本 plan 在 `SandboxRunner.spawn_with_limits` 内部做 docker network attach（**spawn 后立即 attach** — single-responsibility）：daemon spawn → attach failed → terminate daemon → raise。Dify 模式启发我们**不在 `daemon_client._start` 里嵌入 attach 逻辑**（daemon_client 是编排层，类似 Dify `PluginService`），attach 留在 `cgroups_v2.py::_attach_docker_networks`（类似 Dify `PluginInstaller`）。`daemon_client._start` 仅 1 行透传，保持编排层薄。

### 3. 失败回滚策略：cleanup-then-raise（避免假成功）

**Dify 源**: `/Users/admin/ai/ref/dify/repo/api/core/plugin/impl/base.py:90-96` 与 `:238-277`（`_request_with_plugin_daemon_response`：HTTP 失败时 `httpx.RequestError → PluginDaemonInnerError(code=-500)`；业务 code != 0 时 `_handle_plugin_daemon_error()` 翻译为具体业务异常）以及 `:533-577`（`uninstall` 中 `Session(db.engine).begin()` 保证 credentials 删除是事务，失败时整段回滚）

**Takeaway**: Dify 在 daemon 失败时**永不让上层看到假成功**：HTTP 层失败 → 抽象为 `PluginDaemonInnerError`；业务码失败 → 进入 22 case match → 抛具体异常（`InvokeConnectionError`, `InvokeAuthorizationError`, `InvokeRateLimitError`, ...）。db 写入用 `session.begin()` 保证原子。**绝不在异常路径返回空值或 None 让调用方"看起来成功"**。

**与本项目映射**: 本 plan CgroupsV2 `_attach_docker_networks` 三失败模式各自 raise `RuntimeError` **并先 `proc.terminate() + await proc.wait()`**（Pitfall 5 决策），防止 Huly 后续调用一直 ConnectionError 看起来像超时。错误文案沿用 Dify "具体 + 可诊断"风格：`"docker network 'huly_huly_net' not found (check spelling or docker-compose up <stack> first)"`、`"daemon pid=12345 not in any docker container — cannot attach networks=..."`。**绝不让 docker_networks 静默 no-op 后让 Huly 通信失败**。

### 4. manifest field_validator 风格：错误信息含字段名 + 实际值 + 修复提示

**Dify 源**: `/Users/admin/ai/ref/dify/repo/api/core/plugin/entities/plugin.py:82-91`（`Meta.validate_minimum_dify_version`: `raise ValueError(f"Invalid version format: {v}") from e`）以及 `:115-122`（`PluginDeclaration.validate_version` 同模式）和 `:94-95`（`author: str = Field(..., pattern=r"^[a-zA-Z0-9_-]{1,64}$")`, `name: str = Field(..., pattern=r"^[a-z0-9_-]{1,128}$")` 用 `Field(pattern=...)` 做轻量 regex 校验）

**Takeaway**: Dify 命名规范校验 = `Field(pattern=...)` 做单字段 regex（短规则）+ `@field_validator` 做复杂逻辑（多步校验 / 跨依赖校验）。错误信息**始终含字段实际值**（如 `f"Invalid version format: {v}"`），便于运维一眼定位。`from e` 保留原始异常链。

**与本项目映射**: 本 plan `SandboxConfig.docker_networks_must_be_valid_names` 用 `@field_validator` 而非 `Field(pattern=...)`（因为 list 每条都要校验，pattern 只支持单 string）；regex 拆到 module 级 `_DOCKER_NET_RE = re.compile(...)`（与 5.A `_NETWORK_ENTRY_RE` 同风格），中文错误信息含字段名 + 实际值：`"docker_networks entry 必须符合 docker network 命名规范（首字符 alphanumeric，后续允许 alphanumeric/_/./-），实际: {entry!r}"`。**这是 Pitfall 5 拼写错防护的第一道闸**：manifest 加载阶段就拒绝 `huly/net` 或 `-bad` 这类隐患命名，不让其传到 daemon spawn 阶段才暴露。

### 5. subprocess + 外部资源协同模式：声明在 manifest，副作用在 runner / installer

**Dify 源**: `/Users/admin/ai/ref/dify/repo/api/core/plugin/entities/plugin.py:26-58`（`PluginResourceRequirements.memory: int` 在 declaration 层声明，但实际 `cgroups` 不在 Dify 主进程做 — 由 Docker / Kubernetes 编排）+ `/Users/admin/ai/ref/dify/repo/api/core/plugin/impl/base.py:55-59`（`get_pooled_http_client("plugin_daemon", lambda: httpx.Client(limits=..., trust_env=False))` 显式声明连接池上限，避免 daemon 副作用资源泄露）

**Takeaway**: Dify 不在 daemon 内自管 docker SDK / 不让 daemon 自己 `docker network connect`；**资源声明（memory / permission）在 manifest，副作用编排在外部（Docker 启动参数 / k8s spec）**。daemon 进程关注业务逻辑，主进程关注资源声明 → 编排器实施。`trust_env=False` 防止 daemon 副作用受环境变量污染（HTTP_PROXY 之类）。

**与本项目映射**: 本 plan 做出**与 Dify 相反但等价的工程决策**：因为我们 daemon 是**本地 asyncio subprocess**（不是远端 Go 进程），没有外部编排器，所以 `docker network connect` **由 `CgroupsV2Sandbox.spawn_with_limits` 主动做**（spawn 后立即 attach）。但**借鉴点保留**：
- daemon 进程内**不引入 docker SDK 依赖**（否则每个 plugin daemon 都要装 docker 包）—— docker SDK 只在主进程的 `cgroups_v2.py::_attach_docker_networks` 里 `try: import docker except ImportError` 局部加载
- `docker_networks` 字段**只在 manifest 声明**，daemon 启动参数不暴露此细节（daemon 子进程通过已 attach 的 network 接口透明访问 huly，不感知 docker 层）
- 类似 Dify `trust_env=False` 的防御：CgroupsV2 attach 之前先 `client.ping()` 校验 docker daemon 健康，避免拿到一个半死的 docker client 后续报奇怪错

---

## 与本项目的关系（Phase 5.C plan 01 sandbox-docker-networks 落地路径）

本 plan 在 Phase 5.B SandboxRunner 既有契约（Posix / cgroups v2 双实现 + setrlimit）之上**最小化扩展接口**：新增 `docker_networks: list[str] | None = None` kwarg + manifest `SandboxConfig.docker_networks` 字段。Wave 1 完成 → 接口对外冻结，使 Wave 2 三 plan（02 hr huly port / 03 OutlinePlugin / 04 LarkDocsPlugin）+ Wave 3 HulyPlugin 4-capability bundle 可并行开工（hr 教训 §4.4：Huly daemon 必须 attach `huly_huly_net` 才能调 `collaborator:3078`，无此 attach 走 ConnectionError）。

**5 借鉴点 → 本 plan 文件映射表**：

| 借鉴点 | Dify 源文件 | 本 plan target 文件 | 落地形式 |
|---|---|---|---|
| 1. 默认值兼容旧 manifest | `entities/plugin.py:26-58, 82-91` | `backend/app/agent_builder/platforms/manifest.py` | `docker_networks: list[str] = Field(default_factory=list)` + `@field_validator` |
| 2. spawn 后立即副作用 hook | `services/plugin/plugin_service.py:400-415, 515-584` | `backend/app/agent_builder/platforms/sandbox/cgroups_v2.py` | `_attach_docker_networks` 在 `spawn_with_limits` 末尾调，单一职责 |
| 3. cleanup-then-raise 防假成功 | `impl/base.py:238-277, 321-371` | `backend/app/agent_builder/platforms/sandbox/cgroups_v2.py` | 三失败模式各自 `proc.terminate() + await proc.wait()` 再 raise `RuntimeError` |
| 4. validator 错误信息含字段值 | `entities/plugin.py:82-91, 115-122` | `backend/app/agent_builder/platforms/manifest.py` | `f"... 实际: {entry!r}"` + module 级 `_DOCKER_NET_RE` |
| 5. 主进程编排副作用 / daemon 不感知 | `entities/plugin.py:26-58`, `impl/base.py:55-59` | `backend/app/agent_builder/platforms/daemon_client.py` + `cgroups_v2.py` | docker SDK 局部 import / daemon 子进程不引依赖 / `client.ping()` 前置校验 |

**License attribution**: Dify 为 AGPL-3.0；本项目 agent-builder 为 Apache-2.0（与 flock 一致）。本 reading doc 仅记录**设计模式 / 数据结构思路 / 错误处理哲学的归纳**，未复制任何 Dify 源代码片段。CgroupsV2 attach 实现、validator 中文文案、`_resolve_container_for_pid` 的 cgroup v1+v2 双格式 regex 均为本项目独立创作；Dify 借鉴点仅作为"已被生产验证的工程决策"参考，不构成代码衍生关系。

**Wave 2 前置契约（本 reading doc 帮助锁定）**：
- `SandboxRunner.spawn_with_limits(..., docker_networks: list[str] | None = None)` — 签名永不更改
- `SandboxConfig.docker_networks: list[str] = Field(default_factory=list)` — 默认空 list = no attach（PosixResource 完全 no-op，CgroupsV2 跳过 attach 路径）
- 失败时**必 raise + terminate daemon**，绝不静默（Pitfall 5）

---

*Reading doc 完成；准备进入 Task 1 代码实现阶段。*
