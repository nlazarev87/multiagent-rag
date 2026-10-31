import agents


def test_search_agent_calls_store_every_time(monkeypatch):
    seen = []

    def fake(query, limit):
        seen.append((query, limit))
        return [{"text": query, "document_name": "a.txt", "chunk_index": 0}]

    monkeypatch.setattr(agents, "search_chunks", fake)
    agents.search_agent("номер цеха")
    agents.search_agent("номер цеха")
    assert seen == [("номер цеха", 4), ("номер цеха", 4)]


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
