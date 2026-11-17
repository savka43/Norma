# Эскиз REST API (рабочий контракт, уточнять по ходу реализации)

Основа: ЛР №1/№2 + принятые расширения пользователя. Префикс: `/api/v1`.

## Реализованная основа API (фаза 1)

| Метод / путь | Поведение |
|---|---|
| `GET /api/v1/health` | `200 {"status":"ok"}`, не зависит от доступности БД |
| `GET /api/v1/health/ready` | `200 {"status":"ok","database":"ok"}` после `SELECT 1`; ошибка/таймаут — `503 {"detail":"Database is unavailable"}` |
| `GET /openapi.json`, `GET /docs` | Схема реализованных маршрутов и Swagger UI |

Healthcheck не требует аутентификации и не раскрывает параметры подключения.
Техническое решение — ADR-005. Приведённые ниже бизнес-маршруты остаются
планируемым контрактом и добавляются по мере реализации соответствующих фаз.

## Планируемые бизнес-маршруты

| Модуль | Метод / путь | Сценарий |
|---|---|---|
| auth | `POST /auth/register` | Студент создаёт аккаунт |
| auth | `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` | Вход и сессия |
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
- Конкретные тела запросов/ответов и scheme auth определить при реализации и покрыть интеграционными тестами; документация описывает намерение, а не уже запущенный API.
