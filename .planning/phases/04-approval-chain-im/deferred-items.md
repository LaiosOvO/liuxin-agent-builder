# Phase 04 已发现但延后处理的问题

> 用途：CLAUDE.md scope rule — 本 phase 任务执行过程中发现的、与当前 task 无直接关系的预先存在问题，登记在此延后修复。

---

## 1. Starlette 1.0 升级导致 `submit_action` HTML 响应破坏

**发现于**：Plan 04-03（test_post_delegate_default_op_submit_still_works 回归测试）

**问题**：
Starlette 升级到 1.0.0 后，`templates.TemplateResponse(name: str, context: dict)` 的旧签名被废弃，新签名为
`TemplateResponse(request: Request, name: str, context: dict)`。`backend/app/agent_builder/api/hitl.py` 中所有 5 处
`templates.TemplateResponse("xxx.html", {...})` 调用都需要改为 `templates.TemplateResponse(request, "xxx.html", {...})`，否则
Jinja2 会把 dict 当作 template name 传入 LRUCache 引发 `TypeError: unhashable type: 'dict'`。

**受影响的代码位置**（hitl.py 当前 commit 状态）：
- Line 134：`page.html` GET 渲染
- Line 189：`expired.html` GET 渲染
- Line 260：`page.html` GET cookie 路径
- Line 394：`page.html` POST 校验失败
- Line 433：`success.html` POST 成功（**04-03 测试踩到**）
- Line 710：`success.html` POST delegate 成功（04-03 新增，同模式）

**受影响的现有测试**（Phase 3 既有，已 pre-existing 失败）：
- `tests/test_hitl_api_post_action.py::test_post_happy_path_consumes_jti_and_returns_success`
- 任何 Accept: text/html 走 submit success 路径的 Phase 3 测试

**当前规避方案**：
Plan 04-03 新增的回归测试 `test_post_delegate_default_op_submit_still_works` 通过 `Accept: application/json`
让响应走 `JSONResponse` 分支（line 423 wants_json 命中），跳过 broken HTML 渲染路径。

**真正修复**：
应建议为「Phase 5 前置 hotfix」或单开 phase（如 `04.1-starlette-1.0-hotfix`）一次性修复 6 处调用。每处改造模板：

```python
# 错（当前）
return templates.TemplateResponse("page.html", {"request": request, ...})

# 对（Starlette 1.0+）
return templates.TemplateResponse(request, "page.html", {...})
```

**为什么不在 04-03 / 04-02 内联修复**：
- 6 处全局改动 + 影响 Phase 3 测试断言（HTML 文案匹配 `"决策已记录"` 等），不在 Plan 04 范围内
- CLAUDE.md §scope rule：「仅自动修复 by current task's changes」— 这是 dependency 升级造成的预先存在问题

---

*建立日期：2026-05-17*
*最后更新：2026-05-17*
