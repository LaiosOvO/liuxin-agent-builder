"""节点执行器基类模块。

提供：
- NodeExecutionError：节点执行失败异常（重试耗尽 / 不可重试错误）
- BaseNodeExecutor：所有节点 executor 的抽象基类
  - Jinja2 config 递归渲染
  - tenacity 异步重试 + asyncio 超时
  - 统一错误包装
  - State Pointer Pattern 透明集成（防 Pitfall 1 checkpoint 写入放大）
  - LangGraph node fn 入口 __call__

设计参考（Dify 阅读笔记）：
- docs/reading-dify-02-04-base-nodes-2026-05-16.md：节点工厂分发模式
- docs/reading-dify-02-06-redis-pointer-2026-05-16.md：大字段旁路存储模式
- 参考 Dify DifyGraphInitContext frozen dataclass 传递上下文的思路，
  我们用构造参数注入 workspace_id / instance_id / redis
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any
from uuid import UUID

from jinja2.sandbox import SandboxedEnvironment
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.agent_builder.workflow.jinja_env import build_jinja_env

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from app.agent_builder.workflow.event_bus import EventBus


class NodeExecutionError(Exception):
    """节点执行失败（重试耗尽 / 不可重试错误）。

    Attributes:
        node_id: 失败节点的 ID
        message: 错误描述
        original: 原始异常（可为 None）
    """

    def __init__(
        self,
        node_id: str,
        message: str,
        original: Exception | None = None,
    ) -> None:
        self.node_id = node_id
        self.message = message
        self.original = original
        super().__init__(f"[{node_id}] {message}")


class BaseNodeExecutor(ABC):
    """所有节点 executor 的抽象基类。

    职责：
    1. 提供 Jinja2 config 递归渲染（_render_config）
    2. 提供 tenacity 异步重试 + asyncio 超时（__call__）
    3. 统一错误包装（NodeExecutionError）
    4. 作为 LangGraph node fn 入口（__call__ 签名兼容 LangGraph）

    子类实现：
    - execute(config, state) -> dict | Any
    - 可覆盖 _default_retry_count / _default_timeout / _retryable_exceptions

    LangGraph 集成：
    - __call__(state) -> {node_id: result}
    - LangGraph 自动将返回值 merge 到 state
    """

    def __init__(
        self,
        node_def: dict,
        *,
        jinja_env: SandboxedEnvironment | None = None,
        workspace_id: UUID | None = None,
        instance_id: UUID | None = None,
        redis: Redis | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.node_def = node_def
        self.node_id: str = node_def["id"]
        self.node_type: str = node_def["type"]
        self.config: dict = node_def.get("config", {})
        self.jinja_env: SandboxedEnvironment = jinja_env or build_jinja_env()
        # State Pointer Pattern 上下文（由 DSLCompiler 在 Plan 02-07 注入）
        # 可选：未注入时 pointer 功能自动跳过，保持向后兼容
        self.workspace_id: UUID | None = workspace_id
        self.instance_id: UUID | None = instance_id
        self.redis: Redis | None = redis
        # EventBus 上下文（Plan 02-07 注入）：用于 node.start / node.complete 事件
        self.event_bus: EventBus | None = event_bus

    def _has_pointer_context(self) -> bool:
        """检查是否注入了完整的 State Pointer 上下文。

        Returns:
            True 当且仅当 workspace_id / instance_id / redis 均已注入
        """
        return all(
            getattr(self, attr, None) is not None
            for attr in ("workspace_id", "instance_id", "redis")
        )

    async def __call__(self, state: dict) -> dict:
        """LangGraph node fn 入口（含 State Pointer Pattern 透明集成 + EventBus 事件）。

        执行流程：
        0. 发布 node.start 事件（若已注入 event_bus + instance_id）
        1. 入口：若已注入 pointer 上下文，先对 state 做透明解引用（read_state_with_pointers）
        2. 渲染 config、重试、超时、执行节点 execute()
        3. 出口：若已注入 pointer 上下文，大字段透明写 Redis（write_state_with_pointers）
        4. 返回 {node_id: result}，LangGraph 自动 merge

        节点 execute() 代码对 pointer 机制和 EventBus 完全无感知。

        Args:
            state: 当前 LangGraph state dict（可能含 pointer 字符串）

        Returns:
            {self.node_id: result}，LangGraph 自动 merge

        Raises:
            NodeExecutionError: 节点执行失败（重试耗尽或不可重试错误）
        """
        import time as _time
        _start_mono = _time.monotonic()

        # 0. 发布 node.start 事件（参考 Dify QueueNodeStartedEvent）
        if self.event_bus is not None and self.instance_id is not None:
            from app.agent_builder.workflow.event_bus import EVENT_NODE_START
            await self.event_bus.publish(
                self.instance_id,
                EVENT_NODE_START,
                {"node_id": self.node_id, "node_type": self.node_type},
            )

        # 1. 入口：透明解引用（下游节点看到真实值，而非 pointer 字符串）
        if self._has_pointer_context():
            from app.agent_builder.workflow.state_pointer import read_state_with_pointers
            state = await read_state_with_pointers(
                state,
                workspace_id=self.workspace_id,  # type: ignore[arg-type]
                instance_id=self.instance_id,  # type: ignore[arg-type]
                redis=self.redis,  # type: ignore[arg-type]
            )

        # 2. 渲染 config + 重试执行
        rendered_config = self._render_config(state)
        retry_count = rendered_config.get("retry_count", self._default_retry_count())
        backoff = rendered_config.get("backoff_base_sec", 1)
        timeout_sec = rendered_config.get("timeout_sec", self._default_timeout())

        async def _run() -> dict | Any:
            return await asyncio.wait_for(
                self.execute(rendered_config, state),
                timeout=float(timeout_sec),
            )

        retryable = self._retryable_exceptions()
        try:
            if retryable:
                async for attempt in AsyncRetrying(
                    stop=stop_after_attempt(retry_count + 1),
                    wait=wait_exponential(multiplier=backoff, max=60),
                    retry=retry_if_exception_type(retryable),
                    reraise=True,
                ):
                    with attempt:
                        result = await _run()
            else:
                result = await _run()
        except asyncio.TimeoutError as e:
            raise NodeExecutionError(
                self.node_id,
                f"超时（{timeout_sec}s），重试 {retry_count} 次后失败",
                original=e,
            ) from e
        except RetryError as e:
            raise NodeExecutionError(
                self.node_id,
                f"重试 {retry_count + 1} 次仍失败: {e!s}",
                original=e,
            ) from e
        except NodeExecutionError:
            raise
        except Exception as e:
            raise NodeExecutionError(
                self.node_id,
                str(e),
                original=e,
            ) from e

        # 3. 出口：大字段透明写 Redis（pointer wrap），对 execute() 完全无感知
        if isinstance(result, dict) and self._has_pointer_context():
            from app.agent_builder.workflow.state_pointer import write_state_with_pointers
            result = await write_state_with_pointers(
                result,
                workspace_id=self.workspace_id,  # type: ignore[arg-type]
                instance_id=self.instance_id,  # type: ignore[arg-type]
                redis=self.redis,  # type: ignore[arg-type]
            )

        return {self.node_id: result}

    @abstractmethod
    async def execute(self, config: dict, state: dict) -> dict | Any:
        """子类实现：执行节点核心逻辑。

        Args:
            config: 经 Jinja2 渲染后的节点配置（self.config 的渲染结果）
            state: 当前 LangGraph state dict

        Returns:
            节点执行结果，会以 state[self.node_id] 形式写入 state
        """
        ...

    def _render_config(self, state: dict) -> dict:
        """递归用 Jinja2 渲染 config 中所有 str 字段（含嵌套 dict / list）。

        渲染时使用当前 state 作为模板变量上下文。
        对 str 字段：`{{ start.name }}` → 实际值
        非 str 字段（int/bool/None）：原样保留

        Args:
            state: 当前 state dict，作为 Jinja2 渲染上下文

        Returns:
            渲染后的 config 副本（不修改原 self.config）
        """

        def render(value: Any) -> Any:
            if isinstance(value, str):
                return self.jinja_env.from_string(value).render(**state)
            if isinstance(value, dict):
                return {k: render(v) for k, v in value.items()}
            if isinstance(value, list):
                return [render(v) for v in value]
            return value

        return {k: render(v) for k, v in self.config.items()}

    def _default_retry_count(self) -> int:
        """默认重试次数（0 = 不重试）。子类可覆盖。"""
        return 0

    def _default_timeout(self) -> int:
        """默认超时秒数。子类可覆盖。"""
        return 30

    def _retryable_exceptions(self) -> tuple[type[Exception], ...]:
        """可触发重试的异常类型。子类可覆盖。

        Returns:
            空 tuple 表示不重试任何异常（默认行为）
        """
        return ()
