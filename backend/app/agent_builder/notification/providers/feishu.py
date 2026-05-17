"""FeishuProvider — 飞书 IM Provider 实现（Plan 04-06 NOTI-02）。

满足 IMProvider Protocol（鸭子类型）：
- send_hitl_card → client.im.v1.message.create + interactive content
- update_card    → client.im.v1.message.patch
- send_supplement_text → client.im.v1.message.create + text content
- subscribe / verify_webhook_signature → NotImplementedError（Phase 4.5 实现）

设计参考 docs/reading-im-sdk-04-06-feishu-2026-05-17.md：
- lark-oapi 1.6.5（CLAUDE.md §3 强制版本锁定）
- importlib.metadata.version 取版本（lark.__version__ 属性不存在 — reading doc §3）
- 同步 SDK 在 asyncio 内通过 loop.run_in_executor 包装（reading doc §8）
- 延迟 client 初始化 — 避免 import 时建立连接
- ConnectionError 触发 im_jobs.tenacity 重试；其他错误直接 fail

CLAUDE.md immutability：
- 凭据 app_id / app_secret 通过 __init__ 注入，运行时不可改
- send_hitl_card 入参不修改（dict 构造新对象）
"""
from __future__ import annotations

import asyncio
import json
import logging
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from typing import Any

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    PatchMessageRequest,
    PatchMessageRequestBody,
)

from app.agent_builder.notification.cards.feishu_card import (
    build_feishu_hitl_card,
)
from app.agent_builder.notification.providers.base import PROVIDER_FEISHU

log = logging.getLogger(__name__)


# ── SDK 版本锁定（CLAUDE.md §3 强制）────────────────────────────────────────
# lark-oapi 1.6.0/1/2/3 已被 PyPI yanked，必须 pin 1.6.5
_EXPECTED_LARK_VERSION = "1.6.5"


def _resolve_lark_version() -> str:
    """获取已安装 lark-oapi 真实版本。

    陷阱：lark.__version__ 属性不存在（reading doc §3）— 必须用 importlib.metadata。
    """
    try:
        return _pkg_version("lark-oapi")
    except PackageNotFoundError:
        return "unknown"


class FeishuProvider:
    """飞书出站 IM Provider — 实现 IMProvider Protocol（鸭子类型）。

    用法：
        creds = IMCredentialsManager()
        if creds.has_feishu():
            provider = FeishuProvider(
                app_id=creds.feishu().app_id,
                app_secret=creds.feishu().app_secret,
            )
            register_provider(provider)

    Phase 4.5 扩展点：
        subscribe / verify_webhook_signature 在 Phase 4 抛 NotImplementedError，
        Phase 4.5 Bot Trigger plan 各自覆盖实现真实 webhook 接收。
    """

    name = PROVIDER_FEISHU
    """Provider 名（与 IMProvider Protocol.name 字段一致）"""

    def __init__(self, app_id: str, app_secret: str) -> None:
        """初始化飞书 Provider — 不在此刻创建 client（延迟初始化）。

        Args:
            app_id: 飞书应用 App ID（cli_xxx）
            app_secret: 飞书应用 App Secret

        SDK 版本校验在此触发（warning，不抛错 — 开发环境兼容）。
        """
        self.app_id = app_id
        self.app_secret = app_secret
        self._client: lark.Client | None = None

        # 启动校验 SDK 版本（CLAUDE.md §3）
        actual_version = _resolve_lark_version()
        if actual_version != _EXPECTED_LARK_VERSION:
            log.warning(
                "lark-oapi 版本 %s != %s（CLAUDE.md §3 锁定）— "
                "1.6.0/1/2/3 已 yanked，行为可能异常",
                actual_version,
                _EXPECTED_LARK_VERSION,
            )

    @property
    def client(self) -> lark.Client:
        """延迟构造 lark.Client — 避免 module import 时建立连接。

        SDK 内部管理 tenant_access_token cache，单 instance 可重用。
        """
        if self._client is None:
            self._client = (
                lark.Client.builder()
                .app_id(self.app_id)
                .app_secret(self.app_secret)
                .log_level(lark.LogLevel.WARNING)  # SDK 内部日志
                .build()
            )
        return self._client

    # ── send_hitl_card ──────────────────────────────────────────────────────

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
        """投递飞书 HITL 决策卡片（Interactive Card 2.0）。

        Args:
            recipient: 飞书用户 open_id（不是 email — receive_id_type='open_id'）
            其余字段：见 IMProvider Protocol

        Returns:
            {
                "message_id": str,            # 飞书消息 ID（om_xxx），供 update_card 用
                "raw_response": dict          # {"code": int, "msg": str, "log_id": str}
            }

        Raises:
            ConnectionError: 飞书内部错误 / 网络错误 — tenacity 会重试
                             业务错误（11201 token 错 / 230020 用户不存在 等）也包装为
                             ConnectionError 但 im_jobs 会通过 3 次尝试后写 failed +
                             audit_log 让运维介入。
        """
        # 构造卡片 JSON（纯函数 — 不影响异常路径）
        card = build_feishu_hitl_card(
            flow_title=flow_title,
            node_title=node_title,
            applicant_name=applicant_name,
            actor_name=actor_name,
            deadline_at=deadline_at,
            description=description,
            deeplinks=deeplinks,
        )

        # 构造请求（reading doc §4.2 Builder 模式）
        request = (
            CreateMessageRequest.builder()
            .receive_id_type("open_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(recipient)
                .msg_type("interactive")
                .content(json.dumps(card))  # content 必须是字符串
                .build()
            )
            .build()
        )

        # 同步 SDK 在 asyncio 内包装（reading doc §8）
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, self.client.im.v1.message.create, request
        )

        if not response.success():
            # ConnectionError 让 im_jobs.tenacity 重试 — 业务错误也走重试，
            # 重试用尽后写 failed + audit_log（reading doc §7）
            err_msg = (
                f"feishu send_hitl_card failed: "
                f"code={response.code} msg={response.msg} "
                f"log_id={response.get_log_id()}"
            )
            log.error(err_msg)
            raise ConnectionError(err_msg)

        message_id = response.data.message_id if response.data else ""
        return {
            "message_id": message_id,
            "raw_response": {
                "code": response.code,
                "msg": response.msg,
                "log_id": response.get_log_id(),
            },
        }

    # ── update_card ─────────────────────────────────────────────────────────

    async def update_card(
        self,
        *,
        message_id: str,
        new_content: dict[str, Any],
    ) -> None:
        """更新已发送卡片为只读"已被 X 处理"状态 — reading doc §6。

        Args:
            message_id: send_hitl_card 返回的 message_id（om_xxx）
            new_content: 新卡片 JSON dict（通常来自 build_feishu_processed_card）

        Raises:
            ConnectionError: 飞书内部错误 / 网络错误 — tenacity 会重试
                             24h 时间窗外（code=234016）— log warning 不抛错（视为正常）
        """
        request = (
            PatchMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                PatchMessageRequestBody.builder()
                .content(json.dumps(new_content))
                .build()
            )
            .build()
        )

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, self.client.im.v1.message.patch, request
        )

        if not response.success():
            # 234016 = 消息已过期（24h 外 patch）— 流程已超时，视为正常
            if response.code == 234016:
                log.warning(
                    "feishu update_card 跳过：消息已过期（24h 外 patch）"
                    " message_id=%s code=%s",
                    message_id,
                    response.code,
                )
                return
            err_msg = (
                f"feishu update_card failed: "
                f"code={response.code} msg={response.msg} "
                f"log_id={response.get_log_id()}"
            )
            log.error(err_msg)
            raise ConnectionError(err_msg)

    # ── send_supplement_text ────────────────────────────────────────────────

    async def send_supplement_text(
        self,
        *,
        recipient: str,
        text: str,
    ) -> None:
        """补发文本（"流程已被 X 处理" 等通知）— 不支持 update_card 的场景兜底。

        Args:
            recipient: 飞书用户 open_id
            text: 纯文本内容（≤ 200 字符建议）

        失败仅 log warning（不抛错）— 补发非关键路径，主流程已通过 update_card 完成。
        """
        request = (
            CreateMessageRequest.builder()
            .receive_id_type("open_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(recipient)
                .msg_type("text")
                # 飞书 text 消息 content 格式：{"text": "..."}
                .content(json.dumps({"text": text}))
                .build()
            )
            .build()
        )

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, self.client.im.v1.message.create, request
        )

        if not response.success():
            log.warning(
                "feishu send_supplement_text failed: code=%s msg=%s log_id=%s",
                response.code,
                response.msg,
                response.get_log_id(),
            )

    # ── Phase 4.5 入站接口预留（与 Protocol 默认行为一致）──────────────────

    async def subscribe(self, on_event: Any) -> None:
        """[Phase 4.5] 入站事件订阅（Phase 4 抛 NotImplementedError）。"""
        raise NotImplementedError(
            f"{self.name} subscribe 将于 Phase 4.5 Bot Trigger plan 实现"
        )

    async def verify_webhook_signature(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> bool:
        """[Phase 4.5] webhook 签名校验（Phase 4 抛 NotImplementedError）。"""
        raise NotImplementedError(
            f"{self.name} verify_webhook_signature 将于 Phase 4.5 实现"
        )
