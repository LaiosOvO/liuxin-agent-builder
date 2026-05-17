---
phase: 05b-plugin-sandbox
plan: 01
subsystem: infra
tags: [pydantic-v2, k8s-units, sandbox, manifest, validators, plugin-framework]

# Dependency graph
requires:
  - phase: 05a-platform-plugin-framework
    provides: SandboxConfig 3-field placeholder + PlatformManifest Pydantic v2 schema + extra=forbid 决策
provides:
  - SandboxConfig 7 字段 + 2 派生属性（memory_bytes / cpu_limit_seconds）
  - sandbox/ 子包 + parser 模块（parse_memory / parse_cpu_seconds, 0 Pydantic 依赖）
  - K8s 单位解析能力（SI K/M/G/T + binary Ki/Mi/Gi/Ti）
  - network host:port 白名单字段（默认 [] 禁所有出站）
  - env_allowlist 字段（默认 [] strip all，Pitfall 8 防 secret 泄漏）
  - timeout_invoke / timeout_idle / use_cgroups 三层超时 + cgroups opt-in 开关
affects:
  - 05b-02 PosixResourceSandbox（消费 memory_bytes / cpu_limit_seconds）
  - 05b-03 AllowlistTransport（消费 network 字段）
  - 05b-04 CgroupsV2Sandbox + Watchdog（消费 use_cgroups / timeout_* 字段）
  - 05b-05 集成测试 + Linux CI gate（消费整套 schema）

# Tech tracking
tech-stack:
  added: []  # 0 新依赖 — 仅用 Phase 5.A 已锁定 Pydantic v2 + stdlib re
  patterns:
    - "K8s 单位解析独立模块（不依赖 Pydantic）— Wave 2/3 共享"
    - "Pydantic v2 field_validator raise ValueError + from e 保留异常链"
    - "Field(default_factory=list) 避免 mutable 默认值共享"
    - "Field(gt=, le=) 整数范围约束（借鉴 Dify Storage.size 模式）"
    - "memory_bytes / cpu_limit_seconds 派生属性（K8s 字符串字段 + 派生 int property）"

key-files:
  created:
    - docs/reading-dify-05b-01-sandbox-config-2026-05-17.md
    - backend/app/agent_builder/platforms/sandbox/__init__.py
    - backend/app/agent_builder/platforms/sandbox/parser.py
    - backend/tests/platforms/sandbox/__init__.py
    - backend/tests/platforms/sandbox/test_parser.py
    - .planning/phases/05b-plugin-sandbox/deferred-items.md
  modified:
    - backend/app/agent_builder/platforms/manifest.py
    - backend/tests/platforms/test_manifest_schema.py
    - backend/tests/platforms/fixtures/manifest_valid.yaml
    - plugins/huly/platform.yaml

key-decisions:
  - "rename memory_limit → memory（K8s 风格 + Wave 2 runner 显式 import 新名）"
  - "cpu_limit 默认 '2.0'（与 RESEARCH 决策对齐，给 long-running plugin 余量）"
  - "network 默认 []（restrictive baseline — 禁所有出站，安全核心）"
  - "env_allowlist 默认 []（strip all — Pitfall 8 防 secret 泄漏）"
  - "parser.py 不依赖 Pydantic（保持轻量；Wave 2/3 可独立 import）"
  - "K8s 单位 regex 自写 10 行 vs humanfriendly 第三方（0 依赖优先 — CLAUDE.md 鼓励）"
  - "ConfigDict(extra='forbid') 与 5.A 决策保持一致（typo 立刻 raise）"

patterns-established:
  - "Pattern 1: K8s 单位解析独立模块 — Wave 2/3 plans 通过 `from .sandbox.parser import` 共享，避免重复实现"
  - "Pattern 2: schema 字符串字段 + property 派生 int — YAML 可读性 + 业务层用 int（vs Dify int-only 强迫用户手算）"
  - "Pattern 3: restrictive 默认 baseline — network=[] / env_allowlist=[] 默认禁所有，opt-in 放行（vs permissive 默认）"
  - "Pattern 4: Pydantic v2 validator 异常翻译 — `raise ValueError(str(e)) from e` 保留原始异常链"

requirements-completed: [PLUG-FW-13]

# Metrics
duration: 14min
completed: 2026-05-17
---

# Phase 5.B Plan 05b-01: SandboxConfig manifest schema 扩展 Summary

**SandboxConfig 从 3 字段 placeholder 扩展为 7 字段 + 2 派生属性的完整 schema，并建立 sandbox/ 子包（parser.py + __init__.py）作为 Wave 2/3 plans 的共享 K8s 单位解析 helper。**

## Performance

- **Duration:** 14 min
- **Started:** 2026-05-17T23:33:34+08:00 (plan ready)
- **Completed:** 2026-05-17T23:47:14+08:00
- **Tasks:** 3 (Task 0 reading doc + Task 1 schema + Task 2 tests)
- **Files modified:** 10 (4 new code + 2 new test + 2 modified yaml + 1 modified test + 1 deferred-items.md)
- **Commits:** 4 atomic (1 docs + 2 feat + 1 test)

## Accomplishments

- **Dify 阅读笔记**（174 行）覆盖 PluginDeclaration / PluginResourceRequirements 字段与 v2 validators 模式，明确 6 借鉴点 + 5 显式偏离
- **sandbox/parser.py** 提供 K8s 单位解析（SI + binary 8 单位 + 裸 bytes）+ CPU cores 派生（10 行 regex，0 第三方依赖）
- **SandboxConfig 扩展到 7 字段**：cpu_limit / memory (rename) / network / timeout_invoke / timeout_idle / use_cgroups / env_allowlist
- **2 派生属性** memory_bytes / cpu_limit_seconds（Wave 2 RLIMIT_AS / RLIMIT_CPU 用）
- **3 validators**: memory K8s 格式 / network host:port regex / cpu_limit pattern + timeout 范围（Field gt/le）
- **plugins/huly/platform.yaml** 加 sandbox 段演示新字段（含 env_allowlist=[HULY_ENDPOINT]）
- **49 测试 PASS**（21 parser + 14 TestSandboxConfig + 13 5.A baseline + 1 fixture update）
- **0 5.A regression**（193 platforms + 5/5 acid test 全绿）

## Task Commits

每 task 独立 atomic commit：

1. **Task 0: Dify reading doc** — `e5d06cd` (docs)
   - `docs(05b-01): add Dify sandbox config reading doc`
   - 174 行覆盖 PluginDeclaration / PluginResourceRequirements / validators 模式
   - **CLAUDE.md §2.7 硬性 gate 满足** — 此 commit 早于所有 feat(05b-01) commit

2. **Task 1a: parser 模块** — `0a33a08` (feat)
   - `feat(05b-01): add sandbox parser helper (parse_memory + parse_cpu_seconds)`
   - 119 行新代码（sandbox/__init__.py + parser.py）
   - 0 Pydantic 依赖，Wave 2/3 plans 共享

3. **Task 1b: SandboxConfig 扩展** — `1fc573d` (feat)
   - `feat(05b-01): extend SandboxConfig with validators + new fields (PLUG-FW-13)`
   - manifest.py + fixture + huly platform.yaml + 1 测试断言同步
   - rename `memory_limit` → `memory` 同步 4 文件

4. **Task 2: 单元测试** — `1c4d79e` (test)
   - `test(05b-01): add SandboxConfig + parser unit tests (≥ 24 cases)`
   - 21 parser + 14 TestSandboxConfig + 1 deferred-items.md
   - 305 行新增测试

## Files Created/Modified

### Created (6)
- `docs/reading-dify-05b-01-sandbox-config-2026-05-17.md` — Dify PluginDeclaration / 资源限制 设计模式借鉴笔记
- `backend/app/agent_builder/platforms/sandbox/__init__.py` — sandbox 子包入口（docstring 说明 Wave 2/3 子模块规划）
- `backend/app/agent_builder/platforms/sandbox/parser.py` — K8s 单位解析（parse_memory + parse_cpu_seconds，119 行）
- `backend/tests/platforms/sandbox/__init__.py` — pytest 子包标识符
- `backend/tests/platforms/sandbox/test_parser.py` — 21 测试（SI/binary 单位 + edge case + 负数）
- `.planning/phases/05b-plugin-sandbox/deferred-items.md` — pre-existing lark_oapi 模块缺失（out of scope）

### Modified (4)
- `backend/app/agent_builder/platforms/manifest.py` — SandboxConfig 3 字段 → 7 字段 + 2 派生属性 + 3 validators
- `backend/tests/platforms/test_manifest_schema.py` — 新增 `TestSandboxConfig` class (14 测试) + 同步 5.A test_valid_huly_manifest_parses 字段引用
- `backend/tests/platforms/fixtures/manifest_valid.yaml` — sandbox.memory_limit → memory rename（同步 schema 变更）
- `plugins/huly/platform.yaml` — sandbox 段加 4 新字段（timeout_invoke / timeout_idle / use_cgroups / env_allowlist=[HULY_ENDPOINT]）

## Decisions Made

### 字段命名与默认值

1. **rename `memory_limit` → `memory`**（**破坏性变更**）
   - 理由：K8s 风格统一（K8s API 用 `resources.memory`）；Wave 2 runner 显式 import `memory_bytes` property，namespacing 更清晰
   - 影响：5.A SandboxConfig 字段未被任何代码消费（仅 placeholder），rename 不破坏 acid test
   - 同步：fixture yaml + 1 测试断言一并改

2. **`cpu_limit` 默认 `"2.0"` 而非 `"1.0"`**（与 RESEARCH 决策对齐）
   - 理由：long-running plugin daemon 需 CPU 余量；RLIMIT_CPU 是累积秒数（2 core * 3600s = 7200s 给 daemon 累积 2 小时单核 CPU 时间）
   - 与 5.A placeholder `"1.0"` 偏离 — 因 5.A 字段未真消费

3. **`network` 默认 `[]` 禁所有出站**（restrictive baseline — 安全核心）
   - 理由：默认放行是安全 anti-pattern；plugin 作者必须显式声明 host:port，迫使做最小权限设计
   - 与 Dify 一致：Dify 也不预设网络白名单（v2 marketplace 才管）

4. **`env_allowlist` 默认 `[]` strip all**（Pitfall 8 防 secret 泄漏）
   - 理由：daemon 进程默认继承父进程全 env → SMTP_PASSWORD / HMAC_SECRET / OAUTH_CLIENT_SECRET 会泄漏
   - plugin 必须显式声明 allowlist（如 `[HULY_ENDPOINT]`）才传 env

### 实现取舍

5. **`parser.py` 不依赖 Pydantic**
   - 理由：Wave 2/3 plans 的 SandboxRunner / Watchdog 不 import Pydantic，但需 `parse_memory()`；保持纯函数 + 0 依赖让 helper 模块到处可用
   - manifest.py 才依赖 Pydantic（通过 import parser 函数到 validator 内）

6. **K8s 单位 regex 自写 10 行 vs `humanfriendly` 第三方**
   - 理由：CLAUDE.md 鼓励 0 依赖；humanfriendly 100k+ DL/月但 18MB（C 扩展）；自写 regex 行为完全可控
   - 同样的考虑放弃 `psutil`（资源限制场景 stdlib `resource` 已够）

7. **`ConfigDict(extra='forbid')` 保持 5.A 决策**
   - 理由：典型 typo 防护；plugin 作者拼错字段（如 `cpu_limt`）立刻 raise，而非静默被忽略
   - 与 Dify 偏离（Dify 默认 `extra=ignore`），是本项目显式选择

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] rename memory_limit → memory 同步 5.A test fixture + 1 测试断言**
- **Found during:** Task 1 (SandboxConfig 扩展)
- **Issue:** plan 说 "rename `memory_limit` → `memory`"，但 `backend/tests/platforms/fixtures/manifest_valid.yaml:49` 与 `test_manifest_schema.py:87` (`test_valid_huly_manifest_parses` 断言 `manifest.sandbox.memory_limit`) 都引用旧名 — rename 后会让 5.A 现有测试 fail
- **Fix:** 同步改 fixture yaml + 1 测试断言（仅字段名替换，断言语义不变）
- **Files modified:** `backend/tests/platforms/fixtures/manifest_valid.yaml`, `backend/tests/platforms/test_manifest_schema.py`
- **Verification:** `pytest tests/platforms/ -x --no-cov` 193 测试全 PASS（0 5.A regression）
- **Committed in:** `1fc573d` (Task 1b 合并 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking — rename 同步)
**Impact on plan:** 必要的同步修改 — plan rename 本身是显式 spec，但漏说要同步 fixture/test。无 scope creep。

## Dify 参考点

详见 `docs/reading-dify-05b-01-sandbox-config-2026-05-17.md`。

**6 借鉴点（应用于本 plan）**：
1. `@field_validator` 失败 `raise ValueError(...) from e` 模式（Dify `validate_minimum_dify_version` `api/core/plugin/entities/plugin.py:82-91`）→ 应用于 `memory_must_be_k8s_format` validator
2. `Field(ge=, le=)` 整数范围约束（Dify `Storage.size` 行 50）→ 应用于 `timeout_invoke: Field(gt=0, le=3600)` / `timeout_idle: Field(gt=0, le=86400)`
3. `Field(default_factory=list)` 避免 mutable 默认值共享（Dify `Plugins.tools` 行 72）→ 应用于 `network` / `env_allowlist`
4. Pydantic v2 + nested BaseModel 组织（Dify `PluginDeclaration.Plugins` / `.Meta`）→ 我们采用 module-level 类（外部 import 友好）
5. v1 简化原则：拒绝复杂解析时优先（Dify `memory: int` 不接受 K8s 字符串）→ 部分借鉴，但我们选 `memory: str` + property 派生 int（YAML 可读性优先）
6. `from e` 保留异常链 → 应用于 `memory_must_be_k8s_format` validator

**5 显式偏离**：
1. `extra="forbid"` 严格模式（Dify ignore）— typo 立刻 raise
2. K8s 字符串 + property 派生 int（Dify int-only）— YAML 可读性
3. Python 主进程 sandbox（Dify Go daemon）— 0 二进制依赖
4. application-level httpx 白名单（Dify network namespace）— Wave 2 实现
5. `env_allowlist` 字段（Dify 无）— Pitfall 8 P0 防 secret 泄漏

## Test Matrix

### Parser (21 测试)

| 类别 | 测试 | 断言 |
| ---- | ---- | ---- |
| SI 单位 | K/M/G/T × 4 | 乘子 1000^n |
| Binary 单位 | Ki/Mi/Gi/Ti × 4 | 乘子 1024^n |
| 裸 bytes | no-unit | `parse_memory("1024") == 1024` |
| 小数值 | `1.5Gi` | `int(1.5 * 1024^3)` |
| 非法格式 | `512MB`/ `Mi`/空/`1e6` × 4 | raise ValueError "K8s 单位" |
| 负数 | `-1Gi` | raise ValueError |
| CPU integer | `1`/`2`/`2.0` × 3 | 3600 / 7200 / 7200 |
| CPU decimal | `0.5` | 1800 |
| CPU 非法 | `abc` | raise ValueError "cpu_limit" |
| CPU 负数 | `-1.0` | raise ValueError "不能为负" |

### TestSandboxConfig (14 测试)

| 类别 | 测试 | 断言 |
| ---- | ---- | ---- |
| 默认值 | `test_default_values` | 7 字段 + 2 派生 |
| `extra=forbid` | `test_extra_field_rejected` | raise ValidationError |
| memory validator | `test_memory_invalid_format_raises` | `512MB` raise |
| memory_bytes | `test_memory_bytes_property` + `_default_bytes` | property 派生 |
| cpu_limit pattern | `test_cpu_limit_pattern_rejects_letters` | `abc` raise |
| cpu_limit_seconds | `test_cpu_limit_seconds_property` | `1.5` → 5400 |
| network validator | 缺 port / 含 scheme / 大写 / 合法 entry × 4 | 3 raise + 1 pass |
| timeout 范围 | `timeout_invoke=0` / `=3601` / `timeout_idle=86401` × 3 | gt=0/le=3600/le=86400 raise |
| huly load_manifest | `test_huly_platform_yaml_parses_sandbox_section` | 7 字段全断言 + 派生属性 |

## 与 Wave 2/3 plans 的接口契约

| Wave 2/3 plan | 消费接口 | 消费方式 |
| ---- | ---- | ---- |
| **05b-02 PosixResourceSandbox** | `SandboxConfig.memory_bytes` / `.cpu_limit_seconds` | `resource.setrlimit(RLIMIT_AS, (sandbox.memory_bytes, sandbox.memory_bytes))` |
| **05b-02 PosixResourceSandbox** | `SandboxConfig.env_allowlist` | `merged_env = {k: os.environ[k] for k in sandbox.env_allowlist if k in os.environ}` |
| **05b-03 AllowlistTransport** | `SandboxConfig.network` | `AllowlistTransport(allow_list=sandbox.network)` 构造时传入 |
| **05b-04 CgroupsV2Sandbox** | `SandboxConfig.use_cgroups` | `if sandbox.use_cgroups: cgroups_runner else: posix_runner` |
| **05b-04 Watchdog** | `SandboxConfig.timeout_invoke` / `.timeout_idle` | watchdog task 用 `timeout_idle` 扫 idle daemon |

**契约稳定性保证**：本 plan 完成后 SandboxConfig 不再修改字段；Wave 2/3 plans 完全 freeze 此 schema。

## Issues Encountered

- **lark_oapi 模块缺失** — Phase 4 IM 测试 collection failure。**Pre-existing dev env issue**（5.A 完成时即存在，与 Plan 05b-01 无关）。已记入 `.planning/phases/05b-plugin-sandbox/deferred-items.md` deferred 段，不阻塞本 plan（platforms + acid test 全绿）。

## User Setup Required

None — schema 扩展纯代码改动，无外部服务配置。

## Next Phase Readiness

- ✅ **Wave 2 plans 可启动**：05b-02 (PosixResourceSandbox) + 05b-03 (AllowlistTransport) 接口契约确定
- ✅ **Wave 3 plans 可启动**：05b-04 (CgroupsV2Sandbox + Watchdog) 字段 `use_cgroups` / `timeout_*` 已就位
- ✅ **5.A 零 regression**：193 platforms + 5/5 acid test 全绿
- ✅ **CLAUDE.md §2.7 满足**：reading doc commit 早于 feat commit
- 🚦 **Wave 2 plans 独立性**：02 与 03 无相互依赖（PosixResourceSandbox 不依赖 AllowlistTransport），可**并行 dispatch**（CLAUDE.md §2.1）

---
*Phase: 05b-plugin-sandbox*
*Completed: 2026-05-17*

## Self-Check: PASSED

**验证清单**:
- [x] `docs/reading-dify-05b-01-sandbox-config-2026-05-17.md` 存在（174 行 ≥ 80）
- [x] `backend/app/agent_builder/platforms/sandbox/__init__.py` 存在
- [x] `backend/app/agent_builder/platforms/sandbox/parser.py` 存在（含 `def parse_memory` + `def parse_cpu_seconds`）
- [x] `backend/app/agent_builder/platforms/manifest.py` 含 `class SandboxConfig` 7 字段 + 2 properties
- [x] `backend/tests/platforms/sandbox/__init__.py` + `test_parser.py` 存在（21 测试 PASS）
- [x] `backend/tests/platforms/test_manifest_schema.py` 含 `TestSandboxConfig` class（14 测试 PASS）
- [x] `plugins/huly/platform.yaml` 含 `sandbox:` 段 + 7 字段
- [x] commit `e5d06cd` (docs) 存在且早于 `0a33a08` / `1fc573d` / `1c4d79e` (feat/test)
- [x] `pytest tests/platforms/ -x --no-cov` 193 PASS（5.A 0 regression）
- [x] `pytest tests/platforms_integration/ -x --no-cov` 5 PASS（acid test 0 regression）
- [x] `pytest tests/platforms/sandbox/ tests/platforms/test_manifest_schema.py -v --no-cov` 49 PASS（新增测试 100% PASS）
