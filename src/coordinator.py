"""Один вопрос: каталог имён или граф select → clarify → search → answer → check.

Каталог смотрит на слова имени файла, не на подстроку. Неподтверждённый ответ
после повторов заменяется отказом, кроме числа из обзора таблицы.
"""
from pathlib import Path
from datetime import datetime, timezone

import concurrent.futures
import contextvars
import re
import time

from langgraph.graph import END, StateGraph

from agents import CONFIRMED, MISSING, NO_ANSWER, UNCONFIRMED, _codes, _count_ask, _dependent, _extra_rows, _from_overview, _trace, _words, answer_agent, check_agent, clarify_agent, search_agent, select_agent
from dialog import add_turn, get_dialog
from llm import model_name
from settings import routing, runtime
from store import known, list_documents, search_notes_begin, search_notes_end

ATTEMPTS = runtime().get("attempts", 2)
_scope = contextvars.ContextVar("rag_scope", default=None)
_graph_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="graph-timeout")


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


def _refused(answer):
    mark = " ".join((NO_ANSWER or "").lower().replace("ё", "е").split()).rstrip(".")
    return mark in " ".join((answer or "").lower().replace("ё", "е").split())


def _place_tokens(text):
    tokens = []
    for word in _words(text or ""):
        if word not in tokens:
            tokens.append(word)
    for code in _codes(text or ""):
        if code not in tokens:
            tokens.append(code)
    return tokens


def _token_in(blob, token):
    key = (token or "").lower().replace("ё", "е")
    if not key:
        return False
    if key in blob:
        return True
    parts = re.findall(r"[0-9a-zа-яё]{3,}", blob)
    if len(key) >= 5:
        stem = key[:5]
        return any(part.startswith(stem) for part in parts)
    return any(part == key or part.startswith(key) for part in parts)


def _previous_blob(turn):
    names = list(turn.get("document_names") or [])
    places = " ".join(item.get("document_name") or "" for item in turn.get("places") or [])
    texts = " ".join(
        " ".join([source.get("text") or "", source.get("document_name") or ""])
        for source in turn.get("sources") or []
    )
    return " ".join([turn.get("query") or "", turn.get("answer") or "", " ".join(names), places, texts]).lower().replace("ё", "е")


def _places(work, query, feedback=""):
    if "документ" in (feedback or "").lower():
        return None
    if not work or not _dependent(query):
        return None
    last = work[-1]
    if _refused(last.get("answer") or ""):
        return None
    leftover = [token for token in _place_tokens(query) if not _token_in(_previous_blob(last), token)]
    if leftover and (_codes(query) or len(leftover) > 1):
        return None
    places = last.get("places") or None
    if places:
        return places
    names = last.get("document_names") or None
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


def run(query, dialog_id, scope=None, features=None):
    """Вернуть ответ, статус, имена документов и источники для одного вопроса."""
    active = scope if scope is not None else _scope.get()
    if active is not None and not active.kbs:
        add_turn(dialog_id, {"query": query, "answer": NO_ANSWER, "document_names": []})
        return {"answer": NO_ANSWER, "status": MISSING, "document_names": [], "sources": []}
    row_token = _extra_rows.set(active.chunks) if active is not None else None
    trace_token = _trace.set(active.trace) if active is not None else None
    try:
        timeout_s = (runtime().get("timeouts") or {}).get("graph_ms", 120000) / 1000
        ctx = contextvars.copy_context()
        future = _graph_executor.submit(ctx.run, _run, query, dialog_id, active, features)
        try:
            return future.result(timeout=timeout_s)
        except TimeoutError:
            if future.done():
                raise
            raise TimeoutError(f"graph timeout after {timeout_s}s")
    finally:
        if row_token is not None:
            _extra_rows.reset(row_token)
        if trace_token is not None:
            _trace.reset(trace_token)


def _clock():
    return time.perf_counter(), datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _run(query, dialog_id, scope, features=None):
    if features is None:
        features = runtime().get("features", {})
    trace_steps = []

    def _step(node, started, input_summary=None, output_summary=None, extra=None, timed_out=False):
        mark, stamp = started
        entry = {
            "node": node,
            "started_at": stamp,
            "duration_ms": round((time.perf_counter() - mark) * 1000, 2),
            "input_summary": input_summary,
            "output_summary": output_summary,
        }
        if timed_out:
            entry["timed_out"] = True
        if extra:
            entry.update(extra)
        trace_steps.append(entry)

    def _keep_steps():
        if scope is not None:
            scope.trace_steps = list(trace_steps)

    listed = _catalog_result(query, dialog_id, scope)
    if listed is not None:
        _keep_steps()
        return listed

    def select(state):
        started = _clock()
        state["work"] = select_agent(state["query"], get_dialog(state["dialog_id"]))
        work = state.get("work") or []
        chosen = work[0].get("id") if work and isinstance(work[0], dict) else None
        _step(
            "select", started,
            input_summary={"query_len": len(state.get("query") or "")},
            output_summary={"work_len": len(work), "chosen_turn_id": chosen},
        )
        return state

    def clarify(state):
        started = _clock()
        state["clear"] = clarify_agent(state["query"], state["work"])
        _step(
            "clarify", started,
            input_summary={"query_len": len(state.get("query") or "")},
            output_summary={"search_string": state.get("clear")},
        )
        return state

    def search(state):
        started = _clock()
        places = _places(state["work"], state["query"], state.get("feedback") or "")
        names = None
        if places:
            names = [item.get("document_name") for item in places if item.get("document_name")] or None
        # Заметки пишет сам поиск. Второй вызов с debug=True здесь не нужен:
        # при допуске он открыл бы другой индекс. Если имена прошлого хода
        # ничего не дали, один повтор без имён идёт тем же вызовом, что и первый.
        token = search_notes_begin()
        fallback_used = False
        try:
            if scope is not None:
                limit = runtime().get("search_limit", 4)
                state["chunks"] = scope.search(state["clear"], limit, places)
                if not state["chunks"] and names:
                    fallback_used = True
                    state["chunks"] = scope.search(state["clear"], limit, None)
                scope.found = list(state["chunks"] or [])
            else:
                state["chunks"] = search_agent(state["clear"], names)
                if not state["chunks"] and names:
                    fallback_used = True
                    state["chunks"] = search_agent(state["clear"], None)
            notes = search_notes_end(token)
            token = None
        except Exception:
            if token is not None:
                search_notes_end(token)
            _step(
                "search", started,
                output_summary={"error": True, "fallback_used": fallback_used},
                extra={"search_fallback_used": fallback_used},
            )
            raise
        state["search_fallback_used"] = fallback_used
        chunks = [item for item in (state.get("chunks") or []) if isinstance(item, dict)]
        docs = []
        for item in chunks:
            name = item.get("document_name")
            if name and name not in docs:
                docs.append(name)
        if len(notes) == 1:
            focused_query = notes[0].get("focused_query")
            allowed = notes[0].get("allowed")
            ranked_count = notes[0].get("ranked_count")
        elif notes:
            focused_query = [item.get("focused_query") for item in notes]
            allowed = [item.get("allowed") for item in notes]
            ranked_count = sum(item.get("ranked_count") or 0 for item in notes)
        else:
            focused_query = None
            allowed = None
            ranked_count = None
        bases = list(getattr(scope, "used", None) or []) if scope is not None else None
        _step(
            "search", started,
            input_summary={"query": state.get("clear") or state.get("query"), "document_names": names},
            output_summary={
                "chunks_returned": len(chunks),
                "top_ids": [item.get("id") for item in chunks if item.get("id")],
                "top_docs": docs,
                "fallback_used": fallback_used,
            },
            extra={
                "clear_query": state.get("clear"),
                "focused_query": focused_query,
                "allowed": allowed,
                "ranked_count": ranked_count,
                "bases_queried": bases,
                "search_fallback_used": fallback_used,
            },
        )
        return state

    def answer(state):
        started = _clock()
        state["attempts"] = state.get("attempts", 0) + 1
        usage = {}
        state["answer"] = answer_agent(
            state["query"], state["clear"], state["chunks"], state["work"],
            state.get("feedback"), state.get("features"), usage,
        )
        extra = {}
        if usage.get("tokens_in") is not None or usage.get("tokens_out") is not None:
            extra["tokens_in"] = usage.get("tokens_in")
            extra["tokens_out"] = usage.get("tokens_out")
        _step(
            "answer", started,
            output_summary={"model": model_name(), "answer_len": len(state.get("answer") or "")},
            extra=extra or None,
        )
        return state

    def check(state):
        started = _clock()
        checker = scope.known if scope is not None else known
        verdict = check_agent(state["answer"], state["chunks"], state["query"], checker)
        state["status"] = verdict["status"]
        state["feedback"] = verdict["feedback"]
        state["sources"] = verdict["sources"]
        if scope is not None:
            scope.attempts = state.get("attempts") or 0
            scope.feedback = state.get("feedback") or ""
        _step(
            "check", started,
            output_summary={"status": state.get("status"), "feedback": state.get("feedback") or ""},
        )
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
        started = _clock()
        overview = None
        # Вопрос «сколько» не заменяется отказом, если в найденном тексте уже есть полная строка обзора.
        show_overview = (state.get("features") or {}).get("from_overview", True)
        if show_overview and state["status"] in (MISSING, UNCONFIRMED) and _count_ask(state.get("query", "")):
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
        turn = {
            "query": state["query"],
            "answer": state["answer"],
            "document_names": names,
            "sources": state["sources"],
        }
        if places:
            turn["places"] = places
        add_turn(state["dialog_id"], turn)
        _step(
            "finish", started,
            output_summary={"status": state.get("status"), "document_names": list(state.get("document_names") or [])},
        )
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
    out = graph.compile().invoke({
        "query": query,
        "dialog_id": dialog_id,
        "features": features,
        "trace_steps": trace_steps,
    })
    _keep_steps()
    return {
        "answer": out["answer"],
        "status": out["status"],
        "document_names": out["document_names"],
        "sources": out["sources"],
    }
