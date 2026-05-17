# Dify 阅读笔记 — LLM 节点 + PromptTemplateParser（ai_suggest_mentions 钩子）

> 日期: 2026-05-18
> 仓库: https://github.com/langgenius/dify (local clone `/Users/admin/ai/ref/dify/repo/`, AGPL-3.0)
> Stars: ~141k
> 对应 plan: `.planning/phases/05c-doc-capability/05c-06-PLAN.md` (Wave 4, ai_suggest_mentions LLM 钩子真接入)

## 项目概述（一句话）

Dify 是国内最成熟的开源 LLM 应用平台；其 `PromptTemplateParser` + `LLMGenerator` + `SimplePromptTransform` 三件套构成"模板加载 → 变量注入 → messages 拼装 → model provider 调用 → 结构化输出解析 → 失败 fallback"的标准管线，是工作流引擎里所有"内置 LLM 能力"（生成会话标题、建议追问、生成 rule_config 等）的共同骨架，正好对应本 plan 要落地的 `ai_suggest_mentions` 单轮 LLM 调用形态。

## 技术栈（关键技术选择）

- **PromptTemplateParser**：`re.compile(r"\{\{([a-zA-Z_][a-zA-Z0-9_]{0,29}|#histories#|#query#|#context#)\}\}")` 单一正则覆盖普通变量 + 4 类特殊变量；变量名约束（首字符 letter/underscore + 长度 ≤ 30 + 仅 alnum/underscore）防 prompt 注入与误匹配
- **SimplePromptTransform**：把"系统 pre_prompt + 用户 query + context + histories"按 ChatModel / Completion 两种 model_mode 分别拼装；产出 `list[PromptMessage]`（OpenAI messages 兼容形态：`SystemPromptMessage` / `UserPromptMessage` / 多模态 `ImagePromptMessageContent`）
- **LLMGenerator**：所有内置 LLM 任务的"功能门面"（`generate_conversation_name` / `generate_suggested_questions_after_answer` / `generate_rule_config` / 代码生成 / 结构化输出生成），统一走 `ModelManager.for_tenant(tenant_id).get_default_model_instance(...).invoke_llm(...)`
- **结构化输出**：`json.loads()` 兜底 `json_repair.loads()` —— 容忍 LLM 偶尔的非法 JSON，仍尝试修复后解析；最终失败则降级为安全默认值（空 list / 空 dict / 把原 query 作为标题）
- **provider 错误隔离**：`InvokeAuthorizationError` / `InvokeError` 分级 catch，并在最外层 `except Exception` + `logger.exception` 兜底；**任何 LLM 错误绝不向上层 raise，统一返回 fallback**

## 架构要点

```
prompt template (.md / py 常量)
        │
        ▼
PromptTemplateParser({{var}}, {{#histories#}}, …)        ← 借鉴 #1：变量名/字符约束
        │   format(inputs={...}, remove_template_variables=False)
        ▼
rendered prompt str
        │
        ▼
SimplePromptTransform → list[PromptMessage]              ← 借鉴 #2：system/user 分段
   [SystemPromptMessage(content=…),
    UserPromptMessage(content=…)]
        │
        ▼
ModelManager.for_tenant(tenant_id).invoke_llm(...)       ← 借鉴 #5：provider 错误归一化
        │
        ▼
LLMResult.message.get_text_content()  (str)
        │
        ▼
json.loads()  →  json_repair.loads()  →  default {}      ← 借鉴 #3：结构化输出 fallback
        │
        ▼
typed dict / Sequence[str] / Pydantic model 返回给业务
```

对照本 plan：本项目主进程内 `OutlinePlugin.ai_suggest_mentions` / `LarkDocsPlugin.ai_suggest_mentions` → `llm_mention_helper.suggest_mentions_via_llm(...)`，是 Dify 这套管线的"单文件浓缩版"——单一 helper 函数承担全部 5 个阶段，避免为每个 plugin 复制一遍 `LLMGenerator` 模板。

## 可借鉴的设计模式

1. **PromptTemplateParser 变量正则 + 长度上限** — Dify 源 `api/core/prompt/utils/prompt_template_parser.py:4-6`（变量名首字符 letter/underscore + 长度 ≤ 30 + 仅允许 4 类 `#xxx#` 特殊键）→ 本项目 target `backend/app/plugins/_common/llm_mention_helper.py::load_prompt_template`：用 `string.Template` 或对模板做"先替换 `{{var}}` → 字典 inject → 最后 escape markdown 中残留的 `{`"两步走，**不直接 `template.format(**ctx)`**（markdown 正文里随手出现的 `{` 会让 `str.format` 抛 `KeyError`）。变量白名单严格收敛到 4 个：`{{markdown}}` `{{document_id}}` `{{author_id}}` `{{workspace_users_hint}}`。

2. **SimplePromptTransform system/user 分段拼装** — Dify 源 `api/core/prompt/simple_prompt_transform.py:60-91`（`_get_chat_model_prompt_messages` 把 pre_prompt 装 `SystemPromptMessage`，query/context/files 装 `UserPromptMessage`，最终产出 OpenAI 兼容 messages 列表）→ 本项目 target 三个 plugin 的 `prompts/ai_suggest_mentions_zh.md` 模板：用 H2 markdown header `## SYSTEM` / `## USER` 把模板切成两段；`llm_mention_helper` 读取后产出 `[{"role": "system", "content": sys}, {"role": "user", "content": usr_after_inject}]`，正好对齐项目已有的 `call_llm(model_str, messages, ...)` 约定（`backend/app/agent_builder/workflow/llm_client.py:167-211`）。

3. **LLMGenerator JSON 结构化输出 fallback** — Dify 源 `api/core/llm_generator/llm_generator.py:119-131`（`generate_conversation_name` 中 `try: json.loads(answer)` → `except JSONDecodeError: json_repair.loads(answer)` → 若结果不是 dict 就回退为原 query；`generate_suggested_questions_after_answer:232-236` 任意 Exception 都返回空 `questions = []`）→ 本项目 target `llm_mention_helper.suggest_mentions_via_llm`：解析 LLM 返回的 `{"suggestions":[{"user_id","confidence","rationale"}, …]}` 时，**先 `json.loads` → 失败时尝试 `json_repair.loads`（已在 requirements 里）→ 仍失败则返回 `list[MentionSuggestion]()` 空列表**，配合 `outcome="parse_failure"` structured log，绝不向 plugin 业务层抛异常。

4. **PromptTemplateParser 特殊变量命名约定（约束驱动而非自由命名）** — Dify 源 `prompt_template_parser.py` 仅允许 `{{#histories#}}` `{{#query#}}` `{{#context#}}` 三个特殊键，业务模板需要别的"上下文"必须显式声明在 `custom_variable_keys` 里 → 本项目 target 三个 plugin 模板共用 4 个固定 placeholder（`{{markdown}}` `{{document_id}}` `{{author_id}}` `{{workspace_users_hint}}`），并在 helper 里维护白名单常量 `_ALLOWED_KEYS = frozenset([...])`，模板里出现白名单外的变量直接 raise（仅在测试/启动时，不在请求时）—— 提前发现 typo，避免 LLM 拿到 `{{authorid}}` 这种残留 placeholder。

5. **provider 错误归一化 + 全 Exception 兜底返回 fallback** — Dify 源 `llm_generator.py:201-202` 对 `InvokeAuthorizationError` 直接 `return []`、`233-236` 对其他 `Exception` 走 `logger.exception` 后返回 `questions = []` → 本项目 target `llm_mention_helper.suggest_mentions_via_llm`：catch 项目已实现的 `LLMClientError` 全家族（`LLMAuthError` / `LLMRateLimitError` / `LLMServerError` / `LLMTimeoutError` / `LLMBadRequestError` / `LLMContextTooLongError`，见 `backend/app/agent_builder/workflow/llm_client.py:46-72`）→ 统一返回空 `list[MentionSuggestion]` + `logger.info("platform.plugin.invoke", extra={...outcome="llm_failure", error_class=type(exc).__name__})`，schema 对齐 Phase 5.B `PlatformDaemonClient` 已埋点的 5 字段（plugin_name / workspace_id / capability / method / latency_ms / outcome，外加失败时的 error_class）。

## 与本项目的关系

本 plan 的 `llm_mention_helper.suggest_mentions_via_llm(prompt_path, markdown, context, *, plugin_name, llm_model)` 是把 Dify 上面 3 个文件（`prompt_template_parser.py` + `simple_prompt_transform.py` + `llm_generator.py`）的核心管线**收敛到单一函数**：

- **借鉴点 #1** 落地于 `load_prompt_template()` 内部 —— 严格变量白名单 + markdown `{` escape，避免 `KeyError`/prompt 注入。
- **借鉴点 #2** 落地于"按 `## SYSTEM` / `## USER` 切模板 → 拼 OpenAI messages"两步 —— 对接 `call_llm()` 已有签名，不引入新的 `PromptMessage` 抽象。
- **借鉴点 #3** 落地于 `_parse_suggestions(content_str)` —— `json.loads` → `json_repair.loads` → 空 list fallback 三段式。
- **借鉴点 #4** 落地于 helper 顶层 `_ALLOWED_KEYS` 常量 + 单测覆盖（template 含 unknown placeholder 时启动阶段 raise）。
- **借鉴点 #5** 落地于 helper 外层 `try/except LLMClientError as exc` —— 返回空 list + structured log，对齐 Pattern 7 schema 与 Phase 5.B `daemon_client.py:466-472` 的 outcome 取值（扩展 `"llm_failure"` / `"parse_failure"`）。

**memory `feedback_capability_design` 的落地**：Dify 在 `LLMGenerator` 里**为每种内置能力写一个 classmethod**（`generate_conversation_name` / `generate_suggested_questions_after_answer` / `generate_rule_config` …），那是因为它每种能力的 prompt / parser / fallback 差异都很大；而本项目 `ai_suggest_mentions` 在 3 个 plugin 上**只有 prompt 文件不同**（input/output schema、parse 逻辑、fallback 策略完全一致），所以**不为每个 plugin 写 `OutlineAISuggestor` / `LarkAISuggestor` 类**，而是单一 `suggest_mentions_via_llm` helper + 每个 plugin 传不同的 `prompt_path` + `plugin_name`。每个 plugin 的 `ai_suggest_mentions` 方法实际只有 1 行 `return await suggest_mentions_via_llm(...)`。`HulyPlugin` 因 SocialIdentity 复杂查询本期不做，直接 `raise NotImplementedError("DocCapability v1.1, ai_suggest_mentions for Huly deferred")`。

**Pattern 7 structured log 对齐说明**：Dify 用 `core.ops.ops_trace_manager.TraceQueueManager` + `TraceTask` 管理 LLM 调用追踪（含 tenant_id / app_id / timer 等），属重型方案；本项目在 Phase 5.B 已落地轻量 structured log（`logger.info("platform.plugin.invoke", extra={plugin_name, workspace_id, capability, method, latency_ms, outcome})`）。本 plan helper 在调用前后用 `time.perf_counter()` 包夹 `await call_llm(...)` 计算 `latency_ms`，无论 success / llm_failure / parse_failure 都恰好打一条 log（Phase 7 Run Viewer 即可消费）。**outcome 取值集合**对齐 daemon_client.py:466 已用的 `success` / `error` / `timeout` / `blocked`，本 plan 扩展两个新值：`llm_failure`（catch 到 `LLMClientError` 子类时）+ `parse_failure`（LLM 返回非合法 JSON 且 `json_repair` 也失败时）—— 这两个值需要在 Phase 7 Run Viewer 的 outcome 枚举里同步登记。

**测试落点说明**：
- unit tests (`tests/platforms/test_ai_suggest_mentions.py`) 通过 monkeypatch `call_llm` 验证借鉴点 #3（parse 成功/失败）+ #5（5 种 `LLMClientError` 子类的 fallback）+ structured log 字段完整性（用 `caplog` fixture 断言 extra dict）
- integration tests (`tests/platforms_integration/test_ai_suggest_mentions_llm_integration.py`) 用 `pytest.mark.skipif(not os.getenv("ZHIPUAI_API_KEY"))` 真调 `zhipuai:glm-4-flash` 免费档（与 Phase 2.05 已有 LLM provider 校验一致），覆盖 Outline / Lark 各 1 个真 markdown 样本，断言返回 `list[MentionSuggestion]` 非空 + outcome="success" log 落地

**License attribution**: Dify 是 **AGPL-3.0**；本项目 agent-builder 是 **Apache-2.0**（与上游 flock 一致）。本 plan **仅借鉴上述 5 条设计模式 / 变量命名约定 / fallback 思路**，不拷贝任何 Dify 源代码字符；所有借鉴点已明确写出 source file (路径 + 行号) → target module (项目内文件) 的对应关系，便于 reviewer 与未来 audit 追溯。`llm_mention_helper.py` 文件顶部 docstring 与 plan SUMMARY 的 "Dify 参考点" 小节都会指回本 reading doc 路径；3 个 plugin 的 `prompts/ai_suggest_mentions_zh.md` 模板均为本项目原创（基于 OpenAI 通用 prompt 习惯 + 项目自身 UserRef schema），不参考任何 Dify 内置 prompt 文字内容。
