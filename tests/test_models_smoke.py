"""Смоук загрузки QVikhr и RusMind через реальный llm.complete/count_tokens.

Маркирован slow: грузит модели на CPU (гигабайты ОЗУ) и в быстрый набор не входит.
Каждая модель грузится в ОТДЕЛЬНОМ процессе, чтобы освободить RAM перед следующей.

Проверяем не только Llama.create_chat_completion, а публичный путь llm.complete()
и llm.count_tokens(), то есть и chat-template: для QVikhr это noreasoning
(шаблон с /no_think), для RusMind — Gemma4 на llama-cpp-python==0.3.36.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "data" / "models"

SMOKE_CASES = [
    ("qvikhr", "QVikhr-3-1.7B-Instruction-noreasoning-Q4_K_M.gguf"),
    ("rusmind", "RusMind-Momentum-4.7-Q4_K_M.gguf"),
]


def _run_model(path: Path) -> dict:
    """Загрузить модель в отдельном процессе и прогнать complete + count_tokens."""
    script = r'''
import json
import time

try:
    import llm

    system = "Ты — ассистент по технической документации. Отвечай кратко и по делу."
    user = "Сколько будет два плюс два? Ответь одним словом."
    examples = [("Что такое насос?", "Насос — машина для перекачки жидкости.")]

    t0 = time.time()
    llm.load()
    t1 = time.time()
    answer = llm.complete(system, user, examples=examples, max_tokens=32)
    t2 = time.time()
    tokens = llm.count_tokens(system + " " + user)
    print(json.dumps({
        "ok": True,
        "load_s": round(t1 - t0, 2),
        "answer_s": round(t2 - t1, 2),
        "tokens": tokens,
        "answer": answer[:200],
    }))
except Exception as exc:  # noqa: BLE001 — фиксируем точную ошибку загрузки/генерации
    print(json.dumps({"ok": False, "error": repr(exc)}))
'''
    env = dict(os.environ)
    env["LLM_MODEL_PATH"] = str(path)
    env["PYTHONPATH"] = str(ROOT / "src")
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
    )
    lines = [line for line in (proc.stdout or "").strip().splitlines() if line.strip()]
    if proc.returncode != 0 or not lines:
        return {"ok": False, "error": (proc.stderr or "").strip()[:800]}
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return {"ok": False, "error": f"не JSON: {lines[-1][:300]}"}


@pytest.mark.slow
@pytest.mark.parametrize("model_id, filename", SMOKE_CASES, ids=["qvikhr", "rusmind"])
def test_model_loads_and_answers(model_id, filename):
    path = MODELS / filename
    if not path.exists():
        pytest.skip(f"{filename} не скачан (data/models)")
    result = _run_model(path)
    assert result.get("ok"), f"{model_id}: {result.get('error')}"
    assert result["tokens"] > 0, f"{model_id}: count_tokens вернул {result['tokens']}"
    assert result["answer"].strip(), f"{model_id}: пустой ответ"
    print(
        f"[smoke:{model_id}] load={result['load_s']}s "
        f"answer={result['answer_s']}s tokens={result['tokens']}"
    )
