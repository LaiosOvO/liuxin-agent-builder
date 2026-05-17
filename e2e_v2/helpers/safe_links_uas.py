"""Safe Links bot UA 常量 — CLAUDE.md §2.5 Pitfall 3 P0 防护回归测试用。

每个 chain mode E2E spec 必含这 4 个 UA 的 GET 测试，断言：
1. GET /hitl/page/<token> 返回 200
2. hitl_tokens.used_at 仍为 NULL（未消费）
3. 真实用户随后 POST 仍可成功

参考 Phase 3 03-03 BOT_UA_PATTERNS (后端 15 项) + Phase 3 03-10 spec 4 UA 选型。
本 E2E v2 用同 4 UA 保持端到端覆盖一致。
"""
from __future__ import annotations

# Outlook 安全链接预扫描器（最常见，企业 Outlook 安装即默认开）
OUTLOOK_AC_DETECTOR_UA = (
    "Mozilla/5.0 (compatible; Microsoft-Outlook-AC-Detector-Tool/1.0)"
)

# Microsoft Defender ATP Safe Links 扫描（O365 默认开）
MICROSOFT_DEFENDER_UA = "Mozilla/5.0 SafeLinksScanner/1.0"

# Slackbot 自动展开链接预览（Slack 频道贴邮件就触发）
SLACKBOT_UA = "Mozilla/5.0 (compatible; Slackbot-LinkExpanding 1.0)"

# Google 搜索爬虫（极不应该出现在 HITL 邮件中，但作为通用 bot 防御对比）
GOOGLEBOT_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"


BOT_UAS: tuple[tuple[str, str], ...] = (
    ("outlook_ac_detector", OUTLOOK_AC_DETECTOR_UA),
    ("microsoft_defender", MICROSOFT_DEFENDER_UA),
    ("slackbot", SLACKBOT_UA),
    ("googlebot", GOOGLEBOT_UA),
)
"""4 个 (name, ua) tuple — pytest parametrize 用，name 是测试 ID 后缀（便于失败定位）。"""


# 真实浏览器 UA（与 bot 对照）— 真实用户 GET 必须 200 + 签 cookie
REAL_USER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.6 Safari/605.1.15"
)
