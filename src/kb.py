"""Реестр баз. «Документы» смотрит на текущие папку и индекс процесса.

Остальные базы лежат в data/kbs/<id>. Путь, записанный при создании, не используется:
на другой машине это чужой абсолютный каталог.
"""

from pathlib import Path

import auth

LEGACY_ID = "00000000-0000-4000-8000-000000000001"
LEGACY_NAME = "Документы"


def _inbox_default():
    import api

    return Path(api.INBOX)


def _chroma_default():
    import store

    return Path(store.CHROMA)


def ensure_legacy():
    auth.ensure()
    conn = auth._connect()
    try:
        row = conn.execute("SELECT id FROM kb WHERE id = ?", (LEGACY_ID,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO kb (id, name, inbox, chroma, legacy) VALUES (?, ?, ?, ?, 1)",
                (LEGACY_ID, LEGACY_NAME, str(_inbox_default()), str(_chroma_default())),
            )
            conn.commit()
    finally:
        conn.close()


def list_kbs():
    ensure_legacy()
    conn = auth._connect()
    try:
        rows = conn.execute("SELECT * FROM kb ORDER BY name").fetchall()
        return [_public(row) for row in rows]
    finally:
        conn.close()


def get(kb_id):
    ensure_legacy()
    conn = auth._connect()
    try:
        row = conn.execute("SELECT * FROM kb WHERE id = ?", (kb_id,)).fetchone()
        return None if row is None else _public(row)
    finally:
        conn.close()


def _owned(kb_id):
    root = auth.app_root() / "data" / "kbs" / str(kb_id)
    return root / "inbox", root / "chroma"


def _public(row):
    legacy = bool(row["legacy"])
    if legacy:
        inbox, chroma = _inbox_default(), _chroma_default()
    else:
        inbox, chroma = _owned(row["id"])
    return {
        "id": row["id"],
        "name": row["name"],
        "inbox": inbox,
        "chroma": chroma,
        "legacy": legacy,
    }


def create(name):
    ensure_legacy()
    cleaned = " ".join(str(name or "").split())
    if not cleaned or "/" in cleaned or "\\" in cleaned:
        raise ValueError("name")
    import uuid

    kb_id = str(uuid.uuid4())
    inbox, chroma = _owned(kb_id)
    inbox.mkdir(parents=True, exist_ok=True)
    chroma.mkdir(parents=True, exist_ok=True)
    conn = auth._connect()
    try:
        taken = conn.execute("SELECT id FROM kb WHERE name = ?", (cleaned,)).fetchone()
        if taken is not None:
            raise FileExistsError("name")
        conn.execute(
            "INSERT INTO kb (id, name, inbox, chroma, legacy) VALUES (?, ?, ?, ?, 0)",
            (kb_id, cleaned, str(inbox), str(chroma)),
        )
        conn.commit()
    finally:
        conn.close()
    return get(kb_id)


def is_uuid(value):
    import uuid

    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False
