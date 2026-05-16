"""密码服务单元测试。

覆盖：
- hash_password / verify_password 正反向
- validate_password_strength 全规则
- verify_and_update_password rehash 检测
"""
from __future__ import annotations

import pytest

from app.services.password import (
    hash_password,
    validate_password_strength,
    verify_and_update_password,
    verify_password,
)


class TestHashAndVerify:
    """密码哈希与验证测试。"""

    def test_hash_returns_string(self):
        """hash_password 返回非空字符串。"""
        hashed = hash_password("Password123")
        assert isinstance(hashed, str)
        assert len(hashed) > 0

    def test_hash_not_plaintext(self):
        """哈希结果不是明文密码。"""
        plain = "Password123"
        hashed = hash_password(plain)
        assert plain not in hashed

    def test_verify_correct_password(self):
        """正确密码验证返回 True。"""
        plain = "MySecurePass99"
        hashed = hash_password(plain)
        assert verify_password(plain, hashed) is True

    def test_verify_wrong_password(self):
        """错误密码验证返回 False。"""
        hashed = hash_password("CorrectPass1")
        assert verify_password("WrongPass2", hashed) is False

    def test_verify_empty_password(self):
        """空密码验证返回 False。"""
        hashed = hash_password("SomePass1")
        assert verify_password("", hashed) is False

    def test_two_hashes_differ(self):
        """相同明文哈希两次结果不同（argon2 加 salt）。"""
        plain = "SamePassword1"
        hash1 = hash_password(plain)
        hash2 = hash_password(plain)
        assert hash1 != hash2

    def test_verify_case_sensitive(self):
        """密码大小写敏感。"""
        hashed = hash_password("Password123")
        assert verify_password("password123", hashed) is False

    def test_verify_invalid_hash(self):
        """非法哈希字符串返回 False（不抛异常）。"""
        assert verify_password("Password123", "invalid_hash_string") is False


class TestPasswordStrength:
    """密码强度校验测试。"""

    def test_valid_password_returns_empty(self):
        """合法密码返回空错误列表。"""
        errors = validate_password_strength("SecurePass1")
        assert errors == []

    def test_password_too_short(self):
        """密码长度不足 8 位。"""
        errors = validate_password_strength("Ab1")
        assert any("8" in e for e in errors)

    def test_exactly_8_chars_passes(self):
        """恰好 8 位通过（含字母和数字）。"""
        errors = validate_password_strength("Abcdef12")
        assert errors == []

    def test_no_digit_fails(self):
        """无数字不通过。"""
        errors = validate_password_strength("OnlyLetters")
        assert any("数字" in e for e in errors)

    def test_no_letter_fails(self):
        """无字母不通过。"""
        errors = validate_password_strength("12345678")
        assert any("字母" in e for e in errors)

    def test_only_special_chars_fails(self):
        """纯特殊字符（无字母无数字）不通过。"""
        errors = validate_password_strength("!@#$%^&*()")
        assert len(errors) > 0

    def test_no_max_length_restriction(self):
        """密码无最大长度限制（100 字符通过）。"""
        long_password = "Aa1" + "x" * 97
        errors = validate_password_strength(long_password)
        assert errors == []

    def test_chinese_character_with_digits(self):
        """含中文字符 + 数字通过（字母类包含 Unicode 字母）。"""
        errors = validate_password_strength("密码Password1")
        assert errors == []

    def test_multiple_errors_returned(self):
        """多个错误同时返回。"""
        errors = validate_password_strength("12")  # 太短 + 无字母
        assert len(errors) >= 2


class TestVerifyAndUpdate:
    """verify_and_update_password 测试（rehash 检测）。"""

    def test_correct_password_returns_true(self):
        """正确密码返回 (True, None 或 new_hash)。"""
        plain = "TestPass1"
        hashed = hash_password(plain)
        ok, new_hash = verify_and_update_password(plain, hashed)
        assert ok is True

    def test_wrong_password_returns_false(self):
        """错误密码返回 (False, None)。"""
        hashed = hash_password("CorrectPass1")
        ok, new_hash = verify_and_update_password("WrongPass2", hashed)
        assert ok is False
        assert new_hash is None

    def test_invalid_hash_returns_false(self):
        """非法哈希不抛异常，返回 (False, None)。"""
        ok, new_hash = verify_and_update_password("SomePass1", "not_a_real_hash")
        assert ok is False
        assert new_hash is None
