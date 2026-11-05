import agents


def test_from_overview_sum():
    """#132: на «сколько» ответ берётся из «Сумма столбца»."""
    chunks = [
        {
            "id": "c1",
            "text": "Сумма столбца «count»: 8. Количество строк: 2.",
            "kind": "overview_numeric",
        }
    ]
    assert agents._from_overview("Сколько всего?", chunks) == "8 [1]."


def test_from_overview_sum_no_numeric():
    """#132: без числовой строки «сколько» не отвечает текстом обзора."""
    chunks = [{"id": "c1", "text": "Разных значений в столбце «name»: 2.", "kind": "overview"}]
    assert agents._from_overview("Сколько всего?", chunks) is None


def test_from_overview_count_prefers_distinct_over_sum():
    """#132: «сколько» берёт «Разных значений», а не сумму столбца «№»."""
    chunks = [
        {"id": "c0", "text": "Сумма столбца «№»: 36. Количество строк: 8.", "kind": "overview_numeric"},
        {
            "id": "c1",
            "text": "Разных значений в столбце «ИД потока»: 4. Список: A, B, C, D.",
            "kind": "overview",
        },
    ]
    assert agents._from_overview("Сколько потоков?", chunks) == "4 ИД потока [2]."


def test_from_overview_count_distinct_outranks_count():
    """#132: «сколько» берёт «Разных значений», а не «Количество строк»."""
    chunks = [
        {"id": "c0", "text": "Количество строк: 8.", "kind": "overview_count"},
        {
            "id": "c1",
            "text": "Разных значений в столбце «ИД потока»: 4. Список: A, B, C, D.",
            "kind": "overview",
        },
    ]
    assert agents._from_overview("Сколько потоков?", chunks) == "4 ИД потока [2]."


def test_from_overview_list_question_returns_list_not_sum():
    """#132: без «сколько» сумма не подменяет список и не отвечает на «какая сумма»."""
    chunks = [
        {"id": "c0", "text": "Сумма столбца «№»: 36.", "kind": "overview_numeric"},
        {
            "id": "c1",
            "text": "Разных значений в столбце «ИД потока»: 4. Список: A, B.",
            "kind": "overview",
        },
    ]
    assert agents._from_overview("Какие потоки?", chunks) == "A, B [2]."
    assert agents._from_overview("Какая сумма?", chunks) is None


def test_from_overview_count_question_with_digit_does_not_prefer_distinct():
    """#132: «Сколько залов из 3?» не подменяется обзором и не берёт сумму 36."""
    halls = {
        "id": "c1",
        "text": (
            "Библиотека > Залы\n"
            "Разных значений в столбце «Зал»: 3. Список: Читальный, Детский, Архивный."
        ),
        "kind": "overview",
    }
    summed = {"id": "c0", "text": "Сумма столбца «№»: 36.", "kind": "overview_numeric"}
    assert agents._from_overview("Сколько залов из 3?", [summed, halls]) is None
    assert agents._from_overview("Сколько залов из 3?", [summed]) is None


def test_from_overview_count_fallback_when_no_sum():
    """#132: без «Разных значений» и «Суммы» — «Количество строк» как запасной ответ."""
    chunks = [
        {"id": "c0", "text": "Количество строк: 8.", "kind": "overview_count"},
    ]
    assert agents._from_overview("Сколько всего?", chunks) == "8 [1]."
