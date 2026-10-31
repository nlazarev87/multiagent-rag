import agents
import store


def test_search_agent_calls_store_every_time(monkeypatch):
    seen = []

    def fake(query, limit, document_names=None):
        seen.append((query, limit, document_names))
        return [{"text": query, "document_name": "a.txt", "chunk_index": 0}]

    monkeypatch.setattr(agents, "search_chunks", fake)
    agents.search_agent("номер цеха")
    agents.search_agent("номер цеха")
    assert seen == [("номер цеха", 4), ("номер цеха", 4)]


def test_scope_follows_filename_stems():
    index = {"vocabulary": {"тестовое задание.txt": set(), "прочее.txt": set()}}
    assert store.scope(index, "какие проверки выполняются в тестовом задании") == ["тестовое задание.txt"]


def test_scope_follows_a_sign_inside_the_file():
    index = {"vocabulary": {"note.txt": {"npp", "exs"}, "other.txt": {"поток"}}}
    assert store.scope(index, "Сколько потоков между NPP ExS") == ["note.txt"]

def test_search_agent_passes_document_names(monkeypatch):
    seen = []

    def fake(*args):
        seen.append(args)
        return []

    monkeypatch.setattr(agents, "search_chunks", fake)
    agents.search_agent("она", ["charter.txt"])
    agents.search_agent("номер", [])
    agents.search_agent("номер")
    assert seen == [
        ("она", 4, ["charter.txt"]),
        ("номер", 4),
        ("номер", 4),
    ]
