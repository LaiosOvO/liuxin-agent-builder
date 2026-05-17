"""hitl_schema + notification_schema channels 扩展单元测试（Plan 04-10 Task 2）。

测试矩阵（≥ 4 用例）：
1. test_hitl_schema_default_notify_channels_is_email — 默认 ['email']
2. test_hitl_schema_invalid_channel_rejected — 'sms' → jsonschema ValidationError
3. test_hitl_schema_multiple_channels_accepted — ['email','feishu','wecom'] 通过
4. test_hitl_schema_empty_channels_rejected — [] minItems=1
5. test_hitl_schema_notify_channels_required_minItems — minItems=1 必须 ≥1
6. test_hitl_schema_backward_compat_without_notify_channels — 旧 DSL 无字段仍通过
7. test_notification_schema_default_channels_is_email — 默认 ['email']
8. test_notification_schema_multiple_channels_ok — 7 个值全合法
9. test_notification_schema_empty_channels_rejected — [] minItems=1
10. test_notification_schema_invalid_channel_rejected — 'sms' → ValidationError
11. test_notification_schema_wechat_not_in_enum_anymore — 'wechat' 应已替换为 'wecom'
12. test_shared_enum_consistency — hitl_schema 与 notification_schema 共享 enum
"""
from __future__ import annotations

import pytest
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from app.agent_builder.workflow.node_schemas.hitl_schema import (
    HITL_NODE_SCHEMA,
    NOTIFY_CHANNELS_ENUM,
)
from app.agent_builder.workflow.node_schemas.notification_schema import (
    NOTIFICATION_NODE_SCHEMA,
)


# ── HITL schema notify_channels 测试 ─────────────────────────────────────────


def test_hitl_schema_default_notify_channels_is_email():
    """HITL schema notify_channels 字段 default = ['email']。"""
    properties = HITL_NODE_SCHEMA["properties"]
    assert "notify_channels" in properties

    field = properties["notify_channels"]
    assert field["type"] == "array"
    assert field["default"] == ["email"]
    assert field["minItems"] == 1


def test_hitl_schema_invalid_channel_rejected():
    """HITL schema notify_channels=['email','sms'] → ValidationError（sms 不在 enum）。"""
    validator = Draft7Validator(HITL_NODE_SCHEMA)
    invalid_config = {
        "assignees": ["user@example.com"],
        "notify_channels": ["email", "sms"],
    }

    errors = list(validator.iter_errors(invalid_config))
    assert len(errors) >= 1
    # 错误应明确指向 sms 不在 enum
    error_text = " ".join(str(e) for e in errors)
    assert "sms" in error_text or "enum" in error_text.lower()


def test_hitl_schema_multiple_channels_accepted():
    """HITL schema notify_channels=['email','feishu','wecom'] → 通过（3 合法值）。"""
    validator = Draft7Validator(HITL_NODE_SCHEMA)
    valid_config = {
        "assignees": ["user@example.com"],
        "notify_channels": ["email", "feishu", "wecom"],
    }

    errors = list(validator.iter_errors(valid_config))
    assert errors == [], f"应通过但报错: {errors}"


def test_hitl_schema_empty_channels_rejected():
    """HITL schema notify_channels=[] → ValidationError (minItems=1)。"""
    validator = Draft7Validator(HITL_NODE_SCHEMA)
    invalid_config = {
        "assignees": ["user@example.com"],
        "notify_channels": [],
    }

    errors = list(validator.iter_errors(invalid_config))
    assert len(errors) >= 1


def test_hitl_schema_notify_channels_minItems_constraint():
    """HITL schema notify_channels minItems=1 严格校验。"""
    field = HITL_NODE_SCHEMA["properties"]["notify_channels"]
    assert field["minItems"] == 1


def test_hitl_schema_backward_compat_without_notify_channels():
    """HITL 旧 DSL（无 notify_channels 字段）仍通过校验（向后兼容）。"""
    validator = Draft7Validator(HITL_NODE_SCHEMA)
    legacy_config = {
        "assignees": ["user@example.com"],
        "timeout_seconds": 86400,
    }

    errors = list(validator.iter_errors(legacy_config))
    assert errors == [], f"旧 DSL 无 notify_channels 字段应通过: {errors}"


def test_hitl_schema_all_7_channels_individually_valid():
    """HITL schema 7 个 channel 值都合法（feishu/wecom/dingtalk/slack/mattermost/webhook+email）。"""
    validator = Draft7Validator(HITL_NODE_SCHEMA)

    for channel in ["email", "feishu", "wecom", "dingtalk", "slack", "mattermost", "webhook"]:
        config = {
            "assignees": ["user@example.com"],
            "notify_channels": [channel],
        }
        errors = list(validator.iter_errors(config))
        assert errors == [], f"channel={channel} 应通过: {errors}"


# ── Notification schema channels 测试 ─────────────────────────────────────────


def test_notification_schema_default_channels_is_email():
    """Notification schema channels 字段 default = ['email']。"""
    field = NOTIFICATION_NODE_SCHEMA["properties"]["channels"]
    assert field["default"] == ["email"]
    assert field["minItems"] == 1


def test_notification_schema_multiple_channels_ok():
    """Notification schema channels=['email','feishu','slack'] → 通过。"""
    validator = Draft7Validator(NOTIFICATION_NODE_SCHEMA)
    valid_config = {
        "channels": ["email", "feishu", "slack"],
        "recipients": ["user@example.com"],
        "subject": "测试",
        "body": "正文",
    }

    errors = list(validator.iter_errors(valid_config))
    assert errors == [], f"应通过但报错: {errors}"


def test_notification_schema_empty_channels_rejected():
    """Notification schema channels=[] → ValidationError (minItems=1)。"""
    validator = Draft7Validator(NOTIFICATION_NODE_SCHEMA)
    invalid_config = {
        "channels": [],
        "recipients": ["user@example.com"],
        "subject": "x",
        "body": "y",
    }

    errors = list(validator.iter_errors(invalid_config))
    assert len(errors) >= 1


def test_notification_schema_invalid_channel_rejected():
    """Notification schema channels=['sms'] → ValidationError。"""
    validator = Draft7Validator(NOTIFICATION_NODE_SCHEMA)
    invalid_config = {
        "channels": ["sms"],
        "recipients": ["user@example.com"],
        "subject": "x",
        "body": "y",
    }

    errors = list(validator.iter_errors(invalid_config))
    assert len(errors) >= 1


def test_notification_schema_wechat_replaced_by_wecom():
    """Plan 04-10 修正：'wechat' 不在 enum，应是 'wecom'。"""
    field = NOTIFICATION_NODE_SCHEMA["properties"]["channels"]
    enum_values = field["items"]["enum"]
    assert "wechat" not in enum_values, "Plan 04-10 应替换 wechat → wecom"
    assert "wecom" in enum_values


def test_notification_schema_backward_compat_without_channels():
    """Notification 旧 DSL（无 channels 字段）仍通过校验（向后兼容）。"""
    validator = Draft7Validator(NOTIFICATION_NODE_SCHEMA)
    legacy_config = {
        "recipients": ["user@example.com"],
        "subject": "测试",
        "body": "正文",
    }

    errors = list(validator.iter_errors(legacy_config))
    assert errors == [], f"旧 DSL 无 channels 字段应通过: {errors}"


# ── 共享 enum 一致性测试 ─────────────────────────────────────────────────────


def test_shared_enum_consistency_hitl_and_notification():
    """hitl_schema.NOTIFY_CHANNELS_ENUM 与 notification_schema channels enum 共享同一 list。"""
    hitl_field = HITL_NODE_SCHEMA["properties"]["notify_channels"]
    notif_field = NOTIFICATION_NODE_SCHEMA["properties"]["channels"]

    assert hitl_field["items"]["enum"] == notif_field["items"]["enum"]
    # 都引用 NOTIFY_CHANNELS_ENUM 常量
    assert hitl_field["items"]["enum"] is NOTIFY_CHANNELS_ENUM
    assert notif_field["items"]["enum"] is NOTIFY_CHANNELS_ENUM


def test_shared_enum_contains_7_values():
    """NOTIFY_CHANNELS_ENUM 含 7 个值（email + 5 IM + webhook）。"""
    assert len(NOTIFY_CHANNELS_ENUM) == 7
    assert set(NOTIFY_CHANNELS_ENUM) == {
        "email",
        "feishu",
        "wecom",
        "dingtalk",
        "slack",
        "mattermost",
        "webhook",
    }


def test_notification_schema_all_7_channels_individually_valid():
    """Notification schema 7 个 channel 值都合法。"""
    validator = Draft7Validator(NOTIFICATION_NODE_SCHEMA)

    for channel in NOTIFY_CHANNELS_ENUM:
        config = {
            "channels": [channel],
            "recipients": ["user@example.com"],
            "subject": "x",
            "body": "y",
        }
        errors = list(validator.iter_errors(config))
        assert errors == [], f"channel={channel} 应通过: {errors}"
