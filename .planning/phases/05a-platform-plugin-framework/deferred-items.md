# Deferred Items — Phase 5.A 已发现非本 plan 范畴问题

## 2026-05-17 Plan 03 发现

- `test_feishu_provider.py` collect 阶段 `ModuleNotFoundError: No module named 'lark_oapi'`
  - **来源**：pyproject.toml 含 `lark-oapi==1.6.5` 但当前 venv 未安装
  - **影响**：仅本机环境，不影响 Plan 03 capability 实现
  - **建议**：CI 环境装 `pip install lark-oapi==1.6.5` 即可恢复
  - **scope_boundary 判定**：Plan 03 仅新增 capabilities/ 文件，未触碰 feishu provider；out-of-scope

## 2026-05-17 Plan 06 发现

- `test_plugin_facades.py::test_facade_methods_raise_not_implemented` 失败：
  - **来源**：Plan 05 在 `capability_facades.py` 引入 `PluginError("daemon not attached")` —— Plan 04 旧测试期望 `NotImplementedError`，但 Plan 05 facade 行为改为 daemon 未注入时 raise `PluginError`
  - **影响**：仅 Plan 04 旧测试不兼容 Plan 05 新行为；Plan 06 无相关改动
  - **建议**：Plan 05 或后续 plan 同步更新 `test_facade_methods_raise_not_implemented` 改 `expect PluginError`
  - **scope_boundary 判定**：Plan 06 仅新增 `legacy_im_adapter.py` + `base.py` `_PROVIDERS_AS_CAP` + `registry.py` fallback，未触碰 `capability_facades.py`；out-of-scope
  - **验证**：`git stash` 我的 Plan 06 改动后该测试仍失败 → 确认 Plan 05 遗留
