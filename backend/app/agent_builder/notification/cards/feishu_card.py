"""飞书 Interactive Card 2.0 卡片构造器（Plan 04-06）。

设计参考 docs/reading-im-sdk-04-06-feishu-2026-05-17.md §5（卡片 schema）+ §6（patch_message）。

纯函数 — 不引入飞书 SDK 依赖（SDK 调用留 FeishuProvider）：
- build_feishu_hitl_card：HITL 决策卡片（header + 4 字段双列 + 详情 + 4 按钮）
- build_feishu_processed_card：决策后的只读卡片（移除 action + 追加 note 角标 + header 变灰）

CLAUDE.md immutability：
- 入参 dict 不修改（构造新 dict + 浅拷贝）
- 调用方传入的 deeplinks 列表也不修改

按钮颜色映射（飞书原生 type）：
- approve → primary（蓝色，强调）
- reject  → danger（红色，警示）
- return  → default（浅灰描边）
- 其他    → default
"""
from __future__ import annotations

from typing import Any


# ── 按钮颜色 + 中文标签映射 ─────────────────────────────────────────────────────
# 与 04-05 IMProvider HitlCardPayload.deeplinks 标准 action 一致：
#   approve / return / reject / detail / submit


_ACTION_COLOR_MAP: dict[str, str] = {
    "approve": "primary",
    "return": "default",
    "reject": "danger",
    "detail": "default",
    "submit": "default",
}

_ACTION_LABEL_MAP: dict[str, str] = {
    "approve": "同意",
    "return": "退回",
    "reject": "拒绝",
    "detail": "查看详情",
    "submit": "提交",
}


def _build_button(deeplink: dict[str, str]) -> dict[str, Any]:
    """构造单个 multi_url 按钮（参考 reading doc §5.3）。

    Args:
        deeplink: {"action": "approve", "url": "https://..."}

    Returns:
        飞书 Interactive Card 2.0 button element dict
    """
    action = deeplink["action"]
    url = deeplink["url"]
    label = _ACTION_LABEL_MAP.get(action, action)
    color = _ACTION_COLOR_MAP.get(action, "default")

    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": label},
        "type": color,
        "multi_url": {
            # 4 URL 字段全填（reading doc §5.3）— 否则飞书桌面端降级
            "url": url,
            "pc_url": url,
            "android_url": url,
            "ios_url": url,
        },
    }


def build_feishu_hitl_card(
    *,
    flow_title: str,
    node_title: str,
    applicant_name: str,
    actor_name: str,
    deadline_at: str,
    description: str,
    deeplinks: list[dict[str, str]] | tuple[dict[str, str], ...],
) -> dict[str, Any]:
    """构造飞书 Interactive Card 2.0 HITL 决策卡片。

    参考 reading-im-sdk-04-06-feishu §5 卡片骨架 + §5.4 按钮颜色映射。

    Args:
        flow_title: 流程名称（如 "员工入职流程"）— 显示在 header
        node_title: 节点名称（如 "HR 审批"）
        applicant_name: 申请人姓名
        actor_name: 当前审批人姓名
        deadline_at: 截止时间 ISO 字符串
        description: 节点描述
        deeplinks: 按钮深链列表 [{"action": "approve", "url": "..."}, ...]
                   tuple 或 list 都接受（HitlCardPayload.deeplinks 是 tuple）

    Returns:
        飞书 Interactive Card 2.0 JSON dict（**未** json.dumps，序列化由 Provider 做）
    """
    # 按 deeplinks 顺序生成按钮（保留调用方排序）
    buttons = [_build_button(dl) for dl in deeplinks]

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"📋 审批待办：{flow_title}",
            },
            "template": "blue",
        },
        "elements": [
            {
                "tag": "div",
                "fields": [
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**节点**\n{node_title}",
                        },
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**申请人**\n{applicant_name}",
                        },
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**审批人**\n{actor_name}",
                        },
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**截止时间**\n{deadline_at}",
                        },
                    },
                ],
            },
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**详情**\n{description}",
                },
            },
            {"tag": "hr"},
            {"tag": "action", "actions": buttons},
        ],
    }


def build_feishu_processed_card(
    *,
    original_card: dict[str, Any],
    processed_by: str,
) -> dict[str, Any]:
    """构造决策后的只读卡片（patch_message 用）— 参考 reading doc §6.3。

    与 build_feishu_hitl_card 输出结构兼容。修改点：
    - 过滤 action 元素（移除按钮）
    - 末尾追加 note 角标 "✓ 已被 X 处理"
    - header template 改为 grey（视觉示意"已处理"）

    CLAUDE.md immutability：不修改入参 original_card，构造全新 dict 返回。

    Args:
        original_card: 原始卡片 dict（通常是 build_feishu_hitl_card 的输出）
        processed_by: 处理人姓名（显示在 note 角标）

    Returns:
        新卡片 dict — 可序列化后传给 client.im.v1.message.patch
    """
    # 浅拷贝 header dict（确保不修改入参）
    new_header = {**original_card.get("header", {})}
    new_header["template"] = "grey"

    # 过滤 action 元素（保留 div / hr / note 等）— 列表推导创建新列表
    new_elements: list[dict[str, Any]] = [
        element
        for element in original_card.get("elements", [])
        if element.get("tag") != "action"
    ]
    # 追加 note 角标
    new_elements.append(
        {
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": f"✓ 已被 {processed_by} 处理",
                }
            ],
        }
    )

    return {
        **original_card,        # 浅拷贝顶层字段（config 等）
        "header": new_header,   # 覆盖为新 header
        "elements": new_elements,  # 覆盖为新 elements list
    }


def build_feishu_supplement_text(*, who_processed: str, action: str) -> str:
    """构造"已被 X 处理"补充文本（≤ 200 字）— 不支持 patch 时兜底。

    Args:
        who_processed: 处理人姓名
        action: 决策动作（approve/return/reject 等）

    Returns:
        中文文本，可直接作为 send_supplement_text 的 text 参数
    """
    label = _ACTION_LABEL_MAP.get(action, action)
    return f"该审批流程已被 {who_processed} {label}，无需进一步操作。"
