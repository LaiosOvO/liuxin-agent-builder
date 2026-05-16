"""Safe Links Bot UA 检测 — Pitfall 3 P0 防护。

设计参考 docs/reading-dify-03-03-hitl-token-2026-05-17.md。

CLAUDE.md 2.5 契约：
- GET /hitl/page/<token> 检测到 bot UA → 返回静态 HTML，**不签 cookie / 不动 jti / 不写 viewed_at**
- 检测不到 bot UA → 正常签 30min session cookie 渲染表单
- "GET 即消费 jti" 是永不可接受的实现

CONTEXT.md §Safe Links bot UA：13 个核心 pattern + 通用 'safelinks' 前缀 + Outlook 真实 UA 'ac-detector-tool'。

参考实现：
- 03-CONTEXT.md §Token 4-action 设计 + 安全细节
- PITFALLS.md Pitfall 3（office365itpros.com Microsoft Defender Apr 2025）
"""
from __future__ import annotations

# CONTEXT.md §Safe Links bot UA 白名单（13 个核心 + 'safelinks' 通用前缀 + Outlook 真实 UA）
# 全部小写；is_bot_ua 通过 substring 匹配命中
BOT_UA_PATTERNS: tuple[str, ...] = (
    # ── 邮件安全扫描 ─────────────────────────────────────────────────────
    "microsoftdefender",       # MS Defender Safe Links（Microsoft 365 Atp）
    "outlook-safelinks",       # Outlook Safe Links（旧式 UA）
    "safelinks",               # 通用前缀（含上面两种变体）
    "ac-detector-tool",        # Outlook 真实 UA（CONTEXT §Specific Ideas）
    # ── IM / 社交平台 link preview 爬虫 ─────────────────────────────────
    "slackbot-linkexpanding",  # Slack 邮件 / 消息 link preview
    "twitterbot",              # Twitter 卡片爬虫
    "facebookexternalhit",     # Facebook OG 爬虫
    "linkedinbot",             # LinkedIn 分享卡片爬虫
    "whatsapp",                # WhatsApp link preview
    "telegrambot",             # Telegram 链接预览
    "discordbot",              # Discord embed 爬虫
    # ── 搜索引擎 / 通用爬虫 ─────────────────────────────────────────────
    "googlebot",               # Google 搜索 / Gmail 安全扫描
    "duckduckbot",             # DuckDuckGo
    "baiduspider",             # Baidu
    "bingbot",                 # Bing / Microsoft 搜索
)


def is_bot_ua(ua: str | None) -> bool:
    """检测 User-Agent 字符串是否为已知邮件扫描器 / link preview bot。

    Case-insensitive substring 匹配（任意 BOT_UA_PATTERNS 出现在 ua.lower() 即返回 True）。

    安全性保证：
    - None / 空字符串 → 返回 False（不当成 bot；让下游正常签 cookie）
    - 含 unicode 字符（中文 / emoji / 特殊符号）→ 不崩溃，按字符串处理
    - 短 UA / 超长 UA → 同样处理（无长度限制；防御性 lower() 是 O(n)）

    Args:
        ua: HTTP User-Agent header 原值（可能为 None / 空 / 任意 UTF-8 字符串）

    Returns:
        True 表示已知 bot；False 表示未识别或空。

    Example:
        >>> is_bot_ua("Mozilla/5.0 (compatible; AC-Detector-Tool/1.0; +safelinks.protection.outlook.com)")
        True
        >>> is_bot_ua("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko)")
        False
        >>> is_bot_ua(None)
        False
        >>> is_bot_ua("")
        False
    """
    if not ua:
        return False
    ua_lower = ua.lower()
    return any(pattern in ua_lower for pattern in BOT_UA_PATTERNS)
