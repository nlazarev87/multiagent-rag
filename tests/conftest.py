import os
from pathlib import Path

import pytest

os.environ["LLM_MODEL_PATH"] = str(
    Path(__file__).resolve().parents[1] / "data" / "models" / "qwen2.5-1.5b-instruct-q4_k_m.gguf"
)


def pytest_configure(config):
    """Обход ограничения песочницы Windows: os.mkdir(..., mode=0o700) создаёт
    каталог, который затем нельзя просканировать (os.scandir падает с
    PermissionError). pytest использует mode=0o700 для своих tmp_path-каталогов,
    из-за чего все тесты на tmp_path падали на этапе фикстуры. Переписываем
    только 0o700 на 0o777 внутри тестового процесса: код приложения mode=0o700
    не использует, а 0o777 полностью рабочий."""
    real_mkdir = os.mkdir

    def mkdir(path, mode=0o777, *args, **kwargs):
        if mode == 0o700:
            mode = 0o777
        return real_mkdir(path, mode, *args, **kwargs)

    os.mkdir = mkdir


@pytest.fixture(autouse=True)
def _reset_query_rate_limit():
    """#147: лимит /query живёт в памяти процесса. Перед тестом счётчик пустой."""
    import sys

    module = sys.modules.get("api")
    limiter = getattr(module, "limiter", None)
    if limiter is not None:
        limiter.reset()
    yield
