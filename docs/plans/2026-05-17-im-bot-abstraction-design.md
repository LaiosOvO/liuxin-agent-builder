# IM Bot 通用对接设计 — 配置化命令路由 + 自动 help + LLM 意图兜底

> **作者**：来自 offboarding-flow 实战提炼
> **日期**：2026-05-17
> **状态**：设计稿（待 Phase 5 / 6 评审）
> **关联**：[`dify-integration-offboarding-meeting-2026-05-17.md`](../dify-integration-offboarding-meeting-2026-05-17.md)

---

## 0. 背景

### 0.1 为什么需要这个需求

`agent-builder` 当前 v1 已经支持 LangGraph DAG 编排 + HITL 节点邮件深链回调。但**IM 触发**（用户在 Mattermost / 飞书 / 钉钉对 bot 说话即触发工作流）目前是空白：

- 现在只能通过 web UI 手动起流程，或者 HITL 节点收邮件回调
- 缺失「用户主动 @bot 自助启动工作流」「@bot 查询流程状态」「@bot 推送会议纪要触发分析子流程」等真实办公场景
- IM 接入如果每个 deploy 都从 0 写一遍 listener / command parser / dispatcher，单 deploy 就要写 500+ 行模板代码

### 0.2 已有 reference impl（强烈建议先读）

`offboarding-flow` 项目已经把上述能力实现并跑通了，但**写得不够通用**——是单业务硬编码版。本设计的目标是**把它抽象成 agent-builder 的内置能力 + 配置驱动**。

关键 reference 代码（位于 `/Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/`）：

| 文件 | 作用 | 抽象后位置（建议） |
|---|---|---|
| `workers/mattermost_listener.py` | WS 长连 + 事件分发 | `agent_builder/im/listeners/<provider>.py` |
| `services/bot_command_parser.py` | 白名单命令解析 + 中文 trigger 词 | `agent_builder/im/dispatcher/parser.py`（配置驱动） |
| `services/bot_intent_router.py` | LLM 自然语言意图分类 | `agent_builder/im/dispatcher/llm_router.py` |
| `services/bot_service.py` | 命令 → handler 路由 + dispatch | `agent_builder/im/dispatcher/registry.py` |
| `providers/{mattermost,lark,wecom,dingtalk}_provider.py` | IM 平台抽象 | `agent_builder/im/providers/`（直接复用） |
| `auth/jwt_service.py` + `auth/jti_service.py` | magic link token | 复用现有 agent-builder HITL token |

---

## 1. 目标 / 非目标

### 1.1 目标（v1 in scope）

| ID | 目标 | 验证方式 |
|---|---|---|
| G1 | 平台用户**通过 YAML/JSON 配置**就能给一个 agent 加 IM bot 入口，不需要写 Python | 一份 `bot.yaml` 就能让 bot 在 MM 上能接消息 |
| G2 | 命令以**插件式注册**：声明 name / args schema / handler function ref → dispatcher 自动找 | 加一个新命令只需注册 1 个 handler |
| G3 | `help` 命令**完全自动生成**，不需要手写 markdown | 加新命令 → `help` 输出自动更新 |
| G4 | 输入不是白名单命令时走 **LLM 意图分类**，路由到对应命令 / 兜底 ai_qa | 用户说"帮我看看进度"→ 自动路由到 `status` |
| G5 | 支持 **DM + channel @mention** 双触发，自动过滤 bot 自己消息防死循环 | 一套配置同时跑 DM 和 channel |
| G6 | **身份对齐**：MM/飞书 username 必须能映射回 agent-builder 用户表 | 跨系统对齐失败时友好拒绝并提示运维 |
| G7 | 支持自助起流程：「我要离职」类自然语言 → 触发 DAG 启动 + 申请人默认为消息发送者 | reference impl 已有 `SELF_APPLY_SENTINEL` 模式 |

### 1.2 非目标（v1 out of scope）

- ❌ **可视化命令编辑器**：v1 用 YAML 即可，画布加节点是 v2 的事
- ❌ **多语言 i18n**：v1 中文 / 英文双语自动生成 help，更多语言后续
- ❌ **命令权限到字段级 RBAC**：v1 只到 role 级（applicant / manager / hr / admin）
- ❌ **自托管 LLM router**：v1 复用 agent-builder 已配置的 LLM provider（GLM / OpenAI 兼容）
- ❌ **会议总结类「主动 push 内容到 bot」**：作为 Phase 2 扩展，v1 只做命令式

---

## 2. 现状：offboarding-flow 的 IM bot 实现快照

### 2.1 它做对的部分（值得复用）

```
WS event posted
   ↓
sender_name 校验 (bot 自己消息直接 return 防死循环)
   ↓
触发条件检查 (DM / @mention / trigger 词三选一)
   ↓
parse_command(message) — 白名单命令
   ↓ 失败
BotIntentRouter LLM 分类 → intent + confidence + args
   ↓ conf >= 0.6 路由对应命令 / 否则 ai_qa
身份对齐: SELECT users WHERE username = sender_name
   ↓
BotInvocationContext(user_name, user_role, mm_helpers)
   ↓
dispatch(cmd, ctx) → 11 个 handler 中的一个
   ↓
返回文本 → bot 主动 post 回 channel/DM
```

### 2.2 它做得不够通用的部分（本设计要改进）

| 痛点 | 现状 | 期望 |
|---|---|---|
| 命令是硬编码 if/elif | `bot_service.dispatch` 11 个 if 分支 | 注册表 + 动态查表 |
| `help` 文本手写 markdown | 11 行硬编码字符串，加命令要改两处 | 元数据驱动自动生成 |
| LLM intent prompt 硬编码 | `prompts.INTENT_ROUTER_PROMPT` 写死 8 个意图 | YAML 配置每个 bot 的意图集 |
| 触发关键词写死 | `_SELF_APPLY_PHRASES = ("我要离职", ...)` | 配置项 `triggers.keywords` |
| 一个 listener 跑一个业务 | mattermost_listener 只服务 offboarding 业务 | 一个 listener 多 bot 多 workspace |
| Provider 切换要改 import | `from mattermostautodriver import AsyncDriver` 写死 | factory + `IM_PROVIDER` env 切换 |

---

## 3. 需求清单

### 3.1 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| R-IM-01 | YAML/JSON 配置一个 bot：name / provider / triggers / commands / fallback / llm | P0 |
| R-IM-02 | 命令注册支持 (name, description, args_schema, handler_ref, allowed_roles) | P0 |
| R-IM-03 | `help` 命令自动生成（按 allowed_roles 过滤当前用户能看到的命令） | P0 |
| R-IM-04 | LLM intent router 配置化：意图清单 + 路由表 + confidence 阈值 + ai_qa 兜底 | P0 |
| R-IM-05 | 触发条件配置：DM / @mention / 关键词（OR 关系） | P0 |
| R-IM-06 | 身份对齐：sender_name → agent-builder users 表查 role；失败友好拒绝 | P0 |
| R-IM-07 | self-apply 模式：声明某命令 `self_apply: true` 时 args 默认填发送者自己 | P1 |
| R-IM-08 | mm_helpers 抽象：post_channel / send_dm / ensure_in_channel 接口跨 provider 一致 | P1 |
| R-IM-09 | 支持多 bot 共存：一个 listener 进程加载多个 bot.yaml | P1 |
| R-IM-10 | bot 元数据 reload 不重启进程：YAML 改后 SIGHUP 热加载 | P2 |
| R-IM-11 | dispatch 失败时 audit log 入库（who / cmd / error / ts） | P1 |
| R-IM-12 | 命令限流 (per user per minute) 防误刷 | P2 |
| R-IM-13 | 命令支持 idempotency_key（同一 user 同一参数 N 秒内只跑一次） | P2 |

### 3.2 非功能需求

| ID | 需求 |
|---|---|
| N-IM-01 | 单 listener 进程每秒处理 ≥ 50 条 IM 消息（实测 offboarding-flow 约 20/s 是 sync DB 调用瓶颈） |
| N-IM-02 | WS 断线自动重连，重连间隔指数退避（reference impl 已有） |
| N-IM-03 | 凭证（bot_token / api_secret）只通过 env 注入，禁止进 YAML 文件 |
| N-IM-04 | dispatch handler 的 stdout / stderr 必须捕获到日志（不能 leak 到 bot 回复） |
| N-IM-05 | LLM intent 调用必须有 timeout（默认 5s），超时直接走 ai_qa 兜底，不阻塞 dispatcher |

---

## 4. 配置 Schema 设计

### 4.1 整体 schema（YAML，Pydantic 强校验）

```yaml
# bots/offboarding.yaml
name: offboarding-bot
description: 离职流程助手
provider:
  type: mattermost           # mattermost | lark | wecom | dingtalk | slack
  config_env_prefix: MM_     # 凭证从 env 取（MM_BOT_TOKEN / MM_URL / MM_TEAM）

triggers:
  dm: true                   # 任何 DM 都触发
  at_mention: true           # @bot 触发
  keywords:                  # OR 关系
    - 我要离职
    - 申请离职
    - 离职申请

identity:
  source: agent_builder_users   # 从 agent-builder 用户表查 sender_name
  on_unknown: reject_friendly   # reject_friendly | guest_mode | auto_create
  unknown_hint: "未识别账号，请联系管理员同步：`@offboarding-bot users-sync`"

commands:
  - name: start
    description: 启动新的离职流程（参数：员工 username）
    args:
      - name: employee_id
        type: string
        pattern: '^[a-z][a-z0-9._-]{1,30}$'
        required: true
    self_apply:                 # 自助起流程：自然语言"我要离职"时
      enabled: true
      sentinel_phrases: ["我要离职", "申请离职"]
      arg_default:
        employee_id: "${ctx.user_name}"
    handler: handlers.flow:start_flow
    allowed_roles: [admin, hr, applicant]   # applicant 只在 self_apply 模式下能用

  - name: status
    description: 查询某流程状态（参数：flow_id 短/长 UUID）
    args:
      - name: flow_id
        type: uuid8_or_uuid36
        required: true
    handler: handlers.flow:get_status
    allowed_roles: [admin, hr, manager, applicant]

  - name: list
    description: 列出我的 / 全部流程
    args:
      - name: filter
        type: enum
        choices: [active, completed, stuck, mine]
        default: active
        required: false
    handler: handlers.flow:list_flows
    allowed_roles: [admin, hr, manager, applicant]

  - name: meeting-ingest
    description: 推送会议纪要让 AI 分析（多行原文跟在命令后）
    args:
      - name: raw_text
        type: string
        multiline: true
        min_length: 30
        required: true
    handler: handlers.meeting:ingest
    allowed_roles: [admin, hr, manager]

  - name: users-sync
    description: 同步用户到协作文档系统（Outline 等）
    handler: handlers.admin:users_sync
    allowed_roles: [admin]

fallback:
  llm_intent_router:
    enabled: true
    confidence_threshold: 0.6
    timeout_seconds: 5
    intents:                      # 列举所有可识别意图 → 路由表
      - start                      # ↑ 对应 commands.name
      - status
      - list
      - meeting-ingest
      - users-sync
      - ai_qa                      # 特殊：兜底自由问答
    prompt_template_path: prompts/intent_router_zh.md
    llm: ${global.default_llm}    # 引用全局 LLM provider 配置

  ai_qa:
    enabled: true
    prompt_template_path: prompts/ai_qa_zh.md
    max_tokens: 500
    system_message: |
      你是 offboarding-bot，专门帮助离职流程相关问题。
      不要回答与离职无关的问题，礼貌引导用户。

audit:
  log_dispatch: true              # 每次 dispatch 入 audit table
  rate_limit:                     # R-IM-12
    per_user_per_minute: 10

help:
  auto_generate: true             # R-IM-03 — 不手写 help 文本
  template_path: prompts/help_template.md   # 可选自定义 wrapper
  group_by: category              # 按 commands[].category 字段分组（可选）
  show_examples: true             # 显示每个命令的 example_invocations
```

### 4.2 Pydantic schema（实现要点）

```python
# agent_builder/im/schemas/bot_config.py
from pydantic import BaseModel, Field
from typing import Literal

class CommandArg(BaseModel):
    name: str
    type: Literal['string', 'int', 'uuid8_or_uuid36', 'enum', 'bool']
    pattern: str | None = None
    choices: list[str] | None = None
    required: bool = True
    multiline: bool = False
    min_length: int | None = None
    default: str | None = None

class SelfApplySpec(BaseModel):
    enabled: bool = False
    sentinel_phrases: list[str] = []
    arg_default: dict[str, str] = {}

class CommandSpec(BaseModel):
    name: str
    description: str
    args: list[CommandArg] = []
    self_apply: SelfApplySpec | None = None
    handler: str   # "module.path:function_name"
    allowed_roles: list[str] = ['admin']
    category: str | None = None
    example_invocations: list[str] = []

class TriggersSpec(BaseModel):
    dm: bool = True
    at_mention: bool = True
    keywords: list[str] = []

class IdentitySpec(BaseModel):
    source: Literal['agent_builder_users', 'jit_create']
    on_unknown: Literal['reject_friendly', 'guest_mode', 'auto_create']
    unknown_hint: str | None = None

class LLMIntentRouterSpec(BaseModel):
    enabled: bool = True
    confidence_threshold: float = 0.6
    timeout_seconds: float = 5.0
    intents: list[str]
    prompt_template_path: str
    llm: str   # reference to global LLM provider

class FallbackSpec(BaseModel):
    llm_intent_router: LLMIntentRouterSpec | None = None
    ai_qa: 'AiQaSpec | None' = None

class BotConfig(BaseModel):
    name: str
    description: str
    provider: 'ProviderSpec'
    triggers: TriggersSpec
    identity: IdentitySpec
    commands: list[CommandSpec]
    fallback: FallbackSpec
    audit: 'AuditSpec' = None
    help: 'HelpSpec' = None
```

---

## 5. CommandSpec + 动态 Dispatcher 设计

### 5.1 Handler ref 解析与注册

```python
# agent_builder/im/dispatcher/registry.py
import importlib
from typing import Callable, Awaitable

class HandlerRegistry:
    def __init__(self, bot_config: BotConfig):
        self.bot_config = bot_config
        self._cache: dict[str, Callable[..., Awaitable[str]]] = {}

    def resolve(self, handler_ref: str) -> Callable:
        """`handlers.flow:start_flow` → import handlers.flow; get start_flow"""
        if handler_ref in self._cache:
            return self._cache[handler_ref]
        module_path, fn_name = handler_ref.split(':')
        mod = importlib.import_module(module_path)
        fn = getattr(mod, fn_name)
        if not callable(fn):
            raise ValueError(f"handler {handler_ref} not callable")
        self._cache[handler_ref] = fn
        return fn

    async def dispatch(self, cmd_name: str, args: dict, ctx: 'BotContext') -> str:
        spec = self._find_spec(cmd_name)
        if spec is None:
            return await self._dispatch_help(ctx)
        self._check_role(spec, ctx)         # 角色闸门
        self._validate_args(spec, args)     # Pydantic 校验
        await self._audit(cmd_name, ctx)    # R-IM-11
        await self._rate_limit(cmd_name, ctx)  # R-IM-12
        handler = self.resolve(spec.handler)
        return await handler(args=args, ctx=ctx)
```

### 5.2 Handler 函数签名约定

```python
# 用户写的 handler 签名永远是这个形状
async def start_flow(args: dict, ctx: BotContext) -> str:
    """args 已校验通过 + ctx 已对齐身份。返回 markdown 字符串给 bot 回复。"""
    employee_id = args['employee_id']
    # 调 agent-builder workflow runner 启动 DAG
    flow_id = await ctx.workflow.start(
        workflow_name='offboarding',
        inputs={'employee_id': employee_id},
        actor=ctx.user_name,
    )
    return f"✅ 已为 @{employee_id} 启动离职流程，案件 ID `{flow_id}`"
```

`BotContext` 提供：

```python
class BotContext:
    user_name: str         # ↑ 已对齐 agent-builder users
    user_id: str           # IM 内部 id（mm_user_id / lark_open_id）
    user_role: str
    channel_id: str
    bot_config: BotConfig
    workflow: WorkflowAPI  # agent-builder 工作流 API
    im_helpers: IMHelpers  # post_channel / send_dm / ensure_in_channel
    llm: LLMProvider       # 引用全局 LLM
```

### 5.3 args 校验

CommandArg type → Pydantic 动态 model：

```python
def args_to_pydantic(spec: CommandSpec) -> type[BaseModel]:
    fields = {}
    for a in spec.args:
        py_type = _TYPE_MAP[a.type]
        validator = ... # pattern / choices / min_length 转换
        fields[a.name] = (py_type, Field(...))
    return create_model(f"{spec.name}Args", **fields)
```

失败时给用户 bot 友好提示：

```
⚠️ 参数错误：employee_id 必须匹配 ^[a-z][a-z0-9._-]{1,30}$
正确用法：
  @offboarding-bot start <employee_username>
  示例：@offboarding-bot start it.charlie
```

---

## 6. `help` 命令自动生成

### 6.1 元数据驱动

`help` handler 本身**不是用户写的**，是 dispatcher 内置：

```python
# agent_builder/im/dispatcher/builtin_help.py
async def handle_help(args: dict, ctx: BotContext) -> str:
    cfg = ctx.bot_config
    visible = [
        c for c in cfg.commands
        if ctx.user_role in c.allowed_roles or 'admin' in {ctx.user_role}
    ]

    if cfg.help.group_by == 'category':
        groups = defaultdict(list)
        for c in visible:
            groups[c.category or '其他'].append(c)
    else:
        groups = {'命令清单': visible}

    lines = [f"📖 **{cfg.name}** — {cfg.description}\n"]
    for cat, cmds in groups.items():
        lines.append(f"### {cat}")
        for c in cmds:
            args_str = ' '.join(
                f"<{a.name}>" if a.required else f"[{a.name}]"
                for a in c.args
            )
            lines.append(f"- `@{cfg.name} {c.name} {args_str}` — {c.description}")
            if cfg.help.show_examples and c.example_invocations:
                for ex in c.example_invocations[:2]:
                    lines.append(f"    > 示例：`{ex}`")
        lines.append('')

    if cfg.fallback.ai_qa and cfg.fallback.ai_qa.enabled:
        lines.append("> 💡 你也可以直接用自然语言问我，我会尽量帮你路由到对应命令。")

    return '\n'.join(lines)
```

### 6.2 加新命令的工作量

加一个 `simulate-timeout` 命令：

1. 写一个 handler 函数（5-20 行）
2. YAML 加一段 `commands:` 条目（5 行）
3. **不需要**改 dispatcher、不需要改 help 文本、不需要改 LLM router prompt

LLM intent router 也是配置化的——`intents:` 列表加一个 `simulate-timeout` 字符串即可，prompt 模板从配置注入意图清单。

### 6.3 自动验证 — config validate 子命令

```bash
agent-builder bot validate bots/offboarding.yaml
```

启动时检查：
- 所有 handler ref 都能 import 到（防部署时 typo）
- 所有 args type 的 pattern 是合法正则
- llm 引用存在
- 关键词 / 触发条件至少满足一个
- self_apply 命令的 arg_default 字段都在 args 列表里

---

## 7. LLM intent router 抽象

### 7.1 配置

`prompts/intent_router_zh.md`：

```
你是 {{bot_name}} 的意图分类器。判断用户输入属于以下哪个意图，并返回 JSON：

可识别意图：
{{#each intents}}
- {{this}}
{{/each}}

特殊：ai_qa（不属于任何具体意图，走兜底自由问答）

返回格式（严格 JSON，无多余字段）：
{
  "intent": "<上述意图之一>",
  "confidence": <0.0-1.0>,
  "args": { "<arg_name>": "<value>" }
}

用户输入：
{{user_message}}

发送者：username={{sender_username}} role={{sender_role}}
```

### 7.2 路由表

```python
# agent_builder/im/dispatcher/llm_router.py
class IntentResult(BaseModel):
    intent: str
    confidence: float
    args: dict[str, str]
    ai_reply: str | None = None

async def classify(message: str, ctx: BotContext) -> IntentResult:
    cfg = ctx.bot_config.fallback.llm_intent_router
    prompt = render_template(cfg.prompt_template_path, {
        'bot_name': ctx.bot_config.name,
        'intents': cfg.intents,
        'user_message': message,
        'sender_username': ctx.user_name,
        'sender_role': ctx.user_role,
    })
    try:
        resp = await ctx.llm.complete(prompt, timeout=cfg.timeout_seconds)
        return IntentResult.model_validate_json(resp)
    except Exception:
        # 兜底：直接 ai_qa
        return IntentResult(intent='ai_qa', confidence=0.0, args={})
```

dispatcher 拿到 `IntentResult` 后：

```python
if result.confidence >= cfg.confidence_threshold and result.intent != 'ai_qa':
    # 路由到对应命令
    cmd_spec = registry.find(result.intent)
    return await registry.dispatch(cmd_spec.name, result.args, ctx)
else:
    # ai_qa 兜底
    if cfg_ai_qa.enabled:
        return await llm_ai_qa(message, ctx)
    else:
        return "🤖 我没听懂，输入 `help` 查看命令清单"
```

---

## 8. Provider 抽象（复用 offboarding-flow 已有的）

`offboarding-flow` 已经实现：

- `providers/base.py` — `IMProvider` Protocol
- `providers/mattermost_provider.py` — MM 真接入
- `providers/lark_provider.py` — 飞书真接入
- `providers/wecom_provider.py` / `dingtalk_provider.py` — stub

**直接 port 过来**到 `agent-builder/backend/agent_builder/im/providers/`，几乎不动逻辑。

差异：

- agent-builder 用 multi-tenant，所以 provider config 不是 global env，而是 per-workspace DB 字段
- factory 改成 `get_im_provider(workspace_id)` 而不是 `get_im_provider()` 单例
- bot_token 等敏感字段加密存（用 agent-builder 已有的 secret manager）

---

## 9. 与 agent-builder DAG 的整合点

### 9.1 IM Trigger 节点（新增节点类型）

DAG 画布上新增「IM Trigger」节点：

```yaml
# DSL 示例
nodes:
  - id: im_trigger_1
    type: im_trigger
    config:
      bot_ref: offboarding-bot              # 引用某个 bot.yaml
      on_command: start                      # 哪个命令触发本 DAG
      args_mapping:
        employee_id: ${cmd.args.employee_id}
    outputs:
      employee_id: string

  - id: manager_review
    type: hitl_decision
    depends_on: [im_trigger_1]
    config:
      assignee: ${vars.users.manager_of[im_trigger_1.employee_id]}
      ...
```

**触发流程**：

```
IM bot 收 "@bot start it.charlie"
   ↓
dispatcher 路由到 start 命令
   ↓
handler "handlers.flow:start_flow" 拿到 ctx
   ↓
ctx.workflow.start(workflow_name='offboarding', inputs={'employee_id': 'it.charlie'})
   ↓
agent-builder runner 启动 DAG，im_trigger_1 节点立即 done，输出 employee_id
   ↓
触发下游 manager_review HITL 节点
```

### 9.2 Bot 反向通知（DAG → bot）

DAG 跑到 HITL 节点时，除了发邮件，还可以走 IM：

```yaml
nodes:
  - id: notify_manager
    type: im_notify
    config:
      bot_ref: offboarding-bot
      channel: dm                          # dm | channel
      to: ${vars.manager_username}
      template: |
        🔔 你有新的离职审批任务
        员工：${vars.employee_id}
        点击决策：${magic_link}
```

`magic_link` 由 agent-builder 自动签 JWT 注入。

---

## 10. Phase 拆分（建议）

### Phase 5.A — IM bot 基础抽象（2 周）

| 任务 | 输出 |
|---|---|
| 1. `BotConfig` Pydantic schema + YAML loader | `agent_builder/im/schemas/` |
| 2. `HandlerRegistry` 动态注册 + dispatcher | `agent_builder/im/dispatcher/` |
| 3. `BotContext` 接口 + IMHelpers 抽象 | `agent_builder/im/context.py` |
| 4. 内置 `help` 命令自动生成 | `agent_builder/im/dispatcher/builtin_help.py` |
| 5. CLI: `agent-builder bot validate <yaml>` | 启动期校验 |
| 6. 单元测试：注册 / dispatch / 角色闸门 / 参数校验 | pytest |
| 7. 集成测试：跑个 demo bot，发 help / start / 错误命令验证 | pytest-asyncio |

### Phase 5.B — LLM intent router（1 周）

| 任务 | 输出 |
|---|---|
| 1. `LLMIntentRouter.classify` | `agent_builder/im/dispatcher/llm_router.py` |
| 2. prompt 模板 + 渲染（Jinja2） | `agent_builder/im/prompts/` |
| 3. timeout + 兜底逻辑 | 内嵌于 router |
| 4. ai_qa 兜底链 | 同上 |
| 5. 单测：mock LLM 返回不同 intent 验证路由 | pytest |
| 6. E2E：browser-harness 演示 NL → 真实路由（参考 offboarding 的 nl-meeting 截图） | webapp-testing |

### Phase 5.C — Provider 移植 + 多 bot 多 workspace（2 周）

| 任务 | 输出 |
|---|---|
| 1. 移植 4 个 IMProvider（MM/飞书/WeCom/DingTalk） | `agent_builder/im/providers/` |
| 2. 多 bot listener manager：一个进程加载多 workspace 的 bot.yaml | `agent_builder/im/manager.py` |
| 3. per-workspace 凭证加密存（用现有 secret manager） | DB schema 升级 |
| 4. SIGHUP 热加载（R-IM-10） | listener supervisor |
| 5. E2E：双 workspace 各自一个 bot，互不影响 | browser-harness |

### Phase 5.D — DAG 整合：IM Trigger + IM Notify 节点（2 周）

| 任务 | 输出 |
|---|---|
| 1. DSL schema 加 `im_trigger` / `im_notify` 节点类型 | DSL 验证器 |
| 2. runner 实现节点执行逻辑（im_trigger 等 IM 事件 / im_notify 发消息） | LangGraph 节点 |
| 3. 画布 UI：节点拖拽 + 配置面板 | frontend |
| 4. E2E：拖一个含 IM trigger 的工作流 → bot 起 → 跑完 | browser-harness |

---

## 11. 验收标准（DoD）

### Phase 5.A 验收

- [ ] 一份 `bot.yaml` 配置文件 = 一个完整可用的 IM bot
- [ ] 加一个新命令只需写 handler 函数 + YAML 加 5 行
- [ ] `help` 命令输出按 user role 过滤，且加新命令自动更新
- [ ] 参数校验失败时 bot 回复带正确用法示例
- [ ] 单元测试覆盖率 ≥ 85%
- [ ] 集成测试用真实 MM 容器验证

### Phase 5.B 验收

- [ ] 用户说 "帮我看看流程进度" → 自动路由到 `status` 命令（参考 offboarding-flow `intent=status conf>=0.6` 实测）
- [ ] LLM timeout 时不阻塞 dispatcher
- [ ] 不能识别的输入走 ai_qa 兜底而不是报错

### Phase 5.D 验收

- [ ] 画布拖一个 IM Trigger + 3 个 HITL 节点 → 发布
- [ ] MM `@bot start xxx` → 工作流立刻启动
- [ ] HITL 节点 IM Notify 发出去 → 决策回调能正确推进 DAG

---

## 12. 风险 + 兜底

| 风险 | 概率 | 影响 | 兜底 |
|---|---|---|---|
| LLM intent 路由准确率不够 | 中 | 用户体验差 | confidence 阈值 + ai_qa 兜底；用户可以手动 `help` 看清命令 |
| handler 函数抛异常 leak 到 bot 回复（暴露 stack trace） | 中 | 安全 | dispatcher 统一 try/except，wrap 成"❌ 内部错误，请联系管理员"+ audit log |
| YAML 配置语法错误部署后不报错 | 高 | 死 bot | 启动期 strict validate，validate 失败拒绝启动 listener |
| 跨 workspace bot 共用一个 MM bot 账号 | 低 | 错乱 | workspace_id 注入 channel scope，但仍建议每 workspace 独立 bot 账号 |
| 用户在 channel 频繁 @bot 刷 LLM 费用 | 中 | 成本 | R-IM-12 rate limit + LLM intent router 仅命中触发条件时调用 |
| 命令名与 LLM intent 名冲突 | 低 | 路由错误 | validate 期检查 intents ∩ commands.name 一致 |

---

## 13. 参考资料

| 来源 | 路径 |
|---|---|
| offboarding-flow IM bot reference impl | `/Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/services/bot_*.py` + `workers/mattermost_listener.py` |
| offboarding-flow IM provider 抽象 | `/Users/admin/ai/resume/interview/liuxin/hr/backend/src/offboarding_flow/providers/` |
| offboarding-flow LLM intent router 实测截图 | `/Users/admin/ai/resume/interview/liuxin/hr/docs/e2e-screenshots-2026-05-17-final/21-meeting-nl-empty.png` + `22-meeting-nl-real-analysis.png` |
| offboarding-flow magic-link token 设计（可复用） | `/Users/admin/ai/resume/interview/liuxin/hr/README.md` §5 |
| Dify 集成方案对比（已有） | `./dify-integration-offboarding-meeting-2026-05-17.md` |

---

## 14. 开放问题（待评审决定）

1. **bot.yaml 存哪里？** 文件系统 / DB 字段 / 画布编辑器三选一
   - 推荐 v1：文件系统（`workspaces/<ws_id>/bots/<bot_name>.yaml`）+ git 版本管理
   - v2：DB 字段 + 画布 GUI 编辑
2. **handler 写在哪里？** workspace 自带的 Python 包 / 平台预置 / 上传插件
   - 推荐 v1：workspace 上传 zip（已有 Phase 6 plugin 沙箱）
   - v1.5：平台预置常用 handler（start_workflow / get_status / list_workflows）开箱即用
3. **如何避免 LLM router 把"我要离职"路由错？** 触发关键词优先于 LLM router
   - 实现：先跑 keywords 匹配，命中直接走 self_apply，不调 LLM；只有 keywords 不命中才调
4. **多 bot 共享同一个 LLM key 吗？** 是 — 复用 workspace 级 LLM provider 配置
5. **bot 回复支持卡片 / 按钮吗？** Phase 5.D 顺带加，目前 plain markdown 已经够 v1

---

*文档完*
