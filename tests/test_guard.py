import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = json.loads((ROOT / "tests" / "eval" / "questions.json").read_text(encoding="utf-8"))
SOURCES = [path for path in (ROOT / "src").rglob("*") if path.suffix in {".py", ".html", ".js"}]
EDGE = "0-9A-Za-zА-Яа-яЁё_"


def _needles():
    found = set()
    for item in QUESTIONS:
        for fact in item.get("facts", []):
            for option in fact if isinstance(fact, list) else [fact]:
                if len(option) >= 4:
                    found.add(option)
        for phrase in item.get("evidence", []) + item.get("evidence_any", []) + item.get("together", []):
            if len(phrase) >= 4:
                found.add(phrase)
        for token in re.findall(r"[0-9A-Za-zА-Яа-яЁё_.-]+", item["query"]):
            token = token.strip(".-")
            if len(token) >= 3 and sum(ch.isupper() for ch in token) >= 2:
                found.add(token)
        if item.get("document") not in (None, "*"):
            found.add(Path(item["document"]).stem)
    return sorted(found)


def test_src_has_no_document_strings():
    bodies = {path: path.read_text(encoding="utf-8") for path in SOURCES}
    hits = []
    for needle in _needles():
        flags = 0 if needle.upper() == needle else re.IGNORECASE
        pattern = re.compile(f"(?<![{EDGE}]){re.escape(needle)}(?![{EDGE}])", flags)
        for path, body in bodies.items():
            if pattern.search(body):
                hits.append(f"{path.relative_to(ROOT)}: {needle}")
    assert hits == []


def test_src_does_not_read_test_data():
    for path in SOURCES:
        body = path.read_text(encoding="utf-8")
        assert "questions.json" not in body
        assert "user_queries" not in body
