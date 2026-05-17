"""企微卡片构造（Plan 04-07）— wechatpy 1.8.18 + Bot Webhook fallback。

设计参考 docs/reading-im-sdk-04-07-wecom-2026-05-17.md：

Spike 结论：wechatpy 1.8.18 **没有** template_card / button_interaction API；
最稳定且能放置多个可点击链接的入口是 **markdown 消息**（4 个 [text](url) 链接）。

两路径共享同一 markdown 内容（DRY）：
- App message envelope：`{"msgtype": "markdown", "markdown": {"content": "..."}}`
- Bot Webhook envelope：完全一致（企微 API 设计如此）

CLAUDE.md immutability：
- 输入 HitlCardPayload 是 frozen dataclass（不可修改）
- 返回 dict 每次新建（不缓存、不共享）

CLAUDE.md security：
- 用户文本字段（flow_title / applicant_name / description）做 markdown 特殊字符
  转义（防注入：`[` `]` `` ` `` 等）
- 输出 content ≤ 2048 字节（企微 API 限制）

CLAUDE.md 2.7 Dify 参考：Dify email_delivery 用 Jinja 模板；
企微 markdown 内容简单 + 风险点是注入而非模板复杂度 → 不引入 Jinja，纯字符串拼接更可控。
"""
from __future__ import annotations

from typing import Any

from app.agent_builder.notification.cards.base import HitlCardPayload

# ── 常量 ─────────────────────────────────────────────────────────────────────

WECOM_MSGTYPE_MARKDOWN = "markdown"
"""企微消息类型常量 — app message / bot webhook 共用。"""

WECOM_MARKDOWN_MAX_BYTES = 2048
"""企微 markdown content 上限（utf-8 bytes）— 超出 API 直接拒绝。"""

# 标准 4 action 中文映射
_ACTION_LABELS: dict[str, str] = {
    "approve": "同意",
    "return": "退回",
    "reject": "拒绝",
    "detail": "详情",
    "submit": "提交",
    "delegate": "委托",
}


# ── 工具函数 ──────────────────────────────────────────────────────────────────


def _label_for(action: str) -> str:
    """action → 中文标签；未知 action 返回原始 action 名（不抛错）。"""
    return _ACTION_LABELS.get(action, action)


def _escape_markdown_text(text: str) -> str:
    """转义企微 markdown 特殊字符防注入。

    企微 markdown 子集敏感字符：
    - `[` `]`：会被解析为链接 → 转义为 `\\[` `\\]`
    - `` ` ``：会被解析为内联代码 → 转义为 `\\``
    - `*` `_`：粗体 / 斜体 → 转义为 `\\*` `\\_`
    - `<` `>`：可能被解析为 HTML tag（企微支持 `<font>`）→ 转义为 `&lt;` `&gt;`
      （不用 `\\<` 因为企微 markdown 不识别反斜杠转义 html，但 `&lt;` 是 safe 字符）

    Args:
        text: 用户输入文本

    Returns:
        转义后文本
    """
    if not text:
        return text
    # 顺序重要：先转义 `\` 防止双重转义其他字符（本场景不需要，但保持习惯）
    # 1. 方括号（最关键 — 防链接注入）
    out = text.replace("[", "\\[").replace("]", "\\]")
    # 2. 反引号（防代码块逃逸）
    out = out.replace("`", "\\`")
    # 3. 星号、下划线（防粗体/斜体破坏视觉）
    out = out.replace("*", "\\*").replace("_", "\\_")
    # 4. HTML 角括号（防 `<script>` 等）
    out = out.replace("<", "&lt;").replace(">", "&gt;")
    return out


# ── 内容生成器（共享）─────────────────────────────────────────────────────────


def build_wecom_markdown_content(payload: HitlCardPayload) -> str:
    """构造企微 markdown 内容字符串 — app message / bot webhook 共用。

    输出格式（示例）：

        ### 审批待办：员工入职流程
        **节点**：HR 审批
        **申请人**：张三
        **审批人**：李经理
        **截止时间**：2026-05-18T10:00:00Z
        **详情**：新员工入职审批，请决策

        **请决策**：
        - [同意](https://example.com/approve/jwt1)
        - [退回](https://example.com/return/jwt1)
        - [拒绝](https://example.com/reject/jwt1)
        - [详情](https://example.com/detail/jwt1)

    Args:
        payload: HITL 卡片载荷（frozen dataclass）

    Returns:
        markdown 字符串（utf-8 ≤ 2048 bytes 自动截断 description 字段保证总长度合规）
    """
    # 用户文本字段做转义
    flow_title = _escape_markdown_text(payload.flow_title)
    node_title = _escape_markdown_text(payload.node_title)
    applicant_name = _escape_markdown_text(payload.applicant_name)
    actor_name = _escape_markdown_text(payload.actor_name)
    description = _escape_markdown_text(payload.description)
    # deadline_at 是 ISO 字符串，不含 markdown 特殊字符；不转义保持原貌

    # action 链接行（url 不做转义 — 已是受控产生的 deeplink；
    # 若 url 含 `)` 会破坏 markdown 链接 — 现实 jwt deeplink 不含括号）
    link_lines: list[str] = []
    for dl in payload.deeplinks:
        action = dl.get("action", "")
        url = dl.get("url", "")
        if not url:
            continue
        label = _label_for(action)
        link_lines.append(f"- [{label}]({url})")

    lines = [
        f"### 审批待办：{flow_title}",
        f"**节点**：{node_title}",
        f"**申请人**：{applicant_name}",
        f"**审批人**：{actor_name}",
        f"**截止时间**：{payload.deadline_at}",
        f"**详情**：{description}",
        "",
        "**请决策**：",
        *link_lines,
    ]
    content = "\n".join(lines)

    # 边界保护：≤ 2048 bytes（CLAUDE.md security 边界校验）
    encoded = content.encode("utf-8")
    if len(encoded) > WECOM_MARKDOWN_MAX_BYTES:
        # 截断 description 字段（其他都是结构化字段，截断会破坏卡片）
        # 简单策略：从尾部截断整体字符串，留 `...(已截断)` 标记
        # 注意：utf-8 截断需在字符边界对齐避免 invalid sequence
        suffix = "\n\n... (内容超长已截断)"
        suffix_bytes = suffix.encode("utf-8")
        safe_budget = WECOM_MARKDOWN_MAX_BYTES - len(suffix_bytes)
        truncated = encoded[:safe_budget]
        # 找最后一个完整字符边界（utf-8 head byte 不以 10xxxxxx 开头）
        while truncated and (truncated[-1] & 0xC0) == 0x80:
            truncated = truncated[:-1]
        content = truncated.decode("utf-8", errors="ignore") + suffix
    return content


# ── Envelope 构造器 ──────────────────────────────────────────────────────────


def build_wecom_app_message(payload: HitlCardPayload) -> dict[str, Any]:
    """构造企微 **应用消息** envelope（wechatpy.message.send 用）。

    返回 dict 直接传给 `client.message.send(agent_id, user_ids, msg=...)`
    （不含 agent_id / touser — 那些是 SDK 调用方参数）。

    Args:
        payload: HITL 卡片载荷

    Returns:
        ``{"msgtype": "markdown", "markdown": {"content": "..."}}``
    """
    return {
        "msgtype": WECOM_MSGTYPE_MARKDOWN,
        "markdown": {"content": build_wecom_markdown_content(payload)},
    }


def build_wecom_webhook_markdown(payload: HitlCardPayload) -> dict[str, Any]:
    """构造企微 **Bot Webhook** envelope（POST body 用）。

    使用方式：
        POST https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={KEY}
        body = build_wecom_webhook_markdown(payload)

    Args:
        payload: HITL 卡片载荷

    Returns:
        ``{"msgtype": "markdown", "markdown": {"content": "..."}}``
        （envelope 与 app_message 一致 — 企微 API 设计如此）
    """
    return {
        "msgtype": WECOM_MSGTYPE_MARKDOWN,
        "markdown": {"content": build_wecom_markdown_content(payload)},
    }


# ── 补发文本（"已被 X 处理"）─────────────────────────────────────────────────


def build_wecom_supplement_text(*, who_processed: str, action: str) -> str:
    """构造"已被 X 处理"补充文本 — update_card 不可用时的兜底。

    Args:
        who_processed: 已处理人姓名
        action: 处理 action（approve / reject / return / ...）

    Returns:
        ≤ 200 字符的纯文本
    """
    who = _escape_markdown_text(who_processed)
    label = _label_for(action)
    text = f"流程已被 {who} {label}，本卡片已失效。"
    if len(text) > 200:
        text = text[:197] + "..."
    return text
