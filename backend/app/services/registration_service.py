"""用户注册与邮箱验证服务。

注册流程（邀请制，公开注册关闭）：
1. 验证邮箱未注册
2. 哈希密码
3. 创建 User（status='pending_verification'）
4. 绑定 workspace 角色
5. 签发 EmailVerification token，存入 DB
6. 发送验证邮件
7. 写 audit_log('user.registered')

邮箱验证流程（GET 消费，见 auth.py 注释中的区分说明）：
1. decode_consume_jti('email_verifications') — GET 时消费（邮件链接点击即生效）
2. users.status -> 'active'
3. 写 audit_log('user.verified')
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_builder.models.email_verification import EmailVerification
from app.agent_builder.models.role import Role
from app.agent_builder.models.user import User, UserStatus
from app.agent_builder.models.user_workspace_role import UserWorkspaceRole
from app.services import audit as audit_service
from app.services.email_service import send_verification_email
from app.services.jwt_service import (
    TokenAlreadyUsedError,
    TokenExpired,
    TokenInvalid,
    compute_token_hash,
    decode_consume_jti,
    sign_email_verification,
)
from app.services.password import hash_password, validate_password_strength

log = logging.getLogger(__name__)


async def register_user(
    db: AsyncSession,
    email: str,
    password: str,
    display_name: str,
    workspace_id: uuid.UUID,
    role_code: str,
    department: str | None = None,
    invited_via_jti: uuid.UUID | None = None,
    request: Any = None,
) -> User:
    """创建新用户并发送邮箱验证邮件。

    Args:
        db: AsyncSession
        email: 用户邮箱
        password: 明文密码
        display_name: 显示名称
        workspace_id: 目标工作区 ID
        role_code: 目标角色代码（admin/editor/viewer）
        department: 所属部门（可选）
        invited_via_jti: 邀请 token jti（审计用）
        request: Request 对象

    Returns:
        创建的 User 对象（status='pending_verification'）

    Raises:
        ValueError: 密码强度不足 / 邮箱已注册 / 角色不存在
    """
    # 校验密码强度
    errors = validate_password_strength(password)
    if errors:
        raise ValueError(f"密码强度不足：{'；'.join(errors)}")

    # 检查邮箱是否已注册
    existing = await db.execute(
        select(User).where(User.email == email.lower())
    )
    if existing.scalar_one_or_none() is not None:
        raise ValueError(f"邮箱 {email} 已被注册")

    # 查找角色
    role_result = await db.execute(
        select(Role).where(Role.code == role_code)
    )
    role = role_result.scalar_one_or_none()
    if role is None:
        raise ValueError(f"角色 {role_code} 不存在")

    # 创建用户
    user = User(
        id=uuid.uuid4(),
        email=email.lower(),
        password_hash=hash_password(password),
        display_name=display_name,
        department=department,
        status=UserStatus.pending_verification.value,
        is_super_admin=False,
    )
    db.add(user)
    await db.flush()  # 获取 user.id

    # 绑定工作区角色
    uwr = UserWorkspaceRole(
        workspace_id=workspace_id,
        user_id=user.id,
        role_id=role.id,
        granted_by=None,  # 被邀请注册时，系统自动授权
    )
    db.add(uwr)

    # 签发邮箱验证 token
    token, jti = sign_email_verification(user.id, workspace_id)
    token_hash = compute_token_hash(token)

    import datetime

    from app.agent_builder.db.engine import async_session_maker

    now_utc = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    ev = EmailVerification(
        id=uuid.uuid4(),
        user_id=user.id,
        workspace_id=workspace_id,
        jti=jti,
        token_hash=token_hash,
        expires_at=now_utc + __import__("datetime").timedelta(hours=24),
    )
    db.add(ev)

    # 写 audit_log
    await audit_service.log(
        db,
        action="user.registered",
        workspace_id=workspace_id,
        actor_user_id=user.id,
        target_type="user",
        target_id=user.id,
        meta={
            "email": email,
            "role": role_code,
            "invited_via_jti": str(invited_via_jti) if invited_via_jti else None,
        },
        request=request,
    )

    await db.flush()  # 确保 ev 已写入

    # 发送验证邮件（不阻断主流程）
    base_url = os.environ.get("PUBLIC_BASE_URL", "http://localhost:3000")
    verification_url = f"{base_url}/auth/verify-email?token={token}"

    try:
        await send_verification_email(
            to=email,
            verification_url=verification_url,
            display_name=display_name,
            db=db,
            request=request,
        )
    except Exception as exc:
        log.warning("发送验证邮件失败（不影响注册）：%s", exc)

    return user


async def verify_email(
    db: AsyncSession,
    token: str,
    request: Any = None,
) -> User:
    """消费邮箱验证 token，激活用户。

    注意：此处 GET 触发邮件链接点击即消费 jti（与 HITL token 的 GET 不消费规则不同）。
    区别说明：
    - HITL token（Pitfall 3）：被 Safe Links 扫描器 GET → 不能消费，否则用户无法审批
    - 邮箱验证 token：链接点击 = 用户主动操作，GET 消费符合预期
    两类 token 的语义不同，此处 GET 消费是正确行为。

    Args:
        db: AsyncSession
        token: 邮箱验证 JWT 字符串
        request: Request 对象

    Returns:
        已激活的 User 对象

    Raises:
        TokenExpired: token 已过期
        TokenInvalid: token 无效
        TokenAlreadyUsedError: token 已被使用
    """
    # 消费 jti（原子更新 used_at）
    payload = await decode_consume_jti(
        token=token,
        table="email_verifications",
        db=db,
    )

    user_id = uuid.UUID(payload["sub"])

    # 加载用户
    user_result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        raise TokenInvalid(f"用户 {user_id} 不存在")

    # 激活用户
    user.status = UserStatus.active.value

    # 写 audit_log
    workspace_id_str = payload.get("workspace_id")
    workspace_id = uuid.UUID(workspace_id_str) if workspace_id_str else None

    await audit_service.log(
        db,
        action="user.verified",
        workspace_id=workspace_id,
        actor_user_id=user.id,
        target_type="user",
        target_id=user.id,
        request=request,
    )

    log.info("用户邮箱验证成功：%s", user.email)
    return user
