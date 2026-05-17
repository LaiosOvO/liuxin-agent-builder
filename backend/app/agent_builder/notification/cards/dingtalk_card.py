"""钉钉 ActionCard 构造器（Plan 04-08）。

参考 docs/reading-im-sdk-04-08-dingtalk-2026-05-17.md：
- 钉钉工作通知 ActionCard（msgtype="action_card"）
- btn_orientation="0" 横排按钮（PC + 手机端最佳兼容）
- 多按钮使用 btn_json_list（vs single_title / single_url 单按钮互斥）
- markdown 字段支持 ### / ** / 换行

CardBuilder Protocol 鸭子类型（cards/base.py 已定义），无需继承基类。

CLAUDE.md immutability：
- build_dingtalk_action_card 是 pure function（无状态、无副作用）
- 返回新 dict，不修改入参 payload
- _ZH_LABELS 是模块级常量（frozen dict 通过不暴露 mutator 保证）

CLAUDE.md §2.7 Dify 参考点：
- Dify email_delivery 用 Jinja 模板渲染 HTML；IM 卡片走结构化 JSON 字段（dict 直接序列化）
- 不引入模板引擎依赖（卡片字段固定 6 个，直接 f-string 即可）
"""
from __future__ import annotations

from typing import Any

from app.agent_builder.notification.cards.base import HitlCardPayload

# ── 按钮 label 映射（中文 UI 默认 — CLAUDE.md §4.3）──────────────────────────
# 决策板：未知 action 直接用原 string（防新 action 类型加入时报错）
_ZH_LABELS: dict[str, str] = {
    "approve": "同意",
    "return": "退回",
    "reject": "拒绝",
    "detail": "查看详情",
    "submit": "提交",
}


def _zh_label_for(action: str) -> str:
    """将 deeplink.action 映射为中文按钮 label。

    Args:
        action: 'approve' / 'return' / 'reject' / 'detail' / 其它

    Returns:
        中文 label；未知 action 返回原字符串（不抛错）
    """
    return _ZH_LABELS.get(action, action)


def build_dingtalk_action_card(payload: HitlCardPayload) -> dict[str, Any]:
    """构造钉钉工作通知 ActionCard JSON（pure function — 无副作用）。

    输出格式参考钉钉 OAPI 文档 + reading doc：
    {
        "msgtype": "action_card",
        "action_card": {
            "title": "审批待办：...",
            "markdown": "### ... \n\n**节点**: ...",
            "btn_orientation": "0",
            "btn_json_list": [
                {"title": "同意", "action_url": "https://..."},
                ...
            ]
        }
    }

    Args:
        payload: HitlCardPayload (frozen dataclass)

    Returns:
        钉钉 ActionCard JSON dict（送给 OAPI /topapi/message/corpconversation/asyncsend_v2
        请求体的 msg 字段）

    Notes:
        - btn_orientation="0" 硬编码横排（决策板：PC + 手机最佳兼容）
        - 单按钮 vs 多按钮：本项目固定走 btn_json_list（即使 1 个按钮也用列表，
          避免 single_title/single_url 与 btn_json_list 互斥触发的 OAPI 错误）
        - markdown 中各字段间空两行（"\n\n"）保证钉钉渲染识别段落
    """
    markdown = (
        f"### 审批待办：{payload.flow_title}\n\n"
        f"**节点**: {payload.node_title}\n\n"
        f"**申请人**: {payload.applicant_name}\n\n"
        f"**审批人**: {payload.actor_name}\n\n"
        f"**截止时间**: {payload.deadline_at}\n\n"
        f"**详情**:\n{payload.description}\n"
    )
    btn_json_list = [
        {
            "title": _zh_label_for(dl["action"]),
            "action_url": dl["url"],
        }
        for dl in payload.deeplinks
    ]
    return {
        "msgtype": "action_card",
        "action_card": {
            "title": f"审批待办：{payload.flow_title}",
            "markdown": markdown,
            "btn_orientation": "0",
            "btn_json_list": btn_json_list,
        },
    }


def build_dingtalk_supplement_text(*, who_processed: str, action: str) -> str:
    """构造"已被 X 处理"补发文本（≤ 200 字）。

    用于 04-10 multichannel fan-out 决策推进后通知其他 channel 用户 —
    因钉钉工作通知 ActionCard 不支持 update_card，走 text 补发兜底。

    Args:
        who_processed: 处理人姓名（脱敏后）
        action: 处理动作（approve/return/reject）

    Returns:
        中文文本，如 "流程已被 张三 [同意]"
    """
    label = _zh_label_for(action)
    return f"流程已被 {who_processed} [{label}]"
