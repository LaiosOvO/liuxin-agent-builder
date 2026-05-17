# Deferred Items — Phase 5.A 已发现非本 plan 范畴问题

## 2026-05-17 Plan 03 发现

- `test_feishu_provider.py` collect 阶段 `ModuleNotFoundError: No module named 'lark_oapi'`
  - **来源**：pyproject.toml 含 `lark-oapi==1.6.5` 但当前 venv 未安装
  - **影响**：仅本机环境，不影响 Plan 03 capability 实现
  - **建议**：CI 环境装 `pip install lark-oapi==1.6.5` 即可恢复
  - **scope_boundary 判定**：Plan 03 仅新增 capabilities/ 文件，未触碰 feishu provider；out-of-scope
