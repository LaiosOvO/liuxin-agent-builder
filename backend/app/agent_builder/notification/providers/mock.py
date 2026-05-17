"""MockIMProvider — 测试 + E2E 用 Provider（Plan 04-05）。

不发真实 IM 请求，仅记录每次调用的 method + recipient + payload 到 in-memory 队列；
测试代码通过 `mock.calls` 列表断言投递行为。

设计参考 docs/reading-im-sdk-04-05-providers-2026-05-17.md：
- 满足 IMProvider Protocol（鸭子类型 isinstance(mock, IMProvider) is True）
- 不继承基类（Protocol 不是 ABC）
- 支持 fail_send_hitl_card 开关 — 测试 tenacity 重试 / 错误路径

CLAUDE.md immutability：
- MockCallRecord 是 @dataclass(frozen=True)（创建后不可改）
- self.calls 是 list 内部状态（mock 本质需要状态记录）— 但每次 send 创建新 record append
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MockCallRecord:
    """Mock Provider 调用记录（E2E + 集成测试断言用）。

    frozen=True：record 创建后不可修改，保证测试断言看到的是当时调用快照。
    """

    method: str  # 'send_hitl_card' / 'update_card' / 'send_supplement_text'
    recipient: str  # IM 用户 ID（update_card 场景为空字符串）
    payload: dict[str, Any]  # 调用参数快照


class MockIMProvider:
    """测试用 Provider — 满足 IMProvider Protocol 鸭子类型。

    用法：
        mock = MockIMProvider(name=PROVIDER_FEISHU)
        register_provider(mock)
        # ... 触发投递 ...
        assert len(mock.calls) == 1
        assert mock.calls[0].method == 'send_hitl_card'
        assert mock.calls[0].recipient == 'ou_xyz'

    错误模拟：
        mock = MockIMProvider(name=PROVIDER_FEISHU)
        mock.fail_send_hitl_card = True  # 后续 send_hitl_card 抛 ConnectionError
        # 或
        mock = MockIMProvider(name=PROVIDER_FEISHU, fail_count=2)
        # 前 2 次 send_hitl_card 抛 ConnectionError，第 3 次成功（测 tenacity 重试）
    """

    def __init__(
        self,
        name: str = "mock",
        *,
        fail_send_hitl_card: bool = False,
        fail_count: int = 0,
    ) -> None:
        """
        Args:
            name: Provider 名（默认 'mock'；测试中常用 PROVIDER_FEISHU 等代替具体厂商）
            fail_send_hitl_card: True 时所有 send_hitl_card 调用抛 ConnectionError
            fail_count: 前 N 次 send_hitl_card 抛 ConnectionError，第 N+1 次成功
                        （fail_count > 0 时 fail_send_hitl_card 被忽略）
        """
        self.name = name
        self.calls: list[MockCallRecord] = []
        self.fail_send_hitl_card = fail_send_hitl_card
        self.fail_count = fail_count
        self._send_attempts = 0  # 累计 send_hitl_card 调用次数（无论成败）

    async def send_hitl_card(
        self,
        *,
        recipient: str,
        flow_title: str,
        node_title: str,
        applicant_name: str,
        actor_name: str,
        deadline_at: str,
        description: str,
        deeplinks: list[dict[str, str]],
    ) -> dict[str, Any]:
        """投递 HITL 卡片（Mock — 不真发）。

        计入 self.calls 记录，按 fail_count / fail_send_hitl_card 模拟错误。
        """
        self._send_attempts += 1

        # 错误模拟优先级：fail_count > fail_send_hitl_card
        if self.fail_count > 0 and self._send_attempts <= self.fail_count:
            raise ConnectionError(
                f"mock {self.name} 模拟网络错误（attempt {self._send_attempts}/{self.fail_count}）"
            )
        if self.fail_send_hitl_card:
            raise ConnectionError(f"mock {self.name} simulated network error")

        # 记录调用（创建新 frozen record append — 不修改既有 record）
        record = MockCallRecord(
            method="send_hitl_card",
            recipient=recipient,
            payload={
                "flow_title": flow_title,
                "node_title": node_title,
                "applicant_name": applicant_name,
                "actor_name": actor_name,
                "deadline_at": deadline_at,
                "description": description,
                "deeplinks": list(deeplinks),  # 浅拷贝防外部修改
            },
        )
        self.calls.append(record)
        # 返回 message_id 用顺序号（测试可断言 "mock-msg-1" 等）
        return {
            "message_id": f"mock-msg-{len(self.calls)}",
            "raw_response": {"ok": True, "provider": self.name},
        }

    async def update_card(
        self,
        *,
        message_id: str,
        new_content: dict[str, Any],
    ) -> None:
        """更新卡片（Mock — 仅记录）。"""
        self.calls.append(
            MockCallRecord(
                method="update_card",
                recipient="",  # update_card 不针对单个 recipient
                payload={
                    "message_id": message_id,
                    "new_content": dict(new_content),
                },
            )
        )

    async def send_supplement_text(
        self,
        *,
        recipient: str,
        text: str,
    ) -> None:
        """补发文本（Mock — 仅记录）。"""
        self.calls.append(
            MockCallRecord(
                method="send_supplement_text",
                recipient=recipient,
                payload={"text": text},
            )
        )

    # ── Phase 4.5 入站接口预留（Phase 4 与 Protocol 默认行为一致）──────────────
    # runtime_checkable Protocol 校验依赖方法存在性，必须在 Mock 实现这两个方法

    async def subscribe(self, on_event: Any) -> None:
        """[Phase 4.5] 入站订阅（Phase 4 Mock 同样抛 NotImplementedError）。"""
        raise NotImplementedError(f"{self.name} subscribe 将于 Phase 4.5 实现")

    async def verify_webhook_signature(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> bool:
        """[Phase 4.5] 入站签名校验（Phase 4 Mock 同样抛 NotImplementedError）。"""
        raise NotImplementedError(
            f"{self.name} verify_webhook_signature 将于 Phase 4.5 实现"
        )

    def reset(self) -> None:
        """重置 calls + send_attempts — 测试 fixture 复用 mock 时调。"""
        self.calls.clear()
        self._send_attempts = 0
