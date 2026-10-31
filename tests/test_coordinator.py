import agents
import coordinator

CHUNK = {"text": "Цех имеет номер 4.", "document_name": "charter.txt", "chunk_index": 0, "section": ""}
SOURCE = {"number": 1, "document_name": "charter.txt", "section": ""}


def _wire(monkeypatch, order, verdicts):
    monkeypatch.setattr(coordinator, "get_dialog", lambda _id: [])
    monkeypatch.setattr(coordinator, "add_turn", lambda *_args: order.append("save"))
    monkeypatch.setattr(coordinator, "select_agent", lambda *_a: order.append("select") or [])
    monkeypatch.setattr(coordinator, "clarify_agent", lambda *_a: order.append("clarify") or "номер цеха")
    monkeypatch.setattr(coordinator, "search_agent", lambda *_a: order.append("search") or [CHUNK])
    feedback = []

    def answer(*args):
        order.append("answer")
        feedback.append(args[4])
        return "Цех имеет номер 4 [1]."

    monkeypatch.setattr(coordinator, "answer_agent", answer)
    monkeypatch.setattr(coordinator, "check_agent", lambda *_a: order.append("check") or verdicts.pop(0))
    return feedback


def _verdict(status, sources=(), feedback=""):
    return {"status": status, "missing": [], "feedback": feedback, "sources": list(sources)}


def test_run_order_and_sources(monkeypatch):
    order = []
    _wire(monkeypatch, order, [_verdict(agents.CONFIRMED, [SOURCE])])
    result = coordinator.run("Какой номер у цеха?", "d1")
    assert order == ["select", "clarify", "search", "answer", "check", "save"]
    assert result == {"answer": "Цех имеет номер 4 [1].", "status": agents.CONFIRMED, "document_names": ["charter.txt"], "sources": [SOURCE]}


def test_run_retries_once_with_feedback(monkeypatch):
    order = []
    feedback = _wire(monkeypatch, order, [_verdict(agents.UNCONFIRMED, feedback="исправь"), _verdict(agents.CONFIRMED, [SOURCE])])
    result = coordinator.run("Какой номер у цеха?", "d2")
    assert order == ["select", "clarify", "search", "answer", "check", "answer", "check", "save"]
    assert feedback == [None, "исправь"]
    assert result["status"] == agents.CONFIRMED


def test_run_replaces_answer_when_documents_have_none(monkeypatch):
    order = []
    _wire(monkeypatch, order, [_verdict(agents.MISSING)])
    result = coordinator.run("Какая версия Python у цеха?", "d4")
    assert order.count("answer") == 1
    assert result["answer"] == agents.NO_ANSWER
    assert result["status"] == agents.MISSING


def test_run_gives_up_after_second_failure(monkeypatch):
    order = []
    _wire(monkeypatch, order, [_verdict(agents.UNCONFIRMED, feedback="a"), _verdict(agents.UNCONFIRMED, feedback="b")])
    result = coordinator.run("Какой номер у цеха?", "d3")
    assert order.count("answer") == 2
    assert result == {"answer": agents.NO_ANSWER, "status": agents.MISSING, "document_names": [], "sources": []}


def test_run_scopes_search_to_the_previous_document_only_for_a_followup(monkeypatch):
    seen = []
    monkeypatch.setattr(coordinator, "get_dialog", lambda _id: [])
    monkeypatch.setattr(coordinator, "add_turn", lambda *_args: None)
    monkeypatch.setattr(coordinator, "clarify_agent", lambda query, _work: query)
    monkeypatch.setattr(coordinator, "answer_agent", lambda *_args: "Смена длится 8 часов [1].")
    monkeypatch.setattr(coordinator, "check_agent", lambda *_args: _verdict(agents.CONFIRMED, [SOURCE]))

    def search(clear, names=None):
        seen.append((clear, names))
        return [CHUNK]

    monkeypatch.setattr(coordinator, "search_agent", search)
    previous = {"query": "Какой номер у цеха?", "answer": "4", "document_names": ["charter.txt"]}
    monkeypatch.setattr(coordinator, "select_agent", lambda *_args: [previous])
    coordinator.run("Сколько она длится?", "d-follow")
    coordinator.run("Какое давление у насоса?", "d-new")
    monkeypatch.setattr(coordinator, "select_agent", lambda *_args: [{**previous, "document_names": []}])
    coordinator.run("Сколько она длится?", "d-empty")
    assert seen == [
        ("Сколько она длится?", ["charter.txt"]),
        ("Какое давление у насоса?", None),
        ("Сколько она длится?", None),
    ]


def test_run_stops_when_attempt_limit_is_one(monkeypatch):
    order = []
    _wire(monkeypatch, order, [_verdict(agents.UNCONFIRMED, feedback="исправь")])
    monkeypatch.setattr(coordinator, "runtime", lambda: {"attempts": 1})
    result = coordinator.run("Какой номер у цеха?", "d-once")
    assert order.count("answer") == 1
    assert result["answer"] == agents.NO_ANSWER
    assert result["status"] == agents.MISSING
    assert result["sources"] == []


def test_run_researches_when_feedback_names_a_document(monkeypatch):
    order = []
    feedback = _wire(
        monkeypatch,
        order,
        [_verdict(agents.UNCONFIRMED, feedback="Ищи в другом документе."), _verdict(agents.CONFIRMED, [SOURCE])],
    )
    result = coordinator.run("Какой номер у цеха?", "d-doc")
    assert order == ["select", "clarify", "search", "answer", "check", "search", "answer", "check", "save"]
    assert feedback == [None, "Ищи в другом документе."]
    assert result["status"] == agents.CONFIRMED


def test_run_researches_when_list_is_incomplete(monkeypatch):
    order = []
    feedback = _wire(
        monkeypatch,
        order,
        [_verdict(agents.UNCONFIRMED, feedback=agents.LIST_GAP), _verdict(agents.CONFIRMED, [SOURCE])],
    )
    result = coordinator.run("Какие смены есть в цехе?", "d5")
    assert order == ["select", "clarify", "search", "answer", "check", "search", "answer", "check", "save"]
    assert feedback == [None, agents.LIST_GAP]
    assert result["status"] == agents.CONFIRMED
