import pytest
from pathlib import Path

import socket

from ingest import split_chunks

pytestmark = pytest.mark.skipif(
    not (Path(__file__).resolve().parent.parent / "data" / "models" / "multilingual-e5-small").exists(),
    reason="model not available in CI (data/models/multilingual-e5-small)",
)


def test_split_does_not_open_network(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    chunks = split_chunks("Цех имеет номер 4.", "charter.txt")
    assert chunks[0]["document_name"] == "charter.txt"
    assert "4" in chunks[0]["text"]
