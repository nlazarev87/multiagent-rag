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


def test_catalog_lists_loaded_documents_without_search(monkeypatch):
    order = []
    monkeypatch.setattr(coordinator, "list_documents", lambda: ["a.txt", "b.txt"])
    monkeypatch.setattr(coordinator, "select_agent", lambda *_args: order.append("select") or [])
    monkeypatch.setattr(coordinator, "search_agent", lambda *_args: order.append("search") or [])
    result = coordinator.run("Какие документы загружены в систему?", "catalog")
    assert order == []
    assert result == {
        "answer": "a.txt, b.txt",
        "status": agents.CONFIRMED,
        "document_names": [],
        "sources": [],
    }
    again = coordinator.run("По каким документам я могу задавать вопросы?", "catalog-2")
    assert again["answer"] == "a.txt, b.txt"
    assert order == []


def test_catalog_ignores_a_syllable_inside_a_filename_word(monkeypatch):
    monkeypatch.setattr(coordinator, "list_documents", lambda: ["Идеи ИИ ассистентов.docx", "заметка.txt"])
    monkeypatch.setattr(coordinator, "select_agent", lambda *_args: (_ for _ in ()).throw(AssertionError("search")))
    result = coordinator.run("Перечисли название всех документов, которые загружены в систему", "all")
    assert result["answer"] == "Идеи ИИ ассистентов.docx, заметка.txt"


def test_count_keeps_overview_after_a_rejected_example(monkeypatch):
    order = []
    chunk = {
        "text": "Потоки\nРазных значений в столбце «ИД потока»: 4. Список: A, B, C, D.",
        "document_name": "note.txt",
        "chunk_index": 0,
        "section": "Потоки",
    }
    _wire(monkeypatch, order, [_verdict(agents.UNCONFIRMED, feedback="a"), _verdict(agents.UNCONFIRMED, feedback="b")])
    monkeypatch.setattr(coordinator, "search_agent", lambda *_args: order.append("search") or [chunk])
    monkeypatch.setattr(coordinator, "answer_agent", lambda *_args: order.append("answer") or "В библиотеке три потока [1].")
    result = coordinator.run("Сколько интеграционных потоков между системами?", "count")
    assert result["status"] == agents.CONFIRMED
    assert result["answer"] == "4 ИД потока [1]."
    assert result["sources"][0]["document_name"] == "note.txt"


def test_catalog_keeps_only_names_mentioned_in_the_question(monkeypatch):
    monkeypatch.setattr(coordinator, "list_documents", lambda: ["ГОСТ_1.docx", "заметка.txt"])
    monkeypatch.setattr(coordinator, "select_agent", lambda *_args: (_ for _ in ()).throw(AssertionError("search")))
    result = coordinator.run("Какие ГОСТы загружены в систему?", "g")
    assert result["answer"] == "ГОСТ_1.docx"
    assert result["sources"] == []


def test_plain_document_question_is_not_a_catalog(monkeypatch):
    order = []
    _wire(monkeypatch, order, [_verdict(agents.CONFIRMED, [SOURCE])])
    coordinator.run("Какие виды испытаний и какие документы должны оформляться?", "docs")
    assert order[0] == "select"


def test_finish_drops_citations_without_a_source(monkeypatch):
    order = []
    _wire(monkeypatch, order, [_verdict(agents.CONFIRMED, [SOURCE])])
    monkeypatch.setattr(coordinator, "answer_agent", lambda *_args: order.append("answer") or "Факт в тексте [1] [2].")
    result = coordinator.run("Какой номер у цеха?", "cite")
    assert result["answer"] == "Факт в тексте [1]."
    assert [source["number"] for source in result["sources"]] == [1]


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

def test_dependent_question_searches_only_previous_documents(monkeypatch):
    seen = []
    previous = {
        "query": "Какой номер у цеха?",
        "answer": "Цех имеет номер 4.",
        "document_names": ["charter.txt"],
    }
    monkeypatch.setattr(coordinator, "get_dialog", lambda _id: [])
    monkeypatch.setattr(coordinator, "add_turn", lambda *_args: None)
    monkeypatch.setattr(coordinator, "select_agent", lambda *_args: [previous])
    monkeypatch.setattr(coordinator, "clarify_agent", lambda query, _work: query)

    def search(_clear, names=None):
        seen.append(names)
        return [CHUNK]

    monkeypatch.setattr(coordinator, "search_agent", search)
    monkeypatch.setattr(coordinator, "answer_agent", lambda *_args: "Смена длится 8 часов [1].")
    monkeypatch.setattr(coordinator, "check_agent", lambda *_args: _verdict(agents.CONFIRMED, [SOURCE]))
    result = coordinator.run("Сколько она длится?", "d6")
    assert result["status"] == agents.CONFIRMED
    assert seen == [["charter.txt"]]

def test_new_question_is_not_limited_to_previous_documents(monkeypatch):
    seen = []
    previous = {
        "query": "Какой номер у цеха?",
        "answer": "Цех имеет номер 4.",
        "document_names": ["charter.txt"],
    }
    monkeypatch.setattr(coordinator, "get_dialog", lambda _id: [])
    monkeypatch.setattr(coordinator, "add_turn", lambda *_args: None)
    monkeypatch.setattr(coordinator, "select_agent", lambda *_args: [previous])
    monkeypatch.setattr(coordinator, "clarify_agent", lambda query, _work: query)

    def search(_clear, names=None):
        seen.append(names)
        return [CHUNK]

    monkeypatch.setattr(coordinator, "search_agent", search)
    monkeypatch.setattr(coordinator, "answer_agent", lambda *_args: "Давление равно 6 бар [1].")
    monkeypatch.setattr(coordinator, "check_agent", lambda *_args: _verdict(agents.CONFIRMED, [SOURCE]))
    coordinator.run("Какое давление у насоса?", "d7")
    assert seen == [None]

def test_dependent_question_without_documents_stays_unscoped(monkeypatch):
    seen = []
    previous = {"query": "Какой номер у цеха?", "answer": "Цех имеет номер 4.", "document_names": []}
    monkeypatch.setattr(coordinator, "get_dialog", lambda _id: [])
    monkeypatch.setattr(coordinator, "add_turn", lambda *_args: None)
    monkeypatch.setattr(coordinator, "select_agent", lambda *_args: [previous])
    monkeypatch.setattr(coordinator, "clarify_agent", lambda query, _work: query)

    def search(_clear, names=None):
        seen.append(names)
        return [CHUNK]

    monkeypatch.setattr(coordinator, "search_agent", search)
    monkeypatch.setattr(coordinator, "answer_agent", lambda *_args: "Смена длится 8 часов [1].")
    monkeypatch.setattr(coordinator, "check_agent", lambda *_args: _verdict(agents.CONFIRMED, [SOURCE]))
    coordinator.run("Сколько она длится?", "d8")
    assert seen == [None]

def test_run_researches_when_feedback_names_a_document(monkeypatch):
    order = []
    feedback = _wire(
        monkeypatch,
        order,
        [_verdict(agents.UNCONFIRMED, feedback="Возьми другой Документ."), _verdict(agents.CONFIRMED, [SOURCE])],
    )
    result = coordinator.run("Какое давление у насоса?", "d6")
    assert order == ["select", "clarify", "search", "answer", "check", "search", "answer", "check", "save"]
    assert feedback == [None, "Возьми другой Документ."]
    assert result["status"] == agents.CONFIRMED

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

def test_run_scopes_a_followup_to_the_previous_document(monkeypatch):
    seen = []
    turns = [{"query": "Какой номер у цеха?", "answer": "4", "document_names": ["charter.txt"]}]

    def search(_clear, names=None):
        seen.append(names)
        return [CHUNK]

    monkeypatch.setattr(coordinator, "get_dialog", lambda _id: [])
    monkeypatch.setattr(coordinator, "add_turn", lambda *_args: None)
    monkeypatch.setattr(coordinator, "select_agent", lambda *_args: turns)
    monkeypatch.setattr(coordinator, "clarify_agent", lambda *_args: "уточнение")
    monkeypatch.setattr(coordinator, "search_agent", search)
    monkeypatch.setattr(coordinator, "answer_agent", lambda *_args: "Цех имеет номер 4 [1].")
    monkeypatch.setattr(coordinator, "check_agent", lambda *_args: _verdict(agents.CONFIRMED, [SOURCE]))
    coordinator.run("Сколько она длится?", "d7")
    coordinator.run("Какое давление у насоса?", "d8")
    assert seen == [["charter.txt"], None]

def test_run_limits_follow_up_search_to_previous_documents(monkeypatch):
    seen = []
    history = [{
        "query": "Какой номер у цеха?",
        "answer": "Смена длится 8 часов.",
        "document_names": ["charter.txt"],
    }]
    monkeypatch.setattr(coordinator, "get_dialog", lambda _id: history)
    monkeypatch.setattr(coordinator, "add_turn", lambda *_args: None)
    monkeypatch.setattr(coordinator, "search_agent", lambda clear, names=None: seen.append(names) or [CHUNK])
    monkeypatch.setattr(coordinator, "answer_agent", lambda *_args: "8 часов [1].")
    monkeypatch.setattr(coordinator, "check_agent", lambda *_args: _verdict(agents.CONFIRMED, [SOURCE]))
    coordinator.run("Сколько она длится?", "d6")
    assert seen == [["charter.txt"]]
    seen.clear()
    history[0] = {**history[0], "document_names": []}
    coordinator.run("Сколько она длится?", "d6")
    assert seen == [None]
    seen.clear()
    history[0] = {**history[0], "document_names": ["charter.txt"]}
    coordinator.run("Какое давление у насоса?", "d6")
    assert seen == [None]
