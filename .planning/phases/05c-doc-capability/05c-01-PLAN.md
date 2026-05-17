---
phase: 05c-doc-capability
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - docs/reading-dify-05c-01-sandbox-docker-networks-2026-05-18.md
  - backend/app/agent_builder/platforms/sandbox/runner.py
  - backend/app/agent_builder/platforms/sandbox/cgroups_v2.py
  - backend/app/agent_builder/platforms/manifest.py
  - backend/app/agent_builder/platforms/daemon_client.py
  - backend/tests/platforms/sandbox/test_docker_networks.py
  - backend/tests/platforms/test_manifest_schema.py
  - backend/tests/platforms_integration/test_sandbox_docker_networks_integration.py
autonomous: true
requirements:
  - DOC-SANDBOX-NET-01
  - DOC-SANDBOX-NET-02
must_haves:
  truths:
    - "Dify plugin daemon lifecycle 阅读文档已 commit（CLAUDE.md §2.7 硬性 gate，先于任何代码 commit）"
    - "SandboxRunner Protocol 增加 `docker_networks: list[str] | None = None` 参数（接口对外冻结，Wave 2 三 plan 可并行）"
    - "manifest schema SandboxConfig 新增 `docker_networks: list[str]` 字段（默认 [] 空 list = no attach）"
    - "PosixResourceSandbox 收到 docker_networks 非空时 log warning + no-op 返回（macOS dev / 非容器场景安全）"
    - "CgroupsV2Sandbox 收到 docker_networks 非空且 daemon pid 在 container 内时真做 `docker network connect <net> <container_id>`"
    - "docker network attach 三种失败模式（docker 不可用 / network 不存在 / pid 不在 container）各自抛 RuntimeError + 包含明确诊断信息 + terminate daemon 避免假成功（Pitfall 5）"
    - "daemon_client._start 调 spawn_with_limits 时透传 self._sandbox_config.docker_networks"
    - "manifest network 字段格式校验保持 host:port exact match（Phase 5.B 锁定，不引入 wildcard — Pitfall 7）"
    - "Phase 5.B 162 platforms 单测 + 5/5 huly acid test 0 regression"
    - "huly platform.yaml 演示 sandbox.docker_networks: [huly_huly_net] 解析成功"
  artifacts:
    - path: "docs/reading-dify-05c-01-sandbox-docker-networks-2026-05-18.md"
      provides: "Dify plugin daemon lifecycle + manifest 校验链路阅读笔记（5 节标准模板 + 5 借鉴点 + Phase 5.C 关系）"
      min_lines: 80
    - path: "backend/app/agent_builder/platforms/sandbox/runner.py"
      provides: "SandboxRunner Protocol 与 PosixResourceSandbox 增加 docker_networks 参数 + warning log"
      contains: "docker_networks"
    - path: "backend/app/agent_builder/platforms/sandbox/cgroups_v2.py"
      provides: "CgroupsV2Sandbox 增加 docker network attach 链路 + 三模式异常处理 + _resolve_container_for_pid helper"
      contains: "_resolve_container_for_pid"
    - path: "backend/app/agent_builder/platforms/manifest.py"
      provides: "SandboxConfig 新增 docker_networks 字段（含 field_validator 校验 docker network 命名规范）"
      contains: "docker_networks"
    - path: "backend/app/agent_builder/platforms/daemon_client.py"
      provides: "daemon_client._start 透传 docker_networks 给 SandboxRunner（Wave 2 三 plan 复用此入口）"
      contains: "docker_networks=self._sandbox_config.docker_networks"
    - path: "backend/tests/platforms/sandbox/test_docker_networks.py"
      provides: "单元测试 — mock subprocess + mock docker SDK 覆盖 PosixResource no-op + CgroupsV2 attach + 三失败模式各 1 用例"
    - path: "backend/tests/platforms_integration/test_sandbox_docker_networks_integration.py"
      provides: "集成测试 — 真起 `docker network create test-net` + mock huly server @ 127.0.0.1:18087 + daemon spawn 真做 network attach（仅 Linux + docker 可用时跑，否则 skip）"
  key_links:
    - from: "backend/app/agent_builder/platforms/daemon_client.py"
      to: "backend/app/agent_builder/platforms/sandbox/runner.py"
      via: "_start 调 spawn_with_limits 时传 docker_networks=self._sandbox_config.docker_networks"
      pattern: "docker_networks=self._sandbox_config"
    - from: "backend/app/agent_builder/platforms/sandbox/cgroups_v2.py"
      to: "/proc/<pid>/cgroup"
      via: "_resolve_container_for_pid 读 cgroup 文件提取 container_id"
      pattern: "/proc/.*?/cgroup"
    - from: "backend/app/agent_builder/platforms/manifest.py"
      to: "backend/app/agent_builder/platforms/sandbox/runner.py"
      via: "SandboxConfig.docker_networks 字段 → SandboxRunner.spawn_with_limits 参数"
      pattern: "docker_networks: list\\[str\\]"
---

<objective>
建立 Phase 5.C **接口冻结底座**：扩展 Phase 5.B SandboxRunner Protocol 接受 `docker_networks: list[str] | None`，manifest schema 新增 `sandbox.docker_networks` 字段，PosixResourceSandbox no-op + CgroupsV2Sandbox 真做 `docker network connect`。

Purpose: Wave 2 三个并行 plan（02 hr port + 03 OutlinePlugin + 04 LarkDocsPlugin）+ Wave 3 HulyPlugin 4-cap bundle 全部依赖此 docker network attach 能力 — Phase 5.B AllowlistTransport 只验 application-level 白名单，Huly daemon 需要 attach `huly_huly_net` docker network 才能调 `collaborator:3078`（hr 教训 §4.4 / Pitfall 5）。**本 plan 必须在 ~25min 内完成并锁定接口对外契约，不阻塞下游并行**。

Output:
- 1 个 Dify reading doc（CLAUDE.md §2.7 硬性 gate）
- 4 个源文件扩展（runner / cgroups_v2 / manifest / daemon_client）
- 2 个测试文件（unit mock + integration 真 docker）
- DoD: Phase 5.B 5/5 huly acid test 0 regression + 接口对外冻结
</objective>

<execution_context>
@/Users/admin/.claude/get-shit-done/workflows/execute-plan.md
@/Users/admin/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/05c-doc-capability/05c-CONTEXT.md
@.planning/phases/05c-doc-capability/05c-RESEARCH.md
@backend/app/agent_builder/platforms/sandbox/runner.py
@backend/app/agent_builder/platforms/sandbox/cgroups_v2.py
@backend/app/agent_builder/platforms/manifest.py
@backend/app/agent_builder/platforms/daemon_client.py
@CLAUDE.md

<interfaces>
<!-- Phase 5.B 现状（本 plan 扩展），Wave 2/3 依赖本 plan 完成后的最终契约 -->

From backend/app/agent_builder/platforms/sandbox/runner.py（5.B 现状）:
```python
@runtime_checkable
class SandboxRunner(Protocol):
    async def spawn_with_limits(
        self,
        cmd: list[str],
        *,
        cpu_seconds: int,
        memory_bytes: int,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> asyncio.subprocess.Process: ...
```

本 plan 完成后的最终契约（Wave 2/3 依赖此 — 接口对外冻结）:
```python
@runtime_checkable
class SandboxRunner(Protocol):
    async def spawn_with_limits(
        self,
        cmd: list[str],
        *,
        cpu_seconds: int,
        memory_bytes: int,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        docker_networks: list[str] | None = None,   # 新增 — Phase 5.C
    ) -> asyncio.subprocess.Process: ...
```

From backend/app/agent_builder/platforms/manifest.py SandboxConfig（5.B 现状 7 字段）:
```python
class SandboxConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cpu_limit: str = Field(default="2.0", pattern=r"^\d+(\.\d+)?$")
    memory: str = Field(default="1Gi")
    network: list[str] = Field(default_factory=list)        # application-level allowlist
    timeout_invoke: int = Field(default=30, gt=0, le=3600)
    timeout_idle: int = Field(default=300, gt=0, le=86400)
    use_cgroups: bool = False
    env_allowlist: list[str] = Field(default_factory=list)
```

本 plan 完成后（8 字段）:
```python
class SandboxConfig(BaseModel):
    # ... 5.B 7 字段不变 ...
    docker_networks: list[str] = Field(default_factory=list)  # 新增 — Phase 5.C Pattern 4
    # validator: 每条 entry 必须匹配 docker network 命名规范 (^[a-zA-Z0-9][a-zA-Z0-9_.-]*$)
```

From backend/app/agent_builder/platforms/daemon_client.py（5.B 现状第 340 行）:
```python
self._proc = await runner.spawn_with_limits(
    cmd,
    cpu_seconds=self._sandbox_config.cpu_limit_seconds,
    memory_bytes=self._sandbox_config.memory_bytes,
    env=env,
    cwd=self._cwd,
)
```

本 plan 完成后（加 1 行 kwarg）:
```python
self._proc = await runner.spawn_with_limits(
    cmd,
    cpu_seconds=self._sandbox_config.cpu_limit_seconds,
    memory_bytes=self._sandbox_config.memory_bytes,
    env=env,
    cwd=self._cwd,
    docker_networks=self._sandbox_config.docker_networks,  # 新增
)
```
</interfaces>
</context>

<reference>
Dify 模块映射（CLAUDE.md §2.7 强制规则）— 本 plan 实现的是 plugin daemon lifecycle 强化（spawn 后副作用 / manifest 校验）:

- **后端必读**: `/Users/admin/ai/ref/dify/repo/api/services/plugin/plugin_service.py` — Plugin install / fetch / list 路径中 daemon 生命周期与资源限制如何交互（grep "subprocess|spawn|sandbox|resource|network" 30 行上下文）
- **后端必读**: `/Users/admin/ai/ref/dify/repo/api/core/plugin/installer/` 整个目录 — manifest 校验链路 / 字段扩展时 Dify 如何兼容旧版 manifest（向后兼容策略借鉴）
- **后端补充**: `/Users/admin/ai/ref/dify/repo/api/core/plugin/manager.py` — daemon spawn 后副作用（如 healthcheck / register）的注入点（参考 docker network attach 应放在 spawn 后哪个 hook）

借鉴重点（reading doc 必含 5 节标准模板 + 至少 5 个借鉴点）:
1. **manifest 字段扩展时的向后兼容策略**（Dify plugin_service 如何处理新加字段；我们 v1 直接加默认 `default_factory=list` 已天然兼容旧 manifest）
2. **daemon spawn 后副作用注入点**（Dify 在哪个生命周期 hook 做 healthcheck / network 配置；我们直接放 spawn_with_limits 内部）
3. **subprocess + 外部资源（network / volume）协同模式**（Dify 是否在 plugin 安装时 attach docker network？还是 daemon 内自配？）
4. **manifest validator 命名规范**（Dify field_validator 命名 / 错误信息风格；我们沿用 5.A `extra=forbid` + `field_validator` 模式）
5. **失败回滚策略**（Dify install 失败时如何 cleanup；我们 attach 失败 raise + terminate daemon 避免假成功）

License: Dify AGPL-3.0 vs agent-builder Apache-2.0 — 严禁拷源代码，仅借鉴设计模式 / 数据结构思路 / 错误处理哲学。
</reference>

<tasks>

<task type="auto">
  <name>Task 0: Dify plugin daemon lifecycle 阅读文档（CLAUDE.md §2.7 硬性 gate — 第一个 commit）</name>
  <files>docs/reading-dify-05c-01-sandbox-docker-networks-2026-05-18.md</files>
  <action>
**STOP — 这是后续所有 commit 的前置 gate**。先 commit 此文档才允许写代码（CLAUDE.md §2.7）。

阅读以下 Dify 源文件（仅 Read 不 grep，重点理解设计模式）:

1. `/Users/admin/ai/ref/dify/repo/api/services/plugin/plugin_service.py` — Plugin install / fetch / list 路径中 daemon 生命周期与资源限制如何交互
2. `/Users/admin/ai/ref/dify/repo/api/core/plugin/installer/` 整个目录列表（先 `ls` 看包结构）+ 至少 1 个核心 installer 文件（如 `local_installer.py` 或类似）— manifest 校验链路 / 字段扩展兼容策略
3. `/Users/admin/ai/ref/dify/repo/api/core/plugin/manager.py` — daemon spawn 后副作用（healthcheck / register）的注入点
4. 可选: `/Users/admin/ai/ref/dify/repo/api/core/plugin/entities/plugin.py` — PluginDeclaration 中 resource / network 字段（若有）

写到 `docs/reading-dify-05c-01-sandbox-docker-networks-2026-05-18.md`，**完全按 CLAUDE.md §2.7 阅读文档模板**（必须 5 节）:

```markdown
# Dify 阅读笔记 — Plan 05c-01 SandboxRunner docker_networks 字段扩展

> 日期: 2026-05-18
> 仓库: https://github.com/langgenius/dify (local clone /Users/admin/ai/ref/dify/repo/, AGPL-3.0)
> Stars: ~141k

## 项目概述（一句话）
Dify 是国内最成熟的开源 LLM 应用平台；plugin 系统通过 manifest + daemon 进程实现第三方扩展（model / tool / agent / endpoint / datasource）；本 plan 关注 daemon lifecycle 强化（subprocess spawn 后的 network 副作用）。

## 技术栈（关键技术选择）
- Pydantic BaseModel + ConfigDict（manifest 校验）
- Dify plugin daemon 用独立 Go 进程（dify-plugin-daemon repo）而非 Python subprocess
- HTTP / gRPC envelope 通信
- 资源限制依赖 Docker / Kubernetes 编排层（vs 我们走 cgroups v2 + setrlimit baseline）

## 架构要点
…用 3-5 行 + 简图说明 4 层结构：manifest declaration / installer pipeline / daemon manager / 运行时资源调度…

## 可借鉴的设计模式（至少 5 条，每条 [Dify 路径:行号] + 一句话 takeaway + 与本项目映射）

1. **manifest 字段向后兼容策略** — [`api/core/plugin/installer/<file>.py:NN`] Dify install 时如何兼容老 manifest 缺新字段 → 我们 `docker_networks: list[str] = Field(default_factory=list)` 默认空 list 天然兼容（旧 plugin.yaml 不需要改）
2. **daemon lifecycle hook 注入点** — [`api/services/plugin/plugin_service.py:NN`] Dify 在 spawn / install / healthcheck 哪一步配 network → 我们决策放 SandboxRunner.spawn_with_limits 内部（spawn 后立即 attach，单一职责）
3. **失败回滚策略** — [`api/core/plugin/manager.py:NN`] Dify 安装失败如何 cleanup（rollback / undo subprocess） → 我们 attach 失败 raise RuntimeError + proc.terminate() 避免假成功（Pitfall 5 决策）
4. **manifest field_validator 风格** — [`api/core/plugin/entities/plugin.py:NN`] Dify Pydantic v2 validator 错误信息怎么写（中英文 / 是否含字段名） → 我们沿用 5.A 中文错误信息 + 含字段名 + 实际值（如 "docker network 名必须符合 ^[a-zA-Z0-9]... 实际: {value!r}"）
5. **subprocess + 外部资源协同** — [`api/services/plugin/plugin_service.py:NN`] Dify 是否在 plugin 安装时 attach docker network 还是 daemon 内自配 → 我们结论: spawn 后立即 attach（避免 daemon 内自管 docker SDK 增加 daemon 依赖）

## 与本项目的关系
本 plan 实现 SandboxRunner.spawn_with_limits 增加 `docker_networks: list[str]` 参数 + manifest SandboxConfig 新增 docker_networks 字段。Wave 2 三 plan（hr huly internal port / OutlinePlugin / LarkDocsPlugin）+ Wave 3 HulyPlugin 4-cap bundle 全部依赖此能力；Huly daemon attach `huly_huly_net` 才能调 `collaborator:3078`（hr 教训 §4.4）。

License attribution: Dify 是 AGPL-3.0；本项目 Apache-2.0；仅借鉴**设计模式 / 数据结构思路 / 错误处理哲学**，不拷贝任何源代码。每条借鉴点已明确对应到我们要写的具体模块（runner.py / cgroups_v2.py / manifest.py / daemon_client.py）。
```

文档至少 80 行；5 个借鉴点必须明确写出 Dify source file → 我们 target module 的对应关系。**不要**贴 Dify 源代码片段（许可证）。

commit message: `docs(05c-01): add Dify plugin daemon lifecycle reading doc for docker_networks`
  </action>
  <verify>
    <automated>test -f /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05c-01-sandbox-docker-networks-2026-05-18.md && wc -l /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05c-01-sandbox-docker-networks-2026-05-18.md | awk '{exit ($1>=80)?0:1}' && grep -q "AGPL-3.0\|Apache-2.0" /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05c-01-sandbox-docker-networks-2026-05-18.md && grep -q "可借鉴的设计模式\|与本项目的关系" /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05c-01-sandbox-docker-networks-2026-05-18.md</automated>
  </verify>
  <done>reading doc 存在 ≥ 80 行 + 含 License attribution（AGPL/Apache）+ 含可借鉴的设计模式 5 节 + 含与本项目的关系；git commit 必须先于任何代码 commit</done>
</task>

<task type="auto">
  <name>Task 1: 扩展 SandboxRunner Protocol + PosixResourceSandbox + CgroupsV2Sandbox + manifest SandboxConfig（接口冻结）</name>
  <files>backend/app/agent_builder/platforms/sandbox/runner.py,backend/app/agent_builder/platforms/sandbox/cgroups_v2.py,backend/app/agent_builder/platforms/manifest.py,backend/app/agent_builder/platforms/daemon_client.py,plugins/huly/platform.yaml</files>
  <action>
Reading doc 已 commit ✓（CLAUDE.md §2.7 gate 通过），才能开始写代码。

**这是 Wave 1 唯一接口扩展任务 — 完成后接口对外冻结，Wave 2 三 plan 可并行**。

### 1.1 manifest.py — SandboxConfig 加 docker_networks 字段

在 `backend/app/agent_builder/platforms/manifest.py` SandboxConfig 内（5.B 7 字段之后）加：

```python
# ── network 命名规范 regex（CONTEXT.md Pitfall 5：拼写错抓不到）─────────
_DOCKER_NET_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
# Docker 网络名规范（与 docker network create 接受的格式一致）：
# - 首字符必须 alphanumeric
# - 后续字符允许 alphanumeric + `_` `.` `-`
# - 不允许 `/` `:` 空格等特殊符（防 manifest 误写导致 docker SDK 隐式拼接）

class SandboxConfig(BaseModel):
    # ... 5.B 7 字段不变 ...

    docker_networks: list[str] = Field(default_factory=list)
    """Daemon spawn 后需要 attach 的 docker network 列表（Phase 5.C 新增）。

    默认空 list = no attach（PosixResourceSandbox no-op；CgroupsV2Sandbox 也跳过）。

    典型使用场景:
    - Huly plugin 必须 attach `huly_huly_net` 才能调 collaborator:3078
    - 其他平台（Outline / Lark / Slack）走公网 → 留空 list 即可

    与 `network` 字段区别:
    - `network`: application-level 白名单（httpx AllowlistTransport 校验 host:port）
    - `docker_networks`: kernel-level docker bridge 网络 attach（实现 daemon 容器化部署时能访问的网络）

    Reference: Phase 5.C RESEARCH.md §Pattern 4 / Pitfall 5。
    """

    @field_validator("docker_networks")
    @classmethod
    def docker_networks_must_be_valid_names(cls, v: list[str]) -> list[str]:
        """每条 docker network 名必须符合 docker network 命名规范。

        防 manifest 误写（如带 `/` 或空格）导致 docker SDK 隐式拼接产生不可预期 network。
        """
        for entry in v:
            if not _DOCKER_NET_RE.match(entry):
                raise ValueError(
                    f"docker_networks entry 必须符合 docker network 命名规范"
                    f"（首字符 alphanumeric，后续允许 alphanumeric/_/./-），实际: {entry!r}"
                )
        return v
```

**注意**:
- 不修改 `network` 字段（5.B 锁定 host:port exact match — Pitfall 7）
- 不引入 wildcard
- `extra=forbid` 不变
- regex 放 module 级（不嵌入 class）保持与 `_NETWORK_ENTRY_RE` 同一风格

### 1.2 runner.py — SandboxRunner Protocol + PosixResourceSandbox 加 docker_networks 参数

在 `backend/app/agent_builder/platforms/sandbox/runner.py`：

**1) Protocol 签名扩展**:

```python
@runtime_checkable
class SandboxRunner(Protocol):
    async def spawn_with_limits(
        self,
        cmd: list[str],
        *,
        cpu_seconds: int,
        memory_bytes: int,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        docker_networks: list[str] | None = None,   # 新增 — Phase 5.C
    ) -> asyncio.subprocess.Process:
        """spawn 受限子进程。

        ... 5.B docstring 保留 ...

        Args:
            ... 5.B args 保留 ...
            docker_networks: spawn 后需要 attach 的 docker network 列表（None / []  = no attach）。
                **PosixResourceSandbox**: no-op + log warning（daemon 是 host 进程，不在 container）
                **CgroupsV2Sandbox**: 真做 docker network connect（仅当 daemon pid 在 container 内）
        """
        ...
```

**2) PosixResourceSandbox.spawn_with_limits 签名 + no-op 实现**:

```python
class PosixResourceSandbox:
    async def spawn_with_limits(
        self,
        cmd: list[str],
        *,
        cpu_seconds: int,
        memory_bytes: int,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        docker_networks: list[str] | None = None,  # 新增
    ) -> asyncio.subprocess.Process:
        # ... 5.B 现有实现完全不变（loop.subprocess_exec + preexec_fn）...

        # spawn 完成后处理 docker_networks（Phase 5.C 新增）
        if docker_networks:
            _log.info(
                "sandbox.docker_networks ignored on PosixResourceSandbox "
                "(daemon pid=%d runs as host process, not container): %s",
                proc.pid, docker_networks,
            )
        return proc
```

### 1.3 cgroups_v2.py — CgroupsV2Sandbox 真做 docker network attach

在 `backend/app/agent_builder/platforms/sandbox/cgroups_v2.py`：

**1) 在 module 顶部加 import + 常量**:

```python
import re

# /proc/<pid>/cgroup 行格式: "12:devices:/docker/abc123def..."（v1）或 "0::/docker/abc..."（v2）
# 双匹配兼容 cgroup v1 + v2
_CGROUP_DOCKER_RE = re.compile(r"/docker[/-]([0-9a-f]{12,64})")
```

**2) 加 spawn_with_limits 的 docker_networks 处理 + 新 helper**:

```python
class CgroupsV2Sandbox:
    async def spawn_with_limits(
        self,
        cmd: list[str],
        *,
        cpu_seconds: int,
        memory_bytes: int,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        docker_networks: list[str] | None = None,  # 新增
    ) -> asyncio.subprocess.Process:
        # ... 5.B 现有 systemd-run 实现完全不变 ...
        proc = await asyncio.create_subprocess_exec(...)
        _log.info("sandbox.cgroups_v2.spawned pid=%s ...", ...)

        # Phase 5.C: docker network attach（仅在 docker_networks 非空时做）
        if docker_networks:
            await self._attach_docker_networks(proc, docker_networks)

        return proc

    async def _attach_docker_networks(
        self,
        proc: asyncio.subprocess.Process,
        docker_networks: list[str],
    ) -> None:
        """spawn 后 attach docker networks（Phase 5.C Pattern 4 / Pitfall 5）。

        三种失败模式（每种独立诊断 + raise RuntimeError + terminate daemon 避免假成功）:

        1. docker daemon 不可用（CI / macOS dev）→ raise "docker daemon not available"
        2. network 不存在（拼写错 / Huly stack 未启）→ raise "docker network not found"
        3. daemon pid 不在 container（host process）→ raise "daemon pid not in container"

        **决策（CONTEXT Decision 3 + RESEARCH §Pattern 4 注释行 535-541）**:
        attach 失败必须 raise + terminate daemon — 不允许 "silently no network"
        否则 Huly 调用一直 ConnectionError 看起来像超时，难诊断。
        """
        try:
            import docker
            from docker.errors import DockerException, NotFound
        except ImportError as e:
            proc.terminate()
            await proc.wait()
            raise RuntimeError(
                f"docker python SDK not installed but docker_networks={docker_networks!r} requested"
            ) from e

        # 1. docker daemon 不可用
        try:
            client = docker.from_env()
            client.ping()
        except (DockerException, Exception) as e:
            proc.terminate()
            await proc.wait()
            raise RuntimeError(
                f"docker daemon not available (cannot attach networks={docker_networks!r}): {e}"
            ) from e

        # 3. daemon pid 不在 container（先查，避免拿不到 container_id 还去查 network）
        container_id = self._resolve_container_for_pid(proc.pid)
        if container_id is None:
            proc.terminate()
            await proc.wait()
            raise RuntimeError(
                f"daemon pid={proc.pid} not in any docker container — "
                f"cannot attach networks={docker_networks!r}. "
                f"(Note: docker_networks 仅在 daemon 自身运行在 docker container 内时生效；"
                f"host process 部署请用 PosixResourceSandbox 并保持 docker_networks=[])"
            )

        # 2. 逐个 attach network（任一失败 raise + terminate）
        for net_name in docker_networks:
            try:
                net = client.networks.get(net_name)
            except NotFound as e:
                proc.terminate()
                await proc.wait()
                raise RuntimeError(
                    f"docker network {net_name!r} not found "
                    f"(check spelling or docker-compose up <stack> first): {e}"
                ) from e
            try:
                net.connect(container_id)
                _log.info(
                    "docker network attached: net=%s -> container=%s pid=%d",
                    net_name, container_id[:12], proc.pid,
                )
            except Exception as e:
                proc.terminate()
                await proc.wait()
                raise RuntimeError(
                    f"docker network {net_name!r} connect failed for container={container_id[:12]}: {e}"
                ) from e

    def _resolve_container_for_pid(self, pid: int) -> str | None:
        """读 /proc/<pid>/cgroup 提取 docker container id（兼容 cgroup v1 + v2 格式）。

        cgroup v1 行格式: "12:devices:/docker/abc123def..."
        cgroup v2 行格式: "0::/docker/abc123def..." 或 "0::/system.slice/docker-abc123.scope"

        Returns:
            container_id (full hash) 或 None（daemon 不在 container）
        """
        try:
            content = Path(f"/proc/{pid}/cgroup").read_text()
        except (FileNotFoundError, PermissionError):
            return None

        for line in content.splitlines():
            m = _CGROUP_DOCKER_RE.search(line)
            if m:
                return m.group(1)
        return None
```

**注意**:
- `_attach_docker_networks` 是 async 方法（spawn_with_limits 是 async，调用一致）
- `_resolve_container_for_pid` 是 sync（纯文件读 + regex）
- 不引入 `docker` 包到 module 顶部 import（CI 不一定装；放方法内部 try/except ImportError）
- `__all__` 加 `_CGROUP_DOCKER_RE`（便于测试 mock）

### 1.4 daemon_client.py — 透传 docker_networks 给 SandboxRunner

在 `backend/app/agent_builder/platforms/daemon_client.py` 第 340 行附近的 `_start` 方法：

```python
self._proc = await runner.spawn_with_limits(
    cmd,
    cpu_seconds=self._sandbox_config.cpu_limit_seconds,
    memory_bytes=self._sandbox_config.memory_bytes,
    env=env,
    cwd=self._cwd,
    docker_networks=self._sandbox_config.docker_networks,  # 新增 — Phase 5.C
)
```

**注意**: 仅加 1 行 kwarg，其他逻辑不动；不在 daemon_client 内部做条件判断（让 runner 自己决定如何处理 docker_networks）。

### 1.5 plugins/huly/platform.yaml — 演示 docker_networks 字段

在 `plugins/huly/platform.yaml` sandbox 段（5.B 已加）末尾追加:

```yaml
sandbox:
  # ... 5.B 现有字段 ...
  docker_networks:
    - huly_huly_net   # Phase 5.C Pattern 4 — Huly daemon 必 attach 才能调 collaborator:3078
```

### 1.6 代码风格

- black + ruff lint 必须通过
- 所有新增 docstring 中文 + 含 Phase 5.C reference
- import 放对应 import 段（manifest.py 已有 `import re`，cgroups_v2.py 需加）

### 1.7 commit messages（拆 5 commit 便于回滚）

1. `feat(05c-01): add docker_networks field to SandboxConfig manifest (DOC-SANDBOX-NET-01)`
2. `feat(05c-01): extend SandboxRunner Protocol with docker_networks param`
3. `feat(05c-01): PosixResourceSandbox no-op docker_networks + warning log`
4. `feat(05c-01): CgroupsV2Sandbox real docker network attach + 3-mode error handling (Pitfall 5)`
5. `feat(05c-01): daemon_client passes sandbox_config.docker_networks to runner`
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -c "
from app.agent_builder.platforms.manifest import SandboxConfig
from app.agent_builder.platforms.sandbox.runner import SandboxRunner, PosixResourceSandbox
from app.agent_builder.platforms.sandbox.cgroups_v2 import CgroupsV2Sandbox
import inspect

# 1. SandboxConfig 新增 docker_networks 字段且默认 []
c = SandboxConfig()
assert c.docker_networks == [], f'expected [], got {c.docker_networks!r}'

# 2. docker_networks validator 拒非法命名
import pytest
from pydantic import ValidationError
try:
    SandboxConfig(docker_networks=['bad/name'])
    assert False, 'should raise'
except ValidationError:
    pass

# 3. Protocol 签名含 docker_networks（runtime_checkable）
sig = inspect.signature(SandboxRunner.spawn_with_limits)
assert 'docker_networks' in sig.parameters, f'missing docker_networks in {list(sig.parameters)}'

# 4. PosixResourceSandbox 签名一致
sig2 = inspect.signature(PosixResourceSandbox.spawn_with_limits)
assert 'docker_networks' in sig2.parameters

# 5. CgroupsV2Sandbox 签名一致 + _resolve_container_for_pid 方法存在
sig3 = inspect.signature(CgroupsV2Sandbox.spawn_with_limits)
assert 'docker_networks' in sig3.parameters
assert hasattr(CgroupsV2Sandbox, '_resolve_container_for_pid')
assert hasattr(CgroupsV2Sandbox, '_attach_docker_networks')

# 6. Huly platform.yaml 解析 docker_networks
from pathlib import Path
from app.agent_builder.platforms.manifest import load_manifest
m = load_manifest(Path('/Users/admin/ai/resume/interview/liuxin/agent-builder/plugins/huly/platform.yaml'))
assert m.sandbox is not None
assert 'huly_huly_net' in m.sandbox.docker_networks, f'expected huly_huly_net, got {m.sandbox.docker_networks!r}'

print('OK — interface frozen')
"</automated>
  </verify>
  <done>SandboxConfig 8 字段（5.B 7 + docker_networks）+ validator；SandboxRunner Protocol + PosixResourceSandbox + CgroupsV2Sandbox 三处签名含 docker_networks；daemon_client._start 透传；huly platform.yaml 含 docker_networks 段且 load_manifest 解析成功；接口对外冻结</done>
</task>

<task type="auto">
  <name>Task 2: 单元测试 — docker_networks 字段校验 + PosixResource no-op + CgroupsV2 三失败模式 + 集成测试 + 5.B regression</name>
  <files>backend/tests/platforms/sandbox/test_docker_networks.py,backend/tests/platforms/test_manifest_schema.py,backend/tests/platforms_integration/test_sandbox_docker_networks_integration.py</files>
  <action>
**三层测试同 plan 内完成（CLAUDE.md §2.2）**：unit（mock subprocess + mock docker）+ integration（真 docker network create + mock huly server）+ Phase 5.B regression check。E2E 留 Phase 5.C plan 08（本 plan 不做）。

### 2.1 unit test — `backend/tests/platforms/sandbox/test_docker_networks.py`

```python
"""Phase 5.C Plan 01 — SandboxRunner docker_networks 单元测试（mock 路径）。

覆盖:
- PosixResourceSandbox 收到 docker_networks 非空 → no-op + warning log
- CgroupsV2Sandbox._resolve_container_for_pid 解析 cgroup v1 + v2 格式
- CgroupsV2Sandbox._attach_docker_networks 三失败模式（docker 不可用 / network 不存在 / pid 不在 container）

CgroupsV2 真 docker integration test 走 test_sandbox_docker_networks_integration.py
（仅 Linux + docker 可用时跑，否则 skip）。
"""
from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent_builder.platforms.sandbox.cgroups_v2 import (
    CgroupsV2Sandbox,
    _CGROUP_DOCKER_RE,
)
from app.agent_builder.platforms.sandbox.runner import PosixResourceSandbox


# ── PosixResourceSandbox no-op 测试 ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_posix_resource_docker_networks_no_op_with_warning(caplog):
    """PosixResourceSandbox 收 docker_networks 非空：no-op + log info 含 "ignored"。"""
    import logging
    caplog.set_level(logging.INFO)

    sb = PosixResourceSandbox()
    proc = await sb.spawn_with_limits(
        [sys.executable, "-c", "import time; time.sleep(0.01)"],
        cpu_seconds=10,
        memory_bytes=128 * 1024 * 1024,
        docker_networks=["huly_huly_net", "another_net"],
    )
    await proc.wait()

    # warning 必有
    assert any("docker_networks ignored" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_posix_resource_docker_networks_none_no_warning(caplog):
    """PosixResourceSandbox 收 docker_networks=None：完全不 log warning（5.B regression 路径）。"""
    import logging
    caplog.set_level(logging.INFO)

    sb = PosixResourceSandbox()
    proc = await sb.spawn_with_limits(
        [sys.executable, "-c", "pass"],
        cpu_seconds=10,
        memory_bytes=128 * 1024 * 1024,
        # 不传 docker_networks
    )
    await proc.wait()

    assert not any("docker_networks" in r.message for r in caplog.records)


# ── _CGROUP_DOCKER_RE regex 测试 ──────────────────────────────────────────────

class TestCgroupDockerRegex:
    """_CGROUP_DOCKER_RE 兼容 cgroup v1 + v2 格式（每行格式 + 提取 container_id）。"""

    def test_cgroup_v1_format(self):
        line = "12:devices:/docker/abc123def4567890fedcba"
        m = _CGROUP_DOCKER_RE.search(line)
        assert m is not None
        assert m.group(1) == "abc123def4567890fedcba"

    def test_cgroup_v2_format_slash(self):
        line = "0::/docker/abc123def4567890"
        m = _CGROUP_DOCKER_RE.search(line)
        assert m is not None
        assert m.group(1) == "abc123def4567890"

    def test_cgroup_v2_format_systemd_slice(self):
        line = "0::/system.slice/docker-abc123def4567890.scope"
        m = _CGROUP_DOCKER_RE.search(line)
        assert m is not None
        assert m.group(1) == "abc123def4567890"

    def test_non_docker_cgroup_no_match(self):
        line = "0::/user.slice/user-1000.slice/session-1.scope"
        assert _CGROUP_DOCKER_RE.search(line) is None


# ── _resolve_container_for_pid 测试 ───────────────────────────────────────────

class TestResolveContainerForPid:
    """_resolve_container_for_pid 行为：mock /proc 文件 + 各失败场景。"""

    def test_pid_not_in_container_returns_none(self, tmp_path, monkeypatch):
        """daemon 是 host process（/proc/<pid>/cgroup 不含 docker 段）→ 返回 None。"""
        # mock Path.read_text 返回非 docker cgroup 内容
        from app.agent_builder.platforms.sandbox import cgroups_v2 as m

        fake_content = "0::/user.slice/user-1000.slice"
        with patch.object(m, "Path") as mock_path:
            mock_path.return_value.read_text.return_value = fake_content
            sb = CgroupsV2Sandbox()
            result = sb._resolve_container_for_pid(12345)
            assert result is None

    def test_pid_in_container_returns_id(self):
        """daemon 在 container → 返回 container_id。"""
        from app.agent_builder.platforms.sandbox import cgroups_v2 as m

        fake_content = "0::/docker/abc123def4567890fedcba\n"
        with patch.object(m, "Path") as mock_path:
            mock_path.return_value.read_text.return_value = fake_content
            sb = CgroupsV2Sandbox()
            result = sb._resolve_container_for_pid(12345)
            assert result == "abc123def4567890fedcba"

    def test_proc_file_not_found_returns_none(self):
        """/proc/<pid>/cgroup 不存在（macOS 或 pid 已死）→ 返回 None。"""
        from app.agent_builder.platforms.sandbox import cgroups_v2 as m

        with patch.object(m, "Path") as mock_path:
            mock_path.return_value.read_text.side_effect = FileNotFoundError("no proc")
            sb = CgroupsV2Sandbox()
            result = sb._resolve_container_for_pid(99999999)
            assert result is None


# ── _attach_docker_networks 三失败模式 ────────────────────────────────────────

class TestAttachDockerNetworksFailures:
    """三失败模式（Pitfall 5）：docker 不可用 / network 不存在 / pid 不在 container。

    每模式独立 RuntimeError + terminate daemon + 错误信息含明确诊断。
    """

    @pytest.mark.asyncio
    async def test_failure_mode_1_docker_daemon_unavailable(self):
        """模式 1: docker daemon ping 失败 → raise RuntimeError("docker daemon not available")。"""
        mock_proc = MagicMock(spec=asyncio.subprocess.Process)
        mock_proc.terminate = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)
        mock_proc.pid = 12345

        mock_docker_client = MagicMock()
        mock_docker_client.ping.side_effect = Exception("Cannot connect to docker daemon")

        with patch("docker.from_env", return_value=mock_docker_client):
            sb = CgroupsV2Sandbox()
            with pytest.raises(RuntimeError, match="docker daemon not available"):
                await sb._attach_docker_networks(mock_proc, ["huly_huly_net"])

        mock_proc.terminate.assert_called_once()  # daemon terminated 防假成功

    @pytest.mark.asyncio
    async def test_failure_mode_2_network_not_found(self):
        """模式 2: network 不存在 → raise RuntimeError("docker network 'huly_huly_net' not found")。"""
        import docker.errors as derr

        mock_proc = MagicMock(spec=asyncio.subprocess.Process)
        mock_proc.terminate = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)
        mock_proc.pid = 12345

        mock_docker_client = MagicMock()
        mock_docker_client.ping.return_value = True
        mock_docker_client.networks.get.side_effect = derr.NotFound("Network not found")

        # mock 容器 id 解析成功
        with patch("docker.from_env", return_value=mock_docker_client), \
             patch.object(CgroupsV2Sandbox, "_resolve_container_for_pid", return_value="abc123def"):
            sb = CgroupsV2Sandbox()
            with pytest.raises(RuntimeError, match="docker network 'huly_huly_net' not found"):
                await sb._attach_docker_networks(mock_proc, ["huly_huly_net"])

        mock_proc.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_failure_mode_3_pid_not_in_container(self):
        """模式 3: daemon pid 不在 container → raise RuntimeError("daemon pid=N not in any docker container")。"""
        mock_proc = MagicMock(spec=asyncio.subprocess.Process)
        mock_proc.terminate = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)
        mock_proc.pid = 12345

        mock_docker_client = MagicMock()
        mock_docker_client.ping.return_value = True

        with patch("docker.from_env", return_value=mock_docker_client), \
             patch.object(CgroupsV2Sandbox, "_resolve_container_for_pid", return_value=None):
            sb = CgroupsV2Sandbox()
            with pytest.raises(RuntimeError, match="daemon pid=12345 not in any docker container"):
                await sb._attach_docker_networks(mock_proc, ["huly_huly_net"])

        mock_proc.terminate.assert_called_once()


# ── 成功路径 mock 测试（CgroupsV2 attach 真调 net.connect） ────────────────────

@pytest.mark.asyncio
async def test_attach_docker_networks_success_path():
    """成功路径: docker daemon 可用 + network 存在 + pid 在 container → net.connect 调用一次。"""
    mock_proc = MagicMock(spec=asyncio.subprocess.Process)
    mock_proc.pid = 12345
    mock_proc.terminate = MagicMock()

    mock_network = MagicMock()
    mock_docker_client = MagicMock()
    mock_docker_client.ping.return_value = True
    mock_docker_client.networks.get.return_value = mock_network

    with patch("docker.from_env", return_value=mock_docker_client), \
         patch.object(CgroupsV2Sandbox, "_resolve_container_for_pid", return_value="abc123def456"):
        sb = CgroupsV2Sandbox()
        await sb._attach_docker_networks(mock_proc, ["huly_huly_net"])

    mock_network.connect.assert_called_once_with("abc123def456")
    mock_proc.terminate.assert_not_called()  # 成功路径不应 terminate
```

测试覆盖（至少 11 测试）:
- 2 PosixResource no-op（含 docker_networks vs None 分支）
- 4 _CGROUP_DOCKER_RE regex（v1 / v2 slash / v2 systemd-slice / non-docker）
- 3 _resolve_container_for_pid（在 container / 不在 / 文件不存在）
- 3 _attach_docker_networks 失败模式
- 1 _attach_docker_networks 成功路径

### 2.2 manifest schema 测试加 docker_networks 验证 — `backend/tests/platforms/test_manifest_schema.py`

在现有 `TestSandboxConfig` 类内（5.B 已建）追加 ≥ 4 测试：

```python
class TestSandboxConfigDockerNetworks:
    """Phase 5.C Plan 01 — SandboxConfig.docker_networks 字段校验。"""

    def test_docker_networks_default_empty_list(self):
        """默认空 list = no attach（PosixResourceSandbox no-op 路径）。"""
        c = SandboxConfig()
        assert c.docker_networks == []

    def test_docker_networks_valid_names_accepted(self):
        """合法 docker network 命名（alphanumeric + _/./-）接受。"""
        c = SandboxConfig(docker_networks=["huly_huly_net", "my-net", "net.1"])
        assert c.docker_networks == ["huly_huly_net", "my-net", "net.1"]

    def test_docker_networks_invalid_slash_rejected(self):
        """含 `/` 的命名 → ValidationError（防 docker SDK 拼接路径）。"""
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="docker network 命名规范"):
            SandboxConfig(docker_networks=["bad/name"])

    def test_docker_networks_invalid_starts_with_dash_rejected(self):
        """首字符必须 alphanumeric（不允许 `_`/`-` 开头）→ ValidationError。"""
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="docker network 命名规范"):
            SandboxConfig(docker_networks=["-bad"])

    def test_docker_networks_with_space_rejected(self):
        """含空格 → ValidationError。"""
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="docker network 命名规范"):
            SandboxConfig(docker_networks=["bad name"])
```

### 2.3 集成测试 — `backend/tests/platforms_integration/test_sandbox_docker_networks_integration.py`

```python
"""Phase 5.C Plan 01 — SandboxRunner docker_networks 集成测试（真 docker，禁止 mock）。

CLAUDE.md §2.2 / §feedback_e2e_browser_harness:
- 集成测试必须真起 docker network（不 mock docker SDK）
- 真起 mock huly server @ 127.0.0.1:18087 模拟 collaborator 服务
- daemon 真 spawn + 真 docker network create test-net
- 仅 Linux + docker 可用时跑，macOS / 无 docker 环境 skip

测试场景:
- happy path: daemon 是 host process（macOS / Linux 非 container 部署）→ docker_networks=[] no-op
- E2E gate 留 plan 08（DAG → doc_write → 真 Outline/Lark/Huly 文档）
"""
from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys

import pytest

from app.agent_builder.platforms.sandbox.cgroups_v2 import CgroupsV2Sandbox
from app.agent_builder.platforms.sandbox.runner import PosixResourceSandbox


def _docker_available() -> bool:
    """检测 docker daemon 是否真可用（CI / 本地）。"""
    if shutil.which("docker") is None:
        return False
    try:
        r = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True, timeout=2, check=False,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


_DOCKER_OK = _docker_available()
_IS_LINUX = sys.platform == "linux"


# ── happy path: host process no-op ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_posix_resource_docker_networks_empty_default():
    """空 docker_networks → daemon 正常 spawn + no-op + 不依赖 docker SDK。"""
    sb = PosixResourceSandbox()
    proc = await sb.spawn_with_limits(
        [sys.executable, "-c", "print('hello'); import sys; sys.exit(0)"],
        cpu_seconds=10,
        memory_bytes=128 * 1024 * 1024,
        docker_networks=[],
    )
    await proc.wait()
    assert proc.returncode == 0


# ── CgroupsV2 真 docker network attach（仅 Linux + docker 可用） ────────────────

@pytest.mark.skipif(not (_DOCKER_OK and _IS_LINUX), reason="requires Linux + docker daemon")
@pytest.mark.asyncio
async def test_cgroups_v2_attach_real_docker_network_host_pid_fails():
    """CgroupsV2 host process pid（非 container）→ _attach raise RuntimeError。

    此测试在 Linux + docker 可用环境验证 Pitfall 5 失败模式 3 真实表现。
    """
    # 真创建 test-net（如果已存在 ignore）
    subprocess.run(["docker", "network", "create", "test-net-phase5c-01"],
                   capture_output=True, check=False)

    try:
        sb = CgroupsV2Sandbox()
        # 真 spawn 一个 host process
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "import time; time.sleep(2)",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        with pytest.raises(RuntimeError, match="not in any docker container"):
            await sb._attach_docker_networks(proc, ["test-net-phase5c-01"])

        # daemon 应被 terminate
        await proc.wait()
    finally:
        subprocess.run(["docker", "network", "rm", "test-net-phase5c-01"],
                       capture_output=True, check=False)


# ── mock huly server 端口连通性 ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mock_huly_server_can_listen_on_18087():
    """Phase 5.C 测试基线: mock huly server 监听 127.0.0.1:18087 应可用（防端口冲突）。

    若此 test fail（端口被占），后续 Wave 2-3 huly mock 测试会全部失败。
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", 18087))
        s.listen(1)
    except OSError as e:
        pytest.fail(f"port 18087 unavailable (Wave 2-3 mock huly server 基线): {e}")
    finally:
        s.close()
```

### 2.4 Phase 5.B regression 检查（DoD 必跑）

执行命令（必须在 verify 中跑）:

```bash
cd backend && pytest tests/platforms/ -x -q && \
pytest tests/platforms_integration/test_huly_acid_test.py -v && \
pytest tests/platforms_integration/test_fault_isolation.py tests/platforms_integration/test_watchdog_grace_period.py -v
```

**DoD**:
- Phase 5.B platforms 单测全绿（162 测试，不含本 plan 新增）
- 5/5 huly acid test 全绿（test_huly_acid_test.py 含 3 个 test_* function 实际 5 个断言）
- fault_isolation + watchdog_grace_period 0 regression
- 本 plan 新增 ≥ 16 unit tests + ≥ 5 manifest schema tests + ≥ 3 integration tests

### 2.5 commit messages

1. `test(05c-01): add unit tests for docker_networks (mock subprocess + mock docker SDK, 11+ cases)`
2. `test(05c-01): add SandboxConfig.docker_networks validator tests (4 cases)`
3. `test(05c-01): add integration tests for sandbox docker_networks (Linux + docker only)`
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -m pytest tests/platforms/sandbox/test_docker_networks.py tests/platforms/test_manifest_schema.py -x -q 2>&1 | tail -25 && python -m pytest tests/platforms_integration/test_sandbox_docker_networks_integration.py -x -q 2>&1 | tail -10 && python -m pytest tests/platforms/ -q 2>&1 | tail -5 && python -m pytest tests/platforms_integration/test_huly_acid_test.py -v 2>&1 | tail -10</automated>
  </verify>
  <done>≥ 11 unit tests + ≥ 5 manifest schema tests + ≥ 3 integration tests 全绿；Phase 5.B 162 platforms 单测 0 regression；5/5 huly acid test 全绿；fault_isolation + watchdog_grace_period 0 regression</done>
</task>

</tasks>

<testing>
**三层测试矩阵（CLAUDE.md §2.2 强制要求）**:

| 层 | 文件 | 测试数 | mock 策略 | 关键场景 |
|---|---|---|---|---|
| **Unit** | `backend/tests/platforms/sandbox/test_docker_networks.py` | ≥ 11 | mock subprocess + mock `docker.from_env()` + mock `Path.read_text` | PosixResource no-op / regex 4 格式 / _resolve_container_for_pid 3 分支 / 三失败模式 / 1 成功路径 |
| **Unit** | `backend/tests/platforms/test_manifest_schema.py::TestSandboxConfigDockerNetworks` | ≥ 5 | pydantic ValidationError 断言 | 默认 [] / 合法 3 种 / 含 `/` / 首字符 `-` / 含空格 |
| **Integration** | `backend/tests/platforms_integration/test_sandbox_docker_networks_integration.py` | ≥ 3 | **禁止 mock docker** —— 真起 `docker network create test-net-phase5c-01` + 真 spawn host process | happy path 空 list / Linux + docker 真 attach 失败模式 3 / mock huly server 18087 端口连通性 |
| **E2E** | （留 plan 08 — 本 plan 不做） | — | browser-harness CDP 直连用户 Chrome | DAG → doc_write → 真 Outline/Lark/Huly 文档出现 + 协作者收 @ |

**集成测试禁止 mock 数据库 / docker（CLAUDE.md §2.2 / §feedback_e2e_browser_harness）**:
- 真起 `docker network create test-net-phase5c-01`（test 结束 cleanup `docker network rm`）
- 真 spawn host process（`asyncio.create_subprocess_exec` 真起 Python 进程）
- mock huly server 监听 `127.0.0.1:18087`（Wave 2-3 复用，本 plan 仅 verify 端口可用）
- 仅 Linux + docker 可用时跑（CI ubuntu-latest + dev macOS skip 真 docker test，但保留 happy path）

**Phase 5.B regression 必跑**:

```bash
cd backend && pytest tests/platforms/ -x -q                               # 162 单测 0 regression
cd backend && pytest tests/platforms_integration/test_huly_acid_test.py -v   # 5/5 acid test
cd backend && pytest tests/platforms_integration/test_fault_isolation.py -v # 5.B fault isolation
cd backend && pytest tests/platforms_integration/test_watchdog_grace_period.py -v
```

**reading doc gate（CLAUDE.md §2.7）**:

```bash
git log --oneline backend/app/agent_builder/platforms/sandbox/runner.py docs/reading-dify-05c-01-sandbox-docker-networks-2026-05-18.md | head -10
# docs(05c-01): ... 必须早于任何 feat(05c-01) commit
```
</testing>

<verification>
**Phase gate（plan 01 — Wave 1 出口）**:

- [ ] Reading doc commit 早于任何 feat / test commit（`git log` 校验）
- [ ] Reading doc ≥ 80 行 + 5 借鉴点 + License attribution
- [ ] SandboxRunner Protocol + PosixResourceSandbox + CgroupsV2Sandbox 三处签名含 `docker_networks: list[str] | None = None`
- [ ] manifest SandboxConfig 8 字段（5.B 7 + docker_networks），含 field_validator 拒非法命名
- [ ] daemon_client._start 透传 `docker_networks=self._sandbox_config.docker_networks`
- [ ] huly platform.yaml 含 `sandbox.docker_networks: [huly_huly_net]` 且 load_manifest 解析无报错
- [ ] CgroupsV2Sandbox._attach_docker_networks 三失败模式各自抛 RuntimeError + terminate daemon
- [ ] CgroupsV2Sandbox._resolve_container_for_pid 兼容 cgroup v1 + v2 格式
- [ ] Phase 5.B 162 platforms 单测 0 regression
- [ ] 5/5 huly acid test 全绿（test_huly_acid_test.py）
- [ ] fault_isolation + watchdog_grace_period 0 regression
- [ ] 本 plan 新增 ≥ 11 unit + ≥ 5 manifest schema + ≥ 3 integration tests 全绿

**接口冻结声明（Wave 2 三 plan 并行前提）**:
- SandboxRunner.spawn_with_limits 签名最终: `(cmd, *, cpu_seconds, memory_bytes, env=None, cwd=None, docker_networks=None)`
- SandboxConfig.docker_networks: `list[str] = Field(default_factory=list)` + docker_networks_must_be_valid_names validator
- 任何后续 plan 不得修改此契约（仅消费）
</verification>

<success_criteria>
1. **Dify reading doc gate 通过**: docs commit 早于 feat commit；≥ 80 行 + 5 借鉴点 + License attribution
2. **接口冻结**: SandboxRunner Protocol + 2 实现 + SandboxConfig + daemon_client 全部签名扩展到位
3. **三失败模式覆盖**: docker 不可用 / network 不存在 / pid 不在 container 各自独立 RuntimeError + terminate daemon
4. **manifest 字段校验**: docker_networks_must_be_valid_names validator 拒非法命名（防 Pitfall 5 拼写错）
5. **Phase 5.B 0 regression**: 162 platforms 单测 + 5/5 huly acid test + fault_isolation + watchdog_grace_period 全绿
6. **三层测试覆盖**: unit (≥ 11) + manifest schema (≥ 5) + integration (≥ 3)；E2E 留 plan 08
7. **mock huly server 18087 端口基线**: 集成测试验证端口可监听（Wave 2-3 mock huly 复用）
8. **Wave 2 三 plan 可并行**: 接口对外冻结，无后续修改风险
</success_criteria>

<risks>
| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| docker SDK 不在 backend pyproject.toml 依赖中（CI 失败） | 中 | 集成测试无法跑 | Task 1 顺带 add `docker>=7.0` 到 pyproject.toml（或 Task 2 测试用 `pytest.importorskip("docker")`） |
| CI 环境 cgroup v1 格式与本地不同（regex 漏匹配） | 中 | _resolve_container_for_pid 返回 None 误报 | 单测覆盖 v1 / v2 / systemd-slice 3 种格式；集成测试 Linux 真跑兜底 |
| Phase 5.B daemon_client 现有 11 测试因加 docker_networks=None 默认值不影响（向后兼容） | 低 | 5.B 测试 fail | 默认值 None + 调用方不传 → 老路径 unchanged；显式 verify 跑 5.B 测试 |
| huly platform.yaml 已有 sandbox 段（5.B 加），追加 docker_networks 时 YAML 缩进错 | 低 | load_manifest fail | verify 自动跑 load_manifest('plugins/huly/platform.yaml') 检测 |
| 集成测试 docker network 名 `test-net-phase5c-01` 已存在（前次未清理） | 低 | 测试 setup fail | `docker network create` 已用 `check=False`；finally `docker network rm` 兜底 |
| Wave 2 三 plan 发现需要扩展 docker_networks 参数（接口未冻结） | 低 | 接口反复改，三 plan 阻塞 | 本 plan 一次性把所有 Wave 2 需要的参数加齐（与 RESEARCH §Pattern 4 完全对齐）；DoD 含接口冻结声明 |
</risks>

<rollback>
**回滚策略（5 commit 拆分便于精确回滚）**:

1. **manifest.py 回滚**: `git revert <feat-1-sha>` — SandboxConfig.docker_networks 字段移除 + validator 移除
2. **Protocol 回滚**: `git revert <feat-2-sha>` — SandboxRunner.spawn_with_limits 签名去掉 docker_networks
3. **PosixResource 回滚**: `git revert <feat-3-sha>` — no-op + warning log 移除
4. **CgroupsV2 回滚**: `git revert <feat-4-sha>` — _attach_docker_networks + _resolve_container_for_pid 移除
5. **daemon_client 回滚**: `git revert <feat-5-sha>` — 1 行 kwarg 移除

**全部回滚后状态**: Phase 5.B 端到端绿（接口完全恢复 5.B 状态）。

**reading doc 不回滚**: 即使代码全 revert，reading doc 保留作为知识资产（已 commit）。

**Wave 2 阻塞缓解**: 若需要回滚但 Wave 2 已开工，需通知三 plan 暂停 + 等 plan 01 重做（接口冻结违约成本）。
</rollback>

<output>
完成后创建 `.planning/phases/05c-doc-capability/05c-01-SUMMARY.md`，至少含:

- Reading doc 链接 + commit hash（CLAUDE.md §2.7 gate 凭证）
- SandboxConfig 8 字段表（新增 docker_networks 默认 [] + validator regex）
- SandboxRunner Protocol 最终签名（接口对外冻结声明 — Wave 2 三 plan 引用）
- CgroupsV2 三失败模式实现总结（每模式 RuntimeError 文案）
- 三层测试覆盖矩阵（unit / manifest schema / integration 各文件 + 测试数）
- Phase 5.B regression 截图（162 单测 + 5/5 acid test + fault_isolation + watchdog 全绿）
- **Dify 参考点** 小节：列出本 plan reading doc 中 5 借鉴点，每条指回 reading doc 章节锚点
- Wave 2 三 plan 接口契约清单（spawn_with_limits 签名 / SandboxConfig.docker_networks 用法 / daemon_client 透传路径）
</output>
