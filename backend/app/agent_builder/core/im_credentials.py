"""IM 凭据管理（Plan 04-05）— 从 .env 加载 5 家 IM Provider 凭据。

设计参考 docs/reading-im-sdk-04-05-providers-2026-05-17.md：
- Phase 4 简化：单租户全局凭据（多 workspace 共享）
- Phase 6 扩展：workspace 级凭据表 + 加密存储

凭据字段映射（详见 reading doc）：
- feishu     : FEISHU_APP_ID, FEISHU_APP_SECRET
- wecom      : WECOM_CORP_ID, WECOM_AGENT_ID, WECOM_SECRET
- dingtalk   : DINGTALK_APP_KEY, DINGTALK_APP_SECRET
- slack      : SLACK_BOT_TOKEN
- mattermost : MATTERMOST_URL, MATTERMOST_BOT_TOKEN

CLAUDE.md immutability：
- 每家凭据用 @dataclass(frozen=True)（不可修改）
- _load_from_env 一次性加载到 manager 私有字段，外部通过 getter 访问

CLAUDE.md security：
- 缺失字段 warn 不抛错（按需配置 — 用户可能只用 2-3 家）
- getter 调用时缺失抛 RuntimeError + 提示需要的环境变量名
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

log = logging.getLogger(__name__)


# ── 5 家凭据 frozen dataclass ─────────────────────────────────────────────────


@dataclass(frozen=True)
class FeishuCredentials:
    """飞书凭据（lark-oapi 1.6.5）。"""

    app_id: str
    app_secret: str


@dataclass(frozen=True)
class WeComCredentials:
    """企微凭据（wechatpy 1.8.18）。

    Plan 04-07 扩展：
    - `bot_webhook_key`（可选）：群机器人 webhook key，用于 Bot Webhook fallback
      路径（wechatpy templated card API 不可用时启用 — 详见
      docs/reading-im-sdk-04-07-wecom-2026-05-17.md）

    应用消息路径（corp_id + agent_id + secret）与 Bot Webhook 路径
    （bot_webhook_key）相互独立，可单独配置或同时配置；运行时按 `use_bot_fallback`
    切换。当应用消息凭据未配置但 bot_webhook_key 已配置时，WeComProvider 自动启用
    fallback。
    """

    corp_id: str
    agent_id: str
    secret: str
    bot_webhook_key: str = ""
    """企微群机器人 webhook key（可选，Plan 04-07）— 空字符串表示未配置。"""


@dataclass(frozen=True)
class DingTalkCredentials:
    """钉钉凭据（dingtalk-stream 0.24.3）。"""

    app_key: str
    app_secret: str


@dataclass(frozen=True)
class SlackCredentials:
    """Slack 凭据（slack-bolt 1.28.0）。"""

    bot_token: str


@dataclass(frozen=True)
class MattermostCredentials:
    """Mattermost 凭据（httpx 直调，无 SDK）。"""

    base_url: str
    bot_token: str


@dataclass(frozen=True)
class WebhookCredentials:
    """通用 Webhook 凭据（Plan 04-09 NOTI-07）。

    HMAC_SECRET 复用项目全局密钥（已在 startup_checks 校验 ≥ 32 字节），
    本 dataclass 仅承载用户配置的 delivery URL。

    Phase 4 简化：全局单 URL；Phase 6 扩展 workspace 级多 URL。
    """

    delivery_url: str


# ── Manager ───────────────────────────────────────────────────────────────────


class IMCredentialsManager:
    """5 家 IM 凭据加载 + getter（Plan 04-05）。

    用法：
        mgr = IMCredentialsManager()  # 启动时实例化一次，按需 getter
        creds = mgr.feishu()          # 拿到 FeishuCredentials；未配置抛 RuntimeError
        if mgr.has_feishu():          # 检查是否配置（不抛错）
            mgr.feishu().app_id

    Phase 6 扩展点：
    - 增加 by_workspace(workspace_id) 接受 DB session 查 workspace_im_credentials 表
    - 加密存储（HMAC_SECRET 派生 AES-GCM）
    """

    def __init__(self) -> None:
        self._feishu: FeishuCredentials | None = None
        self._wecom: WeComCredentials | None = None
        self._dingtalk: DingTalkCredentials | None = None
        self._slack: SlackCredentials | None = None
        self._mattermost: MattermostCredentials | None = None
        self._webhook: WebhookCredentials | None = None  # Plan 04-09 NOTI-07
        self._load_from_env()

    def _load_from_env(self) -> None:
        """启动时加载 5 家凭据；缺失字段 warn 不抛错。

        加载策略：每家所有必需字段都存在才创建 dataclass，否则保持 None。
        """
        # 飞书
        fapp_id = os.environ.get("FEISHU_APP_ID", "").strip()
        fsecret = os.environ.get("FEISHU_APP_SECRET", "").strip()
        if fapp_id and fsecret:
            self._feishu = FeishuCredentials(app_id=fapp_id, app_secret=fsecret)
        else:
            log.warning(
                "未配置飞书凭据（FEISHU_APP_ID / FEISHU_APP_SECRET）— "
                "FeishuProvider 不可用"
            )

        # 企微（Plan 04-07：app message 三元组 + 可选 bot_webhook_key fallback）
        wcorp_id = os.environ.get("WECOM_CORP_ID", "").strip()
        wagent_id = os.environ.get("WECOM_AGENT_ID", "").strip()
        wsecret = os.environ.get("WECOM_SECRET", "").strip()
        wbot_key = os.environ.get("WECOM_BOT_WEBHOOK_KEY", "").strip()
        if wcorp_id and wagent_id and wsecret:
            # 主路径凭据齐全 → 创建 WeComCredentials（可附带 bot_webhook_key）
            self._wecom = WeComCredentials(
                corp_id=wcorp_id,
                agent_id=wagent_id,
                secret=wsecret,
                bot_webhook_key=wbot_key,
            )
        elif wbot_key:
            # Plan 04-07 fallback：仅 bot_webhook_key 配置（无 app message 凭据）
            # 用占位 corp_id / agent_id / secret = "" 标识 fallback-only 模式
            # WeComProvider 在 use_bot_fallback=True 时仅用 bot_webhook_key
            self._wecom = WeComCredentials(
                corp_id="",
                agent_id="",
                secret="",
                bot_webhook_key=wbot_key,
            )
            log.warning(
                "企微仅配置 Bot Webhook（缺 WECOM_CORP_ID / WECOM_AGENT_ID / WECOM_SECRET）— "
                "WeComProvider 启用 fallback 模式，仅可向群投递"
            )
        else:
            log.warning(
                "未配置企微凭据（WECOM_CORP_ID / WECOM_AGENT_ID / WECOM_SECRET 或 "
                "WECOM_BOT_WEBHOOK_KEY）— WeComProvider 不可用"
            )

        # 钉钉
        dapp_key = os.environ.get("DINGTALK_APP_KEY", "").strip()
        dapp_secret = os.environ.get("DINGTALK_APP_SECRET", "").strip()
        if dapp_key and dapp_secret:
            self._dingtalk = DingTalkCredentials(
                app_key=dapp_key, app_secret=dapp_secret
            )
        else:
            log.warning(
                "未配置钉钉凭据（DINGTALK_APP_KEY / DINGTALK_APP_SECRET）— "
                "DingTalkProvider 不可用"
            )

        # Slack
        stoken = os.environ.get("SLACK_BOT_TOKEN", "").strip()
        if stoken:
            self._slack = SlackCredentials(bot_token=stoken)
        else:
            log.warning(
                "未配置 Slack 凭据（SLACK_BOT_TOKEN）— SlackProvider 不可用"
            )

        # Mattermost
        mm_url = os.environ.get("MATTERMOST_URL", "").strip()
        mm_token = os.environ.get("MATTERMOST_BOT_TOKEN", "").strip()
        if mm_url and mm_token:
            self._mattermost = MattermostCredentials(
                base_url=mm_url, bot_token=mm_token
            )
        else:
            log.warning(
                "未配置 Mattermost 凭据（MATTERMOST_URL / MATTERMOST_BOT_TOKEN）— "
                "MattermostProvider 不可用"
            )

        # 通用 Webhook（Plan 04-09 NOTI-07）
        wh_url = os.environ.get("WEBHOOK_DELIVERY_URL", "").strip()
        if wh_url:
            self._webhook = WebhookCredentials(delivery_url=wh_url)
        else:
            log.warning(
                "未配置通用 Webhook 凭据（WEBHOOK_DELIVERY_URL）— "
                "WebhookProvider 不可用"
            )

    # ── Getters ──────────────────────────────────────────────────────────────

    def feishu(self) -> FeishuCredentials:
        """获取飞书凭据；未配置抛 RuntimeError。"""
        if self._feishu is None:
            raise RuntimeError(
                "Feishu 凭据未配置 — 请设置环境变量 FEISHU_APP_ID / FEISHU_APP_SECRET"
            )
        return self._feishu

    def wecom(self) -> WeComCredentials:
        """获取企微凭据；未配置抛 RuntimeError。"""
        if self._wecom is None:
            raise RuntimeError(
                "WeCom 凭据未配置 — 请设置环境变量 "
                "WECOM_CORP_ID / WECOM_AGENT_ID / WECOM_SECRET"
            )
        return self._wecom

    def dingtalk(self) -> DingTalkCredentials:
        """获取钉钉凭据；未配置抛 RuntimeError。"""
        if self._dingtalk is None:
            raise RuntimeError(
                "DingTalk 凭据未配置 — 请设置环境变量 "
                "DINGTALK_APP_KEY / DINGTALK_APP_SECRET"
            )
        return self._dingtalk

    def slack(self) -> SlackCredentials:
        """获取 Slack 凭据；未配置抛 RuntimeError。"""
        if self._slack is None:
            raise RuntimeError(
                "Slack 凭据未配置 — 请设置环境变量 SLACK_BOT_TOKEN"
            )
        return self._slack

    def mattermost(self) -> MattermostCredentials:
        """获取 Mattermost 凭据；未配置抛 RuntimeError。"""
        if self._mattermost is None:
            raise RuntimeError(
                "Mattermost 凭据未配置 — 请设置环境变量 "
                "MATTERMOST_URL / MATTERMOST_BOT_TOKEN"
            )
        return self._mattermost

    def webhook(self) -> WebhookCredentials:
        """获取通用 Webhook 凭据；未配置抛 RuntimeError。Plan 04-09 NOTI-07。"""
        if self._webhook is None:
            raise RuntimeError(
                "Webhook 凭据未配置 — 请设置环境变量 WEBHOOK_DELIVERY_URL"
            )
        return self._webhook

    # ── 检查（不抛错）──────────────────────────────────────────────────────

    def has_feishu(self) -> bool:
        """检查飞书凭据是否已配置。"""
        return self._feishu is not None

    def has_wecom(self) -> bool:
        """检查企微凭据是否已配置。"""
        return self._wecom is not None

    def has_dingtalk(self) -> bool:
        """检查钉钉凭据是否已配置。"""
        return self._dingtalk is not None

    def has_slack(self) -> bool:
        """检查 Slack 凭据是否已配置。"""
        return self._slack is not None

    def has_mattermost(self) -> bool:
        """检查 Mattermost 凭据是否已配置。"""
        return self._mattermost is not None

    def has_webhook(self) -> bool:
        """检查通用 Webhook 凭据是否已配置。Plan 04-09 NOTI-07。"""
        return self._webhook is not None

    def list_configured(self) -> list[str]:
        """列出已配置的 Provider 名（sorted）— 启动 banner / 健康检查用。"""
        configured: list[str] = []
        if self.has_feishu():
            configured.append("feishu")
        if self.has_wecom():
            configured.append("wecom")
        if self.has_dingtalk():
            configured.append("dingtalk")
        if self.has_slack():
            configured.append("slack")
        if self.has_mattermost():
            configured.append("mattermost")
        if self.has_webhook():
            configured.append("webhook")
        return sorted(configured)
