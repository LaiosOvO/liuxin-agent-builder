---
phase: 05b-plugin-sandbox
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - docs/reading-dify-05b-01-sandbox-config-2026-05-17.md
  - backend/app/agent_builder/platforms/manifest.py
  - backend/app/agent_builder/platforms/sandbox/__init__.py
  - backend/app/agent_builder/platforms/sandbox/parser.py
  - backend/tests/platforms/test_manifest_schema.py
  - backend/tests/platforms/sandbox/__init__.py
  - backend/tests/platforms/sandbox/test_parser.py
  - plugins/huly/platform.yaml
autonomous: true
requirements:
  - PLUG-FW-13

must_haves:
  truths:
    - "SandboxConfig 接受 cpu_limit / memory / network / timeout_invoke / timeout_idle / use_cgroups / env_allowlist 七字段（5.A 三字段补齐 + 五新字段）"
    - "memory 字段必须符合 K8s 风格（512Mi / 1Gi / 2.5Gi），不符则 raise ValidationError"
    - "network 字段必须是 host:port 列表（example.com:443），不符则 raise ValidationError"
    - "SandboxConfig.memory_bytes 属性返回 int bytes（512Mi → 536870912）"
    - "SandboxConfig.cpu_limit_seconds 属性返回 int seconds（'2.0' → 7200）"
    - "manifest 未声明 sandbox 段时使用安全默认值（network=[] 禁所有出站，env_allowlist=[] strip 所有）"
    - "Dify 阅读文档先于代码 commit（CLAUDE.md §2.7 硬性 gate）"
    - "Phase 5.A manifest 现有 13 测试 + 162 platforms 测试 0 regression"
  artifacts:
    - path: "docs/reading-dify-05b-01-sandbox-config-2026-05-17.md"
      provides: "Dify plugin daemon manifest sandbox 段设计借鉴点"
      min_lines: 80
    - path: "backend/app/agent_builder/platforms/manifest.py"
      provides: "SandboxConfig 扩展字段 + Pydantic v2 validators + memory_bytes/cpu_limit_seconds 属性"
      contains: "class SandboxConfig"
    - path: "backend/app/agent_builder/platforms/sandbox/__init__.py"
      provides: "sandbox 子包入口"
    - path: "backend/app/agent_builder/platforms/sandbox/parser.py"
      provides: "parse_memory + parse_cpu helper（独立模块便于 Wave 2/3 引用）"
      contains: "def parse_memory"
    - path: "backend/tests/platforms/sandbox/test_parser.py"
      provides: "parser 单元测试（K8s 单位 8 种 + edge case）"
    - path: "plugins/huly/platform.yaml"
      provides: "示例 manifest 加 sandbox 段（演示新字段）"
      contains: "sandbox:"
  key_links:
    - from: "backend/app/agent_builder/platforms/manifest.py"
      to: "backend/app/agent_builder/platforms/sandbox/parser.py"
      via: "memory_bytes / cpu_limit_seconds 属性内部调用 parse_memory / parse_cpu"
      pattern: "from .sandbox.parser import"
    - from: "backend/tests/platforms/test_manifest_schema.py"
      to: "SandboxConfig validators"
      via: "pydantic ValidationError 断言"
      pattern: "pytest.raises\\(ValidationError"
---

<objective>
扩展 Phase 5.A `SandboxConfig` 的 schema —— 补齐 `timeout_invoke` / `timeout_idle` / `use_cgroups` / `env_allowlist` 四个新字段、给 `memory` / `network` / `cpu_limit` 加 Pydantic v2 validators、新增 `memory_bytes` / `cpu_limit_seconds` 派生属性。同时建立 `backend/app/agent_builder/platforms/sandbox/` 子包结构（parser.py + __init__.py），为 Wave 2/3 plans 提供共享的 K8s 内存单位解析 helper。

Purpose: schema 是后续所有 sandbox runner / watchdog / network / cgroups 实现的**单一真相源**——所有字段在此 plan 落定，后续 plans 不再修改 manifest（避免反复改动 Pydantic schema 造成 5.A regression）。

Output: 1 个 Dify reading doc + 1 个 manifest.py 扩展 + sandbox 子包初始化（parser.py + __init__.py）+ 单元测试覆盖 SandboxConfig 全字段 validators 与 parser K8s 单位。
</objective>

<execution_context>
@/Users/admin/.claude/get-shit-done/workflows/execute-plan.md
@/Users/admin/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/phases/05b-plugin-sandbox/05b-CONTEXT.md
@.planning/phases/05b-plugin-sandbox/05b-RESEARCH.md
@backend/app/agent_builder/platforms/manifest.py
@backend/app/agent_builder/platforms/__init__.py
@plugins/huly/platform.yaml
@CLAUDE.md

<interfaces>
<!-- Phase 5.A 已有 SandboxConfig（70 行片段），本 plan 扩展。Wave 2/3 plans 将引用如下接口。 -->

From backend/app/agent_builder/platforms/manifest.py（5.A 现状，本 plan 扩展）:
```python
class SandboxConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cpu_limit: str | None = "1.0"
    memory_limit: str | None = "512Mi"
    network: list[str] = Field(default_factory=list)
```

本 plan 完成后的最终接口（Wave 2/3 依赖此契约）:
```python
class SandboxConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cpu_limit: str = Field(default="2.0", pattern=r"^\d+(\.\d+)?$")
    memory: str = Field(default="1Gi")                  # rename memory_limit → memory（k8s 风格）
    network: list[str] = Field(default_factory=list)
    timeout_invoke: int = Field(default=30, gt=0, le=3600)
    timeout_idle: int = Field(default=300, gt=0, le=86400)
    use_cgroups: bool = False
    env_allowlist: list[str] = Field(default_factory=list)

    @field_validator("memory")
    @classmethod
    def memory_must_be_k8s_format(cls, v: str) -> str: ...

    @field_validator("network")
    @classmethod
    def network_entries_must_be_host_port(cls, v: list[str]) -> list[str]: ...

    @property
    def memory_bytes(self) -> int: ...

    @property
    def cpu_limit_seconds(self) -> int: ...
```

From backend/app/agent_builder/platforms/sandbox/parser.py（本 plan 创建）:
```python
def parse_memory(value: str) -> int:
    """K8s 风格内存单位解析。"512Mi" → 536870912。支持 K/M/G/T (1000^n) + Ki/Mi/Gi/Ti (1024^n)。"""

def parse_cpu_seconds(value: str) -> int:
    """CPU limit '2.0' → RLIMIT_CPU 累积秒数（保守 3600s × cores）。"""
```
</interfaces>
</context>

<reference>
Dify 模块映射（CLAUDE.md §2.7 强制规则）:
- 后端必读: `api/core/plugin/entities/plugin.py` (PluginDeclaration sandbox/resource 部分 — 0.16+ 版本新增)
- 后端参考: `api/services/plugin/plugin_service.py` (sandbox 段消费链路)

借鉴重点（reading doc 必含）:
1. Dify resource/sandbox 字段命名（cpu_limit 还是 cpu？memory_limit 还是 memory？）
2. Dify K8s 单位解析方式（自写 regex vs humanfriendly 等库）
3. Dify network whitelist 配置方式（如何表达 host:port 列表）
4. Dify 默认值策略（restrictive 默认 vs permissive 默认）
5. Dify Pydantic v2 validators 模式（与 5.A 现有 `extra=forbid` 一致性）

License: Dify AGPL-3.0 vs agent-builder Apache-2.0 — 严禁拷源代码，仅借鉴设计模式。
</reference>

<tasks>

<task type="auto">
  <name>Task 0: Dify reading doc（CLAUDE.md §2.7 硬性 gate）</name>
  <files>docs/reading-dify-05b-01-sandbox-config-2026-05-17.md</files>
  <action>
    阅读以下 Dify 文件并写阅读笔记（**先 commit 此 doc 才能进 Task 1**）:

    1. `/Users/admin/ai/ref/dify/repo/api/core/plugin/entities/plugin.py` — PluginDeclaration sandbox/resource 字段（如果该版本无 sandbox，记录"Dify 暂无对应实现"作为差异点）
    2. `/Users/admin/ai/ref/dify/repo/api/services/plugin/plugin_service.py` — sandbox 段在 manifest 加载链路中如何被消费（grep "sandbox\|resource\|memory_limit\|cpu_limit" 至少 30 行上下文）
    3. （可选补充）`/Users/admin/ai/ref/dify/repo/api/core/plugin/manager.py` — 资源限制在 plugin manager 中的注入点

    文档结构按 CLAUDE.md §2.7 模板:
    ```
    # Dify 阅读笔记 — Plan 05b-01 SandboxConfig manifest 扩展
    > 日期: 2026-05-17
    > 仓库: https://github.com/langgenius/dify (commit ${LOCAL_HEAD}, /Users/admin/ai/ref/dify/repo/)
    > Stars: ~141k

    ## 项目概述（一句话）
    ## 技术栈（Pydantic 版本 / YAML loader / 单位解析方式）
    ## 架构要点（manifest 加载链路简图 / sandbox 段在哪一层消费）
    ## 可借鉴的设计模式（4-6 条，每条 [Dify 路径:行号] + 一句话 takeaway）
    ## 与本项目的关系（Phase 5.B SandboxConfig 字段命名 + validators + 默认值选型如何对齐 / 偏离）
    ## License 与 attribution（AGPL-3.0 不拷源；本 plan 100% 独立创作）
    ```

    最少 80 行；commit message: `docs(05b-01): add Dify sandbox config reading doc`。
    禁止：直接拷贝 Dify Python/Go 源码片段（License 风险）。
  </action>
  <verify>
    <automated>test -f /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05b-01-sandbox-config-2026-05-17.md && wc -l /Users/admin/ai/resume/interview/liuxin/agent-builder/docs/reading-dify-05b-01-sandbox-config-2026-05-17.md | awk '{exit ($1>=80)?0:1}'</automated>
  </verify>
  <done>reading doc 文件存在；≥ 80 行；git log 显示本 doc commit 在 Task 1 之前。</done>
</task>

<task type="auto">
  <name>Task 1: 扩展 SandboxConfig schema + 创建 sandbox/parser.py</name>
  <files>
    backend/app/agent_builder/platforms/manifest.py
    backend/app/agent_builder/platforms/sandbox/__init__.py
    backend/app/agent_builder/platforms/sandbox/parser.py
    plugins/huly/platform.yaml
  </files>
  <action>
    1. **创建 sandbox 子包**:
       - `backend/app/agent_builder/platforms/sandbox/__init__.py`: 空 docstring（"Phase 5.B sandbox runtime: resource limits / network allowlist / watchdog / cgroups."）
       - `backend/app/agent_builder/platforms/sandbox/parser.py`: 两个纯函数 + module-level 常量

    `parser.py` 完整实现:
    ```python
    """K8s 风格资源单位解析 helper（Phase 5.B sandbox runner 共享）。"""
    from __future__ import annotations
    import re

    _MEMORY_RE = re.compile(r"^(\d+(?:\.\d+)?)(Ki|Mi|Gi|Ti|K|M|G|T|)$")
    _MEMORY_MULTIPLIERS = {
        "": 1, "K": 1000, "M": 1000**2, "G": 1000**3, "T": 1000**4,
        "Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4,
    }

    def parse_memory(value: str) -> int:
        """K8s 风格内存解析。'512Mi' → 536870912 bytes。"""
        m = _MEMORY_RE.match(value)
        if not m:
            raise ValueError(f"memory 必须是 K8s 单位格式（如 '512Mi' / '1Gi'），实际: {value!r}")
        val, unit = m.group(1), m.group(2)
        return int(float(val) * _MEMORY_MULTIPLIERS[unit])

    def parse_cpu_seconds(cpu_limit: str) -> int:
        """CPU limit '2.0' → RLIMIT_CPU 累积总秒数（保守 3600s × cores）。

        注：RLIMIT_CPU 是总累积 CPU 秒，非 quota；真正的 CPU quota 限制由 cgroups v2 CPUQuota 提供。
        这里给 long-running plugin 足够余量（3600s × 2 cores = 7200s）。
        """
        return int(float(cpu_limit) * 3600)

    __all__ = ["parse_memory", "parse_cpu_seconds"]
    ```

    2. **扩展 manifest.py 的 SandboxConfig**:
       - **重命名** `memory_limit` → `memory`（k8s 风格 + RESEARCH 决策对齐；旧字段不保留 v1 不需要向后兼容因 5.A 仅留 placeholder 未真消费）
       - **加字段**: `timeout_invoke: int = Field(default=30, gt=0, le=3600)`，`timeout_idle: int = Field(default=300, gt=0, le=86400)`，`use_cgroups: bool = False`，`env_allowlist: list[str] = Field(default_factory=list)`
       - **加 validators**:
         - `cpu_limit`: `Field(default="2.0", pattern=r"^\d+(\.\d+)?$")` （注意默认改成 "2.0" 与 RESEARCH 一致）
         - `memory`: `Field(default="1Gi")` + `@field_validator("memory")` 调用 `parse_memory()` 验证（失败 raise ValueError）
         - `network`: `@field_validator("network")` 遍历每条 entry 用 `re.match(r"^[a-z0-9.-]+:\d+$", entry)` 验证
       - **加属性**:
         - `@property def memory_bytes(self) -> int: return parse_memory(self.memory)`
         - `@property def cpu_limit_seconds(self) -> int: return parse_cpu_seconds(self.cpu_limit)`
       - **import**: `from .sandbox.parser import parse_memory, parse_cpu_seconds`
       - **保留 `extra="forbid"`**（5.A 决策）

    3. **plugins/huly/platform.yaml 加 sandbox 段** 演示新字段:
       ```yaml
       sandbox:
         cpu_limit: "1.0"
         memory: "512Mi"
         network:
           - huly.example.com:443
         timeout_invoke: 30
         timeout_idle: 300
         use_cgroups: false
         env_allowlist:
           - HULY_ENDPOINT
       ```

    **避坑**:
    - 不要保留 `memory_limit` 字段别名（v1 简洁；Wave 2 runner 显式 import 新名）— 5.A 仅 placeholder 未真消费此字段，rename 不破坏 acid test
    - `extra="forbid"` 不能换 `allow`（RESEARCH §Anti-Patterns 明确禁止）
    - `parser.py` 不能 import Pydantic（保持轻量；纯函数）— manifest.py 才依赖 Pydantic
    - 默认 `network=[]` 表示**禁所有出站**（restrictive 默认 — 安全核心，绝不能默认放行）
    - 默认 `env_allowlist=[]` 表示 strip 所有 env（Pitfall 8）

    commit messages（拆 2 个 commit）:
    - `feat(05b-01): add sandbox parser helper (parse_memory + parse_cpu_seconds)`
    - `feat(05b-01): extend SandboxConfig with validators + new fields (PLUG-FW-13)`
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -c "from app.agent_builder.platforms.manifest import SandboxConfig; c = SandboxConfig(); assert c.memory_bytes == 1024**3, c.memory_bytes; assert c.cpu_limit_seconds == 7200, c.cpu_limit_seconds; assert c.use_cgroups is False; assert c.env_allowlist == []"</automated>
  </verify>
  <done>
    SandboxConfig 含 7 字段 + 2 properties；memory_bytes('1Gi') = 1073741824；cpu_limit_seconds('2.0') = 7200；network=[] 默认；env_allowlist=[] 默认；plugins/huly/platform.yaml 加 sandbox 段且通过 load_manifest 解析无报错。
  </done>
</task>

<task type="auto">
  <name>Task 2: 单元测试 — SandboxConfig validators + parser K8s 单位 + 5.A regression</name>
  <files>
    backend/tests/platforms/test_manifest_schema.py
    backend/tests/platforms/sandbox/__init__.py
    backend/tests/platforms/sandbox/test_parser.py
  </files>
  <action>
    1. **创建 `backend/tests/platforms/sandbox/__init__.py`**（空文件，pytest package marker）

    2. **创建 `backend/tests/platforms/sandbox/test_parser.py`** ≥ 12 测试:
       - `test_parse_memory_si_units`: K/M/G/T 各 1 测试，断言乘子 1000^n
       - `test_parse_memory_binary_units`: Ki/Mi/Gi/Ti 各 1 测试，断言乘子 1024^n
       - `test_parse_memory_no_unit_is_bytes`: `parse_memory("1024")` == 1024
       - `test_parse_memory_decimal_value`: `parse_memory("1.5Gi")` == int(1.5 * 1024**3)
       - `test_parse_memory_invalid_format_raises`: `parse_memory("512MB")` raises ValueError（MB 非法，必须 Mi）
       - `test_parse_memory_negative_raises`: `parse_memory("-1Gi")` 触发 ValueError（regex 不匹配负号）
       - `test_parse_cpu_seconds_integer`: `parse_cpu_seconds("2")` == 7200
       - `test_parse_cpu_seconds_decimal`: `parse_cpu_seconds("0.5")` == 1800
       - `test_parse_cpu_seconds_invalid_raises`: `parse_cpu_seconds("abc")` raises ValueError (float 转换失败)

    3. **修改 `backend/tests/platforms/test_manifest_schema.py`**: 加 `class TestSandboxConfig` ≥ 12 测试（与 5.A 现有 TestManifest 并列）:
       - `test_default_values`: SandboxConfig() 全字段默认值断言（cpu="2.0", memory="1Gi", network=[], timeout_invoke=30, timeout_idle=300, use_cgroups=False, env_allowlist=[]）
       - `test_memory_invalid_format_raises`: `SandboxConfig(memory="512MB")` raises ValidationError（K8s 必须用 Mi 不是 MB）
       - `test_memory_bytes_property`: `SandboxConfig(memory="512Mi").memory_bytes == 512 * 1024**2`
       - `test_cpu_limit_pattern_rejects_letters`: `SandboxConfig(cpu_limit="abc")` raises ValidationError
       - `test_cpu_limit_seconds_property`: `SandboxConfig(cpu_limit="1.5").cpu_limit_seconds == 5400`
       - `test_network_entry_invalid_format_raises`: `SandboxConfig(network=["http://example.com"])` raises (必须 host:port 不带 scheme)
       - `test_network_entry_must_have_port`: `SandboxConfig(network=["example.com"])` raises (缺 port)
       - `test_network_uppercase_host_raises`: `SandboxConfig(network=["Example.com:443"])` raises (regex 仅小写)
       - `test_timeout_invoke_must_be_positive`: `SandboxConfig(timeout_invoke=0)` raises (gt=0)
       - `test_timeout_invoke_max_3600`: `SandboxConfig(timeout_invoke=3601)` raises (le=3600)
       - `test_timeout_idle_max_86400`: `SandboxConfig(timeout_idle=86401)` raises (le=86400)
       - `test_extra_field_rejected`: `SandboxConfig(unknown_field="x")` raises（extra=forbid 5.A 决策不能倒退）
       - `test_huly_platform_yaml_parses_sandbox_section`: 用 `load_manifest("plugins/huly/platform.yaml")` 断言 sandbox 字段含 network=["huly.example.com:443"]
       - `test_env_allowlist_default_empty`: 默认空（strip all — Pitfall 8）

    4. **5.A regression check** — 运行 `pytest backend/tests/platforms/ -x -q` 必须 0 fail（5.A 162 测试）。

    避坑:
    - 不能改 5.A 现有测试断言（仅加新 `TestSandboxConfig` class）
    - `from pydantic import ValidationError` 别忘 import
    - 用 `pytest.raises(ValidationError)` 而非 `Exception`（Pydantic 错误更具体）

    commit message: `test(05b-01): add SandboxConfig + parser unit tests (≥ 24 cases)`
  </action>
  <verify>
    <automated>cd /Users/admin/ai/resume/interview/liuxin/agent-builder/backend && python -m pytest tests/platforms/sandbox/test_parser.py tests/platforms/test_manifest_schema.py -x -q 2>&1 | tail -20</automated>
  </verify>
  <done>
    parser 测试 ≥ 12 pass；test_manifest_schema TestSandboxConfig ≥ 12 pass；`pytest backend/tests/platforms/ -x` 0 fail（5.A 162 测试全绿）；huly platform.yaml 加 sandbox 段后 load_manifest 不报错。
  </done>
</task>

</tasks>

<verification>
**phase-local checks**:
- `pytest backend/tests/platforms/sandbox/ backend/tests/platforms/test_manifest_schema.py -v` 全绿（≥ 24 测试新增）
- `pytest backend/tests/platforms/ -x` 5.A 162 测试 0 regression
- `pytest backend/tests/platforms_integration/ -x` 5.A 5/5 acid test 0 regression（manifest 加 sandbox 段后 huly_plugin acid test 仍通过）

**Phase 4 regression**:
- `pytest backend/tests/notification/ -x` Phase 4 81 IM 测试 0 regression

**reading doc gate**:
- `git log --oneline -10 | head` 第一个 docs(05b-01) commit 必须早于任何 feat(05b-01) commit
</verification>

<success_criteria>
1. **schema 落地**: SandboxConfig 7 字段全部带 validator + 2 派生属性
2. **parser 独立**: sandbox/parser.py 不依赖 Pydantic（Wave 2/3 plans 可独立 import）
3. **默认值安全**: network=[] / env_allowlist=[] 默认禁所有（restrictive baseline）
4. **测试覆盖**: SandboxConfig validators ≥ 12 测；parser K8s 单位 ≥ 12 测
5. **5.A regression**: 162 platforms + 5/5 acid test + 81 IM 0 regression
6. **reading doc gate**: docs commit 早于 feat commit（CLAUDE.md §2.7）
</success_criteria>

<output>
After completion, create `.planning/phases/05b-plugin-sandbox/05b-01-SUMMARY.md` 含:
- Dify 借鉴点（reading doc 关键 takeaway 4-6 条）
- 7 字段 + 2 properties 设计取舍（cpu_limit "2.0" 默认 / restrictive network=[] / env_allowlist 默认 strip）
- 单元测试矩阵（parser 12 + manifest 12+）
- 与 Wave 2/3 plans 的接口契约（memory_bytes / cpu_limit_seconds / env_allowlist 哪些 plan 用）
</output>
</content>
</invoke>