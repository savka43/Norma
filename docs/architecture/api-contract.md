# Эскиз REST API (рабочий контракт, уточнять по ходу реализации)

Основа: ЛР №1/№2 + принятые расширения пользователя. Префикс: `/api/v1`.

## Реализованная основа API (фаза 1)

| Метод / путь | Поведение |
|---|---|
| `GET /api/v1/health` | `200 {"status":"ok"}`, не зависит от доступности БД |
| `GET /api/v1/health/ready` | `200 {"status":"ok","database":"ok"}` после `SELECT 1`; ошибка/таймаут — `503 {"detail":"Database is unavailable"}` |
| `GET /openapi.json`, `GET /docs` | Схема реализованных маршрутов и Swagger UI |

Healthcheck не требует аутентификации и не раскрывает параметры подключения.
Техническое решение — ADR-005.

## Реализованная аутентификация (backend-часть фазы 2)

Все пути ниже имеют префикс `/api/v1`. Для `POST` обязателен заголовок
`X-CSRF-Protection: 1`, иначе `403`. API использует тот же origin, что и клиент;
разрешений CORS нет. Тела register/login — JSON, неизвестные поля запрещены.

| Метод / путь | Запрос и результат |
|---|---|
| `POST /auth/register` | `{email, password, full_name, academic_group}` → `201 UserResponse`; только студент; занятый email → `409` |
| `POST /auth/login` | `{email, password}` → `200 UserResponse` + cookie; неверный email/пароль → одинаковый `401` |
| `GET /auth/me` | Cookie действующей сессии → `200 UserResponse`; отсутствует/отозвана/истекла → `401` |
| `POST /auth/logout` | Отзыв текущей сессии и удаление cookie → `204`; повторный выход также `204` |

`UserResponse`: `id` (UUID), `email`, `full_name`, `role`, `academic_group`,
`position`, `department`, `created_at`. Поля другой роли — `null`; пароль,
хэш пароля и токен не входят в JSON. Регистрация сама не выполняет вход.
Новый пароль — 12–128 символов, пароль входа — 1–128; пароль не обрезается.
Email проверяется синтаксически, сравнение email не учитывает регистр.

Cookie `norma_session` — host-only, `HttpOnly`, `SameSite=Lax`, `Path=/api/v1`.
Срок по умолчанию — 8 часов, настраивается; в HTTPS включается `Secure`.
Повторный вход отзывает предыдущую cookie-сессию этого клиента; сессии других
клиентов остаются независимыми. Login/me/logout используют `Cache-Control: no-store`.
Точные схемы и ограничения — в `/openapi.json`.
При `422` ответ содержит `detail: [{loc, msg, type}]` без исходных входных значений.

Руководитель создаётся только CLI-командой bootstrap, см. `docs/development.md`.
Техническое решение и ограничения — [ADR-007](../decisions/ADR-007-auth-sessions-bootstrap.md).
Остальные бизнес-маршруты добавляются по мере реализации фаз.

## Реализованные группы и поиск студентов (backend-часть фазы 2)

Префикс `/api/v1`, все маршруты требуют сессии руководителя: без неё `401`,
студенту `403`. Для `POST` обязателен `X-CSRF-Protection: 1`.

| Метод / путь | Запрос и результат |
|---|---|
| `POST /supervisor-groups` | `{name, academic_year}` → `201 GroupResponse`; владелец — текущий руководитель |
| `GET /supervisor-groups` | Только свои группы → `200 GroupPage` |
| `GET /supervisor-groups/{group_id}` | `200 GroupResponse`; чужая/отсутствующая группа → `404` |
| `GET /supervisor-groups/{group_id}/students` | Состав своей группы → `200 StudentPage`; чужая/отсутствующая → `404` |
| `POST /supervisor-groups/{group_id}/students` | `{student_id: UUID}` → `201 {student_id, group_id, joined_at}`; студент не найден/другая роль → `404`; уже в любой группе → `409` |
| `GET /students?query=...` | Поиск свободных зарегистрированных студентов → `200 StudentPage` |

`GroupResponse`: `id`, `supervisor_id`, `name`, `academic_year`, `created_at`.
`academic_year` — целое число начала учебного года: `2026` для 2026/2027,
диапазон 1–9998; имя — 1–255 символов после обрезки краёв. Неизвестные поля
в телах запросов запрещены. Группа сначала создаётся пустой.

`GroupPage` и `StudentPage`: `{items, limit, offset}`. Элемент студента содержит
только `id`, `full_name`, `email`, `academic_group`; без роли, пароля/хэша,
чужого руководителя/группы. Поиск исключает уже назначенных студентов,
ищет буквальную подстроку ФИО/email без учёта регистра; `query` — 3–100 символов
после обрезки краёв, обязателен. После добавления студент доступен в составе
своей группы, в поиске свободных больше не выводится.

Пагинация: `limit=20` (1–50) для поиска, `limit=50` (1–100) для групп/состава;
`offset=0` (0..2^63−1). Группы сортируются по времени создания/UUID по убыванию,
студенты — по ФИО/UUID по возрастанию. GET-ответы используют `Cache-Control: no-store`.
Невалидные тела/параметры — `422`; повторное и конкурентное назначение студента
не меняет его исходную группу. Удаление и перенос пока не реализованы.
Техническое решение — [ADR-008](../decisions/ADR-008-supervisor-groups.md).

## Реализованные ВКР и настройка этапов (первый backend-инкремент фазы 3)

Префикс `/api/v1`, cookie-сессии и CSRF — как выше. Студент читает только свою
ВКР/этапы/историю; руководитель — назначенные ему ВКР. Чужая и отсутствующая
сущность одинаково дают `404`. Изменения требуют руководителя (`403` студенту).

| Метод / путь | Запрос и результат |
|---|---|
| `POST /theses` | `{student_id, title, start_date, due_date}` → `201 ThesisResponse`; только студент своей группы; недоступный/свободный → `404`, ВКР уже есть → `409` |
| `GET /theses` | Только доступные ВКР → `{items, limit, offset}` |
| `GET /theses/{thesis_id}` | Метаданные, ревизия плана и вычисленный прогресс → `ThesisResponse` |
| `GET /theses/{thesis_id}/stages` | Весь упорядоченный план → `{items: StageResponse[], revision, as_of_date}` |
| `POST /theses/{thesis_id}/stages` | `{name, position, due_date, expected_revision}` → `201`, весь обновлённый план с ревизией |
| `PATCH /stages/{stage_id}` | Те же обязательные поля → `200`, весь обновлённый план с ревизией; UUID этапа сохраняется |
| `GET /stages/{stage_id}/history` | История настройки этапа → `{items, limit, offset}` |
| `GET /supervisor-groups/{group_id}/progress` | Только руководитель своей группы → `{items: [{student, thesis, stages}], limit, offset, as_of_date}` |

`ThesisResponse`: `id`, `student_id`, `supervisor_id`, `title`, `start_date`,
`due_date`, `revision`, `created_at`, `total_stages`, `completed_stages`,
`progress_percent`, `overdue_stages`, `is_overdue`, `as_of_date`.
Тема — 1–500 символов после обрезки краёв; общий срок не раньше начала.
Владелец — из сессии, одна ВКР на студента, ревизия нового плана — 1.
Отдельного общего статуса ВКР и изменения её метаданных пока нет.

`StageResponse`: `id`, `thesis_id`, `name`, `position`, `due_date`, `status`,
`created_at`, `is_overdue`. Имя — 1–255 символов после обрезки краёв.
Позиции — целые `1..N`, при вставке допускается `N+1`; перенос/вставка атомарно
сдвигает остальные позиции. Срок этапа входит в интервал дат ВКР включительно.
Все этапы обязательны, начальный статус — `in_progress`. Передать `status`,
`weight`, `required` или иные посторонние поля нельзя (`422`).

Изменение получает текущую `expected_revision` ВКР; устаревшая ревизия — `409`
без перезаписи. Фактическая правка увеличивает ревизию на 1; актуальный PATCH
без изменений её сохраняет. При наличии этапа `in_review` или `completed`
настройка всего плана временно закрыта (`409`); удаление этапов не реализовано.
История содержит `id`, `stage_id`, `actor_id`, `thesis_revision`, `kind`
(`created|updated`), `before`, `after`, `created_at`; снимки содержат имя,
позицию, срок и статус. История включает сдвиги соседних этапов при перестановке.

Прогресс — `100 * completed / total`; если этапов нет, `progress_percent: null`.
Просрочка — дата срока строго раньше `as_of_date` (текущая дата UTC), завершённые
этапы исключены. `is_overdue` ВКР сравнивает её общий срок с той же датой, пока
не завершены все этапы. Нулевой план не считается завершением.
Сводка включает студентов без ВКР (`thesis: null`, `stages: []`).
План возвращается целиком; списки ВКР, студентов в сводке и событий истории:
`limit=50` (1–100), `offset=0` (0..2^63−1). ВКР — создание/UUID по убыванию,
сводка — ФИО/UUID по возрастанию, история — ревизия по возрастанию.
GET используют `Cache-Control: no-store`.

Отправка, возврат и подтверждение пока **не реализованы**: они должны ссылаться
на неизменяемую версию документа (фазы 4/6). Текущая история — история настройки,
не решения по проверке. Подробности — [ADR-009](../decisions/ADR-009-thesis-stage-planning.md).

## Планируемые бизнес-маршруты

| Модуль | Метод / путь | Сценарий |
|---|---|---|
| stages | `POST /stages/{id}/submit` | `in_progress/changes_requested → in_review`, immutable `DocumentVersion` |
| stages | `POST /stages/{id}/request-changes` | `in_review → changes_requested`, комментарии остаются в истории |
| stages | `POST /stages/{id}/confirm` | `in_review → completed`, только руководитель |
| stages | Расширение `GET /stages/{id}/history` | История отправок и решений вместе с версиями документа |
| documents | `GET /theses/{id}/document` | Lexical JSON + revision + template |
| documents | `PUT /documents/{id}` | Autosave, `expected_revision`, lease |
| documents | `POST /documents/{id}/edit-lease`, `/edit-lease/renew`, `DELETE /documents/{id}/edit-lease` | Последовательный редактор |
| documents | `POST /documents/{id}/import` | UC-01: DOCX → Lexical + warnings; оригинал сохраняется |
| documents | `GET/POST /documents/{id}/versions` | История/контрольные версии |
| documents | `GET /document-versions/{id}` | Снимок без изменения |
| documents | `GET /documents/{id}/diff?base={version_id}&target={version_id}` | UC-06, подсветка added/removed/changed |
| comments | `GET /document-versions/{id}/comments?include_resolved=false` | Замечания с фильтрацией |
| comments | `POST /document-versions/{id}/comments`, `PATCH /comments/{id}` | UC-10, статус/цитата/anchor |
| formatting | `GET/POST /formatting-templates` | Шаблоны оформления |
| formatting | `GET /formatting-templates/{id}/versions` | История неизменяемых параметров |
| formatting | `POST /document-versions/{id}/format-check` | Проверка по snapshot шаблона |
| formatting | `POST /document-versions/{id}/exports` | UC-02, DOCX/PDF |
| plagiarism | `POST /document-versions/{id}/plagiarism-checks` | UC-03, создать долговечное задание |
| plagiarism | `GET /plagiarism-checks/{id}`, `GET /plagiarism-checks/{id}/report` | Статус и отчёт при доступности |

## Соглашения

- Pydantic-схемы на backend; TS типы клиентской части строго соответствуют OpenAPI.
- Разделение по ролям и ownership проверяется на сервере для **каждого** endpoint.
- `403` — нет прав, `404` — не найдено, `409` — конфликт ревизий/правил перехода/блокировки, `422` — невалидные данные.
- `PUT /documents/{id}` получает `expected_revision` и контент с версией схемы. Нельзя молча перезаписывать содержимое при `409`.
- Сохранённые версии immutable; получение diff не меняет их. Отправка этапа связывает `stage_id`, `submitted_version_id`, актёра и время.
- Вызовы API «Антиплагиат» выполняются долговечным worker; `POST` не ждёт синхронного процента. Повторы после ошибки вручную.
- Лимиты API и поддерживаемые виды отчётов неизвестны для конкретного тестового аккаунта: не выдумывать числа.
- Тела будущих бизнес-запросов/ответов уточняются при реализации и покрываются интеграционными тестами; реализованные auth, health, группы, поиск, ВКР и настройка этапов описаны выше.
