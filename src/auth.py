"""Люди, роли, группы, сессии и пароли.

Схема создаётся при первом обращении, не при импорте. В сессии только id человека.
"""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from settings import _root

GLOBAL_ACTIONS = (
    "manage_users",
    "manage_roles",
    "manage_groups",
    "manage_access",
    "create_kb",
    "view_audit",
)
CONTENT_ACTIONS = ("ask", "upload", "delete", "arrange")
KEEPER = ("manage_users", "manage_roles", "manage_access", "create_kb")
SESSION_HOURS = 12
_lock = threading.RLock()
_ready = set()
_BAD_LOGIN = re.compile(r"[/\\:\x00]")


def app_root():
    return _root()


def db_path():
    return app_root() / "data" / "auth.sqlite"


def _connect():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure():
    key = str(db_path())
    if key in _ready:
        return
    with _lock:
        if key in _ready:
            return
        conn = _connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS roles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS role_global (
                    role_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    PRIMARY KEY (role_id, action)
                );
                CREATE TABLE IF NOT EXISTS role_kb (
                    role_id TEXT NOT NULL,
                    kb_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    PRIMARY KEY (role_id, kb_id, action)
                );
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    login TEXT NOT NULL UNIQUE,
                    salt BLOB NOT NULL,
                    password BLOB NOT NULL,
                    role_id TEXT NOT NULL,
                    blocked INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created TEXT NOT NULL,
                    expires TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS groups (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS group_user (
                    group_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    PRIMARY KEY (group_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS group_role (
                    group_id TEXT NOT NULL,
                    role_id TEXT NOT NULL,
                    PRIMARY KEY (group_id, role_id)
                );
                CREATE TABLE IF NOT EXISTS kb (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    inbox TEXT NOT NULL,
                    chroma TEXT NOT NULL,
                    legacy INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS kb_acl (
                    kb_id TEXT NOT NULL,
                    subject_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    effect TEXT NOT NULL,
                    PRIMARY KEY (kb_id, subject_type, subject_id, effect)
                );
                CREATE TABLE IF NOT EXISTS user_kb (
                    user_id TEXT NOT NULL,
                    kb_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    PRIMARY KEY (user_id, kb_id, action)
                );
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            conn.commit()
        finally:
            conn.close()
        _ready.add(key)


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def _stamp(value):
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hash_password(password, salt=None):
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return salt, digest


def password_ok(password, salt, digest):
    salt, fresh = hash_password(password, salt)
    return hmac.compare_digest(fresh, digest)


def login_ok(login):
    text = str(login or "")
    return 1 <= len(text) <= 64 and not _BAD_LOGIN.search(text)


def origin_ok(origin):
    if not origin:
        return True
    host = origin.split("://", 1)[-1].split("/", 1)[0].split("@")[-1]
    host = host.rsplit(":", 1)[0].strip("[]").lower()
    return host in {"127.0.0.1", "localhost", "testserver"}


def count_users():
    ensure()
    conn = _connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()


def _role_actions(conn, role_id):
    rows = conn.execute("SELECT action FROM role_global WHERE role_id = ?", (role_id,)).fetchall()
    return [row["action"] for row in rows]


def user_view(row, conn):
    if row is None:
        return None
    role = conn.execute("SELECT name FROM roles WHERE id = ?", (row["role_id"],)).fetchone()
    return {
        "id": row["id"],
        "login": row["login"],
        "role_id": row["role_id"],
        "role": role["name"] if role else "",
        "blocked": bool(row["blocked"]),
        "actions": _role_actions(conn, row["role_id"]),
    }


def user_by_id(user_id):
    ensure()
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return user_view(row, conn)
    finally:
        conn.close()


def user_by_login(login):
    ensure()
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM users WHERE login = ?", (login,)).fetchone()
        return user_view(row, conn)
    finally:
        conn.close()


def _insert_role(conn, name, actions):
    role_id = secrets.token_hex(16)
    conn.execute("INSERT INTO roles (id, name) VALUES (?, ?)", (role_id, name))
    for action in actions:
        conn.execute("INSERT INTO role_global (role_id, action) VALUES (?, ?)", (role_id, action))
    return role_id


def setup(login, password):
    """Первый человек и роль «Администратор». Потом вызывать нельзя."""
    ensure()
    if not login_ok(login) or len(password or "") < 8:
        raise ValueError("bad-login")
    with _lock:
        conn = _connect()
        try:
            if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
                raise LookupError("exists")
            role_id = _insert_role(conn, "Администратор", GLOBAL_ACTIONS)
            user_id = secrets.token_hex(16)
            salt, digest = hash_password(password)
            conn.execute(
                "INSERT INTO users (id, login, salt, password, role_id, blocked) VALUES (?, ?, ?, ?, ?, 0)",
                (user_id, login, salt, digest, role_id),
            )
            conn.commit()
        finally:
            conn.close()
    return open_session(user_id)


def open_session(user_id):
    ensure()
    session_id = secrets.token_urlsafe(32)
    created = _now()
    expires = created + timedelta(hours=SESSION_HOURS)
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO sessions (id, user_id, created, expires) VALUES (?, ?, ?, ?)",
            (session_id, user_id, _stamp(created), _stamp(expires)),
        )
        conn.commit()
    finally:
        conn.close()
    return session_id


def drop_session(session_id):
    ensure()
    conn = _connect()
    try:
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
    finally:
        conn.close()


def drop_user_sessions(user_id, keep=None):
    ensure()
    conn = _connect()
    try:
        if keep:
            conn.execute("DELETE FROM sessions WHERE user_id = ? AND id != ?", (user_id, keep))
        else:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def user_by_session(session_id):
    ensure()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT users.*, sessions.expires FROM sessions JOIN users ON users.id = sessions.user_id WHERE sessions.id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        expires = datetime.strptime(row["expires"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if expires <= _now():
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()
            return None
        if row["blocked"]:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
            conn.commit()
            return None
        return user_view(row, conn)
    finally:
        conn.close()


def authenticate(login, password):
    """Вернуть (user, error). error: missing, blocked."""
    ensure()
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM users WHERE login = ?", (login,)).fetchone()
        if row is None or not password_ok(password, row["salt"], row["password"]):
            return None, "missing"
        if row["blocked"]:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
            conn.commit()
            return user_view(row, conn), "blocked"
        return user_view(row, conn), ""
    finally:
        conn.close()


def change_password(user_id, old, new, session_id=None):
    ensure()
    if len(new or "") < 8:
        raise ValueError("short")
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None or not password_ok(old, row["salt"], row["password"]):
            raise PermissionError("old")
        salt, digest = hash_password(new)
        conn.execute("UPDATE users SET salt = ?, password = ? WHERE id = ?", (salt, digest, user_id))
        conn.commit()
    finally:
        conn.close()
    drop_user_sessions(user_id, keep=session_id)


def set_password(user_id, new):
    ensure()
    if len(new or "") < 8:
        raise ValueError("short")
    salt, digest = hash_password(new)
    conn = _connect()
    try:
        conn.execute("UPDATE users SET salt = ?, password = ? WHERE id = ?", (salt, digest, user_id))
        conn.commit()
    finally:
        conn.close()
    drop_user_sessions(user_id)


def list_users():
    ensure()
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM users ORDER BY login").fetchall()
        return [user_view(row, conn) for row in rows]
    finally:
        conn.close()


def keepers():
    ensure()
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM users WHERE blocked = 0").fetchall()
        found = []
        for row in rows:
            actions = set(_role_actions(conn, row["role_id"]))
            if set(KEEPER) <= actions:
                found.append(row["id"])
        return found
    finally:
        conn.close()


def _would_keep(conn, user_id, role_id=None, blocked=None):
    rows = conn.execute("SELECT * FROM users WHERE blocked = 0").fetchall()
    count = 0
    for row in rows:
        if row["id"] == user_id:
            if blocked:
                continue
            current_role = role_id or row["role_id"]
        else:
            current_role = row["role_id"]
        actions = set(_role_actions(conn, current_role))
        if set(KEEPER) <= actions:
            count += 1
    return count > 0


def create_user(login, password, role_id):
    ensure()
    if not login_ok(login) or len(password or "") < 8 or not role_id:
        raise ValueError("bad")
    user_id = secrets.token_hex(16)
    salt, digest = hash_password(password)
    conn = _connect()
    try:
        role = conn.execute("SELECT id FROM roles WHERE id = ?", (role_id,)).fetchone()
        if role is None:
            raise LookupError("role")
        conn.execute(
            "INSERT INTO users (id, login, salt, password, role_id, blocked) VALUES (?, ?, ?, ?, ?, 0)",
            (user_id, login, salt, digest, role_id),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        raise ValueError("taken") from None
    finally:
        conn.close()
    return user_by_id(user_id)


def update_user(user_id, *, role_id=None, blocked=None):
    ensure()
    with _lock:
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise LookupError("user")
            new_role = role_id if role_id is not None else row["role_id"]
            new_blocked = int(row["blocked"] if blocked is None else blocked)
            if role_id is not None and conn.execute("SELECT id FROM roles WHERE id = ?", (new_role,)).fetchone() is None:
                raise LookupError("role")
            if not _would_keep(conn, user_id, new_role, new_blocked):
                raise PermissionError("keeper")
            conn.execute("UPDATE users SET role_id = ?, blocked = ? WHERE id = ?", (new_role, new_blocked, user_id))
            if new_blocked:
                conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            conn.commit()
        finally:
            conn.close()
    return user_by_id(user_id)


def delete_user(user_id):
    ensure()
    with _lock:
        conn = _connect()
        try:
            if not _would_keep(conn, user_id, blocked=1):
                raise PermissionError("keeper")
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM user_kb WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM kb_acl WHERE subject_type = 'user' AND subject_id = ?", (user_id,))
            conn.execute("DELETE FROM group_user WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
        finally:
            conn.close()


def list_roles():
    ensure()
    conn = _connect()
    try:
        roles = []
        for row in conn.execute("SELECT * FROM roles ORDER BY name").fetchall():
            roles.append({
                "id": row["id"],
                "name": row["name"],
                "actions": _role_actions(conn, row["id"]),
                "kb_actions": _kb_actions(conn, "role_kb", "role_id", row["id"]),
            })
        return roles
    finally:
        conn.close()


def _kb_actions(conn, table, column, owner):
    rows = conn.execute(f"SELECT kb_id, action FROM {table} WHERE {column} = ?", (owner,)).fetchall()
    found = {}
    for row in rows:
        found.setdefault(row["kb_id"], []).append(row["action"])
    return found


def create_role(name):
    ensure()
    name = str(name or "").strip()
    if not name:
        raise ValueError("name")
    conn = _connect()
    try:
        role_id = _insert_role(conn, name, ())
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        raise ValueError("taken") from None
    finally:
        conn.close()
    return role_id


def update_role(role_id, *, name=None, actions=None, kb_actions=None):
    ensure()
    with _lock:
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM roles WHERE id = ?", (role_id,)).fetchone()
            if row is None:
                raise LookupError("role")
            if name is not None:
                cleaned = str(name).strip()
                if not cleaned:
                    raise ValueError("name")
                try:
                    conn.execute("UPDATE roles SET name = ? WHERE id = ?", (cleaned, role_id))
                except sqlite3.IntegrityError:
                    conn.rollback()
                    raise ValueError("taken") from None
            if actions is not None:
                current = set(_role_actions(conn, role_id))
                proposed = set(actions)
                if set(KEEPER) <= current and not set(KEEPER) <= proposed:
                    others = [
                        user["id"]
                        for user in conn.execute("SELECT id, role_id FROM users WHERE blocked = 0 AND role_id != ?", (role_id,)).fetchall()
                        if set(KEEPER) <= set(_role_actions(conn, user["role_id"]))
                    ]
                    if not others:
                        raise PermissionError("keeper")
                conn.execute("DELETE FROM role_global WHERE role_id = ?", (role_id,))
                for action in proposed:
                    if action in GLOBAL_ACTIONS:
                        conn.execute("INSERT INTO role_global (role_id, action) VALUES (?, ?)", (role_id, action))
            if kb_actions is not None:
                conn.execute("DELETE FROM role_kb WHERE role_id = ?", (role_id,))
                for kb_id, names in kb_actions.items():
                    for action in names or []:
                        if action in CONTENT_ACTIONS:
                            conn.execute(
                                "INSERT INTO role_kb (role_id, kb_id, action) VALUES (?, ?, ?)",
                                (role_id, kb_id, action),
                            )
            conn.commit()
        finally:
            conn.close()


def delete_role(role_id):
    ensure()
    conn = _connect()
    try:
        used = conn.execute("SELECT id FROM users WHERE role_id = ?", (role_id,)).fetchone()
        if used is not None:
            raise PermissionError("used")
        conn.execute("DELETE FROM role_global WHERE role_id = ?", (role_id,))
        conn.execute("DELETE FROM role_kb WHERE role_id = ?", (role_id,))
        conn.execute("DELETE FROM group_role WHERE role_id = ?", (role_id,))
        conn.execute("DELETE FROM kb_acl WHERE subject_type = 'role' AND subject_id = ?", (role_id,))
        conn.execute("DELETE FROM roles WHERE id = ?", (role_id,))
        conn.commit()
    finally:
        conn.close()


def list_groups():
    ensure()
    conn = _connect()
    try:
        groups = []
        for row in conn.execute("SELECT * FROM groups ORDER BY name").fetchall():
            users = [item["user_id"] for item in conn.execute("SELECT user_id FROM group_user WHERE group_id = ?", (row["id"],))]
            roles = [item["role_id"] for item in conn.execute("SELECT role_id FROM group_role WHERE group_id = ?", (row["id"],))]
            groups.append({"id": row["id"], "name": row["name"], "user_ids": users, "role_ids": roles})
        return groups
    finally:
        conn.close()


def create_group(name):
    ensure()
    name = str(name or "").strip()
    if not name:
        raise ValueError("name")
    group_id = secrets.token_hex(16)
    conn = _connect()
    try:
        conn.execute("INSERT INTO groups (id, name) VALUES (?, ?)", (group_id, name))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        raise ValueError("taken") from None
    finally:
        conn.close()
    return group_id


def set_group_members(group_id, user_ids, role_ids):
    ensure()
    conn = _connect()
    try:
        if conn.execute("SELECT id FROM groups WHERE id = ?", (group_id,)).fetchone() is None:
            raise LookupError("group")
        conn.execute("DELETE FROM group_user WHERE group_id = ?", (group_id,))
        conn.execute("DELETE FROM group_role WHERE group_id = ?", (group_id,))
        for user_id in user_ids or []:
            conn.execute("INSERT INTO group_user (group_id, user_id) VALUES (?, ?)", (group_id, user_id))
        for role_id in role_ids or []:
            conn.execute("INSERT INTO group_role (group_id, role_id) VALUES (?, ?)", (group_id, role_id))
        conn.commit()
    finally:
        conn.close()


def delete_group(group_id):
    ensure()
    conn = _connect()
    try:
        conn.execute("DELETE FROM group_user WHERE group_id = ?", (group_id,))
        conn.execute("DELETE FROM group_role WHERE group_id = ?", (group_id,))
        conn.execute("DELETE FROM kb_acl WHERE subject_type = 'group' AND subject_id = ?", (group_id,))
        conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))
        conn.commit()
    finally:
        conn.close()


def group_ids_for(user):
    ensure()
    conn = _connect()
    try:
        direct = {row["group_id"] for row in conn.execute("SELECT group_id FROM group_user WHERE user_id = ?", (user["id"],))}
        via = {row["group_id"] for row in conn.execute("SELECT group_id FROM group_role WHERE role_id = ?", (user["role_id"],))}
        return direct | via
    finally:
        conn.close()


def meta_get(key):
    ensure()
    conn = _connect()
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else row["value"]
    finally:
        conn.close()


def meta_set(key, value):
    ensure()
    conn = _connect()
    try:
        conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
        conn.commit()
    finally:
        conn.close()


def role_content(role_id, kb_id):
    ensure()
    conn = _connect()
    try:
        rows = conn.execute("SELECT action FROM role_kb WHERE role_id = ? AND kb_id = ?", (role_id, kb_id)).fetchall()
        return {row["action"] for row in rows}
    finally:
        conn.close()


def user_content(user_id, kb_id):
    ensure()
    conn = _connect()
    try:
        rows = conn.execute("SELECT action FROM user_kb WHERE user_id = ? AND kb_id = ?", (user_id, kb_id)).fetchall()
        return {row["action"] for row in rows}
    finally:
        conn.close()


def set_user_content(user_id, kb_id, actions):
    ensure()
    conn = _connect()
    try:
        conn.execute("DELETE FROM user_kb WHERE user_id = ? AND kb_id = ?", (user_id, kb_id))
        for action in actions or []:
            if action in CONTENT_ACTIONS:
                conn.execute("INSERT INTO user_kb (user_id, kb_id, action) VALUES (?, ?, ?)", (user_id, kb_id, action))
        conn.commit()
    finally:
        conn.close()


def acl_rows(kb_id=None):
    ensure()
    conn = _connect()
    try:
        if kb_id:
            rows = conn.execute("SELECT * FROM kb_acl WHERE kb_id = ?", (kb_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM kb_acl").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def acl_add(kb_id, subject_type, subject_id, effect):
    ensure()
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO kb_acl (kb_id, subject_type, subject_id, effect) VALUES (?, ?, ?, ?)",
            (kb_id, subject_type, subject_id, effect),
        )
        conn.commit()
    finally:
        conn.close()


def acl_remove(kb_id, subject_type, subject_id, effect):
    ensure()
    conn = _connect()
    try:
        conn.execute(
            "DELETE FROM kb_acl WHERE kb_id = ? AND subject_type = ? AND subject_id = ? AND effect = ?",
            (kb_id, subject_type, subject_id, effect),
        )
        conn.commit()
    finally:
        conn.close()


def user_from_request_cookie(session_id):
    if os.environ.get("RAG_TEST_USER"):
        forced = os.environ["RAG_TEST_USER"]
        if forced == "-":
            return None
        return user_by_id(forced)
    if not session_id:
        return None
    return user_by_session(session_id)
