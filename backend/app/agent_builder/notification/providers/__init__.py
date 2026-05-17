"""IM Provider 抽象层（Plan 04-05 起，Plan 04-09 扩展 webhook）— 6 家 IM 出站投递 Protocol + Registry。

子模块：
- base.py — IMProvider Protocol + ProviderRegistry + 6 家 provider name 常量
- mock.py — MockIMProvider（测试 + E2E 用，记录所有调用 payload）

具体 Provider 实现（04-06..09）：
- feishu.py（lark-oapi 1.6.5）
- wecom.py（wechatpy 1.8.18）
- dingtalk.py（dingtalk-stream 0.24.3）
- slack.py（httpx 直调 Slack Web API，Block Kit）— Plan 04-09
- mattermost.py（httpx 直调 /api/v4/posts）— Plan 04-09
- webhook.py（httpx 直调用户配置 URL + HMAC-SHA256 签名）— Plan 04-09 NOTI-07

详见 docs/reading-im-sdk-04-05-providers-2026-05-17.md
   + docs/reading-im-sdk-04-09-slack-mm-webhook-2026-05-17.md
"""
from app.agent_builder.notification.providers.base import (
    KNOWN_PROVIDERS,
    PROVIDER_DINGTALK,
    PROVIDER_FEISHU,
    PROVIDER_MATTERMOST,
    PROVIDER_SLACK,
    PROVIDER_WEBHOOK,
    PROVIDER_WECOM,
    IMProvider,
    clear_providers,
    get_provider,
    list_providers,
    register_provider,
)

__all__ = [
    "IMProvider",
    "PROVIDER_FEISHU",
    "PROVIDER_WECOM",
    "PROVIDER_DINGTALK",
    "PROVIDER_SLACK",
    "PROVIDER_MATTERMOST",
    "PROVIDER_WEBHOOK",
    "KNOWN_PROVIDERS",
    "register_provider",
    "get_provider",
    "list_providers",
    "clear_providers",
]
