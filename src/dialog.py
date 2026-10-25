_dialogs = {}


def get_dialog(dialog_id):
    return list(_dialogs.get(dialog_id, []))


def add_turn(dialog_id, turn):
    rows = _dialogs.setdefault(dialog_id, [])
    rows.append(turn)
    if len(rows) > 20:
        del rows[0]


def reset():
    _dialogs.clear()
