import agents


def _fail(*_args, **_kwargs):
    raise AssertionError("complete")


def test_select_and_clarify(monkeypatch):
    monkeypatch.setattr(agents, "complete", _fail)
    turns = [{"query": "Какой номер у цеха?", "answer": "Смена длится 8 часов.", "document_names": ["charter.txt"]}]
    assert agents.select_agent("Как зовут мастера?", turns) == []
    assert agents.select_agent("Какой номер у склада?", turns) == []
    work = agents.select_agent("Сколько она длится?", turns)
    assert work == turns
    assert agents.clarify_agent("Сколько она длится?", work) == "Какой номер у цеха? Сколько она длится? 8"
    assert agents.clarify_agent("Какой номер у склада?", work) == "Какой номер у склада?"


def test_select_new_meaning(monkeypatch):
    monkeypatch.setattr(agents, "complete", _fail)
    turns = [{"query": "Какой номер у цеха?", "answer": "4", "document_names": []}]
    assert agents.select_agent("Какое давление у насоса?", turns) == []
    assert agents.clarify_agent("Какое давление у насоса?", []) == "Какое давление у насоса?"


def test_select_two_words_code_and_last(monkeypatch):
    monkeypatch.setattr(agents, "complete", _fail)
    first = {"query": "Какой номер у цеха?", "answer": "4", "document_names": ["charter.txt"]}
    pump = {"query": "Что умеет насос Н-12?", "answer": "Насос имеет обозначение Н-12.", "document_names": ["pump.md"]}
    last = {"query": "Какой номер у цеха?", "answer": "Цех имеет номер 4.", "document_names": ["charter.txt"]}
    assert agents.select_agent("Напомни номер у цеха", [first]) == [first]
    assert agents.select_agent("Какое давление у Н-12?", [pump]) == [pump]
    assert agents.select_agent("Напомни номер у цеха", [first, pump, last]) == [last]


def test_clarify_keeps_the_previous_question_when_the_answer_has_no_number(monkeypatch):
    monkeypatch.setattr(agents, "complete", _fail)
    turns = [{"query": "Как выглядит насос?", "answer": "Насос синий.", "document_names": ["pump.md"]}]
    query = "Какой у него цвет?"
    work = agents.select_agent(query, turns)
    assert work == turns
    assert agents.clarify_agent(query, work) == "Как выглядит насос? Какой у него цвет?"

def test_pronoun_stays_on_the_latest_turn_and_keeps_a_code(monkeypatch):
    monkeypatch.setattr(agents, "complete", _fail)
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
    assert agents.select_agent("Сколько она длится?", []) == []
    assert agents.select_agent("Сколько она длится?", [pump, shift]) == [shift]
    assert agents.select_agent("Какое давление у Н-12?", [pump, shift]) == [pump]
    assert agents.clarify_agent("Какое у него давление?", [pump]) == (
        "Что умеет насос Н-12? Какое у него давление? Н-12"
    )
    plain = {
        "query": "Как зовут мастера?",
        "answer": "Мастер Иванов.",
        "document_names": ["charter.txt"],
    }
    assert agents.clarify_agent("Где он работает?", [plain]) == "Как зовут мастера? Где он работает?"
    assert agents.select_agent("Какое её значение?", [pump, shift]) == [shift]


def test_code_only_followup_stays_on_the_latest_turn(monkeypatch):
    monkeypatch.setattr(agents, "complete", _fail)
    pump = {
        "query": "Что умеет насос Н-12?",
        "answer": "Насос имеет обозначение Н-12 [2].",
        "document_names": ["pump.md"],
    }
    shift = {
        "query": "Сколько длится смена?",
        "answer": "Смена длится 8 часов [1].",
        "document_names": ["charter.txt"],
    }
    assert agents.select_agent("Н-12?", []) == []
    assert agents.select_agent("Н-12?", [pump, shift]) == [shift]
    assert agents.select_agent("Какое у него давление на Н-12?", [pump, shift]) == [shift]
    assert agents.clarify_agent("Н-12?", [shift]) == "Сколько длится смена? Н-12? 8"
    assert agents.clarify_agent("Какое у него давление на Н-12?", [shift]) == (
        "Сколько длится смена? Какое у него давление на Н-12? 8"
    )
    assert agents.clarify_agent("Какое у него давление?", [pump]) == (
        "Что умеет насос Н-12? Какое у него давление? Н-12"
    )


def test_clarify_drops_citation_numbers_and_keeps_a_standard_code(monkeypatch):
    monkeypatch.setattr(agents, "complete", _fail)
    cited = {
        "query": "Какое давление у насоса?",
        "answer": "Давление высокое [1, 2].",
        "document_names": ["pump.md"],
    }
    assert agents.clarify_agent("Какое оно?", [cited]) == "Какое давление у насоса? Какое оно?"
    measured = {
        "query": "Сколько длится смена?",
        "answer": "Смена длится 8 часов [1, 2].",
        "document_names": ["charter.txt"],
    }
    assert agents.clarify_agent("Где она проходит?", [measured]) == (
        "Сколько длится смена? Где она проходит? 8"
    )
    coded = {
        "query": "Какой стандарт указан?",
        "answer": "Применяется ГОСТ 19.201-78 [3].",
        "document_names": ["std.docx"],
    }
    assert agents.clarify_agent("Где он описан?", [coded]) == (
        "Какой стандарт указан? Где он описан? ГОСТ 19.201-78"
    )
