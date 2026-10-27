import agents

PUMP = {"text": "Насос > Характеристики\nРабочее давление: 6 бар\nГод выпуска: 2019", "document_name": "pump.md", "section": "Насос > Характеристики"}
SHOP = {"text": "Цех имеет номер 4. Мастер цеха — Иванов.", "document_name": "charter.txt", "section": ""}


def _words(text):
    return len(text.split())


def test_answer_refuses_empty_chunks():
    assert agents.answer_agent("цвет", "цвет насоса", [], []) == agents.NO_ANSWER


def test_answer_copies_overview_list_without_model(monkeypatch):
    monkeypatch.setattr(agents, "complete", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("complete")))
    halls = {
        "text": "Библиотека > Залы\nРазных значений в столбце «Зал»: 3. Список: Читальный, Детский, Архивный.",
        "document_name": "library.txt",
    }
    extra = {"text": "В залах соблюдается тишина.", "document_name": "rules.txt"}
    assert agents.answer_agent("Какие залы есть в библиотеке?", "Какие залы есть в библиотеке?", [halls, extra], []) == "Читальный, Детский, Архивный [1]."
    assert agents.answer_agent("Сколько залов в библиотеке?", "Сколько залов в библиотеке?", [halls], []) == "3 значений [1]."
    size_calls = []
    monkeypatch.setattr(agents, "count_tokens", _words)
    monkeypatch.setattr(agents, "complete", lambda *_args, **_kwargs: size_calls.append(1) or "Около 1 Мб [1].")
    assert "1 Мб" in agents.answer_agent("Сколько данных в потоке X_9.2?", "Сколько данных в потоке X_9.2?", [halls], [])
    assert size_calls == [1]
    size_calls = []
    monkeypatch.setattr(agents, "complete", lambda *_args, **_kwargs: size_calls.append(1) or "Около 1 Мб [1].")
    assert "1 Мб" in agents.answer_agent("Сколько данных в потоке X_9.2?", "Сколько данных в потоке X_9.2?", [halls], [])
    assert size_calls == [1]
    glossary = {
        "text": "Термины\nТаблица 1 – Сокращения\nРазных значений в столбце «Термин»: 3. Список: АО, ИС, ПО.",
        "document_name": "terms.txt",
    }
    calls = []
    monkeypatch.setattr(agents, "complete", lambda *_args, **_kwargs: calls.append(1) or "В периметре три организации [1].")
    perimeter = {"text": "Организационный периметр\nТаблица 2\nАО «Север»: полный\nАО «Юг»: полный", "document_name": "orgs.txt"}
    agents.answer_agent("Какие организации входят в периметр?", "Какие организации входят в периметр?", [glossary, perimeter], [])
    assert calls == [1]


def test_overview_scores_column_label_not_other_cells(monkeypatch):
    mixed = {
        "text": (
            "Организационный периметр\nТаблица 2\nОрганизация | Роль | Статус\n"
            "Разных значений в столбце «Роль»: 2. Список: заказчик, подрядчик."
        ),
        "document_name": "orgs.txt",
    }
    calls = []
    monkeypatch.setattr(agents, "count_tokens", _words)
    monkeypatch.setattr(agents, "complete", lambda *_args, **_kwargs: calls.append(1) or "В периметре две организации [1].")
    answer = agents.answer_agent("Какие организации входят в периметр?", "Какие организации входят в периметр?", [mixed], [])
    assert calls == [1]
    assert answer != "заказчик, подрядчик [1]."
    both = {
        "text": (
            "Организационный периметр\nТаблица 2\nОрганизация | Роль | Статус\n"
            "Разных значений в столбце «Роль»: 2. Список: заказчик, подрядчик.\n"
            "Разных значений в столбце «Организация»: 2. Список: Север, Юг."
        ),
        "document_name": "orgs.txt",
    }
    monkeypatch.setattr(agents, "complete", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("complete")))
    assert agents.answer_agent("Какие организации входят в периметр?", "Какие организации входят в периметр?", [both], []) == "Север, Юг [1]."


def test_overview_skips_unrelated_column(monkeypatch):
    monkeypatch.setattr(agents, "count_tokens", _words)
    monkeypatch.setattr(agents, "complete", lambda *_args, **_kwargs: "Ландшафты: TEST и PROD [1].")
    characteristics = {
        "text": (
            "ТРЕБОВАНИЯ К ИНТЕГРАЦИИ > Характеристики ИС > Характеристики ИМПУС\n"
            "Таблица 4 – Характеристики ИМПУС\n"
            "Перечень системных ландшафтов: TEST, PROD\n"
            "Разных значений в столбце «Характеристика»: 19. Список: Наименование, Перечень системных ландшафтов."
        ),
        "document_name": "impus.docx",
    }
    connections = {
        "text": (
            "ТЕХНИЧЕСКОЕ ОПИСАНИЕ > Параметры межсистемных соединений\n"
            "Таблица 16 – Параметры межсистемных соединений\n"
            "ИНИЦИАТОР СОЕДИНЕНИЯ / НАЗВАНИЕ: ИМПУС\n"
            "Разных значений в столбце «ИНИЦИАТОР СОЕДИНЕНИЯ / НАЗВАНИЕ»: 3. Список: ИМПУС, Локальная шина SAP PI, СПА."
        ),
        "document_name": "impus.docx",
    }
    query = "Какие системные ландшафты есть у ИМПУС?"
    assert agents.answer_agent(query, query, [characteristics, connections], []) == "Ландшафты: TEST и PROD [1]."
    fields = {
        "text": (
            "ТРЕБОВАНИЯ К ИНТЕГРАЦИИ > Характеристики ИС > Характеристики ИМПУС\n"
            "Таблица 4\n"
            "Разных значений в столбце «Характеристика»: 2. Список: Наименование, Организация-владелец."
        ),
        "document_name": "impus.docx",
    }
    calls = []
    monkeypatch.setattr(agents, "complete", lambda *_args, **_kwargs: calls.append(1) or "Росэнергоатом, БелАЭС [2].")
    orgs = {"text": "Организационный периметр\nРосэнергоатом, БелАЭС, НовАЭС.", "document_name": "impus.docx"}
    agents.answer_agent("Какие организации входят в периметр интеграции СПА и ИМПУС?", "Какие организации входят в периметр интеграции СПА и ИМПУС?", [fields, orgs], [])
    assert calls == [1]


def test_overview_prefers_section_about_the_asked_list(monkeypatch):
    monkeypatch.setattr(agents, "complete", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("complete")))
    connections = {
        "text": (
            "Параметры межсистемных соединений\n"
            "Таблица 16\n"
            "Разных значений в столбце «ИНИЦИАТОР СОЕДИНЕНИЯ / НАЗВАНИЕ»: 3. Список: ИМПУС, Локальная шина SAP PI, СПА."
        ),
        "document_name": "impus.docx",
    }
    flows = {
        "text": (
            "ТРЕБОВАНИЯ К ИНТЕГРАЦИИ > Характеристики потоков данных\n"
            "Таблица 6 – Перечень потоков данных\n"
            "Разных значений в столбце «ИД»: 4. Список: COUNT_1.1, COUNT_1.2, COUNT_2.1, COUNT_2.2."
        ),
        "document_name": "impus.docx",
    }
    query = "Какие потоки данных есть между СПА и ИМПУС?"
    answer = agents.answer_agent(query, query, [connections, flows], [])
    assert answer == "COUNT_1.1, COUNT_1.2, COUNT_2.1, COUNT_2.2 [2]."


def test_overview_yields_to_feedback(monkeypatch):
    halls = {
        "text": "Библиотека > Залы\nРазных значений в столбце «Зал»: 3. Список: Читальный, Детский, Архивный.",
        "document_name": "library.txt",
    }
    calls = []
    monkeypatch.setattr(agents, "count_tokens", _words)
    monkeypatch.setattr(agents, "complete", lambda *_args, **_kwargs: calls.append(1) or "В библиотеке три зала [1].")
    answer = agents.answer_agent("Какие залы есть в библиотеке?", "Какие залы есть в библиотеке?", [halls], [], feedback=agents.COPIED)
    assert calls == [1]
    assert answer == "В библиотеке три зала [1]."


def test_neskolko_does_not_copy_overview_count(monkeypatch):
    halls = {
        "text": "Библиотека > Залы\nРазных значений в столбце «Зал»: 3. Список: Читальный, Детский, Архивный.",
        "document_name": "library.txt",
    }
    calls = []
    monkeypatch.setattr(agents, "count_tokens", _words)
    monkeypatch.setattr(agents, "complete", lambda *_args, **_kwargs: calls.append(1) or "Есть несколько читальных мест [1].")
    answer = agents.answer_agent("Есть ли несколько залов в библиотеке?", "Есть ли несколько залов в библиотеке?", [halls], [])
    assert calls == [1]
    assert answer != "3 значений [1]."


def test_inflected_skolko_copies_overview_count(monkeypatch):
    monkeypatch.setattr(agents, "complete", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("complete")))
    halls = {
        "text": "Библиотека > Залы\nРазных значений в столбце «Зал»: 3. Список: Читальный, Детский, Архивный.",
        "document_name": "library.txt",
    }
    counted = "3 значений [1]."
    for query in (
        "Из скольких залов состоит библиотека?",
        "Сколькими залами располагает библиотека?",
        "К скольким залам есть доступ?",
    ):
        assert agents.answer_agent(query, query, [halls], []) == counted


def test_answer_appends_citation_when_model_omits_it(monkeypatch):
    monkeypatch.setattr(agents, "count_tokens", _words)
    monkeypatch.setattr(agents, "complete", lambda *_args, **_kwargs: "Давление равно 6 бар.")
    assert agents.answer_agent("Какое давление у насоса?", "Какое давление у насоса?", [PUMP, SHOP], []) == "Давление равно 6 бар. [1]"


def test_answer_calls_model_once_with_numbered_fragments(monkeypatch):
    calls = []
    monkeypatch.setattr(agents, "count_tokens", _words)
    monkeypatch.setattr(agents, "complete", lambda system, user, examples=(): calls.append((system, user, examples)) or "Давление равно 6 бар [1].")
    answer = agents.answer_agent("Какое давление у насоса?", "Какое давление у насоса?", [PUMP, SHOP], [])
    assert answer == "Давление равно 6 бар [1]."
    assert len(calls) == 1
    system, user, examples = calls[0]
    assert system == agents.SYSTEM
    assert examples == agents.EXAMPLES
    assert "Фрагмент 1 (документ pump.md):" in user
    assert "Фрагмент 2 (документ charter.txt):" in user
    assert user.count("Вопрос: Какое давление у насоса?") == 2
    assert agents.YES_NO not in user


def test_prompt_keeps_previous_turn_for_dependent_question(monkeypatch):
    monkeypatch.setattr(agents, "count_tokens", _words)
    seen = []
    monkeypatch.setattr(agents, "complete", lambda system, user, examples=(): seen.append(user) or "2019 [1].")
    turns = [{"query": "Какое давление у насоса?", "answer": "Давление равно 6 бар [1].", "document_names": ["pump.md"]}]
    clear = agents.clarify_agent("В каком году его выпустили?", turns)
    assert clear == "Какое давление у насоса? В каком году его выпустили? 6"
    agents.answer_agent("В каком году его выпустили?", clear, [PUMP], turns)
    assert "Прошлый вопрос: Какое давление у насоса?" in seen[0]


def test_yes_no_hint_only_for_questions_with_li(monkeypatch):
    assert agents.YES_NO in agents.build_prompt("Есть ли у насоса фильтр?", [PUMP], count=_words)
    assert agents.YES_NO not in agents.build_prompt("Какое давление у насоса?", [PUMP], count=_words)


def test_prompt_fits_token_budget():
    long = {"text": "\n".join(f"строка {number} " + "слово " * 30 for number in range(40)), "document_name": "long.txt"}
    prompt = agents.build_prompt("Что в длинном файле?", [long, long], count=_words, budget=300)
    assert _words(prompt) <= 300
    assert "Фрагмент 1" in prompt and "Фрагмент 2" not in prompt


def test_check_confirms_grounded_answer_and_cites_sources():
    verdict = agents.check_agent("Рабочее давление насоса равно 6 бар, год выпуска 2019 [1].", [PUMP, SHOP])
    assert verdict["status"] == agents.CONFIRMED
    assert [source["document_name"] for source in verdict["sources"]] == ["pump.md"]


def test_check_rejects_number_missing_from_fragments():
    verdict = agents.check_agent("Насос выпущен в 2021 году [1].", [PUMP, SHOP])
    assert verdict["status"] == agents.UNCONFIRMED
    assert verdict["missing"] == ["2021"]
    assert "2021" in verdict["feedback"]


def test_check_rejects_short_number_from_another_line():
    chunk = {"text": "Насос > Характеристики\nРабочее давление: 6 бар\nНомер цеха: 4", "document_name": "pump.md"}
    decimal = {"text": "Насос > Характеристики\nРабочее давление: 6,5 бар\nНомер цеха: 4", "document_name": "pump.md"}
    wrong = agents.check_agent("Рабочее давление насоса равно 4 бар [1].", [chunk])
    assert wrong["status"] == agents.UNCONFIRMED
    assert wrong["missing"] == ["4"]
    assert agents.check_agent("Рабочее давление насоса равно 6 бар [1].", [chunk])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление насоса равно 6,5 бар [1].", [decimal])["status"] == agents.CONFIRMED
    asked = agents.check_agent(
        "Да, рабочее давление насоса равно 10 бар [1].",
        [chunk],
        "Верно ли, что давление равно 10 бар?",
        known=lambda term: True,
    )
    assert asked["status"] == agents.UNCONFIRMED
    assert "10" in asked["missing"]


def test_check_rejects_number_from_another_fact_in_the_same_sentence():
    joined = {"text": "Насос > Характеристики\nРабочее давление: 6 бар и температура: 80 градусов.", "document_name": "pump.md"}
    note = {"text": "Насос > Характеристики\nРабочее давление составляет 6 бар (цех номер 4).", "document_name": "pump.md"}
    ranged = {"text": "Насос > Режим\nРабочее давление: от 6 до 10 бар", "document_name": "pump.md"}
    coded = {"text": "Насос ХН-7 рабочее давление: 6 бар.", "document_name": "pump.md"}
    wrong = agents.check_agent("Рабочее давление насоса равно 80 бар [1].", [joined])
    assert wrong["status"] == agents.UNCONFIRMED
    assert wrong["missing"] == ["80"]
    assert agents.check_agent("Рабочее давление насоса равно 6 бар [1].", [joined])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 6 бар, температура равна 80 градусов [1].", [joined])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление насоса равно 4 бар [1].", [note])["missing"] == ["4"]
    assert agents.check_agent("Рабочее давление насоса равно 6 бар [1].", [note])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление насоса от 6 до 10 бар [1].", [ranged])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление насоса ХН-7 равно 6 бар [1].", [coded], "Какое давление у насоса ХН-7?")["status"] == agents.CONFIRMED


def test_check_rejects_a_piece_of_a_decimal_or_grouped_number():
    decimal = {"text": "Насос > Характеристики\nРабочее давление: 6,5 бар", "document_name": "pump.md"}
    dotted = {"text": "Насос > Характеристики\nРабочее давление: 6.5 бар", "document_name": "pump.md"}
    tenths = {"text": "Насос > Характеристики\nРабочее давление: 10,5 бар", "document_name": "pump.md"}
    books = {"text": "Библиотека > Фонд\nВ фонде 12 000 книг.", "document_name": "lib.txt"}
    dozen = {"text": "Библиотека > Фонд\nВ фонде 12 книг.", "document_name": "lib.txt"}
    assert agents.check_agent("Рабочее давление насоса равно 6 бар [1].", [decimal])["missing"] == ["6"]
    assert agents.check_agent("Рабочее давление насоса равно 5 бар [1].", [decimal])["missing"] == ["5"]
    assert agents.check_agent("Рабочее давление насоса равно 10 бар [1].", [tenths])["missing"] == ["10"]
    assert agents.check_agent("Рабочее давление насоса равно 6,5 бар [1].", [decimal])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление насоса равно 6 бар [1].", [dotted])["missing"] == ["6"]
    assert agents.check_agent("Рабочее давление насоса равно 6.5 бар [1].", [dotted])["status"] == agents.CONFIRMED
    assert agents.check_agent("В фонде 12 книг [1].", [books])["missing"] == ["12"]
    assert agents.check_agent("В фонде 000 книг [1].", [books])["missing"] == ["000"]
    assert agents.check_agent("В фонде 12 000 книг [1].", [books])["status"] == agents.CONFIRMED
    assert agents.check_agent("В фонде 12 книг [1].", [dozen])["status"] == agents.CONFIRMED


def test_check_rejects_a_number_taken_from_a_designation_or_compound():
    named = {"text": "Насос имеет обозначение Н-12. Рабочее давление равно 6 бар.", "document_name": "pump.md"}
    coded = {"text": "Насос ХН-7 рабочее давление: 6 бар.", "document_name": "pump.md"}
    stock = {"text": "Инвентарный код Н-180. Рабочее давление равно 6 бар.", "document_name": "pump.md"}
    contract = {"text": "Договор от 22.03.2024 № 9/299419-Д.", "document_name": "contract.docx"}
    dated = {"text": "По договору от 22/03/2024 рабочее давление равно 6 бар.", "document_name": "pump.md"}
    clock = {"text": "С 6:00 рабочее давление держится на уровне 8 бар.", "document_name": "pump.md"}
    shift = {"text": "Начало смены в 6:00.", "document_name": "pump.md"}
    width = {"text": "Диаметр патрубка 1/2 дюйма.", "document_name": "pump.md"}
    tight = {"text": "Рабочее давление:6 бар.", "document_name": "pump.md"}
    ranged = {"text": "Рабочее давление: 6-10 бар.", "document_name": "pump.md"}
    assert agents.check_agent("Рабочее давление насоса равно 12 бар [1].", [named])["missing"] == ["12"]
    assert agents.check_agent("Рабочее давление насоса равно 6 бар [1].", [named])["status"] == agents.CONFIRMED
    assert agents.check_agent("Обозначение насоса Н-12 [1].", [named])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление насоса равно 7 бар [1].", [coded])["missing"] == ["7"]
    assert agents.check_agent("Рабочее давление насоса ХН-7 равно 6 бар [1].", [coded])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление насоса равно 180 бар [1].", [stock])["missing"] == ["180"]
    assert agents.check_agent("Номер договора равен 9 [1].", [contract], "Какой номер договора?")["missing"] == ["9"]
    assert agents.check_agent("Номер договора 299419 [1].", [contract], "Какой номер договора?")["missing"] == ["299419"]
    assert agents.check_agent("Номер договора 9/299419-Д [1].", [contract], "Какой номер договора?")["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 22 бар [1].", [dated])["missing"] == ["22"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [dated])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [clock])["missing"] == ["6"]
    assert agents.check_agent("Рабочее давление равно 8 бар [1].", [clock])["status"] == agents.CONFIRMED
    assert agents.check_agent("Начало смены в 6:00 [1].", [shift])["status"] == agents.CONFIRMED
    assert agents.check_agent("Диаметр патрубка равен 2 дюйма [1].", [width])["missing"] == ["2"]
    assert agents.check_agent("Диаметр патрубка равен 1 дюйм [1].", [width])["missing"] == ["1"]
    assert agents.check_agent("Диаметр патрубка 1/2 дюйма [1].", [width])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [tight])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [ranged])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 10 бар [1].", [ranged])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление 6-10 бар [1].", [ranged])["status"] == agents.CONFIRMED


def test_check_rejects_a_number_taken_from_a_negative_value():
    cold = {"text": "Насос > Режим\nРабочая температура: -12 градусов.", "document_name": "pump.md"}
    signed = {"text": "Насос > Режим\nРабочая температура: −12 градусов.", "document_name": "pump.md"}
    word = {"text": "Насос > Режим\nРабочая температура: минус 12 градусов.", "document_name": "pump.md"}
    decimal = {"text": "Насос > Режим\nРабочая температура: -6,5 градусов.", "document_name": "pump.md"}
    both = {"text": "Насос > Режим\nРабочая температура: -12 градусов, рабочее давление: 6 бар.", "document_name": "pump.md"}
    ranged = {"text": "Насос > Режим\nРабочая температура: от -6 до 10 градусов.", "document_name": "pump.md"}
    wide = {"text": "Насос > Режим\nРабочая температура: от 6 до 10 градусов.", "document_name": "pump.md"}
    warm = {"text": "Насос > Режим\nРабочая температура: 12 градусов.", "document_name": "pump.md"}
    assert agents.check_agent("Рабочая температура равна 12 градусов [1].", [cold])["missing"] == ["12"]
    assert agents.check_agent("Рабочая температура равна -12 градусов [1].", [cold])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочая температура равна 12 градусов [1].", [signed])["missing"] == ["12"]
    assert agents.check_agent("Рабочая температура равна −12 градусов [1].", [signed])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочая температура равна минус 12 градусов [1].", [signed])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочая температура равна 12 градусов [1].", [word])["missing"] == ["12"]
    assert agents.check_agent("Рабочая температура равна минус 12 градусов [1].", [word])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочая температура равна -12 градусов [1].", [word])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочая температура равна 6 градусов [1].", [decimal])["missing"] == ["6"]
    assert agents.check_agent("Рабочая температура равна 5 градусов [1].", [decimal])["missing"] == ["5"]
    assert agents.check_agent("Рабочая температура равна 6,5 градусов [1].", [decimal])["missing"] == ["6,5"]
    assert agents.check_agent("Рабочая температура равна -6,5 градусов [1].", [decimal])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 12 бар [1].", [both])["missing"] == ["12"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [both])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочая температура равна -12 градусов [1].", [both])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочая температура равна 6 градусов [1].", [ranged])["missing"] == ["6"]
    assert agents.check_agent("Рабочая температура от -6 до 10 градусов [1].", [ranged])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочая температура от 6 до 10 градусов [1].", [wide])["status"] == agents.CONFIRMED
    asked = agents.check_agent(
        "Да, рабочая температура равна минус 12 градусов [1].",
        [warm],
        "Верно ли, что рабочая температура равна минус 12?",
        known=lambda term: True,
    )
    assert asked["status"] == agents.UNCONFIRMED
    assert "-12" in asked["missing"]
    assert agents.check_agent("Рабочая температура равна -12 градусов [1].", [warm])["missing"] == ["-12"]


def test_check_accepts_a_number_after_a_spaced_dash():
    hyphen = {"text": "Насос > Режим\nРабочее давление - 6 бар.", "document_name": "pump.md"}
    endash = {"text": "Насос > Режим\nРабочее давление – 6 бар.", "document_name": "pump.md"}
    emdash = {"text": "Насос > Режим\nРабочее давление — 6 бар.", "document_name": "pump.md"}
    spaced = {"text": "Насос > Режим\nРабочая температура − 12 градусов.", "document_name": "pump.md"}
    wide = {"text": "Насос > Режим\nРабочее давление: 6 - 10 бар.", "document_name": "pump.md"}
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [hyphen])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно -6 бар [1].", [hyphen])["missing"] == ["-6"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [endash])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно -6 бар [1].", [endash])["missing"] == ["-6"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [emdash])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочая температура равна 12 градусов [1].", [spaced])["missing"] == ["12"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [wide])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 10 бар [1].", [wide])["status"] == agents.CONFIRMED


def test_check_rejects_a_tolerance_taken_as_its_measurement():
    pressure = {"text": "Насос > Режим\nРабочее давление: 6 ± 0,5 бар.", "document_name": "pump.md"}
    tight = {"text": "Насос > Режим\nРабочее давление: 6±0,5 бар.", "document_name": "pump.md"}
    unit = {"text": "Насос > Режим\nРабочее давление: 6 бар ± 0,5 бар.", "document_name": "pump.md"}
    slash = {"text": "Насос > Режим\nДиаметр вала: 50 +/- 0,2 мм.", "document_name": "pump.md"}
    plus = {"text": "Насос > Режим\nДиаметр вала: 50+-0,2 мм.", "document_name": "pump.md"}
    both = {"text": "Диаметр вала: 50 ± 0,2 мм. Длина вала: 10 ± 0,1 мм.", "document_name": "pump.md"}
    labeled = {"text": "Насос > Режим\nПогрешность: ±0,5 бар.", "document_name": "pump.md"}
    ranged = {"text": "Насос > Режим\nРабочее давление: 6-10 бар.", "document_name": "pump.md"}
    assert agents.check_agent("Рабочее давление равно 0,5 бар [1].", [pressure])["missing"] == ["0,5"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [pressure])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 6 ± 0,5 бар [1].", [pressure])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 6 ± 0,9 бар [1].", [pressure])["missing"] == ["0,9"]
    assert agents.check_agent("Рабочее давление равно 0,5 бар [1].", [tight])["missing"] == ["0,5"]
    assert agents.check_agent("Рабочее давление равно 6±0,5 бар [1].", [tight])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 0,5 бар [1].", [unit])["missing"] == ["0,5"]
    assert agents.check_agent("Рабочее давление равно 6 бар ± 0,5 бар [1].", [unit])["status"] == agents.CONFIRMED
    assert agents.check_agent("Диаметр вала равен 0,2 мм [1].", [slash])["missing"] == ["0,2"]
    assert agents.check_agent("Диаметр вала равен 50 мм [1].", [slash])["status"] == agents.CONFIRMED
    assert agents.check_agent("Диаметр вала равен 50 +/- 0,2 мм [1].", [slash])["status"] == agents.CONFIRMED
    assert agents.check_agent("Диаметр вала равен 0,2 мм [1].", [plus])["missing"] == ["0,2"]
    assert agents.check_agent("Диаметр вала равен 50+-0,2 мм [1].", [plus])["status"] == agents.CONFIRMED
    assert agents.check_agent("Диаметр вала равен 0,1 мм [1].", [both])["missing"] == ["0,1"]
    assert agents.check_agent("Длина вала равна 0,2 мм [1].", [both])["missing"] == ["0,2"]
    assert agents.check_agent("Диаметр вала равен 50 ± 0,2 мм [1].", [both])["status"] == agents.CONFIRMED
    assert agents.check_agent("Длина вала равна 10 ± 0,1 мм [1].", [both])["status"] == agents.CONFIRMED
    assert agents.check_agent("Диаметр вала равен 50 ± 0,1 мм [1].", [both])["missing"] == ["0,1"]
    assert agents.check_agent("Погрешность равна 0,5 бар [1].", [labeled])["status"] == agents.CONFIRMED
    assert agents.check_agent("Погрешность равна ±0,5 бар [1].", [labeled])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 0,5 бар [1].", [labeled])["missing"] == ["0,5"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [ranged])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 10 бар [1].", [ranged])["status"] == agents.CONFIRMED


def test_check_rejects_a_measurement_written_before_the_attribute():
    heated = {"text": "Насос > Режим\nПри температуре 80 градусов рабочее давление составляет 6 бар.", "document_name": "pump.md"}
    numbered = {"text": "Насос номер 6 имеет рабочее давление 8 бар.", "document_name": "pump.md"}
    counted = {"text": "В цехе 4 насоса с рабочим давлением 8 бар.", "document_name": "pump.md"}
    speed = {"text": "При частоте 50 Гц рабочее давление равно 6 бар.", "document_name": "pump.md"}
    mass = {"text": "Насос массой 5 кг развивает рабочее давление 6 бар.", "document_name": "pump.md"}
    yield_ = {"text": "КПД 85 процентов при рабочем давлении 6 бар.", "document_name": "pump.md"}
    flow = {"text": "Подача 12 м3/ч при рабочем давлении 6 бар.", "document_name": "pump.md"}
    leading = {"text": "6 бар — рабочее давление насоса.", "document_name": "pump.md"}
    both = {"text": "6 бар — рабочее давление и температура 80 градусов.", "document_name": "pump.md"}
    level = {"text": "При температуре 20 градусов рабочее давление держится на уровне 8 бар.", "document_name": "pump.md"}
    assert agents.check_agent("Рабочее давление равно 80 бар [1].", [heated])["missing"] == ["80"]
    assert agents.check_agent("Рабочее давление составляет 6 бар [1].", [heated])["status"] == agents.CONFIRMED
    assert agents.check_agent("Температура равна 80 градусов, рабочее давление составляет 6 бар [1].", [heated])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление насоса равно 6 бар [1].", [numbered])["missing"] == ["6"]
    assert agents.check_agent("Номер насоса равен 6, рабочее давление равно 8 бар [1].", [numbered])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление насоса равно 8 бар [1].", [numbered])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 4 бар [1].", [counted])["missing"] == ["4"]
    assert agents.check_agent("Рабочее давление равно 8 бар [1].", [counted])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 50 бар [1].", [speed])["missing"] == ["50"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [speed])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление насоса равно 5 бар [1].", [mass])["missing"] == ["5"]
    assert agents.check_agent("Рабочее давление насоса равно 6 бар [1].", [mass])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 85 бар [1].", [yield_])["missing"] == ["85"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [yield_])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 12 бар [1].", [flow])["missing"] == ["12"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [flow])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [leading])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [both])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 80 бар [1].", [both])["missing"] == ["80"]
    assert agents.check_agent("Рабочее давление контура составляет 6 бар [1].", [{"text": "Рабочее давление контура составляет 6 бар и температура 80 градусов.", "document_name": "pump.md"}])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 20 бар [1].", [level])["missing"] == ["20"]
    assert agents.check_agent("Рабочее давление равно 8 бар [1].", [level])["status"] == agents.CONFIRMED


def test_check_rejects_a_measurement_sharing_only_an_adjective_or_a_verb():
    heated = {"text": "Насос > Режим\nРабочая температура: 80 градусов.", "document_name": "pump.md"}
    stated = {"text": "Насос > Режим\nРабочая температура равна 80 градусов.", "document_name": "pump.md"}
    oil = {"text": "Насос > Режим\nРабочая температура масла равна 80 градусов.", "document_name": "pump.md"}
    maximal = {"text": "Насос > Режим\nМаксимальная температура равна 80 градусов.", "document_name": "pump.md"}
    nominal = {"text": "Насос > Режим\nНоминальная температура: 80 градусов.", "document_name": "pump.md"}
    critical = {"text": "Насос > Режим\nКритическая температура равна 80 градусов.", "document_name": "pump.md"}
    verb = {"text": "Насос > Режим\nТемпература составляет 80 градусов.", "document_name": "pump.md"}
    about = {"text": "Насос > Режим\nТемпература примерно 80 градусов.", "document_name": "pump.md"}
    reaches = {"text": "Насос > Режим\nТемпература достигает 80 градусов.", "document_name": "pump.md"}
    equals = {"text": "Насос > Режим\nТемпература равняется 80 градусов.", "document_name": "pump.md"}
    level = {"text": "Насос > Режим\nДавление держится на уровне 80 бар.", "document_name": "pump.md"}
    value = {"text": "Насос > Режим\nТемпература имеет значение 80 градусов.", "document_name": "pump.md"}
    indicator = {"text": "Насос > Режим\nПоказатель температуры составляет 80 градусов.", "document_name": "pump.md"}
    alongside = {"text": "Насос > Режим\nРабочее давление при температуре составляет 6 бар.", "document_name": "pump.md"}
    held = {"text": "Насос > Режим\nРабочее давление держится на уровне 8 бар.", "document_name": "pump.md"}
    plain = {"text": "Насос > Режим\nУровень: 8.", "document_name": "pump.md"}
    hours = {"text": "Рабочее время температурных испытаний составляет 6 часов.", "document_name": "pump.md"}
    both = {"text": "Насос > Режим\nПри температуре 20 уровень равен 8.", "document_name": "pump.md"}
    assert agents.check_agent("Рабочее давление равно 80 бар [1].", [heated])["missing"] == ["80"]
    assert agents.check_agent("Рабочая температура равна 80 градусов [1].", [heated])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 80 бар [1].", [stated])["missing"] == ["80"]
    assert agents.check_agent("Рабочая температура равна 80 градусов [1].", [stated])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 80 бар [1].", [oil])["missing"] == ["80"]
    assert agents.check_agent("Рабочая температура масла равна 80 градусов [1].", [oil])["status"] == agents.CONFIRMED
    assert agents.check_agent("Максимальное давление равно 80 бар [1].", [maximal])["missing"] == ["80"]
    assert agents.check_agent("Максимальная температура равна 80 градусов [1].", [maximal])["status"] == agents.CONFIRMED
    assert agents.check_agent("Номинальное давление равно 80 бар [1].", [nominal])["missing"] == ["80"]
    assert agents.check_agent("Критическое давление равно 80 бар [1].", [critical])["missing"] == ["80"]
    assert agents.check_agent("Критическая температура равна 80 градусов [1].", [critical])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление составляет 80 бар [1].", [verb])["missing"] == ["80"]
    assert agents.check_agent("Температура составляет 80 градусов [1].", [verb])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление примерно 80 бар [1].", [about])["missing"] == ["80"]
    assert agents.check_agent("Давление достигает 80 бар [1].", [reaches])["missing"] == ["80"]
    assert agents.check_agent("Температура достигает 80 градусов [1].", [reaches])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равняется 80 бар [1].", [equals])["missing"] == ["80"]
    assert agents.check_agent("Температура держится на уровне 80 градусов [1].", [level])["missing"] == ["80"]
    assert agents.check_agent("Давление держится на уровне 80 бар [1].", [level])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление имеет значение 80 бар [1].", [value])["missing"] == ["80"]
    assert agents.check_agent("Температура имеет значение 80 градусов [1].", [value])["status"] == agents.CONFIRMED
    assert agents.check_agent("Показатель давления составляет 80 бар [1].", [indicator])["missing"] == ["80"]
    assert agents.check_agent("Показатель температуры составляет 80 градусов [1].", [indicator])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление при температуре составляет 6 бар [1].", [alongside])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление держится на уровне 8 бар [1].", [held])["status"] == agents.CONFIRMED
    assert agents.check_agent("Уровень равен 8 [1].", [plain])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее время температурных испытаний составляет 6 часов [1].", [hours])["status"] == agents.CONFIRMED
    assert agents.check_agent("Уровень равен 8 [1].", [both])["status"] == agents.CONFIRMED
    assert agents.check_agent("Температура равна 20 градусов [1].", [both])["status"] == agents.CONFIRMED


def test_check_rejects_a_measurement_with_a_short_name():
    current = {"text": "Насос > Режим\nРабочее давление: 6 бар и ток: 80 А.", "document_name": "pump.md"}
    stroke = {"text": "Ход 80 мм при рабочем давлении 6 бар.", "document_name": "pump.md"}
    efficiency = {"text": "КПД 85% при рабочем давлении 6 бар.", "document_name": "pump.md"}
    kind = {"text": "Тип 80 и рабочее давление 6 бар.", "document_name": "pump.md"}
    steam = {"text": "Давление 6 бар и пар 80 градусов.", "document_name": "pump.md"}
    weight = {"text": "Вес 5 кг при рабочем давлении 6 бар.", "document_name": "pump.md"}
    paren = {"text": "Рабочее давление: 6 бар (ток 80 А).", "document_name": "pump.md"}
    joined = {"text": "Рабочее давление и ток: 80 А.", "document_name": "pump.md"}
    outlet = {"text": "Рабочее давление на выходе: 6 бар.", "document_name": "pump.md"}
    circuit = {"text": "Рабочее давление контура: 6 бар и температура 80 градусов.", "document_name": "pump.md"}
    assert agents.check_agent("Рабочее давление равно 80 бар [1].", [current])["missing"] == ["80"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [current])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 6 бар и ток равен 80 А [1].", [current])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 80 бар [1].", [stroke])["missing"] == ["80"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [stroke])["status"] == agents.CONFIRMED
    assert agents.check_agent("Ход равен 80 мм, рабочее давление равно 6 бар [1].", [stroke])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 85 бар [1].", [efficiency])["missing"] == ["85"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [efficiency])["status"] == agents.CONFIRMED
    assert agents.check_agent("КПД равен 85%, рабочее давление равно 6 бар [1].", [efficiency])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 80 бар [1].", [kind])["missing"] == ["80"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [kind])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 80 бар [1].", [steam])["missing"] == ["80"]
    assert agents.check_agent("Давление равно 6 бар [1].", [steam])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 5 бар [1].", [weight])["missing"] == ["5"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [weight])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 80 бар [1].", [paren])["missing"] == ["80"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [paren])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 80 бар [1].", [joined])["missing"] == ["80"]
    assert agents.check_agent("Рабочее давление на выходе равно 6 бар [1].", [outlet])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление контура равно 6 бар [1].", [circuit])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление контура равно 80 бар [1].", [circuit])["missing"] == ["80"]
    verbal = {"text": "Рабочее давление и ток равен 80 А.", "document_name": "pump.md"}
    amperage = {"text": "Сила тока равна 80 А. Рабочее давление равно 6 бар.", "document_name": "pump.md"}
    assert agents.check_agent("Рабочее давление равно 80 бар [1].", [verbal])["missing"] == ["80"]
    assert agents.check_agent("Сила тока равна 80 А [1].", [amperage])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [amperage])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 80 бар [1].", [amperage])["missing"] == ["80"]


def test_check_rejects_a_number_owned_by_another_noun():
    oil = {"text": "Насос > Режим\nТемпература масла: 80 градусов.", "document_name": "pump.md"}
    both = {"text": "Насос > Режим\nТемпература масла: 80 градусов. Давление масла: 6 бар.", "document_name": "pump.md"}
    flow = {"text": "Подача насоса: 6 м3/ч.", "document_name": "pump.md"}
    power = {"text": "Мощность насоса: 5 кВт.", "document_name": "pump.md"}
    speed = {"text": "Частота двигателя: 5 Гц.", "document_name": "pump.md"}
    bore = {"text": "Диаметр патрубка: 50 мм.", "document_name": "pump.md"}
    length = {"text": "Длина патрубка: 50 мм.", "document_name": "pump.md"}
    accuracy = {"text": "Класс точности: 80.", "document_name": "pump.md"}
    shield = {"text": "Степень защиты двигателя: 8.", "document_name": "pump.md"}
    efficiency = {"text": "Коэффициент полезного действия равен 1,5.", "document_name": "pump.md"}
    aside = {"text": "Рабочее давление при температуре составляет 6 бар.", "document_name": "pump.md"}
    outlet = {"text": "Рабочее давление на выходе: 6 бар.", "document_name": "pump.md"}
    opening = {"text": "Высота проема: 50 мм.", "document_name": "pump.md"}
    assert agents.check_agent("Давление масла равно 80 бар [1].", [oil])["missing"] == ["80"]
    assert agents.check_agent("Температура масла равна 80 градусов [1].", [oil])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление масла равно 80 бар [1].", [both])["missing"] == ["80"]
    assert agents.check_agent("Давление масла равно 6 бар [1].", [both])["status"] == agents.CONFIRMED
    assert agents.check_agent("Температура масла равна 80 градусов [1].", [both])["status"] == agents.CONFIRMED
    assert agents.check_agent("Напор насоса равен 6 м [1].", [flow])["missing"] == ["6"]
    assert agents.check_agent("Подача насоса равна 6 м3/ч [1].", [flow])["status"] == agents.CONFIRMED
    assert agents.check_agent("Масса насоса равна 5 кг [1].", [power])["missing"] == ["5"]
    assert agents.check_agent("Мощность насоса равна 5 кВт [1].", [power])["status"] == agents.CONFIRMED
    assert agents.check_agent("Мощность двигателя равна 5 кВт [1].", [speed])["missing"] == ["5"]
    assert agents.check_agent("Частота двигателя равна 5 Гц [1].", [speed])["status"] == agents.CONFIRMED
    assert agents.check_agent("Длина патрубка равна 50 мм [1].", [bore])["missing"] == ["50"]
    assert agents.check_agent("Диаметр патрубка равен 50 мм [1].", [bore])["status"] == agents.CONFIRMED
    assert agents.check_agent("Диаметр патрубка равен 50 мм [1].", [length])["missing"] == ["50"]
    assert agents.check_agent("Длина патрубка равна 50 мм [1].", [length])["status"] == agents.CONFIRMED
    assert agents.check_agent("Класс давления равен 80 [1].", [accuracy])["missing"] == ["80"]
    assert agents.check_agent("Класс точности равен 80 [1].", [accuracy])["status"] == agents.CONFIRMED
    assert agents.check_agent("Степень сжатия равна 8 [1].", [shield])["missing"] == ["8"]
    assert agents.check_agent("Степень защиты равна 8 [1].", [shield])["status"] == agents.CONFIRMED
    assert agents.check_agent("Коэффициент запаса равен 1,5 [1].", [efficiency])["missing"] == ["1,5"]
    assert agents.check_agent("Коэффициент полезного действия равен 1,5 [1].", [efficiency])["status"] == agents.CONFIRMED
    assert agents.check_agent("Температура составляет 6 градусов [1].", [aside])["missing"] == ["6"]
    assert agents.check_agent("Рабочее давление составляет 6 бар [1].", [aside])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [outlet])["status"] == agents.CONFIRMED
    assert agents.check_agent("Ширина проема равна 50 мм [1].", [opening])["missing"] == ["50"]
    assert agents.check_agent("Высота проема равна 50 мм [1].", [opening])["status"] == agents.CONFIRMED


def test_check_rejects_a_measurement_taken_from_its_condition():
    heated = {"text": "Насос > Режим\nРабочее давление при температуре 80 градусов.", "document_name": "pump.md"}
    pressed = {"text": "Насос > Режим\nТемпература при давлении 6 бар.", "document_name": "pump.md"}
    motor = {"text": "Мощность при частоте вращения 50 Гц.", "document_name": "pump.md"}
    pumped = {"text": "Напор при подаче 12 м3/ч.", "document_name": "pump.md"}
    viscous = {"text": "Вязкость при температуре 80.", "document_name": "pump.md"}
    celsius = {"text": "Максимальное давление при температуре 80 °C.", "document_name": "pump.md"}
    both = {"text": "Рабочее давление при температуре 80 градусов составляет 6 бар.", "document_name": "pump.md"}
    rated = {"text": "Рабочее давление при температуре 80 °C равно 6 бар.", "document_name": "pump.md"}
    stated = {"text": "Температура при давлении 6 бар составляет 80 градусов.", "document_name": "pump.md"}
    aside = {"text": "Рабочее давление при температуре составляет 6 бар.", "document_name": "pump.md"}
    outlet = {"text": "Рабочее давление на выходе: 6 бар.", "document_name": "pump.md"}
    assert agents.check_agent("Рабочее давление равно 80 бар [1].", [heated])["missing"] == ["80"]
    assert agents.check_agent("Температура равна 80 градусов [1].", [heated])["status"] == agents.CONFIRMED
    assert agents.check_agent("Температура равна 6 градусов [1].", [pressed])["missing"] == ["6"]
    assert agents.check_agent("Давление равно 6 бар [1].", [pressed])["status"] == agents.CONFIRMED
    assert agents.check_agent("Мощность равна 50 кВт [1].", [motor])["missing"] == ["50"]
    assert agents.check_agent("Частота вращения равна 50 Гц [1].", [motor])["status"] == agents.CONFIRMED
    assert agents.check_agent("Напор равен 12 м [1].", [pumped])["missing"] == ["12"]
    assert agents.check_agent("Подача равна 12 м3/ч [1].", [pumped])["status"] == agents.CONFIRMED
    assert agents.check_agent("Вязкость равна 80 [1].", [viscous])["missing"] == ["80"]
    assert agents.check_agent("Температура равна 80 градусов [1].", [viscous])["status"] == agents.CONFIRMED
    assert agents.check_agent("Максимальное давление равно 80 бар [1].", [celsius])["missing"] == ["80"]
    assert agents.check_agent("Температура равна 80 °C [1].", [celsius])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 80 бар [1].", [both])["missing"] == ["80"]
    assert agents.check_agent("Рабочее давление составляет 6 бар [1].", [both])["status"] == agents.CONFIRMED
    assert agents.check_agent("Температура равна 80 градусов [1].", [both])["status"] == agents.CONFIRMED
    assert agents.check_agent("Температура составляет 6 градусов [1].", [both])["missing"] == ["6"]
    assert agents.check_agent("Рабочее давление равно 80 бар [1].", [rated])["missing"] == ["80"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [rated])["status"] == agents.CONFIRMED
    assert agents.check_agent("Температура равна 6 градусов [1].", [stated])["missing"] == ["6"]
    assert agents.check_agent("Температура составляет 80 градусов [1].", [stated])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 6 бар [1].", [stated])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление составляет 80 бар [1].", [stated])["missing"] == ["80"]
    assert agents.check_agent("Рабочее давление составляет 6 бар [1].", [aside])["status"] == agents.CONFIRMED
    assert agents.check_agent("Температура составляет 6 градусов [1].", [aside])["missing"] == ["6"]
    assert agents.check_agent("Рабочее давление на выходе равно 6 бар [1].", [outlet])["status"] == agents.CONFIRMED


def test_check_rejects_a_measurement_taken_from_a_short_condition():
    stroke = {"text": "Насос > Режим\nРабочее давление при ходе 80 мм.", "document_name": "pump.md"}
    piston = {"text": "Насос > Режим\nРабочее давление при ходе поршня 80 мм.", "document_name": "pump.md"}
    current = {"text": "Насос > Режим\nРабочее давление при токе 80 А составляет 6 бар.", "document_name": "pump.md"}
    gap = {"text": "Насос > Режим\nРабочее давление при зазоре 80 мкм составляет 6 бар.", "document_name": "pump.md"}
    weight = {"text": "Насос > Режим\nДавление при весе 5 кг.", "document_name": "pump.md"}
    steam = {"text": "Насос > Режим\nДавление при паре 80 градусов.", "document_name": "pump.md"}
    angle = {"text": "Насос > Режим\nРабочее давление при угле 80 градусов.", "document_name": "pump.md"}
    efficiency = {"text": "Насос > Режим\nДавление при кпд 85 процентов.", "document_name": "pump.md"}
    kind = {"text": "Насос > Режим\nДавление при типе 80.", "document_name": "pump.md"}
    voltage = {"text": "Мощность при напряжении 220 В равна 5 кВт.", "document_name": "pump.md"}
    hours = {"text": "Давление при времени работы 80 часов.", "document_name": "pump.md"}
    running = {"text": "Насос > Режим\nРабочее давление при работе: 6 бар.", "document_name": "pump.md"}
    assert agents.check_agent("Рабочее давление равно 80 бар [1].", [stroke])["missing"] == ["80"]
    assert agents.check_agent("Рабочее давление равно 80 бар [1].", [piston])["missing"] == ["80"]
    assert agents.check_agent("Рабочее давление равно 80 бар [1].", [current])["missing"] == ["80"]
    assert agents.check_agent("Рабочее давление составляет 6 бар [1].", [current])["status"] == agents.CONFIRMED
    assert agents.check_agent("Ток равен 80 А, рабочее давление составляет 6 бар [1].", [current])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 80 бар [1].", [gap])["missing"] == ["80"]
    assert agents.check_agent("Рабочее давление составляет 6 бар [1].", [gap])["status"] == agents.CONFIRMED
    assert agents.check_agent("Зазор равен 80 мкм, рабочее давление составляет 6 бар [1].", [gap])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 5 бар [1].", [weight])["missing"] == ["5"]
    assert agents.check_agent("Давление равно 80 бар [1].", [steam])["missing"] == ["80"]
    assert agents.check_agent("Рабочее давление равно 80 бар [1].", [angle])["missing"] == ["80"]
    assert agents.check_agent("Давление равно 85 бар [1].", [efficiency])["missing"] == ["85"]
    assert agents.check_agent("Давление равно 80 бар [1].", [kind])["missing"] == ["80"]
    assert agents.check_agent("Мощность равна 220 кВт [1].", [voltage])["missing"] == ["220"]
    assert agents.check_agent("Мощность равна 5 кВт [1].", [voltage])["status"] == agents.CONFIRMED
    assert agents.check_agent("Напряжение равно 220 В [1].", [voltage])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 80 бар [1].", [hours])["missing"] == ["80"]
    assert agents.check_agent("Время работы равно 80 часов [1].", [hours])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [running])["status"] == agents.CONFIRMED


def test_check_rejects_a_measurement_that_only_shares_the_object():
    stroke = {"text": "Насос > Режим\nХод поршня: 80 мм.", "document_name": "pump.md"}
    current = {"text": "Насос > Режим\nТок двигателя: 80 А.", "document_name": "pump.md"}
    gap = {"text": "Насос > Режим\nЗазор клапана: 80 мкм.", "document_name": "pump.md"}
    weight = {"text": "Насос > Режим\nВес ротора: 5 кг.", "document_name": "pump.md"}
    angle = {"text": "Насос > Режим\nУгол поворота: 80 градусов.", "document_name": "pump.md"}
    hours = {"text": "Насос > Режим\nВремя работы: 80 часов.", "document_name": "pump.md"}
    voltage = {"text": "Насос > Режим\nНапряжение сети: 220 В.", "document_name": "pump.md"}
    conditioned = {"text": "Рабочее давление при ходе поршня 80 мм составляет 6 бар.", "document_name": "pump.md"}
    oblique = {"text": "Давление при угле поворота 80 градусов составляет 6 бар.", "document_name": "pump.md"}
    temporary = {"text": "Временно давление равно 6 бар.", "document_name": "pump.md"}
    intense = {"text": "Напряженно рабочее давление равно 6 бар.", "document_name": "pump.md"}
    assert agents.check_agent("Диаметр поршня равен 80 мм [1].", [stroke])["missing"] == ["80"]
    assert agents.check_agent("Ход поршня равен 80 мм [1].", [stroke])["status"] == agents.CONFIRMED
    assert agents.check_agent("Мощность двигателя равна 80 кВт [1].", [current])["missing"] == ["80"]
    assert agents.check_agent("Ток двигателя равен 80 А [1].", [current])["status"] == agents.CONFIRMED
    assert agents.check_agent("Диаметр клапана равен 80 мкм [1].", [gap])["missing"] == ["80"]
    assert agents.check_agent("Зазор клапана равен 80 мкм [1].", [gap])["status"] == agents.CONFIRMED
    assert agents.check_agent("Диаметр ротора равен 5 мм [1].", [weight])["missing"] == ["5"]
    assert agents.check_agent("Вес ротора равен 5 кг [1].", [weight])["status"] == agents.CONFIRMED
    assert agents.check_agent("Скорость поворота равна 80 градусов [1].", [angle])["missing"] == ["80"]
    assert agents.check_agent("Угол поворота равен 80 градусов [1].", [angle])["status"] == agents.CONFIRMED
    assert agents.check_agent("Угол равен 80 градусов [1].", [angle])["status"] == agents.CONFIRMED
    assert agents.check_agent("Мощность работы равна 80 [1].", [hours])["missing"] == ["80"]
    assert agents.check_agent("Время работы равно 80 часов [1].", [hours])["status"] == agents.CONFIRMED
    assert agents.check_agent("Мощность сети равна 220 кВт [1].", [voltage])["missing"] == ["220"]
    assert agents.check_agent("Напряжение сети равно 220 В [1].", [voltage])["status"] == agents.CONFIRMED
    assert agents.check_agent("Напряжение равно 220 В [1].", [voltage])["status"] == agents.CONFIRMED
    assert agents.check_agent("Диаметр поршня равен 80 мм [1].", [conditioned])["missing"] == ["80"]
    assert agents.check_agent("Ход поршня равен 80 мм [1].", [conditioned])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление составляет 6 бар [1].", [conditioned])["status"] == agents.CONFIRMED
    assert agents.check_agent("Скорость поворота равна 80 градусов [1].", [oblique])["missing"] == ["80"]
    assert agents.check_agent("Угол поворота равен 80 градусов [1].", [oblique])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление составляет 6 бар [1].", [oblique])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 6 бар [1].", [temporary])["status"] == agents.CONFIRMED
    assert agents.check_agent("Время равно 6 часов [1].", [temporary])["missing"] == ["6"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [intense])["status"] == agents.CONFIRMED
    assert agents.check_agent("Напряжение равно 6 В [1].", [intense])["missing"] == ["6"]


def test_check_rejects_a_measurement_that_only_shares_the_object_of_an_unlisted_name():
    radius = {"text": "Насос > Режим\nРадиус поршня: 80 мм.", "document_name": "pump.md"}
    wall = {"text": "Насос > Режим\nТолщина стенки: 12 мм.", "document_name": "pump.md"}
    life = {"text": "Насос > Режим\nРесурс подшипника: 80 часов.", "document_name": "pump.md"}
    output = {"text": "Насос > Режим\nПроизводительность насоса: 80 м3/ч.", "document_name": "pump.md"}
    pitch = {"text": "Насос > Режим\nШаг резьбы: 2 мм.", "document_name": "pump.md"}
    tank = {"text": "Насос > Режим\nЕмкость резервуара: 80 литров.", "document_name": "pump.md"}
    term = {"text": "Насос > Режим\nСрок службы: 80 месяцев.", "document_name": "pump.md"}
    area = {"text": "Насос > Режим\nПлощадь фильтра: 80 см2.", "document_name": "pump.md"}
    depth = {"text": "Насос > Режим\nГлубина погружения: 40 мм.", "document_name": "pump.md"}
    steady = {"text": "Постоянно радиус поршня равен 80 мм.", "document_name": "pump.md"}
    assert agents.check_agent("Диаметр поршня равен 80 мм [1].", [radius])["missing"] == ["80"]
    assert agents.check_agent("Радиус поршня равен 80 мм [1].", [radius])["status"] == agents.CONFIRMED
    assert agents.check_agent("Высота стенки равна 12 мм [1].", [wall])["missing"] == ["12"]
    assert agents.check_agent("Толщина стенки равна 12 мм [1].", [wall])["status"] == agents.CONFIRMED
    assert agents.check_agent("Масса подшипника равна 80 кг [1].", [life])["missing"] == ["80"]
    assert agents.check_agent("Ресурс подшипника равен 80 часов [1].", [life])["status"] == agents.CONFIRMED
    assert agents.check_agent("Мощность насоса равна 80 кВт [1].", [output])["missing"] == ["80"]
    assert agents.check_agent("Производительность насоса равна 80 м3/ч [1].", [output])["status"] == agents.CONFIRMED
    assert agents.check_agent("Диаметр резьбы равен 2 мм [1].", [pitch])["missing"] == ["2"]
    assert agents.check_agent("Шаг резьбы равен 2 мм [1].", [pitch])["status"] == agents.CONFIRMED
    assert agents.check_agent("Диаметр резервуара равен 80 мм [1].", [tank])["missing"] == ["80"]
    assert agents.check_agent("Емкость резервуара равна 80 литров [1].", [tank])["status"] == agents.CONFIRMED
    assert agents.check_agent("Масса службы равна 80 [1].", [term])["missing"] == ["80"]
    assert agents.check_agent("Срок службы равен 80 месяцев [1].", [term])["status"] == agents.CONFIRMED
    assert agents.check_agent("Диаметр фильтра равен 80 мм [1].", [area])["missing"] == ["80"]
    assert agents.check_agent("Площадь фильтра равна 80 см2 [1].", [area])["status"] == agents.CONFIRMED
    assert agents.check_agent("Длина погружения равна 40 мм [1].", [depth])["missing"] == ["40"]
    assert agents.check_agent("Глубина погружения равна 40 мм [1].", [depth])["status"] == agents.CONFIRMED
    assert agents.check_agent("Диаметр поршня равен 80 мм [1].", [steady])["missing"] == ["80"]
    assert agents.check_agent("Радиус поршня равен 80 мм [1].", [steady])["status"] == agents.CONFIRMED


def test_check_rejects_a_difference_error_or_swing_of_another_measurement():
    drop = {"text": "Насос > Режим\nПерепад давления: 2 бар. Рабочее давление: 6 бар.", "document_name": "pump.md"}
    joined = {"text": "Перепад давления 2 бар и рабочее давление 6 бар.", "document_name": "pump.md"}
    conditioned = {"text": "Рабочее давление при перепаде 2 бар составляет 6 бар.", "document_name": "pump.md"}
    error = {"text": "Погрешность давления: 0,5 бар. Рабочее давление: 6 бар.", "document_name": "pump.md"}
    tolerance = {"text": "Допуск диаметра: 0,2 мм. Диаметр вала: 50 мм.", "document_name": "pump.md"}
    loss = {"text": "Потеря напора: 12 м. Напор насоса: 40 м.", "document_name": "pump.md"}
    fall = {"text": "Падение давления составляет 2 бар.", "document_name": "pump.md"}
    drift = {"text": "Отклонение температуры: 3 градуса.", "document_name": "pump.md"}
    pulse = {"text": "Пульсация давления: 4 бар.", "document_name": "pump.md"}
    swing = {"text": "Амплитуда хода поршня: 80 мм.", "document_name": "pump.md"}
    decrease = {"text": "Снижение давления: 7 бар.", "document_name": "pump.md"}
    gap = {"text": "Разность давлений: 9 бар.", "document_name": "pump.md"}
    uneven = {"text": "Неравномерность подачи: 8 процентов.", "document_name": "pump.md"}
    wave = {"text": "Колебание давления: 4 бар.", "document_name": "pump.md"}
    slope = {"text": "Градиент давления: 5 бар.", "document_name": "pump.md"}
    current = {"text": "Сила тока равна 80 А.", "document_name": "pump.md"}
    numbered = {"text": "Насос номер 6 имеет рабочее давление 8 бар.", "document_name": "pump.md"}
    assert agents.check_agent("Рабочее давление равно 2 бар [1].", [drop])["missing"] == ["2"]
    assert agents.check_agent("Перепад давления равен 2 бар [1].", [drop])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [drop])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 2 бар [1].", [joined])["missing"] == ["2"]
    assert agents.check_agent("Перепад давления равен 2 бар, рабочее давление равно 6 бар [1].", [joined])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 2 бар [1].", [conditioned])["missing"] == ["2"]
    assert agents.check_agent("Перепад равен 2 бар [1].", [conditioned])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление составляет 6 бар [1].", [conditioned])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 0,5 бар [1].", [error])["missing"] == ["0,5"]
    assert agents.check_agent("Погрешность давления равна 0,5 бар [1].", [error])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [error])["status"] == agents.CONFIRMED
    assert agents.check_agent("Диаметр вала равен 0,2 мм [1].", [tolerance])["missing"] == ["0,2"]
    assert agents.check_agent("Допуск диаметра равен 0,2 мм [1].", [tolerance])["status"] == agents.CONFIRMED
    assert agents.check_agent("Диаметр вала равен 50 мм [1].", [tolerance])["status"] == agents.CONFIRMED
    assert agents.check_agent("Напор равен 12 м [1].", [loss])["missing"] == ["12"]
    assert agents.check_agent("Потеря напора равна 12 м [1].", [loss])["status"] == agents.CONFIRMED
    assert agents.check_agent("Напор насоса равен 40 м [1].", [loss])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление составляет 2 бар [1].", [fall])["missing"] == ["2"]
    assert agents.check_agent("Падение давления составляет 2 бар [1].", [fall])["status"] == agents.CONFIRMED
    assert agents.check_agent("Температура равна 3 градуса [1].", [drift])["missing"] == ["3"]
    assert agents.check_agent("Отклонение температуры равно 3 градуса [1].", [drift])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 4 бар [1].", [pulse])["missing"] == ["4"]
    assert agents.check_agent("Пульсация давления равна 4 бар [1].", [pulse])["status"] == agents.CONFIRMED
    assert agents.check_agent("Ход поршня равен 80 мм [1].", [swing])["missing"] == ["80"]
    assert agents.check_agent("Амплитуда хода поршня равна 80 мм [1].", [swing])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 7 бар [1].", [decrease])["missing"] == ["7"]
    assert agents.check_agent("Снижение давления равно 7 бар [1].", [decrease])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 9 бар [1].", [gap])["missing"] == ["9"]
    assert agents.check_agent("Разность давлений равна 9 бар [1].", [gap])["status"] == agents.CONFIRMED
    assert agents.check_agent("Подача равна 8 [1].", [uneven])["missing"] == ["8"]
    assert agents.check_agent("Неравномерность подачи равна 8 процентов [1].", [uneven])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 4 бар [1].", [wave])["missing"] == ["4"]
    assert agents.check_agent("Колебание давления равно 4 бар [1].", [wave])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 5 бар [1].", [slope])["missing"] == ["5"]
    assert agents.check_agent("Градиент давления равен 5 бар [1].", [slope])["status"] == agents.CONFIRMED
    assert agents.check_agent("Сила тока равна 80 А [1].", [current])["status"] == agents.CONFIRMED
    assert agents.check_agent("Номер насоса равен 6, рабочее давление равно 8 бар [1].", [numbered])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [numbered])["missing"] == ["6"]


def test_check_rejects_a_measurement_taken_from_an_unlisted_condition():
    radius = {"text": "Насос > Режим\nРабочее давление при радиусе поршня 80 мм.", "document_name": "pump.md"}
    both = {"text": "Рабочее давление при радиусе поршня 80 мм составляет 6 бар.", "document_name": "pump.md"}
    bare = {"text": "Рабочее давление при радиусе 80 мм составляет 6 бар.", "document_name": "pump.md"}
    named = {"text": "Рабочее давление при радиусе составляет 6 бар.", "document_name": "pump.md"}
    wall = {"text": "Рабочее давление при толщине стенки 12 мм составляет 6 бар.", "document_name": "pump.md"}
    depth = {"text": "Напор при глубине погружения 40 мм.", "document_name": "pump.md"}
    area = {"text": "Подача при площади фильтра 80 см2 составляет 6 м3/ч.", "document_name": "pump.md"}
    life = {"text": "Мощность при ресурсе подшипника 80 часов равна 5 кВт.", "document_name": "pump.md"}
    pitch = {"text": "Давление при шаге резьбы 2 мм составляет 6 бар.", "document_name": "pump.md"}
    tank = {"text": "Давление при емкости резервуара 80 литров составляет 6 бар.", "document_name": "pump.md"}
    term = {"text": "Давление при сроке службы 80 месяцев составляет 6 бар.", "document_name": "pump.md"}
    output = {"text": "Давление при производительности насоса 80 м3/ч составляет 6 бар.", "document_name": "pump.md"}
    running = {"text": "Рабочее давление при работе: 6 бар.", "document_name": "pump.md"}
    outlet = {"text": "Рабочее давление на выходе: 6 бар.", "document_name": "pump.md"}
    pad = {"text": "Рабочее давление на площадке: 6 бар.", "document_name": "pump.md"}
    assert agents.check_agent("Рабочее давление равно 80 бар [1].", [radius])["missing"] == ["80"]
    assert agents.check_agent("Радиус поршня равен 80 мм [1].", [radius])["status"] == agents.CONFIRMED
    assert agents.check_agent("Диаметр поршня равен 80 мм [1].", [radius])["missing"] == ["80"]
    assert agents.check_agent("Рабочее давление равно 80 бар [1].", [both])["missing"] == ["80"]
    assert agents.check_agent("Рабочее давление составляет 6 бар [1].", [both])["status"] == agents.CONFIRMED
    assert agents.check_agent("Радиус поршня равен 80 мм [1].", [both])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 80 бар [1].", [bare])["missing"] == ["80"]
    assert agents.check_agent("Рабочее давление составляет 6 бар [1].", [bare])["status"] == agents.CONFIRMED
    assert agents.check_agent("Радиус равен 80 мм [1].", [bare])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление составляет 6 бар [1].", [named])["status"] == agents.CONFIRMED
    assert agents.check_agent("Радиус составляет 6 мм [1].", [named])["missing"] == ["6"]
    assert agents.check_agent("Рабочее давление равно 12 бар [1].", [wall])["missing"] == ["12"]
    assert agents.check_agent("Рабочее давление составляет 6 бар [1].", [wall])["status"] == agents.CONFIRMED
    assert agents.check_agent("Толщина стенки равна 12 мм [1].", [wall])["status"] == agents.CONFIRMED
    assert agents.check_agent("Напор равен 40 м [1].", [depth])["missing"] == ["40"]
    assert agents.check_agent("Глубина погружения равна 40 мм [1].", [depth])["status"] == agents.CONFIRMED
    assert agents.check_agent("Подача равна 80 [1].", [area])["missing"] == ["80"]
    assert agents.check_agent("Подача составляет 6 [1].", [area])["status"] == agents.CONFIRMED
    assert agents.check_agent("Площадь фильтра равна 80 см2 [1].", [area])["status"] == agents.CONFIRMED
    assert agents.check_agent("Мощность равна 80 кВт [1].", [life])["missing"] == ["80"]
    assert agents.check_agent("Мощность равна 5 кВт [1].", [life])["status"] == agents.CONFIRMED
    assert agents.check_agent("Ресурс подшипника равен 80 часов [1].", [life])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 2 бар [1].", [pitch])["missing"] == ["2"]
    assert agents.check_agent("Давление составляет 6 бар [1].", [pitch])["status"] == agents.CONFIRMED
    assert agents.check_agent("Шаг резьбы равен 2 мм [1].", [pitch])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 80 бар [1].", [tank])["missing"] == ["80"]
    assert agents.check_agent("Давление составляет 6 бар [1].", [tank])["status"] == agents.CONFIRMED
    assert agents.check_agent("Емкость резервуара равна 80 литров [1].", [tank])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 80 бар [1].", [term])["missing"] == ["80"]
    assert agents.check_agent("Давление составляет 6 бар [1].", [term])["status"] == agents.CONFIRMED
    assert agents.check_agent("Срок службы равен 80 месяцев [1].", [term])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 80 бар [1].", [output])["missing"] == ["80"]
    assert agents.check_agent("Давление составляет 6 бар [1].", [output])["status"] == agents.CONFIRMED
    assert agents.check_agent("Производительность насоса равна 80 м3/ч [1].", [output])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [running])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [outlet])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [pad])["status"] == agents.CONFIRMED


def test_check_rejects_another_value_of_the_same_measurement():
    ends = {"text": "Давление на входе 2 бар, давление на выходе 6 бар.", "document_name": "pump.md"}
    joined = {"text": "Давление на входе 2 бар и давление на выходе 6 бар.", "document_name": "pump.md"}
    elided = {"text": "Давление на входе 2 бар и на выходе 6 бар.", "document_name": "pump.md"}
    limits = {"text": "Минимальное давление 6 бар, максимальное давление 16 бар.", "document_name": "pump.md"}
    fluids = {"text": "Давление воды: 6 бар. Давление масла: 16 бар.", "document_name": "pump.md"}
    duties = {"text": "Испытательное давление: 6 бар.\nРабочее давление: 16 бар.", "document_name": "pump.md"}
    radii = {"text": "Радиус крышки: 40 мм. Радиус поршня: 80 мм.", "document_name": "pump.md"}
    strokes = {"text": "Ход поршня: 80 мм. Ход клапана: 40 мм.", "document_name": "pump.md"}
    heated = {"text": "Рабочая температура: 80 градусов.\nДавление: 6 бар.", "document_name": "pump.md"}
    counted = {"text": "В цехе 4 насоса с рабочим давлением 8 бар.", "document_name": "pump.md"}
    ranged = {"text": "Давление от 6 до 10 бар.", "document_name": "pump.md"}
    conditioned = {"text": "Рабочее давление при температуре 80 градусов составляет 6 бар.", "document_name": "pump.md"}
    assert agents.check_agent("Давление на выходе равно 2 бар [1].", [ends])["missing"] == ["2"]
    assert agents.check_agent("Давление на входе равно 6 бар [1].", [ends])["missing"] == ["6"]
    assert agents.check_agent("Давление на выходе равно 6 бар [1].", [ends])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на входе равно 2 бар [1].", [ends])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на выходе равно 2 бар [1].", [joined])["missing"] == ["2"]
    assert agents.check_agent("Давление на выходе равно 6 бар, давление на входе равно 2 бар [1].", [joined])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на выходе равно 2 бар [1].", [elided])["missing"] == ["2"]
    assert agents.check_agent("Давление на выходе равно 6 бар [1].", [elided])["status"] == agents.CONFIRMED
    assert agents.check_agent("Максимальное давление равно 6 бар [1].", [limits])["missing"] == ["6"]
    assert agents.check_agent("Минимальное давление равно 16 бар [1].", [limits])["missing"] == ["16"]
    assert agents.check_agent("Максимальное давление равно 16 бар [1].", [limits])["status"] == agents.CONFIRMED
    assert agents.check_agent("Минимальное давление равно 6 бар [1].", [limits])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление масла равно 6 бар [1].", [fluids])["missing"] == ["6"]
    assert agents.check_agent("Давление воды равно 16 бар [1].", [fluids])["missing"] == ["16"]
    assert agents.check_agent("Давление масла равно 16 бар [1].", [fluids])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление воды равно 6 бар [1].", [fluids])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [duties])["missing"] == ["6"]
    assert agents.check_agent("Испытательное давление равно 16 бар [1].", [duties])["missing"] == ["16"]
    assert agents.check_agent("Рабочее давление равно 16 бар [1].", [duties])["status"] == agents.CONFIRMED
    assert agents.check_agent("Испытательное давление равно 6 бар [1].", [duties])["status"] == agents.CONFIRMED
    assert agents.check_agent("Радиус поршня равен 40 мм [1].", [radii])["missing"] == ["40"]
    assert agents.check_agent("Радиус крышки равен 80 мм [1].", [radii])["missing"] == ["80"]
    assert agents.check_agent("Радиус поршня равен 80 мм [1].", [radii])["status"] == agents.CONFIRMED
    assert agents.check_agent("Радиус крышки равен 40 мм [1].", [radii])["status"] == agents.CONFIRMED
    assert agents.check_agent("Ход клапана равен 80 мм [1].", [strokes])["missing"] == ["80"]
    assert agents.check_agent("Ход поршня равен 40 мм [1].", [strokes])["missing"] == ["40"]
    assert agents.check_agent("Ход клапана равен 40 мм [1].", [strokes])["status"] == agents.CONFIRMED
    assert agents.check_agent("Ход поршня равен 80 мм [1].", [strokes])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [heated])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 80 бар [1].", [heated])["missing"] == ["80"]
    assert agents.check_agent("Рабочее давление равно 8 бар [1].", [counted])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 4 бар [1].", [counted])["missing"] == ["4"]
    assert agents.check_agent("Давление равно 6 бар [1].", [ranged])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 10 бар [1].", [ranged])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление составляет 6 бар [1].", [conditioned])["status"] == agents.CONFIRMED
    assert agents.check_agent("Температура равна 6 градусов [1].", [conditioned])["missing"] == ["6"]
    assert agents.check_agent("Температура равна 80 градусов [1].", [conditioned])["status"] == agents.CONFIRMED


def test_check_rejects_a_long_number_taken_from_another_measurement():
    year = {"text": "Насос > Характеристики\nРабочее давление: 6 бар\nГод выпуска: 2019", "document_name": "pump.md"}
    dense = {"text": "Плотность 1000 кг/м3. Давление 6 бар.", "document_name": "pump.md"}
    books = {"text": "Библиотека > Фонд\nВ фонде 12 000 книг.", "document_name": "lib.txt"}
    stock = {"text": "Инвентарный номер: 1800\nРабочее давление: 6 бар", "document_name": "pump.md"}
    stroke = {"text": "Масса 1000 кг. Ход поршня: 80 мм.", "document_name": "pump.md"}
    radius = {"text": "Радиус поршня: 1000 мм. Масса: 80 кг.", "document_name": "pump.md"}
    real = {"text": "Рабочее давление: 1600 бар.", "document_name": "pump.md"}
    assert agents.check_agent("Рабочее давление равно 2019 бар [1].", [year])["missing"] == ["2019"]
    assert agents.check_agent("Год выпуска равен 2019 [1].", [year])["status"] == agents.CONFIRMED
    assert agents.check_agent("Насос выпущен в 2019 году [1].", [year])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [year])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 1000 бар [1].", [dense])["missing"] == ["1000"]
    assert agents.check_agent("Плотность равна 1000 кг/м3 [1].", [dense])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 6 бар [1].", [dense])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 12 000 бар [1].", [books])["missing"] == ["12 000"]
    assert agents.check_agent("В фонде 12 000 книг [1].", [books])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 1800 бар [1].", [stock])["missing"] == ["1800"]
    assert agents.check_agent("Инвентарный номер равен 1800 [1].", [stock])["status"] == agents.CONFIRMED
    assert agents.check_agent("Ход поршня равен 1000 мм [1].", [stroke])["missing"] == ["1000"]
    assert agents.check_agent("Масса равна 1000 кг [1].", [stroke])["status"] == agents.CONFIRMED
    assert agents.check_agent("Ход поршня равен 80 мм [1].", [stroke])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 1600 бар [1].", [real])["status"] == agents.CONFIRMED
    assert agents.check_agent("Радиус поршня равен 1000 мм [1].", [radius])["status"] == agents.CONFIRMED
    assert agents.check_agent("Масса равна 1000 кг [1].", [radius])["missing"] == ["1000"]


def test_check_rejects_a_year_taken_as_its_measurement():
    since = {"text": "С 2019 года давление составляет 6 бар.", "document_name": "pump.md"}
    during = {"text": "В 2019 году рабочее давление: 6 бар.", "document_name": "pump.md"}
    until = {"text": "До 2019 давление было 6 бар.", "document_name": "pump.md"}
    dated = {"text": "Давление с 2019 года составляет 6 бар.", "document_name": "pump.md"}
    marked = {"text": "1600 — рабочее давление с 2019 года.", "document_name": "pump.md"}
    ranged = {"text": "Давление от 2000 до 2019 бар.", "document_name": "pump.md"}
    real = {"text": "Рабочее давление: 2019 бар.", "document_name": "pump.md"}
    issued = {"text": "Насос > Характеристики\nГод выпуска: 2019", "document_name": "pump.md"}
    assert agents.check_agent("Давление равно 2019 бар [1].", [since])["missing"] == ["2019"]
    assert agents.check_agent("Давление равно 6 бар [1].", [since])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 2019 бар [1].", [during])["missing"] == ["2019"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [during])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 2019 бар [1].", [until])["missing"] == ["2019"]
    assert agents.check_agent("Давление равно 6 бар [1].", [until])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 2019 бар [1].", [dated])["missing"] == ["2019"]
    assert agents.check_agent("Давление равно 6 бар [1].", [dated])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 2019 бар [1].", [marked])["missing"] == ["2019"]
    assert agents.check_agent("Рабочее давление равно 1600 бар [1].", [marked])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 2000 бар [1].", [ranged])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 2019 бар [1].", [ranged])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 2019 бар [1].", [real])["status"] == agents.CONFIRMED
    assert agents.check_agent("Насос выпущен в 2019 году [1].", [issued])["status"] == agents.CONFIRMED
    assert agents.check_agent("Год выпуска равен 2019 [1].", [issued])["status"] == agents.CONFIRMED


def test_check_rejects_a_calendar_day_taken_as_its_measurement():
    dated = {"text": "Давление с 1 января 2019 года составляет 6 бар.", "document_name": "pump.md"}
    may = {"text": "Давление с 12 мая 2019 года составляет 6 бар.", "document_name": "pump.md"}
    winter = {"text": "Давление с 31 декабря 2019 года составляет 6 бар.", "document_name": "pump.md"}
    bare = {"text": "Давление с 1 января 2019 составляет 6 бар.", "document_name": "pump.md"}
    month = {"text": "Давление в январе 2019 составляет 6 бар.", "document_name": "pump.md"}
    leading = {"text": "1 января давление составляет 6 бар.", "document_name": "pump.md"}
    cold = {"text": "Температура 1 января составила 20 градусов.", "document_name": "pump.md"}
    spanned = {"text": "Давление с 1 по 6 января составляет 10 бар.", "document_name": "pump.md"}
    numeric = {"text": "Давление с 01.01.2019 составляет 6 бар.", "document_name": "pump.md"}
    ranged = {"text": "Давление от 1 до 6 бар.", "document_name": "pump.md"}
    unit = {"text": "Диаметр 1 мм.", "document_name": "pump.md"}
    january = {"text": "Давление 1 бар в январе.", "document_name": "pump.md"}
    major = {"text": "Номер 1 майора.", "document_name": "pump.md"}
    real = {"text": "Рабочее давление: 2019 бар.", "document_name": "pump.md"}
    season = {"text": "Подача в мае: 6.", "document_name": "pump.md"}
    assert agents.check_agent("Давление равно 1 бар [1].", [dated])["missing"] == ["1"]
    assert agents.check_agent("Давление равно 2019 бар [1].", [dated])["missing"] == ["2019"]
    assert agents.check_agent("Давление равно 6 бар [1].", [dated])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 12 бар [1].", [may])["missing"] == ["12"]
    assert agents.check_agent("Давление равно 6 бар [1].", [may])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 31 бар [1].", [winter])["missing"] == ["31"]
    assert agents.check_agent("Давление равно 6 бар [1].", [winter])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 1 бар [1].", [bare])["missing"] == ["1"]
    assert agents.check_agent("Давление равно 2019 бар [1].", [bare])["missing"] == ["2019"]
    assert agents.check_agent("Давление равно 6 бар [1].", [bare])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 2019 бар [1].", [month])["missing"] == ["2019"]
    assert agents.check_agent("Давление равно 6 бар [1].", [month])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 1 бар [1].", [leading])["missing"] == ["1"]
    assert agents.check_agent("Давление равно 6 бар [1].", [leading])["status"] == agents.CONFIRMED
    assert agents.check_agent("Температура равна 1 градус [1].", [cold])["missing"] == ["1"]
    assert agents.check_agent("Температура равна 20 градусов [1].", [cold])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 1 бар [1].", [spanned])["missing"] == ["1"]
    assert agents.check_agent("Давление равно 6 бар [1].", [spanned])["missing"] == ["6"]
    assert agents.check_agent("Давление равно 10 бар [1].", [spanned])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 1 бар [1].", [numeric])["missing"] == ["1"]
    assert agents.check_agent("Давление равно 2019 бар [1].", [numeric])["missing"] == ["2019"]
    assert agents.check_agent("Давление равно 6 бар [1].", [numeric])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 1 бар [1].", [ranged])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 6 бар [1].", [ranged])["status"] == agents.CONFIRMED
    assert agents.check_agent("Диаметр равен 1 мм [1].", [unit])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 1 бар [1].", [january])["status"] == agents.CONFIRMED
    assert agents.check_agent("Номер равен 1 [1].", [major])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 2019 бар [1].", [real])["status"] == agents.CONFIRMED
    assert agents.check_agent("Подача равна 6 [1].", [season])["status"] == agents.CONFIRMED


def test_check_rejects_a_clock_time_taken_as_its_measurement():
    between = {"text": "Давление в 6 часов составляет 10 бар.", "document_name": "pump.md"}
    leading = {"text": "В 18 часов рабочее давление: 6 бар.", "document_name": "pump.md"}
    toward = {"text": "К 8 часам давление составило 6 бар.", "document_name": "pump.md"}
    hour = {"text": "В 1 час давление составляет 6 бар.", "document_name": "pump.md"}
    hours = {"text": "В 2 часа давление составляет 6 бар.", "document_name": "pump.md"}
    since = {"text": "С 6 часов давление составляет 10 бар.", "document_name": "pump.md"}
    until = {"text": "До 18 часов давление составляет 6 бар.", "document_name": "pump.md"}
    colon = {"text": "Давление в 14:30 составляет 6 бар.", "document_name": "pump.md"}
    dotted = {"text": "Давление в 14.30 составляет 6 бар.", "document_name": "pump.md"}
    heated = {"text": "Температура в 18 часов составила 80 градусов.", "document_name": "pump.md"}
    lasted = {"text": "Время работы составляет 6 часов.", "document_name": "pump.md"}
    shift = {"text": "Смена в 8 часов.", "document_name": "pump.md"}
    life = {"text": "Срок службы в 6 часов.", "document_name": "pump.md"}
    resource = {"text": "Ресурс до 6 часов.", "document_name": "pump.md"}
    ranged = {"text": "Наработка от 6 до 10 часов.", "document_name": "pump.md"}
    decimal = {"text": "Рабочее давление: 14.30 бар.", "document_name": "pump.md"}
    bars = {"text": "Давление в 6 бар.", "document_name": "pump.md"}
    assert agents.check_agent("Давление равно 6 бар [1].", [between])["missing"] == ["6"]
    assert agents.check_agent("Давление равно 10 бар [1].", [between])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 18 бар [1].", [leading])["missing"] == ["18"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [leading])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 8 бар [1].", [toward])["missing"] == ["8"]
    assert agents.check_agent("Давление равно 6 бар [1].", [toward])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 1 бар [1].", [hour])["missing"] == ["1"]
    assert agents.check_agent("Давление равно 6 бар [1].", [hour])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 2 бар [1].", [hours])["missing"] == ["2"]
    assert agents.check_agent("Давление равно 6 бар [1].", [hours])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 6 бар [1].", [since])["missing"] == ["6"]
    assert agents.check_agent("Давление равно 10 бар [1].", [since])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 18 бар [1].", [until])["missing"] == ["18"]
    assert agents.check_agent("Давление равно 6 бар [1].", [until])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 14 бар [1].", [colon])["missing"] == ["14"]
    assert agents.check_agent("Давление равно 30 бар [1].", [colon])["missing"] == ["30"]
    assert agents.check_agent("Давление равно 6 бар [1].", [colon])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 14 бар [1].", [dotted])["missing"] == ["14"]
    assert agents.check_agent("Давление равно 6 бар [1].", [dotted])["status"] == agents.CONFIRMED
    assert agents.check_agent("Температура равна 18 градусов [1].", [heated])["missing"] == ["18"]
    assert agents.check_agent("Температура равна 80 градусов [1].", [heated])["status"] == agents.CONFIRMED
    assert agents.check_agent("Время работы составляет 6 часов [1].", [lasted])["status"] == agents.CONFIRMED
    assert agents.check_agent("Смена равна 8 часов [1].", [shift])["status"] == agents.CONFIRMED
    assert agents.check_agent("Срок службы равен 6 часов [1].", [life])["status"] == agents.CONFIRMED
    assert agents.check_agent("Ресурс равен 6 часов [1].", [resource])["status"] == agents.CONFIRMED
    assert agents.check_agent("Наработка равна 6 часов [1].", [ranged])["status"] == agents.CONFIRMED
    assert agents.check_agent("Наработка равна 10 часов [1].", [ranged])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 14.30 бар [1].", [decimal])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 14 бар [1].", [decimal])["missing"] == ["14"]
    assert agents.check_agent("Давление равно 6 бар [1].", [bars])["status"] == agents.CONFIRMED


def test_check_rejects_a_clock_minute_taken_as_its_measurement():
    between = {"text": "Давление в 14 часов 30 минут составляет 6 бар.", "document_name": "pump.md"}
    leading = {"text": "В 14 часов 30 минут рабочее давление: 6 бар.", "document_name": "pump.md"}
    toward = {"text": "К 8 часам 15 минут давление составило 6 бар.", "document_name": "pump.md"}
    early = {"text": "Давление в 6 часов 30 минут составляет 10 бар.", "document_name": "pump.md"}
    heated = {"text": "Температура в 18 часов 45 минут составила 80 градусов.", "document_name": "pump.md"}
    precise = {"text": "Давление в 14 часов 30 минут 15 секунд составляет 6 бар.", "document_name": "pump.md"}
    singular = {"text": "Давление в 1 час 1 минуту составляет 6 бар.", "document_name": "pump.md"}
    plural = {"text": "Давление в 2 часа 5 минут составляет 6 бар.", "document_name": "pump.md"}
    lasted = {"text": "Время в 6 часов 30 минут.", "document_name": "pump.md"}
    life = {"text": "Срок службы в 6 часов 30 минут.", "document_name": "pump.md"}
    resource = {"text": "Ресурс до 6 часов 30 минут.", "document_name": "pump.md"}
    counted = {"text": "Количество до 6 часов 30 минут.", "document_name": "pump.md"}
    worked = {"text": "Время работы составляет 6 часов 30 минут.", "document_name": "pump.md"}
    plain = {"text": "Время работы составляет 30 минут.", "document_name": "pump.md"}
    ranged = {"text": "Наработка от 6 до 10 часов.", "document_name": "pump.md"}
    shift = {"text": "Смена в 8 часов.", "document_name": "pump.md"}
    pause = {"text": "Пауза 30 минут. Давление 6 бар.", "document_name": "pump.md"}
    assert agents.check_agent("Давление равно 30 бар [1].", [between])["missing"] == ["30"]
    assert agents.check_agent("Давление равно 14 бар [1].", [between])["missing"] == ["14"]
    assert agents.check_agent("Давление равно 6 бар [1].", [between])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 30 бар [1].", [leading])["missing"] == ["30"]
    assert agents.check_agent("Рабочее давление равно 14 бар [1].", [leading])["missing"] == ["14"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [leading])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 15 бар [1].", [toward])["missing"] == ["15"]
    assert agents.check_agent("Давление равно 8 бар [1].", [toward])["missing"] == ["8"]
    assert agents.check_agent("Давление равно 6 бар [1].", [toward])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 30 бар [1].", [early])["missing"] == ["30"]
    assert agents.check_agent("Давление равно 6 бар [1].", [early])["missing"] == ["6"]
    assert agents.check_agent("Давление равно 10 бар [1].", [early])["status"] == agents.CONFIRMED
    assert agents.check_agent("Температура равна 45 градусов [1].", [heated])["missing"] == ["45"]
    assert agents.check_agent("Температура равна 18 градусов [1].", [heated])["missing"] == ["18"]
    assert agents.check_agent("Температура равна 80 градусов [1].", [heated])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 30 бар [1].", [precise])["missing"] == ["30"]
    assert agents.check_agent("Давление равно 15 бар [1].", [precise])["missing"] == ["15"]
    assert agents.check_agent("Давление равно 14 бар [1].", [precise])["missing"] == ["14"]
    assert agents.check_agent("Давление равно 6 бар [1].", [precise])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 1 бар [1].", [singular])["missing"] == ["1"]
    assert agents.check_agent("Давление равно 6 бар [1].", [singular])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 5 бар [1].", [plural])["missing"] == ["5"]
    assert agents.check_agent("Давление равно 2 бар [1].", [plural])["missing"] == ["2"]
    assert agents.check_agent("Давление равно 6 бар [1].", [plural])["status"] == agents.CONFIRMED
    assert agents.check_agent("Время равно 30 минут [1].", [lasted])["status"] == agents.CONFIRMED
    assert agents.check_agent("Время равно 6 часов [1].", [lasted])["status"] == agents.CONFIRMED
    assert agents.check_agent("Срок службы равен 30 минут [1].", [life])["status"] == agents.CONFIRMED
    assert agents.check_agent("Срок службы равен 6 часов [1].", [life])["status"] == agents.CONFIRMED
    assert agents.check_agent("Ресурс равен 30 минут [1].", [resource])["status"] == agents.CONFIRMED
    assert agents.check_agent("Ресурс равен 6 часов [1].", [resource])["status"] == agents.CONFIRMED
    assert agents.check_agent("Количество равно 30 минут [1].", [counted])["status"] == agents.CONFIRMED
    assert agents.check_agent("Количество равно 6 часов [1].", [counted])["status"] == agents.CONFIRMED
    assert agents.check_agent("Время работы составляет 6 часов [1].", [worked])["status"] == agents.CONFIRMED
    assert agents.check_agent("Время работы составляет 30 минут [1].", [plain])["status"] == agents.CONFIRMED
    assert agents.check_agent("Наработка равна 6 часов [1].", [ranged])["status"] == agents.CONFIRMED
    assert agents.check_agent("Наработка равна 10 часов [1].", [ranged])["status"] == agents.CONFIRMED
    assert agents.check_agent("Смена равна 8 часов [1].", [shift])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 30 бар [1].", [pause])["missing"] == ["30"]
    assert agents.check_agent("Давление равно 6 бар [1].", [pause])["status"] == agents.CONFIRMED
    assert agents.check_agent("Пауза равна 30 минут [1].", [pause])["status"] == agents.CONFIRMED


def test_check_rejects_an_abbreviated_clock_taken_as_its_measurement():
    between = {"text": "Давление в 14 ч 30 мин составляет 6 бар.", "document_name": "pump.md"}
    spelled = {"text": "Давление в 14 часов 30 мин составляет 6 бар.", "document_name": "pump.md"}
    dotted = {"text": "Давление в 14 ч. 30 мин. составляет 6 бар.", "document_name": "pump.md"}
    leading = {"text": "В 14 ч 30 мин рабочее давление: 6 бар.", "document_name": "pump.md"}
    hour = {"text": "Давление в 14 ч составляет 6 бар.", "document_name": "pump.md"}
    precise = {"text": "Давление в 14 ч 30 мин 15 сек составляет 6 бар.", "document_name": "pump.md"}
    singular = {"text": "Давление в 1 ч 1 мин составляет 6 бар.", "document_name": "pump.md"}
    lasted = {"text": "Время в 6 ч 30 мин.", "document_name": "pump.md"}
    life = {"text": "Срок службы в 6 ч 30 мин.", "document_name": "pump.md"}
    worked = {"text": "Время работы составляет 6 ч 30 мин.", "document_name": "pump.md"}
    plain = {"text": "Время работы составляет 30 мин.", "document_name": "pump.md"}
    shift = {"text": "Смена в 8 ч.", "document_name": "pump.md"}
    ranged = {"text": "Наработка от 6 до 10 ч.", "document_name": "pump.md"}
    pause = {"text": "Пауза 30 мин. Давление 6 бар.", "document_name": "pump.md"}
    split = {"text": "Смена в 8 ч. Давление 6 бар.", "document_name": "pump.md"}
    part = {"text": "Давление в 6 часть составляет 10 бар.", "document_name": "pump.md"}
    zone = {"text": "Давление в 6 часового пояса составляет 10 бар.", "document_name": "pump.md"}
    assert agents.check_agent("Давление равно 30 бар [1].", [between])["missing"] == ["30"]
    assert agents.check_agent("Давление равно 14 бар [1].", [between])["missing"] == ["14"]
    assert agents.check_agent("Давление равно 6 бар [1].", [between])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 30 бар [1].", [spelled])["missing"] == ["30"]
    assert agents.check_agent("Давление равно 14 бар [1].", [spelled])["missing"] == ["14"]
    assert agents.check_agent("Давление равно 6 бар [1].", [spelled])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 30 бар [1].", [dotted])["missing"] == ["30"]
    assert agents.check_agent("Давление равно 14 бар [1].", [dotted])["missing"] == ["14"]
    assert agents.check_agent("Давление равно 6 бар [1].", [dotted])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 30 бар [1].", [leading])["missing"] == ["30"]
    assert agents.check_agent("Рабочее давление равно 14 бар [1].", [leading])["missing"] == ["14"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [leading])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 14 бар [1].", [hour])["missing"] == ["14"]
    assert agents.check_agent("Давление равно 6 бар [1].", [hour])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 15 бар [1].", [precise])["missing"] == ["15"]
    assert agents.check_agent("Давление равно 30 бар [1].", [precise])["missing"] == ["30"]
    assert agents.check_agent("Давление равно 14 бар [1].", [precise])["missing"] == ["14"]
    assert agents.check_agent("Давление равно 6 бар [1].", [precise])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 1 бар [1].", [singular])["missing"] == ["1"]
    assert agents.check_agent("Давление равно 6 бар [1].", [singular])["status"] == agents.CONFIRMED
    assert agents.check_agent("Время равно 30 минут [1].", [lasted])["status"] == agents.CONFIRMED
    assert agents.check_agent("Время равно 6 часов [1].", [lasted])["status"] == agents.CONFIRMED
    assert agents.check_agent("Срок службы равен 30 минут [1].", [life])["status"] == agents.CONFIRMED
    assert agents.check_agent("Срок службы равен 6 часов [1].", [life])["status"] == agents.CONFIRMED
    assert agents.check_agent("Время работы составляет 6 часов [1].", [worked])["status"] == agents.CONFIRMED
    assert agents.check_agent("Время работы составляет 30 минут [1].", [plain])["status"] == agents.CONFIRMED
    assert agents.check_agent("Смена равна 8 часов [1].", [shift])["status"] == agents.CONFIRMED
    assert agents.check_agent("Наработка равна 6 часов [1].", [ranged])["status"] == agents.CONFIRMED
    assert agents.check_agent("Наработка равна 10 часов [1].", [ranged])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 30 бар [1].", [pause])["missing"] == ["30"]
    assert agents.check_agent("Давление равно 6 бар [1].", [pause])["status"] == agents.CONFIRMED
    assert agents.check_agent("Пауза равна 30 минут [1].", [pause])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 8 бар [1].", [split])["missing"] == ["8"]
    assert agents.check_agent("Давление равно 6 бар [1].", [split])["status"] == agents.CONFIRMED
    assert agents.check_agent("Смена равна 8 часов [1].", [split])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 6 бар [1].", [part])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 6 бар [1].", [zone])["status"] == agents.CONFIRMED


def test_check_rejects_an_hour_range_taken_as_its_measurement():
    window = {"text": "Давление с 8 до 18 часов составляет 6 бар.", "document_name": "pump.md"}
    leading = {"text": "С 8 до 18 часов рабочее давление: 6 бар.", "document_name": "pump.md"}
    spelled = {"text": "Давление с 8 часов до 18 часов составляет 6 бар.", "document_name": "pump.md"}
    short = {"text": "Рабочее давление с 8 до 18 ч составляет 6 бар.", "document_name": "pump.md"}
    dotted = {"text": "Рабочее давление с 8 до 18 ч. составляет 6 бар.", "document_name": "pump.md"}
    during = {"text": "Давление от 6 до 10 часов составляет 16 бар.", "document_name": "pump.md"}
    heated = {"text": "Температура с 8 до 18 часов составила 80 градусов.", "document_name": "pump.md"}
    ranged = {"text": "Наработка от 6 до 10 часов.", "document_name": "pump.md"}
    shift = {"text": "Смена с 8 до 18 часов.", "document_name": "pump.md"}
    life = {"text": "Срок службы от 6 до 10 часов.", "document_name": "pump.md"}
    worked = {"text": "Время работы от 6 до 10 часов.", "document_name": "pump.md"}
    counted = {"text": "Количество от 6 до 10 часов.", "document_name": "pump.md"}
    resource = {"text": "Ресурс от 6 до 10 часов.", "document_name": "pump.md"}
    bars = {"text": "Давление от 8 до 18 бар.", "document_name": "pump.md"}
    bare = {"text": "Давление от 8 до 18.", "document_name": "pump.md"}
    assert agents.check_agent("Давление равно 8 бар [1].", [window])["missing"] == ["8"]
    assert agents.check_agent("Давление равно 18 бар [1].", [window])["missing"] == ["18"]
    assert agents.check_agent("Давление равно 6 бар [1].", [window])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 8 бар [1].", [leading])["missing"] == ["8"]
    assert agents.check_agent("Рабочее давление равно 18 бар [1].", [leading])["missing"] == ["18"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [leading])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 8 бар [1].", [spelled])["missing"] == ["8"]
    assert agents.check_agent("Давление равно 18 бар [1].", [spelled])["missing"] == ["18"]
    assert agents.check_agent("Давление равно 6 бар [1].", [spelled])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 8 бар [1].", [short])["missing"] == ["8"]
    assert agents.check_agent("Рабочее давление равно 18 бар [1].", [short])["missing"] == ["18"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [short])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 8 бар [1].", [dotted])["missing"] == ["8"]
    assert agents.check_agent("Рабочее давление равно 18 бар [1].", [dotted])["missing"] == ["18"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [dotted])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 6 бар [1].", [during])["missing"] == ["6"]
    assert agents.check_agent("Давление равно 10 бар [1].", [during])["missing"] == ["10"]
    assert agents.check_agent("Давление равно 16 бар [1].", [during])["status"] == agents.CONFIRMED
    assert agents.check_agent("Температура равна 8 градусов [1].", [heated])["missing"] == ["8"]
    assert agents.check_agent("Температура равна 18 градусов [1].", [heated])["missing"] == ["18"]
    assert agents.check_agent("Температура равна 80 градусов [1].", [heated])["status"] == agents.CONFIRMED
    assert agents.check_agent("Наработка равна 6 часов [1].", [ranged])["status"] == agents.CONFIRMED
    assert agents.check_agent("Наработка равна 10 часов [1].", [ranged])["status"] == agents.CONFIRMED
    assert agents.check_agent("Смена равна 8 часов [1].", [shift])["status"] == agents.CONFIRMED
    assert agents.check_agent("Смена равна 18 часов [1].", [shift])["status"] == agents.CONFIRMED
    assert agents.check_agent("Срок службы равен 6 часов [1].", [life])["status"] == agents.CONFIRMED
    assert agents.check_agent("Срок службы равен 10 часов [1].", [life])["status"] == agents.CONFIRMED
    assert agents.check_agent("Время работы составляет 6 часов [1].", [worked])["status"] == agents.CONFIRMED
    assert agents.check_agent("Время работы составляет 10 часов [1].", [worked])["status"] == agents.CONFIRMED
    assert agents.check_agent("Количество равно 6 часов [1].", [counted])["status"] == agents.CONFIRMED
    assert agents.check_agent("Количество равно 10 часов [1].", [counted])["status"] == agents.CONFIRMED
    assert agents.check_agent("Ресурс равен 6 часов [1].", [resource])["status"] == agents.CONFIRMED
    assert agents.check_agent("Ресурс равен 10 часов [1].", [resource])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 8 бар [1].", [bars])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 18 бар [1].", [bars])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 8 бар [1].", [bare])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 18 бар [1].", [bare])["status"] == agents.CONFIRMED


def test_check_rejects_an_hour_range_through_po_taken_as_its_measurement():
    window = {"text": "Давление с 8 по 18 часов составляет 6 бар.", "document_name": "pump.md"}
    leading = {"text": "С 8 по 18 часов рабочее давление: 6 бар.", "document_name": "pump.md"}
    short = {"text": "Рабочее давление с 8 по 18 ч составляет 6 бар.", "document_name": "pump.md"}
    dotted = {"text": "Рабочее давление с 8 по 18 ч. составляет 6 бар.", "document_name": "pump.md"}
    during = {"text": "Давление от 6 по 10 часов составляет 16 бар.", "document_name": "pump.md"}
    heated = {"text": "Температура с 8 по 18 часов составила 80 градусов.", "document_name": "pump.md"}
    minutes = {"text": "Давление с 8 по 18 часов 30 минут составляет 6 бар.", "document_name": "pump.md"}
    brief = {"text": "Давление с 8 по 18 ч 30 мин составляет 6 бар.", "document_name": "pump.md"}
    midnight = {"text": "Давление с 0 по 6 часов составляет 10 бар.", "document_name": "pump.md"}
    each = {"text": "Давление по 6 часов составляет 10 бар.", "document_name": "pump.md"}
    ranged = {"text": "Наработка с 8 по 18 часов.", "document_name": "pump.md"}
    shift = {"text": "Смена с 8 по 18 часов.", "document_name": "pump.md"}
    life = {"text": "Срок службы от 6 по 10 часов.", "document_name": "pump.md"}
    worked = {"text": "Время работы с 8 по 18 часов.", "document_name": "pump.md"}
    counted = {"text": "Количество от 6 по 10 часов.", "document_name": "pump.md"}
    resource = {"text": "Ресурс с 8 по 18 часов.", "document_name": "pump.md"}
    lasted = {"text": "Время с 8 по 18 часов 30 минут.", "document_name": "pump.md"}
    per = {"text": "Наработка по 6 часов.", "document_name": "pump.md"}
    bars = {"text": "Давление с 8 по 18 бар.", "document_name": "pump.md"}
    bare = {"text": "Давление с 8 по 18.", "document_name": "pump.md"}
    part = {"text": "Давление по 6 часть составляет 10 бар.", "document_name": "pump.md"}
    assert agents.check_agent("Давление равно 8 бар [1].", [window])["missing"] == ["8"]
    assert agents.check_agent("Давление равно 18 бар [1].", [window])["missing"] == ["18"]
    assert agents.check_agent("Давление равно 6 бар [1].", [window])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 8 бар [1].", [leading])["missing"] == ["8"]
    assert agents.check_agent("Рабочее давление равно 18 бар [1].", [leading])["missing"] == ["18"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [leading])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 8 бар [1].", [short])["missing"] == ["8"]
    assert agents.check_agent("Рабочее давление равно 18 бар [1].", [short])["missing"] == ["18"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [short])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 8 бар [1].", [dotted])["missing"] == ["8"]
    assert agents.check_agent("Рабочее давление равно 18 бар [1].", [dotted])["missing"] == ["18"]
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [dotted])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 6 бар [1].", [during])["missing"] == ["6"]
    assert agents.check_agent("Давление равно 10 бар [1].", [during])["missing"] == ["10"]
    assert agents.check_agent("Давление равно 16 бар [1].", [during])["status"] == agents.CONFIRMED
    assert agents.check_agent("Температура равна 8 градусов [1].", [heated])["missing"] == ["8"]
    assert agents.check_agent("Температура равна 18 градусов [1].", [heated])["missing"] == ["18"]
    assert agents.check_agent("Температура равна 80 градусов [1].", [heated])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 8 бар [1].", [minutes])["missing"] == ["8"]
    assert agents.check_agent("Давление равно 18 бар [1].", [minutes])["missing"] == ["18"]
    assert agents.check_agent("Давление равно 30 бар [1].", [minutes])["missing"] == ["30"]
    assert agents.check_agent("Давление равно 6 бар [1].", [minutes])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 8 бар [1].", [brief])["missing"] == ["8"]
    assert agents.check_agent("Давление равно 18 бар [1].", [brief])["missing"] == ["18"]
    assert agents.check_agent("Давление равно 30 бар [1].", [brief])["missing"] == ["30"]
    assert agents.check_agent("Давление равно 6 бар [1].", [brief])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 0 бар [1].", [midnight])["missing"] == ["0"]
    assert agents.check_agent("Давление равно 6 бар [1].", [midnight])["missing"] == ["6"]
    assert agents.check_agent("Давление равно 10 бар [1].", [midnight])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 6 бар [1].", [each])["missing"] == ["6"]
    assert agents.check_agent("Давление равно 10 бар [1].", [each])["status"] == agents.CONFIRMED
    assert agents.check_agent("Наработка равна 8 часов [1].", [ranged])["status"] == agents.CONFIRMED
    assert agents.check_agent("Наработка равна 18 часов [1].", [ranged])["status"] == agents.CONFIRMED
    assert agents.check_agent("Смена равна 8 часов [1].", [shift])["status"] == agents.CONFIRMED
    assert agents.check_agent("Смена равна 18 часов [1].", [shift])["status"] == agents.CONFIRMED
    assert agents.check_agent("Срок службы равен 6 часов [1].", [life])["status"] == agents.CONFIRMED
    assert agents.check_agent("Срок службы равен 10 часов [1].", [life])["status"] == agents.CONFIRMED
    assert agents.check_agent("Время работы составляет 8 часов [1].", [worked])["status"] == agents.CONFIRMED
    assert agents.check_agent("Время работы составляет 18 часов [1].", [worked])["status"] == agents.CONFIRMED
    assert agents.check_agent("Количество равно 6 часов [1].", [counted])["status"] == agents.CONFIRMED
    assert agents.check_agent("Количество равно 10 часов [1].", [counted])["status"] == agents.CONFIRMED
    assert agents.check_agent("Ресурс равен 8 часов [1].", [resource])["status"] == agents.CONFIRMED
    assert agents.check_agent("Ресурс равен 18 часов [1].", [resource])["status"] == agents.CONFIRMED
    assert agents.check_agent("Время равно 8 часов [1].", [lasted])["status"] == agents.CONFIRMED
    assert agents.check_agent("Время равно 18 часов [1].", [lasted])["status"] == agents.CONFIRMED
    assert agents.check_agent("Время равно 30 минут [1].", [lasted])["status"] == agents.CONFIRMED
    assert agents.check_agent("Наработка равна 6 часов [1].", [per])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 8 бар [1].", [bars])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 18 бар [1].", [bars])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 8 бар [1].", [bare])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 18 бар [1].", [bare])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 6 бар [1].", [part])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 10 бар [1].", [part])["missing"] == ["10"]


def test_check_rejects_a_long_number_of_another_value():
    ends = {"text": "Давление на входе: 2000 бар. Давление на выходе: 6000 бар.", "document_name": "pump.md"}
    joined = {"text": "Давление на входе 2000 бар и давление на выходе 6000 бар.", "document_name": "pump.md"}
    limits = {"text": "Минимальное давление: 2000 бар. Максимальное давление: 6000 бар.", "document_name": "pump.md"}
    fluids = {"text": "Давление воды: 2000 бар. Давление масла: 6000 бар.", "document_name": "pump.md"}
    year = {"text": "Насос > Характеристики\nРабочее давление на выходе: 6 бар\nГод выпуска: 2019", "document_name": "pump.md"}
    named = {"text": "Год выпуска: 2019\nРабочее давление: 1600 бар.", "document_name": "pump.md"}
    books = {"text": "Давление на входе: 12 000 бар. Давление на выходе: 6 бар.", "document_name": "pump.md"}
    assert agents.check_agent("На выходе значение равно 2000 бар [1].", [ends])["missing"] == ["2000"]
    assert agents.check_agent("На выходе значение равно 6000 бар [1].", [ends])["status"] == agents.CONFIRMED
    assert agents.check_agent("Показатель на выходе равен 2000 бар [1].", [ends])["missing"] == ["2000"]
    assert agents.check_agent("На выходе значение равно 2000 бар [1].", [joined])["missing"] == ["2000"]
    assert agents.check_agent("На выходе значение равно 6000 бар [1].", [joined])["status"] == agents.CONFIRMED
    assert agents.check_agent("Максимальное значение равно 2000 бар [1].", [limits])["missing"] == ["2000"]
    assert agents.check_agent("Максимальное значение равно 6000 бар [1].", [limits])["status"] == agents.CONFIRMED
    assert agents.check_agent("Минимальное значение равно 2000 бар [1].", [limits])["status"] == agents.CONFIRMED
    assert agents.check_agent("Значение масла равно 2000 бар [1].", [fluids])["missing"] == ["2000"]
    assert agents.check_agent("Значение масла равно 6000 бар [1].", [fluids])["status"] == agents.CONFIRMED
    assert agents.check_agent("На выходе значение равно 2019 бар [1].", [year])["missing"] == ["2019"]
    assert agents.check_agent("На выходе значение равно 6 бар [1].", [year])["status"] == agents.CONFIRMED
    assert agents.check_agent("По данным завода 2019 — рабочее давление [1].", [named])["missing"] == ["2019"]
    assert agents.check_agent("По данным завода 1600 — рабочее давление [1].", [named])["status"] == agents.CONFIRMED
    assert agents.check_agent("2019 — год выпуска [1].", [named])["status"] == agents.CONFIRMED
    assert agents.check_agent("На выходе значение равно 12 000 бар [1].", [books])["missing"] == ["12 000"]
    assert agents.check_agent("На выходе значение равно 6 бар [1].", [books])["status"] == agents.CONFIRMED


def test_check_rejects_a_grouped_or_signed_number_of_another_value():
    ends = {"text": "Давление на входе: 12 000 бар. Давление на выходе: 6 бар.", "document_name": "pump.md"}
    both = {"text": "Давление на входе: 12 000 бар. Давление на выходе: 16 000 бар.", "document_name": "pump.md"}
    joined = {"text": "Давление на входе 12 000 бар и давление на выходе 16 000 бар.", "document_name": "pump.md"}
    limits = {"text": "Минимальное давление: 12 000 бар. Максимальное давление: 16 000 бар.", "document_name": "pump.md"}
    fluids = {"text": "Давление воды: 12 000 бар. Давление масла: 6 бар.", "document_name": "pump.md"}
    duties = {"text": "Испытательное давление: 12 000 бар.\nРабочее давление: 6 бар.", "document_name": "pump.md"}
    radii = {"text": "Радиус крышки: 12 000 мм. Радиус поршня: 80 мм.", "document_name": "pump.md"}
    strokes = {"text": "Ход поршня: 12 000 мм. Ход клапана: 40 мм.", "document_name": "pump.md"}
    ranged = {"text": "Давление от 12 000 до 16 000 бар.", "document_name": "pump.md"}
    decimal = {"text": "Давление на входе: 12 000,5 бар. Давление на выходе: 6 бар.", "document_name": "pump.md"}
    signed = {"text": "Давление на входе: -12 бар. Давление на выходе: 6 бар.", "document_name": "pump.md"}
    minus = {"text": "Давление на входе: −12 бар. Давление на выходе: 6 бар.", "document_name": "pump.md"}
    word = {"text": "Давление на входе: минус 12 бар. Давление на выходе: 6 бар.", "document_name": "pump.md"}
    assert agents.check_agent("Давление на выходе равно 12 000 бар [1].", [ends])["missing"] == ["12 000"]
    assert agents.check_agent("Давление на выходе равно 6 бар [1].", [ends])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на входе равно 12 000 бар [1].", [ends])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на выходе равно 12 000 бар [1].", [both])["missing"] == ["12 000"]
    assert agents.check_agent("Давление на входе равно 16 000 бар [1].", [both])["missing"] == ["16 000"]
    assert agents.check_agent("Давление на выходе равно 16 000 бар [1].", [both])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на входе равно 12 000 бар [1].", [both])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на выходе равно 12 000 бар [1].", [joined])["missing"] == ["12 000"]
    assert agents.check_agent("Давление на выходе равно 16 000 бар [1].", [joined])["status"] == agents.CONFIRMED
    assert agents.check_agent("Максимальное давление равно 12 000 бар [1].", [limits])["missing"] == ["12 000"]
    assert agents.check_agent("Минимальное давление равно 16 000 бар [1].", [limits])["missing"] == ["16 000"]
    assert agents.check_agent("Максимальное давление равно 16 000 бар [1].", [limits])["status"] == agents.CONFIRMED
    assert agents.check_agent("Минимальное давление равно 12 000 бар [1].", [limits])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление масла равно 12 000 бар [1].", [fluids])["missing"] == ["12 000"]
    assert agents.check_agent("Давление воды равно 12 000 бар [1].", [fluids])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление масла равно 6 бар [1].", [fluids])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 12 000 бар [1].", [duties])["missing"] == ["12 000"]
    assert agents.check_agent("Испытательное давление равно 12 000 бар [1].", [duties])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [duties])["status"] == agents.CONFIRMED
    assert agents.check_agent("Радиус поршня равен 12 000 мм [1].", [radii])["missing"] == ["12 000"]
    assert agents.check_agent("Радиус крышки равен 12 000 мм [1].", [radii])["status"] == agents.CONFIRMED
    assert agents.check_agent("Радиус поршня равен 80 мм [1].", [radii])["status"] == agents.CONFIRMED
    assert agents.check_agent("Ход клапана равен 12 000 мм [1].", [strokes])["missing"] == ["12 000"]
    assert agents.check_agent("Ход поршня равен 12 000 мм [1].", [strokes])["status"] == agents.CONFIRMED
    assert agents.check_agent("Ход клапана равен 40 мм [1].", [strokes])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 12 000 бар [1].", [ranged])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 16 000 бар [1].", [ranged])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на выходе равно 12 000,5 бар [1].", [decimal])["missing"] == ["12 000,5"]
    assert agents.check_agent("Давление на входе равно 12 000,5 бар [1].", [decimal])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на выходе равно 6 бар [1].", [decimal])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на выходе равно -12 бар [1].", [signed])["missing"] == ["-12"]
    assert agents.check_agent("Давление на входе равно -12 бар [1].", [signed])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на выходе равно 6 бар [1].", [signed])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на выходе равно −12 бар [1].", [minus])["missing"] == ["-12"]
    assert agents.check_agent("Давление на входе равно −12 бар [1].", [minus])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на выходе равно минус 12 бар [1].", [word])["missing"] == ["-12"]
    assert agents.check_agent("Давление на входе равно минус 12 бар [1].", [word])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на выходе равно 6 бар [1].", [word])["status"] == agents.CONFIRMED


def test_check_rejects_a_qualifier_written_after_the_number():
    ends = {"text": "Давление 2 бар на входе и 6 бар на выходе.", "document_name": "pump.md"}
    stated = {"text": "Давление составляет 2 бар на входе и 6 бар на выходе.", "document_name": "pump.md"}
    paren = {"text": "Давление 6 бар (на входе) и 16 бар (на выходе).", "document_name": "pump.md"}
    limits = {"text": "Давление 6 бар минимальное и 16 бар максимальное.", "document_name": "pump.md"}
    grouped = {"text": "Давление 12 000 бар на входе и 6 бар на выходе.", "document_name": "pump.md"}
    signed = {"text": "Давление -12 бар на входе и 6 бар на выходе.", "document_name": "pump.md"}
    carried = {"text": "Максимальное давление 16 бар и 6 бар.", "document_name": "pump.md"}
    assert agents.check_agent("Давление на входе равно 6 бар [1].", [ends])["missing"] == ["6"]
    assert agents.check_agent("Давление на выходе равно 2 бар [1].", [ends])["missing"] == ["2"]
    assert agents.check_agent("Давление на входе равно 2 бар [1].", [ends])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на выходе равно 6 бар [1].", [ends])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на входе равно 6 бар [1].", [stated])["missing"] == ["6"]
    assert agents.check_agent("Давление на входе равно 2 бар [1].", [stated])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на выходе равно 6 бар [1].", [stated])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на входе равно 16 бар [1].", [paren])["missing"] == ["16"]
    assert agents.check_agent("Давление на выходе равно 6 бар [1].", [paren])["missing"] == ["6"]
    assert agents.check_agent("Давление на входе равно 6 бар [1].", [paren])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на выходе равно 16 бар [1].", [paren])["status"] == agents.CONFIRMED
    assert agents.check_agent("Максимальное давление равно 6 бар [1].", [limits])["missing"] == ["6"]
    assert agents.check_agent("Минимальное давление равно 16 бар [1].", [limits])["missing"] == ["16"]
    assert agents.check_agent("Минимальное давление равно 6 бар [1].", [limits])["status"] == agents.CONFIRMED
    assert agents.check_agent("Максимальное давление равно 16 бар [1].", [limits])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на входе равно 6 бар [1].", [grouped])["missing"] == ["6"]
    assert agents.check_agent("Давление на выходе равно 12 000 бар [1].", [grouped])["missing"] == ["12 000"]
    assert agents.check_agent("Давление на входе равно 12 000 бар [1].", [grouped])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на выходе равно 6 бар [1].", [grouped])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на входе равно 6 бар [1].", [signed])["missing"] == ["6"]
    assert agents.check_agent("Давление на выходе равно -12 бар [1].", [signed])["missing"] == ["-12"]
    assert agents.check_agent("Давление на входе равно -12 бар [1].", [signed])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на выходе равно 6 бар [1].", [signed])["status"] == agents.CONFIRMED
    assert agents.check_agent("Максимальное давление равно 16 бар [1].", [carried])["status"] == agents.CONFIRMED
    assert agents.check_agent("Максимальное давление равно 6 бар [1].", [carried])["status"] == agents.CONFIRMED


def test_check_rejects_a_value_whose_clause_drops_the_measurement():
    split = {"text": "На входе давление: 2 бар; на выходе: 6 бар.", "document_name": "pump.md"}
    comma = {"text": "Давление на входе: 2 бар, на выходе: 6 бар.", "document_name": "pump.md"}
    period = {"text": "Давление на входе 2 бар. На выходе 6 бар.", "document_name": "pump.md"}
    limits = {"text": "Давление 6 бар минимальное; 16 бар максимальное.", "document_name": "pump.md"}
    fluids = {"text": "Давление воды: 6 бар. Масла: 16 бар.", "document_name": "pump.md"}
    radius = {"text": "Радиус крышки: 40 мм. Поршня: 80 мм.", "document_name": "pump.md"}
    grouped = {"text": "Давление на входе: 12 000 бар; на выходе: 6 бар.", "document_name": "pump.md"}
    pump = {"text": "Насос №4. Давление 6 бар.", "document_name": "pump.md"}
    heated = {"text": "Рабочая температура: 80 градусов.\nДавление: 6 бар.", "document_name": "pump.md"}
    counted = {"text": "В цехе 4 насоса; давление 8 бар.", "document_name": "pump.md"}
    assert agents.check_agent("Давление на выходе равно 2 бар [1].", [split])["missing"] == ["2"]
    assert agents.check_agent("Давление на входе равно 6 бар [1].", [split])["missing"] == ["6"]
    assert agents.check_agent("Давление на входе равно 2 бар [1].", [split])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на выходе равно 6 бар [1].", [split])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на выходе равно 2 бар [1].", [comma])["missing"] == ["2"]
    assert agents.check_agent("Давление на входе равно 2 бар [1].", [comma])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на выходе равно 6 бар [1].", [comma])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на выходе равно 2 бар [1].", [period])["missing"] == ["2"]
    assert agents.check_agent("Давление на входе равно 2 бар [1].", [period])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на выходе равно 6 бар [1].", [period])["status"] == agents.CONFIRMED
    assert agents.check_agent("Максимальное давление равно 6 бар [1].", [limits])["missing"] == ["6"]
    assert agents.check_agent("Минимальное давление равно 16 бар [1].", [limits])["missing"] == ["16"]
    assert agents.check_agent("Минимальное давление равно 6 бар [1].", [limits])["status"] == agents.CONFIRMED
    assert agents.check_agent("Максимальное давление равно 16 бар [1].", [limits])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление масла равно 6 бар [1].", [fluids])["missing"] == ["6"]
    assert agents.check_agent("Давление воды равно 16 бар [1].", [fluids])["missing"] == ["16"]
    assert agents.check_agent("Давление воды равно 6 бар [1].", [fluids])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление масла равно 16 бар [1].", [fluids])["status"] == agents.CONFIRMED
    assert agents.check_agent("Радиус поршня равен 40 мм [1].", [radius])["missing"] == ["40"]
    assert agents.check_agent("Радиус крышки равен 40 мм [1].", [radius])["status"] == agents.CONFIRMED
    assert agents.check_agent("Радиус поршня равен 80 мм [1].", [radius])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на выходе равно 12 000 бар [1].", [grouped])["missing"] == ["12 000"]
    assert agents.check_agent("Давление на входе равно 12 000 бар [1].", [grouped])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление на выходе равно 6 бар [1].", [grouped])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление насоса равно 6 бар [1].", [pump])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 6 бар [1].", [heated])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 80 бар [1].", [heated])["missing"] == ["80"]
    assert agents.check_agent("Давление равно 8 бар [1].", [counted])["status"] == agents.CONFIRMED
    assert agents.check_agent("Давление равно 4 бар [1].", [counted])["missing"] == ["4"]


def test_check_rejects_three_digit_number_from_another_line():
    chunk = {"text": "Насос > Характеристики\nРабочее давление: 6 бар\nИнвентарный номер: 180", "document_name": "pump.md"}
    real = {"text": "Насос > Характеристики\nРабочее давление: 160 бар\nНомер: 12", "document_name": "pump.md"}
    wrong = agents.check_agent("Рабочее давление насоса равно 180 бар [1].", [chunk])
    assert wrong["status"] == agents.UNCONFIRMED
    assert wrong["missing"] == ["180"]
    assert agents.check_agent("Инвентарный номер насоса равен 180 [1].", [chunk])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление насоса равно 160 бар [1].", [real])["status"] == agents.CONFIRMED


def test_check_fixes_wrong_citation():
    verdict = agents.check_agent("Насос выпущен в 2019 году [2].", [PUMP, SHOP])
    assert verdict["status"] == agents.CONFIRMED
    assert [source["number"] for source in verdict["sources"]] == [1]


def test_check_allows_names_from_question():
    verdict = agents.check_agent("Давление насоса ХН-7 равно 6 бар [1].", [PUMP], "Какое давление у насоса ХН-7?")
    assert verdict["status"] == agents.CONFIRMED


def test_check_refuses_when_question_names_unknown_thing():
    verdict = agents.check_agent("В насосе используется версия 2019 [1].", [PUMP], "Какая версия Python в насосе?", known=lambda term: term != "python")
    assert verdict["status"] == agents.MISSING


def test_check_rejects_yes_when_fragment_negates():
    chunk = {"text": "Охлаждение насоса не требуется. Давление равно 6 бар.", "document_name": "pump.md"}
    assert agents.check_agent("Да, охлаждение требуется [1].", [chunk], "Требуется ли охлаждение насоса?")["feedback"] == agents.INVERT
    assert agents.check_agent("Нет, охлаждение не требуется [1].", [chunk], "Требуется ли охлаждение насоса?")["status"] == agents.CONFIRMED
    absent = {"text": "Фильтра нет.", "document_name": "pump.md"}
    assert agents.check_agent("Да, фильтр есть [1].", [absent], "Есть ли фильтр?")["feedback"] == agents.INVERT
    assert agents.check_agent("Нет, фильтра нет [1].", [absent], "Есть ли фильтр?")["status"] == agents.CONFIRMED
    cooling = {"text": "Охлаждение требуется.", "document_name": "pump.md"}
    other = {"text": "Замена фильтра не требуется.", "document_name": "filter.md"}
    assert agents.check_agent("Да, охлаждение требуется [1].", [cooling, other], "Требуется ли охлаждение?")["status"] == agents.CONFIRMED
    assert agents.check_agent("Нет, охлаждение не требуется [2].", [cooling, other], "Требуется ли охлаждение?")["feedback"] == agents.INVERT
    library = {"text": "Запись заранее не нужна. Вход свободный.", "document_name": "rules.md"}
    assert agents.check_agent("Да, записываться заранее нужно [1].", [library], "Нужно ли записываться заранее?")["feedback"] == agents.INVERT
    assert agents.check_agent("Нет, запись заранее не нужна [1].", [library], "Нужно ли записываться заранее?")["status"] == agents.CONFIRMED
    permit = {"text": "Допуск не нужен. Вход свободный.", "document_name": "rules.md"}
    assert agents.check_agent("Да, допуск нужен [1].", [permit], "Нужно ли получать допуск?")["feedback"] == agents.INVERT
    assert agents.check_agent("Нет, допуск не нужен [1].", [permit], "Нужно ли получать допуск?")["status"] == agents.CONFIRMED
    installed = {"text": "Фильтр установлен на входе. Запасного насоса нет.", "document_name": "pump.md"}
    assert agents.check_agent("Да, фильтр есть [1].", [installed], "Есть ли фильтр у насоса?")["status"] == agents.CONFIRMED
    assert agents.check_agent("Нет, фильтра нет [1].", [installed], "Есть ли фильтр у насоса?")["feedback"] == agents.INVERT


def test_check_rejects_incomplete_list():
    chunk = {"text": "Цех > Смены\nРазных значений в столбце «Смена»: 3. Список: Утренняя, Дневная, Ночная.", "document_name": "charter.txt"}
    assert agents.check_agent("В цехе есть Утренняя и Дневная смены [1].", [chunk], "Какие смены есть в цехе?")["feedback"] == agents.LIST_GAP
    assert agents.check_agent("В цехе 3 смены: Утренняя и Дневная [1].", [chunk], "Какие смены есть в цехе?")["feedback"] == agents.LIST_GAP
    assert agents.check_agent("В цехе 13 смен [1].", [chunk], "Сколько смен в цехе?")["feedback"] == agents.LIST_GAP
    assert agents.check_agent("В цехе три смены: Утренняя, Дневная и Ночная [1].", [chunk], "Какие смены есть в цехе?")["status"] == agents.CONFIRMED
    assert agents.check_agent("3 значений [1].", [chunk], "Сколько смен в цехе?")["status"] == agents.CONFIRMED


def test_check_list_uses_cited_fragment_only():
    halls = {"text": "Залы\nРазных значений в столбце «Зал»: 3. Список: Читальный, Детский, Архивный.", "document_name": "library.txt"}
    other = {"text": "Шины\nРазных значений в столбце «Шина»: 2. Список: ALPHA, BETA.", "document_name": "bus.txt"}
    verdict = agents.check_agent("Читальный, Детский, Архивный [1].", [halls, other], "Какие залы есть в библиотеке?")
    assert verdict["status"] == agents.CONFIRMED


def test_check_rejects_empty_and_broken_answers():
    copied = "Цех имеет номер 4, в нём работают токари, слесари и наладчики, мастер цеха — Иванов, смена длится восемь часов, обед начинается в полдень и длится один час, склад находится рядом с цехом на первом этаже."
    shop = {"text": copied, "document_name": "charter.txt"}
    assert agents.check_agent("Да.", [PUMP])["status"] == agents.UNCONFIRMED
    assert agents.check_agent("Давление 6 бар [5].", [PUMP])["status"] == agents.UNCONFIRMED
    assert agents.check_agent(copied, [shop])["feedback"] == agents.COPIED
    assert agents.check_agent(agents.NO_ANSWER, [PUMP])["status"] == agents.MISSING
