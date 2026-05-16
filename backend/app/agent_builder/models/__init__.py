"""agent-builder ORM 模型包。

导入所有模型，使 Alembic metadata 能发现全部表定义。

使用示例：
    from app.agent_builder.models import Workspace, User, Role, ...
    from app.agent_builder.models import Base  # 用于 Alembic env.py
"""
from app.agent_builder.db.base import Base  # noqa: F401 — 确保 metadata 已创建
from app.agent_builder.models.workspace import Workspace
from app.agent_builder.models.user import User, UserStatus
from app.agent_builder.models.role import Role, RoleCode
from app.agent_builder.models.user_workspace_role import UserWorkspaceRole
from app.agent_builder.models.invite import Invite
from app.agent_builder.models.email_verification import EmailVerification
from app.agent_builder.models.audit_log import AuditLog

__all__ = [
    "Base",
    "Workspace",
    "User",
    "UserStatus",
    "Role",
    "RoleCode",
    "UserWorkspaceRole",
    "Invite",
    "EmailVerification",
    "AuditLog",
]
