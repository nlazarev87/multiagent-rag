import agents
import coordinator
import dialog

CHUNK = {
    "text": "Цех имеет номер 4.",
    "document_name": "charter.txt",
    "chunk_index": 0,
    "section": "",
}
SOURCE = {"number": 1, "document_name": "charter.txt", "section": ""}


def _wire(monkeypatch, order, verdicts):
    monkeypatch.setattr(coordinator, "get_dialog", lambda _id: [])
    monkeypatch.setattr(coordinator, "add_turn", lambda *_args: order.append("save"))
    monkeypatch.setattr(coordinator, "select_agent", lambda *_a: order.append("select") or [])
    monkeypatch.setattr(
        coordinator, "clarify_agent", lambda *_a: order.append("clarify") or "номер цеха"
    )
    monkeypatch.setattr(coordinator, "search_agent", lambda *_a: order.append("search") or [CHUNK])
    feedback = []

    def answer(*args):
        order.append("answer")
        feedback.append(args[4])
        return "Цех имеет номер 4 [1]."

    monkeypatch.setattr(coordinator, "answer_agent", answer)
    monkeypatch.setattr(
        coordinator, "check_agent", lambda *_a: order.append("check") or verdicts.pop(0)
    )
    return feedback


def _verdict(status, sources=(), feedback=""):
    return {"status": status, "missing": [], "feedback": feedback, "sources": list(sources)}


def test_run_order_and_sources(monkeypatch):
    order = []
    _wire(monkeypatch, order, [_verdict(agents.CONFIRMED, [SOURCE])])
    result = coordinator.run("Какой номер у цеха?", "d1")
    assert order == ["select", "clarify", "search", "answer", "check", "save"]
    assert result == {
        "answer": "Цех имеет номер 4 [1].",
        "status": agents.CONFIRMED,
        "document_names": ["charter.txt"],
        "sources": [SOURCE],
    }


def test_run_retries_once_with_feedback(monkeypatch):
    order = []
    feedback = _wire(
        monkeypatch,
        order,
        [_verdict(agents.UNCONFIRMED, feedback="исправь"), _verdict(agents.CONFIRMED, [SOURCE])],
    )
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


def test_run_keeps_model_answer_after_second_failure(monkeypatch):
    order = []
    _wire(
        monkeypatch,
        order,
        [_verdict(agents.UNCONFIRMED, feedback="a"), _verdict(agents.UNCONFIRMED, feedback="b")],
    )
    result = coordinator.run("Какой номер у цеха?", "d3")
    assert order.count("answer") == 2
    assert result["status"] == agents.UNCONFIRMED
    assert result["answer"] == "Цех имеет номер 4 [1]."
    assert result["sources"] == []
    assert result["document_names"] == []


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
    monkeypatch.setattr(
        coordinator, "list_documents", lambda: ["Идеи ИИ ассистентов.docx", "заметка.txt"]
    )
    monkeypatch.setattr(
        coordinator, "select_agent", lambda *_args: (_ for _ in ()).throw(AssertionError("search"))
    )
    result = coordinator.run(
        "Перечисли название всех документов, которые загружены в систему", "all"
    )
    assert result["answer"] == "Идеи ИИ ассистентов.docx, заметка.txt"


def test_count_keeps_overview_after_a_rejected_example(monkeypatch):
    order = []
    chunk = {
        "text": "Потоки\nРазных значений в столбце «ИД потока»: 4. Список: A, B, C, D.",
        "document_name": "note.txt",
        "chunk_index": 0,
        "section": "Потоки",
    }
    _wire(
        monkeypatch,
        order,
        [_verdict(agents.UNCONFIRMED, feedback="a"), _verdict(agents.UNCONFIRMED, feedback="b")],
    )
    monkeypatch.setattr(
        coordinator, "search_agent", lambda *_args: order.append("search") or [chunk]
    )
    monkeypatch.setattr(
        coordinator,
        "answer_agent",
        lambda *_args: order.append("answer") or "В библиотеке три потока [1].",
    )
    result = coordinator.run("Сколько интеграционных потоков между системами?", "count")
    assert result["status"] == agents.CONFIRMED_OVERVIEW
    assert result["answer"] == "4 ИД потока [1]."
    assert result["sources"][0]["document_name"] == "note.txt"


def test_catalog_keeps_only_names_mentioned_in_the_question(monkeypatch):
    monkeypatch.setattr(coordinator, "list_documents", lambda: ["ГОСТ_1.docx", "заметка.txt"])
    monkeypatch.setattr(
        coordinator, "select_agent", lambda *_args: (_ for _ in ()).throw(AssertionError("search"))
    )
    result = coordinator.run("Какие ГОСТы загружены в систему?", "g")
    assert result["answer"] == "ГОСТ_1.docx"
    assert result["sources"] == []


def test_catalog_keeps_every_file_when_the_question_only_says_documents(monkeypatch):
    monkeypatch.setattr(
        coordinator, "list_documents", lambda: ["Документ.docx", "Паспорт насоса.docx"]
    )
    monkeypatch.setattr(
        coordinator, "select_agent", lambda *_args: (_ for _ in ()).throw(AssertionError("search"))
    )
    result = coordinator.run("Какие документы загружены в систему?", "all-docs")
    assert result["status"] == agents.CONFIRMED
    assert result["answer"] == "Документ.docx, Паспорт насоса.docx"


def test_catalog_still_narrows_to_a_named_kind_of_file(monkeypatch):
    monkeypatch.setattr(
        coordinator, "list_documents", lambda: ["Паспорт насоса.docx", "Документ.docx"]
    )
    monkeypatch.setattr(
        coordinator, "select_agent", lambda *_args: (_ for _ in ()).throw(AssertionError("search"))
    )
    result = coordinator.run("Какие паспорта загружены в систему?", "passports")
    assert result["answer"] == "Паспорт насоса.docx"


def test_plain_document_question_is_not_a_catalog(monkeypatch):
    order = []
    _wire(monkeypatch, order, [_verdict(agents.CONFIRMED, [SOURCE])])
    coordinator.run("Какие виды испытаний и какие документы должны оформляться?", "docs")
    assert order[0] == "select"


def test_system_fact_is_not_answered_with_the_file_list(monkeypatch):
    order = []
    _wire(monkeypatch, order, [_verdict(agents.CONFIRMED, [SOURCE])])
    coordinator.run("Какое давление в системе охлаждения?", "pressure")
    assert order[0] == "select"
    order.clear()
    _wire(monkeypatch, order, [_verdict(agents.CONFIRMED, [SOURCE])])
    coordinator.run("Какой модуль загружен в память?", "loaded")
    assert order[0] == "select"


def test_loaded_document_question_is_not_answered_with_the_file_list(monkeypatch):
    order = []
    _wire(monkeypatch, order, [_verdict(agents.CONFIRMED, [SOURCE])])
    coordinator.run("Какое давление в документе, загруженном в систему?", "participle")
    assert order[0] == "select"
    order.clear()
    _wire(monkeypatch, order, [_verdict(agents.CONFIRMED, [SOURCE])])
    coordinator.run(
        "Какие требования к испытаниям у документа, который загружен в систему?", "relative"
    )
    assert order[0] == "select"
    order.clear()
    _wire(monkeypatch, order, [_verdict(agents.CONFIRMED, [SOURCE])])
    coordinator.run("Что сказано в загруженном в систему паспорте про давление?", "inside")
    assert order[0] == "select"


def test_relative_inventory_question_still_lists_files(monkeypatch):
    names = ["Документ.docx", "Паспорт насоса.docx"]
    monkeypatch.setattr(coordinator, "list_documents", lambda: list(names))
    monkeypatch.setattr(
        coordinator, "search_agent", lambda *_args: (_ for _ in ()).throw(AssertionError("search"))
    )
    result = coordinator.run("Какие документы, которые загружены в систему?", "relative-list")
    assert result["status"] == agents.CONFIRMED
    assert result["answer"] == "Документ.docx, Паспорт насоса.docx"
    for query in (
        "Какой документ, который загружен в систему?",
        "Какая документация, которая загружена в систему?",
        "Какое из документов, которое загружено в систему?",
        "Какую из документов, которую загружена в систему?",
    ):
        listed = coordinator.run(query, "singular-list")
        assert listed["status"] == agents.CONFIRMED
        assert listed["answer"] == "Документ.docx, Паспорт насоса.docx"
    order = []
    _wire(monkeypatch, order, [_verdict(agents.CONFIRMED, [SOURCE])])
    coordinator.run("Какое давление у документа, который загружен в систему?", "pressure-relative")
    assert order[0] == "select"
    assert "search" in order
    names[:] = ["Схема.docx", "заметка.txt"]
    scheme = coordinator.run("Какая схема загружена в систему?", "finite")
    assert scheme["status"] == agents.CONFIRMED
    assert scheme["answer"] == "Схема.docx"


def test_singular_question_word_does_not_narrow_the_file_list(monkeypatch):
    # A file whose name is itself a question word stays in the full inventory.
    # A real kind such as «паспорт» still narrows that list.
    names = [
        "Какой-либо.docx",
        "Какая-либо.docx",
        "Какое-либо.docx",
        "Какую-нибудь.docx",
        "Каков.docx",
        "Паспорт насоса.docx",
        "Схема.docx",
        "заметка.txt",
    ]
    monkeypatch.setattr(coordinator, "list_documents", lambda: list(names))
    monkeypatch.setattr(
        coordinator,
        "search_agent",
        lambda *_args: (_ for _ in ()).throw(AssertionError("search")),
    )
    expected = ", ".join(names)
    for query in (
        "Какой документ загружен в систему?",
        "Какая документация загружена в систему?",
        "Какое из документов загружено в систему?",
        "Какую документацию загружена в систему?",
        "Каков документ загружен в систему?",
        "Какова документация загружена в систему?",
        "Каково положение загружено в систему?",
        "Какой документ, который загружен в систему?",
    ):
        listed = coordinator.run(query, "question-word-file")
        assert listed["status"] == agents.CONFIRMED
        assert listed["answer"] == expected
        assert listed["sources"] == []
    passport = coordinator.run("Какой паспорт загружен в систему?", "question-word-passport")
    assert passport["status"] == agents.CONFIRMED
    assert passport["answer"] == "Паспорт насоса.docx"
    scheme = coordinator.run("Какая схема загружена в систему?", "question-word-scheme")
    assert scheme["answer"] == "Схема.docx"
    note = coordinator.run("Какую заметка загружена в систему?", "question-word-note")
    assert note["answer"] == "заметка.txt"


def test_relative_clause_keeps_a_three_letter_subject_on_search(monkeypatch):
    # Words shorter than three letters are inventory boilerplate. A three-letter
    # subject, including a number, is the document the question is about.
    monkeypatch.setattr(
        coordinator, "list_documents", lambda: ["Документ.docx", "Паспорт насоса.docx"]
    )
    monkeypatch.setattr(
        coordinator, "search_agent", lambda *_args: (_ for _ in ()).throw(AssertionError("search"))
    )
    listed = coordinator.run("Какие из документов, которые загружены в систему?", "short-before")
    assert listed["status"] == agents.CONFIRMED
    assert listed["answer"] == "Документ.docx, Паспорт насоса.docx"
    assert listed["sources"] == []
    for question in (
        "Какой газ у документа, который загружен в систему?",
        "Какой 220 у документа, который загружен в систему?",
    ):
        order = []
        _wire(monkeypatch, order, [_verdict(agents.CONFIRMED, [SOURCE])])
        coordinator.run(question, "content-before")
        assert order[0] == "select", question
        assert "search" in order


def test_finish_drops_citations_without_a_source(monkeypatch):
    order = []
    _wire(monkeypatch, order, [_verdict(agents.CONFIRMED, [SOURCE])])
    monkeypatch.setattr(
        coordinator,
        "answer_agent",
        lambda *_args: order.append("answer") or "Факт в тексте [1] [2].",
    )
    result = coordinator.run("Какой номер у цеха?", "cite")
    assert result["answer"] == "Факт в тексте [1]."
    assert [source["number"] for source in result["sources"]] == [1]


def test_finish_keeps_only_known_numbers_inside_one_citation(monkeypatch):
    order = []
    _wire(monkeypatch, order, [_verdict(agents.CONFIRMED, [SOURCE])])
    monkeypatch.setattr(
        coordinator,
        "answer_agent",
        lambda *_args: "Факт [1, 9] и лишнее [8, 7].",
    )
    result = coordinator.run("Какой номер у цеха?", "cite-group")
    assert result["answer"] == "Факт [1] и лишнее."
    assert [source["number"] for source in result["sources"]] == [1]


def test_run_researches_when_list_is_incomplete(monkeypatch):
    order = []
    feedback = _wire(
        monkeypatch,
        order,
        [
            _verdict(agents.UNCONFIRMED, feedback=agents.LIST_GAP),
            _verdict(agents.CONFIRMED, [SOURCE]),
        ],
    )
    result = coordinator.run("Какие смены есть в цехе?", "d5")
    assert order == [
        "select",
        "clarify",
        "search",
        "answer",
        "check",
        "search",
        "answer",
        "check",
        "save",
    ]
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
    monkeypatch.setattr(
        coordinator, "check_agent", lambda *_args: _verdict(agents.CONFIRMED, [SOURCE])
    )
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
    monkeypatch.setattr(
        coordinator, "check_agent", lambda *_args: _verdict(agents.CONFIRMED, [SOURCE])
    )
    coordinator.run("Какое давление у насоса?", "d7")
    assert seen == [None]


def test_dependent_question_without_documents_stays_unscoped(monkeypatch):
    seen = []
    previous = {
        "query": "Какой номер у цеха?",
        "answer": "Цех имеет номер 4.",
        "document_names": [],
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
    monkeypatch.setattr(
        coordinator, "check_agent", lambda *_args: _verdict(agents.CONFIRMED, [SOURCE])
    )
    coordinator.run("Сколько она длится?", "d8")
    assert seen == [None]


def test_run_researches_when_feedback_names_a_document(monkeypatch):
    order = []
    feedback = _wire(
        monkeypatch,
        order,
        [
            _verdict(agents.UNCONFIRMED, feedback="Возьми другой Документ."),
            _verdict(agents.CONFIRMED, [SOURCE]),
        ],
    )
    result = coordinator.run("Какое давление у насоса?", "d6")
    assert order == [
        "select",
        "clarify",
        "search",
        "answer",
        "check",
        "search",
        "answer",
        "check",
        "save",
    ]
    assert feedback == [None, "Возьми другой Документ."]
    assert result["status"] == agents.CONFIRMED


def test_run_scopes_search_to_the_previous_document_only_for_a_followup(monkeypatch):
    seen = []
    monkeypatch.setattr(coordinator, "get_dialog", lambda _id: [])
    monkeypatch.setattr(coordinator, "add_turn", lambda *_args: None)
    monkeypatch.setattr(coordinator, "clarify_agent", lambda query, _work: query)
    monkeypatch.setattr(coordinator, "answer_agent", lambda *_args: "Смена длится 8 часов [1].")
    monkeypatch.setattr(
        coordinator, "check_agent", lambda *_args: _verdict(agents.CONFIRMED, [SOURCE])
    )

    def search(clear, names=None):
        seen.append((clear, names))
        return [CHUNK]

    monkeypatch.setattr(coordinator, "search_agent", search)
    previous = {"query": "Какой номер у цеха?", "answer": "4", "document_names": ["charter.txt"]}
    monkeypatch.setattr(coordinator, "select_agent", lambda *_args: [previous])
    coordinator.run("Сколько она длится?", "d-follow")
    coordinator.run("Какое давление у насоса?", "d-new")
    monkeypatch.setattr(
        coordinator, "select_agent", lambda *_args: [{**previous, "document_names": []}]
    )
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
    monkeypatch.setattr(
        coordinator, "check_agent", lambda *_args: _verdict(agents.CONFIRMED, [SOURCE])
    )
    coordinator.run("Сколько она длится?", "d7")
    coordinator.run("Какое давление у насоса?", "d8")
    assert seen == [["charter.txt"], None]


def test_run_limits_follow_up_search_to_previous_documents(monkeypatch):
    seen = []
    history = [
        {
            "query": "Какой номер у цеха?",
            "answer": "Смена длится 8 часов.",
            "document_names": ["charter.txt"],
        }
    ]
    monkeypatch.setattr(coordinator, "get_dialog", lambda _id: history)
    monkeypatch.setattr(coordinator, "add_turn", lambda *_args: None)
    monkeypatch.setattr(
        coordinator, "search_agent", lambda clear, names=None: seen.append(names) or [CHUNK]
    )
    monkeypatch.setattr(coordinator, "answer_agent", lambda *_args: "8 часов [1].")
    monkeypatch.setattr(
        coordinator, "check_agent", lambda *_args: _verdict(agents.CONFIRMED, [SOURCE])
    )
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


def _watch_search(monkeypatch, work):
    seen = []
    monkeypatch.setattr(coordinator, "get_dialog", lambda _id: work)
    monkeypatch.setattr(coordinator, "add_turn", lambda *_args: None)
    monkeypatch.setattr(coordinator, "select_agent", lambda *_args: work)
    monkeypatch.setattr(coordinator, "clarify_agent", lambda *_args: "ясный")

    def search(clear, names=None):
        seen.append((clear, names))
        return [CHUNK]

    monkeypatch.setattr(coordinator, "search_agent", search)
    monkeypatch.setattr(coordinator, "answer_agent", lambda *_args: "Цех имеет номер 4 [1].")
    monkeypatch.setattr(
        coordinator, "check_agent", lambda *_args: _verdict(agents.CONFIRMED, [SOURCE])
    )
    return seen


def test_run_limits_a_follow_up_to_the_previous_document(monkeypatch):
    turn = {"query": "Какой номер у цеха?", "answer": "4", "document_names": ["charter.txt"]}
    seen = _watch_search(monkeypatch, [turn])
    coordinator.run("Сколько она длится?", "d-follow")
    assert seen == [("ясный", ["charter.txt"])]
    turn["document_names"] = []
    coordinator.run("Сколько она длится?", "d-follow")
    assert seen[-1] == ("ясный", None)


def test_run_searches_every_document_for_a_new_question(monkeypatch):
    turn = {"query": "Какой номер у цеха?", "answer": "4", "document_names": ["charter.txt"]}
    seen = _watch_search(monkeypatch, [turn])
    coordinator.run("Какое давление у насоса?", "d-new")
    assert seen == [("ясный", None)]


def test_run_does_not_scope_a_follow_up_without_history(monkeypatch):
    seen = _watch_search(monkeypatch, [])
    coordinator.run("Сколько она длится?", "d-empty")
    assert seen == [("ясный", None)]


def test_run_stops_when_the_attempt_limit_is_one(monkeypatch):
    monkeypatch.setattr(coordinator, "_attempts", lambda: 1)
    order = []
    _wire(
        monkeypatch,
        order,
        [_verdict(agents.UNCONFIRMED, feedback="исправь"), _verdict(agents.CONFIRMED, [SOURCE])],
    )
    result = coordinator.run("Какой номер у цеха?", "d7")
    assert order == ["select", "clarify", "search", "answer", "check", "save"]
    assert result == {
        "answer": agents.NO_ANSWER,
        "status": agents.MISSING,
        "document_names": [],
        "sources": [],
    }


def test_run_scopes_a_follow_up_and_not_a_new_question(monkeypatch):
    seen = []
    dialog.reset()
    dialog.add_turn(
        "d",
        {
            "query": "Какое давление у насоса?",
            "answer": "6 бар",
            "document_names": ["pump.md"],
        },
    )

    def search(clear, names=None):
        seen.append((names, clear))
        return [CHUNK]

    monkeypatch.setattr(coordinator, "search_agent", search)
    monkeypatch.setattr(coordinator, "answer_agent", lambda *_args: "6 бар [1].")
    monkeypatch.setattr(
        coordinator, "check_agent", lambda *_args: _verdict(agents.CONFIRMED, [SOURCE])
    )
    monkeypatch.setattr(coordinator, "add_turn", lambda *_args: None)
    coordinator.run("Сколько оно составляет?", "d")
    coordinator.run("Какое давление у насоса на складе?", "d")
    coordinator.run("А?", "d")
    dialog.reset()
    dialog.add_turn(
        "e",
        {
            "query": "Какое давление у насоса?",
            "answer": "6 бар",
            "document_names": [],
        },
    )
    coordinator.run("Сколько оно составляет?", "e")
    dialog.reset()
    assert seen == [
        (["pump.md"], "Какое давление у насоса? Сколько оно составляет? 6"),
        (None, "Какое давление у насоса на складе?"),
        (["pump.md"], "Какое давление у насоса? А? 6"),
        (None, "Какое давление у насоса? Сколько оно составляет? 6"),
    ]


def test_run_scopes_a_follow_up_to_the_previous_document(monkeypatch):
    dialog.reset()
    seen = []

    def search(_clear, names=None):
        seen.append(names)
        return [CHUNK]

    monkeypatch.setattr(coordinator, "search_agent", search)
    monkeypatch.setattr(coordinator, "answer_agent", lambda *_args: "Цех имеет номер 4 [1].")
    monkeypatch.setattr(
        coordinator, "check_agent", lambda *_args: _verdict(agents.CONFIRMED, [SOURCE])
    )
    coordinator.run("Какой номер у цеха?", "d-scope")
    coordinator.run("Сколько она длится?", "d-scope")
    coordinator.run("Какое давление у насоса?", "d-scope")
    assert seen == [None, ["charter.txt"], None]


def test_run_searches_again_when_feedback_names_a_document(monkeypatch):
    order = []
    _wire(
        monkeypatch,
        order,
        [
            _verdict(agents.UNCONFIRMED, feedback="Сведения относятся к другому документу."),
            _verdict(agents.UNCONFIRMED, feedback="Сведения относятся к другому документу."),
        ],
    )
    result = coordinator.run("Какой номер у цеха?", "d-doc")
    assert order == [
        "select",
        "clarify",
        "search",
        "answer",
        "check",
        "search",
        "answer",
        "check",
        "save",
    ]
    assert result["status"] == agents.UNCONFIRMED
    assert result["answer"] == "Цех имеет номер 4 [1]."
    assert result["sources"] == []
    assert result["document_names"] == []


def test_catalog_reports_an_empty_library(monkeypatch):
    monkeypatch.setattr(coordinator, "list_documents", lambda: [])
    monkeypatch.setattr(
        coordinator,
        "search_agent",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("search")),
    )
    result = coordinator.run("Какие документы загружены в систему?", "empty-catalog")
    assert result == {
        "answer": agents.NO_ANSWER,
        "status": agents.MISSING,
        "document_names": [],
        "sources": [],
    }


def test_catalog_keeps_a_short_code_and_ignores_a_short_word(monkeypatch):
    monkeypatch.setattr(
        coordinator,
        "search_agent",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("search")),
    )
    monkeypatch.setattr(coordinator, "list_documents", lambda: ["api.txt", "заметка.txt"])
    code = coordinator.run("Какие api загружены в систему?", "short-code")
    assert code["status"] == agents.CONFIRMED
    assert code["answer"] == "api.txt"
    monkeypatch.setattr(coordinator, "list_documents", lambda: ["цех.txt", "насос.txt"])
    word = coordinator.run("Какие цех загружены в систему?", "short-word")
    assert word["answer"] == "цех.txt, насос.txt"


def test_overview_source_skips_a_number_outside_the_fragments():
    chunk = {"document_name": "library.txt", "section": "Залы", "chunk_index": 2}
    assert coordinator._overview_sources("2 Зал [99] [1].", [chunk]) == [
        {
            "number": 1,
            "document_name": "library.txt",
            "section": "Залы",
            "chunk_index": 2,
        }
    ]
    assert coordinator._overview_sources("2 Зал [1].", []) == []


def test_catalog_says_nothing_is_loaded_without_searching(monkeypatch):
    dialog.reset()
    monkeypatch.setattr(coordinator, "list_documents", lambda: [])
    monkeypatch.setattr(
        coordinator, "search_agent", lambda *_args: (_ for _ in ()).throw(AssertionError("search"))
    )
    result = coordinator.run("Какие документы загружены в систему?", "empty-catalog")
    assert result == {
        "answer": agents.NO_ANSWER,
        "status": agents.MISSING,
        "document_names": [],
        "sources": [],
    }
    assert dialog.get_dialog("empty-catalog")[0]["answer"] == agents.NO_ANSWER


def test_catalog_lists_every_file_when_the_names_do_not_overlap(monkeypatch):
    monkeypatch.setattr(coordinator, "list_documents", lambda: ["ГОСТ_1.docx", "насос.md"])
    monkeypatch.setattr(
        coordinator, "search_agent", lambda *_args: (_ for _ in ()).throw(AssertionError("search"))
    )
    result = coordinator.run("Какие ГОСТ и насосы загружены в систему?", "both-names")
    assert result["status"] == agents.CONFIRMED
    assert result["answer"] == "ГОСТ_1.docx, насос.md"
    assert result["sources"] == []


def test_catalog_accepts_each_finite_loaded_form(monkeypatch):
    names = ["Паспорт насоса.docx", "Руководство.docx", "Пособие.docx"]
    monkeypatch.setattr(coordinator, "list_documents", lambda: list(names))
    monkeypatch.setattr(
        coordinator, "search_agent", lambda *_args: (_ for _ in ()).throw(AssertionError("search"))
    )
    listed = ", ".join(names)
    passport = coordinator.run("Какой паспорт загружен в систему?", "finite-m")
    assert passport["status"] == agents.CONFIRMED
    assert passport["answer"] == "Паспорт насоса.docx"
    guide = coordinator.run("Какое руководство загружено в систему?", "finite-n")
    assert guide["answer"] == "Руководство.docx"
    booklet = coordinator.run("Какое пособие загружено в систему?", "finite-book")
    assert booklet["answer"] == "Пособие.docx"
    yo = coordinator.run("Какие документы загружёны в систему?", "finite-yo")
    assert yo["answer"] == listed
    spaced = coordinator.run("Какие  ДОКУМЕНТЫ\nзагружены   в   систему?", "finite-space")
    assert spaced["answer"] == listed
    # «некоторые» содержит «котор», но это не относительное «который».
    some = coordinator.run("Какие некоторые документы загружены в систему?", "finite-some")
    assert some["answer"] == listed
    relative = coordinator.run("Какие документы, которое загружено в систему?", "finite-rel")
    assert relative["status"] == agents.CONFIRMED
    assert relative["answer"] == listed


def test_loaded_clause_and_negation_stay_on_search(monkeypatch):
    questions = [
        "Какое давление в загруженной в систему схеме?",
        "Что сказано про загруженную в систему схему?",
        "Какие схемы из загруженных в систему паспортов?",
        "Что сказано про загруженные в систему схемы?",
        "Почему документы не загружены в систему?",
        "Почему схема не загружена в систему?",
        "Почему пособие не загружено в систему?",
        "Почему файл НЕ  загружен\nв систему?",
        "Какое давление в документе, загружённом в систему?",
        "Какое пособие, которое загружено в систему?",
        "Какой ход у схемы, которая загружена в систему?",
    ]
    for question in questions:
        order = []
        _wire(monkeypatch, order, [_verdict(agents.CONFIRMED, [SOURCE])])
        coordinator.run(question, "loaded-search")
        assert order[0] == "select", question


def test_catalog_skips_a_negated_or_prefixed_load_and_accepts_yo(monkeypatch):
    # «не загружены» and «перезагружен» are not the inventory phrase.
    # «загружёны» is the same phrase with ё and still lists every file.
    monkeypatch.setattr(
        coordinator, "list_documents", lambda: ["Документ.docx", "Паспорт насоса.docx"]
    )
    for query, dialog_id in (
        ("Какие документы не загружены в систему?", "negated-load"),
        ("Какой модуль перезагружен в систему?", "prefixed-load"),
    ):
        order = []
        _wire(monkeypatch, order, [_verdict(agents.CONFIRMED, [SOURCE])])
        coordinator.run(query, dialog_id)
        assert order[0] == "select"
        assert "search" in order

    order = []
    _wire(monkeypatch, order, [_verdict(agents.CONFIRMED, [SOURCE])])
    listed = coordinator.run("Какие документы загружёны в систему?", "yo-load")
    assert order == ["save"]
    assert listed["status"] == agents.CONFIRMED
    assert listed["answer"] == "Документ.docx, Паспорт насоса.docx"
    assert listed["sources"] == []


def test_catalog_short_skip_matches_only_the_whole_token(monkeypatch):
    rules = dict(coordinator.routing())
    rules["catalog_skip"] = ["api"]
    monkeypatch.setattr(coordinator, "routing", lambda: rules)
    monkeypatch.setattr(
        coordinator, "search_agent", lambda *_args: (_ for _ in ()).throw(AssertionError("search"))
    )
    monkeypatch.setattr(
        coordinator, "list_documents", lambda: ["api.txt", "apis.txt", "заметка.txt"]
    )
    exact = coordinator.run("Какие api загружены в систему?", "short-skip")
    assert exact["status"] == agents.CONFIRMED
    assert exact["answer"] == "api.txt, apis.txt, заметка.txt"
    longer = coordinator.run("Какие apis загружены в систему?", "longer-code")
    assert longer["answer"] == "apis.txt"


def test_code_only_followup_searches_the_latest_document(monkeypatch):
    dialog.reset()
    pump = {
        "query": "Что умеет насос Н-12?",
        "answer": "Насос имеет обозначение Н-12.",
        "document_names": ["pump.md"],
    }
    shift = {
        "query": "Сколько длится смена?",
        "answer": "Смена длится 8 часов.",
        "document_names": ["charter.txt"],
    }
    dialog.set_dialog("code-follow", [pump, shift])
    seen = []
    monkeypatch.setattr(coordinator, "add_turn", lambda *_args: None)
    monkeypatch.setattr(
        coordinator,
        "search_agent",
        lambda clear, names=None: seen.append((clear, names)) or [CHUNK],
    )
    monkeypatch.setattr(coordinator, "answer_agent", lambda *_args: "Смена длится 8 часов [1].")
    monkeypatch.setattr(
        coordinator, "check_agent", lambda *_args: _verdict(agents.CONFIRMED, [SOURCE])
    )
    coordinator.run("Н-12?", "code-follow")
    coordinator.run("Какое у него давление на Н-12?", "code-follow")
    assert seen == [
        ("Сколько длится смена? Н-12? 8", None),
        ("Сколько длится смена? Какое у него давление на Н-12? 8", None),
    ]
    shift["document_names"] = []
    dialog.set_dialog("code-follow", [pump, shift])
    coordinator.run("Н-12?", "code-follow")
    assert seen[-1] == ("Сколько длится смена? Н-12? 8", None)
    dialog.reset()


def test_places_keeps_a_pronoun_followup_and_releases_a_new_name():
    turn = {
        "query": "Какой номер у цеха?",
        "answer": "Цех имеет номер 4.",
        "document_names": ["charter.txt"],
        "places": [{"kb_id": "k", "document_name": "charter.txt"}],
    }
    assert coordinator._places([turn], "Сколько она длится?") == turn["places"]
    assert coordinator._places([turn], "Где стоит гидроаккумулятор у него?") is None
    assert coordinator._places([turn], "Сколько она длится?", "Возьми другой документ.") is None
    refused = {**turn, "answer": agents.NO_ANSWER}
    assert coordinator._places([refused], "Сколько она длится?") is None


def test_finish_keeps_sources_without_a_citation_number(monkeypatch):
    extra = {"number": 2, "document_name": "pump.md", "section": ""}
    order = []
    _wire(monkeypatch, order, [_verdict(agents.CONFIRMED, [SOURCE, extra])])
    monkeypatch.setattr(
        coordinator,
        "answer_agent",
        lambda *_args: order.append("answer") or "Факт в тексте [1].",
    )
    result = coordinator.run("Какой номер у цеха?", "two-src")
    assert result["answer"] == "Факт в тексте [1]."
    assert [source["document_name"] for source in result["sources"]] == ["charter.txt", "pump.md"]
    assert result["document_names"] == ["charter.txt", "pump.md"]


def test_finish_drops_only_the_invalid_number_in_a_citation(monkeypatch):
    order = []
    _wire(monkeypatch, order, [_verdict(agents.CONFIRMED, [SOURCE])])
    monkeypatch.setattr(
        coordinator,
        "answer_agent",
        lambda *_args: order.append("answer") or "А [9] Б [1, 2].",
    )
    result = coordinator.run("Какой номер у цеха?", "cite-mix")
    assert result["answer"] == "А Б [1]."
    assert [source["number"] for source in result["sources"]] == [1]


def test_run_writes_trace_steps_to_scope(monkeypatch):
    order = []
    _wire(monkeypatch, order, [_verdict(agents.CONFIRMED, [SOURCE])])
    scope = type("Scope", (), {})()
    scope.kbs = ["kb"]
    scope.trace = []
    scope.chunks = []
    scope.known = lambda _term: True
    scope.search = lambda clear, limit, places: [CHUNK]
    result = coordinator.run("Какой номер у цеха?", "d-trace", scope)
    assert set(result) == {"answer", "status", "document_names", "sources"}
    steps = scope.trace_steps
    assert isinstance(steps, list) and steps
    assert all("node" in step and "started_at" in step and "duration_ms" in step for step in steps)
    seen = [step["node"] for step in steps]
    assert seen == [
        "catalog",
        "select",
        "clarify",
        "search",
        "answer",
        "check",
        "route",
        "finish",
    ]
    for step in steps:
        assert step["input"] and step["output"]
        assert step["attempt"] == 1
    search = next(step for step in steps if step["node"] == "search")
    assert "focused_query" in search["output"]
    assert "previews" in search["output"]
    assert search["output"]["search_fallback_used"] is False
    finish = next(step for step in steps if step["node"] == "finish")
    assert finish["output"]["heuristic_finish_answer"] is False
    assert scope.trace == []


def test_run_finish_step_has_heuristic_flag(monkeypatch):
    order = []
    _wire(
        monkeypatch,
        order,
        [
            _verdict(agents.UNCONFIRMED, feedback="a"),
            _verdict(agents.UNCONFIRMED, feedback="b"),
        ],
    )
    scope = type("Scope", (), {})()
    scope.kbs = ["kb"]
    scope.trace = []
    scope.chunks = []
    scope.known = lambda _term: True
    scope.search = lambda _clear, _limit, _places: [CHUNK]
    result = coordinator.run("Какой номер у цеха?", "d-keep", scope)
    assert result["status"] == agents.UNCONFIRMED
    assert result["answer"] == "Цех имеет номер 4 [1]."
    finish = next(step for step in scope.trace_steps if step["node"] == "finish")
    assert finish["output"]["heuristic_finish_answer"] is True


def _scope_with_search(monkeypatch, seen, results):
    monkeypatch.setattr(coordinator, "get_dialog", lambda _id: [])
    monkeypatch.setattr(coordinator, "add_turn", lambda *_args: None)
    monkeypatch.setattr(coordinator, "clarify_agent", lambda query, _work: query)
    monkeypatch.setattr(coordinator, "answer_agent", lambda *_args: "Смена длится 8 часов [1].")
    monkeypatch.setattr(
        coordinator, "check_agent", lambda *_args: _verdict(agents.CONFIRMED, [SOURCE])
    )

    def search(_clear, _limit, places):
        seen.append(places)
        return results.pop(0)

    scope = type("Scope", (), {})()
    scope.kbs = ["kb"]
    scope.trace = []
    scope.chunks = []
    scope.known = lambda _term: True
    scope.search = search
    return scope


def _search_step(scope):
    return next(step for step in scope.trace_steps if step["node"] == "search")


def test_search_falls_back_when_sliced_search_returns_empty(monkeypatch):
    previous = {
        "query": "Какой номер у цеха?",
        "answer": "Цех имеет номер 4.",
        "document_names": ["a.txt"],
    }
    monkeypatch.setattr(coordinator, "select_agent", lambda *_args: [previous])
    seen = []
    scope = _scope_with_search(monkeypatch, seen, [[], [CHUNK]])
    coordinator.run("Сколько она длится?", "d-fallback", scope)
    assert seen == [[{"kb_id": "", "document_name": "a.txt"}], None]
    step = _search_step(scope)
    assert step["output"]["search_fallback_used"] is True
    assert step["output"]["chunks_returned"] == 1
    assert step["output"]["fallback_used"] is True


def test_search_does_not_fall_back_when_names_empty(monkeypatch):
    previous = {
        "query": "Какой номер у цеха?",
        "answer": "Цех имеет номер 4.",
        "document_names": [],
    }
    monkeypatch.setattr(coordinator, "select_agent", lambda *_args: [previous])
    seen = []
    scope = _scope_with_search(monkeypatch, seen, [[]])
    coordinator.run("Сколько она длится?", "d-empty-names", scope)
    assert seen == [None]
    step = _search_step(scope)
    assert step["output"]["search_fallback_used"] is False
    assert step["output"]["chunks_returned"] == 0


def test_concurrent_runs_dont_block_queue(monkeypatch):
    import threading
    import time

    started = []

    def slow(*_args, **_kwargs):
        started.append(time.perf_counter())
        time.sleep(1.5)
        return {"answer": "ответ", "status": "подтверждён", "document_names": [], "sources": []}

    monkeypatch.setattr(coordinator, "_run", slow)
    threads = [
        threading.Thread(target=coordinator.run, args=("q1", "d1")),
        threading.Thread(target=coordinator.run, args=("q2", "d2")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert len(started) == 2
    gap = abs(started[1] - started[0])
    assert gap < 1.0, f"второй проход стартовал через {gap:.2f}s"


def test_no_global_graph_executor():
    import inspect

    assert "_graph_executor" not in inspect.getsource(coordinator.run)
    assert not hasattr(coordinator, "_graph_executor")


def test_search_does_not_fall_back_when_no_work(monkeypatch):
    monkeypatch.setattr(coordinator, "select_agent", lambda *_args: [])
    seen = []
    scope = _scope_with_search(monkeypatch, seen, [[]])
    coordinator.run("Какое давление у насоса?", "d-no-work", scope)
    assert seen == [None]
    step = _search_step(scope)
    assert step["output"]["search_fallback_used"] is False
    assert step["output"]["chunks_returned"] == 0


def _trace_scope(monkeypatch, verdicts):
    """Scope для trace-тестов: поиск отдаёт CHUNK, проверка берёт вердикты по очереди."""
    scope = type("Scope", (), {})()
    scope.kbs = ["kb"]
    scope.trace = []
    scope.chunks = []
    scope.known = lambda _term: True
    scope.search = lambda _clear, _limit, _places: [CHUNK]
    monkeypatch.setattr(coordinator, "get_dialog", lambda _id: [])
    monkeypatch.setattr(coordinator, "add_turn", lambda *_args: None)
    monkeypatch.setattr(coordinator, "select_agent", lambda *_args: [])
    monkeypatch.setattr(coordinator, "clarify_agent", lambda *_args: "номер цеха")
    monkeypatch.setattr(coordinator, "answer_agent", lambda *_args: "Цех имеет номер 4 [1].")
    monkeypatch.setattr(coordinator, "check_agent", lambda *_args: verdicts.pop(0))
    return scope


def test_trace_order_and_attempts_on_retry(monkeypatch):
    verdicts = [
        _verdict(agents.UNCONFIRMED, feedback="исправь"),
        _verdict(agents.CONFIRMED, [SOURCE]),
    ]
    scope = _trace_scope(monkeypatch, verdicts)
    result = coordinator.run("Какой номер у цеха?", "d-trace-order", scope)
    assert result["status"] == agents.CONFIRMED
    seen = [step["node"] for step in scope.trace_steps]
    assert seen == [
        "catalog",
        "select",
        "clarify",
        "search",
        "answer",
        "check",
        "route",
        "answer",
        "check",
        "route",
        "finish",
    ]
    answers = [step for step in scope.trace_steps if step["node"] == "answer"]
    checks = [step for step in scope.trace_steps if step["node"] == "check"]
    assert [step["attempt"] for step in answers] == [1, 2]
    assert [step["attempt"] for step in checks] == [1, 2]
    routes = [step for step in scope.trace_steps if step["node"] == "route"]
    assert [step["output"]["next"] for step in routes] == ["answer", "finish"]
    for step in scope.trace_steps:
        assert step["input"] and step["output"]


def test_trace_route_decides_search_on_document_feedback(monkeypatch):
    verdicts = [
        _verdict(agents.UNCONFIRMED, feedback="Возьми другой документ."),
        _verdict(agents.CONFIRMED, [SOURCE]),
    ]
    scope = _trace_scope(monkeypatch, verdicts)
    coordinator.run("Какое давление у насоса?", "d-trace-doc", scope)
    seen = [step["node"] for step in scope.trace_steps]
    assert seen.count("search") == 2
    routes = [step for step in scope.trace_steps if step["node"] == "route"]
    assert [step["output"]["next"] for step in routes] == ["search", "finish"]


def test_trace_answer_has_prompt_and_tokens(monkeypatch):
    scope = _trace_scope(monkeypatch, [_verdict(agents.CONFIRMED, [SOURCE])])

    def answer(query, clear, chunks, work, feedback, features, usage):
        scope.trace.append("SYSTEM: пример\nUSER: вопрос")
        usage["tokens_in"] = 12
        usage["tokens_out"] = 7
        return "Цех имеет номер 4 [1]."

    monkeypatch.setattr(coordinator, "answer_agent", answer)
    monkeypatch.setattr(coordinator, "model_display_name", lambda: "test-model")
    coordinator.run("Какой номер у цеха?", "d-trace-answer", scope)
    step = next(s for s in scope.trace_steps if s["node"] == "answer")
    assert step["output"]["prompt"] == "SYSTEM: пример\nUSER: вопрос"
    assert step["output"]["model"] == "test-model"
    assert step["output"]["service"] == "llama.cpp"
    assert step["output"]["tokens_in"] == 12
    assert step["output"]["tokens_out"] == 7
    assert step["attempt"] == 1


def test_trace_search_has_previews(monkeypatch):
    scope = _trace_scope(monkeypatch, [_verdict(agents.CONFIRMED, [SOURCE])])
    coordinator.run("Какой номер у цеха?", "d-trace-preview", scope)
    step = _search_step(scope)
    assert step["output"]["service"] == "chroma+bm25"
    assert step["output"]["previews"] == [
        {"document_name": "charter.txt", "chunk_index": 0, "text": "Цех имеет номер 4."}
    ]


def test_trace_catalog_step_records_decision(monkeypatch):
    scope = _trace_scope(monkeypatch, [_verdict(agents.CONFIRMED, [SOURCE])])
    coordinator.run("Какой номер у цеха?", "d-trace-catalog", scope)
    catalog = scope.trace_steps[0]
    assert catalog["node"] == "catalog"
    assert catalog["output"]["is_catalog"] is False
    assert catalog["attempt"] == 1


def test_trace_catalog_query_records_names(monkeypatch):
    scope = type("Scope", (), {})()
    scope.kbs = ["kb"]
    scope.trace = []
    scope.chunks = []
    scope.names = lambda: ["a.txt", "b.txt"]
    result = coordinator.run("Какие документы загружены в систему?", "d-trace-cat", scope)
    assert result["answer"] == "a.txt, b.txt"
    catalog = scope.trace_steps[0]
    assert catalog["node"] == "catalog"
    assert catalog["output"]["is_catalog"] is True
    assert catalog["output"]["answer"] == "a.txt, b.txt"
    assert catalog["output"]["status"] == agents.CONFIRMED


def test_clip_strings_caps_at_4000():
    value = {"text": "x" * 5000, "nested": {"items": ["y" * 4001, 3]}}
    clipped, cut = coordinator._clip_strings(value)
    assert len(clipped["text"]) == 4000
    assert len(clipped["nested"]["items"][0]) == 4000
    assert clipped["nested"]["items"][1] == 3
    assert cut is True


def test_chunk_previews_cap_count_and_length():
    chunks = [
        {"text": "a" * 700, "document_name": f"d{i}.txt", "chunk_index": i} for i in range(10)
    ]
    previews, truncated = coordinator._chunk_previews(chunks)
    assert len(previews) == 8
    assert all(len(item["text"]) == 600 for item in previews)
    assert truncated is True


def test_fit_trace_caps_at_64_kb():
    steps = [
        {
            "node": "answer",
            "started_at": "t",
            "duration_ms": 1.0,
            "input": {},
            "output": {"prompt": "p" * 100_000},
            "attempt": 1,
            "timed_out": False,
        }
    ]
    fitted = coordinator._fit_trace(steps)
    assert coordinator._trace_size(fitted) <= 64 * 1024
    assert fitted[0]["output"]["truncated"] is True


def test_trace_partial_on_exception(monkeypatch):
    import pytest

    scope = type("Scope", (), {})()
    scope.kbs = ["kb"]
    scope.trace = []
    scope.chunks = []
    scope.known = lambda _term: True
    scope.search = lambda _clear, _limit, _places: [CHUNK]
    monkeypatch.setattr(coordinator, "get_dialog", lambda _id: [])
    monkeypatch.setattr(coordinator, "add_turn", lambda *_args: None)
    monkeypatch.setattr(coordinator, "select_agent", lambda *_args: [])
    monkeypatch.setattr(coordinator, "clarify_agent", lambda *_args: "номер цеха")
    monkeypatch.setattr(coordinator, "answer_agent", lambda *_args: "Цех имеет номер 4 [1].")

    def fail(*_args):
        raise RuntimeError("boom")

    monkeypatch.setattr(coordinator, "check_agent", fail)
    with pytest.raises(RuntimeError):
        coordinator.run("Какой номер у цеха?", "d-trace-fail", scope)
    nodes = [step["node"] for step in scope.trace_steps]
    assert "search" in nodes
    assert "check" not in nodes
