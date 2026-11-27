import type { TemplateParameters, TextStyle } from '../../shared/api/types'
import { Field } from '../../shared/ui/Ui'
import w from '../../shared/ui/Workspace.module.css'
import styles from './Formatting.module.css'

type NumericStyleKey =
  | 'font_size_pt'
  | 'line_spacing'
  | 'first_line_indent_mm'
  | 'space_before_pt'
  | 'space_after_pt'

const numericStyleFields: [NumericStyleKey, string, number, number][] = [
  ['font_size_pt', 'Размер шрифта, пт', 6, 72],
  ['line_spacing', 'Межстрочный интервал', 1, 3],
  ['first_line_indent_mm', 'Отступ первой строки, мм', 0, 100],
  ['space_before_pt', 'Интервал перед блоком, пт', 0, 100],
  ['space_after_pt', 'Интервал после блока, пт', 0, 100],
]

const marginFields: [keyof TemplateParameters['margins'], string][] = [
  ['top_mm', 'Верхнее поле, мм'],
  ['bottom_mm', 'Нижнее поле, мм'],
  ['left_mm', 'Левое поле, мм'],
  ['right_mm', 'Правое поле, мм'],
]

export const alignments: Record<TextStyle['alignment'], string> = {
  left: 'По левому краю',
  center: 'По центру',
  right: 'По правому краю',
  justify: 'По ширине',
}

function NumericField({
  label,
  value,
  onChange,
  min,
  max,
  step = 'any',
}: {
  label: string
  value: number
  onChange: (number: number) => void
  min: number
  max: number
  step?: 'any' | number
}) {
  return (
    <Field
      label={label}
      type="number"
      required
      value={Number.isNaN(value) ? '' : value}
      min={min}
      max={max}
      step={step}
      onChange={(event) => onChange(event.target.valueAsNumber)}
    />
  )
}

function StyleFields({
  title,
  value,
  onChange,
}: {
  title: string
  value: TextStyle
  onChange: (value: TextStyle) => void
}) {
  return (
    <details className={styles.section}>
      <summary>{title}</summary>
      <div className={styles.grid} role="group" aria-label={title}>
        <Field
          label="Семейство шрифта"
          required
          maxLength={100}
          pattern={'[\\p{L}\\p{N}_ \\-]{1,100}'}
          value={value.font_family}
          onChange={(event) =>
            onChange({ ...value, font_family: event.target.value })
          }
        />
        {numericStyleFields.map(([key, label, min, max]) => (
          <NumericField
            key={key}
            label={label}
            value={value[key]}
            min={min}
            max={max}
            onChange={(number) => onChange({ ...value, [key]: number })}
          />
        ))}
        <label className={w.label}>
          Выравнивание
          <select
            value={value.alignment}
            onChange={(event) =>
              onChange({
                ...value,
                alignment: event.target.value as TextStyle['alignment'],
              })
            }
          >
            {Object.entries(alignments).map(([alignment, label]) => (
              <option key={alignment} value={alignment}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <div>
          <label className={styles.check}>
            <input
              type="checkbox"
              checked={value.bold}
              onChange={(event) =>
                onChange({ ...value, bold: event.target.checked })
              }
            />
            Полужирный
          </label>
          <label className={styles.check}>
            <input
              type="checkbox"
              checked={value.italic}
              onChange={(event) =>
                onChange({ ...value, italic: event.target.checked })
              }
            />
            Курсив
          </label>
        </div>
      </div>
    </details>
  )
}

const extraStyles = [
  ['caption', 'Подписи к рисункам и таблицам'],
  ['list', 'Списки'],
  ['table', 'Таблицы'],
] as const

export function TemplateFields({
  parameters,
  onChange,
}: {
  parameters: TemplateParameters
  onChange: (value: TemplateParameters) => void
}) {
  return (
    <div className={w.stack}>
      <div className={styles.grid} role="group" aria-label="Лист A4">
        <label className={w.label}>
          Ориентация листа A4
          <select
            value={parameters.orientation}
            onChange={(event) =>
              onChange({
                ...parameters,
                orientation: event.target
                  .value as TemplateParameters['orientation'],
              })
            }
          >
            <option value="portrait">Книжная</option>
            <option value="landscape">Альбомная</option>
          </select>
        </label>
        <NumericField
          label="Номер первого листа"
          value={parameters.page_number_start}
          min={1}
          max={100_000}
          step={1}
          onChange={(value) =>
            onChange({ ...parameters, page_number_start: value })
          }
        />
        {marginFields.map(([key, label]) => (
          <NumericField
            key={key}
            label={label}
            value={parameters.margins[key]}
            min={0}
            max={100}
            onChange={(value) =>
              onChange({
                ...parameters,
                margins: { ...parameters.margins, [key]: value },
              })
            }
          />
        ))}
      </div>
      <div>
        <StyleFields
          title="Основной текст"
          value={parameters.body}
          onChange={(body) => onChange({ ...parameters, body })}
        />
        {parameters.headings.map((value, index) => (
          <StyleFields
            key={index}
            title={`Заголовок ${index + 1}`}
            value={value}
            onChange={(style) =>
              onChange({
                ...parameters,
                headings: parameters.headings.map((heading, position) =>
                  index === position ? style : heading,
                ),
              })
            }
          />
        ))}
        {extraStyles.map(([key, title]) => (
          <StyleFields
            key={key}
            title={title}
            value={parameters[key]}
            onChange={(value) => onChange({ ...parameters, [key]: value })}
          />
        ))}
      </div>
    </div>
  )
}
