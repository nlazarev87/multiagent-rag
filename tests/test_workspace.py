import threading
from pathlib import Path

import pytest

import dialog
import workspace


def _answer(text):
    return {"answer": text, "sources": [], "document_names": []}


def _overlap(monkeypatch, first, second):
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

    def run(fn):
        try:
            fn()
        except Exception as exc:
            errors.append(exc)

    writer = threading.Thread(target=run, args=(first,))
    other = threading.Thread(target=run, args=(second,))
    writer.start()
    started = False
    try:
        assert entered.wait(5)
        other.start()
        started = True
        other.join(0.5)
        assert other.is_alive()
    finally:
        release.set()
    writer.join(5)
    if started:
        other.join(5)
    assert errors == []
    assert not writer.is_alive()
    assert not other.is_alive()


def test_overlapping_rating_keeps_the_new_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    dialog.reset()
    row = workspace.create_dialog()
    dialog_id = row["id"]
    workspace.append_turn(dialog_id, "первый", _answer("старый"))

    def add_turn():
        workspace.append_turn(dialog_id, "второй", _answer("новый"))

    def rate():
        workspace.patch_ratings(dialog_id, 0, {"answer_complete": 5})

    _overlap(monkeypatch, add_turn, rate)
    saved = next(item for item in workspace.load()["dialogs"] if item["id"] == dialog_id)
    assert [turn["query"] for turn in saved["turns"]] == ["первый", "второй"]
    assert saved["turns"][0]["ratings"]["answer_complete"] == 5
    assert saved["turns"][1]["answer"] == "новый"


def test_overlapping_tree_write_keeps_the_new_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    dialog.reset()
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "первый", _answer("старый"))
    workspace.put_tree(
        {"id": "root", "name": "", "children": [{"document_name": "old.txt"}]},
        ["old.txt", "note.txt"],
    )

    def add_turn():
        workspace.append_turn(row["id"], "второй", _answer("новый"))

    def move():
        workspace.put_tree({
            "id": "root",
            "name": "",
            "children": [
                {"id": "folder", "name": "Папка", "children": [{"document_name": "note.txt"}]},
            ],
        }, ["note.txt"])

    _overlap(monkeypatch, add_turn, move)
    saved = workspace.load()
    stored = next(item for item in saved["dialogs"] if item["id"] == row["id"])
    assert [turn["query"] for turn in stored["turns"]] == ["первый", "второй"]
    assert stored["turns"][1]["answer"] == "новый"
    assert workspace.iter_files(saved["tree"]) == ["note.txt"]
    assert saved["tree"]["children"][0]["name"] == "Папка"


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


def test_ratings_keep_scores_from_one_to_five(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    first = workspace.patch_ratings(row["id"], 0, {
        "answer_complete": 5,
        "answer_correct": "4",
        "links": {"1": 3},
        "documents": {"notes/note.txt": 2},
    })
    assert first["ratings"]["answer_correct"] == 4
    assert first["ratings"]["documents"] == {"note.txt": 2}
    second = workspace.patch_ratings(row["id"], 0, {
        "answer_complete": 0,
        "links": {"1": "нет", "2": 5},
        "documents": {"../other.txt": 8},
    })
    assert second["ratings"]["answer_complete"] is None
    assert second["ratings"]["answer_correct"] == 4
    assert second["ratings"]["links"] == {"1": None, "2": 5}
    assert second["ratings"]["documents"] == {"note.txt": 2, "other.txt": None}
    assert workspace.patch_ratings(row["id"], 3, {"answer_complete": 1}) is None
    assert workspace.patch_ratings("missing", 0, {"answer_complete": 1}) is None


def test_append_turn_keeps_source_documents_and_the_first_title(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    dialog.reset()
    row = workspace.create_dialog()
    saved = workspace.append_turn(row["id"], "номер цеха", {
        "answer": "4",
        "sources": [
            {"document_name": "charter.txt"},
            {"document_name": "charter.txt"},
            {"document_name": "pump.md"},
        ],
    })
    assert saved["title"] == "номер цеха"
    assert saved["turns"][0]["document_names"] == ["charter.txt", "pump.md"]
    again = workspace.append_turn(row["id"], "сколько она длится", {
        "answer": "8",
        "document_names": ["charter.txt"],
        "sources": [{"document_name": "pump.md"}],
    })
    assert again["title"] == "номер цеха"
    assert again["turns"][1]["document_names"] == ["charter.txt"]
    dialog.reset()
    assert workspace.prepare_dialog(row["id"])["id"] == row["id"]
    assert dialog.get_dialog(row["id"])[0]["document_names"] == ["charter.txt", "pump.md"]
    assert dialog.get_dialog(row["id"])[1]["document_names"] == ["charter.txt"]


def test_prepare_missing_dialog_clears_stale_memory(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    dialog.reset()
    dialog.add_turn("gone", {"query": "старое", "answer": "а", "document_names": ["note.txt"]})
    assert workspace.prepare_dialog("gone") is None
    assert dialog.get_dialog("gone") == []
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    dialog.reset()
    loaded = workspace.get_dialog_row(row["id"])
    assert loaded["turns"][0]["query"] == "вопрос"
    assert dialog.get_dialog(row["id"]) == [{"query": "вопрос", "answer": "ответ", "document_names": []}]


def test_tree_stops_on_a_repeated_folder_and_drops_foreign_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    folder = {"id": "a", "name": "", "children": [{"document_name": "notes/note.txt"}]}
    folder["children"].append(folder)
    saved = workspace.put_tree({
        "id": "root",
        "name": "",
        "children": [
            folder,
            {"document_name": "../missing.txt"},
            {"document_name": "nested/note.txt"},
            "nope",
        ],
    }, ["note.txt"])
    assert workspace.iter_files(saved["tree"]) == ["note.txt", "note.txt"]
    assert saved["tree"]["children"][0]["name"] == "Папка"
    assert saved["tree"]["children"][0]["children"] == [{"document_name": "note.txt"}]
    assert "missing.txt" not in workspace.iter_files(saved["tree"])


def test_corrupt_workspace_file_loads_as_empty(tmp_path, monkeypatch):
    path = tmp_path / "workspace.json"
    monkeypatch.setattr(workspace, "PATH", path)
    path.write_text("{", encoding="utf-8")
    assert workspace.load() == workspace.empty()
    path.write_text("[]", encoding="utf-8")
    assert workspace.load() == workspace.empty()
    path.write_text('{"dialogs": {}, "tree": "no"}', encoding="utf-8")
    assert workspace.load() == workspace.empty()


def test_failed_replace_keeps_saved_dialogs(tmp_path, monkeypatch):
    path = tmp_path / "workspace.json"
    monkeypatch.setattr(workspace, "PATH", path)
    row = workspace.create_dialog()
    original = path.read_bytes()
    real_replace = Path.replace

    def fail_temp(self, target):
        if self.name.startswith(f".{path.name}."):
            raise OSError("replace failed")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_temp)
    with pytest.raises(OSError, match="replace failed"):
        workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    assert path.read_bytes() == original
    assert list(tmp_path.glob(f".{path.name}.*.tmp")) == []
    saved = workspace.load()
    assert saved["dialogs"][0]["id"] == row["id"]
    assert saved["dialogs"][0]["turns"] == []
