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
Остальные бизнес-маршруты ниже добавляются по мере реализации фаз.

## Планируемые бизнес-маршруты

| Модуль | Метод / путь | Сценарий |
|---|---|---|
| users | `GET /students?query=...` | Поиск зарегистрированного студента руководителем с ограничением выдаваемых данных |
| supervisor_groups | `GET/POST /supervisor-groups` | UC-07 |
| supervisor_groups | `POST /supervisor-groups/{id}/students` | Добавить зарегистрированного студента, UC-07 |
| theses | `GET /theses`, `GET /theses/{id}` | ВКР / доступ по роли |
| stages | `GET/POST /theses/{id}/stages`, `PATCH /stages/{id}` | UC-08, сроки и порядок |
| stages | `POST /stages/{id}/submit` | `in_progress/changes_requested → in_review`, immutable `DocumentVersion` |
| stages | `POST /stages/{id}/request-changes` | `in_review → changes_requested`, комментарии остаются в истории |
| stages | `POST /stages/{id}/confirm` | `in_review → completed`, только руководитель |
| stages | `GET /stages/{id}/history` | История отправок и решений |
| stages | `GET /supervisor-groups/{id}/progress` | UC-12, completed/total |
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
- Тела будущих бизнес-запросов/ответов уточняются при реализации и покрываются интеграционными тестами; auth и health описаны выше как реализованные.
