"""IMProvider Protocol + Registry — Phase 4 出站 IM 投递抽象层（Plan 04-05）。

设计参考 docs/reading-im-sdk-04-05-providers-2026-05-17.md：
- typing.Protocol 鸭子类型（不用 ABC）— CLAUDE.md python/patterns.md 推荐
- 模块级 dict Registry — startup 一次注册，无 DI 框架依赖
- Phase 4.5 接口预留：subscribe / verify_webhook_signature 在 Protocol 内声明，
  默认抛 NotImplementedError；Phase 4.5 Bot Trigger plan 各 Provider 实现

CLAUDE.md immutability：
- Provider 名常量定义为模块级 str（PROVIDER_FEISHU 等）
- KNOWN_PROVIDERS 为 frozenset 不可变集合
- Registry 内部 dict 是单例可变（startup 注册 / fixture clear），无并发问题
  （register/clear 仅 startup 与测试 fixture 调用）

CLAUDE.md 2.7 Dify 参考点：
- Dify model_provider_factory.get_provider_schema() → 本项目 get_provider(name)
- Dify provider lifecycle init/cleanup → 本项目 register_provider / clear_providers
- 不实现 Dify yaml schema 校验（IM Provider 数量固定 5，硬编码 PROVIDER_* 常量更简洁）
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

# ── Provider 名常量 ──────────────────────────────────────────────────────────
# 集中定义避免字符串 typo 散布到各调用处
PROVIDER_FEISHU = "feishu"
PROVIDER_WECOM = "wecom"
PROVIDER_DINGTALK = "dingtalk"
PROVIDER_SLACK = "slack"
PROVIDER_MATTERMOST = "mattermost"

KNOWN_PROVIDERS: frozenset[str] = frozenset(
    {
        PROVIDER_FEISHU,
        PROVIDER_WECOM,
        PROVIDER_DINGTALK,
        PROVIDER_SLACK,
        PROVIDER_MATTERMOST,
    }
)


@runtime_checkable
class IMProvider(Protocol):
    """IM 出站投递接口（Phase 4 出站 + Phase 4.5 入站预留）。

    Phase 4 必须实现：
    - send_hitl_card：HITL 决策卡片投递（4 按钮：approve/return/reject + 详情链接）
    - update_card：卡片状态更新（飞书/Slack/Mattermost 支持；企微/钉钉走 send_supplement_text）
    - send_supplement_text：补发文本（"已被 X 处理" 等）

    Phase 4.5 扩展（默认 NotImplementedError）：
    - subscribe：入站事件订阅（IM Bot 收 webhook）
    - verify_webhook_signature：入站请求签名校验

    各 Provider 实现见 04-06..09 plan：
    - FeishuProvider（lark-oapi 1.6.5，Interactive Card 2.0）
    - WeComProvider（wechatpy 1.8.18，Template Card）
    - DingTalkProvider（dingtalk-stream 0.24.3，ActionCard）
    - SlackProvider（slack-bolt 1.28.0，Block Kit）
    - MattermostProvider（httpx 直调，Markdown attachment）
    """

    name: str
    """Provider 名（PROVIDER_FEISHU / PROVIDER_WECOM / ...）"""

    async def send_hitl_card(
        self,
        *,
        recipient: str,
        flow_title: str,
        node_title: str,
        applicant_name: str,
        actor_name: str,
        deadline_at: str,
        description: str,
        deeplinks: list[dict[str, str]],
    ) -> dict[str, Any]:
        """投递 HITL 决策卡片。

        Args:
            recipient: IM 用户 ID（不是 email — 飞书 open_id / 企微 userid / Slack U... 等）
            flow_title: 流程名称（如 "员工入职流程"）
            node_title: 节点名称（如 "HR 审批"）
            applicant_name: 申请人姓名
            actor_name: 当前审批人姓名
            deadline_at: 截止时间 ISO 字符串
            description: 节点描述（form_schema.description 或节点 title）
            deeplinks: 按钮深链 [{"action": "approve", "url": "https://..."}, ...]
                       4 个标准 action：approve / return / reject / detail

        Returns:
            {
                "message_id": str,        # Provider 侧消息 ID（用于后续 update_card）
                "raw_response": dict      # 原始响应 dict（调试用）
            }

        Raises:
            ConnectionError / TimeoutError / OSError: 网络错误（tenacity 会重试）
            其他异常: 业务错误（不重试，直接 fail）
        """
        ...

    async def update_card(
        self,
        *,
        message_id: str,
        new_content: dict[str, Any],
    ) -> None:
        """更新已发送卡片（如改为只读 + "已被 X 处理"）。

        Phase 4 行为：
        - 飞书 / Slack / Mattermost：调用对应 update API
        - 企微 / 钉钉：raise NotImplementedError（应在调用方走 send_supplement_text 兜底）

        Args:
            message_id: send_hitl_card 返回的消息 ID
            new_content: 新内容（各家 Provider 自定义字段；通常含 text/blocks）
        """
        ...

    async def send_supplement_text(
        self,
        *,
        recipient: str,
        text: str,
    ) -> None:
        """补发文本（"流程已被 X 处理"）— 对不支持 update_card 的 Provider 用。

        Args:
            recipient: IM 用户 ID
            text: 纯文本内容（≤ 200 字符建议）
        """
        ...

    # ── Phase 4.5 入站接口预留（Phase 4 不实现 → 默认 NotImplementedError）─────

    async def subscribe(self, on_event: Any) -> None:
        """[Phase 4.5] 入站事件订阅。

        Phase 4 默认实现：raise NotImplementedError
        Phase 4.5 Bot Trigger plan：各 Provider 实现 webhook 接收 + dispatch
        """
        raise NotImplementedError(f"{self.name} subscribe 将于 Phase 4.5 实现")

    async def verify_webhook_signature(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> bool:
        """[Phase 4.5] webhook 签名校验。

        Phase 4 默认实现：raise NotImplementedError
        Phase 4.5：各 Provider 实现 HMAC / signature 验签
        """
        raise NotImplementedError(
            f"{self.name} verify_webhook_signature 将于 Phase 4.5 实现"
        )


# ── ProviderRegistry（模块级 dict + 工厂函数）─────────────────────────────────

_PROVIDERS: dict[str, IMProvider] = {}


def register_provider(provider: IMProvider) -> None:
    """注册 Provider（FastAPI lifespan startup 时调用）。

    Args:
        provider: 实现 IMProvider Protocol 的实例（鸭子类型，无需继承基类）

    Raises:
        ValueError: provider.name 不在 KNOWN_PROVIDERS 集合中（typo 防护）
    """
    if provider.name not in KNOWN_PROVIDERS:
        raise ValueError(
            f"unknown provider name '{provider.name}'；"
            f"必须是 KNOWN_PROVIDERS 之一: {sorted(KNOWN_PROVIDERS)}"
        )
    _PROVIDERS[provider.name] = provider


def get_provider(name: str) -> IMProvider:
    """获取 Provider。

    Args:
        name: Provider 名（PROVIDER_FEISHU / PROVIDER_WECOM / ...）

    Returns:
        已注册的 Provider 实例

    Raises:
        KeyError: name 未注册（携带已注册列表便于排查）
    """
    if name not in _PROVIDERS:
        raise KeyError(
            f"IM provider '{name}' 未注册（已注册的: {sorted(_PROVIDERS.keys())}）"
        )
    return _PROVIDERS[name]


def list_providers() -> list[str]:
    """列出已注册的 Provider 名（顺序稳定 sorted）。"""
    return sorted(_PROVIDERS.keys())


def clear_providers() -> None:
    """清空 Provider 注册表 — 测试 fixture 用（每 test setup/teardown 调）。"""
    _PROVIDERS.clear()
