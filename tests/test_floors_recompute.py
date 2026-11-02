"""Wave 0 #113: свежий прогон measure_search должен пройти все floors.

Не читает last.json. Считает заново. Падает, если что-то упало.
"""
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests" / "eval"))

import scorecard as _sc  # noqa: E402


FLOORS_PATH = ROOT / "tests" / "eval" / "floors.json"
QUESTIONS_PATH = ROOT / "tests" / "eval" / "questions.json"


def _floors():
    with open(FLOORS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _searchable_questions():
    with open(QUESTIONS_PATH, encoding="utf-8") as f:
        qs = json.load(f)
    if isinstance(qs, dict):
        qs = qs.get("questions") or qs.get("items") or []
    return [q for q in qs if q.get("evidence") or q.get("evidence_any") or q.get("together")]


@pytest.fixture(scope="module")
def fresh_run():
    cards = _sc.measure_search()
    if not cards:
        pytest.skip("measure_search returned {} — no corpus in data/inbox")
    return cards


@pytest.fixture(scope="module")
def floors():
    return _floors()


def test_per_question_present(fresh_run):
    assert "_per_question" in fresh_run, "measure_search must return _per_question"
    pq = fresh_run["_per_question"]
    assert isinstance(pq, list) and len(pq) > 0
    required = {"id", "split", "best_rank", "is_hit1", "is_hit4",
                "mrr_contribution", "search_latency_ms", "ok"}
    missing = required - set(pq[0].keys())
    assert not missing, f"per_question missing fields: {missing}"


def test_n_questions_matches_floors(fresh_run, floors):
    pq = fresh_run["_per_question"]
    n_dev = sum(1 for q in pq if q["split"] == "dev")
    n_hold = sum(1 for q in pq if q["split"] == "holdout")
    assert n_dev == floors.get("n_questions_dev"), (
        f"n_dev mismatch: measured {n_dev}, floors {floors.get('n_questions_dev')}. "
        f"Число вопросов изменилось — обнови floors.json отдельным PR."
    )
    assert n_hold == floors.get("n_questions_holdout"), (
        f"n_holdout mismatch: measured {n_hold}, floors {floors.get('n_questions_holdout')}."
    )


@pytest.mark.parametrize("metric", [
    "search_hit4_dev",
    "search_hit1_dev",
    "search_mrr_dev",
    "search_hit4_holdout",
])
def test_metric_above_floor(fresh_run, floors, metric):
    card = fresh_run.get(metric)
    assert card is not None, f"metric {metric} not in measure_search output"
    now = card["now"]
    floor = floors[metric]["floor"]
    fails = fresh_run["_per_question"]
    detail = [
        q["id"] for q in fails
        if q["split"] == metric.split("_")[-1] and not q["is_hit1"]
    ][:10]
    assert now >= floor, (
        f"{metric} = {now:.4f} < floor {floor:.4f}. "
        f"Промахи hit1 (первые 10): {detail}. "
        f"Подробности: tests/eval/last.json → _per_question"
    )
