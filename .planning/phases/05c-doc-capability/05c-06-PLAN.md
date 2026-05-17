---
phase: 05c-doc-capability
plan: 06
type: execute
wave: 4
depends_on: ["03", "04", "05"]
files_modified:
  - docs/reading-dify-05c-06-ai-suggest-mentions-2026-05-18.md
  - backend/app/plugins/_common/__init__.py
  - backend/app/plugins/_common/doc_capability_v1_1.py
  - backend/app/plugins/_common/mention_suggestion.py
  - backend/app/plugins/_common/llm_mention_helper.py
  - backend/app/plugins/outline/prompts/ai_suggest_mentions_zh.md
  - backend/app/plugins/outline/outline_plugin.py
  - backend/app/plugins/lark_docs/prompts/ai_suggest_mentions_zh.md
  - backend/app/plugins/lark_docs/lark_docs_plugin.py
  - backend/app/plugins/huly/huly_plugin.py
  - backend/app/plugins/huly/prompts/ai_suggest_mentions_zh.md
  - tests/platforms/test_ai_suggest_mentions.py
  - tests/platforms_integration/test_ai_suggest_mentions_llm_integration.py
autonomous: true
requirements:
  - DOC-AI-01
must_haves:
  truths:
    - "Dify LLM 节点 + PromptTemplateParser 阅读文档已 commit（CLAUDE.md §2.7 硬性 gate）"
    - "DocCapability v1.1 Protocol 扩展 ai_suggest_mentions 方法，原 v1 Protocol（plan 03/04/05 已 freeze）零改"
    - "MentionSuggestion dataclass(frozen=True) 含 user_ref / confidence / rationale 三字段，可被 plugins/tests 共享 import"
    - "llm_mention_helper 公共助手存在 — 1 个函数完成 prompt 加载 + LLM call + structured output parse + 失败 fallback log"
    - "OutlinePlugin.ai_suggest_mentions 真实现 — 加载本 plugin 的 prompts/ai_suggest_mentions_zh.md + 调 call_llm（GLM Flash 默认）+ 返回 MentionSuggestion list"
    - "LarkDocsPlugin.ai_suggest_mentions 真实现 — 同模式，prompt 模板独立"
    - "HulyPlugin.ai_suggest_mentions 留 stub 单行 raise NotImplementedError（v1.1 因 SocialIdentity 复杂查询本期不做）"
    - "LLM 调用失败时（auth/rate-limit/timeout 任一）返回空 list，不 raise 给业务；同时写一条 structured log outcome=llm_failure"
    - "structured log 字段全：plugin_name / workspace_id / capability=doc / method=ai_suggest_mentions / latency_ms / outcome / error_class（失败时）"
    - "unit tests mock call_llm — 验证 prompt 加载路径 + structured output parse + 失败 fallback + log schema"
    - "integration tests 真调 GLM-Flash 免费档 — Outline + Lark 各 1 个 markdown 样本走通"
    - "Phase 5.A 271 platforms tests + Phase 5.B 5/5 acid + Phase 5.C plan 02-05 全 plugin spawn regression 全绿（0 接口破坏）"
  artifacts:
    - path: "docs/reading-dify-05c-06-ai-suggest-mentions-2026-05-18.md"
      provides: "Dify llm_generator + PromptTemplateParser 5 节阅读文档（≥80 行，含 5 借鉴点 + AGPL/Apache attribution）"
      min_lines: 80
    - path: "backend/app/plugins/_common/doc_capability_v1_1.py"
      provides: "DocCapability v1.1 — 单独文件防 conflict with plan 03/04/05 已 freeze 的 v1 Protocol；用 Protocol 继承 + 加 ai_suggest_mentions optional method"
      exports: ["DocCapabilityV1_1"]
    - path: "backend/app/plugins/_common/mention_suggestion.py"
      provides: "MentionSuggestion dataclass(frozen=True) 含 user_ref: UserRef / confidence: float / rationale: str"
      exports: ["MentionSuggestion"]
    - path: "backend/app/plugins/_common/llm_mention_helper.py"
      provides: "公共助手 suggest_mentions_via_llm(prompt_path, markdown, context, *, plugin_name, llm_model) -> list[MentionSuggestion] — 单函数完成全流程"
      exports: ["suggest_mentions_via_llm", "load_prompt_template"]
    - path: "backend/app/plugins/outline/prompts/ai_suggest_mentions_zh.md"
      provides: "OutlinePlugin 专用 ai_suggest_mentions 系统提示（中文，要求 LLM 返回 JSON {suggestions:[{user_id,confidence,rationale}]}）"
      min_lines: 30
    - path: "backend/app/plugins/lark_docs/prompts/ai_suggest_mentions_zh.md"
      provides: "LarkDocsPlugin 专用 ai_suggest_mentions 系统提示（强调 lark_open_id 格式 + 中文）"
      min_lines: 30
    - path: "backend/app/plugins/huly/prompts/ai_suggest_mentions_zh.md"
      provides: "HulyPlugin 占位 prompt 模板（仅 1 行说明 v1.1 stub），保 plugin folder layout 一致"
      contains: "v1.1"
    - path: "backend/app/plugins/outline/outline_plugin.py"
      provides: "OutlinePlugin.ai_suggest_mentions 方法 — 调 llm_mention_helper.suggest_mentions_via_llm + plugin-local prompt 路径"
      contains: "ai_suggest_mentions"
    - path: "backend/app/plugins/lark_docs/lark_docs_plugin.py"
      provides: "LarkDocsPlugin.ai_suggest_mentions 方法 — 同模式"
      contains: "ai_suggest_mentions"
    - path: "backend/app/plugins/huly/huly_plugin.py"
      provides: "HulyPlugin.ai_suggest_mentions = NotImplementedError 单行 stub（v1.1）"
      contains: "NotImplementedError"
    - path: "tests/platforms/test_ai_suggest_mentions.py"
      provides: "unit tests 14+ cases — 3 plugin × {prompt 加载 / parse 成功 / parse 失败 fallback / LLM error fallback / structured log schema} + HulyPlugin NotImplementedError"
      contains: "test_outline_ai_suggest_mentions"
    - path: "tests/platforms_integration/test_ai_suggest_mentions_llm_integration.py"
      provides: "integration tests 4 cases — Outline + Lark 各跑真 GLM-Flash 调用（skipif env not set）+ assert 返回 list[MentionSuggestion] 非空 + structured log outcome=success"
      contains: "test_outline_real_glm_flash"
  key_links:
    - from: "backend/app/plugins/_common/llm_mention_helper.py"
      to: "backend/app/agent_builder/workflow/llm_client.py"
      via: "from app.agent_builder.workflow.llm_client import call_llm, LLMClientError 复用 Phase 2.05 已有 LLM abstraction（GLM / OpenAI / Anthropic 全覆盖）"
      pattern: "from app.agent_builder.workflow.llm_client import call_llm"
    - from: "backend/app/plugins/_common/llm_mention_helper.py"
      to: "backend/app/agent_builder/platforms/capabilities/doc.py"
      via: "import UserRef 构造 MentionSuggestion.user_ref；不重新定义 UserRef"
      pattern: "from app.agent_builder.platforms.capabilities.doc import UserRef"
    - from: "backend/app/plugins/_common/llm_mention_helper.py"
      to: "logger.info 'platform.plugin.invoke'"
      via: "structured log 字段 (plugin_name / workspace_id / capability=doc / method=ai_suggest_mentions / latency_ms / outcome) 对齐 Phase 5.B PlatformDaemonClient.invoke 已埋点 schema（Pattern 7）"
      pattern: "logger.info.*platform.plugin.invoke.*extra="
    - from: "backend/app/plugins/outline/outline_plugin.py"
      to: "backend/app/plugins/_common/llm_mention_helper.py"
      via: "OutlinePlugin.ai_suggest_mentions 1 行 delegate — await suggest_mentions_via_llm(prompt_path=..., markdown=..., context=..., plugin_name='outline')"
      pattern: "from app.plugins._common.llm_mention_helper import suggest_mentions_via_llm"
    - from: "backend/app/plugins/lark_docs/lark_docs_plugin.py"
      to: "backend/app/plugins/_common/llm_mention_helper.py"
      via: "同 Outline 模式 — 复用 helper，仅 prompt 路径 + plugin_name 不同"
      pattern: "from app.plugins._common.llm_mention_helper import suggest_mentions_via_llm"
    - from: "backend/app/plugins/_common/doc_capability_v1_1.py"
      to: "backend/app/agent_builder/platforms/capabilities/doc.py"
      via: "DocCapabilityV1_1(DocCapability, Protocol) — 继承 v1 + 加 ai_suggest_mentions；plan 03/04/05 已 freeze 的 v1 facade 0 改动"
      pattern: "class DocCapabilityV1_1.*DocCapability"
---

<objective>
为 DocCapability 添加 v1.1 `ai_suggest_mentions(markdown, context) -> list[MentionSuggestion]` LLM 钩子真实现，让 3 个文档平台 plugin (Outline / Lark Docs / Huly) 能在 doc_write 节点配置时辅助用户选 @ 谁。

复用 Phase 2.05 已有 `call_llm` LangChain abstraction（GLM / OpenAI / Anthropic 全覆盖），用统一的 prompt 模板机制（**memory feedback_capability_design**：简单 LLM 能力不为每个 plugin 单独写类，用 prompt 模板 + 公共 helper）。

Purpose:
- ADR-001 §3.2 v1.1 留接口，本 plan 把 Outline / Lark 真实现 + Huly 留 v1.1 stub（SocialIdentity 复杂查询本期不做）
- 失败 fallback：返回空 list + structured log，**不阻塞业务**（节点配置 UI 静默退化为手动选 @）
- Pattern 7 structured log 对齐：plugin_name / workspace_id / capability / method / latency_ms / outcome 5 字段全（Phase 7 Run Viewer 钩子）

Output: Dify reading doc（Task 0 硬性 gate）+ DocCapability v1.1 Protocol + MentionSuggestion dataclass + 公共 llm_mention_helper + 3 plugin prompt 模板 + 3 plugin ai_suggest_mentions impl（2 真 + 1 stub）+ 14+ unit tests + 4 integration tests（真 GLM-Flash 调用）。
</objective>

<execution_context>
@/Users/admin/.claude/get-shit-done/workflows/execute-plan.md
@/Users/admin/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/05c-doc-capability/05c-CONTEXT.md
@.planning/phases/05c-doc-capability/05c-RESEARCH.md
@docs/plans/2026-05-17-platform-plugin-framework-ADR.md
@backend/app/agent_builder/platforms/capabilities/doc.py
@backend/app/agent_builder/workflow/llm_client.py

<!-- 假设 plan 03/04/05 已就绪：3 个 plugin daemon 入口 + prompts/ai_suggest_mentions_zh.md 占位 stub -->
@backend/app/plugins/outline/outline_plugin.py
@backend/app/plugins/lark_docs/lark_docs_plugin.py
@backend/app/plugins/huly/huly_plugin.py

<interfaces>
<!-- 关键 type / Protocol / 调用约定，executor 直接使用，无需进一步探索 -->

From backend/app/agent_builder/platforms/capabilities/doc.py（Plan 02 已 freeze，本 plan 0 改动）:
```python
@runtime_checkable
class DocCapability(Protocol):
    name: str
    supports_collaborative_edit: bool
    supports_comments: bool

    async def create_document(self, *, title: str, markdown: str, owners: list[UserRef] | None = None) -> DocRef: ...
    async def replace_document_content(self, doc_ref: DocRef, markdown: str) -> None: ...
    async def apply_document_delta(self, doc_ref: DocRef, delta: CRDTDelta) -> None: ...
    async def add_comment(self, *, doc_ref: DocRef, body: str, mentions: list[UserRef] | None = None) -> CommentRef: ...
    async def get_document(self, doc_ref: DocRef) -> DocInfo | None: ...

@dataclass(frozen=True)
class UserRef:
    plugin_name: str
    native_id: str
```

From backend/app/agent_builder/workflow/llm_client.py（Phase 2.05 已 freeze）:
```python
async def call_llm(
    model_str: str,                              # 如 "zhipuai:glm-4-flash" / "openai:gpt-4o-mini"
    messages: list[dict[str, Any]],              # [{"role": "system", "content": ...}, {"role": "user", ...}]
    *, retry_count: int = 3, **kwargs: Any,
) -> AIMessage:                                  # .content: str, .usage_metadata, .response_metadata

class LLMClientError(Exception): ...
class LLMAuthError(LLMClientError): ...           # 认证 — 不重试
class LLMRateLimitError(LLMClientError): ...      # 429 — 重试后失败抛
class LLMServerError(LLMClientError): ...         # 5xx — 重试后失败抛
class LLMTimeoutError(LLMClientError): ...        # timeout — 重试后失败抛
class LLMBadRequestError(LLMClientError): ...     # 400/422 — 不重试
class LLMContextTooLongError(LLMClientError): ... # 上下文超长 — 不重试

# 已配置 provider 检查
def check_llm_provider_envs() -> list[str]: ...  # ["zhipuai", "openai", ...]
```

From Phase 5.B PlatformDaemonClient（Pattern 7 structured log schema 标准 — daemon_client.py:466-472）:
```python
_log.info(
    "daemon.invoke capability=%s method=%s latency_ms=%d outcome=%s",
    capability, method, latency_ms, outcome,
)
# outcome 取值: "success" | "error" | "timeout" | "blocked"
# 本 plan 在 helper 内补：outcome="success" / "llm_failure" / "parse_failure"
```

Decision (Pattern 10 + Discretion 5)：本 plan 直接在**主进程**（plugin 实例方法）调 LLM，不进 daemon。理由：
- Pitfall 8（daemon 跨进程隔离）— daemon 内调 LLM 需 spawn 时注入所有 LLM env vars，且 LangChain 依赖较重，daemon 启动慢
- ai_suggest_mentions 是**节点配置时**调用（非节点运行时），不在 hot path，主进程调更简单
- 各 plugin 类 `class OutlinePlugin` 在主进程实例化（plan 03/04/05 已建），调 LLM 直接复用 Phase 2.05 路径

Memory feedback_capability_design 应用：
- 不为 Outline / Lark 各写一个 `OutlineAISuggestor` / `LarkAISuggestor` 类
- 只有一个公共 helper `suggest_mentions_via_llm(prompt_path, markdown, context, *, plugin_name, llm_model)`
- 每个 plugin 的 `ai_suggest_mentions` 方法 = 1 行 delegate 到 helper + 传 plugin-local prompt 路径
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 0: Dify LLM 节点 + PromptTemplateParser 阅读文档（CLAUDE.md §2.7 硬性 gate）</name>
  <files>docs/reading-dify-05c-06-ai-suggest-mentions-2026-05-18.md</files>
  <action>
**STOP — 这是后续所有 commit 的前置 gate**。先 commit 此文档才允许写代码（CLAUDE.md §2.7）。

读以下 Dify 源文件（仅 Read 不 grep，重点理解设计模式 — 不要拷贝代码，AGPL-3.0 vs Apache-2.0 严禁拷源）：

1. `/Users/admin/ai/ref/dify/repo/api/core/prompt/utils/prompt_template_parser.py` (~120 行) — `PromptTemplateParser` 正则 + variable inject 机制
2. `/Users/admin/ai/ref/dify/repo/api/core/prompt/simple_prompt_transform.py` — simple prompt 渲染 + variable 替换 + 拼装 messages 列表
3. `/Users/admin/ai/ref/dify/repo/api/core/prompt/advanced_prompt_transform.py` (前 200 行即可) — 高级 prompt 渲染 / system + user 模板组合
4. `/Users/admin/ai/ref/dify/repo/api/core/llm_generator/llm_generator.py` (重点 `class LLMGenerator` 方法) — LLM 调用入口 + 结构化输出 parse + 失败 fallback 模式
5. `/Users/admin/ai/ref/dify/repo/api/core/workflow/nodes/llm/` (如 entities/) — LLM 节点配置 + structured output config (注意：仓库版本中 nodes/llm 已被重构，参考 entities + tests/unit_tests/core/workflow/nodes/llm/test_llm_utils.py 中的调用模式)

写到 `docs/reading-dify-05c-06-ai-suggest-mentions-2026-05-18.md`，**完全按 CLAUDE.md §2.7 阅读文档模板**：

```markdown
# Dify 阅读笔记 — LLM 节点 + PromptTemplateParser

> 日期: 2026-05-18
> 仓库: https://github.com/langgenius/dify (local clone /Users/admin/ai/ref/dify/repo/, AGPL-3.0)
> Stars: ~141k

## 项目概述（一句话）
Dify 是国内最成熟的开源 LLM 应用平台；LLM 节点 + PromptTemplateParser 是其工作流引擎的核心 — 把 markdown / 变量 / 上下文渲染为 messages list 后调 model provider，并对结构化输出（JSON）做 parse + 失败回退。

## 技术栈（关键技术选择）
- PromptTemplateParser: 正则 `{{var}}` + `{{#histories#/#query#/#context#}}` 4 种特殊变量
- LLMGenerator: 单点入口（rule_config / suggested_questions / code generate）
- 模型层: model_manager 抽象多 provider (OpenAI / Azure / 等)，与本项目 LangChain init_chat_model 同类
- 结构化输出: 让 LLM 返回 JSON / YAML，python 端 json.loads 解析，失败时 fallback 到默认值 / 空结构

## 架构要点
（简图 + 文字说明 3-4 层结构：prompt template → variable inject → message build → model call → structured output parse → fallback）

## 可借鉴的设计模式
1. **PromptTemplateParser 正则 + 变量名长度/字符约束**（utils/prompt_template_parser.py REGEX 行）— 防 prompt 注入和模板错误 → 本 plan 借鉴：load_prompt_template 用 str.format(**context) 而不是直接拼 f-string，对 markdown 中可能出现的 `{` 做 escape
2. **simple_prompt_transform messages 拼装** — system 模板 + user 模板分离，inject variables 后拼成 OpenAI messages list → 本 plan 借鉴：prompt 模板分两段 `--- system ---` `--- user ---`（用 H2 markdown header 分隔）
3. **LLMGenerator JSON 结构化输出 fallback**（llm_generator.py rule_config 方法）— LLM 返回 JSON 时 `json.loads` 失败 → 返回默认空 dict，不 raise → 本 plan 借鉴：parse failure 返回空 `list[MentionSuggestion]` + 写 log
4. **advanced_prompt_transform 多轮 history 注入** — `{{#histories#}}` 占位符替换为历史消息序列 → 本 plan v1 不用 history（ai_suggest_mentions 是单轮调用），但 placeholder 命名约定借鉴：`{{document_id}}` `{{author_id}}` `{{markdown}}` 三个标准变量
5. **LLMGenerator timeout + provider 错误隔离**（llm_generator 内 try/except 模式）— LLM provider invocation 失败时不让上层崩溃，封装为统一异常 → 本 plan 借鉴：catch `LLMClientError` 全家族 → 返回空 list + outcome="llm_failure" structured log

## 与本项目的关系
本 plan 实现 `llm_mention_helper.suggest_mentions_via_llm`：
- 用借鉴点 #1 安全加载 prompt（避开 markdown 中的 `{` 引发 KeyError）
- 用借鉴点 #2 把 prompt 模板 split 为 system + user 两段 messages
- 用借鉴点 #3 parse LLM 返回的 JSON `{suggestions:[{user_id, confidence, rationale}]}`，失败时 fallback 到空 list
- 用借鉴点 #4 的变量命名约定，3 plugin prompt 模板共用 `{{markdown}}` `{{document_id}}` `{{author_id}}` `{{workspace_users_hint}}` 4 个变量
- 用借鉴点 #5 catch `LLMClientError` 全家族 → 返回空 list + structured log

**License attribution**: Dify 是 AGPL-3.0；本项目 Apache-2.0；本 plan 仅借鉴**设计模式 / 变量命名约定 / fallback 思路**，不拷贝任何 Dify 源代码。每条借鉴点已明确写出 source file → target module 的对应关系。
```

文档要求：
- **至少 80 行** + 5 个借鉴点必须明确写出 source file → target module 的对应关系
- **不要**贴 Dify 源代码片段（AGPL-3.0 License 防御）
- 末段 License attribution 段必须存在
- 5 节标准模板：项目概述 / 技术栈 / 架构要点 / 可借鉴的设计模式 / 与本项目的关系
  </action>
  <verify>
    <automated>test -f docs/reading-dify-05c-06-ai-suggest-mentions-2026-05-18.md && wc -l docs/reading-dify-05c-06-ai-suggest-mentions-2026-05-18.md | awk '{exit ($1 >= 80 ? 0 : 1)}' && grep -q "AGPL\|Apache-2.0" docs/reading-dify-05c-06-ai-suggest-mentions-2026-05-18.md && grep -q "可借鉴的设计模式" docs/reading-dify-05c-06-ai-suggest-mentions-2026-05-18.md && grep -c "^[0-9]\.\|^### [0-9]" docs/reading-dify-05c-06-ai-suggest-mentions-2026-05-18.md | awk '{exit ($1 >= 5 ? 0 : 1)}'</automated>
  </verify>
  <done>Reading doc ≥ 80 行 + 含 License attribution + 含可借鉴的设计模式章节 + ≥ 5 个借鉴点 + git commit hash 早于后续 Task 1+ commit hash</done>
</task>

<task type="auto">
  <name>Task 1: DocCapability v1.1 Protocol 扩展 + MentionSuggestion dataclass</name>
  <files>backend/app/plugins/_common/__init__.py,backend/app/plugins/_common/doc_capability_v1_1.py,backend/app/plugins/_common/mention_suggestion.py</files>
  <action>
Reading doc 已 commit ✓（CLAUDE.md §2.7 gate 通过），开始写代码。

1. **创建 `backend/app/plugins/_common/__init__.py`** （空 package marker，1 行 docstring）:
```python
"""Phase 5.C plugins 共享代码 — 跨 plugin 复用的 helper / Protocol 扩展 / 值对象。

放在 backend/app/plugins/_common/ 下而非 agent_builder/platforms/，因为：
- agent_builder/platforms/capabilities/doc.py 是 Plan 02 已 freeze 的 v1 Protocol，本 plan 0 改动
- 本 plan 的 v1.1 扩展 + helper 属于"per-plugin 实现层"的共享代码，按 plugins 目录组织
"""
```

2. **`backend/app/plugins/_common/mention_suggestion.py`**:
```python
"""MentionSuggestion 值对象 — DocCapability v1.1 ai_suggest_mentions 返回类型。

CLAUDE.md immutability: dataclass(frozen=True)
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agent_builder.platforms.capabilities.doc import UserRef


@dataclass(frozen=True)
class MentionSuggestion:
    """LLM 建议的 mention 候选。

    Attributes:
        user_ref: 候选用户 handle（plugin_name + native_id）
        confidence: LLM 自评的推荐置信度（0.0-1.0，调用方可按阈值过滤）
        rationale: 简短自然语言说明（"作者上下文提到 @ 张三审核此设计"）
    """

    user_ref: UserRef
    confidence: float
    rationale: str
```

3. **`backend/app/plugins/_common/doc_capability_v1_1.py`** —— v1.1 Protocol 扩展，**Plan 02 v1 Protocol 0 改动**:
```python
"""DocCapability v1.1 Protocol — 在 Plan 02 v1 基础上扩展 ai_suggest_mentions 方法。

设计要点（critical_constraint #2 — 不破坏 plan 03/04/05 已 freeze 的 v1 facade）：
- 用 Protocol 继承（DocCapabilityV1_1(DocCapability, Protocol)）而非修改 v1
- ai_suggest_mentions 是 optional method —— 调用方应先 isinstance check 或 hasattr 检查
- v1.1 是设计 forward-compat 入口，v2 时把 ai_suggest_mentions 提升到必需

ADR-001 §3.2 v1.1 留接口的对应实现（Phase 5.C plan 06）。

Reference: docs/reading-dify-05c-06-ai-suggest-mentions-2026-05-18.md
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.agent_builder.platforms.capabilities.doc import DocCapability

from .mention_suggestion import MentionSuggestion


@runtime_checkable
class DocCapabilityV1_1(DocCapability, Protocol):
    """DocCapability v1.1 — 在 v1 基础上加 ai_suggest_mentions optional method。

    Plugin 实现 v1.1 时仍需实现 v1 全部方法（继承约束）。
    Plugin 不实现 ai_suggest_mentions 时（如 HulyPlugin v1.1），可定义方法直接 raise NotImplementedError。
    """

    async def ai_suggest_mentions(
        self,
        *,
        markdown: str,
        context: dict,
    ) -> list[MentionSuggestion]:
        """LLM 推荐 mentions —— 给定文档 markdown + 上下文，返回候选 @ 用户列表。

        Args:
            markdown: 当前文档正文 Markdown（节点配置时为草稿，运行时为已 replace 后内容）
            context: 上下文 dict，约定 keys:
                - workspace_id: str (uuid)
                - document_id: str | None (文档 id，create 时 None)
                - author_id: str (调用方用户 id)
                - workspace_users_hint: list[str] | None (workspace 内候选用户 hint, e.g. usernames)
                - llm_model: str | None (override 默认模型，如 "zhipuai:glm-4-flash")

        Returns:
            list[MentionSuggestion]: LLM 推荐列表（可空）。
            失败 fallback（LLM error / parse error）：返回空 list 并写 structured log，
            **不** raise 给业务层（节点配置 UI 静默退化为手动选 @）。
        """
        ...
```

4. **更新 `backend/app/plugins/_common/__init__.py`** 末尾 re-export:
```python
from .doc_capability_v1_1 import DocCapabilityV1_1
from .mention_suggestion import MentionSuggestion

__all__ = ["DocCapabilityV1_1", "MentionSuggestion"]
```

5. **关键 import 路径校验** — `app.agent_builder.platforms.capabilities.doc.UserRef` 必须能 import 成功（已 Phase 5.A Plan 02 落地）。

代码风格：black + ruff + mypy 必须通过。**严禁**修改 `app/agent_builder/platforms/capabilities/doc.py`（plan 03/04/05 已 freeze）。
  </action>
  <verify>
    <automated>cd backend && python -c "from app.plugins._common import DocCapabilityV1_1, MentionSuggestion; from app.agent_builder.platforms.capabilities.doc import UserRef; m = MentionSuggestion(user_ref=UserRef(plugin_name='test', native_id='u1'), confidence=0.9, rationale='test'); assert m.confidence == 0.9; print('OK')" && cd /Users/admin/ai/resume/interview/liuxin/agent-builder && git diff --name-only HEAD -- backend/app/agent_builder/platforms/capabilities/doc.py | wc -l | awk '{exit ($1 == 0 ? 0 : 1)}'</automated>
  </verify>
  <done>3 个文件存在；DocCapabilityV1_1 + MentionSuggestion 可 import；frozen dataclass 不可 mutate；**plan 02 的 doc.py 0 改动**（git diff 校验）；black/ruff/mypy 通过</done>
</task>

<task type="auto">
  <name>Task 2: llm_mention_helper 公共助手（prompt 加载 + LLM call + parse + fallback log）</name>
  <files>backend/app/plugins/_common/llm_mention_helper.py</files>
  <action>
实现公共 helper —— 这是 **memory feedback_capability_design** 的核心落地（不为每个 plugin 单独写 LLM 类，统一封装）。

`backend/app/plugins/_common/llm_mention_helper.py`:

```python
"""ai_suggest_mentions LLM 调用公共助手 —— 3 plugin 共用。

设计要点（Pattern 10 + memory feedback_capability_design）：
- 不为每 plugin 写独立 LLM 类 —— 用 prompt 模板 + 单一 helper function
- 失败 fallback：返回空 list + structured log（不 raise 给业务）
- structured log schema 对齐 Phase 5.B PlatformDaemonClient.invoke（Pattern 7）
- prompt 模板用借鉴 Dify PromptTemplateParser 的 `{{variable}}` 双花括号约定
  + 4 个标准变量: {{markdown}} {{document_id}} {{author_id}} {{workspace_users_hint}}

Reference: docs/reading-dify-05c-06-ai-suggest-mentions-2026-05-18.md
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from app.agent_builder.platforms.capabilities.doc import UserRef
from app.agent_builder.workflow.llm_client import (
    LLMClientError,
    call_llm,
)

from .mention_suggestion import MentionSuggestion

_log = logging.getLogger("agent_builder.platform_plugin")

# Pattern 7: workspace_id 通过 contextvars 注入（FastAPI middleware 设置 → 各层透传）
# 与 daemon_client 的 structured log 字段对齐
current_workspace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_workspace_id", default=None
)

# 默认模型 —— GLM-Flash 是免费档（user constraint Critical #4）
DEFAULT_LLM_MODEL = os.environ.get("AI_SUGGEST_MENTIONS_MODEL", "zhipuai:glm-4-flash")

# Prompt 模板分隔符（借鉴点 #2 — system + user 两段分离，避免 hard-code 两份）
_SYSTEM_SECTION_RE = re.compile(r"^##?\s*system\s*$", re.IGNORECASE | re.MULTILINE)
_USER_SECTION_RE = re.compile(r"^##?\s*user\s*$", re.IGNORECASE | re.MULTILINE)

# Prompt 变量正则（借鉴 Dify PromptTemplateParser，但简化为本 plan 4 个变量）
_VARIABLE_RE = re.compile(r"\{\{(markdown|document_id|author_id|workspace_users_hint)\}\}")


def load_prompt_template(prompt_path: Path) -> tuple[str, str]:
    """读 plugin-local prompt 模板，split 为 (system_prompt, user_template)。

    模板格式约定（参考 Dify simple_prompt_transform）:
    ```
    # system
    你是文档协作 @ 推荐助手...

    # user
    文档内容：
    {{markdown}}
    ...
    ```

    Args:
        prompt_path: prompt 模板文件路径（plugin 自带，如 plugins/outline/prompts/ai_suggest_mentions_zh.md）

    Returns:
        (system_prompt_text, user_template_text)
        若文件不含明确的 # system / # user 分段：整个文件作为 user_template，system_prompt = ""

    Raises:
        FileNotFoundError: prompt 文件不存在（调用方应预检）
    """
    text = prompt_path.read_text(encoding="utf-8")

    sys_match = _SYSTEM_SECTION_RE.search(text)
    user_match = _USER_SECTION_RE.search(text)

    if sys_match and user_match:
        system_text = text[sys_match.end() : user_match.start()].strip()
        user_text = text[user_match.end() :].strip()
    else:
        system_text = ""
        user_text = text.strip()

    return system_text, user_text


def _render_user_template(template: str, context: dict[str, Any], markdown: str) -> str:
    """把 {{markdown}} {{document_id}} {{author_id}} {{workspace_users_hint}} 替换为 context 值。

    借鉴点 #1：用 re.sub 而非 str.format —— markdown 内可能有 `{` 字符会让 str.format raise KeyError。

    Args:
        template: user prompt 模板（含 {{var}} 占位符）
        context: 调用方 context dict
        markdown: 文档正文

    Returns:
        渲染后的 user prompt 文本
    """
    values = {
        "markdown": markdown,
        "document_id": str(context.get("document_id") or ""),
        "author_id": str(context.get("author_id") or ""),
        "workspace_users_hint": json.dumps(
            context.get("workspace_users_hint") or [], ensure_ascii=False
        ),
    }

    def _sub(match: re.Match[str]) -> str:
        return values.get(match.group(1), "")

    return _VARIABLE_RE.sub(_sub, template)


def _parse_llm_response(content: str, *, plugin_name: str) -> list[MentionSuggestion]:
    """Parse LLM 返回的 JSON 结构 → list[MentionSuggestion]。

    期望 schema:
        {"suggestions": [{"user_id": "...", "confidence": 0.9, "rationale": "..."}]}

    借鉴点 #3：parse 失败 fallback 空 list（不 raise）。

    Args:
        content: LLM 返回的 raw 文本
        plugin_name: 当前 plugin 名（用于 MentionSuggestion.user_ref.plugin_name）

    Returns:
        list[MentionSuggestion]（可空）
    """
    # 容错：LLM 可能在 JSON 外包 ```json ... ``` 代码块，提取大括号区段
    json_start = content.find("{")
    json_end = content.rfind("}")
    if json_start < 0 or json_end < 0 or json_end <= json_start:
        return []

    try:
        data = json.loads(content[json_start : json_end + 1])
    except json.JSONDecodeError:
        return []

    raw_list = data.get("suggestions")
    if not isinstance(raw_list, list):
        return []

    result: list[MentionSuggestion] = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        user_id = item.get("user_id")
        if not isinstance(user_id, str) or not user_id:
            continue

        # confidence 默认 0.5，clamp 到 [0, 1]
        try:
            confidence = float(item.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))

        rationale = item.get("rationale")
        if not isinstance(rationale, str):
            rationale = ""

        result.append(
            MentionSuggestion(
                user_ref=UserRef(plugin_name=plugin_name, native_id=user_id),
                confidence=confidence,
                rationale=rationale,
            )
        )
    return result


def _log_outcome(
    *,
    plugin_name: str,
    latency_ms: int,
    outcome: str,
    error_class: str | None = None,
    suggestion_count: int = 0,
) -> None:
    """Pattern 7 structured log —— Phase 7 Run Viewer 钩子。

    字段对齐 Phase 5.B PlatformDaemonClient.invoke schema（CONTEXT Decision Discretion 5）：
    plugin_name / workspace_id / capability / method / latency_ms / outcome
    + 本 plan 扩展: error_class / suggestion_count
    """
    extras: dict[str, Any] = {
        "plugin_name": plugin_name,
        "workspace_id": current_workspace_id.get(),
        "capability": "doc",
        "method": "ai_suggest_mentions",
        "latency_ms": latency_ms,
        "outcome": outcome,
        "suggestion_count": suggestion_count,
    }
    if error_class is not None:
        extras["error_class"] = error_class

    _log.info("platform.plugin.invoke", extra=extras)


async def suggest_mentions_via_llm(
    *,
    prompt_path: Path,
    markdown: str,
    context: dict[str, Any],
    plugin_name: str,
    llm_model: str | None = None,
) -> list[MentionSuggestion]:
    """3 plugin 共用入口 —— 加载 prompt + 调 LLM + parse + 失败 fallback。

    重要约定（fallback discipline）：
    - LLM 调用失败（auth / rate-limit / timeout / 5xx）→ 返回空 list + outcome="llm_failure"
    - parse 失败（JSON 非法 / schema 不符）→ 返回空 list + outcome="parse_failure"
    - prompt 文件不存在 → 让 FileNotFoundError 抛出（这是 plugin 配置错误，不应静默）

    Args:
        prompt_path: plugin-local prompt 模板路径
        markdown: 文档正文
        context: 含 workspace_id / document_id / author_id / workspace_users_hint
        plugin_name: 当前 plugin 名（用于 log + MentionSuggestion）
        llm_model: 覆盖默认模型（默认 DEFAULT_LLM_MODEL = zhipuai:glm-4-flash）

    Returns:
        list[MentionSuggestion]（成功或 fallback 都返回 list；不 raise LLMClientError）
    """
    # context 注入到 contextvar（log 字段对齐）
    ws_id = context.get("workspace_id")
    token = None
    if ws_id is not None and current_workspace_id.get() is None:
        token = current_workspace_id.set(str(ws_id))

    start_ts = time.monotonic()
    try:
        system_prompt, user_template = load_prompt_template(prompt_path)
        user_prompt = _render_user_template(user_template, context, markdown)

        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        model_str = llm_model or context.get("llm_model") or DEFAULT_LLM_MODEL

        try:
            ai_message = await call_llm(model_str, messages)
        except LLMClientError as exc:
            latency_ms = int((time.monotonic() - start_ts) * 1000)
            _log_outcome(
                plugin_name=plugin_name,
                latency_ms=latency_ms,
                outcome="llm_failure",
                error_class=type(exc).__name__,
            )
            return []
        except Exception as exc:  # noqa: BLE001 — fallback discipline 兜底
            latency_ms = int((time.monotonic() - start_ts) * 1000)
            _log_outcome(
                plugin_name=plugin_name,
                latency_ms=latency_ms,
                outcome="llm_failure",
                error_class=type(exc).__name__,
            )
            _log.warning(
                "ai_suggest_mentions 非 LLM 异常已 fallback 为空 list",
                exc_info=True,
            )
            return []

        suggestions = _parse_llm_response(
            str(ai_message.content), plugin_name=plugin_name
        )
        latency_ms = int((time.monotonic() - start_ts) * 1000)

        if not suggestions and ai_message.content:
            # 内容非空但 parse 出 0 个 —— 视为 parse failure
            _log_outcome(
                plugin_name=plugin_name,
                latency_ms=latency_ms,
                outcome="parse_failure",
                suggestion_count=0,
            )
            return []

        _log_outcome(
            plugin_name=plugin_name,
            latency_ms=latency_ms,
            outcome="success",
            suggestion_count=len(suggestions),
        )
        return suggestions

    finally:
        if token is not None:
            current_workspace_id.reset(token)
```

代码风格：
- type annotations on all function signatures (PEP 8)
- black 格式化，ruff 通过
- mypy strict（context.get() 处显式 cast 到 str）
- **不引入新依赖**（call_llm / LLMClientError / UserRef 全 Phase 2.05 + 5.A 已有）
  </action>
  <verify>
    <automated>cd backend && python -c "
import asyncio
from pathlib import Path
from unittest.mock import patch, AsyncMock
from langchain_core.messages import AIMessage
from app.plugins._common.llm_mention_helper import (
    suggest_mentions_via_llm, load_prompt_template, _render_user_template, _parse_llm_response,
)
# parse OK
ss = _parse_llm_response('{\"suggestions\":[{\"user_id\":\"u1\",\"confidence\":0.9,\"rationale\":\"ok\"}]}', plugin_name='outline')
assert len(ss) == 1 and ss[0].user_ref.native_id == 'u1' and ss[0].confidence == 0.9
# parse 失败 fallback 空 list
ss2 = _parse_llm_response('not json at all', plugin_name='outline')
assert ss2 == []
# render — markdown 含 { 不应 raise
out = _render_user_template('content: {{markdown}}', {'document_id': 'd1', 'author_id': 'u1'}, '# title { brace }')
assert '{{' not in out and 'brace' in out
print('OK helper basic')
"</automated>
  </verify>
  <done>llm_mention_helper.py 存在 + 5 个函数（load_prompt_template / _render_user_template / _parse_llm_response / _log_outcome / suggest_mentions_via_llm）+ basic smoke 通过（parse OK / parse fallback / markdown { escape）</done>
</task>

<task type="auto">
  <name>Task 3: OutlinePlugin 接入 ai_suggest_mentions（真实现 + plugin-local prompt）</name>
  <files>backend/app/plugins/outline/prompts/ai_suggest_mentions_zh.md,backend/app/plugins/outline/outline_plugin.py</files>
  <action>
1. **`backend/app/plugins/outline/prompts/ai_suggest_mentions_zh.md`** —— 替换 plan 03 已写的 stub，写真 prompt（≥30 行）：

```markdown
# system

你是 Outline 文档协作的 @ 推荐助手。

你的任务：根据用户当前正在编辑的文档内容（markdown）、文档元信息、workspace 内可选的协作者列表，推荐 0-5 个最值得 @ 的同事，帮助作者快速找到合适的协作对象。

## 输出格式

必须返回严格的 JSON（不要包 ```json``` 代码块标记，直接输出 JSON）：

```
{
  "suggestions": [
    {"user_id": "<outline user id>", "confidence": 0.0-1.0, "rationale": "为什么推荐这个人，简短中文"}
  ]
}
```

## 规则

- 若文档中明确提到某人姓名（如"请张三审核"），confidence 应 ≥ 0.8
- 若仅按主题相关性推断（如代码 review 推荐技术 lead），confidence 0.4-0.7
- 若无明显线索，返回空 suggestions list（[]）
- user_id 必须从下方 workspace_users_hint 中选取，**不要编造**
- 推荐数量 ≤ 5，按 confidence 降序

# user

请根据以下信息推荐 @ 候选人：

## 文档元信息

- workspace_id: {{document_id}}
- 文档 ID: {{document_id}}
- 作者 ID: {{author_id}}

## 可选协作者（user_id 必须从此列表选取）

{{workspace_users_hint}}

## 文档正文（markdown）

{{markdown}}

请直接输出 JSON，不要任何额外说明文字。
```

2. **修改 `backend/app/plugins/outline/outline_plugin.py`** —— 加 `ai_suggest_mentions` 方法（plan 03 已有 class，只追加方法）：

```python
# 在 OutlinePlugin class 内追加（保留 plan 03 已有所有方法）：

from pathlib import Path
from typing import Any

from app.plugins._common.llm_mention_helper import suggest_mentions_via_llm
from app.plugins._common.mention_suggestion import MentionSuggestion

class OutlinePlugin:
    # ... plan 03 已有 name / supports_collaborative_edit=False / create_document / replace_document_content
    # ... apply_document_delta (raise NotImplementedError) / add_comment / get_document

    _PROMPT_PATH = Path(__file__).parent / "prompts" / "ai_suggest_mentions_zh.md"

    async def ai_suggest_mentions(
        self,
        *,
        markdown: str,
        context: dict[str, Any],
    ) -> list[MentionSuggestion]:
        """DocCapability v1.1 — Outline LLM mention 推荐。

        失败 fallback：返回空 list + structured log（helper 内已处理，不 raise）。
        """
        return await suggest_mentions_via_llm(
            prompt_path=self._PROMPT_PATH,
            markdown=markdown,
            context=context,
            plugin_name="outline",
        )
```

3. **关键约束**：
- **plan 03 已有的 OutlinePlugin 类 0 接口破坏**（不改 name / supports_collaborative_edit / 5 个 v1 方法签名）
- 只**追加** `_PROMPT_PATH` 类变量 + `ai_suggest_mentions` 方法 + 2 个 import
- 若 plan 03 已建 prompts/ai_suggest_mentions_zh.md stub（如 `# TODO ai_suggest_mentions stub`）→ 整体覆盖为真 prompt
  </action>
  <verify>
    <automated>cd backend && test -f app/plugins/outline/prompts/ai_suggest_mentions_zh.md && wc -l app/plugins/outline/prompts/ai_suggest_mentions_zh.md | awk '{exit ($1 >= 30 ? 0 : 1)}' && grep -q "ai_suggest_mentions" app/plugins/outline/outline_plugin.py && grep -q "suggest_mentions_via_llm" app/plugins/outline/outline_plugin.py && python -c "
from app.plugins.outline.outline_plugin import OutlinePlugin
assert hasattr(OutlinePlugin, 'ai_suggest_mentions')
# 检查 v1 接口未被破坏
assert hasattr(OutlinePlugin, 'create_document')
assert hasattr(OutlinePlugin, 'replace_document_content')
assert hasattr(OutlinePlugin, 'add_comment')
print('Outline ai_suggest_mentions wired + v1 0 broken')
"</automated>
  </verify>
  <done>Outline prompt 真实 ≥ 30 行 + OutlinePlugin.ai_suggest_mentions 方法存在 + plan 03 v1 接口 0 改动（5 method 全在）</done>
</task>

<task type="auto">
  <name>Task 4: LarkDocsPlugin 接入 ai_suggest_mentions（真实现 + lark_open_id 专用 prompt）</name>
  <files>backend/app/plugins/lark_docs/prompts/ai_suggest_mentions_zh.md,backend/app/plugins/lark_docs/lark_docs_plugin.py</files>
  <action>
1. **`backend/app/plugins/lark_docs/prompts/ai_suggest_mentions_zh.md`** —— 替换 plan 04 已写的 stub，写真 prompt（≥30 行）。**与 Outline 不同**：强调 `lark_open_id` 格式（`ou_xxxxxxxxxxxxxxxxxxxxx`）。

```markdown
# system

你是飞书文档协作的 @ 推荐助手。

你的任务：根据用户当前正在编辑的文档内容（markdown）、文档元信息、workspace 内可选的协作者列表，推荐 0-5 个最值得 @ 的同事，帮助作者快速找到合适的协作对象。

## 输出格式

必须返回严格的 JSON（不要包 ```json``` 代码块，直接输出 JSON）：

```
{
  "suggestions": [
    {"user_id": "ou_xxxxxxxxxxxxxxxxxxxxx", "confidence": 0.0-1.0, "rationale": "为什么推荐，简短中文"}
  ]
}
```

## 飞书特定规则

- `user_id` 必须是飞书 `open_id` 格式（以 `ou_` 开头的 21 字符字符串）
- user_id 必须从下方 `workspace_users_hint` 列表中选取，**不要编造任何 open_id**
- 若文档中提到某人姓名或 @ 标记（如 `@张三`），且能在 hint 中找到对应 open_id，confidence ≥ 0.85
- 若按主题相关性推断（代码 review → 技术 lead；产品讨论 → PM），confidence 0.4-0.7
- 若无明显线索或 hint 为空 list，返回空 suggestions（[]）
- 推荐数量 ≤ 5，按 confidence 降序

# user

请根据以下信息推荐 @ 候选人：

## 文档元信息

- 文档 ID: {{document_id}}
- 作者 open_id: {{author_id}}

## 可选协作者（必须从此列表选 open_id）

{{workspace_users_hint}}

## 文档正文（markdown）

{{markdown}}

请直接输出 JSON，不要任何额外说明文字。
```

2. **修改 `backend/app/plugins/lark_docs/lark_docs_plugin.py`** —— 追加 `ai_suggest_mentions` 方法（plan 04 已有 class）：

```python
from pathlib import Path
from typing import Any

from app.plugins._common.llm_mention_helper import suggest_mentions_via_llm
from app.plugins._common.mention_suggestion import MentionSuggestion


class LarkDocsPlugin:
    # ... plan 04 已有所有 DocCapability + IdentityCapability 方法

    _PROMPT_PATH = Path(__file__).parent / "prompts" / "ai_suggest_mentions_zh.md"

    async def ai_suggest_mentions(
        self,
        *,
        markdown: str,
        context: dict[str, Any],
    ) -> list[MentionSuggestion]:
        """DocCapability v1.1 — Lark Docs LLM mention 推荐（lark_open_id 格式）。

        失败 fallback：返回空 list + structured log。
        """
        return await suggest_mentions_via_llm(
            prompt_path=self._PROMPT_PATH,
            markdown=markdown,
            context=context,
            plugin_name="lark_docs",
        )
```

3. **关键约束**：
- plan 04 LarkDocsPlugin 已有的 DocCapability v1 + IdentityCapability 方法 0 接口破坏
- prompt 必须强调 `ou_` 前缀 + 21 字符（feishu open_id 格式约定）
- plugin_name="lark_docs"（**不是** "lark"；与 plan 04 注册名一致）
  </action>
  <verify>
    <automated>cd backend && test -f app/plugins/lark_docs/prompts/ai_suggest_mentions_zh.md && wc -l app/plugins/lark_docs/prompts/ai_suggest_mentions_zh.md | awk '{exit ($1 >= 30 ? 0 : 1)}' && grep -q "ou_" app/plugins/lark_docs/prompts/ai_suggest_mentions_zh.md && grep -q "ai_suggest_mentions" app/plugins/lark_docs/lark_docs_plugin.py && python -c "
from app.plugins.lark_docs.lark_docs_plugin import LarkDocsPlugin
assert hasattr(LarkDocsPlugin, 'ai_suggest_mentions')
# 检查 v1 接口未被破坏
assert hasattr(LarkDocsPlugin, 'create_document')
assert hasattr(LarkDocsPlugin, 'replace_document_content')
print('Lark ai_suggest_mentions wired + v1 0 broken')
"</automated>
  </verify>
  <done>Lark prompt 真实 ≥ 30 行 + 含 `ou_` open_id 格式说明 + LarkDocsPlugin.ai_suggest_mentions 方法存在 + plan 04 v1 接口 0 改动</done>
</task>

<task type="auto">
  <name>Task 5: HulyPlugin ai_suggest_mentions 留 stub（单行 NotImplementedError，v1.1 占位）</name>
  <files>backend/app/plugins/huly/huly_plugin.py,backend/app/plugins/huly/prompts/ai_suggest_mentions_zh.md</files>
  <action>
1. **`backend/app/plugins/huly/prompts/ai_suggest_mentions_zh.md`** —— 占位 stub（保 plugin folder layout 一致；几行说明 v1.1）：

```markdown
# system

(Huly ai_suggest_mentions 暂未实现 —— Phase 5.C plan 06 决策保留为 v1.1 stub)

# user

(此模板将在 v1.1 真实现时填充。当前 HulyPlugin.ai_suggest_mentions 直接 raise NotImplementedError，
helper 不会读取此文件。)

## 不实现原因（v1 决策）

- Huly identity 走 SocialIdentity → Employee mixin 链 + LRU cache（plan 05 已建）
- workspace_users_hint 需要预查 daemon 内 LRU 缓存的 PersonUuid 列表
- 涉及复杂 mixin join 查询，超出本 phase 范围
- v1.1 实现时复用 plan 05 的 identity_resolver.py + 加 LLM 调用
```

2. **修改 `backend/app/plugins/huly/huly_plugin.py`** —— 追加单行 stub method（plan 05 已有 4-cap bundle class）：

```python
from typing import Any

# 不 import suggest_mentions_via_llm（v1.1 不调，避免引入未用 import）


class HulyPlugin:
    # ... plan 05 已有 4 capability bundle (DocCapability + IMCapability + IdentityCapability + TrackerCapability stub)
    # ... + 共享 HulyPlatformClient + connect_huly + _ensure_client lock

    async def ai_suggest_mentions(
        self,
        *,
        markdown: str,
        context: dict[str, Any],
    ) -> list:
        """DocCapability v1.1 — Huly LLM mention 推荐留 v1.1 stub。

        v1 不实现的原因：Huly identity 走 SocialIdentity → Employee mixin 链（plan 05），
        workspace_users_hint 需要预查 daemon 内 LRU 缓存的 PersonUuid 列表，涉及复杂
        mixin join 查询，超出本 phase 范围。v1.1 实现时复用 plan 05 identity_resolver.py。
        """
        raise NotImplementedError(
            "HulyPlugin.ai_suggest_mentions 留 v1.1 实现 — 需 SocialIdentity LRU 查询 + LLM 调用"
        )
```

3. **关键约束**：
- plan 05 已有的 HulyPlugin 4-cap bundle 类 0 接口破坏（DocCapability v1 5 method + IMCapability + IdentityCapability + TrackerCapability stub 全保留）
- ai_suggest_mentions 是**单行 raise**，不调 helper，不读 prompt 文件
- prompts 文件存在只是为了 plugin folder layout 一致性
  </action>
  <verify>
    <automated>cd backend && test -f app/plugins/huly/prompts/ai_suggest_mentions_zh.md && grep -q "v1.1" app/plugins/huly/prompts/ai_suggest_mentions_zh.md && grep -q "NotImplementedError" app/plugins/huly/huly_plugin.py && python -c "
import asyncio
from app.plugins.huly.huly_plugin import HulyPlugin
plugin = HulyPlugin.__new__(HulyPlugin)  # bypass __init__ deps
try:
    asyncio.run(plugin.ai_suggest_mentions(markdown='', context={}))
    raise AssertionError('expected NotImplementedError')
except NotImplementedError as exc:
    assert 'v1.1' in str(exc)
    print('Huly stub raises as expected')
"</automated>
  </verify>
  <done>Huly prompt stub 文件存在 + HulyPlugin.ai_suggest_mentions raise NotImplementedError + plan 05 4-cap bundle 0 改动</done>
</task>

<task type="auto">
  <name>Task 6: unit tests — mock LLM 验证 prompt 加载 / parse / fallback / log schema（3 plugin 全覆盖）</name>
  <files>tests/platforms/test_ai_suggest_mentions.py</files>
  <action>
**注意：unit tests 全 mock `call_llm`（不发真网络）。整 plan 单测 ≤ 60s。**

`tests/platforms/test_ai_suggest_mentions.py`:

```python
"""Phase 5.C plan 06 — ai_suggest_mentions LLM 钩子 unit tests。

测试矩阵（14+ cases）：
- 3 plugin × {prompt 加载 / parse 成功 / parse 失败 fallback / LLM error fallback / structured log schema}
- HulyPlugin NotImplementedError 单测
- helper-level：_parse_llm_response 边界（多种非法 JSON / JSON 内嵌代码块 / suggestions 非 list）
- helper-level：_render_user_template（markdown 含 `{` 不 raise / 空 hint）

全 mock call_llm，不发真网络。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage

from app.agent_builder.workflow.llm_client import (
    LLMAuthError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.plugins._common.llm_mention_helper import (
    DEFAULT_LLM_MODEL,
    _parse_llm_response,
    _render_user_template,
    load_prompt_template,
    suggest_mentions_via_llm,
)
from app.plugins._common.mention_suggestion import MentionSuggestion
from app.plugins.outline.outline_plugin import OutlinePlugin
from app.plugins.lark_docs.lark_docs_plugin import LarkDocsPlugin
from app.plugins.huly.huly_plugin import HulyPlugin
from app.agent_builder.platforms.capabilities.doc import UserRef


# ── helper-level tests ────────────────────────────────────────────────────────


class TestParseLLMResponse:
    def test_well_formed_json_returns_list(self):
        content = json.dumps({"suggestions": [
            {"user_id": "u1", "confidence": 0.9, "rationale": "explicit mention"},
            {"user_id": "u2", "confidence": 0.5, "rationale": "topic match"},
        ]})
        result = _parse_llm_response(content, plugin_name="outline")
        assert len(result) == 2
        assert result[0].user_ref.native_id == "u1"
        assert result[0].user_ref.plugin_name == "outline"
        assert result[0].confidence == 0.9
        assert result[0].rationale == "explicit mention"

    def test_json_wrapped_in_codeblock_extracted(self):
        content = "```json\n" + json.dumps({"suggestions": [
            {"user_id": "u1", "confidence": 0.7, "rationale": "ok"}
        ]}) + "\n```"
        result = _parse_llm_response(content, plugin_name="lark_docs")
        assert len(result) == 1
        assert result[0].user_ref.plugin_name == "lark_docs"

    def test_garbage_returns_empty_list(self):
        assert _parse_llm_response("not json at all", plugin_name="outline") == []
        assert _parse_llm_response("", plugin_name="outline") == []
        assert _parse_llm_response("{ broken json", plugin_name="outline") == []

    def test_suggestions_not_list_returns_empty(self):
        content = json.dumps({"suggestions": "not a list"})
        assert _parse_llm_response(content, plugin_name="outline") == []

    def test_confidence_clamped_to_0_1(self):
        content = json.dumps({"suggestions": [
            {"user_id": "u1", "confidence": 2.5, "rationale": "over"},
            {"user_id": "u2", "confidence": -0.3, "rationale": "under"},
            {"user_id": "u3", "confidence": "bad", "rationale": "non-numeric"},
        ]})
        result = _parse_llm_response(content, plugin_name="outline")
        assert len(result) == 3
        assert result[0].confidence == 1.0
        assert result[1].confidence == 0.0
        assert result[2].confidence == 0.5  # 默认值

    def test_invalid_items_skipped(self):
        content = json.dumps({"suggestions": [
            {"user_id": "u1", "confidence": 0.8, "rationale": "ok"},
            "not a dict",
            {"confidence": 0.5},  # 缺 user_id
            {"user_id": "", "confidence": 0.5},  # 空 user_id
            {"user_id": None, "confidence": 0.5},  # None
        ]})
        result = _parse_llm_response(content, plugin_name="outline")
        assert len(result) == 1
        assert result[0].user_ref.native_id == "u1"


class TestRenderUserTemplate:
    def test_basic_substitution(self):
        tpl = "doc {{document_id}} by {{author_id}}: {{markdown}}"
        out = _render_user_template(
            tpl,
            {"document_id": "d1", "author_id": "a1"},
            "hello world",
        )
        assert "d1" in out and "a1" in out and "hello world" in out
        assert "{{" not in out

    def test_markdown_with_braces_no_raise(self):
        """关键 regression — markdown 内 `{` 不应让 str.format raise KeyError。"""
        markdown_with_braces = "code: {{x}}{y}{ name }"
        out = _render_user_template(
            "content: {{markdown}}",
            {"document_id": "d", "author_id": "a"},
            markdown_with_braces,
        )
        # 不应 raise，且 markdown 中的 { 原样保留
        assert "{y}" in out

    def test_workspace_users_hint_json_encoded(self):
        out = _render_user_template(
            "users: {{workspace_users_hint}}",
            {"workspace_users_hint": ["alice", "bob"]},
            "",
        )
        # JSON encoded list
        assert "alice" in out and "bob" in out
        assert "[" in out and "]" in out


class TestLoadPromptTemplate:
    def test_split_system_user_sections(self, tmp_path: Path):
        f = tmp_path / "p.md"
        f.write_text(
            "# system\nYou are a helper.\n\n# user\nDo X: {{markdown}}\n",
            encoding="utf-8",
        )
        sys_text, user_text = load_prompt_template(f)
        assert "helper" in sys_text and "# system" not in sys_text
        assert "Do X" in user_text and "# user" not in user_text

    def test_no_sections_full_text_as_user(self, tmp_path: Path):
        f = tmp_path / "p.md"
        f.write_text("Just user prompt: {{markdown}}", encoding="utf-8")
        sys_text, user_text = load_prompt_template(f)
        assert sys_text == ""
        assert "Just user prompt" in user_text


# ── plugin-level tests with mock call_llm ────────────────────────────────────


@pytest.fixture
def good_llm_response():
    """LLM 成功返回 — 2 个 suggestion。"""
    return AIMessage(content=json.dumps({"suggestions": [
        {"user_id": "u1", "confidence": 0.9, "rationale": "explicit"},
        {"user_id": "u2", "confidence": 0.5, "rationale": "topic"},
    ]}))


class TestOutlineAISuggestMentions:
    @pytest.mark.asyncio
    async def test_success_returns_list(self, good_llm_response):
        with patch(
            "app.plugins._common.llm_mention_helper.call_llm",
            new=AsyncMock(return_value=good_llm_response),
        ):
            plugin = OutlinePlugin.__new__(OutlinePlugin)
            result = await plugin.ai_suggest_mentions(
                markdown="# title\nplease review",
                context={"workspace_id": "ws1", "document_id": "d1",
                         "author_id": "a1", "workspace_users_hint": ["u1", "u2"]},
            )
            assert len(result) == 2
            assert all(isinstance(s, MentionSuggestion) for s in result)
            assert all(s.user_ref.plugin_name == "outline" for s in result)

    @pytest.mark.asyncio
    async def test_llm_auth_error_returns_empty(self, caplog):
        with patch(
            "app.plugins._common.llm_mention_helper.call_llm",
            new=AsyncMock(side_effect=LLMAuthError("no key")),
        ):
            plugin = OutlinePlugin.__new__(OutlinePlugin)
            with caplog.at_level(logging.INFO, logger="agent_builder.platform_plugin"):
                result = await plugin.ai_suggest_mentions(
                    markdown="x", context={"workspace_id": "ws1"},
                )
            assert result == []
            # structured log assertion — outcome=llm_failure
            log_records = [r for r in caplog.records
                          if r.message == "platform.plugin.invoke"]
            assert any(r.outcome == "llm_failure" for r in log_records)
            assert any(getattr(r, "error_class", "") == "LLMAuthError" for r in log_records)

    @pytest.mark.asyncio
    async def test_llm_rate_limit_returns_empty(self):
        with patch(
            "app.plugins._common.llm_mention_helper.call_llm",
            new=AsyncMock(side_effect=LLMRateLimitError("429")),
        ):
            plugin = OutlinePlugin.__new__(OutlinePlugin)
            result = await plugin.ai_suggest_mentions(markdown="x", context={})
            assert result == []

    @pytest.mark.asyncio
    async def test_llm_timeout_returns_empty(self):
        with patch(
            "app.plugins._common.llm_mention_helper.call_llm",
            new=AsyncMock(side_effect=LLMTimeoutError("timeout")),
        ):
            plugin = OutlinePlugin.__new__(OutlinePlugin)
            result = await plugin.ai_suggest_mentions(markdown="x", context={})
            assert result == []

    @pytest.mark.asyncio
    async def test_parse_failure_returns_empty(self, caplog):
        with patch(
            "app.plugins._common.llm_mention_helper.call_llm",
            new=AsyncMock(return_value=AIMessage(content="totally not json")),
        ):
            plugin = OutlinePlugin.__new__(OutlinePlugin)
            with caplog.at_level(logging.INFO, logger="agent_builder.platform_plugin"):
                result = await plugin.ai_suggest_mentions(markdown="x", context={})
            assert result == []
            log_records = [r for r in caplog.records
                          if r.message == "platform.plugin.invoke"]
            assert any(r.outcome == "parse_failure" for r in log_records)

    @pytest.mark.asyncio
    async def test_structured_log_schema_complete(self, good_llm_response, caplog):
        with patch(
            "app.plugins._common.llm_mention_helper.call_llm",
            new=AsyncMock(return_value=good_llm_response),
        ):
            plugin = OutlinePlugin.__new__(OutlinePlugin)
            with caplog.at_level(logging.INFO, logger="agent_builder.platform_plugin"):
                await plugin.ai_suggest_mentions(
                    markdown="x",
                    context={"workspace_id": "ws-123"},
                )
            invokes = [r for r in caplog.records if r.message == "platform.plugin.invoke"]
            assert len(invokes) >= 1
            r = invokes[-1]
            # Pattern 7 schema 字段全
            assert r.plugin_name == "outline"
            assert r.workspace_id == "ws-123"
            assert r.capability == "doc"
            assert r.method == "ai_suggest_mentions"
            assert isinstance(r.latency_ms, int) and r.latency_ms >= 0
            assert r.outcome == "success"
            assert r.suggestion_count == 2


class TestLarkAISuggestMentions:
    @pytest.mark.asyncio
    async def test_success_returns_list_with_lark_plugin_name(self, good_llm_response):
        # Mock 返回 ou_ 格式 user_id 模拟真 Lark open_id
        with patch(
            "app.plugins._common.llm_mention_helper.call_llm",
            new=AsyncMock(return_value=AIMessage(content=json.dumps({"suggestions": [
                {"user_id": "ou_abc123def456ghi789jk", "confidence": 0.85, "rationale": "explicit"}
            ]}))),
        ):
            plugin = LarkDocsPlugin.__new__(LarkDocsPlugin)
            result = await plugin.ai_suggest_mentions(
                markdown="@张三 请审核", context={"workspace_id": "ws1"},
            )
            assert len(result) == 1
            assert result[0].user_ref.plugin_name == "lark_docs"
            assert result[0].user_ref.native_id.startswith("ou_")

    @pytest.mark.asyncio
    async def test_llm_error_returns_empty(self):
        with patch(
            "app.plugins._common.llm_mention_helper.call_llm",
            new=AsyncMock(side_effect=LLMRateLimitError("rate limit")),
        ):
            plugin = LarkDocsPlugin.__new__(LarkDocsPlugin)
            result = await plugin.ai_suggest_mentions(markdown="x", context={})
            assert result == []


class TestHulyAISuggestMentionsStub:
    @pytest.mark.asyncio
    async def test_huly_raises_not_implemented(self):
        plugin = HulyPlugin.__new__(HulyPlugin)
        with pytest.raises(NotImplementedError) as exc_info:
            await plugin.ai_suggest_mentions(markdown="x", context={})
        assert "v1.1" in str(exc_info.value)


class TestPromptTemplateLoadable:
    """3 plugin prompt 模板都能被 load_prompt_template 解析。"""

    def test_outline_prompt_loadable(self):
        path = Path("backend/app/plugins/outline/prompts/ai_suggest_mentions_zh.md")
        if not path.exists():
            # tests 在不同 cwd 跑时回退到 __file__-relative
            from app.plugins.outline import outline_plugin
            path = Path(outline_plugin.__file__).parent / "prompts/ai_suggest_mentions_zh.md"
        sys_text, user_text = load_prompt_template(path)
        # system 段必须存在 + user 段含 {{markdown}}
        assert len(sys_text) > 50
        assert "{{markdown}}" in user_text
        assert "JSON" in (sys_text + user_text)

    def test_lark_prompt_loadable(self):
        from app.plugins.lark_docs import lark_docs_plugin
        path = Path(lark_docs_plugin.__file__).parent / "prompts/ai_suggest_mentions_zh.md"
        sys_text, user_text = load_prompt_template(path)
        assert "{{markdown}}" in user_text
        # Lark 专用约束 — ou_ 格式说明
        assert "ou_" in (sys_text + user_text)
```

注意：
- 全 mock `call_llm`，避免真实网络（~60s 整 plan 单测时间）
- `OutlinePlugin.__new__(OutlinePlugin)` bypass `__init__` 依赖（plan 03 可能要传 api_token，但本 method 不用）
- structured log assertion 用 `caplog` + extra dict 字段直接读
- 14+ test methods（覆盖 parse 边界 / render / load / 3 plugin × 多 case / Huly stub）
- 加 `pytest.ini` mark `unit` 区分 integration（已有 conftest 处理）
  </action>
  <verify>
    <automated>cd backend && pytest tests/platforms/test_ai_suggest_mentions.py -v -x --tb=short 2>&1 | tail -40 && pytest tests/platforms/test_ai_suggest_mentions.py --collect-only -q 2>&1 | grep -c "test_" | awk '{exit ($1 >= 14 ? 0 : 1)}'</automated>
  </verify>
  <done>tests/platforms/test_ai_suggest_mentions.py 含 ≥ 14 个 test method 全 pass；mock call_llm 不发真网络；structured log schema 6 字段（plugin_name/workspace_id/capability/method/latency_ms/outcome）assert 通过；Huly stub NotImplementedError 测试通过</done>
</task>

<task type="auto">
  <name>Task 7: integration tests — 真调 GLM-Flash 免费档（Outline + Lark 各 1 样本）</name>
  <files>tests/platforms_integration/test_ai_suggest_mentions_llm_integration.py</files>
  <action>
**真 LLM 调用 — GLM-Flash 免费档（user constraint Critical #4）。所有测试 skipif ZHIPUAI_API_KEY 未配置。**

`tests/platforms_integration/test_ai_suggest_mentions_llm_integration.py`:

```python
"""Phase 5.C plan 06 — ai_suggest_mentions 真 LLM 集成测试（GLM-Flash 免费档）。

测试矩阵（4 cases）：
- OutlinePlugin × 1 markdown 样本（含明确 @ 提示） — 真 GLM-Flash → 返回 ≥ 1 suggestion
- OutlinePlugin × 1 markdown 样本（无明确提示，空 hint） — 真 GLM-Flash → 可能空 list
- LarkDocsPlugin × 1 markdown 样本（含 ou_ open_id hint） — 真 GLM-Flash → 返回正确 plugin_name
- LarkDocsPlugin × 1 markdown 样本（fallback：故意构造错 model_str） — 触发 LLMClientError → 返回空 list + log outcome=llm_failure

所有测试 skipif ZHIPUAI_API_KEY 未配置（CI / 本地 dev 无 key 时跳过）。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import pytest

from app.plugins._common.llm_mention_helper import suggest_mentions_via_llm
from app.plugins._common.mention_suggestion import MentionSuggestion
from app.plugins.outline.outline_plugin import OutlinePlugin
from app.plugins.lark_docs.lark_docs_plugin import LarkDocsPlugin


pytestmark = pytest.mark.skipif(
    not os.environ.get("ZHIPUAI_API_KEY"),
    reason="ZHIPUAI_API_KEY 未配置 — integration tests 跳过（GLM-Flash 免费档需 key）",
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_outline_real_glm_flash_with_explicit_mention():
    """OutlinePlugin 真调 GLM-Flash —— markdown 内含明确 @ 提示，期望 ≥ 1 suggestion。"""
    plugin = OutlinePlugin.__new__(OutlinePlugin)
    result = await plugin.ai_suggest_mentions(
        markdown="""# 新功能设计：异步任务队列

## 背景

为了支持大量并发任务，需要引入异步队列。建议 **请张三审核架构设计**，
他在 RabbitMQ 和 Celery 方向有丰富经验。

## 方案

使用 arq + Redis 实现轻量级任务队列。
""",
        context={
            "workspace_id": "ws-it-1",
            "document_id": "doc-it-1",
            "author_id": "u-author",
            "workspace_users_hint": [
                {"user_id": "u-zhangsan", "name": "张三", "role": "tech_lead"},
                {"user_id": "u-lisi", "name": "李四", "role": "frontend"},
                {"user_id": "u-wangwu", "name": "王五", "role": "pm"},
            ],
        },
    )
    # 真 LLM 应能识别"请张三审核"并推荐 u-zhangsan
    assert isinstance(result, list)
    assert all(isinstance(s, MentionSuggestion) for s in result)
    assert all(s.user_ref.plugin_name == "outline" for s in result)
    # 关键 — 若 LLM 完全工作，至少 1 个 suggestion；不强 assert ≥1 避免 LLM 概率性失败 flaky
    # 但 plugin_name 是 deterministic 必须正确
    print(f"[integration] Outline GLM-Flash returned {len(result)} suggestions")
    for s in result:
        print(f"  - user={s.user_ref.native_id} conf={s.confidence:.2f} rat={s.rationale[:60]}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_outline_real_glm_flash_no_context():
    """无明确线索 + 空 hint —— 期望空 list 或低 confidence；不应 raise。"""
    plugin = OutlinePlugin.__new__(OutlinePlugin)
    result = await plugin.ai_suggest_mentions(
        markdown="# 标题\n\n一些普通段落。",
        context={
            "workspace_id": "ws-it-2",
            "workspace_users_hint": [],  # 空 hint
        },
    )
    assert isinstance(result, list)
    # LLM 应识别 hint 为空 → 返回空 list（按 prompt 规则）
    # 不强 assert == []（LLM 可能仍编造，本测试主要验证不 raise）
    print(f"[integration] Outline no-context returned {len(result)} suggestions")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_lark_real_glm_flash_open_id():
    """LarkDocsPlugin 真调 GLM-Flash —— 验证 plugin_name 正确 + ou_ 格式 hint 工作。"""
    plugin = LarkDocsPlugin.__new__(LarkDocsPlugin)
    result = await plugin.ai_suggest_mentions(
        markdown="""# 产品需求文档

我们计划在 Q3 上线新版搜索功能。
@王经理 请评估资源投入。
""",
        context={
            "workspace_id": "ws-it-3",
            "document_id": "doc-it-3",
            "author_id": "ou_author000000000001",
            "workspace_users_hint": [
                {"user_id": "ou_wang0000000000000001", "name": "王经理", "role": "pm"},
                {"user_id": "ou_li000000000000000002", "name": "李工程师", "role": "be"},
            ],
        },
    )
    assert isinstance(result, list)
    assert all(s.user_ref.plugin_name == "lark_docs" for s in result)
    # LLM 返回的 user_id 应该来自 hint 中的 ou_ 格式
    for s in result:
        # 不强 assert ou_ 前缀（LLM 可能编造）但要确保 native_id 是 string
        assert isinstance(s.user_ref.native_id, str)
        assert len(s.user_ref.native_id) > 0
    print(f"[integration] Lark GLM-Flash returned {len(result)} suggestions")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_lark_invalid_model_fallback_to_empty_list(caplog):
    """故意传错 model_str → 触发 LLMClientError → 返回空 list（不 raise）+ log outcome=llm_failure。"""
    plugin = LarkDocsPlugin.__new__(LarkDocsPlugin)

    # 通过 context 注入错误模型（helper 会优先用 context.llm_model）
    with caplog.at_level(logging.INFO, logger="agent_builder.platform_plugin"):
        result = await plugin.ai_suggest_mentions(
            markdown="x",
            context={
                "workspace_id": "ws-it-fallback",
                "llm_model": "definitely_not_a_real_provider:nonexistent-model-9999",
            },
        )
    # 关键 DoD — fallback discipline：返回空 list，不 raise 给业务
    assert result == []
    # structured log 应记录 llm_failure
    invoke_records = [r for r in caplog.records if r.message == "platform.plugin.invoke"]
    assert any(r.outcome == "llm_failure" for r in invoke_records), \
        f"expected outcome=llm_failure log, got: {[r.outcome for r in invoke_records]}"
```

注意：
- 4 个 test method，分别覆盖 Outline 含 hint / Outline 空 hint / Lark ou_ hint / Lark fallback discipline
- pytestmark module-level skipif 让 CI / 本地 dev 无 key 时跳过整个文件
- 不 assert 严格的 suggestion 数量（LLM 概率性输出，避免 flaky 测试）；只 assert deterministic 字段（plugin_name / type）
- 最后一个测试故意构造错 model_str 验证 fallback discipline（DoD critical）
- 加 print 输出方便调试

GLM-Flash model_str 标准格式：`zhipuai:glm-4-flash`（已在 DEFAULT_LLM_MODEL）。
  </action>
  <verify>
    <automated>cd backend && pytest tests/platforms_integration/test_ai_suggest_mentions_llm_integration.py --collect-only -q 2>&1 | grep -c "test_" | awk '{exit ($1 >= 4 ? 0 : 1)}' && if [ -n "$ZHIPUAI_API_KEY" ]; then pytest tests/platforms_integration/test_ai_suggest_mentions_llm_integration.py -v -x --tb=short 2>&1 | tail -30; else pytest tests/platforms_integration/test_ai_suggest_mentions_llm_integration.py -v 2>&1 | grep -E "skipped|passed" | tail -5; fi</automated>
  </verify>
  <done>4 个 integration test method 已收集 + 若 ZHIPUAI_API_KEY 配置则全 pass，否则全 skip（不 fail）；fallback discipline 测试验证错 model → 返回 [] + structured log outcome=llm_failure</done>
</task>

<task type="auto">
  <name>Task 8: regression + final DoD —— Phase 5.A 271 + 5.B 5/5 + 5.C plan 02-05 全 plugin spawn 绿</name>
  <files></files>
  <action>
**这是 plan 06 收尾 gate —— 验证零接口破坏 + 整 phase 健康。无新文件，纯回归。**

依次跑：

1. **Phase 5.A platforms 全套**（271 tests baseline，本 plan 后 += 14+ unit = 285+）:
   ```bash
   cd backend && pytest tests/platforms/ -v --tb=short 2>&1 | tail -30
   ```
   期望：`= XXX passed in YYs =` 全绿，无 failure / error。

2. **Phase 5.B acid test 5/5**：
   ```bash
   cd backend && pytest tests/platforms/test_huly_plugin_acid.py -v 2>&1 | tail -15
   ```
   期望：5 passed（plan 02-05 已升级 huly stub → 真实现，acid test 应仍绿）。

3. **Phase 5.C plan 02-05 plugin spawn 集成测**：
   ```bash
   cd backend && pytest tests/platforms_integration/ -v --tb=short -k "outline or lark or huly" 2>&1 | tail -30
   ```
   期望：plan 02 huly internal port 测 / plan 03 OutlinePlugin spawn 测 / plan 04 LarkDocsPlugin spawn 测 / plan 05 HulyPlugin 4-cap spawn 测全绿（这是 0 接口破坏的实证）。

4. **Phase 4 IM regression**（避免连环影响）:
   ```bash
   cd backend && pytest tests/test_im_provider_*.py -v 2>&1 | tail -10
   ```
   期望：51+ passed。

5. **本 plan 单测 + 集成测全跑**:
   ```bash
   cd backend && pytest tests/platforms/test_ai_suggest_mentions.py tests/platforms_integration/test_ai_suggest_mentions_llm_integration.py -v 2>&1 | tail -30
   ```
   期望：14+ unit passed + 4 integration pass-or-skip（取决于 ZHIPUAI_API_KEY）。

6. **License attribution audit**（plan 02 已加，本 plan 不引入新 hr port 文件，但确认 _common/ 文件无 hr 源借鉴需求 — 都是新写）：
   ```bash
   grep -L "Apache-2.0\|# Inspired by" backend/app/plugins/_common/*.py | head -5
   ```
   期望：本 plan 创建的 _common/ 文件无需 hr attribution（都是新写不借鉴 hr）。

7. **black + ruff 全检查**:
   ```bash
   cd backend && black --check app/plugins/_common/ app/plugins/outline/outline_plugin.py app/plugins/lark_docs/lark_docs_plugin.py app/plugins/huly/huly_plugin.py tests/platforms/test_ai_suggest_mentions.py tests/platforms_integration/test_ai_suggest_mentions_llm_integration.py && ruff check app/plugins/_common/ tests/platforms/test_ai_suggest_mentions.py
   ```
   期望：no diff + no lint errors。

8. **mypy strict** on _common/:
   ```bash
   cd backend && mypy app/plugins/_common/ --strict 2>&1 | tail -10
   ```
   期望：success, no issues found。

**写一个 inline regression summary**（控制台打印，给 SUMMARY 用）：
```bash
echo "=== Phase 5.C Plan 06 Regression Gate ==="
echo "Phase 5.A platforms: $(cd backend && pytest tests/platforms/ --collect-only -q 2>/dev/null | tail -1)"
echo "Phase 5.B acid: $(cd backend && pytest tests/platforms/test_huly_plugin_acid.py --collect-only -q 2>/dev/null | tail -1)"
echo "Phase 4 IM: $(cd backend && pytest tests/test_im_provider_*.py --collect-only -q 2>/dev/null | tail -1)"
echo "Plan 06 unit: $(cd backend && pytest tests/platforms/test_ai_suggest_mentions.py --collect-only -q 2>/dev/null | tail -1)"
echo "Plan 06 integration: $(cd backend && pytest tests/platforms_integration/test_ai_suggest_mentions_llm_integration.py --collect-only -q 2>/dev/null | tail -1)"
```

**若任一步骤红 → 立即 stop 修复，不进 SUMMARY**。
  </action>
  <verify>
    <automated>cd backend && pytest tests/platforms/ -v --tb=short 2>&1 | tail -3 | grep -E "passed" && pytest tests/platforms/test_huly_plugin_acid.py -v 2>&1 | tail -3 | grep -E "5 passed" && pytest tests/test_im_provider_*.py 2>&1 | tail -3 | grep -E "passed" && pytest tests/platforms/test_ai_suggest_mentions.py 2>&1 | tail -3 | grep -E "passed" && black --check app/plugins/_common/ app/plugins/outline/outline_plugin.py app/plugins/lark_docs/lark_docs_plugin.py app/plugins/huly/huly_plugin.py tests/platforms/test_ai_suggest_mentions.py tests/platforms_integration/test_ai_suggest_mentions_llm_integration.py 2>&1 | tail -2</automated>
  </verify>
  <done>Phase 5.A platforms 285+ passed（baseline 271 + 本 plan 14+ unit）+ Phase 5.B acid 5/5 passed + Phase 4 IM 51+ passed + 本 plan unit/integration 全绿 + black/ruff/mypy clean + plan 02-05 plugin spawn 集成测 0 regression</done>
</task>

</tasks>

<verification>
Phase 5.C plan 06 收尾 gate:
- [ ] Reading doc commit hash 早于 Task 1-8 commit hash（CLAUDE.md §2.7 校验）
- [ ] DocCapability v1.1 Protocol 扩展生效（DocCapabilityV1_1.isinstance(OutlinePlugin()) == True，且 plan 02 v1 facade 0 改动 — git diff 校验）
- [ ] llm_mention_helper 是唯一 LLM call 入口（grep `call_llm` in backend/app/plugins/ 仅出现在 _common/llm_mention_helper.py 一处）
- [ ] 3 plugin ai_suggest_mentions 全实现（Outline + Lark 真调 helper，Huly raise NotImplementedError）
- [ ] structured log schema 6 字段全（plugin_name + workspace_id + capability=doc + method=ai_suggest_mentions + latency_ms + outcome）— unit test assert 通过
- [ ] fallback discipline 验证（LLM error → 返回 [] + outcome=llm_failure；parse error → 返回 [] + outcome=parse_failure；不 raise 给业务）
- [ ] 14+ unit tests pass + 4 integration tests pass-or-skip
- [ ] Phase 5.A platforms 271+ baseline → 本 plan 后 285+ 全绿（0 regression）
- [ ] Phase 5.B 5/5 acid test 全绿（HulyPlugin 4-cap bundle 接口 0 改动）
- [ ] Phase 5.C plan 02-05 plugin spawn 集成测全绿（plan 03/04/05 v1 facade 0 接口破坏的实证）
- [ ] Phase 4 IM 51+ tests 0 regression
- [ ] black + ruff + mypy strict 全 clean
</verification>

<success_criteria>
- Dify LLM 节点 + PromptTemplateParser reading doc ≥ 80 行 + 5 借鉴点明确（指回 source file → target module）+ AGPL/Apache attribution 段，commit 在前
- DocCapabilityV1_1 Protocol 用继承扩展 v1 + ai_suggest_mentions optional method（plan 03/04/05 已 freeze 的 DocCapability v1 facade 0 改动）
- MentionSuggestion dataclass(frozen=True) 含 user_ref(UserRef) / confidence(float 0-1) / rationale(str)
- llm_mention_helper.suggest_mentions_via_llm 是 3 plugin 唯一 LLM 入口（memory feedback_capability_design 落地 — 不每个 plugin 单独写类）
- 3 plugin ai_suggest_mentions 全接入：OutlinePlugin 真实现 + LarkDocsPlugin 真实现 + HulyPlugin 单行 NotImplementedError stub
- 3 prompt 模板存在（Outline ≥30 行 / Lark ≥30 行 + 含 ou_ 格式约定 / Huly 占位说明 v1.1）
- LLM 失败 fallback：LLMClientError 全家族（Auth/RateLimit/Server/Timeout/BadRequest/ContextTooLong）+ 任意 Exception 兜底 → 返回空 list + structured log outcome=llm_failure
- parse 失败 fallback：JSON 非法 / schema 不符 / suggestions 非 list → 返回空 list + structured log outcome=parse_failure
- structured log Pattern 7 schema 6 字段全：plugin_name + workspace_id (contextvars) + capability=doc + method=ai_suggest_mentions + latency_ms + outcome (+ optional error_class / suggestion_count)
- 14+ unit tests 全 pass（mock call_llm，不发真网络，整 plan 单测 < 60s）
- 4 integration tests 真调 GLM-Flash 免费档（skipif ZHIPUAI_API_KEY 未配置）— Outline 含 hint / Outline 空 hint / Lark ou_ hint / Lark fallback discipline
- 整 phase regression 全绿：Phase 5.A 271+ → 285+ platforms tests / Phase 5.B 5/5 acid / Phase 5.C plan 02-05 plugin spawn / Phase 4 IM 51+
- black + ruff + mypy strict 通过
- 0 接口破坏：DocCapability v1 Protocol（doc.py）+ OutlinePlugin v1 5 method + LarkDocsPlugin v1 + IdentityCapability + HulyPlugin 4-cap bundle 全保留
</success_criteria>

<output>
完成后创建 `.planning/phases/05c-doc-capability/05c-06-SUMMARY.md`，至少含：
- Reading doc 链接 + commit hash（CLAUDE.md §2.7 attribution）
- DocCapabilityV1_1 Protocol 扩展示例（继承图）
- llm_mention_helper.suggest_mentions_via_llm 调用 trace（system + user prompt 渲染示例 + LLM messages + JSON parse 输出）
- 3 plugin ai_suggest_mentions 接入清单（OutlinePlugin / LarkDocsPlugin 真实现 + HulyPlugin stub）
- Pattern 7 structured log 实例 grep（5+ 行日志示范，含 outcome=success / llm_failure / parse_failure 三种）
- regression 截图：Phase 5.A platforms 数字 + Phase 5.B acid 5/5 + Phase 4 IM + 本 plan unit/integration
- **Dify 参考点** 小节：列出本 plan reading doc 中 5 借鉴点，每条指回 reading doc 章节锚点 + 实际落地到本 plan 的具体 module/function
- **License attribution** 小节：确认 _common/ 文件无 Dify 源码拷贝（只借鉴 PromptTemplateParser 正则约定 / system+user 分离 / JSON fallback 思路）
- **Memory feedback_capability_design 应用证据**：grep `class .*AISuggestor` 应返回 0（确认未为每个 plugin 写独立 LLM 类）
- 下一步指引：plan 07（capability fallback service layer）+ plan 08（E2E browser-harness gate）
</output>
