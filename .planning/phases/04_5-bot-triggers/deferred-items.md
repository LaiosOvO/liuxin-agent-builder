# Phase 4.5 Deferred Items

## Pre-existing 环境问题（非本 phase 引入，已确认与 04_5-01 plan 无关）

### `lark_oapi` 模块缺失

- **发现于**: Plan 04_5-01 Task 3 regression check
- **症状**: `tests/test_feishu_provider.py` collection error
  ```
  ModuleNotFoundError: No module named 'lark_oapi'
  ```
- **影响范围**: 仅 `tests/test_feishu_provider.py` (collection 失败导致 5+ test 无法执行)
- **验证非本 phase 引入**: `git stash --include-untracked` 后症状仍现，确认 pre-existing
- **建议处理**: Wave 2-6 plan 中或 Phase 5.E 飞书 IM 入站时通过 `uv add lark-oapi==1.6.5` 修复
  （CLAUDE.md §3 已锁版本号）
- **当前状态**: 不阻塞 Wave 1（其他 154 个 Phase 4 IM 测试 + 271 个 Phase 5.A 测试全绿）
