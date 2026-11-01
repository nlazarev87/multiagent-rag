"""Один вопрос: каталог имён или граф select → clarify → search → answer → check.

Каталог смотрит на слова имени файла, не на подстроку. Неподтверждённый ответ
после повторов заменяется отказом, кроме числа из обзора таблицы.
"""
from pathlib import Path

import contextvars
import re

from langgraph.graph import END, StateGraph

from agents import CONFIRMED, MISSING, NO_ANSWER, UNCONFIRMED, _count_ask, _dependent, _extra_rows, _from_overview, _trace, answer_agent, check_agent, clarify_agent, search_agent, select_agent
from dialog import add_turn, get_dialog
from settings import routing, runtime
from store import known, list_documents

ATTEMPTS = runtime().get("attempts", 2)
_scope = contextvars.ContextVar("rag_scope", default=None)


def _attempts():
    return runtime().get("attempts", ATTEMPTS)


def _cited(answer, sources):
    allowed = {source.get("number") for source in sources or []}

    def keep(match):
        numbers = [int(number) for number in re.findall(r"\d+", match.group(0))]
        kept = [number for number in numbers if number in allowed]
        if not kept:
            return ""
        return "".join(f" [{number}]" for number in kept)

    text = re.sub(r"\s*\[[\d\s,]+\]", keep, answer or "")
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _overview_sources(answer, chunks):
    sources = []
    for number in [int(item) for item in re.findall(r"\[(\d+)\]", answer or "")]:
        if not 1 <= number <= len(chunks or []):
            continue
        chunk = chunks[number - 1]
        sources.append({
            "number": number,
            "document_name": chunk.get("document_name", ""),
            "section": chunk.get("section", ""),
            "chunk_index": chunk.get("chunk_index", 0),
        })
    return sources


def _catalog_query(query):
    text = " ".join((query or "").lower().replace("ё", "е").split())
    for pattern in routing().get("catalog") or []:
        match = re.search(pattern, text)
        if match and _inventory_verb(match, text):
            return True
    return False


def _inventory_verb(match, text):
    # The inventory verb is the finite form: загружен, загружена, загружено,
    # загружены. A declined participle such as "загруженном" does not match.
    # "который загружен" is a relative clause. It is still the inventory
    # question when every word before it is boilerplate ("какие документы,
    # которые загружены"), and a content question when any other word remains
    # ("какое давление у документа, который загружен").
    if not match.group(0).startswith("загружен"):
        return True
    before = text[:match.start()]
    if not re.search(r"\bкотор", before):
        return True
    return not any(
        not _catalog_noise(token)
        for token in re.findall(r"[0-9a-zа-яё]{3,}", before)
    )


def _name_words(name):
    stem = Path(name).stem.lower().replace("ё", "е")
    return set(re.findall(r"[0-9a-zа-яё]+", stem))


def _catalog_noise(token):
    # The inventory question itself says "документы" and "систему". Those words
    # are not a file name: a file called Документ.docx must stay in the full list.
    for raw in routing().get("catalog_skip") or []:
        skip = str(raw).lower().replace("ё", "е")
        if len(skip) < 4:
            if token == skip:
                return True
            continue
        if token == skip or token.startswith(skip):
            return True
    return False


def _catalog_names(query, names):
    """Оставить имена, чьи слова совпали с вопросом. Подстрока внутри слова не считается."""
    words = {name: _name_words(name) for name in names}
    marks = []
    for token in re.findall(r"[0-9a-zа-яё]{3,}", (query or "").lower().replace("ё", "е")):
        if _catalog_noise(token):
            continue
        pieces = {token}
        if len(token) >= 5:
            pieces.add(token[:4])
        for piece in pieces:
            if len(piece) < 4 and not piece.isascii():
                continue
            hits = [
                name for name in names
                # Слово имени целиком или его начало. Кусок из середины слова не подходит.
                if any(word == piece or (len(word) >= 4 and piece.startswith(word)) for word in words[name])
            ]
            if hits and len(hits) < len(names):
                marks.append(set(hits))
    if not marks:
        return names
    chosen = set.intersection(*marks)
    return [name for name in names if name in chosen] or names


def _catalog_result(query, dialog_id, scope=None):
    if not _catalog_query(query):
        return None
    raw = scope.names() if scope is not None else list_documents()
    names = _catalog_names(query, raw)
    answer = ", ".join(names) if names else NO_ANSWER
    add_turn(dialog_id, {"query": query, "answer": answer, "document_names": []})
    if not names:
        return {"answer": NO_ANSWER, "status": MISSING, "document_names": [], "sources": []}
    return {"answer": answer, "status": CONFIRMED, "document_names": [], "sources": []}


def _places(work, query):
    if not work or not _dependent(query):
        return None
    places = work[-1].get("places") or None
    if places:
        return places
    names = work[-1].get("document_names") or None
    if not names:
        return None
    return [{"kb_id": "", "document_name": name} for name in names]


def _stamp_sources(state):
    chunks = state.get("chunks") or []
    for source in state.get("sources") or []:
        if source.get("kb_id"):
            continue
        for chunk in chunks:
            if chunk.get("document_name") == source.get("document_name") and chunk.get("kb_id"):
                source["kb_id"] = chunk.get("kb_id")
                source["kb_name"] = chunk.get("kb_name") or ""
                break


def run(query, dialog_id, scope=None):
    """Вернуть ответ, статус, имена документов и источники для одного вопроса."""
    active = scope if scope is not None else _scope.get()
    if active is not None and not active.kbs:
        add_turn(dialog_id, {"query": query, "answer": NO_ANSWER, "document_names": []})
        return {"answer": NO_ANSWER, "status": MISSING, "document_names": [], "sources": []}
    row_token = _extra_rows.set(active.chunks) if active is not None else None
    trace_token = _trace.set(active.trace) if active is not None else None
    try:
        return _run(query, dialog_id, active)
    finally:
        if row_token is not None:
            _extra_rows.reset(row_token)
        if trace_token is not None:
            _trace.reset(trace_token)


def _run(query, dialog_id, scope):
    listed = _catalog_result(query, dialog_id, scope)
    if listed is not None:
        return listed

    def select(state):
        state["work"] = select_agent(state["query"], get_dialog(state["dialog_id"]))
        return state

    def clarify(state):
        state["clear"] = clarify_agent(state["query"], state["work"])
        return state

    def search(state):
        if scope is not None:
            limit = runtime().get("search_limit", 4)
            state["chunks"] = scope.search(state["clear"], limit, _places(state["work"], state["query"]))
            return state
        names = None
        if state["work"] and _dependent(state["query"]):
            names = state["work"][-1].get("document_names") or None
        state["chunks"] = search_agent(state["clear"], names)
        return state

    def answer(state):
        state["attempts"] = state.get("attempts", 0) + 1
        state["answer"] = answer_agent(state["query"], state["clear"], state["chunks"], state["work"], state.get("feedback"))
        return state

    def check(state):
        checker = scope.known if scope is not None else known
        verdict = check_agent(state["answer"], state["chunks"], state["query"], checker)
        state["status"] = verdict["status"]
        state["feedback"] = verdict["feedback"]
        state["sources"] = verdict["sources"]
        return state

    def route(state):
        # «документ» и обзор таблицы просят другой поиск. Остальной отзыв переписывает ответ.
        if state["status"] != UNCONFIRMED or state["attempts"] >= _attempts():
            return "finish"
        feedback = state.get("feedback") or ""
        if "Разных значений" in feedback or "документ" in feedback.lower():
            return "search"
        return "answer"

    def finish(state):
        overview = None
        # Вопрос «сколько» не заменяется отказом, если в найденном тексте уже есть полная строка обзора.
        if state["status"] in (MISSING, UNCONFIRMED) and _count_ask(state.get("query", "")):
            overview = _from_overview(state.get("query", ""), state.get("chunks") or [])
        if state["status"] in (MISSING, UNCONFIRMED) and not overview:
            state["answer"] = NO_ANSWER
            state["sources"] = []
            state["status"] = MISSING
        elif overview:
            state["answer"] = overview
            state["sources"] = _overview_sources(overview, state.get("chunks") or [])
            state["status"] = CONFIRMED
        else:
            state["answer"] = _cited(state["answer"], state["sources"])
        names = []
        for source in state["sources"]:
            if source["document_name"] not in names:
                names.append(source["document_name"])
        state["document_names"] = names
        _stamp_sources(state)
        places = []
        seen = set()
        for source in state["sources"]:
            kb_id = source.get("kb_id") or ""
            name = source.get("document_name") or ""
            if kb_id and name and (kb_id, name) not in seen:
                places.append({"kb_id": kb_id, "document_name": name})
                seen.add((kb_id, name))
        turn = {"query": state["query"], "answer": state["answer"], "document_names": names}
        if places:
            turn["places"] = places
        add_turn(state["dialog_id"], turn)
        return state

    graph = StateGraph(dict)
    for name, node in (("select", select), ("clarify", clarify), ("search", search), ("answer", answer), ("check", check), ("finish", finish)):
        graph.add_node(name, node)
    graph.set_entry_point("select")
    graph.add_edge("select", "clarify")
    graph.add_edge("clarify", "search")
    graph.add_edge("search", "answer")
    graph.add_edge("answer", "check")
    graph.add_conditional_edges("check", route, {"answer": "answer", "search": "search", "finish": "finish"})
    graph.add_edge("finish", END)
    out = graph.compile().invoke({"query": query, "dialog_id": dialog_id})
    return {
        "answer": out["answer"],
        "status": out["status"],
        "document_names": out["document_names"],
        "sources": out["sources"],
    }
