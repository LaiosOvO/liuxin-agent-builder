# Phase 5.B Deferred Items

Issues discovered during execution but **out of scope** for current plan; track here for later phases.

## Plan 05b-01

### 1. lark_oapi 模块缺失（Pre-existing dev env issue）

- **Discovery context**: 运行 `pytest backend/tests/test_feishu_provider.py` 等 Phase 4 IM 测试时 collection failure
- **Error**: `ModuleNotFoundError: No module named 'lark_oapi'`
- **Status**: **Out of scope** — Plan 05b-01 仅修改 manifest.py / sandbox/ / huly platform.yaml，没碰 IM 模块
- **Pre-existing**: 该错误在 5.A 完成时即已存在（lark-oapi==1.6.5 列在 pyproject.toml 但当前 dev env 未安装）
- **Resolution path**: 单独运行 `cd backend && pip install lark-oapi==1.6.5` 或在 CI Docker 镜像中验证
- **Not blocking**: Plan 05b-01 PLATFORMS 测试 193 + ACID 5 全绿，与 IM 模块无依赖关系
