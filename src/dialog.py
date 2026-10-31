"""Память диалога внутри процесса. На диске то же хранит workspace.

Координатор видит последние 20 ходов. Имена документов хода берутся из
document_names или, если их нет, из sources.
"""
_dialogs = {}


def get_dialog(dialog_id):
    """Копия ходов диалога. Чужой код может менять список, не трогая память."""
    return list(_dialogs.get(dialog_id, []))


def add_turn(dialog_id, turn):
    """Добавить ход и оставить только последние 20."""
    rows = _dialogs.setdefault(dialog_id, [])
    rows.append(turn)
    if len(rows) > 20:
        del rows[0]


def set_dialog(dialog_id, turns):
    """Заменить ходы последними 20. Имена документов читаются из хода или из sources."""
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


def drop_dialog(dialog_id):
    """Забыть диалог в памяти процесса."""
    _dialogs.pop(dialog_id, None)


def reset():
    _dialogs.clear()
