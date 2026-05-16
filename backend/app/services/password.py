"""密码哈希与强度校验服务。

使用 pwdlib[argon2] 0.3.0 实现 argon2id 哈希：
- time_cost=2, memory_cost=65536, parallelism=4（安全默认值）
- 自动 detect & rehash legacy 哈希（v2 兼容）
- 强度校验：长度 ≥ 8、含字母与数字
"""
from __future__ import annotations

from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

# 实例化 PasswordHash（argon2id 参数与 CONTEXT.md 一致）
password_hash = PasswordHash(
    [
        Argon2Hasher(
            time_cost=2,
            memory_cost=65536,
            parallelism=4,
        )
    ]
)


def hash_password(plain: str) -> str:
    """将明文密码哈希为 argon2 格式字符串。

    Args:
        plain: 明文密码

    Returns:
        argon2 哈希字符串（可直接存入 users.password_hash）
    """
    return password_hash.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码是否匹配哈希值。

    如果哈希算法过时（pwdlib 自动 detect），内部触发 rehash，
    调用者需负责更新 DB 中的 password_hash 字段。

    Args:
        plain: 明文密码
        hashed: 数据库存储的哈希字符串

    Returns:
        True 表示匹配，False 表示不匹配
    """
    try:
        ok, new_hash = password_hash.verify_and_update(plain, hashed)
        return ok
    except Exception:
        return False


def verify_and_update_password(plain: str, hashed: str) -> tuple[bool, str | None]:
    """校验密码并在需要时返回新哈希（rehash 检测）。

    Args:
        plain: 明文密码
        hashed: 数据库存储的哈希字符串

    Returns:
        (is_valid, new_hash_or_none)
        - is_valid: 密码是否匹配
        - new_hash_or_none: 如果哈希算法过时需要更新，返回新哈希；否则返回 None
    """
    try:
        ok, new_hash = password_hash.verify_and_update(plain, hashed)
        return ok, new_hash
    except Exception:
        return False, None


def validate_password_strength(plain: str) -> list[str]:
    """校验密码强度，返回中文错误列表（空列表表示通过）。

    规则（CONTEXT.md）：
    - 长度 ≥ 8
    - 含字母（大写或小写均可）
    - 含数字
    - 不限最大长度
    - 不强制特殊字符

    Args:
        plain: 明文密码

    Returns:
        中文错误描述列表，空列表表示密码强度通过
    """
    errors: list[str] = []

    if len(plain) < 8:
        errors.append("密码长度不得少于 8 位")

    has_letter = any(c.isalpha() for c in plain)
    has_digit = any(c.isdigit() for c in plain)

    if not has_letter:
        errors.append("密码必须包含至少一个字母")

    if not has_digit:
        errors.append("密码必须包含至少一个数字")

    return errors
