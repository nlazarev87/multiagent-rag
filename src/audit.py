"""Журнал только дописывается. Цепочка хешей пишется под одним замком."""
import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone

import auth

_lock = threading.Lock()
_ready = set()


def path():
    return auth.app_root() / "data" / "audit" / "log.sqlite"


def _connect():
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure():
    key = str(path())
    if key in _ready:
        return
    with _lock:
        if key in _ready:
            return
        conn = _connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prev_hash TEXT NOT NULL,
                    row_hash TEXT NOT NULL,
                    body TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS events_no_update
                BEFORE UPDATE ON events
                BEGIN
                    SELECT RAISE(ABORT, 'audit');
                END;
                CREATE TRIGGER IF NOT EXISTS events_no_delete
                BEFORE DELETE ON events
                BEGIN
                    SELECT RAISE(ABORT, 'audit');
                END;
                """
            )
            conn.commit()
        finally:
            conn.close()
        _ready.add(key)


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _stamp():
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def write(kind, user, payload, ok=True):
    ensure()
    body = {
        "kind": kind,
        "time": _stamp(),
        "ok": bool(ok),
        "user_id": "" if user is None else user.get("id", ""),
        "login": "" if user is None else user.get("login", ""),
        "role_id": "" if user is None else user.get("role_id", ""),
        "role": "" if user is None else user.get("role", ""),
        "groups": [] if user is None else sorted(auth.group_ids_for(user)),
        "payload": payload or {},
    }
    text = canonical(body)
    with _lock:
        conn = _connect()
        try:
            prev = conn.execute("SELECT row_hash FROM events ORDER BY id DESC LIMIT 1").fetchone()
            prev_hash = prev["row_hash"] if prev else "0" * 64
            row_hash = hashlib.sha256((prev_hash + text).encode("utf-8")).hexdigest()
            conn.execute(
                "INSERT INTO events (prev_hash, row_hash, body) VALUES (?, ?, ?)",
                (prev_hash, row_hash, text),
            )
            conn.commit()
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        finally:
            conn.close()


def verify():
    ensure()
    conn = _connect()
    try:
        rows = conn.execute("SELECT id, prev_hash, row_hash, body FROM events ORDER BY id").fetchall()
    finally:
        conn.close()
    prev = "0" * 64
    for row in rows:
        if row["prev_hash"] != prev:
            return False
        digest = hashlib.sha256((row["prev_hash"] + row["body"]).encode("utf-8")).hexdigest()
        if digest != row["row_hash"]:
            return False
        prev = row["row_hash"]
    return True


def _load(row):
    body = json.loads(row["body"])
    body["id"] = row["id"]
    body["prev_hash"] = row["prev_hash"]
    body["row_hash"] = row["row_hash"]
    return body


def list_events(*, user_id="", role_id="", group_id="", kind="", after="", before="", limit=50):
    ensure()
    conn = _connect()
    try:
        rows = conn.execute("SELECT id, prev_hash, row_hash, body FROM events ORDER BY id DESC").fetchall()
    finally:
        conn.close()
    found = []
    for row in rows:
        body = _load(row)
        if before and body["time"] >= before:
            continue
        if after and body["time"] <= after:
            continue
        if user_id and body.get("user_id") != user_id:
            continue
        if role_id and body.get("role_id") != role_id:
            continue
        if group_id and group_id not in (body.get("groups") or []):
            continue
        if kind and body.get("kind") != kind:
            continue
        found.append(body)
        if len(found) >= limit:
            break
    return found


def get_event(event_id):
    ensure()
    conn = _connect()
    try:
        row = conn.execute("SELECT id, prev_hash, row_hash, body FROM events WHERE id = ?", (event_id,)).fetchone()
    finally:
        conn.close()
    return None if row is None else _load(row)
