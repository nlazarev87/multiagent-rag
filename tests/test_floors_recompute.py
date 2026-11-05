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
    required = {
        "id",
        "split",
        "best_rank",
        "is_hit1",
        "is_hit4",
        "mrr_contribution",
        "search_latency_ms",
        "ok",
    }
    missing = required - set(pq[0].keys())
    assert not missing, f"per_question missing fields: {missing}"


def test_per_question_has_overview_columns(fresh_run):
    pq = fresh_run.get("_per_question", [])
    assert pq, "no per_question entries"
    assert (
        "overview_columns_in_slots" in pq[0]
    ), "per_question missing overview_columns_in_slots field"
    for q in pq:
        val = q["overview_columns_in_slots"]
        assert isinstance(
            val, list
        ), f"{q['id']}: overview_columns_in_slots is not a list ({type(val).__name__})"
        for item in val:
            assert isinstance(item, str), f"{q['id']}: overview_columns_in_slots item is not str"


def test_per_question_has_features_active(fresh_run):
    pq = fresh_run.get("_per_question", [])
    assert pq, "no per_question entries"
    assert "features_active" in pq[0], "per_question missing features_active"
    for q in pq:
        assert isinstance(q["features_active"], list), f"{q['id']}: features_active is not a list"
        for name in q["features_active"]:
            assert isinstance(name, str), f"{q['id']}: features_active item is not str"


def test_per_question_has_total_duration(fresh_run):
    pq = fresh_run.get("_per_question", [])
    assert pq, "no per_question entries"
    assert "total_duration_ms" in pq[0], "per_question missing total_duration_ms"
    for question in pq:
        value = question["total_duration_ms"]
        assert isinstance(
            value, (int, float)
        ), f"{question['id']}: total_duration_ms is not numeric ({type(value).__name__})"
        assert value >= 0, f"{question['id']}: total_duration_ms must be non-negative"


def test_per_question_has_staged_fields(fresh_run):
    pq = fresh_run.get("_per_question", [])
    assert pq, "no per_question entries"
    required = {
        "candidate_hit",
        "fusion_hit_12",
        "fusion_hit_4",
        "stage_lost",
        "raw_lexical_rank",
        "raw_dense_rank",
        "ranked_rank",
    }
    missing = required - set(pq[0].keys())
    assert not missing, f"per_question missing staged fields: {missing}"


def test_stage_lost_values(fresh_run):
    pq = fresh_run.get("_per_question", [])
    valid = {None, "retrieval", "filter", "contexts"}
    for q in pq:
        assert q["stage_lost"] in valid, f"invalid stage_lost {q['stage_lost']!r} for {q['id']}"


def test_n_questions_matches_floors(fresh_run, floors):
    pq = fresh_run["_per_question"]
    n_dev = sum(1 for q in pq if q["split"] == "dev")
    n_hold = sum(1 for q in pq if q["split"] == "holdout")
    assert n_dev == floors.get("n_questions_dev"), (
        f"n_dev mismatch: measured {n_dev}, floors {floors.get('n_questions_dev')}. "
        f"Число вопросов изменилось — обнови floors.json отдельным PR."
    )
    assert n_hold == floors.get(
        "n_questions_holdout"
    ), f"n_holdout mismatch: measured {n_hold}, floors {floors.get('n_questions_holdout')}."


@pytest.mark.parametrize(
    "metric",
    [
        "search_hit4_dev",
        "search_hit1_dev",
        "search_mrr_dev",
        "search_hit4_holdout",
        "search_hit1_holdout",
        "search_mrr_holdout",
    ],
)
def test_metric_above_floor(fresh_run, floors, metric):
    card = fresh_run.get(metric)
    assert card is not None, f"metric {metric} not in measure_search output"
    now = card["now"]
    floor = floors[metric]["floor"]
    fails = fresh_run["_per_question"]
    detail = [q["id"] for q in fails if q["split"] == metric.split("_")[-1] and not q["is_hit1"]][
        :10
    ]
    assert now >= floor, (
        f"{metric} = {now:.4f} < floor {floor:.4f}. "
        f"Промахи hit1 (первые 10): {detail}. "
        f"Подробности: tests/eval/last.json → _per_question"
    )


@pytest.mark.parametrize(
    "metric",
    [
        "search_retrieval_recall",
        "search_fusion_recall_at_30",
        "search_fusion_recall_at_12",
        "search_fusion_recall_at_4",
    ],
)
def test_staged_metric_above_floor(fresh_run, floors, metric):
    card = fresh_run.get(metric)
    assert card is not None, f"metric {metric} not in output"
    assert (
        card["now"] >= floors[metric]["floor"]
    ), f"{metric} = {card['now']:.4f} < floor {floors[metric]['floor']:.4f}"


def test_per_question_has_five_boolean_levels(fresh_run):
    pq = fresh_run.get("_per_question", [])
    assert pq, "no per_question entries"
    required = {"in_retrieval", "in_ranked_30", "in_ranked_12", "in_ranked_4", "in_slots"}
    missing = required - set(pq[0].keys())
    assert not missing, f"per_question missing boolean levels: {missing}"


def test_invariants(fresh_run):
    pq = fresh_run.get("_per_question", [])
    for q in pq:
        assert (
            q["in_slots"] or not q["in_ranked_4"]
        ), f"{q['id']}: in_ranked_4={q['in_ranked_4']} but in_slots={q['in_slots']} — impossible"
        assert (not q["in_ranked_30"]) or q[
            "in_retrieval"
        ], f"{q['id']}: in_ranked_30 but not in_retrieval — fuse/meta lost it"
        assert (not q["in_ranked_12"]) or q[
            "in_ranked_30"
        ], f"{q['id']}: in_ranked_12 but not in_ranked_30"
        assert (not q["in_ranked_4"]) or q[
            "in_ranked_12"
        ], f"{q['id']}: in_ranked_4 but not in_ranked_12"
