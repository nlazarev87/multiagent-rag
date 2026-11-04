# Пороги и константы

Колонка Config — вынесено ли в config/runtime.json.

## store.py
| Порог | Значение | Тест | Config |
|---|---|---|---|
| K1 | 1.5 | test_store::test_k1_b_from_runtime | ✅ |
| B | 0.75 | test_store::test_k1_b_defaults_when_missing | ✅ |
| CANDIDATES | 30 | test_store | ✅ |
| RRF | 5 | test_store | ✅ |
| search_limit | 4 | test_store | ✅ |
| rare word len | ≥5 | test_store::test_rare | ❌ |
| rare files max | 2 | test_store::test_rare | ❌ |
| focus min words | ≥2 длиной>3 | test_store::test_focus | ❌ |
| scope word len | ≥5 | test_store::test_scope | ❌ |
| scope words count | 2 | test_store::test_scope | ❌ |
| contexts scan | limit*3=12 | test_store::test_contexts | ❌ Wave 4 |
| context tokens | 260 | test_store::test_render | ✅ |
| chroma_ms | 10000 | test_timeouts | ✅ |

## agents.py
| Порог | Значение | Тест | Config |
|---|---|---|---|
| select: history words | 2 | test_agents::test_select | ❌ |
| select: word len | >3 | test_agents::test_select | ❌ |
| cover_latin: len | ≥3 | test_agents::test_cover_latin | ❌ |
| check: word len | ≥5 | test_answer | ❌ |
| check: sources max | 4 | test_answer::test_sources | ❌ |
| check: 3× | 3.0 | test_answer::test_hallucination | ❌ |

## coordinator.py
| Порог | Значение | Тест | Config |
|---|---|---|---|
| attempts max | 2 | test_coordinator | ✅ |
| graph_ms | 120000 | test_timeouts | ✅ |
| node_ms | 60000 | не используется: короче llm_ms (90000), на answer сработает раньше модели. Wave 2 follow-up (per-node или не короче llm_ms) | ✅ |
| retry keyword | «документ» | test_coordinator | ❌ |

## ingest.py
| Порог | Значение | Тест | Config |
|---|---|---|---|
| tokens | 250 | test_ingest | ✅ |
| overlap | 40 | test_ingest | ✅ |
| intro | 120 | test_ingest::test_intro | ✅ |

## ingest

| Порог | Значение | Смысл | Config |
|---|---|---|---|
| `max_file_size_mb` | 50 | файл больше — пропускается с `file_too_large` | ✅ `runtime.json` |
| `max_chunks_per_doc` | 5000 | больше кусков — первые 5000 + warning | ✅ `runtime.json` |

## llm.py
| Порог | Значение | Config |
|---|---|---|
| prompt_tokens | 1500 | ✅ |
| max_tokens | 200 | ✅ |
| n_ctx | 4096 | ✅ |
| llm_ms | 90000 | ✅ |
| retries | 1 | ✅ |

## audit

| Порог | Значение | Смысл | Config |
|---|---|---|---|
| `rotation_threshold_mb` | 100 | при превышении `log.sqlite` архивируется | ✅ `runtime.json` |
| `trace_json` | true | писать полный trace в audit | ✅ `runtime.json` |

## Дубли (Wave 6)
- «код»: store._names, agents._codes, agents._anchors.
- «первые 5 букв»: store, agents, coordinator.
- «фраза отказа»: agents.py + api.py.
- «Разных значений»: ingest.py + agents.py.
