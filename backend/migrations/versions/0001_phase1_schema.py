"""Phase 1 数据库 schema 初始化。

7 张表：workspaces / users / roles / user_workspace_roles /
        invites / email_verifications / audit_logs

包含：
- CREATE EXTENSION IF NOT EXISTS "uuid-ossp" / citext / pgcrypto / pg_trgm
- 7 张表建表 SQL（含 workspace_id 复合索引）
- 全部外键约束
- roles 种子数据（4 条）
- downgrade() 完整反向

Revision ID: 0001
Revises: None
Create Date: 2026-05-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建所有表、索引、外键，并插入种子数据。"""

    # ── 扩展 ──────────────────────────────────────────────────────────────────
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # ── 1. workspaces ─────────────────────────────────────────────────────────
    op.create_table(
        "workspaces",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            comment="工作区主键",
        ),
        sa.Column("name", sa.String(120), nullable=False, comment="工作区显示名称"),
        sa.Column("slug", sa.String(60), nullable=False, comment="URL 友好标识符，全局唯一"),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="创建者 user_id（首次 setup 时为 NULL）",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("slug", name="uq_workspaces_slug"),
        sa.PrimaryKeyConstraint("id", name="pk_workspaces"),
    )

    # ── 2. users ──────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            comment="用户主键",
        ),
        sa.Column(
            "email",
            postgresql.CITEXT(),
            nullable=False,
            comment="邮箱（CITEXT 大小写不敏感唯一约束）",
        ),
        sa.Column("password_hash", sa.String(255), nullable=False, comment="argon2 哈希密码"),
        sa.Column("display_name", sa.String(120), nullable=True, comment="显示名称"),
        sa.Column("department", sa.String(120), nullable=True, comment="所属部门"),
        sa.Column(
            "status",
            sa.String(30),
            nullable=False,
            server_default="pending_verification",
            comment="用户状态",
        ),
        sa.Column(
            "is_super_admin",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="是否平台级超级管理员",
        ),
        sa.Column(
            "im_bindings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            server_default="{}",
            comment="IM 账号绑定信息",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )

    # ── 3. roles（静态种子表）────────────────────────────────────────────────
    op.create_table(
        "roles",
        sa.Column("id", sa.SmallInteger(), primary_key=True, comment="角色 ID（SMALLINT）"),
        sa.Column("code", sa.String(20), nullable=False, comment="角色代码"),
        sa.Column("description", sa.String(255), nullable=True, comment="角色描述"),
        sa.UniqueConstraint("code", name="uq_roles_code"),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
    )

    # 种子数据（4 条；external 不入此表）
    op.execute(
        """
        INSERT INTO roles (id, code, description) VALUES
            (1, 'super_admin', '平台级超级管理员，仅 setup 阶段创建，可跨 workspace 查看'),
            (2, 'admin',       '工作区级管理员，可邀请成员、管理工作区设置'),
            (3, 'editor',      '工作区编辑者，可创建/编辑/发布工作流'),
            (4, 'viewer',      '只读用户，仅查看工作流和实例，不可启动')
        """
    )

    # ── 4. user_workspace_roles ───────────────────────────────────────────────
    op.create_table(
        "user_workspace_roles",
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="工作区 ID（复合 PK 第一列）",
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="用户 ID（复合 PK 第二列）",
        ),
        sa.Column("role_id", sa.SmallInteger(), nullable=False, comment="角色 ID"),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_user_workspace_roles_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_workspace_roles_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name="fk_user_workspace_roles_role_id_roles",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "user_id", name="pk_user_workspace_roles"),
    )
    op.create_index(
        "ix_user_workspace_roles_user_id_workspace_id",
        "user_workspace_roles",
        ["user_id", "workspace_id"],
    )

    # ── 5. invites ────────────────────────────────────────────────────────────
    op.create_table(
        "invites",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="目标工作区 ID（业务表首列，满足多租户索引规则）",
        ),
        sa.Column("email", postgresql.CITEXT(), nullable=False, comment="被邀请人邮箱"),
        sa.Column("target_role_code", sa.String(20), nullable=False, comment="目标角色代码"),
        sa.Column(
            "jti",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="JWT jti（一次性消费 ID）",
        ),
        sa.Column("token_hash", sa.String(128), nullable=False, comment="JWT 哈希（审计用）"),
        sa.Column("invited_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_invites_workspace_id_workspaces",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by"],
            ["users.id"],
            name="fk_invites_invited_by_users",
        ),
        sa.UniqueConstraint("jti", name="uq_invites_jti"),
        sa.PrimaryKeyConstraint("id", name="pk_invites"),
    )
    op.create_index(
        "ix_invites_workspace_id_created_at",
        "invites",
        ["workspace_id", "created_at"],
    )
    op.create_index(
        "ix_invites_email_workspace_id",
        "invites",
        ["email", "workspace_id"],
    )

    # ── 6. email_verifications ────────────────────────────────────────────────
    op.create_table(
        "email_verifications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="目标用户 ID",
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="关联工作区（setup super_admin 为 NULL）",
        ),
        sa.Column(
            "jti",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="JWT jti（一次性消费 ID）",
        ),
        sa.Column("token_hash", sa.String(128), nullable=False, comment="JWT 哈希（审计用）"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_email_verifications_user_id_users",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("jti", name="uq_email_verifications_jti"),
        sa.PrimaryKeyConstraint("id", name="pk_email_verifications"),
    )
    op.create_index(
        "ix_email_verifications_user_id_created_at",
        "email_verifications",
        ["user_id", "created_at"],
    )

    # ── 7. audit_logs ─────────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column(
            "id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
            comment="自增审计日志 ID（BIGSERIAL）",
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="工作区 ID（系统级事件为 NULL）",
        ),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "actor_meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            server_default="{}",
        ),
        sa.Column("action", sa.String(80), nullable=False, comment="操作类型"),
        sa.Column("target_type", sa.String(40), nullable=True),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            server_default="{}",
        ),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
    )
    op.create_index(
        "ix_audit_logs_workspace_id_created_at",
        "audit_logs",
        ["workspace_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_audit_logs_actor_user_id_created_at",
        "audit_logs",
        ["actor_user_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_audit_logs_action_created_at",
        "audit_logs",
        ["action", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    """删除所有表（顺序与 upgrade 相反，遵从外键依赖关系）。"""

    # 删除有依赖关系的表（先删子表）
    op.drop_table("audit_logs")
    op.drop_table("email_verifications")
    op.drop_table("invites")
    op.drop_table("user_workspace_roles")
    op.drop_table("roles")
    op.drop_table("users")
    op.drop_table("workspaces")

    # 扩展保留（DROP EXTENSION 可能影响其他依赖），
    # 仅在测试环境完全清理时使用
    # op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    # op.execute("DROP EXTENSION IF EXISTS pgcrypto")
    # op.execute("DROP EXTENSION IF EXISTS citext")
    # op.execute('DROP EXTENSION IF EXISTS "uuid-ossp"')
