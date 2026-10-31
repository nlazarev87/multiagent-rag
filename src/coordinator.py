from pathlib import Path

import re

from langgraph.graph import END, StateGraph

from agents import CONFIRMED, MISSING, NO_ANSWER, UNCONFIRMED, _count_ask, _dependent, _from_overview, answer_agent, check_agent, clarify_agent, search_agent, select_agent
from dialog import add_turn, get_dialog
from settings import routing, runtime
from store import known, list_documents

ATTEMPTS = runtime().get("attempts", 2)


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
    return any(re.search(pattern, text) for pattern in (routing().get("catalog") or []))


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
                if any(word == piece or (len(word) >= 4 and piece.startswith(word)) for word in words[name])
            ]
            if hits and len(hits) < len(names):
                marks.append(set(hits))
    if not marks:
        return names
    chosen = set.intersection(*marks)
    return [name for name in names if name in chosen] or names


def _catalog_result(query, dialog_id):
    if not _catalog_query(query):
        return None
    names = _catalog_names(query, list_documents())
    answer = ", ".join(names) if names else NO_ANSWER
    add_turn(dialog_id, {"query": query, "answer": answer, "document_names": []})
    if not names:
        return {"answer": NO_ANSWER, "status": MISSING, "document_names": [], "sources": []}
    return {"answer": answer, "status": CONFIRMED, "document_names": [], "sources": []}


def run(query, dialog_id):
    listed = _catalog_result(query, dialog_id)
    if listed is not None:
        return listed

    def select(state):
        state["work"] = select_agent(state["query"], get_dialog(state["dialog_id"]))
        return state

    def clarify(state):
        state["clear"] = clarify_agent(state["query"], state["work"])
        return state

    def search(state):
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
        verdict = check_agent(state["answer"], state["chunks"], state["query"], known)
        state["status"] = verdict["status"]
        state["feedback"] = verdict["feedback"]
        state["sources"] = verdict["sources"]
        return state

    def route(state):
        if state["status"] != UNCONFIRMED or state["attempts"] >= _attempts():
            return "finish"
        feedback = state.get("feedback") or ""
        if "Разных значений" in feedback or "документ" in feedback.lower():
            return "search"
        return "answer"

    def finish(state):
        overview = None
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
        add_turn(state["dialog_id"], {"query": state["query"], "answer": state["answer"], "document_names": names})
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
