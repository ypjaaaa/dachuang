"""用户表(SQLite,stdlib sqlite3):注册/登录/角色/禁用等

表结构:
  users(id INTEGER PK, username UNIQUE, password_hash, role, disabled, created_at)

首次建库时自动创建默认管理员(config.DEFAULT_ADMIN_USERNAME / DEFAULT_ADMIN_PASSWORD),
可在项目根目录 .env 里用 ADMIN_USERNAME / ADMIN_PASSWORD 覆盖。
"""
import sqlite3
from datetime import datetime

from . import config
from .auth import hash_password, validate_password, validate_username, verify_password

ROLE_ADMIN = "admin"
ROLE_USER = "user"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'user',
    disabled      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);
"""


def _conn() -> sqlite3.Connection:
    config.USER_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(config.USER_DB), timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(_SCHEMA)
    con.commit()
    return con


def _row_to_dict(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    d["disabled"] = bool(d["disabled"])
    return d


# ================= 建库 / 默认管理员 =================

def ensure_admin():
    """用户表为空或没有管理员时,创建默认管理员(不覆盖已有密码)"""
    con = _conn()
    try:
        n = con.execute("SELECT COUNT(*) FROM users WHERE role=?", (ROLE_ADMIN,)).fetchone()[0]
        if n == 0:
            con.execute(
                "INSERT INTO users(username, password_hash, role, disabled, created_at) VALUES (?,?,?,0,?)",
                (config.DEFAULT_ADMIN_USERNAME,
                 hash_password(config.DEFAULT_ADMIN_PASSWORD),
                 ROLE_ADMIN,
                 datetime.now().isoformat(timespec="seconds")),
            )
            con.commit()
            print(f"[auth] 已创建默认管理员: {config.DEFAULT_ADMIN_USERNAME}"
                  f"(密码 {config.DEFAULT_ADMIN_PASSWORD}, 请尽快登录后修改)")
    finally:
        con.close()


# ================= 基础 CRUD =================

def create_user(username: str, password: str, role: str = ROLE_USER) -> dict:
    """注册用户;重名抛 ValueError"""
    username = validate_username(username)
    password = validate_password(password)
    if get_user_by_name(username):
        raise ValueError("用户名已被注册")
    con = _conn()
    try:
        cur = con.execute(
            "INSERT INTO users(username, password_hash, role, disabled, created_at) VALUES (?,?,?,0,?)",
            (username, hash_password(password), role, datetime.now().isoformat(timespec="seconds")),
        )
        con.commit()
        return get_user_by_id(cur.lastrowid)
    finally:
        con.close()


def get_user_by_name(username: str) -> dict | None:
    con = _conn()
    try:
        return _row_to_dict(con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone())
    finally:
        con.close()


def get_user_by_id(uid: int) -> dict | None:
    con = _conn()
    try:
        return _row_to_dict(con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
    finally:
        con.close()


def authenticate(username: str, password: str) -> dict | None:
    """校验登录;用户名/密码错、被禁用均返回 None"""
    user = get_user_by_name((username or "").strip())
    if not user or user["disabled"]:
        return None
    if not verify_password(password or "", user["password_hash"]):
        return None
    return user


def list_users() -> list[dict]:
    con = _conn()
    try:
        rows = con.execute("SELECT * FROM users ORDER BY id").fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        con.close()


def count_admins() -> int:
    con = _conn()
    try:
        return con.execute("SELECT COUNT(*) FROM users WHERE role=? AND disabled=0",
                           (ROLE_ADMIN,)).fetchone()[0]
    finally:
        con.close()


def set_disabled(uid: int, disabled: bool):
    con = _conn()
    try:
        con.execute("UPDATE users SET disabled=? WHERE id=?", (1 if disabled else 0, uid))
        con.commit()
    finally:
        con.close()


def set_role(uid: int, role: str):
    if role not in (ROLE_ADMIN, ROLE_USER):
        raise ValueError("角色只能是 admin 或 user")
    con = _conn()
    try:
        con.execute("UPDATE users SET role=? WHERE id=?", (role, uid))
        con.commit()
    finally:
        con.close()


def set_password(uid: int, new_password: str):
    new_password = validate_password(new_password)
    con = _conn()
    try:
        con.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new_password), uid))
        con.commit()
    finally:
        con.close()


def delete_user(uid: int):
    con = _conn()
    try:
        con.execute("DELETE FROM users WHERE id=?", (uid,))
        con.commit()
    finally:
        con.close()
