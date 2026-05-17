"""IMCredentialsManager .env 加载 + 启动校验单元测试（Plan 04-05 Task 2）。

测试覆盖（≥ 8 用例）：
1. test_load_with_feishu_env_creates_credentials：飞书全字段配置后 feishu() 返回正确 dataclass
2. test_load_without_feishu_env_returns_none_until_getter_raises：未配置时 getter 抛 RuntimeError
3. test_load_5_providers_independently：每家可独立配，互不影响
4. test_credentials_are_frozen：所有 5 个 dataclass(frozen=True) 不可修改
5. test_load_warns_on_missing：caplog 看到 warning 提示哪些 provider 未配
6. test_has_provider_returns_correct_bool：has_* 方法精确反映配置状态
7. test_list_configured_returns_sorted_names：list_configured 排序
8. test_partial_wecom_env_does_not_create_credentials：企微 3 字段缺 1 → 不创建
9. test_whitespace_in_env_is_stripped：env 变量两端空白被 strip
10. test_empty_string_env_treated_as_missing：FEISHU_APP_ID="" → 视为未配置
11. test_feishu_credentials_dataclass_equality：相同字段 dataclass 相等

CLAUDE.md 2.2 单元测试：纯 Python + monkeypatch env，无 DB 依赖。
"""
from __future__ import annotations

import logging

import pytest

from app.agent_builder.core.im_credentials import (
    DingTalkCredentials,
    FeishuCredentials,
    IMCredentialsManager,
    MattermostCredentials,
    SlackCredentials,
    WebhookCredentials,
    WeComCredentials,
)


# ── Fixture：清理 env 变量 ───────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_im_env(monkeypatch):
    """每个测试前清空所有 IM 环境变量（隔离）。"""
    for var in [
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "WECOM_CORP_ID",
        "WECOM_AGENT_ID",
        "WECOM_SECRET",
        "DINGTALK_APP_KEY",
        "DINGTALK_APP_SECRET",
        "SLACK_BOT_TOKEN",
        "MATTERMOST_URL",
        "MATTERMOST_BOT_TOKEN",
        "WEBHOOK_DELIVERY_URL",  # Plan 04-09 NOTI-07
    ]:
        monkeypatch.delenv(var, raising=False)
    yield


# ── 1. 单家 provider 加载 ────────────────────────────────────────────────────


def test_load_with_feishu_env_creates_credentials(monkeypatch):
    """飞书全字段配置后 feishu() 返回正确 dataclass。"""
    monkeypatch.setenv("FEISHU_APP_ID", "cli_a1b2c3d4")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret_xyz123")

    mgr = IMCredentialsManager()
    creds = mgr.feishu()

    assert isinstance(creds, FeishuCredentials)
    assert creds.app_id == "cli_a1b2c3d4"
    assert creds.app_secret == "secret_xyz123"


def test_load_without_feishu_env_returns_none_until_getter_raises():
    """未配置飞书时 feishu() 抛 RuntimeError + 提示需要的环境变量。"""
    mgr = IMCredentialsManager()

    assert mgr.has_feishu() is False

    with pytest.raises(RuntimeError) as exc_info:
        mgr.feishu()
    assert "FEISHU_APP_ID" in str(exc_info.value)
    assert "FEISHU_APP_SECRET" in str(exc_info.value)


# ── 2. 5 家独立加载 ──────────────────────────────────────────────────────────


def test_load_5_providers_independently(monkeypatch):
    """每家可独立配，互不影响：只配飞书 + Slack，其他抛 RuntimeError。"""
    monkeypatch.setenv("FEISHU_APP_ID", "feishu_id")
    monkeypatch.setenv("FEISHU_APP_SECRET", "feishu_secret")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")

    mgr = IMCredentialsManager()

    # 已配置
    assert mgr.has_feishu() is True
    assert mgr.has_slack() is True
    assert mgr.feishu().app_id == "feishu_id"
    assert mgr.slack().bot_token == "xoxb-test-token"

    # 未配置
    assert mgr.has_wecom() is False
    assert mgr.has_dingtalk() is False
    assert mgr.has_mattermost() is False

    for getter, env_var in [
        (mgr.wecom, "WECOM_CORP_ID"),
        (mgr.dingtalk, "DINGTALK_APP_KEY"),
        (mgr.mattermost, "MATTERMOST_URL"),
    ]:
        with pytest.raises(RuntimeError) as exc_info:
            getter()
        assert env_var in str(exc_info.value)


# ── 3. immutability ─────────────────────────────────────────────────────────


def test_credentials_are_frozen(monkeypatch):
    """所有 5 个 dataclass(frozen=True) 不可修改。"""
    monkeypatch.setenv("FEISHU_APP_ID", "a")
    monkeypatch.setenv("FEISHU_APP_SECRET", "b")
    monkeypatch.setenv("WECOM_CORP_ID", "c")
    monkeypatch.setenv("WECOM_AGENT_ID", "d")
    monkeypatch.setenv("WECOM_SECRET", "e")
    monkeypatch.setenv("DINGTALK_APP_KEY", "f")
    monkeypatch.setenv("DINGTALK_APP_SECRET", "g")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "h")
    monkeypatch.setenv("MATTERMOST_URL", "https://mm.example.com")
    monkeypatch.setenv("MATTERMOST_BOT_TOKEN", "i")

    mgr = IMCredentialsManager()

    for creds in [
        mgr.feishu(),
        mgr.wecom(),
        mgr.dingtalk(),
        mgr.slack(),
        mgr.mattermost(),
    ]:
        # frozen dataclass 修改任意字段抛 FrozenInstanceError
        with pytest.raises(Exception):
            # 取第一个字段名进行赋值尝试
            field_name = list(creds.__dataclass_fields__.keys())[0]
            object.__setattr__(creds, field_name, "evil")
            # object.__setattr__ 会绕过 frozen — 使用普通赋值更直接
            setattr(creds, field_name, "evil2")


# ── 4. caplog 看到 warning ────────────────────────────────────────────────


def test_load_warns_on_missing(caplog):
    """未配置任何 provider → 6 条 warning（Plan 04-09 新增 webhook）。"""
    caplog.set_level(logging.WARNING, logger="app.agent_builder.core.im_credentials")
    IMCredentialsManager()

    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    # 6 家全未配置 → 至少 6 条 warning
    assert any("飞书" in w or "FEISHU" in w for w in warnings)
    assert any("企微" in w or "WECOM" in w for w in warnings)
    assert any("钉钉" in w or "DINGTALK" in w for w in warnings)
    assert any("Slack" in w or "SLACK" in w for w in warnings)
    assert any("Mattermost" in w or "MATTERMOST" in w for w in warnings)
    assert any("Webhook" in w or "WEBHOOK" in w for w in warnings)


def test_load_no_warning_when_all_configured(monkeypatch, caplog):
    """6 家全配置 → 无 warning。"""
    monkeypatch.setenv("FEISHU_APP_ID", "a")
    monkeypatch.setenv("FEISHU_APP_SECRET", "b")
    monkeypatch.setenv("WECOM_CORP_ID", "c")
    monkeypatch.setenv("WECOM_AGENT_ID", "d")
    monkeypatch.setenv("WECOM_SECRET", "e")
    monkeypatch.setenv("DINGTALK_APP_KEY", "f")
    monkeypatch.setenv("DINGTALK_APP_SECRET", "g")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "h")
    monkeypatch.setenv("MATTERMOST_URL", "https://mm.example.com")
    monkeypatch.setenv("MATTERMOST_BOT_TOKEN", "i")
    monkeypatch.setenv("WEBHOOK_DELIVERY_URL", "https://example.com/hook")

    caplog.set_level(logging.WARNING, logger="app.agent_builder.core.im_credentials")
    IMCredentialsManager()
    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == []


# ── 5. has_* + list_configured ──────────────────────────────────────────────


def test_has_provider_returns_correct_bool(monkeypatch):
    """has_* 方法精确反映配置状态。"""
    monkeypatch.setenv("DINGTALK_APP_KEY", "k")
    monkeypatch.setenv("DINGTALK_APP_SECRET", "s")

    mgr = IMCredentialsManager()
    assert mgr.has_dingtalk() is True
    assert mgr.has_feishu() is False
    assert mgr.has_wecom() is False
    assert mgr.has_slack() is False
    assert mgr.has_mattermost() is False
    assert mgr.has_webhook() is False


def test_list_configured_returns_sorted_names(monkeypatch):
    """list_configured 返回 sorted 已配置 name 列表。"""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "x")
    monkeypatch.setenv("FEISHU_APP_ID", "a")
    monkeypatch.setenv("FEISHU_APP_SECRET", "b")
    monkeypatch.setenv("WECOM_CORP_ID", "c")
    monkeypatch.setenv("WECOM_AGENT_ID", "d")
    monkeypatch.setenv("WECOM_SECRET", "e")

    mgr = IMCredentialsManager()
    # sorted（feishu / slack / wecom）
    assert mgr.list_configured() == ["feishu", "slack", "wecom"]


def test_list_configured_empty_when_none(caplog):
    """list_configured 空配置返回空列表。"""
    caplog.set_level(logging.WARNING)
    mgr = IMCredentialsManager()
    assert mgr.list_configured() == []


# ── 6. 部分字段缺失 ─────────────────────────────────────────────────────────


def test_partial_wecom_env_does_not_create_credentials(monkeypatch, caplog):
    """企微 3 字段缺 1 → 不创建凭据（has_wecom False）。"""
    monkeypatch.setenv("WECOM_CORP_ID", "corp")
    monkeypatch.setenv("WECOM_AGENT_ID", "agent")
    # 故意不设 WECOM_SECRET

    caplog.set_level(logging.WARNING, logger="app.agent_builder.core.im_credentials")
    mgr = IMCredentialsManager()
    assert mgr.has_wecom() is False
    with pytest.raises(RuntimeError):
        mgr.wecom()


def test_partial_mattermost_env_does_not_create_credentials(monkeypatch):
    """Mattermost 缺 BOT_TOKEN → 不创建。"""
    monkeypatch.setenv("MATTERMOST_URL", "https://mm.example.com")
    # 不设 MATTERMOST_BOT_TOKEN

    mgr = IMCredentialsManager()
    assert mgr.has_mattermost() is False


# ── 7. env 处理：whitespace / empty string ──────────────────────────────────


def test_whitespace_in_env_is_stripped(monkeypatch):
    """env 变量两端空白被 strip — 防止 .env 文件意外引号 / 空格。"""
    monkeypatch.setenv("FEISHU_APP_ID", "  cli_xyz  ")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret_padded   ")

    mgr = IMCredentialsManager()
    creds = mgr.feishu()
    assert creds.app_id == "cli_xyz"
    assert creds.app_secret == "secret_padded"


def test_empty_string_env_treated_as_missing(monkeypatch):
    """FEISHU_APP_ID="" 视为未配置（strip 后空字符串等于 None）。"""
    monkeypatch.setenv("FEISHU_APP_ID", "")
    monkeypatch.setenv("FEISHU_APP_SECRET", "   ")  # 仅空白

    mgr = IMCredentialsManager()
    assert mgr.has_feishu() is False
    with pytest.raises(RuntimeError):
        mgr.feishu()


# ── 8. dataclass 相等性 ─────────────────────────────────────────────────────


def test_feishu_credentials_dataclass_equality():
    """FeishuCredentials 相同字段相等（dataclass __eq__）。"""
    a = FeishuCredentials(app_id="x", app_secret="y")
    b = FeishuCredentials(app_id="x", app_secret="y")
    c = FeishuCredentials(app_id="x", app_secret="z")

    assert a == b
    assert a != c


def test_all_5_credentials_have_distinct_types():
    """5 家 dataclass 是独立类（类型隔离）。"""
    types = {
        FeishuCredentials,
        WeComCredentials,
        DingTalkCredentials,
        SlackCredentials,
        MattermostCredentials,
    }
    assert len(types) == 5
