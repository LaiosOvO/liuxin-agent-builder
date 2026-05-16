"""Notification 节点 Schema 定义（Plan 03-05 / NODE-07）。

Notification 节点（独立通知节点）：
- 不暂停 graph（vs HITL 节点的 interrupt），发送后立即继续
- 不创建 hitl_token、不参与催办循环（reminder_round 恒为 0）
- 复用 03-04 NotificationService.enqueue_generic_email 入队基础设施

config 字段（DSL 编辑时校验）：
- channels（默认 ["email"]）：通道列表，Phase 3 仅 email 实现；其他值会被 skip
- recipients（必填）：收件人列表 或 单个字符串（支持 Jinja2 {{ start.user.email }} 渲染）
- subject（必填）：邮件主题（支持 Jinja2 渲染）
- body（必填）：邮件正文（支持 Jinja2 渲染，autoescape 防 XSS）

设计参考 docs/reading-dify-03-05-notification-node-2026-05-17.md §4：
- Dify 没有独立 Notification 节点（通知耦合在 HumanInputForm 投递链）
- 本项目按 CONTEXT §NODE-07 解耦：channels enum + recipients (oneOf list|string) + Jinja 模板
"""
from __future__ import annotations

# Notification 节点 JSON Schema（DSL 编辑器 / DSLValidator 兼容）
NOTIFICATION_NODE_SCHEMA: dict = {
    "type": "object",
    "required": ["recipients", "subject", "body"],
    "additionalProperties": False,
    "properties": {
        "channels": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "email",
                    "feishu",
                    "wechat",
                    "dingtalk",
                    "slack",
                    "mattermost",
                    "webhook",
                ],
            },
            "minItems": 1,
            "default": ["email"],
            "description": (
                "通道列表（Phase 3 仅 email 实现）；含其他值时会被节点 skip "
                "（标记 skipped=True 不抛错，等 Phase 4+ 实现）"
            ),
        },
        "recipients": {
            "oneOf": [
                {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                },
                {"type": "string", "minLength": 1},
            ],
            "description": (
                "收件人：邮箱列表 或 单个邮箱字符串；支持 Jinja2 "
                "（如 '{{ start.applicant.email }}' 或 ['{{ a }}', '{{ b }}']）"
            ),
        },
        "subject": {
            "type": "string",
            "minLength": 1,
            "maxLength": 200,
            "description": "邮件主题（支持 Jinja2，不走 HTML autoescape 防注入由代码侧约束）",
        },
        "body": {
            "type": "string",
            "minLength": 1,
            "description": (
                "邮件正文（支持 Jinja2，autoescape=html 防 XSS）；"
                "用户输入字段如 description 已通过模板 escape"
            ),
        },
    },
}

# Notification 节点输出字段
# 节点执行后 state[node_id] = {sent_count, failed_count, notification_ids, skipped?}
NOTIFICATION_OUTPUT_FIELDS: frozenset[str] = frozenset({
    "sent_count",        # 成功入队数（int）
    "failed_count",      # 入队失败数（int）
    "notification_ids",  # 入队成功的 notifications.id 列表（list[int]）
    "skipped",           # 当 channels 不含 email 时为 True（其他字段为 0/[]）
})
