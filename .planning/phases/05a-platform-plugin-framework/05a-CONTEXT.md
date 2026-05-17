# Phase 5.A: PlatformPlugin 框架（Dify-style） - Context

**Gathered:** 2026-05-17
**Status:** Ready for planning
**Authoritative spec:** `docs/plans/2026-05-17-platform-plugin-framework-ADR.md` (ADR-001)

<domain>
## Phase Boundary

实现 Dify-style 通用插件框架基础设施：

- 顶层抽象 `PlatformPlugin`
- 6 个 Capability Protocols（IM / Doc / HR / Identity / Trigger / Tool — 后两者 v1.1 留接口）
- `platform.yaml` manifest 解析与校验
- `PlatformPluginRegistry` discover / install / get_capability（per-workspace 隔离）
- `LegacyIMProviderAdapter` 让 Phase 4 6 家既有 IMProvider 通过新 IMCapability 接口被调用
- `MockPlatformPlugin` 用于测试
- **HulyPlugin stub acid test**（manifest + 4 facade + JSONRPC over stdio 至少 1 capability call 真实跑通）

**Phase 5.A 不做**（留 5.B/5.C/5.D/6）：
- Plugin 沙箱进程资源限制（5.B）
- DocCapability / HRCapability 真实平台接入（5.C / 5.D）
- 第三方 plugin marketplace 上传 / 安全审计（6）
- 画布节点配置 UI 自动渲染（5.A 仅 manifest config_schema 解析；前端 UI 5.C 起）

**Requirements**（待 plan-phase 细化）:
- PLUG-* 框架级（v1.1 新增）
- IM-* 部分子集（5.D 完成 user mapping 才 closes 全部）
</domain>

<decisions>
## Implementation Decisions

### Manifest 格式 + Plugin Discovery

**Manifest 格式**：YAML
- 人友好 + 注释友好 + Dify 同果 + kubeconfig 同思路
- 内部 Pydantic schema 严格校验（`extra=forbid`）

**Plugin 存储位置**：文件系统 `plugins/<plugin_name>/platform.yaml` + DB `workspace_plugin_installations` 表
- 文件系统持核心 plugins（与代码 git 同仓库，可审核）
- DB 表持 per-workspace 启用 / 禁用 / 凭据状态
- hybrid 模式与 Dify + Phase 6 marketplace 合成

**Discovery 时机**：启动期扫描 manifest（仅 metadata 入 PluginRegistry）+ 懒加载 daemon
- 启动期完成 manifest 校验 + Registry 注册（manifest 错误启动时阻断）
- 首次 `get_capability()` 才 spawn daemon 进程（性能 + 启动速度均衡）
- daemon spawn 后保活，进程级缓存

**Pydantic schema 严格度**：`extra=forbid`
- manifest 未声明字段 raise → 防 typo
- 防未来新增字段产生的隐式冲突
- 短期 plugin 开发者体验略差但长期更稳

### Capability Negotiation 策略

**Protocol 风格**：`runtime_checkable` Protocol（与 Phase 4 IMProvider 一致）
- 鸭子类型 + isinstance 双保险
- plugin 不需要继承 abstract class

**多 capability facade 注入**：lazy property + 共享底层 daemon client
- `HulyPlugin.im` / `.doc` / `.hr` / `.identity` 都返回 facade
- 4 facade 持同一个 `PlatformDaemonClient` 实例
- 一个 daemon 进程对应一个 plugin instance（共享底层 WS / HTTP connection pool）

**缺 capability 处理**：`registry.get_capability()` return None；调用方显式 if 检查
- registry 层 fail-quiet（不抛异常）
- 节点执行层调用方 `if cap is None: log + skip / fallback`
- 避免运行时 raise 中断 workflow

**版本兼容**：manifest 声明 `agent_builder_version: ">=1.0"` + 启动期 SemVer 校验
- plugin 跟核心版本不匹配时启动期阻断
- 后续 Capability Protocol 演进按 SemVer

### LegacyAdapter 平滑迁移 + 弃用窗口

**Phase 4 6 家 IMProvider 迁移**：永不强制
- 现有 `register_provider("feishu", FeishuProvider)` 注册时自动 wrap 为 `LegacyIMProviderAdapter`
- LegacyAdapter 实现 IMCapability Protocol，内部代理到旧 provider 方法
- Phase 4 既有测试 0 regression（验收硬性）

**新老 plugin 共存**：完全共存
- 同一 workspace 可同时有"老 register_provider 注册的 feishu"和"新 manifest 注册的 huly"
- capability_registry 按 `plugin_name` 路由
- workspace_settings.default_im_plugin 选默认

**Protocol 演进破坏性版本**：SemVer（major 破坏 / minor 兼容 / patch 修复）
- manifest 声明 `capability_versions: {im: "1.x"}` 告知期望兼容范围
- 框架升级 IMCapability major 时，旧 plugin manifest 校验失败 + 友好引导更新

**弃用机制**：
- `docs/deprecation_warnings.md` 维护时间线
- manifest 字段 `deprecated: true` + `deprecated_since: "1.2"` + `removal_target: "2.0"`
- v1 仅警告日志；实际 removal 留 v2

### HulyPlugin Acid Test 范围 + 验收硬性

**stub 深度**：最小 1 capability call 真实跑通
- HulyPlugin manifest + 4 facade（IM / Doc / HR / Identity）骨架
- 至少 1 个 IMCapability.send_card 端到端：主进程 → JSONRPC over stdio → daemon process → mock huly server → 返回 MessageRef
- 其他 3 capability 仅 facade 占位（NotImplementedError）— 真实接入留 Phase 5.C

**真实 Huly server vs mock**：mock huly server
- Python aiohttp 起本地 stub server 监听端口模拟 Huly chunter API
- 测试隔离 + 不需要真 Huly self-host
- 真实接入留 Phase 5.C

**测试层级**：
- 单测：mock JSONRPC client（不真 spawn daemon），验证 facade 调用 → JSONRPC 参数正确
- 集成测：真 spawn daemon 子进程 + mock huly server，至少 1 send_card 端到端

**验收硬性**（user 2026-05-17 明确要求 — 不再让"抽象只在纸面"发生）：
- [ ] HulyPlugin stub 真实运行：1 ainvoke 成功（端到端经过 JSONRPC stdio）
- [ ] Fault isolation 验证：daemon process 崩溃，主进程不受影响 + capability call 返回明确错误
- [ ] LegacyIMProviderAdapter 让 Phase 4 既有 6 家 provider 通过新接口被调用，所有 Phase 4 测试 0 regression
- [ ] 6 Capability Protocols 文件存在 + 单元测试覆盖 ≥ 80%
- [ ] PlatformPluginRegistry per-workspace 隔离测试通过（双 workspace 互不串扰）

### Claude's Discretion

- JSONRPC 实现：自写轻量 vs 用 `jsonrpc-2.0-py` 库（推荐用库）
- Manifest YAML 加载库：`PyYAML` vs `ruamel.yaml`（推荐 PyYAML — 已是 Phase 1 依赖）
- Capability Protocol 文件组织：单 file vs 每 capability 一 file（推荐每 capability 一 file，便于演进）
- Mock huly server 实现：用 Phase 1 已有的 aiohttp / httpx mock-server 模式
- structured log 字段命名 schema（沿用 Phase 4 `im.card.send` 模式）
- 文档：写 `docs/plugin-developer-guide.md` 给第三方 plugin 开发者参考

</decisions>

<specifics>
## Specific Ideas

- **Dify plugin entities 必读**：`/Users/admin/ai/ref/dify/repo/api/core/plugin/entities/{plugin,bundle,endpoint,plugin_daemon}.py`（manifest schema + daemon protocol 参考）
- **Dify plugin daemon**：`https://github.com/langgenius/dify-plugin-daemon`（独立仓库，Go 实现 — 借鉴 daemon 进程管理思路，本项目 Python）
- **Huly platform clone**：`/Users/admin/ai/ref/agent/huly`（chunter / document / hr plugin index.ts 已确认存在）
- **Phase 4 IMProvider Protocol**：`backend/app/agent_builder/notification/providers/base.py`（LegacyAdapter wrap 对象）
- **Acid test 报告**：`docs/plans/2026-05-17-huly-spike-abstraction-acid-test.md`（5 gap 对照表）
- 节点可视化 memory：daemon 调用必须 structured log（capability, method, latency, workspace_id）— Phase 7 Run Viewer 钩子

</specifics>

<deferred>
## Deferred Ideas

- **Plugin runtime 多语言支持**（Node.js / Go）→ v2（v1 Python only）
- **Plugin Marketplace UI**（上传 zip / 安装向导 / 评分）→ Phase 6
- **画布节点配置 UI 自动渲染**（manifest config_schema → React form）→ Phase 5.C 起
- **Plugin 跨 workspace 共享 daemon**（节约进程） → v1.5（v1 每 workspace 独立 daemon）
- **Plugin hot reload / SIGHUP**（manifest 改后不重启服务）→ v2
- **TriggerCapability + ToolCapability + WorkflowCapability 完整接口**（v1.1 留 Protocol 骨架；真实接入留 Phase 5.D+）
- **Plugin 跨平台 user mapping 反向 sync 全自动**（仅在 5.D 落地）

</deferred>

---

*Phase: 05a-platform-plugin-framework*
*Context gathered: 2026-05-17*
