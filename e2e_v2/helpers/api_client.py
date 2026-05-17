"""E2E API 客户端 — Python port 自 e2e/helpers/api-client.ts。

封装 backend HTTP API 调用：
- setup / login / register / invite-accept
- workspace 切换 + 用户管理（创建 + im_bindings 写入）
- workflow CRUD + publish + instance launch
- HITL: page 渲染 / action 提交 / delegate

约定：
- 所有方法返回 (status, body_json) 或抛 httpx.HTTPStatusError
- httpx.AsyncClient 由 conftest fixture 提供（base_url 已设）
- cookie 自动透传（client.cookies 持续保留）
"""
from __future__ import annotations

import os
import secrets
from typing import Any

import httpx


API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
DEFAULT_PASSWORD = "E2EPassword2026!"


# ── 通用辅助 ──────────────────────────────────────────────────────────


def random_email(prefix: str = "user") -> str:
    """生成测试用唯一邮箱。"""
    return f"{prefix}_{secrets.token_hex(4)}@e2e.test"


# ── Setup / Auth ──────────────────────────────────────────────────────


async def get_setup_state(client: httpx.AsyncClient) -> dict[str, Any]:
    r = await client.get("/api/setup/state")
    r.raise_for_status()
    return r.json()


async def initialize_system(
    client: httpx.AsyncClient,
    *,
    email: str,
    password: str = DEFAULT_PASSWORD,
    display_name: str = "E2E 管理员",
    workspace_name: str | None = None,
) -> dict[str, Any]:
    """初始化系统（POST /api/setup/initialize）。"""
    payload = {
        "email": email,
        "password": password,
        "display_name": display_name,
        "workspace_name": workspace_name or f"E2E 工作区_{secrets.token_hex(3)}",
    }
    r = await client.post("/api/setup/initialize", json=payload)
    r.raise_for_status()
    return r.json()


async def login(
    client: httpx.AsyncClient,
    *,
    email: str,
    password: str = DEFAULT_PASSWORD,
) -> dict[str, Any]:
    """POST /api/auth/login — session cookie 自动写入 client.cookies。"""
    r = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    r.raise_for_status()
    return r.json()


async def ensure_initialized(
    client: httpx.AsyncClient,
    *,
    admin_email: str | None = None,
) -> tuple[str, str]:
    """幂等初始化：如未 setup 则 initialize，已 setup 则直接 login。

    Returns:
        (email, password) — 已登录的 admin 凭据
    """
    state = await get_setup_state(client)
    email = admin_email or "admin@e2e.test"

    if not state.get("initialized"):
        await initialize_system(client, email=email)
        return email, DEFAULT_PASSWORD

    # 已初始化 — 尝试登录
    try:
        await login(client, email=email)
    except httpx.HTTPStatusError:
        # 默认 admin 不存在，跑测试前需要预设；fail-loud 提示用户
        raise RuntimeError(
            f"系统已 initialize 但默认 admin {email} 登录失败 — "
            "请确认测试环境与 E2E_ADMIN_EMAIL 配置一致"
        )
    return email, DEFAULT_PASSWORD


# ── 邀请 / 用户管理 ──────────────────────────────────────────────────


async def create_invite(
    admin_client: httpx.AsyncClient,
    *,
    email: str,
    role_code: str = "editor",
) -> dict[str, Any]:
    """创建邀请（admin cookie 已绑定 client.cookies）。"""
    r = await admin_client.post(
        "/api/invites", json={"email": email, "role_code": role_code}
    )
    r.raise_for_status()
    return r.json()


async def accept_invite(
    client: httpx.AsyncClient,
    *,
    token: str,
    password: str = DEFAULT_PASSWORD,
    display_name: str | None = None,
) -> dict[str, Any]:
    """通过邀请 token 完成注册（新 client，不带 admin cookie）。"""
    r = await client.post(
        "/api/invites/accept",
        json={
            "token": token,
            "password": password,
            "display_name": display_name or "E2E 用户",
        },
    )
    r.raise_for_status()
    return r.json()


# ── Workflow / Instance ──────────────────────────────────────────────


async def create_workflow(
    client: httpx.AsyncClient, *, dsl: dict[str, Any]
) -> dict[str, Any]:
    """创建 workflow（admin / editor cookie 已绑定）。"""
    r = await client.post(
        "/api/v1/workflows", json={"name": dsl["name"], "dsl": dsl}
    )
    r.raise_for_status()
    return r.json()


async def publish_workflow(
    client: httpx.AsyncClient, *, workflow_id: str
) -> dict[str, Any]:
    """发布 workflow（status: draft → published）。"""
    r = await client.post(f"/api/v1/workflows/{workflow_id}/publish")
    r.raise_for_status()
    return r.json()


async def launch_instance(
    client: httpx.AsyncClient,
    *,
    workflow_id: str,
    input_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """启动流程实例（POST /api/v1/instances）。"""
    payload = {
        "workflow_id": workflow_id,
        "input": input_payload or {"reason": "E2E 测试"},
    }
    r = await client.post("/api/v1/instances", json=payload)
    r.raise_for_status()
    return r.json()


async def get_instance(
    client: httpx.AsyncClient, *, instance_id: str
) -> dict[str, Any]:
    r = await client.get(f"/api/v1/instances/{instance_id}")
    r.raise_for_status()
    return r.json()


# ── HITL ──────────────────────────────────────────────────────────────


async def hitl_get_page(
    client: httpx.AsyncClient,
    *,
    token: str,
    user_agent: str | None = None,
    accept_json: bool = True,
) -> httpx.Response:
    """GET /hitl/page/<token>（公网 endpoint，无 cookie 也可）。

    Args:
        user_agent: 设置自定义 UA（Safe Links bot 回归用）
        accept_json: True 走 JSON 路径；False 走 HTML（默认 JSON 便于断言）
    """
    headers: dict[str, str] = {}
    if user_agent:
        headers["User-Agent"] = user_agent
    if accept_json:
        headers["Accept"] = "application/json"
    # 新 client 避免污染 cookie；如果传入的 client 已经设过 cookies，bot path 不会签新 cookie
    r = await client.get(f"/hitl/page/{token}", headers=headers)
    return r


async def hitl_post_action(
    client: httpx.AsyncClient,
    *,
    token: str,
    action: str,
    form_data: dict[str, Any] | None = None,
    cookie_value: str | None = None,
) -> httpx.Response:
    """POST /hitl/action/<token>（需 hitl_session_<jti> cookie）。

    Args:
        cookie_value: 完整 hitl_session_<jti> cookie value（由 hitl_get_page Set-Cookie 获得）
    """
    headers = {"Accept": "application/json"}
    data: dict[str, Any] = {"action": action}
    if form_data:
        data["form_data"] = form_data

    # form-urlencoded
    r = await client.post(f"/hitl/action/{token}", data=data, headers=headers)
    return r


async def hitl_delegate(
    client: httpx.AsyncClient,
    *,
    token: str,
    to_email: str,
    reason: str = "委托给同事",
) -> httpx.Response:
    """POST /hitl/action/<token>?op=delegate — 委托原 token 给新 actor。"""
    headers = {"Accept": "application/json"}
    payload = {"to_email": to_email, "reason": reason}
    r = await client.post(
        f"/hitl/action/{token}",
        params={"op": "delegate"},
        json=payload,
        headers=headers,
    )
    return r
