import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "tests" / "eval"
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

import universality

SOURCES = universality.src_files()


def test_src_has_no_document_strings():
    assert universality.src_hits() == []


def test_src_does_not_read_test_data():
    for path in SOURCES:
        body = path.read_text(encoding="utf-8")
        assert "questions.json" not in body
        assert "user_queries" not in body
