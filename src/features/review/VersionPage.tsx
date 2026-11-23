import { useForm } from '@tanstack/react-form'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { download, send } from '../../shared/api/client'
import { invalidatePaths, useApi } from '../../shared/api/queries'
import type {
  Document,
  Stage,
  StagePlan,
  Thesis,
  User,
  Version,
} from '../../shared/api/types'
import { Button, date, ErrorNotice, Notice, Panel } from '../../shared/ui/Ui'
import w from '../../shared/ui/Workspace.module.css'
import { useDocument } from '../theses/ThesisPage'
import { withLease } from '../theses/documents'
import { Comments } from './Comments'
import { Plagiarism } from './Plagiarism'
import styles from './Review.module.css'
import { textBlocks } from './snapshot'

function Decision({
  stage,
  revision,
  versionId,
}: {
  stage: Stage
  revision: number
  versionId: string
}) {
  const client = useQueryClient()
  const navigate = useNavigate()
  const mutation = useMutation({
    mutationFn: ({
      action,
      comment,
    }: {
      action: 'confirm' | 'request-changes'
      comment: string
    }) =>
      send(`/stages/${stage.id}/${action}`, {
        method: 'POST',
        json: {
          expected_revision: revision,
          submitted_version_id: versionId,
          comment: comment.trim() || null,
        },
      }),
    onSuccess: async () => {
      await invalidatePaths(client, '/stages', '/theses', '/supervisor-groups')
      void navigate(`/works/${stage.thesis_id}`)
    },
    onError: () => invalidatePaths(client, `/theses/${stage.thesis_id}/stages`),
  })
  const form = useForm({ defaultValues: { comment: '' } })
  return (
    <Panel title={`Решение по этапу «${stage.name}»`}>
      <div className={w.form}>
        <form.Field name="comment">
          {(field) => (
            <label className={w.label}>
              Пояснение к решению
              <textarea
                rows={3}
                maxLength={2000}
                value={field.state.value}
                onChange={(event) => field.handleChange(event.target.value)}
              />
            </label>
          )}
        </form.Field>
        <ErrorNotice error={mutation.error} />
        <div className={w.actions}>
          <Button
            disabled={mutation.isPending}
            onClick={() =>
              mutation.mutate({
                action: 'confirm',
                comment: form.getFieldValue('comment'),
              })
            }
          >
            Подтвердить этап
          </Button>
          <Button
            variant="secondary"
            disabled={mutation.isPending}
            onClick={() =>
              mutation.mutate({
                action: 'request-changes',
                comment: form.getFieldValue('comment'),
              })
            }
          >
            Вернуть на доработку
          </Button>
        </div>
      </div>
    </Panel>
  )
}

function Snapshot({
  version,
  stage,
  plan,
  student,
  document: workingDocument,
}: {
  version: Version
  stage?: Stage
  plan?: StagePlan
  student: boolean
  document: Document
}) {
  const client = useQueryClient()
  const navigate = useNavigate()
  const blocks = useMemo(() => textBlocks(version.content), [version.content])
  const [selected, setSelected] = useState<string | null>(null)
  const exported = useMutation({
    mutationFn: (format: 'pdf' | 'docx') =>
      download(
        `/document-versions/${version.id}/exports`,
        { format },
        `ВКР — версия ${version.number}.${format}`,
      ),
  })
  const restore = useMutation({
    mutationFn: () =>
      withLease(workingDocument.id, (headers) =>
        send<{ document: Document; version: Version }>(
          `/documents/${workingDocument.id}/restore`,
          {
            method: 'POST',
            headers,
            json: {
              version_id: version.id,
              expected_revision: workingDocument.revision,
            },
          },
        ),
      ),
    onSuccess: async ({ document: saved }) => {
      client.setQueryData([`/theses/${saved.thesis_id}/document`], saved)
      await invalidatePaths(client, `/documents/${saved.id}/versions`)
      void navigate(`/works/${saved.thesis_id}/edit`)
    },
  })
  return (
    <div className={w.columns}>
      <div className={w.stack}>
        <Panel
          title="Текст сохранённой версии"
          action={
            <div className={w.actions}>
              <Button
                variant="secondary"
                disabled={exported.isPending}
                onClick={() => exported.mutate('docx')}
              >
                Скачать DOCX
              </Button>
              <Button
                variant="secondary"
                disabled={exported.isPending}
                onClick={() => exported.mutate('pdf')}
              >
                Скачать PDF
              </Button>
            </div>
          }
        >
          <ErrorNotice error={exported.error} />
          {student && (
            <details>
              <summary>Восстановить версию</summary>
              <p>
                Рабочий текст будет заменён. В истории появится новая версия.
              </p>
              <ErrorNotice error={restore.error} />
              <Button
                variant="secondary"
                disabled={restore.isPending}
                onClick={() => restore.mutate()}
              >
                Подтвердить восстановление
              </Button>
            </details>
          )}
          {!blocks.length && <p>В версии нет текста.</p>}
          <div className={styles.snapshot}>
            {blocks.map((block) => (
              <p
                key={block.id}
                id={`block-${block.id}`}
                tabIndex={-1}
                className={`${styles[block.type === 'norma-caption' ? 'caption' : block.type] ?? ''} ${selected === block.id ? styles.anchor : ''}`}
              >
                {block.text.split('\ufffc').join('[Изображение]')}
              </p>
            ))}
          </div>
        </Panel>
        {!student && stage?.status === 'in_review' && plan && (
          <Decision
            stage={stage}
            revision={plan.revision}
            versionId={version.id}
          />
        )}
      </div>
      <div className={w.stack}>
        <Comments
          version={version}
          supervisor={!student}
          blocks={blocks}
          onJump={(id) => {
            setSelected(id)
            const target = document.getElementById(`block-${id}`)
            target?.focus()
            target?.scrollIntoView({ block: 'nearest' })
          }}
        />
        <Plagiarism versionId={version.id} student={student} />
      </div>
    </div>
  )
}

export function VersionPage({ role }: { role: User['role'] }) {
  const { thesisId = '', versionId = '' } = useParams()
  const [params] = useSearchParams()
  const thesis = useApi<Thesis>(`/theses/${thesisId}`)
  const document = useDocument(thesisId, !!thesis.data)
  const version = useApi<Version>(
    `/document-versions/${versionId}`,
    !!document.data,
  )
  const plan = useApi<StagePlan>(`/theses/${thesisId}/stages`, !!thesis.data)
  const snapshot =
    document.data && version.data?.document_id === document.data.id
      ? version.data
      : null
  const stage = plan.data?.items.find(
    (item) =>
      item.submitted_version_id === versionId &&
      (!params.has('stage') || params.get('stage') === item.id),
  )
  return (
    <div className={w.page}>
      <header className={w.heading}>
        <div>
          <Link to={`/works/${thesisId}`}>
            {thesis.data?.title ?? 'К работе'}
          </Link>
          <h1>
            {snapshot ? `Версия №${snapshot.number}` : 'Версия документа'}
          </h1>
          {snapshot && (
            <p className={w.subheading}>
              {date(snapshot.created_at)}
              {stage ? ` · ${stage.name}` : ''}
            </p>
          )}
        </div>
      </header>
      <ErrorNotice
        error={thesis.error ?? document.error ?? version.error ?? plan.error}
      />
      {(thesis.isPending ||
        (thesis.data && document.isPending) ||
        (document.data && version.isPending)) && (
        <Notice>Загружаем версию…</Notice>
      )}
      {(document.data === null || (version.data && !snapshot)) && (
        <Notice error>Версия этой работы не найдена.</Notice>
      )}
      {snapshot && document.data && (
        <Snapshot
          key={snapshot.id}
          version={snapshot}
          stage={stage}
          plan={plan.data}
          student={role === 'student'}
          document={document.data}
        />
      )}
    </div>
  )
}
