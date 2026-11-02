# Issue #1 — детальный план (эталон формата)

## Цель
Заменить `_merge_last` (пишет только улучшения) на `_measure_and_merge` (пишет всегда) + per-question в last.json.

## Файлы

### tests/eval/scorecard.py
- measure_search → per_question[].
- _merge_last → _measure_and_merge, всегда перезаписывает last.json, старый лучший — best.json.

Пример per_question:
```json
{"id":"impus-flow-count","list":"dev","hit1_rank":2,"mrr_contribution":0.5,"doc_p4":1.0,"slot_kind":["table","table","text","overview"],"triggered_heuristics":["inject_rare"],"features_active":["inject_rare","focus","scope"],"stage_lost":null,"total_duration_ms":87}
```

### tests/test_floors.py
- Вызывает measure_search заново.
- Падает при падении hit1_dev/mrr_dev/hit4_holdout.
- Проверяет n == len(questions).

### tests/eval/floors.json
- Перегенерировать с 81 вопроса. Удалить старые (22). Добавить n_questions: 81.

## Набросок

```python
def measure_search(store, questions, limit=4):
    per_question = []
    for q in questions:
        chunks = store.search_chunks(q["query"], limit=limit)
        rank = _find_answer_rank(q["evidence"], chunks)
        per_question.append({
            "id": q["id"], "list": q["list"], "hit1_rank": rank,
            "mrr_contribution": (1.0/rank) if rank else 0.0,
            "doc_p4": _doc_p4(q, chunks),
            "slot_kind": [c.get("kind") for c in chunks],
            "triggered_heuristics": _heuristics_fired(q, chunks),
            "features_active": _active_features(),
        })
    return {
        "search_hit1_dev": _aggregate(per_question,"dev",lambda r: r["hit1_rank"]==1),
        "search_mrr_dev": _mean_mrr(per_question,"dev"),
        "search_hit4_holdout": _aggregate(per_question,"holdout",lambda r: r["hit1_rank"] is not None),
        "per_question": per_question,
    }

def _measure_and_merge(store, questions):
    result = measure_search(store, questions)
    _write_json("tests/eval/last.json", result)
    best = _read_json("tests/eval/best.json") or {}
    if result["search_mrr_dev"] > best.get("search_mrr_dev", 0):
        _write_json("tests/eval/best.json", result)
    return result
```

## AC
- [ ] per_question[] в last.json.
- [ ] Искусственное -1% роняет тест.
- [ ] n_questions: 81, падение при изменении.
- [ ] git diff last.json виден.

## НЕ входит
Wave 0 #2, #3, #4, #5.

## Проверка
```bash
python tests/eval/scorecard.py
jq '.per_question | length' tests/eval/last.json   # 81
pytest tests/test_floors_recompute.py -v
pytest -m "not slow and not holdout" -q
```
