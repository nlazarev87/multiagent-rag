"""Память диалога внутри процесса. На диске то же хранит workspace.

Координатор видит последние 20 ходов. Имена документов хода берутся из
document_names или, если их нет, из sources.
"""
import threading

_dialogs = {}
_lock = threading.Lock()


def get_dialog(dialog_id):
    """Копия ходов диалога. Чужой код может менять список, не трогая память."""
    with _lock:
        return list(_dialogs.get(dialog_id, []))


def add_turn(dialog_id, turn):
    """Добавить ход и оставить только последние 20."""
    with _lock:
        rows = _dialogs.setdefault(dialog_id, [])
        rows.append(turn)
        if len(rows) > 20:
            del rows[0]


def _places(turn, names):
    places = []
    seen = set()
    for item in turn.get("places") or []:
        name = item.get("document_name")
        if name and (item.get("kb_id") or "", name) not in seen:
            places.append({"kb_id": item.get("kb_id") or "", "document_name": name})
            seen.add((item.get("kb_id") or "", name))
    for source in turn.get("sources") or []:
        name = source.get("document_name")
        kb_id = source.get("kb_id") or ""
        if name and kb_id and (kb_id, name) not in seen:
            places.append({"kb_id": kb_id, "document_name": name})
            seen.add((kb_id, name))
    return places


def set_dialog(dialog_id, turns):
    """Заменить ходы последними 20. Имена документов читаются из хода или из sources."""
    rows = []
    for turn in list(turns or [])[-20:]:
        names = []
        for name in turn.get("document_names") or []:
            if isinstance(name, str) and name and name not in names:
                names.append(name)
        if not names:
            for source in turn.get("sources") or []:
                name = source.get("document_name")
                if name and name not in names:
                    names.append(name)
        row = {
            "query": turn.get("query", ""),
            "answer": turn.get("answer", ""),
            "document_names": names,
        }
        places = _places(turn, names)
        if places:
            row["places"] = places
        rows.append(row)
    with _lock:
        _dialogs[dialog_id] = rows


def drop_dialog(dialog_id):
    """Забыть диалог в памяти процесса."""
    with _lock:
        _dialogs.pop(dialog_id, None)


def reset():
    with _lock:
        _dialogs.clear()
