import threading

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


def test_overlapping_tree_save_keeps_the_new_turn(tmp_path, monkeypatch):
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

    def save_tree():
        try:
            workspace.put_tree(
                {"id": "root", "name": "", "children": [{"document_name": "note.txt"}]},
                ["note.txt"],
            )
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
    assert workspace.iter_files(saved["tree"]) == ["note.txt"]


def test_ratings_keep_only_scores_from_one_to_five(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "первый", _answer("старый"))
    workspace.append_turn(row["id"], "второй", _answer("новый"))
    first = workspace.patch_ratings(row["id"], 0, {
        "answer_complete": 5,
        "answer_correct": "4",
        "links": {"1": 3, "2": 0, "3": "нет"},
        "documents": {"../inbox/note.txt": 2, "missing.txt": 9, "": 1},
    })
    assert first["ratings"]["answer_complete"] == 5
    assert first["ratings"]["answer_correct"] == 4
    assert first["ratings"]["links"] == {"1": 3, "2": None, "3": None}
    assert first["ratings"]["documents"]["note.txt"] == 2
    assert first["ratings"]["documents"]["missing.txt"] is None
    assert all("/" not in key for key in first["ratings"]["documents"])
    merged = workspace.patch_ratings(row["id"], 0, {"links": {"1": 1}, "documents": ["нет"]})
    assert merged["ratings"]["links"] == {"1": 1, "2": None, "3": None}
    assert merged["ratings"]["documents"]["note.txt"] == 2
    assert merged["ratings"]["answer_complete"] == 5
    cleared = workspace.patch_ratings(row["id"], 0, {"answer_complete": 6, "answer_correct": ""})
    assert cleared["ratings"]["answer_complete"] is None
    assert cleared["ratings"]["answer_correct"] is None
    assert cleared["ratings"]["links"]["1"] == 1
    saved = workspace.load()["dialogs"][0]
    assert saved["turns"][1]["ratings"] == workspace.blank_ratings()
    assert workspace.patch_ratings(row["id"], -1, {"answer_complete": 1}) is None
    assert workspace.patch_ratings(row["id"], 5, {"answer_complete": 1}) is None
    assert workspace.patch_ratings("missing", 0, {"answer_complete": 1}) is None
    assert workspace.load()["dialogs"][0]["turns"][0]["ratings"]["links"]["1"] == 1


def test_tree_strips_paths_and_skips_duplicate_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    saved = workspace.put_tree({
        "id": "root",
        "name": "",
        "children": [
            "skip",
            {"document_name": "../inbox/note.txt"},
            {"document_name": "../secret.txt"},
            {"id": "same", "name": "", "children": [{"document_name": "kept.txt"}]},
            {"id": "same", "name": "повтор", "children": [{"document_name": "hidden.txt"}]},
            {"id": "long", "name": "П" * 90, "children": []},
        ],
    }, ["note.txt", "kept.txt", "hidden.txt"])
    assert saved["dialogs"][0]["id"] == row["id"]
    assert saved["dialogs"][0]["turns"][0]["answer"] == "ответ"
    files = workspace.iter_files(saved["tree"])
    assert files.count("note.txt") == 1
    assert files.count("kept.txt") == 1
    assert files.count("hidden.txt") == 1
    assert "secret.txt" not in files
    assert all("/" not in name and "\\" not in name for name in files)
    folders = [child for child in saved["tree"]["children"] if "document_name" not in child]
    assert [folder["id"] for folder in folders].count("same") == 1
    same = next(folder for folder in folders if folder["id"] == "same")
    assert same["name"] == "Папка"
    assert workspace.iter_files(same) == ["kept.txt"]
    long_folder = next(folder for folder in folders if folder["id"] == "long")
    assert long_folder["name"] == "П" * 80
    root_files = [child["document_name"] for child in saved["tree"]["children"] if child.get("document_name")]
    assert "hidden.txt" in root_files


def test_dialog_title_and_source_names(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    first = workspace.append_turn(row["id"], "   ", {
        "answer": "пусто",
        "sources": [
            {"document_name": "note.txt"},
            {"document_name": ""},
            {"document_name": "note.txt"},
            {"document_name": "other.txt"},
        ],
    })
    assert first["title"] == "Новый диалог"
    assert first["turns"][0]["document_names"] == ["note.txt", "other.txt"]
    second = workspace.append_turn(row["id"], "  Какой   номер  ", _answer("4"))
    assert second["title"] == "Какой номер"
    third = workspace.append_turn(row["id"], "Б" * 80, _answer("дальше"))
    assert third["title"] == "Какой номер"
    fresh = workspace.create_dialog()
    titled = workspace.append_turn(fresh["id"], "А" * 70, _answer("а"))
    assert titled["title"] == ("А" * 60) + "…"


def test_broken_workspace_file_loads_as_empty(tmp_path, monkeypatch):
    path = tmp_path / "workspace.json"
    monkeypatch.setattr(workspace, "PATH", path)
    path.write_text("{", encoding="utf-8")
    assert workspace.load() == workspace.empty()
    path.write_text("[]", encoding="utf-8")
    assert workspace.load() == workspace.empty()
    path.write_text('{"dialogs": "нет", "tree": []}', encoding="utf-8")
    assert workspace.load() == workspace.empty()


def test_failed_write_removes_the_temporary_file(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    real = workspace.Path.write_text

    def boom(self, *args, **kwargs):
        if self.name.startswith(".workspace.json."):
            raise OSError("disk")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(workspace.Path, "write_text", boom)
    with pytest.raises(OSError, match="disk"):
        workspace.create_dialog()
    assert list(tmp_path.iterdir()) == []


def test_append_does_not_recreate_a_deleted_dialog(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    workspace.delete_dialog(row["id"])
    assert workspace.append_turn(row["id"], "вопрос", _answer("ответ"), create=False) is None
    assert all(item["id"] != row["id"] for item in workspace.load()["dialogs"])
    assert dialog.get_dialog(row["id"]) == []
