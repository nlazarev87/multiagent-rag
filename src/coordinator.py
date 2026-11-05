"""Один вопрос: каталог имён или граф select → clarify → search → answer → check.

Каталог смотрит на слова имени файла, не на подстроку. Неподтверждённый ответ
после повторов заменяется отказом, кроме числа из обзора таблицы.
"""

import concurrent.futures
import contextvars
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langgraph.graph import END, StateGraph

from agents import (
    CONFIRMED,
    CONFIRMED_OVERVIEW,
    MISSING,
    NO_ANSWER,
    UNCONFIRMED,
    answer_agent,
    check_agent,
    clarify_agent,
    search_agent,
    select_agent,
)
from dialog import add_turn, get_dialog
from llm import model_display_name
from pipeline_types import GraphState
from pipeline_utils import (
    _codes,
    _count_ask,
    _dependent,
    _extra_rows,
    _from_overview,
    _trace,
    _words,
)
from settings import routing, runtime
from store import known, list_documents, search_notes_begin, search_notes_end

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
        sources.append(
            {
                "number": number,
                "document_name": chunk.get("document_name", ""),
                "section": chunk.get("section", ""),
                "chunk_index": chunk.get("chunk_index", 0),
            }
        )
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
    before = text[: match.start()]
    if not re.search(r"\bкотор", before):
        return True
    return not any(not _catalog_noise(token) for token in re.findall(r"[0-9a-zа-яё]{3,}", before))


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
                name
                for name in names
                # Слово имени целиком или его начало. Кусок из середины слова не подходит.
                if any(
                    word == piece or (len(word) >= 4 and piece.startswith(word))
                    for word in words[name]
                )
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
    return (
        " ".join(
            [turn.get("query") or "", turn.get("answer") or "", " ".join(names), places, texts]
        )
        .lower()
        .replace("ё", "е")
    )


def _places(work, query, feedback=""):
    if "документ" in (feedback or "").lower():
        return None
    if not work or not _dependent(query):
        return None
    last = work[-1]
    if _refused(last.get("answer") or ""):
        return None
    leftover = [
        token for token in _place_tokens(query) if not _token_in(_previous_blob(last), token)
    ]
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
    """Вернуть ответ, статус, имена документов и источники для одного вопроса.

    Свой пул на этот вызов. Пул закрывается без ожидания потока, поэтому
    следующий вызов не стоит в очереди за зависшим проходом.
    """
    active = scope if scope is not None else _scope.get()
    if active is not None and not active.kbs:
        add_turn(dialog_id, {"query": query, "answer": NO_ANSWER, "document_names": []})
        return {"answer": NO_ANSWER, "status": MISSING, "document_names": [], "sources": []}
    row_token = _extra_rows.set(active.chunks) if active is not None else None
    trace_token = _trace.set(active.trace) if active is not None else None
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="graph-call")
    try:
        ctx = contextvars.copy_context()
        future = executor.submit(ctx.run, _run, query, dialog_id, active, features)
        return future.result()
    finally:
        executor.shutdown(wait=False)
        if row_token is not None:
            _extra_rows.reset(row_token)
        if trace_token is not None:
            _trace.reset(trace_token)


def _clock():
    return time.perf_counter(), datetime.now(timezone.utc).isoformat(timespec="milliseconds")


_TRACE_STRING_LIMIT = 4000
_TRACE_CHUNK_LIMIT = 600
_TRACE_CHUNK_COUNT = 8
_TRACE_BYTES_LIMIT = 64 * 1024


def _clip_strings(value, limit=_TRACE_STRING_LIMIT):
    """Обрезать строки в структуре до limit. Вернуть (структура, была ли обрезка)."""
    if isinstance(value, str):
        if len(value) > limit:
            return value[:limit], True
        return value, False
    if isinstance(value, dict):
        clipped_dict: dict[str, Any] = {}
        truncated = False
        for key, item in value.items():
            clipped, cut = _clip_strings(item, limit)
            clipped_dict[key] = clipped
            truncated = truncated or cut
        return clipped_dict, truncated
    if isinstance(value, list):
        clipped_list: list[Any] = []
        truncated = False
        for item in value:
            clipped, cut = _clip_strings(item, limit)
            clipped_list.append(clipped)
            truncated = truncated or cut
        return clipped_list, truncated
    return value, False


def _chunk_previews(chunks):
    """Превью фрагментов: максимум 8, текст не длиннее 600 символов."""
    previews: list[dict[str, Any]] = []
    truncated = len(chunks or []) > _TRACE_CHUNK_COUNT
    for chunk in (chunks or [])[:_TRACE_CHUNK_COUNT]:
        text = chunk.get("text") or ""
        if len(text) > _TRACE_CHUNK_LIMIT:
            text = text[:_TRACE_CHUNK_LIMIT]
            truncated = True
        previews.append(
            {
                "document_name": chunk.get("document_name") or "",
                "chunk_index": chunk.get("chunk_index", 0),
                "text": text,
            }
        )
    return previews, truncated


def _trace_size(steps):
    return len(json.dumps(steps, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def _fit_trace(steps):
    """Трасса не больше 64 КБ. Сначала пустеют превью фрагментов, потом строки."""
    if _trace_size(steps) <= _TRACE_BYTES_LIMIT:
        return steps
    for step in steps:
        output = step.get("output")
        if isinstance(output, dict):
            for preview in output.get("previews") or []:
                if isinstance(preview, dict):
                    preview["text"] = ""
    limit = _TRACE_STRING_LIMIT
    while _trace_size(steps) > _TRACE_BYTES_LIMIT and limit > 0:
        limit //= 2
        for step in steps:
            for key in ("input", "output"):
                value = step.get(key)
                if isinstance(value, dict):
                    clipped, _ = _clip_strings(value, limit)
                    step[key] = clipped
    for step in steps:
        output = step.get("output")
        if isinstance(output, dict):
            output["truncated"] = True
    return steps


def _run(query: str, dialog_id: str, scope, features: dict | None = None) -> GraphState:
    if features is None:
        features = runtime().get("features", {})
    trace_steps: list[dict[str, Any]] = []

    def _step(node, started, input=None, output=None, attempt=None, timed_out=False):
        mark, stamp = started
        input_value, input_cut = _clip_strings(input if input is not None else {})
        output_value, output_cut = _clip_strings(output if output is not None else {})
        if input_cut:
            input_value["truncated"] = True
        if output_cut or output_value.get("truncated"):
            output_value["truncated"] = True
        entry = {
            "node": node,
            "started_at": stamp,
            "duration_ms": round((time.perf_counter() - mark) * 1000, 2),
            "input": input_value,
            "output": output_value,
            "attempt": attempt if attempt is not None else 1,
            "timed_out": bool(timed_out),
        }
        trace_steps.append(entry)
        if scope is not None:
            scope.trace_steps = list(trace_steps)

    def _keep_steps():
        if scope is not None:
            scope.trace_steps = _fit_trace(list(trace_steps))

    catalog_started = _clock()
    listed = _catalog_result(query, dialog_id, scope)
    catalog_output: dict[str, Any] = {"is_catalog": listed is not None}
    if listed is not None:
        catalog_output["answer"] = listed.get("answer")
        catalog_output["status"] = listed.get("status")
        catalog_output["document_names"] = listed.get("document_names")
    _step("catalog", catalog_started, input={"query": query}, output=catalog_output, attempt=1)
    if listed is not None:
        _keep_steps()
        return listed

    def select(state: GraphState):
        started = _clock()
        dialog_turns = get_dialog(state["dialog_id"])
        state["work"] = select_agent(state["query"], dialog_turns)
        work = state.get("work") or []
        chosen = work[0].get("id") if work and isinstance(work[0], dict) else None
        _step(
            "select",
            started,
            input={"query": state.get("query"), "dialog_turns": len(dialog_turns)},
            output={"turns": work, "chosen_turn_id": chosen},
            attempt=1,
        )
        return state

    def clarify(state: GraphState):
        started = _clock()
        state["clear"] = clarify_agent(state["query"], state["work"])
        _step(
            "clarify",
            started,
            input={"query": state.get("query"), "work": state.get("work")},
            output={"search_string": state.get("clear")},
            attempt=1,
        )
        return state

    def search(state: GraphState):
        started = _clock()
        places = _places(state["work"], state["query"], state.get("feedback") or "")
        names = None
        if places:
            names = [
                item.get("document_name") for item in places if item.get("document_name")
            ] or None
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
                "search",
                started,
                input={
                    "query": state.get("clear") or state.get("query"),
                    "document_names": names,
                },
                output={
                    "service": "chroma+bm25",
                    "error": True,
                    "fallback_used": fallback_used,
                    "search_fallback_used": fallback_used,
                },
                attempt=state.get("attempts", 0) + 1,
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
        previews, previews_truncated = _chunk_previews(chunks)
        output: dict[str, Any] = {
            "service": "chroma+bm25",
            "chunks_returned": len(chunks),
            "previews": previews,
            "top_ids": [item.get("id") for item in chunks if item.get("id")],
            "top_docs": docs,
            "fallback_used": fallback_used,
            "search_fallback_used": fallback_used,
            "focused_query": focused_query,
            "allowed": allowed,
            "ranked_count": ranked_count,
            "bases_queried": bases,
        }
        if previews_truncated:
            output["truncated"] = True
        _step(
            "search",
            started,
            input={
                "query": state.get("clear") or state.get("query"),
                "document_names": names,
                "places": places,
            },
            output=output,
            attempt=state.get("attempts", 0) + 1,
        )
        return state

    def answer(state: GraphState):
        started = _clock()
        state["attempts"] = state.get("attempts", 0) + 1
        usage: dict[str, Any] = {}
        trace_mark = len(getattr(scope, "trace", None) or []) if scope is not None else 0
        state["answer"] = answer_agent(
            state["query"],
            state["clear"],
            state["chunks"],
            state["work"],
            state.get("feedback"),
            state.get("features"),
            usage,
        )
        prompt = None
        if scope is not None:
            prompts = list(getattr(scope, "trace", None) or [])[trace_mark:]
            if prompts:
                prompt = prompts[-1]
        output: dict[str, Any] = {
            "answer": state.get("answer"),
            "model": model_display_name(),
            "service": "llama.cpp",
            "answer_len": len(state.get("answer") or ""),
        }
        if prompt is not None:
            output["prompt"] = prompt
        if usage.get("tokens_in") is not None or usage.get("tokens_out") is not None:
            output["tokens_in"] = usage.get("tokens_in")
            output["tokens_out"] = usage.get("tokens_out")
        _step(
            "answer",
            started,
            input={
                "query": state.get("query"),
                "clear_query": state.get("clear"),
                "feedback": state.get("feedback"),
            },
            output=output,
            attempt=state.get("attempts", 0),
        )
        return state

    def check(state: GraphState):
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
            "check",
            started,
            input={"answer": state.get("answer"), "query": state.get("query")},
            output={
                "status": state.get("status"),
                "feedback": state.get("feedback") or "",
                "sources": state.get("sources"),
            },
            attempt=state.get("attempts", 0),
        )
        return state

    def route(state: GraphState):
        started = _clock()
        # «документ» и обзор таблицы просят другой поиск. Остальной отзыв переписывает ответ.
        if state["status"] != UNCONFIRMED or state["attempts"] >= _attempts():
            decision = "finish"
        else:
            feedback = state.get("feedback") or ""
            if "Разных значений" in feedback or "документ" in feedback.lower():
                decision = "search"
            else:
                decision = "answer"
        _step(
            "route",
            started,
            input={
                "status": state.get("status"),
                "attempts": state.get("attempts", 0),
                "feedback": state.get("feedback") or "",
            },
            output={"next": decision},
            attempt=state.get("attempts", 0) or 1,
        )
        return decision

    def finish(state: GraphState):
        started = _clock()
        incoming_answer = state.get("answer")
        incoming_status = state.get("status")
        overview = None
        # Вопрос «сколько» не заменяется отказом, если в найденном тексте уже есть полная строка обзора.
        show_overview = (state.get("features") or {}).get("from_overview", True)
        if (
            show_overview
            and state["status"] in (MISSING, UNCONFIRMED)
            and _count_ask(state.get("query", ""))
        ):
            overview = _from_overview(state.get("query", ""), state.get("chunks") or [])
        heuristic_finish_answer = False
        if overview:
            state["answer"] = overview
            state["sources"] = _overview_sources(overview, state.get("chunks") or [])
            state["status"] = CONFIRMED_OVERVIEW
            state["feedback"] = "ответ построен по строке обзора, не моделью"
            heuristic_finish_answer = True
        elif (
            state["status"] == UNCONFIRMED
            and state.get("attempts", 0) >= 2
            and state.get("answer")
            and state.get("chunks")
        ):
            # Текст модели остаётся как есть: _cited сотрёт номер при пустых источниках.
            heuristic_finish_answer = True
        elif state["status"] in (MISSING, UNCONFIRMED):
            state["answer"] = NO_ANSWER
            state["sources"] = []
            state["status"] = MISSING
        else:
            state["answer"] = _cited(state["answer"], state["sources"])
        if scope is not None:
            scope.feedback = state.get("feedback") or ""
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
            "finish",
            started,
            input={"answer": incoming_answer, "status": incoming_status},
            output={
                "status": state.get("status"),
                "answer": state.get("answer"),
                "document_names": list(state.get("document_names") or []),
                "feedback": state.get("feedback") or "",
                "heuristic_finish_answer": heuristic_finish_answer,
            },
            attempt=state.get("attempts", 0) or 1,
        )
        return state

    graph = StateGraph(GraphState)
    for name, node in (
        ("select", select),
        ("clarify", clarify),
        ("search", search),
        ("answer", answer),
        ("check", check),
        ("finish", finish),
    ):
        graph.add_node(name, node)
    graph.set_entry_point("select")
    graph.add_edge("select", "clarify")
    graph.add_edge("clarify", "search")
    graph.add_edge("search", "answer")
    graph.add_edge("answer", "check")
    graph.add_conditional_edges(
        "check", route, {"answer": "answer", "search": "search", "finish": "finish"}
    )
    graph.add_edge("finish", END)
    try:
        out = graph.compile().invoke(
            {
                "query": query,
                "dialog_id": dialog_id,
                "features": features,
                "trace_steps": trace_steps,
            }
        )
        return {
            "answer": out["answer"],
            "status": out["status"],
            "document_names": out["document_names"],
            "sources": out["sources"],
        }
    finally:
        _keep_steps()
