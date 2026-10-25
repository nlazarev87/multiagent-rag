import agents


def _fail(*_args, **_kwargs):
    raise AssertionError("complete")


def test_select_and_clarify(monkeypatch):
    monkeypatch.setattr(agents, "complete", _fail)
    turns = [{"query": "Какой номер у цеха?", "answer": "Смена длится 8 часов.", "document_names": ["charter.txt"]}]
    assert agents.select_agent("Как зовут мастера?", turns) == []
    assert agents.select_agent("Какой номер у склада?", turns) == turns
    work = agents.select_agent("Сколько она длится?", turns)
    assert work == turns
    assert agents.clarify_agent("Сколько она длится?", work) == "Какой номер у цеха? Сколько она длится?"
    assert agents.clarify_agent("Какой номер у склада?", work) == "Какой номер у склада?"


def test_select_new_meaning(monkeypatch):
    monkeypatch.setattr(agents, "complete", _fail)
    turns = [{"query": "Какой номер у цеха?", "answer": "4", "document_names": []}]
    assert agents.select_agent("Какое давление у насоса?", turns) == []
    assert agents.clarify_agent("Какое давление у насоса?", []) == "Какое давление у насоса?"
