"""首启 Setup 流程服务。

首次启动时检测 super_admin 是否存在：
- 未初始化（is_setup_complete=False）→ 中间件阻断所有非 setup 路由
- 初始化（initialize_first_admin 调用成功）→ 缓存 _setup_complete=True

DB 查询：SELECT EXISTS(SELECT 1 FROM users WHERE is_super_admin=TRUE LIMIT 1)
缓存：module-level _setup_complete（进程内，重启后重查 DB）
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import exists, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_builder.models.user import User, UserStatus
from app.agent_builder.models.workspace import Workspace
from app.services import audit as audit_service
from app.services.password import hash_password, validate_password_strength

log = logging.getLogger(__name__)

# ── 进程内缓存（避免每请求查 DB）────────────────────────────────────────────────
_setup_complete: bool | None = None  # None 表示尚未查询


async def is_setup_complete(db: AsyncSession) -> bool:
    """检查系统是否已初始化（有 super_admin 用户）。

    首次调用查询 DB，后续使用进程内缓存。
    initialize_first_admin 成功后调用 mark_setup_complete() 更新缓存。

    Args:
        db: AsyncSession

    Returns:
        True 表示已初始化，False 表示未初始化
    """
    global _setup_complete

    if _setup_complete is not None:
        return _setup_complete

    # 查询是否存在 super_admin
    result = await db.execute(
        select(exists().where(User.is_super_admin.is_(True)))
    )
    exists_val = result.scalar()
    _setup_complete = bool(exists_val)
    return _setup_complete


def mark_setup_complete() -> None:
    """标记 setup 已完成（initialize_first_admin 成功后调用）。"""
    global _setup_complete
    _setup_complete = True


def reset_setup_cache() -> None:
    """重置进程内缓存（测试用）。"""
    global _setup_complete
    _setup_complete = None


async def initialize_first_admin(
    db: AsyncSession,
    email: str,
    password: str,
    display_name: str,
    workspace_name: str,
    request: Any = None,
) -> tuple[User, Workspace]:
    """创建第一个 super_admin 用户 + 第一个 workspace。

    在单个事务中完成：
    1. 校验密码强度
    2. 创建 super_admin User（status='active'，跳过邮箱验证）
    3. 创建第一个 Workspace
    4. 写 user_workspace_role（admin 角色）
    5. 写 audit_log（setup.created）
    6. 更新进程内缓存

    Args:
        db: AsyncSession（调用方的 session，统一 commit）
        email: 超级管理员邮箱
        password: 明文密码
        display_name: 超级管理员显示名
        workspace_name: 第一个工作区名称
        request: Request 对象（audit 提取 IP/UA）

    Returns:
        (User, Workspace) — 已创建的超级管理员和第一个工作区

    Raises:
        ValueError: 密码强度不足 / 邮箱已存在等
        RuntimeError: 系统已初始化（setup 已完成）
    """
    # 检查是否已经初始化
    if await is_setup_complete(db):
        raise RuntimeError("系统已初始化，无法重复执行 setup")

    # 校验密码强度
    errors = validate_password_strength(password)
    if errors:
        raise ValueError(f"密码强度不足：{'；'.join(errors)}")

    # 检查邮箱是否已存在
    existing = await db.execute(
        select(User).where(User.email == email.lower())
    )
    if existing.scalar_one_or_none() is not None:
        raise ValueError(f"邮箱 {email} 已被使用")

    # 1. 创建 super_admin 用户
    user = User(
        id=uuid.uuid4(),
        email=email.lower(),
        password_hash=hash_password(password),
        display_name=display_name,
        status=UserStatus.active.value,
        is_super_admin=True,
    )
    db.add(user)
    await db.flush()  # 获取 user.id

    # 2. 创建第一个 Workspace
    from app.agent_builder.models.workspace import Workspace

    slug = _generate_slug(workspace_name)
    workspace = Workspace(
        id=uuid.uuid4(),
        name=workspace_name,
        slug=slug,
        created_by=user.id,
    )
    db.add(workspace)
    await db.flush()  # 获取 workspace.id

    # 3. 绑定 user_workspace_role（admin）
    from app.agent_builder.models.user_workspace_role import UserWorkspaceRole

    # 查找 admin role ID（roles 表已在 migration 0001 种子化）
    from app.agent_builder.models.role import Role

    role_result = await db.execute(
        select(Role).where(Role.code == "admin")
    )
    admin_role = role_result.scalar_one_or_none()
    if admin_role is None:
        raise RuntimeError("roles 表缺少 admin 种子数据，请检查 migration 0001")

    uwr = UserWorkspaceRole(
        workspace_id=workspace.id,
        user_id=user.id,
        role_id=admin_role.id,
        granted_by=user.id,
    )
    db.add(uwr)

    # 4. 写 audit_log
    await audit_service.log(
        db,
        action="setup.created",
        workspace_id=workspace.id,
        actor_user_id=user.id,
        target_type="workspace",
        target_id=workspace.id,
        meta={
            "email": email,
            "workspace_name": workspace_name,
        },
        request=request,
    )

    # 5. 更新进程内缓存（在 commit 前标记，避免 commit 后查询重复触发）
    mark_setup_complete()

    log.info(
        "setup 初始化完成：super_admin=%s workspace=%s",
        email,
        workspace_name,
    )

    return user, workspace


def _generate_slug(name: str) -> str:
    """从工作区名称生成 URL-safe slug。

    简单规则：小写 + 空格变连字符 + 去除特殊字符 + 截断 60 字节。
    """
    import re

    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    slug = slug.strip("-")
    # 处理非 ASCII（中文等）：转为 hex 前缀
    try:
        slug.encode("ascii")
    except UnicodeEncodeError:
        # 中文名：用 uuid 前 8 位替代
        slug = str(uuid.uuid4())[:8]
    return slug[:60] or "workspace"
