"""DingTalkProvider — 钉钉 IM 出站投递实现（Plan 04-08）。

参考 docs/reading-im-sdk-04-08-dingtalk-2026-05-17.md：
- SDK: dingtalk-stream==0.24.3（CLAUDE.md §3 锁定）
- access_token 获取走 SDK 的 DingTalkStreamClient.get_access_token（内置 5min buffer 缓存）
- 工作通知 ActionCard 投递走 OAPI HTTP：POST /topapi/message/corpconversation/asyncsend_v2
- update_card → NotImplementedError（钉钉工作通知 ActionCard 静态，走 send_supplement_text）

满足 IMProvider Protocol（notification/providers/base.py）：
- name="dingtalk"
- send_hitl_card → dict[str, Any]（含 message_id + raw_response）
- update_card → NotImplementedError
- send_supplement_text → None
- subscribe / verify_webhook_signature → NotImplementedError（Phase 4.5 实现）

CLAUDE.md immutability：
- DingTalkProvider 实例字段 immutable（credentials / agent_id / http_client_factory）
- 每次 send 创建新 dict 入参/出参，不修改既有数据
- SDK 客户端单例（同一 credentials 复用 token 缓存）

CLAUDE.md security：
- access_token 不写日志（仅记录前 8 字符 + ... 占位）
- 异常 message 不泄漏 token / secret
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.agent_builder.core.im_credentials import DingTalkCredentials
from app.agent_builder.notification.cards.base import HitlCardPayload
from app.agent_builder.notification.cards.dingtalk_card import (
    build_dingtalk_action_card,
    build_dingtalk_supplement_text,
)
from app.agent_builder.notification.providers.base import PROVIDER_DINGTALK

log = logging.getLogger(__name__)

# ── 钉钉 OAPI endpoint 常量 ─────────────────────────────────────────────────
_DINGTALK_OAPI_BASE = "https://oapi.dingtalk.com"
_ACTION_CARD_SEND_PATH = "/topapi/message/corpconversation/asyncsend_v2"
_TEXT_SEND_PATH = "/topapi/message/corpconversation/asyncsend_v2"

# ── 默认 HTTP 超时（与 email_jobs tenacity 1s/2s/4s 兼容） ───────────────────
_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)


@dataclass(frozen=True)
class _DingTalkSendResult:
    """钉钉 OAPI asyncsend_v2 响应解析结果（内部用）。"""

    errcode: int
    errmsg: str
    task_id: str | None  # 成功时为字符串 task_id；失败为 None


class DingTalkProvider:
    """钉钉 IM Provider（实现 IMProvider Protocol 鸭子类型）。

    用法：
        creds = im_credentials_manager.dingtalk()  # DingTalkCredentials
        provider = DingTalkProvider(credentials=creds, agent_id=123456)
        register_provider(provider)
        # ... im_jobs.send_hitl_card_job 自动调用 ...

    架构：
    - access_token 通过 SDK 的 DingTalkStreamClient（同步）+ asyncio.to_thread 桥接
    - 实际投递走 httpx.AsyncClient → OAPI `/topapi/message/corpconversation/asyncsend_v2`
    - 不开启 SDK stream 模式（Phase 4 仅出站；Phase 4.5 Bot Trigger 时启动 start_forever）
    """

    name: str = PROVIDER_DINGTALK

    def __init__(
        self,
        *,
        credentials: DingTalkCredentials,
        agent_id: int,
        http_client: httpx.AsyncClient | None = None,
        sdk_client: Any | None = None,
    ) -> None:
        """
        Args:
            credentials: DingTalkCredentials (app_key + app_secret)
            agent_id: 钉钉工作通知 agent_id（int — 来自 env DINGTALK_AGENT_ID）
            http_client: 注入式 httpx.AsyncClient（测试可 mock；未传则按需创建）
            sdk_client: 注入式 dingtalk_stream.DingTalkStreamClient（测试可 mock）
        """
        self._credentials = credentials
        self._agent_id = agent_id
        self._http_client = http_client  # None → send 时按需创建
        self._sdk_client = sdk_client  # None → 首次 send 时延迟创建
        self._lock = asyncio.Lock()

    # ── access_token 获取（SDK 同步 → asyncio 桥接 + token 缓存） ───────────

    async def _get_access_token(self) -> str:
        """获取钉钉 access_token（asyncio.to_thread 包装 SDK 同步调用）。

        SDK 内置 5min buffer 缓存（DingTalkStreamClient._access_token），
        无需本类自管。

        Returns:
            access_token 字符串

        Raises:
            ConnectionError: SDK 返回 None（网络错 / 凭据错），由调用方传给 tenacity 重试
        """
        # 延迟创建 SDK client（避免 import 阶段触发；单例复用 token 缓存）
        if self._sdk_client is None:
            async with self._lock:
                if self._sdk_client is None:
                    self._sdk_client = self._create_sdk_client()

        # SDK get_access_token 是同步 requests 调用 — 包到 to_thread 避免阻塞 event loop
        token = await asyncio.to_thread(self._sdk_client.get_access_token)
        if not token:
            raise ConnectionError(
                "钉钉 access_token 获取失败（SDK 返回 None — 检查 app_key/app_secret 或网络）"
            )
        return token

    def _create_sdk_client(self) -> Any:
        """创建 dingtalk_stream.DingTalkStreamClient 实例（延迟 import 防测试环境无 SDK 失败）。"""
        import dingtalk_stream

        credential = dingtalk_stream.Credential(
            self._credentials.app_key,
            self._credentials.app_secret,
        )
        return dingtalk_stream.DingTalkStreamClient(credential)

    # ── HTTP client lifecycle ──────────────────────────────────────────────

    async def _get_http_client(self) -> httpx.AsyncClient:
        """获取或创建 httpx.AsyncClient（单例复用连接池）。"""
        if self._http_client is None:
            async with self._lock:
                if self._http_client is None:
                    self._http_client = httpx.AsyncClient(
                        base_url=_DINGTALK_OAPI_BASE,
                        timeout=_DEFAULT_TIMEOUT,
                    )
        return self._http_client

    # ── IMProvider 接口实现 ────────────────────────────────────────────────

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
        """投递 HITL 决策卡片（钉钉 ActionCard 工作通知）。

        Args:
            recipient: 钉钉 userid（不是 unionid / mobile — OAPI userid_list 字段）
            flow_title / node_title / applicant_name / actor_name / deadline_at / description:
                卡片字段（与其他 Provider 通用 — HitlCardPayload 字段）
            deeplinks: [{"action": "approve", "url": "https://..."}, ...]

        Returns:
            {
                "message_id": str,        # 钉钉 task_id（用于 update_card；本 Provider 不支持 update）
                "raw_response": dict      # OAPI 原始响应
            }

        Raises:
            ConnectionError: OAPI errcode != 0 / 网络错（tenacity 会重试）
        """
        payload = HitlCardPayload(
            flow_title=flow_title,
            node_title=node_title,
            applicant_name=applicant_name,
            actor_name=actor_name,
            deadline_at=deadline_at,
            description=description,
            deeplinks=tuple(deeplinks),  # frozen — 防外部修改
        )
        card_msg = build_dingtalk_action_card(payload)

        access_token = await self._get_access_token()
        request_body = {
            "agent_id": self._agent_id,
            "userid_list": recipient,
            "msg": card_msg,
        }
        result = await self._post_to_oapi(_ACTION_CARD_SEND_PATH, access_token, request_body)

        if result.errcode != 0:
            # 业务错（errcode != 0）也包成 ConnectionError 触发 tenacity 重试
            # （某些 errcode 如 40078 token 过期，重试新 token 后可成功）
            raise ConnectionError(
                f"钉钉 ActionCard 发送失败 errcode={result.errcode} errmsg={result.errmsg}"
            )

        return {
            "message_id": result.task_id or "",
            "raw_response": {
                "errcode": result.errcode,
                "errmsg": result.errmsg,
                "task_id": result.task_id,
            },
        }

    async def update_card(
        self,
        *,
        message_id: str,
        new_content: dict[str, Any],
    ) -> None:
        """钉钉工作通知 ActionCard 不支持发送后修改 → 调用方应走 send_supplement_text 兜底。"""
        raise NotImplementedError(
            "钉钉工作通知 ActionCard 不支持 update_card（静态卡片）— "
            "请使用 send_supplement_text 发送'流程已被 X 处理'补充文本"
        )

    async def send_supplement_text(
        self,
        *,
        recipient: str,
        text: str,
    ) -> None:
        """发送文本工作通知（钉钉 msgtype="text"）。

        用于 04-10 multichannel fan-out 决策推进后通知其他 channel 用户。

        Args:
            recipient: 钉钉 userid
            text: 纯文本内容（建议 ≤ 200 字符）

        Raises:
            ConnectionError: OAPI errcode != 0 / 网络错
        """
        access_token = await self._get_access_token()
        request_body = {
            "agent_id": self._agent_id,
            "userid_list": recipient,
            "msg": {
                "msgtype": "text",
                "text": {"content": text},
            },
        }
        result = await self._post_to_oapi(_TEXT_SEND_PATH, access_token, request_body)
        if result.errcode != 0:
            raise ConnectionError(
                f"钉钉 supplement text 发送失败 errcode={result.errcode} errmsg={result.errmsg}"
            )

    # ── Phase 4.5 入站接口预留 ──────────────────────────────────────────────

    async def subscribe(self, on_event: Any) -> None:
        """[Phase 4.5] 入站 stream 订阅（待 Bot Trigger plan 实现）。"""
        raise NotImplementedError(
            f"{self.name} subscribe 将于 Phase 4.5 实现 — "
            "届时启动 DingTalkStreamClient.start_forever() + register_callback_handler"
        )

    async def verify_webhook_signature(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> bool:
        """[Phase 4.5] webhook 签名校验（钉钉 stream 模式自带签名 — 占位）。"""
        raise NotImplementedError(
            f"{self.name} verify_webhook_signature 将于 Phase 4.5 实现"
        )

    # ── 内部 OAPI 调用 ─────────────────────────────────────────────────────

    async def _post_to_oapi(
        self,
        path: str,
        access_token: str,
        body: dict[str, Any],
    ) -> _DingTalkSendResult:
        """POST 钉钉 OAPI（统一错误处理 + 响应解析）。

        Args:
            path: OAPI 路径（如 /topapi/message/corpconversation/asyncsend_v2）
            access_token: 通过 _get_access_token 获取
            body: 请求 JSON 体

        Returns:
            _DingTalkSendResult（errcode / errmsg / task_id）

        Raises:
            ConnectionError: HTTP 错（5xx / 网络）— httpx.HTTPError 包装
        """
        client = await self._get_http_client()
        try:
            response = await client.post(
                path,
                params={"access_token": access_token},
                json=body,
            )
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            # 网络层错误 → ConnectionError（tenacity 重试可吞）
            raise ConnectionError(f"钉钉 OAPI 网络错: {exc}") from exc

        # OAPI 即使业务错也返 HTTP 200，errcode 在 body 中
        if response.status_code >= 500:
            raise ConnectionError(
                f"钉钉 OAPI HTTP {response.status_code} — 临时不可用"
            )
        if response.status_code >= 400:
            raise ConnectionError(
                f"钉钉 OAPI HTTP {response.status_code} 客户端错: {response.text[:200]}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise ConnectionError(f"钉钉 OAPI 响应非 JSON: {response.text[:200]}") from exc

        errcode = int(data.get("errcode", -1))
        errmsg = str(data.get("errmsg", "unknown"))
        # task_id 在 asyncsend_v2 响应顶层（钉钉文档约定）
        task_id = data.get("task_id")
        task_id_str = str(task_id) if task_id is not None else None

        return _DingTalkSendResult(
            errcode=errcode,
            errmsg=errmsg,
            task_id=task_id_str,
        )

    # ── 关闭（FastAPI lifespan shutdown 调） ───────────────────────────────

    async def aclose(self) -> None:
        """关闭 httpx 客户端（lifespan shutdown 调，可选）。"""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
