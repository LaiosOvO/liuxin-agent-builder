"""企微 IMProvider 实现（Plan 04-07）— wechatpy 1.8.18 + Bot Webhook fallback。

设计 + spike 见 docs/reading-im-sdk-04-07-wecom-2026-05-17.md。

**双路径模型**：
- 主路径（app message）：wechatpy.enterprise.WeChatClient.message.send（user-targeted）
- Fallback（bot webhook）：httpx.AsyncClient POST 群机器人 webhook URL

两路径共用同一 markdown 内容（`build_wecom_markdown_content`），envelope 完全一致。

**自动 fallback 选择**：
- 若 corp_id/agent_id/secret 任一缺失但 bot_webhook_key 存在 → 自动 use_bot_fallback=True
- 若三者齐全且 use_bot_fallback=False（默认）→ 走主路径
- 用户可显式 use_bot_fallback=True 强制走 webhook（即使主路径凭据齐全）

**异常包装**：
- wechatpy `WeChatClientException` → `ConnectionError`（im_jobs tenacity 重试触发）
- 企微 API 返回 errcode≠0（业务错误）→ `ConnectionError`（同样重试 — 网络抖动可能导致 token 失效）
- httpx HTTPStatusError → `ConnectionError`

**update_card 显式拒绝**：
- 企微 markdown 消息没有 update API；调用方应基于 `supports_card_update=False` 改用
  `send_supplement_text` 兜底（04-10 fan-out 调用方实现）

**Phase 4.5 入站接口**：
- `subscribe` / `verify_webhook_signature` 抛 NotImplementedError（与 IMProvider Protocol 默认行为一致）

CLAUDE.md immutability：
- 凭据由 __init__ 接收后不可改（self.* 属性不公开 setter）
- 每次 send 创建新 dict envelope（不缓存）

CLAUDE.md security：
- 不在 log 中输出 secret / bot_webhook_key（敏感字段脱敏：仅 log corp_id 前缀）
- 调用 wechatpy 失败时不暴露完整 stack trace 到 ConnectionError message（截 200 字符）
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.agent_builder.notification.cards.base import HitlCardPayload
from app.agent_builder.notification.cards.wecom_card import (
    build_wecom_app_message,
    build_wecom_webhook_markdown,
)
from app.agent_builder.notification.providers.base import PROVIDER_WECOM

log = logging.getLogger(__name__)


# ── 常量 ─────────────────────────────────────────────────────────────────────

WECOM_BOT_WEBHOOK_BASE_URL = (
    "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
)
"""企微群机器人 webhook 固定 URL（key 通过 query string 传）。"""

WECOM_HTTP_TIMEOUT = 10.0
"""httpx Bot Webhook 请求超时（秒）— 与 im_jobs tenacity 重试间隔（1s/2s/4s）协调。"""

_ERROR_MSG_MAX_LEN = 200
"""ConnectionError message 截断长度（防 stack trace 泄露 secret / 过长日志）。"""


# ── WeComProvider ─────────────────────────────────────────────────────────────


class WeComProvider:
    """企微 IM Provider — 实现 IMProvider Protocol（鸭子类型）。

    用法（FastAPI lifespan startup 注册）：

        from app.agent_builder.core.im_credentials import IMCredentialsManager
        from app.agent_builder.notification.providers import wecom
        from app.agent_builder.notification.providers.base import register_provider

        mgr = IMCredentialsManager()
        if mgr.has_wecom():
            creds = mgr.wecom()
            register_provider(wecom.WeComProvider(
                corp_id=creds.corp_id,
                agent_id=creds.agent_id,
                secret=creds.secret,
                bot_webhook_key=creds.bot_webhook_key,
            ))
    """

    # 类属性：调用方可据此选择 update_card vs send_supplement_text（04-10 fan-out）
    supports_card_update: bool = False
    """企微 markdown 消息不支持 update — 静态卡片限制。"""

    def __init__(
        self,
        *,
        corp_id: str,
        agent_id: str,
        secret: str,
        bot_webhook_key: str = "",
        use_bot_fallback: bool = False,
    ) -> None:
        """初始化 WeComProvider。

        Args:
            corp_id: 企业 corp_id（应用消息必需）
            agent_id: 应用 agent_id（应用消息必需）
            secret: 应用 secret（应用消息必需）
            bot_webhook_key: 群机器人 webhook key（fallback 路径必需）
            use_bot_fallback: True 强制走 webhook（即使 app 凭据齐全）

        Raises:
            ValueError: use_bot_fallback=True 但 bot_webhook_key 为空
        """
        self.name = PROVIDER_WECOM
        self.corp_id = corp_id
        self.agent_id = agent_id
        self.secret = secret
        self.bot_webhook_key = bot_webhook_key

        # 自动 fallback 选择：app 凭据缺失但 bot_webhook_key 存在 → 启用 fallback
        app_creds_complete = bool(corp_id and agent_id and secret)
        if not app_creds_complete and bot_webhook_key:
            use_bot_fallback = True
            log.info(
                "WeComProvider 自动启用 fallback 模式（app 凭据缺失，仅 bot_webhook_key 可用）"
            )

        # 启动 fast-fail：fallback 模式必须有 bot_webhook_key
        if use_bot_fallback and not bot_webhook_key:
            raise ValueError(
                "WeComProvider use_bot_fallback=True 时必须提供 bot_webhook_key — "
                "请设置环境变量 WECOM_BOT_WEBHOOK_KEY"
            )

        # 启动 fast-fail：非 fallback 模式必须有完整 app 凭据
        if not use_bot_fallback and not app_creds_complete:
            raise ValueError(
                "WeComProvider 主路径（app message）需要完整凭据 corp_id + agent_id + secret；"
                "或设置 bot_webhook_key 走 fallback"
            )

        self.use_bot_fallback = use_bot_fallback
        self._client: Any = None  # 延迟初始化（避免 import 时 wechatpy 必须可用）

    # ── 主接口：send_hitl_card ────────────────────────────────────────────────

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
        """投递 HITL 决策卡片（按 use_bot_fallback 选择路径）。

        Returns:
            ``{"message_id": str, "raw_response": dict}``

        Raises:
            ConnectionError: 网络错误 / 企微 API errcode≠0（触发 tenacity 重试）
        """
        payload = HitlCardPayload(
            flow_title=flow_title,
            node_title=node_title,
            applicant_name=applicant_name,
            actor_name=actor_name,
            deadline_at=deadline_at,
            description=description,
            deeplinks=tuple(deeplinks),
        )

        if self.use_bot_fallback:
            return await self._send_via_bot_webhook(payload)
        return await self._send_via_app_message(payload=payload, recipient=recipient)

    # ── 主路径：app message via wechatpy ────────────────────────────────────

    async def _send_via_app_message(
        self,
        *,
        payload: HitlCardPayload,
        recipient: str,
    ) -> dict[str, Any]:
        """主路径：wechatpy app message。

        wechatpy 是同步 SDK；本方法在 async context 中直接同步调用
        （单条 IM 请求 ≤ 1s，不阻塞事件循环明显 — Phase 7 可改 thread executor）。
        """
        client = self._get_client()
        msg = build_wecom_app_message(payload)
        try:
            response = client.message.send(
                agent_id=int(self.agent_id) if self.agent_id.isdigit() else self.agent_id,
                user_ids=recipient,
                msg=msg,
            )
        except Exception as e:  # 包括 wechatpy.exceptions.WeChatClientException
            err_msg = self._safe_error_message(e)
            log.warning(
                "im.card.send.failed",
                extra={
                    "provider": self.name,
                    "path": "app_message",
                    "recipient": recipient,
                    "error": err_msg,
                },
            )
            raise ConnectionError(
                f"WeCom app message send failed: {err_msg}"
            ) from e

        # 业务错误（errcode≠0）也包装为 ConnectionError 让 tenacity 重试
        errcode = response.get("errcode", 0)
        if errcode != 0:
            errmsg = response.get("errmsg", "unknown")
            log.warning(
                "im.card.send.api_error",
                extra={
                    "provider": self.name,
                    "path": "app_message",
                    "recipient": recipient,
                    "errcode": errcode,
                    "errmsg": errmsg,
                },
            )
            raise ConnectionError(
                f"WeCom app message API error errcode={errcode} errmsg={errmsg}"
            )

        message_id = str(response.get("msgid", "")) or "wecom-app"
        return {"message_id": message_id, "raw_response": response}

    # ── Fallback：bot webhook via httpx ─────────────────────────────────────

    async def _send_via_bot_webhook(
        self, payload: HitlCardPayload
    ) -> dict[str, Any]:
        """Fallback：群机器人 webhook + markdown 消息。"""
        url = f"{WECOM_BOT_WEBHOOK_BASE_URL}?key={self.bot_webhook_key}"
        body = build_wecom_webhook_markdown(payload)
        try:
            async with httpx.AsyncClient(timeout=WECOM_HTTP_TIMEOUT) as cli:
                resp = await cli.post(url, json=body)
        except (httpx.RequestError, httpx.TimeoutException) as e:
            err_msg = self._safe_error_message(e)
            log.warning(
                "im.card.send.failed",
                extra={
                    "provider": self.name,
                    "path": "bot_webhook",
                    "error": err_msg,
                },
            )
            raise ConnectionError(
                f"WeCom bot webhook network error: {err_msg}"
            ) from e

        # HTTP 状态码非 2xx → ConnectionError
        if resp.status_code != 200:
            text_preview = resp.text[:_ERROR_MSG_MAX_LEN]
            log.warning(
                "im.card.send.http_error",
                extra={
                    "provider": self.name,
                    "path": "bot_webhook",
                    "status_code": resp.status_code,
                    "text": text_preview,
                },
            )
            raise ConnectionError(
                f"WeCom bot webhook HTTP {resp.status_code}: {text_preview}"
            )

        try:
            data = resp.json()
        except Exception as e:
            raise ConnectionError(
                f"WeCom bot webhook returned non-JSON: {resp.text[:_ERROR_MSG_MAX_LEN]}"
            ) from e

        errcode = data.get("errcode", 0)
        if errcode != 0:
            errmsg = data.get("errmsg", "unknown")
            log.warning(
                "im.card.send.api_error",
                extra={
                    "provider": self.name,
                    "path": "bot_webhook",
                    "errcode": errcode,
                    "errmsg": errmsg,
                },
            )
            raise ConnectionError(
                f"WeCom bot webhook API error errcode={errcode} errmsg={errmsg}"
            )

        # Bot Webhook 不返回 msgid → 用固定标识 + 时间戳
        return {"message_id": "wecom-bot-webhook", "raw_response": data}

    # ── update_card：企微不支持 ────────────────────────────────────────────

    async def update_card(
        self,
        *,
        message_id: str,
        new_content: dict[str, Any],
    ) -> None:
        """企微 markdown 消息不支持更新 — 显式抛 NotImplementedError。

        调用方应基于 `supports_card_update=False` 改用 `send_supplement_text` 兜底
        （04-10 fan-out 调用方实现 supplement 路径）。
        """
        raise NotImplementedError(
            f"{self.name} 不支持 update_card（企微 markdown 消息为静态卡片）— "
            "调用方应改用 send_supplement_text 兜底（supports_card_update=False）"
        )

    # ── send_supplement_text ────────────────────────────────────────────────

    async def send_supplement_text(
        self,
        *,
        recipient: str,
        text: str,
    ) -> None:
        """补发文本消息（"已被 X 处理"等）。

        Args:
            recipient: 用户 ID（app message 模式必需；fallback 模式忽略）
            text: 纯文本内容（≤ 2048 字节）
        """
        if self.use_bot_fallback:
            await self._send_supplement_via_webhook(text)
        else:
            await self._send_supplement_via_app_message(
                recipient=recipient, text=text
            )

    async def _send_supplement_via_app_message(
        self, *, recipient: str, text: str
    ) -> None:
        """补发文本 — app message text msgtype。"""
        client = self._get_client()
        msg = {
            "msgtype": "text",
            "text": {"content": text},
        }
        try:
            response = client.message.send(
                agent_id=int(self.agent_id) if self.agent_id.isdigit() else self.agent_id,
                user_ids=recipient,
                msg=msg,
            )
        except Exception as e:
            raise ConnectionError(
                f"WeCom supplement text send failed: {self._safe_error_message(e)}"
            ) from e

        errcode = response.get("errcode", 0)
        if errcode != 0:
            raise ConnectionError(
                f"WeCom supplement text API error errcode={errcode} "
                f"errmsg={response.get('errmsg', '')}"
            )

    async def _send_supplement_via_webhook(self, text: str) -> None:
        """补发文本 — bot webhook text msgtype。"""
        url = f"{WECOM_BOT_WEBHOOK_BASE_URL}?key={self.bot_webhook_key}"
        body = {"msgtype": "text", "text": {"content": text}}
        try:
            async with httpx.AsyncClient(timeout=WECOM_HTTP_TIMEOUT) as cli:
                resp = await cli.post(url, json=body)
        except (httpx.RequestError, httpx.TimeoutException) as e:
            raise ConnectionError(
                f"WeCom bot webhook supplement network error: "
                f"{self._safe_error_message(e)}"
            ) from e
        if resp.status_code != 200:
            raise ConnectionError(
                f"WeCom bot webhook supplement HTTP {resp.status_code}"
            )
        data = resp.json() if resp.content else {}
        if data.get("errcode", 0) != 0:
            raise ConnectionError(
                f"WeCom bot webhook supplement errcode={data.get('errcode')} "
                f"errmsg={data.get('errmsg', '')}"
            )

    # ── Phase 4.5 预留接口 ──────────────────────────────────────────────────

    async def subscribe(self, on_event: Any) -> None:
        """[Phase 4.5] 入站事件订阅（Phase 4 不实现）。"""
        raise NotImplementedError(
            f"{self.name} subscribe 将于 Phase 4.5 实现"
        )

    async def verify_webhook_signature(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> bool:
        """[Phase 4.5] 入站 webhook 签名校验（Phase 4 不实现）。"""
        raise NotImplementedError(
            f"{self.name} verify_webhook_signature 将于 Phase 4.5 实现"
        )

    # ── 私有 helpers ────────────────────────────────────────────────────────

    def _get_client(self) -> Any:
        """延迟初始化 wechatpy WeChatClient（避免 import 时强依赖）。

        测试可 monkeypatch 此方法返回 fake_client。
        """
        if self._client is None:
            # 延迟 import 避免上层 import wecom.py 时 wechatpy 不可用
            from wechatpy.enterprise import WeChatClient

            self._client = WeChatClient(
                corp_id=self.corp_id,
                secret=self.secret,
            )
        return self._client

    @staticmethod
    def _safe_error_message(e: Exception) -> str:
        """异常 → 安全 message（截断长度防 secret 泄露 / 日志爆量）。"""
        msg = str(e)
        if len(msg) > _ERROR_MSG_MAX_LEN:
            msg = msg[:_ERROR_MSG_MAX_LEN] + "...(已截断)"
        return msg
