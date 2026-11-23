import { useForm } from '@tanstack/react-form'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { send } from '../../shared/api/client'
import { invalidatePaths, useApi } from '../../shared/api/queries'
import type {
  Document,
  ImportResult,
  Page,
  Template,
  TemplateVersion,
  VersionSummary,
} from '../../shared/api/types'
import {
  Button,
  date,
  ErrorNotice,
  Notice,
  Pager,
  Panel,
} from '../../shared/ui/Ui'
import w from '../../shared/ui/Workspace.module.css'
import { DOCX, withLease } from './documents'

function CreateDocument({ thesisId }: { thesisId: string }) {
  const client = useQueryClient()
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState('')
  const limit = 25
  const templates = useApi<Page<Template>>(
    `/formatting-templates?limit=${limit}&offset=${offset}`,
  )
  const versions = useApi<Page<TemplateVersion>>(
    `/formatting-templates/${selected}/versions?limit=1`,
    !!selected,
  )
  const version = versions.data?.items[0]
  const create = useMutation({
    mutationFn: (template_version_id: string) =>
      send<Document>(`/theses/${thesisId}/document`, {
        method: 'POST',
        json: { template_version_id },
      }),
    onSuccess: (document) =>
      client.setQueryData([`/theses/${thesisId}/document`], document),
  })
  return (
    <div className={w.stack}>
      <ErrorNotice error={templates.error ?? versions.error ?? create.error} />
      {templates.isPending && <Notice>Загружаем шаблоны…</Notice>}
      {templates.data && (
        <>
          {templates.data.items.length ? (
            <label className={w.label}>
              Шаблон оформления
              <select
                value={selected}
                onChange={(event) => setSelected(event.target.value)}
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
            onChange={(next) => {
              setOffset(next)
              setSelected('')
            }}
          />
        </>
      )}
      <div>
        <Button
          disabled={!version || create.isPending}
          onClick={() => {
            if (version) create.mutate(version.id)
          }}
        >
          Создать документ
        </Button>
      </div>
    </div>
  )
}

function UploadDocx({ document }: { document: Document }) {
  const client = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const mutation = useMutation({
    mutationFn: (file: File) =>
      withLease(document.id, (headers) =>
        send<ImportResult>(
          `/documents/${document.id}/import?expected_revision=${document.revision}&confirm_replace=true`,
          {
            method: 'POST',
            body: file,
            headers: { ...headers, 'Content-Type': DOCX },
          },
        ),
      ),
    onSuccess: ({ document: saved }) => {
      client.setQueryData([`/theses/${document.thesis_id}/document`], saved)
      return invalidatePaths(client, `/documents/${document.id}/versions`)
    },
  })
  const form = useForm({
    defaultValues: { file: null as File | null, confirmed: false },
    onSubmit: async ({ value, formApi }) => {
      if (!value.file || !value.confirmed) return
      try {
        await mutation.mutateAsync(value.file)
        formApi.reset()
        if (input.current) input.current.value = ''
      } catch {
        // Keep the selected file available for a retry.
      }
    },
  })
  return (
    <form
      className={w.form}
      onReset={() => form.reset()}
      onSubmit={(event) => {
        event.preventDefault()
        void form.handleSubmit()
      }}
    >
      <form.Field name="file">
        {(field) => (
          <label className={w.label}>
            Файл DOCX
            <input
              ref={input}
              type="file"
              accept={`.docx,${DOCX}`}
              required
              onChange={(event) =>
                field.handleChange(event.target.files?.[0] ?? null)
              }
            />
          </label>
        )}
      </form.Field>
      <form.Field name="confirmed">
        {(field) => (
          <label>
            <input
              type="checkbox"
              required
              checked={field.state.value}
              onChange={(event) => field.handleChange(event.target.checked)}
            />{' '}
            Заменить рабочий документ. Предыдущая версия сохранится.
          </label>
        )}
      </form.Field>
      <ErrorNotice error={mutation.error} />
      {mutation.data && (
        <Notice>
          Загружена версия №{mutation.data.version.number}.
          {Object.keys(mutation.data.import_record.warnings).length > 0 &&
            ' При импорте были предупреждения.'}
        </Notice>
      )}
      <Button type="submit" disabled={mutation.isPending}>
        Загрузить DOCX
      </Button>
    </form>
  )
}

function VersionList({
  documentId,
  thesisId,
}: {
  documentId: string
  thesisId: string
}) {
  const [offset, setOffset] = useState(0)
  const limit = 15
  const versions = useApi<Page<VersionSummary>>(
    `/documents/${documentId}/versions?limit=${limit}&offset=${offset}`,
  )
  return (
    <Panel title="Версии документа">
      <ErrorNotice error={versions.error} />
      {versions.isPending && <Notice>Загружаем версии…</Notice>}
      {versions.data && (
        <>
          {!versions.data.items.length && (
            <p>
              {offset
                ? 'На этой странице нет версий.'
                : 'Версии появятся после сохранения из редактора, загрузки DOCX или отправки этапа.'}
            </p>
          )}
          <ul className={w.list}>
            {versions.data.items.map((version) => (
              <li key={version.id} className={w.row}>
                <Link to={`/works/${thesisId}/versions/${version.id}`}>
                  Версия №{version.number}
                </Link>
                <small>{date(version.created_at)}</small>
              </li>
            ))}
          </ul>
          <Pager
            offset={offset}
            limit={limit}
            size={versions.data.items.length}
            onChange={setOffset}
          />
        </>
      )}
    </Panel>
  )
}

export function DocumentPanel({
  thesisId,
  document,
  canEdit,
  locked,
}: {
  thesisId: string
  document: Document | null
  canEdit: boolean
  locked: boolean
}) {
  if (!document)
    return (
      <Panel title="Документ ВКР">
        {canEdit ? (
          <CreateDocument thesisId={thesisId} />
        ) : (
          <p>Студент ещё не создал документ.</p>
        )}
      </Panel>
    )
  return (
    <div className={w.stack}>
      {canEdit && (
        <Panel
          title="Рабочий документ"
          action={<Link to={`/works/${thesisId}/edit`}>Открыть редактор</Link>}
        >
          {locked ? (
            <p>
              Документ на проверке. Загрузка доступна после решения по всем
              отправленным этапам.
            </p>
          ) : (
            <UploadDocx document={document} />
          )}
        </Panel>
      )}
      <VersionList documentId={document.id} thesisId={thesisId} />
    </div>
  )
}
