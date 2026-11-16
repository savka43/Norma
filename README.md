# Система сопровождения выполнения этапов ВКР — спецификация для Codex

Пакет **документации**, с которого можно сразу начинать реализацию. Это **не готовое приложение** и **не отдельный прототип**. Исходные DOCX ЛР №1/№2 не включены: содержащиеся в них требования уже разложены по файлам.

## Действующий план и инструкции

Единственный план разработки для всех агентов — [docs/plans/roadmap.md](docs/plans/roadmap.md).
Общие инструкции — [AGENTS.md](AGENTS.md); требования, архитектура и ADR перечислены ниже.
Корневые `PLAN.md` и `CLAUDE.md` служат указателями. Прежние документы Claude сохранены
в `docs/archive/claude/` только для истории и не используются при разработке.

## На чём основан продукт

- ЛР №1 (Business Use Case) — 12 сценариев взаимодействия студента и научного руководителя.
- ЛР №2 (UML) — 9 классов, 10 связей; этапы, сроки, версии работы, замечания, шаблоны, проверка заимствований.
- Явно согласованные расширения: самостоятельная регистрация студента, группирование руководителем, **Lexical** как встроенный редактор, постраничное отображение A4, импорт DOCX и нормализация оформления, CSS Modules, TanStack Form, diff, история замечаний, тестовое API «Антиплагиат».

## Утверждённый стек

**Backend:** FastAPI, PostgreSQL, async SQLAlchemy, Alembic, Pydantic, `uv`, Ruff, BasedPyright, pytest.

**Frontend:** React + TypeScript + Vite, React Router, TanStack Query, **TanStack Form**, **Lexical**, **CSS Modules** и самостоятельно созданные UI-компоненты.

**Запрещены без нового решения:** Tiptap, Tailwind CSS, shadcn/ui, React Hook Form, Zod. Совместного редактирования в реальном времени и ML-помощника по разрывам страниц в текущем объёме нет.

## Карта документации

- `AGENTS.md` — инструкции Codex, ограничения и правила.
- `docs/requirements/product.md` — функциональные требования и утверждённые бизнес-правила.
- `docs/requirements/use-cases.md` — 12 UC и сквозная приёмка.
- `docs/requirements/editor.md` — продуктовые требования к минималистичному постраничному редактору.
- `docs/architecture/domain-model.md` — отображение девяти классов ЛР №2 на данные.
- `docs/architecture/overview.md` — границы модулей, инфраструктура, workflow.
- `docs/architecture/editor-design.md` — Lexical JSON, страницы, DOCX, шаблоны, diff и comments.
- `docs/architecture/api-contract.md` — рабочий эскиз HTTP API.
- `docs/decisions/` — ADR по редактору, API и стилям.
- `docs/plans/roadmap.md` — порядок реализации и проверяемые критерии.
- `docs/plans/first-task.md` — **готовое задание для первого запуска Codex**.

## Навыки frontend

В проект установлены `frontend-design` и `webapp-testing` из `anthropics/skills`,
а также `web-design-guidelines` из `vercel-labs/agent-skills`.
Codex использует `.agents/skills/`, Claude Code — ссылки в `.claude/skills/`.
Источники и контрольные суммы фиксирует `skills-lock.json`.
Папка `.claude/` локальная и исключена из Git; команды установки ниже создают её заново.

Применение: `frontend-design` для разработки интерфейса, `web-design-guidelines`
для его ревью и доступности, `webapp-testing` для браузерных проверок.
Навыки применяются с сохранением утверждённого стека и ограничений `AGENTS.md`.

Повторная установка в чистом проекте:

```bash
npx skills add anthropics/skills --skill frontend-design --skill webapp-testing -a claude-code -a codex --yes
npx skills add vercel-labs/agent-skills --skill web-design-guidelines -a claude-code -a codex --yes
```

## Как начать

1. Создай Git-репозиторий и скопируй **содержимое** архива в корень (файл `AGENTS.md` должен оказаться в корне).
2. Открой проект в Codex.
3. Скопируй текст задания из `docs/plans/first-task.md` в Codex и дай ему реализовать первую задачу. Согласование отдельного пробного редактора до начала проекта **не требуется**.
4. При следующей задаче ориентируйся на `docs/plans/roadmap.md`.

**Оговорка по редактору:** Lexical — ядро редактирования, но не готовый Word и не движок постраничной верстки. Постраничность и корректный DOCX round-trip разрабатываются внутри продукта, приёмка — на проверяемых демонстрационных документах. Источник: https://lexical.dev/docs/intro/.
