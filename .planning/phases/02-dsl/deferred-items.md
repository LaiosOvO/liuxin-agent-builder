# Deferred Items — Phase 02-dsl

## Pre-existing Flock TypeScript Errors (out of scope)

**发现于：** Plan 02-03 Task 3 构建验证

### 1. Members/index.tsx 类型错误
- **文件：** `web/src/components/Members/index.tsx:539`
- **错误：** `UploadOptions` 类型不匹配（flock 原有文件，非 02-03 改动引入）
- **状态：** 不修复（fork discipline — 不改 flock 上游文件）
- **影响：** `npm run build` 失败，但 `build:no-check` 通过，新增页面编译正常

