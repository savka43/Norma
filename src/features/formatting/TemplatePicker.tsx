import { useState } from 'react'
import { useApi } from '../../shared/api/queries'
import type { Page, Template, TemplateVersion } from '../../shared/api/types'
import { ErrorNotice, Notice, Pager } from '../../shared/ui/Ui'
import w from '../../shared/ui/Workspace.module.css'
import styles from './Formatting.module.css'

const limit = 25

export function useTemplatePicker(useLatest = false) {
  const [offset, setOffset] = useState(0)
  const [templateId, setTemplateId] = useState('')
  const [versionOffset, setVersionOffset] = useState(0)
  const [versionId, setVersionId] = useState('')
  const templates = useApi<Page<Template>>(
    `/formatting-templates?limit=${limit}&offset=${offset}`,
  )
  const versions = useApi<Page<TemplateVersion>>(
    `/formatting-templates/${templateId}/versions?limit=${limit}&offset=${versionOffset}`,
    !!templateId,
  )
  const version =
    versions.data?.items.find(({ id }) => id === versionId) ??
    (useLatest && versionOffset === 0 ? versions.data?.items[0] : undefined)

  function selectTemplate(id: string) {
    setTemplateId(id)
    setVersionOffset(0)
    setVersionId('')
  }

  return {
    useLatest,
    templates,
    versions,
    templateId,
    version,
    offset,
    versionOffset,
    selectTemplate,
    selectVersion: setVersionId,
    changePage(next: number) {
      setOffset(next)
      selectTemplate('')
    },
    changeVersionPage(next: number) {
      setVersionOffset(next)
      setVersionId('')
    },
  }
}

export function TemplateSummary({ version }: { version: TemplateVersion }) {
  const { parameters } = version
  const { body, margins, orientation } = parameters
  const format = (value: number) => value.toLocaleString('ru-RU')
  return (
    <div className={styles.summary}>
      <strong>Версия шаблона №{version.number}</strong>
      <div>
        A4, {orientation === 'landscape' ? 'альбомная' : 'книжная'} ориентация
      </div>
      <div>
        {body.font_family}, {format(body.font_size_pt)} пт, интервал{' '}
        {format(body.line_spacing)}
      </div>
      <div>
        Поля слева и справа {format(margins.left_mm)} /{' '}
        {format(margins.right_mm)} мм, сверху и снизу {format(margins.top_mm)} /{' '}
        {format(margins.bottom_mm)} мм
      </div>
    </div>
  )
}

export function TemplatePicker({
  picker,
}: {
  picker: ReturnType<typeof useTemplatePicker>
}) {
  const {
    templates,
    versions,
    templateId,
    version,
    offset,
    versionOffset,
    useLatest,
  } = picker
  return (
    <div className={w.stack}>
      <ErrorNotice error={templates.error ?? versions.error} />
      {templates.isPending && <Notice>Загружаем шаблоны…</Notice>}
      {templates.data && (
        <>
          {templates.data.items.length ? (
            <label className={w.label}>
              Шаблон оформления
              <select
                value={templateId}
                onChange={(event) => picker.selectTemplate(event.target.value)}
              >
                <option value="">Выберите шаблон</option>
                {templates.data.items.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <p>
              {offset
                ? 'На этой странице нет шаблонов.'
                : 'Попросите руководителя добавить шаблон оформления.'}
            </p>
          )}
          <Pager
            limit={limit}
            offset={offset}
            size={templates.data.items.length}
            onChange={picker.changePage}
          />
        </>
      )}
      {templateId && versions.isPending && (
        <Notice>Загружаем версии шаблона…</Notice>
      )}
      {templateId && versions.data && (
        <>
          <label className={w.label}>
            Версия шаблона
            <select
              value={version?.id ?? ''}
              onChange={(event) => picker.selectVersion(event.target.value)}
            >
              {(!useLatest || versionOffset > 0) && (
                <option value="">Выберите версию</option>
              )}
              {versions.data.items.map((item) => (
                <option key={item.id} value={item.id}>
                  Версия №{item.number}
                </option>
              ))}
            </select>
          </label>
          <Pager
            limit={limit}
            offset={versionOffset}
            size={versions.data.items.length}
            onChange={picker.changeVersionPage}
          />
        </>
      )}
    </div>
  )
}
