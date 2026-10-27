import re
import sys
from pathlib import Path

EVAL = Path(__file__).resolve().parent / "eval"
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

import universality


def test_code_knowledge_leakage():
    hits = universality.src_hits()
    assert hits == [], "src содержит факты корпуса; чинить знаниями в коде нельзя\n" + "\n".join(hits)


def test_document_swap_pass_rate():
    measured = universality.measure_swap()
    assert measured["swap"]["now"] == 1.0, "смена корпуса без правок src должна отвечать по своему тексту и отказываться вне него"
    assert measured["citation"]["now"] >= 1.0


def test_citation_coverage():
    import agents

    chunk = {
        "text": "Насос имеет обозначение Н-12. Рабочее давление равно 6 бар.",
        "document_name": "pump.md",
        "section": "",
    }
    answer = "Насос имеет обозначение Н-12 [1]."
    assert re.search(r"\[\d+\]", answer)
    verdict = agents.check_agent(answer, [chunk], "Какое обозначение у насоса?", lambda _term: True)
    assert verdict["status"] == agents.CONFIRMED


def test_config_only_change_success():
    measured = universality.measure_config_only()
    assert measured["now"] == 1.0, "фильтр metadata или lexicon должен менять поведение без правок src"
