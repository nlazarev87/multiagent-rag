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

    def fake(query, limit, document_names=None):
        seen.append((query, limit, document_names))
        return []

    monkeypatch.setattr(agents, "search_chunks", fake)
    agents.search_agent("номер цеха", ["pump.md", "note.txt"])
    agents.search_agent("номер цеха", [])
    assert seen == [
        ("номер цеха", 4, ["pump.md", "note.txt"]),
        ("номер цеха", 4, None),
    ]
