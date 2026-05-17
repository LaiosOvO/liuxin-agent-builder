"""SlackProvider — 通过 httpx 直调 Slack Web API（Plan 04-09 NOTI-05）。

参考 docs/reading-im-sdk-04-09-slack-mm-webhook-2026-05-17.md。

设计要点：
- 用 httpx.AsyncClient 直接 POST Slack Web API（不用 slack-bolt 重依赖）
- Authorization: Bearer xoxb-...
- chat.postMessage 发送卡片（含 blocks + text fallback）
- chat.update 更新已发送卡片（**Slack 支持 update**）
- chat.postMessage 不带 blocks 发补充文本
- 错误分级：HTTP ≥ 500 / `{"ok": false, "error": "..."}` 网络错误 → ConnectionError（tenacity 重试）
- HTTP 4xx（非 429） / 业务错误（auth 等）→ RuntimeError（不重试）
- supports_card_update=True

CLAUDE.md immutability：每次调用创建新 httpx.AsyncClient（with timeout），不共享状态。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.agent_builder.notification.cards.base import HitlCardPayload
from app.agent_builder.notification.cards.slack_card import SlackCardBuilder
from app.agent_builder.notification.providers.base import PROVIDER_SLACK

log = logging.getLogger(__name__)


# ── 常量 ─────────────────────────────────────────────────────────────────────


_SLACK_API_BASE = "https://slack.com/api"
_DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


# ── Provider ─────────────────────────────────────────────────────────────────


class SlackProvider:
    """Slack 出站投递 Provider — 满足 IMProvider Protocol 鸭子类型。"""

    name: str = PROVIDER_SLACK
    supports_card_update: bool = True  # Slack 支持 chat.update

    def __init__(self, *, bot_token: str) -> None:
        """
        Args:
            bot_token: Slack Bot User OAuth Token（xoxb-...）
        """
        if not bot_token:
            raise ValueError("SlackProvider: bot_token 不能为空")
        self._bot_token = bot_token
        self._card_builder = SlackCardBuilder()

    # ── 内部辅助 ─────────────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        """构造 Slack API 请求 headers。"""
        return {
            "Authorization": f"Bearer {self._bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    @staticmethod
    def _ensure_slack_ok(response: httpx.Response, *, api: str) -> dict[str, Any]:
        """校验 Slack API 响应：HTTP ≥ 500 → ConnectionError；ok=false → RuntimeError。

        Returns:
            解析后的 dict 响应体
        """
        # HTTP 层错误分级
        if response.status_code >= 500 or response.status_code == 429:
            # 5xx 服务端 / 429 限流 → 网络层 retry 触发
            raise ConnectionError(
                f"Slack {api} HTTP {response.status_code} {response.text[:200]}"
            )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Slack {api} HTTP {response.status_code} {response.text[:200]}"
            )

        # 业务层错误（ok=false）
        try:
            body: dict[str, Any] = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Slack {api} 响应非 JSON: {response.text[:200]}") from exc

        if not body.get("ok", False):
            err = body.get("error", "unknown")
            # 部分网络相关错误码（虽然 200）划入 ConnectionError 触发重试
            if err in {"timeout", "service_unavailable", "ratelimited", "fatal_error"}:
                raise ConnectionError(f"Slack {api} 业务错误（可重试）: {err}")
            raise RuntimeError(f"Slack {api} 业务错误: {err}")

        return body

    # ── IMProvider 方法 ──────────────────────────────────────────────────────

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
        """投递 HITL 决策卡片（chat.postMessage + Block Kit）。

        Args:
            recipient: Slack channel ID (C...) 或 DM ID (D...)

        Returns:
            {"message_id": "ts:channel", "raw_response": dict}
            message_id 同时含 ts 与 channel — chat.update 需要两者
        """
        payload = HitlCardPayload(
            flow_title=flow_title,
            node_title=node_title,
            applicant_name=applicant_name,
            actor_name=actor_name,
            deadline_at=deadline_at,
            description=description,
            deeplinks=tuple(deeplinks),  # immutable 转换
        )
        card = self._card_builder.build_hitl_card(payload)

        body = {
            "channel": recipient,
            "blocks": card["blocks"],
            "text": card["text"],  # fallback
        }

        log.info(
            "im.card.send.attempt",
            extra={"provider": self.name, "recipient": recipient, "api": "chat.postMessage"},
        )

        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            try:
                response = await client.post(
                    f"{_SLACK_API_BASE}/chat.postMessage",
                    headers=self._headers(),
                    json=body,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                raise ConnectionError(f"Slack chat.postMessage 网络错误: {exc}") from exc

        result = self._ensure_slack_ok(response, api="chat.postMessage")
        ts = result.get("ts", "")
        channel = result.get("channel", recipient)

        # message_id 编码 ts + channel — chat.update 需要两者
        message_id = f"{channel}:{ts}"

        return {
            "message_id": message_id,
            "raw_response": result,
        }

    async def update_card(
        self,
        *,
        message_id: str,
        new_content: dict[str, Any],
    ) -> None:
        """更新已发送卡片（chat.update）。

        Args:
            message_id: send_hitl_card 返回的 "channel:ts" 复合 ID
            new_content: 含 'blocks' 与/或 'text' 字段
        """
        if ":" not in message_id:
            raise ValueError(
                f"SlackProvider.update_card: message_id 必须为 'channel:ts' 格式，得到 {message_id!r}"
            )
        channel, ts = message_id.split(":", 1)

        body: dict[str, Any] = {"channel": channel, "ts": ts}
        if "blocks" in new_content:
            body["blocks"] = new_content["blocks"]
        if "text" in new_content:
            body["text"] = new_content["text"]

        log.info(
            "im.card.send.attempt",
            extra={"provider": self.name, "api": "chat.update", "message_id": message_id},
        )

        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            try:
                response = await client.post(
                    f"{_SLACK_API_BASE}/chat.update",
                    headers=self._headers(),
                    json=body,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                raise ConnectionError(f"Slack chat.update 网络错误: {exc}") from exc

        self._ensure_slack_ok(response, api="chat.update")

    async def send_supplement_text(
        self,
        *,
        recipient: str,
        text: str,
    ) -> None:
        """补发文本（chat.postMessage 仅 text，不带 blocks）。"""
        body = {"channel": recipient, "text": text}

        log.info(
            "im.card.send.attempt",
            extra={"provider": self.name, "recipient": recipient, "api": "chat.postMessage", "kind": "supplement"},
        )

        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            try:
                response = await client.post(
                    f"{_SLACK_API_BASE}/chat.postMessage",
                    headers=self._headers(),
                    json=body,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                raise ConnectionError(f"Slack chat.postMessage 网络错误: {exc}") from exc

        self._ensure_slack_ok(response, api="chat.postMessage")

    # ── Phase 4.5 入站接口预留 ───────────────────────────────────────────────

    async def subscribe(self, on_event: Any) -> None:
        """[Phase 4.5] 入站订阅 — Phase 4 抛 NotImplementedError。"""
        raise NotImplementedError(f"{self.name} subscribe 将于 Phase 4.5 实现")

    async def verify_webhook_signature(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> bool:
        """[Phase 4.5] 入站签名校验 — Phase 4 抛 NotImplementedError。"""
        raise NotImplementedError(
            f"{self.name} verify_webhook_signature 将于 Phase 4.5 实现"
        )
