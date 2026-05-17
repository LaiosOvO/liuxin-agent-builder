r"""Phase 4.5 — bot.yaml Pydantic v2 schema（R-IM-01 + Pitfall 7/8 防护）。

设计要点（参考 docs/reading-dify-04_5-01-trigger-nodes-2026-05-18.md + 设计稿 §4）:

- ``ConfigDict(extra="forbid")`` 12 sub-model 全开 — 让 YAML/JSON typo 立即 raise
  ValidationError（防 dispatcher 读到 None 默认值 silent miss-route）
- ``name`` 字段全部带 ``pattern`` regex（与 Phase 5.A manifest.py 模式一致）
- 3 个 ``@model_validator(mode="after")`` 在顶层 ``BotConfig``：
    a) ``at_least_one_trigger``: dm / at_mention / keywords 至少一个 truthy（防死 bot）
    b) ``intents_must_subset_commands``: intents - {ai_qa} ⊆ commands.name（Pitfall 8）
    c) ``no_plaintext_credentials``: 递归 model_dump 检测 ``_token``/``_secret``/``_key``
       后缀且 value ≥ 32 char 的明文凭据 → raise（Pitfall 7 + N-IM-03）

不引入：
- ``arbitrary_types_allowed=True`` —— 强类型 baseline 与 5.A 一致
- ``extra="allow"`` —— 防 typo 第一防线

License: 借鉴 Dify ``api/core/trigger/entities/entities.py`` Pydantic v2 模式
（AGPL-3.0），本 module 100% 独立创作，不拷贝任何 Dify 源码。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# 启发式凭据检测后缀（N-IM-03 + Pitfall 7）
# 命中规则：字段名以这些后缀结尾 + value 是 str + len(value) >= 32
_CREDENTIAL_SUSPICIOUS_SUFFIXES: tuple[str, ...] = (
    "_token",
    "_secret",
    "_key",
)

# 命中后允许的 value 最大长度（< 32 视为占位符/示例，不触发警报）
_CREDENTIAL_MIN_LENGTH: int = 32


# ── 子模型: CommandArg / CommandSpec ─────────────────────────────────────────


class CommandArg(BaseModel):
    """单命令参数声明 — 参数粒度。

    Fields:
        name: 参数名（小写蛇形，最长 64 字符）
        type: 参数类型（string / int / uuid8_or_uuid36 / enum / bool）
        pattern: 字符串类型时的 regex 校验（仅 type=string 生效）
        choices: enum 类型时的合法值列表（仅 type=enum 生效）
        required: 是否必填
        multiline: 字符串是否允许多行
        min_length: 字符串最小长度
        default: 默认值（仅 required=False 时合法）
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    type: Literal["string", "int", "uuid8_or_uuid36", "enum", "bool"]
    pattern: str | None = None
    choices: list[str] | None = None
    required: bool = True
    multiline: bool = False
    min_length: int | None = None
    default: str | None = None


class SelfApplySpec(BaseModel):
    """自助起流程模式（自然语言短路触发命令）。

    Fields:
        enabled: 是否启用 self-apply 模式
        sentinel_phrases: 短路关键词列表（如 ["我要离职", "申请离职"]）
        arg_default: 命中关键词时填充的 args 默认（如 employee_id="${ctx.user_name}"）
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    sentinel_phrases: list[str] = Field(default_factory=list)
    arg_default: dict[str, str] = Field(default_factory=dict)


class CommandSpec(BaseModel):
    """单命令声明 — handler 注册条目。

    Fields:
        name: 命令名（小写蛇形 + 连字符，最长 64 字符）
        description: 命令说明（help 自动生成会用到）
        args: 参数列表（空 list = 无参命令）
        self_apply: 自助起流程配置（仅适用 start 类命令）
        handler: handler 函数引用（如 "handlers.flow:start_flow"）
        allowed_roles: 允许执行的角色列表（与 Phase 1 RoleCode 对齐）
        category: 命令分类（help 自动生成按此分组）
        example_invocations: 示例调用列表（help 显示）
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    description: str = Field(min_length=1)
    args: list[CommandArg] = Field(default_factory=list)
    self_apply: SelfApplySpec | None = None
    handler: str = Field(min_length=1)
    allowed_roles: list[str] = Field(default_factory=lambda: ["admin"])
    category: str | None = None
    example_invocations: list[str] = Field(default_factory=list)


# ── 子模型: TriggersSpec / IdentitySpec ──────────────────────────────────────


class TriggersSpec(BaseModel):
    """触发条件 — DM / @mention / keywords 三 OR 关系。

    Fields:
        dm: 任意 DM 触发
        at_mention: @bot 触发
        keywords: 触发关键词列表（消息含任一关键词即触发）

    BotConfig.at_least_one_trigger 校验：三者必须至少一个为 truthy（防死 bot）。
    """

    model_config = ConfigDict(extra="forbid")

    dm: bool = True
    at_mention: bool = True
    keywords: list[str] = Field(default_factory=list)


class IdentitySpec(BaseModel):
    """sender_name → agent-builder users 表对齐策略。

    Fields:
        source: 身份源 (agent_builder_users / jit_create)
        on_unknown: 未识别用户处理 (reject_friendly / guest_mode / auto_create)
        unknown_hint: 拒绝时给用户的友好提示
    """

    model_config = ConfigDict(extra="forbid")

    source: Literal["agent_builder_users", "jit_create"] = "agent_builder_users"
    on_unknown: Literal["reject_friendly", "guest_mode", "auto_create"] = "reject_friendly"
    unknown_hint: str | None = None


# ── 子模型: LLMIntentRouterSpec / AIQaSpec / FallbackSpec ───────────────────


class LLMIntentRouterSpec(BaseModel):
    """LLM 意图分类配置（命令不命中白名单时兜底）。

    Fields:
        enabled: 是否启用 LLM 兜底
        confidence_threshold: 路由阈值（< threshold 走 ai_qa）
        timeout_seconds: LLM 单次调用超时（避免阻塞 dispatcher）
        intents: 可识别意图清单（必须 ⊆ commands.name ∪ {"ai_qa"}）
        prompt_template_path: prompt 模板路径
        llm: LLM provider 引用（如 "${global.default_llm}"）
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    intents: list[str] = Field(min_length=1)
    prompt_template_path: str = Field(min_length=1)
    llm: str = Field(min_length=1)


class AIQaSpec(BaseModel):
    """自由问答兜底配置（无明确意图时降级到 LLM 直答）。

    Fields:
        enabled: 是否启用 ai_qa 兜底
        prompt_template_path: ai_qa prompt 模板路径
        max_tokens: LLM 单次回答 token 上限（防过长回复刷屏）
        system_message: bot 人设 system prompt
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    prompt_template_path: str = Field(min_length=1)
    max_tokens: int = Field(default=500, gt=0, le=4000)
    system_message: str | None = None


class FallbackSpec(BaseModel):
    """命令不命中白名单时的兜底链（intent_router → ai_qa）。

    Fields:
        llm_intent_router: LLM 意图分类配置
        ai_qa: 自由问答兜底配置
    """

    model_config = ConfigDict(extra="forbid")

    llm_intent_router: LLMIntentRouterSpec | None = None
    ai_qa: AIQaSpec | None = None


# ── 子模型: AuditSpec / RateLimitSpec / HelpSpec ────────────────────────────


class RateLimitSpec(BaseModel):
    """命令限流配置（R-IM-12，防误刷 / 防 LLM 费用炸）。

    Fields:
        per_user_per_minute: 单用户每分钟最多 dispatch 次数（fixed-window counter）
    """

    model_config = ConfigDict(extra="forbid")

    per_user_per_minute: int = Field(default=10, gt=0, le=600)


class AuditSpec(BaseModel):
    """dispatch 审计配置（R-IM-11）。

    Fields:
        log_dispatch: 是否每次 dispatch 入 bot_audit_logs 表
        rate_limit: 限流配置（None = 无限流）
    """

    model_config = ConfigDict(extra="forbid")

    log_dispatch: bool = True
    rate_limit: RateLimitSpec | None = None


class HelpSpec(BaseModel):
    """help 命令自动生成配置（R-IM-03）。

    Fields:
        auto_generate: 是否启用 help 自动生成（False = 不内置 help handler）
        template_path: 可选自定义 help wrapper 模板
        group_by: 命令分组维度（category / 无分组）
        show_examples: 是否在 help 中显示 example_invocations
    """

    model_config = ConfigDict(extra="forbid")

    auto_generate: bool = True
    template_path: str | None = None
    group_by: Literal["category", "none"] = "category"
    show_examples: bool = True


# ── 子模型: ProviderSpec ─────────────────────────────────────────────────────


class ProviderSpec(BaseModel):
    """IM 平台 + 凭据 env 前缀（凭据本身仅 env 注入，不入 YAML — N-IM-03）。

    Fields:
        type: IM 平台类型（v1 仅 mattermost；Phase 5.E 扩展 feishu/wecom/dingtalk/slack）
        config_env_prefix: 凭据 env 变量前缀（必须 UPPER，如 ``MM_``、``LARK_``）
            实际凭据由 env 注入（``${prefix}BOT_TOKEN`` / ``${prefix}URL`` / ``${prefix}TEAM``）
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["mattermost"] = "mattermost"
    config_env_prefix: str = Field(min_length=1, pattern=r"^[A-Z][A-Z0-9_]{0,31}$")


# ── 顶层 BotConfig ────────────────────────────────────────────────────────────


class BotConfig(BaseModel):
    r"""bot.yaml 顶层 schema — 1 个 bot 1 份 YAML。

    Fields:
        name: bot 名（小写蛇形 + 连字符，3-32 字符）
        description: bot 简介（help 自动生成会用到）
        provider: IM 平台 + env 前缀
        triggers: 触发条件（DM / @mention / keywords）
        identity: sender 身份对齐策略
        commands: 命令清单（至少 1 个）
        fallback: 命令不命中兜底链（LLM intent_router → ai_qa）
        audit: 审计 + 限流配置
        help: help 命令自动生成配置

    Validators（三道闸）:
        - at_least_one_trigger: dm/at_mention/keywords 至少一个 truthy（防死 bot）
        - intents_must_subset_commands: intents - {ai_qa} ⊆ commands.name（Pitfall 8）
        - no_plaintext_credentials: 任何 ``_token``/``_secret``/``_key`` 后缀且 value ≥ 32
          char 的 string 字段 → raise（Pitfall 7 + N-IM-03）
    """

    model_config = ConfigDict(extra="forbid")

    # ── 基础元数据 ─────────────────────────────────────────────────────────
    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_-]{2,31}$")
    description: str = Field(min_length=1)

    # ── Provider + 触发 + 身份 ────────────────────────────────────────────
    provider: ProviderSpec
    triggers: TriggersSpec
    identity: IdentitySpec

    # ── 命令清单 ───────────────────────────────────────────────────────────
    commands: list[CommandSpec] = Field(min_length=1)

    # ── 兜底链 + 审计 + help ──────────────────────────────────────────────
    fallback: FallbackSpec | None = None
    audit: AuditSpec | None = None
    help: HelpSpec | None = None

    # ── Validators ────────────────────────────────────────────────────────

    @model_validator(mode="after")
    def at_least_one_trigger(self) -> "BotConfig":
        """dm / at_mention / keywords 三者至少一个为 truthy —— 防死 bot。"""
        t = self.triggers
        if not (t.dm or t.at_mention or t.keywords):
            raise ValueError(
                "triggers: dm / at_mention / keywords 至少一个必须为 truthy"
                "（否则 bot 永远不会触发，等同 dead bot）"
            )
        return self

    @model_validator(mode="after")
    def intents_must_subset_commands(self) -> "BotConfig":
        """LLM intent router 配置的 intents - {ai_qa} 必须 ⊆ commands.name（Pitfall 8）。

        防御场景：YAML 配置 intents=['start','status','xxx_typo']，但 commands 没有
        'xxx_typo'，LLM 选了 'xxx_typo' 后 dispatcher 找不到对应 handler 会 silent
        fail（用户什么都收不到）。本 validator 启动期立即 raise。
        """
        if not (self.fallback and self.fallback.llm_intent_router):
            return self
        intents = set(self.fallback.llm_intent_router.intents) - {"ai_qa"}
        command_names = {c.name for c in self.commands}
        missing = intents - command_names
        if missing:
            raise ValueError(
                f"intents 含未声明的命令: {sorted(missing)}"
                f"（Pitfall 8 — 启动期 raise 防 silent miss-route）"
            )
        return self

    @model_validator(mode="after")
    def no_plaintext_credentials(self) -> "BotConfig":
        """检测明文凭据 — 任何字段名以 ``_token`` / ``_secret`` / ``_key`` 结尾
        且 value 是 str + len(value) >= 32 → raise（N-IM-03 + Pitfall 7）。

        递归扫描 model_dump() 全树（支持任意层嵌套 dict / list）。

        实现要点：
        - 仅当 value 是 str 才检测（数字 / bool / None 直接放行）
        - len(value) < 32 视为占位符 / 示例 / env var 名（如 ``MM_BOT_TOKEN``），放行
        - 命中后 raise 时**不打印 value 本身**（仅打印命中字段路径），防泄漏到日志
        """
        dumped = self.model_dump(mode="python")
        hits = _scan_plaintext_credentials(dumped, path="")
        if hits:
            raise ValueError(
                f"检测到疑似明文凭据字段（≥{_CREDENTIAL_MIN_LENGTH} 字符且字段名以 "
                f"{_CREDENTIAL_SUSPICIOUS_SUFFIXES} 结尾）: {hits}\n"
                f"凭据必须通过 env 注入（参考 provider.config_env_prefix），"
                f"严禁明文入 YAML（N-IM-03 + Pitfall 7）。"
            )
        return self


# ── helper: 递归扫描 model_dump 树检测疑似明文凭据 ────────────────────────────


def _scan_plaintext_credentials(node: Any, path: str) -> list[str]:
    """递归扫描 dict / list 检测疑似明文凭据。

    Args:
        node: 当前节点（dict / list / scalar）
        path: 当前节点在原树中的路径（用于命中报告）

    Returns:
        list[str]: 命中的字段路径列表（不含 value 本身，防泄漏）
    """
    hits: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            key_path = f"{path}.{k}" if path else str(k)
            # 命中规则：字段名后缀匹配 + value 是 str + 长度阈值
            if (
                isinstance(v, str)
                and len(v) >= _CREDENTIAL_MIN_LENGTH
                and any(str(k).endswith(suf) for suf in _CREDENTIAL_SUSPICIOUS_SUFFIXES)
            ):
                hits.append(key_path)
            # 递归
            hits.extend(_scan_plaintext_credentials(v, key_path))
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            idx_path = f"{path}[{idx}]"
            hits.extend(_scan_plaintext_credentials(item, idx_path))
    # scalar (str / int / bool / None) → 不递归
    return hits


__all__ = [
    "AIQaSpec",
    "AuditSpec",
    "BotConfig",
    "CommandArg",
    "CommandSpec",
    "FallbackSpec",
    "HelpSpec",
    "IdentitySpec",
    "LLMIntentRouterSpec",
    "ProviderSpec",
    "RateLimitSpec",
    "SelfApplySpec",
    "TriggersSpec",
]
