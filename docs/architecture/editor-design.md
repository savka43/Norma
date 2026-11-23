# Технический дизайн редактора на Lexical

**Статус:** целевая архитектура с проверяемыми рисками. Реализован backend хранения,
ревизий, lease и контрольных версий (ADR-010), импорт DOCX (ADR-011),
экспорт/оформление (ADR-012), workflow/замечания/diff (ADR-013);
frontend/layout ниже ещё не реализованы.
Сверяться с `docs/requirements/editor.md` и ADR-001.

## Компоненты

```text
frontend/src/features/document-editor/
  components/
    DocumentEditor.tsx          # Lexical integration / edit lease
    DocumentEditor.module.css
    EditorToolbar.tsx
    EditorToolbar.module.css
    PageViewport.tsx            # A4 листы, поля, page numbers
    PageViewport.module.css
    DocumentOutline.tsx
    CommentsPanel.tsx
    VersionDiffViewer.tsx
  editor/
    nodes/                     # семантические node types, если нужны
    plugins/                   # Lexical plugins
    serialization/             # JSON/schema_version
    pagination/                # измерения и расчёт breakpoints
    formatting/                # styling from templates
  api/
  hooks/
  types/
```

Данные и логика редактора не должны расползаться по `pages/`. `shared/ui` не зависит от Lexical.

Backend принимает schema v1: paragraph/heading/quote/list/listitem/text/linebreak,
и v2 с table/tablerow/tablecell и inline `norma-image {asset_id, alt_text, version: 1}`.
У картинки нет произвольного src; содержимое читается защищённым API assets.
При сохранении backend проверяет принадлежность UUID этому документу. Неизвестные
узлы/inline CSS отклоняются. Фикстуры `@lexical/headless`/`@lexical/table` 0.53.0
проверяют сериализацию, дополнительно проверен HTTP/JSONB round-trip.
Custom image node проверен сериализационной заглушкой, продуктовый frontend-узел
и TablePlugin ещё предстоит реализовать. Поддержка backend не означает готовность UI.
Для чтения выбранных параметров есть `GET /formatting-template-versions/{version_id}`.
Точный API, аренда и восстановление — [API-контракт](api-contract.md) и
[ADR-010](../decisions/ADR-010-document-storage-versions-leases.md).

## Источник данных и пагинация

`Document.content` — один Lexical EditorState JSON с `schema_version`; `Document.revision` — номер атомарного сохранения. `DocumentVersion.content` — неизменяемый snapshot. Не хранить page_1/page_2 как отдельные части истины и не вшивать логические page breaks из отображения в содержимое без явного пользовательского разрыва.

**Pagination engine** — отдельная ответственность frontend (измерение высот и расположения блоков по метрикам документа). Ему передаются семантические блоки, ширина печатной области, метрики шрифтов и доступная высота. Он возвращает layout/breakpoints, а не изменяет сохранённый текст. При изменениях пересчитывает затронутые страницы и последующие.

Lexical даёт дерево и редакторские операции, но не гарантирует Word-подобное форматирование/постраничность: https://lexical.dev/docs/intro/. Из-за сложности выбора курсора, выделения через границы листов и таблиц **нельзя** просто разбить документ на независимые редактируемые экземпляры Lexical по страницам. На первой рабочей итерации — единый Lexical editor с визуальными границами страниц и измеряемым layout; для истинного переносимого DOM между листами требуется дальнейшая реализация с проверкой selection/IME/undo. Не объявлять ED-02/03 завершёнными по одному CSS-макету.

Приёмочные проверки пагинации: длинный абзац через границу; вставка в начале документа; удаление в середине; таблица и изображение у конца листа; смена шаблона; выделение и undo/redo при переразбиении. Автоматический AI/ML rewrite текста исключён.

## Семантика и шаблоны

При создании/импорте используются семантические узлы: body paragraph, heading(level), bullet/numbered list, table, image, caption и т. д. Внешний вид — CSS Modules + параметры выбранного сохранённого шаблона через ограниченный набор CSS variables, полученных из валидированных значений. Проверка оформления сравнивает **семантические свойства** и настроенные правила; генерация DOCX/PDF использует тот же snapshot шаблона. Историю шаблонов сохранять.

## DOCX → Lexical

Реализован `backend/app/api_v1/documents/docx_import.py`: прямой разбор OOXML
(`zipfile` + `defusedxml`) в семантические узлы Lexical v2 без промежуточного HTML.
Pillow перекодирует PNG/JPEG, отдельные assets доступны по защищённому UUID.
`import_service.py` атомарно сохраняет исходник, assets, защитную и импортированную
версии; после разбора повторно проверяет lease/revision под row lock. Выбранный
template_version_id сохраняется. `confirm_replace=true` обязателен; frontend должен
показать пользователю подтверждение до отправки файла. Warnings возвращаются
и сохраняются с импортом, UI должен показать их. Подробности/границы — ADR-011.
python-docx используется только для генерации синтетической проверочной фикстуры.

Исходник хранится отдельно в PostgreSQL BYTEA и не заменяется. ZIP/XML проверяются
с ограничениями размера/количества/глубины, внешние ссылки не загружаются.
Формулы/сложные объекты отражаются предупреждениями; исходные элементы остаются
в оригинале. HTML не создаётся. Его санитизация обязательна, если HTML-конвертация
будет добавлена в будущем.

## Вывод DOCX/PDF

Реализовано в backend: `DocumentVersion + FormattingTemplateVersion → python-docx → DOCX → LibreOffice → PDF`.
Параметры снимка шаблона определяют стили и геометрию; ручные overrides
показываются в отчёте и могут быть сброшены отдельным действием с сохранением
защитной/итоговой версии. Schema v3 добавляет семантические подписи рисунка/таблицы.
Подробности — [ADR-012](../decisions/ADR-012-formatting-and-export.md).
Проверять нумерацию, поля, размеры, изображения, переносы таблиц и подписи на
сформированном файле. **Браузерная pagination — предварительный вид**; frontend
пока отсутствует. Идентичность пагинации Word/браузера/PDF не гарантируется.

## Комментарии, diff, права и сохранение

- User edit lease и `expected_revision` проверяются в backend; при `409` текущий локальный текст не выбрасывать.
- Реализован backend замечаний: immutable `version_id`, body/quote/anchor
  `{block_id, offset_start, offset_end}`, статус `open/resolved` с ревизией/историей.
  `block_id` — путь children исходной версии, offsets — UTF-16 units; frontend
  должен переводить selection Lexical в этот формат. Глобальные UUID узлов не
  добавлялись. При потере/неоднозначности цитаты `current_anchor=null`,
  `is_detached=true`; источник сохраняется. Закрытые и detached скрыты по умолчанию.
- Реализован API diff двух immutable версий одного документа: структура и текст,
  equal/added/removed/changed, полные before/after; переносы показаны удалением и
  добавлением. UI подсветки ещё нет. Лимиты вычисления — ADR-013/API-контракт.
- Этап ссылается на `submitted_version_id`; решение руководителя называет эту
  версию и ожидаемую ревизию ВКР. Каждый submit создаёт новый снимок. Для главы
  редактору предстоит сохранять NodeState `normaStageId` в верхнеуровневом `h1`
  (schema v4). Сервер блокирует изменения всех глав на проверке. Отправка этапа
  без привязки блокирует запись всего документа. Область видна в истории
  отправок (`scope`) и определяется по заголовкам именно контрольного снимка.
  Подробности — [ADR-015](../decisions/ADR-015-stage-chapters.md).

Детали реализации — [ADR-013](../decisions/ADR-013-stage-review-comments-diff.md).
Поддержка backend не означает готовности CommentsPanel/VersionDiffViewer и E2E.

## Проверки

Unit: сериализация Lexical и схема; нормализация шаблона; вычисление страниц на фиктивных метриках; diff; комменты/anchors. Integration: импорт DOCX с заголовками/таблицами/картинкой; экспорт в DOCX/PDF; сохранение revision + конфликт. Browser E2E: набор в A4, перенос и возврат, импорт, отправка этапа, замечания, сравнение версий. Визуальные регрессии для page boundaries.
