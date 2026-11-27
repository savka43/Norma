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
import { DocumentFormatting } from '../formatting/DocumentFormatting'
import { TemplatePicker, useTemplatePicker } from '../formatting/TemplatePicker'
import { DOCX, versionListPath, versionPageSize, withLease } from './documents'
import { ImportHistory } from './ImportHistory'
import styles from './ThesisPage.module.css'

function CreateDocument({ thesisId }: { thesisId: string }) {
  const client = useQueryClient()
  const picker = useTemplatePicker(true)
  const version = picker.version
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
      <ErrorNotice error={create.error} />
      <TemplatePicker picker={picker} />
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
      return invalidatePaths(
        client,
        `/documents/${document.id}/versions`,
        `/documents/${document.id}/imports`,
      )
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
      className={`${w.form} ${styles.upload}`}
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

export function VersionList({ document }: { document: Document }) {
  const [offset, setOffset] = useState(0)
  const versions = useApi<Page<VersionSummary>>(
    versionListPath(document.id, offset),
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
                <Link
                  to={`/works/${document.thesis_id}/versions/${version.id}`}
                >
                  Версия №{version.number}
                </Link>
                <small>{date(version.created_at)}</small>
              </li>
            ))}
          </ul>
          <Pager
            offset={offset}
            limit={versionPageSize}
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
  if (!canEdit)
    return (
      <div className={w.stack}>
        <VersionList document={document} />
        <ImportHistory documentId={document.id} thesisId={document.thesis_id} />
      </div>
    )

  return (
    <div className={w.stack}>
      <Panel title="Рабочий документ">
        {locked ? (
          <p>
            Документ на проверке. Загрузка доступна после решения по всем
            отправленным этапам.
          </p>
        ) : (
          <UploadDocx document={document} />
        )}
      </Panel>
      <DocumentFormatting document={document} />
    </div>
  )
}
