"""CardBuilder 抽象基类 + HitlCardPayload 不可变数据（Plan 04-05）。

设计参考 docs/reading-im-sdk-04-05-providers-2026-05-17.md：
- 抽象层不引入任何 IM SDK 依赖
- HitlCardPayload 是 @dataclass(frozen=True)（CLAUDE.md immutability）
- 各 Provider plan（04-06..09）实现 build_hitl_card → 返回各家 native 卡片 dict

CLAUDE.md 2.7 Dify 参考：Dify email_delivery 用 Jinja 模板渲染 HTML；
IM 卡片走 JSON 结构化字段（飞书 / Slack Block Kit 等），不走模板 — 各家 SDK 接受 dict 直接序列化。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class HitlCardPayload:
    """HITL 决策卡片不可变载荷 — 跨 5 家 Provider 通用字段。

    各 Provider 的 build_hitl_card 接受此对象，内部转换为各家 native 卡片 dict。
    frozen=True 保证传入后不被修改（CLAUDE.md immutability）。

    Fields:
        flow_title: 流程名称（如 "员工入职流程"）
        node_title: 节点名称（如 "HR 审批"）
        applicant_name: 申请人姓名
        actor_name: 当前审批人姓名
        deadline_at: 截止时间 ISO 字符串（前端展示用，各 Provider 不动）
        description: 节点描述
        deeplinks: 按钮深链列表 [{"action": "approve", "url": "..."}, ...]
                   4 个标准 action：approve / return / reject / detail
    """

    flow_title: str
    node_title: str
    applicant_name: str
    actor_name: str
    deadline_at: str
    description: str
    deeplinks: tuple[dict[str, str], ...] = field(default_factory=tuple)
    # tuple + default_factory=tuple 保证 immutable（dataclass frozen 不防 list 内部 mutate）


class CardBuilder(Protocol):
    """卡片构造器协议 — 各 Provider plan 自实现。

    typing.Protocol 鸭子类型：实现 build_hitl_card / build_supplement_text 即可
    （不需要继承基类，与 IMProvider 设计一致）。
    """

    provider_name: str

    def build_hitl_card(self, payload: HitlCardPayload) -> dict[str, Any]:
        """构造 HITL 决策卡片（各家 native 格式 dict）。"""
        ...

    def build_supplement_text(self, *, who_processed: str, action: str) -> str:
        """构造"已被 X 处理"补充文本（≤ 200 字）。"""
        ...
