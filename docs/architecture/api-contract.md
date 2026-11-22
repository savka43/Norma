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

## Реализованные документы и шаблоны (backend-инкремент фазы 4)

Все пути под `/api/v1`. Чтение документа/контрольных версий — только студенту
своей ВКР и её руководителю; изменения — только студенту своей ВКР (`403`
руководителю). Чужая/отсутствующая сущность — `404`, без сессии — `401`.
Для мутаций требуется `X-CSRF-Protection: 1`; документы возвращают `no-store`.

| Метод / путь | Запрос и результат |
|---|---|
| `POST /theses/{thesis_id}/document` | `{template_version_id}` → `201 DocumentResponse`; пустой абзац, ревизия 1; повтор → `409` |
| `GET /theses/{thesis_id}/document`, `GET /documents/{document_id}` | `200 DocumentResponse`, GET ничего не создаёт |
| `PUT /documents/{document_id}` | `{content, schema_version, template_version_id, expected_revision}` + `X-Edit-Lease` → `200 DocumentResponse`, ревизия +1 |
| `POST /documents/{document_id}/edit-lease` | Без тела → `201 LeaseResponse`; действующая аренда → `409`, даже в другой вкладке того же студента |
| `POST /documents/{document_id}/edit-lease/renew` | `X-Edit-Lease` → `200 LeaseResponse`; истёкшая/чужая/старая аренда → `409` |
| `DELETE /documents/{document_id}/edit-lease` | `X-Edit-Lease` → `204`; старый UUID не освобождает новую аренду (`409`) |
| `POST /documents/{document_id}/versions` | `{expected_revision, comment?}` + `X-Edit-Lease` → `201 VersionResponse`, снимок рабочего документа |
| `GET /documents/{document_id}/versions` | `{items: VersionSummary[], limit, offset}`; порядок номеров по убыванию, без полного текста в списке |
| `GET /document-versions/{version_id}` | `200 VersionResponse` с неизменяемым JSON |
| `POST /documents/{document_id}/restore` | `{version_id, expected_revision, comment?}` + `X-Edit-Lease` → `200 {document, version}`; ревизия +1, новая версия из снимка этого документа |
| `POST /formatting-templates` | Только руководитель; `{name, parameters}` → `201 {template, version}` с первой версией |
| `GET /formatting-templates` | Свои шаблоны руководителя / шаблоны руководителя группы студента → `{items, limit, offset}` |
| `POST /formatting-templates/{template_id}/versions` | Только владелец; `{expected_version, parameters}` → `201 TemplateVersionResponse`; конфликт → `409` |
| `GET /formatting-templates/{template_id}/versions` | Доступные версии → `{items, limit, offset}`, номера по убыванию |
| `GET /formatting-template-versions/{version_id}` | Версия параметров по ссылке из документа/снимка; чужая/отсутствующая → `404` |

`DocumentResponse`: `id`, `thesis_id`, `content`, `schema_version`, `revision`,
`last_version_number`, `template_version_id`, `created_at`, `updated_at`.
`LeaseResponse`: `document_id`, `lease_id`, `holder_id`, `acquired_at`, `expires_at`.
`X-Edit-Lease` — UUID из ответа выдачи/продления. Отсутствие/невалидный UUID — `422`;
корректный UUID отсутствующей/истёкшей/заменённой аренды — `409`.
TTL по умолчанию 120 секунд, настраивается; save не продлевает его автоматически.
После истечения новую аренду нужно получить явно. GET документа не раскрывает UUID аренды.

`VersionSummary`: `id`, `document_id`, `number`, `document_revision`,
`schema_version`, `template_version_id`, `created_by_id`, `comment`,
`restored_from_id`, `created_at`. `VersionResponse` дополнительно содержит `content`.
Снимок не увеличивает ревизию текста, номера версий выдаются последовательно.
Два параллельных запроса снимка могут создать две самостоятельные версии одного текста.
Восстановление создаёт новую версию, исходные остаются неизменными; рабочий черновик
заменяется явно, его автоматического дополнительного архивирования перед restore нет.
Устаревшая ревизия/аренда при save/snapshot/restore даёт `409` без записи.

`content` — строгая схема Lexical: v1 принимает root/paragraph/heading/quote/list/listitem/text/linebreak,
вложенные списки, штатные флаги выделения, пустой inline CSS. V2 дополнительно
принимает table/tablerow/tablecell и norma-image (см. импорт ниже); выдавать их за v1
нельзя (`422`). Старые v1-снимки не меняются. Корень не пустой.
Неизвестные узлы, версии или поля, произвольные URL/HTML дают `422`,
никакое содержимое не отбрасывается молча. Лимит содержимого — 2 MiB компактного UTF-8
JSON, 50 000 объектов, 64 уровня JSON. Точные поля — в OpenAPI, ограничения — ADR-010.

`TemplateResponse`: `id`, `supervisor_id`, `name`, `latest_version`, `created_at`.
`TemplateVersionResponse`: `id`, `template_id`, `number`, `parameters`, `created_at`.
Параметры задаются явно: schema v1, A4, ориентация, поля в мм, стили body/headings
(6 уровней)/caption/list/table, начало нумерации. Стиль задаёт шрифт, размер в pt,
интервалы, отступ, выравнивание и bold/italic. Выбирать в документ можно только
версию шаблона руководителя этой ВКР. Свободному студенту список шаблонов пуст.
ГОСТ-предустановка, применение оформления и экспорт реализованы ниже.

Списки шаблонов/версий: `limit=50` (1–100), `offset=0` (0..2^63−1).
Шаблоны сортируются по созданию/UUID по убыванию, их версии — номер по убыванию.
Неизвестные поля запросов запрещены. Обновления/удаления снимков через API нет;
UPDATE обеих таблиц версий также отвергается триггером PostgreSQL.
Подробности — [ADR-010](../decisions/ADR-010-document-storage-versions-leases.md).

## Реализованный импорт DOCX (первый backend-инкремент фазы 5)

Права чтения/изменения — как для документа выше. Изменение — только студенту
своей ВКР, с CSRF, действующей арендой `X-Edit-Lease` и ожидаемой ревизией.

| Метод / путь | Запрос и результат |
|---|---|
| `POST /documents/{document_id}/import?expected_revision=N&confirm_replace=true` | Бинарное тело DOCX → `201 {document, version, import_record}` |
| `GET /documents/{document_id}/imports` | `{items: ImportSummary[], limit, offset}`; исходные байты не входят в список |
| `GET /documents/{document_id}/imports/{import_id}/source` | Исходные байты DOCX как attachment с UUID-именем |
| `GET /documents/{document_id}/assets/{asset_id}` | Обработанный PNG по UUID из текста, доступен также после restore |

Content-Type загрузки:
`application/vnd.openxmlformats-officedocument.wordprocessingml.document`.
Тело — сам файл, не multipart. OpenAPI описывает binary upload/download.
Другой Content-Type/Content-Encoding — `415`; файл >10 MiB, включая chunked body, —
`413`; неправильный Content-Length — `400`; повреждённый/небезопасный или слишком
сложный ZIP/XML — `422`. Отсутствующее/ложное подтверждение, неверная ревизия
в query или неизвестный параметр — `422`. Устаревшая revision/lease — `409` без записи.
Неавторизованный запрос — `401`, недоступный UUID — `404`.

После разбора сервер повторно проверяет lease/revision под row lock. Транзакция
создаёт защитную версию черновика, заменяет содержимое (schema v2), увеличивает
revision на 1 и создаёт контрольную версию импорта, исходник и assets.
`last_version_number` увеличивается на 2; выбранный template_version_id сохраняется.
Возвращаемая `version` — снимок импортированного текста. Повтор с прежней revision
не добавляет исходников. Восстановить черновик можно обычным restore.

`ImportSummary`: `id`, `document_id`, `version_id`, `previous_version_id`,
`created_by_id`, `source_size`, `source_sha256`, `warnings: {code: count}`, `created_at`.
Источники и assets не обновляются, UPDATE запрещён БД. Исходник хранится отдельно
в BYTEA, точно совпадает с загрузкой. Список: `limit=50` (1–100), `offset=0`
(0..2^63−1), создание/UUID по убыванию. Все ответы — `no-store`; binary ответы
с `nosniff`, исходник — attachment, PNG дополнительно с CSP sandbox.

Поддержаны текст/заголовки/базовое выделение/вложенные списки, типовые таблицы,
PNG/JPEG; рисунки перекодируются в PNG без исходных метаданных. `norma-image` —
`{type: "norma-image", version: 1, asset_id: UUID, alt_text}` внутри текстового блока.
Внешних src/HTML нет; сохранение неизвестного/чужого asset_id — `422`.
`table/tablerow/tablecell` совместимы с проверенным подмножеством @lexical/table
0.53.0; таблица до 100 столбцов/1000 строк, colSpan поддержан, rowSpan=1,
backgroundColor=null. Размеры/цвета/inline CSS не задаются свободно.

Warnings сообщают о нормализации оформления/размещения изображения,
сносках/колонтитулах/полях/формулах/ссылках/сложных таблицах и других неподдержанных
элементах; полный перечень и лимиты — [ADR-011](../decisions/ADR-011-docx-import.md).
HTML не создаётся, внешние relationships не загружаются. Исходник остаётся доступен
при любых предупреждениях. Импорт семантический: визуальное оформление по шаблону,
редактор/A4 пока не реализованы; экспорт по шаблону описан ниже,
Word round-trip произвольного документа не гарантируется.

## Реализованные оформление и экспорт (второй backend-инкремент фазы 5)

Все пути под `/api/v1`. Сессии/CSRF/ownership — как для документов выше.

| Метод / путь | Поведение |
|---|---|
| `GET /formatting-presets/gost-7-32-2017` | Любой вошедший пользователь получает редактируемые `TemplateParameters`; сохранить через обычное создание шаблона руководителем |
| `POST /document-versions/{version_id}/format-check` | Студент своей ВКР и её руководитель; проверка по pinned версии шаблона, снимок не меняется |
| `POST /documents/{document_id}/apply-formatting` | Только студент-владелец, `X-Edit-Lease`; `{expected_revision, template_version_id, confirm_apply: true}` → `{document, previous_version, version, corrected_issues}` |
| `POST /document-versions/{version_id}/exports` | Студент своей ВКР и её руководитель; `{format: "docx"|"pdf"}` → binary attachment; источник и шаблон берутся исключительно из версии |

`FormattingReport`: `{version_id, template_version_id, parameters, conforms,
issue_count, issues, truncated, scope: "semantic-formatting"}`.
`issues` — первые 1000 `{path, code, actual, expected}`; `issue_count` — полный
счётчик. Коды: `alignment_override`, `indent_override`, `text_effect_override`.
Проверяются семантический JSON и сохранённые параметры, а не геометрия страниц
или исходный DOCX. Свободные шрифты/CSS уже запрещены схемой; размеры и интервалы
определяются шаблоном. `conforms` не означает полного аудита ГОСТ.

Применение сохраняет защитный снимок, очищает ручные overrides, выбирает шаблон,
увеличивает revision на 1 и сохраняет итоговую версию (`last_version_number +2`).
Текст/структура/изображения/семантические выделения сохраняются. Старый снимок
не переписывается. Неактуальная revision/lease — `409`; неизвестная/чужая версия
шаблона — `404`; ложное/небулево подтверждение и неизвестные поля — `422`.

Schema v3 дополнительно принимает `{type: "norma-caption", version: 1,
kind: "figure"|"table", children, direction, format, indent, textFormat?, textStyle?}`.
`children` — стандартные inline-узлы; `textStyle` по-прежнему только пустой.
Подписи требуют `schema_version: 3`; v1/v2-снимки не меняются. Повторный импорт
собственных DOCX-стилей `Norma Figure Caption`/`Norma Table Caption` сохраняет kind.

Экспорт возвращает `200` с Content-Type DOCX либо `application/pdf`, `no-store`,
`nosniff`, `Content-Disposition: attachment` и UUID-именем, `X-Document-Version`
и `X-Template-Version`. `X-Export-Warnings` — разделённые запятыми коды:
`manual_formatting_normalized` (применены правила поверх ручных overrides),
`font_substitution` (для PDF исходный шрифт отсутствует/проверка недоступна).
Документ при экспорте не меняется. DOCX хранит запрошенные семейства; Docker PDF
использует установленные Liberation/DejaVu, возможна замена Times New Roman.

DOCX поддерживает семантические блоки v1–v3, девять уровней списков, numbering/start,
типовые таблицы/colSpan, PNG/alt text, A4/ориентацию/поля и поле PAGE.
Слишком глубокие списки/превышение бюджета изображений или файла (32 MiB) — `422`.
PDF создаётся LibreOffice из сгенерированного DOCX с отдельным профилем/каталогом;
таймаут по умолчанию 60 секунд. Конвертер недоступен/ошибка/таймаут или два
занятых слота экспорта на процесс — `503`; автоматического повтора нет.
Файлы экспорта не сохраняются в БД; неизменяемые исходные версии сохраняются.
Подробности — [ADR-012](../decisions/ADR-012-formatting-and-export.md).

## Планируемые бизнес-маршруты

| Модуль | Метод / путь | Сценарий |
|---|---|---|
| stages | `POST /stages/{id}/submit` | `in_progress/changes_requested → in_review`, immutable `DocumentVersion` |
| stages | `POST /stages/{id}/request-changes` | `in_review → changes_requested`, комментарии остаются в истории |
| stages | `POST /stages/{id}/confirm` | `in_review → completed`, только руководитель |
| stages | Расширение `GET /stages/{id}/history` | История отправок и решений вместе с версиями документа |
| documents | `GET /documents/{id}/diff?base={version_id}&target={version_id}` | UC-06, подсветка added/removed/changed |
| comments | `GET /document-versions/{id}/comments?include_resolved=false` | Замечания с фильтрацией |
| comments | `POST /document-versions/{id}/comments`, `PATCH /comments/{id}` | UC-10, статус/цитата/anchor |
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
- Тела будущих бизнес-запросов/ответов уточняются при реализации и покрываются интеграционными тестами; реализованные auth, health, группы, ВКР, этапы, документы и версии шаблонов описаны выше.
