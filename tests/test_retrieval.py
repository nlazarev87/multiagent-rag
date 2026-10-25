import json
from pathlib import Path

import pytest

import store
from ingest import ingest_dir

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "data" / "inbox"
QUESTIONS = json.loads((ROOT / "tests" / "eval" / "questions.json").read_text(encoding="utf-8"))


def _flat(text):
    return " ".join(text.lower().replace("ё", "е").split())


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    if not any(INBOX.glob("*.docx")):
        pytest.skip("В data/inbox нет документов")
    saved = store.CHROMA
    store.CHROMA = tmp_path_factory.mktemp("chroma")
    store.reset()
    store.upsert_chunks(ingest_dir(INBOX))
    yield
    store.CHROMA = saved
    store.reset()


def found(item):
    chunks = store.search_chunks(item["query"], 4)
    if item.get("document") not in (None, "*"):
        chunks = [chunk for chunk in chunks if chunk["document_name"] == item["document"]]
    texts = [_flat(chunk["text"]) for chunk in chunks]
    ok = all(any(_flat(phrase) in text for text in texts) for phrase in item.get("evidence", []))
    if item.get("evidence_any"):
        ok = ok and any(_flat(phrase) in text for phrase in item["evidence_any"] for text in texts)
    if item.get("together"):
        ok = ok and any(all(_flat(phrase) in text for phrase in item["together"]) for text in texts)
    return ok


def cases(split):
    keys = ("evidence", "evidence_any", "together")
    return [item for item in QUESTIONS if item["split"] == split and any(item.get(key) for key in keys)]


@pytest.mark.parametrize("item", cases("dev"), ids=lambda item: item["id"])
def test_dev_retrieval(base, item):
    assert found(item)


@pytest.mark.holdout
def test_holdout_retrieval(base):
    items = cases("holdout")
    missed = [item["id"] for item in items if not found(item)]
    assert len(missed) <= 0.1 * len(items), missed
