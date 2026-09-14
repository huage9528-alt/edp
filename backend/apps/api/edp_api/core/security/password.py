"""Argon2id 密码哈希与校验（argon2-cffi，默认参数即 Argon2id）。"""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """生成 Argon2id 哈希（随机盐，$argon2id$ 前缀）。"""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """校验密码与哈希是否匹配；不匹配（VerifyMismatchError）返回 False。"""
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
