import os
from pathlib import Path

from fastapi.testclient import TestClient

import access
import auth
import kb
from api import app
from coordinator import run
from agents import NO_ANSWER


def _client(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("APP_ROOT", str(tmp_path / "root"))
    monkeypatch.setenv("CONFIG_DIR", str(repo / "config"))
    monkeypatch.setenv("PROMPTS_DIR", str(repo / "data" / "prompts"))
    monkeypatch.delenv("RAG_TEST_USER", raising=False)
    import settings
    settings.reload()
    client = TestClient(app)
    client.post("/setup", json={"login": "admin", "password": "password12"})
    return client


def _people():
    admin = auth.user_by_login("admin")
    role_id = auth.create_role("Сотрудник")
    auth.create_user("ivan", "password12", role_id)
    auth.create_user("maria", "password12", role_id)
    return admin, auth.user_by_login("ivan"), auth.user_by_login("maria")


def test_deny_overrides_allow(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    _admin, ivan, maria = _people()
    auth.acl_add(kb.LEGACY_ID, "role", ivan["role_id"], "allow")
    auth.acl_add(kb.LEGACY_ID, "user", ivan["id"], "deny")
    auth.update_role(ivan["role_id"], kb_actions={kb.LEGACY_ID: ["ask"]})
    assert access.opened(ivan, kb.LEGACY_ID) is False
    assert access.opened(maria, kb.LEGACY_ID) is True


def test_role_deny_blocks_a_named_allow(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    _admin, ivan, _maria = _people()
    auth.acl_add(kb.LEGACY_ID, "user", ivan["id"], "allow")
    auth.acl_add(kb.LEGACY_ID, "role", ivan["role_id"], "deny")
    assert access.opened(ivan, kb.LEGACY_ID) is False


def test_group_deny_blocks_a_named_allow(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    _admin, ivan, _maria = _people()
    group_id = auth.create_group("Бухгалтерия")
    auth.set_group_members(group_id, [], [ivan["role_id"]])
    auth.acl_add(kb.LEGACY_ID, "user", ivan["id"], "allow")
    auth.acl_add(kb.LEGACY_ID, "group", group_id, "deny")
    assert access.opened(ivan, kb.LEGACY_ID) is False


def test_named_allow_without_role_mention(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    _admin, ivan, maria = _people()
    auth.acl_add(kb.LEGACY_ID, "user", ivan["id"], "allow")
    assert access.opened(ivan, kb.LEGACY_ID) is True
    assert access.opened(maria, kb.LEGACY_ID) is False


def test_role_allow_without_groups(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    _admin, ivan, _maria = _people()
    auth.acl_add(kb.LEGACY_ID, "role", ivan["role_id"], "allow")
    assert access.opened(ivan, kb.LEGACY_ID) is True


def test_no_rows_means_closed(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    row = kb.create("Другая")
    ivan_role = auth.create_role("Сотрудник")
    auth.create_user("ivan", "password12", ivan_role)
    ivan = auth.user_by_login("ivan")
    assert access.opened(ivan, row["id"]) is False


def test_unrelated_group_does_not_open(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    _admin, ivan, _maria = _people()
    group_id = auth.create_group("Чужие")
    auth.acl_add(kb.LEGACY_ID, "group", group_id, "allow")
    assert access.opened(ivan, kb.LEGACY_ID) is False


def test_personal_upload_without_role_action(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _admin, ivan, maria = _people()
    auth.acl_add(kb.LEGACY_ID, "user", ivan["id"], "allow")
    auth.set_user_content(ivan["id"], kb.LEGACY_ID, ["upload"])
    assert access.can(ivan, kb.LEGACY_ID, "upload") is True
    assert access.can(maria, kb.LEGACY_ID, "upload") is False
    ivan_client = TestClient(app)
    ivan_client.post("/login", json={"login": "ivan", "password": "password12"})
    assert ivan_client.get("/documents").status_code == 200
    maria_client = TestClient(app)
    maria_client.post("/login", json={"login": "maria", "password": "password12"})
    assert maria_client.get("/documents").json()["documents"] == []
    assert client.get("/documents").status_code == 200


def test_role_action_opens_with_role_allow(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    _admin, ivan, _maria = _people()
    auth.acl_add(kb.LEGACY_ID, "role", ivan["role_id"], "allow")
    auth.update_role(ivan["role_id"], kb_actions={kb.LEGACY_ID: ["upload"]})
    assert access.can(ivan, kb.LEGACY_ID, "upload") is True
    assert auth.user_content(ivan["id"], kb.LEGACY_ID) == set()


def test_open_group_without_actions_hides_files(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    _admin, ivan, _maria = _people()
    group_id = auth.create_group("Все")
    auth.set_group_members(group_id, [ivan["id"]], [])
    auth.acl_add(kb.LEGACY_ID, "group", group_id, "allow")
    ivan_client = TestClient(app)
    ivan_client.post("/login", json={"login": "ivan", "password": "password12"})
    assert ivan_client.get("/documents").json()["documents"] == []


def test_delete_user_and_group_drops_acl_but_keeps_the_base(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    _admin, ivan, _maria = _people()
    group_id = auth.create_group("Все")
    auth.acl_add(kb.LEGACY_ID, "user", ivan["id"], "allow")
    auth.acl_add(kb.LEGACY_ID, "group", group_id, "deny")
    auth.set_user_content(ivan["id"], kb.LEGACY_ID, ["ask"])
    auth.delete_user(ivan["id"])
    auth.delete_group(group_id)
    left = auth.acl_rows(kb.LEGACY_ID)
    assert all(row["subject_id"] != ivan["id"] for row in left)
    assert all(row["subject_id"] != group_id for row in left)
    assert kb.get(kb.LEGACY_ID)["name"] == "Документы"


def test_self_grant_does_not_override_a_role_deny(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    admin = auth.user_by_login("admin")
    auth.acl_add(kb.LEGACY_ID, "role", admin["role_id"], "deny")
    response = client.post(f"/admin/kb/{kb.LEGACY_ID}/self")
    assert response.status_code == 400
    assert response.json()["detail"] == "Роль или группа закрывает эту базу"
    assert access.opened(admin, kb.LEGACY_ID) is False


def test_question_without_an_open_base_does_not_call_the_model(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    called = []
    monkeypatch.setattr("agents.complete", lambda *args, **kwargs: called.append(args) or "нет")
    scope = type("Scope", (), {})()
    scope.kbs = []
    result = run("секретная фраза", "d1", scope)
    assert result["answer"] == NO_ANSWER
    assert called == []


def test_second_base_is_not_searched_from_the_global_index(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    other = kb.create("Вторая")
    role_id = auth.create_role("Только вторая")
    auth.update_role(role_id, actions=["manage_users"], kb_actions={other["id"]: ["ask"]})
    auth.create_user("solo", "password12", role_id)
    solo = auth.user_by_login("solo")
    auth.acl_add(other["id"], "user", solo["id"], "allow")
    monkeypatch.setattr("api.list_documents", lambda: ["secret.txt"])
    monkeypatch.setattr("store.search_chunks", lambda *args, **kwargs: [])
    solo_client = TestClient(app)
    solo_client.post("/login", json={"login": "solo", "password": "password12"})
    response = solo_client.post("/query", json={"query": "секрет", "dialog_id": "d"})
    assert response.status_code == 200
    assert "secret" not in response.json()["answer"]
    assert client.get("/documents").status_code == 200
