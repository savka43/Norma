# Разработка и запуск Нормы

Система сопровождения этапов ВКР для студента и научного руководителя.

Разработка начинается с API. Реализована основа backend: FastAPI,
PostgreSQL, SQLAlchemy async, Alembic, конфигурация и healthcheck.
В фазе 2 добавлены модель пользователя с двумя ролями и миграция `0002_users`.
Бизнес-маршруты регистрации, групп и ВКР добавляются следующими задачами roadmap.
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
без учёта регистра. `uv run alembic upgrade head` применяет обе ревизии;
`uv run alembic current` показывает `0002_users (head)`.
Приложение не вызывает `create_all` и не запускает миграции при каждом HTTP-запросе.

Учётная запись содержит ФИО, email, уже подготовленный хэш пароля и явную роль
`student` или `supervisor`. У студента указывается `academic_group`, у руководителя —
`position` и `department`; БД проверяет соответствие полей роли. Учётные записи
автоматически не создаются: регистрация и bootstrap ещё не реализованы.
Подробности хранения — [ADR-006](decisions/ADR-006-user-model.md).

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
сохранение пользователей и ограничения ролей, профилей и уникальности email.
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
