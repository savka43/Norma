# Первое задание для Codex: начать реализацию

Скопируй следующий текст в Codex **из корня репозитория**:

> Прочитай `AGENTS.md`, `docs/requirements/product.md`, `docs/requirements/use-cases.md`, `docs/requirements/editor.md`, `docs/architecture/overview.md`, `docs/architecture/domain-model.md`, `docs/architecture/editor-design.md` и `docs/plans/roadmap.md`.
>
> **Приступи к реализации фазы 1**. Это полноценная система сопровождения этапов ВКР на FastAPI + PostgreSQL + React + TypeScript. Исходных DOCX лабораторных в репозитории нет; их требования уже включены в спецификацию. **Не создавай отдельный прототип редактора и не ограничивайся планом.**
>
> Настрой монорепозиторий: `backend/` с `uv`, FastAPI, SQLAlchemy 2 async, Alembic, Pydantic, Ruff, BasedPyright, pytest; `frontend/` с Vite React TypeScript, React Router, TanStack Query, TanStack Form, CSS Modules, ESLint, Prettier, Vitest; `compose.yaml` с PostgreSQL, backend и frontend; `.env.example` без секретов. Структура backend `app/api_v1/<feature>/views.py,schemas.py,crud.py,dependencies.py` и `service.py` только по необходимости; модели в `app/core/models/`. Сделай healthcheck backend, стартовый маршрут frontend и базовые тесты. Добавь команды запуска и проверок в корневой `README.md` (сохрани ссылки на спецификацию).
>
> **Редактором будет Lexical, НЕ Tiptap.** Не внедряй сам редактор целиком в фазе 1, но оставь архитектурные границы для `features/document-editor`. Без Tailwind, shadcn/ui, React Hook Form и Zod. Не внедряй ML, real-time collaboration, нормоконтролёра и заведующего кафедрой.
>
> Сначала напиши короткий план изменений, затем **создай файлы и запусти доступные проверки**: backend Ruff, BasedPyright и pytest; frontend TypeScript check, ESLint, Vitest/build; Docker Compose config. Если Docker недоступен, явно об этом сообщи. Не утверждай, что тесты прошли, если не запускал их. Не создавай коммит и не делай push.
>
> По завершении перечисли созданные файлы, выполненные команды/результаты, как запустить проект, и какие ограничения остаются к фазе 2.

Далее в Codex: **«Переходи к фазе 2 из docs/plans/roadmap.md. Сначала спланируй auth и группы, затем реализуй вертикально и проверь права».**
