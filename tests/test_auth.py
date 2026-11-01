import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

import audit
import auth
import kb
import workspace
from api import app


def _root(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("APP_ROOT", str(tmp_path / "root"))
    monkeypatch.setenv("CONFIG_DIR", str(repo / "config"))
    monkeypatch.setenv("PROMPTS_DIR", str(repo / "data" / "prompts"))
    monkeypatch.delenv("RAG_TEST_USER", raising=False)
    import settings
    settings.reload()
    return TestClient(app)


def test_setup_once_and_password_rules(tmp_path, monkeypatch):
    client = _root(tmp_path, monkeypatch)
    assert client.post("/setup", json={"login": "a", "password": "short"}).status_code == 400
    created = client.post("/setup", json={"login": "admin", "password": "password12"})
    assert created.status_code == 200
    assert created.json()["login"] == "admin"
    assert client.post("/setup", json={"login": "other", "password": "password12"}).status_code == 404
    assert Path(os.environ["APP_ROOT"]) in auth.db_path().resolve().parents


def test_login_failure_block_and_origin(tmp_path, monkeypatch):
    client = _root(tmp_path, monkeypatch)
    client.post("/setup", json={"login": "admin", "password": "password12"})
    fresh = TestClient(app)
    assert fresh.post("/login", json={"login": "admin", "password": "nope"}).json()["detail"] == "Неверный логин или пароль"
    assert fresh.get("/documents").status_code == 401
    role_id = auth.create_role("Гость")
    guest = auth.create_user("guest", "password12", role_id)
    auth.update_user(guest["id"], blocked=True)
    blocked = fresh.post("/login", json={"login": "guest", "password": "password12"})
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "Учётная запись заблокирована"
    foreign = fresh.post(
        "/login",
        json={"login": "admin", "password": "password12"},
        headers={"origin": "http://evil.example"},
    )
    assert foreign.status_code == 403
    assert fresh.get("/documents", headers={"origin": "http://evil.example"}).status_code == 403


def test_session_expires_and_password_change_drops_the_other(tmp_path, monkeypatch):
    client = _root(tmp_path, monkeypatch)
    client.post("/setup", json={"login": "admin", "password": "password12"})
    other = TestClient(app)
    other.post("/login", json={"login": "admin", "password": "password12"})
    assert other.get("/me").status_code == 200
    conn = auth._connect()
    try:
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute("UPDATE sessions SET expires = ?", (past,))
        conn.commit()
    finally:
        conn.close()
    assert other.get("/me").status_code == 401
    again = TestClient(app)
    again.post("/login", json={"login": "admin", "password": "password12"})
    second = TestClient(app)
    second.post("/login", json={"login": "admin", "password": "password12"})
    assert again.post("/me/password", json={"old": "password12", "new": "password13"}).status_code == 200
    dropped = audit.list_events(kind="session_drop")
    assert dropped
    packed = json.dumps(dropped, ensure_ascii=False)
    assert "password12" not in packed
    assert "password13" not in packed
    assert second.get("/documents").status_code == 401
    assert again.get("/me").status_code == 200
    logout = again.post("/logout")
    assert logout.status_code == 200
    assert again.get("/me").status_code == 401


def test_two_people_do_not_share_a_dialog(tmp_path, monkeypatch):
    client = _root(tmp_path, monkeypatch)
    client.post("/setup", json={"login": "admin", "password": "password12"})
    role_id = auth.user_by_login("admin")["role_id"]
    auth.create_user("other", "password12", role_id)
    other = TestClient(app)
    other.post("/login", json={"login": "other", "password": "password12"})
    created = client.post("/ui/dialogs").json()
    monkeypatch.setattr("api.run", lambda query, dialog_id, scope=None: {
        "answer": "только я", "status": "подтверждён", "document_names": [], "sources": [],
    })
    client.post("/query", json={"query": "только я", "dialog_id": created["id"]})
    foreign = other.get(f"/ui/dialogs/{created['id']}")
    assert foreign.status_code == 404
    assert auth.db_path().is_file()
    assert kb.LEGACY_ID
    assert workspace.PATH


def test_duplicate_role_group_and_login_are_refused(tmp_path, monkeypatch):
    client = _root(tmp_path, monkeypatch)
    client.post("/setup", json={"login": "admin", "password": "password12"})
    assert client.post("/admin/roles", json={"name": "Администратор"}).json()["detail"] == "Такое имя уже есть"
    assert client.post("/admin/roles", json={"name": "Архив"}).status_code == 200
    assert client.post("/admin/roles", json={"name": "Архив"}).status_code == 400
    assert client.post("/admin/groups", json={"name": "Смена"}).status_code == 200
    assert client.post("/admin/groups", json={"name": "Смена"}).json()["detail"] == "Такое имя уже есть"
    role_id = auth.user_by_login("admin")["role_id"]
    again = client.post("/admin/users", json={"login": "admin", "password": "password12", "role_id": role_id})
    assert again.status_code == 400
    assert again.json()["detail"] == "Такой логин уже есть"


def test_same_dialog_id_keeps_each_person_turn(tmp_path, monkeypatch):
    client = _root(tmp_path, monkeypatch)
    client.post("/setup", json={"login": "admin", "password": "password12"})
    admin = auth.user_by_login("admin")
    auth.create_user("other", "password12", admin["role_id"])
    other_user = auth.user_by_login("other")
    monkeypatch.setattr("api.run", lambda query, dialog_id, scope=None: {
        "answer": query, "status": "подтверждён", "document_names": [], "sources": [],
    })
    assert client.post("/query", json={"query": "мой ход", "dialog_id": "d"}).status_code == 200
    other = TestClient(app)
    other.post("/login", json={"login": "other", "password": "password12"})
    assert other.post("/query", json={"query": "чужой ход", "dialog_id": "d"}).status_code == 200
    root = Path(os.environ["APP_ROOT"])
    admin_text = (root / "data" / "users" / admin["id"] / "dialogs.json").read_text(encoding="utf-8")
    other_text = (root / "data" / "users" / other_user["id"] / "dialogs.json").read_text(encoding="utf-8")
    assert "мой ход" in admin_text and "чужой ход" not in admin_text
    assert "чужой ход" in other_text and "мой ход" not in other_text
    seen = []

    def run(query, dialog_id, scope=None):
        seen.append(dialog_id)
        return {"answer": "ещё", "status": "подтверждён", "document_names": [], "sources": []}

    monkeypatch.setattr("api.run", run)
    client.post("/query", json={"query": "ещё", "dialog_id": "d"})
    assert seen == [f"{admin['id']}:d"]


def test_blocked_person_and_new_password_lose_the_session(tmp_path, monkeypatch):
    client = _root(tmp_path, monkeypatch)
    client.post("/setup", json={"login": "admin", "password": "password12"})
    role_id = auth.create_role("Гость")
    auth.create_user("guest", "password12", role_id)
    guest = TestClient(app)
    guest.post("/login", json={"login": "guest", "password": "password12"})
    assert guest.get("/me").status_code == 200
    guest_id = auth.user_by_login("guest")["id"]
    assert client.patch(f"/admin/users/{guest_id}", json={"blocked": True}).status_code == 200
    assert guest.get("/documents").status_code == 401
    auth.update_user(guest_id, blocked=False)
    guest.post("/login", json={"login": "guest", "password": "password12"})
    assert guest.get("/me").status_code == 200
    assert client.patch(f"/admin/users/{guest_id}", json={"password": "password99"}).status_code == 200
    assert guest.get("/documents").status_code == 401


def test_last_manager_refusal_is_the_server_text(tmp_path, monkeypatch):
    client = _root(tmp_path, monkeypatch)
    client.post("/setup", json={"login": "admin", "password": "password12"})
    admin_id = auth.user_by_login("admin")["id"]
    refused = client.delete(f"/admin/users/{admin_id}")
    assert refused.status_code == 400
    assert refused.json()["detail"] == "Нельзя оставить систему без управляющего"
