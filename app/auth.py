"""用户认证:密码哈希 + 无第三方依赖的签名令牌

- 密码:PBKDF2-HMAC-SHA256(每用户随机盐,迭代 260k,stdlib hashlib,无外部依赖)
- 令牌:HMAC-SHA256 签名的 {payload}.{signature}(与 JWT 思路一致),
  签名密钥来自 config.get_auth_secret()(AUTH_SECRET_KEY 或 data/.secret_key)
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from . import config

_PBKDF2_ITER = 260_000
_TOKEN_TTL = max(1, config.ACCESS_TOKEN_EXPIRE_MINUTES) * 60


# ================= 密码哈希 =================

def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_password(password: str) -> str:
    """返回可存储的哈希串: pbkdf2_sha256$iter$salt$hash"""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITER)
    return f"pbkdf2_sha256${_PBKDF2_ITER}${_b64e(salt)}${_b64e(dk)}"


def verify_password(password: str, stored: str) -> bool:
    """校验密码(常量时间比较)"""
    try:
        algo, iter_s, salt_s, hash_s = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        salt = _b64d(salt_s)
        expected = _b64d(hash_s)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iter_s))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


# ================= 签名令牌(HMAC-SHA256) =================

def create_token(uid: int, username: str, role: str) -> str:
    """签发令牌,载荷含 uid/username/role/exp"""
    payload = {
        "uid": uid,
        "username": username,
        "role": role,
        "exp": int(time.time()) + _TOKEN_TTL,
    }
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64e(hmac.new(config.get_auth_secret().encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def decode_token(token: str) -> dict | None:
    """校验并解析令牌;无效/过期返回 None"""
    try:
        body, sig = (token or "").split(".", 1)
        secret = config.get_auth_secret().encode("utf-8")
        expect = _b64e(hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(expect, sig):
            return None
        payload = json.loads(_b64d(body).decode("utf-8"))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


# ================= 输入校验 =================

def validate_username(name: str) -> str:
    name = (name or "").strip()
    if not (2 <= len(name) <= 32):
        raise ValueError("用户名长度需为 2-32 个字符")
    if not all(c.isalnum() or c in "_-." for c in name):
        raise ValueError("用户名只能包含字母、数字、下划线、横线或点")
    return name


def validate_password(pw: str) -> str:
    if not isinstance(pw, str) or not (6 <= len(pw) <= 64):
        raise ValueError("密码长度需为 6-64 个字符")
    return pw
