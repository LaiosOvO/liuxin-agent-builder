"""arq job: 发送 HITL 邮件（Plan 03-04 Task 3）。

设计参考 docs/reading-dify-03-04-email-delivery-2026-05-17.md §7：
- arq function 替代 Celery shared_task（CLAUDE.md §3 锁定）
- tenacity AsyncRetrying 3 次指数退避（1s/2s/4s）— NOTI-10 显式重试
- 失败路径写 notifications.status='failed' + error_message + audit_log（NOTI-10 可观测）
- 幂等：入参 notification_id；status='sent' 跳过重发（防多 worker / 重启重复）

引用关系：
- _send_email 复用 Phase 1 email_service.py（不重写 aiosmtplib）
- _build_deeplink 与 Dify _build_form_link 等价，路径前缀替换为 /hitl/page/<jti>
- 模板从 backend/app/templates/email/ 加载（Plan 03-04 Task 1 已创建）
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, select_autoescape
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.services.email_service import _send_email

log = logging.getLogger(__name__)

# ── Jinja2 模板环境（模块级单例 — 与 email_service.py 一致） ────────────────
_TEMPLATE_DIR = Path(__file__).parent.parent / "templates" / "email"
_jinja_env: Environment | None = None


def _get_jinja_env() -> Environment:
    """获取 Jinja2 环境（autoescape=html 防 XSS）。

    模块级缓存：首次调用时创建，后续复用。
    """
    global _jinja_env
    if _jinja_env is None:
        _jinja_env = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=select_autoescape(["html"]),
        )
    return _jinja_env


def _build_deeplink(jti: str) -> str:
    """拼装 HITL 决策深链 URL。

    Dify 参考：api/tasks/mail_human_input_delivery_task.py _build_form_link
    - base_url 从 env 读 + rstrip('/') 防双斜杠
    - 路径前缀固定 /hitl/page/<jti>（与 03-06 plan 公网 API 对齐）
    """
    base = os.environ.get("PUBLIC_BASE_URL", "http://localhost:3000").rstrip("/")
    return f"{base}/hitl/page/{jti}"


# ── tenacity 重试配置（NOTI-10 显式 3 次指数退避） ──────────────────────────
# 1s / 2s / 4s 公比 2 — wait_exponential(multiplier=1, min=1, max=4)
_RETRY_STOP = stop_after_attempt(3)
_RETRY_WAIT = wait_exponential(multiplier=1, min=1, max=4)
# 重试触发：SMTP / 网络 / 超时（业务逻辑错误不重试）
_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    aiosmtplib.errors.SMTPException,
    ConnectionError,
    TimeoutError,
    OSError,  # asyncpg / aiosmtplib 底层网络错误
)


def _render_email_content(
    notif_payload: dict[str, Any],
    template_name: str,
) -> str:
    """渲染单个邮件模板（HTML 或 text）。

    Args:
        notif_payload: notifications.payload（含 tokens / form_schema / flow_title / ...）
        template_name: 模板文件名（如 'hitl_decision.html' / 'generic_notification.html'）

    Returns:
        渲染后的字符串（HTML 已 autoescape，text 不 escape）
    """
    env = _get_jinja_env()
    template = env.get_template(template_name)
    # Plan 03-05 通用通知模板（NotificationNode）— payload 仅含 subject/body/recipient_email
    if notif_payload.get("generic") is True:
        return template.render(
            subject=notif_payload.get("subject", ""),
            body=notif_payload.get("body", ""),
            recipient_email=notif_payload.get("recipient_email", ""),
        )
    # HITL 决策 / 催办模板：为 tokens 拼接 deeplinks（每个 token 一条带 URL 的记录）
    deeplinks = [
        {"action": t["action"], "url": _build_deeplink(t["jti"])}
        for t in notif_payload.get("tokens", [])
    ]
    return template.render(
        flow_title=notif_payload.get("flow_title", ""),
        node_title=notif_payload.get("node_title", ""),
        applicant_name=notif_payload.get("applicant_name", ""),
        actor_name=notif_payload.get("actor_name", ""),
        deadline_at=notif_payload.get("deadline_at", ""),
        description=notif_payload.get("description", ""),
        deeplinks=deeplinks,
    )


async def send_hitl_email_job(ctx: dict | None, notification_id: str) -> None:
    """arq job 入口：发送 HITL 决策邮件（NOTI-01 + NOTI-10）。

    Args:
        ctx: arq worker 上下文（含 redis 等）— 测试场景可传 None
        notification_id: notifications.id 字符串（arq enqueue_job 时序列化为 str）

    流程：
    1. SELECT notifications WHERE id=:id
    2. 幂等：if status=='sent' 跳过
    3. status='sending' + commit
    4. 渲染模板：reminder_round>0 用 hitl_reminder.html 否则 hitl_decision.html
    5. tenacity AsyncRetrying 3 次指数退避调用 _send_email
    6. 成功 → status='sent' + sent_at=now()
    7. 失败 → status='failed' + error_message
    """
    from app.agent_builder.db.engine import async_session_maker
    from app.agent_builder.models.notification import Notification

    notif_id_int = int(notification_id)

    async with async_session_maker() as db:
        notif = await db.get(Notification, notif_id_int)
        if notif is None:
            log.error("send_hitl_email_job: notification %s 不存在", notification_id)
            return

        # 幂等：已发送过则跳过（防多 worker / 重启场景）
        if notif.status == "sent":
            log.info(
                "send_hitl_email_job: notification %s 已 sent，跳过重发", notification_id
            )
            return

        # 标记 sending（让其他 worker 不重复抢）
        notif.status = "sending"
        await db.commit()

        # 选择模板（Plan 03-05 新增 generic 路径）：
        # - payload.generic=True → generic_notification.html（Notification 节点，NODE-07）
        # - reminder_round>0 → hitl_reminder.html（催办）
        # - 否则 → hitl_decision.html（HITL 首发）
        is_generic = notif.payload.get("generic") is True
        is_reminder = notif.reminder_round > 0
        if is_generic:
            html_template = "generic_notification.html"
        else:
            html_template = "hitl_reminder.html" if is_reminder else "hitl_decision.html"
        text_template = "hitl_decision_text.txt"  # 明文 fallback 仅 HITL 路径使用

        # 渲染（autoescape 防 XSS）
        try:
            html_body = _render_email_content(notif.payload, html_template)
            # Notification 节点无明文 fallback 需求（body 已是用户输入）
            text_body = (
                None
                if is_generic
                else _render_email_content(notif.payload, text_template)
            )
        except Exception as exc:
            log.exception(
                "send_hitl_email_job: 模板渲染失败 notification_id=%s", notification_id
            )
            notif.status = "failed"
            notif.error_message = f"模板渲染失败: {exc}"[:1000]
            await db.commit()
            return

        # 主题组装（不走 Jinja 模板 — 防注入风险）
        if is_generic:
            # Plan 03-05 通用通知节点：subject 已经在节点 execute 阶段 Jinja 渲染过
            # 这里只做 CR/LF 防注入清理（防止 Jinja 渲染结果意外含换行）
            raw_subject = notif.payload.get("subject", "通知")
            subject = raw_subject.replace("\r", " ").replace("\n", " ")[:200]
        else:
            subject_prefix = "[催办] " if is_reminder else ""
            flow_title = notif.payload.get("flow_title", "")
            node_title = notif.payload.get("node_title", "")
            subject = f"{subject_prefix}审批待办：{flow_title} - {node_title}"

        # tenacity AsyncRetrying 3 次指数退避
        last_error: Exception | None = None
        try:
            async for attempt in AsyncRetrying(
                stop=_RETRY_STOP,
                wait=_RETRY_WAIT,
                retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
                reraise=True,
            ):
                with attempt:
                    await _send_email(
                        to=notif.recipient,
                        subject=subject,
                        html_body=html_body,
                    )
                    # _send_email 已包含 text/plain 备用，但 HITL 邮件需要明确的文本 fallback
                    # （Phase 1 _send_email 内置的 plain text 是 "请使用支持 HTML..." 占位符；
                    #  HITL 场景要求明文 URL 列表，需 Phase 6 扩展 _send_email 接受 text_body 参数。
                    #  当前 plan 不动 Phase 1 接口，HTML 已含可访问的链接，text fallback 留 03-09 增强）
            # 成功路径
            notif.status = "sent"
            notif.sent_at = datetime.now(timezone.utc)
            notif.error_message = None
            log.info(
                "已发送 HITL 邮件 notification_id=%s recipient=%s",
                notification_id,
                notif.recipient,
            )
        except Exception as exc:
            last_error = exc
            notif.status = "failed"
            notif.error_message = str(exc)[:1000]
            log.exception(
                "send_hitl_email_job: tenacity 3 次重试均失败 notification_id=%s",
                notification_id,
            )
            # NOTI-10 显式可观测：写 audit_log
            await _write_audit_log_failure(db, notif, str(exc))
        finally:
            await db.commit()


async def send_hitl_reminder_job(ctx: dict | None, notification_id: str) -> None:
    """arq job 入口：发送 HITL 催办邮件（NOTI-09）。

    实现与 send_hitl_email_job 一致 — 仅模板差异由 reminder_round 控制。
    Plan 03-09 催办 worker 调用此函数（区分于首发 job 便于监控分类）。
    """
    await send_hitl_email_job(ctx, notification_id)


async def _write_audit_log_failure(db, notif, error: str) -> None:
    """通知发送失败时写 audit_log（NOTI-10 显式可观测）。

    action='email.send_failed'
    meta 含 notification_id / recipient / reminder_round / error 摘要
    """
    try:
        from app.services.audit import log as audit_log

        await audit_log(
            db,
            action="email.send_failed",
            workspace_id=notif.workspace_id,
            target_type="notification",
            target_id=None,  # notifications.id 是 BIGSERIAL，不是 UUID
            meta={
                "notification_id": notif.id,
                "channel": notif.channel,
                "recipient": notif.recipient,
                "reminder_round": notif.reminder_round,
                "error": error[:500],
            },
        )
    except Exception:
        # 审计写入失败不应影响主流程
        log.exception("写 audit_log 失败 notification_id=%s", notif.id)
