"""HITL 公网回调 API — Phase 3 P0 价值演示阶段的核心入口（Plan 03-06）。

设计参考 docs/reading-dify-03-06-hitl-api-2026-05-17.md：
- §3 架构对比：Dify Flask + 短 token vs 我们 FastAPI + JWT + jti
- §5.3 Token-as-login HMAC cookie（30min session）
- §7 三层并发防护（slowapi + advisory_xact_lock + UPDATE RETURNING）

公网仅暴露 2 个端点（Phase 1 NET-02 nginx 已锁定 /hitl/page/* + /hitl/action/* + /api/im/webhook/*）：

GET /hitl/page/<token>
  - 不消费 jti（CLAUDE.md 2.5 永不可接受 GET 消费）
  - bot UA 检测短路（Pitfall 3 P0）→ 返回 bot_scan.html 200
  - 真实用户 → 签 30min HMAC cookie + 渲染 page.html

POST /hitl/action/<token>
  - cookie 校验 + advisory_lock + jti 消费 + sibling 失效 + LangGraph resume + audit
  - 全链路在 HitlActionService.submit_action 内（service 层厚 + controller 层薄）

CLAUDE.md 2.4 多租户：
- thread_id "{workspace_id}:{instance_id}" 已含 workspace 前缀（Pitfall 13）
- 公网 endpoint 不依赖 session，但通过 jti → instance_id → workspace_id 链路隔离

CLAUDE.md 2.5（GET 不消费 jti）：
- GET 路径仅 HitlTokenService.decode + store.is_consumed（查询，不写）
- POST 路径才走 HitlTokenStore.consume（advisory_lock 保护下 UPDATE）
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_builder.api.deps import get_db  # 注：与 v1 路径用同一个 get_db
from app.agent_builder.models.flow_instance import FlowInstance
from app.agent_builder.models.node_state import NodeState
from app.agent_builder.security.bot_detector import is_bot_ua
from app.agent_builder.security.rate_limit import limiter
from app.agent_builder.services.hitl_action_service import (
    FlowInstanceNotFound,
    FormDataValidationError,
    HitlActionService,
    JtiAlreadyConsumed,
    NodeStateNotFound,
)
from app.agent_builder.workflow.hitl_token_store import HitlTokenStore
from app.services.hitl_token_service import (
    HitlTokenError,
    HitlTokenService,
    InvalidAudience,
    InvalidSignature,
    TokenExpired,
)

log = logging.getLogger(__name__)


# ── Router + Templates ──────────────────────────────────────────────────────

router = APIRouter(prefix="/hitl", tags=["hitl"])

_TEMPLATE_DIR = Path(__file__).parent.parent.parent / "templates" / "hitl"
templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))


# ── 内部工具：session cookie HMAC ──────────────────────────────────────────

# CLAUDE.md 2.6 HMAC_SECRET >= 32 字节（Phase 1 startup_checks 已校验）
def _get_hmac_secret() -> bytes:
    """获取 HMAC_SECRET 用于 cookie 签名（与 JWT_SECRET 隔离）。"""
    secret = os.environ.get("HMAC_SECRET", "")
    if len(secret) < 32:
        # 测试环境 conftest 已 setdefault；生产由 startup_checks 阻断启动
        secret = secret or "fallback-hmac-secret-min-32-bytes!"
    return secret.encode("utf-8")


def _sign_session_cookie(jti: str) -> str:
    """为 jti 签 cookie value: <jti>:<HMAC-SHA256(jti)>。

    cookie 名 hitl_session_<jti> 保证多 token 独立 session（用户可同时打开多个邮件链接）。
    """
    secret = _get_hmac_secret()
    sig = hmac.new(secret, jti.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{jti}:{sig}"


def _verify_session_cookie(jti: str, cookie_value: str | None) -> bool:
    """常量时间比较 cookie value 与签名一致性。"""
    if not cookie_value:
        return False
    expected = _sign_session_cookie(jti)
    return hmac.compare_digest(expected, cookie_value)


def _get_redis(request: Request):
    """从 app.state 拿 Redis 客户端（main.py lifespan 创建）。

    测试环境会直接 monkeypatch 注入；如未注入，按需懒加载。
    """
    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        # 懒加载（生产环境 lifespan 应已设置；此分支保险）
        from redis.asyncio import Redis
        redis = Redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
        )
        request.app.state.redis = redis
    return redis


def _render_error(request: Request, message: str, status_code: int) -> HTMLResponse:
    """统一渲染 error.html 模板。"""
    return templates.TemplateResponse(
        "error.html",
        {"request": request, "error": message},
        status_code=status_code,
    )


def _wants_json(request: Request) -> bool:
    """Content negotiation: 当 Accept 含 application/json 时返回 True。

    Next.js 前端 SSR fetch 用 Accept: application/json；
    邮件客户端 / 浏览器直访保持 HTML 默认。
    """
    accept = request.headers.get("Accept", "")
    return "application/json" in accept.lower()


def _render_error_negotiated(
    request: Request, message: str, status_code: int
) -> HTMLResponse | JSONResponse:
    """按 Accept 头返回 HTML 或 JSON 错误响应。"""
    if _wants_json(request):
        return JSONResponse(
            {"error": message, "status_code": status_code},
            status_code=status_code,
        )
    return _render_error(request, message, status_code)


# ── GET /hitl/page/<token> ───────────────────────────────────────────────────


@router.get("/page/{token}", response_class=HTMLResponse)
@limiter.limit("60/minute")
async def hitl_page_view(
    request: Request,
    token: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    """GET 决策页 — Phase 3 P0 价值演示入口。

    CLAUDE.md 2.5：GET **不消费** jti（永不可接受 GET 消费）。
    """
    ua = request.headers.get("User-Agent", "")
    wants_json = _wants_json(request)

    # ── 0. Bot UA 检测（Pitfall 3 P0 防护）───────────────────────────────
    # 必须在 JWT decode 之前 — bot 可能用任意 token 探测，不浪费 CPU 解码
    if is_bot_ua(ua):
        log.info("bot UA detected on GET, returning static scan page (ua=%s)", ua[:80])
        if wants_json:
            return JSONResponse(
                {"bot_scan": True, "message": "邮件扫描，未触发任何状态变更"},
                status_code=200,
            )
        return templates.TemplateResponse(
            "bot_scan.html",
            {"request": request},
            status_code=200,
        )

    # ── 1. JWT decode（仅校签 + exp + aud；不消费 jti）─────────────────
    try:
        payload = HitlTokenService.decode(token)
    except TokenExpired:
        return _render_error_negotiated(
            request, "链接已过期，请联系发起人重新发起。", status.HTTP_410_GONE
        )
    except (InvalidSignature, InvalidAudience):
        return _render_error_negotiated(
            request, "无效的链接签名。", status.HTTP_401_UNAUTHORIZED
        )
    except HitlTokenError as e:
        log.warning("HITL token decode failed: %s", e)
        return _render_error_negotiated(
            request, "链接格式错误。", status.HTTP_400_BAD_REQUEST
        )

    # ── 2. 检查 jti 已消费（**仅查询，不消费**）─────────────────────────
    redis = _get_redis(request)
    store = HitlTokenStore(db, redis)
    jti_uuid = UUID(payload["jti"])
    if await store.is_consumed(jti_uuid):
        return _render_error_negotiated(
            request,
            "决策已提交，链接失效。",
            status.HTTP_410_GONE,
        )

    # ── 3. 加载节点状态（form_schema / records / deadline）─────────────
    node_state = await db.get(NodeState, UUID(payload["node_state_id"]))
    if node_state is None:
        return _render_error_negotiated(
            request, "节点不存在。", status.HTTP_404_NOT_FOUND
        )

    ns_payload = node_state.payload or {}

    # ── 4. 签 30min HMAC session cookie ────────────────────────────────
    cookie_value = _sign_session_cookie(payload["jti"])

    # ── 5. 渲染 page.html or JSON ───────────────────────────────────────
    # allowed_actions 是 JWT payload 内的字段（HitlTokenService.sign 写入）
    allowed_actions = payload.get("allowed_actions", [])
    primary_action = allowed_actions[0] if allowed_actions else "submit"

    if wants_json:
        # JSON 响应（供 Next.js 前端 SSR / client fetch 消费）
        response = JSONResponse(
            {
                "bot_scan": False,
                "token": token,
                "jti": payload["jti"],
                "action": primary_action,
                "allowed_actions": allowed_actions,
                "node_state_id": payload["node_state_id"],
                "form_schema": ns_payload.get("form_schema", {}),
                "records": ns_payload.get("records", []),
                "deadline_at": ns_payload.get("deadline_at"),
                "current_actor": ns_payload.get("current_actor"),
                "phase": ns_payload.get("phase", "submit"),
                "flow_title": ns_payload.get("flow_title"),
            },
            status_code=200,
        )
    else:
        response = templates.TemplateResponse(
            "page.html",
            {
                "request": request,
                "token": token,
                "jti": payload["jti"],
                "action": primary_action,
                "node_state_id": payload["node_state_id"],
                "form_schema": ns_payload.get("form_schema", {}),
                "records": ns_payload.get("records", []),
                "deadline_at": ns_payload.get("deadline_at"),
                "current_actor": ns_payload.get("current_actor"),
                "phase": ns_payload.get("phase", "submit"),
                "flow_title": ns_payload.get("flow_title"),
            },
            status_code=200,
        )

    response.set_cookie(
        key=f"hitl_session_{payload['jti']}",
        value=cookie_value,
        max_age=1800,  # 30 分钟
        httponly=True,
        secure=False,  # 测试环境用 http；生产 nginx 强制 https，secure=True 由 reverse proxy 处理
        samesite="lax",
    )
    return response


# ── POST /hitl/action/<token> ────────────────────────────────────────────────


@router.post("/action/{token}", response_class=HTMLResponse)
@limiter.limit("10/minute")
async def hitl_action_submit(
    request: Request,
    token: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    action: Annotated[str, Form()] = "",
    reason: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """POST 提交决策 — advisory_lock + jti 消费 + LangGraph resume + audit。

    CLAUDE.md 2.5：POST **才** 消费 jti。
    """
    ua = request.headers.get("User-Agent", "")
    ip = request.client.host if request.client else ""
    wants_json = _wants_json(request)

    # ── 1. JWT decode ──────────────────────────────────────────────────
    try:
        payload = HitlTokenService.decode(token)
    except TokenExpired:
        return _render_error_negotiated(
            request, "链接已过期，无法提交。", status.HTTP_410_GONE
        )
    except (InvalidSignature, InvalidAudience):
        return _render_error_negotiated(
            request, "无效的链接签名。", status.HTTP_401_UNAUTHORIZED
        )
    except HitlTokenError as e:
        log.warning("HITL POST token decode failed: %s", e)
        return _render_error_negotiated(
            request, "链接格式错误。", status.HTTP_400_BAD_REQUEST
        )

    # ── 2. cookie 校验（Token-as-login HMAC session）────────────────────
    cookie_value = request.cookies.get(f"hitl_session_{payload['jti']}")
    if not _verify_session_cookie(payload["jti"], cookie_value):
        return _render_error_negotiated(
            request,
            "会话已过期或无效，请重新点击邮件链接。",
            status.HTTP_401_UNAUTHORIZED,
        )

    # ── 3. action 字段校验（不可空）────────────────────────────────────
    if not action:
        return _render_error_negotiated(
            request, "缺少 action 字段。", status.HTTP_400_BAD_REQUEST
        )

    # ── 4. form_data 从其他 Form 字段读取（排除 action/reason/jti）─────
    form = await request.form()
    form_data = {
        k: v for k, v in form.items() if k not in ("action", "reason", "jti")
    }

    # ── 5. 业务层：HitlActionService.submit_action ─────────────────────
    redis = _get_redis(request)
    service = HitlActionService(db, redis, graph_loader=_default_graph_loader)
    try:
        result = await service.submit_action(
            payload=payload,
            action=action,
            reason=reason,
            form_data=form_data,
            ip=ip,
            ua=ua,
        )
    except JtiAlreadyConsumed:
        return _render_error_negotiated(
            request,
            "决策已提交，无法重复提交。",
            status.HTTP_409_CONFLICT,
        )
    except FormDataValidationError as e:
        # 422 + 重新渲染 page.html 含 errors（HTML） 或 JSON {errors: [...]}
        if wants_json:
            return JSONResponse(
                {
                    "error": "表单校验失败",
                    "errors": e.errors,
                    "status_code": status.HTTP_422_UNPROCESSABLE_ENTITY,
                },
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        node_state = await db.get(NodeState, UUID(payload["node_state_id"]))
        ns_payload = (node_state.payload or {}) if node_state else {}
        return templates.TemplateResponse(
            "page.html",
            {
                "request": request,
                "token": token,
                "jti": payload["jti"],
                "action": payload.get("allowed_actions", ["submit"])[0],
                "node_state_id": payload["node_state_id"],
                "form_schema": ns_payload.get("form_schema", {}),
                "records": ns_payload.get("records", []),
                "deadline_at": ns_payload.get("deadline_at"),
                "current_actor": ns_payload.get("current_actor"),
                "phase": ns_payload.get("phase", "submit"),
                "errors": e.errors,
            },
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    except (FlowInstanceNotFound, NodeStateNotFound) as e:
        log.warning("HITL POST resource not found: %s", e)
        return _render_error_negotiated(
            request, "关联资源不存在。", status.HTTP_404_NOT_FOUND
        )
    except ValueError as e:
        # compute_next_status 非法 action / phase 组合
        return _render_error_negotiated(
            request, f"非法决策动作：{e}", status.HTTP_400_BAD_REQUEST
        )

    # ── 6. 成功页 / JSON 响应 ───────────────────────────────────────────
    if wants_json:
        return JSONResponse(
            {
                "ok": True,
                "action": action,
                "instance_id": str(result["instance_id"]),
                "new_node_status": result["new_node_status"],
            },
            status_code=200,
        )
    return templates.TemplateResponse(
        "success.html",
        {
            "request": request,
            "action": action,
            "instance_id": result["instance_id"],
            "new_node_status": result["new_node_status"],
        },
        status_code=200,
    )


# ── 默认 graph_loader（生产用，注入到 HitlActionService）──────────────────


async def _default_graph_loader(flow_instance: FlowInstance, db, redis):
    """默认 graph loader — 编译 workflow_version.dsl 返回 graph。

    Phase 2 的 ExecutionEngine 已落 DSLCompiler；此处复用编译路径。
    测试环境通过 HitlActionService.__init__(graph_loader=mock) 覆盖。

    v1 简化：若编译失败或缺少依赖（如 checkpointer 未初始化），返回 None
    跳过 ainvoke — node_state.payload 仍然完整更新，可由后台 worker 补救。
    """
    try:
        from app.agent_builder.models.workflow_version import WorkflowVersion
        from app.agent_builder.workflow.compiler import DSLCompiler

        workflow_version = await db.get(
            WorkflowVersion, flow_instance.workflow_version_id
        )
        if workflow_version is None or not workflow_version.dsl:
            return None

        compiler = DSLCompiler(
            workspace_id=flow_instance.workspace_id,
            instance_id=flow_instance.id,
            redis=redis,
        )
        compiled = compiler.compile(workflow_version.dsl)
        return compiled.graph
    except Exception as e:
        log.warning(
            "HITL default_graph_loader failed (skipping ainvoke): %s", e
        )
        return None
