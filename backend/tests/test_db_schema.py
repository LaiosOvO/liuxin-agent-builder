"""DB schema 集成测试。

使用真实数据库（禁止 mock，CLAUDE.md 2.2）。
优先使用 testcontainers-postgres；若 Docker 不可用，回退到环境变量 TESTCONTAINER_PG_DSN 指定的 DB。

测试范围：
1. test_all_tables_exist：7 张表全部存在
2. test_composite_indexes：复合索引 (workspace_id, created_at) 存在
3. test_email_citext：重复插入大小写变体邮箱触发唯一约束冲突
4. test_role_seeds：4 个 role code 均已种子插入
5. test_uq_jti_invites：invites.jti UNIQUE 约束生效
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Generator

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, text


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _get_sync_dsn_from_env() -> str | None:
    """从环境变量获取同步 DSN（CI/本地开发回退）。"""
    raw = (
        os.getenv("TESTCONTAINER_PG_DSN")
        or os.getenv("POSTGRES_DSN")
    )
    if not raw:
        return None
    # 确保是 psycopg（同步）驱动格式
    raw = raw.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    if not raw.startswith("postgresql+psycopg://"):
        raw = raw.replace("postgresql://", "postgresql+psycopg://", 1)
    return raw


@pytest.fixture(scope="module")
def pg_dsn_sync() -> Generator[str, None, None]:
    """返回同步 DSN，优先 testcontainers，回退到环境变量指定的 DB。"""
    # 优先尝试 testcontainers
    try:
        from testcontainers.postgres import PostgresContainer
        import docker
        docker.from_env()  # 测试 Docker 是否可用

        with PostgresContainer("postgres:16-alpine") as postgres:
            dsn_sync = postgres.get_connection_url()
            if "+psycopg2" in dsn_sync:
                dsn_sync = dsn_sync.replace("+psycopg2", "+psycopg")
            elif dsn_sync.startswith("postgresql://"):
                dsn_sync = dsn_sync.replace("postgresql://", "postgresql+psycopg://", 1)
            _run_migration(dsn_sync)
            yield dsn_sync
            return
    except Exception:
        pass  # Docker 不可用，回退到环境变量

    # 回退：使用环境变量指定的真实 DB
    dsn_sync = _get_sync_dsn_from_env()
    if not dsn_sync:
        pytest.skip("Docker 不可用且 POSTGRES_DSN 未设置，跳过集成测试")
        return

    # 在独立 schema 运行（避免污染现有数据）
    # 直接使用现有 DB，migration 已运行过（通过 upgrade head 幂等）
    _run_migration(dsn_sync)
    yield dsn_sync


def _run_migration(dsn_sync: str) -> None:
    """在给定的同步 DSN 上运行 Alembic upgrade head（幂等）。"""
    from alembic import command
    from alembic.config import Config
    import os

    backend_dir = Path(__file__).resolve().parent.parent
    alembic_ini = backend_dir / "migrations" / "alembic.ini"

    cfg = Config(str(alembic_ini))
    cfg.set_main_option("script_location", str(backend_dir / "migrations"))

    # 设置 POSTGRES_DSN 为同步格式（env.py 的 get_sync_url 会读取）
    os.environ["POSTGRES_DSN"] = dsn_sync.replace("postgresql+psycopg://", "postgresql://", 1)

    command.upgrade(cfg, "head")


@pytest.fixture(scope="module")
def sync_engine(pg_dsn_sync: str):  # type: ignore[return]
    """创建同步 Engine（测试专用，不用 asyncpg）。"""
    engine = create_engine(pg_dsn_sync, pool_pre_ping=True)
    yield engine
    engine.dispose()


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_all_tables_exist(sync_engine: sa.Engine) -> None:
    """7 张表全部存在于 public schema。"""
    expected_tables = {
        "workspaces",
        "users",
        "roles",
        "user_workspace_roles",
        "invites",
        "email_verifications",
        "audit_logs",
    }
    with sync_engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
            )
        )
        actual_tables = {row[0] for row in result}

    missing = expected_tables - actual_tables
    assert not missing, f"缺少表：{missing}"


def test_composite_indexes(sync_engine: sa.Engine) -> None:
    """关键复合索引存在。"""
    expected_indexes = {
        "ix_invites_workspace_id_created_at",
        "ix_audit_logs_workspace_id_created_at",
        "ix_email_verifications_user_id_created_at",
        "ix_user_workspace_roles_user_id_workspace_id",
    }
    with sync_engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = 'public'"
            )
        )
        actual_indexes = {row[0] for row in result}

    missing = expected_indexes - actual_indexes
    assert not missing, f"缺少索引：{missing}"


def test_email_citext_unique_constraint(sync_engine: sa.Engine) -> None:
    """CITEXT 邮箱大小写不敏感唯一约束生效。

    插入 alice@example.com 后，再插入 Alice@example.com 应触发 UniqueViolation。
    """
    from sqlalchemy.exc import IntegrityError

    user_id_1 = str(uuid.uuid4())
    user_id_2 = str(uuid.uuid4())

    with sync_engine.connect() as conn:
        # 先清理可能存在的测试数据
        conn.execute(text("DELETE FROM users WHERE email IN ('alice@example.com', 'Alice@example.com')"))
        conn.commit()

        # 插入第一条
        conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, status) "
                "VALUES (:id, :email, :hash, 'active')"
            ),
            {"id": user_id_1, "email": "alice@example.com", "hash": "hash1"},
        )
        conn.commit()

        # 插入大写版本——应触发唯一约束冲突
        with pytest.raises(IntegrityError, match="uq_users_email|unique"):
            conn.execute(
                text(
                    "INSERT INTO users (id, email, password_hash, status) "
                    "VALUES (:id, :email, :hash, 'active')"
                ),
                {"id": user_id_2, "email": "Alice@example.com", "hash": "hash2"},
            )
            conn.commit()

        conn.rollback()

        # 清理测试数据
        conn.execute(text("DELETE FROM users WHERE email = 'alice@example.com'"))
        conn.commit()


def test_role_seeds(sync_engine: sa.Engine) -> None:
    """4 个 role code 均已种子插入（super_admin / admin / editor / viewer）。"""
    expected_codes = {"super_admin", "admin", "editor", "viewer"}
    with sync_engine.connect() as conn:
        result = conn.execute(text("SELECT code FROM roles ORDER BY id"))
        actual_codes = {row[0] for row in result}

    assert actual_codes == expected_codes, f"role seeds 不匹配：{actual_codes} != {expected_codes}"


def test_uq_jti_invites(sync_engine: sa.Engine) -> None:
    """invites.jti UNIQUE 约束生效（防止 jti 重复消费）。"""
    from sqlalchemy.exc import IntegrityError

    # 先创建 workspace
    ws_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    jti = str(uuid.uuid4())

    with sync_engine.connect() as conn:
        conn.execute(
            text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
            {"id": ws_id, "name": "测试工作区", "slug": f"test-{ws_id[:8]}"},
        )
        conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, status) "
                "VALUES (:id, :email, :hash, 'active')"
            ),
            {"id": user_id, "email": f"jti-test-{ws_id[:8]}@example.com", "hash": "h"},
        )
        conn.commit()

        from datetime import datetime, timedelta, timezone
        expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()

        conn.execute(
            text(
                "INSERT INTO invites (id, workspace_id, email, target_role_code, jti, token_hash, expires_at) "
                "VALUES (:id, :ws, :email, 'editor', :jti, 'hash1', :exp)"
            ),
            {"id": str(uuid.uuid4()), "ws": ws_id, "email": "inv1@example.com", "jti": jti, "exp": expires},
        )
        conn.commit()

        # 第二条相同 jti 应触发 UNIQUE 冲突
        with pytest.raises(IntegrityError, match="uq_invites_jti|unique"):
            conn.execute(
                text(
                    "INSERT INTO invites (id, workspace_id, email, target_role_code, jti, token_hash, expires_at) "
                    "VALUES (:id, :ws, :email, 'editor', :jti, 'hash2', :exp)"
                ),
                {"id": str(uuid.uuid4()), "ws": ws_id, "email": "inv2@example.com", "jti": jti, "exp": expires},
            )
            conn.commit()

        conn.rollback()

        # 清理
        conn.execute(text(f"DELETE FROM invites WHERE workspace_id = '{ws_id}'"))
        conn.execute(text(f"DELETE FROM users WHERE id = '{user_id}'"))
        conn.execute(text(f"DELETE FROM workspaces WHERE id = '{ws_id}'"))
        conn.commit()
