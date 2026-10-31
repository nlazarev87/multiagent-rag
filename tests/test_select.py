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
