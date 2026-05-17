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

from fastapi import APIRouter, Depends, Form, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_builder.api.deps import get_db  # 注：与 v1 路径用同一个 get_db
from app.agent_builder.models.audit_log import AuditLog
from app.agent_builder.models.flow_instance import FlowInstance
from app.agent_builder.models.node_state import NodeState
from app.agent_builder.models.user import User
from app.agent_builder.schemas.hitl import DelegateRequest, DelegateResponse
from app.agent_builder.security.bot_detector import is_bot_ua
from app.agent_builder.security.rate_limit import limiter
from app.agent_builder.services.hitl_action_service import (
    FlowInstanceNotFound,
    FormDataValidationError,
    HitlActionService,
    JtiAlreadyConsumed,
    NodeStateNotFound,
)
from app.agent_builder.services.hitl_service import (
    DEFAULT_TOKEN_EXPIRES_IN,
    DelegateError,
    HitlService,
)
from app.agent_builder.workflow.checkpoint import build_thread_id
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
    op: Annotated[str, Query(description="操作类型：submit(默认) | delegate")] = "submit",
    action: Annotated[str, Form()] = "",
    reason: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """POST 提交决策 — advisory_lock + jti 消费 + LangGraph resume + audit。

    支持的 op:
    - submit(默认): 提交决策（approve/return/reject/submit）
    - delegate(Plan 04-03): 委托给同事；body 须含 to_email + reason

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

    # ── 2.5. op 分支（Plan 04-03 委托）──────────────────────────────────
    if op == "delegate":
        return await _handle_delegate(
            request=request,
            payload=payload,
            db=db,
            ip=ip,
            ua=ua,
            wants_json=wants_json,
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
    service = HitlActionService(db, redis, graph_resumer=_default_graph_resumer)
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


# ── 默认 graph_resumer（生产用，注入到 HitlActionService）──────────────────


async def _default_graph_resumer(
    flow_instance: FlowInstance,
    db,
    redis,
    *,
    resume_args: dict,
    thread_id: str,
) -> bool:
    """默认 graph resumer — 持 AsyncPostgresSaver checkpointer 生命周期，
    编译 workflow_version.dsl 后立即 ainvoke(Command(resume=...))。

    必须在 advisory_lock 持有期间被调用（HitlActionService.submit_action 内）。
    Checkpointer 是 context manager，在 with 块退出时关闭连接 —
    因此 compile + ainvoke 必须**同时**位于 with-scope 内。

    Returns:
        True: 成功 ainvoke 推进流程；False: DSL 缺失 / 编译失败（不阻塞写入）
    """
    from langgraph.types import Command

    from app.agent_builder.models.workflow_version import WorkflowVersion
    from app.agent_builder.workflow.checkpoint import get_checkpointer
    from app.agent_builder.workflow.compiler import DSLCompiler

    try:
        workflow_version = await db.get(
            WorkflowVersion, flow_instance.workflow_version_id
        )
        if workflow_version is None or not workflow_version.dsl:
            log.warning(
                "HITL graph resume skipped: workflow_version dsl missing "
                "(instance_id=%s)",
                flow_instance.id,
            )
            return False

        async with get_checkpointer() as checkpointer:
            compiler = DSLCompiler(
                workspace_id=flow_instance.workspace_id,
                instance_id=flow_instance.id,
                redis=redis,
            )
            compiled = compiler.compile(
                workflow_version.dsl,
                checkpointer=checkpointer,
            )
            await compiled.graph.ainvoke(
                Command(resume=resume_args),
                config={"configurable": {"thread_id": thread_id}},
            )
        return True
    except Exception as e:
        log.warning(
            "HITL default_graph_resumer failed (node_state still updated): %s",
            e,
        )
        return False


# ── Plan 04-03 委托端点 helper ──────────────────────────────────────────────


# 错误码 → HTTP 状态码映射（reading-dify-04-03 §5）
_DELEGATE_ERROR_STATUS: dict[str, int] = {
    "depth_exceeded": status.HTTP_409_CONFLICT,
    "self_delegate": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "circular": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "recipient_not_found": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "cross_workspace": status.HTTP_422_UNPROCESSABLE_ENTITY,
}


async def _handle_delegate(
    *,
    request: Request,
    payload: dict,
    db: AsyncSession,
    ip: str,
    ua: str,
    wants_json: bool,
) -> JSONResponse | HTMLResponse:
    """POST /hitl/action/<jwt>?op=delegate 处理函数（Plan 04-03，HITL-06）。

    完整流程：
    1. 解析 body（DelegateRequest pydantic 校验：to_email + reason）
    2. 加载 from_user / flow_instance / node_state（FK 链路必备）
    3. pg_advisory_xact_lock（与 submit 同锁 key）
    4. HitlTokenStore.consume(jti) → 原 token 立即失效
    5. HitlService.create_delegate_token → 创建被委托人 3 个新 token + 更新 payload
    6. （Phase 4 简化）发邮件通知被委托人 — 留 04-12 集成 NotificationService.enqueue_hitl_multichannel
    7. audit_log action='hitl.delegate'
    8. structured log 'hitl.chain.delegate'
    9. commit

    Args:
        request: FastAPI Request（读 body / 渲染响应）
        payload: HitlTokenService.decode 返回的 JWT payload
        db: AsyncSession
        ip / ua: 审计字段
        wants_json: Accept 头是否含 application/json

    Returns:
        201 JSONResponse(DelegateResponse) on success
        409 / 422 / 404 / 401 错误（JSON 或 HTML 根据 Accept）
    """
    # ── 1. 解析 body（pydantic 校验） ────────────────────────────────
    # 支持 application/json 或 application/x-www-form-urlencoded
    content_type = request.headers.get("Content-Type", "")
    body_data: dict | None = None
    try:
        if "application/json" in content_type.lower():
            body_data = await request.json()
        else:
            form = await request.form()
            body_data = {k: v for k, v in form.items() if k not in ("action",)}
        delegate_req = DelegateRequest(**(body_data or {}))
    except ValidationError as e:
        return _render_error_negotiated(
            request,
            f"请求参数错误：{e.errors()[0]['msg']}",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    except Exception as e:  # noqa: BLE001 — body 解析异常兜底
        log.warning("delegate body parse failed: %s", e)
        return _render_error_negotiated(
            request,
            "请求体格式错误（需要 to_email + reason）。",
            status.HTTP_400_BAD_REQUEST,
        )

    # ── 2. 加载关联实体 ────────────────────────────────────────────────
    jti = UUID(payload["jti"])
    actor_id = UUID(payload["actor_id"])
    node_state_id = UUID(payload["node_state_id"])
    instance_id = UUID(payload["flow_id"])

    from_user = await db.get(User, actor_id)
    if from_user is None:
        return _render_error_negotiated(
            request, "委托发起人不存在。", status.HTTP_404_NOT_FOUND
        )

    flow_instance = await db.get(FlowInstance, instance_id)
    if flow_instance is None:
        return _render_error_negotiated(
            request, "流程实例不存在。", status.HTTP_404_NOT_FOUND
        )

    thread_id = build_thread_id(flow_instance.workspace_id, instance_id)

    # ── 3. advisory_xact_lock（Pitfall 2 防护，与 submit_action 同锁 key）─
    lock_key = hash(thread_id) & 0x7FFFFFFFFFFFFFFF
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:k)"),
        {"k": lock_key},
    )

    node_state = await db.get(NodeState, node_state_id)
    if node_state is None:
        return _render_error_negotiated(
            request, "节点状态不存在。", status.HTTP_404_NOT_FOUND
        )

    # ── 4. 消费原 token（action='delegate' 通过 used_ip 标识）──────────
    redis = _get_redis(request)
    store = HitlTokenStore(db, redis)
    # 委托用 used_ip 后缀标识来源（与真实 submit / sibling-invalidate / chain-invalidate 区分）
    consumed_token = await store.consume(
        jti,
        ip=f"{ip}:delegate" if ip else "system:delegate",
        ua=ua,
    )
    if consumed_token is None:
        return _render_error_negotiated(
            request,
            "决策链接已被使用或失效。",
            status.HTTP_409_CONFLICT,
        )

    # ── 5. 创建被委托人新 token + 更新 payload ──────────────────────────
    hitl_svc = HitlService(db)
    try:
        new_tokens, depth = await hitl_svc.create_delegate_token(
            from_user=from_user,
            to_email=str(delegate_req.to_email),
            reason=delegate_req.reason,
            node_state=node_state,
            flow_instance=flow_instance,
            ip=ip,
            ua=ua,
            timeout_seconds=DEFAULT_TOKEN_EXPIRES_IN,
        )
    except DelegateError as e:
        status_code = _DELEGATE_ERROR_STATUS.get(
            e.code, status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        # 业务校验失败不阻塞 token 消费 — 已 consume 的原 token 保持失效
        # 但需 rollback 防止半状态（new_tokens 已 add 但应被丢弃）
        await db.rollback()
        if wants_json:
            return JSONResponse(
                {"error": e.code, "message": str(e)},
                status_code=status_code,
            )
        return _render_error_negotiated(request, str(e), status_code)

    # ── 6. audit_log action='hitl.delegate' ────────────────────────────
    audit = AuditLog(
        workspace_id=flow_instance.workspace_id,
        actor_user_id=actor_id,
        action="hitl.delegate",
        target_type="node_state",
        target_id=node_state_id,
        actor_ip=ip,
        actor_ua=ua,
        decision="delegate",
        node_state_id=node_state_id,
        meta={
            "jti": str(jti),
            "instance_id": str(instance_id),
            "from_actor": str(actor_id),
            "from_email": from_user.email,
            "to_email": str(delegate_req.to_email),
            "to_actor": str(new_tokens[0].actor_id) if new_tokens else None,
            "depth": depth,
            "reason": delegate_req.reason,
            "new_token_count": len(new_tokens),
        },
    )
    db.add(audit)

    # ── 7. structured log（Phase 7 Run Viewer 钩子）────────────────────
    to_user_id_str = str(new_tokens[0].actor_id) if new_tokens else None
    log.info(
        "hitl.chain.delegate",
        extra={
            "from_user_id": str(actor_id),
            "to_user_id": to_user_id_str,
            "depth": depth,
            "instance_id": str(instance_id),
            "node_state_id": str(node_state_id),
            "new_token_count": len(new_tokens),
        },
    )

    # ── 8. commit 事务（advisory_lock 在此刻释放）─────────────────────
    await db.commit()

    # ── 9. 响应 ────────────────────────────────────────────────────────
    response_body = DelegateResponse(
        ok=True,
        new_token_count=len(new_tokens),
        depth=depth,
        recipient_email=str(delegate_req.to_email),
        instance_id=str(instance_id),
    )
    if wants_json:
        return JSONResponse(
            response_body.model_dump(),
            status_code=status.HTTP_201_CREATED,
        )
    # HTML 客户端（邮件直连）返回简单成功页
    return templates.TemplateResponse(
        "success.html",
        {
            "request": request,
            "action": "delegate",
            "instance_id": instance_id,
            "new_node_status": "delegated",
            "recipient_email": str(delegate_req.to_email),
        },
        status_code=status.HTTP_201_CREATED,
    )
