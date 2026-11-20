# Разработка и запуск Нормы

Система сопровождения этапов ВКР для студента и научного руководителя.

Разработка начинается с API. Реализована основа backend: FastAPI,
PostgreSQL, SQLAlchemy async, Alembic, конфигурация и healthcheck.
В backend-части фазы 2 реализованы модель пользователя, регистрация студента,
login/logout/me, серверные сессии и CLI bootstrap руководителя, группы и их права,
поиск свободных зарегистрированных студентов. Первый backend-инкремент фазы 3
добавляет ВКР, настройку обязательных этапов/сроков, историю плана и сводку прогресса.
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
`uv run alembic current` показывает `0005_theses_stages (head)`.
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

## Проверки backend

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
