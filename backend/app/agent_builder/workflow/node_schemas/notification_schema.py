"""Notification 节点 Schema 定义（Plan 03-05 / NODE-07 + Plan 04-10 多通道）。

Notification 节点（独立通知节点）：
- 不暂停 graph（vs HITL 节点的 interrupt），发送后立即继续
- 不创建 hitl_token、不参与催办循环（reminder_round 恒为 0）
- 复用 03-04 NotificationService.enqueue_generic_email 入队基础设施
- Plan 04-10：channels 含 IM 时调 enqueue_generic_im_card 分发 send_hitl_card_job

config 字段（DSL 编辑时校验）：
- channels（默认 ["email"]）：通道列表，支持 email + 5 家 IM + webhook
- recipients（必填）：收件人列表 或 单个字符串（支持 Jinja2 {{ start.user.email }} 渲染）
  * email channel：必须是邮箱格式
  * IM channel：IM user_id（开发者从 users.im_bindings 取或直接配置）
- subject（必填）：邮件主题（支持 Jinja2 渲染）
- body（必填）：邮件正文（支持 Jinja2 渲染，autoescape 防 XSS）

设计参考 docs/reading-dify-03-05-notification-node-2026-05-17.md §4 +
docs/reading-dify-04-10-multichannel-2026-05-17.md：
- Dify 没有独立 Notification 节点（通知耦合在 HumanInputForm 投递链）
- 本项目按 CONTEXT §NODE-07 + §多通道并发投递 解耦：
  channels enum 7 个值 + recipients (oneOf list|string) + Jinja 模板

Plan 04-10 channels enum 修正：
- 替换 'wechat' → 'wecom'（与 NotificationService._IM_CHANNELS 一致）
- 与 hitl_schema.NOTIFY_CHANNELS_ENUM 共享同一个常量
"""
from __future__ import annotations

from app.agent_builder.workflow.node_schemas.hitl_schema import (
    NOTIFY_CHANNELS_ENUM,
)

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
                "enum": NOTIFY_CHANNELS_ENUM,  # 与 hitl_schema 共享 7 个值
            },
            "minItems": 1,
            "default": ["email"],
            "description": (
                "通道列表（Plan 04-10 支持 7 个值）；"
                "email 走 enqueue_generic_email，IM 走 enqueue_generic_im_card。"
                "向后兼容：现有 DSL 无 channels 字段时默认 ['email']。"
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
                "收件人：邮箱列表 / IM user_id 列表 / 单个字符串；支持 Jinja2。"
                "email channel 校验邮箱格式；IM channel 接受任意字符串。"
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
    "skipped",           # 当 channels 完全无法处理时为 True（兼容字段，Plan 04-10 通常不再触发）
})
