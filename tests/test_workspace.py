import threading

import dialog
import workspace


def _answer(text):
    return {"answer": text, "sources": [], "document_names": []}


def test_overlapping_rating_keeps_the_new_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    dialog.reset()
    row = workspace.create_dialog()
    dialog_id = row["id"]
    workspace.append_turn(dialog_id, "первый", _answer("старый"))
    entered = threading.Event()
    release = threading.Event()
    state = {"stalled": False}

    def stall(_data):
        if state["stalled"]:
            return
        state["stalled"] = True
        entered.set()
        release.wait(5)

    monkeypatch.setattr(workspace, "_before_write", stall)
    errors = []

    def add_turn():
        try:
            workspace.append_turn(dialog_id, "второй", _answer("новый"))
        except Exception as exc:
            errors.append(exc)

    def rate():
        try:
            workspace.patch_ratings(dialog_id, 0, {"answer_complete": 5})
        except Exception as exc:
            errors.append(exc)

    writer = threading.Thread(target=add_turn)
    rater = threading.Thread(target=rate)
    writer.start()
    started = False
    try:
        assert entered.wait(5)
        rater.start()
        started = True
        rater.join(0.5)
        assert rater.is_alive()
    finally:
        release.set()
    writer.join(5)
    if started:
        rater.join(5)
    assert errors == []
    assert not writer.is_alive()
    assert not rater.is_alive()
    saved = next(item for item in workspace.load()["dialogs"] if item["id"] == dialog_id)
    assert [turn["query"] for turn in saved["turns"]] == ["первый", "второй"]
    assert saved["turns"][0]["ratings"]["answer_complete"] == 5
    assert saved["turns"][1]["answer"] == "новый"


def test_forget_file_keeps_the_dialog(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    workspace.put_tree({
        "id": "root",
        "name": "",
        "children": [
            {"id": "folder", "name": "Папка", "children": [{"document_name": "gone.txt"}]},
            {"document_name": "note.txt"},
        ],
    }, ["note.txt", "gone.txt"])
    workspace.forget_file("gone.txt", ["note.txt"])
    saved = workspace.load()
    assert saved["dialogs"][0]["id"] == row["id"]
    assert saved["dialogs"][0]["turns"][0]["answer"] == "ответ"
    names = workspace.iter_files(saved["tree"])
    assert names == ["note.txt"]
    assert saved["tree"]["children"][0]["name"] == "Папка"


def test_append_does_not_recreate_a_deleted_dialog(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    workspace.delete_dialog(row["id"])
    assert workspace.append_turn(row["id"], "вопрос", _answer("ответ"), create=False) is None
    assert all(item["id"] != row["id"] for item in workspace.load()["dialogs"])
    assert dialog.get_dialog(row["id"]) == []


def test_ratings_keep_valid_scores_and_basenames(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    workspace.patch_ratings(row["id"], 0, {
        "answer_complete": 4,
        "answer_correct": 5,
        "links": {"1": 3},
        "documents": {"note.txt": 2},
    })
    updated = workspace.patch_ratings(row["id"], 0, {
        "answer_complete": 9,
        "answer_correct": "",
        "links": {"2": 0, "3": "нет"},
        "documents": {"../other.txt": 4, "nested/note.txt": 1},
    })
    assert updated["ratings"]["answer_complete"] is None
    assert updated["ratings"]["answer_correct"] is None
    assert updated["ratings"]["links"] == {"1": 3, "2": None, "3": None}
    assert updated["ratings"]["documents"] == {"note.txt": 1, "other.txt": 4}
    assert workspace.patch_ratings(row["id"], 0, {"links": ["1"]})["ratings"]["links"]["1"] == 3
    assert workspace.patch_ratings(row["id"], -1, {"answer_complete": 1}) is None
    assert workspace.patch_ratings(row["id"], 3, {"answer_complete": 1}) is None
    assert workspace.patch_ratings("missing", 0, {"answer_complete": 1}) is None
    kept = workspace.load()["dialogs"][0]["turns"][0]["ratings"]
    assert kept["links"]["1"] == 3
    assert kept["answer_complete"] is None


def test_tree_keeps_only_known_basenames(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    saved = workspace.put_tree({
        "id": "root",
        "name": "",
        "children": [
            {"document_name": "nested/note.txt", "children": [{"document_name": "secret.txt"}]},
            {"document_name": "../secret.txt"},
            {"document_name": "missing.txt"},
            "skip",
            {"id": "dup", "name": "", "children": [{"document_name": "note.txt"}]},
            {"id": "dup", "name": "Вторая", "children": [{"document_name": "secret.txt"}]},
            {"id": "long", "name": "Я" * 90, "children": []},
        ],
    }, ["note.txt", "secret.txt"])
    children = saved["tree"]["children"]
    assert children[0] == {"document_name": "note.txt"}
    assert children[1] == {"document_name": "secret.txt"}
    assert [item.get("name") for item in children[2:]] == ["Папка", "Я" * 80]
    assert children[2]["children"] == [{"document_name": "note.txt"}]
    assert "Вторая" not in [item.get("name") for item in children]
    stored = (tmp_path / "workspace.json").read_text(encoding="utf-8")
    assert "../" not in stored
    assert "missing.txt" not in stored
    assert workspace.sanitize_tree("нет", {"note.txt"}) == {"id": "root", "name": "", "children": []}


def test_corrupt_workspace_file_reads_as_empty(tmp_path, monkeypatch):
    path = tmp_path / "workspace.json"
    monkeypatch.setattr(workspace, "PATH", path)
    empty = {"dialogs": [], "tree": {"id": "root", "name": "", "children": []}}
    path.write_text("{", encoding="utf-8")
    assert workspace.load() == empty
    path.write_text("[]", encoding="utf-8")
    assert workspace.load() == empty
    path.write_text('{"dialogs": "нет", "tree": []}', encoding="utf-8")
    assert workspace.load() == empty


def test_append_turn_titles_sorts_and_reads_source_names(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    first = workspace.create_dialog()
    second = workspace.create_dialog()
    saved = workspace.append_turn(first["id"], "a" * 70, {
        "answer": "ответ",
        "sources": [
            {"document_name": "note.txt"},
            {"document_name": ""},
            {"document_name": "note.txt"},
            {"document_name": "other.txt"},
        ],
    })
    assert saved["title"] == "a" * 60 + "…"
    assert saved["turns"][0]["document_names"] == ["note.txt", "other.txt"]
    again = workspace.append_turn(first["id"], "другой вопрос", _answer("ещё"))
    assert again["title"] == "a" * 60 + "…"
    named = workspace.append_turn(second["id"], "  номер   цеха ", _answer("4"))
    assert named["title"] == "номер цеха"
    blank = workspace.create_dialog()
    assert workspace.append_turn(blank["id"], " \n ", _answer("пусто"))["title"] == "Новый диалог"
    assert [row["id"] for row in workspace.load()["dialogs"]][0] == blank["id"]


def test_prepare_dialog_restores_saved_turns_and_drops_orphans(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    dialog.reset()
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "первый", _answer("ответ"))
    dialog.reset()
    assert dialog.get_dialog(row["id"]) == []
    loaded = workspace.prepare_dialog(row["id"])
    assert loaded["id"] == row["id"]
    assert [turn["query"] for turn in dialog.get_dialog(row["id"])] == ["первый"]
    dialog.set_dialog("missing", [{"query": "секрет", "answer": "a", "document_names": ["note.txt"]}])
    assert workspace.prepare_dialog("missing") is None
    assert dialog.get_dialog("missing") == []


def test_overlapping_tree_save_keeps_the_new_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    dialog_id = row["id"]
    workspace.append_turn(dialog_id, "первый", _answer("старый"))
    entered = threading.Event()
    release = threading.Event()
    state = {"stalled": False}

    def stall(_data):
        if state["stalled"]:
            return
        state["stalled"] = True
        entered.set()
        release.wait(5)

    monkeypatch.setattr(workspace, "_before_write", stall)
    errors = []

    def add_turn():
        try:
            workspace.append_turn(dialog_id, "второй", _answer("новый"))
        except Exception as exc:
            errors.append(exc)

    def save_tree():
        try:
            workspace.put_tree({
                "id": "root",
                "name": "",
                "children": [
                    {"id": "folder", "name": "Архив", "children": [{"document_name": "note.txt"}]},
                ],
            }, ["note.txt"])
        except Exception as exc:
            errors.append(exc)

    writer = threading.Thread(target=add_turn)
    saver = threading.Thread(target=save_tree)
    writer.start()
    started = False
    try:
        assert entered.wait(5)
        saver.start()
        started = True
        saver.join(0.5)
        assert saver.is_alive()
    finally:
        release.set()
    writer.join(5)
    if started:
        saver.join(5)
    assert errors == []
    assert not writer.is_alive()
    assert not saver.is_alive()
    saved = workspace.load()
    stored = next(item for item in saved["dialogs"] if item["id"] == dialog_id)
    assert [turn["query"] for turn in stored["turns"]] == ["первый", "второй"]
    assert stored["turns"][1]["answer"] == "новый"
    assert saved["tree"]["children"][0]["name"] == "Архив"
    assert saved["tree"]["children"][0]["children"] == [{"document_name": "note.txt"}]
