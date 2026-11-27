import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../../shared/api/queries'
import type { ImportSummary, Page } from '../../shared/api/types'
import { date, ErrorNotice, Notice, Pager, Panel } from '../../shared/ui/Ui'
import w from '../../shared/ui/Workspace.module.css'
import styles from './ImportHistory.module.css'

const warningLabels: Record<string, string> = {
  formatting_normalized_to_template: 'Исходное оформление приведено к шаблону',
  image_layout_normalized: 'Упрощено размещение рисунка',
  unsupported_image: 'Формат изображения не поддерживается',
  drawing_not_imported: 'Рисунок не импортирован',
  external_relationship_ignored: 'Ссылка на внешний ресурс пропущена',
  nested_table_flattened: 'Вложенная таблица упрощена',
  vertical_merge_normalized: 'Вертикальное объединение ячеек упрощено',
  irregular_table_normalized: 'Нерегулярная структура таблицы упрощена',
  unknown_style: 'Стиль Word заменён подходящим стилем редактора',
  unknown_numbering: 'Нумерация Word не распознана',
  numbering_format_normalized: 'Формат нумерации приведён к стандартному',
  list_depth_normalized: 'Уровень вложенности списка уменьшен',
  heading_level_normalized: 'Уровень заголовка приведён к поддерживаемому',
  page_break_normalized: 'Разрыв страницы обработан при компоновке',
  section_break_normalized: 'Параметры раздела Word не перенесены',
  unsupported_inline: 'Встроенный элемент Word не поддерживается',
  unsupported_block: 'Блок Word не поддерживается',
  unsupported_part_header: 'Верхние колонтитулы остались в оригинале',
  unsupported_part_footer: 'Нижние колонтитулы остались в оригинале',
  unsupported_part_footnotes: 'Сноски остались в оригинале',
  unsupported_part_endnotes: 'Концевые сноски остались в оригинале',
  unsupported_part_comments: 'Комментарии Word остались в оригинале',
  unsupported_part_embeddings: 'Вложенные объекты остались в оригинале',
  unsupported_hyperlink: 'Сохранён только текст гиперссылки',
  unsupported_fldSimple: 'Поле Word перенесено как доступный текст',
  unsupported_fldChar: 'Управляющий символ поля Word пропущен',
  unsupported_instrText: 'Инструкция поля Word пропущена',
  unsupported_footnoteReference: 'Ссылка на сноску пропущена',
  unsupported_endnoteReference: 'Ссылка на концевую сноску пропущена',
  unsupported_oMath: 'Формула перенесена без математической вёрстки',
  unsupported_oMathPara: 'Блок формулы перенесён без математической вёрстки',
  unsupported_pict: 'Изображение в устаревшем формате Word пропущено',
  unsupported_object: 'Объект Word пропущен',
  unsupported_ins:
    'Вставка с отслеживанием изменений перенесена обычным текстом',
  unsupported_del:
    'Удаление с отслеживанием изменений перенесено обычным текстом',
  unsupported_sdt: 'Перенесён доступный текст элемента управления',
  unsupported_commentRangeStart: 'Начало диапазона комментария Word пропущено',
  unsupported_commentRangeEnd: 'Конец диапазона комментария Word пропущен',
  unsupported_commentReference: 'Ссылка на комментарий Word пропущена',
}

export function ImportHistory({
  documentId,
  thesisId,
}: {
  documentId: string
  thesisId: string
}) {
  const [offset, setOffset] = useState(0)
  const limit = 10
  const path = `/documents/${documentId}/imports`
  const imports = useApi<Page<ImportSummary>>(
    `${path}?limit=${limit}&offset=${offset}`,
  )
  return (
    <Panel title="История импорта DOCX">
      <ErrorNotice error={imports.error} />
      {imports.isPending && <Notice>Загружаем историю импорта…</Notice>}
      {imports.data && (
        <>
          {!imports.data.items.length && (
            <p>
              {offset
                ? 'На этой странице нет загрузок.'
                : 'DOCX ещё не загружали.'}
            </p>
          )}
          <ul className={w.list}>
            {imports.data.items.map((entry) => {
              const warnings = Object.entries(entry.warnings)
              return (
                <li key={entry.id}>
                  <div className={w.row}>
                    <strong>{date(entry.created_at)}</strong>
                    <Link
                      to={`/works/${thesisId}/versions/${entry.version_id}`}
                    >
                      Открыть версию
                    </Link>
                  </div>
                  <div className={styles.download}>
                    <a href={`/api/v1${path}/${entry.id}/source`}>
                      Скачать исходный DOCX
                    </a>
                    <small className={w.muted}>
                      {new Intl.NumberFormat('ru-RU', {
                        maximumFractionDigits: 1,
                      }).format(entry.source_size / 1024)}{' '}
                      КБ
                    </small>
                  </div>
                  {warnings.length ? (
                    <details>
                      <summary className={w.toggle}>
                        Предупреждения (
                        {warnings.reduce(
                          (total, [, count]) => total + count,
                          0,
                        )}
                        )
                      </summary>
                      <ul className={styles.warnings}>
                        {warnings.map(([code, count]) => (
                          <li key={code}>
                            {warningLabels[code] ??
                              `Элемент Word требует внимания (${code})`}{' '}
                            × {count}
                          </li>
                        ))}
                      </ul>
                    </details>
                  ) : (
                    <small className={w.muted}>Без предупреждений</small>
                  )}
                </li>
              )
            })}
          </ul>
          <Pager
            limit={limit}
            offset={offset}
            size={imports.data.items.length}
            onChange={setOffset}
          />
        </>
      )}
    </Panel>
  )
}
