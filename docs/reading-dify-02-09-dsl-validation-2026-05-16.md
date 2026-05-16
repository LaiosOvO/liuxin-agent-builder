# Dify 阅读笔记 — DSL 校验 + Issue UI

> 日期: 2026-05-16
> 仓库: https://github.com/langgenius/dify (commit e7e6fe88, local clone /Users/admin/ai/ref/dify/repo/)
> Stars: ~141k

## 项目概述（一句话）

Dify 的 DSL 校验体系分两层：前端 `use-checklist.ts` hook 提供实时 Issue 清单（基于节点可用变量 + 节点自带 `checkValid` 函数），后端 `workflow_service.py` 在发布前做最终权威校验。

## 技术栈（关键技术选择）

- 前端校验：React hooks + useMemo 缓存校验结果，不依赖后端网络请求
- 节点级校验注册：每个节点 type 在 `nodesExtraData[type].checkValid` 注册一个同步校验函数，由 `use-checklist` 统一调用
- 变量引用校验：`useNodesAvailableVarList(nodes)` 构造 map（nodeId → availableVars），遍历每个节点的 `usedVars`，检查是否存在于上游 availableVars
- Issue UI：`ChecklistItem[]` 聚合所有错误，底部 panel 展示；节点上渲染状态边框（`getNodeStatusBorders`）
- 发布前权威检查：`useChecklistBeforePublish()` hook 里异步串行逐节点检查，遇到错误立即 `toast.error + return false`

## 架构要点（核心架构模式）

```
画布变更
  ↓
useChecklist(nodes, edges) — useMemo 实时重算
  ↓ 遍历每个节点
  ├── 调 nodesExtraData[type].checkValid(data, t) → errorMessage?
  ├── 检查变量引用 usedVars ⊆ availableVars（by useNodesAvailableVarList）
  └── 检查连通性 validNodes（by getValidTreeNodes）
  ↓
workflowStore.setState({ checklistItems })  // 全局存储结果
  ↓
底部 ChecklistPanel 渲染 ChecklistItem[]（点击 → navigate to node）

节点边框状态：
  getNodeStatusBorders(runningStatus, hasVarValue, showSelectedBorder)
  → border-state-success-solid / border-state-destructive-solid / border-state-warning-solid
```

关键文件路径：
- `web/app/components/workflow/hooks/use-checklist.ts` — 核心实时校验 hook（580 行）
- `web/app/components/workflow/nodes/_base/node.helpers.tsx` — `getNodeStatusBorders` 边框状态函数
- `web/app/components/workflow/nodes/_base/node.tsx` — 节点 JSX 消费 `getNodeStatusBorders` + 渲染 error 指示
- `web/app/components/workflow/nodes/_base/components/variable/utils.ts` — `getNodeUsedVars()` 提取节点模板变量引用

## 可借鉴的设计模式

### 1. ChecklistItem 数据结构
文件：`web/app/components/workflow/hooks/use-checklist.ts:74-85`
```typescript
type ChecklistItem = {
  id: string;           // 节点 ID
  type: BlockEnum;      // 节点类型（用于显示图标）
  title: string;        // 节点标题
  errorMessages: string[];  // 可能多个错误
  canNavigate: boolean;     // 是否可跳转节点
  unConnected?: boolean;    // 是否未连线
}
```
借鉴点：错误以 `errorMessages: string[]` 数组存储，一个节点可有多条错误，Issue 清单显示时展开；`canNavigate` 控制是否允许点击跳转（插件缺失时禁止跳转）。

### 2. 节点状态边框函数式映射
文件：`web/app/components/workflow/nodes/_base/node.helpers.tsx`
```typescript
const { showFailedBorder } = getNodeStatusBorders(runningStatus, hasVarValue, showSelectedBorder);
// JSX 中：
className={cn(
  showFailedBorder && 'border-state-destructive-solid!',
  showSuccessBorder && 'border-state-success-solid!',
)}
```
借鉴点：状态边框通过纯函数 `getNodeStatusBorders` 计算，避免复杂 if-else 嵌套；我们的实现同样用 `cn(hasError && "border-red-500")` 这种简洁模式。

### 3. 两阶段校验：实时 useMemo vs 发布前串行检查
- 实时：`useChecklist` 用 `useMemo` 缓存，节点/边变化时自动重算，**不发网络请求**
- 发布前：`useChecklistBeforePublish` 用 `useCallback` + async，遇错立即返回 false + toast

借鉴点：本项目同样实现两阶段——前端 300ms debounce（纯本地 TS validator）+ 发布前 POST /validate（后端权威复检）。

### 4. 变量符号表 + 上游检查
文件：`web/app/components/workflow/hooks/use-nodes-available-var-list.ts`
Dify 为每个节点构造 `availableVars`（拓扑序上游所有节点的输出变量），遍历当前节点引用的 `usedVars`，检查是否在 `availableVars` 中。

借鉴点：我们的 `variables.ts` 同样构造 `visited_nodes` 集合（拓扑序遍历），仅允许引用已访问节点，逻辑等价。

### 5. 节点级 checkValid 注册模式
每个节点 type 注册 `checkValid: (data, t, moreData?) => { errorMessage?: string }` 函数，由统一的 `useChecklist` 调用。
借鉴点：不需要中央校验器了解所有节点细节，节点自身定义校验规则；本项目用 zod schema + `configs.ts` 实现类似效果。

## 与本项目的关系（如何应用到当前 plan）

| Dify 模式 | 我们的实现 |
|-----------|-----------|
| `useChecklist` hook（useMemo 实时校验）| `useDebouncedValidator(300)` hook（useEffect + setTimeout 300ms）|
| `ChecklistItem[]` 数据结构 | `ValidationError[]`（severity/code/message/node_id/field_path）|
| `getNodeStatusBorders` 边框状态函数 | `hasError && "border-red-500"` 在节点 JSX 中直接 cn() 判断 |
| 底部 ChecklistPanel | `IssueList` 组件（聚合 + 点击跳转）|
| 节点点击弹出错误详情 | `ErrorPopover` 组件（Popover 显示该节点 errors + 修复建议）|
| `useChecklistBeforePublish` 发布前检查 | 发布按钮 disabled={hasFatalErrors} + POST /validate 后端复检 |
| `nodesExtraData[type].checkValid` 节点级注册 | zod schema 在 `node-schemas.ts` 注册，`configs.ts` 统一调用 |

**关键差异**：
- Dify 变量引用用 `[nodeId, fieldName]` ValueSelector 元组格式；我们用 Jinja2 `{{ node_id.field }}` 字符串格式，需要正则扫描提取
- Dify 校验与 reactflow store 深度耦合（`useStoreApi`）；我们通过 `useCanvasStore().exportDSL()` 解耦，校验器只接收纯 DSL 对象
- Dify 无后端 validate API（完全前端）；我们增加了后端 POST /validate 作为发布前权威复检（更严格）
