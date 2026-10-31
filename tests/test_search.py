import agents


def test_search_agent_calls_store_every_time(monkeypatch):
    seen = []

    def fake(query, limit, document_names=None):
        seen.append((query, limit, document_names))
        return [{"text": query, "document_name": "a.txt", "chunk_index": 0}]

    monkeypatch.setattr(agents, "search_chunks", fake)
    agents.search_agent("номер цеха")
    agents.search_agent("номер цеха")
    agents.search_agent("сколько она длится", ["charter.txt"])
    assert seen == [
        ("номер цеха", 4, None),
        ("номер цеха", 4, None),
        ("сколько она длится", 4, ["charter.txt"]),
    ]
