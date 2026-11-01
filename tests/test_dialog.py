import dialog


def test_dialog_keeps_twenty_turns():
    dialog.reset()
    for index in range(21):
        dialog.add_turn("d", {"query": str(index), "answer": "a", "document_names": []})
    rows = dialog.get_dialog("d")
    assert len(rows) == 20
    assert rows[0]["query"] == "1"


def test_set_dialog_keeps_twenty_turns():
    dialog.reset()
    turns = [{"query": str(index), "answer": "a", "document_names": ["a.md"]} for index in range(25)]
    dialog.set_dialog("d", turns)
    rows = dialog.get_dialog("d")
    assert len(rows) == 20
    assert rows[0]["query"] == "5"
    assert rows[-1]["query"] == "24"


def test_drop_dialog_forgets_turns():
    dialog.reset()
    dialog.add_turn("d", {"query": "q", "answer": "a", "document_names": []})
    dialog.drop_dialog("d")
    assert dialog.get_dialog("d") == []


def test_set_dialog_uses_listed_names_without_sources():
    dialog.reset()
    dialog.set_dialog("d", [{
        "query": "q",
        "document_names": ["note.txt", "", "note.txt", "other.txt"],
        "sources": [{"document_name": "ignored.txt"}],
    }])
    assert dialog.get_dialog("d") == [{
        "query": "q",
        "answer": "",
        "document_names": ["note.txt", "other.txt"],
    }]
    dialog.set_dialog("d", None)
    assert dialog.get_dialog("d") == []


def test_set_dialog_reads_names_from_sources():
    dialog.reset()
    dialog.set_dialog("d", [{
        "query": "q",
        "answer": "a",
        "sources": [{"document_name": "note.txt"}, {"document_name": "note.txt"}],
    }])
    assert dialog.get_dialog("d")[0]["document_names"] == ["note.txt"]


def test_get_dialog_copy_does_not_change_memory():
    dialog.reset()
    dialog.add_turn("d", {"query": "q", "answer": "a", "document_names": ["note.txt"]})
    rows = dialog.get_dialog("d")
    rows.append({"query": "extra", "answer": "", "document_names": []})
    rows.clear()
    assert dialog.get_dialog("missing") == []
    dialog.get_dialog("missing").append({"query": "x"})
    assert dialog.get_dialog("d") == [{
        "query": "q",
        "answer": "a",
        "document_names": ["note.txt"],
    }]
    assert dialog.get_dialog("missing") == []


def test_set_dialog_skips_blank_names_before_sources():
    dialog.reset()
    dialog.set_dialog("d", [{
        "query": "q",
        "answer": "a",
        "document_names": ["", "note.txt", ""],
        "sources": [{"document_name": "other.txt"}],
    }])
    assert dialog.get_dialog("d")[0]["document_names"] == ["note.txt"]
    dialog.set_dialog("d", [{
        "query": "q",
        "answer": "a",
        "document_names": ["", ""],
        "sources": [
            {},
            {"document_name": ""},
            {"document_name": "b.txt"},
            {"document_name": "a.txt"},
            {"document_name": "b.txt"},
        ],
    }])
    assert dialog.get_dialog("d")[0]["document_names"] == ["b.txt", "a.txt"]


def test_get_dialog_copy_ignores_later_edits():
    dialog.reset()
    turn = {"query": "q", "answer": "a", "document_names": ["note.txt"]}
    dialog.set_dialog("d", [turn])
    turn["query"] = "changed"
    turn["document_names"].append("other.txt")
    rows = dialog.get_dialog("d")
    assert rows == [{"query": "q", "answer": "a", "document_names": ["note.txt"]}]
    rows.clear()
    rows.append({"query": "other", "answer": "b", "document_names": []})
    assert dialog.get_dialog("d") == [{"query": "q", "answer": "a", "document_names": ["note.txt"]}]


def test_set_dialog_reads_sources_when_listed_names_are_blank():
    dialog.reset()
    dialog.set_dialog("d", [{
        "query": "q",
        "answer": "a",
        "document_names": ["", None],
        "sources": [
            {"document_name": ""},
            {"document_name": "note.txt"},
            {"document_name": "note.txt"},
            {},
        ],
    }])
    assert dialog.get_dialog("d") == [{
        "query": "q",
        "answer": "a",
        "document_names": ["note.txt"],
    }]
