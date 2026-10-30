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


def test_set_dialog_reads_names_from_sources():
    dialog.reset()
    dialog.set_dialog("d", [{
        "query": "q",
        "answer": "a",
        "sources": [{"document_name": "note.txt"}, {"document_name": "note.txt"}],
    }])
    assert dialog.get_dialog("d")[0]["document_names"] == ["note.txt"]
