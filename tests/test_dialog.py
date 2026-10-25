import dialog


def test_dialog_keeps_twenty_turns():
    dialog.reset()
    for index in range(21):
        dialog.add_turn("d", {"query": str(index), "answer": "a", "document_names": []})
    rows = dialog.get_dialog("d")
    assert len(rows) == 20
    assert rows[0]["query"] == "1"
