import json
import re
from pathlib import Path

import pytest

import dialog
import store
from agents import CONFIRMED
from coordinator import run
from ingest import ingest_dir

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "data" / "inbox"
QUESTIONS = json.loads((ROOT / "tests" / "eval" / "questions.json").read_text(encoding="utf-8"))
EDGE = "0-9a-zа-я_"


def _flat(text):
    return " ".join(text.lower().replace("ё", "е").split())


def _has(fact, answer):
    flat = _flat(fact)
    tail = f"(?![{EDGE}])" if flat[-1].isdigit() else ""
    return re.search(f"(?<![{EDGE}]){re.escape(flat)}{tail}", answer) is not None


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    if not any(INBOX.glob("*.docx")):
        pytest.skip("В data/inbox нет документов")
    saved = store.CHROMA
    store.CHROMA = tmp_path_factory.mktemp("chroma")
    store.reset()
    dialog.reset()
    store.upsert_chunks(ingest_dir(INBOX))
    yield
    store.CHROMA = saved
    store.reset()


def problems(item):
    result = run(item["query"], f"eval-{item['id']}")
    answer = _flat(result["answer"])
    found = []
    expected = item.get("status", CONFIRMED)
    if result["status"] != expected:
        found.append(f"статус {result['status']}")
    for fact in item.get("facts", []):
        options = fact if isinstance(fact, list) else [fact]
        if not any(_has(option, answer) for option in options):
            found.append(f"нет «{options[0]}»")
    for fact in item.get("forbidden", []):
        if _flat(fact) in answer:
            found.append(f"лишнее «{fact}»")
    if item.get("starts") and not answer.startswith(_flat(item["starts"])):
        found.append(f"не начинается с «{item['starts']}»")
    if expected == CONFIRMED and item.get("document") not in (None, "*") and item["document"] not in result["document_names"]:
        found.append("не тот документ")
    return found, result["answer"]


def _ids(split):
    return [item for item in QUESTIONS if item["split"] == split]


@pytest.mark.slow
@pytest.mark.parametrize("item", _ids("dev"), ids=lambda item: item["id"])
def test_dev_answer(base, item):
    found, answer = problems(item)
    assert not found, f"{found}: {answer}"


@pytest.mark.slow
@pytest.mark.holdout
@pytest.mark.parametrize("item", _ids("holdout"), ids=lambda item: item["id"])
def test_holdout_answer(base, item):
    found, answer = problems(item)
    assert not found, f"{found}: {answer}"
