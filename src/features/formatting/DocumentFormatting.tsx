import { useForm } from '@tanstack/react-form'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { send } from '../../shared/api/client'
import { invalidatePaths, useApi } from '../../shared/api/queries'
import type {
  Document,
  FormattingApplied,
  Page,
  TemplateVersion,
  VersionSummary,
} from '../../shared/api/types'
import { Button, ErrorNotice, Notice, Panel } from '../../shared/ui/Ui'
import w from '../../shared/ui/Workspace.module.css'
import { versionListPath, withLease } from '../theses/documents'
import { FormatReport } from './FormatReport'
import styles from './Formatting.module.css'
import {
  TemplatePicker,
  TemplateSummary,
  useTemplatePicker,
} from './TemplatePicker'

function ConfirmFormatting({
  document,
  version,
}: {
  document: Document
  version: TemplateVersion
}) {
  const client = useQueryClient()
  const apply = useMutation({
    mutationFn: () =>
      withLease(document.id, (headers) =>
        send<FormattingApplied>(`/documents/${document.id}/apply-formatting`, {
          method: 'POST',
          headers,
          json: {
            expected_revision: document.revision,
            template_version_id: version.id,
            confirm_apply: true,
          },
        }),
      ),
    onSuccess: ({ document: saved }) => {
      client.setQueryData([`/theses/${saved.thesis_id}/document`], saved)
      return invalidatePaths(client, `/documents/${saved.id}/versions`)
    },
    onError: () =>
      invalidatePaths(client, `/theses/${document.thesis_id}/document`),
  })
  const form = useForm({
    defaultValues: { confirmed: false },
    onSubmit: async ({ value }) => {
      if (!value.confirmed) return
      try {
        await apply.mutateAsync()
      } catch {
        // Keep the selection available for a retry.
      } finally {
        form.reset()
      }
    },
  })
  return (
    <form
      className={w.form}
      onSubmit={(event) => {
        event.preventDefault()
        void form.handleSubmit()
      }}
    >
      {version.id !== document.template_version_id && (
        <TemplateSummary version={version} />
      )}
      <form.Field name="confirmed">
        {(field) => (
          <label className={styles.check}>
            <input
              type="checkbox"
              required
              checked={field.state.value}
              onChange={(event) => field.handleChange(event.target.checked)}
            />
            Применить выбранный шаблон к рабочему документу и исправить ручное
            оформление. Предыдущая версия сохранится.
          </label>
        )}
      </form.Field>
      <ErrorNotice error={apply.error} />
      {apply.data && (
        <Notice>
          Оформление применено. Исправлено отклонений:{' '}
          {apply.data.corrected_issues}.{' '}
          <Link
            to={`/works/${document.thesis_id}/versions/${apply.data.version.id}`}
          >
            Открыть версию №{apply.data.version.number}
          </Link>
          {' · '}
          <Link to={`/works/${document.thesis_id}/edit`}>
            Посмотреть в редакторе
          </Link>
        </Notice>
      )}
      <form.Subscribe selector={(state) => state.values.confirmed}>
        {(confirmed) => (
          <Button type="submit" disabled={!confirmed || apply.isPending}>
            Применить оформление
          </Button>
        )}
      </form.Subscribe>
    </form>
  )
}

export function DocumentFormatting({ document }: { document: Document }) {
  const versions = useApi<Page<VersionSummary>>(versionListPath(document.id))
  const latest = versions.data?.items[0]
  const picker = useTemplatePicker()
  const active = useApi<TemplateVersion>(
    `/formatting-template-versions/${document.template_version_id}`,
  )
  return (
    <Panel title="Оформление">
      <div className={w.stack}>
        <ErrorNotice error={active.error} />
        {active.isPending && <Notice>Загружаем действующий шаблон…</Notice>}
        {active.data && (
          <div>
            <strong>Действующее оформление</strong>
            <TemplateSummary version={active.data} />
          </div>
        )}
        <details className={styles.section}>
          <summary>Проверка сохранённой версии</summary>
          <ErrorNotice error={versions.error} />
          {versions.isPending && <Notice>Загружаем версии…</Notice>}
          {versions.isSuccess && !latest && (
            <p>Чтобы проверить оформление, сохраните версию в редакторе.</p>
          )}
          {latest && <FormatReport key={latest.id} version={latest} />}
        </details>
        <details className={styles.section}>
          <summary>Выбрать шаблон</summary>
          <div className={w.stack}>
            <TemplatePicker picker={picker} />
            {picker.version && (
              <ConfirmFormatting
                key={picker.version.id}
                document={document}
                version={picker.version}
              />
            )}
          </div>
        </details>
      </div>
    </Panel>
  )
}
