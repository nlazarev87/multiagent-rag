_dialogs = {}


def get_dialog(dialog_id):
    return list(_dialogs.get(dialog_id, []))


def add_turn(dialog_id, turn):
    rows = _dialogs.setdefault(dialog_id, [])
    rows.append(turn)
    if len(rows) > 20:
        del rows[0]


def set_dialog(dialog_id, turns):
    rows = []
    for turn in list(turns or [])[-20:]:
        names = []
        for name in turn.get("document_names") or []:
            if name and name not in names:
                names.append(name)
        if not names:
            for source in turn.get("sources") or []:
                name = source.get("document_name")
                if name and name not in names:
                    names.append(name)
        rows.append({
            "query": turn.get("query", ""),
            "answer": turn.get("answer", ""),
            "document_names": names,
        })
    _dialogs[dialog_id] = rows


def reset():
    _dialogs.clear()
