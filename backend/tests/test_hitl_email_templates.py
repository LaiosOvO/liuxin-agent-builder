"""HITL 邮件模板渲染单元测试（Plan 03-04 Task 1）。

测试 5 用例（PLAN.md Task 1 验收）：
1. test_hitl_decision_html_renders_3_buttons：3 deeplinks → HTML 含 3 个 <a href>
2. test_hitl_decision_html_button_colors：submit/approve 绿、return 黄、reject 红
3. test_hitl_decision_html_escapes_user_data：description XSS 输入被 escape
4. test_hitl_decision_text_contains_all_urls：deeplink 全部在明文版本中
5. test_hitl_reminder_subject_prefix：催办模板含 [催办] banner 标识

无 DB / 无 SMTP 依赖（纯 Jinja2 单元测试）。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

# 模板目录（与 email_service.py 一致）
_TEMPLATE_DIR = (
    Path(__file__).resolve().parent.parent / "app" / "templates" / "email"
)


@pytest.fixture(scope="module")
def jinja_env() -> Environment:
    """Jinja2 Environment（autoescape=html 防 XSS）。"""
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )


@pytest.fixture
def sample_context() -> dict:
    """3 deeplink 的标准 context（submit phase）。"""
    return {
        "flow_title": "员工入职流程",
        "node_title": "HR 审批",
        "applicant_name": "张三",
        "actor_name": "李四",
        "deadline_at": "2026-05-18 14:00:00",
        "description": "请审批新员工入职申请",
        "deeplinks": [
            {"action": "submit", "url": "http://test.local/hitl/page/jwt-token-1"},
            {"action": "return", "url": "http://test.local/hitl/page/jwt-token-2"},
            {"action": "reject", "url": "http://test.local/hitl/page/jwt-token-3"},
        ],
    }


# ── 5 个测试用例 ─────────────────────────────────────────────────────────────


def test_hitl_decision_html_renders_3_buttons(jinja_env, sample_context):
    """3 deeplinks 渲染出 3 个 <a href> 按钮。"""
    template = jinja_env.get_template("hitl_decision.html")
    html = template.render(**sample_context)

    # 3 个按钮独立 URL（重复 2 次：按钮区 + 备用链接区）
    assert html.count("http://test.local/hitl/page/jwt-token-1") >= 1
    assert html.count("http://test.local/hitl/page/jwt-token-2") >= 1
    assert html.count("http://test.local/hitl/page/jwt-token-3") >= 1

    # 3 个文案按钮（提交 / 退回 / 拒绝）
    assert "提交" in html
    assert "退回" in html
    assert "拒绝" in html


def test_hitl_decision_html_button_colors(jinja_env, sample_context):
    """按 action 着色：submit/approve 绿色 (#10b981)、return 黄色 (#f59e0b)、reject 红色 (#ef4444)。"""
    template = jinja_env.get_template("hitl_decision.html")
    html = template.render(**sample_context)

    # 各色至少出现一次（用 hex 颜色作为锚点）
    assert "#10b981" in html, "submit 绿色按钮缺失"
    assert "#f59e0b" in html, "return 黄色按钮缺失"
    assert "#ef4444" in html, "reject 红色按钮缺失"

    # approve 也用绿色（review phase 替代 submit）
    context_approve = {**sample_context}
    context_approve["deeplinks"] = [
        {"action": "approve", "url": "http://test.local/hitl/page/approve-token"}
    ]
    html_approve = template.render(**context_approve)
    assert "#10b981" in html_approve
    assert "通过" in html_approve


def test_hitl_decision_html_escapes_user_data(jinja_env, sample_context):
    """description 含 <script> 等 HTML 注入字符必须被 escape（autoescape 防 XSS）。"""
    malicious_context = {
        **sample_context,
        "description": "<script>alert('XSS')</script>",
        "applicant_name": "<img src=x onerror=alert(1)>",
        "flow_title": "Title & <b>hack</b>",
    }
    template = jinja_env.get_template("hitl_decision.html")
    html = template.render(**malicious_context)

    # 原始注入内容不应出现
    assert "<script>alert" not in html, "XSS payload 未被 escape！"
    assert "<img src=x onerror=" not in html, "img onerror 未被 escape！"

    # escape 后的字符出现（&lt; / &gt; / &amp; / &#39; 等任一）
    assert "&lt;script&gt;" in html or "&lt;script" in html
    assert "&lt;img" in html or "&lt;img " in html
    # & 在 'Title & <b>hack</b>' 被 escape 成 &amp;
    assert "&amp;" in html


def test_hitl_decision_text_contains_all_urls(jinja_env, sample_context):
    """明文 fallback 在底部列出所有 deeplink URL。"""
    # 注意：text 模板不开 autoescape（按 select_autoescape(['html']) 规则，.txt 不在列表内）
    template = jinja_env.get_template("hitl_decision_text.txt")
    text = template.render(**sample_context)

    # 3 deeplink URL 全部出现
    assert "http://test.local/hitl/page/jwt-token-1" in text
    assert "http://test.local/hitl/page/jwt-token-2" in text
    assert "http://test.local/hitl/page/jwt-token-3" in text

    # 标题 / 上下文字段渲染（明文不 escape）
    assert "员工入职流程" in text
    assert "HR 审批" in text
    assert "张三" in text  # applicant
    assert "李四" in text  # actor
    assert "2026-05-18 14:00:00" in text
    assert "请审批新员工入职申请" in text

    # action label
    assert "[提交]" in text
    assert "[退回]" in text
    assert "[拒绝]" in text


def test_hitl_reminder_subject_prefix(jinja_env, sample_context):
    """催办模板含 [催办] 标识 + 标题反映催办场景。"""
    template = jinja_env.get_template("hitl_reminder.html")
    html = template.render(**sample_context)

    # [催办] 出现至少 1 次（banner + title 任一）
    assert "[催办]" in html, "催办模板未含 [催办] 标识"

    # 红色 banner 颜色
    assert "#dc2626" in html, "催办红色 banner 缺失"

    # 按钮区仍然渲染 3 deeplink（结构与 decision 一致）
    assert "http://test.local/hitl/page/jwt-token-1" in html
    assert "http://test.local/hitl/page/jwt-token-2" in html
    assert "http://test.local/hitl/page/jwt-token-3" in html

    # 提示文案包含"超期"语义
    assert "超期" in html or "尽快" in html or "催办" in html
