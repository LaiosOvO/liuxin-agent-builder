"""IM Provider 抽象层（Plan 04-05）— 5 家 IM 出站投递 Protocol + Registry。

子模块：
- base.py — IMProvider Protocol + ProviderRegistry + 5 家 provider name 常量
- mock.py — MockIMProvider（测试 + E2E 用，记录所有调用 payload）

具体 Provider 实现（04-06..09）：
- feishu.py（lark-oapi 1.6.5）
- wecom.py（wechatpy 1.8.18）
- dingtalk.py（dingtalk-stream 0.24.3）
- slack.py（slack-bolt 1.28.0）
- mattermost.py（httpx 直调，无专用 SDK）

详见 docs/reading-im-sdk-04-05-providers-2026-05-17.md
"""
from app.agent_builder.notification.providers.base import (
    KNOWN_PROVIDERS,
    PROVIDER_DINGTALK,
    PROVIDER_FEISHU,
    PROVIDER_MATTERMOST,
    PROVIDER_SLACK,
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
    "KNOWN_PROVIDERS",
    "register_provider",
    "get_provider",
    "list_providers",
    "clear_providers",
]
