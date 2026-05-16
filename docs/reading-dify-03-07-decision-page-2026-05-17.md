# Dify 阅读笔记 — HITL 决策页前端（Plan 03-07）

> 日期: 2026-05-17
> 仓库: https://github.com/langgenius/dify
> Local clone: `/Users/admin/ai/ref/dify/repo/`
> Stars: ~141k
> Plan: 03-07 (Phase 3 Wave 5)

## 1. 项目概述（一句话）

Dify 是国内最成熟的开源 LLM 应用工作流平台，其 HITL（Human-in-the-Loop）模块提供"画布配置 → 邮件投递 → 用户决策"完整闭环。本笔记聚焦其**节点配置面板**（编辑期 UI）与 **HumanInput 表单模型**（运行时 payload），借鉴其 form schema 设计与"3 按钮 + reason"用户决策交互范式。

## 2. 技术栈

- **前端**：Next.js 14（App Router）+ React 19 + Lexical PromptEditor + Tailwind CSS + dify-ui 组件库
- **后端**：Flask + SQLAlchemy + AGPL 自管 form/delivery/recipient 三表
- **国际化**：react-i18next（多语言）
- **节点 schema**：`HumanInputNodeType` TypeScript 类型与 Python `HumanInputForm` 数据模型双向对齐

## 3. 架构要点

```
┌──────────────────────────────────────────────────────────┐
│  Dify 画布编辑期                                            │
│  ┌────────────┐  ┌────────────┐  ┌────────────────────┐  │
│  │ FormContent│→ │ UserAction │→ │ DeliveryMethods   │  │
│  │ Lexical    │  │ 多按钮      │  │ email/slack/...   │  │
│  │ Editor     │  │ ID+title    │  │ recipient        │  │
│  └────────────┘  └────────────┘  └────────────────────┘  │
└──────────────────────────────────────────────────────────┘
                  ↓ 保存为 HumanInputNodeType
┌──────────────────────────────────────────────────────────┐
│ Dify 运行时（执行人收件）                                     │
│  ┌────────────────────────────────────────┐               │
│  │ SingleRunForm（决策页内嵌组件）           │               │
│  │  - data.form_content 解析为 content list  │              │
│  │  - inputs map（form 字段值）              │              │
│  │  - data.actions 渲染按钮 + button_style  │              │
│  │  - onSubmit({inputs, action})           │              │
│  └────────────────────────────────────────┘               │
└──────────────────────────────────────────────────────────┘
```

我们 Phase 3 简化版（Plan 03-07）：

```
┌──────────────────────────────────────────────────────────┐
│  Next.js 16.2 公网决策页 `/hitl/[token]`                    │
│  ┌──────────────────────────────────────────────────┐    │
│  │ Server Component (page.tsx)                       │    │
│  │  fetch GET /hitl/page/<token>                     │    │
│  │  Accept: application/json + cookie forwarding      │    │
│  │  → HitlPageData OR BotScanResponse                │    │
│  └──────────────────────────────────────────────────┘    │
│                       ↓ hydrate                            │
│  ┌──────────────────────────────────────────────────┐    │
│  │ Client Components                                  │    │
│  │  - DecisionForm（RJSF 渲染 form_schema + 3 button）│    │
│  │  - RecordsTimeline                                 │    │
│  │  - DeadlineCountdown（setInterval 1s）             │    │
│  │  - BotScanPage（bot UA 短路）                      │    │
│  └──────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

## 4. 可借鉴的设计模式

### 4.1 用户决策按钮（3 按钮 + ID/title 分离）

**Dify 源**：`web/app/components/workflow/nodes/human-input/components/single-run-form.tsx:74-85`

```tsx
{data.actions.map((action: UserAction) => (
  <Button
    key={action.id}
    disabled={isSubmitting}
    variant={getButtonStyle(action.button_style) as ButtonProps['variant']}
    onClick={() => submit(action.id)}
  >
    {action.title}
  </Button>
))}
```

**借鉴点**：
- `action.id`（机器读，提交时传后端） vs `action.title`（人读，按钮文字）—— 解耦显示与语义
- `disabled={isSubmitting}` —— 防双提交（Pitfall 2 应用层第一道防护）
- `getButtonStyle(action.button_style)` —— 按钮变体映射器（primary/default/accent/ghost）

**本项目落点**：`web/src/components/hitl/decision-form.tsx`
- 按 `phase` 决定 3 按钮组合（submit/return/reject 或 approve/return/reject）
- `submitting` 状态控制 disable —— Pitfall 2 应用层防护
- Tailwind 颜色：绿（submit/approve）/ 黄（return）/ 红（reject）

### 4.2 表单状态管理（useState + onChange）

**Dify 源**：`single-run-form.tsx:32-40`

```tsx
const [inputs, setInputs] = useState(defaultInputs)
const [isSubmitting, setIsSubmitting] = useState(false)

const handleInputsChange = (name, value) => {
  setInputs(prev => ({ ...prev, [name]: value }))
}
```

**借鉴点**：
- 受控组件 + 单 source of truth（`inputs` map）
- 函数式 setState（`prev => {...prev, ...}`）—— 防 stale closure

**本项目落点**：`decision-form.tsx`
- `formData` useState（RJSF 接管 onChange）
- `reason` 独立 useState（不进 form_schema）
- `submitting` useState（控制 disable）
- `error` useState（422 inline 显示）

### 4.3 按钮样式枚举

**Dify 源**：`web/app/components/workflow/nodes/human-input/types.ts:50-56`

```typescript
export enum UserActionButtonType {
  Primary = 'primary',
  Default = 'default',
  Accent = 'accent',
  Ghost = 'ghost',
}
```

**借鉴点**：枚举映射颜色，可换肤 / 主题。

**本项目反向取舍**：v1 直接写 Tailwind class（`bg-emerald-600 hover:bg-emerald-700`）— RJSF widget 完全可控，无需自管按钮组件库。

### 4.4 表单字段类型与 form_schema 渲染

**Dify 后端**：`api/core/workflow/human_input_forms.py:38-58`
- `HumanInputFormRecipient` 三表关联模式（Form / Delivery / Recipient）—— 我们不采用（v1 单表 hitl_tokens）
- `HumanInputSurface.SERVICE_API` —— 不同入口的 form 配置返回不同 token —— 我们 v1 不区分

**Dify 前端**：`single-run-form.tsx:30-31`
```typescript
const defaultInputs = initializeInputs(data.inputs, data.resolved_default_values || {})
const contentList = splitByOutputVar(data.form_content)
```

**借鉴点**：
- 默认值初始化（`resolved_default_values` 注入）
- form_content 拆分为 content list（Dify 用 Lexical Editor 模板渲染）

**本项目反向取舍**：直接吃 JSON Schema → @rjsf/core 5.x 自动渲染，无需自定义 Editor。
- JSON Schema 子集（type/properties/required）覆盖 v1 字段类型：string/number/boolean/enum/textarea
- 默认值用 form_schema 的 `default` 字段（RJSF 原生支持）

### 4.5 super 反向取舍：Dify 没有公网决策页（必须登录）

Dify 的 SingleRunForm 是**画布预览**用的（编辑期模拟运行）；真实生产场景下用户必须登录到 Dify dashboard 才能决策。

**本项目独立创新**：
- **公网无登录决策页**（`/hitl/[token]`，nginx 已开放 NET-02）
- **Token-as-login**：HMAC session cookie 30min（Plan 03-06 已落）
- **Safe Links bot 静态短路页**（Pitfall 3 P0）

## 5. RJSF 5.x（react-jsonschema-form）借鉴

**官方文档**：https://rjsf-team.github.io/react-jsonschema-form/

### 5.1 核心 API

```tsx
import Form from '@rjsf/core';
import validator from '@rjsf/validator-ajv8';
import type { RJSFSchema } from '@rjsf/utils';

<Form
  schema={formSchema}
  validator={validator}
  formData={formData}
  onChange={(e) => setFormData(e.formData)}
  uiSchema={{ "ui:submitButtonOptions": { norender: true } }}
>
  <></>  {/* 关闭默认 submit 按钮 */}
</Form>
```

### 5.2 关键设计原则

- **schema = JSON Schema Draft-07**（与后端 jsonschema 4.x AJV-7 兼容）
- **uiSchema** 定制 UI 表现（widget 类型 / 排序 / 隐藏）
- **validator-ajv8** 用 AJV 8 做客户端校验（与后端独立但 schema 一致）
- **onChange** 受控更新 formData
- **norender submit** 让我们自己控制按钮 + 提交流程（必须）

### 5.3 v1 字段类型对照

| JSON Schema 类型 | RJSF 默认 widget | 我们的用法 |
|---|---|---|
| `string` | text input | 单行文本 |
| `string` + `format: textarea` | textarea | 多行文本 |
| `number` / `integer` | number input | 金额 / 数量 |
| `boolean` | checkbox | 二选一 |
| `string` + `enum: [...]` | select | 下拉选择 |
| `array` | repeating fields | v1 不用 |
| `object` | nested fieldset | v1 不用 |

## 6. 与本项目的关系

### 6.1 落点映射表

| 我们的需求 | Dify 模式 | 本项目实现 | 文件 |
|---|---|---|---|
| 3 按钮 + ID/title | UserAction + getButtonStyle | ACTIONS_BY_PHASE 配置 + Tailwind class | `web/src/components/hitl/decision-form.tsx` |
| disable 防双提交 | `disabled={isSubmitting}` | `submitting` useState + disabled all buttons | `decision-form.tsx` |
| form_schema 动态字段 | Lexical Editor + form_content | @rjsf/core 5.x + JSON Schema | `decision-form.tsx` (RJSF) |
| 历史 records | 无（Dify dashboard 内有 history） | RecordsTimeline 组件（脱敏 IP/UA） | `web/src/components/hitl/records-timeline.tsx` |
| 截止时间倒计时 | timeout 输入（编辑期） | DeadlineCountdown setInterval 1s | `web/src/components/hitl/deadline-countdown.tsx` |
| Bot UA 短路 | 无（必须登录） | BotScanPage 静态组件 | `web/src/components/hitl/bot-scan-page.tsx` |
| Token-as-login | 无（必须登录） | cookie 自动携带 + credentials: 'include' | `web/src/lib/api/hitl.ts` |

### 6.2 不照搬 Dify 的部分（AGPL 合规）

1. **不复制 Dify 源码**：所有组件独立用 TypeScript + Tailwind v4 + React 19 重写
2. **不复制 Dify form_content Editor**：v1 仅 JSON Schema → RJSF（无 Markdown 模板）
3. **不复制 Dify 三表 ORM 模式**：单表 hitl_tokens（已在 03-01 简化）
4. **Attribution**：reading doc 标注借鉴的设计模式 + Dify 源码路径

## 7. Next.js 16.2 server + client 组件拆分

### 7.1 路由结构

```
web/src/app/hitl/
├── [token]/
│   └── page.tsx          # Server Component（fetch SSR）
├── success/
│   └── [id]/
│       └── page.tsx      # Server Component（静态）
```

### 7.2 Server Component 职责

```tsx
// web/src/app/hitl/[token]/page.tsx
import { cookies, headers } from 'next/headers';

export default async function Page({ params }: { params: { token: string } }) {
  const cookieStore = await cookies();
  const headersList = await headers();

  // 透传 cookie + UA 到后端
  const data = await fetchHitlPage(params.token, {
    cookie: cookieStore.toString(),
    userAgent: headersList.get('user-agent') ?? '',
  });

  if (data.bot_scan) {
    return <BotScanPage />;
  }

  return <DecisionPageLayout data={data} token={params.token} />;
}
```

### 7.3 Client Component 职责

- `DecisionForm`（'use client'）：useState + RJSF + 提交
- `RecordsTimeline`（'use client'）：useState formatting
- `DeadlineCountdown`（'use client'）：useEffect + setInterval
- `BotScanPage`（'use client'，可纯静态）：noindex meta + 文案

### 7.4 cookie 转发关键点

Next.js 16.2 Server Component 中：
- `cookies()` 是 async（必须 await）
- 透传到 backend：`fetch(url, { headers: { cookie: cookieStore.toString() } })`
- Backend Set-Cookie 透传回浏览器：用 Next.js Route Handler 或直接 redirect

⚠️ **关键**：我们的场景下，用户首次访问 `/hitl/[token]` 时浏览器**还没有** `hitl_session_<jti>` cookie，后端 GET 会签发该 cookie。Server Component 直接 fetch 后端时，后端的 Set-Cookie 头不会自动转发到浏览器响应。

**解决方案**：在 `/hitl/[token]` Next.js route 添加 Route Handler 中间件，或在 Server Component 内：
1. fetch backend `/hitl/page/<token>` with `Accept: application/json`
2. backend 返回 JSON 数据 + `Set-Cookie` header
3. Next.js Server Component 读取 `Set-Cookie` header → 在响应中重新 set 到浏览器
4. 简化方案：**v1 让客户端直接 fetch 后端**（避免 cookie 转发坑），server component 仅做骨架渲染 → client component useEffect fetch

**v1 简化采纳**：客户端 fetch 模式（避免 SSR cookie 转发复杂性）；server component 只渲染容器 + 客户端 hydrate 实际数据。

## 8. 与 hr/offboarding-flow 项目对照

- hr/PRD §7 已设计"双通道通知"+ "邮件深链 + 多按钮"模式 —— 与本 phase HITL 同源
- hr/ 已落 email + Mattermost 投递；本项目 v1 仅 email
- hr/ 的决策页 UI 设计（参考 hr/docs/）—— 部分模式可借鉴：响应式 / 倒计时 / 提交后 disable

## 9. 实施清单（落到 Plan 03-07 task）

- [x] Task 0：本 reading doc commit（CLAUDE.md 2.7 GATE）
- [ ] Task 1：安装 @rjsf/core 5.x + 写 types + api client
- [ ] Task 2：4 组件（DecisionForm + RecordsTimeline + DeadlineCountdown + BotScanPage）
- [ ] Task 3：2 页面（/hitl/[token] + /hitl/success/[id]）
- [ ] Task 4：vitest 测试 10 用例

---

*Reading doc completed: 2026-05-17*
*Plan: 03-07*
*Next commit must reference this doc*
