"""HITL 决策页 — browser-harness 操作模板 (仅 #5 / #6 spec 用)。

用 heredoc 注入 browser-harness 控制浏览器：
- 访问决策页 URL（含 token）
- 等待 React 渲染
- 抓页面信息（URL / 标题 / 是否含审批文案）
- （#6）点击 delegate 按钮 + 填表

设计参考 e2e/pages/hitl.page.ts（Playwright），改用 browser-harness CDP 重写。
"""
from __future__ import annotations

from dataclasses import dataclass

from e2e_v2.helpers.browser_session import (
    BrowserHarnessResult,
    run_browser_harness_script,
)


@dataclass(frozen=True)
class DecisionPageVerification:
    """决策页验证结果（不可变快照）。"""

    final_url: str
    title: str
    contains_audit_button: bool
    contains_reject_button: bool
    contains_delegate_button: bool
    raw_stdout: str


def visit_decision_page_and_verify(
    *,
    deeplink_url: str,
    bu_name: str = "spec_decision_page",
    timeout: float = 30.0,
) -> DecisionPageVerification:
    """打开 deeplink → 等待加载 → 抓验证关键字（同意 / 拒绝 / 委托按钮）。

    Returns:
        DecisionPageVerification 含页面状态 + raw stdout（调试用）
    """
    script = f"""
new_tab({deeplink_url!r})
wait_for_load(timeout=10)

# 决策页是 SPA，wait_for_load 后还需等 hydration
import time
time.sleep(2.0)

info = page_info()
print(f"FINAL_URL={{info.get('url','')}}")
print(f"TITLE={{info.get('title','')}}")

# 抓页面文本（验证按钮存在）
text = js("document.body ? document.body.innerText : ''")
text = text or ''
print(f"HAS_APPROVE={{'通过' in text or 'approve' in text.lower()}}")
print(f"HAS_REJECT={{'拒绝' in text or 'reject' in text.lower()}}")
print(f"HAS_DELEGATE={{'委托' in text or 'delegate' in text.lower()}}")
"""

    result = run_browser_harness_script(script, name=bu_name, timeout=timeout)

    if result.returncode != 0:
        raise RuntimeError(
            f"browser-harness 子进程失败 returncode={result.returncode}\n"
            f"stderr: {result.stderr[:500]}"
        )

    lines = result.stdout.splitlines()

    def _extract(prefix: str) -> str:
        for line in lines:
            if line.startswith(prefix):
                return line[len(prefix):]
        return ""

    return DecisionPageVerification(
        final_url=_extract("FINAL_URL="),
        title=_extract("TITLE="),
        contains_audit_button=_extract("HAS_APPROVE=").strip() == "True",
        contains_reject_button=_extract("HAS_REJECT=").strip() == "True",
        contains_delegate_button=_extract("HAS_DELEGATE=").strip() == "True",
        raw_stdout=result.stdout,
    )


def click_delegate_and_submit(
    *,
    deeplink_url: str,
    to_email: str,
    reason: str = "出差期间委托",
    bu_name: str = "spec_delegate",
    timeout: float = 60.0,
) -> BrowserHarnessResult:
    """打开决策页 → 点 delegate 按钮 → 填表 → 提交。

    Returns:
        BrowserHarnessResult（raw stdout 含 RESULT_STATUS=200/422/409 等）
    """
    script = f"""
new_tab({deeplink_url!r})
wait_for_load(timeout=10)

import time
time.sleep(2.0)

# 点 delegate 按钮（兼容文案 "委托" / "delegate"）
clicked = js('''
const btns = Array.from(document.querySelectorAll('button'));
const target = btns.find(b => b.textContent.includes('委托') || b.textContent.toLowerCase().includes('delegate'));
if (target) {{ target.click(); return true; }}
return false;
''')
print(f"DELEGATE_BTN_CLICKED={{clicked}}")

if clicked:
    time.sleep(1.0)
    # 填表 — to_email 字段
    if wait_for_element('input[name=\"to_email\"]', timeout=5):
        fill_input('input[name=\"to_email\"]', {to_email!r})
        print("TO_EMAIL_FILLED=True")
    # reason 字段
    if wait_for_element('textarea[name=\"reason\"]', timeout=2):
        fill_input('textarea[name=\"reason\"]', {reason!r})
        print("REASON_FILLED=True")

    # 提交（兼容文案）
    submitted = js('''
const btns = Array.from(document.querySelectorAll('button[type="submit"], button'));
const target = btns.find(b =>
    (b.textContent.includes('确认') || b.textContent.includes('提交') ||
     b.textContent.includes('Submit')) && !b.disabled
);
if (target) {{ target.click(); return true; }}
return false;
''')
    print(f"DELEGATE_SUBMITTED={{submitted}}")

    time.sleep(2.0)
    info = page_info()
    print(f"FINAL_URL={{info.get('url','')}}")
    text = js("document.body ? document.body.innerText : ''") or ''
    print(f"HAS_SUCCESS={{'成功' in text or 'success' in text.lower()}}")
    print(f"HAS_ERROR={{'错误' in text or 'error' in text.lower() or 'fail' in text.lower()}}")
"""

    return run_browser_harness_script(script, name=bu_name, timeout=timeout)
