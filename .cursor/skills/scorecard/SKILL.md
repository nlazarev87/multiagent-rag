---
name: scorecard
description: Runs live quality metrics for the multi-agent RAG pipeline (select, clarify, search, ingest, check, coord, answer, e2e, univ, floors, GATE). Use after changing src, config, or prompts, before a PR, or when the user mentions scorecard, floors, holdout, hit@1, MRR, or component metrics.
---

# Scorecard

Python: `C:\Users\Home\AppData\Local\Programs\Python\Python312\python.exe`. `PYTHONPATH=src` is set by `pytest.ini` and by `tests/eval/scorecard.py`.

`tests/test_floors.py` only diffs `tests/eval/floors.json` vs `tests/eval/last.json`. After a code change, re-run `scorecard.py`. Stale `last.json` can stay green while the code got worse.

## Commands

```text
python tests/eval/scorecard.py --nodes ingest,search
python tests/eval/scorecard.py --nodes fast
python tests/eval/scorecard.py --nodes all --holdout
python scripts/release_check.py
```

`--nodes fast` = ingest, select, clarify, search, check, coord, univ (no 1.5B).
`--nodes all --holdout` = fast + answer + e2e (dev, dialog, holdout) on Qwen2.5-1.5B. Tens of minutes on CPU.

Also run the matching pytest files. Knowledge/routing changes: `tests/test_universality.py` and `tests/test_guard.py`.

`--write-floors` / `--raise-floors` only if the user asked and GATE is OK. Do not put document facts in `src/` to lift a card.

## File to node

| Change | Nodes |
| --- | --- |
| `src/ingest.py` | ingest, search |
| `src/store.py` | search, univ |
| `src/agents.py` | select, clarify, search, check (answer if the prompt/answer path moved) |
| `src/coordinator.py` | coord |
| `src/llm.py` | `tests/test_llm.py`; answer before a PR |
| `config/`, `data/prompts/` | univ + the node whose behavior changed |
| `tests/eval/questions.json` | search; answer/e2e before a PR |

Unsure which node → `--nodes fast`.

## Cards (already measured)

- ingest: `ingest_overview_complete`, `ingest_table_intro_group`, `ingest_version`
- select / clarify / search (`hit4`, `hit1`, `mrr`, overview, together) / check / coord
- univ: `code_knowledge_leakage` (must be 0), `document_swap_pass_rate` (must be 1), `citation_coverage`, `config_only_change_success`
- slow: `answer_facts_dev`, `answer_cite_dev`, `answer_by_type_*`, `e2e_dev`, `e2e_holdout`, `e2e_dialog`

GATE FAIL on a card → fix that node. Leakage or failed swap: do not fix with knowledge in code.

## Report

After a run, show touched keys as `now / floor / room` (and hits/n when present). Do not say only "tests passed".
