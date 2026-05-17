"""MailHog 邮件捕获客户端（Python port 自 e2e/helpers/mailhog-client.ts）。

MailHog API: http://localhost:8025/api/v2/messages

提供：
- get_latest_email(to_email, timeout): 轮询找指定收件人邮件
- get_emails_for(to_email, timeout, min_count): 找 N 封发给同一人的邮件（chain mode）
- purge_all(): 清空所有邮件（spec 隔离）
- parse_hitl_deeplinks(html): 解析 HITL 邮件中的 4 按钮 deeplink
- extract_jti_from_token(token): 不校验签名提取 jti 字段
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx


MAILHOG_API_URL = os.environ.get("MAILHOG_API_URL", "http://localhost:8025")


# ── 数据结构 ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HitlDeeplink:
    """HITL 邮件按钮 deeplink（不可变快照）。"""

    action: str  # approve / return / reject / submit / unknown
    url: str
    token: str  # JWT 字符串
    jti: str


@dataclass(frozen=True)
class HitlEmailParsed:
    """解析后的 HITL 邮件结构。"""

    to: str
    subject: str
    html: str  # 主体 HTML
    text: str  # 纯文本 fallback
    is_reminder: bool  # subject 含 [催办]
    is_escalation: bool  # subject 含 [升级]
    is_supplement: bool  # subject 含 [终止] / [已被处理]
    deeplinks: tuple[HitlDeeplink, ...]


# ── HTTP fetch helpers ──────────────────────────────────────────────────


async def _fetch_messages(client: httpx.AsyncClient, limit: int = 50) -> list[dict]:
    """从 MailHog API 抓邮件列表。"""
    r = await client.get(f"{MAILHOG_API_URL}/api/v2/messages?limit={limit}")
    r.raise_for_status()
    return r.json().get("items", [])


def _msg_to_addresses(msg: dict) -> list[str]:
    """提取邮件的所有收件人 email（小写）。"""
    return [
        f"{t.get('Mailbox','')}@{t.get('Domain','')}".lower()
        for t in msg.get("To", [])
    ]


# ── 公共 API ────────────────────────────────────────────────────────────


async def purge_all(client: httpx.AsyncClient | None = None) -> None:
    """清空 MailHog 所有邮件。"""
    own = client is None
    if own:
        client = httpx.AsyncClient()
    try:
        await client.delete(f"{MAILHOG_API_URL}/api/v1/messages")
    finally:
        if own:
            await client.aclose()


async def get_latest_email(
    to_email: str,
    timeout: float = 10.0,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """轮询找发给 to_email 的最新邮件（最近一封）。

    Raises:
        TimeoutError: timeout 秒内没找到匹配邮件
    """
    own = client is None
    if own:
        client = httpx.AsyncClient()
    try:
        deadline = time.time() + timeout
        target = to_email.lower()
        while time.time() < deadline:
            items = await _fetch_messages(client)
            for m in items:
                if target in _msg_to_addresses(m):
                    return m
            await asyncio.sleep(0.3)
        raise TimeoutError(f"{timeout}s 内未找到发给 {to_email} 的邮件")
    finally:
        if own:
            await client.aclose()


async def get_emails_for(
    to_email: str,
    min_count: int = 1,
    timeout: float = 15.0,
    client: httpx.AsyncClient | None = None,
) -> list[dict]:
    """轮询直到至少 min_count 封邮件发给 to_email（chain mode 验证 N 人同时收到）。

    返回所有匹配邮件（按 mailhog 顺序，最新在前）。
    """
    own = client is None
    if own:
        client = httpx.AsyncClient()
    try:
        deadline = time.time() + timeout
        target = to_email.lower()
        while time.time() < deadline:
            items = await _fetch_messages(client)
            matches = [m for m in items if target in _msg_to_addresses(m)]
            if len(matches) >= min_count:
                return matches
            await asyncio.sleep(0.3)
        raise TimeoutError(
            f"{timeout}s 内未找到 {min_count} 封发给 {to_email} 的邮件"
        )
    finally:
        if own:
            await client.aclose()


async def get_all_emails(client: httpx.AsyncClient | None = None) -> list[dict]:
    """获取 MailHog 所有邮件列表。"""
    own = client is None
    if own:
        client = httpx.AsyncClient()
    try:
        return await _fetch_messages(client, limit=200)
    finally:
        if own:
            await client.aclose()


# ── MIME body 切分 ──────────────────────────────────────────────────────


_QUOTED_PRINTABLE_BYTE = re.compile(rb"=([0-9A-Fa-f]{2})")


def _decode_quoted_printable(raw: str) -> str:
    """quoted-printable → utf-8。"""
    no_soft_break = raw.replace("=\n", "").replace("=\r\n", "")
    as_bytes = no_soft_break.encode("latin-1", errors="ignore")
    decoded_bytes = _QUOTED_PRINTABLE_BYTE.sub(
        lambda m: bytes.fromhex(m.group(1).decode()), as_bytes
    )
    return decoded_bytes.decode("utf-8", errors="replace")


def _decode_mime_header(raw: str) -> str:
    """=?UTF-8?B|Q?...?= 编码的 MIME header 解码（RFC 2047）。"""

    def _decode(match: re.Match[str]) -> str:
        enc = match.group(2).upper()
        text = match.group(3)
        try:
            if enc == "B":
                return base64.b64decode(text).decode("utf-8", errors="replace")
            return _decode_quoted_printable(text.replace("_", " "))
        except Exception:
            return text

    return re.sub(r"=\?([^?]+)\?([BbQq])\?([^?]*)\?=", _decode, raw)


def _split_mime_body(body: str) -> tuple[str, str]:
    """切分 multipart MIME body → (html, text)。"""
    if "Content-Type:" not in body and "boundary=" not in body:
        if body.lstrip().startswith("<") or "<html" in body:
            return body, ""
        return "", body

    html, text = "", ""
    html_match = re.search(
        r"Content-Type:\s*text/html[^\n]*\n(?:[^\n]*\n)*?\n([\s\S]*?)(?:\n--[a-zA-Z0-9_-]+|\n\.|\Z)",
        body,
        re.IGNORECASE,
    )
    if html_match:
        html = _decode_quoted_printable(html_match.group(1))

    text_match = re.search(
        r"Content-Type:\s*text/plain[^\n]*\n(?:[^\n]*\n)*?\n([\s\S]*?)(?:\n--[a-zA-Z0-9_-]+|\n\.|\Z)",
        body,
        re.IGNORECASE,
    )
    if text_match:
        text = _decode_quoted_printable(text_match.group(1))

    if not html and not text:
        html = body

    return html, text


# ── HITL 邮件解析 ───────────────────────────────────────────────────────


def extract_jti_from_jwt(token: str) -> str:
    """从 JWT token 解码 jti（不校验签名，仅 E2E 断言用）。"""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return ""
        payload_b64 = parts[1]
        # base64url → base64 + padding
        base64_str = payload_b64.replace("-", "+").replace("_", "/")
        padded = base64_str + "=" * ((4 - len(base64_str) % 4) % 4)
        payload_json = base64.b64decode(padded).decode("utf-8", errors="replace")
        payload = json.loads(payload_json)
        return str(payload.get("jti", ""))
    except Exception:
        return ""


def _infer_action(label: str, url: str) -> str:
    """按 button 文案 + URL fragment 推断 action。"""
    lower = label.lower()
    if "通过" in label or "approve" in lower:
        return "approve"
    if "提交" in label or "submit" in lower:
        return "submit"
    if "退回" in label or "return" in lower:
        return "return"
    if "拒绝" in label or "reject" in lower:
        return "reject"

    m = re.search(r"[?&]action=(\w+)", url)
    if m:
        return m.group(1)
    return "unknown"


_HITL_HTML_LINK = re.compile(
    r"""<a\s+[^>]*href=["']([^"']*/hitl/page/([A-Za-z0-9._-]+))[^"']*["'][^>]*>([^<]*)</a>""",
    re.IGNORECASE,
)
_HITL_TEXT_LINK = re.compile(
    r"""(https?://[^\s<>"']*/hitl/page/([A-Za-z0-9._-]+))""",
    re.IGNORECASE,
)


def parse_hitl_deeplinks(body: str) -> tuple[HitlDeeplink, ...]:
    """从邮件 HTML / plain text 中解析所有 /hitl/page/<token> 按钮。

    去重：同 token 仅记一次。
    """
    out: list[HitlDeeplink] = []
    seen: set[str] = set()

    for m in _HITL_HTML_LINK.finditer(body):
        url, token, label = m.group(1), m.group(2), m.group(3).strip()
        if token in seen:
            continue
        seen.add(token)
        out.append(
            HitlDeeplink(
                action=_infer_action(label, url),
                url=url,
                token=token,
                jti=extract_jti_from_jwt(token),
            )
        )

    for m in _HITL_TEXT_LINK.finditer(body):
        url, token = m.group(1), m.group(2)
        if token in seen:
            continue
        seen.add(token)
        out.append(
            HitlDeeplink(
                action=_infer_action("", url),
                url=url,
                token=token,
                jti=extract_jti_from_jwt(token),
            )
        )

    return tuple(out)


def parse_hitl_email(msg: dict) -> HitlEmailParsed:
    """把 MailHog message dict 解析成 HitlEmailParsed 结构。"""
    headers = msg.get("Content", {}).get("Headers", {})
    subject_raw = (headers.get("Subject", [""]) or [""])[0]
    subject = _decode_mime_header(subject_raw)
    to_raw = (headers.get("To", [""]) or [""])[0]
    to_addr = _decode_mime_header(to_raw)

    body = msg.get("Content", {}).get("Body", "")
    html, text = _split_mime_body(body)
    main_body = html or body

    return HitlEmailParsed(
        to=to_addr,
        subject=subject,
        html=html or body,
        text=text,
        is_reminder="[催办]" in subject,
        is_escalation="[升级]" in subject,
        is_supplement="[终止]" in subject or "已被" in subject,
        deeplinks=parse_hitl_deeplinks(main_body),
    )


async def get_latest_hitl_email(
    to_email: str,
    timeout: float = 15.0,
    client: httpx.AsyncClient | None = None,
) -> HitlEmailParsed:
    """组合：等邮件 → 解析为 HitlEmailParsed。"""
    raw = await get_latest_email(to_email, timeout=timeout, client=client)
    return parse_hitl_email(raw)
