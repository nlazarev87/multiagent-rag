import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVAL = Path(__file__).resolve().parent
SRC = ROOT / "src"
FLOORS = EVAL / "floors.json"
LAST = EVAL / "last.json"
FROZEN = EVAL / "frozen_chunks.json"
DOCS = ROOT / "tests" / "docs"
INBOX = ROOT / "data" / "inbox"
QUESTIONS_PATH = EVAL / "questions.json"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault(
    "LLM_MODEL_PATH",
    str(ROOT / "data" / "models" / "qwen2.5-1.5b-instruct-q4_k_m.gguf"),
)

HIGHER = {
    "select_exact", "select_precision", "select_recall",
    "clarify_passthrough", "clarify_rewrite", "clarify_anchor", "clarify_search_hit4",
    "search_hit4_dev", "search_hit4_holdout", "search_hit1_dev", "search_mrr_dev",
    "search_doc_p4_dev", "search_together_dev", "search_overview_dev",
    "answer_facts_dev", "answer_starts_dev", "answer_forbidden_dev", "answer_cite_dev",
    "answer_noanswer_dev",
    "check_status_exact", "check_source_doc", "check_feedback_type",
    "coord_order", "coord_retry_cap", "coord_empty_skip", "coord_retry_help", "coord_status_exact",
    "e2e_dev", "e2e_holdout", "e2e_dialog",
}
LOWER = {
    "select_false_attach", "select_false_drop",
    "clarify_overrewrite",
    "check_false_confirm", "check_false_reject", "check_false_missing",
    "coord_discard_good",
}
TIME_KEYS = {"search_latency_ms", "answer_latency_s", "e2e_latency_s"}
FAST_NODES = ("select", "clarify", "search", "check", "coord")
SLOW_NODES = ("answer", "e2e")
OVERVIEW_MARKERS = ("сколько", "какие", "перечисли")
NO_ANSWER = "В документах нет ответа."
EDGE = "0-9a-zа-я_"
DIALOG_STEPS = [
    ("Какой номер у цеха?", "4", None, None, "charter.txt"),
    ("Как зовут мастера?", "Иванов", None, None, "charter.txt"),
    ("Сколько она длится?", "8", None, None, "charter.txt"),
    ("Какое давление у насоса?", "6 бар", "Иванов", None, "pump.md"),
    ("В каком году его выпустили?", "2019", "18", None, "pump.md"),
    ("Какая температура на складе?", "18", "6 бар", None, "charter.txt"),
    ("Какой цвет у насоса?", None, "синий", {"подтверждён", "нет ответа"}, None),
    ("Какой номер у цеха?", "4", None, None, "charter.txt"),
]


def _dump(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _questions():
    return _load(QUESTIONS_PATH)


def _flat(text):
    return " ".join((text or "").lower().replace("ё", "е").split())


def _has(needle, text):
    flat = _flat(needle)
    if not flat:
        return False
    import re
    tail = f"(?![{EDGE}])" if flat[-1].isdigit() else ""
    return re.search(f"(?<![{EDGE}]){re.escape(flat)}{tail}", _flat(text)) is not None


def _item_type(item):
    if item.get("status") == "нет ответа":
        return "noanswer"
    if item.get("starts"):
        return "yesno"
    query = item["query"].lower()
    if "сколько" in query:
        return "count"
    if "перечисли" in query or query.startswith("какие") or " какие " in query:
        return "list"
    return "fact"


def _is_overview_query(query):
    text = query.lower()
    return any(marker in text for marker in OVERVIEW_MARKERS)


def _direction(key):
    if key in TIME_KEYS or key in LOWER:
        return "lower"
    return "higher"


def card(key, now, n, best=None, hits=None, extra=None):
    direction = _direction(key)
    if best is None:
        if key in TIME_KEYS:
            best = now
        else:
            best = 0.0 if direction == "lower" else 1.0
    if n == 0:
        room = None
    elif key in TIME_KEYS:
        room = max(0.0, now - best)
    elif direction == "lower":
        room = max(0.0, now - best)
    else:
        room = max(0.0, best - now)
    out = {
        "now": now,
        "best": best,
        "room": room,
        "floor": now,
        "n": n,
        "direction": direction,
    }
    if hits is not None:
        out["hits"] = hits
    if extra:
        out.update(extra)
    return {key: out}


def _rate(hits, n):
    return 1.0 if n == 0 else hits / n


def _mean(values):
    return 0.0 if not values else sum(values) / len(values)


def _selected_indices(selected, turns):
    found, used = [], set()
    for item in selected:
        for index, turn in enumerate(turns):
            if index in used:
                continue
            if turn == item:
                found.append(index)
                used.add(index)
                break
    return found


def measure_select():
    from agents import select_agent

    cases = _load(EVAL / "cases_select.json")
    exact = precision = recall = 0.0
    attach = attach_n = drop = drop_n = 0
    for case in cases:
        turns = case["turns"]
        gold = case["gold"]
        got = _selected_indices(select_agent(case["query"], turns), turns)
        gold_set, got_set = set(gold), set(got)
        exact += int(got == gold)
        if got:
            precision += len(gold_set & got_set) / len(got)
        else:
            precision += 1.0 if not gold else 0.0
        if gold:
            recall += len(gold_set & got_set) / len(gold)
            drop_n += 1
            drop += int(not got)
        else:
            recall += 1.0
            attach_n += 1
            attach += int(bool(got))
    n = len(cases)
    cards = {}
    cards.update(card("select_exact", _rate(exact, n), n, hits=int(exact)))
    cards.update(card("select_precision", precision / n, n))
    cards.update(card("select_recall", recall / n, n))
    cards.update(card("select_false_attach", _rate(attach, attach_n), attach_n, hits=attach))
    cards.update(card("select_false_drop", _rate(drop, drop_n), drop_n, hits=drop))
    return cards


def _feedback_type(verdict):
    text = verdict.get("feedback") or ""
    if "переписывал" in text:
        return "copied"
    if "нет во фрагментах" in text:
        return "missing"
    if "не содержал фактов" in text:
        return "retry"
    if "инверс" in text or "Да или Нет" in text or "начни с" in text.lower():
        return "inversion"
    if "Список" in text or "перечисл" in text or "Разных значений" in text:
        return "incomplete"
    if "Ссылайся только" in text:
        return "cite"
    return text[:40] if text else ""


def _check_known(case):
    missing_terms = {_flat(term) for term in case.get("known_missing", [])}
    if not missing_terms:
        return None
    return lambda term, banned=missing_terms: _flat(term) not in banned


def measure_check():
    from agents import CONFIRMED, MISSING, check_agent

    cases = _load(EVAL / "cases_check.json")
    status_hits = confirm_err = reject_err = missing_err = 0
    confirm_n = reject_n = missing_n = 0
    source_hits = source_n = 0
    feedback_hits = feedback_n = 0
    for case in cases:
        verdict = check_agent(case["answer"], case["chunks"], case["query"], _check_known(case))
        gold = case["gold_status"]
        status_hits += int(verdict["status"] == gold)
        if gold == CONFIRMED:
            reject_n += 1
            reject_err += int(verdict["status"] != CONFIRMED)
            source_n += 1
            names = [source["document_name"] for source in verdict.get("sources") or []]
            source_hits += int(verdict["status"] == CONFIRMED and case.get("gold_document") in names)
        else:
            confirm_n += 1
            confirm_err += int(verdict["status"] == CONFIRMED)
            feedback_n += 1
            feedback_hits += int(_feedback_type(verdict) == case.get("feedback_type", ""))
        if gold != MISSING:
            missing_n += 1
            missing_err += int(verdict["status"] == MISSING)
    n = len(cases)
    cards = {}
    cards.update(card("check_status_exact", _rate(status_hits, n), n, hits=status_hits))
    cards.update(card("check_false_confirm", _rate(confirm_err, confirm_n), confirm_n, hits=confirm_err))
    cards.update(card("check_false_reject", _rate(reject_err, reject_n), reject_n, hits=reject_err))
    cards.update(card("check_false_missing", _rate(missing_err, missing_n), missing_n, hits=missing_err))
    cards.update(card("check_source_doc", _rate(source_hits, source_n), source_n, hits=source_hits))
    cards.update(card("check_feedback_type", _rate(feedback_hits, feedback_n), feedback_n, hits=feedback_hits))
    return cards


def _inbox_ready():
    return any(INBOX.glob("*.docx"))


def _with_chroma(folder, ingest_path):
    import store
    from ingest import ingest_dir

    saved = store.CHROMA
    store.CHROMA = Path(folder)
    store.reset()
    store.upsert_chunks(ingest_dir(ingest_path))
    return saved


def _restore_chroma(saved):
    import store

    store.CHROMA = saved
    store.reset()


def _retrieval_ok(item, chunks):
    texts = [_flat(chunk["text"]) for chunk in chunks]
    ok = all(any(_flat(phrase) in text for text in texts) for phrase in item.get("evidence", []))
    if item.get("evidence_any"):
        ok = ok and any(_flat(phrase) in text for phrase in item["evidence_any"] for text in texts)
    if item.get("together"):
        ok = ok and any(all(_flat(phrase) in text for phrase in item["together"]) for text in texts)
    return ok and any(item.get(key) for key in ("evidence", "evidence_any", "together"))


def _first_needed_rank(item, chunks):
    if not chunks:
        return None
    if not _retrieval_ok(item, chunks):
        return None
    for rank in range(1, len(chunks) + 1):
        if _retrieval_ok(item, chunks[:rank]):
            return rank
    return None


def measure_search(holdout=True, existing=None):
    import store

    if not _inbox_ready():
        return {}
    import tempfile

    tmp = existing or tempfile.mkdtemp(prefix="score-search-")
    saved = _with_chroma(tmp, INBOX) if existing is None else None
    try:
        items = _questions()
        cards = {}
        for split, suffix in (("dev", "dev"), ("holdout", "holdout")):
            if split == "holdout" and not holdout:
                continue
            rows = [item for item in items if item["split"] == split and any(item.get(key) for key in ("evidence", "evidence_any", "together"))]
            hit4 = hit1 = mrr = 0.0
            doc_scores = []
            together_hits = together_n = 0
            overview_hits = overview_n = 0
            times = []
            for item in rows:
                start = time.perf_counter()
                chunks = store.search_chunks(item["query"], 4)
                times.append((time.perf_counter() - start) * 1000)
                rank = _first_needed_rank(item, chunks)
                if rank is not None and rank <= 4:
                    hit4 += 1
                    mrr += 1.0 / rank
                    if rank == 1:
                        hit1 += 1
                if item.get("document") not in (None, "*"):
                    if chunks:
                        doc_scores.append(sum(chunk["document_name"] == item["document"] for chunk in chunks) / len(chunks))
                if item.get("together"):
                    together_n += 1
                    together_hits += int(any(all(_flat(phrase) in _flat(chunk["text"]) for phrase in item["together"]) for chunk in chunks))
                if split == "dev" and _is_overview_query(item["query"]):
                    overview_n += 1
                    overview_hits += int(any(chunk.get("kind") == "overview" for chunk in chunks))
            cards.update(card(f"search_hit4_{suffix}", _rate(hit4, len(rows)), len(rows), hits=int(hit4)))
            if split == "dev":
                cards.update(card("search_hit1_dev", _rate(hit1, len(rows)), len(rows), hits=int(hit1)))
                cards.update(card("search_mrr_dev", mrr / len(rows) if rows else 0.0, len(rows)))
                cards.update(card("search_doc_p4_dev", _mean(doc_scores), len(doc_scores)))
                cards.update(card("search_together_dev", _rate(together_hits, together_n), together_n, hits=together_hits))
                cards.update(card("search_overview_dev", _rate(overview_hits, overview_n), overview_n, hits=overview_hits))
                latency = _mean(times)
                best = latency
                if FLOORS.exists() and "search_latency_ms" in _load(FLOORS):
                    best = min(latency, _load(FLOORS)["search_latency_ms"]["best"])
                cards.update(card("search_latency_ms", latency, len(rows), best=best))
        return cards
    finally:
        if saved is not None:
            _restore_chroma(saved)


def measure_clarify():
    import tempfile

    import store
    from agents import clarify_agent
    from ingest import ingest_dir

    cases = _load(EVAL / "cases_clarify.json")
    independent = [case for case in cases if case.get("independent")]
    dependent = [case for case in cases if not case.get("independent")]
    passthrough = over = 0
    for case in independent:
        got = clarify_agent(case["query"], case["work"])
        passthrough += int(got == case.get("gold", case["query"]))
        over += int(got != case["query"])
    rewrite = anchor = 0
    for case in dependent:
        got = clarify_agent(case["query"], case["work"])
        rewrite += int(got != case["query"])
        needles = case.get("must_contain") or []
        anchor += int(all(needle.lower() in got.lower() for needle in needles))
    saved = store.CHROMA
    folder = tempfile.mkdtemp(prefix="score-docs-")
    store.CHROMA = Path(folder)
    store.reset()
    store.upsert_chunks(ingest_dir(DOCS))
    try:
        search_cases = [case for case in dependent if case.get("evidence")]
        hits = raw_hits = 0
        for case in search_cases:
            clear = clarify_agent(case["query"], case["work"])
            clarified = store.search_chunks(clear, 4)
            original = store.search_chunks(case["query"], 4)
            item = {"evidence": case["evidence"]}
            hits += int(_retrieval_ok(item, clarified))
            raw_hits += int(_retrieval_ok(item, original))
    finally:
        store.CHROMA = saved
        store.reset()
    cards = {}
    cards.update(card("clarify_passthrough", _rate(passthrough, len(independent)), len(independent), hits=passthrough))
    cards.update(card("clarify_rewrite", _rate(rewrite, len(dependent)), len(dependent), hits=rewrite))
    cards.update(card("clarify_anchor", _rate(anchor, len(dependent)), len(dependent), hits=anchor))
    cards.update(card("clarify_overrewrite", _rate(over, len(independent)), len(independent), hits=over))
    extra = {"raw_hit4": raw_hits, "raw_n": len(search_cases)}
    cards.update(card("clarify_search_hit4", _rate(hits, len(search_cases)), len(search_cases), hits=hits, extra=extra))
    return cards


def _has_fact_tokens(text):
    import re
    return bool(re.search(r"\d|[A-ZА-Я]{2,}", text or ""))


def measure_coord():
    import agents
    import coordinator

    chunk = {"text": "Цех имеет номер 4.", "document_name": "charter.txt", "chunk_index": 0, "section": ""}
    source = {"number": 1, "document_name": "charter.txt", "section": ""}

    def verdict(status, sources=(), feedback=""):
        return {"status": status, "missing": [], "feedback": feedback, "sources": list(sources)}

    scenarios = [
        {
            "id": "happy",
            "chunks": [chunk],
            "verdicts": [verdict(agents.CONFIRMED, [source])],
            "reply": "Цех имеет номер 4 [1].",
            "order": ["select", "clarify", "search", "answer", "check", "save"],
            "status": agents.CONFIRMED,
            "answers": 1,
            "retry": False,
        },
        {
            "id": "retry-ok",
            "chunks": [chunk],
            "verdicts": [verdict(agents.UNCONFIRMED, feedback="исправь"), verdict(agents.CONFIRMED, [source])],
            "reply": "Цех имеет номер 4 [1].",
            "order": ["select", "clarify", "search", "answer", "check", "answer", "check", "save"],
            "status": agents.CONFIRMED,
            "answers": 2,
            "retry": True,
        },
        {
            "id": "retry-fail",
            "chunks": [chunk],
            "verdicts": [verdict(agents.UNCONFIRMED, feedback="a"), verdict(agents.UNCONFIRMED, feedback="b")],
            "reply": "Цех имеет номер 4 [1].",
            "order": ["select", "clarify", "search", "answer", "check", "answer", "check", "save"],
            "status": agents.UNCONFIRMED,
            "answers": 2,
            "retry": True,
        },
        {
            "id": "missing",
            "chunks": [chunk],
            "verdicts": [verdict(agents.MISSING)],
            "reply": "Цех имеет номер 4 [1].",
            "order": ["select", "clarify", "search", "answer", "check", "save"],
            "status": agents.MISSING,
            "answers": 1,
            "retry": False,
        },
        {
            "id": "empty-search",
            "chunks": [],
            "verdicts": None,
            "reply": None,
            "order": ["select", "clarify", "search", "answer", "check", "save"],
            "status": agents.MISSING,
            "answers": 1,
            "retry": False,
            "empty": True,
        },
    ]

    originals = {name: getattr(coordinator, name) for name in ("get_dialog", "add_turn", "select_agent", "clarify_agent", "search_agent", "answer_agent", "check_agent")}
    real_complete = agents.complete
    order_hits = cap_hits = empty_hits = empty_n = 0
    retry_help = retry_n = discard = 0
    status_hits = 0
    try:
        for case in scenarios:
            order = []
            model_calls = []

            def track_complete(*args, **kwargs):
                model_calls.append(1)
                return real_complete(*args, **kwargs)

            chunks = list(case["chunks"])
            coordinator.get_dialog = lambda _id: []
            coordinator.add_turn = lambda *_args: order.append("save")
            coordinator.select_agent = lambda *_a: order.append("select") or []
            coordinator.clarify_agent = lambda *_a: order.append("clarify") or "номер цеха"
            coordinator.search_agent = lambda *_a, rows=chunks: order.append("search") or rows
            if case.get("empty"):
                coordinator.answer_agent = originals["answer_agent"]
                coordinator.check_agent = originals["check_agent"]
                agents.complete = track_complete
            else:
                reply = case["reply"]

                def answer(*_args, text=reply):
                    order.append("answer")
                    return text

                verdicts = list(case["verdicts"])

                def check(*_args, rows=verdicts):
                    order.append("check")
                    return rows.pop(0)

                coordinator.answer_agent = answer
                coordinator.check_agent = check
                agents.complete = real_complete
            result = coordinator.run("Какой номер у цеха?", f"score-{case['id']}")
            if case.get("empty"):
                order_hits += int(order[:3] == ["select", "clarify", "search"] and order[-1] == "save")
                empty_n += 1
                empty_hits += int(len(model_calls) == 0)
            else:
                order_hits += int(order == case["order"])
            cap_hits += int(order.count("answer") <= 2)
            if case.get("retry"):
                retry_n += 1
                retry_help += int(result["status"] == agents.CONFIRMED and _has_fact_tokens(result["answer"]))
            if _has_fact_tokens(case.get("reply") or "") and result["answer"] == agents.NO_ANSWER and case["status"] != agents.MISSING:
                discard += 1
            if case.get("empty"):
                status_hits += int(result["status"] == agents.MISSING and result["answer"] == agents.NO_ANSWER)
            else:
                status_hits += int(result["status"] == case["status"])
    finally:
        agents.complete = real_complete
        for name, value in originals.items():
            setattr(coordinator, name, value)
    n = len(scenarios)
    cards = {}
    cards.update(card("coord_order", _rate(order_hits, n), n, hits=order_hits))
    cards.update(card("coord_retry_cap", _rate(cap_hits, n), n, hits=cap_hits))
    cards.update(card("coord_empty_skip", _rate(empty_hits, empty_n), empty_n, hits=empty_hits))
    cards.update(card("coord_retry_help", _rate(retry_help, retry_n), retry_n, hits=retry_help))
    cards.update(card("coord_discard_good", _rate(discard, n), n, hits=discard))
    cards.update(card("coord_status_exact", _rate(status_hits, n), n, hits=status_hits))
    return cards


def freeze_chunks(folder=None):
    import tempfile

    import store

    tmp = folder or tempfile.mkdtemp(prefix="score-freeze-")
    saved = _with_chroma(tmp, INBOX)
    try:
        frozen = {}
        for item in _questions():
            chunks = store.search_chunks(item["query"], 4)
            frozen[item["id"]] = [
                {
                    "text": chunk["text"],
                    "document_name": chunk["document_name"],
                    "section": chunk.get("section", ""),
                    "kind": chunk.get("kind", "text"),
                    "chunk_index": chunk.get("chunk_index", 0),
                }
                for chunk in chunks
            ]
        _dump(FROZEN, frozen)
        return frozen, tmp
    finally:
        if folder is None:
            _restore_chroma(saved)


def _answer_flags(item, answer, chunks):
    import re
    from agents import NO_ANSWER as STOP

    flat = _flat(answer)
    facts_ok = True
    for fact in item.get("facts", []):
        options = fact if isinstance(fact, list) else [fact]
        if not any(_has(option, answer) for option in options):
            facts_ok = False
    starts_ok = True
    if item.get("starts"):
        starts_ok = flat.startswith(_flat(item["starts"]))
    forbidden_ok = True
    for fact in item.get("forbidden", []):
        if _flat(fact) in flat:
            forbidden_ok = False
    noanswer_ok = True
    if item.get("status") == "нет ответа":
        noanswer_ok = _flat(STOP).rstrip(".") in flat
    cite_ok = True
    if item.get("status") != "нет ответа":
        numbers = [int(num) for num in re.findall(r"\[(\d+)\]", answer or "")]
        cite_ok = bool(numbers) and all(1 <= num <= max(1, len(chunks)) for num in numbers)
    return {
        "facts": facts_ok,
        "starts": starts_ok if item.get("starts") else None,
        "forbidden": forbidden_ok if item.get("forbidden") else None,
        "noanswer": noanswer_ok if item.get("status") == "нет ответа" else None,
        "cite": cite_ok if item.get("status") != "нет ответа" else None,
        "type": _item_type(item),
    }


def measure_answer():
    from agents import answer_agent
    import dialog

    if not FROZEN.exists():
        freeze_chunks()
    frozen = _load(FROZEN)
    items = [item for item in _questions() if item["split"] == "dev"]
    facts = starts = forbidden = cite = noanswer = 0
    facts_n = starts_n = forbidden_n = cite_n = noanswer_n = 0
    by_type = {}
    times = []
    for item in items:
        chunks = frozen.get(item["id"]) or []
        dialog.reset()
        start = time.perf_counter()
        answer = answer_agent(item["query"], item["query"], chunks, [])
        times.append(time.perf_counter() - start)
        flags = _answer_flags(item, answer, chunks)
        if item.get("facts"):
            facts_n += 1
            facts += int(flags["facts"])
        if flags["starts"] is not None:
            starts_n += 1
            starts += int(flags["starts"])
        if flags["forbidden"] is not None:
            forbidden_n += 1
            forbidden += int(flags["forbidden"])
        if flags["cite"] is not None:
            cite_n += 1
            cite += int(flags["cite"])
        if flags["noanswer"] is not None:
            noanswer_n += 1
            noanswer += int(flags["noanswer"])
        kind = flags["type"]
        bucket = by_type.setdefault(kind, [0, 0])
        bucket[1] += 1
        bucket[0] += int(flags["facts"] if kind != "noanswer" else flags["noanswer"])
        print(f"answer {item['id']}: facts={flags['facts']} type={kind} t={times[-1]:.1f}s", flush=True)
    latency = _mean(times)
    best = latency
    if FLOORS.exists() and "answer_latency_s" in _load(FLOORS):
        best = min(latency, _load(FLOORS)["answer_latency_s"]["best"])
    cards = {}
    cards.update(card("answer_facts_dev", _rate(facts, facts_n), facts_n, hits=facts))
    cards.update(card("answer_starts_dev", _rate(starts, starts_n), starts_n, hits=starts))
    cards.update(card("answer_forbidden_dev", _rate(forbidden, forbidden_n), forbidden_n, hits=forbidden))
    cards.update(card("answer_cite_dev", _rate(cite, cite_n), cite_n, hits=cite))
    cards.update(card("answer_noanswer_dev", _rate(noanswer, noanswer_n), noanswer_n, hits=noanswer))
    for kind, (hits, n) in sorted(by_type.items()):
        cards.update(card(f"answer_by_type_{kind}", _rate(hits, n), n, hits=hits))
    cards.update(card("answer_latency_s", latency, len(items), best=best))
    return cards


def _e2e_ok(item, result):
    from agents import CONFIRMED

    flags = _answer_flags(item, result["answer"], [{"text": ""}] * 4)
    expected = item.get("status", CONFIRMED)
    status_ok = result["status"] == expected
    doc_ok = True
    if expected == CONFIRMED and item.get("document") not in (None, "*"):
        doc_ok = item["document"] in result.get("document_names", [])
    facts_ok = flags["facts"] if item.get("facts") else True
    starts_ok = flags["starts"] if flags["starts"] is not None else True
    forbidden_ok = flags["forbidden"] if flags["forbidden"] is not None else True
    return status_ok and doc_ok and facts_ok and starts_ok and forbidden_ok


def measure_e2e(holdout=False, only_holdout=False):
    import tempfile

    import dialog
    import store
    from coordinator import run
    from ingest import ingest_dir

    if not _inbox_ready():
        return {}
    tmp = tempfile.mkdtemp(prefix="score-e2e-")
    saved = store.CHROMA
    store.CHROMA = Path(tmp)
    store.reset()
    dialog.reset()
    store.upsert_chunks(ingest_dir(INBOX))
    cards = {}
    try:
        splits = ["holdout"] if only_holdout else (["dev"] + (["holdout"] if holdout else []))
        for split in splits:
            items = [item for item in _questions() if item["split"] == split]
            hits = 0
            by_type = {}
            times = []
            for item in items:
                dialog.reset()
                start = time.perf_counter()
                result = run(item["query"], f"score-{item['id']}")
                elapsed = time.perf_counter() - start
                times.append(elapsed)
                ok = _e2e_ok(item, result)
                hits += int(ok)
                kind = _item_type(item)
                bucket = by_type.setdefault(kind, [0, 0])
                bucket[1] += 1
                bucket[0] += int(ok)
                print(f"e2e {item['id']}: ok={ok} status={result['status']} t={elapsed:.1f}s", flush=True)
            key = "e2e_dev" if split == "dev" else "e2e_holdout"
            cards.update(card(key, _rate(hits, len(items)), len(items), hits=hits))
            if split == "dev":
                for kind, (got, n) in sorted(by_type.items()):
                    cards.update(card(f"e2e_by_type_{kind}", _rate(got, n), n, hits=got))
                latency = _mean(times)
                best = latency
                if FLOORS.exists() and "e2e_latency_s" in _load(FLOORS):
                    best = min(latency, _load(FLOORS)["e2e_latency_s"]["best"])
                cards.update(card("e2e_latency_s", latency, len(items), best=best))
        if only_holdout:
            return cards
        docs_tmp = tempfile.mkdtemp(prefix="score-dialog-")
        store.CHROMA = Path(docs_tmp)
        store.reset()
        dialog.reset()
        store.upsert_chunks(ingest_dir(DOCS))
        from agents import CONFIRMED, MISSING

        dialog_hits = 0
        for query, fact, banned, statuses, name in DIALOG_STEPS:
            result = run(query, "shop-pump")
            allowed = statuses or {CONFIRMED}
            ok = result["status"] in allowed
            if fact:
                ok = ok and fact.lower() in result["answer"].lower()
            if banned:
                ok = ok and banned.lower() not in result["answer"].lower()
            if name:
                ok = ok and name in result["document_names"]
            dialog_hits += int(ok)
            print(f"e2e_dialog {query!r}: ok={ok} status={result['status']}", flush=True)
        cards.update(card("e2e_dialog", _rate(dialog_hits, len(DIALOG_STEPS)), len(DIALOG_STEPS), hits=dialog_hits))
        return cards
    finally:
        store.CHROMA = saved
        store.reset()
        dialog.reset()


def measure(nodes, holdout=False):
    cards = {}
    for node in nodes:
        print(f"== {node} ==", flush=True)
        if node == "select":
            cards.update(measure_select())
        elif node == "clarify":
            cards.update(measure_clarify())
        elif node == "search":
            cards.update(measure_search(holdout=True))
        elif node == "check":
            cards.update(measure_check())
        elif node == "coord":
            cards.update(measure_coord())
        elif node == "answer":
            cards.update(measure_answer())
        elif node == "e2e":
            cards.update(measure_e2e(holdout=holdout))
        elif node == "holdout":
            cards.update(measure_e2e(holdout=True, only_holdout=True))
        else:
            raise SystemExit(f"unknown node: {node}")
    return cards


def _merge_last(cards):
    current = _load(LAST) if LAST.exists() else {}
    current.update(cards)
    _dump(LAST, current)
    return current


def write_floors(cards, raise_only=False):
    existing = _load(FLOORS) if FLOORS.exists() else {}
    for key, item in cards.items():
        if key not in existing:
            stored = dict(item)
            stored["floor"] = item["now"]
            existing[key] = stored
            continue
        if not raise_only:
            continue
        old = existing[key]
        if item.get("n") == 0:
            continue
        better = item["now"] > old["floor"] + 1e-12 if item["direction"] == "higher" else item["now"] < old["floor"] - 1e-12
        if better:
            old["floor"] = item["now"]
        old["now"] = item["now"]
        if key in TIME_KEYS:
            old["best"] = min(old.get("best", item["now"]), item["now"])
            old["room"] = max(0.0, item["now"] - old["best"])
        else:
            old["best"] = item["best"]
            old["room"] = item["room"]
        old["n"] = item["n"]
        if "hits" in item:
            old["hits"] = item["hits"]
    _dump(FLOORS, existing)
    return existing


def compare(floors, latest, keys=None):
    violations = []
    for key, item in floors.items():
        if keys is not None and key not in keys:
            continue
        if item.get("n") == 0:
            continue
        if key not in latest:
            violations.append(f"{key}: нет свежего значения")
            continue
        now = latest[key]["now"]
        floor = item["floor"]
        direction = item.get("direction") or _direction(key)
        if direction == "higher":
            if now + 1e-12 < floor:
                violations.append(f"{key}: {now} < floor {floor}")
        else:
            slack = 5.0 if key in TIME_KEYS else 0.0
            if key == "search_latency_ms":
                slack = 5000.0
            if now - 1e-12 > floor + slack:
                violations.append(f"{key}: {now} > floor {floor}+{slack}")
    return violations


def print_report(cards):
    groups = []
    seen = set()
    for key in list(cards):
        node = key.split("_")[0]
        if node == "e2e":
            node = "e2e"
        if node not in seen:
            seen.add(node)
            groups.append(node)
    print("\n=== scorecard now / best (осталось room) ===", flush=True)
    for node in groups:
        print(node, flush=True)
        for key, item in cards.items():
            if not (key == node or key.startswith(node + "_")):
                continue
            room = item["room"]
            room_s = "n/a" if room is None else f"{room:.3f}" if isinstance(room, float) else str(room)
            if "hits" in item and item["n"]:
                frac = f"{item['hits']}/{item['n']} = "
            else:
                frac = f"n={item['n']} "
            now = item["now"]
            best = item["best"]
            print(f"  {key:28} {frac}{now:.4f} / {best:.4f}  (осталось {room_s})  floor={item.get('floor', now):.4f}", flush=True)
        keys = [key for key in cards if key == node or key.startswith(node + "_")]
        rooms = [cards[key]["room"] for key in keys if cards[key]["room"] is not None]
        if rooms and all(room == 0 for room in rooms):
            print(f"  [{node} закрыт на этом наборе: room=0 по всем ключам]", flush=True)


def _parse_nodes(raw):
    if raw in ("fast",):
        return list(FAST_NODES)
    if raw in ("slow",):
        return list(SLOW_NODES)
    if raw in ("all", ""):
        return list(FAST_NODES + SLOW_NODES)
    return [part.strip() for part in raw.split(",") if part.strip()]


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--nodes", default="fast")
    parser.add_argument("--holdout", action="store_true")
    parser.add_argument("--write-floors", action="store_true")
    parser.add_argument("--raise-floors", action="store_true")
    parser.add_argument("--freeze", action="store_true")
    args = parser.parse_args(argv)
    if args.freeze:
        freeze_chunks()
        print(f"wrote {FROZEN}", flush=True)
        if args.nodes == "fast" and not args.write_floors:
            return 0
    nodes = _parse_nodes(args.nodes)
    cards = measure(nodes, holdout=args.holdout)
    latest = _merge_last(cards)
    if args.write_floors or (args.raise_floors and not compare(_load(FLOORS) if FLOORS.exists() else {}, latest)):
        write_floors(cards, raise_only=args.raise_floors)
    elif args.raise_floors:
        print("пороги не подняты: есть падения", flush=True)
        for line in compare(_load(FLOORS), latest):
            print(line, flush=True)
    report = _load(LAST)
    scoped = {key: report[key] for key in report if any(key == node or key.startswith(node + "_") or (node == "e2e" and key.startswith("e2e_")) for node in set(_parse_nodes(args.nodes)) | ({"search"} if "search" in nodes else set()))}
    print_report(report if args.nodes in ("all", "fast", "slow") else cards)
    if FLOORS.exists():
        bad = compare(_load(FLOORS), _load(LAST))
        if bad:
            print("\nGATE FAIL", flush=True)
            for line in bad:
                print(line, flush=True)
            return 1
        print("\nGATE OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
