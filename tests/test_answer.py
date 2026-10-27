import agents

PUMP = {"text": "Насос > Характеристики\nРабочее давление: 6 бар\nГод выпуска: 2019", "document_name": "pump.md", "section": "Насос > Характеристики"}
SHOP = {"text": "Цех имеет номер 4. Мастер цеха — Иванов.", "document_name": "charter.txt", "section": ""}


def _words(text):
    return len(text.split())


def test_answer_refuses_empty_chunks():
    assert agents.answer_agent("цвет", "цвет насоса", [], []) == agents.NO_ANSWER


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


def test_check_rejects_incomplete_list():
    chunk = {"text": "Цех > Смены\nРазных значений в столбце «Смена»: 3. Список: Утренняя, Дневная, Ночная.", "document_name": "charter.txt"}
    assert agents.check_agent("В цехе есть Утренняя и Дневная смены [1].", [chunk], "Какие смены есть в цехе?")["feedback"] == agents.LIST_GAP
    assert agents.check_agent("В цехе три смены: Утренняя, Дневная и Ночная [1].", [chunk], "Какие смены есть в цехе?")["status"] == agents.CONFIRMED


def test_check_rejects_empty_and_broken_answers():
    copied = "Цех имеет номер 4, в нём работают токари, слесари и наладчики, мастер цеха — Иванов, смена длится восемь часов, обед начинается в полдень и длится один час, склад находится рядом с цехом на первом этаже."
    shop = {"text": copied, "document_name": "charter.txt"}
    assert agents.check_agent("Да.", [PUMP])["status"] == agents.UNCONFIRMED
    assert agents.check_agent("Давление 6 бар [5].", [PUMP])["status"] == agents.UNCONFIRMED
    assert agents.check_agent(copied, [shop])["feedback"] == agents.COPIED
    assert agents.check_agent(agents.NO_ANSWER, [PUMP])["status"] == agents.MISSING
