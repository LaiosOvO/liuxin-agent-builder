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

# Phase 2 工作流相关模型（4 张新表）
from app.agent_builder.models.workflow import Workflow
from app.agent_builder.models.workflow_version import WorkflowVersion
from app.agent_builder.models.flow_instance import FlowInstance
from app.agent_builder.models.node_state import NodeState

# Phase 3 HITL + Notification 模型（2 张新表 + audit_log NET-05 alter）
from app.agent_builder.models.hitl_token import HitlToken
from app.agent_builder.models.notification import Notification

# Phase 5.A PlatformPlugin 框架（per-workspace 安装态）
from app.agent_builder.models.workspace_plugin_installation import WorkspacePluginInstallation

__all__ = [
    "Base",
    # Phase 1 模型
    "Workspace",
    "User",
    "UserStatus",
    "Role",
    "RoleCode",
    "UserWorkspaceRole",
    "Invite",
    "EmailVerification",
    "AuditLog",
    # Phase 2 工作流模型
    "Workflow",
    "WorkflowVersion",
    "FlowInstance",
    "NodeState",
    # Phase 3 HITL 模型
    "HitlToken",
    "Notification",
    # Phase 5.A PlatformPlugin 框架
    "WorkspacePluginInstallation",
]
