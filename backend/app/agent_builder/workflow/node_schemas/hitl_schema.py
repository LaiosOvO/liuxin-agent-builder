"""HITL 节点 Schema 定义（Plan 03-02 + Plan 04-10）。

HITL 节点（Human-In-The-Loop）：
- 流程在此节点暂停（LangGraph 1.2 interrupt）
- 通过邮件深链 + IM 卡片（Plan 04-10 多通道）通知 assignees 决策
- 用户 POST /hitl/action/<jwt>（03-06）→ Command(resume) 推进流程

config 字段（DSL 编辑时校验）：
- assignees（必填，≥1）：决策人 user_id / user_email / role: / dept: 列表
- timeout_seconds（默认 86400 = 24h）：超时升级阈值
- form_schema（可选）：决策表单 JSON Schema（前端 RJSF 渲染 + 服务端校验）
- escalate_to（可选）：超时升级人（v1 string，Phase 5 支持 role:/dept: 解析）
- email_recipients（可选）：补充收件人邮箱列表
- notify_channels（Plan 04-10 NOTI-08）：通知通道列表（默认 ['email']，向后兼容）

设计参考 docs/reading-dify-03-02-hitl-executor-2026-05-17.md §4.1：
- Dify EmailRecipients.items[] (BoundRecipient | ExternalRecipient) 简化为 assignees + email_recipients 两列

Plan 04-10 多通道扩展（reading doc docs/reading-dify-04-10-multichannel-2026-05-17.md）：
- notify_channels enum: email/feishu/wecom/dingtalk/slack/mattermost/webhook
- 默认 ['email']（向后兼容 Phase 3 — 现有 DSL 无 notify_channels 字段时仍走 email-only 路径）
"""
from __future__ import annotations

# Plan 04-10：HITL + Notification 节点共享的通道 enum（7 个值）
# 与 NotificationService._ALL_KNOWN_CHANNELS 一致
NOTIFY_CHANNELS_ENUM: list[str] = [
    "email",
    "feishu",
    "wecom",
    "dingtalk",
    "slack",
    "mattermost",
    "webhook",
]

# HITL 节点 JSON Schema（DSL 编辑器 / 02-02 DSLValidator 兼容）
HITL_NODE_SCHEMA: dict = {
    "type": "object",
    "required": ["assignees"],
    "additionalProperties": False,
    "properties": {
        "assignees": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "minItems": 1,
            "description": (
                "决策人列表，每项可为 user_id / email / 'role:admin' / 'dept:HR' "
                "（v1 single 模式：取 assignees[0] 为 current_actor）"
            ),
        },
        "timeout_seconds": {
            "type": "integer",
            "minimum": 60,
            "maximum": 30 * 86400,  # 最长 30 天
            "default": 86400,  # 默认 24h
            "description": "节点超时秒数（决定 deadline_at + 催办首次触发）",
        },
        "form_schema": {
            "type": "object",
            "description": (
                "决策表单 JSON Schema（Draft-7 子集），前端 RJSF 渲染 + "
                "服务端用 jsonschema 4.x 校验"
            ),
            "default": {},
        },
        "escalate_to": {
            "type": "string",
            "minLength": 1,
            "description": "超时升级人（v1 user_email；Phase 5 支持 role:/dept:）",
        },
        "email_recipients": {
            "type": "array",
            "items": {"type": "string", "format": "email"},
            "description": "补充收件人邮箱列表（assignees 之外抄送 / 直接通知）",
            "default": [],
        },
        # Plan 04-10 NOTI-08 多通道并发投递
        "notify_channels": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": NOTIFY_CHANNELS_ENUM,
            },
            "minItems": 1,
            "default": ["email"],
            "description": (
                "通知通道列表（NOTI-08 多通道并发投递）；"
                "默认 ['email'] 向后兼容 Phase 3。"
                "IM 通道需 assignee 用户在 users.im_bindings 配置对应映射。"
            ),
        },
        # ── 由 ExecutionEngine 注入（不在 DSL 编辑时由用户填写） ───────────
        # 这些字段不出现在 config，由节点 enter 时由 service 层动态写入
        # interrupt payload。在此声明仅作文档用。
    },
}

# HITL 节点输出字段
# 节点 resume 完成后写入 state[node_id] = {action, reason, form_data, ...}
HITL_OUTPUT_FIELDS: frozenset[str] = frozenset({
    "action",  # 决策动作：submit / approve / return / reject
    "reason",  # 决策原因（可选）
    "form_data",  # 表单数据（已通过 form_schema 校验）
    "actor_id",  # 决策人 user_id
    "jti",  # 消费的 token jti（用于审计 + 链路追踪）
    "ip",  # 决策时客户端 IP（NET-05）
    "ua",  # 决策时客户端 UA（NET-05）
    "completed_at",  # 完成时间（ISO8601）
})
