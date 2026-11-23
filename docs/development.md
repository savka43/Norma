# Разработка и запуск Нормы

Система сопровождения этапов ВКР для студента и научного руководителя.

Разработка начинается с API. Реализована основа backend: FastAPI,
PostgreSQL, SQLAlchemy async, Alembic, конфигурация и healthcheck.
В backend-части фазы 2 реализованы модель пользователя, регистрация студента,
login/logout/me, серверные сессии и CLI bootstrap руководителя, группы и их права,
поиск свободных зарегистрированных студентов. Первый backend-инкремент фазы 3
добавляет ВКР, настройку обязательных этапов/сроков, историю плана и сводку прогресса.
Backend-инкремент фазы 4 добавляет документы, аренду редактирования, сохранение
с ревизиями, неизменяемые контрольные версии/восстановление и версии шаблонов.
Первый backend-инкремент фазы 5 добавляет защищённый импорт DOCX с исходником,
предупреждениями, таблицами и обработанными изображениями.
Корневая `src/` пока содержит исходную заготовку Vite/React.

## Запуск API в Docker

Требуются Docker Engine и Docker Compose. При первой настройке скопируйте
`.env.example` в `.env` и задайте непустой `NORMA_DATABASE_PASSWORD`:

```bash
cp .env.example .env
```

Если `.env` уже существует, сохраните его настройки. Файл не включается в Git.
Пароль передаётся отдельным параметром и может содержать специальные символы.

Из корня репозитория:

```bash
docker compose config --quiet
docker compose up --build --detach --wait
docker compose ps --all
```

Compose поднимает PostgreSQL 16, выполняет миграции отдельным одноразовым
контейнером `migrate`, затем запускает `backend`. Данные БД сохраняются в volume.
API и PostgreSQL опубликованы только на `127.0.0.1`; порты по умолчанию — 8000 и 5432.

- Swagger UI: <http://localhost:8000/docs>.
- OpenAPI: <http://localhost:8000/openapi.json>.
- Liveness: <http://localhost:8000/api/v1/health>, ответ `{"status":"ok"}`.
- Readiness: <http://localhost:8000/api/v1/health/ready>, ответ
  `{"status":"ok","database":"ok"}`; при недоступной БД — `503`.

Liveness не обращается к БД. Readiness выполняет `SELECT 1` с ограниченным
временем ожидания и не раскрывает клиенту подробности ошибки подключения.

```bash
docker compose logs --tail=100 backend migrate
docker compose down
```

`docker compose down` сохраняет volume БД. После первого запуска PostgreSQL
изменение пароля в `.env` само по себе не изменяет пароль уже созданного пользователя БД.

## Локальная разработка backend

Требуются `uv` и Python 3.12. Конфигурация API и Alembic читается из корневой
`.env` независимо от рабочей директории. Переменные окружения имеют приоритет.
Для локального API используйте `NORMA_DATABASE_HOST=127.0.0.1`; внутри Compose
хост автоматически заменяется на `postgres`.

Из корня репозитория можно запустить только БД:

```bash
docker compose up --detach --wait postgres
```

Затем из `backend/`:

```bash
uv sync --locked
uv run alembic upgrade head
uv run fastapi dev
```

Перед локальным запуском остановите контейнер API, если он занимает порт 8000:
`docker compose stop backend` из корня. Для изменения схемы после добавления моделей:

```bash
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
uv run alembic check
```

Базовая ревизия `0001_api_foundation` фиксирует начало истории миграций.
Ревизия `0002_users` создаёт `users`, enum `user_role` и уникальный индекс email
без учёта регистра. `0003_auth_sessions` добавляет отзываемые серверные сессии.
`uv run alembic upgrade head` применяет все ревизии;
`0004_supervisor_groups` создаёт группы руководителей и уникальные назначения студентов.
`0005_theses_stages` добавляет ВКР, этапы, enum состояний и историю настройки плана.
`0006_documents` добавляет документы, аренды, контрольные версии и шаблоны;
триггеры PostgreSQL запрещают UPDATE контрольных версий и снимков параметров.
`0007_docx_import` добавляет отдельные исходники/изображения и schema v2;
UPDATE исходников/assets также запрещён. Откат к v1 при наличии v2-документов
или снимков запрещён, чтобы не менять историю.
`uv run alembic current` показывает `0007_docx_import (head)`.
Приложение не вызывает `create_all` и не запускает миграции при каждом HTTP-запросе.

Учётная запись содержит ФИО, email, хэш пароля Argon2id и явную роль
`student` или `supervisor`. У студента указывается `academic_group`, у руководителя —
`position` и `department`; БД проверяет соответствие полей роли. Учётные записи
автоматически не создаются. Подробности хранения — [ADR-006](decisions/ADR-006-user-model.md),
аутентификация — [ADR-007](decisions/ADR-007-auth-sessions-bootstrap.md).

## Регистрация и вход

В Swagger откройте `POST /api/v1/auth/register`, укажите заголовок
`x-csrf-protection` со значением `1` и JSON:

```json
{
  "email": "student@example.com",
  "password": "Synthetic-password-123",
  "full_name": "Тестовый Студент",
  "academic_group": "ИДБ-23-08"
}
```

Это искусственный пример, задайте свой пароль для реальной учётной записи.
Регистрация возвращает `201`; роль всегда `student`, неизвестные поля запрещены.
Email сравнивается без учёта регистра, повторный адрес даёт `409`.
Пароль регистрации — 12–128 символов; пробелы в пароле сохраняются.

Затем вызовите `POST /api/v1/auth/login` с тем же заголовком и `{email, password}`.
Браузер сохранит `HttpOnly` cookie; `GET /api/v1/auth/me` вернёт текущий профиль.
`POST /api/v1/auth/logout` с `X-CSRF-Protection: 1` отзывает сессию на сервере
и удаляет cookie, возвращая `204`. В Swagger и frontend используйте один hostname
на всём пути, например `localhost`, не чередуйте его с `127.0.0.1`.

`NORMA_SESSION_LIFETIME_SECONDS` задаёт абсолютный срок сессии (по умолчанию 28800).
Для HTTPS установите `NORMA_SESSION_COOKIE_SECURE=true`; локальный HTTP использует
`false`. Frontend должен обращаться через тот же origin; при разработке
используется Vite proxy. CORS-разрешений нет, все изменяющие запросы с cookie
должны передавать `X-CSRF-Protection: 1`.

## Создание руководителя

Публичная регистрация руководителя отсутствует. После применения миграций
из `backend/` запустите:

```bash
uv run python -m app.bootstrap --email supervisor@example.com --full-name "Тестовый Руководитель" --position "Доцент" --department "Информационные системы"
```

Для уже работающего Compose из корня (без `-T`, нужен интерактивный ввод):

```bash
docker compose exec backend python -m app.bootstrap --email supervisor@example.com --full-name "Тестовый Руководитель" --position "Доцент" --department "Информационные системы"
```

Команда дважды запросит скрытый пароль; пароль не передаётся аргументом CLI
и не выводится. Повторный email завершается ошибкой и не меняет существующую
учётную запись или роль. Созданный руководитель входит через обычный `/auth/login`.

## Группы руководителя

После входа руководителем через `/api/v1/auth/login` в Swagger:

1. `POST /api/v1/supervisor-groups` с `X-CSRF-Protection: 1` и
   `{"name":"Выпуск 2027","academic_year":2026}` создаёт свою пустую группу.
   Год — начало учебного года (2026/2027). Владельца передавать не нужно.
2. `GET /api/v1/students?query=Студент` ищет свободных зарегистрированных студентов
   по ФИО или email. Запрос — 3–100 символов, `limit` по умолчанию 20, максимум 50;
   ответ `{items, limit, offset}` содержит только минимальные профили.
3. `POST /api/v1/supervisor-groups/{group_id}/students` с тем же заголовком
   и `{"student_id":"UUID из поиска"}` добавляет студента. Ответ `201` содержит
   `student_id`, `group_id`, `joined_at`.
4. `GET /api/v1/supervisor-groups` показывает свои группы;
   `GET /api/v1/supervisor-groups/{group_id}` — одну свою группу;
   `GET /api/v1/supervisor-groups/{group_id}/students` — её состав.
   У списков групп/состава `limit` по умолчанию 50, максимум 100, `offset` — от 0.

Студенту эти маршруты дают `403`, без входа — `401`. Чужая и несуществующая группа
одинаково дают `404`. Повторное добавление, в том числе в другую группу/другому
руководителю, возвращает `409` без переноса студента; это защищено и при гонке.
После назначения студент исчезает из поиска свободных и остаётся в составе группы.
Учебная группа профиля при этом сохраняется. Удаление/перенос пока отсутствуют.
Решения — [ADR-008](decisions/ADR-008-supervisor-groups.md).

## ВКР, этапы и прогресс

После добавления студента в свою группу руководитель выполняет:

1. `POST /api/v1/theses` с `X-CSRF-Protection: 1` и JSON
   `{"student_id":"UUID студента","title":"Тема ВКР","start_date":"2026-09-01","due_date":"2027-06-30"}`.
   Ответ `201` содержит UUID ВКР и `revision: 1`. Повторное создание — `409`.
2. `POST /api/v1/theses/{thesis_id}/stages` с тем же заголовком и
   `{"name":"Введение","position":1,"due_date":"2026-12-01","expected_revision":1}`.
   Ответ — весь план, UUID этапов и новая `revision: 2`.
3. Добавляет следующие этапы с актуальной ревизией. Вставка в занятую позицию
   сдвигает остальные этапы. Срок этапа должен входить в даты ВКР включительно.
4. `PATCH /api/v1/stages/{stage_id}` с теми же четырьмя обязательными полями
   меняет имя, позицию и срок. При `409` нужно перечитать план; повторно отправлять
   устаревшие данные с новой ревизией без решения пользователя не следует.
5. `GET /api/v1/supervisor-groups/{group_id}/progress` показывает студентов,
   ВКР, этапы, прогресс и просрочки; включает студентов, у которых ВКР ещё нет.

`GET /api/v1/theses` — доступные ВКР, `GET /api/v1/theses/{thesis_id}` — одна ВКР,
`GET /api/v1/theses/{thesis_id}/stages` — актуальный план и его ревизия,
`GET /api/v1/stages/{stage_id}/history` — история настройки и снимки до/после.
Эти чтения доступны студенту своей ВКР и её руководителю; чужие UUID дают `404`.
Списки ВКР, сводка группы и история принимают `limit`/`offset` как списки групп.

Все этапы обязательны. Прогресс равен `100 * completed / total`; если этапов
нет, возвращается `null`. Просрочка считается после даты срока, по дате UTC,
которая возвращается в `as_of_date`. Сегодняшний срок ещё не просрочен.
Состояния проверки пока не меняются через API: сначала нужны версии документа,
затем отправка/возврат/явное подтверждение по roadmap. Настройка плана при наличии
`in_review` или `completed` закрыта (`409`). Удаление этапов, редактирование
метаданных ВКР, frontend и история решений проверки пока не реализованы.
Техническое решение — [ADR-009](decisions/ADR-009-thesis-stage-planning.md).

## Документы и версии

Сначала руководитель своей учётной записью создаёт шаблон через
`POST /api/v1/formatting-templates` с CSRF-заголовком: `{name, parameters}`.
Параметры задаются явно, см. OpenAPI. Такой пример JSON можно получить из корня
репозитория (это демонстрационные параметры, не утверждение соответствия ГОСТ):

```bash
python3 - <<'PY'
import json
style = {"font_family": "Times New Roman", "font_size_pt": 14, "line_spacing": 1.5,
         "first_line_indent_mm": 12.5, "space_before_pt": 0, "space_after_pt": 0,
         "alignment": "justify", "bold": False, "italic": False}
parameters = {"schema_version": 1, "page_format": "A4", "orientation": "portrait",
              "margins": {"top_mm": 20, "bottom_mm": 20, "left_mm": 30, "right_mm": 15},
              "body": style, "headings": [{**style, "bold": True} for _ in range(6)],
              "caption": style, "list": style, "table": style, "page_number_start": 1}
print(json.dumps({"name": "Пример A4", "parameters": parameters}, ensure_ascii=False, indent=2))
PY
```

Ответ `201` содержит `template` и `version`; сохраните `version.id`.
`POST /api/v1/formatting-templates/{template_id}/versions` с
`{expected_version, parameters}` создаёт новый снимок, не изменяя прежний.
`GET /api/v1/formatting-templates` и `GET /api/v1/formatting-templates/{template_id}/versions`
доступны владельцу и студентам его групп; `GET /api/v1/formatting-template-versions/{version_id}`
читает конкретный снимок. Свободный студент получает пустой список шаблонов.

Далее войдите **студентом** своей ВКР:

1. `POST /api/v1/theses/{thesis_id}/document` с `{"template_version_id":"UUID версии"}`
   создаёт документ с пустым абзацем и `revision: 1`; повтор — `409`.
   `GET /api/v1/theses/{thesis_id}/document` и `GET /api/v1/documents/{document_id}`
   только читают существующий документ.
2. `POST /api/v1/documents/{document_id}/edit-lease` без тела возвращает `lease_id`
   и `expires_at`. До истечения аренды продлевайте её через
   `POST /api/v1/documents/{document_id}/edit-lease/renew` с `X-Edit-Lease: UUID`.
   TTL — `NORMA_DOCUMENT_LEASE_SECONDS` (по умолчанию 120 секунд, диапазон 30–3600).
3. `PUT /api/v1/documents/{document_id}` с заголовками `X-CSRF-Protection: 1`,
   `X-Edit-Lease: UUID` и `{expected_revision, schema_version, content, template_version_id}`
   сохраняет JSON и возвращает новую ревизию. Нельзя подставлять новую ревизию
   к старому запросу без разрешения конфликта; при `409` сохраните локальный текст.
4. `POST /api/v1/documents/{document_id}/versions` с теми же заголовками и
   `{expected_revision, comment?}` создаёт контрольный снимок. GET списка версий
   поддерживает `limit`/`offset`; `GET /api/v1/document-versions/{version_id}` читает текст.
5. `POST /api/v1/documents/{document_id}/restore` с теми же заголовками и
   `{expected_revision, version_id, comment?}` заменяет рабочий текст/шаблон
   снимком **этого** документа и создаёт новую контрольную версию со ссылкой на источник.
   Текущий неснятый в версию черновик автоматически не архивируется.
6. `DELETE /api/v1/documents/{document_id}/edit-lease` с двумя заголовками
   освобождает аренду (`204`). Старый UUID не может освободить новую аренду.

Сохранение/снимки/восстановление требуют текущую аренду и ревизию; конфликты — `409`.
Чтение доступно также руководителю этой ВКР, изменение — только студенту.
История текста и параметров сохраняется при дальнейших изменениях.
Клиент хранит один Lexical JSON, а не отдельный текст для каждой страницы.
Схема v1 поддерживает абзацы, заголовки, цитаты, базовое выделение, переносы
строк и вложенные списки; v2 добавляет таблицы и узел изображения по asset UUID.
Передавайте schema_version прочитанного документа, после импорта — 2.
Неизвестные узлы/inline CSS/произвольные URL — `422`.
Оформление и экспорт описаны ниже; diff и frontend/A4 остаются следующими задачами.
Подробности — [ADR-010](decisions/ADR-010-document-storage-versions-leases.md).

### Импорт DOCX

После создания документа и получения аренды студент отправляет файл бинарным
телом на `POST /api/v1/documents/{document_id}/import?expected_revision=N&confirm_replace=true`.
Обязательны сессия, `X-CSRF-Protection: 1`, `X-Edit-Lease: UUID` и Content-Type DOCX.
Подтверждение замены нужно получить от пользователя до запроса; это не preview.
Пример из корня (подставьте UUID/актуальную revision и cookie-файл после входа):

```bash
curl 'http://localhost:8000/api/v1/documents/DOCUMENT_UUID/import?expected_revision=1&confirm_replace=true' \
  --cookie cookies.txt \
  --header 'X-CSRF-Protection: 1' \
  --header 'X-Edit-Lease: LEASE_UUID' \
  --header 'Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document' \
  --data-binary @backend/tests/fixtures/synthetic-import.docx
```

`201` содержит обновлённый `document`, контрольную `version`, `import_record`.
Исходник и снимки до/после сохраняются одной транзакцией; revision увеличивается
на 1, номера контрольных версий — на 2. Шаблон остаётся прежним. При конфликте
аренды/revision — `409`, исходник и версии не добавляются. Прежний черновик можно
восстановить по `import_record.previous_version_id` обычным restore.

- `GET /api/v1/documents/{document_id}/imports?limit=50&offset=0` — метаданные,
  SHA-256, warnings и ссылки на снимки; без blobs.
- `GET /api/v1/documents/{document_id}/imports/{import_id}/source` — точный оригинал.
- `GET /api/v1/documents/{document_id}/assets/{asset_id}` — обработанный PNG;
  UUID находится в `norma-image` содержимого. Читает также руководитель этой ВКР.

Лимит загрузки — 10 MiB (`413`), повреждённый/небезопасный ZIP/XML — `422`,
другой Content-Type/Content-Encoding — `415`. Multipart не поддерживается.
Неизвестные/сложные элементы отражаются в `warnings: {code: count}`; frontend
должен показывать их. Отдельные колонтитулы/сноски/сложные объекты остаются
в оригинале, внешние ссылки не загружаются. Это семантический импорт с выбранным
шаблоном; редактор/A4 пока не реализован, оформление/экспорт описаны ниже.
Точные ограничения/коды — [ADR-011](decisions/ADR-011-docx-import.md).

### Проверочная фикстура Lexical

`backend/tests/fixtures/lexical-0.53.0.json` получен настоящим headless-редактором,
затем прочитан обратно им же; Python и API проверяют сохранение той же структуры.
Для повторного создания из корня (Node.js/npm нужны только этому tooling):

```bash
npm install --prefix /tmp/norma-lexical-qa --no-save --ignore-scripts --package-lock=false lexical@0.53.0 @lexical/headless@0.53.0 @lexical/rich-text@0.53.0 @lexical/list@0.53.0 @lexical/table@0.53.0
node backend/tests/fixtures/generate_lexical.cjs /tmp/norma-lexical-qa backend/tests/fixtures/lexical-0.53.0.json
node backend/tests/fixtures/generate_lexical_table.cjs /tmp/norma-lexical-qa backend/tests/fixtures/lexical-table-0.53.0.json
```

В backend runtime пакеты npm не нужны; обычный pytest использует готовую фикстуру.
Второй генератор дополнительно принимает путь к импортированному JSON и проверяет
сохранность текста/изображений/таблиц при чтении реальным Lexical. `norma-image`
здесь — сериализационная заглушка; продуктового frontend-рендерера ещё нет.
Синтетический DOCX с заголовком, списками, таблицей, рисунком и колонтитулом
создаётся из `backend/` командой `uv run python tests/fixtures/generate_docx.py`;
python-docx — только dev-зависимость. Оригинальные документы пользователя не нужны.

## Проверки backend

### Оформление и экспорт DOCX/PDF

1. Вошедший пользователь получает `GET /api/v1/formatting-presets/gost-7-32-2017`.
   Руководитель может отредактировать параметры и сохранить через
   `POST /api/v1/formatting-templates`, затем студент выбирает эту версию шаблона.
2. Студент сохраняет документ и создаёт контрольную версию обычным API.
   `POST /api/v1/document-versions/{version_id}/format-check` возвращает отчёт
   по неизменяемой версии и её параметрам; доступен также руководителю.
3. Для исправления студент отправляет
   `POST /api/v1/documents/{document_id}/apply-formatting` с JSON
   `{expected_revision, template_version_id, confirm_apply: true}`,
   CSRF и текущим `X-Edit-Lease`. Сохраняются версии до/после, revision +1.
4. Для скачивания: `POST /api/v1/document-versions/{version_id}/exports`,
   CSRF и JSON `{"format":"docx"}` либо `{"format":"pdf"}`. Ответ — файл,
   не JSON. UUID исходной версии и шаблона — в `X-Document-Version` и
   `X-Template-Version`. Используется шаблон снимка, изменение черновика на него
   не влияет. В Swagger доступны binary response и download.

Docker-образ включает LibreOffice Writer и Liberation/DejaVu. При локальном запуске
вне Docker PDF требует отдельной установки LibreOffice и пути
`NORMA_PDF_CONVERTER` (по умолчанию `libreoffice`).
`NORMA_PDF_TIMEOUT_SECONDS` — 60 по умолчанию, 1–120. При недоступности/таймауте
возвращается `503`; DOCX продолжает работать. Два экспорта на процесс и 32 MiB
ограничивают ресурсы; занятость требует явного повторного запроса.

`X-Export-Warnings: font_substitution` сообщает о замене шрифта в PDF:
Microsoft Times New Roman не поставляется в образе, LibreOffice может применять
Liberation Serif. Для точного выбранного семейства установите лицензированный
шрифт в собственный образ. DOCX сохраняет исходное название семейства.
`manual_formatting_normalized` означает применение семантических правил к экспорту
без изменения исходного снимка. Проверка JSON не заменяет визуальную приёмку
страниц или полный аудит ГОСТ. Точная идентичность Word/браузеру не обещается.

Визуальные фикстуры создаются из `backend/` без пользовательских документов:

```bash
uv run python -m tests.fixtures.generate_export /tmp/norma-export-qa
```

Генератор пишет short/long/landscape DOCX с кириллицей, таблицами, вложенными
списками и рисунком. Реальные PDF-тесты запускаются в среде с LibreOffice;
на хосте без него явно пропускаются. Отдельный запуск в контейнере с тестами,
смонтированными в `/app/tests`, может использовать минимальное тестовое окружение
`uv run --no-dev --with pytest --with pytest-asyncio --with pypdf pytest`.

### Проверка этапов, замечания и diff

Миграция `0009_stage_review` добавляет историю отправок и замечания. После
`docker compose up --build` Swagger по-прежнему доступен на
`http://localhost:8000/docs`; интерфейсы workflow пока отсутствуют.

После создания ВКР, ненулевого плана и документа:

1. Студент получает lease, сохраняет текст и отправляет
   `POST /api/v1/stages/{stage_id}/submit` с `X-Edit-Lease`,
   `{expected_revision, expected_document_revision, comment?}`.
   Первая ревизия относится к ВКР, вторая — к документу. Сервер сам создаёт
   контрольную версию; ответ содержит stage/revision/event.
2. Руководитель читает `stage.submitted_version_id` через API версий и при
   необходимости создаёт замечания. `request-changes`/`confirm` принимают
   `{expected_revision, submitted_version_id, comment?}`.
3. После возврата студент сохраняет правки и повторно отправляет этап либо
   отдельно делает `resume`. Подтверждение всегда отдельным действием руководителя.

Пока сопоставления глав этапам нет, отправляется весь документ. При любом
`in_review` save/import/restore/apply-formatting возвращают `409`; чтение,
снимки и экспорт разрешены. После решения по всем проверкам правки доступны.
При `409` клиент обязан сохранить локальный несинхронизированный текст и
перечитать ревизию/статусы; автоматической перезаписи нет.

Замечание создаётся к неизменяемой версии с проверяемой quote и anchor:
`block_id` — путь индексов children (`0`, `3/0/0/0`), диапазон — UTF-16 units
одного семантического блока. `PATCH /comments/{id}` закрывает замечание с
expected_revision, не подтверждая этап. Чтобы получить все замечания версии,
передайте `include_resolved=true&include_detached=true`. Исходные цитаты,
anchors и события не переписываются. Diff любых двух версий одного документа —
`GET /api/v1/documents/{id}/diff?base={version_id}&target={version_id}`.
Полные тела/лимиты — [API-контракт](architecture/api-contract.md),
решения/ограничения — [ADR-013](decisions/ADR-013-stage-review-comments-diff.md).

### Проверка на заимствования

По умолчанию сервис `worker` запускается с отключённой интеграцией. Для
демонстрации в отдельном окружении с искусственными данными задайте в `.env`
`NORMA_PLAGIARISM_ENABLED=true`, `NORMA_PLAGIARISM_LOGIN` и
`NORMA_PLAGIARISM_PASSWORD` из [документации тестового API](https://docs.antiplagiat.ru/ru/api/).
WSDL и компания заданы в `.env.example`. Общий тестовый аккаунт публикует
загруженные материалы другим пользователям. Для него подходят только
искусственный текст и демонстрационные учётные записи.

```bash
docker compose up --build --detach --wait
docker compose logs worker
```

Студент сохраняет версию с демонстрационным текстом и вызывает
`POST /api/v1/document-versions/{version_id}/plagiarism-checks` с
`X-CSRF-Protection: 1` и `{"confirm_demo_document": true}`.
Ответ `202` содержит ID проверки. Статус, историю и отчёт можно читать
позднее, даже после перезапуска API. После `failed` тот же POST запускает
новую попытку с историей предыдущей. Внешние запросы не повторяются
автоматически после ошибки. Ошибка `interrupted` означает, что worker
прервался до подтверждения загрузки или запуска.

Отчёт содержит сохранённые проценты и доступные ссылки на краткий и полный
отчёты для чтения. Параметры таймаутов, polling и необязательного лимита
текста перечислены в `.env.example`. Миграция `0010_plagiarism_checks`
запрещает откат при наличии попыток. Обычные тесты используют имитацию
поставщика и не выполняют внешнюю загрузку.
См. [контракт](architecture/api-contract.md) и [ADR-002](decisions/ADR-002-antiplagiat.md).

### Команды

Из `backend/`:

```bash
uv run ruff check .
uv run ruff format --check .
uv run basedpyright
uv run pytest -m "not integration"
```

Интеграционные тесты используют настоящую PostgreSQL и проверяют readiness,
применение/откат миграций, отсутствие расхождения ORM-метаданных со схемой,
сохранение пользователей и ограничения ролей, профилей и уникальности email,
auth-сценарии, истечение/отзыв/ротацию сессий и bootstrap руководителя,
группы, чужой доступ, поиск и конкурентное добавление студента,
ВКР, настройку этапов, историю, прогресс и конкурентные изменения плана.
Дополнительно проверяются JSON-схемы документов/параметров, аренда/истечение,
сохранение, снимки/восстановление, запрет UPDATE снимков и двенадцать сценариев гонок
на независимых соединениях PostgreSQL.
Проверяются DOCX-импорт/предупреждения/источники/assets, опасные ZIP/XML,
лимиты chunked upload, сохранность снимков и защита отката schema v2.
Workflow-тесты проверяют повторную отправку, явные решения по версии, блокировку
всех путей замены текста, несколько проверок, цитаты/UTF-16, скрытие закрытых и
detached, неизменность источников и diff. Семь новых гонок используют независимые
соединения: submit/submit/save/import/restore/format, решения и закрытие замечания.
Откат `0009_stage_review` при наличии истории проверки намеренно запрещён.
Создайте отдельную тестовую БД один раз (из корня репозитория):

```bash
docker compose exec -T postgres sh -c 'createdb -U "$POSTGRES_USER" norma_test'
```

Затем из `backend/`:

```bash
NORMA_RUN_DB_TESTS=1 NORMA_DATABASE_NAME=norma_test uv run pytest
```

Без `NORMA_RUN_DB_TESTS=1` тесты БД явно пропускаются. Имя тестовой БД должно
заканчиваться на `_test`; миграционные тесты выполняют downgrade и не предназначены
для рабочей базы. Сквозные frontend-сценарии добавляются в следующих фазах.

## Спецификация и контекст разработки

- [Правила работы](../AGENTS.md).
- [Единый roadmap, текущий статус и журнал выполнения](plans/roadmap.md).
- [Требования продукта](requirements/product.md) и [12 UC](requirements/use-cases.md).
- [Требования редактора](requirements/editor.md).
- [Архитектура](architecture/overview.md), [предметная модель](architecture/domain-model.md),
  [дизайн редактора](architecture/editor-design.md), [API](architecture/api-contract.md).
- [Архитектурные решения](decisions/).
