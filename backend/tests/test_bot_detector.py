"""bot_detector.is_bot_ua 单元测试（10+ 用例）。

覆盖范围（plan 03-03 must_haves）：
- 真实 UA 字符串 → 命中（Outlook Safe Links / MS Defender / Slackbot / Googlebot）
- 真实用户 UA → 不误判（Chrome / Safari iPhone）
- 鲁棒性：None / 空 / unicode 字符不崩溃
- 大小写混合匹配
- BOT_UA_PATTERNS 中每个 pattern 都有对应测试

注意：本测试**不依赖** Postgres / Redis / FastAPI，是纯函数 单元测试。
"""
from __future__ import annotations

import pytest

from app.agent_builder.security.bot_detector import BOT_UA_PATTERNS, is_bot_ua


# ── 真实 Bot UA 测试 ─────────────────────────────────────────────────────────────


class TestRealBotUserAgents:
    """覆盖 CONTEXT.md §Specific Ideas + §Safe Links bot UA 列出的真实 UA 字符串。"""

    def test_outlook_safelinks_real_ua_detected(self):
        """Outlook Safe Links 真实 UA（CONTEXT.md §Specific Ideas）必须返回 True。"""
        ua = (
            "Mozilla/5.0 (compatible; AC-Detector-Tool/1.0; "
            "+safelinks.protection.outlook.com)"
        )
        assert is_bot_ua(ua) is True

    def test_microsoft_defender_ua_detected(self):
        """Microsoft Defender Safe Links UA。"""
        ua = "Mozilla/5.0 (compatible; MicrosoftDefender/1.0)"
        assert is_bot_ua(ua) is True

    def test_slackbot_linkexpanding_ua_detected(self):
        """Slackbot link expanding 爬虫。"""
        ua = "Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)"
        assert is_bot_ua(ua) is True

    def test_googlebot_detected(self):
        """Googlebot 爬虫 UA。"""
        ua = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
        assert is_bot_ua(ua) is True


# ── 真实用户 UA 测试（不应误判为 bot） ────────────────────────────────────────────


class TestRealUserAgentsNotBot:
    """真实用户浏览器 UA — 必须返回 False。"""

    def test_chrome_real_user_ua_not_bot(self):
        """Chrome desktop 真实 UA → False。"""
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/119.0.0.0 Safari/537.36"
        )
        assert is_bot_ua(ua) is False

    def test_safari_iphone_real_user_not_bot(self):
        """Safari iPhone 移动端真实 UA → False。"""
        ua = (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
            "Mobile/15E148 Safari/604.1"
        )
        assert is_bot_ua(ua) is False

    def test_firefox_linux_real_user_not_bot(self):
        """Firefox Linux 真实用户 UA → False。"""
        ua = "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
        assert is_bot_ua(ua) is False


# ── 边界 / 鲁棒性测试 ────────────────────────────────────────────────────────────


class TestRobustness:
    """边界场景：None / 空 / unicode / case-insensitive。"""

    def test_empty_ua_returns_false(self):
        """空字符串 → False。"""
        assert is_bot_ua("") is False

    def test_none_ua_returns_false(self):
        """None → False（不抛 AttributeError）。"""
        assert is_bot_ua(None) is False

    def test_case_insensitive_matching(self):
        """大小写混合命中。"""
        # 大写
        assert is_bot_ua("GOOGLEBOT/2.1") is True
        # 大小写混合
        assert is_bot_ua("Mozilla/5.0 GoOgLeBoT/2.1") is True
        # 全小写
        assert is_bot_ua("mozilla googlebot/2.1") is True

    def test_unicode_ua_no_crash(self):
        """UA 含中文 / emoji / 特殊 unicode 字符不崩溃。"""
        # 含中文
        assert is_bot_ua("奇怪的浏览器/1.0 中文版") is False
        # 含 emoji
        assert is_bot_ua("Mozilla/5.0 🚀 (Custom; +https://example.com)") is False
        # 含中文 + bot pattern → 仍命中
        assert is_bot_ua("Mozilla/5.0 googlebot/2.1 中文标识") is True
        # 全 unicode 字符
        assert is_bot_ua("浏览器名称") is False

    def test_whitespace_only_ua_returns_false(self):
        """仅空格的 UA → False（被 `if not ua` 短路 — 空格 truthy 但 lower() 不含 pattern）。

        注：" " 是 truthy（非空），所以会进入 lower 匹配；
        没 bot pattern 命中即返回 False。
        """
        assert is_bot_ua("   ") is False

    def test_very_long_ua_does_not_crash(self):
        """超长 UA（10K+ 字符）不崩溃。"""
        long_ua = "Mozilla/5.0 " + ("x" * 10000)
        assert is_bot_ua(long_ua) is False  # 不含 bot pattern
        long_ua_with_bot = ("x" * 5000) + " googlebot/2.1 " + ("y" * 5000)
        assert is_bot_ua(long_ua_with_bot) is True  # 含 pattern


# ── BOT_UA_PATTERNS 全覆盖参数化测试 ─────────────────────────────────────────────


class TestAllPatternsCovered:
    """确保 BOT_UA_PATTERNS 中**每个 pattern**都有对应测试（防新增 pattern 漏测）。"""

    @pytest.mark.parametrize("pattern", BOT_UA_PATTERNS)
    def test_each_pattern_in_BOT_UA_PATTERNS_is_detected(self, pattern):
        """parametrize 跑 BOT_UA_PATTERNS 中的每一个 pattern，验证 substring 匹配生效。"""
        # 构造一个最简 UA：Mozilla 前缀 + pattern + 后缀（保留 pattern 原样大小写）
        ua = f"Mozilla/5.0 (compatible; {pattern}/1.0; +https://example.com/bot)"
        assert is_bot_ua(ua) is True, f"pattern '{pattern}' 应被 is_bot_ua 识别"

    def test_BOT_UA_PATTERNS_count_at_least_13(self):
        """BOT_UA_PATTERNS 至少 13 项（CONTEXT.md §Safe Links bot UA 列表）。"""
        # CONTEXT.md 显式列出 13 个核心 pattern；本实现额外加 'safelinks' 通用前缀
        # 和 'ac-detector-tool'（§Specific Ideas）
        assert len(BOT_UA_PATTERNS) >= 13

    def test_BOT_UA_PATTERNS_all_lowercase(self):
        """常量定义必须全小写（is_bot_ua 用 ua.lower() 匹配；大写 pattern 永不命中）。"""
        for pattern in BOT_UA_PATTERNS:
            assert pattern == pattern.lower(), f"pattern '{pattern}' 包含大写字母"

    def test_BOT_UA_PATTERNS_no_duplicates(self):
        """去重 — 不能存在重复 pattern（影响性能 + 暗示常量定义错误）。"""
        assert len(BOT_UA_PATTERNS) == len(set(BOT_UA_PATTERNS))
