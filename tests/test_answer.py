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


def test_overview_yields_to_feedback(monkeypatch):
    halls = {
        "text": "Библиотека > Залы\nРазных значений в столбце «Зал»: 3. Список: Читальный, Детский, Архивный.",
        "document_name": "library.txt",
    }
    calls = []
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


def test_check_rejects_incomplete_list():
    chunk = {"text": "Цех > Смены\nРазных значений в столбце «Смена»: 3. Список: Утренняя, Дневная, Ночная.", "document_name": "charter.txt"}
    assert agents.check_agent("В цехе есть Утренняя и Дневная смены [1].", [chunk], "Какие смены есть в цехе?")["feedback"] == agents.LIST_GAP
    assert agents.check_agent("В цехе три смены: Утренняя, Дневная и Ночная [1].", [chunk], "Какие смены есть в цехе?")["status"] == agents.CONFIRMED


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
