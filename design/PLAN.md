# План работ: редизайн UI (Wave 7)

> Статус: задачи созданы в GitHub (issues #185–#196). Мокапы — `design/mockups/`.
> База для веток — `main`. Ветка: `wave7/<slug>`. Один issue — один PR, минимальный diff.

## Глобальные ограничения (для всех задач)

1. **Один файл, без сборки.** Вся разметка и стили остаются в `src/web/index.html`.
2. **Запрещены `innerHTML` / `insertAdjacentHTML`.** Текст только через `textContent` и
   `createElement` — это проверяет `tests/test_api.py`.
3. **Не ломать поведение** из `docs/ui.md` (подгрузка `/ui`, 401 → форма входа,
   перетаскивание папок, загрузка файлов, режимы «Агент»/«Документы»).
4. **Проверка каждого PR:** `pytest -m "not slow and not holdout"` зелёный.

## Задачи Wave 7 (12 issues)

| # | Задача | Depends on |
|---|---|---|
| #185 | Дизайн-токены и базовая типографика | — |
| #186 | Каркас окна: статус-бар и разделители колонок | #185 |
| #187 | Сайдбар диалогов | #186 |
| #188 | Чат агента | #187 |
| #189 | Дерево документов | #188 |
| #190 | Превью документа | #189 |
| #191 | Каркас панели управления: левая навигация | #186 |
| #192 | Пользователи и роли | #191 |
| #193 | Группы, доступы и журнал | #192 |
| #194 | Вход / первый запуск | #185 |
| #195 | Тёмная тема и переключатель | #194 |
| #196 | Полировка и доступность | #195 |

Детали каждой задачи (что сделать, acceptance criteria, out of scope) — в самих issues.

## Порядок и параллельность

- Строго последовательно внутри цепочки зависимостей.
- После #185 можно параллельно вести три ветви: «чат/дерево» (#187→#190),
  «админка» (#191→#193) и «вход/тема» (#194→#195).
- Метки: `wave-7-ui`, `area-ui`, `type-enhancement`.

## Сверка с API (проверено по `src/api.py`)

Мокап админки ложится на реальные контракты без изменений бэкенда:

| Экран | Эндпоинт | Поля |
| --- | --- | --- |
| Пользователи | `GET/POST /admin/users`, `PATCH/DELETE /admin/users/{id}` | `id`, `login`, `role_id`, `role` (имя), `blocked` |
| Роли | `GET/POST /admin/roles`, `PATCH/DELETE /admin/roles/{id}` | `id`, `name`, `actions[]`, `kb_actions{base_id:[ask,upload,delete,arrange]}`; `GET /admin/roles` также отдаёт `bases:[{id,name}]` |
| Группы | `GET/POST /admin/groups`, `PUT /admin/groups/{id}/members` | `id`, `name`, `user_ids[]`, `role_ids[]` |
| Доступы | `GET /admin/kb` | `bases:[{id,name,acl[],role_actions{},personal{}}]`, `people:[{id,login}]`, `roles:[{id,name}]`, `groups:[{id,name}]`; `acl[]` — `{subject_type,subject_id,effect}` |
| Журнал | `GET /admin/audit` | `events:[{id,time,kind,login,…}]`; фильтры `user,role,group,kind,before,after,before_id`; деталь — `GET /admin/audit/{id}` |

Особенности, которые учитывает редизайн:
- «Журнал» не обновляется по таймеру (каждый просмотр пишет событие) → только кнопка «Обновить».
- `manage_access` нет, но `manage_roles` есть → `GET /admin/kb` отдаёт только имена баз; секция «Доступы» скрывается.
- Статус базы в «Доступах» выводится из `acl` (allow/deny), личные действия — из `personal`.

## Сверка с мокапами

Файлы: `design/mockups/{main,main-dark,documents,admin,login}.html` (+ `.png`),
`design/mockups/style.css`. Реализация должна визуально совпадать с ними.
