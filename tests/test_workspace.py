import threading
from pathlib import Path

import pytest

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


def test_overlapping_tree_write_keeps_the_new_turn(tmp_path, monkeypatch):
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
    editor = threading.Thread(target=save_tree)
    writer.start()
    started = False
    try:
        assert entered.wait(5)
        editor.start()
        started = True
        editor.join(0.5)
        assert editor.is_alive()
    finally:
        release.set()
    writer.join(5)
    if started:
        editor.join(5)
    assert errors == []
    assert not writer.is_alive()
    assert not editor.is_alive()
    saved = workspace.load()
    kept = next(item for item in saved["dialogs"] if item["id"] == dialog_id)
    assert [turn["query"] for turn in kept["turns"]] == ["первый", "второй"]
    assert kept["turns"][1]["answer"] == "новый"
    assert saved["tree"]["children"][0]["name"] == "Архив"
    assert workspace.iter_files(saved["tree"]) == ["note.txt"]


def test_failed_write_keeps_the_saved_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    original = (tmp_path / "workspace.json").read_text(encoding="utf-8")
    real_replace = Path.replace

    def fail_workspace_replace(self, target):
        if self.name.startswith(".workspace.json."):
            raise OSError("disk full")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_workspace_replace)
    with pytest.raises(OSError, match="disk full"):
        workspace.append_turn(row["id"], "второй", _answer("потеря"))
    assert (tmp_path / "workspace.json").read_text(encoding="utf-8") == original
    assert list(tmp_path.glob(".workspace.json.*.tmp")) == []
    saved = workspace.load()["dialogs"]
    assert [item["id"] for item in saved] == [row["id"]]
    assert [turn["query"] for turn in saved[0]["turns"]] == ["вопрос"]
    assert saved[0]["turns"][0]["answer"] == "ответ"


def test_patch_ratings_validates_scores_and_document_names(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    other = workspace.create_dialog()
    workspace.append_turn(other["id"], "другой", _answer("второй"))
    updated = workspace.patch_ratings(row["id"], 0, {
        "answer_complete": "4",
        "answer_correct": 5,
        "links": {"1": 3},
        "documents": {"note.txt": 2},
    })
    assert updated["ratings"]["answer_complete"] == 4
    assert updated["ratings"]["answer_correct"] == 5
    cleared = workspace.patch_ratings(row["id"], 0, {
        "answer_complete": 9,
        "links": {"1": "нет", "2": 1},
        "documents": {"../secret/note.txt": 3, "dir/other.txt": 0},
    })
    assert cleared["query"] == "вопрос"
    assert cleared["answer"] == "ответ"
    assert cleared["ratings"]["answer_complete"] is None
    assert cleared["ratings"]["answer_correct"] == 5
    assert cleared["ratings"]["links"] == {"1": None, "2": 1}
    assert cleared["ratings"]["documents"] == {"note.txt": 3, "other.txt": None}
    ignored = workspace.patch_ratings(row["id"], 0, {"links": ["1"], "documents": "note.txt"})
    assert ignored["ratings"]["links"]["2"] == 1
    assert ignored["ratings"]["documents"]["note.txt"] == 3
    assert workspace.patch_ratings(row["id"], 3, {"answer_complete": 1}) is None
    assert workspace.patch_ratings(row["id"], -1, {"answer_complete": 1}) is None
    assert workspace.patch_ratings("missing", 0, {"answer_complete": 1}) is None
    saved = workspace.load()["dialogs"]
    kept = next(item for item in saved if item["id"] == row["id"])
    assert kept["turns"][0]["ratings"]["answer_correct"] == 5
    assert kept["turns"][0]["answer"] == "ответ"
    untouched = next(item for item in saved if item["id"] == other["id"])
    assert untouched["turns"][0]["answer"] == "второй"
    assert untouched["turns"][0]["ratings"]["answer_complete"] is None


def test_put_tree_keeps_dialogs_and_drops_unsafe_nodes(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    saved = workspace.put_tree({
        "id": "root",
        "name": "",
        "children": [
            "skip",
            {"document_name": "../secret/note.txt"},
            {"document_name": "missing.txt"},
            {
                "id": "folder",
                "name": "П" * 100,
                "children": [
                    {"id": "folder", "name": "повтор", "children": [{"document_name": "hidden.txt"}]},
                    {"document_name": "note.txt"},
                ],
            },
            {"id": "empty", "name": "", "children": []},
        ],
    }, ["note.txt", "extra.txt"])
    assert saved["dialogs"][0]["turns"][0]["answer"] == "ответ"
    folders = [child for child in saved["tree"]["children"] if "document_name" not in child]
    assert folders[0]["id"] == "folder"
    assert folders[0]["name"] == "П" * 80
    assert folders[0]["children"] == [{"document_name": "note.txt"}]
    assert folders[1]["id"] == "empty"
    assert folders[1]["name"] == "Папка"
    names = workspace.iter_files(saved["tree"])
    assert "missing.txt" not in names
    assert "hidden.txt" not in names
    assert "../secret/note.txt" not in names
    assert names.count("note.txt") == 2
    assert names[-1] == "extra.txt"
    assert workspace.load()["dialogs"][0]["turns"][0]["query"] == "вопрос"


def test_append_turn_names_the_dialog_and_sorts_it_first(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    dialog.reset()
    older = workspace.create_dialog()
    newer = workspace.create_dialog()
    long_query = "  вопрос " + ("слово " * 20)
    row = workspace.append_turn(older["id"], long_query, {
        "answer": "ответ",
        "sources": [
            {"document_name": "note.txt"},
            {"document_name": "note.txt"},
            {"document_name": "other.txt"},
        ],
    })
    collapsed = " ".join(long_query.split())
    assert row["title"].endswith("…")
    assert "  " not in row["title"]
    assert collapsed.startswith(row["title"][:-1])
    assert len(row["title"]) < len(collapsed)
    assert row["turns"][0]["document_names"] == ["note.txt", "other.txt"]
    assert row["turns"][0]["ratings"] == workspace.blank_ratings()
    again = workspace.append_turn(older["id"], "ещё", {
        "answer": "второй",
        "document_names": ["kept.txt"],
        "sources": [{"document_name": "ignored.txt"}],
    })
    assert again["title"] == row["title"]
    assert again["turns"][1]["document_names"] == ["kept.txt"]
    assert [item["id"] for item in workspace.load()["dialogs"]][0] == older["id"]
    blank = workspace.append_turn(newer["id"], "   ", {"answer": ""})
    assert blank["title"] == workspace.TITLE


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

def test_dialog_memory_keeps_the_last_twenty_saved_turns(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    dialog.reset()
    created = workspace.create_dialog()
    for index in range(25):
        workspace.append_turn(created["id"], f"вопрос {index}", {
            "answer": f"ответ {index}",
            "sources": [{"document_name": "note.txt"}],
            "document_names": ["note.txt"],
        })
    dialog.reset()
    prepared = workspace.prepare_dialog(created["id"])
    assert [turn["query"] for turn in prepared["turns"]] == [f"вопрос {index}" for index in range(25)]
    assert [turn["query"] for turn in dialog.get_dialog(created["id"])] == [f"вопрос {index}" for index in range(5, 25)]
    assert dialog.get_dialog(created["id"])[0]["document_names"] == ["note.txt"]
    dialog.set_dialog("missing", [{"query": "секрет", "answer": "a", "document_names": ["note.txt"]}])
    assert workspace.prepare_dialog("missing") is None
    assert dialog.get_dialog("missing") == []
    dialog.reset()
    loaded = workspace.get_dialog_row(created["id"])
    assert len(loaded["turns"]) == 25
    assert [turn["query"] for turn in dialog.get_dialog(created["id"])] == [f"вопрос {index}" for index in range(5, 25)]
    assert workspace.get_dialog_row("missing") is None
    assert all(item["id"] != "missing" for item in workspace.load()["dialogs"])

def test_failed_replace_keeps_the_saved_dialog(tmp_path, monkeypatch):
    path = tmp_path / "workspace.json"
    monkeypatch.setattr(workspace, "PATH", path)
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    original = path.read_text(encoding="utf-8")
    real_replace = Path.replace

    def fail_temp(self, target):
        if self.name.startswith(".workspace.json.") and self.name.endswith(".tmp"):
            raise OSError("disk full")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_temp)
    with pytest.raises(OSError, match="disk full"):
        workspace.append_turn(row["id"], "второй", _answer("потеря"))
    assert path.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob(".workspace.json.*.tmp")) == []
    saved = workspace.load()["dialogs"]
    assert [turn["query"] for turn in saved[0]["turns"]] == ["вопрос"]
    assert saved[0]["turns"][0]["answer"] == "ответ"

def test_ratings_keep_partial_updates_and_reject_bad_scores(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    workspace.patch_ratings(row["id"], 0, {
        "links": {"1": 5},
        "documents": {"note.txt": 3},
    })
    saved = workspace.patch_ratings(row["id"], 0, {
        "answer_complete": "5",
        "answer_correct": 0,
        "links": {"2": "нет"},
        "documents": {"../../note.txt": 9, "folder/other.txt": 4},
    })
    assert saved["ratings"]["answer_complete"] == 5
    assert saved["ratings"]["answer_correct"] is None
    assert saved["ratings"]["links"] == {"1": 5, "2": None}
    assert saved["ratings"]["documents"] == {"note.txt": None, "other.txt": 4}
    assert workspace.patch_ratings(row["id"], 3, {"answer_complete": 1}) is None
    assert workspace.patch_ratings("missing", 0, {"answer_complete": 1}) is None
    again = next(item for item in workspace.load()["dialogs"] if item["id"] == row["id"])
    assert again["turns"][0]["answer"] == "ответ"
    assert again["turns"][0]["ratings"]["links"]["1"] == 5
    assert again["turns"][0]["ratings"]["answer_complete"] == 5

def test_prepare_dialog_clears_memory_when_the_dialog_is_not_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    dialog.reset()
    dialog.add_turn("ghost", {"query": "секрет", "answer": "x", "document_names": ["hidden.txt"]})
    assert workspace.prepare_dialog("ghost") is None
    assert dialog.get_dialog("ghost") == []

def test_append_turn_reads_document_names_from_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    saved = workspace.append_turn(row["id"], "вопрос", {
        "answer": "ответ",
        "document_names": [],
        "sources": [
            {"document_name": "note.txt"},
            {"document_name": "note.txt"},
            {"document_name": ""},
            {"document_name": "other.txt"},
        ],
    })
    assert saved["turns"][0]["document_names"] == ["note.txt", "other.txt"]
    assert saved["title"] == "вопрос"
    again = workspace.append_turn(row["id"], "другой вопрос", _answer("ещё"))
    assert again["title"] == "вопрос"

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

def _freeze_clock(monkeypatch):
    clock = {"n": 0}

    def now():
        clock["n"] += 1
        return f"2020-01-01T00:00:{clock['n']:02d}+00:00"

    monkeypatch.setattr(workspace, "_now", now)

def _run_beside_append(monkeypatch, dialog_id, other):
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

    def side():
        try:
            other()
        except Exception as exc:
            errors.append(exc)

    writer = threading.Thread(target=add_turn)
    extra = threading.Thread(target=side)
    writer.start()
    started = False
    try:
        assert entered.wait(5)
        extra.start()
        started = True
        extra.join(0.5)
        assert extra.is_alive()
    finally:
        release.set()
    writer.join(5)
    if started:
        extra.join(5)
    assert errors == []
    assert not writer.is_alive()
    assert not extra.is_alive()

def test_load_keeps_a_broken_file_until_the_next_save(tmp_path, monkeypatch):
    path = tmp_path / "workspace.json"
    monkeypatch.setattr(workspace, "PATH", path)
    path.write_text("{", encoding="utf-8")
    assert workspace.load() == workspace.empty()
    assert path.read_text(encoding="utf-8") == "{"
    path.write_text("[]", encoding="utf-8")
    assert workspace.load() == workspace.empty()
    assert path.read_text(encoding="utf-8") == "[]"
    raw = '{"dialogs": {"id": "x"}, "tree": []}'
    path.write_text(raw, encoding="utf-8")
    loaded = workspace.load()
    assert loaded["dialogs"] == []
    assert loaded["tree"] == {"id": "root", "name": "", "children": []}
    assert path.read_text(encoding="utf-8") == raw
    row = workspace.create_dialog()
    saved = workspace.load()
    assert saved["dialogs"][0]["id"] == row["id"]
    assert saved["tree"]["id"] == "root"

def test_prepare_dialog_restores_saved_scope_without_creating_a_row(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    dialog.reset()
    row = workspace.create_dialog()
    data = workspace.load()
    data["dialogs"][0]["turns"] = [{
        "query": "где насос",
        "answer": "в цехе",
        "sources": [
            {"document_name": "pump.md"},
            {"document_name": "pump.md"},
            {"document_name": "note.txt"},
        ],
    }]
    workspace.save(data)
    dialog.add_turn(row["id"], {"query": "устарело", "answer": "x", "document_names": ["other.md"]})
    found = workspace.prepare_dialog(row["id"])
    assert found["id"] == row["id"]
    assert dialog.get_dialog(row["id"]) == [{
        "query": "где насос",
        "answer": "в цехе",
        "document_names": ["pump.md", "note.txt"],
    }]
    dialog.add_turn("missing", {"query": "устарело", "answer": "x", "document_names": ["other.md"]})
    assert workspace.prepare_dialog("missing") is None
    assert dialog.get_dialog("missing") == []
    assert all(item["id"] != "missing" for item in workspace.load()["dialogs"])

def test_append_turn_names_sources_and_keeps_the_title(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    dialog.reset()
    _freeze_clock(monkeypatch)
    first = workspace.create_dialog()
    second = workspace.create_dialog()
    saved = workspace.append_turn(first["id"], "а" * 61, {
        "answer": "6 бар",
        "document_names": [],
        "sources": [
            {"document_name": "pump.md"},
            {"document_name": "pump.md"},
            {"document_name": ""},
            {"document_name": "note.txt"},
        ],
    })
    assert saved["title"] == ("а" * 60) + "…"
    assert saved["turns"][0]["document_names"] == ["pump.md", "note.txt"]
    again = workspace.append_turn(first["id"], "другой вопрос", _answer("дальше"))
    assert again["title"] == ("а" * 60) + "…"
    assert [item["id"] for item in workspace.load()["dialogs"]][0] == first["id"]
    blank = workspace.append_turn(second["id"], "   ", _answer("пусто"))
    assert blank["title"] == workspace.TITLE
    assert [item["id"] for item in workspace.load()["dialogs"]][0] == second["id"]

def test_sanitize_tree_stops_on_a_repeated_folder_and_strips_paths():
    tree = workspace.sanitize_tree({
        "id": "root",
        "name": "",
        "children": [
            {
                "id": "loop",
                "name": "",
                "children": [
                    {"id": "loop", "name": "снова", "children": [{"document_name": "note.txt"}]},
                    {"document_name": "sub/note.txt"},
                    {"document_name": "../secret.txt"},
                    "nope",
                ],
            },
            {"id": "long", "name": "П" * 90, "children": []},
        ],
    }, {"note.txt"})
    assert tree == {
        "id": "root",
        "name": "",
        "children": [
            {"id": "loop", "name": "Папка", "children": [{"document_name": "note.txt"}]},
            {"id": "long", "name": "П" * 80, "children": []},
        ],
    }

def test_patch_ratings_merges_and_rejects_out_of_range(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    dialog.reset()
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", {
        "answer": "ответ",
        "sources": [{"number": 1, "document_name": "note.txt"}],
        "document_names": ["note.txt"],
    })
    assert workspace.patch_ratings(row["id"], 0, {"answer_complete": 4})["ratings"]["answer_complete"] == 4
    workspace.patch_ratings(row["id"], 0, {"answer_correct": "5"})
    workspace.patch_ratings(row["id"], 0, {"links": {"1": 3}})
    workspace.patch_ratings(row["id"], 0, {"links": {"2": "4", "3": "нет"}})
    workspace.patch_ratings(row["id"], 0, {"documents": {"note.txt": 2}})
    workspace.patch_ratings(row["id"], 0, {"documents": {"../../note.txt": 1, "other.txt": 6}})
    workspace.patch_ratings(row["id"], 0, {"answer_complete": 0})
    assert workspace.patch_ratings(row["id"], -1, {"answer_correct": 1}) is None
    assert workspace.patch_ratings(row["id"], 3, {"answer_correct": 1}) is None
    assert workspace.patch_ratings("missing", 0, {"answer_correct": 1}) is None
    ratings = workspace.load()["dialogs"][0]["turns"][0]["ratings"]
    assert ratings == {
        "answer_complete": None,
        "answer_correct": 5,
        "links": {"1": 3, "2": 4, "3": None},
        "documents": {"note.txt": 1, "other.txt": None},
    }

def test_broken_workspace_file_loads_empty_and_can_be_saved(tmp_path, monkeypatch):
    path = tmp_path / "workspace.json"
    monkeypatch.setattr(workspace, "PATH", path)
    for text in ("{", "[]", '{"dialogs": {}, "tree": []}'):
        path.write_text(text, encoding="utf-8")
        assert workspace.load() == workspace.empty()
    row = workspace.create_dialog()
    assert workspace.load()["dialogs"][0]["id"] == row["id"]

def test_append_turn_keeps_title_sources_and_order(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    clock = {"n": 0}

    def now():
        clock["n"] += 1
        return f"2020-01-01T00:00:{clock['n']:02d}+00:00"

    monkeypatch.setattr(workspace, "_now", now)
    older = workspace.create_dialog()
    newer = workspace.create_dialog()
    long_query = "а" * 80
    workspace.append_turn(older["id"], long_query, {
        "answer": "ответ",
        "document_names": [],
        "sources": [
            {"document_name": "note.txt"},
            {"document_name": "note.txt"},
            {"document_name": "other.txt"},
        ],
    })
    workspace.append_turn(older["id"], "второй вопрос", _answer("ещё"))
    saved = next(item for item in workspace.load()["dialogs"] if item["id"] == older["id"])
    assert saved["title"] == "а" * 60 + "…"
    assert [turn["query"] for turn in saved["turns"]] == [long_query, "второй вопрос"]
    assert saved["turns"][0]["document_names"] == ["note.txt", "other.txt"]
    assert [item["id"] for item in workspace.load()["dialogs"]][:2] == [older["id"], newer["id"]]
    blank = workspace.create_dialog()
    workspace.append_turn(blank["id"], "   ", _answer("пусто"))
    titled = next(item for item in workspace.load()["dialogs"] if item["id"] == blank["id"])
    assert titled["title"] == workspace.TITLE
    assert next(item for item in workspace.load()["dialogs"] if item["id"] == newer["id"])["turns"] == []

def test_snapshot_lists_known_files_once_and_keeps_dialogs(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    workspace.put_tree({
        "id": "root",
        "name": "",
        "children": [{"document_name": "note.txt"}],
    }, ["note.txt"])
    first = workspace.snapshot(["note.txt", "other.txt"])
    second = workspace.snapshot(["note.txt", "other.txt"])
    assert workspace.iter_files(first["tree"]) == ["note.txt", "other.txt"]
    assert workspace.iter_files(second["tree"]) == ["note.txt", "other.txt"]
    assert second["dialogs"][0]["id"] == row["id"]
    assert second["dialogs"][0]["turns"][0]["answer"] == "ответ"

def test_get_dialog_row_keeps_the_last_twenty_turns(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    dialog.reset()
    row = workspace.create_dialog()
    for number in range(25):
        workspace.append_turn(row["id"], str(number), _answer(str(number)))
    dialog.reset()
    loaded = workspace.get_dialog_row(row["id"])
    assert loaded["id"] == row["id"]
    assert [turn["query"] for turn in dialog.get_dialog(row["id"])] == [str(number) for number in range(5, 25)]
    assert len(workspace.load()["dialogs"][0]["turns"]) == 25
    assert workspace.get_dialog_row("missing") is None
