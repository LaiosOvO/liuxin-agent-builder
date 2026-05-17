---
phase: 05a-platform-plugin-framework
plan: 04
subsystem: platforms/registry
tags: [platform, plugin, manifest, pydantic-v2, registry, per-workspace-isolation, lazy-facade, dify-reference]
provides:
  - PlatformManifest Pydantic v2 schema（extra=forbid + 3 嵌套子类型 RuntimeConfig/CapabilitySpec/SandboxConfig）
  - load_manifest(path) 统一入口（yaml.safe_load + 异常翻译 ManifestValidationError）
  - PlatformPlugin 顶层类（lazy facade + daemon 注入预留点）
  - PlatformPluginRegistry per-workspace 隔离 + 启动期 discover + 懒加载缓存
  - capability_facades stub（IMFacade / DocFacade / HRFacade / IdentityFacade — Plan 05 替换为真 daemon 转发）
  - plugins/huly/platform.yaml fixture（Plan 07 acid test 入口）
requires:
  - phase: 05a-platform-plugin-framework Plan 01
    provides: workspace_plugin_installations 表（v1 Plan 04 暂不强制 DB 校验，Plan 05+ 接入）
  - phase: 05a-platform-plugin-framework Plan 02
    provides: IMCapability / DocCapability Protocol + RecipientSpec/MessageRef/DocRef 等值对象（_capability_type_to_name 映射用）
  - phase: 05a-platform-plugin-framework Plan 03
    provides: HRCapability / IdentityCapability / TriggerCapability / ToolCapability + 完整 capabilities/__init__.py 24 exports
affects:
  - 05a-05 (LegacyIMProviderAdapter — Plan 04 暂不影响；Plan 05 让 register_provider 自动 wrap 后接入 Registry)
  - 05a-06 (PlatformDaemonClient — capability_facades stub 方法待真接入 daemon.invoke 转发)
  - 05a-07 (HulyPlugin acid test — discover/get_plugin/get_capability 链路已就位，daemon entry plugins/huly/huly_plugin.py 待 Plan 07 实现)
  - Phase 5.B (Sandbox — SandboxConfig 解析已就位，5.B 落地 cgroups v2 + network whitelist 强制)
  - Phase 5.C (Doc/HR 真接入 — capability_facades 替换 stub 为真 platform 调用)
  - Phase 5.D (Trigger/Tool 真接入 + Huly user 反向 sync)
tech-stack:
  added: []  # 全用 Phase 1-4 已锁定 pydantic v2 / PyYAML / asyncio / typing
  patterns:
    - "Pydantic v2 ConfigDict(extra=forbid) 严格 schema —— 防 typo + 防隐式冲突（CONTEXT.md 强制决策）"
    - "Pydantic Field(pattern=...) 字段级正则校验（vs @field_validator 自定义函数）"
    - "yaml.safe_load 永不用 yaml.load（Pitfall 3 防注入）"
    - "嵌套 BaseModel 组织（RuntimeConfig / CapabilitySpec / SandboxConfig）— 借鉴 Dify"
    - "异常翻译模式：所有 yaml.YAMLError / Pydantic ValidationError → ManifestValidationError"
    - "classmethod-only Registry + 模块级 class var —— 进程级 singleton + 测试 clear() 隔离"
    - "(workspace_id, plugin_name) tuple key —— Pitfall 5 per-workspace 隔离防护"
    - "Lazy facade 模式：@property im/doc/hr/identity + _cap_cache 二次访问返回 cache"
    - "TYPE_CHECKING import + from __future__ import annotations —— 引用尚未存在的 daemon_client 模块"
    - "Fail-quiet 路由：get_capability 缺 capability 返回 None（不 raise，调用方显式 if cap is None）"
key-files:
  created:
    - docs/reading-dify-05a-04-manifest-registry-2026-05-17.md  # 279 行
    - backend/app/agent_builder/platforms/manifest.py            # 218 行
    - backend/app/agent_builder/platforms/plugin.py              # 166 行
    - backend/app/agent_builder/platforms/registry.py            # 295 行
    - backend/app/agent_builder/platforms/capability_facades.py  # 192 行
    - backend/tests/platforms/test_manifest_schema.py            # 13 tests
    - backend/tests/platforms/test_registry.py                   # 13 tests
    - backend/tests/platforms/test_plugin_facades.py             # 10 tests
    - backend/tests/platforms/fixtures/manifest_valid.yaml
    - backend/tests/platforms/fixtures/manifest_invalid_extra_field.yaml
    - backend/tests/platforms/fixtures/manifest_no_capabilities.yaml
    - plugins/huly/platform.yaml                                  # Plan 07 acid test 入口
  modified: []
key-decisions:
  - "PlatformManifest 名 pattern ^[a-z][a-z0-9_-]{2,31}$ 比 Dify ^[a-z0-9_-]{1,128}$ 更严：首字符强制小写字母 + 长度 3-32（便于 daemon 进程名 / 文件路径生成）"
  - "version 三段 SemVer ^\\d+\\.\\d+\\.\\d+$ 简化 vs Dify packaging.Version 接受 dev/rc 后缀（v1 简化，v2 可放宽）"
  - "CapabilitySpec 聚合 6 cap flag 单 class —— vs Plan PLAN.md 推荐分散 IMCapabilitySpec/DocCapabilitySpec/...；聚合让 manifest YAML 结构平 + extra=forbid 仍生效防 typo（v2 字段多了可拆细）"
  - "v1 Plan 04 不强制 DB workspace_plugin_installations 表查询：get_plugin 直接从 _MANIFESTS dict 取（Plan 05+ install lifecycle 接入后再加 status='installed' 过滤）"
  - "discover() fail-fast：任一 manifest 校验失败 raise PluginError 阻断启动 —— Dify 同策略，防生产期半挂"
  - "duplicate plugin name 检测：两个目录都声明同 name → 第二个 raise（防 manifest 拷贝/分发场景的意外重名）"
  - "get_capability fail-quiet 返回 None：vs raise CapabilityMissingError —— CONTEXT.md 决策，让节点执行不中断（调用方显式 if cap is None: log + fallback）"
  - "_PLUGINS key = (workspace_id, plugin_name) tuple —— Pitfall 5 关键防护（vs 单 dict[plugin_name] 串户事故）"
  - "PlatformPlugin.attach_daemon 重复 attach raise RuntimeError —— 防 Plan 05+ 误用（每 plugin 1 daemon 严格 1:1）"
  - "capability_facades.py 选 (b) 创建 stub 而非 (a) 内部 import：让 IDE / mypy / 静态分析不报 ModuleNotFoundError；Plan 05 只改方法实现，不动签名/位置 → 0 接口破坏"
  - "subscribe_events / watch_user_changes stub 也用 `if False: yield {}` 模式 —— 保持 async generator function 标记，与 capabilities/im.py + identity.py 一致（Plan 02/03 已建 inspect.isasyncgenfunction 断言模式）"
patterns-established:
  - "Pattern: classmethod-only + 模块级 class var 实现进程级 singleton（测试用 clear() fixture 隔离）"
  - "Pattern: (workspace_id, plugin_name) tuple key —— per-tenant 资源隔离的通用 dict pattern"
  - "Pattern: Lazy facade + _cap_cache 缓存（首次访问实例化，二次返回 cache） —— 多 capability bundle plugin 的标准实现"
  - "Pattern: 异常翻译层（yaml.YAMLError / pydantic.ValidationError → 业务异常 ManifestValidationError），保 chain （raise X from e）"
  - "Pattern: fail-quiet 返回 None vs fail-fast raise —— 节点执行层 fail-quiet（不中断 workflow），启动期 fail-fast（防半挂）"
  - "Pattern: TYPE_CHECKING + from __future__ import annotations —— 引用尚未存在的下游模块（daemon_client Plan 06 创建）"
  - "Pattern: stub class 方法 raise NotImplementedError —— 为 Plan 05+ 演进留 0-cost placeholder"
requirements-completed:
  - PLUG-FW-02
  - PLUG-FW-03
metrics:
  duration: 15min
  tasks_completed: 3
  files_created: 12
  files_modified: 0
  tests_added: 36
  tests_passing: 36
  total_platforms_tests: 94
  phase4_im_regression: 0
  ruff_clean: true
  black_clean: true
  completed_date: "2026-05-17"
---

# Phase 5.A Plan 04: PlatformManifest + PluginRegistry + capability_facades stub Summary

**PlatformManifest Pydantic v2 schema（extra=forbid 严格 + 13 单测覆盖 8 失败场景）+ PlatformPluginRegistry per-workspace 隔离（Pitfall 5 防护测试明确通过）+ PlatformPlugin lazy facade（4 capability 共享 daemon）+ capability_facades stub（Plan 05 替换为真转发 0 接口破坏）+ plugins/huly/platform.yaml fixture（Plan 07 acid test 入口）— 完成 PLUG-FW-02 / PLUG-FW-03 双 requirement，36 新测试 0 regression，94/94 platforms tests + 51/51 Phase 4 IM 0 regression**

## Performance

- **Duration:** ~15 min（20:20 → 20:35 UTC+8）
- **Started:** 2026-05-17T12:20:33Z
- **Completed:** 2026-05-17T12:35:55Z
- **Tasks:** 3（Task 0 reading doc → Task 1 PlatformManifest → Task 2 Registry + Plugin + Facades stub）
- **Files created:** 12
- **Files modified:** 0
- **Tests added:** 36（13 manifest + 13 registry + 10 plugin_facades）
- **Tests passing:** 36/36（含 Plan 04 全部）+ 94/94 全 platforms（含 Plan 02/03 累积）+ 51/51 Phase 4 IM 0 regression
- **Lint:** ruff clean + black clean（含 fix UP037 quoted-annotation + I001 import-sort + black reformat）

## Accomplishments

- **PlatformManifest Pydantic v2 schema** —— 顶层 + 3 嵌套子类型（RuntimeConfig / CapabilitySpec / SandboxConfig）全 extra=forbid；name 严格小写蛇形 / version 三段 SemVer / capabilities Literal 多选；JSON Schema dict 透传
- **load_manifest(path)** 统一入口 —— yaml.safe_load（Pitfall 3 防注入）+ 异常统一翻译 ManifestValidationError + 顶层非 mapping 检测
- **PlatformPlugin 顶层类** —— lazy facade 4 capability（im/doc/hr/identity）+ daemon 注入预留点 attach_daemon + 重复 attach 防护 + 4 facade 共享同一 _daemon
- **PlatformPluginRegistry** —— 进程级 singleton（classmethod-only + 模块级 class var）+ discover() 启动期扫描 + get_plugin per-workspace 懒加载缓存 + get_capability 按类型路由 fail-quiet
- **capability_facades stub** —— IMFacade / DocFacade / HRFacade / IdentityFacade 4 stub class 共享 _BaseFacade(daemon, manifest)；所有方法 raise NotImplementedError；subscribe_events/watch_user_changes 保 async generator 标记（与 Plan 02/03 inspect.isasyncgenfunction 断言一致）
- **plugins/huly/platform.yaml** —— Plan 07 acid test 入口（4 capability + sandbox + JSON Schema config）
- **Pitfall 5 per-workspace 隔离防护测试明确通过** —— `test_two_workspaces_isolated`：双 workspace 调同 plugin_name 拿不同 PlatformPlugin instance（plugin_a is not plugin_b）
- **36 单测 0 regression** —— Plan 04 36 + Plan 02-03 累积 58 = 94 全 pass；Phase 4 IM 51 测试 0 regression

## Task Commits

每个 task 原子 commit（按 plan 规范）：

1. **Task 0: Dify Manifest + PluginService + Permission 阅读笔记（硬性 gate）** — `41af227` (docs)
   - 279 行（≥ 60 PLAN.md 硬性 gate）+ 11 处 License/AGPL 标注
   - 6 借鉴点（≥ 5 PLAN.md 要求）：PluginDeclaration Pydantic v2 + PluginCategory StrEnum vs Literal / PluginInstallation tenant scoping / PluginService static method / plugin_permission_service ACL / 启动期 vs 懒加载分离
   - 详细映射表：6 借鉴点 → Plan 04 落地 module 路径

2. **Task 1: PlatformManifest Pydantic v2 schema + load_manifest + 3 fixture YAML + 13 单测（PLUG-FW-02）** — `a8c8d24` (feat)
   - manifest.py 218 行（≥ 120 PLAN.md 要求）
   - 3 fixture YAML（manifest_valid / manifest_invalid_extra_field / manifest_no_capabilities）
   - 13 测试全 pass：valid_huly + extra_field + empty_capabilities + invalid_semver + invalid_name + runtime_type_python_only + capability_literal + yaml_not_a_mapping + file_not_found + invalid_yaml_syntax + returns_correct_subtypes + nested_extra_field + optional_fields_use_defaults

3. **Task 2: PlatformPlugin + PluginRegistry + capability_facades stub + 23 单测（PLUG-FW-03）** — `2658fe2` (feat)
   - plugin.py 166 行（≥ 80 PLAN.md 要求）
   - registry.py 295 行（≥ 150 PLAN.md 要求）
   - capability_facades.py 192 行（≥ 40 PLAN.md 要求）
   - plugins/huly/platform.yaml fixture（Plan 07 acid test 入口）
   - 23 测试全 pass（13 registry + 10 plugin_facades）
   - **核心**：`test_two_workspaces_isolated` 明确验证 Pitfall 5 per-workspace 隔离

**Plan metadata commit**（本 SUMMARY.md + STATE.md + ROADMAP.md 单独 commit，下一步执行）

## Files Created/Modified

### 新增（12 文件）

**Reading doc + 源码（5 文件）：**
- `docs/reading-dify-05a-04-manifest-registry-2026-05-17.md`（279 行）— Dify Manifest + PluginService + Permission 阅读 + 6 借鉴点 + License attribution
- `backend/app/agent_builder/platforms/manifest.py`（218 行）— PlatformManifest Pydantic v2 schema + 3 嵌套子类型 + load_manifest()
- `backend/app/agent_builder/platforms/plugin.py`（166 行）— PlatformPlugin 顶层类 + 4 lazy facade + daemon 注入预留点
- `backend/app/agent_builder/platforms/registry.py`（295 行）— PlatformPluginRegistry classmethod-only + discover/get_plugin/get_capability/clear
- `backend/app/agent_builder/platforms/capability_facades.py`（192 行）— 4 stub facade（IMFacade/DocFacade/HRFacade/IdentityFacade）共享 _BaseFacade

**测试 + fixtures（6 文件）：**
- `backend/tests/platforms/test_manifest_schema.py`（13 tests）— Pydantic schema 全面 cover
- `backend/tests/platforms/test_registry.py`（13 tests）— discover/per-workspace 隔离/get_capability 路由
- `backend/tests/platforms/test_plugin_facades.py`（10 tests）— Plugin lazy facade + stub 行为 + async generator 标记
- `backend/tests/platforms/fixtures/manifest_valid.yaml` — huly 风格完整 manifest
- `backend/tests/platforms/fixtures/manifest_invalid_extra_field.yaml` — 触发 extra=forbid
- `backend/tests/platforms/fixtures/manifest_no_capabilities.yaml` — 触发 at_least_one_capability validator

**Plan 07 acid test 入口（1 文件）：**
- `plugins/huly/platform.yaml` — Plan 07 discover 目标 manifest（plugins/huly/__init__.py + huly_plugin.py 留 Plan 07 创建）

### 修改（0 文件）

无 — 本 plan 仅新增文件，未修改既有 Phase 1-4 + Plan 02/03 代码。

## Decisions Made

详见 frontmatter `key-decisions`。核心 11 条决策：

1. **name pattern 比 Dify 更严**（`^[a-z][a-z0-9_-]{2,31}$` vs Dify `^[a-z0-9_-]{1,128}$`）：首字符强制小写字母 + 长度 3-32（便于 daemon 进程名 / 文件路径 / log subject）
2. **version 三段 SemVer 简化**（`^\\d+\\.\\d+\\.\\d+$` vs Dify `packaging.Version` 接受 dev/rc）：v1 不支持预发布版本（v2 可放宽）
3. **CapabilitySpec 聚合单 class** vs PLAN.md 推荐分散：6 cap flag 一 class，extra=forbid 仍生效防 typo，让 manifest YAML 结构平
4. **v1 Plan 04 不强制 DB 查询**：get_plugin 直接从 _MANIFESTS dict（Plan 05+ install lifecycle 接入后加 status='installed' 过滤）
5. **discover() fail-fast**：任一 manifest 校验失败 raise PluginError 阻断启动（Dify 同策略）
6. **duplicate name 检测**：第二个声明同 name 的 plugin raise（防意外重名场景）
7. **get_capability fail-quiet**：缺 capability 返回 None（CONTEXT.md 决策；调用方显式 fallback）
8. **(workspace_id, plugin_name) tuple key**：Pitfall 5 关键防护，vs 单 dict[plugin_name] 串户事故
9. **重复 attach_daemon raise RuntimeError**：每 plugin 1 daemon 严格 1:1
10. **capability_facades 选 (b) 创建 stub** vs (a) 内部 import：IDE/mypy 不报错；Plan 05 只改方法实现，不动签名/位置 → 0 接口破坏
11. **stub async generator 保 `if False: yield {}` 模式**：保持 inspect.isasyncgenfunction 标记（与 Plan 02/03 一致）

## Dify 参考点（详见 reading doc）

6 借鉴点对应 reading doc 章节锚点：

| # | Dify 源文件 | 借鉴模式 | 5.A Plan 04 落地 |
|---|---|---|---|
| 1 | `plugin.py:70-141` (PluginDeclaration) | Pydantic v2 BaseModel + Field validator + SemVer | `PlatformManifest` + `@field_validator at_least_one_capability` |
| 2 | `plugin.py:61-67` (PluginCategory StrEnum) | 单选 enum → 多选 Literal | `capabilities: list[Literal["im","doc","hr","identity","trigger","tool"]]` |
| 3 | `plugin.py:143-154` (PluginInstallation) | tenant_id × plugin_id 唯一约束 | `_PLUGINS: dict[(workspace_id, plugin_name), PlatformPlugin]` |
| 4 | `plugin_service.py:45+` (PluginService static) | static method-only + tenant_id 第一参 | `PlatformPluginRegistry` classmethod-only |
| 5 | `plugin_permission_service.py:7-13` (get_permission) | per-tenant 显式 WHERE | `test_two_workspaces_isolated` Pitfall 5 防护 |
| 6 | `plugin.py + plugin_service.py` (启动期 vs 运行时) | discover 不 spawn / 懒加载 daemon | `discover()` 仅 load manifest / `get_plugin()` 懒实例化 |

**License attribution**：Dify AGPL-3.0 vs 本项目 Apache-2.0 — 仅借鉴设计模式 / 数据结构 / 边界考虑，**严禁拷源代码**。reading doc 明确标注每条借鉴点为独立创作。

## Huly Acid Test Gap → Plan 04 解决映射

Plan 04 是 Plan 07 acid test 的基础设施。本 plan 直接解决 / 准备的 gap：

| Gap 编号 | Gap 描述 | Plan 04 解决方式 |
| --- | --- | --- |
| **#4 (一体化平台共享 client)** | Phase 4 IMProvider 一 provider 一 capability —— Huly 需 IM+Doc+HR+Identity 4 capability 一 instance | `PlatformPlugin` 4 lazy facade 共享同一 `_daemon`（Plan 05 真接入后 1 进程 / 1 WS 池） |
| **预备：discover/get_plugin 链路** | Plan 07 acid test 必须能 discover plugins/huly/platform.yaml → get_plugin(ws, "huly") → plugin.im.send_card | 本 plan 完成 Registry + Plugin + Facade stub 全链路；plugins/huly/platform.yaml 已就位；待 Plan 05 接入 daemon 后 Plan 07 即可端到端跑 |

剩余 gap（#1 RecipientSpec 多态 / #2 DocCapability 双路径 / #3 HRCapability / #5 Identity 反向 sync / #b IM 3 cap flag）由 Plan 02/03 已解决；Plan 04 通过 capability_facades 4 stub 完整 plumbing 这 6 gap 的接入点。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_get_capability_im_returns_facade 测试 hr_cap_none 断言错误**

- **Found during:** Task 2 测试执行
- **Issue:** 初版测试断言 `hr_cap_none is None`（认为 huly fixture 不含 hr），但 fixture manifest_valid.yaml 实际声明 `capabilities: [im, doc, hr, identity]` 全 4 个
- **Fix:** 改断言为 `assert isinstance(hr_cap, HRFacade)`（与其他 3 capability 同模式）
- **Files modified:** backend/tests/platforms/test_registry.py
- **Verification:** test 通过；plan_all_4_facades_cached 测试也验证了 4 capability 全有
- **Committed in:** `2658fe2`（与 Task 2 一并）

**2. [Rule 1 - Bug] manifest.py docstring 含 `\d` 触发 Python 3.13 SyntaxWarning**

- **Found during:** Task 1 import 检测
- **Issue:** `version: 三段 SemVer ^\\d+\\.\\d+\\.\\d+$` 字面 backslash 在 docstring 内被 Python 解析为 invalid escape sequence
- **Fix:** 将 docstring 前缀 `"""` 改为 raw string `r"""` —— 整个 module docstring 不再处理 escape sequence
- **Files modified:** backend/app/agent_builder/platforms/manifest.py
- **Verification:** Python 3.13.5 import 无 warning
- **Committed in:** `a8c8d24`（与 Task 1 一并）

**3. [Rule 3 - Blocking] ruff UP037 / I001 + black 格式化**

- **Found during:** Task 2 lint check
- **Issue:** ruff 报 9 处 UP037 quoted-annotation（TYPE_CHECKING import 的引用不需要 quotes，因为已 `from __future__ import annotations`）+ 3 处 I001 unsorted-imports；black 7 文件需 reformat
- **Fix:** `ruff check --fix` 自动修复全部 12 处；`black` 自动 reformat 7 文件；re-run 测试全 pass
- **Files modified:** 7 个 Plan 04 文件（4 source + 3 test）
- **Verification:** ruff clean + black clean + 36 测试全 pass（含 black/ruff 自动修改后回归）
- **Committed in:** `2658fe2`（与 Task 2 一并）

---

**Total deviations:** 3 auto-fixed（2 bugs + 1 blocking lint），**0 architectural decisions ask**。所有问题均按 deviation Rule 1-3 处理，不引入 scope creep。

## Issues Encountered

**1. `lark_oapi` 模块缺失（pre-existing 环境问题）** — 同 Plan 02/03 状况

- 触发时机：跑 Phase 4 全 IM 测试套时 `test_feishu_provider.py ModuleNotFoundError`
- 来源：pyproject.toml 含 `lark-oapi==1.6.5` 但当前 venv 未安装
- 处理：跳过该测试文件；用 `test_im_provider_protocol.py + test_im_credentials_loader.py + test_dingtalk_provider.py` 51 测试做 regression 验证 100% pass
- scope_boundary 判定：Plan 04 仅新增 platforms/ 文件 + plugins/huly/ fixture，未触碰 feishu provider — out-of-scope
- 已记入 `.planning/phases/05a-platform-plugin-framework/deferred-items.md`（Plan 03 已 log，无需重复）

## User Setup Required

None — 本 plan 仅纯 Python typing.Protocol + Pydantic v2 + asyncio + classmethod，无外部服务依赖。

## Next Phase Readiness

### Plan 04 直接解锁

- **Plan 05 (LegacyIMProviderAdapter + PlatformDaemonClient + MockPlatformPlugin)**：
  - `capability_facades.py` 4 stub class 方法签名已就位 —— Plan 05 替换 `raise NotImplementedError` 为 `await self._daemon.invoke(...)` 真转发
  - `PlatformPlugin.attach_daemon(daemon)` 注入点已就位 —— Plan 05 创建 PlatformDaemonClient 后 `await PlatformPluginRegistry.get_plugin(ws, "huly")` 自动注入
  - LegacyIMProviderAdapter 实现 IMCapability 后可通过 Registry 路由（注册到 _MANIFESTS 或独立 _LEGACY_ADAPTERS dict）

- **Plan 06 (PlatformDaemonClient JSONRPC over stdio)**：
  - `daemon_client.py` 模块文件名 + class 名 PlatformDaemonClient 已在 TYPE_CHECKING import 预留（plugin.py / capability_facades.py）
  - `_BaseFacade._daemon` 字段类型为 `PlatformDaemonClient | None` —— Plan 06 直接实现该 class 即可注入

- **Plan 07 (HulyPlugin acid test)**：
  - `plugins/huly/platform.yaml` manifest 已就位（discover() 目标）
  - `plugins/huly/__init__.py + huly_plugin.py` 待 Plan 07 创建（daemon entrypoint）
  - 完整链路：discover → get_plugin(ws, "huly") → plugin.im.send_card → daemon stdin → daemon → mock huly server → stdout → MessageRef

### Phase 5.B / 5.C / 5.D （未来）

- Phase 5.B：`SandboxConfig` 解析已就位 → 5.B 落地 cgroups v2 + network whitelist 强制执行（subprocess spawn 前 apply）
- Phase 5.C：`config_schema` JSON Schema 字段透传已就位 → 5.C 前端自动渲染配置 UI
- Phase 5.D：Trigger / Tool capability facade 已就位（Plan 03 提供 Protocol + 本 plan 已可路由）→ 5.D 真接入

### 无 blocker

Plan 04 100% 完成 `PLUG-FW-02` + `PLUG-FW-03` 双 requirement。Phase 5.A 进度从 3/7 → 4/7（57%）。

---

## 测试结果

### Plan 04 直接覆盖（36 测试）

```
$ pytest tests/platforms/test_manifest_schema.py tests/platforms/test_registry.py tests/platforms/test_plugin_facades.py -v -o "addopts="
============================== 36 passed in 5.18s ==============================
```

### 全 platforms tests（Plan 02/03/04 累积 94 测试）

```
$ pytest tests/platforms/ -o "addopts=" --ignore=tests/platforms/test_migration_0006.py
============================== 94 passed in 3.65s ==============================
```

### Phase 4 IM Regression（51/51 pass）

```
$ pytest tests/test_im_provider_protocol.py tests/test_im_credentials_loader.py tests/test_dingtalk_provider.py -o "addopts="
============================== 51 passed in 3.73s ==============================
```

0 regression（feishu_provider 因 pre-existing lark_oapi env 缺失跳过，详 deferred-items.md）。

### Lint / Format（全 pass）

```
$ ruff check app/agent_builder/platforms/manifest.py ... tests/platforms/test_registry.py
All checks passed!

$ black --check app/agent_builder/platforms/ ... tests/platforms/...
All done! ✨ 🍰 ✨
7 files would be left unchanged.
```

---

## Self-Check: PASSED

**Files created exist (12):**

- ✓ docs/reading-dify-05a-04-manifest-registry-2026-05-17.md（279 行 ≥ 60）
- ✓ backend/app/agent_builder/platforms/manifest.py（218 行 ≥ 120）
- ✓ backend/app/agent_builder/platforms/plugin.py（166 行 ≥ 80）
- ✓ backend/app/agent_builder/platforms/registry.py（295 行 ≥ 150）
- ✓ backend/app/agent_builder/platforms/capability_facades.py（192 行 ≥ 40）
- ✓ backend/tests/platforms/test_manifest_schema.py（13 tests pass）
- ✓ backend/tests/platforms/test_registry.py（13 tests pass）
- ✓ backend/tests/platforms/test_plugin_facades.py（10 tests pass）
- ✓ backend/tests/platforms/fixtures/manifest_valid.yaml
- ✓ backend/tests/platforms/fixtures/manifest_invalid_extra_field.yaml
- ✓ backend/tests/platforms/fixtures/manifest_no_capabilities.yaml
- ✓ plugins/huly/platform.yaml（Plan 07 acid test 入口）

**Commits exist:**

- ✓ 41af227 (Task 0 reading doc) — CLAUDE.md §2.7 硬性 gate
- ✓ a8c8d24 (Task 1 PlatformManifest schema + 13 单测)
- ✓ 2658fe2 (Task 2 Registry + Plugin + Facades stub + 23 单测)

**Tests pass:**

- ✓ 13/13 manifest_schema tests
- ✓ 13/13 registry tests（含 `test_two_workspaces_isolated` Pitfall 5 关键防护）
- ✓ 10/10 plugin_facades tests（含 `test_facade_async_generator_is_marked` High 5 静态断言）
- ✓ 36/36 Plan 04 全 pass
- ✓ 94/94 全 platforms tests pass（Plan 02+03+04 累积）
- ✓ 51/51 Phase 4 IM 测试 0 regression

**Reading doc gate:**

- ✓ Reading doc commit 41af227 早于代码 commit a8c8d24 / 2658fe2 ✓
- ✓ License attribution（Dify AGPL-3.0 vs 本项目 Apache-2.0）✓
- ✓ 6 借鉴点（≥ 5 PLAN.md 要求）✓ — PluginDeclaration / PluginCategory / PluginInstallation / PluginService static / per-tenant ACL / 启动期-懒加载分离
- ✓ 279 行（≥ 60 PLAN.md 要求）✓

**Plan 04 acceptance:**

- ✓ PlatformManifest Pydantic v2 schema 可 import + 校验完整（13 测试 cover 8 失败场景 + 5 正常场景）
- ✓ extra=forbid 严格模式生效（顶层 + 3 嵌套子类型）
- ✓ load_manifest yaml.safe_load + 异常翻译 ManifestValidationError（统一入口）
- ✓ PlatformPlugin 4 lazy facade（共享 _daemon）+ attach_daemon 注入预留 + 重复 attach 防护
- ✓ PlatformPluginRegistry classmethod-only + 进程级 singleton（_MANIFESTS / _PLUGINS class var）
- ✓ discover() fail-fast + duplicate name 检测 + 无 platform.yaml 子目录静默跳过
- ✓ get_plugin per-workspace 懒加载缓存（(workspace_id, plugin_name) tuple key）
- ✓ get_capability 按类型路由 fail-quiet（缺 capability 返回 None）+ prefer 参数优先
- ✓ capability_facades 4 stub class（IMFacade/DocFacade/HRFacade/IdentityFacade）共享 _BaseFacade(daemon, manifest)
- ✓ subscribe_events / watch_user_changes 保 async generator function 标记
- ✓ plugins/huly/platform.yaml fixture 就位（Plan 07 acid test 入口）

**Requirements covered:**

- ✓ PLUG-FW-02（platform.yaml manifest Pydantic schema extra=forbid + YAML 解析 + 校验）
- ✓ PLUG-FW-03（PlatformPluginRegistry 启动期 discover + 懒加载 daemon + per-workspace 隔离）

**Pitfall 5 关键防护（CONTEXT.md acid test DoD #5）：**

- ✓ test_two_workspaces_isolated 明确断言：`plugin_a is not plugin_b`（双 workspace 不同 instance）+ `plugin_a.manifest is plugin_b.manifest`（manifest 是只读共享 OK）

---

*Phase: 05a-platform-plugin-framework*
*Plan: 04*
*Completed: 2026-05-17*
