import os
from pathlib import Path

from fastapi.testclient import TestClient

import access
import auth
import kb
from api import app
import coordinator
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


def test_rejected_base_keeps_one_reason(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    admin = auth.user_by_login("admin")
    closed = kb.create("Закрытая")
    opened = kb.create("Без вопроса")
    auth.acl_add(opened["id"], "user", admin["id"], "allow")
    scope = access.build_scope(admin)
    reasons = {row["kb_id"]: row["reason"] for row in access.rejections(admin, scope)}
    assert reasons[closed["id"]] == "нет входа"
    assert reasons[opened["id"]] == "нет спрашивать"
    assert kb.LEGACY_ID not in reasons


def test_second_check_refusal_stays_inside_the_search(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    admin = auth.user_by_login("admin")
    scope = access.build_scope(admin)
    monkeypatch.setattr(
        "store.search_permit",
        lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("closed")),
    )
    assert scope.search("вопрос", 4, None) == []
    reasons = {row["kb_id"]: row["reason"] for row in access.rejections(admin, scope)}
    assert reasons[kb.LEGACY_ID] == "нет входа"


def _stub_index(monkeypatch):
    import store
    monkeypatch.setattr(store, "_embed", lambda texts: [[0.1, 0.2, 0.3, 0.4] for _ in texts])


def test_group_role_picks_up_a_new_person_and_drops_them(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    _admin, ivan, _maria = _people()
    group_id = auth.create_group("Смена")
    auth.set_group_members(group_id, [], [ivan["role_id"]])
    fresh = auth.create_user("new", "password12", ivan["role_id"])
    assert group_id in auth.group_ids_for(fresh)
    other = auth.create_role("Другая")
    moved = auth.update_user(fresh["id"], role_id=other)
    assert group_id not in auth.group_ids_for(moved)


def test_new_person_and_second_admin_do_not_see_files(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setattr("api.list_documents", lambda: ["secret.txt"])
    role_id = auth.create_role("Новый")
    auth.create_user("ivan", "password12", role_id)
    ivan = TestClient(app)
    ivan.post("/login", json={"login": "ivan", "password": "password12"})
    assert ivan.get("/documents").json()["documents"] == []
    assert ivan.get(f"/kb/{kb.LEGACY_ID}/documents/secret.txt/preview").status_code == 404
    admin_role = auth.user_by_login("admin")["role_id"]
    auth.create_user("boss", "password12", admin_role)
    boss = TestClient(app)
    boss.post("/login", json={"login": "boss", "password": "password12"})
    assert boss.get("/documents").json()["documents"] == []
    assert boss.get("/admin/users").status_code == 200
    assert client.get("/documents").status_code == 200


def test_role_action_stays_on_one_base(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    _admin, ivan, _maria = _people()
    other = kb.create("Рядом")
    auth.update_role(ivan["role_id"], kb_actions={kb.LEGACY_ID: ["delete"]})
    assert auth.role_content(ivan["role_id"], kb.LEGACY_ID) == {"delete"}
    assert auth.role_content(ivan["role_id"], other["id"]) == set()


def test_backfill_does_not_return_a_removed_action(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    admin = auth.user_by_login("admin")
    auth.set_user_content(admin["id"], kb.LEGACY_ID, [])
    access.backfill_legacy(admin["id"])
    assert auth.user_content(admin["id"], kb.LEGACY_ID) == set()


def test_access_screen_lists_people_and_roles_by_name(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _admin, ivan, _maria = _people()
    listed = client.get("/admin/kb").json()
    assert "ivan" in [row["login"] for row in listed["people"]]
    assert "Сотрудник" in [row["name"] for row in listed["roles"]]


def test_opening_a_person_shows_the_base(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _stub_index(monkeypatch)
    monkeypatch.setattr("api.list_documents", lambda: ["secret.txt"])
    _admin, ivan, maria = _people()
    import store
    other = kb.create("Разное")
    store.upsert_at(other["chroma"], [{
        "text": "личный файл",
        "document_name": "mine.txt",
        "chunk_index": 0,
        "checksum": "m",
        "section": "",
    }])
    sent = client.post(
        f"/admin/kb/{other['id']}/allow",
        json={"subject_type": "user", "subject_id": ivan["id"]},
    )
    assert sent.status_code == 200
    assert auth.user_content(ivan["id"], other["id"]) == {"ask"}
    person = TestClient(app)
    person.post("/login", json={"login": "ivan", "password": "password12"})
    listed = person.get("/documents").json()["documents"]
    assert [row["kb_name"] for row in listed] == ["Разное"]
    assert [row["name"] for row in listed] == ["mine.txt"]
    twin = TestClient(app)
    twin.post("/login", json={"login": "maria", "password": "password12"})
    assert twin.get("/documents").json()["documents"] == []


def test_opening_a_role_does_not_add_ask(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _admin, ivan, _maria = _people()
    other = kb.create("Разное")
    sent = client.post(
        f"/admin/kb/{other['id']}/allow",
        json={"subject_type": "role", "subject_id": ivan["role_id"]},
    )
    assert sent.status_code == 200
    assert auth.role_content(ivan["role_id"], other["id"]) == set()
    assert access.opened(ivan, other["id"]) is True
    assert access.can_see(ivan, other["id"]) is False


def test_store_page_tree_refuses_a_folder_without_a_visible_base(tmp_path, monkeypatch):
    from fastapi import HTTPException
    import api
    _client(tmp_path, monkeypatch)
    role_id = auth.create_role("Гость")
    auth.create_user("guest", "password12", role_id)
    guest = auth.user_by_login("guest")
    incoming = {"id": "root", "name": "", "children": [{"id": "f", "name": "Папка", "children": []}]}
    try:
        api._store_page_tree(guest, incoming)
    except HTTPException as exc:
        assert exc.status_code == 403
        return
    raise AssertionError("an empty-folder save without a base was accepted")


def test_upload_on_a_role_needs_an_open_base(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    _stub_index(monkeypatch)
    monkeypatch.setattr("api.ingest_dir", lambda folder: [])
    monkeypatch.setattr("api.upsert_chunks", lambda chunks: None)
    _admin, ivan, _maria = _people()
    other = kb.create("Сосед")
    auth.update_role(ivan["role_id"], kb_actions={kb.LEGACY_ID: ["upload"], other["id"]: ["upload"]})
    assert access.can(ivan, kb.LEGACY_ID, "upload") is False
    person = TestClient(app)
    person.post("/login", json={"login": "ivan", "password": "password12"})
    closed = person.post(
        "/upload",
        data={"kb_id": kb.LEGACY_ID},
        files=[("files", ("note.txt", b"text", "text/plain"))],
    )
    assert closed.status_code == 403
    auth.acl_add(kb.LEGACY_ID, "role", ivan["role_id"], "allow")
    opened = person.post(
        "/upload",
        data={"kb_id": kb.LEGACY_ID},
        files=[("files", ("note.txt", b"text", "text/plain"))],
    )
    assert opened.status_code == 200
    neighbor = person.post(
        "/upload",
        data={"kb_id": other["id"]},
        files=[("files", ("note.txt", b"text", "text/plain"))],
    )
    assert neighbor.status_code == 403


def test_closed_group_hides_the_list_while_the_role_is_open(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    monkeypatch.setattr("api.list_documents", lambda: ["note.txt"])
    _admin, ivan, _maria = _people()
    auth.acl_add(kb.LEGACY_ID, "role", ivan["role_id"], "allow")
    auth.update_role(ivan["role_id"], kb_actions={kb.LEGACY_ID: ["ask"]})
    person = TestClient(app)
    person.post("/login", json={"login": "ivan", "password": "password12"})
    assert [row["name"] for row in person.get("/documents").json()["documents"]] == ["note.txt"]
    group_id = auth.create_group("Закрытая")
    auth.set_group_members(group_id, [], [ivan["role_id"]])
    auth.acl_add(kb.LEGACY_ID, "group", group_id, "deny")
    assert person.get("/documents").json()["documents"] == []


def test_self_grant_opens_the_file_and_writes_two_events(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _stub_index(monkeypatch)
    import store
    row = kb.create("Личная")
    store.upsert_at(row["chroma"], [{
        "text": "секретная фраза",
        "document_name": "note.txt",
        "chunk_index": 0,
        "checksum": "s",
        "section": "",
    }])
    admin = auth.user_by_login("admin")
    role_before = auth.role_content(admin["role_id"], row["id"])
    preview = f"/kb/{row['id']}/documents/note.txt/preview"
    assert client.get(preview).status_code == 404
    granted = client.post(f"/admin/kb/{row['id']}/self")
    assert granted.status_code == 200
    body = client.get(preview).json()
    assert "секретная фраза" in body["chunks"][0]["text"]
    assert auth.role_content(admin["role_id"], row["id"]) == role_before
    kinds = [item["kind"] for item in __import__("audit").list_events()]
    assert "access_allow" in kinds
    assert "personal_actions" in kinds
    assert "role_actions" not in kinds


def test_role_upload_creates_a_personal_base_and_hides_legacy_files(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    _stub_index(monkeypatch)
    monkeypatch.setattr("api.ingest_dir", lambda folder: [])
    monkeypatch.setattr("store.upsert_at", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("api.list_documents", lambda: ["secret.txt"])
    _admin, ivan, maria = _people()
    auth.update_role(ivan["role_id"], kb_actions={kb.LEGACY_ID: ["upload"]})
    person = TestClient(app)
    person.post("/login", json={"login": "ivan", "password": "password12"})
    targets = person.get("/upload-targets").json()
    assert targets["create"] is True
    assert targets["bases"] == []
    assert person.get("/documents").json()["documents"] == []
    sent = person.post(
        "/upload",
        data={"new_name": "Личное"},
        files=[("files", ("mine.txt", b"text", "text/plain"))],
    )
    assert sent.status_code == 200
    names = [row["name"] for row in person.get("/upload-targets").json()["bases"]]
    assert names == ["Личное"]
    listed = [row["name"] for row in person.get("/documents").json()["documents"]]
    assert "secret.txt" not in listed
    twin = TestClient(app)
    twin.post("/login", json={"login": "maria", "password": "password12"})
    assert twin.get("/upload-targets").json()["bases"] == []
    assert twin.get("/documents").json()["documents"] == []
    refused = twin.post(
        "/upload",
        data={"kb_id": next(row["id"] for row in kb.list_kbs() if row["name"] == "Личное")},
        files=[("files", ("no.txt", b"text", "text/plain"))],
    )
    assert refused.status_code == 403


def test_new_base_without_upload_action_is_refused(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    role_id = auth.create_role("Гость")
    auth.create_user("guest", "password12", role_id)
    person = TestClient(app)
    person.post("/login", json={"login": "guest", "password": "password12"})
    assert person.get("/upload-targets").json() == {"bases": [], "create": False}
    refused = person.post(
        "/upload",
        data={"new_name": "Личное"},
        files=[("files", ("mine.txt", b"text", "text/plain"))],
    )
    assert refused.status_code == 403


def test_creator_sees_a_new_base_and_the_same_role_does_not(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _stub_index(monkeypatch)
    monkeypatch.setattr("api.ingest_dir", lambda folder: [])
    monkeypatch.setattr("store.upsert_at", lambda *_args, **_kwargs: None)
    sent = client.post(
        "/upload",
        data={"new_name": "Цех"},
        files=[("files", ("note.txt", b"text", "text/plain"))],
    )
    assert sent.status_code == 200
    uploaded = [item for item in __import__("audit").list_events(kind="upload") if item["ok"]]
    assert uploaded and "note.txt" in (uploaded[0]["payload"].get("names") or [])
    targets = client.get("/upload-targets").json()
    created = next(row for row in targets["bases"] if row["name"] == "Цех")
    again = client.post(
        "/upload",
        data={"kb_id": created["id"]},
        files=[("files", ("more.txt", b"text", "text/plain"))],
    )
    assert again.status_code == 200
    twin = TestClient(app)
    auth.create_user("twin", "password12", auth.user_by_login("admin")["role_id"])
    twin.post("/login", json={"login": "twin", "password": "password12"})
    names = [row["name"] for row in twin.get("/upload-targets").json()["bases"]]
    assert "Цех" not in names
    auth.acl_add(created["id"], "role", auth.user_by_login("admin")["role_id"], "allow")
    refused = twin.post(
        "/upload",
        data={"kb_id": created["id"]},
        files=[("files", ("no.txt", b"text", "text/plain"))],
    )
    assert refused.status_code == 403
    assert any(item["kind"] == "upload" and item["ok"] is False for item in __import__("audit").list_events())


def test_follow_up_without_a_base_id_does_not_open_the_other_catalog(tmp_path, monkeypatch):
    import store
    monkeypatch.setattr(store, "CHROMA", tmp_path / "chroma")
    _stub_index(monkeypatch)
    store.reset()
    _client(tmp_path, monkeypatch)
    other = kb.create("Вторая")
    admin = auth.user_by_login("admin")
    auth.acl_add(other["id"], "user", admin["id"], "allow")
    auth.set_user_content(admin["id"], other["id"], ["ask"])
    store.upsert_chunks([{
        "text": "насос альфа стоит в цехе",
        "document_name": "a.txt",
        "chunk_index": 0,
        "checksum": "a",
        "section": "",
    }])
    store.upsert_at(other["chroma"], [{
        "text": "секрет второй базы",
        "document_name": "b.txt",
        "chunk_index": 0,
        "checksum": "b",
        "section": "",
    }])
    opened = []
    real = store.search_permit

    def spy(permit, *args, **kwargs):
        opened.append(permit.kb_id)
        return real(permit, *args, **kwargs)

    monkeypatch.setattr(store, "search_permit", spy)
    scope = access.build_scope(admin)
    found = scope.search("насос", 4, [{"kb_id": "", "document_name": "a.txt"}])
    assert {row["document_name"] for row in found} == {"a.txt"}
    assert other["id"] not in opened
    assert "секрет" not in " ".join(row["text"] for row in found)
    assert other["id"] in scope.skipped
    store.reset()


def test_rrf_keeps_bases_that_hold_a_rare_query_word():
    docs = [
        {"kb_id": "d", "kb_name": "Документы", "document_name": f"a{index}.docx", "chunk_index": 0, "text": f"является система {index}"}
        for index in range(4)
    ]
    extra = [{"kb_id": "y", "kb_name": "Ещё", "document_name": "y.docx", "chunk_index": 0, "text": "является насос"}]
    one = [{"kb_id": "o", "kb_name": "Один", "document_name": "one.docx", "chunk_index": 0, "text": "колобок катится по дороге"}]
    two = [{"kb_id": "t", "kb_name": "Два", "document_name": "two.docx", "chunk_index": 0, "text": "колобок лежит на окне"}]
    found = access._rrf_merge([docs, extra, one, two], 4, "Кем является колобок?")
    keys = {(row["kb_id"], row["document_name"]) for row in found}
    assert ("o", "one.docx") in keys
    assert ("t", "two.docx") in keys


def test_rrf_drops_a_file_that_only_matches_the_base_name():
    docs = [{
        "kb_id": "d",
        "kb_name": "Документы",
        "document_name": "impus.docx",
        "chunk_index": 0,
        "text": "Целью настоящего документа является описание решения.",
    }]
    tale = [
        {
            "kb_id": "o",
            "kb_name": "Отморозок",
            "document_name": "one.docx",
            "chunk_index": 5,
            "text": "Бабка с дедом стояли у ворот и звали.",
        },
        {
            "kb_id": "o",
            "kb_name": "Отморозок",
            "document_name": "one.docx",
            "chunk_index": 0,
            "text": "Испеки, старуха, колобка. Не для еды — для дома.",
        },
    ]
    other = [{
        "kb_id": "r",
        "kb_name": "Разное отморозка",
        "document_name": "fin.docx",
        "chunk_index": 0,
        "text": "Чистый денежный поток уменьшился.",
    }]
    found = access._rrf_merge(
        [docs, tale, other],
        4,
        "Кем является колобок? Отморозком или терпилой?",
    )
    names = {row["document_name"] for row in found}
    assert "one.docx" in names
    assert "fin.docx" not in names
    assert "impus.docx" not in names


def test_rrf_picks_the_chunk_that_holds_the_question_words():
    ideas = [{
        "kb_id": "d",
        "kb_name": "Документы",
        "document_name": "ideas.docx",
        "chunk_index": 20,
        "text": "отвечает на главные вопросы: «Зачем мне это?»",
    }]
    tale = [
        {
            "kb_id": "o",
            "kb_name": "Один",
            "document_name": "one.docx",
            "chunk_index": 5,
            "text": "чтоб он сам отвязался, довольный. Бабка с дедом пусть путь держат.",
        },
        {
            "kb_id": "o",
            "kb_name": "Один",
            "document_name": "one.docx",
            "chunk_index": 0,
            "text": "Испеки, старуха, колобка. Не для еды — для дома.",
        },
    ]
    two = [
        {
            "kb_id": "t",
            "kb_name": "Два",
            "document_name": "two.docx",
            "chunk_index": 7,
            "text": "Они же меня испекли. Бабка рассердится.",
        },
        {
            "kb_id": "t",
            "kb_name": "Два",
            "document_name": "two.docx",
            "chunk_index": 0,
            "text": "Испеки колобка, чтоб было кому сказку на ночь.",
        },
    ]
    found = access._rrf_merge(
        [ideas, tale, two],
        4,
        "Зачем бабка и дед испекли колобка?",
    )
    names = {row["document_name"] for row in found}
    assert "ideas.docx" not in names
    assert names <= {"one.docx", "two.docx"}
    assert any(row["document_name"] == "one.docx" and row["chunk_index"] == 0 for row in found)


def test_rrf_keeps_hits_from_a_second_base():
    left = [
        {"kb_id": "a", "document_name": f"a{index}.txt", "chunk_index": 0, "text": f"насос {index}"}
        for index in range(4)
    ]
    right = left + [{"kb_id": "b", "document_name": "b.txt", "chunk_index": 0, "text": "уникальное слово"}]
    found = access._rrf_merge([left, right], 4)
    assert found[0]["kb_id"] == "a"
    assert {row["kb_id"] for row in found} == {"a", "b"}
    assert sum(1 for row in found if row["document_name"].startswith("a")) <= 3


def test_follow_up_with_a_new_name_searches_the_other_base(tmp_path, monkeypatch):
    import store
    monkeypatch.setattr(store, "CHROMA", tmp_path / "chroma")
    _stub_index(monkeypatch)
    store.reset()
    _client(tmp_path, monkeypatch)
    other = kb.create("Вторая")
    admin = auth.user_by_login("admin")
    auth.acl_add(other["id"], "user", admin["id"], "allow")
    auth.set_user_content(admin["id"], other["id"], ["ask"])
    store.upsert_chunks([{
        "text": "насос альфа стоит в цехе",
        "document_name": "a.txt",
        "chunk_index": 0,
        "checksum": "a",
        "section": "",
    }])
    store.upsert_at(other["chroma"], [{
        "text": "уникальное слово только здесь",
        "document_name": "b.txt",
        "chunk_index": 0,
        "checksum": "b",
        "section": "",
    }])
    scope = access.build_scope(admin)
    previous = {
        "query": "что сказано про насос",
        "answer": "насос альфа стоит в цехе",
        "document_names": ["a.txt"],
        "places": [{"kb_id": kb.LEGACY_ID, "document_name": "a.txt"}],
    }
    pinned = coordinator._places([previous], "сколько он стоит?")
    assert pinned == previous["places"]
    held = scope.search("насос", 4, pinned)
    assert {row["document_name"] for row in held} == {"a.txt"}
    released = coordinator._places([previous], "где оно и уникальное слово?")
    assert released is None
    found = scope.search("уникальное слово", 4, released)
    assert any(row["document_name"] == "b.txt" for row in found)
    store.reset()


def test_same_file_name_keeps_each_base_text():
    found = [
        {"document_name": "note.txt", "chunk_index": 0, "kb_id": "a", "text": "альфа"},
        {"document_name": "note.txt", "chunk_index": 0, "kb_id": "b", "text": "бета"},
    ]
    result = {"sources": [
        {"document_name": "note.txt", "chunk_index": 0, "kb_id": "a"},
        {"document_name": "note.txt", "chunk_index": 0, "kb_id": "b"},
    ]}
    rows = access.source_rows(result, found)
    assert [row["text"] for row in rows] == ["альфа", "бета"]


def test_new_base_records_the_personal_grant(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    created = client.post("/kb", json={"name": "Цех"}).json()
    import audit
    kinds = [
        item["kind"]
        for item in audit.list_events()
        if (item.get("payload") or {}).get("kb_id") == created["id"]
    ]
    assert "kb_create" in kinds
    assert "access_allow" in kinds
    assert "personal_actions" in kinds
    assert "role_actions" not in kinds


def test_one_base_search_matches_direct_order(tmp_path, monkeypatch):
    import store
    monkeypatch.setattr(store, "CHROMA", tmp_path / "chroma")
    _stub_index(monkeypatch)
    store.reset()
    _client(tmp_path, monkeypatch)
    store.upsert_chunks([
        {"text": "насос альфа стоит в цехе", "document_name": "a.txt", "chunk_index": 0, "checksum": "a", "section": ""},
        {"text": "насос бета стоит на складе", "document_name": "b.txt", "chunk_index": 0, "checksum": "b", "section": ""},
    ])
    admin = auth.user_by_login("admin")
    scope = access.build_scope(admin)
    direct = store.search_chunks("насос", 4)
    found = scope.search("насос", 4, None)
    assert [(row["document_name"], row["chunk_index"]) for row in found] == [
        (row["document_name"], row["chunk_index"]) for row in direct
    ]
    assert found
    limited = scope.search("насос", 4, [{"kb_id": "", "document_name": "a.txt"}])
    assert limited
    assert {row["document_name"] for row in limited} == {"a.txt"}
    store.reset()


def test_skipped_base_does_not_confirm_a_word(tmp_path, monkeypatch):
    import store
    monkeypatch.setattr(store, "CHROMA", tmp_path / "chroma")
    _stub_index(monkeypatch)
    store.reset()
    _client(tmp_path, monkeypatch)
    other = kb.create("Вторая")
    admin = auth.user_by_login("admin")
    auth.acl_add(other["id"], "user", admin["id"], "allow")
    auth.set_user_content(admin["id"], other["id"], ["ask"])
    store.upsert_chunks([
        {"text": "насос альфа", "document_name": "a.txt", "chunk_index": 0, "checksum": "a", "section": ""},
    ])
    store.upsert_at(other["chroma"], [{
        "text": "уникальное слово только здесь",
        "document_name": "b.txt",
        "chunk_index": 0,
        "checksum": "b",
        "section": "",
    }])
    scope = access.build_scope(admin)
    seen = []
    real = store.known_permit

    def spy(permit, term):
        seen.append(permit.kb_id)
        return real(permit, term)

    monkeypatch.setattr(store, "known_permit", spy)
    scope.search("насос", 4, [{"kb_id": kb.LEGACY_ID, "document_name": "a.txt"}])
    assert scope.known("уникальное") is False
    assert other["id"] not in seen
    store.reset()


def test_closed_base_is_rejected_and_not_opened(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    other = kb.create("Закрытая")
    opened = []

    def spy(permit, *_args, **_kwargs):
        opened.append(permit.kb_id)
        return []

    monkeypatch.setattr("store.search_permit", spy)
    monkeypatch.setattr("agents.complete", lambda *_args, **_kwargs: "пусто")
    monkeypatch.setattr("agents.count_tokens", lambda text: 1)
    response = client.post("/query", json={"query": "где уникальная фраза второй базы", "dialog_id": "d"})
    assert response.status_code == 200
    assert "уникальная фраза" not in response.json()["answer"]
    assert other["id"] not in opened
    import audit
    rows = [row for row in audit.list_events(kind="query") if row["payload"].get("query")]
    assert rows
    rejected = {item["kb_id"]: item["reason"] for item in rows[0]["payload"]["rejected"]}
    assert rejected[other["id"]] == "нет входа"
    assert other["id"] not in rows[0]["payload"]["opened"]
    joined = str(rows[0]["payload"]["sources"])
    assert "уникальная фраза" not in joined


def test_run_without_scope_does_not_write_the_journal(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    import audit
    monkeypatch.setattr("coordinator.list_documents", lambda: ["a.txt"])
    before = len(audit.list_events(kind="query"))
    result = run("Какие документы загружены в систему?", "mem", None)
    assert "a.txt" in result["answer"]
    assert len(audit.list_events(kind="query")) == before
