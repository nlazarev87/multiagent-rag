import os
from pathlib import Path

import pytest

os.environ["LLM_MODEL_PATH"] = str(
    Path(__file__).resolve().parents[1] / "data" / "models" / "qwen2.5-1.5b-instruct-q4_k_m.gguf"
)


@pytest.fixture(autouse=True)
def _reset_query_rate_limit():
    """#147: лимит /query живёт в памяти процесса. Перед тестом счётчик пустой."""
    import sys
    module = sys.modules.get("api")
    limiter = getattr(module, "limiter", None)
    if limiter is not None:
        limiter.reset()
    yield
