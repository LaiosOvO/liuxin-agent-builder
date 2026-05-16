"""DeclarativeBase + naming convention + metadata。

命名约定使 Alembic autogenerate 产生稳定的约束名，
便于 migration 文件跨数据库比对。
"""
from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# 标准命名约定，与 Alembic 自动生成的约束名保持一致
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}


class Base(DeclarativeBase):
    """agent-builder ORM 基类。

    所有 agent_builder 模型均继承此类，
    与 flock 原有 SQLModel 元数据完全独立。
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
