"""异步邮件发送服务。

使用 aiosmtplib 5.1.0 + Jinja2 3.1.6 渲染 HTML 模板。
SMTP 配置从环境变量读取（startup_checks 已确认非空）。
失败时写 audit_log action='email.send_failed'，Phase 1 不做重试（Phase 3 引入 arq）。

支持发送的邮件类型：
- verification.html: 邮箱验证邮件
- invitation.html:   邀请注册邮件
- welcome.html:      欢迎邮件（邀请落地后发送）
"""
from __future__ import annotations

import logging
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, select_autoescape

log = logging.getLogger(__name__)

# 邮件模板目录（相对于本文件）
_TEMPLATE_DIR = Path(__file__).parent.parent / "templates" / "email"

# Jinja2 环境（autoescape=True 防 XSS）
_jinja_env: Environment | None = None


def _get_jinja_env() -> Environment:
    global _jinja_env
    if _jinja_env is None:
        _jinja_env = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=select_autoescape(["html"]),
        )
    return _jinja_env


def _render_template(template_name: str, context: dict[str, Any]) -> str:
    """渲染 Jinja2 模板。

    Args:
        template_name: 模板文件名（如 'verification.html'）
        context: 模板变量

    Returns:
        渲染后的 HTML 字符串
    """
    env = _get_jinja_env()
    template = env.get_template(template_name)
    return template.render(**context)


def _get_smtp_config() -> dict[str, Any]:
    """读取 SMTP 配置（已由 startup_checks 校验存在）。"""
    return {
        "hostname": os.environ.get("SMTP_HOST", "localhost"),
        "port": int(os.environ.get("SMTP_PORT", "1025")),
        "username": os.environ.get("SMTP_USERNAME", ""),
        "password": os.environ.get("SMTP_PASSWORD", ""),
        "from_addr": os.environ.get("SMTP_FROM", "noreply@agent-builder.local"),
        "use_tls": os.environ.get("SMTP_TLS", "false").lower() == "true",
        "start_tls": os.environ.get("SMTP_STARTTLS", "false").lower() == "true",
    }


async def _send_email(
    to: str,
    subject: str,
    html_body: str,
) -> None:
    """底层发送逻辑：构建 MIME 消息 + aiosmtplib 发送。

    Args:
        to: 收件人邮箱
        subject: 邮件主题
        html_body: HTML 正文
    """
    cfg = _get_smtp_config()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["from_addr"]
    msg["To"] = to

    # 纯文本备用（主流邮件客户端降级显示）
    plain_text = "请使用支持 HTML 的邮件客户端查看此邮件。"
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    kwargs: dict[str, Any] = {
        "hostname": cfg["hostname"],
        "port": cfg["port"],
        "message": msg,
    }

    # 认证（仅在 username 非空时）
    if cfg["username"]:
        kwargs["username"] = cfg["username"]
        kwargs["password"] = cfg["password"]

    # TLS 配置：TLS 优先于 STARTTLS
    if cfg["use_tls"]:
        kwargs["use_tls"] = True
    elif cfg["start_tls"]:
        kwargs["start_tls"] = True

    await aiosmtplib.send(**kwargs)


async def send_verification_email(
    to: str,
    verification_url: str,
    display_name: str | None = None,
    db: Any = None,
    request: Any = None,
) -> None:
    """发送邮箱验证邮件。

    Args:
        to: 收件人邮箱
        verification_url: 验证链接（含 JWT token）
        display_name: 用户显示名（可为 None）
        db: AsyncSession（失败时写 audit_log）
        request: Request 对象（audit 提取 IP/UA）
    """
    try:
        html = _render_template(
            "verification.html",
            {
                "display_name": display_name or to,
                "verification_url": verification_url,
            },
        )
        await _send_email(
            to=to,
            subject="请验证您的邮箱地址 — agent-builder",
            html_body=html,
        )
        log.info("已发送验证邮件到 %s", to)
    except Exception as exc:
        log.error("发送验证邮件失败 to=%s error=%s", to, exc)
        if db is not None:
            # 异步写 audit_log（注意：不 await，避免递归失败）
            try:
                from app.services.audit import log as audit_log

                await audit_log(
                    db,
                    action="email.send_failed",
                    meta={
                        "to": to,
                        "type": "verification",
                        "error": str(exc),
                    },
                    request=request,
                )
            except Exception:
                pass  # 审计写入失败不应影响主流程


async def send_invitation_email(
    to: str,
    invitation_url: str,
    workspace_name: str,
    role: str,
    invited_by_name: str,
    db: Any = None,
    request: Any = None,
) -> None:
    """发送邀请注册邮件。

    Args:
        to: 被邀请人邮箱
        invitation_url: 邀请链接（含 JWT token）
        workspace_name: 工作区名称
        role: 目标角色名
        invited_by_name: 邀请人显示名
        db: AsyncSession（失败时写 audit_log）
        request: Request 对象
    """
    try:
        html = _render_template(
            "invitation.html",
            {
                "to_email": to,
                "invitation_url": invitation_url,
                "workspace_name": workspace_name,
                "role": role,
                "invited_by_name": invited_by_name,
            },
        )
        await _send_email(
            to=to,
            subject=f"{invited_by_name} 邀请您加入 {workspace_name} — agent-builder",
            html_body=html,
        )
        log.info("已发送邀请邮件到 %s", to)
    except Exception as exc:
        log.error("发送邀请邮件失败 to=%s error=%s", to, exc)
        if db is not None:
            try:
                from app.services.audit import log as audit_log

                await audit_log(
                    db,
                    action="email.send_failed",
                    meta={
                        "to": to,
                        "type": "invitation",
                        "error": str(exc),
                    },
                    request=request,
                )
            except Exception:
                pass


async def send_welcome_email(
    to: str,
    display_name: str | None = None,
    db: Any = None,
    request: Any = None,
) -> None:
    """发送欢迎邮件（邀请落地注册完成后）。

    Args:
        to: 用户邮箱
        display_name: 用户显示名
        db: AsyncSession（失败时写 audit_log）
        request: Request 对象
    """
    try:
        html = _render_template(
            "welcome.html",
            {
                "display_name": display_name or to,
                "login_url": f"{os.environ.get('PUBLIC_BASE_URL', 'http://localhost:3000')}/login",
            },
        )
        await _send_email(
            to=to,
            subject="欢迎加入 agent-builder",
            html_body=html,
        )
        log.info("已发送欢迎邮件到 %s", to)
    except Exception as exc:
        log.error("发送欢迎邮件失败 to=%s error=%s", to, exc)
        if db is not None:
            try:
                from app.services.audit import log as audit_log

                await audit_log(
                    db,
                    action="email.send_failed",
                    meta={
                        "to": to,
                        "type": "welcome",
                        "error": str(exc),
                    },
                    request=request,
                )
            except Exception:
                pass
