"""WebhookProvider — 通用 HTTP webhook 投递（Plan 04-09 NOTI-07）。

参考 docs/reading-im-sdk-04-09-slack-mm-webhook-2026-05-17.md。

设计要点：
- 用 httpx.AsyncClient 直接 POST JSON payload 到用户配置的 delivery URL
- HMAC-SHA256 签名 → X-Agent-Builder-Signature header（防伪造）
- HMAC_SECRET 复用项目全局密钥（已在 startup_checks 校验 ≥ 32 字节）
- payload 序列化用 sort_keys=True + 紧凑 separators，保证用户端可复现验签
- 错误分级：HTTP ≥ 500 / 429 / 网络错误 → ConnectionError（tenacity 重试）
- HTTP 4xx → RuntimeError（不重试）
- update_card 抛 NotImplementedError（用户自定义 webhook 一般不支持 update）
- send_supplement_text → POST 新 payload（event=hitl_supplement）
- supports_card_update=False

CLAUDE.md immutability：每次调用创建新 httpx.AsyncClient + 新 payload dict。
CLAUDE.md security：HMAC 用 hmac.compare_digest 验签语义（本 provider 仅签名，验签由用户端做）。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Any

import httpx

from app.agent_builder.notification.cards.base import HitlCardPayload
from app.agent_builder.notification.cards.webhook_payload import (
    WEBHOOK_EVENT_HITL_REQUIRED,
    WEBHOOK_EVENT_HITL_SUPPLEMENT,
    WebhookCardBuilder,
    build_webhook_payload,
    build_webhook_supplement_payload,
)
from app.agent_builder.notification.providers.base import PROVIDER_WEBHOOK

log = logging.getLogger(__name__)


# ── 常量 ─────────────────────────────────────────────────────────────────────


_DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
SIGNATURE_HEADER = "X-Agent-Builder-Signature"
EVENT_HEADER = "X-Agent-Builder-Event"


# ── 签名工具（独立函数 — 便于测试与用户端复现）────────────────────────────


def serialize_payload(payload: dict[str, Any]) -> bytes:
    """稳定 JSON 序列化：sort_keys + 紧凑分隔符 + UTF-8 编码。

    用户端必须用相同方式序列化才能复现签名。
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_signature(*, payload_bytes: bytes, secret: str) -> str:
    """计算 HMAC-SHA256 hex digest（64 字符）。"""
    if not secret:
        raise RuntimeError("HMAC_SECRET 未配置 — 无法签名 Webhook 请求")
    return hmac.new(
        key=secret.encode("utf-8"),
        msg=payload_bytes,
        digestmod=hashlib.sha256,
    ).hexdigest()


def verify_signature(
    *, payload_bytes: bytes, signature: str, secret: str
) -> bool:
    """验签辅助（用户端可复用 — 本 provider 出站不调用，仅供测试 round-trip）。"""
    expected = compute_signature(payload_bytes=payload_bytes, secret=secret)
    return hmac.compare_digest(expected, signature)


# ── Provider ─────────────────────────────────────────────────────────────────


class WebhookProvider:
    """通用 Webhook 出站投递 Provider — 满足 IMProvider Protocol 鸭子类型。"""

    name: str = PROVIDER_WEBHOOK
    supports_card_update: bool = False  # 通用 webhook 不支持 update

    def __init__(self, *, delivery_url: str, hmac_secret: str | None = None) -> None:
        """
        Args:
            delivery_url: 用户配置的 HTTPS endpoint
            hmac_secret: HMAC 密钥；None 时从 os.environ['HMAC_SECRET'] 读取
        """
        if not delivery_url:
            raise ValueError("WebhookProvider: delivery_url 不能为空")
        self._delivery_url = delivery_url
        # secret 延迟读取 — 允许 startup 后再 set env（测试场景）
        self._hmac_secret = hmac_secret
        self._card_builder = WebhookCardBuilder()

    def _get_secret(self) -> str:
        """读取 HMAC 密钥（构造时 None 则从 env 读，每次调用兜底）。"""
        secret = self._hmac_secret if self._hmac_secret is not None else os.environ.get(
            "HMAC_SECRET", ""
        )
        if not secret:
            raise RuntimeError(
                "Webhook 投递失败：HMAC_SECRET 未配置（环境变量缺失）"
            )
        return secret

    # ── 内部 HTTP POST ──────────────────────────────────────────────────────

    async def _post_with_signature(
        self, *, payload: dict[str, Any], event: str
    ) -> dict[str, Any]:
        """POST payload 到 delivery_url，header 含 HMAC 签名 + event 标识。

        Returns:
            响应 dict（若用户端返回 JSON）；非 JSON 返回空 dict
        """
        payload_bytes = serialize_payload(payload)
        signature = compute_signature(
            payload_bytes=payload_bytes, secret=self._get_secret()
        )
        headers = {
            "Content-Type": "application/json",
            SIGNATURE_HEADER: signature,
            EVENT_HEADER: event,
        }

        log.info(
            "im.card.send.attempt",
            extra={
                "provider": self.name,
                "url": self._delivery_url,
                "event": event,
                "payload_bytes": len(payload_bytes),
            },
        )

        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            try:
                response = await client.post(
                    self._delivery_url,
                    content=payload_bytes,  # 用 raw bytes 保证字节序列与签名一致
                    headers=headers,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                raise ConnectionError(
                    f"Webhook {self._delivery_url} 网络错误: {exc}"
                ) from exc

        # 错误分级
        if response.status_code >= 500 or response.status_code == 429:
            raise ConnectionError(
                f"Webhook HTTP {response.status_code} {response.text[:200]}"
            )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Webhook HTTP {response.status_code} {response.text[:200]}"
            )

        # 解析响应（可能不是 JSON — 用户端自由响应）
        try:
            return response.json()
        except ValueError:
            return {}

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
        """投递 HITL 决策 envelope（POST + HMAC 签名）。

        Args:
            recipient: 用户标识 — 用户端决定如何路由（user_id / email / 自定义 key）

        Returns:
            {"message_id": "webhook:<delivery_url 哈希>", "raw_response": dict}
            message_id 仅作占位符（webhook 无 update 概念）
        """
        hitl_payload = HitlCardPayload(
            flow_title=flow_title,
            node_title=node_title,
            applicant_name=applicant_name,
            actor_name=actor_name,
            deadline_at=deadline_at,
            description=description,
            deeplinks=tuple(deeplinks),
        )
        envelope = build_webhook_payload(
            hitl_payload, recipient=recipient
        )

        raw = await self._post_with_signature(
            payload=envelope, event=WEBHOOK_EVENT_HITL_REQUIRED
        )

        # message_id 用 url + recipient 哈希简化（webhook 无原生 message_id）
        url_hash = hashlib.sha256(self._delivery_url.encode("utf-8")).hexdigest()[:8]
        message_id = f"webhook:{url_hash}:{recipient}"

        return {"message_id": message_id, "raw_response": raw}

    async def update_card(
        self,
        *,
        message_id: str,
        new_content: dict[str, Any],
    ) -> None:
        """通用 webhook 不支持 update — 抛 NotImplementedError。

        调用方应改走 send_supplement_text。
        """
        raise NotImplementedError(
            f"{self.name} update_card 不支持 — 通用 webhook 无 update 概念，请走 send_supplement_text"
        )

    async def send_supplement_text(
        self,
        *,
        recipient: str,
        text: str,
    ) -> None:
        """补发文本（POST 新 envelope，event=hitl_supplement）。"""
        envelope = build_webhook_supplement_payload(
            recipient=recipient, text=text
        )
        await self._post_with_signature(
            payload=envelope, event=WEBHOOK_EVENT_HITL_SUPPLEMENT
        )

    # ── Phase 4.5 入站接口预留 ───────────────────────────────────────────────

    async def subscribe(self, on_event: Any) -> None:
        """[Phase 4.5] 入站订阅 — Phase 4 抛 NotImplementedError。"""
        raise NotImplementedError(f"{self.name} subscribe 将于 Phase 4.5 实现")

    async def verify_webhook_signature(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> bool:
        """[Phase 4.5] 入站签名校验 — Phase 4 抛 NotImplementedError。

        注意：本方法属于"入站"webhook 校验（Phase 4.5 双向 IM）；
        本 provider 的出站 send_* 内部直接用 compute_signature 签名（已实现）。
        """
        raise NotImplementedError(
            f"{self.name} verify_webhook_signature 将于 Phase 4.5 实现"
        )
