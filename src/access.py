"""Открытие базы и действия. Закрытие человека, его роли или его группы перекрывает открытие."""
import auth
import kb
from permit import Permit, sign

CONTENT = auth.CONTENT_ACTIONS


def _subjects(user):
    pairs = [("user", user["id"]), ("role", user["role_id"])]
    for group_id in auth.group_ids_for(user):
        pairs.append(("group", group_id))
    return pairs


def opened(user, kb_id):
    if user is None or kb.get(kb_id) is None:
        return False
    rows = auth.acl_rows(kb_id)
    subjects = set(_subjects(user))
    if any((row["subject_type"], row["subject_id"]) in subjects and row["effect"] == "deny" for row in rows):
        return False
    return any((row["subject_type"], row["subject_id"]) in subjects and row["effect"] == "allow" for row in rows)


def actions_for(user, kb_id):
    if user is None:
        return set()
    return set(auth.role_content(user["role_id"], kb_id)) | set(auth.user_content(user["id"], kb_id))


def can(user, kb_id, action):
    return opened(user, kb_id) and action in actions_for(user, kb_id)


def can_see(user, kb_id):
    return opened(user, kb_id) and bool(actions_for(user, kb_id) & set(CONTENT))


def has_global(user, action):
    return user is not None and action in (user.get("actions") or [])


def issue_see(user, kb_id):
    """Допуск на чтение списка или текста: хватает любого из четырёх действий."""
    for action in CONTENT:
        permit = issue(user, kb_id, action)
        if permit is not None:
            return permit
    return None


def issue(user, kb_id, action):
    row = kb.get(kb_id)
    if row is None or not can(user, kb_id, action):
        return None
    chroma = row["chroma"]
    signature = sign(kb_id, action, chroma)

    def check():
        current = kb.get(kb_id)
        if current is None or not Path_same(current["chroma"], chroma):
            return False
        return can(user, kb_id, action)

    return Permit(kb_id, action, chroma, row["inbox"], signature, check)


def Path_same(left, right):
    from pathlib import Path
    return Path(left).resolve() == Path(right).resolve()


def ask_kbs(user):
    return [row["id"] for row in kb.list_kbs() if can(user, row["id"], "ask")]


def visible_documents(user):
    import store
    rows = []
    for item in kb.list_kbs():
        if not can_see(user, item["id"]):
            continue
        if item["legacy"]:
            names = store.list_documents()
        else:
            permit = issue_see(user, item["id"])
            if permit is None:
                continue
            try:
                names = store.list_permit(permit)
            except PermissionError:
                continue
        for name in names:
            rows.append({"kb_id": item["id"], "kb_name": item["name"], "name": name})
    return rows


def backfill_legacy(user_id):
    """Один раз открыть «Документы» первому администратору личными действиями."""
    if auth.meta_get("legacy_rights"):
        return
    kb.ensure_legacy()
    auth.acl_add(kb.LEGACY_ID, "user", user_id, "allow")
    auth.set_user_content(user_id, kb.LEGACY_ID, list(CONTENT))
    auth.meta_set("legacy_rights", user_id)


def denied_by_role_or_group(user, kb_id):
    rows = auth.acl_rows(kb_id)
    subjects = set(_subjects(user))
    subjects.discard(("user", user["id"]))
    return any((row["subject_type"], row["subject_id"]) in subjects and row["effect"] == "deny" for row in rows)


def _rrf_merge(rankings, limit):
    import store
    from settings import runtime
    width = runtime().get("rrf", store._rrf())
    score = {}
    meta = {}
    for ranking in rankings:
        for place, chunk in enumerate(ranking, start=1):
            key = (
                chunk.get("kb_id") or "",
                chunk.get("document_name") or "",
                chunk.get("chunk_index") or 0,
                chunk.get("text") or "",
            )
            score[key] = score.get(key, 0) + 1 / (width + place)
            meta[key] = chunk
    ordered = sorted(score, key=lambda key: (-score[key], key[0], key[1], key[2]))
    return [meta[key] for key in ordered[:limit]]


def build_scope(user):
    """Поиск для координатора. Пустой список баз — модель не звать."""
    import store
    from settings import runtime

    kbs = ask_kbs(user)
    trace = []

    def names():
        rows = [row for row in visible_documents(user) if can(user, row["kb_id"], "ask")]
        counts = {}
        for row in rows:
            counts[row["name"]] = counts.get(row["name"], 0) + 1
        if len({row["kb_id"] for row in rows}) <= 1:
            return [row["name"] for row in rows]
        shown = []
        for row in rows:
            if counts[row["name"]] > 1:
                shown.append(f"{row['kb_name']} / {row['name']}")
            else:
                shown.append(row["name"])
        return shown

    def _tag(chunks, kb_id):
        row = kb.get(kb_id) or {}
        tagged = []
        for chunk in chunks:
            item = dict(chunk)
            item["kb_id"] = kb_id
            item["kb_name"] = row.get("name") or ""
            tagged.append(item)
        return tagged

    used = []
    skipped = []
    closed = []

    def _named(permit, names):
        try:
            listed = set(store.list_permit(permit))
        except PermissionError:
            return None
        return [name for name in names if name in listed]

    def _one(kb_id, clear, limit, places):
        permit = issue(user, kb_id, "ask")
        if permit is None or not permit.confirm():
            closed.append(kb_id)
            return []
        doc_names = None
        if places is not None:
            doc_names = [
                item.get("document_name") or ""
                for item in places
                if (item.get("kb_id") or "") in ("", kb_id) and item.get("document_name")
            ]
            if not doc_names:
                skipped.append(kb_id)
                return []
            # Имени в этой базе нет — весь её индекс не открывать: пустой фильтр
            # в поиске означает «искать везде».
            doc_names = _named(permit, doc_names)
            if doc_names is None:
                closed.append(kb_id)
                return []
            if not doc_names:
                skipped.append(kb_id)
                return []
        used.append(kb_id)
        try:
            found = store.search_permit(permit, clear, limit, doc_names)
        except PermissionError:
            used.pop()
            closed.append(kb_id)
            return []
        return _tag(found, kb_id)

    def search(clear, limit, places):
        used.clear()
        skipped.clear()
        closed.clear()
        if not kbs:
            return []
        if len(kbs) == 1:
            return _one(kbs[0], clear, limit, places)
        depth = runtime().get("candidates", 30)
        rankings = []
        for kb_id in kbs:
            found = _one(kb_id, clear, depth, places)
            if found:
                rankings.append(found)
        if not rankings:
            return []
        if len(rankings) == 1:
            return rankings[0][:limit]
        return _rrf_merge(rankings, limit)

    def word(term):
        for kb_id in list(used):
            permit = issue(user, kb_id, "ask")
            if permit is None:
                continue
            try:
                if store.known_permit(permit, term):
                    return True
            except PermissionError:
                continue
        return False

    def chunks(name, kb_id):
        if not kb_id:
            kb_id = kbs[0] if len(kbs) == 1 else ""
        if not kb_id:
            return []
        permit = issue(user, kb_id, "ask")
        if permit is None:
            return []
        try:
            rows = store.chunks_permit(permit, name)
        except PermissionError:
            return []
        row = kb.get(kb_id) or {}
        tagged = []
        for item in rows:
            copied = dict(item)
            copied["kb_id"] = kb_id
            copied["kb_name"] = row.get("name") or ""
            tagged.append(copied)
        return tagged

    scope = type("Scope", (), {})()
    scope.kbs = kbs
    scope.search = search
    scope.names = names
    scope.known = word
    scope.chunks = chunks
    scope.trace = trace
    scope.used = used
    scope.skipped = skipped
    scope.closed = closed
    scope.attempts = 0
    scope.feedback = ""
    return scope


def opened_now(scope):
    """Базы, которые этот вопрос реально открыл. Отсечённая сюда не входит."""
    used = list(getattr(scope, "used", None) or [])
    skipped = list(getattr(scope, "skipped", None) or [])
    closed = list(getattr(scope, "closed", None) or [])
    if used or skipped or closed:
        return used
    return list(getattr(scope, "kbs", None) or [])


def source_rows(result, found):
    """Текст куска в журнале тот же, что уже найден, а не пересказ."""
    sources = []
    for source in (result or {}).get("sources") or []:
        item = dict(source)
        if not item.get("text"):
            for chunk in found or []:
                same_name = chunk.get("document_name") == item.get("document_name")
                same_index = chunk.get("chunk_index") == item.get("chunk_index")
                same_base = not item.get("kb_id") or not chunk.get("kb_id") or chunk.get("kb_id") == item.get("kb_id")
                if same_name and same_index and same_base:
                    item["text"] = chunk.get("text") or ""
                    item.setdefault("kb_id", chunk.get("kb_id") or "")
                    item.setdefault("section", chunk.get("section") or "")
                    break
        sources.append(item)
    return sources


def query_record(user, scope, *, query, answer, status, dialog_id, sources, attempts=0, feedback="", error=""):
    """Одна запись вопроса: открытые базы, отказ и пустой текст модели при сбое."""
    payload = {
        "query": query,
        "answer": answer or "",
        "status": status or "",
        "dialog_id": dialog_id,
        "opened": opened_now(scope),
        "rejected": rejections(user, scope),
        "sources": sources or [],
        "trace": list(getattr(scope, "trace", None) or []),
        "attempts": attempts or 0,
        "feedback": feedback or "",
    }
    if error:
        payload["error"] = error
    return payload


def rejections(user, scope):
    """Базы, которые в этот вопрос не открывались, и одна причина на каждую."""
    skipped = set(getattr(scope, "skipped", None) or [])
    closed = set(getattr(scope, "closed", None) or [])
    used = set(getattr(scope, "used", None) or [])
    if not used and not skipped and not closed:
        used = set(getattr(scope, "kbs", None) or [])
    rows = []
    for row in kb.list_kbs():
        kb_id = row["id"]
        if kb_id in used and kb_id not in skipped and kb_id not in closed:
            continue
        if kb_id in closed:
            reason = "нет входа"
        elif kb_id in skipped:
            reason = "прошлый ход её не касается"
        elif not opened(user, kb_id):
            reason = "нет входа"
        elif not can(user, kb_id, "ask"):
            reason = "нет спрашивать"
        else:
            reason = "прошлый ход её не касается"
        rows.append({"kb_id": kb_id, "name": row["name"], "reason": reason})
    return rows


def self_grant(user, kb_id):
    if kb.get(kb_id) is None:
        raise LookupError("kb")
    if denied_by_role_or_group(user, kb_id):
        raise PermissionError("closed")
    already = opened(user, kb_id) and set(CONTENT) <= set(auth.user_content(user["id"], kb_id))
    if already:
        return False
    auth.acl_add(kb_id, "user", user["id"], "allow")
    auth.set_user_content(user["id"], kb_id, list(CONTENT))
    return True
