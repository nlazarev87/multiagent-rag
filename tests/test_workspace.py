import threading
from pathlib import Path

import pytest

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


def test_overlapping_tree_save_keeps_the_new_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    dialog.reset()
    row = workspace.create_dialog()
    dialog_id = row["id"]
    workspace.append_turn(dialog_id, "первый", _answer("старый"))
    workspace.put_tree({
        "id": "root",
        "name": "",
        "children": [{"id": "folder", "name": "Старая", "children": [{"document_name": "note.txt"}]}],
    }, ["note.txt"])
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
                "children": [{"id": "folder", "name": "Новая", "children": [{"document_name": "note.txt"}]}],
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
    dialog_row = next(item for item in saved["dialogs"] if item["id"] == dialog_id)
    assert [turn["query"] for turn in dialog_row["turns"]] == ["первый", "второй"]
    assert dialog_row["turns"][1]["answer"] == "новый"
    assert saved["tree"]["children"][0]["name"] == "Новая"


def test_ratings_keep_only_scores_from_one_to_five(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    saved = workspace.patch_ratings(row["id"], 0, {
        "answer_complete": 4,
        "answer_correct": 2,
        "links": {"1": 5},
        "documents": {"folder/note.txt": 3},
    })
    assert saved["answer"] == "ответ"
    assert saved["ratings"]["answer_complete"] == 4
    assert saved["ratings"]["documents"] == {"note.txt": 3}
    updated = workspace.patch_ratings(row["id"], 0, {
        "answer_complete": 9,
        "links": {"1": 0, "2": "нет"},
        "documents": {"../note.txt": 1},
    })
    assert updated["ratings"]["answer_complete"] is None
    assert updated["ratings"]["answer_correct"] == 2
    assert updated["ratings"]["links"] == {"1": None, "2": None}
    assert updated["ratings"]["documents"] == {"note.txt": 1}
    assert workspace.patch_ratings(row["id"], -1, {"answer_complete": 5}) is None
    assert workspace.patch_ratings(row["id"], 1, {"answer_complete": 5}) is None
    assert workspace.patch_ratings("missing", 0, {"answer_complete": 5}) is None
    stored = workspace.load()["dialogs"][0]["turns"][0]
    assert stored["answer"] == "ответ"
    assert stored["ratings"]["answer_correct"] == 2
    assert stored["ratings"]["answer_complete"] is None


def test_turn_records_each_source_document_once(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    saved = workspace.append_turn(row["id"], "вопрос", {
        "answer": "ответ",
        "sources": [
            {"document_name": "note.txt"},
            {"document_name": "note.txt"},
            {"document_name": ""},
            {},
            {"document_name": "other.txt"},
        ],
    })
    assert saved["turns"][0]["document_names"] == ["note.txt", "other.txt"]


def test_tree_keeps_basename_and_drops_a_repeated_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    data = workspace.put_tree({
        "id": "root",
        "name": "",
        "children": [
            {"document_name": "nested/note.txt"},
            {"document_name": "../secret.txt"},
            {"document_name": "missing.txt"},
            "not-a-node",
            {
                "id": "folder",
                "name": "",
                "children": [
                    {"id": "folder", "name": "повтор", "children": [{"document_name": "note.txt"}]},
                    {"document_name": "note.txt"},
                ],
            },
            {"id": "same", "name": "Первая", "children": []},
            {"id": "same", "name": "Вторая", "children": []},
            {"id": "wide", "name": "П" * 90, "children": []},
        ],
    }, ["note.txt", "secret.txt"])
    assert set(workspace.iter_files(data["tree"])) == {"note.txt", "secret.txt"}
    folders = [child for child in data["tree"]["children"] if "document_name" not in child]
    folder = next(item for item in folders if item["id"] == "folder")
    assert folder["name"] == "Папка"
    assert all(child.get("id") != "folder" for child in folder["children"])
    assert [item["name"] for item in folders if item["id"] == "same"] == ["Первая"]
    assert next(item for item in folders if item["id"] == "wide")["name"] == "П" * 80
    assert workspace.sanitize_tree(["x"], {"note.txt"}) == {"id": "root", "name": "", "children": []}


def test_corrupt_workspace_file_loads_as_empty(tmp_path, monkeypatch):
    path = tmp_path / "workspace.json"
    monkeypatch.setattr(workspace, "PATH", path)
    path.write_text("{", encoding="utf-8")
    assert workspace.load() == workspace.empty()
    path.write_text("[]", encoding="utf-8")
    assert workspace.load() == workspace.empty()
    path.write_text('{"dialogs": "nope", "tree": []}', encoding="utf-8")
    loaded = workspace.load()
    assert loaded["dialogs"] == []
    assert loaded["tree"] == {"id": "root", "name": "", "children": []}
    row = workspace.create_dialog()
    saved = workspace.load()
    assert [item["id"] for item in saved["dialogs"]] == [row["id"]]
    assert saved["dialogs"][0]["turns"] == []

def test_failed_replace_keeps_the_saved_workspace(tmp_path, monkeypatch):
    path = tmp_path / "workspace.json"
    monkeypatch.setattr(workspace, "PATH", path)
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    before = path.read_text(encoding="utf-8")
    original = Path.replace

    def replace(self, target):
        if self.parent == path.parent and self.name.startswith(".workspace.json."):
            raise OSError("disk full")
        return original(self, target)

    monkeypatch.setattr(Path, "replace", replace)
    with pytest.raises(OSError, match="disk full"):
        workspace.append_turn(row["id"], "второй", _answer("потеря"))
    assert path.read_text(encoding="utf-8") == before
    assert list(path.parent.glob(".workspace.json.*.tmp")) == []
    saved = workspace.load()["dialogs"]
    assert [turn["query"] for turn in saved[0]["turns"]] == ["вопрос"]

def test_corrupt_workspace_loads_as_empty(tmp_path, monkeypatch):
    path = tmp_path / "workspace.json"
    monkeypatch.setattr(workspace, "PATH", path)
    path.write_text("{", encoding="utf-8")
    assert workspace.load() == workspace.empty()
    path.write_text("[]", encoding="utf-8")
    assert workspace.load() == workspace.empty()
    path.write_text('{"dialogs": {"id": "x"}, "tree": []}', encoding="utf-8")
    loaded = workspace.load()
    assert loaded["dialogs"] == []
    assert loaded["tree"] == {"id": "root", "name": "", "children": []}
    row = workspace.create_dialog()
    assert workspace.load()["dialogs"][0]["id"] == row["id"]

def test_ratings_keep_one_to_five_and_strip_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    turn = workspace.patch_ratings(row["id"], 0, {
        "answer_complete": 0,
        "answer_correct": 6,
        "links": {"1": "4", "2": "нет", "3": None},
        "documents": {"../secret/note.txt": 3, "other.txt": ""},
    })
    ratings = turn["ratings"]
    assert ratings["answer_complete"] is None
    assert ratings["answer_correct"] is None
    assert ratings["links"] == {"1": 4, "2": None, "3": None}
    assert ratings["documents"] == {"note.txt": 3, "other.txt": None}
    again = workspace.patch_ratings(row["id"], 0, {"answer_complete": 5})
    assert again["ratings"]["answer_complete"] == 5
    assert again["ratings"]["links"]["1"] == 4
    assert workspace.patch_ratings(row["id"], -1, {"answer_complete": 1}) is None
    assert workspace.patch_ratings(row["id"], 1, {"answer_complete": 1}) is None
    assert workspace.patch_ratings("missing", 0, {"answer_complete": 1}) is None
    stored = workspace.load()["dialogs"][0]["turns"][0]["ratings"]["answer_complete"]
    assert stored == 5

def test_tree_drops_cycles_unknown_files_and_path_prefixes(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    saved = workspace.put_tree({
        "id": "root",
        "children": [
            {
                "id": "loop",
                "name": "",
                "children": [
                    {"id": "loop", "name": "снова", "children": [{"document_name": "hidden.txt"}]},
                    "bad",
                    {"document_name": "../note.txt"},
                    {"document_name": "missing.txt"},
                ],
            },
            {"id": "long", "name": "Я" * 90, "children": []},
        ],
    }, ["note.txt", "hidden.txt"])
    tree = saved["tree"]
    folder = next(child for child in tree["children"] if child.get("id") == "loop")
    assert folder["name"] == "Папка"
    assert folder["children"] == [{"document_name": "note.txt"}]
    long = next(child for child in tree["children"] if child.get("id") == "long")
    assert long["name"] == "Я" * 80
    root_files = [child.get("document_name") for child in tree["children"]]
    assert "hidden.txt" in root_files
    assert "missing.txt" not in workspace.iter_files(tree)
    assert workspace.iter_files(tree).count("note.txt") == 1
    assert workspace.iter_files(workspace.load()["tree"]) == workspace.iter_files(tree)

def test_title_is_trimmed_once_and_names_come_from_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    long_query = "  " + " ".join(["цех"] * 40) + "  "
    saved = workspace.append_turn(row["id"], long_query, {
        "answer": "ответ",
        "sources": [{"document_name": "note.txt"}, {"document_name": "note.txt"}, {"document_name": "pump.md"}],
    })
    assert saved["title"].endswith("…")
    assert len(saved["title"]) <= 61
    assert "  " not in saved["title"]
    assert saved["turns"][0]["document_names"] == ["note.txt", "pump.md"]
    again = workspace.append_turn(row["id"], "другой вопрос", _answer("ещё"))
    assert again["title"] == saved["title"]
    assert workspace.append_turn(row["id"], "   ", _answer("пусто"))["title"] == saved["title"]

def test_get_dialog_row_restores_memory_from_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    dialog.reset()
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    dialog.reset()
    assert dialog.get_dialog(row["id"]) == []
    loaded = workspace.get_dialog_row(row["id"])
    assert loaded["turns"][0]["answer"] == "ответ"
    assert dialog.get_dialog(row["id"]) == [{"query": "вопрос", "answer": "ответ", "document_names": []}]
    assert workspace.get_dialog_row("missing") is None
    assert dialog.get_dialog("missing") == []
