"""MattermostProvider — 通过 httpx 直调 Mattermost API v4（Plan 04-09 NOTI-06）。

参考 docs/reading-im-sdk-04-09-slack-mm-webhook-2026-05-17.md。

设计要点：
- 用 httpx.AsyncClient 直接 POST/PUT Mattermost API（不引入 mattermost-driver 重依赖）
- Authorization: Bearer <bot_token>
- POST /api/v4/posts 发卡片（含 message + props.attachments）
- PUT /api/v4/posts/<id>/patch 更新卡片
- 错误分级：HTTP ≥ 500 → ConnectionError（重试）；4xx → RuntimeError（不重试）
- supports_card_update=True

CLAUDE.md immutability：每次调用创建新 httpx.AsyncClient（with timeout）。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.agent_builder.notification.cards.base import HitlCardPayload
from app.agent_builder.notification.cards.mattermost_card import MattermostCardBuilder
from app.agent_builder.notification.providers.base import PROVIDER_MATTERMOST

log = logging.getLogger(__name__)


_DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class MattermostProvider:
    """Mattermost 出站投递 Provider — 满足 IMProvider Protocol 鸭子类型。"""

    name: str = PROVIDER_MATTERMOST
    supports_card_update: bool = True  # Mattermost 支持 post patch

    def __init__(self, *, base_url: str, bot_token: str) -> None:
        """
        Args:
            base_url: Mattermost 实例 URL（如 'https://mm.example.com'，无尾部 /）
            bot_token: Bot Access Token
        """
        if not base_url:
            raise ValueError("MattermostProvider: base_url 不能为空")
        if not bot_token:
            raise ValueError("MattermostProvider: bot_token 不能为空")
        self._base_url = base_url.rstrip("/")
        self._bot_token = bot_token
        self._card_builder = MattermostCardBuilder()

    # ── 内部辅助 ─────────────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        """构造 Mattermost API 请求 headers。"""
        return {
            "Authorization": f"Bearer {self._bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    @staticmethod
    def _ensure_http_ok(
        response: httpx.Response, *, endpoint: str
    ) -> dict[str, Any]:
        """校验响应：HTTP ≥ 500 / 429 → ConnectionError；其他 4xx → RuntimeError。

        Returns:
            解析后的 dict 响应体
        """
        if response.status_code >= 500 or response.status_code == 429:
            raise ConnectionError(
                f"Mattermost {endpoint} HTTP {response.status_code} {response.text[:200]}"
            )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Mattermost {endpoint} HTTP {response.status_code} {response.text[:200]}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"Mattermost {endpoint} 响应非 JSON: {response.text[:200]}"
            ) from exc

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
        """投递 HITL 决策卡片（POST /api/v4/posts）。

        Args:
            recipient: Mattermost channel ID（含 DM channel）

        Returns:
            {"message_id": post_id, "raw_response": dict}
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
        card = self._card_builder.build_hitl_card(payload)

        body = {
            "channel_id": recipient,
            "message": card["message"],
            "props": card["props"],
        }

        endpoint = "/api/v4/posts"
        log.info(
            "im.card.send.attempt",
            extra={"provider": self.name, "recipient": recipient, "endpoint": endpoint},
        )

        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            try:
                response = await client.post(
                    f"{self._base_url}{endpoint}",
                    headers=self._headers(),
                    json=body,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                raise ConnectionError(f"Mattermost {endpoint} 网络错误: {exc}") from exc

        result = self._ensure_http_ok(response, endpoint=endpoint)
        post_id = result.get("id", "")
        if not post_id:
            raise RuntimeError(f"Mattermost {endpoint} 响应缺少 id 字段: {result}")

        return {
            "message_id": post_id,
            "raw_response": result,
        }

    async def update_card(
        self,
        *,
        message_id: str,
        new_content: dict[str, Any],
    ) -> None:
        """更新已发送卡片（PUT /api/v4/posts/<id>/patch）。

        Args:
            message_id: send_hitl_card 返回的 post_id
            new_content: 含 'message' 与/或 'props' 字段
        """
        if not message_id:
            raise ValueError("MattermostProvider.update_card: message_id 不能为空")

        body: dict[str, Any] = {}
        if "message" in new_content:
            body["message"] = new_content["message"]
        if "props" in new_content:
            body["props"] = new_content["props"]
        if not body:
            raise ValueError(
                "MattermostProvider.update_card: new_content 必须含 'message' 或 'props'"
            )

        endpoint = f"/api/v4/posts/{message_id}/patch"
        log.info(
            "im.card.send.attempt",
            extra={"provider": self.name, "endpoint": endpoint, "message_id": message_id},
        )

        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            try:
                response = await client.put(
                    f"{self._base_url}{endpoint}",
                    headers=self._headers(),
                    json=body,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                raise ConnectionError(f"Mattermost {endpoint} 网络错误: {exc}") from exc

        self._ensure_http_ok(response, endpoint=endpoint)

    async def send_supplement_text(
        self,
        *,
        recipient: str,
        text: str,
    ) -> None:
        """补发文本（POST /api/v4/posts，无 props.attachments）。"""
        body = {"channel_id": recipient, "message": text}
        endpoint = "/api/v4/posts"

        log.info(
            "im.card.send.attempt",
            extra={"provider": self.name, "recipient": recipient, "endpoint": endpoint, "kind": "supplement"},
        )

        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            try:
                response = await client.post(
                    f"{self._base_url}{endpoint}",
                    headers=self._headers(),
                    json=body,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                raise ConnectionError(f"Mattermost {endpoint} 网络错误: {exc}") from exc

        self._ensure_http_ok(response, endpoint=endpoint)

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
