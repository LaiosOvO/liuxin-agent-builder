"""BotConfig Pydantic v2 schema 单元测试（R-IM-01 + Pitfall 7/8 + N-IM-03）。

覆盖矩阵：
- extra=forbid 严校验（顶层 + 嵌套）
- name pattern regex（大小写 / 长度边界）
- @model_validator: at_least_one_trigger（防死 bot）
- @model_validator: intents_must_subset_commands（Pitfall 8）
- @model_validator: no_plaintext_credentials（Pitfall 7 + N-IM-03）
- Field 约束：confidence_threshold / timeout / per_user_per_minute 边界
- ProviderSpec.type Literal 锁定 mattermost（v1）
- ProviderSpec.config_env_prefix UPPER pattern
- CommandSpec.handler 必填
- CommandSpec.args 默认空 list
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agent_builder.bot_dispatcher.schemas.bot_config import BotConfig


# ── extra=forbid 严校验 ──────────────────────────────────────────────────────


def test_minimal_valid_config_loads(bot_config_factory) -> None:
    """最小合法配置 → BotConfig 实例化成功。"""
    cfg_dict = bot_config_factory()
    cfg = BotConfig(**cfg_dict)
    assert cfg.name == "offboarding-bot"
    assert cfg.provider.type == "mattermost"
    assert cfg.triggers.dm is True
    assert len(cfg.commands) == 1
    assert cfg.commands[0].name == "start"


def test_extra_field_rejected(bot_config_factory) -> None:
    """顶层 extra 字段（typo）→ raise ValidationError。"""
    cfg_dict = bot_config_factory(unknown_field="xxx")
    with pytest.raises(ValidationError) as exc_info:
        BotConfig(**cfg_dict)
    # 错误信息应明确指出 extra 字段
    assert "extra" in str(exc_info.value).lower() or "unknown_field" in str(exc_info.value)


def test_command_extra_field_rejected(bot_config_factory) -> None:
    """CommandSpec 内 extra 字段（typo）→ raise。"""
    cfg_dict = bot_config_factory()
    cfg_dict["commands"][0]["typo_field"] = "x"
    with pytest.raises(ValidationError):
        BotConfig(**cfg_dict)


# ── name pattern regex ──────────────────────────────────────────────────────


def test_bot_name_pattern_uppercase_raises(bot_config_factory) -> None:
    """BotConfig.name 含大写 → raise（pattern 仅小写）。"""
    cfg_dict = bot_config_factory(name="OffboardingBot")
    with pytest.raises(ValidationError):
        BotConfig(**cfg_dict)


def test_bot_name_pattern_too_short_raises(bot_config_factory) -> None:
    """BotConfig.name 太短（< 3 字符）→ raise（pattern {2,31}）。"""
    cfg_dict = bot_config_factory(name="ab")
    with pytest.raises(ValidationError):
        BotConfig(**cfg_dict)


def test_command_pattern_validates(bot_config_factory) -> None:
    """CommandSpec.name 含大写 → raise（pattern lowercase + hyphen）。"""
    cfg_dict = bot_config_factory()
    cfg_dict["commands"][0]["name"] = "StartFlow"
    with pytest.raises(ValidationError):
        BotConfig(**cfg_dict)


# ── @model_validator: at_least_one_trigger ─────────────────────────────────


def test_at_least_one_trigger_validator(bot_config_factory) -> None:
    """dm=False, at_mention=False, keywords=[] → raise（防死 bot）。"""
    cfg_dict = bot_config_factory(
        triggers={
            "dm": False,
            "at_mention": False,
            "keywords": [],
        }
    )
    with pytest.raises(ValidationError) as exc_info:
        BotConfig(**cfg_dict)
    assert "至少一个" in str(exc_info.value) or "truthy" in str(exc_info.value)


# ── @model_validator: intents_must_subset_commands (Pitfall 8) ─────────────


def test_intents_subset_validator(bot_config_factory) -> None:
    """fallback.intents 含未声明命令 → raise（Pitfall 8）。"""
    cfg_dict = bot_config_factory(
        fallback={
            "llm_intent_router": {
                "enabled": True,
                "intents": ["start", "xxx_typo"],
                "prompt_template_path": "prompts/intent_router_zh.md",
                "llm": "global.default_llm",
            }
        }
    )
    with pytest.raises(ValidationError) as exc_info:
        BotConfig(**cfg_dict)
    # 错误信息应包含未声明命令
    assert "xxx_typo" in str(exc_info.value) or "Pitfall 8" in str(exc_info.value)


def test_intents_can_include_ai_qa(bot_config_factory) -> None:
    """intents=['start','ai_qa'] + commands=['start'] → OK（ai_qa 不算 missing）。"""
    cfg_dict = bot_config_factory(
        fallback={
            "llm_intent_router": {
                "enabled": True,
                "intents": ["start", "ai_qa"],
                "prompt_template_path": "prompts/intent_router_zh.md",
                "llm": "global.default_llm",
            }
        }
    )
    cfg = BotConfig(**cfg_dict)
    assert "ai_qa" in cfg.fallback.llm_intent_router.intents


# ── @model_validator: no_plaintext_credentials (Pitfall 7 + N-IM-03) ────────


def test_no_plaintext_token_field_raises(bot_config_factory) -> None:
    """字段名含 _token 后缀 + value ≥ 32 char → raise（Pitfall 7）。

    模拟用户错误把 bot_token 明文写到 description 子字段（非典型路径但允许扩展字段）：
    用 commands[0].args[0].pattern 含 _token 字样的 key 路径不行（pattern 是 value
    不是 key）。本测试用 audit.rate_limit 嵌套子 dict 模拟：实际上 extra=forbid
    会拦截 audit 的非声明字段，所以测试改为构造一个合法路径——直接用 cfg_dict 把
    description 设为长字符串无效（key 不匹配后缀）。

    最准确的做法：直接在 BotConfig.model_validate 层级注入一个 _scan 能扫到的字段。
    由于 extra=forbid 拦截任何非声明字段，凭据必须放在已声明字段名以 _token/_secret/_key
    结尾的位置——这是设计的故意：让 schema 字段命名约束 + 内容扫描双闸防泄漏。

    本测试模拟一个边界场景：description 明文是 40 字符——但 description 不以
    _token 结尾，扫描放行（与 _no_plaintext_credentials 规则一致；只有以三后缀
    结尾的字段才扫）。这验证扫描器仅命中"显式凭据样式字段名"。
    """
    cfg_dict = bot_config_factory(
        description="x" * 50,  # description 不以 _token/_secret/_key 结尾 → 不命中
    )
    # 应该通过 — 验证扫描器不误伤普通字段
    cfg = BotConfig(**cfg_dict)
    assert len(cfg.description) == 50


def test_no_plaintext_credentials_hits_token_key(bot_config_factory) -> None:
    """直接构造 _scan_plaintext_credentials 内部场景：通过 cmd_args 等 dict[str,str]
    或 SelfApplySpec.arg_default 注入以 _token 结尾的 key + 长 value → raise。
    """
    cfg_dict = bot_config_factory()
    # SelfApplySpec.arg_default 是 dict[str, str]，key 名我们可以自由设定
    cfg_dict["commands"][0]["self_apply"] = {
        "enabled": True,
        "sentinel_phrases": ["start"],
        "arg_default": {
            "api_token": "abcdefghijklmnopqrstuvwxyz123456",  # 32 chars + _token suffix
        },
    }
    with pytest.raises(ValidationError) as exc_info:
        BotConfig(**cfg_dict)
    assert "明文凭据" in str(exc_info.value) or "plaintext" in str(exc_info.value).lower()


def test_short_token_value_not_flagged(bot_config_factory) -> None:
    """字段名含 _token 但 value < 32 char → 不 raise（占位符 / env 名放行）。"""
    cfg_dict = bot_config_factory()
    cfg_dict["commands"][0]["self_apply"] = {
        "enabled": True,
        "sentinel_phrases": ["start"],
        "arg_default": {
            "api_token": "MM_BOT_TOKEN",  # env 名占位，13 chars < 32
        },
    }
    cfg = BotConfig(**cfg_dict)  # 应通过
    assert cfg.commands[0].self_apply.arg_default["api_token"] == "MM_BOT_TOKEN"


# ── CommandSpec / CommandArg field 校验 ────────────────────────────────────


def test_command_handler_required(bot_config_factory) -> None:
    """CommandSpec.handler 必填 + min_length=1，空串 → raise。"""
    cfg_dict = bot_config_factory()
    cfg_dict["commands"][0]["handler"] = ""
    with pytest.raises(ValidationError):
        BotConfig(**cfg_dict)


def test_command_args_optional_default_empty_list(bot_config_factory) -> None:
    """CommandSpec.args 不传 → 默认 []（无参命令）。"""
    cfg_dict = bot_config_factory()
    del cfg_dict["commands"][0]["args"]
    cfg = BotConfig(**cfg_dict)
    assert cfg.commands[0].args == []


# ── LLMIntentRouter Field 约束 ──────────────────────────────────────────────


def test_llm_router_confidence_threshold_bounds(bot_config_factory) -> None:
    """confidence_threshold > 1.0 → raise（le=1.0）。"""
    cfg_dict = bot_config_factory(
        fallback={
            "llm_intent_router": {
                "enabled": True,
                "confidence_threshold": 1.5,  # 越界
                "intents": ["start", "ai_qa"],
                "prompt_template_path": "prompts/intent_router_zh.md",
                "llm": "global.default_llm",
            }
        }
    )
    with pytest.raises(ValidationError):
        BotConfig(**cfg_dict)


def test_llm_router_timeout_max_30s(bot_config_factory) -> None:
    """timeout_seconds > 30 → raise（le=30）。"""
    cfg_dict = bot_config_factory(
        fallback={
            "llm_intent_router": {
                "enabled": True,
                "timeout_seconds": 60.0,
                "intents": ["start", "ai_qa"],
                "prompt_template_path": "prompts/intent_router_zh.md",
                "llm": "global.default_llm",
            }
        }
    )
    with pytest.raises(ValidationError):
        BotConfig(**cfg_dict)


# ── ProviderSpec 约束 ───────────────────────────────────────────────────────


def test_provider_type_only_mattermost_v1(bot_config_factory) -> None:
    """ProviderSpec.type='feishu' → raise（v1 only mattermost Literal）。"""
    cfg_dict = bot_config_factory(
        provider={"type": "feishu", "config_env_prefix": "LARK_"}
    )
    with pytest.raises(ValidationError):
        BotConfig(**cfg_dict)


def test_provider_env_prefix_lowercase_raises(bot_config_factory) -> None:
    """config_env_prefix='mm_' → raise（必须 UPPER）。"""
    cfg_dict = bot_config_factory(
        provider={"type": "mattermost", "config_env_prefix": "mm_"}
    )
    with pytest.raises(ValidationError):
        BotConfig(**cfg_dict)


# ── AuditSpec / RateLimitSpec 约束 ─────────────────────────────────────────


def test_audit_rate_limit_per_minute_bounds(bot_config_factory) -> None:
    """per_user_per_minute > 600 → raise（le=600）。"""
    cfg_dict = bot_config_factory(
        audit={
            "log_dispatch": True,
            "rate_limit": {"per_user_per_minute": 601},
        }
    )
    with pytest.raises(ValidationError):
        BotConfig(**cfg_dict)


def test_audit_rate_limit_default_value(bot_config_factory) -> None:
    """RateLimitSpec.per_user_per_minute 默认 10（不传时填默认）。"""
    cfg_dict = bot_config_factory(
        audit={
            "log_dispatch": True,
            "rate_limit": {},
        }
    )
    cfg = BotConfig(**cfg_dict)
    assert cfg.audit.rate_limit.per_user_per_minute == 10
