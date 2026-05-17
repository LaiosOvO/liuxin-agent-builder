# Dify 阅读笔记 — Plan 05b-01 SandboxConfig manifest 扩展

> 日期: 2026-05-17
> 仓库: https://github.com/langgenius/dify (commit `e7e6fe8813c30d7d4815d7d347f0b48748c4aaa0`, local clone `/Users/admin/ai/ref/dify/repo/`)
> Stars: ~141k
> 阅读模块：`api/core/plugin/entities/plugin.py`（PluginDeclaration + PluginResourceRequirements 字段，204 行）/ `api/services/plugin/plugin_service.py`（sandbox 段消费链路）

---

## 项目概述（一句话）

Dify 是国内最成熟的开源 LLM 应用工作流平台（141k stars），插件运行时通过 **独立 Go 项目 `dify-plugin-daemon`** 实现，Python 主仓库只声明资源**预算**（`PluginResourceRequirements.memory`），真正的 cgroups / network 限制全部下沉到 daemon 进程。

---

## 技术栈（Pydantic 版本 / YAML loader / 单位解析方式）

- **Pydantic v2**（`pydantic import BaseModel, Field, field_validator, model_validator`），与本项目 Phase 5.A 锁定的 v2 一致
- **未用 `extra=forbid`**（Dify `PluginResourceRequirements` / `PluginDeclaration` 都默认 `extra=ignore`） — 我们项目 5.A 决策强严格 `forbid` 是**显式偏离 Dify**
- **未自带 K8s 内存单位解析**：Dify `PluginResourceRequirements.memory: int` 直接是 int bytes，不接受 "512Mi" / "1Gi" 字符串
- **未在 Python 侧实现网络白名单**：grep `/Users/admin/ai/ref/dify/repo/api/core/plugin/` 整个目录 0 匹配 `AllowlistTransport / network_allow / cpu_limit / RLIMIT_`
- **YAML loader**：未直接读 yaml（Dify plugin manifest 通过 dify-plugin-daemon 解析后 push 给 main process）

---

## 架构要点（manifest 加载链路简图 / sandbox 段在哪一层消费）

```text
Dify 架构（resource 段消费）：

  plugin.yaml (TOML)                                    ┌─────────────────────────┐
        │                                               │ dify-plugin-daemon (Go) │
        ▼                                               │  - cgroups v2 系统      │
  dify-plugin-daemon (Go binary)         ──REST──▶     │  - network namespace    │
        │                                               │  - syscall sandbox      │
        │ 解析 + 校验                                   └─────────────────────────┘
        ▼
  POST /plugin/install → Python main API
        │
        ▼
  PluginDeclaration (Pydantic) ←── 只保留 metadata（包括 resource.memory: int 字段）
        │
        ▼
  PluginInstallation 存 DB
```

**关键发现**：Dify 主仓库 (Python) **完全不做 sandbox enforcement** —— `PluginResourceRequirements` 只是 declaration / budget，真实限制由独立 Go daemon 完成。这与我们的 Phase 5.B 方向不同：**我们用 Python 主进程 + `resource.setrlimit` baseline 实现限制**（不引入 Go 二进制依赖，零额外运维成本）。

---

## 可借鉴的设计模式

### 1. PluginResourceRequirements 嵌套结构（不可借鉴，因过度简化）

**位置**：`api/core/plugin/entities/plugin.py:26-58`

```python
class PluginResourceRequirements(BaseModel):
    memory: int                                # ← 仅 int bytes，无单位解析

    class Permission(BaseModel):
        class Tool(BaseModel):                 # 嵌套类设计 — 权限 namespace
            enabled: bool | None = Field(default=False)
        class Model(BaseModel):                # 6 个子权限（llm / text_embedding / rerank / tts / speech2text / moderation）
            ...
        class Storage(BaseModel):
            size: int = Field(ge=1024, le=1073741824, default=1048576)
        ...
    permission: Permission | None = Field(default=None)
```

**Takeaway**：Dify 把 `permission` 与 `resource` 高度耦合（同一类下嵌套）。我们项目 5.B `SandboxConfig` **不耦合 permission**（permission 在 capability 段，与资源限制正交），更清晰。

### 2. Field 约束 `ge` / `le` 用法（直接借鉴）

**位置**：`api/core/plugin/entities/plugin.py:50` (`Storage.size: int = Field(ge=1024, le=1073741824, default=1048576)`)

**Takeaway**：用 `Field(ge=..., le=...)` 直接给数值字段加范围约束。
我们项目 5.B `timeout_invoke: int = Field(default=30, gt=0, le=3600)` 与 `timeout_idle: int = Field(default=300, gt=0, le=86400)` **直接采用此模式**，与 Phase 5.A `Storage.size: ge=1024` 风格一致。

### 3. `@field_validator` 失败 raise ValueError 模式（直接借鉴）

**位置**：`api/core/plugin/entities/plugin.py:82-91`

```python
@field_validator("minimum_dify_version")
@classmethod
def validate_minimum_dify_version(cls, v: str | None) -> str | None:
    if v is None:
        return v
    try:
        Version(v)
        return v
    except InvalidVersion as e:
        raise ValueError(f"Invalid version format: {v}") from e
```

**Takeaway**：Pydantic v2 `@field_validator` 失败 **raise ValueError**（不要 raise ValidationError 因为 Pydantic 会自动包装）。
我们 5.B `memory_must_be_k8s_format` validator 调用 `parse_memory()` 失败时也是 `raise ValueError(...) from e`，与 Dify 同模式。

### 4. nested BaseModel 组织（直接借鉴）

**位置**：`api/core/plugin/entities/plugin.py:70-104` (PluginDeclaration 内嵌 Plugins / Meta)

**Takeaway**：把强相关子结构作为 nested class 而非 module-level 兄弟类。可降低导入复杂度。
我们项目 Phase 5.A 已用此模式（`RuntimeConfig` / `CapabilitySpec` / `SandboxConfig` 都是 manifest module top-level —— 这是与 Dify 的偏离，因为 Wave 2 plans 需要 `from ... import SandboxConfig`，nested class 不便外部 import）。

### 5. `Field(default_factory=list)` 而非 `= []`（直接借鉴）

**位置**：`api/core/plugin/entities/plugin.py:72-76` (`tools: list[str] | None = Field(default_factory=list[str])`)

**Takeaway**：mutable 默认值用 `default_factory` 避免类间共享。
我们 5.B `network: list[str] = Field(default_factory=list)` 与 `env_allowlist: list[str] = Field(default_factory=list)` 直接采用。

### 6. v1 简化原则：不接受复杂字符串解析（部分借鉴 + 部分偏离）

**Dify 偏离点**：Dify `memory: int` 字段直接拒绝单位字符串 — plugin 作者必须算好 bytes 写 int。

**我们的选择**：`memory: str` 接受 K8s 风格 `"512Mi"` / `"1Gi"` 字符串，提供 `memory_bytes` property 派生 int。
理由：YAML 配置可读性 / 与 K8s/Docker 生态对齐 / Phase 5.B `parse_memory` 是独立模块（Wave 2/3 runner 可单独使用），10 行 regex 实现成本极低，比 Dify 强迫用户手算 bytes 体验好。

---

## 与本项目的关系（Phase 5.B SandboxConfig 字段命名 + validators + 默认值选型如何对齐 / 偏离）

| 字段 / 行为 | Dify 实现 | 我们 5.B 实现 | 取舍理由 |
| ---- | ---- | ---- | ---- |
| **`memory` 字段** | `memory: int` (bytes) | `memory: str = "1Gi"` (K8s 单位) + `memory_bytes: int` property | YAML 可读性 > 单类型简洁；K8s 生态对齐 |
| **`cpu_limit`** | 无（Go daemon 实现） | `cpu_limit: str = "2.0"` (Docker style cores) + `cpu_limit_seconds: int` property | 与 cgroups v2 `CPUQuota=` 单位对齐 |
| **`network` 白名单** | 无（network namespace 在 Go 层） | `network: list[str]`, regex `^[a-z0-9.-]+:\d+$` | application-level httpx Transport 实现（5.B Wave 2） |
| **`timeout_invoke` / `timeout_idle`** | 无 | `int Field(gt=0, le=3600/86400)` | 三层超时是我们 5.B 核心创新 |
| **`use_cgroups` 开关** | 无（Go daemon 默认开） | `bool = False`（Python `resource.setrlimit` baseline 默认） | 跨平台优先 |
| **`env_allowlist`** | 无（Go daemon 内部 strip） | `list[str]` 默认 `[]` (strip all) | Pitfall 8 防 secret 泄漏 |
| **`extra="forbid"`** | 未启用 | 启用（5.A 决策） | typo 立刻 raise，防隐式冲突 |
| **K8s 单位解析** | 不解析 | `parse_memory()` 自写 10 行 regex | 0 依赖；Wave 2/3 共享 |
| **`@field_validator` raise ValueError** | 是 | 是 | 同 |
| **`Field(ge=/le=)` 范围约束** | 是（Storage.size） | 是（timeout_*） | 同模式 |
| **`Field(default_factory=list)`** | 是 | 是 | 同模式 |
| **Pydantic v2** | 是 | 是 | 同 |

---

## License 与 attribution

- Dify 仓库 License: **AGPL-3.0**（`/Users/admin/ai/ref/dify/repo/LICENSE`）
- 我们 agent-builder License: **Apache-2.0**（与 flock 一致）

**严禁**直接拷贝 Dify Python 源码（包括 PluginResourceRequirements / PluginDeclaration 类定义）。本 plan **100% 独立创作**：
- `SandboxConfig` 类是 Phase 5.A 已存在的 placeholder（3 字段）的扩展，与 Dify `PluginResourceRequirements` 结构、字段名、嵌套方式都不同
- `parse_memory` / `parse_cpu_seconds` 是 10 行 regex helper，无 Dify 对应实现可拷贝
- Validators 模式（`raise ValueError(...) from e`）是 Pydantic 官方文档推荐用法，非 Dify 独创

仅借鉴**设计哲学**（v1 简化 / Field 约束模式 / default_factory 用法），无源码级拷贝。

---

## 阅读总结：可借鉴 6 点 + 偏离 5 点

**直接借鉴（6）**：
1. Pydantic v2 + `@field_validator` 失败 raise ValueError 模式
2. `Field(ge=/le=)` 整数范围约束
3. `Field(default_factory=list)` 避免 mutable 默认值共享
4. `from e` 保留异常链
5. Nested BaseModel 组织子配置（我们用 module-level 类，但同一模块下集中）
6. v1 简化原则（不接受复杂字符串解析时优先拒绝）

**显式偏离（5）**：
1. `extra="forbid"` 严格模式（Dify ignore；我们 forbid）
2. K8s 风格 memory 字符串 + property 派生 int（Dify int only）
3. Python 主进程实现 sandbox（Dify Go daemon 实现）
4. application-level httpx 白名单（Dify network namespace 真隔离）
5. `env_allowlist` 字段（Dify 无对应 — 是我们 Pitfall 8 防 secret 泄漏的关键 v1 必备）

**结论**：Dify 在 Python 层只保留 declarative resource budget，真正 enforcement 全部下沉 Go binary。我们 Phase 5.B 走另一条路 — Python 主进程内 baseline + Linux opt-in cgroups，零额外二进制依赖。Dify 给我们的最大借鉴是**字段命名思路 + Pydantic v2 validator 模式**，不是 sandbox 实现细节。
